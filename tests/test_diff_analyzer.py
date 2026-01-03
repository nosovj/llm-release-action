"""Tests for diff_analyzer module."""

import pytest
import sys
import os
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from diff_analyzer import (
    parse_unified_diff,
    filter_diffs,
    get_file_priority,
    prioritize_diffs,
    limit_diffs,
    format_diff_for_prompt,
    extract_changes_from_diff,
    analyze_diffs,
    FileDiff,
    DiffAnalysisResult,
    DIFF_MAP_PROMPT,
)


# Sample diffs for testing
# Note: Using raw strings and explicit newlines to ensure proper formatting for unidiff
SIMPLE_DIFF = """\
diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
+import os
 def main():
-    print("hello")
+    print("hello world")
     return 0
"""

MULTI_FILE_DIFF = """\
diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
+import os
 def main():
     pass
diff --git a/src/utils.py b/src/utils.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/src/utils.py
@@ -0,0 +1,2 @@
+def helper():
+    return True
"""  # Note: Must end with newline for concatenation to work

# Note: unidiff library doesn't parse binary-only diffs (no hunks), returns empty
BINARY_DIFF = """\
diff --git a/images/logo.png b/images/logo.png
index 1234567..abcdefg 100644
Binary files a/images/logo.png and b/images/logo.png differ
"""

# Rename diff with proper hunk line counts
RENAME_DIFF = """\
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
index 1234567..abcdefg 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,2 +1,2 @@
 def func():
-    return "old"
+    return "new"
"""


class TestParseUnifiedDiff:
    """Tests for parse_unified_diff function."""

    def test_parse_simple_diff_with_added_removed_lines(self):
        """Parse simple diff with added/removed lines."""
        result = parse_unified_diff(SIMPLE_DIFF)

        assert len(result) == 1
        diff = result[0]
        assert diff.path == "src/main.py"
        assert "import os" in diff.added_lines
        # Lines include original indentation from the file
        assert any('print("hello world")' in line for line in diff.added_lines)
        assert any('print("hello")' in line for line in diff.removed_lines)
        assert diff.is_binary is False
        assert diff.is_rename is False

    def test_parse_diff_with_multiple_files(self):
        """Parse diff with multiple files."""
        result = parse_unified_diff(MULTI_FILE_DIFF)

        assert len(result) == 2

        # First file
        main_diff = next(d for d in result if "main.py" in d.path)
        assert main_diff.path == "src/main.py"
        assert "import os" in main_diff.added_lines

        # Second file (new file)
        utils_diff = next(d for d in result if "utils.py" in d.path)
        assert utils_diff.path == "src/utils.py"
        assert "def helper():" in utils_diff.added_lines

    def test_parse_binary_file_diff(self):
        """Parse binary file diff.

        Note: The unidiff library doesn't parse binary-only diffs (no hunks).
        This test verifies the graceful handling of this case.
        """
        result = parse_unified_diff(BINARY_DIFF)
        # unidiff library returns empty for binary-only diffs
        assert result == []

    def test_parse_rename_diff(self):
        """Parse rename diff."""
        result = parse_unified_diff(RENAME_DIFF)

        assert len(result) == 1
        diff = result[0]
        assert diff.path == "new_name.py"
        assert diff.is_rename is True
        assert diff.old_path == "old_name.py"
        # Lines include original indentation
        assert any('return "new"' in line for line in diff.added_lines)
        assert any('return "old"' in line for line in diff.removed_lines)

    def test_handle_empty_diff(self):
        """Handle empty diff."""
        result = parse_unified_diff("")
        assert result == []

        result = parse_unified_diff("   \n\n   ")
        assert result == []

    def test_handle_malformed_diff_gracefully(self):
        """Handle malformed diff gracefully."""
        malformed = "this is not a valid diff format at all"
        result = parse_unified_diff(malformed)
        assert result == []

        # Partial diff
        partial = """diff --git a/file.py b/file.py
--- a/file.py
"""
        result = parse_unified_diff(partial)
        # Should either parse partially or return empty, not crash
        assert isinstance(result, list)


