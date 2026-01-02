"""Tests for flatten module (Phase 0: Net State Analysis)."""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from flatten import (
    flatten_changes,
    flatten_changes_to_list,
    parse_flattened_response,
    parse_flattened_changes,
    _parse_category,
    _parse_importance,
    FLATTEN_PROMPT,
)
from models import Change, ChangeCategory, Importance


class TestParseFlattenedResponse:
    """Tests for parse_flattened_response."""

    def test_extracts_content_between_tags(self):
        response = """Some preamble text
<FLATTENED>
[feature|high] Dark mode | Added dark mode toggle
[docs|low] README | Updated documentation
</FLATTENED>

<REMOVED reason="reverted">
- Stripe payment - reverted
</REMOVED>
"""
        result = parse_flattened_response(response)
        assert "[feature|high] Dark mode" in result
        assert "[docs|low] README" in result
        assert "Stripe" not in result
        assert "<REMOVED>" not in result

    def test_handles_missing_tags(self):
        response = "[feature|high] Some feature | Description"
        result = parse_flattened_response(response)
        assert result == "[feature|high] Some feature | Description"

    def test_handles_empty_response(self):
        response = ""
        result = parse_flattened_response(response)
        assert result == ""

    def test_handles_only_removed_section(self):
        response = """<FLATTENED>
</FLATTENED>

<REMOVED>
- Everything was reverted
</REMOVED>
"""
        result = parse_flattened_response(response)
        assert result == ""


class TestParseFlattenedChanges:
    """Tests for parse_flattened_changes."""

    def test_parses_single_change(self):
        response = """<FLATTENED>
[feature|high] Dark mode | Added dark mode toggle
</FLATTENED>
"""
        changes = parse_flattened_changes(response)
        assert len(changes) == 1
        assert changes[0].category == ChangeCategory.FEATURE
        assert changes[0].importance == Importance.HIGH
        assert changes[0].title == "Dark mode"
        assert changes[0].description == "Added dark mode toggle"

    def test_parses_multiple_changes(self):
        response = """<FLATTENED>
[feature|high] OAuth 2.0 | Full OAuth flow
[fix|medium] Login bug | Fixed redirect issue
[docs|low] README | Updated docs
</FLATTENED>
"""
        changes = parse_flattened_changes(response)
        assert len(changes) == 3
        assert changes[0].category == ChangeCategory.FEATURE
        assert changes[1].category == ChangeCategory.FIX
        assert changes[2].category == ChangeCategory.DOCUMENTATION

    def test_handles_missing_importance(self):
        response = """<FLATTENED>
[feature] Dark mode | Added toggle
</FLATTENED>
"""
        changes = parse_flattened_changes(response)
        assert len(changes) == 1
        assert changes[0].importance == Importance.MEDIUM  # default

    def test_handles_missing_description(self):
        response = """<FLATTENED>
[feature|high] Dark mode
</FLATTENED>
"""
        changes = parse_flattened_changes(response)
        assert len(changes) == 1
        assert changes[0].title == "Dark mode"
        assert changes[0].description == ""

    def test_skips_invalid_lines(self):
        response = """<FLATTENED>
[feature|high] Valid change | Description
This is not a valid change line
# This is a comment
- This is a bullet point
[feature|high] Another valid | Also valid
</FLATTENED>
"""
        changes = parse_flattened_changes(response)
        assert len(changes) == 2

    def test_handles_empty_flattened_section(self):
        response = """<FLATTENED>
</FLATTENED>
"""
        changes = parse_flattened_changes(response)
        assert len(changes) == 0


