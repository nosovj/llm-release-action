"""End-to-end evaluations for changelog generation.

These tests evaluate the quality of generated changelogs across
different audiences, languages, and formats.

Run with: PYTHONPATH=src pytest evals/test_changelog_evals.py -v -m eval

Requires AWS credentials configured for Bedrock access.
"""

import pytest
import litellm
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from deepeval.metrics import GEval
from deepeval.models import DeepEvalBaseLLM

from prompts import Phase2Config, render_phase2_prompt
from models import Change, ChangeCategory, Importance, BreakingInfo
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
        temperature=0.3,
        max_tokens=2000,
    )
    return response.choices[0].message.content


def get_eval_llm() -> BedrockLLM:
    """Get Sonnet 4.5 for evaluating outputs."""
    return BedrockLLM(get_eval_model())


# =============================================================================
# Sample Changelogs for Transformation
# =============================================================================

TECHNICAL_CHANGELOG = """## v2.0.0

### Breaking Changes
- **BREAKING**: Removed deprecated `/api/v1/users` endpoint. Migrate to `/api/v2/users`.
  - Old: `GET /api/v1/users?page=1` → New: `GET /api/v2/users?cursor=abc123`
  - Response schema changed: `{ users: [...] }` → `{ data: [...], meta: { cursor } }`
- **BREAKING**: Changed authentication from API keys to OAuth2.
  - New endpoint: `POST /oauth/token` with `grant_type=client_credentials`
  - Add header: `Authorization: Bearer <token>` (replaces `X-API-Key`)
  - Token refresh: `POST /oauth/token` with `grant_type=refresh_token`

### Features
- Added dark mode support with `prefers-color-scheme` media query detection
  - New CSS variables: `--bg-primary`, `--text-primary`, `--accent-color`
  - Toggle API: `PUT /api/v2/users/:id/preferences` with `{ theme: "dark" | "light" | "system" }`
- Implemented bulk data export via `POST /api/v2/export`
  - Request: `{ format: "csv" | "json" | "xlsx", filters: {...}, fields: [...] }`
  - Returns `202 Accepted` with `Location` header for download URL
  - Max 100k rows per export, pagination via `cursor` parameter
- New WebSocket API at `wss://api.example.com/ws/v2/notifications`
  - Events: `user.updated`, `export.complete`, `system.alert`
  - Message format: `{ type: string, payload: object, timestamp: ISO8601 }`
  - Requires JWT auth via `?token=` query param

### Bug Fixes
- Fixed memory leak in `ConnectionPool.acquire()` - connections now properly released on timeout (issue #234)
- Resolved race condition in `AsyncJobProcessor.enqueue()` by adding mutex lock
- Fixed `NullPointerException` in `UserSerializer.toJson()` when `user.metadata` is null

### Performance
- Reduced API response time by 40% via query optimization
  - Added composite index on `(tenant_id, created_at)` for users table
  - Rewrote N+1 queries in `UserRepository.findWithRoles()` to use JOIN FETCH
- Implemented Redis caching with 5-minute TTL for `/api/v2/users/:id` endpoint
  - Cache key pattern: `user:{tenant}:{id}`
  - Invalidation on `PUT /api/v2/users/:id`
"""

SAMPLE_CHANGES = [
    Change(
        id="1",
        category=ChangeCategory.BREAKING,
        title="Remove v1 API",
        description="Removed deprecated /api/v1/users endpoint",
        importance=Importance.HIGH,
        breaking=BreakingInfo(
            severity="high",
            affected="All v1 API users",
            migration=["Update API calls to v2", "Update authentication headers"],
        ),
    ),
    Change(
        id="2",
        category=ChangeCategory.FEATURE,
        title="Dark mode support",
        description="Added dark mode with system preference detection",
        importance=Importance.HIGH,
    ),
    Change(
        id="3",
        category=ChangeCategory.FEATURE,
        title="Bulk data export",
        description="Export to CSV, JSON, and Excel formats",
        importance=Importance.MEDIUM,
    ),
    Change(
        id="4",
        category=ChangeCategory.FIX,
        title="Memory leak fix",
        description="Fixed memory leak in connection pool",
        importance=Importance.HIGH,
    ),
]


# =============================================================================
# Audience-Specific Changelog Evals
# =============================================================================