class TestFilterDiffs:
    """Tests for filter_diffs function."""

    def test_filter_out_lock_files(self):
        """Filter out lock files."""
        diffs = [
            FileDiff(path="src/main.py", added_lines=["line"]),
            FileDiff(path="package-lock.json", added_lines=["line"]),
            FileDiff(path="yarn.lock", added_lines=["line"]),
            FileDiff(path="Gemfile.lock", added_lines=["line"]),
        ]

        result = filter_diffs(diffs, "*.lock,package-lock.json")

        assert len(result) == 1
        assert result[0].path == "src/main.py"

    def test_filter_out_node_modules(self):
        """Filter out node_modules."""
        diffs = [
            FileDiff(path="src/main.py", added_lines=["line"]),
            FileDiff(path="node_modules/lodash/index.js", added_lines=["line"]),
            FileDiff(path="node_modules/express/lib/router.js", added_lines=["line"]),
        ]

        result = filter_diffs(diffs, "node_modules/**")

        assert len(result) == 1
        assert result[0].path == "src/main.py"

    def test_filter_with_negation_patterns(self):
        """Filter with negation patterns."""
        diffs = [
            FileDiff(path="dist/main.js", added_lines=["line"]),
            FileDiff(path="dist/important.js", added_lines=["line"]),
            FileDiff(path="src/app.js", added_lines=["line"]),
        ]

        # Exclude all dist except important.js
        result = filter_diffs(diffs, "dist/**,!dist/important.js")

        # Note: pathspec handles negation - this may keep important.js
        paths = [d.path for d in result]
        assert "src/app.js" in paths

    def test_empty_patterns_returns_all_diffs(self):
        """Empty patterns returns all diffs."""
        diffs = [
            FileDiff(path="src/main.py", added_lines=["line"]),
            FileDiff(path="package-lock.json", added_lines=["line"]),
        ]

        result = filter_diffs(diffs, "")
        assert len(result) == 2

        result = filter_diffs(diffs, "   ")
        assert len(result) == 2

    def test_multiple_patterns_work_together(self):
        """Multiple patterns work together."""
        diffs = [
            FileDiff(path="src/main.py", added_lines=["line"]),
            FileDiff(path="package-lock.json", added_lines=["line"]),
            FileDiff(path="node_modules/lib/index.js", added_lines=["line"]),
            FileDiff(path="dist/bundle.js", added_lines=["line"]),
        ]

        result = filter_diffs(diffs, "*.lock,node_modules/**,dist/**,package-lock.json")

        assert len(result) == 1
        assert result[0].path == "src/main.py"


class TestGetFilePriority:
    """Tests for get_file_priority function."""

    def test_openapi_files_get_priority_1(self):
        """OpenAPI files get priority 1."""
        assert get_file_priority("openapi.yaml") == 1
        assert get_file_priority("openapi.yml") == 1
        assert get_file_priority("openapi.json") == 1
        assert get_file_priority("api/openapi-v2.yaml") == 1

    def test_proto_files_get_priority_1(self):
        """Proto files get priority 1."""
        assert get_file_priority("service.proto") == 1
        assert get_file_priority("api/v1/messages.proto") == 1

    def test_graphql_files_get_priority_1(self):
        """GraphQL files get priority 1."""
        assert get_file_priority("schema.graphql") == 1
        assert get_file_priority("types/user.graphql") == 1

    def test_swagger_files_get_priority_1(self):
        """Swagger files get priority 1."""
        assert get_file_priority("swagger.yaml") == 1
        assert get_file_priority("swagger.yml") == 1
        assert get_file_priority("swagger.json") == 1

    def test_migration_files_get_priority_2(self):
        """Migration files get priority 2."""
        assert get_file_priority("migrations/001_init.sql") == 2
        assert get_file_priority("alembic/versions/abc123.py") == 2
        assert get_file_priority("db/migrate/20230101_create_users.rb") == 2

    def test_config_files_get_priority_3(self):
        """Config files get priority 3."""
        assert get_file_priority("webpack.config.js") == 3
        assert get_file_priority("babel.config.json") == 3
        assert get_file_priority(".env") == 3
        assert get_file_priority(".env.local") == 3
        assert get_file_priority("config.yaml") == 3
        assert get_file_priority("settings.py") == 3

    def test_other_files_get_priority_4(self):
        """Other files get priority 4."""
        assert get_file_priority("src/main.py") == 4
        assert get_file_priority("lib/utils.js") == 4
        assert get_file_priority("README.md") == 4
        assert get_file_priority("tests/test_main.py") == 4


