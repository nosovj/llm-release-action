"""Configuration parsing and validation for changelog generation."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from presets import (
    VALID_OUTPUT_FORMATS,
    VALID_PRESETS,
    VALID_SECTIONS,
    VALID_TONES,
    get_preset,
)


@dataclass
class ValidationConfig:
    """Configuration for output validation."""

    enabled: bool = True
    check_structure: bool = True
    check_not_empty: bool = True
    check_no_placeholders: bool = True
    check_language_match: bool = True
    check_references_changes: bool = True
    min_length: int = 50
    max_length: int = 100000
    on_failure: str = "retry"  # retry, warn, error, fallback
    max_retries: int = 2


@dataclass
class AudienceConfig:
    """Configuration for a single audience."""

    # Base
    name: str
    preset: Optional[str] = None
    languages: List[str] = field(default_factory=lambda: ["en"])

    # Sections
    sections: List[str] = field(
        default_factory=lambda: [
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
        ]
    )

    # Content
    include_commits: bool = False
    include_contributors: bool = False
    include_infrastructure: bool = True
    group_related: bool = True
    benefit_focused: bool = False
    summary_only: bool = False

    # Filtering
    exclude_categories: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    exclude_labels: List[str] = field(default_factory=list)
    exclude_authors: List[str] = field(default_factory=list)
    max_items_per_section: Optional[int] = None

    # Style
    emojis: bool = False
    tone: str = "professional"

    # Breaking changes
    breaking_highlight: bool = True
    breaking_migration: bool = True
    breaking_severity: bool = True

    # Links (base_url auto-derived)
    link_commits: bool = False
    link_prs: bool = False
    link_issues: bool = False

    # Metadata generation
    generate_title: bool = False
    generate_summary: bool = False
    generate_highlights: int = 0

    # Format
    output_format: str = "markdown"

    # Validation
    validation: ValidationConfig = field(default_factory=ValidationConfig)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "AudienceConfig":
        """Create an AudienceConfig from a dictionary, applying preset if specified."""
        # Start with preset defaults if specified
        if "preset" in data:
            preset_name = data["preset"]
            config_dict = get_preset(preset_name)
        else:
            config_dict = {}

        # Override with user-provided values
        for key, value in data.items():
            if key == "validation" and isinstance(value, dict):
                # Handle nested validation config
                config_dict["validation"] = ValidationConfig(**value)
            else:
                config_dict[key] = value

        # Add name
        config_dict["name"] = name

        # Handle validation if it's still a dict
        if "validation" in config_dict and isinstance(config_dict["validation"], dict):
            config_dict["validation"] = ValidationConfig(**config_dict["validation"])

        return cls(**config_dict)


@dataclass
class ChangelogConfig:
    """Root configuration containing all audience configs."""

    audiences: Dict[str, AudienceConfig] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "ChangelogConfig":
        """Parse changelog_config from YAML string.

        Args:
            yaml_str: YAML/JSON string containing audience configurations

        Returns:
            ChangelogConfig with all audience configurations

        Raises:
            ValueError: If the YAML is invalid or malformed
        """
        if not yaml_str or not yaml_str.strip():
            return cls()

        try:
            data = yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid changelog_config YAML: {e}") from e

        if data is None:
            return cls()

        if not isinstance(data, dict):
            raise ValueError("changelog_config must be a YAML/JSON object")

        audiences = {}
        for audience_name, audience_settings in data.items():
            if not isinstance(audience_settings, dict):
                raise ValueError(f"Audience '{audience_name}' must be an object")
            audiences[audience_name] = AudienceConfig.from_dict(audience_name, audience_settings)

        return cls(audiences=audiences)


def validate_audience_name(name: str) -> List[str]:
    """Validate audience name as safe identifier.

    Args:
        name: The audience name to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Must be valid identifier format
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{0,49}$", name):
        errors.append(
            f"Audience name '{name}' must be 1-50 chars, start with letter, "
            "contain only letters, numbers, underscores, hyphens"
        )

    # Block reserved words that could confuse LLM
    reserved = {"system", "user", "assistant", "human", "ai", "prompt", "instruction"}
    if name.lower() in reserved:
        errors.append(f"Audience name '{name}' is reserved")

    return errors


def validate_changelog_config(config: Dict[str, Any]) -> List[str]:
    """Validate changelog_config structure and values.

    Args:
        config: Parsed changelog config dictionary

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    valid_on_failure = {"retry", "warn", "error", "fallback"}

    for audience, settings in config.items():
        # Validate audience name
        name_errors = validate_audience_name(audience)
        errors.extend(name_errors)

        if not isinstance(settings, dict):
            errors.append(f"{audience}: must be an object")
            continue

        # Preset validation
        if preset := settings.get("preset"):
            if preset not in VALID_PRESETS:
                errors.append(f"{audience}: Unknown preset '{preset}'. Valid: {VALID_PRESETS}")

        # Tone validation
        if tone := settings.get("tone"):
            if tone not in VALID_TONES:
                errors.append(f"{audience}: Invalid tone '{tone}'. Valid: {VALID_TONES}")

        # Output format validation
        if output_format := settings.get("output_format"):
            if output_format not in VALID_OUTPUT_FORMATS:
                errors.append(
                    f"{audience}: Invalid output_format '{output_format}'. Valid: {VALID_OUTPUT_FORMATS}"
                )

        # Sections validation
        if sections := settings.get("sections"):
            if not isinstance(sections, list):
                errors.append(f"{audience}: sections must be a list")
            else:
                for section in sections:
                    if section not in VALID_SECTIONS:
                        errors.append(
                            f"{audience}: Unknown section '{section}'. Valid: {VALID_SECTIONS}"
                        )

        # Languages validation is done separately in input_validation.py
        # to use langcodes library

        # Numeric validations
        if highlights := settings.get("generate_highlights"):
            if not isinstance(highlights, int) or highlights < 0:
                errors.append(f"{audience}: generate_highlights must be a non-negative integer")

        if max_items := settings.get("max_items_per_section"):
            if not isinstance(max_items, int) or max_items < 1:
                errors.append(f"{audience}: max_items_per_section must be a positive integer")

        # Validation config
        if validation := settings.get("validation"):
            if isinstance(validation, dict):
                if on_failure := validation.get("on_failure"):
                    if on_failure not in valid_on_failure:
                        errors.append(
                            f"{audience}: Invalid on_failure '{on_failure}'. Valid: {valid_on_failure}"
                        )

    return errors
