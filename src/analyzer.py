"""Parse Phase 1 LLM response (semantic analysis) using XML-style delimiters.

This module parses the structured output from Phase 1 analysis using robust
XML-style delimiters that work reliably across different LLM providers.
"""

import re
from typing import Dict, List, Optional, Tuple

from models import (
    AnalysisResult,
    BreakingInfo,
    Change,
    ChangeCategory,
    ChangeGroup,
    ChangeStats,
    Importance,
)


# Valid bump types
VALID_BUMPS = frozenset({"major", "minor", "patch"})

# Category mapping from string to enum
CATEGORY_MAP = {
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

# Importance mapping from string to enum
IMPORTANCE_MAP = {
    "high": Importance.HIGH,
    "medium": Importance.MEDIUM,
    "low": Importance.LOW,
}


def extract_tag_content(response: str, tag: str) -> Optional[str]:
    """Extract content between XML-style tags.

    Args:
        response: The full LLM response
        tag: The tag name (e.g., "BUMP", "REASONING")

    Returns:
        The content between tags, or None if not found
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def validate_bump(bump: str) -> str:
    """Validate bump is major/minor/patch, return lowercase.

    Args:
        bump: The bump type string from LLM response

    Returns:
        Normalized bump type (lowercase)

    Raises:
        ValueError: If bump is not a valid type
    """
    if not bump:
        raise ValueError("Bump type cannot be empty")

    bump_lower = bump.lower().strip()
    if bump_lower not in VALID_BUMPS:
        raise ValueError(
            f"Invalid bump type: '{bump}'. Must be 'major', 'minor', or 'patch'."
        )
    return bump_lower


def parse_stats(stats_content: str) -> Dict[str, int]:
    """Parse the STATS section.

    Args:
        stats_content: Content from <STATS> tag

    Returns:
        Dictionary with counts
    """
    stats = {}
    for line in stats_content.split("\n"):
        line = line.strip()
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            # Extract number from value (e.g., "[count]" -> skip, "5" -> 5)
            if value.isdigit():
                stats[key] = int(value)
            else:
                # Try to extract number
                match = re.search(r"(\d+)", value)
                if match:
                    stats[key] = int(match.group(1))
    return stats


def parse_breaking_change(line: str) -> Optional[BreakingInfo]:
    """Parse a breaking change line.

    Format: - [severity:high|medium|low] Description
            Migration: steps

    Args:
        line: Line from BREAKING_CHANGES section

    Returns:
        BreakingInfo or None if can't parse
    """
    # Extract severity
    severity_match = re.search(r"\[severity:(\w+)\]", line, re.IGNORECASE)
    severity = severity_match.group(1).lower() if severity_match else "high"

    # Remove the severity tag to get description
    description = re.sub(r"\[severity:\w+\]\s*", "", line).strip()
    description = description.lstrip("- ").strip()

    if not description:
        return None

    return BreakingInfo(
        severity=severity,
        affected=description,
        migration=[],
    )


def parse_change_line(line: str, index: int) -> Optional[Change]:
    """Parse a single change line from the CHANGES section.

    Format: [category|importance] Title | Description | commits:sha1,sha2

    Args:
        line: Single line from CHANGES section
        index: Line index for generating ID

    Returns:
        Change object or None if line is a summary/unparseable
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Check for summary line
    if line.lower().startswith("[summary]"):
        return None

    # Parse [category|importance] prefix
    prefix_match = re.match(r"\[(\w+)(?:\|(\w+))?\]\s*(.+)", line)
    if not prefix_match:
        # Try alternate format: just [category] Title | Description
        alt_match = re.match(r"\[(\w+)\]\s*(.+)", line)
        if alt_match:
            category_str = alt_match.group(1).lower()
            rest = alt_match.group(2)
            importance_str = "medium"
        else:
            return None
    else:
        category_str = prefix_match.group(1).lower()
        importance_str = prefix_match.group(2).lower() if prefix_match.group(2) else "medium"
        rest = prefix_match.group(3)

    # Map category
    category = CATEGORY_MAP.get(category_str, ChangeCategory.OTHER)
    importance = IMPORTANCE_MAP.get(importance_str, Importance.MEDIUM)

    # Parse the rest: Title | Description | key:value pairs
    parts = [p.strip() for p in rest.split("|")]

    title = parts[0] if parts else "Untitled change"
    description = ""
    commits: List[str] = []
    breaking_info: Optional[BreakingInfo] = None

    for part in parts[1:]:
        part = part.strip()
        if part.lower().startswith("commits:"):
            commit_str = part[8:].strip()
            commits = [c.strip() for c in commit_str.split(",") if c.strip()]
        elif part.lower().startswith("importance:"):
            # Already parsed from prefix, but allow override
            imp_str = part[11:].strip().lower()
            if imp_str in IMPORTANCE_MAP:
                importance = IMPORTANCE_MAP[imp_str]
        elif part.lower().startswith("breaking:"):
            severity = part[9:].strip().lower()
            breaking_info = BreakingInfo(severity=severity, affected=title, migration=[])
        elif part.lower().startswith("affected:"):
            if breaking_info:
                breaking_info.affected = part[9:].strip()
        elif part.lower().startswith("migration:"):
            if breaking_info:
                migration_str = part[10:].strip()
                breaking_info.migration = [s.strip() for s in migration_str.split(";") if s.strip()]
        elif not description:
            # First non-key:value part is description
            description = part

    return Change(
        id=f"change-{index}",
        category=category,
        title=title,
        description=description,
        commits=commits,
        authors=[],
        importance=importance,
        breaking=breaking_info,
    )


def parse_changes_section(content: str) -> List[Change]:
    """Parse the CHANGES section into Change objects.

    Args:
        content: Content from <CHANGES> tag

    Returns:
        List of Change objects
    """
    changes = []
    index = 0

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        change = parse_change_line(line, index)
        if change:
            changes.append(change)
            index += 1

    return changes


def parse_breaking_section(content: str, existing_changes: List[Change]) -> List[Change]:
    """Parse BREAKING_CHANGES section and update/add to changes.

    Args:
        content: Content from <BREAKING_CHANGES> tag
        existing_changes: Changes already parsed from CHANGES section

    Returns:
        Updated list of changes with breaking info
    """
    # Create a set of existing breaking change titles for deduplication
    breaking_titles = {
        c.title.lower() for c in existing_changes if c.breaking is not None
    }

    new_changes = []
    current_breaking: Optional[BreakingInfo] = None
    current_description = ""

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check for migration line
        if line.lower().startswith("migration:"):
            if current_breaking:
                migration_str = line[10:].strip()
                current_breaking.migration = [s.strip() for s in migration_str.split(";") if s.strip()]
            continue

        # New breaking change entry
        if line.startswith("-") or line.startswith("*"):
            # Save previous if exists
            if current_breaking and current_description:
                if current_description.lower() not in breaking_titles:
                    new_changes.append(Change(
                        id=f"breaking-{len(new_changes)}",
                        category=ChangeCategory.BREAKING,
                        title=current_description,
                        description="",
                        commits=[],
                        authors=[],
                        importance=Importance.HIGH,
                        breaking=current_breaking,
                    ))

            current_breaking = parse_breaking_change(line)
            current_description = line.lstrip("-* ").strip()
            # Remove severity tag from description
            current_description = re.sub(r"\[severity:\w+\]\s*", "", current_description).strip()

    # Don't forget the last one
    if current_breaking and current_description:
        if current_description.lower() not in breaking_titles:
            new_changes.append(Change(
                id=f"breaking-{len(new_changes)}",
                category=ChangeCategory.BREAKING,
                title=current_description,
                description="",
                commits=[],
                authors=[],
                importance=Importance.HIGH,
                breaking=current_breaking,
            ))

    return existing_changes + new_changes


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
        match = re.match(r"^[-*]\s*(.+)$", line)
        if match:
            items.append(match.group(1).strip())
    return items


def parse_phase1_response(response: str) -> AnalysisResult:
    """Parse Phase 1 LLM response with XML-style delimiters.

    Args:
        response: Raw LLM response with XML tags

    Returns:
        AnalysisResult with bump, reasoning, changes, and stats

    Raises:
        ValueError: If response is invalid or missing required fields
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

    # Extract optional CHANGES section
    changes_content = extract_tag_content(response, "CHANGES")
    changes = parse_changes_section(changes_content) if changes_content else []

    # Extract optional BREAKING_CHANGES section and merge
    breaking_content = extract_tag_content(response, "BREAKING_CHANGES")
    if breaking_content:
        changes = parse_breaking_section(breaking_content, changes)

    # Extract CHANGELOG if present
    changelog = extract_tag_content(response, "CHANGELOG") or ""

    # Build result (stats are calculated automatically in __post_init__)
    return AnalysisResult(
        bump=bump,
        reasoning=reasoning,
        changes=changes,
        changelog=changelog,
    )


# =============================================================================
# Grouping utilities (unchanged from before)
# =============================================================================

def _word_tokenize(text: str) -> set:
    """Simple word tokenization for similarity comparison."""
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    stop_words = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are"}
    return {w for w in words if len(w) > 2 and w not in stop_words}


def _calculate_title_similarity(title1: str, title2: str) -> float:
    """Calculate Jaccard similarity between two titles."""
    words1 = _word_tokenize(title1)
    words2 = _word_tokenize(title2)

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def group_related_changes(changes: List[Change]) -> List[ChangeGroup]:
    """Group related changes by detecting common themes.

    Uses simple heuristics:
    - Same PR number
    - Similar titles (word overlap > 50%)
    - Same labels

    Args:
        changes: List of changes to group

    Returns:
        List of ChangeGroup objects containing related changes
    """
    if not changes:
        return []

    assigned = set()
    groups: List[ChangeGroup] = []

    for i, change in enumerate(changes):
        if i in assigned:
            continue

        group_changes = [change]
        assigned.add(i)

        for j, other in enumerate(changes):
            if j in assigned:
                continue

            is_related = False

            if change.pr_number is not None and change.pr_number == other.pr_number:
                is_related = True

            if not is_related and change.labels and other.labels:
                if set(change.labels) & set(other.labels):
                    is_related = True

            if not is_related:
                if _calculate_title_similarity(change.title, other.title) >= 0.5:
                    is_related = True

            if is_related:
                group_changes.append(other)
                assigned.add(j)

        if len(group_changes) == 1:
            group = ChangeGroup(
                title=change.title,
                description=change.description,
                changes=group_changes,
                category=change.category,
            )
        else:
            common_labels = set(group_changes[0].labels)
            for gc in group_changes[1:]:
                common_labels &= set(gc.labels)

            if common_labels:
                title = f"Related changes: {', '.join(sorted(common_labels))}"
            else:
                category_counts: dict = {}
                for gc in group_changes:
                    cat = gc.category.value
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                most_common = max(category_counts, key=category_counts.get)
                title = f"{most_common.title()} changes ({len(group_changes)} items)"

            descriptions = [gc.description for gc in group_changes if gc.description]
            description = " ".join(descriptions[:3])
            if len(descriptions) > 3:
                description += "..."

            group = ChangeGroup(
                title=title,
                description=description,
                changes=group_changes,
                category=group_changes[0].category,
            )

        groups.append(group)

    return groups
