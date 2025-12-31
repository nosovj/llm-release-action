"""Tests for analyzer.py module (XML delimiter parsing)."""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analyzer import (
    extract_tag_content,
    parse_breaking_change,
    parse_change_line,
    parse_changes_section,
    parse_phase1_response,
    validate_bump,
    group_related_changes,
    _word_tokenize,
    _calculate_title_similarity,
)
from models import ChangeCategory, Importance, Change, BreakingInfo


class TestValidateBump:
    """Tests for validate_bump function."""

    def test_valid_major(self):
        """Test validating major bump."""
        assert validate_bump("major") == "major"
        assert validate_bump("MAJOR") == "major"
        assert validate_bump("Major") == "major"

    def test_valid_minor(self):
        """Test validating minor bump."""
        assert validate_bump("minor") == "minor"
        assert validate_bump("MINOR") == "minor"

    def test_valid_patch(self):
        """Test validating patch bump."""
        assert validate_bump("patch") == "patch"
        assert validate_bump("PATCH") == "patch"

    def test_with_whitespace(self):
        """Test validation with surrounding whitespace."""
        assert validate_bump("  minor  ") == "minor"

    def test_invalid_bump(self):
        """Test invalid bump raises error."""
        with pytest.raises(ValueError) as exc_info:
            validate_bump("invalid")
        assert "Invalid bump type" in str(exc_info.value)

    def test_empty_bump(self):
        """Test empty bump raises error."""
        with pytest.raises(ValueError) as exc_info:
            validate_bump("")
        assert "cannot be empty" in str(exc_info.value)


class TestExtractTagContent:
    """Tests for extract_tag_content function."""

    def test_extract_simple_tag(self):
        """Test extracting simple tag content."""
        response = "<BUMP>minor</BUMP>"
        result = extract_tag_content(response, "BUMP")
        assert result == "minor"

    def test_extract_multiline_content(self):
        """Test extracting multiline content."""
        response = """<REASONING>
This is a detailed explanation
spanning multiple lines.
</REASONING>"""
        result = extract_tag_content(response, "REASONING")
        assert "detailed explanation" in result
        assert "multiple lines" in result

    def test_extract_case_insensitive(self):
        """Test case insensitive tag matching."""
        response = "<bump>patch</bump>"
        result = extract_tag_content(response, "BUMP")
        assert result == "patch"

    def test_extract_with_surrounding_text(self):
        """Test extracting when there's surrounding text."""
        response = """
Here is my analysis:

<BUMP>minor</BUMP>

<REASONING>New features added</REASONING>

That's the result.
"""
        bump = extract_tag_content(response, "BUMP")
        reasoning = extract_tag_content(response, "REASONING")
        assert bump == "minor"
        assert reasoning == "New features added"

    def test_extract_missing_tag(self):
        """Test missing tag returns None."""
        response = "<BUMP>minor</BUMP>"
        result = extract_tag_content(response, "MISSING")
        assert result is None

    def test_extract_empty_tag(self):
        """Test empty tag content."""
        response = "<BUMP></BUMP>"
        result = extract_tag_content(response, "BUMP")
        assert result == ""


class TestParseBreakingChange:
    """Tests for parse_breaking_change function."""

    def test_parse_with_severity(self):
        """Test parsing breaking change with severity tag."""
        line = "- [severity:high] Removed legacy API endpoint"
        result = parse_breaking_change(line)
        assert result is not None
        assert result.severity == "high"
        assert "legacy API" in result.affected

    def test_parse_without_severity(self):
        """Test parsing breaking change without severity defaults to high."""
        line = "- Removed old configuration format"
        result = parse_breaking_change(line)
        assert result is not None
        assert result.severity == "high"  # default
        assert "configuration" in result.affected

    def test_parse_empty_line(self):
        """Test parsing empty line returns None."""
        result = parse_breaking_change("- ")
        assert result is None


