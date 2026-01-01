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
    INTERNAL_CONTENT_PATTERNS,
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

    def test_no_preset_checks_by_default(self):
        """No preset should still check for internal content (default behavior)."""
        content = """## Changes
- Updated `company/backend`
"""
        issues = check_internal_content(content, preset=None)
        assert len(issues) >= 1

    def test_custom_preset_checks_by_default(self):
        """Custom preset should check for internal content by default."""
        content = """## Changes
- Updated `company/backend`
"""
        issues = check_internal_content(content, preset="my-custom-preset")
        assert len(issues) >= 1

    def test_skip_internal_check_option(self):
        """skip_internal_check=True should skip all checks."""
        content = """## Changes
- Updated `company/backend`
- CI/CD pipeline updated
- arn:aws:s3:::my-bucket exposed
"""
        issues = check_internal_content(content, preset="customer", skip_internal_check=True)
        assert issues == []


class TestNewInternalContentPatterns:
    """Tests for newly added internal content patterns."""

    def test_aws_arn_detected(self):
        """AWS ARN patterns should be detected."""
        content = """## Changes
- Updated bucket arn:aws:s3:::my-company-bucket for storage
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1
        assert "Internal content leaked" in issues[0]

    def test_aws_arn_with_region_detected(self):
        """AWS ARN with region should be detected."""
        content = """## Changes
- Lambda function arn:aws:lambda:us-east-1:123456789012:function:myfunction deployed
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_internal_domain_detected(self):
        """Internal domain URLs should be detected."""
        content = """## Changes
- API endpoint changed to api.internal.company.com
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_local_domain_detected(self):
        """Local domain URLs should be detected."""
        content = """## Changes
- Testing against db.local.dev
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_corp_domain_detected(self):
        """Corp domain URLs should be detected."""
        content = """## Changes
- Updated Jenkins at jenkins.corp.example
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_private_domain_detected(self):
        """Private domain URLs should be detected."""
        content = """## Changes
- Vault server at vault.private.network
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_slack_webhook_detected(self):
        """Slack webhook URLs should be detected."""
        content = """## Changes
- Notifications now go to hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXX
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_api_key_pattern_detected(self):
        """API key patterns should be detected."""
        content = """## Changes
- Set api_key=abcdefghij1234567890abcdefghij for authentication
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_token_pattern_detected(self):
        """Token patterns should be detected."""
        content = """## Changes
- Configure token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_secret_pattern_detected(self):
        """Secret patterns should be detected."""
        content = """## Changes
- Set secret="my_super_secret_value_12345678901234567890"
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_private_ip_10_range_detected(self):
        """Private IP 10.x.x.x should be detected."""
        content = """## Changes
- Database server moved to 10.0.1.50
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_private_ip_192_range_detected(self):
        """Private IP 192.168.x.x should be detected."""
        content = """## Changes
- Connect to Redis at 192.168.1.100
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_private_ip_172_range_detected(self):
        """Private IP 172.16-31.x.x should be detected."""
        content = """## Changes
- Kubernetes cluster at 172.16.0.10
"""
        issues = check_internal_content(content, preset="customer")
        assert len(issues) == 1

    def test_public_ip_not_flagged(self):
        """Public IP addresses should not be flagged."""
        content = """## Changes
- Server responds from 8.8.8.8 (Google DNS)
"""
        issues = check_internal_content(content, preset="customer")
        # Public IP should not match private IP patterns
        assert issues == []

    def test_172_outside_range_not_flagged(self):
        """IP 172.15.x.x and 172.32.x.x should not be flagged."""
        content = """## Changes
- Public server at 172.15.1.1 and 172.32.1.1
"""
        issues = check_internal_content(content, preset="customer")
        assert issues == []


class TestCustomPatterns:
    """Tests for custom internal content patterns."""

    def test_custom_pattern_detected(self):
        """Custom patterns should be detected."""
        content = """## Changes
- Updated JIRA-12345 ticket reference
"""
        custom_patterns = [r"JIRA-\d+"]
        issues = check_internal_content(content, preset="customer", custom_patterns=custom_patterns)
        assert len(issues) == 1

    def test_custom_pattern_merged_with_builtin(self):
        """Custom patterns should be merged with built-in patterns."""
        content = """## Changes
- Updated `company/backend` repository
"""
        custom_patterns = [r"JIRA-\d+"]
        issues = check_internal_content(content, preset="customer", custom_patterns=custom_patterns)
        # Built-in pattern should still work
        assert len(issues) == 1

    def test_invalid_custom_pattern_skipped(self):
        """Invalid regex patterns should be skipped."""
        content = """## Changes
- Some content here
"""
        custom_patterns = [r"[invalid(regex"]  # Invalid regex
        # Should not raise an exception, just skip the invalid pattern
        issues = check_internal_content(content, preset="customer", custom_patterns=custom_patterns)
        assert issues == []

    def test_multiple_custom_patterns(self):
        """Multiple custom patterns should work."""
        content = """## Changes
- Updated JIRA-12345 for CONFLUENCE-789
"""
        custom_patterns = [r"JIRA-\d+", r"CONFLUENCE-\d+"]
        issues = check_internal_content(content, preset="customer", custom_patterns=custom_patterns)
        assert len(issues) == 1  # Only reports first match


class TestPresetBehavior:
    """Tests for preset-based internal content checking behavior."""

    def test_security_preset_checks_by_default(self):
        """Security preset should check for internal content."""
        content = """## Changes
- Updated `company/backend`
"""
        issues = check_internal_content(content, preset="security")
        assert len(issues) >= 1

    def test_developer_uses_skip_internal_check_from_preset(self):
        """Developer preset behavior via skip_internal_check flag."""
        content = """## Changes
- Updated `company/backend`
- CI/CD pipeline changed
"""
        # When using preset="developer", internal check is skipped
        issues = check_internal_content(content, preset="developer")
        assert issues == []

        # Same content with skip_internal_check=True should also skip
        issues = check_internal_content(content, preset=None, skip_internal_check=True)
        assert issues == []

    def test_ops_uses_skip_internal_check_from_preset(self):
        """Ops preset behavior via skip_internal_check flag."""
        content = """## Changes
- Updated 10.0.1.50 server
- GitHub Actions workflow modified
"""
        # When using preset="ops", internal check is skipped
        issues = check_internal_content(content, preset="ops")
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
