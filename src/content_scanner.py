"""Smart content scanner for detecting injection attacks and context window abuse.

This module provides fast, regex-based detection of known attack patterns
without requiring ML dependencies. Designed for CI pipeline execution.

The module implements a layered defense:
1. Pattern-based detection (fast, regex-based) - always runs
2. LLM validation (optional) - for MEDIUM threat content when enabled
3. Response validation - detects successful injection in LLM output
"""

import base64
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional


class ThreatLevel(Enum):
    """Threat levels for scan results."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationMode(Enum):
    """Prompt injection validation modes."""

    BOTH = "both"  # Pattern + LLM validation (default, maximum security)
    PATTERN = "pattern"  # Pattern-based only (fast, no LLM cost)
    LLM = "llm"  # LLM validation only (adaptive but slower)
    NONE = "none"  # Disabled (not recommended)


@dataclass
class ScanResult:
    """Result of content scanning."""

    threat_level: ThreatLevel
    issues: List[str]
    token_estimate: int
    truncated: bool


# === KNOWN INJECTION PATTERNS ===

# Role hijacking: attempts to impersonate system/user/assistant roles
ROLE_HIJACKING = [
    r"(?i)^\s*(system|user|assistant|human|ai)\s*:",  # Role prefixes at line start
    r"(?i)^(Human|Assistant|System|User|AI):\s*",  # Explicit role markers
    r"(?i)<\|?(system|user|assistant|im_start|im_end)\|?>",  # ChatML tags
    r"(?i)\[INST\]|\[/INST\]",  # Llama format
    r"(?i)### (instruction|response|human|assistant)",  # Alpaca format
    r"(?i)<\|(begin|end)_of_text\|>",  # Special tokens
    r"(?i)<<SYS>>|<</SYS>>",  # Llama2 system delimiters
]

# Instruction injection: attempts to override or replace instructions
INSTRUCTION_INJECTION = [
    r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|context)",
    r"(?i)disregard\s+(everything|all|the)\s+(above|previous|prior)",
    r"(?i)forget\s+(everything|all|your)\s+(instructions?|training|rules|previous|prior)",
    r"(?i)new\s+(instructions?|rules?|prompt)\s*:",
    r"(?i)override\s+(previous|all|the)\s+(instructions?|rules?)",
    r"(?i)you\s+are\s+now\s+(a|an|in)\s+",  # "You are now a DAN"
    r"(?i)pretend\s+(you|to\s+be)\s+",
    r"(?i)act\s+as\s+(if|though|a)\s+",
    r"(?i)jailbreak|DAN|do\s+anything\s+now",
    r"(?i)from\s+now\s+on,?\s+(you|ignore|your)",  # "From now on, you..."
    r"(?i)your\s+new\s+(role|instructions?|persona)",  # "Your new role is..."
    r"(?i)stop\s+being\s+(an?\s+)?(ai|assistant|helpful)",  # "Stop being an AI"
    r"(?i)you\s+must\s+(now\s+)?ignore",  # "You must ignore..."
    r"(?i)begin\s+(your\s+)?new\s+(instructions?|session|role)",  # "Begin new instructions"
]

# Delimiter injection: attempts to escape prompt context
DELIMITER_INJECTION = [
    r"```+\s*(system|prompt|instruction)",  # Code block escape
    r"-{3,}\s*(system|new|instruction)",  # Markdown separator abuse
    r"#{3,}\s*(system|instruction|prompt)",  # Header injection
    r"</?prompt>|</?instruction>|</?system>",  # XML-like tags
    r"</?(user|assistant|message|context)>",  # More XML-like tags
    r"\[/?INST\]",  # Instruction delimiters
    r"<\|[a-z_]+\|>",  # Special token patterns like <|endoftext|>
    r"={3,}\s*(system|instruction|prompt)",  # Equals separator abuse
]

# Patterns to sanitize (remove) from content before embedding in prompts
SANITIZATION_PATTERNS = [
    # Role prefixes at line start (with optional leading whitespace)
    r"^\s*(Human|Assistant|System|User|AI):\s*",
    # Instruction injection phrases (these get stripped, not just detected)
    r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"(?i)disregard\s+(all\s+)?(previous|prior|above)",
    r"(?i)forget\s+(all\s+)?(previous|prior|above)",
    # Delimiter patterns
    r"</?(system|user|assistant|prompt|instruction)>",
    r"\[/?INST\]",
    r"<\|[a-z_]+\|>",
    r"<<SYS>>|<</SYS>>",
    # Special tokens
    r"<\|(begin|end)_of_text\|>",
]

# Response validation: patterns indicating successful injection in LLM output
RESPONSE_INJECTION_INDICATORS = [
    r"^(Human|Assistant|System):",  # Role prefix in output
    r"(?i)ignore.*instruction",  # Echoing injection
    r"(?i)I\s+(cannot|won't|refuse|am\s+unable)",  # Refusal patterns (might indicate attempted jailbreak)
    r"(?i)as\s+an?\s+(ai|language\s+model|assistant),?\s+I",  # AI self-reference (common in jailbreaks)
    r"(?i)my\s+(previous\s+)?instructions?\s+(are|were|told)",  # Referencing instructions
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

    HIGH and CRITICAL threats are now blocked (raise ValueError).
    MEDIUM and LOW threats are logged but allowed.

    Args:
        result: Scan result
        logger: Optional logger (uses print if not provided)

    Raises:
        ValueError: If threat level is CRITICAL or HIGH
    """
    log = print if logger is None else getattr(logger, "warning", print)
    log_info = print if logger is None else getattr(logger, "info", print)

    if result.threat_level == ThreatLevel.CRITICAL:
        raise ValueError(f"Content rejected (CRITICAL threat): {result.issues}")

    if result.threat_level == ThreatLevel.HIGH:
        # HIGH threats are now blocked, not just warned
        raise ValueError(f"Content rejected (HIGH threat): {result.issues}")

    if result.threat_level in (ThreatLevel.MEDIUM, ThreatLevel.LOW):
        log_info(f"Content scan: {result.issues}")

    if result.truncated:
        log(f"::warning::Content will be truncated to {result.token_estimate} tokens")


