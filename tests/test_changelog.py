"""Tests for the changelog generation module."""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from changelog import (
    AUDIENCE_PERSONAS,
    CATEGORY_TO_SECTION,
    SECTION_NAMES,
    TONE_DESCRIPTIONS,
    build_changelog_prompt,
    build_metadata_prompt,
    filter_changes,
    generate_changelogs,
    get_changes_by_section,
    parse_changelog_response,
    parse_metadata_response,
)
from config import AudienceConfig, ChangelogConfig
from models import BreakingInfo, Change, ChangeCategory, Importance, ReleaseMetadata


class TestFilterChanges:
    """Tests for filter_changes function."""

    def test_filter_by_category(self) -> None:
        """Test filtering changes by excluded categories."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="New feature", description=""),
            Change(id="2", category=ChangeCategory.INFRASTRUCTURE, title="Infra change", description=""),
            Change(id="3", category=ChangeCategory.FIX, title="Bug fix", description=""),
        ]

        config = AudienceConfig(name="test", exclude_categories=["infrastructure"])
        result = filter_changes(changes, config)

        assert len(result) == 2
        assert all(c.category != ChangeCategory.INFRASTRUCTURE for c in result)

    def test_filter_by_labels(self) -> None:
        """Test filtering changes by excluded labels."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Public feature", description="", labels=["public"]),
            Change(id="2", category=ChangeCategory.FEATURE, title="Internal feature", description="", labels=["internal"]),
        ]

        config = AudienceConfig(name="test", exclude_labels=["internal"])
        result = filter_changes(changes, config)

        assert len(result) == 1
        assert result[0].id == "1"

    def test_filter_by_authors(self) -> None:
        """Test filtering changes by excluded authors."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature 1", description="", authors=["dev1"]),
            Change(id="2", category=ChangeCategory.FEATURE, title="Feature 2", description="", authors=["bot"]),
        ]

        config = AudienceConfig(name="test", exclude_authors=["bot"])
        result = filter_changes(changes, config)

        assert len(result) == 1
        assert result[0].id == "1"

    def test_filter_by_pattern_title(self) -> None:
        """Test filtering changes by regex pattern matching title."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Add new feature", description=""),
            Change(id="2", category=ChangeCategory.FEATURE, title="[WIP] Work in progress", description=""),
            Change(id="3", category=ChangeCategory.FEATURE, title="Another feature", description=""),
        ]

        config = AudienceConfig(name="test", exclude_patterns=[r"\[WIP\]"])
        result = filter_changes(changes, config)

        assert len(result) == 2
        assert all("[WIP]" not in c.title for c in result)

    def test_filter_by_pattern_description(self) -> None:
        """Test filtering changes by regex pattern matching description."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description="This is experimental"),
            Change(id="2", category=ChangeCategory.FEATURE, title="Feature", description="This is stable"),
        ]

        config = AudienceConfig(name="test", exclude_patterns=[r"experimental"])
        result = filter_changes(changes, config)

        assert len(result) == 1
        assert result[0].id == "2"

    def test_max_items_per_section(self) -> None:
        """Test limiting items per section."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature 1", description=""),
            Change(id="2", category=ChangeCategory.FEATURE, title="Feature 2", description=""),
            Change(id="3", category=ChangeCategory.FEATURE, title="Feature 3", description=""),
            Change(id="4", category=ChangeCategory.FIX, title="Fix 1", description=""),
            Change(id="5", category=ChangeCategory.FIX, title="Fix 2", description=""),
        ]

        config = AudienceConfig(
            name="test",
            sections=["features", "fixes"],
            max_items_per_section=2,
        )
        result = filter_changes(changes, config)

        # Should have 2 features and 2 fixes
        assert len(result) == 4
        feature_count = sum(1 for c in result if c.category == ChangeCategory.FEATURE)
        fix_count = sum(1 for c in result if c.category == ChangeCategory.FIX)
        assert feature_count == 2
        assert fix_count == 2

    def test_invalid_regex_pattern_raises_error(self) -> None:
        """Test that invalid regex patterns raise PatternCompilationError."""
        from input_validation import PatternCompilationError

        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]

        config = AudienceConfig(name="test", exclude_patterns=["[invalid regex"])

        # With ReDoS protection, invalid patterns now raise errors instead of being silently ignored
        with pytest.raises(PatternCompilationError) as exc_info:
            filter_changes(changes, config)

        assert "invalid regex" in str(exc_info.value).lower()

    def test_combined_filters(self) -> None:
        """Test multiple filters applied together."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Good feature",
                description="",
                authors=["dev1"],
                labels=["public"],
            ),
            Change(
                id="2",
                category=ChangeCategory.INFRASTRUCTURE,
                title="Infra",
                description="",
                authors=["dev1"],
                labels=["public"],
            ),
            Change(
                id="3",
                category=ChangeCategory.FEATURE,
                title="Internal feature",
                description="",
                authors=["dev1"],
                labels=["internal"],
            ),
            Change(
                id="4",
                category=ChangeCategory.FEATURE,
                title="Bot feature",
                description="",
                authors=["bot"],
                labels=["public"],
            ),
        ]

        config = AudienceConfig(
            name="test",
            exclude_categories=["infrastructure"],
            exclude_labels=["internal"],
            exclude_authors=["bot"],
        )
        result = filter_changes(changes, config)

        assert len(result) == 1
        assert result[0].id == "1"


class TestGetChangesBySection:
    """Tests for get_changes_by_section function."""

    def test_groups_by_section(self) -> None:
        """Test that changes are grouped into correct sections."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature 1", description=""),
            Change(id="2", category=ChangeCategory.FIX, title="Fix 1", description=""),
            Change(id="3", category=ChangeCategory.FEATURE, title="Feature 2", description=""),
        ]

        result = get_changes_by_section(changes, ["features", "fixes"])

        assert len(result["features"]) == 2
        assert len(result["fixes"]) == 1

    def test_respects_section_order(self) -> None:
        """Test that sections are in specified order."""
        changes = [
            Change(id="1", category=ChangeCategory.FIX, title="Fix", description=""),
            Change(id="2", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]

        result = get_changes_by_section(changes, ["features", "fixes"])
        sections = list(result.keys())

        assert sections == ["features", "fixes"]

    def test_excludes_unlisted_sections(self) -> None:
        """Test that changes in unlisted sections are excluded."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
            Change(id="2", category=ChangeCategory.DOCUMENTATION, title="Docs", description=""),
        ]

        result = get_changes_by_section(changes, ["features"])

        assert "docs" not in result
        assert len(result["features"]) == 1


class TestBuildChangelogPrompt:
    """Tests for build_changelog_prompt function."""

    def test_includes_version(self) -> None:
        """Test that version is included in prompt."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description="Desc"),
        ]
        config = AudienceConfig(name="test", sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.2.0")

        assert "1.2.0" in prompt

    def test_includes_audience_description(self) -> None:
        """Test that preset persona is included."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", preset="developer", sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        # Check for key phrases from the developer persona prompt
        assert "DEVELOPERS" in prompt
        assert "API changes" in prompt

    def test_includes_tone(self) -> None:
        """Test that tone description is included."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", tone="excited", sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        assert TONE_DESCRIPTIONS["excited"] in prompt

    def test_includes_language(self) -> None:
        """Test that target language is included."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", sections=["features"])

        prompt = build_changelog_prompt(changes, config, "es", "1.0.0")

        assert "es" in prompt

    def test_includes_format_requirements(self) -> None:
        """Test that format requirements are included."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", emojis=True, output_format="markdown", sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        assert "markdown" in prompt.lower()
        assert "emoji" in prompt.lower()

    def test_includes_change_details(self) -> None:
        """Test that change details are included."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Add new login",
                description="A new login system",
            ),
        ]
        config = AudienceConfig(name="test", sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        assert "Add new login" in prompt
        assert "A new login system" in prompt

    def test_includes_user_benefit_when_benefit_focused(self) -> None:
        """Test that user benefit is included when benefit_focused is true."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Feature",
                description="",
                user_benefit="Faster login times",
            ),
        ]
        config = AudienceConfig(name="test", benefit_focused=True, sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        assert "Faster login times" in prompt

    def test_includes_technical_detail_when_not_benefit_focused(self) -> None:
        """Test that technical detail is included when not benefit_focused."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Feature",
                description="",
                technical_detail="Uses OAuth 2.0",
            ),
        ]
        config = AudienceConfig(name="test", benefit_focused=False, sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        assert "Uses OAuth 2.0" in prompt

    def test_includes_breaking_info(self) -> None:
        """Test that breaking change info is included."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.BREAKING,
                title="API change",
                description="",
                breaking=BreakingInfo(
                    severity="high",
                    affected="REST API v1",
                    migration=["Update to v2 endpoints"],
                ),
            ),
        ]
        config = AudienceConfig(
            name="test",
            breaking_migration=True,
            sections=["breaking"],
        )

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0")

        assert "high" in prompt
        assert "REST API v1" in prompt
        assert "Update to v2 endpoints" in prompt

    def test_includes_commit_links(self) -> None:
        """Test that commit links are included when configured."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Feature",
                description="",
                commits=["abc1234567890"],
            ),
        ]
        config = AudienceConfig(name="test", include_commits=True, link_commits=True, sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0", base_url="https://github.com/org/repo")

        assert "abc1234" in prompt
        assert "https://github.com/org/repo/commit/abc1234567890" in prompt

    def test_includes_pr_links(self) -> None:
        """Test that PR links are included when configured."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Feature",
                description="",
                pr_number=123,
            ),
        ]
        config = AudienceConfig(name="test", link_prs=True, sections=["features"])

        prompt = build_changelog_prompt(changes, config, "en", "1.0.0", base_url="https://github.com/org/repo")

        assert "#123" in prompt
        assert "https://github.com/org/repo/pull/123" in prompt


