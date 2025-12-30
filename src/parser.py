"""Parse LLM responses with XML-style delimiters."""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AnalysisResult:
    """Parsed result from LLM analysis."""

    bump: str
    reasoning: str
    breaking_changes: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)
    changelog: str = ""


def extract_tag_content(response: str, tag: str) -> Optional[str]:
    """Extract content between XML-style tags.

    Args:
        response: The full LLM response
        tag: The tag name (e.g., "BUMP")

    Returns:
        The content between tags, or None if not found
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def parse_list_items(content: str) -> List[str]:
    """Parse markdown list items from content.

    Args:
        content: Text containing markdown list items

    Returns:
        List of items (without leading dash/asterisk)
    """
    if not content:
        return []

    items = []
    for line in content.split("\n"):
        line = line.strip()
        # Match lines starting with - or *
        match = re.match(r"^[-*]\s*(.+)$", line)
        if match:
            items.append(match.group(1).strip())
    return items


def validate_bump(bump: str) -> str:
    """Validate bump type is one of major, minor, patch.

    Args:
        bump: The bump type from LLM

    Returns:
        Normalized bump type (lowercase)

    Raises:
        ValueError: If bump is not valid
    """
    bump_lower = bump.lower().strip()
    if bump_lower not in ("major", "minor", "patch"):
        raise ValueError(
            f"Invalid bump type: '{bump}'. Must be exactly 'major', 'minor', or 'patch'."
        )
    return bump_lower


def parse_response(response: str) -> AnalysisResult:
    """Parse the full LLM response into structured result.

    Args:
        response: The raw LLM response text

    Returns:
        AnalysisResult with parsed fields

    Raises:
        ValueError: If required fields are missing or invalid
    """
    # Extract required BUMP tag
    bump_raw = extract_tag_content(response, "BUMP")
    if not bump_raw:
        raise ValueError("Missing required <BUMP> tag in LLM response")

    bump = validate_bump(bump_raw)

    # Extract required REASONING tag
    reasoning = extract_tag_content(response, "REASONING")
    if not reasoning:
        raise ValueError("Missing required <REASONING> tag in LLM response")

    # Extract optional tags
    breaking_changes_raw = extract_tag_content(response, "BREAKING_CHANGES")
    features_raw = extract_tag_content(response, "FEATURES")
    fixes_raw = extract_tag_content(response, "FIXES")
    changelog = extract_tag_content(response, "CHANGELOG") or ""

    return AnalysisResult(
        bump=bump,
        reasoning=reasoning,
        breaking_changes=parse_list_items(breaking_changes_raw) if breaking_changes_raw else [],
        features=parse_list_items(features_raw) if features_raw else [],
        fixes=parse_list_items(fixes_raw) if fixes_raw else [],
        changelog=changelog,
    )
