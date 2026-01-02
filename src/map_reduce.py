"""Map/Reduce processing for large inputs.

This module handles chunking large inputs and processing them in parallel
to avoid data loss from truncation.

Architecture:
    Input
        ↓
    needs_chunking? ──No──→ Return input unchanged
        │Yes
        ↓
    chunk_with_overlap()
        ↓
    MAP: extract_changes_from_chunk() for each (parallel)
        ↓ (each chunk is sanitized before embedding in prompt)
    REDUCE: reduce_changes() - deduplicate, consolidate, prioritize
        ↓
    FLATTEN: flatten_changes() - determine net state (Phase 0)
        ↓
    List[Change]
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from content_scanner import sanitize_content, validate_response
from flatten import flatten_changes_to_list
from models import Change, ChangeCategory, Importance
from text_splitter import chunk_with_overlap, needs_chunking

# Default thresholds
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_CHUNKING_THRESHOLD = 2000


# Prompts for map/reduce phases
MAP_PROMPT_TEMPLATE = """Extract ALL changes described in this content.

For each change, output ONE LINE in this format:
[category|importance] Title | Description

Categories: breaking, security, feature, improvement, fix, performance, deprecation, infrastructure, docs, other
Importance: high, medium, low

Example:
[feature|high] OAuth 2.0 Support | Added OAuth 2.0 authorization with new authorize endpoint
[fix|medium] Login crash fixed | Resolved application crash on startup due to missing config

IMPORTANT: Extract ALL changes. Do not filter or prioritize.

Content to analyze:
---
{content}
---

<CHANGES>
"""


REDUCE_PROMPT_TEMPLATE = """You have changes extracted from overlapping chunks. Many are DUPLICATES.

Your job: DEDUPLICATE only. Keep distinct changes as separate items.