class TestBuildMetadataPrompt:
    """Tests for build_metadata_prompt function."""

    def test_returns_empty_if_no_metadata_needed(self) -> None:
        """Test that empty string is returned if no metadata is configured."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(
            name="test",
            generate_title=False,
            generate_summary=False,
            generate_highlights=0,
        )

        prompt = build_metadata_prompt(changes, config, "en", "1.0.0")

        assert prompt == ""

    def test_includes_title_request(self) -> None:
        """Test that title is requested when configured."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", generate_title=True)

        prompt = build_metadata_prompt(changes, config, "en", "1.0.0")

        assert "title" in prompt.lower()

    def test_includes_summary_request(self) -> None:
        """Test that summary is requested when configured."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", generate_summary=True)

        prompt = build_metadata_prompt(changes, config, "en", "1.0.0")

        assert "summary" in prompt.lower()

    def test_includes_highlights_request(self) -> None:
        """Test that highlights are requested when configured."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", generate_highlights=5)

        prompt = build_metadata_prompt(changes, config, "en", "1.0.0")

        assert "highlights" in prompt.lower()
        assert "5" in prompt

    def test_includes_version(self) -> None:
        """Test that version is included."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = AudienceConfig(name="test", generate_summary=True)

        prompt = build_metadata_prompt(changes, config, "en", "2.0.0")

        assert "2.0.0" in prompt


class TestParseChangelogResponse:
    """Tests for parse_changelog_response function."""

    def test_returns_plain_text(self) -> None:
        """Test that plain text is returned as-is."""
        response = "# Changelog\n\n## Features\n- New feature"

        result = parse_changelog_response(response)

        assert result == "# Changelog\n\n## Features\n- New feature"

    def test_removes_markdown_code_block(self) -> None:
        """Test that markdown code blocks are removed."""
        response = "```markdown\n# Changelog\n- Feature\n```"

        result = parse_changelog_response(response)

        assert result == "# Changelog\n- Feature"

    def test_removes_md_code_block(self) -> None:
        """Test that md code blocks are removed."""
        response = "```md\n# Changelog\n```"

        result = parse_changelog_response(response)

        assert result == "# Changelog"

    def test_removes_generic_code_block(self) -> None:
        """Test that generic code blocks are removed."""
        response = "```\n# Changelog\n```"

        result = parse_changelog_response(response)

        assert result == "# Changelog"

    def test_strips_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        response = "  \n\n# Changelog\n\n  "

        result = parse_changelog_response(response)

        assert result == "# Changelog"


class TestParseMetadataResponse:
    """Tests for parse_metadata_response function."""

    def test_parses_json_object(self) -> None:
        """Test that JSON object is parsed correctly."""
        response = '{"title": "Big Release", "summary": "Great changes", "highlights": ["Fast", "Secure"]}'

        result = parse_metadata_response(response)

        assert result.title == "Big Release"
        assert result.summary == "Great changes"
        assert result.highlights == ["Fast", "Secure"]

    def test_extracts_json_from_code_block(self) -> None:
        """Test that JSON is extracted from code block."""
        response = """Here is the metadata:
