"""Repository URL derivation from environment or git."""

import os
import subprocess
from typing import Optional


def get_repository_url() -> Optional[str]:
    """Derive repository URL from environment or git.

    First tries GITHUB_REPOSITORY environment variable (GitHub Actions).
    Falls back to git remote origin.

    Returns:
        Repository URL (HTTPS format) or None if not found
    """
    # First try GitHub Actions environment
    github_repo = os.environ.get("GITHUB_REPOSITORY")
    github_server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    if github_repo:
        return f"{github_server}/{github_repo}"

    # Fallback to git remote
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip()
        return convert_to_https(url)
    except subprocess.CalledProcessError:
        return None


def convert_to_https(url: str) -> str:
    """Convert SSH URL to HTTPS format.

    Args:
        url: Git URL (SSH or HTTPS)

    Returns:
        HTTPS URL
    """
    # Already HTTPS
    if url.startswith("https://"):
        return url.rstrip(".git")

    # Convert SSH format: git@github.com:owner/repo.git
    if url.startswith("git@"):
        # git@github.com:owner/repo.git -> https://github.com/owner/repo
        url = url.replace(":", "/").replace("git@", "https://")
        return url.rstrip(".git")

    # Other formats - just strip .git
    return url.rstrip(".git")


def get_commit_url(base_url: Optional[str], commit_hash: str) -> Optional[str]:
    """Generate URL for a specific commit.

    Args:
        base_url: Repository base URL
        commit_hash: Commit hash

    Returns:
        Commit URL or None if base_url not available
    """
    if not base_url:
        return None
    return f"{base_url}/commit/{commit_hash}"


def get_pr_url(base_url: Optional[str], pr_number: int) -> Optional[str]:
    """Generate URL for a pull request.

    Args:
        base_url: Repository base URL
        pr_number: PR number

    Returns:
        PR URL or None if base_url not available
    """
    if not base_url:
        return None
    return f"{base_url}/pull/{pr_number}"


def get_issue_url(base_url: Optional[str], issue_number: int) -> Optional[str]:
    """Generate URL for an issue.

    Args:
        base_url: Repository base URL
        issue_number: Issue number

    Returns:
        Issue URL or None if base_url not available
    """
    if not base_url:
        return None
    return f"{base_url}/issues/{issue_number}"
