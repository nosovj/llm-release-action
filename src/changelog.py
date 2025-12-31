"""Phase 2: Generate audience-specific changelogs from structured changes.

This module handles the generation of audience-specific changelogs by:
1. Filtering changes based on audience configuration
2. Building LLM prompts with appropriate context and formatting instructions
3. Parsing LLM responses into structured output

The module uses shared utilities from i18n.py, templates.py, and repo_url.py
for consistent formatting across the codebase.
"""

import re
from typing import Callable, Dict, List, Optional, Tuple

from config import AudienceConfig, ChangelogConfig
from i18n import (
    SECTION_NAMES as I18N_SECTION_NAMES,
    TONE_DESCRIPTIONS,
    get_language_instruction,
    get_section_icon,
    get_section_name,
    get_tone_description,
)
from models import Change, ChangeCategory, ReleaseMetadata
from repo_url import get_commit_url, get_issue_url, get_pr_url
from templates import CATEGORY_TO_SECTION, format_section_header

# Preset descriptions for audience context
PRESET_DESCRIPTIONS: Dict[str, str] = {
    "developer": (
        "Software developers who need technical details, API changes, migration guides, "
        "and commit references to understand the implementation impact."
    ),
    "customer": (
        "End users who care about new features, improvements, and bug fixes that affect "
        "their daily usage. They want to know what's new and how it benefits them."
    ),
    "executive": (
        "Business stakeholders who need a high-level summary of business impact, key "
        "features, and strategic changes without technical details."
    ),
    "marketing": (
        "Marketing teams who need compelling feature announcements and benefits-focused "
        "content for promotional materials."
    ),
    "security": (
        "Security teams who need to assess vulnerabilities, patches, and security-related "
        "changes for compliance and risk management."
    ),
    "ops": (
        "Operations and DevOps teams who need to understand infrastructure changes, "
        "deployment requirements, and operational impacts."
    ),
}

# Section display names (used for prompt building)
SECTION_NAMES: Dict[str, str] = {
    "breaking": "Breaking Changes",
    "security": "Security",
    "features": "New Features",
    "improvements": "Improvements",
    "fixes": "Bug Fixes",
    "performance": "Performance",
    "deprecations": "Deprecations",
    "infrastructure": "Infrastructure",
    "docs": "Documentation",
    "other": "Other",
}


def filter_changes(changes: List[Change], config: AudienceConfig) -> List[Change]:
    """Filter changes based on audience configuration.

    Applies:
    - exclude_categories
    - exclude_patterns (regex match on title/description)
    - exclude_labels
    - exclude_authors
    - max_items_per_section (applied per-section after other filters)

    Args:
        changes: List of changes to filter
        config: Audience configuration with filter settings

    Returns:
        Filtered list of changes
    """
    filtered = []

    # Compile exclude patterns once
    compiled_patterns = []
    for pattern in config.exclude_patterns:
        try:
            compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            # Skip invalid patterns
            continue

    for change in changes:
        # Check category exclusion
        if change.category.value in config.exclude_categories:
            continue

        # Check label exclusion
        if config.exclude_labels and any(
            label in config.exclude_labels for label in change.labels
        ):
            continue

        # Check author exclusion
        if config.exclude_authors and any(
            author in config.exclude_authors for author in change.authors
        ):
            continue

        # Check pattern exclusion (match against title and description)
        pattern_matched = False
        for pattern in compiled_patterns:
            if pattern.search(change.title) or pattern.search(change.description):
                pattern_matched = True
                break
        if pattern_matched:
            continue

        filtered.append(change)

    # Apply max_items_per_section if configured
    if config.max_items_per_section is not None:
        filtered = _apply_max_items_per_section(filtered, config.sections, config.max_items_per_section)

    return filtered


def _apply_max_items_per_section(
    changes: List[Change], sections: List[str], max_items: int
) -> List[Change]:
    """Apply max items per section limit.

    Args:
        changes: List of changes to limit
        sections: List of sections to consider
        max_items: Maximum items per section

    Returns:
        Changes with per-section limits applied
    """
    # Group by section
    by_section: Dict[str, List[Change]] = {}
    for change in changes:
        section = CATEGORY_TO_SECTION.get(change.category, "other")
        if section not in by_section:
            by_section[section] = []
        by_section[section].append(change)

    # Take only max_items from each section, preserving order
    result = []
    for section in sections:
        section_changes = by_section.get(section, [])[:max_items]
        result.extend(section_changes)

    return result


