"""Jinja2 prompt templates for LLM interactions.

This module provides conditional prompt generation based on configuration.
Templates only include sections relevant to the current request, reducing
token usage and parsing complexity.

Key features:
- Adaptive detail level based on input volume (few commits = detailed, many = summarized)
- Conditional sections (skip changelog if not needed, skip breaking detection if disabled)
- Audience-specific Phase 2 prompts for transformation
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jinja2 import Environment, BaseLoader


# Create Jinja2 environment with no file loading (templates are inline)
_env = Environment(
    loader=BaseLoader(),
    autoescape=False,  # Not HTML, no escaping needed
    trim_blocks=True,
    lstrip_blocks=True,
)

# Thresholds for adaptive detail level
DETAIL_THRESHOLD_FULL = 30      # <= this: full detail on everything
DETAIL_THRESHOLD_MODERATE = 100  # <= this: detail on important, summarize rest


def get_detail_level(commit_count: int) -> str:
    """Determine detail level based on commit count.

    Args:
        commit_count: Number of commits in the release

    Returns:
        One of: 'full', 'moderate', 'minimal'
    """
    if commit_count <= DETAIL_THRESHOLD_FULL:
        return "full"
    elif commit_count <= DETAIL_THRESHOLD_MODERATE:
        return "moderate"
    else:
        return "minimal"


# =============================================================================
# Phase 1: Semantic Analysis Prompt
# =============================================================================

PHASE1_TEMPLATE = _env.from_string("""
You are a semantic versioning expert analyzing changes for a software release.

## Task
Analyze the changes below SEMANTICALLY (conventional commit prefixes are NOT required).
Determine the appropriate version bump and categorize the changes.

## Current Version
{{ base_version }}

## Rules for Version Bump
- **MAJOR**: Breaking changes - be CONSERVATIVE, need EXPLICIT evidence:
  - API endpoints removed or renamed
  - Required parameters added to public APIs
  - Response/return type schema changes
  - Behavior changes that break existing integrations
- **MINOR**: New features or significant enhancements (additive changes)
- **PATCH**: Bug fixes, documentation, internal changes, performance improvements

Be CONSERVATIVE with major bumps. When in doubt, choose the lower bump.
{% if detect_breaking %}

## Detecting Breaking Changes
Look for these signals even WITHOUT explicit "BREAKING CHANGE" markers:
- API endpoints removed, renamed, or changed
- Required parameters added to existing functions/APIs
- Database migrations that drop or rename columns
- Configuration format or environment variable changes
- Removed features, methods, or options
{% endif %}

## Detail Level
{% if detail_level == "full" %}
This is a SMALL release ({{ commit_count }} commits). Provide DETAILED entries for all changes.
Each significant commit should have its own entry with full description.
{% elif detail_level == "moderate" %}
This is a MEDIUM release ({{ commit_count }} commits). Provide:
- DETAILED entries for: breaking changes, security fixes, new features
- SUMMARIZED entries for: bug fixes, improvements (e.g., "Fixed 8 bugs including cache issues and API errors")
- COUNTS ONLY for: documentation, chores, dependencies (e.g., "12 documentation updates")
{% else %}
This is a LARGE release ({{ commit_count }} commits). Focus on HIGH IMPACT only:
- DETAILED entries for: ALL breaking changes with migration steps, security fixes, top 5-10 features
- ONE-LINE summaries for: other features, significant fixes
- COUNTS ONLY for: minor fixes, docs, chores, dependencies (e.g., "47 bug fixes, 23 dependency updates")
{% endif %}

## Input

{{ input_content }}
{% if diff_content %}

## File Diffs

```diff
{{ diff_content }}
```
{% endif %}

## Required Output Format
Use XML-style delimiters. Only include sections that have content.

<BUMP>major|minor|patch</BUMP>

<REASONING>
Brief explanation of why this bump was chosen (1-2 sentences).
</REASONING>

<STATS>
Total commits: {{ commit_count }}
Features: [count]
Fixes: [count]
Breaking: [count]
Other: [count]
</STATS>
{% if detect_breaking %}

<BREAKING_CHANGES>
- [severity:high|medium|low] Description of breaking change
  Migration: Step-by-step migration instructions
</BREAKING_CHANGES>
{% endif %}

<CHANGES>
List changes with this format (one per line):
[category|importance] Title | Description{% if include_commits %} | commits:sha1,sha2{% endif %}

Categories: feature, fix, breaking, security, improvement, performance, deprecation, infrastructure, docs, other
Importance: high, medium, low

