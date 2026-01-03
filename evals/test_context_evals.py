"""End-to-end evaluations for context files feature.

These tests verify that providing project context improves version bump accuracy,
especially for distinguishing public APIs from internal implementation details.

Run with: PYTHONPATH=src pytest evals/test_context_evals.py -v -m eval

Requires AWS credentials configured for Bedrock access.
"""

import pytest
import litellm
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from deepeval.metrics import GEval
from deepeval.models import DeepEvalBaseLLM

from prompt_builder import build_semantic_analysis_prompt, CommitInfo
from analyzer import parse_phase1_response
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
    """Get evaluator LLM."""
    return BedrockLLM(get_eval_model())


# =============================================================================
# Context Documents
# =============================================================================

CONTEXT_WITH_PUBLIC_INTERNAL = """# LLM Release Action - API Context

## Public APIs (breaking if changed)
These are documented, versioned, and used by external consumers:

- `action.yml` inputs and outputs - GitHub Action interface
- `build_semantic_analysis_prompt()` - main entry point for analysis
- `parse_phase1_response()` - response parsing interface
- `AnalysisResult`, `Change`, `ChangeStats` - output data models
- `/src/analyzer.py` public functions
- `/src/changelog.py` public functions

## Internal Implementation (not breaking if changed)
These are internal details that can change without version bump:

- `_validate*` functions - internal validation helpers
- `_parse*` functions - internal parsing helpers
- `_extract*` functions - internal extraction helpers
- `text_splitter.py` - internal chunking implementation
- `summarizing_map_reduce.py` - internal summarization
- `context_loader.py` - internal context loading
- `diff_analyzer.py` - internal diff processing
- All functions starting with underscore
- All classes in `/src/prompts.py` - internal prompt templates
- Test utilities and fixtures

## Conventions
- Public functions have docstrings with Args/Returns
- Internal functions start with underscore or are in internal modules
- Breaking changes require MAJOR version bump
- Internal refactoring is PATCH
"""

CONTEXT_MINIMAL = """# Project Context

Public interface: action.yml inputs/outputs
Everything else is internal implementation.
"""


# =============================================================================
# Test Commits - Ambiguous Without Context
# =============================================================================

# These commits could be MAJOR or PATCH depending on whether the code is public
INTERNAL_REFACTOR_COMMITS = [
    CommitInfo(hash="abc1234", message="refactor: rename _validate_input to _check_input"),
    CommitInfo(hash="def5678", message="refactor: move text_splitter logic to new module"),
    CommitInfo(hash="ghi9012", message="chore: simplify _extract_summary implementation"),
]

PUBLIC_API_CHANGE_COMMITS = [
    CommitInfo(hash="abc1234", message="refactor: rename build_semantic_analysis_prompt parameters"),
    CommitInfo(hash="def5678", message="fix: change AnalysisResult.changes from list to tuple"),
    CommitInfo(hash="ghi9012", message="refactor: update parse_phase1_response return type"),
]

MIXED_INTERNAL_COMMITS = [
    CommitInfo(hash="abc1234", message="refactor: rewrite summarizing_map_reduce internals"),
    CommitInfo(hash="def5678", message="chore: update context_loader default exclusions"),
    CommitInfo(hash="ghi9012", message="fix: improve diff_analyzer error handling"),
    CommitInfo(hash="jkl3456", message="docs: update README examples"),
]

ACTION_INTERFACE_COMMITS = [
    CommitInfo(hash="abc1234", message="feat: add new context_files input to action.yml"),
    CommitInfo(hash="def5678", message="feat: add warnings output to action.yml"),
    CommitInfo(hash="ghi9012", message="docs: document new inputs in README"),
]

BREAKING_ACTION_COMMITS = [
    CommitInfo(hash="abc1234", message="refactor: rename 'model' input to 'llm_model' in action.yml"),
    CommitInfo(hash="def5678", message="refactor: change changelogs output format from object to array"),
]


# =============================================================================
# Context Files Evals
# =============================================================================

