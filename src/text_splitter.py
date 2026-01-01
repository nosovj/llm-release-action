"""Text splitting utilities for chunking large inputs.

Extracted from LangChain's RecursiveCharacterTextSplitter to avoid
pulling in the entire langchain dependency.

Source: https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain/text_splitter.py
"""

import logging
import re
from typing import Callable, Iterable, List, Optional


def _split_text_with_regex(
    text: str, separator: str, keep_separator: bool
) -> List[str]:
    """Split text using regex, optionally keeping the separator."""
    if separator:
        if keep_separator:
            # The parentheses in the pattern keep the delimiters in the result.
            _splits = re.split(f"({separator})", text)
            splits = [_splits[i] + _splits[i + 1] for i in range(1, len(_splits), 2)]
            if len(_splits) % 2 == 0:
                splits += _splits[-1:]
            splits = [_splits[0]] + splits
        else:
            splits = re.split(separator, text)
    else:
        splits = list(text)
    return [s for s in splits if s != ""]


class RecursiveCharacterTextSplitter:
    """Split text by recursively looking at characters.

    Recursively tries to split by different characters to find one
    that works, preserving natural boundaries like paragraphs and sentences.
    """

    def __init__(
        self,
        separators: Optional[List[str]] = None,
        keep_separator: bool = True,
        is_separator_regex: bool = False,
        length_function: Optional[Callable[[str], int]] = len,
        strip_whitespace: bool = True,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
    ) -> None:
        """Create a new TextSplitter.

        Args:
            separators: List of separators to try, in order of preference.
                        Default: ["\\n\\n", "\\n", " ", ""]
            keep_separator: Whether to keep the separator in the chunks.
            is_separator_regex: Whether separators are regex patterns.
            length_function: Function to measure chunk length.
            strip_whitespace: Whether to strip whitespace from chunks.
            chunk_size: Maximum size of each chunk.
            chunk_overlap: Number of characters to overlap between chunks.
        """
        self._separators = separators or ["\n\n", "\n", " ", ""]
        self._is_separator_regex = is_separator_regex
        self._strip_whitespace = strip_whitespace
        self._length_function = length_function
        self._keep_separator = keep_separator
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def _join_docs(self, docs: List[str], separator: str) -> Optional[str]:
        text = separator.join(docs)
        if self._strip_whitespace:
            text = text.strip()
        if text == "":
            return None
        return text

    def _merge_splits(self, splits: Iterable[str], separator: str) -> List[str]:
        """Merge smaller splits into chunks of appropriate size."""
        separator_len = self._length_function(separator)

        docs = []
        current_doc: List[str] = []
        total = 0
        for d in splits:
            _len = self._length_function(d)
            if (
                total + _len + (separator_len if len(current_doc) > 0 else 0)
                > self._chunk_size
            ):
                if total > self._chunk_size:
                    logging.warning(
                        f"Created a chunk of size {total}, "
                        f"which is longer than the specified {self._chunk_size}"
                    )
                if len(current_doc) > 0:
                    doc = self._join_docs(current_doc, separator)
                    if doc is not None:
                        docs.append(doc)
                    # Keep on popping if:
                    # - we have a larger chunk than in the chunk overlap
                    # - or if we still have any chunks and the length is long
                    while total > self._chunk_overlap or (
                        total + _len + (separator_len if len(current_doc) > 0 else 0)
                        > self._chunk_size
                        and total > 0
                    ):
                        total -= self._length_function(current_doc[0]) + (
                            separator_len if len(current_doc) > 1 else 0
                        )
                        current_doc = current_doc[1:]
            current_doc.append(d)
            total += _len + (separator_len if len(current_doc) > 1 else 0)
        doc = self._join_docs(current_doc, separator)
        if doc is not None:
            docs.append(doc)
        return docs

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """Split incoming text and return chunks."""
        final_chunks = []
        # Get appropriate separator to use
        separator = separators[-1]
        new_separators = []
        for i, _s in enumerate(separators):
            _separator = _s if self._is_separator_regex else re.escape(_s)
            if _s == "":
                separator = _s
                break
            if re.search(_separator, text):
                separator = _s
                new_separators = separators[i + 1 :]
                break

        _separator = separator if self._is_separator_regex else re.escape(separator)
        splits = _split_text_with_regex(text, _separator, self._keep_separator)

        # Now go merging things, recursively splitting longer texts.
        _good_splits = []
        _separator = "" if self._keep_separator else separator
        for s in splits:
            if self._length_function(s) < self._chunk_size:
                _good_splits.append(s)
            else:
                if _good_splits:
                    merged_text = self._merge_splits(_good_splits, _separator)
                    final_chunks.extend(merged_text)
                    _good_splits = []
                if not new_separators:
                    final_chunks.append(s)
                else:
                    other_info = self._split_text(s, new_separators)
                    final_chunks.extend(other_info)
        if _good_splits:
            merged_text = self._merge_splits(_good_splits, _separator)
            final_chunks.extend(merged_text)
        return final_chunks

    def split_text(self, text: str) -> List[str]:
        """Split text into chunks.

        Args:
            text: The text to split.

        Returns:
            List of text chunks with overlap.
        """
        return self._split_text(text, self._separators)


def chunk_with_overlap(
    content: str,
    chunk_size: int = 2000,
    overlap: int = 200,
) -> List[str]:
    """Split content into overlapping chunks.

    Uses RecursiveCharacterTextSplitter to split on natural boundaries
    (paragraphs, lines, words) while maintaining overlap between chunks.

    Args:
        content: The text content to split.
        chunk_size: Maximum size of each chunk (default 2000 chars).
        overlap: Number of characters to overlap between chunks (default 200).

    Returns:
        List of text chunks. Returns [content] if content is smaller than chunk_size.
    """
    if len(content) <= chunk_size:
        return [content]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", " ", ""],  # paragraph → line → word → char
    )

    return splitter.split_text(content)


def needs_chunking(content: str, threshold: int = 2000) -> bool:
    """Check if content needs to be chunked.

    Args:
        content: The text content to check.
        threshold: Size threshold above which chunking is needed.

    Returns:
        True if content length exceeds threshold.
    """
    return len(content) > threshold