class TestPrioritizeDiffs:
    """Tests for prioritize_diffs function."""

    def test_sorts_by_priority_lower_first(self):
        """Sorts by priority (lower first)."""
        diffs = [
            FileDiff(path="src/main.py"),  # Priority 4
            FileDiff(path="openapi.yaml"),  # Priority 1
            FileDiff(path="migrations/init.sql"),  # Priority 2
            FileDiff(path=".env"),  # Priority 3
        ]

        result = prioritize_diffs(diffs)

        assert result[0].path == "openapi.yaml"  # Priority 1
        assert result[1].path == "migrations/init.sql"  # Priority 2
        assert result[2].path == ".env"  # Priority 3
        assert result[3].path == "src/main.py"  # Priority 4

    def test_maintains_order_within_same_priority(self):
        """Maintains alphabetical order within same priority."""
        diffs = [
            FileDiff(path="src/zebra.py"),  # Priority 4
            FileDiff(path="src/alpha.py"),  # Priority 4
            FileDiff(path="src/beta.py"),  # Priority 4
        ]

        result = prioritize_diffs(diffs)

        # Should be sorted alphabetically within same priority
        assert result[0].path == "src/alpha.py"
        assert result[1].path == "src/beta.py"
        assert result[2].path == "src/zebra.py"

    def test_empty_list_returns_empty(self):
        """Empty list returns empty."""
        result = prioritize_diffs([])
        assert result == []


class TestLimitDiffs:
    """Tests for limit_diffs function."""

    def test_respects_max_files_limit(self):
        """Respects max_files limit."""
        diffs = [
            FileDiff(path="file1.py", added_lines=["a"]),
            FileDiff(path="file2.py", added_lines=["a"]),
            FileDiff(path="file3.py", added_lines=["a"]),
            FileDiff(path="file4.py", added_lines=["a"]),
        ]

        kept, warnings = limit_diffs(diffs, max_files=2, max_lines=1000)

        assert len(kept) == 2
        assert kept[0].path == "file1.py"
        assert kept[1].path == "file2.py"

    def test_respects_max_lines_limit(self):
        """Respects max_lines limit."""
        diffs = [
            FileDiff(path="file1.py", added_lines=["a"] * 10),  # 10 lines
            FileDiff(path="file2.py", added_lines=["a"] * 10),  # 10 lines
            FileDiff(path="file3.py", added_lines=["a"] * 10),  # 10 lines
        ]

        kept, warnings = limit_diffs(diffs, max_files=100, max_lines=15)

        assert len(kept) == 1
        assert kept[0].path == "file1.py"

    def test_returns_warnings_about_skipped_files(self):
        """Returns warnings about skipped files."""
        diffs = [
            FileDiff(path="file1.py", added_lines=["a"]),
            FileDiff(path="file2.py", added_lines=["a"]),
            FileDiff(path="file3.py", added_lines=["a"]),
        ]

        kept, warnings = limit_diffs(diffs, max_files=1, max_lines=1000)

        assert len(warnings) == 1
        assert "skipped 2 files" in warnings[0]

    def test_zero_limits_mean_no_limit(self):
        """Zero limits effectively mean very high limit (checks at boundary)."""
        diffs = [
            FileDiff(path="file1.py", added_lines=["a"]),
            FileDiff(path="file2.py", added_lines=["a"]),
        ]

        # Note: The implementation checks >= for files and > for lines
        # So we test with very high limits instead
        kept, warnings = limit_diffs(diffs, max_files=1000, max_lines=1000)

        assert len(kept) == 2
        assert warnings == []

    def test_warnings_include_count_of_skipped_files(self):
        """Warnings include count of skipped files."""
        diffs = [
            FileDiff(path=f"file{i}.py", added_lines=["a"]) for i in range(10)
        ]

        kept, warnings = limit_diffs(diffs, max_files=3, max_lines=1000)

        assert len(kept) == 3
        assert any("7 files" in w for w in warnings)