class TestFlattenChanges:
    """Tests for flatten_changes function."""

    def test_calls_llm_with_prompt(self):
        called_prompts = []

        def mock_llm(prompt: str) -> str:
            called_prompts.append(prompt)
            return """<FLATTENED>
[feature|high] Result | Description
</FLATTENED>
"""

        input_content = "1. feat: Add feature\n2. fix: Fix bug"
        result = flatten_changes(input_content, mock_llm)

        assert len(called_prompts) == 1
        assert input_content in called_prompts[0]
        assert "NET STATE" in called_prompts[0]

    def test_returns_flattened_content(self):
        def mock_llm(prompt: str) -> str:
            return """<FLATTENED>
[feature|high] Dark mode | Added toggle
</FLATTENED>

<REMOVED>
- Stripe payment - reverted
</REMOVED>
"""

        input_content = """1. feat: Add Stripe payment
2. fix: Fix payment validation
3. feat: Add dark mode
4. revert: Revert Stripe payment
"""
        result = flatten_changes(input_content, mock_llm)

        assert "[feature|high] Dark mode" in result
        assert "Stripe" not in result

    def test_handles_empty_input(self):
        def mock_llm(prompt: str) -> str:
            raise AssertionError("Should not call LLM for empty input")

        result = flatten_changes("", mock_llm)
        assert result == ""

    def test_handles_whitespace_only_input(self):
        def mock_llm(prompt: str) -> str:
            raise AssertionError("Should not call LLM for whitespace input")

        result = flatten_changes("   \n  \n  ", mock_llm)
        assert result == ""


class TestFlattenChangesToList:
    """Tests for flatten_changes_to_list function."""

    def test_returns_change_objects(self):
        def mock_llm(prompt: str) -> str:
            return """<FLATTENED>
[feature|high] OAuth support | Full OAuth 2.0 flow
[fix|medium] Login fix | Fixed redirect
</FLATTENED>
"""

        changes = flatten_changes_to_list("some input", mock_llm)

        assert len(changes) == 2
        assert all(isinstance(c, Change) for c in changes)
        assert changes[0].category == ChangeCategory.FEATURE
        assert changes[1].category == ChangeCategory.FIX

    def test_handles_empty_input(self):
        def mock_llm(prompt: str) -> str:
            raise AssertionError("Should not call LLM for empty input")

        result = flatten_changes_to_list("", mock_llm)
        assert result == []


class TestNetStateScenarios:
    """Tests for specific net state scenarios from the proposal."""

    def test_feature_added_then_reverted_excluded(self):
        """Reverted feature should not appear in output."""

        def mock_llm(prompt: str) -> str:
            # Simulate LLM correctly identifying net state
            return """<FLATTENED>
[feature|high] Dark mode | Added dark mode toggle
</FLATTENED>

<REMOVED reason="reverted">
- Stripe payment - reverted by later commit
- Payment validation fix - related to reverted feature
</REMOVED>
"""

        input_content = """1. feat: Add Stripe payment
2. fix: Fix payment validation
3. feat: Add dark mode
4. revert: Revert Stripe payment
"""
        result = flatten_changes(input_content, mock_llm)

        assert "Dark mode" in result
        assert "Stripe" not in result
        assert "payment" not in result.lower()

    def test_related_changes_consolidated(self):
        """Related changes should become one entry."""

        def mock_llm(prompt: str) -> str:
            return """<FLATTENED>
[feature|high] OAuth 2.0 authentication | Full OAuth flow with token refresh and scope support
</FLATTENED>
"""

        input_content = """1. feat: Add OAuth login
2. fix: Fix OAuth token refresh
3. feat: Add OAuth scope support
"""
        changes = flatten_changes_to_list(input_content, mock_llm)

        # Should have ONE OAuth entry, not three
        assert len(changes) == 1
        assert "OAuth" in changes[0].title

    def test_all_changes_reverted_returns_empty(self):
        """If everything is reverted, output should be empty."""

        def mock_llm(prompt: str) -> str:
            return """<FLATTENED>
</FLATTENED>

<REMOVED>
- Feature A - reverted
- Feature B - reverted
</REMOVED>
"""

        input_content = """1. feat: Add feature A
2. feat: Add feature B
3. revert: Revert feature A
4. revert: Revert feature B
"""
        changes = flatten_changes_to_list(input_content, mock_llm)

        assert len(changes) == 0


class TestPromptContent:
    """Tests to verify the flatten prompt contains required instructions."""

    def test_prompt_includes_net_state_instruction(self):
        assert "NET STATE" in FLATTEN_PROMPT

    def test_prompt_includes_revert_handling(self):
        assert "REVERTED" in FLATTEN_PROMPT or "reverted" in FLATTEN_PROMPT.lower()

    def test_prompt_includes_consolidation_instruction(self):
        assert "consolidate" in FLATTEN_PROMPT.lower() or "RELATED" in FLATTEN_PROMPT

    def test_prompt_includes_output_format(self):
        assert "<FLATTENED>" in FLATTEN_PROMPT
        assert "[category" in FLATTEN_PROMPT.lower()
