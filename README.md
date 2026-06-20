# Dockerfile Doctor

Dockerfile Doctor is now a research project, not a production one-click
Dockerfile fixer.

The original product hypothesis was straightforward: a deterministic tool could
find common Dockerfile problems and safely rewrite many of them for CI bots or
batch pull requests. After building the rule set, fixer matrix, GitHub corpus
gate, and manual equivalence review workflow, the evidence does not support
that product direction.

The project remains useful as a benchmark and research artifact for studying
where static Dockerfile auto-fixing works, where it fails, and what proof is
required before a generated patch can be trusted.

## Current Conclusion

Do not treat this repository as a source of unattended upstream PRs.

On the current diversified GitHub corpus:

- 100 Dockerfile-like files were collected from 41 public repositories.
- 738 issues were detected.
- 139 fixer operations were generated across 62 files.
- Manual diff review classified the 62 fixed files as:
  - 6 behavior-equivalent by inspection.
  - 8 mostly equivalent but still requiring build proof.
  - 48 non-equivalent, context-risky, documentation/test fixture rewrites, or
    otherwise unsafe for blind PRs.

This means the one-click auto-fix premise failed on the current sample: most
generated patches are not semantic-preserving transformations.

## What Was Learned

The demand signal is real. Modern public Dockerfiles still contain many
security, maintainability, and reproducibility findings: unpinned base images,
missing `USER`, missing health checks, package-manager cleanup gaps, shell
pipelines without `pipefail`, legacy `MAINTAINER`, deprecated base images, and
other recurring issues.

The hard part is not finding issues. The hard part is proving that an automatic
rewrite preserves the author's intent.

Examples from the corpus:

- Adding `set -o pipefail` is good hardening, but it changes whether a build
  succeeds when an earlier pipeline command fails.
- Replacing an old base image changes the operating system, packages, ABI,
  vulnerabilities, and runtime behavior.
- Adding JVM container flags changes memory/runtime behavior.
- Converting shell-form `CMD` or `ENTRYPOINT` changes quoting, expansion,
  signal, and process semantics.
- Removing `sudo` changes user and permission assumptions.
- Rewriting `ADD` to `COPY` is only safe for local non-archive sources; it is
  wrong for remote URLs and misleading inside documentation snippets.
- Test fixtures and vulnerability labs often intentionally contain "bad"
  Dockerfiles.

## What Is Still Valuable

The reusable value is the evaluation framework, not the one-click fixer story.

- **Rule taxonomy:** 80 rules covering Dockerfile security, performance,
  correctness, and maintainability.
- **Policy matrix:** each rule is classified as safe, review-only, or advisory
  for test purposes in `tests/rule_matrix.py`.
- **Canonical cases:** every rule has trigger and clean cases in
  `tests/rule_cases.py`.
- **Fixer contracts:** matrix tests verify rule registration, issue metadata,
  public fixer behavior, review-only behavior, idempotency, and convergence.
- **Corpus collector:** `scripts/collect_github_dockerfiles.py` performs
  read-only GitHub collection and preserves repository, commit, source path,
  immutable URL, raw URL, local path, and content hash metadata.
- **Corpus gate:** `scripts/run_corpus_gate.py` runs the fixer pipeline across
  the corpus, records issues/fixes/idempotency, and prunes stale generated
  fixed files.
- **Manual-review validator:** `scripts/review_corpus_fixes.py` verifies that
  every current fixed output has a human equivalence review row and no stale
  generated file remains.

These pieces are useful for research on automatic code modification,
Dockerfile linting, and LLM/tool-assisted repair evaluation.

## Current Research Workflow

The corpus workflow is read-only with respect to GitHub. It does not open
issues, create branches, submit pull requests, or comment upstream.

```bash
python scripts/collect_github_dockerfiles.py \
  --query "language:Dockerfile stars:>100 archived:false fork:false is:public" \
  --max-repos 120 \
  --max-files 100 \
  --max-files-per-repo 5 \
  --include-containerfile

python scripts/run_corpus_gate.py \
  --write-fixed \
  --prune-fixed \
  --strict-remaining-applied

python scripts/review_corpus_fixes.py --write-draft
# Inspect every generated diff and fill reports/manual_review.md.
python scripts/review_corpus_fixes.py
```

The current manual review report is generated under:

```text
corpus/github_dockerfiles/reports/manual_review.md
```

`corpus/github_dockerfiles/` is intentionally ignored by git because it is a
local generated dataset snapshot.

## Running Tests

```bash
python -m pytest -q
python -m pytest --cov=dockerfile_doctor --cov-report=term-missing -q
```

Current verification at the time of this README rewrite:

- 1,500+ tests in the repository.
- `1852 passed`.
- Total package coverage: 98%.
- Corpus gate: 100 files, 139 fixer operations, 0 failures.
- Manual review validator: 62 reviewed fixed files, no stale or missing fixed
  outputs.

## Rule Coverage

80 rules across security, performance, correctness, and maintainability.

### Research Safe-Fix Bucket

These rules still have public fixer handlers in the current prototype. The
bucket name is historical and test-oriented; it does not mean every generated
patch is safe for unattended upstream PRs.

`DD004`, `DD007`, `DD009`, `DD011`, `DD013`, `DD017`, `DD019`, `DD021`, `DD023`,
`DD024`, `DD025`, `DD026`, `DD031`, `DD033`, `DD034`, `DD036`, `DD037`, `DD040`,
`DD041`, `DD043`, `DD044`, `DD045`, `DD047`, `DD048`, `DD049`, `DD050`, `DD051`,
`DD055`, `DD056`, `DD059`, `DD061`, `DD062`, `DD065`, `DD068`, `DD071`, `DD073`,
`DD075`, `DD076`, `DD077`, `DD079`, `DD080`.

### Review-Only Suggestions

`DD003`, `DD005`, `DD008`, `DD010`, `DD015`, `DD035`, `DD046`, `DD067`, `DD072`,
`DD078`.

### Advisory / Non-Fix Rules

`DD001`, `DD002`, `DD006`, `DD012`, `DD014`, `DD016`, `DD018`, `DD020`, `DD022`,
`DD027`, `DD028`, `DD029`, `DD030`, `DD032`, `DD038`, `DD039`, `DD042`, `DD052`,
`DD053`, `DD054`, `DD057`, `DD058`, `DD060`, `DD063`, `DD064`, `DD066`, `DD069`,
`DD070`, `DD074`.

## Suggested Future Use

Recommended:

- Use this repository as a research benchmark.
- Use the rule taxonomy to study Dockerfile quality patterns.
- Use the corpus gate to evaluate fixers or LLM-generated patches.
- Use manual equivalence review data to decide which rewrites can ever be made
  safe.

Not recommended:

- Do not market this as a production one-click Dockerfile fixer.
- Do not run generated patches as unattended upstream PRs.
- Do not expand the fixer count without first adding corpus evidence and
  equivalence review.

## License

Apache 2.0
