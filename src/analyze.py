#!/usr/bin/env python3
"""Main analysis script for LLM semantic versioning with multi-audience changelogs.

This script implements a three-phase architecture:
1. Phase 1: Semantic Analysis - Analyze commits/content and suggest version bump
2. Phase 2: Changelog Generation - Generate audience-specific changelogs
3. Phase 3: Validation - Validate generated content quality
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import litellm


@dataclass
class LLMUsage:
    """Usage statistics for a single LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""


@dataclass
class AggregateUsage:
    """Aggregate usage statistics for all LLM calls."""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    models: Dict[str, Dict[str, float]] = field(default_factory=dict)  # model -> {tokens, latency, calls}

    def add(self, usage: LLMUsage) -> None:
        """Add a usage record."""
        self.total_calls += 1
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_tokens += usage.total_tokens
        self.total_latency_ms += usage.latency_ms

        # Track by model
        if usage.model not in self.models:
            self.models[usage.model] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0.0, "calls": 0}
        self.models[usage.model]["input_tokens"] += usage.input_tokens
        self.models[usage.model]["output_tokens"] += usage.output_tokens
        self.models[usage.model]["total_tokens"] += usage.total_tokens
        self.models[usage.model]["latency_ms"] += usage.latency_ms
        self.models[usage.model]["calls"] += 1

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            model: {
                "calls": int(stats["calls"]),
                "input_tokens": int(stats["input_tokens"]),
                "output_tokens": int(stats["output_tokens"]),
                "latency_ms": round(stats["latency_ms"], 0),
            }
            for model, stats in self.models.items()
        }


# Global usage tracker
_usage = AggregateUsage()

from analyzer import parse_phase1_response
from changelog import build_changelog_prompt, filter_changes, generate_changelog
from config import AudienceConfig, ChangelogConfig
from content_scanner import handle_scan_result, scan_content_override, truncate_for_context
from input_validation import validate_inputs
from model_config import ModelConfig
from models import AnalysisResult, Change, ChangeStats, ReleaseMetadata
from prompt_builder import (
    CommitInfo,
    build_prompt,
    build_semantic_analysis_prompt,
    get_commits,
    has_breaking_change,
    sanitize_message,
)
from repo_url import get_repository_url
from validation import ValidationConfig, generate_fallback_changelog, validate_changelog
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


def log_warning(message: str) -> None:
    """Log a warning message in GitHub Actions format."""
    print(f"::warning::{message}")


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
        preview = value[:100] + "..." if len(value) > 100 else value
        print(f"OUTPUT {name}={preview}")


def call_llm_with_retry(
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    max_retries: int = 3,
    debug: bool = False,
) -> Tuple[str, LLMUsage]:
    """Call LLM with exponential backoff retry.

    Returns:
        Tuple of (response content, usage statistics)
    """
    if debug:
        log_group("Debug: Prompt")
        print(prompt)
        log_group_end()

    last_error = None
    for attempt in range(max_retries):
        try:
            start_time = time.perf_counter()

            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            result = response.choices[0].message.content
            if not result:
                raise RuntimeError("LLM returned empty response")

            # Extract usage
            usage = LLMUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                latency_ms=latency_ms,
                model=model,
            )

            # Track globally
            _usage.add(usage)

            if debug:
                log_group("Debug: Response")
                print(result)
                print(f"[Usage] {usage.input_tokens} in / {usage.output_tokens} out = {usage.total_tokens} total | {latency_ms:.0f}ms")
                log_group_end()

            return result, usage

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
    """Sanitize changelog output."""
    import re

    # Strip HTML tags
    sanitized = re.sub(r"<[^>]+>", "", changelog)

    # Remove javascript: URLs
    sanitized = re.sub(r"javascript:[^\s\"']+", "", sanitized)

    # Truncate if too large
    if len(sanitized.encode("utf-8")) > max_size:
        while len(sanitized.encode("utf-8")) > max_size - 20:
            sanitized = sanitized[:-100]
        sanitized = sanitized.rstrip() + "\n\n... (truncated)"

    return sanitized


