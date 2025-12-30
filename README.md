# LLM Semantic Version Action

A GitHub Action that uses LLM to analyze commits and suggest semantic version bumps.

## Features

- Analyzes commit history to determine appropriate version bump (major, minor, patch)
- Supports multiple LLM providers via [LiteLLM](https://github.com/BerriAI/litellm)
- Detects breaking changes from commit messages and file diffs
- Generates release notes grouped by category
- Conservative versioning (only suggests major when explicit evidence exists)

## Quick Start

```yaml
- uses: nosovj/llm-semver-action@v1
  with:
    model: anthropic/claude-3-haiku-20240307
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `model` | Yes | - | LiteLLM model string (e.g., `anthropic/claude-3-haiku-20240307`) |
| `current_version` | No | auto-detect | Version to compare from. Auto-detects from latest semver tag if not provided. |
| `head_ref` | No | `HEAD` | Head ref to compare to |
| `include_diffs` | No | `**/openapi*.yaml,**/migrations/**,**/*.proto` | File patterns for diff analysis (comma-separated) |
| `max_commits` | No | `50` | Max recent commits to include in full (rest summarized) |
| `temperature` | No | `0.2` | LLM temperature (lower = more deterministic) |
| `max_tokens` | No | `2000` | Max tokens in LLM response |
| `timeout` | No | `60` | Request timeout in seconds |
| `debug` | No | `false` | Enable verbose debug logging |
| `dry_run` | No | `false` | Perform analysis without suggesting version |

## Outputs

| Output | Description |
|--------|-------------|
| `bump` | Bump type: `major`, `minor`, or `patch` |
| `current_version` | The version compared from (detected or provided) |
| `next_version` | Calculated next semantic version |
| `changelog` | Generated markdown changelog |
| `breaking_changes` | JSON array of detected breaking changes |
| `reasoning` | LLM explanation for the version suggestion |

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

      - uses: nosovj/llm-semver-action@v1
        id: semver
        with:
          model: anthropic/claude-3-haiku-20240307
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Create Release
        run: |
          echo "Creating release ${{ steps.semver.outputs.next_version }}"
          echo "Bump type: ${{ steps.semver.outputs.bump }}"
```

### With OpenAI

```yaml
- uses: nosovj/llm-semver-action@v1
  with:
    model: openai/gpt-4o-mini
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### Explicit Version

```yaml
- uses: nosovj/llm-semver-action@v1
  with:
    model: anthropic/claude-3-haiku-20240307
    current_version: v1.2.0
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Dry-Run on PR

```yaml
name: PR Version Check
on:
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: nosovj/llm-semver-action@v1
        id: semver
        with:
          model: anthropic/claude-3-haiku-20240307
          dry_run: true
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - uses: actions/github-script@v6
        with:
          script: |
            github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## Version Suggestion\n\n**Bump**: ${{ steps.semver.outputs.bump }}\n**Next Version**: ${{ steps.semver.outputs.next_version }}\n\n${{ steps.semver.outputs.reasoning }}`
            })
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

- Anthropic: `anthropic/claude-3-haiku-20240307`, `anthropic/claude-sonnet-4-20250514`
- OpenAI: `openai/gpt-4o-mini`, `openai/gpt-4o`
- Azure OpenAI: `azure/<deployment-name>`
- And many more...

## Security Considerations

- **Commit messages are sent to the LLM provider.** For sensitive repositories, consider using a self-hosted LLM.
- Commit messages are sanitized to remove XML-like tags (prompt injection protection).
- LLM outputs are validated (bump must be exactly `major`, `minor`, or `patch`).
- Changelog is sanitized (HTML stripped, size limited).

## Requirements

- `fetch-depth: 0` in checkout action (full git history required)
- API key for your chosen LLM provider

## License

MIT