```json
{"title": "Release", "summary": "Summary"}
```"""

        result = parse_metadata_response(response)

        assert result.title == "Release"
        assert result.summary == "Summary"

    def test_finds_json_in_text(self) -> None:
        """Test that JSON is found in surrounding text."""
        response = 'Based on the changes, here is the metadata: {"title": "Release"} - that should work.'

        result = parse_metadata_response(response)

        assert result.title == "Release"

    def test_returns_empty_on_invalid_json(self) -> None:
        """Test that empty metadata is returned on invalid JSON."""
        response = "This is not JSON at all"

        result = parse_metadata_response(response)

        assert result.title is None
        assert result.summary is None
        assert result.highlights is None

    def test_handles_partial_metadata(self) -> None:
        """Test that partial metadata is handled."""
        response = '{"title": "Only Title"}'

        result = parse_metadata_response(response)

        assert result.title == "Only Title"
        assert result.summary is None
        assert result.highlights is None


class TestGenerateChangelogs:
    """Tests for generate_changelogs function."""

    def test_generates_for_all_audiences(self) -> None:
        """Test that changelogs are generated for all audiences."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = ChangelogConfig(
            audiences={
                "developer": AudienceConfig(name="developer", languages=["en"]),
                "customer": AudienceConfig(name="customer", languages=["en"]),
            }
        )

        def mock_llm(prompt: str) -> str:
            return "# Changelog"

        changelogs, metadata = generate_changelogs(changes, config, "1.0.0", None, mock_llm)

        assert "developer" in changelogs
        assert "customer" in changelogs
        assert "en" in changelogs["developer"]
        assert "en" in changelogs["customer"]

    def test_generates_for_all_languages(self) -> None:
        """Test that changelogs are generated for all languages."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = ChangelogConfig(
            audiences={
                "customer": AudienceConfig(name="customer", languages=["en", "es", "ja"]),
            }
        )

        calls = []

        def mock_llm(prompt: str) -> str:
            calls.append(prompt)
            return "# Changelog"

        changelogs, metadata = generate_changelogs(changes, config, "1.0.0", None, mock_llm)

        assert len(changelogs["customer"]) == 3
        assert "en" in changelogs["customer"]
        assert "es" in changelogs["customer"]
        assert "ja" in changelogs["customer"]

    def test_applies_filters(self) -> None:
        """Test that audience filters are applied."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
            Change(id="2", category=ChangeCategory.INFRASTRUCTURE, title="Infra", description=""),
        ]
        config = ChangelogConfig(
            audiences={
                "customer": AudienceConfig(
                    name="customer",
                    languages=["en"],
                    exclude_categories=["infrastructure"],
                ),
            }
        )

        prompts = []

        def mock_llm(prompt: str) -> str:
            prompts.append(prompt)
            return "# Changelog"

        generate_changelogs(changes, config, "1.0.0", None, mock_llm)

        # Infrastructure change should not be in prompt
        assert "Infra" not in prompts[0]
        assert "Feature" in prompts[0]

    def test_generates_metadata_when_configured(self) -> None:
        """Test that metadata is generated when configured."""
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        config = ChangelogConfig(
            audiences={
                "customer": AudienceConfig(
                    name="customer",
                    languages=["en"],
                    generate_title=True,
                    generate_summary=True,
                    generate_highlights=3,
                ),
            }
        )

        call_count = {"count": 0}

        def mock_llm(prompt: str) -> str:
            call_count["count"] += 1
            if "metadata" in prompt.lower():
                return '{"title": "Release", "summary": "Summary", "highlights": ["A", "B", "C"]}'
            return "# Changelog"

        changelogs, metadata = generate_changelogs(changes, config, "1.0.0", None, mock_llm)

        # Should have 2 calls: changelog + metadata
        assert call_count["count"] == 2
        assert metadata["customer"]["en"].title == "Release"
        assert metadata["customer"]["en"].summary == "Summary"
        assert len(metadata["customer"]["en"].highlights) == 3

    def test_handles_empty_filtered_changes(self) -> None:
        """Test that empty changelogs are returned when all changes filtered."""
        changes = [
            Change(id="1", category=ChangeCategory.INFRASTRUCTURE, title="Infra", description=""),
        ]
        config = ChangelogConfig(
            audiences={
                "customer": AudienceConfig(
                    name="customer",
                    languages=["en"],
                    exclude_categories=["infrastructure"],
                ),
            }
        )

        def mock_llm(prompt: str) -> str:
            raise AssertionError("LLM should not be called for empty changes")

        changelogs, metadata = generate_changelogs(changes, config, "1.0.0", None, mock_llm)

        assert changelogs["customer"]["en"] == ""
        assert metadata["customer"]["en"].title is None


