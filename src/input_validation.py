"""Input validation for the action.

All inputs are validated BEFORE any LLM calls. If validation fails,
the action fails fast with clear error messages.
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import regex
import yaml

from config import validate_changelog_config
from content_scanner import scan_content_override, handle_scan_result, ValidationMode


# Maximum pattern length to reduce ReDoS attack surface
MAX_PATTERN_LENGTH = 200

# Default timeout for regex operations (in seconds)
REGEX_TIMEOUT = 1.0


class PatternCompilationError(Exception):
    """Error raised when a regex pattern fails to compile or is unsafe."""

    pass


class PatternTimeoutError(Exception):
    """Error raised when a regex pattern times out during matching."""

    pass


def validate_pattern_safety(pattern: str) -> List[str]:
    """Validate that a regex pattern is not prone to ReDoS attacks.

    Detects dangerous patterns:
    - Nested quantifiers: (a+)+, (a*)+, (a?)+, (a*)*, etc.
    - Overlapping alternations: (a|a)+, (a|ab)+
    - Excessive repetition groups

    Args:
        pattern: Regex pattern to validate

    Returns:
        List of validation errors (empty if safe)
    """
    errors = []

    # Check pattern length
    if len(pattern) > MAX_PATTERN_LENGTH:
        errors.append(
            f"Pattern too long ({len(pattern)} chars, max {MAX_PATTERN_LENGTH})"
        )
        return errors  # Skip other checks for overly long patterns

    # Detect nested quantifiers: (...)+ or (...)* followed by another quantifier
    # Pattern: group with quantifier inside, followed by outer quantifier
    nested_quantifier_patterns = [
        r"\([^)]*[+*]\)[+*?]",  # (...+)* or (...*)+
        r"\([^)]*[+*]\)\{",  # (...+){n} or (...*){n}
        r"\([^)]*\{[^}]+\}\)[+*?]",  # (...{n})+
        r"\([^)]*\{[^}]+\}\)\{",  # (...{n}){m}
    ]

    for np in nested_quantifier_patterns:
        if re.search(np, pattern):
            errors.append(
                f"Pattern contains nested quantifiers which can cause catastrophic backtracking: {pattern}"
            )
            break

    # Detect overlapping alternations with quantifier: (a|a)+ or similar
    # Simple check: alternation inside group with quantifier
    if re.search(r"\([^)]*\|[^)]*\)[+*]", pattern):
        # Check if the alternation parts overlap
        match = re.search(r"\(([^)|]+)\|([^)]+)\)[+*]", pattern)
        if match:
            alt1, alt2 = match.group(1), match.group(2)
            # Check for obvious overlap (one starts with the other)
            if alt1.startswith(alt2) or alt2.startswith(alt1):
                errors.append(
                    f"Pattern contains overlapping alternations which can cause backtracking: {pattern}"
                )

    # Detect patterns like .* or .+ followed by same, which can be slow
    if re.search(r"\.\*.*\.\*", pattern) or re.search(r"\.\+.*\.\+", pattern):
        # Only warn if there's no anchoring
        if not pattern.startswith("^") and not pattern.endswith("$"):
            errors.append(
                f"Pattern contains multiple unbounded wildcards without anchoring: {pattern}"
            )

    return errors


class TimeoutPattern:
    """Wrapper around regex.Pattern that applies timeout on matching operations."""

    def __init__(self, pattern: regex.Pattern, timeout: float):
        self._pattern = pattern
        self._timeout = timeout

    def search(self, string: str, *args, **kwargs):
        """Search with timeout."""
        try:
            return self._pattern.search(string, *args, timeout=self._timeout, **kwargs)
        except TimeoutError:
            raise PatternTimeoutError(
                f"Pattern matching timed out after {self._timeout}s"
            )

    def match(self, string: str, *args, **kwargs):
        """Match with timeout."""
        try:
            return self._pattern.match(string, *args, timeout=self._timeout, **kwargs)
        except TimeoutError:
            raise PatternTimeoutError(
                f"Pattern matching timed out after {self._timeout}s"
            )

    def fullmatch(self, string: str, *args, **kwargs):
        """Fullmatch with timeout."""
        try:
            return self._pattern.fullmatch(string, *args, timeout=self._timeout, **kwargs)
        except TimeoutError:
            raise PatternTimeoutError(
                f"Pattern matching timed out after {self._timeout}s"
            )

    def findall(self, string: str, *args, **kwargs):
        """Findall with timeout."""
        try:
            return self._pattern.findall(string, *args, timeout=self._timeout, **kwargs)
        except TimeoutError:
            raise PatternTimeoutError(
                f"Pattern matching timed out after {self._timeout}s"
            )

    def sub(self, repl, string: str, *args, **kwargs):
        """Sub with timeout."""
        try:
            return self._pattern.sub(repl, string, *args, timeout=self._timeout, **kwargs)
        except TimeoutError:
            raise PatternTimeoutError(
                f"Pattern matching timed out after {self._timeout}s"
            )

    @property
    def pattern(self):
        """Return the pattern string."""
        return self._pattern.pattern


def safe_compile_pattern(
    pattern: str, timeout: float = REGEX_TIMEOUT
) -> TimeoutPattern:
    """Safely compile a regex pattern with timeout support.

    Uses the `regex` library which supports timeout on matching operations.
    Returns a wrapper that automatically applies timeout on all matching methods.

    Args:
        pattern: Regex pattern to compile
        timeout: Timeout in seconds for matching operations (default: 1.0)

    Returns:
        TimeoutPattern wrapper with automatic timeout on matching operations

    Raises:
        PatternCompilationError: If pattern is invalid or fails safety checks
    """
    # First, validate pattern safety
    safety_errors = validate_pattern_safety(pattern)
    if safety_errors:
        raise PatternCompilationError("; ".join(safety_errors))

    try:
        # Compile pattern (timeout is applied on matching operations, not compile)
        compiled = regex.compile(pattern, regex.IGNORECASE)
        return TimeoutPattern(compiled, timeout)
    except regex.error as e:
        raise PatternCompilationError(f"Invalid regex pattern: {e}")
    except Exception as e:
        raise PatternCompilationError(f"Failed to compile pattern: {e}")


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


def validate_filter_value(value: str, field_name: str, is_pattern: bool = False) -> List[str]:
    """Validate filter values (patterns, authors, labels).

    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        is_pattern: Whether this value is a regex pattern (applies stricter validation)

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Pattern length limit (stricter for regex patterns)
    max_length = MAX_PATTERN_LENGTH if is_pattern else 100
    if len(value) > max_length:
        errors.append(f"{field_name} value too long (max {max_length} chars)")

    # No control characters or newlines
    if re.search(r"[\x00-\x1f]", value):
        errors.append(f"{field_name} contains invalid characters")

    # For patterns, also validate ReDoS safety
    if is_pattern:
        safety_errors = validate_pattern_safety(value)
        for err in safety_errors:
            errors.append(f"{field_name}: {err}")

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


