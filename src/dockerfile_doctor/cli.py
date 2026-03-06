"""CLI entry point for Dockerfile Doctor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from dockerfile_doctor import __version__
from dockerfile_doctor.config import Config, load_config
from dockerfile_doctor.models import AnalysisResult, Severity
from dockerfile_doctor.reporter import report


# ---------------------------------------------------------------------------
# Dockerfile discovery
# ---------------------------------------------------------------------------

_DOCKERFILE_PATTERNS = ("Dockerfile", "Dockerfile.*", "*.dockerfile")


def _find_dockerfiles(paths: Sequence[str]) -> list[str]:
    """Resolve *paths* to a list of Dockerfile paths.

    If a path is a directory, search it (non-recursively) for files matching
    common Dockerfile naming conventions.  If a path is a regular file, use
    it directly.
    """
    found: list[str] = []
    for entry in paths:
        p = Path(entry)
        if p.is_file():
            found.append(str(p))
        elif p.is_dir():
            for pattern in _DOCKERFILE_PATTERNS:
                for match in sorted(p.glob(pattern)):
                    if match.is_file() and str(match) not in found:
                        found.append(str(match))
        else:
            _error(f"Path not found: {entry}")
    return found


def _error(msg: str) -> None:
    """Print an error message to stderr."""
    sys.stderr.write(f"dockerfile-doctor: error: {msg}\n")


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dockerfile-doctor",
        description="Lint, analyze, and auto-fix Dockerfiles for best practices, security, and performance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=None,
        metavar="PATHS",
        help="Dockerfile paths or directories to scan (default: ./Dockerfile)",
    )

    parser.add_argument(
        "-f", "--fix",
        action="store_true",
        default=False,
        help="Auto-fix issues where possible",
    )

    parser.add_argument(
        "--format",
        dest="fmt",
        choices=("text", "json", "sarif"),
        default="text",
        help="Output format (default: text)",
    )

    parser.add_argument(
        "--severity",
        choices=("info", "warning", "error"),
        default=None,
        help="Minimum severity to report (default: info)",
    )

    parser.add_argument(
        "--ignore",
        default=None,
        help="Comma-separated rule IDs to ignore (e.g. DD001,DD012)",
    )

    parser.add_argument(
        "--config",
        default=None,
        metavar="FILE",
        help="Path to .dockerfile-doctor.yaml config file",
    )

    parser.add_argument(
        "-o", "--output",
        default=None,
        metavar="FILE",
        help="Write output to file instead of stdout",
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Only output errors/warnings count",
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable colored output",
    )

    parser.add_argument(
        "--diff",
        nargs="?",
        const="HEAD",
        default=None,
        metavar="REF",
        help="Only report issues on lines changed since REF (default: HEAD)",
    )

    parser.add_argument(
        "--score",
        action="store_true",
        default=False,
        help="Show a Dockerfile quality score (A-F grade)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


# ---------------------------------------------------------------------------
# Severity filtering
# ---------------------------------------------------------------------------

_SEV_RANK = {
    "error": 0,
    "warning": 1,
    "info": 2,
}


def _filter_issues(result: AnalysisResult, *, min_severity: str, ignore: list[str]) -> AnalysisResult:
    """Return a new AnalysisResult with issues filtered by severity and ignore list."""
    min_rank = _SEV_RANK.get(min_severity, 2)
    filtered = [
        issue
        for issue in result.issues
        if _SEV_RANK.get(issue.severity.value, 2) <= min_rank
        and issue.rule_id not in ignore
    ]
    return AnalysisResult(
        filepath=result.filepath,
        issues=filtered,
        fixes=result.fixes,
        stats=result.stats,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Load configuration ---
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        _error(f"Failed to load config: {exc}")
        return 1

    # CLI overrides
    ignore_list: list[str] = list(config.ignore)
    if args.ignore:
        ignore_list.extend(r.strip() for r in args.ignore.split(",") if r.strip())

    min_severity = args.severity or config.severity

    # --- Discover Dockerfiles ---
    paths = args.paths if args.paths else ["./Dockerfile"]
    dockerfiles = _find_dockerfiles(paths)

    if not dockerfiles:
        _error("No Dockerfiles found.")
        return 1

    # --- Lazy imports of analysis modules (allows stub-free import of cli) ---
    try:
        from dockerfile_doctor.parser import parse as parse_dockerfile  # type: ignore[import-not-found]
        from dockerfile_doctor.rules import analyze  # type: ignore[import-not-found]
        from dockerfile_doctor.fixer import fix as apply_fixes  # type: ignore[import-not-found]
    except ImportError as exc:
        _error(
            f"Missing analysis module ({exc}). "
            "Make sure parser, rules, and fixer modules are installed."
        )
        return 1

    # --- Analyze each Dockerfile ---
    results: list[AnalysisResult] = []
    has_errors = False

    for filepath in dockerfiles:
        try:
            with open(filepath, encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            _error(f"Cannot read {filepath}: {exc}")
            continue

        try:
            dockerfile = parse_dockerfile(content)
        except Exception as exc:
            _error(f"Failed to parse {filepath}: {exc}")
            continue

        issues = analyze(dockerfile)

        # Apply severity overrides from config
        for issue in issues:
            rule_cfg = config.rules.get(issue.rule_id)
            if rule_cfg and rule_cfg.severity:
                try:
                    issue.severity = Severity(rule_cfg.severity)
                except ValueError:
                    pass  # ignore invalid overrides

        # Filter by severity and ignored rules BEFORE fixing
        ar = AnalysisResult(filepath=filepath, issues=issues)
        ar = _filter_issues(ar, min_severity=min_severity, ignore=ignore_list)

        # Optionally apply fixes (only on filtered issues)
        if args.fix:
            try:
                excluded = {i.rule_id for i in issues} - {i.rule_id for i in ar.issues}
                fixed_content, fixes = apply_fixes(
                    dockerfile, ar.issues, exclude_rules=excluded or None,
                )
                ar.fixes = fixes
                if fixes:
                    with open(filepath, "w", encoding="utf-8") as fh:
                        fh.write(fixed_content)
            except Exception as exc:
                _error(f"Failed to apply fixes to {filepath}: {exc}")

        # Filter by diff (changed lines only)
        if args.diff is not None:
            from dockerfile_doctor.diff import get_changed_lines, filter_issues_by_diff
            changed = get_changed_lines(filepath, diff_ref=args.diff)
            ar = AnalysisResult(
                filepath=ar.filepath,
                issues=filter_issues_by_diff(ar.issues, changed),
                fixes=ar.fixes,
                stats=ar.stats,
            )

        if ar.error_count > 0:
            has_errors = True

        results.append(ar)

    # --- Report ---
    report(
        results,
        fmt=args.fmt,
        no_color=args.no_color,
        quiet=args.quiet,
        output=args.output,
    )

    # --- Score (after report) ---
    if args.score:
        from dockerfile_doctor.score import compute_scores, format_score_text
        scores = compute_scores(results)
        score_text = format_score_text(scores)
        sys.stdout.write("\n" + score_text + "\n")

    return 1 if has_errors else 0


# Allow `python -m dockerfile_doctor`
if __name__ == "__main__":
    raise SystemExit(main())
