"""Output reporters for Dockerfile Doctor.

Supports three formats:
- text  : colored terminal output (default)
- json  : machine-readable JSON
- sarif : SARIF 2.1.0 for GitHub Code Scanning integration
"""

from __future__ import annotations

import json
import os
import sys
from typing import IO, Optional, Sequence

from dockerfile_doctor import __version__
from dockerfile_doctor.models import AnalysisResult, Issue, Severity


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

class _Colors:
    """ANSI escape codes for terminal colouring."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


_NO_COLORS = type("_NoColors", (), {
    attr: "" for attr in dir(_Colors) if not attr.startswith("_")
})()


def _get_colors(use_color: bool) -> _Colors:
    if use_color:
        return _Colors()
    return _NO_COLORS  # type: ignore[return-value]


def _should_use_color(no_color_flag: bool) -> bool:
    """Decide whether to emit ANSI colours."""
    if no_color_flag:
        return False
    # Respect NO_COLOR convention (https://no-color.org/)
    if os.environ.get("NO_COLOR") is not None:
        return False
    # Respect TERM=dumb
    if os.environ.get("TERM") == "dumb":
        return False
    # Only colour when writing to a real terminal
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


def _severity_color(severity: Severity, c: _Colors) -> str:
    return {
        Severity.ERROR: c.RED,
        Severity.WARNING: c.YELLOW,
        Severity.INFO: c.BLUE,
    }.get(severity, c.WHITE)


def _severity_label(severity: Severity) -> str:
    return severity.value.upper()


# ---------------------------------------------------------------------------
# Text reporter
# ---------------------------------------------------------------------------

def _format_text(
    results: Sequence[AnalysisResult],
    *,
    use_color: bool = True,
    quiet: bool = False,
) -> str:
    """Render results as coloured text for terminal output."""
    c = _get_colors(use_color)
    lines: list[str] = []

    total_errors = 0
    total_warnings = 0
    total_infos = 0
    total_fixable = 0

    for result in results:
        if not quiet:
            lines.append(f"{c.BOLD}{c.CYAN}Dockerfile: {result.filepath}{c.RESET}")

        errors = result.error_count
        warnings = result.warning_count
        infos = result.info_count
        fixable = sum(1 for i in result.issues if i.fix_available)

        total_errors += errors
        total_warnings += warnings
        total_infos += infos
        total_fixable += fixable

        if not result.issues:
            if not quiet:
                lines.append(f"  {c.GREEN}No issues found.{c.RESET}")
                lines.append("")
            continue

        if not quiet:
            # Sort issues by line number
            sorted_issues = sorted(result.issues, key=lambda i: i.line_number)
            for issue in sorted_issues:
                sc = _severity_color(issue.severity, c)
                label = _severity_label(issue.severity)
                fix_tag = f"  {c.GREEN}(fixable){c.RESET}" if issue.fix_available else ""
                line_str = f"Line {issue.line_number}" if issue.line_number > 0 else "File"
                lines.append(
                    f"  {line_str:<8} {sc}[{label}]{c.RESET}  "
                    f"{c.DIM}{issue.rule_id}{c.RESET}  "
                    f"{issue.title}{fix_tag}"
                )

            lines.append("")

            # Summary for this file
            parts: list[str] = []
            if errors:
                parts.append(f"{c.RED}{errors} error{'s' if errors != 1 else ''}{c.RESET}")
            if warnings:
                parts.append(f"{c.YELLOW}{warnings} warning{'s' if warnings != 1 else ''}{c.RESET}")
            if infos:
                parts.append(f"{c.BLUE}{infos} info{c.RESET}")
            total_in_file = errors + warnings + infos
            lines.append(
                f"  Found {total_in_file} issue{'s' if total_in_file != 1 else ''} "
                f"({', '.join(parts)})"
            )
            if result.fixes:
                nfixed = len(result.fixes)
                lines.append(
                    f"  {c.GREEN}{nfixed} fix{'es' if nfixed != 1 else ''} applied{c.RESET}"
                )
            elif fixable:
                lines.append(
                    f"  {c.GREEN}{fixable} auto-fixable issue{'s' if fixable != 1 else ''}{c.RESET}"
                    f" (use {c.BOLD}--fix{c.RESET} to apply)"
                )
            lines.append("")

    # Grand total when multiple files
    if len(results) > 1 and not quiet:
        grand_total = total_errors + total_warnings + total_infos
        lines.append(f"{c.BOLD}Total: {grand_total} issue{'s' if grand_total != 1 else ''} "
                      f"across {len(results)} file{'s' if len(results) != 1 else ''}{c.RESET}")

    if quiet:
        parts_q: list[str] = []
        if total_errors:
            parts_q.append(f"{total_errors} error{'s' if total_errors != 1 else ''}")
        if total_warnings:
            parts_q.append(f"{total_warnings} warning{'s' if total_warnings != 1 else ''}")
        if parts_q:
            lines.append(", ".join(parts_q))
        else:
            lines.append("0 issues")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON reporter
# ---------------------------------------------------------------------------

def _issue_to_dict(issue: Issue) -> dict:
    d = {
        "ruleId": issue.rule_id,
        "title": issue.title,
        "description": issue.description,
        "severity": issue.severity.value,
        "category": issue.category.value,
        "line": issue.line_number,
        "fixAvailable": issue.fix_available,
    }
    if issue.fix_description:
        d["fixDescription"] = issue.fix_description
    return d


def _format_json(results: Sequence[AnalysisResult]) -> str:
    """Render results as JSON."""
    total_errors = sum(r.error_count for r in results)
    total_warnings = sum(r.warning_count for r in results)
    total_infos = sum(r.info_count for r in results)

    payload = {
        "version": __version__,
        "files": [
            {
                "filepath": r.filepath,
                "issues": [_issue_to_dict(i) for i in r.issues],
                "stats": {
                    "errors": r.error_count,
                    "warnings": r.warning_count,
                    "infos": r.info_count,
                    "fixable": sum(1 for i in r.issues if i.fix_available),
                },
            }
            for r in results
        ],
        "totals": {
            "files": len(results),
            "errors": total_errors,
            "warnings": total_warnings,
            "infos": total_infos,
            "issues": total_errors + total_warnings + total_infos,
        },
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# SARIF 2.1.0 reporter
# ---------------------------------------------------------------------------

_SARIF_SEVERITY_MAP = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
}


def _format_sarif(results: Sequence[AnalysisResult]) -> str:
    """Render results as SARIF 2.1.0 JSON."""
    # Collect unique rules across all results
    rules_seen: dict[str, Issue] = {}
    sarif_results: list[dict] = []

    for result in results:
        for issue in result.issues:
            if issue.rule_id not in rules_seen:
                rules_seen[issue.rule_id] = issue

            sarif_result: dict = {
                "ruleId": issue.rule_id,
                "level": _SARIF_SEVERITY_MAP.get(issue.severity, "note"),
                "message": {
                    "text": issue.title,
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": result.filepath.replace("\\", "/"),
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {
                                "startLine": max(issue.line_number, 1),
                            },
                        },
                    }
                ],
            }
            if issue.fix_available and issue.fix_description:
                sarif_result["fixes"] = [
                    {
                        "description": {
                            "text": issue.fix_description,
                        },
                        "artifactChanges": [],
                    }
                ]
            sarif_results.append(sarif_result)

    # Build rule descriptors
    rule_descriptors = []
    for rule_id, sample_issue in rules_seen.items():
        rule_descriptors.append({
            "id": rule_id,
            "name": rule_id,
            "shortDescription": {
                "text": sample_issue.title,
            },
            "fullDescription": {
                "text": sample_issue.description,
            },
            "defaultConfiguration": {
                "level": _SARIF_SEVERITY_MAP.get(sample_issue.severity, "note"),
            },
            "properties": {
                "category": sample_issue.category.value,
            },
        })

    sarif_doc = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "dockerfile-doctor",
                        "version": __version__,
                        "informationUri": "https://github.com/crabsatellite/dockerfile-doctor",
                        "rules": rule_descriptors,
                    }
                },
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(sarif_doc, indent=2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def report(
    results: Sequence[AnalysisResult],
    *,
    fmt: str = "text",
    no_color: bool = False,
    quiet: bool = False,
    output: Optional[str] = None,
) -> str:
    """Format *results* and optionally write to *output* file.

    Returns the formatted string.
    """
    use_color = _should_use_color(no_color)

    if fmt == "json":
        text = _format_json(results)
    elif fmt == "sarif":
        text = _format_sarif(results)
    else:
        text = _format_text(results, use_color=use_color, quiet=quiet)

    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write("\n")
    else:
        dest: IO[str] = sys.stdout
        dest.write(text)
        dest.write("\n")

    return text