class TestAudienceTransformationEvals:
    """Evaluate changelog transformation for different audiences."""

    def test_developer_audience_technical(self):
        """Developer changelog should include technical details."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Developer",
            audience_description="Technical users who need implementation details, API changes, and code-level information.",
            tone="professional",
            benefit_focused=False,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Should keep technical terms
        response_lower = response.lower()
        assert "api" in response_lower, "Developer changelog should mention API"
        assert "v1" in response_lower or "v2" in response_lower, \
            "Developer changelog should reference API versions"

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="A technical changelog with API details, code references, and implementation specifics",
        )

        technical_metric = GEval(
            name="Technical Depth",
            criteria="The changelog should include technical details like API endpoints, code changes, and implementation specifics appropriate for developers.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [technical_metric])

    def test_customer_audience_benefits(self):
        """Customer changelog should focus on user benefits."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Customer",
            audience_description="End users who care about what's new, what's fixed, and how it benefits them. Avoid technical jargon.",
            tone="friendly",
            benefit_focused=True,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Should focus on benefits, not implementation
        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="A user-friendly changelog focusing on benefits and improvements, avoiding technical jargon",
        )

        benefit_metric = GEval(
            name="Benefit Focus",
            criteria="The changelog should focus on user benefits (what they can do, what's improved) rather than technical implementation details. It should use friendly, accessible language.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [benefit_metric])

    def test_executive_audience_summary(self):
        """Executive changelog should be concise and business-focused."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Executive",
            audience_description="Business stakeholders who need a high-level summary of key changes and business impact.",
            tone="formal",
            summary_only=True,
            max_items=5,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Should be concise
        word_count = len(response.split())
        assert word_count < 500, f"Executive summary should be concise, got {word_count} words"

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="A concise business-focused summary of key changes",
        )

        conciseness_metric = GEval(
            name="Executive Conciseness",
            criteria="The changelog should be concise (under 300 words), focus on business impact, and highlight only the most important changes.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [conciseness_metric])


# =============================================================================
# Language Transformation Evals
# =============================================================================

class TestLanguageTransformationEvals:
    """Evaluate changelog translation to different languages."""

    def test_spanish_translation(self):
        """Test changelog translation to Spanish."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Customer",
            audience_description="Spanish-speaking customers",
            language="es",
            language_name="Spanish",
            benefit_focused=True,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Should contain Spanish words
        spanish_indicators = ["nuevo", "cambios", "mejoras", "correcciones", "versión"]
        has_spanish = any(word in response.lower() for word in spanish_indicators)

        assert has_spanish, "Response should be in Spanish"

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="A changelog written entirely in Spanish",
        )

        language_metric = GEval(
            name="Spanish Language",
            criteria="The changelog must be written entirely in Spanish, with proper grammar and natural phrasing.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.8,
            model=get_eval_llm(),
        )

        assert_test(test_case, [language_metric])

    def test_japanese_translation(self):
        """Test changelog translation to Japanese."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Customer",
            audience_description="Japanese-speaking customers",
            language="ja",
            language_name="Japanese",
            benefit_focused=True,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Should contain Japanese characters
        has_japanese = any('\u3040' <= char <= '\u30ff' or '\u4e00' <= char <= '\u9fff' for char in response)

        assert has_japanese, "Response should contain Japanese characters"

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="A changelog written entirely in Japanese",
        )

        language_metric = GEval(
            name="Japanese Language",
            criteria="The changelog must be written entirely in Japanese, using appropriate kanji, hiragana, and katakana.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.8,
            model=get_eval_llm(),
        )

        assert_test(test_case, [language_metric])


# =============================================================================
# Format and Tone Evals
# =============================================================================

class TestFormatAndToneEvals:
    """Evaluate output format and tone adherence."""

    def test_markdown_format(self):
        """Test that output is valid markdown."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Developer",
            audience_description="Technical users",
            output_format="markdown",
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Check markdown elements
        assert "#" in response, "Markdown should have headers"
        assert "-" in response or "*" in response, "Markdown should have list items"

    def test_emoji_inclusion(self):
        """Test that emojis are included when requested."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Marketing",
            audience_description="Marketing team for promotional content",
            output_format="markdown",
            use_emojis=True,
            tone="excited",
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        # Check for common changelog emojis
        common_emojis = ["🚀", "✨", "🐛", "⚡", "🔒", "💥", "📚", "🎉"]
        has_emoji = any(emoji in response for emoji in common_emojis)

        assert has_emoji, "Response should include emojis when requested"

    def test_formal_tone(self):
        """Test formal tone adherence."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Enterprise",
            audience_description="Enterprise customers requiring formal communication",
            tone="formal",
            tone_description="Formal, professional language suitable for enterprise communications",
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        test_case = LLMTestCase(
            input=prompt,
            actual_output=response,
            expected_output="A formally written changelog with professional language",
        )

        tone_metric = GEval(
            name="Formal Tone",
            criteria="The changelog should use formal, professional language. Avoid casual expressions, slang, or overly enthusiastic phrasing.",
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=0.7,
            model=get_eval_llm(),
        )

        assert_test(test_case, [tone_metric])


# =============================================================================
# Breaking Change Formatting Evals
# =============================================================================

class TestBreakingChangeFormattingEvals:
    """Evaluate breaking change presentation."""

    def test_breaking_changes_prominent(self):
        """Test that breaking changes are prominently displayed."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Developer",
            audience_description="Technical users who need migration guidance",
            include_breaking=True,
            has_breaking_changes=True,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        response_lower = response.lower()

        # Breaking changes should be mentioned prominently
        assert "breaking" in response_lower, "Should mention breaking changes"

        # Should appear early in the changelog
        breaking_pos = response_lower.find("breaking")
        features_pos = response_lower.find("feature")
        if features_pos > 0:
            assert breaking_pos < features_pos, "Breaking changes should appear before features"

    def test_migration_steps_included(self):
        """Test that migration steps are included for breaking changes."""
        config = Phase2Config(
            version="v2.0.0",
            source_changelog=TECHNICAL_CHANGELOG,
            audience_name="Developer",
            audience_description="Technical users who need migration guidance",
            include_breaking=True,
            has_breaking_changes=True,
        )

        prompt = render_phase2_prompt(config)
        response = call_llm(prompt)

        response_lower = response.lower()

        # Should include migration guidance
        migration_terms = ["migration", "upgrade", "update", "change", "instead", "replace"]
        has_migration = any(term in response_lower for term in migration_terms)

        assert has_migration, "Breaking changes should include migration guidance"