def validate_gitignore_pattern(pattern: str) -> List[str]:
    """Validate a gitignore-style pattern for context_files.

    Supports negation (!) and standard glob patterns.

    Args:
        pattern: Gitignore-style pattern to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not pattern:
        return errors  # Empty pattern is valid (will be skipped)

    # Strip whitespace
    pattern = pattern.strip()

    # Handle negation prefix
    actual_pattern = pattern[1:] if pattern.startswith("!") else pattern

    if not actual_pattern:
        errors.append(f"Empty pattern after negation prefix: {pattern}")
        return errors

    # Check for invalid characters
    if re.search(r"[<>|;`$]", actual_pattern):
        errors.append(f"Pattern contains invalid characters: {pattern}")

    # Check for path traversal attempts
    if ".." in actual_pattern:
        errors.append(f"Pattern contains path traversal (..): {pattern}")

    # Validate pattern length
    if len(pattern) > 500:
        errors.append(f"Pattern too long (max 500 chars): {pattern[:50]}...")

    return errors


def validate_context_files_patterns(patterns_str: str) -> List[str]:
    """Validate comma-separated context file patterns.

    Args:
        patterns_str: Comma-separated gitignore-style patterns

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not patterns_str or not patterns_str.strip():
        return errors  # Empty is valid (no context files)

    patterns = [p.strip() for p in patterns_str.split(",")]

    for pattern in patterns:
        pattern_errors = validate_gitignore_pattern(pattern)
        errors.extend(pattern_errors)

    # Try to compile with pathspec to catch syntax errors
    try:
        import pathspec
        pathspec.PathSpec.from_lines("gitwildmatch", patterns)
    except ImportError:
        # pathspec not installed yet - skip this check
        pass
    except Exception as e:
        errors.append(f"Invalid pattern syntax: {e}")

    return errors


