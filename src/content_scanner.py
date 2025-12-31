"""Smart content scanner for detecting injection attacks and context window abuse.

This module provides fast, regex-based detection of known attack patterns
without requiring ML dependencies. Designed for CI pipeline execution.
"""

import base64
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ThreatLevel(Enum):
    """Threat levels for scan results."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ScanResult:
    """Result of content scanning."""

    threat_level: ThreatLevel
    issues: List[str]
    token_estimate: int
    truncated: bool


# === KNOWN INJECTION PATTERNS ===

ROLE_HIJACKING = [
    r"(?i)^\s*(system|user|assistant|human|ai)\s*:",  # Role prefixes
    r"(?i)<\|?(system|user|assistant|im_start|im_end)\|?>",  # ChatML tags
    r"(?i)\[INST\]|\[/INST\]",  # Llama format
    r"(?i)### (instruction|response|human|assistant)",  # Alpaca format
]

INSTRUCTION_INJECTION = [
    r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|context)",
    r"(?i)disregard\s+(everything|all|the)\s+(above|previous|prior)",
    r"(?i)forget\s+(everything|all|your)\s+(instructions?|training|rules)",
    r"(?i)new\s+(instructions?|rules?|prompt)\s*:",
    r"(?i)override\s+(previous|all|the)\s+(instructions?|rules?)",
    r"(?i)you\s+are\s+now\s+(a|an|in)\s+",  # "You are now a DAN"
    r"(?i)pretend\s+(you|to\s+be)\s+",
    r"(?i)act\s+as\s+(if|though|a)\s+",
    r"(?i)jailbreak|DAN|do\s+anything\s+now",
]

DELIMITER_INJECTION = [
    r"```+\s*(system|prompt|instruction)",  # Code block escape
    r"-{3,}\s*(system|new|instruction)",  # Markdown separator abuse
    r"#{3,}\s*(system|instruction|prompt)",  # Header injection
    r"</?prompt>|</?instruction>|</?system>",  # XML-like tags
]


# === CONTEXT WINDOW ATTACKS ===


def detect_context_attacks(content: str) -> List[str]:
    """Detect attempts to exhaust or manipulate context window.

    Args:
        content: Content to analyze

    Returns:
        List of detected issues
    """
    issues = []

    # Excessive repetition (trying to fill context)
    # Find any pattern repeated more than 10 times
    for match in re.finditer(r"(.{10,}?)\1{10,}", content):
        repeat_count = len(match.group(0)) // len(match.group(1))
        issues.append(
            f"Excessive repetition detected: '{match.group(1)[:30]}...' repeated {repeat_count} times"
        )

    # Very long lines without breaks (context stuffing)
    for i, line in enumerate(content.split("\n")):
        if len(line) > 10000:
            issues.append(f"Line {i + 1} exceeds 10KB - possible context stuffing")

    # Excessive whitespace/newlines
    if len(content) > 0 and content.count("\n") > len(content) / 3:
        issues.append("Excessive newlines - possible context padding")

    return issues


# === ENCODING TRICKS ===


def detect_encoding_tricks(content: str) -> List[str]:
    """Detect encoding-based attacks.

    Args:
        content: Content to analyze

    Returns:
        List of detected issues
    """
    issues = []

    # Base64 encoded blocks (might hide instructions)
    base64_pattern = r"[A-Za-z0-9+/]{50,}={0,2}"
    b64_matches = re.findall(base64_pattern, content)
    for match in b64_matches:
        try:
            decoded = base64.b64decode(match).decode("utf-8", errors="ignore")
            # Check if decoded content contains injection patterns
            for pattern in INSTRUCTION_INJECTION:
                if re.search(pattern, decoded):
                    issues.append("Base64-encoded injection detected")
                    break
        except Exception:
            pass

    # Unicode tricks
    # Zero-width characters
    if re.search(r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f]", content):
        issues.append("Zero-width or invisible unicode characters detected")

    # Homoglyphs (Cyrillic/Greek letters that look like Latin)
    if re.search(r"[\u0400-\u04ff\u0370-\u03ff]", content):
        # Check if mixed with Latin
        if re.search(r"[a-zA-Z]", content):
            issues.append("Mixed script detected (possible homoglyph attack)")

    # RTL override characters
    if re.search(r"[\u202a-\u202e\u2066-\u2069]", content):
        issues.append("Bidirectional text override characters detected")

    return issues


# === FORMAT VALIDATION ===


def validate_changelog_format(content: str) -> List[str]:
    """Validate content looks like changelogs, not exploits.

    Args:
        content: Content to validate

    Returns:
        List of format issues
    """
    issues = []

    lines = content.strip().split("\n")
    if not lines:
        issues.append("Empty content")
        return issues

    # Changelogs should have structure
    has_headers = any(line.startswith("#") for line in lines)
    has_bullets = any(line.strip().startswith(("-", "*", "•")) for line in lines)

    if not has_headers and not has_bullets:
        issues.append("Content doesn't look like a changelog (no headers or bullet points)")

    # Code ratio check (changelogs shouldn't be mostly code)
    code_block_chars = sum(len(m.group(0)) for m in re.finditer(r"```[\s\S]*?```", content))
    if len(content) > 0 and code_block_chars / len(content) > 0.5:
        issues.append("Content is >50% code blocks - unusual for changelog")

    # URL density check
    urls = re.findall(r"https?://\S+", content)
    if len(urls) > 50:
        issues.append(f"Excessive URLs ({len(urls)}) - possible spam/injection")

    return issues


# === TOKEN ESTIMATION ===


def estimate_tokens(content: str) -> int:
    """Rough token estimate without loading tokenizer.

    Rule of thumb: ~4 chars per token for English, ~2 for code.

    Args:
        content: Content to estimate

    Returns:
        Estimated token count
    """
    # Simple heuristic: split on whitespace and punctuation
    words = re.findall(r"\b\w+\b", content)
    # Add extra for punctuation and special chars
    return int(len(words) * 1.3)


# === MAIN SCANNER ===

MAX_TOKENS = 8000  # Leave room for prompt template
MAX_CONTENT_SIZE = 500_000  # 500KB hard limit


def _max_threat_level(current: ThreatLevel, new: ThreatLevel) -> ThreatLevel:
    """Get the higher of two threat levels."""
    levels = list(ThreatLevel)
    return current if levels.index(current) >= levels.index(new) else new


def scan_content_override(content: str) -> ScanResult:
    """Comprehensive scan of content_override for security issues.

    Args:
        content: Content to scan

    Returns:
        ScanResult with threat level, issues, and token estimate
    """
    issues: List[str] = []
    threat_level = ThreatLevel.NONE

    # === Size checks ===
    if len(content) > MAX_CONTENT_SIZE:
        return ScanResult(
            threat_level=ThreatLevel.CRITICAL,
            issues=["Content exceeds 500KB limit"],
            token_estimate=0,
            truncated=False,
        )

    token_estimate = estimate_tokens(content)
    truncated = False

    if token_estimate > MAX_TOKENS:
        issues.append(
            f"Content estimated at {token_estimate} tokens, will be truncated to {MAX_TOKENS}"
        )
        truncated = True
        threat_level = ThreatLevel.LOW

    # === Injection pattern detection ===
    for pattern in ROLE_HIJACKING:
        if re.search(pattern, content):
            issues.append(f"Role hijacking pattern detected: {pattern}")
            threat_level = _max_threat_level(threat_level, ThreatLevel.HIGH)

    for pattern in INSTRUCTION_INJECTION:
        if re.search(pattern, content):
            issues.append("Instruction injection pattern detected")
            threat_level = _max_threat_level(threat_level, ThreatLevel.HIGH)

    for pattern in DELIMITER_INJECTION:
        if re.search(pattern, content):
            issues.append("Delimiter injection pattern detected")
            threat_level = _max_threat_level(threat_level, ThreatLevel.MEDIUM)

    # === Context attacks ===
    context_issues = detect_context_attacks(content)
    issues.extend(context_issues)
    if context_issues:
        threat_level = _max_threat_level(threat_level, ThreatLevel.MEDIUM)

    # === Encoding tricks ===
    encoding_issues = detect_encoding_tricks(content)
    issues.extend(encoding_issues)
    if encoding_issues:
        threat_level = _max_threat_level(threat_level, ThreatLevel.HIGH)

    # === Format validation ===
    format_issues = validate_changelog_format(content)
    issues.extend(format_issues)
    if format_issues:
        threat_level = _max_threat_level(threat_level, ThreatLevel.LOW)

    # === Control characters ===
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", content):
        issues.append("Control characters detected")
        threat_level = _max_threat_level(threat_level, ThreatLevel.MEDIUM)

    return ScanResult(
        threat_level=threat_level,
        issues=issues,
        token_estimate=min(token_estimate, MAX_TOKENS),
        truncated=truncated,
    )


def parse_changelog_sections(content: str) -> dict:
    """Parse content into sections by detecting headers.

    Args:
        content: Changelog content

    Returns:
        Dictionary mapping section type to content
    """
    sections: dict = {}
    current_section = "other"
    current_content: List[str] = []

    section_keywords = {
        "breaking": ["breaking", "incompatible"],
        "feature": ["feature", "new", "added", "add"],
        "fix": ["fix", "bug", "patch", "resolved"],
        "security": ["security", "vulnerability", "cve"],
    }

    for line in content.split("\n"):
        if line.startswith("#"):
            # Save previous section
            if current_content:
                sections[current_section] = "\n".join(current_content)
                current_content = []

            # Detect section type
            header_lower = line.lower()
            detected = "other"
            for section_type, keywords in section_keywords.items():
                if any(kw in header_lower for kw in keywords):
                    detected = section_type
                    break
            current_section = detected

        current_content.append(line)

    # Save final section
    if current_content:
        sections[current_section] = "\n".join(current_content)

    return sections


def truncate_section(section: str, max_tokens: int) -> str:
    """Truncate a section to fit within token budget.

    Args:
        section: Section content
        max_tokens: Maximum tokens

    Returns:
        Truncated section
    """
    lines = section.split("\n")
    result: List[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = estimate_tokens(line)
        if current_tokens + line_tokens > max_tokens:
            result.append("... (truncated)")
            break
        result.append(line)
        current_tokens += line_tokens

    return "\n".join(result)


def truncate_for_context(content: str, max_tokens: int = MAX_TOKENS) -> str:
    """Intelligently truncate content to fit context window.

    Prioritizes:
    1. Breaking changes
    2. Security
    3. Features
    4. Fixes
    5. Other

    Args:
        content: Content to truncate
        max_tokens: Maximum tokens

    Returns:
        Truncated content
    """
    sections = parse_changelog_sections(content)

    priority_order = ["breaking", "security", "feature", "fix", "other"]

    result_parts: List[str] = []
    remaining_tokens = max_tokens

    for section_type in priority_order:
        if section_type in sections:
            section_tokens = estimate_tokens(sections[section_type])
            if section_tokens <= remaining_tokens:
                result_parts.append(sections[section_type])
                remaining_tokens -= section_tokens
            else:
                # Truncate this section
                truncated = truncate_section(sections[section_type], remaining_tokens)
                result_parts.append(truncated)
                break

    return "\n\n".join(result_parts)


def handle_scan_result(result: ScanResult, logger: Optional[object] = None) -> None:
    """Handle scan result based on threat level.

    Args:
        result: Scan result
        logger: Optional logger (uses print if not provided)

    Raises:
        ValueError: If threat level is CRITICAL
    """
    log = print if logger is None else getattr(logger, "warning", print)
    log_info = print if logger is None else getattr(logger, "info", print)

    if result.threat_level == ThreatLevel.CRITICAL:
        raise ValueError(f"Content rejected: {result.issues}")

    if result.threat_level == ThreatLevel.HIGH:
        log(f"::warning::High threat content: {result.issues}")

    if result.threat_level in (ThreatLevel.MEDIUM, ThreatLevel.LOW):
        log_info(f"Content scan: {result.issues}")

    if result.truncated:
        log(f"::warning::Content will be truncated to {result.token_estimate} tokens")
