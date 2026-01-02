"""End-to-end evaluations for flatten (Phase 0: Net State) functionality.

These tests call the actual LLM and verify that:
1. Reverted features are excluded from output
2. Related changes are consolidated
3. Net state is accurately determined

Run with: PYTHONPATH=src pytest evals/test_flatten_evals.py -v -m eval
"""

import pytest
import litellm
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from deepeval.metrics import GEval
from deepeval.models import DeepEvalBaseLLM

from flatten import flatten_changes, flatten_changes_to_list, FLATTEN_PROMPT
from conftest import get_test_model, get_eval_model

pytestmark = [
    pytest.mark.eval,
    pytest.mark.slow,
]


class BedrockLLM(DeepEvalBaseLLM):
    """Custom DeepEval LLM using AWS Bedrock via LiteLLM."""

    def __init__(self, model: str):
        self._model = model

    def load_model(self):
        return self._model

    def generate(self, prompt: str) -> str:
        response = litellm.completion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1000,
        )
        return response.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return self._model


def call_llm(prompt: str) -> str:
    """Call LLM via LiteLLM."""
    response = litellm.completion(
        model=get_test_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000,
    )
    return response.choices[0].message.content


def get_eval_llm() -> BedrockLLM:
    """Get Sonnet 4.5 for evaluating outputs."""
    return BedrockLLM(get_eval_model())


# =============================================================================
# Test Fixtures - Net State Scenarios
# =============================================================================

REVERTED_FEATURE_INPUT = """1. abc123: feat: Add Stripe payment integration
2. def456: fix: Fix payment validation edge case
3. ghi789: feat: Add dark mode support
4. jkl012: revert: Revert "Add Stripe payment integration"
   This reverts commit abc123
5. mno345: docs: Update README
"""

RELATED_CHANGES_INPUT = """1. abc123: feat: Add OAuth login
2. def456: fix: Fix OAuth token refresh bug
3. ghi789: feat: Add OAuth scope support
4. jkl012: docs: Document OAuth flow
"""

ALL_REVERTED_INPUT = """1. abc123: feat: Add caching layer
2. def456: feat: Improve caching performance
3. ghi789: revert: Revert caching due to memory issues
   This reverts commit abc123 and def456
"""

CHANGELOG_TEXT_INPUT = """## v1.0.0
- Added new caching layer for improved performance

## v1.0.1
- Enhanced caching with TTL support

## v1.0.2
- Removed caching due to memory leak issues

## v1.1.0
- Added OAuth 2.0 authentication
- Added user preferences API
"""


# =============================================================================
# Reverted Feature Detection Evals
# =============================================================================

