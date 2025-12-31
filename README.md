# LLM Release Action

A GitHub Action that uses LLM to analyze commits, suggest semantic version bumps, and generate multi-audience changelogs.

## Features

### Semantic Version Analysis
- Analyzes commit history to determine appropriate version bump (major, minor, patch)
- Detects breaking changes from commit messages, conventional commit markers, and file diffs
- Conservative versioning: only suggests major bumps when explicit evidence exists
- Extracts structured change data with categories, importance, and user benefits

### Multi-Audience Changelog Generation
- **Multiple audiences**: Generate different changelogs for developers, customers, executives, marketing, security, ops
- **Multiple languages**: Translate changelogs to any language (en, es, ja, de, fr, zh, etc.)
- **Customizable tone**: formal, casual, professional, excited, friendly
- **Flexible sections**: breaking, security, features, improvements, fixes, performance, deprecations, infrastructure, docs
- **Content filtering**: exclude categories, patterns, labels, or authors per audience
- **Metadata generation**: auto-generate release titles, summaries, and highlights
- **Parallel execution**: all changelog transformations run concurrently for speed

### Additional Features
- **Multiple LLM Providers**: Supports any provider via [LiteLLM](https://github.com/BerriAI/litellm) (Anthropic, OpenAI, AWS Bedrock, etc.)
- **Usage Tracking**: Returns token counts and latency per model for cost monitoring
- **Multi-repo support**: Combine changelogs from multiple repositories into a single product release

## How It Works

The action runs in two phases:

1. **Phase 1 - Semantic Analysis**: Analyzes commits and diffs to extract structured changes with categories, importance levels, user benefits, and technical details. Determines the appropriate version bump.

2. **Phase 2 - Changelog Generation**: Transforms the structured changes into audience-specific changelogs. Each audience/language combination runs in parallel. Applies filtering, tone, formatting, and translation.

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

| Output | Type | Description |
|--------|------|-------------|
| `bump` | `string` | Bump type: `major`, `minor`, or `patch` |
| `current_version` | `string` | The version compared from (detected or provided) |
| `next_version` | `string` | Calculated next semantic version (e.g., `v1.2.0`) |
| `changelog` | `string` | Generated markdown changelog (legacy single changelog) |
| `changelogs` | `{audience: {lang: string}}` | Changelogs per audience and language. See [schema](#changelogs) |
| `metadata` | `{audience: {lang: Metadata}}` | Release metadata (title, summary, highlights) per audience. See [schema](#metadata) |
| `changes` | `Change[]` | Structured changes with category, title, commits, authors, breaking info. See [schema](#changes) |
| `stats` | `Stats` | Change counts by category and contributor count. See [schema](#stats) |
| `breaking_changes` | `BreakingChange[]` | Extracted breaking changes with severity and migration steps. See [schema](#breaking_changes) |
| `reasoning` | `string` | LLM explanation for the version suggestion |
| `usage` | `{model: UsageStats}` | Token counts and latency per model. See [schema](#usage) |

### Output Schemas

#### `changelogs`

Nested object: `{[audience: string]: {[language: string]: string}}`

```json
{
  "customer": {
    "en": "## What's New\n\n### ✨ Features\n- **Dark Mode** - Easier on the eyes...",
    "es": "## Novedades\n\n### ✨ Características\n- **Modo Oscuro** - Más fácil para los ojos..."
  },
  "developer": {
    "en": "## Changelog\n\n### Breaking Changes\n- Removed deprecated `/api/v1` endpoints..."
  }
}
```

#### `metadata`

Nested object: `{[audience: string]: {[language: string]: Metadata}}`

```typescript
interface Metadata {
  title: string | null;    // Generated release title (if generate_title: true)
  summary: string | null;  // 1-2 sentence summary (if generate_summary: true)
  highlights: string[];    // Key highlights (if generate_highlights > 0)
}
```

```json
{
  "customer": {
    "en": {
      "title": "February Release: Dark Mode & Performance",
      "summary": "This release brings the long-awaited dark mode and 2x faster load times.",
      "highlights": ["Dark mode support", "50% faster page loads", "New dashboard widgets"]
    }
  }
}
```

#### `changes`

Array of structured changes from Phase 1 analysis:

```typescript
interface Change {
  id: string;                        // Unique identifier
  category: Category;                // See categories below
  title: string;                     // Short description
  description: string;               // Detailed description
  commits: string[];                 // Associated commit hashes
  authors: string[];                 // Contributors
  importance: "high" | "medium" | "low";
  user_benefit: string | null;       // What users gain
  technical_detail: string | null;   // Implementation details
  breaking: BreakingInfo | null;     // Breaking change details
  labels: string[];                  // Associated labels
  source: string | null;             // Source repo (multi-repo mode)
  pr_number: number | null;          // Pull request number
  issue_numbers: number[];           // Related issues
}

type Category = "breaking" | "security" | "feature" | "improvement"
              | "fix" | "performance" | "deprecation"
              | "infrastructure" | "docs" | "other";

interface BreakingInfo {
  severity: "high" | "medium" | "low";
  affected: string;                  // What is affected
  migration: string[];               // Migration steps
}
```

```json
[
  {
    "id": "change-1",
    "category": "feature",
    "title": "Add dark mode support",
    "description": "Users can now toggle between light and dark themes",
    "commits": ["abc1234", "def5678"],
    "authors": ["alice", "bob"],
    "importance": "high",
    "user_benefit": "Reduced eye strain during nighttime use",
    "technical_detail": "Implemented via CSS variables with system preference detection",
    "breaking": null,
    "labels": ["ui", "accessibility"],
    "source": null,
    "pr_number": 123,
    "issue_numbers": [100, 101]
  },
  {
    "id": "change-2",
    "category": "breaking",
    "title": "Remove deprecated API v1 endpoints",
    "description": "All /api/v1/* endpoints have been removed",
    "commits": ["ghi9012"],
    "authors": ["charlie"],
    "importance": "high",
    "user_benefit": null,
    "technical_detail": null,
    "breaking": {
      "severity": "high",
      "affected": "API consumers using v1 endpoints",
      "migration": ["Update base URL from /api/v1 to /api/v2", "Update auth header format"]
    },
    "labels": ["api"],
    "source": null,
    "pr_number": 456,
    "issue_numbers": []
  }
]
```

#### `stats`

Counts of changes by category:

```typescript
interface Stats {
  features: number;
  fixes: number;
  improvements: number;
  breaking: number;
  security: number;
  performance: number;
  deprecations: number;
  infrastructure: number;
  docs: number;
  other: number;
  contributors: number;  // Unique authors count
}
```

```json
{
  "features": 5,
  "fixes": 12,
  "improvements": 3,
  "breaking": 1,
  "security": 0,
  "performance": 2,
  "deprecations": 1,
  "infrastructure": 4,
  "docs": 2,
  "other": 0,
  "contributors": 8
}
```

#### `breaking_changes`

Extracted breaking changes for easy access:

```typescript
interface BreakingChange {
  title: string;
  severity: "high" | "medium" | "low";
  affected: string;
  migration: string[];
}
```

```json
[
  {
    "title": "Remove deprecated API v1 endpoints",
    "severity": "high",
    "affected": "API consumers using v1 endpoints",
    "migration": ["Update base URL from /api/v1 to /api/v2", "Update auth header format"]
  }
]
```

#### `usage`

LLM usage statistics per model:

```typescript
interface Usage {
  [model: string]: {
    calls: number;         // Number of LLM calls
    input_tokens: number;  // Total input tokens
    output_tokens: number; // Total output tokens
    latency_ms: number;    // Total latency in milliseconds
  }
}
```

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
      developer:
        preset: developer
        languages: [en]
      customer:
        preset: customer
        emojis: true
        languages: [en, es, ja]
      executive:
        preset: executive
        max_items_per_section: 5
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

## Changelog Config Schema

The `changelog_config` input accepts YAML defining one or more audiences. Each audience key becomes a key in the `changelogs` output.

### Using Presets

Presets provide sensible defaults for common audiences:

| Preset | Description | Default Sections | Tone |
|--------|-------------|------------------|------|
| `developer` | Full technical changelog with commits, PRs, contributors | All sections | professional |
| `customer` | User-facing changes with benefits focus | breaking, features, improvements, fixes | friendly |
| `executive` | High-level business summary | breaking, features | formal |
| `marketing` | Promotional feature announcements | features, improvements | excited |
| `security` | Security-focused with CVE details | security, breaking, fixes | formal |
| `ops` | Operations/DevOps focused | breaking, infrastructure, performance, security | professional |

```yaml
changelog_config: |
  developer:
    preset: developer
  customer:
    preset: customer
    languages: [en, es, fr]
```

### Full Schema Reference

```yaml
<audience_name>:
  # Base settings
  preset: developer|customer|executive|marketing|security|ops  # Optional, provides defaults
  languages: [en, es, ja, ...]  # ISO 639-1 codes, default: [en]

  # Sections to include (in order)
  sections:
    - breaking      # Breaking changes
    - security      # Security patches
    - features      # New features
    - improvements  # Enhancements
    - fixes         # Bug fixes
    - performance   # Performance improvements
    - deprecations  # Deprecated features
    - infrastructure # CI/CD, build, deps
    - docs          # Documentation
    - other         # Everything else

  # Content options
  include_commits: false       # Include commit hashes
  include_contributors: false  # List authors
  include_infrastructure: true # Include infra changes
  group_related: true          # Group related changes
  benefit_focused: false       # Focus on user benefits vs technical
  summary_only: false          # Brief summary instead of full list

  # Filtering
  exclude_categories: []       # Categories to hide: [infrastructure, docs, other]
  exclude_patterns: []         # Regex patterns to exclude
  exclude_labels: []           # Labels to exclude
  exclude_authors: []          # Authors to exclude
  max_items_per_section: null  # Limit items per section

  # Style
  emojis: false                # Include emojis in output
  tone: professional           # formal|casual|professional|excited|friendly

  # Breaking changes
  breaking_highlight: true     # Highlight breaking changes
  breaking_migration: true     # Include migration steps
  breaking_severity: true      # Show severity level

  # Links (requires repo URL detection)
  link_commits: false          # Link to commit URLs
  link_prs: false              # Link to PR URLs
  link_issues: false           # Link to issue URLs

  # Metadata generation
  generate_title: false        # Generate release title
  generate_summary: false      # Generate 1-2 sentence summary
  generate_highlights: 0       # Number of highlights to generate

  # Output format
  output_format: markdown      # markdown|html|json|plain
```

### Custom Audience Example

```yaml
changelog_config: |
  api-consumers:
    languages: [en]
    sections: [breaking, features, deprecations]
    tone: formal
    include_commits: true
    link_commits: true
    breaking_migration: true
    emojis: false

  internal-devs:
    preset: developer
    include_infrastructure: true

  release-notes:
    preset: customer
    generate_title: true
    generate_summary: true
    generate_highlights: 3
    languages: [en, es, de, ja, zh]
```

## Content Override (Multi-Repo Analysis)

The `content_override` input bypasses git commit detection and accepts pre-formatted changelog content. This is useful for:

- **Monorepo releases**: Aggregate changes from multiple packages
- **Multi-repo products**: Combine changelogs from frontend, backend, mobile repos
- **External sources**: Process changes from external systems (Jira, Linear, etc.)

### Format

Content should be structured markdown with clear sections:

```markdown
## Frontend (v2.1.0)
### Features
- New dashboard with real-time analytics
- Dark mode support

### Fixes
- Fixed login redirect on Safari

## Backend (v3.0.0)
### Breaking Changes
- Removed deprecated /api/v1 endpoints
- Changed auth token format (migration guide: docs/auth-migration.md)

### Features
- Added GraphQL subscriptions
- New rate limiting with Redis

## Mobile (v1.5.0)
### Features
- Push notification preferences
- Offline mode improvements
```

### Multi-Repo Workflow Example

```yaml
name: Product Release
on:
  workflow_dispatch:
    inputs:
      frontend_version:
        description: 'Frontend version'
        required: true
      backend_version:
        description: 'Backend version'
        required: true

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      # Fetch changelogs from each repo
      - name: Get Frontend Changelog
        id: frontend
        run: |
          CHANGELOG=$(gh api repos/myorg/frontend/releases/tags/${{ inputs.frontend_version }} --jq '.body')
          echo "changelog<<EOF" >> $GITHUB_OUTPUT
          echo "$CHANGELOG" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Get Backend Changelog
        id: backend
        run: |
          CHANGELOG=$(gh api repos/myorg/backend/releases/tags/${{ inputs.backend_version }} --jq '.body')
          echo "changelog<<EOF" >> $GITHUB_OUTPUT
          echo "$CHANGELOG" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      # Analyze combined changes
      - uses: nosovj/llm-release-action@v1
        id: release
        with:
          model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
          current_version: v2024.12.0
          content_override: |
            ## Frontend ${{ inputs.frontend_version }}
            ${{ steps.frontend.outputs.changelog }}

            ## Backend ${{ inputs.backend_version }}
            ${{ steps.backend.outputs.changelog }}
          changelog_config: |
            customer:
              preset: customer
              languages: [en, es]
            internal:
              preset: developer
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_REGION: us-east-1

      - name: Create Product Release
        run: |
          echo "Version: ${{ steps.release.outputs.next_version }}"
          echo "Customer changelog:"
          echo '${{ steps.release.outputs.changelogs }}' | jq -r '.customer.en'
```

### Security Notes for content_override

- Content is scanned for injection patterns (role hijacking, instruction injection)
- Content is truncated if it exceeds token limits (~8000 tokens)
- Suspicious patterns trigger warnings but don't block execution
- Critical threats (>500KB content) are rejected

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
