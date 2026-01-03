"""Context file loading for project understanding.

This module loads and processes context files (README, ARCHITECTURE, etc.)
to provide the LLM with project understanding for better version analysis.

Features:
- Gitignore-style pattern matching (via pathspec)
- Negation support (!pattern)
- Depth-first ordering (shallower files first)
- Token budget enforcement (via summarization or truncation)
- Staleness detection (warn when changes affect undocumented areas)
- Default exclusions for common dependency/generated directories
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Set

import pathspec


# Default exclusions for common directories that shouldn't be included in context
# These are always excluded unless explicitly included with a positive pattern
DEFAULT_EXCLUSIONS = [
    # Package managers / dependencies
    "!**/node_modules/**",
    "!**/vendor/**",
    "!**/.pnpm/**",
    "!**/Pods/**",
    "!**/.dart_tool/**",
    "!**/.gradle/**",
    "!**/elm-stuff/**",
    "!**/_build/**",
    "!**/deps/**",
    "!**/.bundle/**",
    "!**/.cargo/**",
    # Version control
    "!**/.git/**",
    # Python
    "!**/__pycache__/**",
    "!**/.pytest_cache/**",
    "!**/.venv/**",
    "!**/venv/**",
    "!**/.tox/**",
    "!**/.mypy_cache/**",
    "!**/.ruff_cache/**",
    "!**/htmlcov/**",
    "!**/*.egg-info/**",
    # Build outputs
    "!**/dist/**",
    "!**/build/**",
    "!**/target/**",
    "!**/out/**",
    # Caches
    "!**/.cache/**",
    "!**/.parcel-cache/**",
    "!**/.turbo/**",
    # Framework-specific
    "!**/.next/**",
    "!**/.nuxt/**",
    "!**/.output/**",
    "!**/.svelte-kit/**",
    "!**/storybook-static/**",
    # Coverage
    "!**/coverage/**",
    "!**/.nyc_output/**",
    # IDE / Editor
    "!**/.idea/**",
    "!**/.vscode/**",
    "!**/.vs/**",
    # Infrastructure / Deploy
    "!**/.terraform/**",
    "!**/.serverless/**",
    "!**/.vercel/**",
    "!**/.netlify/**",
    # Generated docs
    "!**/site/**",
    "!**/_site/**",
    "!**/docs/_build/**",
    # Logs
    "!**/logs/**",
    "!**/.logs/**",
    # Temp
    "!**/tmp/**",
    "!**/temp/**",
    "!**/.tmp/**",
]

from summarizing_map_reduce import SummarizeResult, summarize_context, estimate_tokens, fits_budget


@dataclass
class ContextResult:
    """Result of loading context files."""
    content: str
    files_loaded: List[str]
    was_summarized: bool
    warnings: List[str] = field(default_factory=list)


def parse_patterns(patterns_str: str) -> List[str]:
    """Parse comma-separated patterns string.

    Args:
        patterns_str: Comma-separated gitignore-style patterns.

    Returns:
        List of individual patterns.
    """
    if not patterns_str or not patterns_str.strip():
        return []

    return [p.strip() for p in patterns_str.split(",") if p.strip()]


def find_matching_files(patterns: List[str], root_dir: str = ".") -> List[str]:
    """Find files matching gitignore-style patterns.

    Args:
        patterns: List of gitignore-style patterns (supports negation).
        root_dir: Root directory to search from.

    Returns:
        List of matching file paths, sorted by depth then alphabetically.
    """
    if not patterns:
        return []

    # Separate positive and negative patterns
    positive_patterns = [p for p in patterns if not p.startswith("!")]
    negative_patterns = [p[1:] for p in patterns if p.startswith("!")]

    # Create pathspec for matching
    positive_spec = pathspec.PathSpec.from_lines("gitwildmatch", positive_patterns) if positive_patterns else None
    negative_spec = pathspec.PathSpec.from_lines("gitwildmatch", negative_patterns) if negative_patterns else None

    # Walk directory and find matches
    matches: List[str] = []
    root = Path(root_dir)

    for path in root.rglob("*"):
        if path.is_file():
            # Get relative path for matching
            rel_path = str(path.relative_to(root))

            # Check positive patterns
            if positive_spec and positive_spec.match_file(rel_path):
                # Check negative patterns (exclusions)
                if negative_spec and negative_spec.match_file(rel_path):
                    continue  # Excluded
                matches.append(rel_path)

    # Sort by depth (shallower first), then alphabetically
    def sort_key(path: str) -> tuple:
        depth = path.count("/") + path.count("\\")
        return (depth, path.lower())

    return sorted(matches, key=sort_key)


def read_and_concatenate(
    files: List[str],
    root_dir: str = ".",
    max_tokens: Optional[int] = None,
) -> tuple[str, List[str], List[str]]:
    """Read files and concatenate with headers.

    Args:
        files: List of file paths to read.
        root_dir: Root directory for file paths.
        max_tokens: Optional token limit (for truncation without LLM).

    Returns:
        Tuple of (content, files_loaded, warnings).
    """
    content_parts: List[str] = []
    files_loaded: List[str] = []
    warnings: List[str] = []
    current_tokens = 0

    for file_path in files:
        full_path = os.path.join(root_dir, file_path)

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                file_content = f.read()

            # Check if adding this file would exceed budget (if budget specified)
            file_part = f"# {file_path}\n\n{file_content}\n\n"
            file_tokens = estimate_tokens(file_part)

            if max_tokens and current_tokens + file_tokens > max_tokens:
                warnings.append(f"Skipped {file_path} - would exceed token budget")
                continue

            content_parts.append(file_part)
            files_loaded.append(file_path)
            current_tokens += file_tokens

        except Exception as e:
            warnings.append(f"Failed to read {file_path}: {e}")

    return "".join(content_parts).strip(), files_loaded, warnings


def load_context_files(
    patterns: str,
    max_tokens: int = 800,
    llm_caller: Optional[Callable[[str], str]] = None,
    root_dir: str = ".",
    include_default_exclusions: bool = True,
) -> ContextResult:
    """Load context files matching patterns.

    If content exceeds max_tokens:
    - With llm_caller: Uses map/reduce to summarize
    - Without llm_caller: Truncates with warning

    Args:
        patterns: Comma-separated gitignore-style patterns.
        max_tokens: Maximum tokens in result (default: 800).
        llm_caller: Optional LLM caller for summarization.
        root_dir: Root directory to search from.
        include_default_exclusions: Whether to add default exclusions for
            node_modules, vendor, build directories, etc. (default: True).

    Returns:
        ContextResult with content and metadata.
    """
    warnings: List[str] = []

    # Parse patterns
    pattern_list = parse_patterns(patterns)
    if not pattern_list:
        return ContextResult(
            content="",
            files_loaded=[],
            was_summarized=False,
            warnings=[],
        )

    # Add default exclusions (unless user explicitly disabled them)
    if include_default_exclusions:
        pattern_list = pattern_list + DEFAULT_EXCLUSIONS

    # Find matching files
    matching_files = find_matching_files(pattern_list, root_dir)
    if not matching_files:
        warnings.append(f"No files found matching patterns: {patterns}")
        return ContextResult(
            content="",
            files_loaded=[],
            was_summarized=False,
            warnings=warnings,
        )

    # Read and concatenate files (without token limit first)
    content, files_loaded, read_warnings = read_and_concatenate(matching_files, root_dir)
    warnings.extend(read_warnings)

    if not content:
        return ContextResult(
            content="",
            files_loaded=files_loaded,
            was_summarized=False,
            warnings=warnings,
        )

    # Check if summarization is needed
    if fits_budget(content, max_tokens):
        return ContextResult(
            content=content,
            files_loaded=files_loaded,
            was_summarized=False,
            warnings=warnings,
        )

    # Content exceeds budget - try to summarize
    if llm_caller:
        result = summarize_context(content, max_tokens, llm_caller)
        warnings.extend(result.warnings)
        if result.was_summarized:
            warnings.append(
                f"Context summarized from ~{result.original_tokens} to ~{result.final_tokens} tokens"
            )
        return ContextResult(
            content=result.content,
            files_loaded=files_loaded,
            was_summarized=result.was_summarized,
            warnings=warnings,
        )
    else:
        # No LLM caller - truncate with warning
        max_chars = max_tokens * 4
        truncated = content[:max_chars]
        original_tokens = estimate_tokens(content)
        warnings.append(
            f"Context truncated from ~{original_tokens} to ~{max_tokens} tokens (no LLM for summarization)"
        )
        return ContextResult(
            content=truncated,
            files_loaded=files_loaded,
            was_summarized=False,
            warnings=warnings,
        )


def detect_staleness(
    context: str,
    changed_files: List[str],
) -> List[str]:
    """Detect if context might be stale based on changed files.

    Looks for files/directories in changed_files that aren't mentioned
    in the context content.

    Args:
        context: Context content to check.
        changed_files: List of file paths that changed.

    Returns:
        List of warnings about potentially stale context.
    """
    warnings: List[str] = []

    if not context or not changed_files:
        return warnings

    # Normalize context to lowercase for matching
    context_lower = context.lower()

    # Extract unique directory prefixes from changed files
    undocumented_areas: Set[str] = set()

    for file_path in changed_files:
        # Check if the file or its directory is mentioned in context
        path_parts = file_path.replace("\\", "/").split("/")

        # Check full path
        if file_path.lower() in context_lower:
            continue

        # Check directory names
        found = False
        for part in path_parts[:-1]:  # Skip filename
            if part.lower() in context_lower:
                found = True
                break

        if not found and len(path_parts) > 1:
            # Use the top-level directory as the "area"
            area = path_parts[0]
            if area not in [".", ".."]:
                undocumented_areas.add(area)

    if undocumented_areas:
        areas_str = ", ".join(sorted(undocumented_areas)[:5])
        if len(undocumented_areas) > 5:
            areas_str += f" (+{len(undocumented_areas) - 5} more)"
        warnings.append(
            f"Changes detected in areas not covered by context: {areas_str}. "
            "Consider updating your context files."
        )

    return warnings
