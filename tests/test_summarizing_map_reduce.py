"""Tests for summarizing_map_reduce module."""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from summarizing_map_reduce import (
    estimate_tokens,
    fits_budget,
    SummarizingMapReduce,
    SummarizeResult,
    summarize_context,
    CONTEXT_MAP_PROMPT,
    CONTEXT_REDUCE_PROMPT,
)


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # 4 chars = 1 token
        assert estimate_tokens("test") == 1

    def test_longer_string(self):
        # 100 chars = 25 tokens
        assert estimate_tokens("x" * 100) == 25

    def test_typical_sentence(self):
        text = "This is a typical sentence with about 40 characters."
        # Should be roughly 40/4 = 10 tokens
        tokens = estimate_tokens(text)
        assert 10 <= tokens <= 15


class TestFitsBudget:
    """Tests for fits_budget function."""

    def test_empty_string_fits(self):
        assert fits_budget("", 100) is True

    def test_small_text_fits(self):
        assert fits_budget("test", 10) is True

    def test_large_text_exceeds(self):
        # 400 chars = ~100 tokens, should not fit in 50 token budget
        assert fits_budget("x" * 400, 50) is False

    def test_exact_fit(self):
        # 400 chars = ~100 tokens
        assert fits_budget("x" * 400, 100) is True


class TestSummarizingMapReduceInit:
    """Tests for SummarizingMapReduce initialization."""

    def test_default_prompts(self):
        summarizer = SummarizingMapReduce()
        assert summarizer.map_prompt == CONTEXT_MAP_PROMPT
        assert summarizer.reduce_prompt == CONTEXT_REDUCE_PROMPT

    def test_custom_prompts(self):
        custom_map = "Custom map {content}"
        custom_reduce = "Custom reduce {summaries}"
        summarizer = SummarizingMapReduce(
            map_prompt=custom_map,
            reduce_prompt=custom_reduce,
        )
        assert summarizer.map_prompt == custom_map
        assert summarizer.reduce_prompt == custom_reduce

    def test_default_chunk_settings(self):
        summarizer = SummarizingMapReduce()
        assert summarizer.chunk_size == 2000
        assert summarizer.chunk_overlap == 200
        assert summarizer.max_workers == 5


class TestSummarizingMapReducePassthrough:
    """Tests for passthrough behavior when content fits budget."""

    def test_small_content_passthrough(self):
        """Content that fits budget should be returned unchanged."""
        summarizer = SummarizingMapReduce()
        content = "This is small content"

        # Mock LLM caller that should NOT be called
        llm_caller = Mock()

        result = summarizer.summarize_to_budget(content, max_tokens=100, llm_caller=llm_caller)

        assert result.content == content
        assert result.was_summarized is False
        assert result.warnings == []
        llm_caller.assert_not_called()

    def test_passthrough_preserves_original_tokens(self):
        """Passthrough should report same original and final tokens."""
        summarizer = SummarizingMapReduce()
        content = "Test content here"

        result = summarizer.summarize_to_budget(content, max_tokens=100, llm_caller=Mock())

        assert result.original_tokens == result.final_tokens
        assert result.original_tokens == estimate_tokens(content)


