"""Tests for ReDoS (Regular Expression Denial of Service) protection.

Tests cover:
1. Pattern safety validation (detecting ReDoS-prone patterns)
2. Safe pattern compilation with timeout
3. Pattern length limits
4. Integration with filter_changes()
"""

import pytest
import sys
import os
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from input_validation import (
    MAX_PATTERN_LENGTH,
    REGEX_TIMEOUT,
    PatternCompilationError,
    PatternTimeoutError,
    validate_pattern_safety,
    safe_compile_pattern,
    validate_filter_value,
)


class TestValidatePatternSafety:
    """Tests for validate_pattern_safety function."""

    def test_safe_simple_pattern(self):
        """Simple patterns should pass validation."""
        assert validate_pattern_safety("hello") == []
        assert validate_pattern_safety("fix|bug") == []
        assert validate_pattern_safety("^start") == []
        assert validate_pattern_safety("end$") == []

    def test_safe_pattern_with_single_quantifier(self):
        """Patterns with single quantifiers should be safe."""
        assert validate_pattern_safety("a+") == []
        assert validate_pattern_safety("a*") == []
        assert validate_pattern_safety("a?") == []
        assert validate_pattern_safety("[a-z]+") == []

    def test_nested_quantifier_detected(self):
        """Nested quantifiers should be detected as unsafe."""
        # Classic ReDoS patterns
        errors = validate_pattern_safety("(a+)+")
        assert len(errors) > 0
        assert "nested quantifiers" in errors[0].lower()

        errors = validate_pattern_safety("(a*)+")
        assert len(errors) > 0

        errors = validate_pattern_safety("(a+)*")
        assert len(errors) > 0

    def test_nested_quantifier_with_count(self):
        """Nested quantifiers with counts should be detected."""
        errors = validate_pattern_safety("(a{2,})+")
        assert len(errors) > 0

        errors = validate_pattern_safety("(a+){2,}")
        assert len(errors) > 0

    def test_overlapping_alternation_detected(self):
        """Overlapping alternations should be detected as unsafe."""
        # Pattern where one alternative is prefix of another
        errors = validate_pattern_safety("(a|ab)+")
        assert len(errors) > 0
        assert "overlapping" in errors[0].lower()

    def test_multiple_unbounded_wildcards_detected(self):
        """Multiple unbounded wildcards without anchoring should be detected."""
        errors = validate_pattern_safety(".*foo.*")
        assert len(errors) > 0
        assert "wildcards" in errors[0].lower()

        errors = validate_pattern_safety(".+bar.+")
        assert len(errors) > 0

    def test_anchored_wildcards_safe(self):
        """Anchored wildcards should be safe."""
        assert validate_pattern_safety("^.*foo.*$") == []

    def test_pattern_too_long(self):
        """Patterns exceeding max length should be rejected."""
        long_pattern = "a" * (MAX_PATTERN_LENGTH + 1)
        errors = validate_pattern_safety(long_pattern)
        assert len(errors) == 1
        assert "too long" in errors[0].lower()

    def test_pattern_at_max_length(self):
        """Patterns at exactly max length should be allowed."""
        max_pattern = "a" * MAX_PATTERN_LENGTH
        errors = validate_pattern_safety(max_pattern)
        # Should not have length error (may have other errors depending on pattern)
        assert not any("too long" in e.lower() for e in errors)


class TestSafeCompilePattern:
    """Tests for safe_compile_pattern function."""

    def test_compile_simple_pattern(self):
        """Simple patterns should compile successfully."""
        pattern = safe_compile_pattern("hello")
        assert pattern is not None
        assert pattern.search("hello world") is not None

    def test_compile_with_flags(self):
        """Patterns should compile with case-insensitive flag."""
        pattern = safe_compile_pattern("HELLO")
        assert pattern.search("hello world") is not None

    def test_reject_nested_quantifier(self):
        """Nested quantifier patterns should be rejected at compile time."""
        with pytest.raises(PatternCompilationError) as exc_info:
            safe_compile_pattern("(a+)+")
        assert "nested quantifiers" in str(exc_info.value).lower()

    def test_reject_invalid_regex(self):
        """Invalid regex syntax should raise PatternCompilationError."""
        with pytest.raises(PatternCompilationError) as exc_info:
            safe_compile_pattern("[unclosed")
        assert "invalid regex" in str(exc_info.value).lower()

    def test_reject_pattern_too_long(self):
        """Patterns exceeding max length should be rejected."""
        long_pattern = "x" * (MAX_PATTERN_LENGTH + 1)
        with pytest.raises(PatternCompilationError) as exc_info:
            safe_compile_pattern(long_pattern)
        assert "too long" in str(exc_info.value).lower()

    def test_timeout_parameter(self):
        """Timeout parameter should be applied to compiled pattern."""
        pattern = safe_compile_pattern("simple", timeout=0.5)
        assert pattern is not None
        # Pattern should work for simple matches
        assert pattern.search("simple text") is not None


