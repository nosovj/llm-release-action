"""Pytest configuration for DeepEval tests."""

import os
import sys

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Model configuration:
# - EVAL_MODEL: Sonnet 4.5 for judging output quality (smarter)
# - TEST_MODEL: Haiku 4.5 for analysis/changelog generation (what we're testing)
# See: https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html
DEFAULT_EVAL_MODEL = "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_TEST_MODEL = "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "eval: mark test as an LLM evaluation test")
    config.addinivalue_line("markers", "slow: mark test as slow (requires LLM calls)")


def get_eval_model() -> str:
    """Get model for evaluating outputs (should be smarter)."""
    return os.environ.get("EVAL_MODEL", DEFAULT_EVAL_MODEL)


def get_test_model() -> str:
    """Get model for generating outputs (what we're testing)."""
    return os.environ.get("TEST_MODEL", DEFAULT_TEST_MODEL)
