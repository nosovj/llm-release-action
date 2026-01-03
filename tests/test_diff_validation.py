"""Tests for diff analysis input validation functions.

Tests cover:
1. validate_analyze_diffs - boolean string validation
2. validate_diff_exclude_patterns - gitignore-style pattern validation
3. validate_diff_max_files - non-negative integer validation
4. validate_diff_max_total_lines - non-negative integer validation
5. Integration with validate_inputs
"""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from input_validation import (
    validate_analyze_diffs,
    validate_diff_exclude_patterns,
    validate_diff_max_files,
    validate_diff_max_total_lines,
    validate_inputs,
)


class TestValidateAnalyzeDiffs:
    """Tests for validate_analyze_diffs function."""

    def test_valid_true(self):
        """'true' should be valid."""
        errors = validate_analyze_diffs("true")
        assert errors == []

    def test_valid_false(self):
        """'false' should be valid."""
        errors = validate_analyze_diffs("false")
        assert errors == []

    def test_valid_true_uppercase(self):
        """'TRUE' should be valid (case insensitive)."""
        errors = validate_analyze_diffs("TRUE")
        assert errors == []

    def test_valid_false_uppercase(self):
        """'FALSE' should be valid (case insensitive)."""
        errors = validate_analyze_diffs("FALSE")
        assert errors == []

    def test_valid_mixed_case(self):
        """Mixed case should be valid."""
        errors = validate_analyze_diffs("True")
        assert errors == []
        errors = validate_analyze_diffs("False")
        assert errors == []

    def test_valid_with_whitespace(self):
        """Value with surrounding whitespace should be valid."""
        errors = validate_analyze_diffs("  true  ")
        assert errors == []
        errors = validate_analyze_diffs("  false  ")
        assert errors == []

    def test_empty_string(self):
        """Empty string should be valid (uses default)."""
        errors = validate_analyze_diffs("")
        assert errors == []

    def test_none_value(self):
        """None should be valid (uses default)."""
        errors = validate_analyze_diffs(None)
        assert errors == []

    def test_whitespace_only(self):
        """Whitespace-only string should be valid (uses default)."""
        errors = validate_analyze_diffs("   ")
        assert errors == []

    def test_invalid_value(self):
        """Invalid boolean string should return error."""
        errors = validate_analyze_diffs("yes")
        assert len(errors) == 1
        assert "must be 'true' or 'false'" in errors[0]

    def test_invalid_number(self):
        """Numeric value should return error."""
        errors = validate_analyze_diffs("1")
        assert len(errors) == 1
        assert "must be 'true' or 'false'" in errors[0]

    def test_invalid_random_string(self):
        """Random string should return error."""
        errors = validate_analyze_diffs("enable")
        assert len(errors) == 1
        assert "must be 'true' or 'false'" in errors[0]


