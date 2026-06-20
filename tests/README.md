# Test Architecture

The test suite is organized around the rule matrix first, with legacy tests
kept as detailed regression coverage.

## Matrix Layer

- `rule_matrix.py` is the source of truth for every `DD###` rule's policy:
  `safe`, `review-only`, or `advisory`.
- `rule_cases.py` contains one canonical trigger case and one canonical clean
  case for every rule.
- `test_rule_matrix.py` verifies that the matrix matches the registered rules,
  fixer registry, README rule lists, and primary legacy test files.
- `test_rule_contracts.py` verifies uniform behavior for all rules:
  trigger/clean cases, issue metadata, safe fixer convergence, review-only
  public skip behavior, and advisory non-fix behavior.
- `test_fixer_evidence.py` defines the machine confidence bundle for each
  fixer: independent legacy references, trigger-vs-clean comparison, concrete
  recorded operations, post-fix rule elimination, and convergence/idempotency.

## Fixer Confidence Sources

A fixer is not treated as trusted because it appears in the handler registry.
For every `safe` or `review-only` fixer, the suite requires objective evidence:

1. It is registered in `_FIX_HANDLERS`.
2. Its canonical trigger case reports the rule.
3. Its canonical clean case suppresses the rule.
4. It has independent, non-matrix regression references in the legacy suite.
5. It records a concrete replacement, insertion, or deletion.
6. The fixed output parses and no longer reports the same rule.
7. Safe fixes run through the public `fix()` path and converge on the second
   pass.
8. Review-only fixes are skipped by public `fix()` but apply through the
   targeted review helper.

## Regression Layer

- `test_rules.py` covers detailed behavior for `DD001-DD020`.
- `test_rules_expanded.py` and `test_rules_edge_*.py` cover detailed behavior
  for `DD021-DD080`.
- `test_fixer*.py`, `test_integrity.py`, and `test_integration_expanded.py`
  cover fixer interactions, idempotency, adversarial inputs, and pipeline
  regressions.

## Corpus Evidence Layer

- `scripts/collect_github_dockerfiles.py` builds a local, read-only GitHub
  Dockerfile corpus with source repository, commit, URL, and local path
  metadata preserved. Use `--max-files-per-repo` to keep the corpus from being
  dominated by one repository.
- `scripts/run_corpus_gate.py` runs the public safe fixer path against the
  corpus and records issues, fixes, idempotency, remaining applied rules, and
  optional fixed outputs.
- `scripts/review_corpus_fixes.py` generates the manual-review draft and
  validates that every current fixed output has a reviewed row, every row still
  matches the current gate fixes, and no stale fixed files remain.
- `test_corpus_review.py` protects the manual-review completeness validator so
  corpus evidence cannot silently drift away from the generated fixed files.

## Adding or Changing Rules

Update the matrix layer first. A new rule is not considered wired into the test
suite until it has:

1. A `RULE_MATRIX` entry.
2. A `RULE_CASES` trigger and clean case.
3. A primary `TestDD###...` regression class in the matrix's test file.
4. Fixer behavior aligned with its policy bucket.

After that, add focused regression cases for edge conditions and interactions.
