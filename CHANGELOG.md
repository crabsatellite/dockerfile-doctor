# Changelog

All notable changes to this project will be documented in this file.

## [0.1.3] - 2026-03-07

### Fixed
- Fix systemic stale-line-number bug: when DD005 (RUN combining) shrinks the lines
  array in Phase 1, Phase 2 handlers now defer to the next convergence pass instead
  of using stale indices. Fixes DD019 IndexError on Dockerfiles with consecutive RUN
  instructions followed by CMD/ENTRYPOINT.

## [0.1.2] - 2026-03-07

### Fixed
- Fix DD008 (USER instruction) corruption when combined with DD004 (apt cleanup)
  on single-RUN Dockerfiles. Handler now scans mutated lines instead of stale parse data.
- Reporter now shows "N fixes applied" when --fix is used instead of "use --fix to apply".

## [0.1.1] - 2026-03-07

### Fixed
- Fallback YAML parser now supports 2-level nesting for per-rule config overrides
  (e.g. `rules: DD008: severity: error`). Only affected environments without PyYAML.

## [0.1.0] - 2026-03-07

### Added
- 80 lint rules covering security, performance, correctness, and maintainability
- 50 auto-fixers with deterministic, two-phase convergence loop
- Dockerfile parser supporting continuations, heredoc, multi-stage builds, and escape directives
- CLI with --fix, --format (text/json/sarif), --severity, --ignore, --score, --diff
- SARIF 2.1.0 output for GitHub Code Scanning integration
- GitHub Action (action.yml) with diff mode, score, and SARIF upload
- Pre-commit hook support
- Configuration file support (.dockerfile-doctor.yaml)
- Programmatic API: parse, analyze, fix
- Zero external dependencies (PyYAML optional)
