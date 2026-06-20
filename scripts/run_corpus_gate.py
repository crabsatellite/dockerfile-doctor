#!/usr/bin/env python3
"""Run Dockerfile Doctor against a collected Dockerfile corpus."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dockerfile_doctor.fixer import fix  # noqa: E402
from dockerfile_doctor.parser import parse  # noqa: E402
from dockerfile_doctor.rules import analyze  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    entries = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def issue_record(issue: Any, source_html_url: str) -> dict[str, Any]:
    line_url = source_html_url
    if issue.line_number > 0:
        line_url = f"{source_html_url}#L{issue.line_number}"
    return {
        "rule_id": issue.rule_id,
        "title": issue.title,
        "severity": issue.severity.value,
        "category": issue.category.value,
        "line_number": issue.line_number,
        "source_line_url": line_url,
        "fix_available": issue.fix_available,
    }


def fix_record(fix_obj: Any) -> dict[str, Any]:
    return {
        "rule_id": fix_obj.rule_id,
        "description": fix_obj.description,
        "replacement_count": len(fix_obj.replacements),
        "insertion_count": len(fix_obj.insertions),
        "deletion_count": len(fix_obj.deletions),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixed_relpath(fixed_local_path: str | None) -> str | None:
    if not fixed_local_path:
        return None
    return fixed_local_path.removeprefix("fixed/").replace("\\", "/")


def prune_stale_fixed_files(corpus_dir: Path, expected_fixed: set[str]) -> int:
    fixed_dir = corpus_dir / "fixed"
    if not fixed_dir.exists():
        return 0
    pruned = 0
    for path in sorted((p for p in fixed_dir.rglob("*") if p.is_file()), reverse=True):
        relpath = str(path.relative_to(fixed_dir)).replace("\\", "/")
        if relpath not in expected_fixed:
            path.unlink()
            pruned += 1
    for path in sorted((p for p in fixed_dir.rglob("*") if p.is_dir()), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass
    return pruned


def run_entry(
    corpus_dir: Path,
    entry: dict[str, Any],
    *,
    write_fixed: bool,
) -> tuple[dict[str, Any], str | None]:
    local_path = corpus_dir / entry["local_path"]
    content = local_path.read_text(encoding="utf-8", errors="replace")
    dockerfile = parse(content)
    issues = analyze(dockerfile)
    fixed_content, fixes = fix(dockerfile, issues)
    fixed_df = parse(fixed_content)
    fixed_issues = analyze(fixed_df)
    fixed_again, fixes_again = fix(fixed_df, fixed_issues)

    idempotent = fixed_again == fixed_content and not fixes_again
    applied_rule_ids = {fix_obj.rule_id for fix_obj in fixes}
    remaining_applied_rules = sorted({
        issue.rule_id
        for issue in fixed_issues
        if issue.rule_id in applied_rule_ids
    })

    fixed_local_path = None
    if write_fixed and fixed_content != content:
        fixed_path = corpus_dir / "fixed" / entry["local_path"]
        fixed_path.parent.mkdir(parents=True, exist_ok=True)
        fixed_path.write_text(fixed_content, encoding="utf-8")
        fixed_local_path = str(fixed_path.relative_to(corpus_dir)).replace("\\", "/")

    result = {
        "repo_full_name": entry["repo_full_name"],
        "commit_sha": entry["commit_sha"],
        "source_path": entry["source_path"],
        "source_html_url": entry["source_html_url"],
        "local_path": entry["local_path"],
        "fixed_local_path": fixed_local_path,
        "issue_count": len(issues),
        "fixable_issue_count": sum(1 for issue in issues if issue.fix_available),
        "applied_fix_count": len(fixes),
        "fixed_issue_count": len(fixed_issues),
        "idempotent": idempotent,
        "remaining_applied_rules": remaining_applied_rules,
        "issues": [issue_record(issue, entry["source_html_url"]) for issue in issues],
        "fixes": [fix_record(fix_obj) for fix_obj in fixes],
    }

    failure = None
    if not idempotent:
        failure = "not_idempotent"
    return result, failure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="corpus/github_dockerfiles")
    parser.add_argument("--manifest", default="manifest.jsonl")
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--write-fixed", action="store_true")
    parser.add_argument(
        "--prune-fixed",
        action="store_true",
        help="Delete generated fixed files that are not referenced by this gate run",
    )
    parser.add_argument("--strict-remaining-applied", action="store_true")
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus)
    manifest_path = corpus_dir / args.manifest
    entries = load_manifest(manifest_path)
    if args.max_files is not None:
        entries = entries[:args.max_files]

    reports_dir = corpus_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    results_path = reports_dir / "gate_results.jsonl"
    failures: list[dict[str, Any]] = []
    issue_counter: Counter[str] = Counter()
    fix_counter: Counter[str] = Counter()
    severity_counter: Counter[str] = Counter()
    expected_fixed: set[str] = set()

    with results_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            try:
                result, failure = run_entry(corpus_dir, entry, write_fixed=args.write_fixed)
            except Exception as exc:
                result = {
                    "repo_full_name": entry.get("repo_full_name"),
                    "commit_sha": entry.get("commit_sha"),
                    "source_path": entry.get("source_path"),
                    "source_html_url": entry.get("source_html_url"),
                    "local_path": entry.get("local_path"),
                    "error": repr(exc),
                }
                failure = "exception"

            for issue in result.get("issues", []):
                issue_counter[issue["rule_id"]] += 1
                severity_counter[issue["severity"]] += 1
            for fix_obj in result.get("fixes", []):
                fix_counter[fix_obj["rule_id"]] += 1
            relpath = fixed_relpath(result.get("fixed_local_path"))
            if relpath:
                expected_fixed.add(relpath)

            if args.strict_remaining_applied and result.get("remaining_applied_rules"):
                failure = failure or "remaining_applied_rules"
            if failure:
                failures.append({
                    "failure": failure,
                    "repo_full_name": result.get("repo_full_name"),
                    "source_path": result.get("source_path"),
                    "source_html_url": result.get("source_html_url"),
                    "details": result.get("error") or result.get("remaining_applied_rules"),
                })
            handle.write(json.dumps(result, sort_keys=True) + "\n")

    pruned_fixed_files = 0
    if args.write_fixed and args.prune_fixed:
        pruned_fixed_files = prune_stale_fixed_files(corpus_dir, expected_fixed)

    summary = {
        "generated_at": utc_now(),
        "manifest": str(manifest_path),
        "files_evaluated": len(entries),
        "failures": failures,
        "failure_count": len(failures),
        "issue_count": sum(issue_counter.values()),
        "fix_count": sum(fix_counter.values()),
        "issues_by_rule": dict(sorted(issue_counter.items())),
        "fixes_by_rule": dict(sorted(fix_counter.items())),
        "issues_by_severity": dict(sorted(severity_counter.items())),
        "pruned_fixed_files": pruned_fixed_files,
        "results": str(results_path.relative_to(corpus_dir)),
        "write_fixed": args.write_fixed,
    }
    write_json(reports_dir / "gate_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
