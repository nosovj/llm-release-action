"""Output validation for generated changelogs (Phase 3).

Validates generated changelogs before output to catch:
- Malformed content
- Empty responses
- Placeholder text
- Language mismatches
- Hallucinations
"""

from dataclasses import dataclass, field
from typing import List, Optional

from models import Change


@dataclass
class ValidationConfig:
    """Configuration for output validation."""

    enabled: bool = True

    # Checks to perform
    check_structure: bool = True  # Valid markdown/html format
    check_not_empty: bool = True  # Has actual content
    check_no_placeholders: bool = True  # No "[INSERT HERE]", "TODO:", etc.
    check_language_match: bool = True  # Actually in requested language
    check_references_changes: bool = True  # Mentions real changes

    # Length bounds
    min_length: int = 50  # Catches truncation
    max_length: int = 100000  # Catches runaway generation

    # Failure handling
    on_failure: str = "retry"  # retry | warn | error | fallback
    max_retries: int = 2


@dataclass
class ValidationResult:
    """Result of validation."""

    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# Common placeholder patterns that indicate LLM failures
PLACEHOLDER_PATTERNS = [
    "[INSERT",
    "TODO:",
    "XXX",
    "[TBD]",
    "PLACEHOLDER",
    "[ADD",
    "[FILL",
    "[YOUR",
    "...",  # Often indicates truncation
    "EXAMPLE:",
]


def detect_language(text: str) -> str:
    """Detect the language of text.

    Args:
        text: Text to analyze

    Returns:
        ISO 639-1 language code or "unknown"
    """
    try:
        from langdetect import detect

        # Need at least some content
        if len(text.strip()) < 20:
            return "unknown"

        return detect(text)
    except ImportError:
        # langdetect not installed
        return "unknown"
    except Exception:
        return "unknown"


def check_markdown_structure(content: str) -> List[str]:
    """Check if content has valid markdown structure.

    Args:
        content: Markdown content to check

    Returns:
        List of issues found
    """
    issues = []
    lines = content.split("\n")

    # Should have at least one header
    has_header = any(line.startswith("#") for line in lines)
    if not has_header:
        issues.append("No markdown headers found")

    # Check for unclosed code blocks
    code_block_count = content.count("```")
    if code_block_count % 2 != 0:
        issues.append("Unclosed code block detected")

    # Check for malformed links
    # Look for [text]( without closing )
    import re

    unclosed_links = re.findall(r"\[[^\]]*\]\([^)]*$", content, re.MULTILINE)
    if unclosed_links:
        issues.append("Unclosed markdown links detected")

    return issues


def check_html_structure(content: str) -> List[str]:
    """Check if content has valid HTML structure.

    Args:
        content: HTML content to check

    Returns:
        List of issues found
    """
    issues = []

    # Simple check for balanced tags
    import re

    open_tags = re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*>", content)
    close_tags = re.findall(r"</([a-zA-Z][a-zA-Z0-9]*)>", content)

    # Filter out self-closing tags
    self_closing = {"br", "hr", "img", "input", "meta", "link"}
    open_tags = [t.lower() for t in open_tags if t.lower() not in self_closing]
    close_tags = [t.lower() for t in close_tags]

    if len(open_tags) != len(close_tags):
        issues.append("Unbalanced HTML tags detected")

    return issues


def check_references_changes(content: str, changes: List[Change]) -> List[str]:
    """Check if changelog references actual changes.

    This is a heuristic check to catch hallucinations.

    Args:
        content: Generated changelog
        changes: Actual changes from Phase 1

    Returns:
        List of issues found
    """
    issues = []

    if not changes:
        return issues

    # Extract key terms from actual changes
    change_terms = set()
    for change in changes:
        # Add words from title
        words = change.title.lower().split()
        change_terms.update(w for w in words if len(w) > 3)

    # Check if content references at least some of these terms
    content_lower = content.lower()
    matched_terms = sum(1 for term in change_terms if term in content_lower)

    # Should match at least 20% of terms
    if change_terms and matched_terms / len(change_terms) < 0.2:
        issues.append("Changelog may not reference actual changes (possible hallucination)")

    return issues


def validate_changelog(
    changelog: str,
    language: str,
    changes: List[Change],
    config: ValidationConfig,
    output_format: str = "markdown",
) -> ValidationResult:
    """Validate a generated changelog.

    Args:
        changelog: Generated changelog content
        language: Expected language code
        changes: Actual changes from Phase 1
        config: Validation configuration
        output_format: Expected format (markdown, html, json, plain)

    Returns:
        ValidationResult with valid flag and issues
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not config.enabled:
        return ValidationResult(valid=True)

    # Length check - minimum
    if config.check_not_empty:
        if len(changelog.strip()) < config.min_length:
            errors.append(
                f"Changelog too short ({len(changelog)} < {config.min_length} chars)"
            )

    # Length check - maximum
    if len(changelog) > config.max_length:
        errors.append(f"Changelog too long ({len(changelog)} > {config.max_length} chars)")

    # Placeholder check
    if config.check_no_placeholders:
        changelog_upper = changelog.upper()
        for placeholder in PLACEHOLDER_PATTERNS:
            if placeholder.upper() in changelog_upper:
                errors.append(f"Found placeholder: {placeholder}")

    # Structure check
    if config.check_structure:
        if output_format == "markdown":
            structure_issues = check_markdown_structure(changelog)
            warnings.extend(structure_issues)
        elif output_format == "html":
            structure_issues = check_html_structure(changelog)
            warnings.extend(structure_issues)

    # Language match check
    if config.check_language_match:
        detected = detect_language(changelog)
        if detected != "unknown":
            # Handle language code normalization (e.g., "zh-TW" -> "zh")
            expected_base = language.split("-")[0].lower()
            detected_base = detected.lower()
            if detected_base != expected_base:
                warnings.append(
                    f"Language mismatch: expected {language}, detected {detected}"
                )

    # References changes check
    if config.check_references_changes:
        reference_issues = check_references_changes(changelog, changes)
        warnings.extend(reference_issues)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def generate_fallback_changelog(
    version: str,
    changes: List[Change],
    language: str = "en",
) -> str:
    """Generate a minimal fallback changelog when validation fails.

    Args:
        version: Version string
        changes: List of changes
        language: Target language (only English supported for fallback)

    Returns:
        Minimal changelog content
    """
    from models import ChangeStats

    stats = ChangeStats.from_changes(changes)

    # Simple fallback template
    parts = [f"## {version}", ""]

    if stats.breaking > 0:
        parts.append(f"**Breaking Changes:** {stats.breaking}")
    if stats.features > 0:
        parts.append(f"**New Features:** {stats.features}")
    if stats.fixes > 0:
        parts.append(f"**Bug Fixes:** {stats.fixes}")
    if stats.improvements > 0:
        parts.append(f"**Improvements:** {stats.improvements}")
    if stats.security > 0:
        parts.append(f"**Security Updates:** {stats.security}")

    parts.append("")
    parts.append("See commit history for details.")

    return "\n".join(parts)
