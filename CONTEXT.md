# LLM Release Action - API Context

This file helps the LLM distinguish public APIs from internal implementation
when analyzing commits for version bumps.

## Public APIs (breaking if changed)

These are documented, versioned, and used by external consumers:

### GitHub Action Interface (`action.yml`)
- All inputs: `model`, `current_version`, `head_ref`, `context_files`, etc.
- All outputs: `bump`, `next_version`, `changelogs`, `warnings`, etc.
- Renaming, removing, or changing types of inputs/outputs is BREAKING

### Output Data Models (`src/models.py`)
- `AnalysisResult` - Phase 1 output structure
- `Change` - individual change item
- `ChangeStats` - statistics summary
- `ReleaseMetadata` - release metadata

### Core Functions (external callers)
- `build_semantic_analysis_prompt()` - main prompt builder
- `parse_phase1_response()` - response parser
- `generate_changelog()` - changelog generation

## Internal Implementation (not breaking if changed)

These are internal details that can change freely:

### Internal Modules
- `text_splitter.py` - chunking implementation
- `summarizing_map_reduce.py` - summarization logic
- `context_loader.py` - context file loading
- `diff_analyzer.py` - diff processing
- `flatten.py` - change consolidation
- `map_reduce.py` - large input processing
- `content_scanner.py` - security scanning

### Internal Functions
- All functions starting with underscore (`_validate*`, `_parse*`, `_extract*`)
- Helper functions not documented in README
- Test utilities and fixtures

### Prompt Templates (`src/prompts.py`)
- `PHASE1_TEMPLATE`, `PHASE2_TEMPLATE` - internal prompts
- `DiffMapConfig`, `Phase1Config` - internal config classes
- Prompt wording changes are internal (as long as outputs match schema)

## Versioning Rules

- **MAJOR**: Remove/rename action.yml inputs or outputs, change output schema
- **MINOR**: Add new inputs/outputs, add new features
- **PATCH**: Bug fixes, internal refactoring, documentation, prompt improvements
