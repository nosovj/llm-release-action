"""Tests for map_reduce module."""

import pytest
import sys
import os
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from map_reduce import (
    determine_version_from_changes,
    extract_changes_from_chunk,
    reduce_changes,
    process_large_input,
    _extract_changes_from_response,
    _parse_change_line,
    _parse_category,
    _parse_importance,
)
from models import Change, ChangeCategory, Importance


class TestParseCategory:
    """Tests for _parse_category helper."""

    def test_breaking(self):
        assert _parse_category("breaking") == ChangeCategory.BREAKING

    def test_feature(self):
        assert _parse_category("feature") == ChangeCategory.FEATURE

    def test_fix(self):
        assert _parse_category("fix") == ChangeCategory.FIX

    def test_security(self):
        assert _parse_category("security") == ChangeCategory.SECURITY

    def test_improvement(self):
        assert _parse_category("improvement") == ChangeCategory.IMPROVEMENT

    def test_unknown_defaults_to_other(self):
        assert _parse_category("unknown") == ChangeCategory.OTHER

    def test_case_insensitive(self):
        assert _parse_category("BREAKING") == ChangeCategory.BREAKING
        assert _parse_category("Feature") == ChangeCategory.FEATURE


class TestParseImportance:
    """Tests for _parse_importance helper."""

    def test_high(self):
        assert _parse_importance("high") == Importance.HIGH

    def test_medium(self):
        assert _parse_importance("medium") == Importance.MEDIUM

    def test_low(self):
        assert _parse_importance("low") == Importance.LOW

    def test_unknown_defaults_to_medium(self):
        assert _parse_importance("unknown") == Importance.MEDIUM


class TestParseChangeLine:
    """Tests for _parse_change_line helper."""

    def test_simple_line(self):
        result = _parse_change_line("[feature|high] OAuth Support | Added OAuth 2.0", 0)
        assert result is not None
        assert result.category == ChangeCategory.FEATURE
        assert result.importance == Importance.HIGH
        assert result.title == "OAuth Support"
        assert result.description == "Added OAuth 2.0"

    def test_without_description(self):
        result = _parse_change_line("[fix|medium] Bug fixed", 0)
        assert result is not None
        assert result.category == ChangeCategory.FIX
        assert result.title == "Bug fixed"
        assert result.description == ""

    def test_without_importance(self):
        result = _parse_change_line("[security] XSS vulnerability fixed", 0)
        assert result is not None
        assert result.category == ChangeCategory.SECURITY
        assert result.importance == Importance.MEDIUM  # default
        assert result.title == "XSS vulnerability fixed"

    def test_invalid_line(self):
        result = _parse_change_line("not a valid change line", 0)
        assert result is None

    def test_empty_line(self):
        result = _parse_change_line("", 0)
        assert result is None


class TestExtractChangesFromResponse:
    """Tests for _extract_changes_from_response helper."""

    def test_with_changes_tag(self):
        response = """<CHANGES>
[feature|high] OAuth Support | Added OAuth 2.0
[fix|medium] Bug fixed | Fixed login crash
</CHANGES>"""
        result = _extract_changes_from_response(response)
        assert len(result) == 2
        assert result[0].category == ChangeCategory.FEATURE
        assert result[1].category == ChangeCategory.FIX

    def test_without_closing_tag(self):
        """Should still parse if closing tag is missing (truncated output)."""
        response = """<CHANGES>
[feature|high] OAuth Support | Added OAuth 2.0
[fix|medium] Bug fixed | Fixed login crash"""
        result = _extract_changes_from_response(response)
        assert len(result) == 2

    def test_empty_response(self):
        result = _extract_changes_from_response("")
        assert result == []

    def test_mixed_valid_invalid_lines(self):
        response = """<CHANGES>
[feature|high] Valid feature | Description
This is not a valid line
[fix|low] Valid fix | Another description
</CHANGES>"""
        result = _extract_changes_from_response(response)
        assert len(result) == 2


class TestDetermineVersionFromChanges:
    """Tests for determine_version_from_changes function."""

    def test_breaking_returns_major(self):
        changes = [
            Change(id="1", category=ChangeCategory.BREAKING, title="Breaking", description=""),
            Change(id="2", category=ChangeCategory.FEATURE, title="Feature", description=""),
        ]
        assert determine_version_from_changes(changes) == "major"

    def test_feature_returns_minor(self):
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature", description=""),
            Change(id="2", category=ChangeCategory.FIX, title="Fix", description=""),
        ]
        assert determine_version_from_changes(changes) == "minor"

    def test_fixes_only_returns_patch(self):
        changes = [
            Change(id="1", category=ChangeCategory.FIX, title="Fix 1", description=""),
            Change(id="2", category=ChangeCategory.FIX, title="Fix 2", description=""),
        ]
        assert determine_version_from_changes(changes) == "patch"

    def test_empty_returns_patch(self):
        assert determine_version_from_changes([]) == "patch"

    def test_improvement_only_returns_patch(self):
        changes = [
            Change(id="1", category=ChangeCategory.IMPROVEMENT, title="Improvement", description=""),
        ]
        assert determine_version_from_changes(changes) == "patch"


