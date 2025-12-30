"""Integration tests for the full analysis flow."""

import os
import sys
import tempfile
import subprocess
from unittest.mock import patch, MagicMock

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analyze import main, call_llm_with_retry, sanitize_changelog
from version import parse_version
from parser import parse_response
from prompt_builder import build_prompt, CommitInfo


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_full_flow_with_mock_llm(self):
        """Test the complete flow from commits to version suggestion."""
        # Simulate commits
        commits = [
            CommitInfo(hash="abc1234", message="feat: add new login page"),
            CommitInfo(hash="def5678", message="fix: resolve login redirect bug"),
            CommitInfo(hash="ghi9012", message="chore: update dependencies"),
        ]

        # Build prompt
        prompt = build_prompt(commits, "v1.0.0")

        # Verify prompt contains expected content
        assert "v1.0.0 -> next" in prompt
        assert "3 total" in prompt
        assert "feat: add new login page" in prompt
        assert "fix: resolve login redirect bug" in prompt

        # Simulate LLM response
        mock_response = """
<BUMP>minor</BUMP>
<REASONING>New feature added (login page) with bug fix. No breaking changes detected.</REASONING>
<BREAKING_CHANGES>
</BREAKING_CHANGES>
<FEATURES>
- New login page
</FEATURES>
<FIXES>
- Login redirect bug fixed
</FIXES>
<CHANGELOG>
## What's Changed

### Features
- New login page

### Bug Fixes
- Login redirect bug fixed
</CHANGELOG>
"""

        # Parse response
        result = parse_response(mock_response)

        assert result.bump == "minor"
        assert "login page" in result.reasoning.lower()
        assert len(result.features) == 1
        assert len(result.fixes) == 1

        # Calculate next version
        current = parse_version("v1.0.0")
        next_version = current.bump(result.bump)

        assert str(next_version) == "v1.1.0"

    def test_breaking_change_flow(self):
        """Test flow with breaking change detected."""
        commits = [
            CommitInfo(
                hash="abc1234",
                message="feat!: remove deprecated API endpoint",
                has_breaking_marker=True,
            ),
            CommitInfo(hash="def5678", message="fix: update error messages"),
        ]

        prompt = build_prompt(commits, "v2.0.0")

        assert "[BREAKING]" in prompt
        assert "Explicit BREAKING markers**: 1" in prompt

        # Simulate LLM response for breaking change
        mock_response = """
<BUMP>major</BUMP>
<REASONING>Breaking change detected: API endpoint removed.</REASONING>
<BREAKING_CHANGES>
- Deprecated API endpoint removed
</BREAKING_CHANGES>
<FEATURES>
</FEATURES>
<FIXES>
- Error messages updated
</FIXES>
<CHANGELOG>
## What's Changed

### Breaking Changes
- Deprecated API endpoint removed

### Bug Fixes
- Error messages updated
</CHANGELOG>
"""

        result = parse_response(mock_response)

        assert result.bump == "major"
        assert len(result.breaking_changes) == 1

        current = parse_version("v2.0.0")
        next_version = current.bump(result.bump)

        assert str(next_version) == "v3.0.0"

    def test_patch_only_flow(self):
        """Test flow with only bug fixes."""
        commits = [
            CommitInfo(hash="abc1234", message="fix: resolve memory leak"),
            CommitInfo(hash="def5678", message="fix: correct typo in error message"),
            CommitInfo(hash="ghi9012", message="docs: update readme"),
        ]

        prompt = build_prompt(commits, "v1.5.2")

        mock_response = """
<BUMP>patch</BUMP>
<REASONING>Only bug fixes and documentation updates. No new features.</REASONING>
<BREAKING_CHANGES>
</BREAKING_CHANGES>
<FEATURES>
</FEATURES>
<FIXES>
- Memory leak resolved
- Typo in error message corrected
</FIXES>
<CHANGELOG>
## What's Changed

### Bug Fixes
- Memory leak resolved
- Typo in error message corrected
</CHANGELOG>
"""

        result = parse_response(mock_response)

        assert result.bump == "patch"
        assert len(result.fixes) == 2

        current = parse_version("v1.5.2")
        next_version = current.bump(result.bump)

        assert str(next_version) == "v1.5.3"