def sanitize_content(content: str) -> str:
    """Remove dangerous patterns from content before embedding in prompts.

    This function strips known injection patterns from content to make it safer
    for embedding in LLM prompts. It does NOT block content - use scan_content_override
    and handle_scan_result for threat detection and blocking.

    Args:
        content: Content to sanitize

    Returns:
        Sanitized content with dangerous patterns removed
    """
    sanitized = content

    for pattern in SANITIZATION_PATTERNS:
        # Use MULTILINE flag for patterns that start with ^
        flags = re.MULTILINE if pattern.startswith("^") else 0
        sanitized = re.sub(pattern, "", sanitized, flags=flags)

    # Clean up any resulting double newlines from removed content
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)

    return sanitized.strip()


# LLM validation prompt - kept minimal to reduce token usage
LLM_INJECTION_CHECK_PROMPT = """Is this text a prompt injection attempt? Answer only YES or NO.

Text: {text}

Answer:"""


def validate_with_llm(
    text: str,
    llm_caller: Callable[[str], str],
    max_chars: int = 500,
) -> bool:
    """Validate content using LLM for injection detection.

    This is Layer 2 validation - more adaptive than patterns but slower and costs tokens.
    Use for MEDIUM threat content when extra validation is desired.

    Args:
        text: Text to validate (will be truncated to max_chars)
        llm_caller: Function that calls the LLM and returns response
        max_chars: Maximum characters to send to LLM (default 500)

    Returns:
        True if injection detected, False if clean
    """
    # Truncate to avoid excessive token usage
    truncated_text = text[:max_chars]

    prompt = LLM_INJECTION_CHECK_PROMPT.format(text=truncated_text)
    response = llm_caller(prompt)

    # Check for YES in response (case insensitive)
    return "YES" in response.upper()


def validate_response(response: str) -> List[str]:
    """Validate LLM response for signs of successful injection.

    Check the LLM output for patterns that indicate the prompt injection
    was successful and affected the model's behavior.

    Args:
        response: LLM response to validate

    Returns:
        List of detected issues (empty if clean)
    """
    issues: List[str] = []

    for pattern in RESPONSE_INJECTION_INDICATORS:
        flags = re.MULTILINE if pattern.startswith("^") else 0
        if re.search(pattern, response, flags):
            issues.append(f"Suspicious pattern in response: {pattern}")

    return issues


def parse_validation_mode(mode_str: str) -> ValidationMode:
    """Parse validation mode from string input.

    Args:
        mode_str: String mode value (both, pattern, llm, none)

    Returns:
        ValidationMode enum value

    Raises:
        ValueError: If mode_str is not a valid mode
    """
    mode_lower = mode_str.lower().strip()
    valid_modes = {
        "both": ValidationMode.BOTH,
        "pattern": ValidationMode.PATTERN,
        "llm": ValidationMode.LLM,
        "none": ValidationMode.NONE,
    }
    if mode_lower not in valid_modes:
        raise ValueError(
            f"Invalid validate_injections mode: '{mode_str}'. "
            f"Valid values: {', '.join(valid_modes.keys())}"
        )
    return valid_modes[mode_lower]