Rules:
- REMOVE exact duplicates (same change mentioned multiple times)
- KEEP different changes as SEPARATE items (don't merge unrelated items)
- ALL breaking changes (each one separate)
- ALL security changes (each one separate)
- ALL distinct features (don't combine different features into one)
- ALL distinct fixes

Do NOT over-consolidate. "OAuth support" and "Audit Trail" are DIFFERENT features.

Output format - ONE LINE per change:
[category|importance] Title | Description

Changes (with duplicates from overlapping chunks):
{changes_text}

<CHANGES>
"""


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


def _parse_change_line(line: str, index: int) -> Optional[Change]:
    """Parse a single change line in format: [category|importance] Title | Description"""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Parse [category|importance] prefix
    prefix_match = re.match(r"\[(\w+)(?:\|(\w+))?\]\s*(.+)", line)
    if not prefix_match:
        return None

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
        return None

    return Change(
        id=f"change-{index}",
        category=_parse_category(category_str),
        title=title,
        description=description,
        importance=_parse_importance(importance_str),
    )


def _extract_changes_from_response(response: str) -> List[Change]:
    """Extract changes from LLM response with <CHANGES> delimiter."""
    changes = []

    # Try to find content after <CHANGES> tag
    changes_match = re.search(r"<CHANGES>\s*(.*?)(?:</CHANGES>|$)", response, re.DOTALL | re.IGNORECASE)
    if changes_match:
        content = changes_match.group(1)
    else:
        # Fallback: just use the whole response
        content = response

    # Parse each line
    for i, line in enumerate(content.split("\n")):
        change = _parse_change_line(line, i)
        if change:
            changes.append(change)

    return changes


def _changes_to_text(changes: List[Change]) -> str:
    """Convert changes to text format for reduce prompt.

    Titles and descriptions are sanitized to prevent injection in the reduce phase.
    """
    lines = []
    for c in changes:
        # Sanitize content before embedding in reduce prompt
        sanitized_title = sanitize_content(c.title)
        line = f"[{c.category.value}|{c.importance.value}] {sanitized_title}"
        if c.description:
            sanitized_desc = sanitize_content(c.description)
            line += f" | {sanitized_desc}"
        lines.append(line)
    return "\n".join(lines)


def extract_changes_from_chunk(
    chunk: str,
    llm_caller: Callable[[str], str],
) -> List[Change]:
    """Extract changes from a single chunk using LLM.

    The chunk is sanitized before embedding in the prompt to remove
    any potential injection patterns.

    Args:
        chunk: Text chunk to analyze
        llm_caller: Function that calls the LLM and returns response

    Returns:
        List of extracted changes
    """
    # Sanitize content before embedding in prompt
    sanitized_chunk = sanitize_content(chunk)
    prompt = MAP_PROMPT_TEMPLATE.format(content=sanitized_chunk)
    response = llm_caller(prompt)

    # Validate response for injection indicators
    response_issues = validate_response(response)
    if response_issues:
        print(f"Warning: Suspicious patterns in LLM response: {response_issues}")

    return _extract_changes_from_response(response)


def reduce_changes(
    all_changes: List[Change],
    llm_caller: Callable[[str], str],
) -> List[Change]:
    """Reduce/consolidate changes from multiple chunks.

    Args:
        all_changes: All changes extracted from all chunks
        llm_caller: Function that calls the LLM and returns response

    Returns:
        Deduplicated, consolidated list of changes
    """
    if not all_changes:
        return []

    # If few changes, no need to reduce
    if len(all_changes) <= 5:
        return all_changes

    changes_text = _changes_to_text(all_changes)
    prompt = REDUCE_PROMPT_TEMPLATE.format(changes_text=changes_text)
    response = llm_caller(prompt)

    # Validate response for injection indicators
    response_issues = validate_response(response)
    if response_issues:
        print(f"Warning: Suspicious patterns in reduce response: {response_issues}")

    reduced = _extract_changes_from_response(response)

    # Fallback: if reduce failed to parse, use original changes sorted by importance
    if not reduced and all_changes:
        print(f"Warning: Reduce phase failed to parse, using {len(all_changes)} original changes")
        # Sort by importance (high first) and category priority (breaking > security > feature)
        priority = {
            ChangeCategory.BREAKING: 0,
            ChangeCategory.SECURITY: 1,
            ChangeCategory.FEATURE: 2,
            ChangeCategory.FIX: 3,
        }
        imp_priority = {Importance.HIGH: 0, Importance.MEDIUM: 1, Importance.LOW: 2}
        sorted_changes = sorted(
            all_changes,
            key=lambda c: (imp_priority.get(c.importance, 2), priority.get(c.category, 10))
        )
        return sorted_changes

    return reduced


def process_large_input(
    content: str,
    llm_caller: Callable[[str], str],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_workers: int = 5,
    reduce_llm_caller: Optional[Callable[[str], str]] = None,
) -> List[Change]:
    """Process large input using map/reduce pattern.

    If input is small enough, returns empty list (caller should use normal path).
    If input is large, chunks it, extracts changes from each chunk in parallel,
    then reduces/consolidates the results.

    Args:
        content: Input content to process
        llm_caller: Function that calls the LLM and returns response (for map phase)
        chunk_size: Maximum size of each chunk
        chunk_overlap: Overlap between chunks
        max_workers: Maximum parallel workers for map phase
        reduce_llm_caller: Optional separate LLM caller for reduce phase (higher token limit)

    Returns:
        List of extracted and consolidated changes
    """
    # Check if chunking is needed
    if not needs_chunking(content, threshold=chunk_size):
        return []  # Signal to use normal processing

    # Chunk the content
    chunks = chunk_with_overlap(content, chunk_size, chunk_overlap)

    if len(chunks) <= 1:
        return []  # Single chunk, use normal processing

    # Map phase: extract changes from each chunk in parallel
    all_changes: List[Change] = []
    change_id_counter = 1

    with ThreadPoolExecutor(max_workers=min(len(chunks), max_workers)) as executor:
        future_to_chunk = {
            executor.submit(extract_changes_from_chunk, chunk, llm_caller): i
            for i, chunk in enumerate(chunks)
        }

        for future in as_completed(future_to_chunk):
            chunk_idx = future_to_chunk[future]
            try:
                chunk_changes = future.result()
                # Assign unique IDs
                for change in chunk_changes:
                    change.id = f"change-{change_id_counter}"
                    change_id_counter += 1
                all_changes.extend(chunk_changes)
            except Exception as e:
                # Log but don't fail - we may still get useful data from other chunks
                print(f"Warning: Failed to extract changes from chunk {chunk_idx}: {e}")

    if not all_changes:
        return []

    # Reduce phase: consolidate all changes (use separate caller if provided for higher token limit)
    reducer = reduce_llm_caller if reduce_llm_caller else llm_caller
    reduced_changes = reduce_changes(all_changes, reducer)

    if not reduced_changes:
        return []

    # Phase 0: Flatten to net state
    # Convert reduced changes to text for flatten
    print("Phase 0: Flattening to net state...")
    changes_text = _changes_to_text(reduced_changes)
    flattened_changes = flatten_changes_to_list(changes_text, reducer)

    # Use flattened if we got results, otherwise fall back to reduced
    if flattened_changes:
        print(f"Flattened {len(reduced_changes)} changes to {len(flattened_changes)} net changes")
        final_changes = flattened_changes
    else:
        print("Flatten returned empty, using reduced changes")
        final_changes = reduced_changes

    # Re-assign final IDs
    for i, change in enumerate(final_changes, 1):
        change.id = f"change-{i}"

    return final_changes


def determine_version_from_changes(changes: List[Change]) -> str:
    """Determine version bump from extracted changes.

    Logic:
    - Any breaking change → major
    - Any feature (no breaking) → minor
    - Otherwise → patch

    Args:
        changes: List of changes

    Returns:
        Version bump type: "major", "minor", or "patch"
    """
    has_breaking = any(c.category == ChangeCategory.BREAKING for c in changes)
    has_feature = any(c.category == ChangeCategory.FEATURE for c in changes)

    if has_breaking:
        return "major"
    elif has_feature:
        return "minor"
    else:
        return "patch"
