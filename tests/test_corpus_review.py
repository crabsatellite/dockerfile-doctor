"""Tests for corpus manual-review coverage validation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "review_corpus_fixes.py"
SPEC = importlib.util.spec_from_file_location("review_corpus_fixes", SCRIPT)
assert SPEC and SPEC.loader
review_corpus_fixes = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review_corpus_fixes
SPEC.loader.exec_module(review_corpus_fixes)


def _write_results(corpus: Path) -> Path:
    reports = corpus / "reports"
    reports.mkdir(parents=True)
    rows = [
        {
            "repo_full_name": "example/app",
            "source_path": "Dockerfile",
            "source_html_url": "https://github.com/example/app/blob/abc/Dockerfile",
            "fixed_local_path": "fixed/files/example__app/Dockerfile",
            "fixes": [{"rule_id": "DD073"}],
        },
        {
            "repo_full_name": "example/api",
            "source_path": "docker/Dockerfile",
            "source_html_url": "https://github.com/example/api/blob/def/docker/Dockerfile",
            "fixed_local_path": "fixed/files/example__api/docker/Dockerfile",
            "fixes": [{"rule_id": "DD004"}, {"rule_id": "DD009"}],
        },
    ]
    results = reports / "gate_results.jsonl"
    results.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    for row in rows:
        fixed_path = corpus / row["fixed_local_path"]
        fixed_path.parent.mkdir(parents=True, exist_ok=True)
        fixed_path.write_text("FROM scratch\n", encoding="utf-8")
    return results


def _write_review(corpus: Path, *, omit_second: bool = False) -> Path:
    report = corpus / "reports" / "manual_review.md"
    rows = [
        "| # | source | fixes | value | equivalent | PR readiness | manual note |",
        "|---:|---|---|---|---|---|---|",
        "| 1 | [example/app::Dockerfile](https://github.com/example/app/blob/abc/Dockerfile) | `DD073` | low | yes | no standalone | final newline only |",
    ]
    if not omit_second:
        rows.append(
            "| 2 | [example/api::docker/Dockerfile](https://github.com/example/api/blob/def/docker/Dockerfile) | "
            "`DD004,DD009` | medium | mostly | build proof required | useful hygiene after diff review |"
        )
    report.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return report


def test_validate_review_accepts_complete_current_report(tmp_path):
    corpus = tmp_path / "corpus"
    results = _write_results(corpus)
    report = _write_review(corpus)

    failures = review_corpus_fixes.validate_review(corpus, results, report)

    assert failures == []


def test_validate_review_rejects_missing_review_row(tmp_path):
    corpus = tmp_path / "corpus"
    results = _write_results(corpus)
    report = _write_review(corpus, omit_second=True)

    failures = review_corpus_fixes.validate_review(corpus, results, report)

    assert any("missing review row" in failure for failure in failures)


def test_validate_review_rejects_stale_fixed_file(tmp_path):
    corpus = tmp_path / "corpus"
    results = _write_results(corpus)
    report = _write_review(corpus)
    stale = corpus / "fixed" / "files" / "stale__repo" / "Dockerfile"
    stale.parent.mkdir(parents=True)
    stale.write_text("FROM scratch\n", encoding="utf-8")

    failures = review_corpus_fixes.validate_review(corpus, results, report)

    assert any("stale fixed file" in failure for failure in failures)


def test_write_draft_requires_manual_fields_before_strict_validation(tmp_path):
    corpus = tmp_path / "corpus"
    results = _write_results(corpus)
    report = corpus / "reports" / "manual_review.md"

    review_corpus_fixes.write_draft(corpus, results, report)

    strict_failures = review_corpus_fixes.validate_review(corpus, results, report)
    allowed_failures = review_corpus_fixes.validate_review(
        corpus,
        results,
        report,
        allow_placeholders=True,
    )
    assert any("placeholder" in failure for failure in strict_failures)
    assert allowed_failures == []