class TestConstants:
    """Tests for module constants."""

    def test_tone_descriptions_complete(self) -> None:
        """Test that all tones have descriptions."""
        from presets import VALID_TONES

        for tone in VALID_TONES:
            assert tone in TONE_DESCRIPTIONS

    def test_preset_personas_complete(self) -> None:
        """Test that all presets have audience personas."""
        from presets import VALID_PRESETS

        for preset in VALID_PRESETS:
            assert preset in AUDIENCE_PERSONAS

    def test_section_names_complete(self) -> None:
        """Test that all sections have display names."""
        from presets import VALID_SECTIONS

        for section in VALID_SECTIONS:
            assert section in SECTION_NAMES

    def test_category_to_section_complete(self) -> None:
        """Test that all categories map to sections."""
        for category in ChangeCategory:
            assert category in CATEGORY_TO_SECTION


class TestEmptyChangesHandling:
    """Tests to prevent hallucination when changes are filtered out."""

    def test_developer_preset_includes_all_category_sections(self) -> None:
        """Ensure developer preset includes sections for all categories.

        This prevents the bug where Phase 1 categorizes changes (e.g., 'docs', 'other')
        but Phase 2 filters them out because the preset doesn't include those sections,
        causing the LLM to hallucinate content.
        """
        from presets import DEVELOPER, VALID_SECTIONS

        developer_sections = set(DEVELOPER["sections"])

        # Developer preset should include all valid sections
        # since it's meant to be a "full technical changelog"
        assert developer_sections == VALID_SECTIONS, (
            f"Developer preset missing sections: {VALID_SECTIONS - developer_sections}"
        )

    def test_empty_changes_produces_empty_prompt_sections(self) -> None:
        """Test that empty changes list produces empty Changes to Include section."""
        config = AudienceConfig(name="test", preset="developer")

        prompt = build_changelog_prompt(
            changes=[],
            config=config,
            language="en",
            version="v1.0.0",
            base_url=None,
        )

        # The "Changes to Include" section should be essentially empty
        start = prompt.find("## Changes to Include")
        end = prompt.find("## Format Requirements")
        changes_section = prompt[start:end].strip()

        # Should only have the header, no actual changes
        lines = [l for l in changes_section.split("\n") if l.strip() and not l.startswith("##")]
        assert len(lines) == 0, f"Expected no changes, got: {lines}"

    def test_filtered_changes_all_excluded_by_sections(self) -> None:
        """Test that changes are filtered out if their sections aren't in preset."""
        # Create changes with categories that map to 'docs' and 'other' sections
        changes = [
            Change(id="1", category=ChangeCategory.DOCUMENTATION, title="Doc change", description=""),
            Change(id="2", category=ChangeCategory.OTHER, title="Other change", description=""),
        ]

        # Use a config that EXCLUDES docs and other sections (like old developer preset)
        config = AudienceConfig(
            name="test",
            sections=["breaking", "features", "fixes"],  # Missing docs and other
        )

        # Get changes by section
        changes_by_section = get_changes_by_section(changes, config.sections)

        # Both changes should be filtered out since their sections aren't included
        total_changes = sum(len(v) for v in changes_by_section.values())
        assert total_changes == 0, (
            "Changes with sections not in config should be filtered out"
        )