def parse_commits_json(json_str: str) -> List[CommitInfo]:
    """Parse commits from JSON format (for multi-repo mode).

    Args:
        json_str: JSON array of commit objects with hash and message fields

    Returns:
        List of CommitInfo objects

    Raises:
        ValueError: If JSON is invalid or missing required fields
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid commits_json: {e}") from e

    if not isinstance(data, list):
        raise ValueError("commits_json must be a JSON array")

    commits = []
    for item in data:
        if not isinstance(item, dict):
            continue

        if "hash" not in item or "message" not in item:
            raise ValueError(f"Commit {item} missing required fields (hash, message)")

        commit_hash = item["hash"]
        message = item["message"]

        # Add repo prefix if present
        if "repo" in item:
            commit_hash = f"[{item['repo']}] {commit_hash}"

        # Sanitize message
        message = sanitize_message(message)

        # Detect breaking changes
        has_breaking = has_breaking_change(message)

        commits.append(CommitInfo(
            hash=commit_hash,
            message=message,
            has_breaking_marker=has_breaking,
        ))

    return commits


def run_phase1(
    model: str,
    commits: List[CommitInfo],
    base_version: str,
    content_override: Optional[str],
    max_commits: int,
    include_diffs: str,
    head_ref: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    debug: bool,
) -> AnalysisResult:
    """Run Phase 1: Semantic Analysis.

    Args:
        model: LiteLLM model string
        commits: List of commits (ignored if content_override provided)
        base_version: Current version string
        content_override: Optional content to analyze instead of commits
        max_commits: Max commits to include
        include_diffs: Comma-separated file patterns for diffs
        head_ref: Head git ref
        temperature: LLM temperature
        max_tokens: Max response tokens
        timeout: Request timeout
        debug: Enable debug logging

    Returns:
        AnalysisResult with bump, reasoning, and changes
    """
    log_group("Phase 1: Semantic Analysis")

    # Build prompt
    if content_override:
        # Scan and potentially truncate content
        scan_result = scan_content_override(content_override)
        handle_scan_result(scan_result)

        if scan_result.truncated:
            content_override = truncate_for_context(content_override)

        prompt = build_semantic_analysis_prompt(
            commits=[],
            base_version=base_version,
            content_override=content_override,
        )
    else:
        diff_patterns = [p.strip() for p in include_diffs.split(",") if p.strip()]
        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version=base_version,
            max_commits=max_commits,
            diff_patterns=diff_patterns,
            base_ref=base_version,
            head_ref=head_ref,
        )

    print(f"Prompt built ({len(prompt)} chars)")

    # Call LLM
    response, usage = call_llm_with_retry(
        model=model,
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        debug=debug,
    )

    # Parse response
    result = parse_phase1_response(response)

    print(f"Bump: {result.bump}")
    print(f"Changes: {len(result.changes)}")
    if result.stats:
        print(f"Stats: {result.stats.features} features, {result.stats.fixes} fixes")
    print(f"Usage: {usage.input_tokens} in / {usage.output_tokens} out | {usage.latency_ms:.0f}ms")

    log_group_end()
    return result


def run_phase2(
    model: str,
    changes: List[Change],
    changelog_config: ChangelogConfig,
    version: str,
    base_url: Optional[str],
    temperature: float,
    max_tokens: int,
    timeout: int,
    debug: bool,
) -> tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, dict]]]:
    """Run Phase 2: Changelog Generation (parallel execution).

    Args:
        model: LiteLLM model string
        changes: List of changes from Phase 1
        changelog_config: Audience configurations
        version: Version string for the release
        base_url: Optional repository URL for links
        temperature: LLM temperature
        max_tokens: Max response tokens
        timeout: Request timeout
        debug: Enable debug logging

    Returns:
        Tuple of (changelogs dict, metadata dict)
    """
    log_group("Phase 2: Changelog Generation")

    changelogs: Dict[str, Dict[str, str]] = {}
    metadata: Dict[str, Dict[str, dict]] = {}

    if not changelog_config.audiences:
        # Create default audience when no config provided
        print("No changelog_config provided, using default audience")
        changelog_config = ChangelogConfig.from_yaml("""
default:
  preset: developer
  languages: [en]
