"""Phase 0: Flatten changes to net state.

This module determines the NET STATE of changes by analyzing them chronologically:
1. If something was ADDED then later REMOVED/REVERTED → exclude both (net zero)
2. If something was ADDED then IMPROVED → show only final state
3. If changes are RELATED → consolidate into one entry

This ensures Phase 1 sees clean input for accurate version bump calculation.
"""

import re
from typing import Callable, List

from models import Change, ChangeCategory, Importance


FLATTEN_PROMPT = """You are analyzing a sequence of changes to determine the NET STATE.

Go through the changes chronologically and determine what ACTUALLY remains:

1. If something was ADDED then later REMOVED/REVERTED → NET ZERO → exclude both
2. If something was ADDED then IMPROVED → show only FINAL state
3. If changes are RELATED (same feature/area) → consolidate into ONE entry
4. REVERT commits themselves should never appear in output

Think step by step:
- What was added?
- Was it later modified? Show final state.
- Was it later removed/reverted? Exclude entirely.

Input:
{input}

Output format:
<FLATTENED>
[category|importance] Title | Description
...
</FLATTENED>

<REMOVED reason="why excluded">
- Item that was removed/reverted
</REMOVED>
"""


def parse_flattened_response(response: str) -> str:
    """Extract flattened changes from LLM response.

    Args:
        response: Raw LLM response containing <FLATTENED> tags

    Returns:
        Content between <FLATTENED> tags, or full response if tags not found
    """
    match = re.search(r"<FLATTENED>(.*?)</FLATTENED>", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response.strip()


def _parse_category(cat_str: str) -> ChangeCategory:
    """Parse category string to enum."""
    cat_map = {
        "breaking": ChangeCategory.BREAKING,
        "security": ChangeCategory.SECURITY,
        "feature": ChangeCategory.FEATURE,
        "improvement": ChangeCategory.IMPROVEMENT,
        "fix": ChangeCategory.FIX,
        "performance": ChangeCategory.PERFORMANCE,
        "deprecation": ChangeCategory.DEPRECATION,
        "infrastructure": ChangeCategory.INFRASTRUCTURE,
        "docs": ChangeCategory.DOCUMENTATION,
        "documentation": ChangeCategory.DOCUMENTATION,
        "other": ChangeCategory.OTHER,
    }
    return cat_map.get(cat_str.lower(), ChangeCategory.OTHER)


def _parse_importance(imp_str: str) -> Importance:
    """Parse importance string to enum."""
    imp_map = {
        "high": Importance.HIGH,
        "medium": Importance.MEDIUM,
        "low": Importance.LOW,
    }
    return imp_map.get(imp_str.lower(), Importance.MEDIUM)


def parse_flattened_changes(response: str) -> List[Change]:
    """Parse flattened response into Change objects.

    Args:
        response: Raw LLM response

    Returns:
        List of Change objects parsed from the flattened content
    """
    content = parse_flattened_response(response)
    changes = []

    for i, line in enumerate(content.split("\n")):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Parse [category|importance] prefix
        prefix_match = re.match(r"\[(\w+)(?:\|(\w+))?\]\s*(.+)", line)
        if not prefix_match:
            continue

        category_str = prefix_match.group(1).lower()
        importance_str = prefix_match.group(2).lower() if prefix_match.group(2) else "medium"
        rest = prefix_match.group(3)

        # Split title | description
        if "|" in rest:
            parts = rest.split("|", 1)
            title = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ""
        else:
            title = rest.strip()
            description = ""

        if not title:
            continue

        changes.append(Change(
            id=f"change-{i + 1}",
            category=_parse_category(category_str),
            title=title,
            description=description,
            importance=_parse_importance(importance_str),
        ))

    return changes


def flatten_changes(
    input_content: str,
    llm_caller: Callable[[str], str],
) -> str:
    """Flatten input to net state using LLM.

    This is Phase 0 of the changelog pipeline. It analyzes changes chronologically
    to determine what ACTUALLY remains after all events are applied.

    Args:
        input_content: Raw changes (commits formatted as text, or changelog text)
        llm_caller: Function that calls the LLM and returns response

    Returns:
        Flattened changes as formatted string (content between <FLATTENED> tags)
    """
    if not input_content or not input_content.strip():
        return ""

    prompt = FLATTEN_PROMPT.format(input=input_content)
    response = llm_caller(prompt)
    return parse_flattened_response(response)


def flatten_changes_to_list(
    input_content: str,
    llm_caller: Callable[[str], str],
) -> List[Change]:
    """Flatten input to net state and return as Change objects.

    Convenience function that combines flatten_changes with parsing.

    Args:
        input_content: Raw changes (commits or text)
        llm_caller: Function that calls the LLM and returns response

    Returns:
        List of Change objects representing the net state
    """
    if not input_content or not input_content.strip():
        return []

    prompt = FLATTEN_PROMPT.format(input=input_content)
    response = llm_caller(prompt)
    return parse_flattened_changes(response)
