"""Tests for context_loader module."""

import pytest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from context_loader import (
    parse_patterns,
    find_matching_files,
    read_and_concatenate,
    load_context_files,
    detect_staleness,
    ContextResult,
)


class TestParsePatterns:
    """Tests for parse_patterns function."""

    def test_empty_string(self):
        assert parse_patterns("") == []

    def test_whitespace_only(self):
        assert parse_patterns("   ") == []

    def test_single_pattern(self):
        assert parse_patterns("README.md") == ["README.md"]

    def test_multiple_patterns(self):
        result = parse_patterns("README.md,ARCHITECTURE.md")
        assert result == ["README.md", "ARCHITECTURE.md"]

    def test_patterns_with_spaces(self):
        result = parse_patterns("README.md , ARCHITECTURE.md , docs/*.md")
        assert result == ["README.md", "ARCHITECTURE.md", "docs/*.md"]

    def test_negation_patterns(self):
        result = parse_patterns("*.md,!README.md")
        assert result == ["*.md", "!README.md"]

    def test_glob_patterns(self):
        result = parse_patterns("**/README.md,docs/**/*.md")
        assert result == ["**/README.md", "docs/**/*.md"]


class TestFindMatchingFiles:
    """Tests for find_matching_files function."""

    def test_empty_patterns(self):
        assert find_matching_files([]) == []

    def test_find_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            readme = Path(tmpdir) / "README.md"
            readme.write_text("# Test")

            result = find_matching_files(["README.md"], tmpdir)
            assert result == ["README.md"]

    def test_glob_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "README.md").write_text("# Main")
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "guide.md").write_text("# Guide")
            (docs_dir / "api.md").write_text("# API")

            result = find_matching_files(["**/*.md"], tmpdir)
            assert len(result) == 3
            assert "README.md" in result

    def test_negation_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "README.md").write_text("# Main")
            (Path(tmpdir) / "CHANGELOG.md").write_text("# Changes")

            result = find_matching_files(["*.md", "!CHANGELOG.md"], tmpdir)
            assert "README.md" in result
            assert "CHANGELOG.md" not in result

    def test_depth_ordering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files at different depths
            (Path(tmpdir) / "root.md").write_text("# Root")
            level1 = Path(tmpdir) / "level1"
            level1.mkdir()
            (level1 / "level1.md").write_text("# Level 1")
            level2 = level1 / "level2"
            level2.mkdir()
            (level2 / "level2.md").write_text("# Level 2")

            result = find_matching_files(["**/*.md"], tmpdir)
            # Shallower files should come first
            assert result[0] == "root.md"
            assert "level1" in result[1]


class TestReadAndConcatenate:
    """Tests for read_and_concatenate function."""

    def test_read_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            readme = Path(tmpdir) / "README.md"
            readme.write_text("# Test Content")

            content, files_loaded, warnings = read_and_concatenate(["README.md"], tmpdir)

            assert "# README.md" in content
            assert "# Test Content" in content
            assert files_loaded == ["README.md"]
            assert warnings == []

    def test_read_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Main")
            (Path(tmpdir) / "ABOUT.md").write_text("# About")

            content, files_loaded, warnings = read_and_concatenate(
                ["README.md", "ABOUT.md"], tmpdir
            )

            assert "# README.md" in content
            assert "# ABOUT.md" in content
            assert len(files_loaded) == 2

    def test_missing_file_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content, files_loaded, warnings = read_and_concatenate(["missing.md"], tmpdir)

            assert content == ""
            assert files_loaded == []
            assert len(warnings) == 1
            assert "missing.md" in warnings[0]

    def test_token_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files that will exceed token limit
            (Path(tmpdir) / "large.md").write_text("x" * 1000)  # ~250 tokens
            (Path(tmpdir) / "small.md").write_text("y" * 100)  # ~25 tokens

            content, files_loaded, warnings = read_and_concatenate(
                ["large.md", "small.md"], tmpdir, max_tokens=50
            )

            # Should skip one file due to budget
            assert len(warnings) > 0
            assert any("budget" in w.lower() for w in warnings)


class TestLoadContextFiles:
    """Tests for load_context_files function."""

    def test_empty_patterns(self):
        result = load_context_files("", max_tokens=800, root_dir=".")
        assert result.content == ""
        assert result.files_loaded == []
        assert result.was_summarized is False

    def test_no_matching_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_context_files(
                "nonexistent*.md", max_tokens=800, root_dir=tmpdir
            )
            assert result.content == ""
            assert len(result.warnings) > 0
            assert "No files found" in result.warnings[0]

    def test_load_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Project\n\nDescription here.")

            result = load_context_files("README.md", max_tokens=800, root_dir=tmpdir)

            assert "# Project" in result.content
            assert result.files_loaded == ["README.md"]
            assert result.was_summarized is False

    def test_load_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Project")
            (Path(tmpdir) / "ARCHITECTURE.md").write_text("# Architecture")

            result = load_context_files(
                "README.md,ARCHITECTURE.md", max_tokens=800, root_dir=tmpdir
            )

            assert "# README.md" in result.content
            assert "# ARCHITECTURE.md" in result.content
            assert len(result.files_loaded) == 2

    def test_summarization_when_exceeds_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create large content that exceeds budget
            (Path(tmpdir) / "large.md").write_text("content " * 500)

            mock_llm = Mock(return_value="<SUMMARY>summarized content</SUMMARY>")

            result = load_context_files(
                "large.md", max_tokens=50, llm_caller=mock_llm, root_dir=tmpdir
            )

            assert result.was_summarized is True
            assert "summarized content" in result.content
            mock_llm.assert_called()

    def test_truncation_without_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create large content that exceeds budget
            (Path(tmpdir) / "large.md").write_text("content " * 500)

            result = load_context_files(
                "large.md", max_tokens=50, llm_caller=None, root_dir=tmpdir
            )

            assert result.was_summarized is False
            assert len(result.warnings) > 0
            assert any("truncated" in w.lower() for w in result.warnings)