class TestLLMRetry:
    """Tests for LLM retry logic."""

    def test_retry_on_rate_limit(self):
        """Test retry on 429 rate limit."""
        mock_completion = MagicMock()

        # First call fails with rate limit, second succeeds
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "<BUMP>patch</BUMP><REASONING>test</REASONING>"

        mock_completion.side_effect = [
            Exception("429 rate limit exceeded"),
            mock_response,
        ]

        with patch("analyze.litellm.completion", mock_completion):
            with patch("analyze.time.sleep"):  # Skip actual sleep
                result = call_llm_with_retry(
                    model="test/model",
                    prompt="test prompt",
                    temperature=0.2,
                    max_tokens=100,
                    timeout=30,
                )

        assert "<BUMP>patch</BUMP>" in result
        assert mock_completion.call_count == 2

    def test_no_retry_on_auth_error(self):
        """Test immediate failure on auth error."""
        mock_completion = MagicMock()
        mock_completion.side_effect = Exception("401 authentication failed")

        with patch("analyze.litellm.completion", mock_completion):
            with pytest.raises(RuntimeError) as exc_info:
                call_llm_with_retry(
                    model="test/model",
                    prompt="test prompt",
                    temperature=0.2,
                    max_tokens=100,
                    timeout=30,
                )

        assert "Authentication failed" in str(exc_info.value)
        assert mock_completion.call_count == 1  # No retries

    def test_max_retries_exceeded(self):
        """Test failure after max retries."""
        mock_completion = MagicMock()
        mock_completion.side_effect = Exception("500 server error")

        with patch("analyze.litellm.completion", mock_completion):
            with patch("analyze.time.sleep"):
                with pytest.raises(RuntimeError) as exc_info:
                    call_llm_with_retry(
                        model="test/model",
                        prompt="test prompt",
                        temperature=0.2,
                        max_tokens=100,
                        timeout=30,
                        max_retries=3,
                    )

        assert "failed after 3 attempts" in str(exc_info.value)
        assert mock_completion.call_count == 3


class TestChangelogSanitization:
    """Tests for changelog sanitization."""

    def test_strips_html(self):
        """Test HTML tags are stripped."""
        changelog = "## Changes\n<script>alert('xss')</script>\n- Fixed bug"
        result = sanitize_changelog(changelog)

        assert "<script>" not in result
        assert "## Changes" in result
        assert "Fixed bug" in result

    def test_removes_javascript_urls(self):
        """Test javascript: URLs are removed."""
        changelog = "## Changes\n[Click here](javascript:alert('xss'))\n- Fixed bug"
        result = sanitize_changelog(changelog)

        assert "javascript:" not in result

    def test_truncates_large_changelog(self):
        """Test large changelog is truncated."""
        changelog = "x" * 100000
        result = sanitize_changelog(changelog, max_size=1000)

        assert len(result.encode("utf-8")) <= 1000
        assert "(truncated)" in result


class TestPreReleaseVersioning:
    """Tests for pre-release version handling."""

    def test_prerelease_patch_bump(self):
        """Test patch bump on pre-release version."""
        current = parse_version("v1.0.0-alpha.1")
        next_version = current.bump("patch")

        assert str(next_version) == "v1.0.0-alpha.2"

    def test_prerelease_minor_bump(self):
        """Test minor bump on pre-release version resets to stable."""
        current = parse_version("v1.0.0-alpha.1")
        next_version = current.bump("minor")

        assert str(next_version) == "v1.1.0"

    def test_prerelease_major_bump(self):
        """Test major bump on pre-release version resets to stable."""
        current = parse_version("v1.0.0-beta.5")
        next_version = current.bump("major")

        assert str(next_version) == "v2.0.0"