{% if detail_level == "full" %}
Include ALL changes with descriptions.
{% elif detail_level == "moderate" %}
Include detailed entries for important changes, summarize the rest.
End with summary line if needed: [summary] 15 minor fixes and 8 documentation updates
{% else %}
Focus on significant changes. End with: [summary] X minor changes not listed
{% endif %}
</CHANGES>
{% if generate_changelog %}

<CHANGELOG>
Write changelog following this EXACT format:

### 🚀 Features
- OAuth Support: Added OAuth 2.0 authorization with new authorize endpoint
- Performance: Improved query speed by 40% through index optimization
- Audit Trail: Added activity tracking page to dashboard

### 🐛 Bug Fixes
- Session Handling: Fixed timeout not redirecting to login page
- Search: Resolved special characters breaking queries

FORMAT RULES:
- Title is SHORT (2-4 words) - names the feature/area, NOT a sentence
- Description explains WHAT changed - adds NEW information, not repetition
- BAD: "Fixed JSON Parsing Errors: Fixed JSON parsing errors" (redundant!)
- GOOD: "JSON Parsing: Fixed errors when response contains markdown blocks"
- NO bold (**), NO multi-line entries
{% if detail_level == "minimal" %}
Keep concise - summarize minor changes, detail only significant ones.
{% endif %}
</CHANGELOG>
{% endif %}

## Guidelines
1. Only include sections that have content (omit empty sections entirely)
2. Group related commits into single logical changes
3. Be specific but concise in descriptions
{% if detect_breaking %}
4. Breaking changes MUST include migration steps
{% endif %}
""".strip())


# =============================================================================
# Phase 2: Changelog Transformation Prompt
# =============================================================================

PHASE2_TEMPLATE = _env.from_string("""
You are transforming a changelog for a specific audience.

## Task
Rewrite the changelog below for the target audience{% if language != "en" %} in {{ language_name }}{% endif %}.

## Target Audience: {{ audience_name }}
{{ audience_description }}

## Tone: {{ tone }}
{{ tone_description }}
{% if language != "en" %}

## Language: {{ language_name }} ({{ language }})
Write ALL content in {{ language_name }}, including section headers.
{% endif %}

## Source Changelog (English, technical)

{{ source_changelog }}

## Transformation Rules
{% if benefit_focused %}
- Focus on USER BENEFITS, not technical implementation
- Answer "what does this mean for me?" for each change
- Avoid jargon and technical terms where possible
{% else %}
- Include relevant technical details
- Reference specific APIs, methods, or configurations changed
{% endif %}
{% if summary_only %}
- Keep it CONCISE: max 5-7 most important items
- Summarize related changes into single entries
{% endif %}
{% if include_breaking and has_breaking_changes %}
- Breaking changes should be prominently displayed with clear migration steps
{% endif %}