class TestParseChangeLine:
    """Tests for parse_change_line function."""

    def test_parse_simple_change(self):
        """Test parsing simple change line."""
        line = "[feature] Add dark mode | New theme toggle in settings"
        result = parse_change_line(line, 0)
        assert result is not None
        assert result.category == ChangeCategory.FEATURE
        assert result.title == "Add dark mode"
        assert "theme toggle" in result.description

    def test_parse_with_importance(self):
        """Test parsing change with importance."""
        line = "[fix|high] Critical security patch | Fixed SQL injection"
        result = parse_change_line(line, 0)
        assert result is not None
        assert result.category == ChangeCategory.FIX
        assert result.importance == Importance.HIGH

    def test_parse_with_commits(self):
        """Test parsing change with commits."""
        line = "[feature|medium] New API | RESTful endpoints | commits:abc1234,def5678"
        result = parse_change_line(line, 0)
        assert result is not None
        assert result.commits == ["abc1234", "def5678"]

    def test_parse_breaking_change(self):
        """Test parsing breaking change with migration."""
        line = "[breaking|high] Remove v1 API | Old endpoints gone | breaking:high | affected:API users | migration:Use v2;Update headers"
        result = parse_change_line(line, 0)
        assert result is not None
        assert result.category == ChangeCategory.BREAKING
        assert result.breaking is not None
        assert result.breaking.severity == "high"
        assert "API users" in result.breaking.affected
        assert "Use v2" in result.breaking.migration

    def test_parse_summary_line_returns_none(self):
        """Test summary line is skipped."""
        line = "[summary] 15 minor fixes and documentation updates"
        result = parse_change_line(line, 0)
        assert result is None

    def test_parse_all_categories(self):
        """Test parsing all valid categories."""
        categories = [
            ("breaking", ChangeCategory.BREAKING),
            ("security", ChangeCategory.SECURITY),
            ("feature", ChangeCategory.FEATURE),
            ("improvement", ChangeCategory.IMPROVEMENT),
            ("fix", ChangeCategory.FIX),
            ("performance", ChangeCategory.PERFORMANCE),
            ("deprecation", ChangeCategory.DEPRECATION),
            ("infrastructure", ChangeCategory.INFRASTRUCTURE),
            ("docs", ChangeCategory.DOCUMENTATION),
            ("other", ChangeCategory.OTHER),
        ]
        for cat_str, cat_enum in categories:
            line = f"[{cat_str}] Test change | Description"
            result = parse_change_line(line, 0)
            assert result is not None
            assert result.category == cat_enum


class TestParseChangesSection:
    """Tests for parse_changes_section function."""

    def test_parse_multiple_changes(self):
        """Test parsing multiple changes."""
        content = """[feature|high] New login flow | OAuth2 support | commits:abc123
[fix|medium] Memory leak | Fixed cache cleanup
[docs|low] Update README | Added examples"""

        changes = parse_changes_section(content)
        assert len(changes) == 3
        assert changes[0].category == ChangeCategory.FEATURE
        assert changes[1].category == ChangeCategory.FIX
        assert changes[2].category == ChangeCategory.DOCUMENTATION

    def test_parse_with_summary(self):
        """Test parsing section with summary line (ignored)."""
        content = """[feature] Main feature | Important new capability
[summary] 10 minor bug fixes not listed"""

        changes = parse_changes_section(content)
        assert len(changes) == 1  # Summary line skipped

    def test_parse_empty_content(self):
        """Test parsing empty content."""
        changes = parse_changes_section("")
        assert changes == []


