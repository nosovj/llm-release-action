"""End-to-end evaluations for LLM semver analysis.

These tests call the actual LLM and verify the responses match expectations.
Run with: PYTHONPATH=src pytest evals/ -v -m eval

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
    """Call LLM via LiteLLM (uses Haiku 4.5 for testing)."""
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
# Test Fixtures - Different Commit Scenarios
# =============================================================================

PATCH_COMMITS = [
    CommitInfo(hash="abc1234", message="Fix typo in README"),
    CommitInfo(hash="def5678", message="Update documentation for API"),
    CommitInfo(hash="ghi9012", message="Fix null pointer in login handler"),
]

MINOR_COMMITS = [
    CommitInfo(hash="abc1234", message="Add dark mode toggle to settings"),
    CommitInfo(hash="def5678", message="Implement export to CSV feature"),
    CommitInfo(hash="ghi9012", message="Add user profile customization"),
    CommitInfo(hash="jkl3456", message="Fix minor styling issues"),
]

MAJOR_COMMITS = [
    CommitInfo(hash="abc1234", message="Remove deprecated v1 API endpoints", has_breaking_marker=True),
    CommitInfo(hash="def5678", message="BREAKING CHANGE: Rename user.name to user.fullName"),
    CommitInfo(hash="ghi9012", message="Add new v2 authentication flow"),
    CommitInfo(hash="jkl3456", message="Update migration scripts for schema change"),
]

MIXED_COMMITS = [
    CommitInfo(hash="abc1234", message="Add new dashboard analytics"),
    CommitInfo(hash="def5678", message="Fix memory leak in cache module"),
    CommitInfo(hash="ghi9012", message="Update dependencies"),
    CommitInfo(hash="jkl3456", message="Improve error messages"),
    CommitInfo(hash="mno7890", message="Add bulk import feature"),
]


# =============================================================================
# Version Bump Detection Evals
# =============================================================================

class TestVersionBumpEvals:
    """Evaluate version bump detection accuracy."""

    def test_patch_bump_detection(self):
        """Test that bug fixes and docs result in patch bump."""
        prompt = build_semantic_analysis_prompt(
            commits=PATCH_COMMITS,
            base_version="v1.2.3",
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        # Create test case for DeepEval
        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="patch",
            context=[
                "The commits are: fix typo, update docs, fix null pointer",
                "No new features or breaking changes",
                "Expected bump: patch",
            ],
        )

        # Custom metric for version bump correctness (uses Sonnet 4.5 for evaluation)
        correctness = GEval(
            name="Version Bump Correctness",
            criteria="The version bump should be 'patch' for bug fixes and documentation changes only.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "patch", f"Expected patch, got {result.bump}"
        assert_test(test_case, [correctness])

    def test_minor_bump_detection(self):
        """Test that new features result in minor bump."""
        prompt = build_semantic_analysis_prompt(
            commits=MINOR_COMMITS,
            base_version="v1.2.3",
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="minor",
            context=[
                "The commits include: dark mode, CSV export, user customization",
                "These are new features without breaking changes",
                "Expected bump: minor",
            ],
        )

        correctness = GEval(
            name="Version Bump Correctness",
            criteria="The version bump should be 'minor' for new features without breaking changes.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "minor", f"Expected minor, got {result.bump}"
        assert_test(test_case, [correctness])

    def test_major_bump_detection(self):
        """Test that breaking changes result in major bump."""
        prompt = build_semantic_analysis_prompt(
            commits=MAJOR_COMMITS,
            base_version="v1.2.3",
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="major",
            context=[
                "The commits include: removed v1 API, renamed user.name to user.fullName",
                "These are breaking changes requiring user action",
                "Expected bump: major",
            ],
        )

        correctness = GEval(
            name="Version Bump Correctness",
            criteria="The version bump should be 'major' for breaking changes.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert result.bump == "major", f"Expected major, got {result.bump}"
        assert_test(test_case, [correctness])


# =============================================================================
# Changelog Quality Evals
# =============================================================================

class TestChangelogQualityEvals:
    """Evaluate changelog generation quality."""

    def test_changelog_contains_all_changes(self):
        """Test that changelog mentions all significant changes."""
        prompt = build_semantic_analysis_prompt(
            commits=MINOR_COMMITS,
            base_version="v1.0.0",
            generate_changelog=True,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        # Check changelog contains key terms
        changelog_lower = result.changelog.lower()

        assert "dark mode" in changelog_lower or "theme" in changelog_lower, \
            "Changelog should mention dark mode feature"
        assert "csv" in changelog_lower or "export" in changelog_lower, \
            "Changelog should mention export feature"

        test_case = LLMTestCase(
            input=prompt,
            actual_output=result.changelog,
            expected_output="A changelog mentioning dark mode, CSV export, and user customization features",
        )

        relevancy = GEval(
            name="Changelog Relevancy",
            criteria="The changelog should mention all the key changes: dark mode, CSV export, user customization.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
            threshold=0.6,
            model=get_eval_llm(),
        )
        assert_test(test_case, [relevancy])

    def test_changelog_structure(self):
        """Test that changelog has proper markdown structure."""
        prompt = build_semantic_analysis_prompt(
            commits=MIXED_COMMITS,
            base_version="v2.0.0",
            generate_changelog=True,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        changelog = result.changelog

        # Check for markdown headers
        assert "#" in changelog, "Changelog should have markdown headers"

        # Check for bullet points
        assert "-" in changelog or "*" in changelog, "Changelog should have bullet points"

        test_case = LLMTestCase(
            input=prompt,
            actual_output=changelog,
            expected_output="A well-structured markdown changelog with headers and bullet points",
        )

        structure_metric = GEval(
            name="Changelog Structure",
            criteria="The changelog should be well-formatted markdown with clear sections (Features, Bug Fixes, etc.) and bullet points.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [structure_metric])


# =============================================================================
# Breaking Change Detection Evals
# =============================================================================

class TestBreakingChangeEvals:
    """Evaluate breaking change detection accuracy."""

    def test_detects_api_removal(self):
        """Test detection of API endpoint removal."""
        commits = [
            CommitInfo(hash="abc1234", message="Remove /api/v1/users endpoint"),
            CommitInfo(hash="def5678", message="Add /api/v2/users with new schema"),
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.0.0",
            detect_breaking=True,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        assert result.bump == "major", "API removal should trigger major bump"

        # Check that breaking changes are mentioned
        response_lower = response.lower()
        assert "breaking" in response_lower or "remove" in response_lower, \
            "Response should mention breaking change"

    def test_detects_schema_change(self):
        """Test detection of database schema changes."""
        commits = [
            CommitInfo(hash="abc1234", message="Rename column user_name to full_name in users table"),
            CommitInfo(hash="def5678", message="Add migration script for column rename"),
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.0.0",
            detect_breaking=True,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        # Schema changes should be at least minor, possibly major
        assert result.bump in ["minor", "major"], \
            f"Schema change should trigger minor or major bump, got {result.bump}"

    def test_detects_config_change(self):
        """Test detection of configuration format changes."""
        commits = [
            CommitInfo(hash="abc1234", message="Change config format from YAML to JSON"),
            CommitInfo(hash="def5678", message="Update config parser for new format"),
            CommitInfo(hash="ghi9012", message="BREAKING: Old YAML configs no longer supported"),
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.0.0",
            detect_breaking=True,
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        assert result.bump == "major", "Config format change should trigger major bump"


# =============================================================================
# XML Parsing Robustness Evals
# =============================================================================

class TestParsingRobustnessEvals:
    """Evaluate that XML parsing handles various LLM response formats."""

    def test_parses_response_with_extra_text(self):
        """Test parsing when LLM adds extra commentary."""
        prompt = build_semantic_analysis_prompt(
            commits=PATCH_COMMITS,
            base_version="v1.0.0",
        )

        response = call_llm(prompt)

        # Should not raise, even with extra text
        result = parse_phase1_response(response)

        assert result.bump in ["major", "minor", "patch"]
        assert result.reasoning is not None
        assert len(result.reasoning) > 0

    def test_handles_multiline_reasoning(self):
        """Test parsing with multiline reasoning sections."""
        prompt = build_semantic_analysis_prompt(
            commits=MIXED_COMMITS,
            base_version="v1.0.0",
        )

        response = call_llm(prompt)
        result = parse_phase1_response(response)

        # Reasoning should be extracted properly
        assert result.reasoning is not None
        assert len(result.reasoning) > 10, "Reasoning should be substantive"


# =============================================================================
# Adaptive Detail Level Evals
# =============================================================================

class TestAdaptiveDetailEvals:
    """Evaluate that detail level adapts to commit count."""

    def test_small_release_detailed(self):
        """Test that small releases get detailed output."""
        # 5 commits = "full" detail level
        commits = PATCH_COMMITS[:3]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.0.0",
        )

        # Prompt should mention "SMALL release"
        assert "SMALL release" in prompt or "DETAILED" in prompt, \
            "Small release should request detailed output"

    def test_large_release_summarized(self):
        """Test that large releases get summarized output."""
        # Create 150 commits
        commits = [
            CommitInfo(hash=f"hash{i:03d}", message=f"Commit {i}: Some change")
            for i in range(150)
        ]

        prompt = build_semantic_analysis_prompt(
            commits=commits,
            base_version="v1.0.0",
        )

        # Prompt should mention "LARGE release"
        assert "LARGE release" in prompt or "HIGH IMPACT" in prompt, \
            "Large release should request summarized output"