class TestSummarizingMapReduceSummarization:
    """Tests for summarization behavior when content exceeds budget."""

    def test_single_chunk_summarization(self):
        """Content that needs summarizing but is a single chunk."""
        summarizer = SummarizingMapReduce(chunk_size=2000)

        # Create content that exceeds 10 token budget (40 chars) but fits in one chunk
        content = "x" * 100  # 25 tokens, exceeds 10 token budget

        # Mock LLM to return shorter summary
        llm_caller = Mock(return_value="<SUMMARY>short</SUMMARY>")

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=llm_caller)

        assert result.was_summarized is True
        assert result.content == "short"
        llm_caller.assert_called_once()

    def test_multi_chunk_map_reduce(self):
        """Content that needs chunking and map/reduce."""
        summarizer = SummarizingMapReduce(chunk_size=100, chunk_overlap=10, max_workers=2)

        # Create content that will be split into multiple chunks
        content = "chunk one " * 20 + "chunk two " * 20  # 400 chars

        # Track calls to verify MAP and REDUCE phases
        call_count = [0]

        def mock_llm(prompt: str) -> str:
            call_count[0] += 1
            if "Extract the KEY FACTS" in prompt:
                return "<SUMMARY>fact from chunk</SUMMARY>"
            else:
                return "<SUMMARY>consolidated facts</SUMMARY>"

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=mock_llm)

        assert result.was_summarized is True
        assert result.content == "consolidated facts"
        # Should have multiple MAP calls plus one REDUCE call
        assert call_count[0] >= 2

    def test_summary_extraction_with_tag(self):
        """Should extract content from <SUMMARY> tags."""
        summarizer = SummarizingMapReduce(chunk_size=2000)
        content = "x" * 100

        llm_caller = Mock(return_value="Some preamble\n<SUMMARY>The actual summary</SUMMARY>\nsome trailing text")

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=llm_caller)

        assert result.content == "The actual summary"

    def test_summary_extraction_without_tag(self):
        """Should use full response if no <SUMMARY> tag."""
        summarizer = SummarizingMapReduce(chunk_size=2000)
        content = "x" * 100

        llm_caller = Mock(return_value="Just a plain response without tags")

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=llm_caller)

        assert result.content == "Just a plain response without tags"

    def test_truncation_when_summary_exceeds_budget(self):
        """Should truncate if summary still exceeds budget."""
        summarizer = SummarizingMapReduce(chunk_size=2000)
        content = "x" * 100

        # Return a summary that's still too long (400 chars = 100 tokens)
        llm_caller = Mock(return_value="<SUMMARY>" + "y" * 400 + "</SUMMARY>")

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=llm_caller)

        assert result.was_summarized is True
        # Should be truncated to fit 10 tokens = 40 chars
        assert len(result.content) <= 40
        assert any("truncated" in w.lower() for w in result.warnings)


class TestSummarizingMapReduceErrorHandling:
    """Tests for error handling in summarization."""

    def test_chunk_failure_continues(self):
        """Should continue if some chunks fail."""
        summarizer = SummarizingMapReduce(chunk_size=100, chunk_overlap=10, max_workers=1)
        content = "chunk one " * 20 + "chunk two " * 20

        call_count = [0]

        def mock_llm(prompt: str) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("First chunk failed")
            if "Extract the KEY FACTS" in prompt:
                return "<SUMMARY>fact from chunk</SUMMARY>"
            return "<SUMMARY>consolidated</SUMMARY>"

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=mock_llm)

        # Should still produce a result
        assert result.content is not None
        assert any("Failed to summarize chunk" in w for w in result.warnings)

    def test_all_chunks_fail_fallback(self):
        """Should fallback to truncation if all chunks fail."""
        summarizer = SummarizingMapReduce(chunk_size=100, chunk_overlap=10, max_workers=1)
        content = "x" * 300  # Will create multiple chunks

        def mock_llm(prompt: str) -> str:
            raise RuntimeError("All calls fail")

        result = summarizer.summarize_to_budget(content, max_tokens=10, llm_caller=mock_llm)

        # Should fallback to truncated original
        assert result.content is not None
        assert result.was_summarized is False
        assert any("falling back" in w.lower() for w in result.warnings)


class TestSummarizeContext:
    """Tests for the summarize_context convenience function."""

    def test_passthrough(self):
        """Small content should pass through."""
        content = "Small context"
        result = summarize_context(content, max_tokens=100, llm_caller=Mock())

        assert result.content == content
        assert result.was_summarized is False

    def test_uses_context_prompts(self):
        """Should use context-focused prompts."""
        content = "x" * 100

        captured_prompt = []

        def mock_llm(prompt: str) -> str:
            captured_prompt.append(prompt)
            return "<SUMMARY>summarized</SUMMARY>"

        result = summarize_context(content, max_tokens=10, llm_caller=mock_llm)

        # Should have called with context-focused prompt
        assert len(captured_prompt) > 0
        assert "KEY FACTS" in captured_prompt[0] or "project" in captured_prompt[0].lower()


class TestSummarizeResultDataclass:
    """Tests for SummarizeResult dataclass."""

    def test_creation(self):
        result = SummarizeResult(
            content="test",
            was_summarized=True,
            original_tokens=100,
            final_tokens=10,
            warnings=["warning1"],
        )

        assert result.content == "test"
        assert result.was_summarized is True
        assert result.original_tokens == 100
        assert result.final_tokens == 10
        assert result.warnings == ["warning1"]
