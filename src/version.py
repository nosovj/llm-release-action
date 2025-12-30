"""Semantic version parsing and manipulation utilities."""

import re
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class SemanticVersion:
    """Represents a semantic version."""

    major: int
    minor: int
    patch: int
    prerelease: Optional[str] = None

    def __str__(self) -> str:
        """Return version string with v prefix."""
        base = f"v{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            return f"{base}-{self.prerelease}"
        return base

    def bump(self, bump_type: str) -> "SemanticVersion":
        """Return a new version with the specified bump applied."""
        if bump_type == "major":
            return SemanticVersion(self.major + 1, 0, 0)
        elif bump_type == "minor":
            return SemanticVersion(self.major, self.minor + 1, 0)
        elif bump_type == "patch":
            if self.prerelease:
                # Bump prerelease suffix
                return self._bump_prerelease()
            return SemanticVersion(self.major, self.minor, self.patch + 1)
        else:
            raise ValueError(f"Invalid bump type: {bump_type}. Must be major, minor, or patch.")

    def _bump_prerelease(self) -> "SemanticVersion":
        """Bump the prerelease version suffix."""
        if not self.prerelease:
            raise ValueError("Cannot bump prerelease on a non-prerelease version")

        # Match pattern like alpha.1, beta.2, rc.3
        match = re.match(r"^(.+)\.(\d+)$", self.prerelease)
        if match:
            prefix = match.group(1)
            number = int(match.group(2))
            new_prerelease = f"{prefix}.{number + 1}"
            return SemanticVersion(self.major, self.minor, self.patch, new_prerelease)

        # No numeric suffix, append .1
        return SemanticVersion(self.major, self.minor, self.patch, f"{self.prerelease}.1")


def parse_version(version_str: str) -> SemanticVersion:
    """Parse a version string into a SemanticVersion object.

    Args:
        version_str: Version string like "v1.2.3" or "1.2.3-alpha.1"

    Returns:
        SemanticVersion object

    Raises:
        ValueError: If the version string is invalid
    """
    # Remove v prefix if present
    version_str = version_str.lstrip("v")

    # Split prerelease suffix
    prerelease = None
    if "-" in version_str:
        version_str, prerelease = version_str.split("-", 1)

    # Parse major.minor.patch
    parts = version_str.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {version_str}. Expected major.minor.patch")

    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])
    except ValueError as e:
        raise ValueError(f"Invalid version numbers in {version_str}: {e}") from e

    if major < 0 or minor < 0 or patch < 0:
        raise ValueError(f"Version numbers cannot be negative: {version_str}")

    return SemanticVersion(major, minor, patch, prerelease)


def detect_latest_tag() -> Optional[str]:
    """Detect the latest semver tag from git.

    Returns:
        The latest semver tag (e.g., "v1.2.3") or None if no tags found
    """
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=-v:refname"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to list git tags: {e.stderr}") from e

    tags = result.stdout.strip().split("\n")
    tags = [t for t in tags if t]  # Remove empty strings

    # Find first valid semver tag
    semver_pattern = re.compile(r"^v?\d+\.\d+\.\d+(-[\w.]+)?$")
    for tag in tags:
        if semver_pattern.match(tag):
            return tag

    return None


def is_shallow_clone() -> bool:
    """Check if the repository is a shallow clone."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() == "true"
    except subprocess.CalledProcessError:
        return False
