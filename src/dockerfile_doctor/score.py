"""Dockerfile Score — A/B/C/D/F grading for Dockerfile quality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import AnalysisResult, Severity


@dataclass
class Score:
    """Quality score for a single Dockerfile."""
    filepath: str
    points: int          # 0-100
    grade: str           # A, B, C, D, F
    errors: int
    warnings: int
    infos: int
    total_issues: int
    deductions: list[str]  # human-readable deduction reasons


def compute_scores(results: list[AnalysisResult]) -> list[Score]:
    """Compute quality scores for each analyzed Dockerfile."""
    return [_score_one(r) for r in results]


def _score_one(result: AnalysisResult) -> Score:
    """Score a single Dockerfile analysis result.

    Scoring method:
    - Start at 100 points
    - Each ERROR: -15 points
    - Each WARNING: -5 points
    - Each INFO: -1 point
    - Floor at 0
    """
    points = 100
    deductions: list[str] = []

    errors = result.error_count
    warnings = result.warning_count
    infos = result.info_count
    total = errors + warnings + infos

    if errors > 0:
        penalty = errors * 15
        points -= penalty
        deductions.append(f"-{penalty} ({errors} error{'s' if errors > 1 else ''})")

    if warnings > 0:
        penalty = warnings * 5
        points -= penalty
        deductions.append(f"-{penalty} ({warnings} warning{'s' if warnings > 1 else ''})")

    if infos > 0:
        penalty = infos * 1
        points -= penalty
        deductions.append(f"-{penalty} ({infos} info{'s' if infos > 1 else ''})")

    points = max(0, points)
    grade = _points_to_grade(points)

    return Score(
        filepath=result.filepath,
        points=points,
        grade=grade,
        errors=errors,
        warnings=warnings,
        infos=infos,
        total_issues=total,
        deductions=deductions,
    )


def _points_to_grade(points: int) -> str:
    """Convert numeric score to letter grade."""
    if points >= 90:
        return "A"
    elif points >= 80:
        return "B"
    elif points >= 70:
        return "C"
    elif points >= 60:
        return "D"
    else:
        return "F"


def format_score_text(scores: list[Score], use_color: bool = False) -> str:
    """Format scores as human-readable text."""
    lines: list[str] = []

    for s in scores:
        lines.append(f"{'='*60}")
        lines.append(f"Dockerfile Score: {s.filepath}")
        lines.append(f"{'='*60}")
        lines.append(f"  Grade: {s.grade}  ({s.points}/100)")
        lines.append(f"  Issues: {s.total_issues} "
                      f"({s.errors} errors, {s.warnings} warnings, {s.infos} infos)")
        if s.deductions:
            lines.append(f"  Deductions:")
            for d in s.deductions:
                lines.append(f"    {d}")
        lines.append("")

    if len(scores) > 1:
        avg = sum(s.points for s in scores) / len(scores)
        avg_grade = _points_to_grade(int(avg))
        lines.append(f"Overall: {avg_grade} ({avg:.0f}/100 average across {len(scores)} files)")

    return "\n".join(lines)


def format_score_json(scores: list[Score]) -> dict:
    """Format scores as a JSON-serializable dict."""
    return {
        "scores": [
            {
                "filepath": s.filepath,
                "grade": s.grade,
                "points": s.points,
                "errors": s.errors,
                "warnings": s.warnings,
                "infos": s.infos,
                "totalIssues": s.total_issues,
                "deductions": s.deductions,
            }
            for s in scores
        ],
        "average": {
            "points": sum(s.points for s in scores) / max(len(scores), 1),
            "grade": _points_to_grade(
                int(sum(s.points for s in scores) / max(len(scores), 1))
            ),
        } if scores else None,
    }
