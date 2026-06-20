# Contributing to Dockerfile Doctor

## Quick Start

```bash
git clone https://github.com/crabsatellite/dockerfile-doctor.git
cd dockerfile-doctor
pip install -e ".[dev]"
pytest
```

## Adding a New Rule

1. Add the rule to `tests/rule_matrix.py` first so its policy bucket and test contract are explicit
2. Add the rule function in `src/dockerfile_doctor/rules.py` with the `@rule` decorator
3. Use the next available DD number (currently DD081+)
4. Add canonical trigger/clean cases in `tests/rule_cases.py`
5. Add or update the primary behavioral tests named by the rule matrix
6. If auto-fixable, add a handler in `src/dockerfile_doctor/fixer.py` with `@_handler("DD0XX")`

## Running Tests

```bash
pytest                          # Run all tests
pytest -x                      # Stop on first failure
pytest --cov=dockerfile_doctor  # With coverage
pytest -k "test_dd001"         # Run specific test
```

## Corpus Gate

The GitHub corpus workflow is read-only. It collects public Dockerfiles, runs
the safe fixer gate, and requires a manual equivalence review for every
generated fixed file before the corpus is used as evidence.

```bash
python scripts/collect_github_dockerfiles.py --include-containerfile --max-files-per-repo 20
python scripts/run_corpus_gate.py --write-fixed --prune-fixed --strict-remaining-applied
python scripts/review_corpus_fixes.py --write-draft
# edit corpus/github_dockerfiles/reports/manual_review.md after inspecting diffs
python scripts/review_corpus_fixes.py
```

Do not submit upstream PRs from corpus output without repo-specific build or
runtime proof. The corpus gate proves parser/fixer convergence and review
coverage; it does not prove semantic equivalence for risky rules.

## Code Style

- Pure Python, zero external dependencies (stdlib only)
- Type annotations on all public functions
- Each rule function returns `list[Issue]`
