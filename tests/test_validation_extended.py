"""Extended tests for validation module - empty sections and internal content."""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from validation import (
    check_empty_sections,
    check_internal_content,
    strip_empty_sections,
)


class TestCheckEmptySections:
    """Tests for check_empty_sections function."""

    def test_no_empty_sections(self):
        """Changelog with content in all sections should pass."""
        content = """## Features
- Added OAuth support
- Added dashboard improvements

## Fixes
- Fixed login issue
"""
        issues = check_empty_sections(content)
        assert issues == []

    def test_empty_section_detected(self):
        """Empty section should be detected."""
        content = """## Features

## Fixes
- Fixed login issue
"""
        issues = check_empty_sections(content)
        assert len(issues) == 1
        assert "Features" in issues[0]

    def test_multiple_empty_sections(self):
        """Multiple empty sections should all be detected."""
        content = """## Features

## Improvements

## Fixes
- Fixed something
"""
        issues = check_empty_sections(content)
        assert len(issues) == 2

    def test_empty_section_at_end(self):
        """Empty section at end should be detected."""
        content = """## Features
- Added feature

## Fixes
"""
        issues = check_empty_sections(content)
        assert len(issues) == 1
        assert "Fixes" in issues[0]

    def test_whitespace_only_section(self):
        """Section with only whitespace should be detected as empty."""
        content = """## Features


## Fixes
- Fixed something
"""
        issues = check_empty_sections(content)
        assert len(issues) == 1


class TestCheckInternalContent:
    """Tests for check_internal_content function."""

    def test_no_internal_content(self):
        """Customer-friendly content should pass."""
        content = """## Features
- You can now export reports as PDF
- Dashboard loads 50% faster
"""
        issues = check_internal_content(content, preset="customer")
        assert issues == []

    def test_repo_reference_detected(self):
        """Repository references should be detected."""
        content = """## Features
- Added OAuth support in `company/backend`
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1
        assert "Internal content leaked" in issues[0]

    def test_database_schema_detected(self):
        """Database schema references should be detected."""
        content = """## Breaking Changes
- Database schema changed for user table
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_developer_preset_not_checked(self):
        """Developer preset should not check for internal content."""
        content = """## Changes
- Updated `company/backend` repository
- Database schema migration required
"""
        issues = check_internal_content(content, preset="developer")
        assert issues == []

    def test_ops_preset_not_checked(self):
        """Ops preset should not check for internal content."""
        content = """## Changes
- CI/CD pipeline updated
- GitHub Actions workflow modified
"""
        issues = check_internal_content(content, preset="ops")
        assert issues == []

    def test_executive_preset_checked(self):
        """Executive preset should check for internal content."""
        content = """## Summary
- Major update to `company/api` with database schema changes
"""
        issues = check_internal_content(content, preset="executive")
        assert len(issues) >= 1

    def test_marketing_preset_checked(self):
        """Marketing preset should check for internal content."""
        content = """## Highlights
- Improved CI/CD pipeline efficiency
"""
        issues = check_internal_content(content, preset="marketing")
        assert len(issues) == 1

    def test_no_preset_skips_check(self):
        """No preset should skip internal content check."""
        content = """## Changes
- Updated `company/backend`
"""
        issues = check_internal_content(content, preset=None)
        assert issues == []


class TestStripEmptySections:
    """Tests for strip_empty_sections function."""

    def test_preserves_sections_with_content(self):
        """Sections with content should be preserved."""
        content = """## Features
- Added feature

## Fixes
- Fixed bug
"""
        result = strip_empty_sections(content)
        assert "## Features" in result
        assert "## Fixes" in result

    def test_removes_empty_sections(self):
        """Empty sections should be removed."""
        content = """## Features

## Fixes
- Fixed bug
"""
        result = strip_empty_sections(content)
        assert "## Features" not in result
        assert "## Fixes" in result
        assert "Fixed bug" in result

    def test_removes_multiple_empty_sections(self):
        """Multiple empty sections should be removed."""
        content = """## Features

## Improvements

## Fixes
- Fixed bug

## Breaking
"""
        result = strip_empty_sections(content)
        assert "## Features" not in result
        assert "## Improvements" not in result
        assert "## Breaking" not in result
        assert "## Fixes" in result

    def test_preserves_content_before_sections(self):
        """Content before first section should be preserved."""
        content = """# Changelog v1.0

Some intro text.

## Features

## Fixes
- Fixed bug
"""
        result = strip_empty_sections(content)
        assert "# Changelog v1.0" in result
        assert "Some intro text." in result
        assert "## Features" not in result
        assert "## Fixes" in result

    def test_empty_content(self):
        """Empty content should return empty."""
        result = strip_empty_sections("")
        assert result == ""


class TestRealWorldScenarios:
    """Tests with real-world-like content."""

    def test_customer_changelog_quality_check(self):
        """Test the v2.0.0 problematic output pattern."""
        # This content has vague intro text (not actionable items) but not technically empty
        problematic_content = """## 🚀 New Features
We're excited to bring you some fantastic new features in this release!

## 🐛 Fixes
We've squashed some bugs to ensure everything runs smoothly.

## ⚠️ Breaking Changes
### Database Schema Changes in `company/pymono`
Added new columns and indices to the process table.
"""
        # These sections have text (even if vague), so they're not structurally empty
        # The real issue is the internal content leak
        empty_issues = check_empty_sections(problematic_content)
        # Sections have some text, so may or may not be detected as empty depending on implementation

        # Check for internal content - this is the key quality issue
        internal_issues = check_internal_content(problematic_content, preset="customer")
        assert len(internal_issues) >= 1  # Contains repo reference

    def test_good_customer_changelog(self):
        """Test a well-formed customer changelog."""
        good_content = """## 🚀 New Features
- You can now export reports to PDF and Excel
- Dashboard performance improved by 50%

## 🐛 Bug Fixes
- Fixed login issues on mobile devices
- Resolved slow page loads for large data sets

## ⚠️ Breaking Changes
### Authentication Method Update
You'll need to re-authenticate after updating. Your saved settings will be preserved.
"""
        empty_issues = check_empty_sections(good_content)
        assert empty_issues == []

        internal_issues = check_internal_content(good_content, preset="customer")
        assert internal_issues == []