## Output Format: {{ output_format }}
{% if output_format == "markdown" %}
Use Markdown formatting with headers (##, ###) for sections.
{% if use_emojis %}Include emojis in section headers.{% endif %}

### REQUIRED FORMAT - Follow this example EXACTLY:

```markdown
## v1.2.0

### 🚀 New Features
- OAuth Support: Added OAuth 2.0 authorization with new authorize endpoint
- Dark Mode: Users can now toggle between light and dark themes
- Export API: New endpoint for bulk data export in CSV and JSON formats

### 🔧 Improvements
- Performance: Improved query speed by 40% through index optimization
- UI Polish: Updated button styles and spacing across dashboard

### 🐛 Bug Fixes
- Session Handling: Fixed timeout not redirecting to login page
- Search: Resolved issue where special characters broke queries
```

FORMAT RULES:
- Title is SHORT (2-4 words) naming the feature/area
- Description explains WHAT changed - must add NEW information
- BAD: "Fixed Login Bug: Fixed login bug" (redundant!)
- GOOD: "Login: Fixed session timeout not redirecting properly"
- NO bold (**), NO multi-line, NO "Description:" labels
{% elif output_format == "html" %}
### REQUIRED FORMAT - Follow this example EXACTLY:

```html
<h2>v1.2.0</h2>

<h3>🚀 New Features</h3>
<ul>
<li>OAuth Support: Added OAuth 2.0 authorization with new authorize endpoint</li>
<li>Dark Mode: Users can now toggle between light and dark themes</li>
</ul>

<h3>🐛 Bug Fixes</h3>
<ul>
<li>Session Handling: Fixed timeout not redirecting to login page</li>
</ul>
```

FORMAT RULES:
- Title is SHORT (2-4 words), description adds NEW information
- Each <li> is ONE LINE, NO nested elements
{% elif output_format == "plain" %}
### REQUIRED FORMAT - Follow this example EXACTLY:

```
v1.2.0

🚀 New Features
• OAuth Support: Added OAuth 2.0 authorization with new authorize endpoint
• Dark Mode: Users can now toggle between light and dark themes

🐛 Bug Fixes
• Session Handling: Fixed timeout not redirecting to login page
```

FORMAT RULES:
- Title is SHORT (2-4 words), description adds NEW information
- Each entry ONE LINE, NO multi-line
{% endif %}

## Guidelines
1. Do NOT invent changes - only include what's in the source
2. Do NOT add explanatory text before/after - output ONLY the changelog
3. Maintain the same version number: {{ version }}
{% if max_items %}
4. Limit to {{ max_items }} most important items per section
{% endif %}
5. MANDATORY: Each bullet point MUST be a SINGLE line. NO multi-line entries. NO "Description:" labels. Format: `- Title: One sentence description`
""".strip())


# =============================================================================
# Template Rendering Functions
# =============================================================================

@dataclass
class Phase1Config:
    """Configuration for Phase 1 prompt generation."""

    base_version: str
    input_content: str
    commit_count: int  # Used for adaptive detail level
    diff_content: Optional[str] = None
    detect_breaking: bool = True
    generate_changelog: bool = True
    include_commits: bool = True
    next_version_placeholder: str = "vX.Y.Z"


@dataclass
class Phase2Config:
    """Configuration for Phase 2 changelog transformation."""

    version: str
    source_changelog: str  # The base changelog from Phase 1
    audience_name: str
    audience_description: str
    tone: str = "professional"
    tone_description: str = "Clear, professional language"
    language: str = "en"
    language_name: str = "English"
    output_format: str = "markdown"
    use_emojis: bool = False
    benefit_focused: bool = False
    summary_only: bool = False
    include_breaking: bool = True
    has_breaking_changes: bool = False
    max_items: Optional[int] = None


# Language name lookup
LANGUAGE_NAMES: Dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
    "zh": "Chinese",
    "pt": "Portuguese",
    "ko": "Korean",
    "it": "Italian",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
}


def get_language_name(code: str) -> str:
    """Get human-readable language name from code.

    Args:
        code: BCP 47 language code (e.g., 'en', 'es', 'zh-TW')

    Returns:
        Human-readable name
    """
    base_code = code.split("-")[0].lower()
    return LANGUAGE_NAMES.get(base_code, code)


def render_phase1_prompt(config: Phase1Config) -> str:
    """Render the Phase 1 semantic analysis prompt.

    The prompt adapts based on commit_count:
    - Small releases (<=DETAIL_THRESHOLD_FULL): Full detail on everything
    - Medium releases (<=DETAIL_THRESHOLD_MODERATE): Detail on important, summarize rest
    - Large releases (>DETAIL_THRESHOLD_MODERATE): Focus on high-impact only

    Args:
        config: Phase 1 configuration

    Returns:
        Rendered prompt string
    """
    detail_level = get_detail_level(config.commit_count)

    return PHASE1_TEMPLATE.render(
        base_version=config.base_version,
        input_content=config.input_content,
        commit_count=config.commit_count,
        detail_level=detail_level,
        diff_content=config.diff_content,
        detect_breaking=config.detect_breaking,
        generate_changelog=config.generate_changelog,
        include_commits=config.include_commits,
        next_version_placeholder=config.next_version_placeholder,
    )


def render_phase2_prompt(config: Phase2Config) -> str:
    """Render the Phase 2 changelog transformation prompt.

    This takes the base changelog from Phase 1 and transforms it
    for a specific audience and language.

    Args:
        config: Phase 2 configuration

    Returns:
        Rendered prompt string
    """
    return PHASE2_TEMPLATE.render(
        version=config.version,
        source_changelog=config.source_changelog,
        audience_name=config.audience_name,
        audience_description=config.audience_description,
        tone=config.tone,
        tone_description=config.tone_description,
        language=config.language,
        language_name=config.language_name,
        output_format=config.output_format,
        use_emojis=config.use_emojis,
        benefit_focused=config.benefit_focused,
        summary_only=config.summary_only,
        include_breaking=config.include_breaking,
        has_breaking_changes=config.has_breaking_changes,
        max_items=config.max_items,
    )
