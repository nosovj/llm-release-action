"""Generic Summarizing Map/Reduce for large content.

This module provides a reusable abstraction for summarizing large content
to fit within a token budget. It can be used for:
- Context files (summarize project context)
- Diff analysis (extract structured changes)
- Content override (extract changelog items)

Architecture:
    Content
        ↓
    fits_budget? ──Yes──→ Return unchanged (passthrough)
        │No
        ↓
    chunk_content()
        ↓
    MAP: summarize each chunk (parallel)
        ↓
    REDUCE: consolidate summaries
        ↓
    fits_budget? ──No──→ Truncate with warning
        │Yes
        ↓
    Return summarized content
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, List, Optional

from text_splitter import chunk_with_overlap


# Default prompts for context summarization
CONTEXT_MAP_PROMPT = """Extract the KEY FACTS from this project documentation that are relevant for:
- Understanding what the project does
- Identifying public vs internal APIs/endpoints
- Understanding breaking change policies
- Identifying naming conventions

Be concise. Output only the essential facts, one per line.

Content:
---
{content}
---

<SUMMARY>
"""

CONTEXT_REDUCE_PROMPT = """Consolidate these extracted facts into a concise project summary.

Remove duplicates. Keep all unique, important facts about:
- Project purpose
- Public vs internal APIs
- Breaking change policies
- Key conventions

Output a consolidated summary.

Facts to consolidate:
---
{summaries}
---

<SUMMARY>
"""


@dataclass
class SummarizeResult:
    """Result of summarization."""
    content: str
    was_summarized: bool
    original_tokens: int
    final_tokens: int
    warnings: List[str]


def estimate_tokens(text: str) -> int:
    """Estimate token count from text.

    Uses a simple heuristic: ~4 characters per token on average.
    """
    return len(text) // 4


def fits_budget(text: str, max_tokens: int) -> bool:
    """Check if text fits within token budget."""
    return estimate_tokens(text) <= max_tokens


class SummarizingMapReduce:
    """Generic map/reduce for summarizing content to fit a token budget.

    Usage:
        summarizer = SummarizingMapReduce(
            map_prompt=MY_MAP_PROMPT,
            reduce_prompt=MY_REDUCE_PROMPT,
        )
        result = summarizer.summarize_to_budget(
            content=large_content,
            max_tokens=800,
            llm_caller=my_llm_caller,
        )
    """

    def __init__(
        self,
        map_prompt: str = CONTEXT_MAP_PROMPT,
        reduce_prompt: str = CONTEXT_REDUCE_PROMPT,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        max_workers: int = 5,
    ):
        """Initialize the summarizer.

        Args:
            map_prompt: Prompt template for MAP phase. Must contain {content}.
            reduce_prompt: Prompt template for REDUCE phase. Must contain {summaries}.
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Overlap between chunks to preserve context.
            max_workers: Maximum parallel workers for MAP phase.
        """
        self.map_prompt = map_prompt
        self.reduce_prompt = reduce_prompt
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_workers = max_workers

    def _extract_summary(self, response: str) -> str:
        """Extract summary from LLM response."""
        # Try to find content after <SUMMARY> tag
        if "<SUMMARY>" in response:
            parts = response.split("<SUMMARY>", 1)
            if len(parts) > 1:
                summary = parts[1]
                # Remove closing tag if present
                if "</SUMMARY>" in summary:
                    summary = summary.split("</SUMMARY>")[0]
                return summary.strip()
        # Fallback: use whole response
        return response.strip()

    def _summarize_chunk(
        self,
        chunk: str,
        llm_caller: Callable[[str], str],
    ) -> str:
        """Summarize a single chunk (MAP phase)."""
        prompt = self.map_prompt.format(content=chunk)
        response = llm_caller(prompt)
        return self._extract_summary(response)

    def _reduce_summaries(
        self,
        summaries: List[str],
        llm_caller: Callable[[str], str],
    ) -> str:
        """Consolidate summaries (REDUCE phase)."""
        combined = "\n\n".join(summaries)
        prompt = self.reduce_prompt.format(summaries=combined)
        response = llm_caller(prompt)
        return self._extract_summary(response)

    def summarize_to_budget(
        self,
        content: str,
        max_tokens: int,
        llm_caller: Callable[[str], str],
    ) -> SummarizeResult:
        """Summarize content to fit within token budget.

        If content already fits, returns it unchanged (passthrough).
        Otherwise, uses map/reduce to summarize.

        Args:
            content: Content to summarize.
            max_tokens: Maximum tokens in result.
            llm_caller: Function that calls LLM and returns response.

        Returns:
            SummarizeResult with content and metadata.
        """
        original_tokens = estimate_tokens(content)
        warnings: List[str] = []

        # Passthrough if content fits
        if fits_budget(content, max_tokens):
            return SummarizeResult(
                content=content,
                was_summarized=False,
                original_tokens=original_tokens,
                final_tokens=original_tokens,
                warnings=[],
            )

        # Chunk the content
        chunks = chunk_with_overlap(content, self.chunk_size, self.chunk_overlap)

        if len(chunks) <= 1:
            # Single chunk but still too large - just summarize directly
            summary = self._summarize_chunk(content[:self.chunk_size * 2], llm_caller)
            final_tokens = estimate_tokens(summary)

            # If still too large, truncate
            if not fits_budget(summary, max_tokens):
                max_chars = max_tokens * 4
                summary = summary[:max_chars]
                warnings.append(f"Summary truncated to fit {max_tokens} token budget")
                final_tokens = max_tokens

            return SummarizeResult(
                content=summary,
                was_summarized=True,
                original_tokens=original_tokens,
                final_tokens=final_tokens,
                warnings=warnings,
            )

        # MAP phase: summarize each chunk in parallel
        summaries: List[str] = []

        with ThreadPoolExecutor(max_workers=min(len(chunks), self.max_workers)) as executor:
            future_to_idx = {
                executor.submit(self._summarize_chunk, chunk, llm_caller): i
                for i, chunk in enumerate(chunks)
            }

            # Collect results in order
            results = [None] * len(chunks)
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    warnings.append(f"Failed to summarize chunk {idx}: {e}")
                    results[idx] = ""

            summaries = [r for r in results if r]

        if not summaries:
            # All chunks failed - return truncated original with warning
            max_chars = max_tokens * 4
            warnings.append("All summarization failed, falling back to truncation")
            return SummarizeResult(
                content=content[:max_chars],
                was_summarized=False,
                original_tokens=original_tokens,
                final_tokens=max_tokens,
                warnings=warnings,
            )

        # REDUCE phase: consolidate summaries
        reduced = self._reduce_summaries(summaries, llm_caller)
        final_tokens = estimate_tokens(reduced)

        # If still too large, truncate
        if not fits_budget(reduced, max_tokens):
            max_chars = max_tokens * 4
            reduced = reduced[:max_chars]
            warnings.append(f"Reduced summary truncated to fit {max_tokens} token budget")
            final_tokens = max_tokens

        return SummarizeResult(
            content=reduced,
            was_summarized=True,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            warnings=warnings,
        )


# Convenience function for context files
def summarize_context(
    content: str,
    max_tokens: int,
    llm_caller: Callable[[str], str],
) -> SummarizeResult:
    """Summarize context content to fit within token budget.

    Uses the default context-focused prompts.

    Args:
        content: Context content to summarize.
        max_tokens: Maximum tokens in result.
        llm_caller: Function that calls LLM and returns response.

    Returns:
        SummarizeResult with content and metadata.
    """
    summarizer = SummarizingMapReduce()
    return summarizer.summarize_to_budget(content, max_tokens, llm_caller)
