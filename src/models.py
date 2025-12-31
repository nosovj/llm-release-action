"""Core data models for the multi-audience changelog system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ChangeCategory(Enum):
    """Categories for classifying changes."""

    BREAKING = "breaking"
    SECURITY = "security"
    FEATURE = "feature"
    IMPROVEMENT = "improvement"
    FIX = "fix"
    PERFORMANCE = "performance"
    DEPRECATION = "deprecation"
    INFRASTRUCTURE = "infrastructure"
    DOCUMENTATION = "docs"
    OTHER = "other"


class Importance(Enum):
    """Importance level of a change."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Tone(Enum):
    """Tone options for changelog generation."""

    FORMAL = "formal"
    CASUAL = "casual"
    PROFESSIONAL = "professional"
    EXCITED = "excited"
    FRIENDLY = "friendly"


class OutputFormat(Enum):
    """Output format options."""

    MARKDOWN = "markdown"
    HTML = "html"
    JSON = "json"
    PLAIN = "plain"


@dataclass
class BreakingInfo:
    """Details about a breaking change."""

    severity: str  # high, medium, low
    affected: str  # What is affected
    migration: List[str] = field(default_factory=list)  # Migration steps


@dataclass
class Change:
    """Represents a single change in the changelog."""

    id: str
    category: ChangeCategory
    title: str
    description: str
    commits: List[str] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    importance: Importance = Importance.MEDIUM
    user_benefit: Optional[str] = None
    technical_detail: Optional[str] = None
    breaking: Optional[BreakingInfo] = None
    labels: List[str] = field(default_factory=list)
    source: Optional[str] = None  # Source repo for multi-repo
    pr_number: Optional[int] = None
    issue_numbers: List[int] = field(default_factory=list)


@dataclass
class ChangeGroup:
    """A group of related changes under a common heading."""

    title: str
    description: str
    changes: List[Change] = field(default_factory=list)
    category: Optional[ChangeCategory] = None


@dataclass
class ChangeStats:
    """Statistics about changes in a release."""

    features: int = 0
    fixes: int = 0
    improvements: int = 0
    breaking: int = 0
    security: int = 0
    performance: int = 0
    deprecations: int = 0
    infrastructure: int = 0
    docs: int = 0
    other: int = 0
    contributors: int = 0

    @classmethod
    def from_changes(cls, changes: List[Change]) -> "ChangeStats":
        """Calculate stats from a list of changes."""
        stats = cls()
        authors = set()

        for change in changes:
            if change.category == ChangeCategory.FEATURE:
                stats.features += 1
            elif change.category == ChangeCategory.FIX:
                stats.fixes += 1
            elif change.category == ChangeCategory.IMPROVEMENT:
                stats.improvements += 1
            elif change.category == ChangeCategory.BREAKING:
                stats.breaking += 1
            elif change.category == ChangeCategory.SECURITY:
                stats.security += 1
            elif change.category == ChangeCategory.PERFORMANCE:
                stats.performance += 1
            elif change.category == ChangeCategory.DEPRECATION:
                stats.deprecations += 1
            elif change.category == ChangeCategory.INFRASTRUCTURE:
                stats.infrastructure += 1
            elif change.category == ChangeCategory.DOCUMENTATION:
                stats.docs += 1
            else:
                stats.other += 1

            # Count unique authors
            authors.update(change.authors)

        stats.contributors = len(authors)
        return stats

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "features": self.features,
            "fixes": self.fixes,
            "improvements": self.improvements,
            "breaking": self.breaking,
            "security": self.security,
            "performance": self.performance,
            "deprecations": self.deprecations,
            "infrastructure": self.infrastructure,
            "docs": self.docs,
            "other": self.other,
            "contributors": self.contributors,
        }


@dataclass
class ReleaseMetadata:
    """Metadata for a release (per audience, per language)."""

    title: Optional[str] = None
    summary: Optional[str] = None
    highlights: Optional[List[str]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "title": self.title,
            "summary": self.summary,
            "highlights": self.highlights,
        }


@dataclass
class AnalysisResult:
    """Result of Phase 1 semantic analysis."""

    bump: str  # major, minor, patch
    reasoning: str
    changes: List[Change] = field(default_factory=list)
    stats: Optional[ChangeStats] = None
    changelog: str = ""  # Base changelog generated in Phase 1 (used for Phase 2 transformations)

    def __post_init__(self) -> None:
        """Calculate stats after initialization."""
        if self.stats is None and self.changes:
            self.stats = ChangeStats.from_changes(self.changes)