class TestParsePhase1Response:
    """Tests for parse_phase1_response function (XML format)."""

    def test_parse_complete_response(self):
        """Test parsing complete Phase 1 response with XML tags."""
        response = """
<BUMP>minor</BUMP>

<REASONING>
Added new features without breaking changes. Two new features and one bug fix.
</REASONING>

<CHANGES>
[feature|high] Dark mode support | Added theme toggle in settings | commits:abc1234
[feature|medium] Export to PDF | New export functionality
[fix|medium] Login timeout | Fixed session expiry issue
</CHANGES>
"""
        result = parse_phase1_response(response)
        assert result.bump == "minor"
        assert "new features" in result.reasoning
        assert len(result.changes) == 3
        assert result.changes[0].title == "Dark mode support"
        assert result.stats is not None
        assert result.stats.features == 2
        assert result.stats.fixes == 1

    def test_parse_with_breaking_changes(self):
        """Test parsing response with breaking changes."""
        response = """
<BUMP>major</BUMP>

<REASONING>Breaking API changes require major version bump.</REASONING>

<CHANGES>
[breaking|high] Remove v1 API | Legacy endpoints removed | breaking:high | affected:v1 users | migration:Use v2 API
</CHANGES>

<BREAKING_CHANGES>
- [severity:high] Removed /v1/users endpoint
  Migration: Use /v2/users instead
</BREAKING_CHANGES>
"""
        result = parse_phase1_response(response)
        assert result.bump == "major"
        assert len(result.changes) >= 1
        # At least one change should have breaking info
        breaking_changes = [c for c in result.changes if c.breaking is not None]
        assert len(breaking_changes) >= 1

    def test_parse_with_changelog(self):
        """Test parsing response with changelog."""
        response = """
<BUMP>patch</BUMP>

<REASONING>Bug fixes only.</REASONING>

<CHANGELOG>
## v1.2.1

### Bug Fixes
- Fixed login timeout issue
- Resolved memory leak in cache
</CHANGELOG>
"""
        result = parse_phase1_response(response)
        assert result.bump == "patch"
        assert "v1.2.1" in result.changelog
        assert "Bug Fixes" in result.changelog

    def test_parse_missing_bump_raises_error(self):
        """Test missing BUMP tag raises error."""
        response = """
<REASONING>Some reasoning</REASONING>
"""
        with pytest.raises(ValueError) as exc_info:
            parse_phase1_response(response)
        assert "BUMP" in str(exc_info.value)

    def test_parse_missing_reasoning_raises_error(self):
        """Test missing REASONING tag raises error."""
        response = """
<BUMP>minor</BUMP>
"""
        with pytest.raises(ValueError) as exc_info:
            parse_phase1_response(response)
        assert "REASONING" in str(exc_info.value)

    def test_parse_invalid_bump_raises_error(self):
        """Test invalid bump value raises error."""
        response = """
<BUMP>huge</BUMP>
<REASONING>Test</REASONING>
"""
        with pytest.raises(ValueError) as exc_info:
            parse_phase1_response(response)
        assert "Invalid bump type" in str(exc_info.value)

    def test_parse_empty_changes(self):
        """Test parsing response with no changes."""
        response = """
<BUMP>patch</BUMP>
<REASONING>Maintenance release with no significant changes.</REASONING>
"""
        result = parse_phase1_response(response)
        assert result.bump == "patch"
        assert result.changes == []
        assert result.stats is None


class TestWordTokenize:
    """Tests for _word_tokenize helper function."""

    def test_tokenize_simple(self):
        """Test simple tokenization."""
        result = _word_tokenize("Add new feature")
        assert "add" in result
        assert "new" in result
        assert "feature" in result

    def test_tokenize_removes_punctuation(self):
        """Test punctuation is removed."""
        result = _word_tokenize("Fix bug: login issue")
        assert "fix" in result
        assert "bug" in result
        assert "login" in result

    def test_tokenize_removes_stop_words(self):
        """Test stop words are removed."""
        result = _word_tokenize("the feature is a new one")
        assert "the" not in result
        assert "is" not in result
        assert "a" not in result
        assert "feature" in result
        assert "new" in result
        assert "one" in result

    def test_tokenize_removes_short_words(self):
        """Test short words are removed."""
        result = _word_tokenize("to do it")
        assert "to" not in result
        assert "do" not in result
        assert "it" not in result