class TestValidateFilterValue:
    """Tests for validate_filter_value with pattern validation."""

    def test_regular_value_validation(self):
        """Non-pattern values should be validated normally."""
        errors = validate_filter_value("short", "field_name")
        assert errors == []

    def test_pattern_validation_safe(self):
        """Safe patterns should pass validation."""
        errors = validate_filter_value("fix|bug", "exclude_patterns", is_pattern=True)
        assert errors == []

    def test_pattern_validation_unsafe(self):
        """Unsafe patterns should fail validation with clear error."""
        errors = validate_filter_value("(a+)+", "exclude_patterns", is_pattern=True)
        assert len(errors) > 0
        assert any("nested quantifiers" in e.lower() for e in errors)

    def test_pattern_length_limit_enforced(self):
        """Pattern-specific length limit should be enforced."""
        # Regular values have 100 char limit
        short_value = "a" * 101
        errors = validate_filter_value(short_value, "author")
        assert any("too long" in e.lower() for e in errors)

        # Patterns have MAX_PATTERN_LENGTH limit
        pattern_value = "a" * (MAX_PATTERN_LENGTH + 1)
        errors = validate_filter_value(pattern_value, "pattern", is_pattern=True)
        assert any("too long" in e.lower() for e in errors)

    def test_control_characters_rejected(self):
        """Control characters should be rejected in all values."""
        errors = validate_filter_value("test\x00value", "field")
        assert any("invalid characters" in e.lower() for e in errors)


class TestRealWorldPatterns:
    """Tests with real-world-like patterns that users might provide."""

    def test_common_exclusion_patterns_safe(self):
        """Common, legitimate exclusion patterns should work."""
        safe_patterns = [
            "chore:",  # Conventional commit type
            "^ci:",  # CI commits
            "bot$",  # Bot authors
            "\\[skip ci\\]",  # Skip CI marker
            "deps|dependencies",  # Dependency updates
            "merge branch",  # Merge commits
            "renovate|dependabot",  # Bot names
        ]
        for pattern in safe_patterns:
            errors = validate_pattern_safety(pattern)
            assert errors == [], f"Pattern '{pattern}' should be safe but got: {errors}"

            # Should also compile successfully
            compiled = safe_compile_pattern(pattern)
            assert compiled is not None

    def test_email_pattern_safe(self):
        """Email-like patterns should be safe."""
        pattern = "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"
        errors = validate_pattern_safety(pattern)
        assert errors == []

    def test_version_pattern_safe(self):
        """Version patterns should be safe."""
        pattern = "v?[0-9]+\\.[0-9]+\\.[0-9]+"
        errors = validate_pattern_safety(pattern)
        assert errors == []

    def test_malicious_redos_pattern_rejected(self):
        """Known malicious ReDoS patterns should be rejected."""
        malicious_patterns = [
            "(a+)+$",  # Classic exponential
            "(a|a)+$",  # Overlapping alternation
            "([a-zA-Z]+)*$",  # Nested quantifier on character class
            "(a*)*$",  # Nested star
        ]
        for pattern in malicious_patterns:
            errors = validate_pattern_safety(pattern)
            assert len(errors) > 0, f"Malicious pattern '{pattern}' should be rejected"


