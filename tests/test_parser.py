"""Tests for parser.py module."""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from parser import extract_tag_content, parse_list_items, validate_bump, parse_response


class TestExtractTagContent:
    """Tests for extract_tag_content function."""

    def test_extract_simple(self):
        """Test extracting simple tag content."""
        response = "<BUMP>minor</BUMP>"
        result = extract_tag_content(response, "BUMP")
        assert result == "minor"

    def test_extract_multiline(self):
        """Test extracting multiline content."""
        response = """<REASONING>
This is a multiline
reasoning section.
</REASONING>"""
        result = extract_tag_content(response, "REASONING")
        assert "multiline" in result
        assert "reasoning section" in result

    def test_extract_case_insensitive(self):
        """Test tag extraction is case insensitive."""
        response = "<bump>patch</BUMP>"
        result = extract_tag_content(response, "BUMP")
        assert result == "patch"

    def test_extract_not_found(self):
        """Test extraction returns None when tag not found."""
        response = "<BUMP>minor</BUMP>"
        result = extract_tag_content(response, "MISSING")
        assert result is None

    def test_extract_with_surrounding_text(self):
        """Test extraction with text before and after tag."""
        response = "Some preamble\n<BUMP>major</BUMP>\nSome epilogue"
        result = extract_tag_content(response, "BUMP")
        assert result == "major"


class TestParseListItems:
    """Tests for parse_list_items function."""

    def test_parse_dash_list(self):
        """Test parsing dash-prefixed list."""
        content = "- item 1\n- item 2\n- item 3"
        result = parse_list_items(content)
        assert result == ["item 1", "item 2", "item 3"]

    def test_parse_asterisk_list(self):
        """Test parsing asterisk-prefixed list."""
        content = "* item 1\n* item 2"
        result = parse_list_items(content)
        assert result == ["item 1", "item 2"]

    def test_parse_mixed_list(self):
        """Test parsing mixed list markers."""
        content = "- item 1\n* item 2\n- item 3"
        result = parse_list_items(content)
        assert result == ["item 1", "item 2", "item 3"]

    def test_parse_with_extra_whitespace(self):
        """Test parsing list with extra whitespace."""
        content = "  - item 1  \n  -   item 2"
        result = parse_list_items(content)
        assert result == ["item 1", "item 2"]

    def test_parse_empty_content(self):
        """Test parsing empty content."""
        result = parse_list_items("")
        assert result == []

    def test_parse_none_content(self):
        """Test parsing None content."""
        result = parse_list_items(None)
        assert result == []

    def test_parse_no_list_items(self):
        """Test parsing text without list items."""
        content = "Just some text\nwithout list markers"
        result = parse_list_items(content)
        assert result == []


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
        with pytest.raises(ValueError):
            validate_bump("")


class TestParseResponse:
    """Tests for parse_response function."""

    def test_parse_full_response(self):
        """Test parsing complete response."""
        response = """
<BUMP>minor</BUMP>
<REASONING>New feature added</REASONING>
<BREAKING_CHANGES>
- Breaking change 1
</BREAKING_CHANGES>
<FEATURES>
- Feature 1
- Feature 2
</FEATURES>
<FIXES>
- Fix 1
</FIXES>
<CHANGELOG>## What's Changed

### Features
- Feature 1
- Feature 2
</CHANGELOG>
"""
        result = parse_response(response)
        assert result.bump == "minor"
        assert result.reasoning == "New feature added"
        assert len(result.breaking_changes) == 1
        assert len(result.features) == 2
        assert len(result.fixes) == 1
        assert "What's Changed" in result.changelog

    def test_parse_minimal_response(self):
        """Test parsing response with only required fields."""
        response = """
<BUMP>patch</BUMP>
<REASONING>Bug fix only</REASONING>
"""
        result = parse_response(response)
        assert result.bump == "patch"
        assert result.reasoning == "Bug fix only"
        assert result.breaking_changes == []
        assert result.features == []
        assert result.fixes == []

    def test_parse_missing_bump(self):
        """Test parsing response without BUMP tag raises error."""
        response = "<REASONING>Something</REASONING>"
        with pytest.raises(ValueError) as exc_info:
            parse_response(response)
        assert "Missing required <BUMP>" in str(exc_info.value)

    def test_parse_missing_reasoning(self):
        """Test parsing response without REASONING tag raises error."""
        response = "<BUMP>minor</BUMP>"
        with pytest.raises(ValueError) as exc_info:
            parse_response(response)
        assert "Missing required <REASONING>" in str(exc_info.value)

    def test_parse_invalid_bump_value(self):
        """Test parsing response with invalid bump value raises error."""
        response = """
<BUMP>huge</BUMP>
<REASONING>Something</REASONING>
"""
        with pytest.raises(ValueError) as exc_info:
            parse_response(response)
        assert "Invalid bump type" in str(exc_info.value)