class TestValidateDiffExcludePatterns:
    """Tests for validate_diff_exclude_patterns function."""

    def test_empty_string(self):
        """Empty string should be valid."""
        errors = validate_diff_exclude_patterns("")
        assert errors == []

    def test_none_value(self):
        """None should be valid."""
        errors = validate_diff_exclude_patterns(None)
        assert errors == []

    def test_single_valid_pattern(self):
        """Single valid pattern should pass."""
        errors = validate_diff_exclude_patterns("**/*.lock")
        assert errors == []

    def test_multiple_valid_patterns(self):
        """Multiple valid patterns should pass."""
        errors = validate_diff_exclude_patterns("**/*.lock,**/node_modules/**,**/*.min.js")
        assert errors == []

    def test_default_patterns_valid(self):
        """Default action patterns should be valid."""
        default_patterns = (
            "**/*.lock,**/package-lock.json,**/yarn.lock,**/Cargo.lock,"
            "**/poetry.lock,**/vendor/**,**/node_modules/**,**/*.generated.*,"
            "**/generated/**,**/*.min.js,**/*.min.css"
        )
        errors = validate_diff_exclude_patterns(default_patterns)
        assert errors == []

    def test_negation_pattern(self):
        """Negation patterns should be valid."""
        errors = validate_diff_exclude_patterns("**/*.lock,!**/important.lock")
        assert errors == []

    def test_invalid_pattern_with_shell_chars(self):
        """Patterns with shell metacharacters should fail."""
        errors = validate_diff_exclude_patterns("*.lock;rm -rf /")
        assert len(errors) > 0
        assert any("invalid characters" in e.lower() for e in errors)

    def test_invalid_pattern_with_pipe(self):
        """Patterns with pipe should fail."""
        errors = validate_diff_exclude_patterns("*.lock|cat /etc/passwd")
        assert len(errors) > 0

    def test_path_traversal_rejected(self):
        """Path traversal patterns should be rejected."""
        errors = validate_diff_exclude_patterns("../../../etc/passwd")
        assert len(errors) > 0
        assert any("path traversal" in e.lower() for e in errors)

    def test_pattern_too_long(self):
        """Very long patterns should be rejected."""
        long_pattern = "a" * 600
        errors = validate_diff_exclude_patterns(long_pattern)
        assert len(errors) > 0
        assert any("too long" in e.lower() for e in errors)


class TestValidateDiffMaxFiles:
    """Tests for validate_diff_max_files function."""

    def test_valid_positive_integer(self):
        """Positive integer should be valid."""
        errors = validate_diff_max_files("50")
        assert errors == []

    def test_valid_zero(self):
        """Zero should be valid."""
        errors = validate_diff_max_files("0")
        assert errors == []

    def test_valid_large_number(self):
        """Large positive number should be valid."""
        errors = validate_diff_max_files("1000")
        assert errors == []

    def test_empty_string(self):
        """Empty string should be valid (uses default)."""
        errors = validate_diff_max_files("")
        assert errors == []

    def test_none_value(self):
        """None should be valid (uses default)."""
        errors = validate_diff_max_files(None)
        assert errors == []

    def test_whitespace_only(self):
        """Whitespace-only string should be valid (uses default)."""
        errors = validate_diff_max_files("   ")
        assert errors == []

    def test_invalid_negative(self):
        """Negative integer should return error."""
        errors = validate_diff_max_files("-1")
        assert len(errors) == 1
        assert "must be non-negative" in errors[0]

    def test_invalid_float(self):
        """Float should return error."""
        errors = validate_diff_max_files("50.5")
        assert len(errors) == 1
        assert "must be an integer" in errors[0]

    def test_invalid_string(self):
        """Non-numeric string should return error."""
        errors = validate_diff_max_files("fifty")
        assert len(errors) == 1
        assert "must be an integer" in errors[0]


class TestValidateDiffMaxTotalLines:
    """Tests for validate_diff_max_total_lines function."""

    def test_valid_positive_integer(self):
        """Positive integer should be valid."""
        errors = validate_diff_max_total_lines("5000")
        assert errors == []

    def test_valid_zero(self):
        """Zero should be valid."""
        errors = validate_diff_max_total_lines("0")
        assert errors == []

    def test_valid_large_number(self):
        """Large positive number should be valid."""
        errors = validate_diff_max_total_lines("100000")
        assert errors == []

    def test_empty_string(self):
        """Empty string should be valid (uses default)."""
        errors = validate_diff_max_total_lines("")
        assert errors == []

    def test_none_value(self):
        """None should be valid (uses default)."""
        errors = validate_diff_max_total_lines(None)
        assert errors == []

    def test_whitespace_only(self):
        """Whitespace-only string should be valid (uses default)."""
        errors = validate_diff_max_total_lines("   ")
        assert errors == []

    def test_invalid_negative(self):
        """Negative integer should return error."""
        errors = validate_diff_max_total_lines("-100")
        assert len(errors) == 1
        assert "must be non-negative" in errors[0]

    def test_invalid_float(self):
        """Float should return error."""
        errors = validate_diff_max_total_lines("5000.5")
        assert len(errors) == 1
        assert "must be an integer" in errors[0]

    def test_invalid_string(self):
        """Non-numeric string should return error."""
        errors = validate_diff_max_total_lines("five-thousand")
        assert len(errors) == 1
        assert "must be an integer" in errors[0]