class TestCalculateTitleSimilarity:
    """Tests for _calculate_title_similarity function."""

    def test_identical_titles(self):
        """Test identical titles have similarity 1.0."""
        similarity = _calculate_title_similarity("Add new feature", "Add new feature")
        assert similarity == 1.0

    def test_completely_different_titles(self):
        """Test completely different titles have low similarity."""
        similarity = _calculate_title_similarity("Add login", "Remove cache")
        assert similarity == 0.0

    def test_partial_overlap(self):
        """Test titles with partial overlap."""
        similarity = _calculate_title_similarity(
            "Add dark mode toggle", "Add light mode toggle"
        )
        assert 0.3 < similarity < 0.8  # Some overlap

    def test_empty_title(self):
        """Test empty title returns 0."""
        similarity = _calculate_title_similarity("", "Some title")
        assert similarity == 0.0


class TestGroupRelatedChanges:
    """Tests for group_related_changes function."""

    def test_group_by_pr_number(self):
        """Test changes with same PR number are grouped."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Part 1",
                description="",
                pr_number=123,
            ),
            Change(
                id="2",
                category=ChangeCategory.FEATURE,
                title="Part 2",
                description="",
                pr_number=123,
            ),
            Change(
                id="3",
                category=ChangeCategory.FIX,
                title="Unrelated fix",
                description="",
                pr_number=456,
            ),
        ]
        groups = group_related_changes(changes)
        assert len(groups) == 2
        # One group should have 2 changes (same PR)
        group_sizes = sorted([len(g.changes) for g in groups])
        assert group_sizes == [1, 2]

    def test_group_by_labels(self):
        """Test changes with same labels are grouped."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Feature A",
                description="",
                labels=["ui", "frontend"],
            ),
            Change(
                id="2",
                category=ChangeCategory.IMPROVEMENT,
                title="Improvement B",
                description="",
                labels=["ui", "styling"],
            ),
            Change(
                id="3",
                category=ChangeCategory.FIX,
                title="Backend fix",
                description="",
                labels=["backend"],
            ),
        ]
        groups = group_related_changes(changes)
        assert len(groups) == 2
        # Changes 1 and 2 should be grouped (share "ui" label)
        group_sizes = sorted([len(g.changes) for g in groups])
        assert group_sizes == [1, 2]

    def test_group_by_similar_titles(self):
        """Test changes with similar titles are grouped."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Add dark mode theme",
                description="",
            ),
            Change(
                id="2",
                category=ChangeCategory.FIX,
                title="Fix dark mode theme",
                description="",
            ),
            Change(
                id="3",
                category=ChangeCategory.FEATURE,
                title="Improve search performance",
                description="",
            ),
        ]
        groups = group_related_changes(changes)
        # Changes 1 and 2 should be grouped (similar titles)
        assert len(groups) == 2

    def test_empty_changes(self):
        """Test empty changes list returns empty groups."""
        groups = group_related_changes([])
        assert groups == []

    def test_single_change(self):
        """Test single change returns single group."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Only change",
                description="",
            )
        ]
        groups = group_related_changes(changes)
        assert len(groups) == 1
        assert groups[0].title == "Only change"
        assert len(groups[0].changes) == 1

    def test_no_relations(self):
        """Test unrelated changes each get their own group."""
        changes = [
            Change(
                id="1",
                category=ChangeCategory.FEATURE,
                title="Add login",
                description="",
            ),
            Change(
                id="2",
                category=ChangeCategory.FIX,
                title="Fix cache",
                description="",
            ),
            Change(
                id="3",
                category=ChangeCategory.SECURITY,
                title="Update deps",
                description="",
            ),
        ]
        groups = group_related_changes(changes)
        assert len(groups) == 3
