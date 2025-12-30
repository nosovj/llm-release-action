"""Tests for version.py module."""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from version import SemanticVersion, parse_version


class TestSemanticVersion:
    """Tests for SemanticVersion class."""

    def test_str_basic(self):
        """Test basic version string output."""
        v = SemanticVersion(1, 2, 3)
        assert str(v) == "v1.2.3"

    def test_str_with_prerelease(self):
        """Test version string with prerelease."""
        v = SemanticVersion(1, 0, 0, "alpha.1")
        assert str(v) == "v1.0.0-alpha.1"

    def test_bump_major(self):
        """Test major version bump."""
        v = SemanticVersion(1, 2, 3)
        bumped = v.bump("major")
        assert bumped.major == 2
        assert bumped.minor == 0
        assert bumped.patch == 0

    def test_bump_minor(self):
        """Test minor version bump."""
        v = SemanticVersion(1, 2, 3)
        bumped = v.bump("minor")
        assert bumped.major == 1
        assert bumped.minor == 3
        assert bumped.patch == 0

    def test_bump_patch(self):
        """Test patch version bump."""
        v = SemanticVersion(1, 2, 3)
        bumped = v.bump("patch")
        assert bumped.major == 1
        assert bumped.minor == 2
        assert bumped.patch == 4

    def test_bump_patch_prerelease(self):
        """Test patch bump on prerelease version bumps the suffix."""
        v = SemanticVersion(1, 0, 0, "alpha.1")
        bumped = v.bump("patch")
        assert str(bumped) == "v1.0.0-alpha.2"

    def test_bump_patch_prerelease_no_number(self):
        """Test patch bump on prerelease without number appends .1."""
        v = SemanticVersion(1, 0, 0, "beta")
        bumped = v.bump("patch")
        assert str(bumped) == "v1.0.0-beta.1"

    def test_bump_invalid(self):
        """Test invalid bump type raises error."""
        v = SemanticVersion(1, 2, 3)
        with pytest.raises(ValueError) as exc_info:
            v.bump("invalid")
        assert "Invalid bump type" in str(exc_info.value)


class TestParseVersion:
    """Tests for parse_version function."""

    def test_parse_with_v_prefix(self):
        """Test parsing version with v prefix."""
        v = parse_version("v1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3
        assert v.prerelease is None

    def test_parse_without_v_prefix(self):
        """Test parsing version without v prefix."""
        v = parse_version("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_with_prerelease(self):
        """Test parsing version with prerelease suffix."""
        v = parse_version("v1.0.0-alpha.1")
        assert v.major == 1
        assert v.minor == 0
        assert v.patch == 0
        assert v.prerelease == "alpha.1"

    def test_parse_with_complex_prerelease(self):
        """Test parsing version with complex prerelease."""
        v = parse_version("v2.0.0-rc.1.build.123")
        assert v.major == 2
        assert v.prerelease == "rc.1.build.123"

    def test_parse_invalid_format(self):
        """Test parsing invalid version format raises error."""
        with pytest.raises(ValueError) as exc_info:
            parse_version("1.2")
        assert "Invalid version format" in str(exc_info.value)

    def test_parse_invalid_numbers(self):
        """Test parsing non-numeric version raises error."""
        with pytest.raises(ValueError) as exc_info:
            parse_version("v1.two.3")
        assert "Invalid version numbers" in str(exc_info.value)

    def test_parse_negative_numbers(self):
        """Test parsing invalid format with leading dash raises error."""
        # v-1.2.3 is malformed - the "-" is interpreted as prerelease separator
        # resulting in invalid format for the version part
        with pytest.raises(ValueError) as exc_info:
            parse_version("v-1.2.3")
        assert "Invalid version" in str(exc_info.value)

    def test_parse_zero_version(self):
        """Test parsing zero version (v0.0.0)."""
        v = parse_version("v0.0.0")
        assert v.major == 0
        assert v.minor == 0
        assert v.patch == 0