class TestExtractChangesFromChunk:
    """Tests for extract_changes_from_chunk function."""

    def test_extracts_changes_from_valid_response(self):
        mock_response = """<CHANGES>
[feature|high] New feature | Added something
[fix|medium] Bug fix | Fixed something
</CHANGES>"""

        def mock_llm_caller(prompt: str) -> str:
            return mock_response

        changes = extract_changes_from_chunk("Some chunk content", mock_llm_caller)
        assert len(changes) == 2
        assert changes[0].category == ChangeCategory.FEATURE
        assert changes[0].title == "New feature"
        assert changes[1].category == ChangeCategory.FIX

    def test_handles_empty_response(self):
        def mock_llm_caller(prompt: str) -> str:
            return "<CHANGES>\n</CHANGES>"

        changes = extract_changes_from_chunk("Some chunk content", mock_llm_caller)
        assert changes == []

    def test_handles_invalid_response(self):
        def mock_llm_caller(prompt: str) -> str:
            return "I don't understand"

        changes = extract_changes_from_chunk("Some chunk content", mock_llm_caller)
        assert changes == []


class TestReduceChanges:
    """Tests for reduce_changes function."""

    def test_few_changes_no_reduction(self):
        changes = [
            Change(id="1", category=ChangeCategory.FEATURE, title="Feature 1", description=""),
            Change(id="2", category=ChangeCategory.FIX, title="Fix 1", description=""),
        ]

        def mock_llm_caller(prompt: str) -> str:
            raise AssertionError("Should not call LLM for few changes")

        # Should return as-is without calling LLM
        result = reduce_changes(changes, mock_llm_caller)
        assert result == changes

    def test_many_changes_calls_llm(self):
        changes = [
            Change(id=str(i), category=ChangeCategory.FEATURE, title=f"Feature {i}", description="")
            for i in range(10)
        ]

        mock_response = """<CHANGES>
[feature|high] Combined Feature 1 | desc
[feature|medium] Combined Feature 2 | desc
</CHANGES>"""

        def mock_llm_caller(prompt: str) -> str:
            return mock_response

        result = reduce_changes(changes, mock_llm_caller)
        assert len(result) == 2
        assert result[0].title == "Combined Feature 1"

    def test_empty_changes(self):
        def mock_llm_caller(prompt: str) -> str:
            raise AssertionError("Should not call LLM for empty changes")

        result = reduce_changes([], mock_llm_caller)
        assert result == []


class TestProcessLargeInput:
    """Tests for process_large_input function."""

    def test_small_input_returns_empty(self):
        """Small input should return empty list (signal to use normal processing)."""
        def mock_llm_caller(prompt: str) -> str:
            raise AssertionError("Should not call LLM for small input")

        result = process_large_input("Small content", mock_llm_caller, chunk_size=1000)
        assert result == []

    def test_large_input_processes_chunks(self):
        """Large input should be chunked and processed."""
        # Create content that will be chunked
        large_content = "\n\n".join([f"Paragraph {i} with content." for i in range(50)])

        call_count = [0]

        def mock_llm_caller(prompt: str) -> str:
            call_count[0] += 1
            if "Extract ALL changes" in prompt:
                # Map phase
                return '<CHANGES>\n[feature|medium] Feature from chunk | desc\n</CHANGES>'
            else:
                # Reduce phase
                return '<CHANGES>\n[feature|high] Final Feature | consolidated\n</CHANGES>'

        result = process_large_input(
            large_content,
            mock_llm_caller,
            chunk_size=100,
            chunk_overlap=20,
        )

        # Should have called LLM multiple times (map + reduce)
        assert call_count[0] >= 2
        # Should return consolidated changes
        assert len(result) >= 1

    def test_single_chunk_returns_empty(self):
        """Content that fits in single chunk should return empty (use normal path)."""
        content = "Some content that fits in one chunk easily"

        def mock_llm_caller(prompt: str) -> str:
            raise AssertionError("Should not call LLM for single chunk")

        result = process_large_input(content, mock_llm_caller, chunk_size=1000)
        assert result == []