""")


    # Build list of all tasks to run in parallel
    tasks: List[Tuple[str, str, AudienceConfig, List[Change], str, Optional[str]]] = []

    for audience_name, config in changelog_config.audiences.items():
        changelogs[audience_name] = {}
        metadata[audience_name] = {}

        # Filter changes for this audience
        filtered_changes = filter_changes(changes, config)
        print(f"Audience '{audience_name}': {len(filtered_changes)} changes, languages: {config.languages}")

        for language in config.languages:
            tasks.append((audience_name, language, config, filtered_changes, version, base_url))

    if not tasks:
        log_group_end()
        return changelogs, metadata

    def process_task(task: Tuple[str, str, AudienceConfig, List[Change], str, Optional[str]]) -> Tuple[str, str, str, dict]:
        """Process a single audience/language task."""
        audience_name, language, config, filtered_changes, ver, task_base_url = task

        # Build prompt for this audience/language
        prompt = build_changelog_prompt(
            changes=filtered_changes,
            config=config,
            version=ver,
            language=language,
            base_url=task_base_url,
        )

        # Call LLM
        response, usage = call_llm_with_retry(
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            debug=debug,
        )

        # Extract changelog and metadata from response
        changelog_content, release_metadata = parse_phase2_response(
            response, config, language
        )

        return audience_name, language, changelog_content, release_metadata.to_dict()

    # Run all tasks in parallel
    print(f"Generating {len(tasks)} changelogs in parallel...")
    phase2_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=min(len(tasks), 10)) as executor:
        futures = {executor.submit(process_task, task): task for task in tasks}

        for future in as_completed(futures):
            task = futures[future]
            task_name = f"{task[0]}.{task[1]}"  # audience.language
            try:
                audience_name, language, changelog_content, meta = future.result()
                changelogs[audience_name][language] = changelog_content
                metadata[audience_name][language] = meta
                print(f"  ✓ {audience_name}.{language} completed")
            except Exception as e:
                print(f"  ✗ {task_name} failed: {e}")
                raise RuntimeError(f"Phase 2 failed for {task_name}: {e}") from e

    phase2_latency = (time.perf_counter() - phase2_start) * 1000
    print(f"Phase 2 completed: {len(tasks)} changelogs in {phase2_latency:.0f}ms (parallel)")

    log_group_end()
    return changelogs, metadata


def parse_phase2_response(
    response: str,
    config: AudienceConfig,
    language: str,
) -> tuple[str, ReleaseMetadata]:
    """Parse Phase 2 LLM response.

    The response should be the changelog content, potentially with metadata.

    Args:
        response: Raw LLM response
        config: Audience configuration
        language: Target language

    Returns:
        Tuple of (changelog content, metadata)
    """
    # For now, treat the entire response as the changelog
    # In a more sophisticated implementation, we could parse
    # structured output with metadata
    changelog = response.strip()

    # Create metadata (would be extracted from structured response)
    metadata = ReleaseMetadata(
        title=None,
        summary=None,
        highlights=None,
    )

    return changelog, metadata


def run_phase3(
    changelogs: Dict[str, Dict[str, str]],
    changes: List[Change],
    changelog_config: ChangelogConfig,
    version: str,
) -> Dict[str, Dict[str, str]]:
    """Run Phase 3: Validation.

    Args:
        changelogs: Generated changelogs from Phase 2
        changes: Original changes from Phase 1
        changelog_config: Audience configurations
        version: Version string

    Returns:
        Validated (and possibly fixed) changelogs
    """
    log_group("Phase 3: Validation")

    validated: Dict[str, Dict[str, str]] = {}

    for audience_name, audience_changelogs in changelogs.items():
        validated[audience_name] = {}
        config = changelog_config.audiences.get(audience_name)

        if not config:
            validated[audience_name] = audience_changelogs
            continue

        validation_config = config.validation

        for language, changelog in audience_changelogs.items():
            result = validate_changelog(
                changelog=changelog,
                language=language,
                changes=changes,
                config=validation_config,
                output_format=config.output_format,
            )

            if result.valid:
                validated[audience_name][language] = changelog
                print(f"  {audience_name}.{language}: Valid")
            else:
                print(f"  {audience_name}.{language}: Invalid - {result.errors}")

                if validation_config.on_failure == "error":
                    raise ValueError(f"Validation failed: {result.errors}")
                elif validation_config.on_failure == "warn":
                    log_warning(f"Validation warnings for {audience_name}.{language}: {result.errors}")
                    validated[audience_name][language] = changelog
                elif validation_config.on_failure == "fallback":
                    print(f"  Using fallback changelog")
                    validated[audience_name][language] = generate_fallback_changelog(
                        version=version,
                        changes=changes,
                        language=language,
                    )
                else:  # retry - but for now just use as-is
                    validated[audience_name][language] = changelog

            if result.warnings:
                for warning in result.warnings:
                    log_warning(f"{audience_name}.{language}: {warning}")

    log_group_end()
    return validated


def main() -> int:
    """Main entry point."""
    debug = get_env_bool("INPUT_DEBUG", False)

    try:
        # Parse inputs
        model = get_env("INPUT_MODEL")
        model_analysis = os.environ.get("INPUT_MODEL_ANALYSIS", "")
        model_changelog = os.environ.get("INPUT_MODEL_CHANGELOG", "")
        current_version_input = os.environ.get("INPUT_CURRENT_VERSION", "")
        head_ref = get_env("INPUT_HEAD_REF", "HEAD")
        include_diffs = get_env("INPUT_INCLUDE_DIFFS", "**/openapi*.yaml,**/migrations/**,**/*.proto")
        max_commits = get_env_int("INPUT_MAX_COMMITS", 50)
        temperature = get_env_float("INPUT_TEMPERATURE", 0.2)
        max_tokens = get_env_int("INPUT_MAX_TOKENS", 4000)
        timeout = get_env_int("INPUT_TIMEOUT", 120)
        dry_run = get_env_bool("INPUT_DRY_RUN", False)
        content_override = os.environ.get("INPUT_CONTENT_OVERRIDE", "")
        changelog_config_str = os.environ.get("INPUT_CHANGELOG_CONFIG", "")

        # Configure per-phase models
        model_config = ModelConfig.from_env(
            model=model,
            model_analysis=model_analysis if model_analysis else None,
            model_changelog=model_changelog if model_changelog else None,
        )

        # Validate inputs
        log_group("Validating inputs")
        validation_result = validate_inputs(
            current_version=current_version_input if current_version_input else None,
            content_override=content_override if content_override else None,
            changelog_config=changelog_config_str if changelog_config_str else None,
            include_diffs=include_diffs,
        )

        if not validation_result.valid:
            for error in validation_result.errors:
                log_error(error)
            return 1

        print("Inputs validated successfully")
        log_group_end()

        # Parse changelog config
        changelog_config = ChangelogConfig.from_yaml(changelog_config_str)

        # Determine content source
        use_content_override = bool(content_override.strip())
        commits: List[CommitInfo] = []

        if use_content_override:
            log_group("Using content override")
            print(f"Content override provided ({len(content_override)} chars)")
            log_group_end()

            # For content override, current_version is required
            if not current_version_input:
                log_error("current_version is required when using content_override")
                return 1

            current_version_str = current_version_input
            current_version = parse_version(current_version_str)
        else:
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

            current_version = parse_version(current_version_str)
            log_group_end()

            log_group("Fetching commits")
            commits = get_commits(current_version_str, head_ref)
            if not commits:
                log_error(f"No commits found between {current_version_str} and {head_ref}")
                return 1
            print(f"Found {len(commits)} commits")
            log_group_end()

        # Get repository URL for links
        base_url = get_repository_url()

        # === PHASE 1: Semantic Analysis ===
        analysis_result = run_phase1(
            model=model_config.get_analysis_model(),
            commits=commits,
            base_version=str(current_version),
            content_override=content_override if use_content_override else None,
            max_commits=max_commits,
            include_diffs=include_diffs,
            head_ref=head_ref,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            debug=debug,
        )

        # Calculate next version
        next_version = current_version.bump(analysis_result.bump)

        # === PHASE 2: Changelog Generation ===
        changelogs, metadata = run_phase2(
            model=model_config.get_changelog_model(),
            changes=analysis_result.changes,
            changelog_config=changelog_config,
            version=str(next_version),
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            debug=debug,
        )

        # === PHASE 3: Validation ===
        if changelogs:
            changelogs = run_phase3(
                changelogs=changelogs,
                changes=analysis_result.changes,
                changelog_config=changelog_config,
                version=str(next_version),
            )

        # === Set Outputs ===
        log_group("Setting outputs")

        set_output("bump", analysis_result.bump)
        set_output("current_version", str(current_version))
        set_output("next_version", str(next_version))
        set_output("reasoning", analysis_result.reasoning)

        # Changelogs (always populated - uses default audience if no config)
        set_output("changelogs", json.dumps(changelogs))
        set_output("metadata", json.dumps(metadata))

        # Changes as JSON
        changes_json = [
            {
                "id": c.id,
                "category": c.category.value,
                "title": c.title,
                "description": c.description,
                "importance": c.importance.value,
                "commits": c.commits,
                "authors": c.authors,
            }
            for c in analysis_result.changes
        ]
        set_output("changes", json.dumps(changes_json))

        # Stats
        stats = analysis_result.stats or ChangeStats.from_changes(analysis_result.changes)
        set_output("stats", json.dumps(stats.to_dict()))

        # Breaking changes (legacy format)
        breaking = [
            c.title for c in analysis_result.changes
            if c.breaking is not None
        ]
        set_output("breaking_changes", json.dumps(breaking))

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

    finally:
        # Always output usage stats, even on failure (for cost tracking)
        if _usage.models:
            set_output("usage", json.dumps(_usage.to_dict()))
            print()
            print("=== LLM Usage (tokens consumed before exit) ===")
            for model, stats in _usage.models.items():
                print(f"  {model}: {int(stats['calls'])} calls, {int(stats['input_tokens']):,}+{int(stats['output_tokens']):,} tokens, {stats['latency_ms']:.0f}ms")
        else:
            print()
            print("=== LLM Usage: No LLM calls were made ===")


if __name__ == "__main__":
    sys.exit(main())