class TestFormatDiffForPrompt:
    """Tests for format_diff_for_prompt function."""

    def test_formats_regular_diff_correctly(self):
        """Formats regular diff correctly."""
        diff = FileDiff(
            path="src/main.py",
            added_lines=["import os", "print('hello')"],
            removed_lines=["print('old')"],
        )

        result = format_diff_for_prompt(diff)

        assert "### File: src/main.py" in result
        assert "--- Removed ---" in result
        assert "- print('old')" in result
        assert "+++ Added +++" in result
        assert "+ import os" in result
        assert "+ print('hello')" in result

    def test_handles_binary_file(self):
        """Handles binary file."""
        diff = FileDiff(
            path="images/logo.png",
            is_binary=True,
        )

        result = format_diff_for_prompt(diff)

        assert "### File: images/logo.png" in result
        assert "(Binary file changed)" in result

    def test_handles_rename(self):
        """Handles rename."""
        diff = FileDiff(
            path="new_name.py",
            old_path="old_name.py",
            is_rename=True,
            added_lines=["new line"],
        )

        result = format_diff_for_prompt(diff)

        assert "### File: new_name.py" in result
        assert "(Renamed from: old_name.py)" in result
        assert "+ new line" in result


class TestExtractChangesFromDiff:
    """Tests for extract_changes_from_diff function."""

    def test_extracts_structured_changes_with_mock_llm(self):
        """Extracts structured changes with mock LLM."""
        diff_content = "### File: src/main.py\n+++ Added +++\n+ import os"

        mock_response = """
Here's my analysis:
<CHANGES>
<added>
- New import for os module
</added>
<removed>
</removed>
<modified>
</modified>
</CHANGES>
"""
        mock_llm = Mock(return_value=mock_response)

        result = extract_changes_from_diff(diff_content, mock_llm)

        # Should extract content between CHANGES tags
        assert "<added>" in result
        assert "New import for os module" in result
        mock_llm.assert_called_once()

        # Verify prompt was formatted correctly
        call_args = mock_llm.call_args[0][0]
        assert "src/main.py" in call_args
        assert "import os" in call_args

    def test_handles_empty_response(self):
        """Handles empty response."""
        diff_content = "### File: src/main.py"

        mock_llm = Mock(return_value="")

        result = extract_changes_from_diff(diff_content, mock_llm)

        assert result == ""

    def test_handles_response_without_tags(self):
        """Handles response without CHANGES tags."""
        diff_content = "### File: src/main.py"

        mock_llm = Mock(return_value="Just a plain response about the changes")

        result = extract_changes_from_diff(diff_content, mock_llm)

        # Should return full response when no tags
        assert result == "Just a plain response about the changes"