def get_changes_by_section(changes: List[Change], sections: List[str]) -> Dict[str, List[Change]]:
    """Group changes by section in the specified order.

    Args:
        changes: List of changes to group
        sections: List of sections to include (in order)

    Returns:
        Dictionary mapping section names to lists of changes
    """
    result: Dict[str, List[Change]] = {}

    # Initialize sections in order
    for section in sections:
        result[section] = []

    # Group changes
    for change in changes:
        section = CATEGORY_TO_SECTION.get(change.category, "other")
        if section in result:
            result[section].append(change)

    return result


def format_changelog_section(
    section: str,
    changes: List[Change],
    config: AudienceConfig,
    base_url: Optional[str] = None,
) -> str:
    """Format a single section of the changelog.

    This function formats one section (e.g., 'features', 'fixes') with its changes
    according to the audience configuration. It's used internally by prompt builders
    but can also be called directly for custom changelog assembly.

    Args:
        section: The section identifier (e.g., 'breaking', 'features', 'fixes')
        changes: List of changes belonging to this section
        config: Audience configuration for styling and content options
        base_url: Optional base URL for commit/PR/issue links

    Returns:
        Formatted section string including header and all change items.
        Returns empty string if changes list is empty.
    """
    if not changes:
        return ""

    lines = []

    # Get language for section name (default to English for prompt building)
    language = config.languages[0] if config.languages else "en"

    # Add section header
    section_header = format_section_header(
        section=section,
        language=language,
        use_emoji=config.emojis,
        output_format=config.output_format,
    )
    lines.append(section_header)

    # Format each change in the section
    for change in changes:
        formatted_change = _format_change_for_prompt(change, config, base_url)
        lines.append(formatted_change)

    lines.append("")  # Add blank line after section

    return "\n".join(lines)


def _format_change_for_prompt(
    change: Change,
    config: AudienceConfig,
    base_url: Optional[str],
) -> str:
    """Format a single change for inclusion in the prompt.

    Args:
        change: The change to format
        config: Audience configuration
        base_url: Optional base URL for links

    Returns:
        Formatted change string
    """
    lines = [f"- **{change.title}**"]

    if change.description:
        lines.append(f"  Description: {change.description}")

    if config.benefit_focused and change.user_benefit:
        lines.append(f"  User benefit: {change.user_benefit}")

    if not config.benefit_focused and change.technical_detail:
        lines.append(f"  Technical detail: {change.technical_detail}")

    if change.breaking:
        lines.append(
            f"  Breaking: severity={change.breaking.severity}, "
            f"affected={change.breaking.affected}"
        )
        if config.breaking_migration and change.breaking.migration:
            migration_steps = "; ".join(change.breaking.migration)
            lines.append(f"  Migration: {migration_steps}")

    if config.include_commits and change.commits:
        if base_url and config.link_commits:
            commit_links = []
            for commit_sha in change.commits[:3]:
                commit_url = get_commit_url(base_url, commit_sha)
                if commit_url:
                    commit_links.append(f"[{commit_sha[:7]}]({commit_url})")
                else:
                    commit_links.append(commit_sha[:7])
            lines.append(f"  Commits: {', '.join(commit_links)}")
        else:
            lines.append(f"  Commits: {', '.join(c[:7] for c in change.commits[:3])}")

    if config.include_contributors and change.authors:
        lines.append(f"  Authors: {', '.join(change.authors)}")

    if change.pr_number and config.link_prs:
        pr_url = get_pr_url(base_url, change.pr_number)
        if pr_url:
            lines.append(f"  PR: [#{change.pr_number}]({pr_url})")
        else:
            lines.append(f"  PR: #{change.pr_number}")

    if change.issue_numbers and config.link_issues:
        issue_links = []
        for issue_num in change.issue_numbers[:3]:
            issue_url = get_issue_url(base_url, issue_num)
            if issue_url:
                issue_links.append(f"[#{issue_num}]({issue_url})")
            else:
                issue_links.append(f"#{issue_num}")
        lines.append(f"  Issues: {', '.join(issue_links)}")

    return "\n".join(lines)


