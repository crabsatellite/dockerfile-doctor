#!/usr/bin/env python3
"""Generate and validate manual review coverage for corpus fixed outputs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLACEHOLDERS = {"", "todo", "tbd", "needs-human-review", "needs review"}
DEFAULT_CORPUS = "corpus/github_dockerfiles"
DEFAULT_RESULTS = "reports/gate_results.jsonl"
DEFAULT_REPORT = "reports/manual_review.md"


@dataclass(frozen=True)
class FixedRecord:
    key: str
    source_cell: str
    fixed_relpath: str
    fixes: str


def load_gate_results(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def fixed_records(rows: list[dict[str, Any]]) -> list[FixedRecord]:
    records: list[FixedRecord] = []
    for row in rows:
        fixed_local_path = row.get("fixed_local_path")
        if not fixed_local_path:
            continue
        repo = row["repo_full_name"]
        source_path = row["source_path"]
        key = f"{repo}::{source_path}"
        source_cell = f"[{key}]({row['source_html_url']})"
        fixes = ",".join(fix["rule_id"] for fix in row.get("fixes", []))
        records.append(FixedRecord(
            key=key,
            source_cell=source_cell,
            fixed_relpath=fixed_local_path.removeprefix("fixed/").replace("\\", "/"),
            fixes=fixes,
        ))
    return records


def fixed_files(corpus_dir: Path) -> set[str]:
    fixed_dir = corpus_dir / "fixed"
    if not fixed_dir.exists():
        return set()
    return {
        str(path.relative_to(fixed_dir)).replace("\\", "/")
        for path in fixed_dir.rglob("*")
        if path.is_file()
    }


def split_markdown_row(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line.strip():
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def review_rows(report_path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not report_path.exists():
        raise FileNotFoundError(report_path)
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| #") or line.startswith("|---"):
            continue
        cells = split_markdown_row(line)
        if len(cells) < 7:
            raise ValueError(f"Malformed review row: {line}")
        source = cells[1]
        fixes = cells[2].strip("`")
        rows[source] = {
            "fixes": fixes,
            "value": cells[3],
            "equivalent": cells[4],
            "pr_readiness": cells[5],
            "manual_note": cells[6],
        }
    return rows


def is_placeholder(value: str) -> bool:
    return value.strip().lower() in PLACEHOLDERS


def validate_review(
    corpus_dir: Path,
    results_path: Path,
    report_path: Path,
    *,
    allow_placeholders: bool = False,
) -> list[str]:
    expected = fixed_records(load_gate_results(results_path))
    expected_sources = {record.source_cell: record for record in expected}
    actual_sources = review_rows(report_path)
    expected_fixed = {record.fixed_relpath for record in expected}
    actual_fixed = fixed_files(corpus_dir)

    failures: list[str] = []
    for relpath in sorted(expected_fixed - actual_fixed):
        failures.append(f"missing fixed file: {relpath}")
    for relpath in sorted(actual_fixed - expected_fixed):
        failures.append(f"stale fixed file: {relpath}")
    for source in sorted(expected_sources.keys() - actual_sources.keys()):
        failures.append(f"missing review row: {source}")
    for source in sorted(actual_sources.keys() - expected_sources.keys()):
        failures.append(f"stale review row: {source}")

    for source, record in sorted(expected_sources.items()):
        row = actual_sources.get(source)
        if row is None:
            continue
        if row["fixes"] != record.fixes:
            failures.append(
                f"fix mismatch for {record.key}: report={row['fixes']} gate={record.fixes}"
            )
        if not allow_placeholders:
            for field in ("value", "equivalent", "pr_readiness", "manual_note"):
                if is_placeholder(row[field]):
                    failures.append(f"placeholder {field} for {record.key}")
    return failures


def write_draft(corpus_dir: Path, results_path: Path, report_path: Path) -> None:
    records = fixed_records(load_gate_results(results_path))
    lines = [
        "# GitHub Dockerfile Fixed Output Manual Review",
        "",
        "Scope: current `manifest.jsonl` and current `reports/gate_results.jsonl`.",
        "",
        "| # | source | fixes | value | equivalent | PR readiness | manual note |",
        "|---:|---|---|---|---|---|---|",
    ]
    for idx, record in enumerate(records, 1):
        lines.append(
            f"| {idx} | {record.source_cell} | `{record.fixes}` | "
            "needs-human-review | needs-human-review | needs-human-review | "
            "Review the actual diff before using this row as evidence. |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} draft rows to {report_path.relative_to(corpus_dir)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--results", default=DEFAULT_RESULTS)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--write-draft", action="store_true")
    parser.add_argument("--allow-placeholders", action="store_true")
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus)
    results_path = corpus_dir / args.results
    report_path = corpus_dir / args.report

    if args.write_draft:
        write_draft(corpus_dir, results_path, report_path)
        return 0

    failures = validate_review(
        corpus_dir,
        results_path,
        report_path,
        allow_placeholders=args.allow_placeholders,
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"Manual review covers {len(fixed_records(load_gate_results(results_path)))} fixed files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
