"""Build tiered prompts for LLM analysis."""

import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class CommitInfo:
    """Information about a single commit."""

    hash: str
    message: str
    has_breaking_marker: bool = False


def sanitize_message(message: str, max_length: int = 500) -> str:
    """Sanitize commit message to prevent prompt injection.

    Args:
        message: Raw commit message
        max_length: Maximum message length

    Returns:
        Sanitized message
    """
    # Remove XML-like tags
    sanitized = re.sub(r"<[^>]+>", "", message)

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."

    return sanitized.strip()


def parse_commit_type(message: str) -> str:
    """Extract conventional commit type from message.

    Args:
        message: Commit message

    Returns:
        Commit type (feat, fix, chore, etc.) or "other"
    """
    # Match conventional commit prefix
    match = re.match(r"^(\w+)(!)?(\(.+?\))?:", message)
    if match:
        return match.group(1).lower()
    return "other"


def has_breaking_change(message: str) -> bool:
    """Check if commit has breaking change marker.

    Args:
        message: Commit message (may include body)

    Returns:
        True if breaking change detected
    """
    # Check for ! after type
    if re.match(r"^\w+!(\(.+?\))?:", message):
        return True

    # Check for BREAKING CHANGE: in body
    if "BREAKING CHANGE:" in message.upper():
        return True

    return False


def get_commits(base_ref: str, head_ref: str = "HEAD") -> List[CommitInfo]:
    """Get commits between two refs.

    Args:
        base_ref: Base reference (tag or commit)
        head_ref: Head reference (default: HEAD)

    Returns:
        List of CommitInfo objects

    Raises:
        RuntimeError: If git command fails
    """
    try:
        # Use %x00 as delimiter for parsing
        result = subprocess.run(
            [
                "git",
                "log",
                f"{base_ref}..{head_ref}",
                "--format=%H%x00%B%x00%x01",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get commits: {e.stderr}") from e

    commits = []
    raw_commits = result.stdout.split("\x01")

    for raw in raw_commits:
        raw = raw.strip()
        if not raw:
            continue

        parts = raw.split("\x00", 2)
        if len(parts) < 2:
            continue

        commit_hash = parts[0].strip()
        message = parts[1].strip() if len(parts) > 1 else ""

        commits.append(
            CommitInfo(
                hash=commit_hash[:8],
                message=sanitize_message(message),
                has_breaking_marker=has_breaking_change(message),
            )
        )

    return commits


def get_file_diff(base_ref: str, head_ref: str, patterns: List[str], max_lines: int = 100) -> str:
    """Get diff for specific file patterns.

    Args:
        base_ref: Base reference
        head_ref: Head reference
        patterns: File patterns to include
        max_lines: Maximum lines of diff to include

    Returns:
        Truncated diff output
    """
    try:
        cmd = ["git", "diff", f"{base_ref}..{head_ref}", "--"]
        cmd.extend(patterns)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return ""

    lines = result.stdout.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"... (truncated, {len(result.stdout.split(chr(10))) - max_lines} more lines)")

    return "\n".join(lines)


def summarize_commits_by_type(commits: List[CommitInfo]) -> str:
    """Summarize commits by type.

    Args:
        commits: List of commits to summarize

    Returns:
        Summary string
    """
    type_counts: dict[str, int] = {}
    for commit in commits:
        commit_type = parse_commit_type(commit.message)
        type_counts[commit_type] = type_counts.get(commit_type, 0) + 1

    parts = [f"{t}: {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])]
    return ", ".join(parts)


def build_prompt(
    commits: List[CommitInfo],
    base_version: str,
    max_commits: int = 50,
    diff_patterns: Optional[List[str]] = None,
    base_ref: str = "",
    head_ref: str = "HEAD",
) -> str:
    """Build tiered prompt for LLM analysis.

    Args:
        commits: All commits to analyze
        base_version: Current version string
        max_commits: Max recent commits to include in full
        diff_patterns: File patterns for diff inclusion
        base_ref: Base git ref for diffs
        head_ref: Head git ref for diffs

    Returns:
        Complete prompt string
    """
    # Tier 1: Metadata summary
    breaking_count = sum(1 for c in commits if c.has_breaking_marker)
    metadata = f"""## Release Analysis for {base_version} -> next

**Commits**: {len(commits)} total
**Explicit BREAKING markers**: {breaking_count}
**Commit types**: {summarize_commits_by_type(commits)}
"""

    # Tier 2: Recent commits
    recent = commits[:max_commits]
    older = commits[max_commits:]

    commit_section = "## Recent Commits\n\n"
    for commit in recent:
        breaking_marker = " [BREAKING]" if commit.has_breaking_marker else ""
        # Get first line of message
        first_line = commit.message.split("\n")[0]
        commit_section += f"- {commit.hash}: {first_line}{breaking_marker}\n"

    if older:
        commit_section += f"\n... and {len(older)} more commits ({summarize_commits_by_type(older)})\n"

    # Tier 3: Key file diffs
    diff_section = ""
    if diff_patterns and base_ref:
        diff = get_file_diff(base_ref, head_ref, diff_patterns)
        if diff:
            diff_section = f"""## Key File Diffs

```diff
{diff}
```
"""

    # System prompt with instructions
    system = """You are a semantic versioning expert. Analyze the commits and determine the appropriate version bump.

## Rules

- **MAJOR**: Only if there is explicit evidence of breaking changes:
  - Commit contains "BREAKING CHANGE:" in body
  - Commit type ends with "!" (e.g., feat!, fix!)
  - API endpoints or fields removed
  - Database columns dropped
- **MINOR**: New features (feat:) or significant enhancements
- **PATCH**: Bug fixes, documentation, internal changes

Be CONSERVATIVE. When in doubt, choose the lower bump.

## Required Response Format

You MUST respond with these XML tags:

<BUMP>major|minor|patch</BUMP>
<REASONING>Brief explanation of why this bump was chosen</REASONING>
<BREAKING_CHANGES>
- Breaking change 1 (if any)
</BREAKING_CHANGES>
<FEATURES>
- New feature 1 (if any)
</FEATURES>
<FIXES>
- Bug fix 1 (if any)
</FIXES>
<CHANGELOG>
## What's Changed

### Breaking Changes (if any)
- Item

### Features (if any)
- Item

### Bug Fixes (if any)
- Item
</CHANGELOG>
"""

    return f"{system}\n\n{metadata}\n{commit_section}\n{diff_section}"