def build_changelog_prompt(
    changes: List[Change],
    config: AudienceConfig,
    language: str,
    version: str,
    base_url: Optional[str] = None,
) -> str:
    """Build the LLM prompt for Phase 2 changelog generation.

    The prompt describes the audience, lists changes, specifies formatting,
    and requests output in the target language.

    Args:
        changes: Filtered list of changes to include
        config: Audience configuration
        language: Target language code (e.g., "en", "es", "ja")
        version: Version string for the release
        base_url: Optional base URL for commit/PR/issue links

    Returns:
        Complete prompt string for LLM
    """
    # Get audience description
    audience_desc = PRESET_DESCRIPTIONS.get(
        config.preset or "",
        f"Users interested in {config.name} updates who need relevant changelog information."
    )

    # Get tone description
    tone_desc = TONE_DESCRIPTIONS.get(config.tone, TONE_DESCRIPTIONS["professional"])

    # Group changes by section
    changes_by_section = get_changes_by_section(changes, config.sections)

    # Build changes text
    changes_text_parts = []
    for section in config.sections:
        section_changes = changes_by_section.get(section, [])
        if not section_changes:
            continue

        section_name = SECTION_NAMES.get(section, section.title())
        changes_text_parts.append(f"\n### {section_name}")

        for change in section_changes:
            formatted = _format_change_for_prompt(change, config, base_url)
            changes_text_parts.append(formatted)

    changes_text = "\n".join(changes_text_parts)

    # Build format requirements
    format_reqs = []
    format_reqs.append(f"- Use {config.output_format} format")

    if config.emojis:
        format_reqs.append("- Include appropriate emojis for section headers and key items")
    else:
        format_reqs.append("- Do NOT use emojis")

    if config.benefit_focused:
        format_reqs.append("- Focus on user benefits and practical impact rather than technical implementation")
    else:
        format_reqs.append("- Include technical details where relevant")

    if config.summary_only:
        format_reqs.append("- Provide a concise summary rather than detailed bullet points")

    if config.group_related:
        format_reqs.append("- Group related changes together under meaningful headings where appropriate")

    format_reqs.append(f"- Sections to include (in order): {', '.join(config.sections)}")
    format_reqs.append("- Only include sections that have changes")

    format_requirements = "\n".join(format_reqs)

    # Build the prompt
    prompt = f"""You are generating a changelog for version {version}.

## Audience
{audience_desc}

## Tone
{tone_desc}

## Language
Generate ALL content in {language}. All text, including section headers, descriptions, and summaries, must be in {language}. If the original content is in a different language, translate it appropriately.

## Changes to Include
{changes_text}

## Format Requirements
{format_requirements}

## Instructions
1. Generate a well-structured changelog based on the changes provided above
2. Organize changes into the specified sections
3. Write clear, concise descriptions appropriate for the target audience
4. Maintain the tone specified throughout
5. Do not add any changes that are not in the provided list
6. Do not include empty sections

Generate the changelog now:"""

    return prompt


def build_metadata_prompt(
    changes: List[Change],
    config: AudienceConfig,
    language: str,
    version: str,
) -> str:
    """Build prompt for generating release metadata (title, summary, highlights).

    Args:
        changes: List of changes to summarize
        config: Audience configuration
        language: Target language code
        version: Version string

    Returns:
        Prompt string for metadata generation
    """
    # Get audience description
    audience_desc = PRESET_DESCRIPTIONS.get(
        config.preset or "",
        f"Users interested in {config.name} updates."
    )

    # Get tone description
    tone_desc = TONE_DESCRIPTIONS.get(config.tone, TONE_DESCRIPTIONS["professional"])

    # Build a brief summary of changes
    change_summaries = []
    for change in changes[:20]:  # Limit to avoid prompt bloat
        category_label = change.category.value
        change_summaries.append(f"- [{category_label}] {change.title}")

    changes_text = "\n".join(change_summaries)

    # Determine what metadata to generate
    metadata_reqs = []
    if config.generate_title:
        metadata_reqs.append("- **title**: A compelling, concise title for this release (max 80 characters)")
    if config.generate_summary:
        metadata_reqs.append("- **summary**: A 1-2 sentence overview of the most important changes")
    if config.generate_highlights > 0:
        metadata_reqs.append(
            f"- **highlights**: A JSON array of {config.generate_highlights} key highlights "
            "(brief phrases, max 100 chars each)"
        )

    if not metadata_reqs:
        return ""

    metadata_requirements = "\n".join(metadata_reqs)

    prompt = f"""Generate release metadata for version {version}.

## Audience
{audience_desc}

## Tone
{tone_desc}

## Language
Generate ALL content in {language}.

## Changes Summary
{changes_text}

## Required Metadata
Generate the following metadata fields:
{metadata_requirements}

## Output Format
Return ONLY a JSON object with the requested fields. Example format:
```json
{{
  "title": "Release title here",
  "summary": "Brief summary here",
  "highlights": ["Highlight 1", "Highlight 2", "Highlight 3"]
}}
```

Only include fields that were requested above. Generate now:"""

    return prompt