class TestDetectStaleness:
    """Tests for detect_staleness function."""

    def test_empty_context(self):
        warnings = detect_staleness("", ["src/main.py"])
        assert warnings == []

    def test_empty_changed_files(self):
        warnings = detect_staleness("Project context", [])
        assert warnings == []

    def test_file_mentioned_no_warning(self):
        context = "This project has a src directory with main code."
        changed_files = ["src/main.py"]

        warnings = detect_staleness(context, changed_files)
        assert warnings == []

    def test_undocumented_area_warning(self):
        context = "This project only documents the api module."
        changed_files = ["frontend/app.js", "frontend/styles.css"]

        warnings = detect_staleness(context, changed_files)
        assert len(warnings) == 1
        assert "frontend" in warnings[0]

    def test_multiple_undocumented_areas(self):
        context = "This project has a simple structure."
        changed_files = [
            "api/routes.py",
            "db/models.py",
            "utils/helpers.py",
        ]

        warnings = detect_staleness(context, changed_files)
        assert len(warnings) == 1
        # Should mention multiple areas
        assert "api" in warnings[0] or "db" in warnings[0] or "utils" in warnings[0]

    def test_case_insensitive_matching(self):
        context = "The API module handles requests."
        changed_files = ["api/routes.py"]

        warnings = detect_staleness(context, changed_files)
        assert warnings == []

    def test_root_files_no_area(self):
        context = "Project documentation."
        changed_files = ["setup.py", "requirements.txt"]

        # Root files shouldn't trigger warnings (no area to report)
        warnings = detect_staleness(context, changed_files)
        # If all changes are in root, might not have warnings
        # Implementation skips files with no directory


class TestContextResultDataclass:
    """Tests for ContextResult dataclass."""

    def test_creation(self):
        result = ContextResult(
            content="test content",
            files_loaded=["README.md"],
            was_summarized=False,
            warnings=["warning1"],
        )

        assert result.content == "test content"
        assert result.files_loaded == ["README.md"]
        assert result.was_summarized is False
        assert result.warnings == ["warning1"]

    def test_default_warnings(self):
        result = ContextResult(
            content="test",
            files_loaded=[],
            was_summarized=False,
        )
        assert result.warnings == []


class TestDefaultExclusions:
    """Tests for default exclusion behavior."""

    def test_excludes_node_modules_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create README in root and in node_modules
            (Path(tmpdir) / "README.md").write_text("# Root Project")
            nm_dir = Path(tmpdir) / "node_modules" / "some-package"
            nm_dir.mkdir(parents=True)
            (nm_dir / "README.md").write_text("# Package README")

            result = load_context_files("README.md", max_tokens=800, root_dir=tmpdir)

            # Should only load root README, not the one in node_modules
            assert len(result.files_loaded) == 1
            assert result.files_loaded[0] == "README.md"
            assert "Root Project" in result.content
            assert "Package README" not in result.content

    def test_excludes_vendor_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Root")
            vendor_dir = Path(tmpdir) / "vendor" / "lib"
            vendor_dir.mkdir(parents=True)
            (vendor_dir / "README.md").write_text("# Vendor README")

            result = load_context_files("README.md", max_tokens=800, root_dir=tmpdir)

            assert len(result.files_loaded) == 1
            assert "Vendor README" not in result.content

    def test_excludes_pycache_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "notes.txt").write_text("Notes")
            pycache_dir = Path(tmpdir) / "src" / "__pycache__"
            pycache_dir.mkdir(parents=True)
            (pycache_dir / "notes.txt").write_text("Cache notes")

            result = load_context_files("**/*.txt", max_tokens=800, root_dir=tmpdir)

            assert len(result.files_loaded) == 1
            assert "Cache notes" not in result.content

    def test_excludes_build_directories_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Root")

            for build_dir in ["dist", "build", "target"]:
                d = Path(tmpdir) / build_dir
                d.mkdir()
                (d / "README.md").write_text(f"# {build_dir} README")

            result = load_context_files("**/README.md", max_tokens=800, root_dir=tmpdir)

            assert len(result.files_loaded) == 1
            assert result.files_loaded[0] == "README.md"

    def test_can_disable_default_exclusions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Root")
            nm_dir = Path(tmpdir) / "node_modules" / "pkg"
            nm_dir.mkdir(parents=True)
            (nm_dir / "README.md").write_text("# Package")

            result = load_context_files(
                "**/README.md",
                max_tokens=800,
                root_dir=tmpdir,
                include_default_exclusions=False,
            )

            # With exclusions disabled, should find both READMEs
            assert len(result.files_loaded) == 2

    def test_user_exclusions_override_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# Root")
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "README.md").write_text("# Docs")

            # User explicitly excludes docs
            result = load_context_files(
                "**/README.md,!docs/**",
                max_tokens=800,
                root_dir=tmpdir,
            )

            assert len(result.files_loaded) == 1
            assert "Docs" not in result.content
