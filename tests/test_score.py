"""Tests for the Dockerfile Doctor scoring system."""

from __future__ import annotations

import json

import pytest

from dockerfile_doctor.models import AnalysisResult, Issue, Severity, Category
from dockerfile_doctor.score import (
    Score,
    compute_scores,
    format_score_text,
    format_score_json,
    _points_to_grade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_issue(severity: Severity = Severity.WARNING) -> Issue:
    return Issue(
        rule_id="DD001",
        title="Test",
        description="Test",
        severity=severity,
        category=Category.BEST_PRACTICE,
        line_number=1,
    )


def _make_result(errors: int = 0, warnings: int = 0, infos: int = 0) -> AnalysisResult:
    issues = (
        [_make_issue(Severity.ERROR)] * errors
        + [_make_issue(Severity.WARNING)] * warnings
        + [_make_issue(Severity.INFO)] * infos
    )
    return AnalysisResult(filepath="Dockerfile", issues=issues)


# ===========================================================================
# Grade calculation
# ===========================================================================

class TestPointsToGrade:
    def test_grade_a(self):
        assert _points_to_grade(100) == "A"
        assert _points_to_grade(95) == "A"
        assert _points_to_grade(90) == "A"

    def test_grade_b(self):
        assert _points_to_grade(89) == "B"
        assert _points_to_grade(80) == "B"

    def test_grade_c(self):
        assert _points_to_grade(79) == "C"
        assert _points_to_grade(70) == "C"

    def test_grade_d(self):
        assert _points_to_grade(69) == "D"
        assert _points_to_grade(60) == "D"

    def test_grade_f(self):
        assert _points_to_grade(59) == "F"
        assert _points_to_grade(0) == "F"


# ===========================================================================
# Score computation
# ===========================================================================

class TestComputeScores:
    def test_perfect_score(self):
        result = _make_result()
        scores = compute_scores([result])
        assert len(scores) == 1
        assert scores[0].points == 100
        assert scores[0].grade == "A"

    def test_one_error(self):
        result = _make_result(errors=1)
        scores = compute_scores([result])
        assert scores[0].points == 85
        assert scores[0].grade == "B"

    def test_one_warning(self):
        result = _make_result(warnings=1)
        scores = compute_scores([result])
        assert scores[0].points == 95
        assert scores[0].grade == "A"

    def test_one_info(self):
        result = _make_result(infos=1)
        scores = compute_scores([result])
        assert scores[0].points == 99
        assert scores[0].grade == "A"

    def test_many_errors_floor_at_zero(self):
        result = _make_result(errors=10)
        scores = compute_scores([result])
        assert scores[0].points == 0
        assert scores[0].grade == "F"

    def test_mixed_issues(self):
        result = _make_result(errors=2, warnings=3, infos=5)
        scores = compute_scores([result])
        # 100 - 30 - 15 - 5 = 50
        assert scores[0].points == 50
        assert scores[0].grade == "F"

    def test_deductions_listed(self):
        result = _make_result(errors=1, warnings=2)
        scores = compute_scores([result])
        assert len(scores[0].deductions) == 2

    def test_multiple_files(self):
        r1 = _make_result(errors=0)
        r2 = _make_result(errors=2)
        scores = compute_scores([r1, r2])
        assert len(scores) == 2
        assert scores[0].grade == "A"
        assert scores[1].grade == "C"


# ===========================================================================
# Text formatting
# ===========================================================================

class TestFormatScoreText:
    def test_contains_grade(self):
        result = _make_result()
        scores = compute_scores([result])
        text = format_score_text(scores)
        assert "Grade: A" in text
        assert "100/100" in text

    def test_contains_filepath(self):
        result = _make_result()
        scores = compute_scores([result])
        text = format_score_text(scores)
        assert "Dockerfile" in text

    def test_multiple_files_overall(self):
        r1 = _make_result()
        r2 = _make_result(warnings=2)
        scores = compute_scores([r1, r2])
        text = format_score_text(scores)
        assert "Overall:" in text
        assert "2 files" in text


# ===========================================================================
# JSON formatting
# ===========================================================================

class TestFormatScoreJson:
    def test_structure(self):
        result = _make_result(errors=1)
        scores = compute_scores([result])
        data = format_score_json(scores)
        assert "scores" in data
        assert "average" in data
        assert len(data["scores"]) == 1

    def test_score_fields(self):
        result = _make_result(errors=1, warnings=2)
        scores = compute_scores([result])
        data = format_score_json(scores)
        s = data["scores"][0]
        assert s["grade"] in ("A", "B", "C", "D", "F")
        assert s["points"] >= 0
        assert s["errors"] == 1
        assert s["warnings"] == 2
        assert s["filepath"] == "Dockerfile"

    def test_average_calculation(self):
        r1 = _make_result()
        r2 = _make_result(errors=2)
        scores = compute_scores([r1, r2])
        data = format_score_json(scores)
        avg = data["average"]["points"]
        assert avg == (100 + 70) / 2

    def test_empty_scores(self):
        data = format_score_json([])
        assert data["scores"] == []
        assert data["average"] is None


# ===========================================================================
# CLI integration
# ===========================================================================

class TestScoreCLI:
    def test_score_with_clean_file(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        content = (
            "FROM alpine:3.19\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            "USER nobody\n"
            "HEALTHCHECK CMD wget -q http://localhost/\n"
            'CMD ["echo", "hello"]\n'
        )
        path = tmp_dockerfile(content)
        try:
            exit_code = main(["--score", str(path)])
        except SystemExit as e:
            exit_code = e.code or 0
        captured = capsys.readouterr()
        assert "Grade:" in captured.out

    def test_score_with_issues(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        content = "FROM ubuntu:22.04\nENV password=secret123\nCMD bash\n"
        path = tmp_dockerfile(content)
        try:
            main(["--score", str(path)])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "Grade:" in captured.out
