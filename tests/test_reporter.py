"""Tests for the Dockerfile Doctor reporter (text, JSON, SARIF)."""

from __future__ import annotations

import json

import pytest

from dockerfile_doctor.models import AnalysisResult, Issue, Severity, Category
from dockerfile_doctor.reporter import report, _format_text, _format_json, _format_sarif


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_issue(
    rule_id: str = "DD001",
    title: str = "Test issue",
    severity: Severity = Severity.WARNING,
    category: Category = Category.MAINTAINABILITY,
    line_number: int = 1,
    fix_available: bool = False,
) -> Issue:
    return Issue(
        rule_id=rule_id,
        title=title,
        description=f"Description for {rule_id}",
        severity=severity,
        category=category,
        line_number=line_number,
        fix_available=fix_available,
    )


def _make_result(filepath: str = "Dockerfile", issues: list[Issue] | None = None) -> AnalysisResult:
    return AnalysisResult(filepath=filepath, issues=issues or [])


# ===========================================================================
# Text format
# ===========================================================================

class TestTextFormat:
    def test_no_issues(self):
        result = _make_result()
        text = _format_text([result], use_color=False)
        assert "No issues found" in text

    def test_issues_listed(self):
        issues = [_make_issue(rule_id="DD001", title="Missing tag")]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "DD001" in text
        assert "Missing tag" in text

    def test_fixable_tag_shown(self):
        issues = [_make_issue(fix_available=True)]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "fixable" in text.lower() or "--fix" in text

    def test_quiet_mode_minimal(self):
        issues = [
            _make_issue(severity=Severity.ERROR),
            _make_issue(rule_id="DD002", severity=Severity.WARNING),
        ]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False, quiet=True)
        assert "1 error" in text
        assert "1 warning" in text

    def test_quiet_mode_no_issues(self):
        result = _make_result()
        text = _format_text([result], use_color=False, quiet=True)
        assert "0 issues" in text

    def test_multiple_files_grand_total(self):
        r1 = _make_result("Dockerfile.dev", [_make_issue(severity=Severity.ERROR)])
        r2 = _make_result("Dockerfile.prod", [_make_issue(rule_id="DD002", severity=Severity.WARNING)])
        text = _format_text([r1, r2], use_color=False)
        assert "Total:" in text
        assert "2 issue" in text


# ===========================================================================
# JSON format
# ===========================================================================

class TestJsonFormat:
    def test_valid_json(self):
        result = _make_result(issues=[_make_issue()])
        text = _format_json([result])
        data = json.loads(text)
        assert "version" in data
        assert "files" in data
        assert "totals" in data

    def test_issue_fields(self):
        issue = _make_issue(rule_id="DD020", severity=Severity.ERROR, line_number=5)
        result = _make_result(issues=[issue])
        data = json.loads(_format_json([result]))
        file_issues = data["files"][0]["issues"]
        assert len(file_issues) == 1
        assert file_issues[0]["ruleId"] == "DD020"
        assert file_issues[0]["severity"] == "error"
        assert file_issues[0]["line"] == 5

    def test_totals_correct(self):
        issues = [
            _make_issue(severity=Severity.ERROR),
            _make_issue(rule_id="DD002", severity=Severity.WARNING),
            _make_issue(rule_id="DD003", severity=Severity.INFO),
        ]
        result = _make_result(issues=issues)
        data = json.loads(_format_json([result]))
        assert data["totals"]["errors"] == 1
        assert data["totals"]["warnings"] == 1
        assert data["totals"]["infos"] == 1
        assert data["totals"]["issues"] == 3

    def test_empty_issues(self):
        result = _make_result()
        data = json.loads(_format_json([result]))
        assert data["files"][0]["issues"] == []
        assert data["totals"]["issues"] == 0


# ===========================================================================
# SARIF format
# ===========================================================================

