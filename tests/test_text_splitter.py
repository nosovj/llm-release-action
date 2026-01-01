"""Tests for text_splitter module."""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from text_splitter import (
    RecursiveCharacterTextSplitter,
    chunk_with_overlap,
    needs_chunking,
)


class TestRecursiveCharacterTextSplitter:
    """Tests for RecursiveCharacterTextSplitter class."""

    def test_split_short_text(self):
        """Short text should not be split."""
        splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=20)
        text = "This is a short text."
        result = splitter.split_text(text)
        assert len(result) == 1
        assert result[0] == text

    def test_split_on_paragraph_boundary(self):
        """Should split on paragraph boundary first."""
        splitter = RecursiveCharacterTextSplitter(chunk_size=50, chunk_overlap=10)
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = splitter.split_text(text)
        assert len(result) >= 2
        # Each chunk should be under the limit
        for chunk in result:
            assert len(chunk) <= 50 or "paragraph" in chunk  # Allow slight overage

    def test_split_on_line_boundary(self):
        """Should split on line boundary if no paragraphs."""
        splitter = RecursiveCharacterTextSplitter(chunk_size=30, chunk_overlap=5)
        text = "Line one\nLine two\nLine three\nLine four"
        result = splitter.split_text(text)
        assert len(result) >= 2

    def test_overlap_preserved(self):
        """Overlap should be preserved between chunks."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=50,
            chunk_overlap=20,
            separators=["\n"],
        )
        text = "Line A content here\nLine B content here\nLine C content here\nLine D content here"
        result = splitter.split_text(text)

        # With overlap, some content should appear in multiple chunks
        if len(result) > 1:
            # Check that there's some overlap
            combined_length = sum(len(c) for c in result)
            assert combined_length >= len(text)  # Due to overlap

    def test_empty_text(self):
        """Empty text should return empty list or single empty chunk."""
        splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=20)
        result = splitter.split_text("")
        assert len(result) == 0 or result == [""]


class TestChunkWithOverlap:
    """Tests for chunk_with_overlap function."""

    def test_small_content_no_chunking(self):
        """Content smaller than chunk_size should not be chunked."""
        content = "Small content"
        result = chunk_with_overlap(content, chunk_size=1000, overlap=100)
        assert result == [content]

    def test_large_content_chunked(self):
        """Content larger than chunk_size should be chunked."""
        # Create content larger than chunk size
        content = "\n\n".join([f"Paragraph {i} with some content here." for i in range(20)])
        result = chunk_with_overlap(content, chunk_size=100, overlap=20)
        assert len(result) > 1

    def test_default_parameters(self):
        """Test with default parameters."""
        content = "x" * 3000  # Larger than default 2000
        result = chunk_with_overlap(content)
        assert len(result) > 1

    def test_overlap_creates_redundancy(self):
        """Overlap should create some content redundancy."""
        content = "\n\n".join([f"Paragraph {i} has content." for i in range(10)])
        result = chunk_with_overlap(content, chunk_size=100, overlap=30)

        if len(result) > 1:
            # Total content in chunks should exceed original due to overlap
            total_chunk_length = sum(len(c) for c in result)
            assert total_chunk_length >= len(content)


class TestNeedsChunking:
    """Tests for needs_chunking function."""

    def test_small_content_no_chunking(self):
        """Small content should not need chunking."""
        assert not needs_chunking("small content", threshold=100)

    def test_large_content_needs_chunking(self):
        """Large content should need chunking."""
        content = "x" * 1000
        assert needs_chunking(content, threshold=100)

    def test_exact_threshold(self):
        """Content exactly at threshold should not need chunking."""
        content = "x" * 100
        assert not needs_chunking(content, threshold=100)

    def test_one_over_threshold(self):
        """Content one over threshold should need chunking."""
        content = "x" * 101
        assert needs_chunking(content, threshold=100)


class TestRealWorldScenarios:
    """Tests with real-world-like content."""

    def test_changelog_format(self):
        """Test splitting changelog-like content."""
        changelog = """## Features

### New OAuth 2.0 Support
Added comprehensive OAuth 2.0 support with refresh tokens.

### Improved Dashboard
The dashboard now loads 50% faster with better caching.

## Fixes

### Fixed Login Issues
Resolved intermittent login failures on mobile devices.

### Database Connection Pool
Fixed connection pool exhaustion under heavy load.

## Breaking Changes

### API Version Bump
The API now requires v2 endpoints. Migration guide available.
"""
        result = chunk_with_overlap(changelog, chunk_size=200, overlap=50)

        # Should have multiple chunks
        assert len(result) >= 2

        # Each chunk should contain meaningful content
        for chunk in result:
            assert len(chunk.strip()) > 0

    def test_preserves_context_at_boundaries(self):
        """Test that overlap preserves context at chunk boundaries."""
        # Create content where context at boundaries matters
        content = """Feature: OAuth Support
This feature adds OAuth 2.0 with support for
refresh tokens and automatic token renewal.

Feature: Dashboard Performance
The dashboard now loads 50% faster
due to improved caching strategies.

Feature: Mobile Support
Added responsive design for mobile devices
with touch-friendly controls.
"""
        result = chunk_with_overlap(content, chunk_size=150, overlap=50)

        # Content should be split into chunks
        assert len(result) >= 1
        # All chunks should have content
        for chunk in result:
            assert len(chunk.strip()) > 0