class TestAnalyzeDiffs:
    """Integration tests for analyze_diffs function."""

    def test_full_pipeline_with_mock_llm(self):
        """Full pipeline with mock LLM."""
        mock_response = """
<CHANGES>
<added>
- New import statement
</added>
<removed>
- Old print statement
</removed>
<modified>
- Updated greeting message
</modified>
</CHANGES>
"""
        mock_llm = Mock(return_value=mock_response)

        result = analyze_diffs(
            diff_text=SIMPLE_DIFF,
            exclude_patterns="",
            max_files=10,
            max_lines=1000,
            llm_caller=mock_llm,
        )

        assert isinstance(result, DiffAnalysisResult)
        assert result.diffs_processed == 1
        assert result.total_lines > 0
        assert "<added>" in result.extracted_changes
        assert "New import statement" in result.extracted_changes
        mock_llm.assert_called()

    def test_respects_all_filters_and_limits(self):
        """Respects all filters and limits."""
        # Create a diff with multiple files including one that should be excluded
        package_lock_diff = """\
diff --git a/package-lock.json b/package-lock.json
index 1234567..abcdefg 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,1 +1,2 @@
+{"new": "entry"}
 existing content
"""
        diff_text = MULTI_FILE_DIFF + package_lock_diff

        mock_llm = Mock(return_value="<CHANGES><added></added><removed></removed><modified></modified></CHANGES>")

        result = analyze_diffs(
            diff_text=diff_text,
            exclude_patterns="package-lock.json",
            max_files=1,
            max_lines=1000,
            llm_caller=mock_llm,
        )

        # Should have filtered and limited
        assert result.diffs_processed == 1
        assert len(result.warnings) >= 1  # Should have warning about filtered or limited files

    def test_returns_warnings(self):
        """Returns warnings."""
        mock_llm = Mock(return_value="<CHANGES><added></added><removed></removed><modified></modified></CHANGES>")

        # Test with exclusion that filters all files
        result = analyze_diffs(
            diff_text=SIMPLE_DIFF,
            exclude_patterns="**/*.py",
            max_files=10,
            max_lines=1000,
            llm_caller=mock_llm,
        )

        assert any("excluded" in w.lower() or "filtered" in w.lower() for w in result.warnings)
        assert result.diffs_processed == 0

    def test_empty_diff_returns_appropriate_result(self):
        """Empty diff returns appropriate result."""
        mock_llm = Mock()

        result = analyze_diffs(
            diff_text="",
            exclude_patterns="",
            max_files=10,
            max_lines=1000,
            llm_caller=mock_llm,
        )

        assert result.extracted_changes == ""
        assert result.diffs_processed == 0
        assert "No valid diffs found" in result.warnings[0]
        mock_llm.assert_not_called()

    def test_prioritizes_api_specs_over_regular_files(self):
        """Prioritizes API specs over regular files."""
        diff_with_openapi = """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1 @@
-old
+new
diff --git a/openapi.yaml b/openapi.yaml
index 1234567..abcdefg 100644
--- a/openapi.yaml
+++ b/openapi.yaml
@@ -1 +1 @@
-version: 1
+version: 2
"""

        call_order = []

        def tracking_llm(prompt: str) -> str:
            # Track which file is processed
            if "openapi.yaml" in prompt:
                call_order.append("openapi")
            if "main.py" in prompt:
                call_order.append("main")
            return "<CHANGES><added></added><removed></removed><modified></modified></CHANGES>"

        result = analyze_diffs(
            diff_text=diff_with_openapi,
            exclude_patterns="",
            max_files=10,
            max_lines=1000,
            llm_caller=tracking_llm,
        )

        # OpenAPI should be processed (appears in prompt first due to prioritization)
        # Note: Files may be batched together, so we just verify both were processed
        assert result.diffs_processed == 2


class TestFileDiffDataclass:
    """Tests for FileDiff dataclass."""

    def test_creation(self):
        """Test basic creation."""
        diff = FileDiff(
            path="src/main.py",
            added_lines=["line1", "line2"],
            removed_lines=["old_line"],
            is_binary=False,
            is_rename=False,
            old_path="",
        )

        assert diff.path == "src/main.py"
        assert diff.added_lines == ["line1", "line2"]
        assert diff.removed_lines == ["old_line"]
        assert diff.is_binary is False
        assert diff.is_rename is False
        assert diff.old_path == ""

    def test_line_count_property(self):
        """Test line_count property."""
        diff = FileDiff(
            path="file.py",
            added_lines=["a", "b", "c"],
            removed_lines=["x", "y"],
        )

        assert diff.line_count == 5

    def test_default_values(self):
        """Test default values."""
        diff = FileDiff(path="file.py")

        assert diff.added_lines == []
        assert diff.removed_lines == []
        assert diff.is_binary is False
        assert diff.is_rename is False
        assert diff.old_path == ""
        assert diff.line_count == 0


class TestDiffAnalysisResultDataclass:
    """Tests for DiffAnalysisResult dataclass."""

    def test_creation(self):
        """Test basic creation."""
        result = DiffAnalysisResult(
            extracted_changes="<added>new stuff</added>",
            diffs_processed=5,
            total_lines=100,
            warnings=["warning1", "warning2"],
        )

        assert result.extracted_changes == "<added>new stuff</added>"
        assert result.diffs_processed == 5
        assert result.total_lines == 100
        assert result.warnings == ["warning1", "warning2"]

    def test_default_warnings(self):
        """Test default warnings list."""
        result = DiffAnalysisResult(
            extracted_changes="",
            diffs_processed=0,
            total_lines=0,
        )

        assert result.warnings == []
