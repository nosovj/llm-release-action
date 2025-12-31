# LLM Release Action

A GitHub Action that uses LLM to analyze commits, suggest semantic version bumps, and generate multi-audience changelogs.

## Features

- **Semantic Version Analysis**: Analyzes commit history to determine appropriate version bump (major, minor, patch)
- **Multi-Audience Changelogs**: Generate changelogs for different audiences (developers, customers, executives) in multiple languages
- **Parallel Execution**: Changelog transformations run in parallel for speed
- **Usage Tracking**: Returns token counts and latency per model for cost monitoring
- **Multiple LLM Providers**: Supports any provider via [LiteLLM](https://github.com/BerriAI/litellm) (Anthropic, OpenAI, AWS Bedrock, etc.)
- **Breaking Change Detection**: Detects breaking changes from commit messages and file diffs
- **Conservative Versioning**: Only suggests major bumps when explicit evidence exists

## Quick Start

```yaml
- uses: nosovj/llm-release-action@v1
  with:
    model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
  env:
    AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
    AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    AWS_REGION: us-east-1
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `model` | Yes | - | LiteLLM model string (e.g., `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| `model_analysis` | No | `model` | Model for Phase 1 semantic analysis (falls back to `model`) |
| `model_changelog` | No | `model` | Model for Phase 2 changelog generation (falls back to `model`) |
| `current_version` | No | auto-detect | Version to compare from. Auto-detects from latest semver tag if not provided. |
| `head_ref` | No | `HEAD` | Head ref to compare to |
| `include_diffs` | No | `**/openapi*.yaml,...` | File patterns for diff analysis (comma-separated) |
| `max_commits` | No | `50` | Max recent commits to include in full (rest summarized) |
| `temperature` | No | `0.2` | LLM temperature (lower = more deterministic) |
| `max_tokens` | No | `4000` | Max tokens in LLM response |
| `timeout` | No | `120` | Request timeout in seconds |
| `debug` | No | `false` | Enable verbose debug logging |
| `dry_run` | No | `false` | Perform analysis without suggesting version |
| `content_override` | No | - | Pre-formatted content for multi-repo analysis (bypasses git) |
| `changelog_config` | No | - | YAML config for multi-audience changelog generation |

## Outputs

| Output | Description |
|--------|-------------|
| `bump` | Bump type: `major`, `minor`, or `patch` |
| `current_version` | The version compared from (detected or provided) |
| `next_version` | Calculated next semantic version |
| `changelog` | Generated markdown changelog (legacy single changelog) |
| `changelogs` | JSON object with changelogs per audience/language: `{audience: {language: content}}` |
| `metadata` | JSON object with release metadata per audience/language |
| `changes` | JSON array of structured changes from analysis |
| `stats` | JSON object with change statistics: `{features, fixes, breaking, ...}` |
| `breaking_changes` | JSON array of detected breaking changes |
| `reasoning` | LLM explanation for the version suggestion |
| `usage` | JSON object with LLM usage stats per model (tokens, latency) |

### Usage Output Example

```json
{
  "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0": {
    "calls": 4,
    "input_tokens": 1882,
    "output_tokens": 1126,
    "latency_ms": 8843
  }
}
```

## Usage Examples

### Basic Usage (Auto-detect Version)

```yaml
name: Release
on:
  push:
    branches: [main]

jobs:
  version:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Required for full history

      - uses: nosovj/llm-release-action@v1
        id: release
        with:
          model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_REGION: us-east-1

      - name: Create Release
        run: |
          echo "Creating release ${{ steps.release.outputs.next_version }}"
          echo "Bump type: ${{ steps.release.outputs.bump }}"
```

### Multi-Audience Changelogs

Generate different changelogs for different audiences:

```yaml
- uses: nosovj/llm-release-action@v1
  id: release
  with:
    model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
    changelog_config: |
      audiences:
        developer:
          description: "Technical users who need API details"
          tone: professional
          languages: [en]
        customer:
          description: "End users who care about benefits"
          tone: friendly
          benefit_focused: true
          use_emojis: true
          languages: [en, es, ja]
        executive:
          description: "Business stakeholders"
          tone: formal
          summary_only: true
          max_items: 5
          languages: [en]
  env:
    AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
    AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    AWS_REGION: us-east-1

- name: Get Customer Changelog (Spanish)
  run: |
    echo '${{ steps.release.outputs.changelogs }}' | jq -r '.customer.es'
```

### Different Models for Analysis vs Changelog

Use a smarter model for analysis, faster model for changelogs:

```yaml
- uses: nosovj/llm-release-action@v1
  with:
    model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
    model_analysis: bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
    model_changelog: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
```

### With OpenAI

```yaml
- uses: nosovj/llm-release-action@v1
  with:
    model: openai/gpt-4o-mini
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### With Anthropic Direct

```yaml
- uses: nosovj/llm-release-action@v1
  with:
    model: anthropic/claude-3-5-haiku-20241022
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Monitor LLM Costs

```yaml
- uses: nosovj/llm-release-action@v1
  id: release
  with:
    model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0

- name: Log Usage
  run: |
    echo "LLM Usage: ${{ steps.release.outputs.usage }}"
```

## Versioning Rules

The action is conservative about version bumps:

**MAJOR** (requires explicit evidence):
- Commit contains `BREAKING CHANGE:` in body
- Commit type ends with `!` (e.g., `feat!:`, `fix!:`)
- API endpoint or field removal in OpenAPI diff
- Database column drop in migration diff

**MINOR** (new functionality):
- Commits with `feat:` type
- New API endpoints or fields

**PATCH** (everything else):
- Bug fixes (`fix:`)
- Documentation, tests, chores
- Internal improvements

## Supported Providers

Any LLM provider supported by [LiteLLM](https://docs.litellm.ai/docs/providers):

- **AWS Bedrock**: `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`
- **Anthropic**: `anthropic/claude-3-5-haiku-20241022`
- **OpenAI**: `openai/gpt-4o-mini`, `openai/gpt-4o`
- **Azure OpenAI**: `azure/<deployment-name>`
- And many more...

## Evals

The action includes a DeepEval test suite to verify LLM output quality:

```bash
# Install eval dependencies
pip install -r evals/requirements.txt

# Run evals (requires AWS credentials for Bedrock)
PYTHONPATH=src pytest evals/ -v -m eval
```

Evals cover:
- Version bump accuracy (patch/minor/major detection)
- Changelog quality and structure
- Breaking change detection
- Audience transformation (technical vs customer-friendly)
- Language translation quality

## Security Considerations

- **Commit messages are sent to the LLM provider.** For sensitive repositories, consider using a self-hosted LLM or AWS Bedrock (data stays in your AWS account).
- Commit messages are sanitized to remove XML-like tags (prompt injection protection).
- LLM outputs are validated (bump must be exactly `major`, `minor`, or `patch`).
- Changelog is sanitized (HTML stripped, size limited).

## Requirements

- `fetch-depth: 0` in checkout action (full git history required)
- API credentials for your chosen LLM provider

## License

MIT