class TestPatternCompilationPerformance:
    """Tests to verify pattern compilation doesn't hang."""

    def test_compilation_is_fast(self):
        """Pattern compilation should complete quickly."""
        start = time.time()

        # Compile many patterns quickly
        for _ in range(100):
            try:
                safe_compile_pattern("simple|pattern")
            except PatternCompilationError:
                pass

        elapsed = time.time() - start
        # Should complete in under 1 second for 100 compilations
        assert elapsed < 1.0, f"Compilation took too long: {elapsed}s"

    def test_unsafe_pattern_rejected_immediately(self):
        """Unsafe patterns should be rejected immediately, not hang."""
        start = time.time()

        with pytest.raises(PatternCompilationError):
            safe_compile_pattern("(a+)+")

        elapsed = time.time() - start
        # Should fail almost immediately, not after timeout
        assert elapsed < 0.1, f"Pattern rejection took too long: {elapsed}s"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_pattern(self):
        """Empty pattern should compile (matches everything)."""
        pattern = safe_compile_pattern("")
        assert pattern.search("anything") is not None

    def test_pattern_with_special_regex_chars(self):
        """Patterns with escaped special characters should work."""
        pattern = safe_compile_pattern("\\[test\\]")
        assert pattern.search("[test]") is not None
        assert pattern.search("test") is None

    def test_unicode_pattern(self):
        """Unicode patterns should work."""
        errors = validate_pattern_safety("日本語")
        assert errors == []

        pattern = safe_compile_pattern("日本語")
        assert pattern.search("日本語テスト") is not None

    def test_pattern_with_lookahead(self):
        """Patterns with lookahead should work if safe."""
        # Simple lookahead should be safe
        errors = validate_pattern_safety("foo(?=bar)")
        assert errors == []

    def test_pattern_with_lookbehind(self):
        """Patterns with lookbehind should work if safe."""
        errors = validate_pattern_safety("(?<=foo)bar")
        assert errors == []


class TestFilterChangesIntegration:
    """Integration tests for filter_changes with ReDoS protection."""

    def test_filter_with_safe_patterns(self):
        """filter_changes should work with safe patterns."""
        from changelog import filter_changes
        from config import AudienceConfig
        from models import Change, ChangeCategory

        changes = [
            Change(
                id="change-1",
                title="Add new feature",
                description="A great new feature",
                category=ChangeCategory.FEATURE,
            ),
            Change(
                id="change-2",
                title="chore: update deps",
                description="Dependency update",
                category=ChangeCategory.INFRASTRUCTURE,
            ),
        ]

        config = AudienceConfig(
            name="test",
            sections=["features", "infrastructure"],
            exclude_patterns=["chore:"],  # Safe pattern
        )

        result = filter_changes(changes, config)
        assert len(result) == 1
        assert result[0].title == "Add new feature"

    def test_filter_rejects_unsafe_pattern(self):
        """filter_changes should raise error for unsafe patterns."""
        from changelog import filter_changes
        from config import AudienceConfig
        from models import Change, ChangeCategory

        changes = [
            Change(
                id="change-1",
                title="Test change",
                description="Description",
                category=ChangeCategory.FEATURE,
            ),
        ]

        config = AudienceConfig(
            name="test",
            sections=["features"],
            exclude_patterns=["(a+)+"],  # ReDoS-prone pattern
        )

        with pytest.raises(PatternCompilationError):
            filter_changes(changes, config)

    def test_filter_with_multiple_safe_patterns(self):
        """filter_changes should work with multiple safe patterns."""
        from changelog import filter_changes
        from config import AudienceConfig
        from models import Change, ChangeCategory

        changes = [
            Change(
                id="change-1",
                title="Feature: Add login",
                description="New login feature",
                category=ChangeCategory.FEATURE,
            ),
            Change(
                id="change-2",
                title="chore: cleanup",
                description="Code cleanup",
                category=ChangeCategory.INFRASTRUCTURE,
            ),
            Change(
                id="change-3",
                title="ci: update workflow",
                description="CI update",
                category=ChangeCategory.INFRASTRUCTURE,
            ),
            Change(
                id="change-4",
                title="Fix: resolve bug",
                description="Bug fix",
                category=ChangeCategory.FIX,
            ),
        ]

        config = AudienceConfig(
            name="test",
            sections=["features", "fixes", "infrastructure"],
            exclude_patterns=["^chore:", "^ci:"],  # Multiple safe patterns
        )

        result = filter_changes(changes, config)
        assert len(result) == 2
        assert "Feature: Add login" in [c.title for c in result]
        assert "Fix: resolve bug" in [c.title for c in result]