class TestRevertedFeatureEvals:
    """Evaluate that reverted features are correctly excluded."""

    def test_reverted_feature_excluded(self):
        """Test that a feature added then reverted is excluded from output."""
        result = flatten_changes(REVERTED_FEATURE_INPUT, call_llm)
        result_lower = result.lower()

        # Stripe should be excluded (it was reverted)
        assert "stripe" not in result_lower, \
            f"Stripe should be excluded (was reverted). Got: {result}"

        # Payment should be excluded (related to reverted feature)
        assert "payment" not in result_lower, \
            f"Payment should be excluded (related to reverted). Got: {result}"

        # Dark mode should be included (not reverted)
        assert "dark" in result_lower, \
            f"Dark mode should be included. Got: {result}"

        # Create DeepEval test case
        test_case = LLMTestCase(
            input=REVERTED_FEATURE_INPUT,
            actual_output=result,
            expected_output="Dark mode and README updates only (no Stripe)",
            context=[
                "Stripe payment was added then reverted - net zero",
                "Dark mode was added and not reverted",
                "README was updated",
                "Output should NOT contain Stripe or payment",
            ],
        )

        correctness = GEval(
            name="Revert Detection",
            criteria="The output should NOT mention Stripe or payment (which was reverted). It SHOULD mention dark mode and docs.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [correctness])

    def test_all_reverted_returns_minimal(self):
        """Test that if all features are reverted, output is empty or minimal."""
        changes = flatten_changes_to_list(ALL_REVERTED_INPUT, call_llm)

        # Should have no caching-related changes
        caching_changes = [c for c in changes if "caching" in c.title.lower()]

        assert len(caching_changes) == 0, \
            f"Caching should be excluded (all reverted). Got: {[c.title for c in changes]}"

        test_case = LLMTestCase(
            input=ALL_REVERTED_INPUT,
            actual_output=str([c.title for c in changes]),
            expected_output="Empty or no caching-related entries",
            context=[
                "Caching was added then fully reverted",
                "Net state is zero - nothing actually changed",
            ],
        )

        correctness = GEval(
            name="Full Revert Detection",
            criteria="When all changes are reverted, the output should be empty or contain no caching-related entries.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [correctness])


# =============================================================================
# Consolidation Evals
# =============================================================================

class TestConsolidationEvals:
    """Evaluate that related changes are consolidated."""

    def test_related_changes_consolidated(self):
        """Test that related OAuth changes are consolidated."""
        changes = flatten_changes_to_list(RELATED_CHANGES_INPUT, call_llm)

        # Should have fewer entries than input commits (4)
        assert len(changes) < 4, \
            f"Related changes should be consolidated. Got {len(changes)} entries from 4 commits"

        # All OAuth-related work should be represented
        all_titles = " ".join(c.title.lower() for c in changes)
        assert "oauth" in all_titles, \
            f"OAuth should be mentioned. Got: {[c.title for c in changes]}"

        test_case = LLMTestCase(
            input=RELATED_CHANGES_INPUT,
            actual_output=str([(c.title, c.description) for c in changes]),
            expected_output="Consolidated OAuth entries (fewer than 4)",
            context=[
                "4 commits all related to OAuth",
                "Should consolidate into fewer logical entries",
                "OAuth functionality should be preserved",
            ],
        )

        consolidation = GEval(
            name="Change Consolidation",
            criteria="Related changes should be consolidated into fewer entries while preserving the key functionality (OAuth).",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.6,
            model=get_eval_llm(),
        )

        assert_test(test_case, [consolidation])


# =============================================================================
# Content Override (Changelog Text) Evals
# =============================================================================

class TestContentOverrideEvals:
    """Evaluate that changelog text input works the same as commits."""

    def test_changelog_text_net_state(self):
        """Test that changelog text with add+remove produces correct net state."""
        changes = flatten_changes_to_list(CHANGELOG_TEXT_INPUT, call_llm)

        # Caching should be excluded (added in v1.0.0, removed in v1.0.2)
        all_titles = " ".join(c.title.lower() for c in changes)
        assert "caching" not in all_titles, \
            f"Caching should be excluded (was removed). Got: {[c.title for c in changes]}"

        # OAuth should be included
        assert "oauth" in all_titles or "auth" in all_titles, \
            f"OAuth should be included. Got: {[c.title for c in changes]}"

        test_case = LLMTestCase(
            input=CHANGELOG_TEXT_INPUT,
            actual_output=str([c.title for c in changes]),
            expected_output="OAuth and preferences (no caching)",
            context=[
                "Caching was added in v1.0.0 and removed in v1.0.2 - net zero",
                "OAuth and preferences were added in v1.1.0 and kept",
                "Output should contain OAuth and preferences but NOT caching",
            ],
        )

        correctness = GEval(
            name="Changelog Net State",
            criteria="Changelog text with add then remove should produce net state. Caching should be excluded, OAuth and preferences should be included.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [correctness])


# =============================================================================
# Version Bump Accuracy Evals
# =============================================================================

class TestVersionBumpAfterFlattenEvals:
    """Evaluate that version bump is accurate after flattening."""

    def test_reverted_feature_correct_bump(self):
        """Test: Reverted major feature should not cause major bump."""
        # If Stripe (a feature) was added and reverted, only dark mode remains
        # Dark mode = minor bump, not influenced by reverted Stripe
        changes = flatten_changes_to_list(REVERTED_FEATURE_INPUT, call_llm)

        # Determine what bump this would produce
        has_breaking = any(c.category.value == "breaking" for c in changes)
        has_feature = any(c.category.value == "feature" for c in changes)

        # Dark mode is a feature, so minor bump
        # But critically, Stripe (also a feature) should NOT influence the bump
        stripe_in_changes = any("stripe" in c.title.lower() for c in changes)

        assert not stripe_in_changes, \
            "Stripe should not be in changes (was reverted)"

        # If only dark mode feature, bump should be minor
        if has_feature and not has_breaking:
            expected_bump = "minor"
        else:
            expected_bump = "patch"

        test_case = LLMTestCase(
            input=REVERTED_FEATURE_INPUT,
            actual_output=f"Changes: {[c.title for c in changes]}, Bump: {expected_bump}",
            expected_output="minor bump (dark mode feature only)",
            context=[
                "Stripe was reverted, so it doesn't count",
                "Dark mode is a new feature",
                "Version bump should be based on net state only",
            ],
        )

        accuracy = GEval(
            name="Version Bump Accuracy",
            criteria="Version bump should be based on net state (dark mode = minor), not raw history (which would include Stripe).",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [accuracy])
