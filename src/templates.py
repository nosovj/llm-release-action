"""Changelog formatting and rendering templates.

This module handles the formatting and rendering of changelogs, including
section headers, change items, and complete changelog documents.
"""

from typing import Dict, List, Optional

from config import AudienceConfig
from i18n import get_section_icon, get_section_name
from models import Change, ChangeCategory

# Default section order for changelog rendering
DEFAULT_SECTION_ORDER: List[str] = [
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

# Mapping from ChangeCategory enum values to section keys
CATEGORY_TO_SECTION: Dict[ChangeCategory, str] = {
    ChangeCategory.BREAKING: "breaking",
    ChangeCategory.SECURITY: "security",
    ChangeCategory.FEATURE: "features",
    ChangeCategory.IMPROVEMENT: "improvements",
    ChangeCategory.FIX: "fixes",
    ChangeCategory.PERFORMANCE: "performance",
    ChangeCategory.DEPRECATION: "deprecations",
    ChangeCategory.INFRASTRUCTURE: "infrastructure",
    ChangeCategory.DOCUMENTATION: "docs",
    ChangeCategory.OTHER: "other",
}


def format_section_header(
    section: str,
    language: str,
    use_emoji: bool,
    output_format: str,
) -> str:
    """Format a section header for the changelog.

    Args:
        section: The section identifier (e.g., 'breaking', 'features')
        language: The target language code (e.g., 'en', 'es')
        use_emoji: Whether to include emoji in the header
        output_format: The output format ('markdown', 'html', 'plain', 'json')

    Returns:
        The formatted section header string.
    """
    section_name = get_section_name(section, language, use_emoji=use_emoji)

    if output_format == "markdown":
        return f"### {section_name}\n"
    elif output_format == "html":
        return f"<h3>{section_name}</h3>\n"
    elif output_format == "plain":
        return f"{section_name}\n{'-' * len(section_name)}\n"
    else:
        # For JSON format, return the section name without formatting
        return section_name


def format_change_item(
    change: Change,
    config: AudienceConfig,
    base_url: Optional[str] = None,
) -> str:
    """Format a single change item for the changelog.

    Args:
        change: The Change object to format
        config: The audience configuration for styling options
        base_url: Optional base URL for linking to commits, PRs, and issues

    Returns:
        The formatted change item string.
    """
    output_format = config.output_format

    # Start with the title/description
    if config.benefit_focused and change.user_benefit:
        text = change.user_benefit
    else:
        text = change.title

    # Add technical detail if available and not summary_only
    if not config.summary_only and change.technical_detail:
        text = f"{text} - {change.technical_detail}"

    # Build links
    links = []

    if base_url:
        # PR link
        if config.link_prs and change.pr_number:
            pr_link = _format_link(f"#{change.pr_number}", f"{base_url}/pull/{change.pr_number}", output_format)
            links.append(pr_link)

        # Issue links
        if config.link_issues and change.issue_numbers:
            for issue_num in change.issue_numbers:
                issue_link = _format_link(f"#{issue_num}", f"{base_url}/issues/{issue_num}", output_format)
                links.append(issue_link)

        # Commit links
        if config.link_commits and change.commits:
            for commit_sha in change.commits[:3]:  # Limit to first 3 commits
                short_sha = commit_sha[:7]
                commit_link = _format_link(short_sha, f"{base_url}/commit/{commit_sha}", output_format)
                links.append(commit_link)

    # Add authors if configured
    author_text = ""
    if config.include_contributors and change.authors:
        authors_formatted = ", ".join(f"@{author}" for author in change.authors)
        author_text = f" ({authors_formatted})"

    # Format the final item
    if output_format == "markdown":
        links_text = f" ({', '.join(links)})" if links else ""
        return f"- {text}{author_text}{links_text}\n"
    elif output_format == "html":
        links_text = f" ({', '.join(links)})" if links else ""
        return f"<li>{text}{author_text}{links_text}</li>\n"
    elif output_format == "plain":
        links_text = f" ({', '.join(links)})" if links else ""
        return f"  * {text}{author_text}{links_text}\n"
    else:
        # JSON format - return just the text for now
        return text


def format_breaking_change(
    change: Change,
    config: AudienceConfig,
) -> str:
    """Format a breaking change with special highlighting and migration info.

    Args:
        change: The Change object representing a breaking change
        config: The audience configuration for styling options

    Returns:
        The formatted breaking change string with optional severity and migration info.
    """
    output_format = config.output_format

    # Start with the basic formatting
    title = change.title
    lines = []

    if output_format == "markdown":
        # Add severity badge if configured
        if config.breaking_severity and change.breaking:
            severity = change.breaking.severity.upper()
            lines.append(f"- **[{severity}]** {title}")
        elif config.breaking_highlight:
            lines.append(f"- **{title}**")
        else:
            lines.append(f"- {title}")

        # Add affected info
        if change.breaking and change.breaking.affected:
            lines.append(f"  - **Affected:** {change.breaking.affected}")

        # Add migration steps if configured
        if config.breaking_migration and change.breaking and change.breaking.migration:
            lines.append("  - **Migration:**")
            for step in change.breaking.migration:
                lines.append(f"    1. {step}")

    elif output_format == "html":
        # HTML format with styling
        severity_class = ""
        if config.breaking_severity and change.breaking:
            severity_class = f' class="severity-{change.breaking.severity}"'

        lines.append(f"<li{severity_class}>")
        lines.append(f"  <strong>{title}</strong>")

        if change.breaking and change.breaking.affected:
            lines.append(f"  <p><strong>Affected:</strong> {change.breaking.affected}</p>")

        if config.breaking_migration and change.breaking and change.breaking.migration:
            lines.append("  <p><strong>Migration:</strong></p>")
            lines.append("  <ol>")
            for step in change.breaking.migration:
                lines.append(f"    <li>{step}</li>")
            lines.append("  </ol>")

        lines.append("</li>")

    elif output_format == "plain":
        # Plain text format
        if config.breaking_severity and change.breaking:
            lines.append(f"  * [{change.breaking.severity.upper()}] {title}")
        else:
            lines.append(f"  * {title}")

        if change.breaking and change.breaking.affected:
            lines.append(f"      Affected: {change.breaking.affected}")

        if config.breaking_migration and change.breaking and change.breaking.migration:
            lines.append("      Migration:")
            for i, step in enumerate(change.breaking.migration, 1):
                lines.append(f"        {i}. {step}")

    else:
        # JSON format - return basic text
        return title

    return "\n".join(lines) + "\n"


def render_changelog(
    changes: List[Change],
    config: AudienceConfig,
    language: str,
    version: str,
    base_url: Optional[str] = None,
) -> str:
    """Render a complete changelog from a list of changes.

    Args:
        changes: List of Change objects to include in the changelog
        config: The audience configuration for styling and filtering
        language: The target language code
        version: The version string for this release
        base_url: Optional base URL for linking to commits, PRs, and issues

    Returns:
        The complete rendered changelog as a string.
    """
    output_format = config.output_format

    # Group changes by section
    sections: Dict[str, List[Change]] = {section: [] for section in DEFAULT_SECTION_ORDER}

    for change in changes:
        section = CATEGORY_TO_SECTION.get(change.category, "other")

        # Skip excluded categories
        if section in config.exclude_categories:
            continue

        # Skip infrastructure if not included
        if section == "infrastructure" and not config.include_infrastructure:
            continue

        # Skip if section is not in configured sections
        if section not in config.sections:
            continue

        sections[section].append(change)

    # Apply max_items_per_section limit if configured
    if config.max_items_per_section:
        for section in sections:
            sections[section] = sections[section][:config.max_items_per_section]

    # Build the changelog
    lines = []

    # Add version header
    use_emoji = config.emojis
    if output_format == "markdown":
        lines.append(f"## {version}\n\n")
    elif output_format == "html":
        lines.append(f"<h2>{version}</h2>\n")
    elif output_format == "plain":
        lines.append(f"{version}\n{'=' * len(version)}\n\n")

    # Render each section in order
    section_order = config.sections if config.sections else DEFAULT_SECTION_ORDER

    for section in section_order:
        section_changes = sections.get(section, [])
        if not section_changes:
            continue

        # Add section header
        header = format_section_header(section, language, use_emoji, output_format)
        lines.append(header)

        if output_format == "html":
            lines.append("<ul>\n")

        # Render each change
        for change in section_changes:
            if section == "breaking":
                item = format_breaking_change(change, config)
            else:
                item = format_change_item(change, config, base_url)
            lines.append(item)

        if output_format == "html":
            lines.append("</ul>\n")

        lines.append("\n")

    # Add contributors section if configured
    if config.include_contributors:
        all_authors = set()
        for change in changes:
            all_authors.update(change.authors)

        if all_authors:
            contributors_header = get_section_name("contributors", language, use_emoji=use_emoji)
            if output_format == "markdown":
                lines.append(f"### {contributors_header}\n")
                for author in sorted(all_authors):
                    lines.append(f"- @{author}\n")
            elif output_format == "html":
                lines.append(f"<h3>{contributors_header}</h3>\n<ul>\n")
                for author in sorted(all_authors):
                    lines.append(f"<li>@{author}</li>\n")
                lines.append("</ul>\n")
            elif output_format == "plain":
                lines.append(f"\n{contributors_header}\n{'-' * len(contributors_header)}\n")
                for author in sorted(all_authors):
                    lines.append(f"  * @{author}\n")

    return "".join(lines)


def _format_link(text: str, url: str, output_format: str) -> str:
    """Format a link based on the output format.

    Args:
        text: The link text
        url: The link URL
        output_format: The output format ('markdown', 'html', 'plain', 'json')

    Returns:
        The formatted link string.
    """
    if output_format == "markdown":
        return f"[{text}]({url})"
    elif output_format == "html":
        return f'<a href="{url}">{text}</a>'
    else:
        # Plain and JSON just show text
        return text
