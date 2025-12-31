"""Preset configurations for different audiences."""

from typing import Any, Dict

# All valid sections
VALID_SECTIONS = {
    "breaking",
    "security",
    "features",
    "improvements",
    "fixes",
    "performance",
    "deprecations",
    "infrastructure",
    "docs",
    "other",
}

# All valid presets
VALID_PRESETS = {"developer", "customer", "executive", "marketing", "security", "ops"}

# All valid tones
VALID_TONES = {"formal", "casual", "professional", "excited", "friendly"}

# All valid output formats
VALID_OUTPUT_FORMATS = {"markdown", "html", "json", "plain"}

# Developer preset - full technical changelog
DEVELOPER: Dict[str, Any] = {
    "languages": ["en"],
    "sections": [
        "breaking",
        "security",
        "features",
        "improvements",
        "fixes",
        "performance",
        "infrastructure",
        "deprecations",
    ],
    "include_commits": True,
    "include_contributors": True,
    "include_infrastructure": True,
    "group_related": True,
    "benefit_focused": False,
    "summary_only": False,
    "emojis": False,
    "tone": "professional",
    "breaking_highlight": True,
    "breaking_migration": True,
    "breaking_severity": True,
    "link_commits": True,
    "link_prs": True,
    "link_issues": True,
    "generate_title": False,
    "generate_summary": False,
    "generate_highlights": 0,
    "output_format": "markdown",
}

# Customer preset - user-facing changes
CUSTOMER: Dict[str, Any] = {
    "languages": ["en"],
    "sections": ["breaking", "features", "improvements", "fixes"],
    "include_commits": False,
    "include_contributors": False,
    "include_infrastructure": False,
    "group_related": True,
    "exclude_categories": ["infrastructure", "docs", "other"],
    "benefit_focused": True,
    "summary_only": False,
    "emojis": True,
    "tone": "friendly",
    "breaking_highlight": True,
    "breaking_migration": True,
    "breaking_severity": False,
    "link_commits": False,
    "link_prs": False,
    "link_issues": False,
    "generate_title": True,
    "generate_summary": True,
    "generate_highlights": 3,
    "output_format": "markdown",
}

# Executive preset - business summary
EXECUTIVE: Dict[str, Any] = {
    "languages": ["en"],
    "sections": ["breaking", "features"],
    "include_commits": False,
    "include_contributors": False,
    "include_infrastructure": False,
    "group_related": True,
    "exclude_categories": ["infrastructure", "docs", "performance", "other"],
    "benefit_focused": True,
    "summary_only": True,
    "emojis": False,
    "tone": "formal",
    "max_items_per_section": 5,
    "breaking_highlight": True,
    "breaking_migration": False,
    "breaking_severity": False,
    "link_commits": False,
    "link_prs": False,
    "link_issues": False,
    "generate_title": False,
    "generate_summary": True,
    "generate_highlights": 3,
    "output_format": "markdown",
}

# Marketing preset - promotional copy
MARKETING: Dict[str, Any] = {
    "languages": ["en"],
    "sections": ["features", "improvements"],
    "include_commits": False,
    "include_contributors": False,
    "include_infrastructure": False,
    "group_related": True,
    "exclude_categories": ["fix", "infrastructure", "docs", "other"],
    "benefit_focused": True,
    "summary_only": False,
    "emojis": True,
    "tone": "excited",
    "breaking_highlight": False,
    "breaking_migration": False,
    "breaking_severity": False,
    "link_commits": False,
    "link_prs": False,
    "link_issues": False,
    "generate_title": True,
    "generate_summary": False,
    "generate_highlights": 5,
    "output_format": "markdown",
}

# Security preset - security-focused
SECURITY: Dict[str, Any] = {
    "languages": ["en"],
    "sections": ["security", "breaking", "fixes"],
    "include_commits": True,
    "include_contributors": False,
    "include_infrastructure": False,
    "group_related": False,
    "benefit_focused": False,
    "summary_only": False,
    "emojis": False,
    "tone": "formal",
    "breaking_highlight": True,
    "breaking_migration": True,
    "breaking_severity": True,
    "link_commits": True,
    "link_prs": True,
    "link_issues": True,
    "generate_title": False,
    "generate_summary": True,
    "generate_highlights": 0,
    "output_format": "markdown",
}

# Ops preset - operations-focused
OPS: Dict[str, Any] = {
    "languages": ["en"],
    "sections": ["breaking", "infrastructure", "performance", "security"],
    "include_commits": True,
    "include_contributors": False,
    "include_infrastructure": True,
    "group_related": True,
    "exclude_categories": ["feature", "docs", "other"],
    "benefit_focused": False,
    "summary_only": False,
    "emojis": False,
    "tone": "professional",
    "breaking_highlight": True,
    "breaking_migration": True,
    "breaking_severity": True,
    "link_commits": True,
    "link_prs": True,
    "link_issues": True,
    "generate_title": False,
    "generate_summary": False,
    "generate_highlights": 0,
    "output_format": "markdown",
}

# Preset mapping
PRESETS: Dict[str, Dict[str, Any]] = {
    "developer": DEVELOPER,
    "customer": CUSTOMER,
    "executive": EXECUTIVE,
    "marketing": MARKETING,
    "security": SECURITY,
    "ops": OPS,
}


def get_preset(name: str) -> Dict[str, Any]:
    """Get a preset configuration by name.

    Args:
        name: Preset name (developer, customer, executive, marketing, security, ops)

    Returns:
        Preset configuration dictionary

    Raises:
        ValueError: If preset name is not recognized
    """
    if name not in PRESETS:
        raise ValueError(f"Unknown preset: {name}. Valid presets: {', '.join(PRESETS.keys())}")
    return PRESETS[name].copy()