def parse_changelog_response(response: str) -> str:
    """Parse Phase 2 LLM response to extract changelog content.

    Handles potential markdown code blocks or other formatting in the response.

    Args:
        response: Raw LLM response

    Returns:
        Cleaned changelog content
    """
    content = response.strip()

    # Remove markdown code block if present
    if content.startswith("```markdown"):
        content = content[11:]
    elif content.startswith("```md"):
        content = content[5:]
    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def parse_metadata_response(response: str) -> ReleaseMetadata:
    """Parse metadata response into ReleaseMetadata object.

    Args:
        response: Raw LLM response containing JSON

    Returns:
        ReleaseMetadata object with parsed values
    """
    import json

    content = response.strip()

    # Extract JSON from code block if present
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if json_match:
        content = json_match.group(1)
    else:
        # Try to find JSON object directly
        brace_match = re.search(r"\{.*\}", content, re.DOTALL)
        if brace_match:
            content = brace_match.group(0)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Return empty metadata if parsing fails
        return ReleaseMetadata()

    return ReleaseMetadata(
        title=data.get("title"),
        summary=data.get("summary"),
        highlights=data.get("highlights"),
    )


def generate_changelog(
    changes: List[Change],
    config: AudienceConfig,
    version: str,
    language: str,
    base_url: Optional[str] = None,
) -> str:
    """Generate a changelog prompt for a single audience and language.

    This is the main entry point for changelog generation. It filters the changes
    based on the audience configuration, builds an LLM prompt with appropriate
    context, tone, and formatting instructions, and returns the prompt string.

    The caller is responsible for sending the prompt to the LLM and parsing
    the response using `parse_changelog_response()`.

    Args:
        changes: List of all changes from Phase 1 analysis
        config: Audience configuration specifying filtering, tone, format, etc.
        version: Version string for the release (e.g., "v1.2.0")
        language: Target language code (e.g., "en", "es", "ja")
        base_url: Optional repository base URL for commit/PR/issue links

    Returns:
        Complete LLM prompt string for changelog generation.

    Example:
        >>> prompt = generate_changelog(changes, customer_config, "v1.2.0", "en")
        >>> response = llm.call(prompt)
        >>> changelog = parse_changelog_response(response)
    """
    # Filter changes based on audience configuration
    filtered_changes = filter_changes(changes, config)

    # Build and return the prompt
    return build_changelog_prompt(
        changes=filtered_changes,
        config=config,
        language=language,
        version=version,
        base_url=base_url,
    )


def generate_changelogs(
    changes: List[Change],
    changelog_config: ChangelogConfig,
    version: str,
    base_url: Optional[str],
    llm_caller: Callable[[str], str],
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, ReleaseMetadata]]]:
    """Generate changelogs for all audiences and languages.

    Args:
        changes: List of all changes from Phase 1
        changelog_config: Configuration with audience definitions
        version: Version string for the release
        base_url: Optional base URL for links
        llm_caller: Function that takes a prompt and returns LLM response

    Returns:
        Tuple of (changelogs, metadata) where:
        - changelogs: {audience: {language: content}}
        - metadata: {audience: {language: ReleaseMetadata}}
    """
    changelogs: Dict[str, Dict[str, str]] = {}
    metadata: Dict[str, Dict[str, ReleaseMetadata]] = {}

    for audience_name, audience_config in changelog_config.audiences.items():
        changelogs[audience_name] = {}
        metadata[audience_name] = {}

        # Filter changes for this audience
        filtered_changes = filter_changes(changes, audience_config)

        if not filtered_changes:
            # No changes for this audience after filtering
            for language in audience_config.languages:
                changelogs[audience_name][language] = ""
                metadata[audience_name][language] = ReleaseMetadata()
            continue

        for language in audience_config.languages:
            # Generate changelog
            changelog_prompt = build_changelog_prompt(
                changes=filtered_changes,
                config=audience_config,
                language=language,
                version=version,
                base_url=base_url,
            )

            changelog_response = llm_caller(changelog_prompt)
            changelog_content = parse_changelog_response(changelog_response)
            changelogs[audience_name][language] = changelog_content

            # Generate metadata if configured
            needs_metadata = (
                audience_config.generate_title
                or audience_config.generate_summary
                or audience_config.generate_highlights > 0
            )

            if needs_metadata:
                metadata_prompt = build_metadata_prompt(
                    changes=filtered_changes,
                    config=audience_config,
                    language=language,
                    version=version,
                )

                if metadata_prompt:
                    metadata_response = llm_caller(metadata_prompt)
                    metadata[audience_name][language] = parse_metadata_response(metadata_response)
                else:
                    metadata[audience_name][language] = ReleaseMetadata()
            else:
                metadata[audience_name][language] = ReleaseMetadata()

    return changelogs, metadata