def validate_context_max_tokens(value: str) -> List[str]:
    """Validate context_max_tokens input.

    Args:
        value: String value from action input

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not value or not value.strip():
        return errors  # Empty uses default

    try:
        tokens = int(value)
        if tokens <= 0:
            errors.append(f"context_max_tokens must be positive, got {tokens}")
        if tokens > 100000:
            errors.append(f"context_max_tokens too large ({tokens}), max 100000")
    except ValueError:
        errors.append(f"context_max_tokens must be an integer, got '{value}'")

    return errors


def validate_analyze_diffs(value: str) -> List[str]:
    """Validate analyze_diffs input (boolean string).

    Args:
        value: String value from action input ('true' or 'false')

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not value or not value.strip():
        return errors  # Empty uses default

    normalized = value.strip().lower()
    if normalized not in ("true", "false"):
        errors.append(
            f"analyze_diffs must be 'true' or 'false', got '{value}'"
        )

    return errors


def validate_diff_exclude_patterns(patterns: str) -> List[str]:
    """Validate diff_exclude_patterns input (comma-separated gitignore-style patterns).

    Reuses validate_context_files_patterns for consistent pattern validation.

    Args:
        patterns: Comma-separated gitignore-style patterns

    Returns:
        List of validation errors (empty if valid)
    """
    # Reuse existing gitignore pattern validation
    return validate_context_files_patterns(patterns)


def validate_diff_max_files(value: str) -> List[str]:
    """Validate diff_max_files input (non-negative integer).

    Args:
        value: String value from action input

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not value or not value.strip():
        return errors  # Empty uses default

    try:
        max_files = int(value)
        if max_files < 0:
            errors.append(f"diff_max_files must be non-negative, got {max_files}")
    except ValueError:
        errors.append(f"diff_max_files must be an integer, got '{value}'")

    return errors


def validate_diff_max_total_lines(value: str) -> List[str]:
    """Validate diff_max_total_lines input (non-negative integer).

    Args:
        value: String value from action input

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not value or not value.strip():
        return errors  # Empty uses default

    try:
        max_lines = int(value)
        if max_lines < 0:
            errors.append(f"diff_max_total_lines must be non-negative, got {max_lines}")
    except ValueError:
        errors.append(f"diff_max_total_lines must be an integer, got '{value}'")

    return errors


def validate_inputs(
    current_version: Optional[str] = None,
    head_ref: Optional[str] = None,
    content_override: Optional[str] = None,
    changelog_config: Optional[str] = None,
    include_diffs: Optional[str] = None,
    validation_mode: ValidationMode = ValidationMode.BOTH,
    context_files: Optional[str] = None,
    context_max_tokens: Optional[str] = None,
    analyze_diffs: Optional[str] = None,
    diff_exclude_patterns: Optional[str] = None,
    diff_max_files: Optional[str] = None,
    diff_max_total_lines: Optional[str] = None,
) -> InputValidationResult:
    """Validate all action inputs before processing.

    Args:
        current_version: Current version string
        head_ref: Head git ref
        content_override: Optional content override for multi-repo
        changelog_config: Optional changelog config YAML/JSON
        include_diffs: Comma-separated file patterns
        validation_mode: Content validation mode (NONE skips injection scanning)
        context_files: Comma-separated gitignore-style patterns for context files
        context_max_tokens: Maximum tokens for context content
        analyze_diffs: Enable diff analysis ('true' or 'false')
        diff_exclude_patterns: Comma-separated gitignore-style patterns for diff exclusion
        diff_max_files: Maximum number of files to include in diff analysis
        diff_max_total_lines: Maximum total lines of diff content

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

    # Content override validation (smart scanner) - skip if validation_mode is NONE
    if content_override and validation_mode != ValidationMode.NONE:
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

    # context_files must be valid gitignore-style patterns
    if context_files:
        errors.extend(validate_context_files_patterns(context_files))

    # context_max_tokens must be a positive integer
    if context_max_tokens:
        errors.extend(validate_context_max_tokens(context_max_tokens))

    # Diff analysis parameters validation
    if analyze_diffs:
        errors.extend(validate_analyze_diffs(analyze_diffs))

    if diff_exclude_patterns:
        errors.extend(validate_diff_exclude_patterns(diff_exclude_patterns))

    if diff_max_files:
        errors.extend(validate_diff_max_files(diff_max_files))

    if diff_max_total_lines:
        errors.extend(validate_diff_max_total_lines(diff_max_total_lines))

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

        # Validate exclude patterns (with ReDoS safety check)
        for pattern in settings.get("exclude_patterns", []):
            pattern_errors = validate_filter_value(
                pattern, f"{audience}.exclude_patterns", is_pattern=True
            )
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
