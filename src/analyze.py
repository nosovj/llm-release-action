#!/usr/bin/env python3
"""Main analysis script for LLM semantic versioning."""

import json
import os
import sys
import time
from typing import Optional

import litellm

from parser import parse_response
from prompt_builder import build_prompt, get_commits
from version import SemanticVersion, detect_latest_tag, is_shallow_clone, parse_version


def get_env(name: str, default: Optional[str] = None) -> str:
    """Get environment variable or raise error if missing and no default."""
    value = os.environ.get(name, default)
    if value is None:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def get_env_bool(name: str, default: bool = False) -> bool:
    """Get environment variable as boolean."""
    value = os.environ.get(name, str(default)).lower()
    return value in ("true", "1", "yes")


def get_env_int(name: str, default: int) -> int:
    """Get environment variable as integer."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as e:
        raise ValueError(f"Invalid integer value for {name}: {value}") from e


def get_env_float(name: str, default: float) -> float:
    """Get environment variable as float."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as e:
        raise ValueError(f"Invalid float value for {name}: {value}") from e


def log_group(title: str) -> None:
    """Start a GitHub Actions log group."""
    print(f"::group::{title}")


def log_group_end() -> None:
    """End a GitHub Actions log group."""
    print("::endgroup::")


def log_error(message: str) -> None:
    """Log an error message in GitHub Actions format."""
    print(f"::error::{message}")


def set_output(name: str, value: str) -> None:
    """Set a GitHub Actions output."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            # Use heredoc syntax for multiline values
            if "\n" in value:
                delimiter = f"EOF_{int(time.time())}"
                f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
            else:
                f.write(f"{name}={value}\n")
    else:
        # Fallback for local testing
        print(f"OUTPUT {name}={value[:100]}{'...' if len(value) > 100 else ''}")


def call_llm_with_retry(
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    max_retries: int = 3,
    debug: bool = False,
) -> str:
    """Call LLM with exponential backoff retry.

    Args:
        model: LiteLLM model string
        prompt: The prompt to send
        temperature: LLM temperature
        max_tokens: Max response tokens
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts
        debug: Enable debug logging

    Returns:
        LLM response text

    Raises:
        RuntimeError: If all retries fail
    """
    if debug:
        log_group("Debug: Prompt")
        print(prompt)
        log_group_end()

    last_error = None
    for attempt in range(max_retries):
        try:
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )

            result = response.choices[0].message.content
            if not result:
                raise RuntimeError("LLM returned empty response")

            if debug:
                log_group("Debug: Response")
                print(result)
                log_group_end()

            return result

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # Don't retry auth errors
            if "401" in error_str or "403" in error_str or "authentication" in error_str:
                raise RuntimeError(f"Authentication failed: {e}") from e

            # Retry on rate limits and transient errors
            if attempt < max_retries - 1:
                if "429" in error_str or "rate" in error_str:
                    wait_time = 2 ** (attempt + 1)
                    print(f"Rate limited, waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                elif "500" in error_str or "502" in error_str or "503" in error_str:
                    wait_time = 2 ** (attempt + 1)
                    print(f"Server error, waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue

            raise RuntimeError(f"LLM call failed after {attempt + 1} attempts: {e}") from e

    raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_error}")


def sanitize_changelog(changelog: str, max_size: int = 65536) -> str:
    """Sanitize changelog output.

    Args:
        changelog: Raw changelog text
        max_size: Maximum size in bytes

    Returns:
        Sanitized changelog
    """
    import re

    # Strip HTML tags
    sanitized = re.sub(r"<[^>]+>", "", changelog)

    # Remove javascript: URLs
    sanitized = re.sub(r"javascript:[^\s\"']+", "", sanitized)

    # Truncate if too large
    if len(sanitized.encode("utf-8")) > max_size:
        # Truncate at character level (approximate)
        while len(sanitized.encode("utf-8")) > max_size - 20:
            sanitized = sanitized[:-100]
        sanitized = sanitized.rstrip() + "\n\n... (truncated)"

    return sanitized


def main() -> int:
    """Main entry point."""
    try:
        # Parse inputs
        model = get_env("INPUT_MODEL")
        current_version_input = os.environ.get("INPUT_CURRENT_VERSION", "")
        head_ref = get_env("INPUT_HEAD_REF", "HEAD")
        include_diffs = get_env("INPUT_INCLUDE_DIFFS", "**/openapi*.yaml,**/migrations/**,**/*.proto")
        max_commits = get_env_int("INPUT_MAX_COMMITS", 50)
        temperature = get_env_float("INPUT_TEMPERATURE", 0.2)
        max_tokens = get_env_int("INPUT_MAX_TOKENS", 2000)
        timeout = get_env_int("INPUT_TIMEOUT", 60)
        debug = get_env_bool("INPUT_DEBUG", False)
        dry_run = get_env_bool("INPUT_DRY_RUN", False)

        log_group("Validating git environment")

        # Check for shallow clone
        if is_shallow_clone():
            log_error("Shallow clone detected. Use fetch-depth: 0 in your checkout action.")
            return 1

        # Determine current version
        if current_version_input:
            current_version_str = current_version_input
            print(f"Using provided version: {current_version_str}")
        else:
            detected = detect_latest_tag()
            if not detected:
                log_error("No semver tags found. Please provide current_version input.")
                return 1
            current_version_str = detected
            print(f"Auto-detected version: {current_version_str}")

        # Parse version
        current_version = parse_version(current_version_str)
        log_group_end()

        log_group("Fetching commits")

        # Get commits
        commits = get_commits(current_version_str, head_ref)
        if not commits:
            log_error(f"No commits found between {current_version_str} and {head_ref}")
            return 1

        print(f"Found {len(commits)} commits")
        log_group_end()

        log_group("Building prompt")

        # Build prompt
        diff_patterns = [p.strip() for p in include_diffs.split(",") if p.strip()]
        prompt = build_prompt(
            commits=commits,
            base_version=str(current_version),
            max_commits=max_commits,
            diff_patterns=diff_patterns,
            base_ref=current_version_str,
            head_ref=head_ref,
        )

        print(f"Prompt built ({len(prompt)} chars)")
        log_group_end()

        log_group("Calling LLM")

        # Call LLM
        response = call_llm_with_retry(
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            debug=debug,
        )

        print("LLM response received")
        log_group_end()

        log_group("Parsing response")

        # Parse response
        result = parse_response(response)
        print(f"Bump: {result.bump}")
        print(f"Breaking changes: {len(result.breaking_changes)}")
        print(f"Features: {len(result.features)}")
        print(f"Fixes: {len(result.fixes)}")
        log_group_end()

        # Calculate next version
        next_version = current_version.bump(result.bump)

        log_group("Setting outputs")

        # Set outputs
        set_output("bump", result.bump)
        set_output("current_version", str(current_version))
        set_output("next_version", str(next_version))
        set_output("changelog", sanitize_changelog(result.changelog))
        set_output("breaking_changes", json.dumps(result.breaking_changes))
        set_output("reasoning", result.reasoning)

        print(f"Current version: {current_version}")
        print(f"Next version: {next_version}")
        if dry_run:
            print("(dry-run mode - no version will be created)")
        log_group_end()

        return 0

    except Exception as e:
        log_error(str(e))
        if debug:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