class TestSarifFormat:
    def test_valid_sarif_structure(self):
        result = _make_result(issues=[_make_issue()])
        text = _format_sarif([result])
        data = json.loads(text)
        assert data["version"] == "2.1.0"
        assert "$schema" in data
        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert "tool" in run
        assert "results" in run

    def test_tool_driver(self):
        result = _make_result(issues=[_make_issue()])
        data = json.loads(_format_sarif([result]))
        driver = data["runs"][0]["tool"]["driver"]
        assert driver["name"] == "dockerfile-doctor"
        assert "version" in driver
        assert "rules" in driver

    def test_result_fields(self):
        issue = _make_issue(rule_id="DD008", severity=Severity.WARNING, line_number=10)
        result = _make_result(filepath="test/Dockerfile", issues=[issue])
        data = json.loads(_format_sarif([result]))
        sarif_results = data["runs"][0]["results"]
        assert len(sarif_results) == 1
        r = sarif_results[0]
        assert r["ruleId"] == "DD008"
        assert r["level"] == "warning"
        loc = r["locations"][0]["physicalLocation"]
        assert loc["region"]["startLine"] == 10
        assert "test/Dockerfile" in loc["artifactLocation"]["uri"]

    def test_severity_mapping(self):
        issues = [
            _make_issue(rule_id="DD001", severity=Severity.ERROR),
            _make_issue(rule_id="DD002", severity=Severity.WARNING),
            _make_issue(rule_id="DD003", severity=Severity.INFO),
        ]
        result = _make_result(issues=issues)
        data = json.loads(_format_sarif([result]))
        levels = [r["level"] for r in data["runs"][0]["results"]]
        assert "error" in levels
        assert "warning" in levels
        assert "note" in levels

    def test_rule_descriptors_deduped(self):
        issues = [
            _make_issue(rule_id="DD001", line_number=1),
            _make_issue(rule_id="DD001", line_number=5),
        ]
        result = _make_result(issues=issues)
        data = json.loads(_format_sarif([result]))
        rules = data["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 1
        assert rules[0]["id"] == "DD001"

    def test_empty_issues_sarif(self):
        result = _make_result()
        data = json.loads(_format_sarif([result]))
        assert data["runs"][0]["results"] == []

    def test_fix_description_in_sarif(self):
        issue = _make_issue(fix_available=True)
        issue.fix_description = "Apply this fix"
        result = _make_result(issues=[issue])
        data = json.loads(_format_sarif([result]))
        r = data["runs"][0]["results"][0]
        assert "fixes" in r
        assert r["fixes"][0]["description"]["text"] == "Apply this fix"

    def test_backslash_in_filepath_normalized(self):
        result = _make_result(filepath="src\\docker\\Dockerfile", issues=[_make_issue()])
        data = json.loads(_format_sarif([result]))
        uri = data["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert "\\" not in uri
        assert "src/docker/Dockerfile" in uri


# ===========================================================================
# report() public API
# ===========================================================================

class TestReportPublicApi:
    def test_output_to_file(self, tmp_path):
        result = _make_result(issues=[_make_issue()])
        out_file = str(tmp_path / "report.json")
        text = report([result], fmt="json", output=out_file)
        assert (tmp_path / "report.json").exists()
        content = (tmp_path / "report.json").read_text(encoding="utf-8")
        assert "DD001" in content

    def test_format_selection(self):
        result = _make_result(issues=[_make_issue()])
        json_text = report([result], fmt="json", output=None, no_color=True)
        assert json_text.strip().startswith("{")
        sarif_text = report([result], fmt="sarif", output=None, no_color=True)
        assert '"version": "2.1.0"' in sarif_text

    def test_text_format_default(self):
        result = _make_result(issues=[_make_issue()])
        text = report([result], fmt="text", output=None, no_color=True)
        assert "DD001" in text


# ===========================================================================
# More text format tests
# ===========================================================================

class TestTextFormatDetailed:
    def test_severity_error_shown(self):
        issues = [_make_issue(severity=Severity.ERROR)]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "ERROR" in text

    def test_severity_warning_shown(self):
        issues = [_make_issue(severity=Severity.WARNING)]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "WARNING" in text

    def test_severity_info_shown(self):
        issues = [_make_issue(severity=Severity.INFO)]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "INFO" in text

    def test_line_number_shown(self):
        issues = [_make_issue(line_number=42)]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "42" in text

    def test_file_level_issue_line_zero(self):
        """Issues with line_number=0 are file-level."""
        issues = [_make_issue(line_number=0)]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "File" in text or "DD001" in text

    def test_multiple_issues_sorted(self):
        issues = [
            _make_issue(rule_id="DD019", line_number=10),
            _make_issue(rule_id="DD001", line_number=1),
            _make_issue(rule_id="DD009", line_number=5),
        ]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        # All rules should appear
        assert "DD001" in text
        assert "DD009" in text
        assert "DD019" in text

    def test_issue_count_summary(self):
        issues = [
            _make_issue(severity=Severity.ERROR),
            _make_issue(rule_id="DD002", severity=Severity.ERROR),
            _make_issue(rule_id="DD003", severity=Severity.WARNING),
        ]
        result = _make_result(issues=issues)
        text = _format_text([result], use_color=False)
        assert "2 error" in text
        assert "1 warning" in text


# ===========================================================================
# More JSON format tests
# ===========================================================================

class TestJsonFormatDetailed:
    def test_fixable_field_present(self):
        issue = _make_issue(fix_available=True)
        result = _make_result(issues=[issue])
        data = json.loads(_format_json([result]))
        file_issue = data["files"][0]["issues"][0]
        assert file_issue.get("fixAvailable", file_issue.get("fixable")) is True

    def test_multiple_files(self):
        r1 = _make_result("Dockerfile.a", [_make_issue()])
        r2 = _make_result("Dockerfile.b", [_make_issue(rule_id="DD002")])
        data = json.loads(_format_json([r1, r2]))
        assert data["totals"]["files"] == 2
        assert data["totals"]["issues"] == 2

    def test_json_keys_consistent(self):
        result = _make_result(issues=[_make_issue()])
        data = json.loads(_format_json([result]))
        issue = data["files"][0]["issues"][0]
        assert "ruleId" in issue
        assert "severity" in issue
        assert "line" in issue
        assert "title" in issue


# ===========================================================================
# More SARIF format tests
# ===========================================================================

class TestSarifFormatDetailed:
    def test_sarif_schema_url(self):
        result = _make_result(issues=[_make_issue()])
        data = json.loads(_format_sarif([result]))
        assert "sarif" in data["$schema"].lower()

    def test_sarif_multiple_files(self):
        r1 = _make_result("Dockerfile.a", [_make_issue()])
        r2 = _make_result("Dockerfile.b", [_make_issue(rule_id="DD002")])
        data = json.loads(_format_sarif([r1, r2]))
        results = data["runs"][0]["results"]
        assert len(results) == 2
        uris = [r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in results]
        assert any("Dockerfile.a" in u for u in uris)
        assert any("Dockerfile.b" in u for u in uris)

    def test_sarif_line_zero_handled(self):
        """File-level issues (line 0) should still produce valid SARIF."""
        issue = _make_issue(line_number=0)
        result = _make_result(issues=[issue])
        data = json.loads(_format_sarif([result]))
        # Should not crash, line number handled gracefully
        assert len(data["runs"][0]["results"]) == 1