class TestContextImprovesAccuracy:
    """Test that providing context improves version bump accuracy."""

    def test_internal_refactor_is_patch_with_context(self):
        """Internal refactoring should be PATCH when context clarifies it's internal."""
        prompt = build_semantic_analysis_prompt(
            commits=INTERNAL_REFACTOR_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="patch",
            context=[
                "Commits rename _validate_input, move text_splitter, simplify _extract_summary",
                "Context explicitly says underscore functions are internal",
                "Context says text_splitter.py is internal implementation",
                "Internal changes should be PATCH, not MAJOR",
            ],
        )

        correctness = GEval(
            name="Internal Refactor Detection",
            criteria="Changes to internal/private code (underscore functions, internal modules) should be PATCH, not MAJOR.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "patch", f"Expected patch for internal refactor, got {result.bump}"
        assert_test(test_case, [correctness])

    def test_public_api_change_is_major_with_context(self):
        """Public API changes should be MAJOR when context identifies them as public."""
        prompt = build_semantic_analysis_prompt(
            commits=PUBLIC_API_CHANGE_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="major",
            context=[
                "Commits change build_semantic_analysis_prompt, AnalysisResult, parse_phase1_response",
                "Context explicitly lists these as PUBLIC APIs",
                "Changing public API signatures is a breaking change",
                "Should be MAJOR bump",
            ],
        )

        correctness = GEval(
            name="Public API Change Detection",
            criteria="Changes to public API signatures (documented, versioned interfaces) should be MAJOR.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "major", f"Expected major for public API change, got {result.bump}"
        assert_test(test_case, [correctness])

    def test_mixed_internal_is_patch_with_context(self):
        """Mixed internal changes should be PATCH when context identifies all as internal."""
        prompt = build_semantic_analysis_prompt(
            commits=MIXED_INTERNAL_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="patch",
            context=[
                "Commits change summarizing_map_reduce, context_loader, diff_analyzer",
                "Context lists all these modules as internal implementation",
                "Internal module changes should be PATCH",
            ],
        )

        correctness = GEval(
            name="Internal Module Detection",
            criteria="Changes to internal modules (listed as internal in context) should be PATCH.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "patch", f"Expected patch for internal modules, got {result.bump}"
        assert_test(test_case, [correctness])

    def test_action_interface_addition_is_minor(self):
        """Adding new action.yml inputs should be MINOR (additive, not breaking)."""
        prompt = build_semantic_analysis_prompt(
            commits=ACTION_INTERFACE_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="minor",
            context=[
                "Commits add new context_files input and warnings output",
                "Adding NEW inputs/outputs is backwards compatible",
                "Existing users are not affected",
                "Should be MINOR (new feature), not MAJOR",
            ],
        )

        correctness = GEval(
            name="Additive API Change Detection",
            criteria="Adding new optional inputs/outputs to action.yml is backwards compatible and should be MINOR.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "minor", f"Expected minor for additive changes, got {result.bump}"
        assert_test(test_case, [correctness])

    def test_breaking_action_change_is_major(self):
        """Renaming/removing action.yml inputs should be MAJOR (breaking)."""
        prompt = build_semantic_analysis_prompt(
            commits=BREAKING_ACTION_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="major",
            context=[
                "Commits rename 'model' input and change output format",
                "Renaming inputs breaks existing workflows",
                "Changing output format breaks consumers",
                "Should be MAJOR (breaking change)",
            ],
        )

        correctness = GEval(
            name="Breaking Action Change Detection",
            criteria="Renaming inputs or changing output formats in action.yml breaks existing users and should be MAJOR.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "major", f"Expected major for breaking action change, got {result.bump}"
        assert_test(test_case, [correctness])


class TestContextVsNoContext:
    """Compare results with and without context for ambiguous cases."""

    def test_internal_refactor_comparison(self):
        """Compare bump detection for internal refactor with and without context."""
        # Without context - LLM might be unsure if _validate_input is public
        prompt_no_context = build_semantic_analysis_prompt(
            commits=INTERNAL_REFACTOR_COMMITS,
            base_version="v1.2.3",
        )

        # With context - LLM knows underscore means internal
        prompt_with_context = build_semantic_analysis_prompt(
            commits=INTERNAL_REFACTOR_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response_no_context = call_llm(prompt_no_context)
        response_with_context = call_llm(prompt_with_context)

        result_no_context = parse_phase1_response(response_no_context)
        result_with_context = parse_phase1_response(response_with_context)

        # With context should definitely be patch
        assert result_with_context.bump == "patch", \
            f"With context, internal refactor should be patch, got {result_with_context.bump}"

        # Log comparison for analysis
        print(f"\n=== Internal Refactor Comparison ===")
        print(f"Without context: {result_no_context.bump}")
        print(f"With context: {result_with_context.bump}")

        # The key insight: context should make the decision more confident/correct
        # Without context, LLM might conservatively say minor or even major
        # With context, it should confidently say patch

    def test_minimal_context_still_helps(self):
        """Even minimal context should help distinguish public from internal."""
        prompt = build_semantic_analysis_prompt(
            commits=MIXED_INTERNAL_COMMITS,
            base_version="v1.2.3",
            context_content=CONTEXT_MINIMAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        # Minimal context says "Everything else is internal implementation"
        # So internal module changes should still be PATCH
        assert result.bump == "patch", \
            f"With minimal context, internal changes should be patch, got {result.bump}"


class TestRealWorldScenarios:
    """Test scenarios based on actual llm-release-action development."""

    def test_adding_context_files_feature(self):
        """Adding the context_files feature itself should be MINOR."""
        commits = [
            CommitInfo(hash="abc1234", message="feat: add context_files input for project understanding"),
            CommitInfo(hash="def5678", message="feat: add context_max_tokens input"),
            CommitInfo(hash="ghi9012", message="feat: implement summarizing map/reduce for large context"),
            CommitInfo(hash="jkl3456", message="feat: add default exclusions for node_modules, vendor, etc"),
            CommitInfo(hash="mno7890", message="docs: document context files feature in README"),
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.3.0",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        assert result.bump == "minor", \
            f"Adding new feature (context_files) should be minor, got {result.bump}"

    def test_fixing_dry_run_summarization(self):
        """Fixing dry_run to allow summarization should be PATCH."""
        commits = [
            CommitInfo(hash="abc1234", message="fix: allow context summarization in dry_run mode"),
            CommitInfo(hash="def5678", message="test: add tests for default exclusions"),
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.3.1",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        assert result.bump == "patch", \
            f"Bug fix and test additions should be patch, got {result.bump}"

    def test_refactoring_prompts_is_internal(self):
        """Refactoring prompt templates should be PATCH (internal)."""
        commits = [
            CommitInfo(hash="abc1234", message="refactor: update CONTEXT_MAP_PROMPT for better extraction"),
            CommitInfo(hash="def5678", message="refactor: simplify CONTEXT_REDUCE_PROMPT"),
            CommitInfo(hash="ghi9012", message="chore: add comments to prompt templates"),
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.3.2",
            context_content=CONTEXT_WITH_PUBLIC_INTERNAL,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        # Context says prompts.py classes are internal
        assert result.bump == "patch", \
            f"Prompt template refactoring (internal) should be patch, got {result.bump}"
