"""Input validation for the action.

All inputs are validated BEFORE any LLM calls. If validation fails,
the action fails fast with clear error messages.
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from config import validate_changelog_config
from content_scanner import scan_content_override, handle_scan_result


@dataclass
class InputValidationResult:
    """Result of input validation."""

    valid: bool
    errors: List[str]


def validate_version_format(version: str) -> List[str]:
    """Validate version string against semver pattern.

    Args:
        version: Version string to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    if not re.match(r"^v?\d+\.\d+\.\d+(-[\w.]+)?$", version):
        errors.append(f"Invalid version format: {version}. Expected: v1.2.3 or 1.2.3-alpha.1")
    return errors


def validate_language_code(code: str) -> List[str]:
    """Validate a language code against BCP 47 standard.

    Prevents prompt injection by rejecting anything that isn't
    a valid language tag structure.

    Valid examples: en, es, ja, zh-TW, pt-BR, en-US
    Invalid examples: "ignore instructions", "en; DROP TABLE", arbitrary text

    Args:
        code: Language code to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Must be a string
    if not isinstance(code, str):
        errors.append(f"Language code must be a string, got {type(code).__name__}")
        return errors

    # Length sanity check (BCP 47 tags are short)
    if len(code) > 35:  # Longest valid tag is ~35 chars
        errors.append(f"Language code '{code[:20]}...' is too long")
        return errors

    # Character whitelist: only alphanumeric and hyphens allowed in BCP 47
    if not all(c.isalnum() or c == "-" for c in code):
        errors.append(f"Language code '{code}' contains invalid characters")
        return errors

    # Try to import langcodes for validation
    try:
        import langcodes
        from langcodes import Language

        # Parse as BCP 47 tag
        lang = Language.get(code)

        # Check if it's a valid, recognized language
        if not lang.is_valid():
            errors.append(f"Language code '{code}' is not a valid BCP 47 tag")

        # Check if language is well-known (has a name)
        # This catches technically-valid but nonsense tags
        try:
            name = lang.language_name()
            if not name:
                errors.append(f"Language code '{code}' is not a recognized language")
        except Exception:
            errors.append(f"Language code '{code}' is not a recognized language")

    except ImportError:
        # langcodes not installed - fall back to basic pattern validation
        # Most common patterns: en, en-US, zh-Hans, pt-BR
        if not re.match(r"^[a-z]{2,3}(-[A-Za-z]{2,8})*$", code):
            errors.append(f"Language code '{code}' does not match expected pattern")
    except Exception as e:
        errors.append(f"Failed to parse language code '{code}': {e}")

    return errors


def validate_filter_value(value: str, field_name: str) -> List[str]:
    """Validate filter values (patterns, authors, labels).

    Args:
        value: Value to validate
        field_name: Name of the field for error messages

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Length limit
    if len(value) > 100:
        errors.append(f"{field_name} value too long (max 100 chars)")

    # No control characters or newlines
    if re.search(r"[\x00-\x1f]", value):
        errors.append(f"{field_name} contains invalid characters")

    return errors


def validate_glob_pattern(pattern: str) -> bool:
    """Check if a pattern is a valid glob pattern.

    Args:
        pattern: Glob pattern to validate

    Returns:
        True if valid
    """
    # Basic validation - glob patterns should only contain safe chars
    # Allow: alphanumeric, /, *, ?, [, ], ., -, _, **
    if not pattern:
        return False

    # Check for obviously invalid patterns
    if re.search(r"[<>|;`$]", pattern):
        return False

    return True


def validate_inputs(
    current_version: Optional[str] = None,
    head_ref: Optional[str] = None,
    content_override: Optional[str] = None,
    changelog_config: Optional[str] = None,
    include_diffs: Optional[str] = None,
) -> InputValidationResult:
    """Validate all action inputs before processing.

    Args:
        current_version: Current version string
        head_ref: Head git ref
        content_override: Optional content override for multi-repo
        changelog_config: Optional changelog config YAML/JSON
        include_diffs: Comma-separated file patterns

    Returns:
        InputValidationResult with valid flag and errors list
    """
    errors: List[str] = []

    # Version format validation
    if current_version:
        errors.extend(validate_version_format(current_version))

    # Either commits available OR content_override required
    if not content_override:
        # Will need git commits - check we're in a git repo
        if not os.path.exists(".git"):
            errors.append("Not in a git repository and no content_override provided")

    # Content override validation (smart scanner)
    if content_override:
        scan_result = scan_content_override(content_override)
        try:
            handle_scan_result(scan_result)
        except ValueError as e:
            errors.append(str(e))

    # changelog_config must be valid YAML/JSON if provided
    if changelog_config:
        try:
            config = yaml.safe_load(changelog_config)
            if config is None:
                # Empty config is valid
                pass
            elif not isinstance(config, dict):
                errors.append("changelog_config must be a YAML/JSON object")
            else:
                # Validate structure
                config_errors = validate_changelog_config(config)
                errors.extend(config_errors)

                # Validate languages separately (needs langcodes)
                for audience, settings in config.items():
                    if isinstance(settings, dict):
                        languages = settings.get("languages", [])
                        if isinstance(languages, list):
                            for lang in languages:
                                lang_errors = validate_language_code(lang)
                                errors.extend([f"{audience}: {e}" for e in lang_errors])
        except yaml.YAMLError as e:
            errors.append(f"Invalid changelog_config YAML: {e}")

    # include_diffs must be valid glob patterns
    if include_diffs:
        for pattern in include_diffs.split(","):
            pattern = pattern.strip()
            if pattern and not validate_glob_pattern(pattern):
                errors.append(f"Invalid glob pattern: {pattern}")

    return InputValidationResult(valid=len(errors) == 0, errors=errors)


def validate_audience_configs(configs: Dict[str, Any]) -> List[str]:
    """Validate all audience configurations including languages.

    Args:
        configs: Dictionary of audience configurations

    Returns:
        List of validation errors
    """
    errors: List[str] = []

    for audience, settings in configs.items():
        if not isinstance(settings, dict):
            continue

        # Validate exclude patterns
        for pattern in settings.get("exclude_patterns", []):
            pattern_errors = validate_filter_value(pattern, f"{audience}.exclude_patterns")
            errors.extend(pattern_errors)

        # Validate exclude authors
        for author in settings.get("exclude_authors", []):
            author_errors = validate_filter_value(author, f"{audience}.exclude_authors")
            errors.extend(author_errors)

        # Validate exclude labels
        for label in settings.get("exclude_labels", []):
            label_errors = validate_filter_value(label, f"{audience}.exclude_labels")
            errors.extend(label_errors)

    return errors