class TestValidateInputsIntegration:
    """Integration tests for validate_inputs with diff analysis parameters."""

    def test_valid_diff_params(self, tmp_path, monkeypatch):
        """Valid diff parameters should pass validation."""
        # Create a fake git repo
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        result = validate_inputs(
            analyze_diffs="true",
            diff_exclude_patterns="**/*.lock,**/node_modules/**",
            diff_max_files="50",
            diff_max_total_lines="5000",
        )
        assert result.valid is True
        assert result.errors == []

    def test_invalid_analyze_diffs_in_validate_inputs(self, tmp_path, monkeypatch):
        """Invalid analyze_diffs should fail in validate_inputs."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        result = validate_inputs(
            analyze_diffs="yes",
        )
        assert result.valid is False
        assert any("must be 'true' or 'false'" in e for e in result.errors)

    def test_invalid_diff_max_files_in_validate_inputs(self, tmp_path, monkeypatch):
        """Invalid diff_max_files should fail in validate_inputs."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        result = validate_inputs(
            diff_max_files="-10",
        )
        assert result.valid is False
        assert any("must be non-negative" in e for e in result.errors)

    def test_invalid_diff_max_total_lines_in_validate_inputs(self, tmp_path, monkeypatch):
        """Invalid diff_max_total_lines should fail in validate_inputs."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        result = validate_inputs(
            diff_max_total_lines="invalid",
        )
        assert result.valid is False
        assert any("must be an integer" in e for e in result.errors)

    def test_invalid_diff_exclude_patterns_in_validate_inputs(self, tmp_path, monkeypatch):
        """Invalid diff_exclude_patterns should fail in validate_inputs."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        result = validate_inputs(
            diff_exclude_patterns="../../etc/passwd",
        )
        assert result.valid is False
        assert any("path traversal" in e.lower() for e in result.errors)

    def test_multiple_invalid_diff_params(self, tmp_path, monkeypatch):
        """Multiple invalid parameters should all be reported."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        result = validate_inputs(
            analyze_diffs="maybe",
            diff_max_files="-5",
            diff_max_total_lines="lots",
        )
        assert result.valid is False
        assert len(result.errors) == 3


class TestRealWorldPatterns:
    """Tests with real-world-like patterns."""

    def test_common_exclusion_patterns(self):
        """Common, legitimate exclusion patterns should work."""
        patterns = [
            "**/*.lock",
            "**/package-lock.json",
            "**/yarn.lock",
            "**/Cargo.lock",
            "**/poetry.lock",
            "**/vendor/**",
            "**/node_modules/**",
            "**/*.generated.*",
            "**/generated/**",
            "**/*.min.js",
            "**/*.min.css",
        ]
        for pattern in patterns:
            errors = validate_diff_exclude_patterns(pattern)
            assert errors == [], f"Pattern '{pattern}' should be valid but got: {errors}"

    def test_migration_file_patterns(self):
        """Database migration patterns should work."""
        patterns = [
            "**/migrations/*.py",
            "**/db/migrations/*",
            "**/*.sql",
        ]
        for pattern in patterns:
            errors = validate_diff_exclude_patterns(pattern)
            assert errors == [], f"Pattern '{pattern}' should be valid"

    def test_test_file_patterns(self):
        """Test file patterns should work."""
        patterns = [
            "**/test_*.py",
            "**/*_test.go",
            "**/tests/**",
            "**/__tests__/**",
        ]
        for pattern in patterns:
            errors = validate_diff_exclude_patterns(pattern)
            assert errors == [], f"Pattern '{pattern}' should be valid"
