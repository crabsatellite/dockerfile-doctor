"""Tests for the Dockerfile Doctor CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dockerfile_doctor.cli import main


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_cli(args: list[str], capsys=None) -> int:
    """Run the CLI main() with given args and return the exit code.

    If capsys is provided, stdout/stderr can be captured by the caller.
    """
    try:
        exit_code = main(args)
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0
    return exit_code


# ===========================================================================
# Default run on a single Dockerfile
# ===========================================================================

class TestDefaultRun:
    def test_clean_file_exit_zero(self, tmp_dockerfile, capsys):
        content = (
            "FROM alpine:3.19\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            "USER nobody\n"
            "HEALTHCHECK CMD wget -q http://localhost/\n"
            'CMD ["echo", "hello"]\n'
        )
        path = tmp_dockerfile(content)
        exit_code = _run_cli([str(path)], capsys)
        assert exit_code == 0

    def test_bad_file_exit_nonzero(self, tmp_dockerfile, capsys):
        # DD020 (secrets in ENV) is ERROR severity, so exit code should be 1
        content = "FROM ubuntu:22.04\nENV password=secret123\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        exit_code = _run_cli([str(path)], capsys)
        assert exit_code == 1


# ===========================================================================
# --fix mode
# ===========================================================================

class TestFixMode:
    def test_fix_writes_corrected_file(self, tmp_dockerfile):
        content = "FROM alpine:3.19\nMAINTAINER user@example.com\nCMD python app.py\n"
        path = tmp_dockerfile(content)
        exit_code = _run_cli(["--fix", str(path)])
        fixed_content = path.read_text(encoding="utf-8")
        assert "MAINTAINER" not in fixed_content

    def test_fix_on_clean_file_no_change(self, tmp_dockerfile):
        content = (
            "FROM alpine:3.19\n"
            'LABEL maintainer="me" description="test" version="1.0.0"\n'
            "WORKDIR /app\n"
            "COPY . /app\n"
            "USER nobody\n"
            "HEALTHCHECK CMD wget -q http://localhost/\n"
            'CMD ["echo", "hello"]\n'
        )
        path = tmp_dockerfile(content)
        _run_cli(["--fix", str(path)])
        assert path.read_text(encoding="utf-8") == content


# ===========================================================================
# --format json
# ===========================================================================

class TestJsonFormat:
    def test_json_output_is_valid(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        _run_cli(["--format", "json", str(path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict) or isinstance(data, list)


# ===========================================================================
# --severity filtering
# ===========================================================================

class TestSeverityFilter:
    def test_filter_error_only(self, tmp_dockerfile, capsys):
        content = (
            "FROM ubuntu:22.04\n"
            "ENV password=secret123\n"
            "CMD [\"bash\"]\n"
        )
        path = tmp_dockerfile(content)
        _run_cli(["--severity", "error", "--format", "json", str(path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        # With error filter, DD020 (secrets, ERROR) should appear
        # but DD001 (WARNING) should not
        if isinstance(data, dict) and "files" in data:
            issues = data["files"][0]["issues"]
        elif isinstance(data, dict):
            issues = data.get("issues", [])
        else:
            issues = data
        rule_ids = {i.get("ruleId", i.get("rule_id", "")) for i in issues}
        assert "DD020" in rule_ids
        # DD001 is WARNING and should be filtered out
        assert "DD001" not in rule_ids


# ===========================================================================
# --ignore rule filtering
# ===========================================================================

class TestIgnoreFilter:
    def test_ignore_single_rule(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        _run_cli(["--ignore", "DD020", "--format", "json", str(path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        if isinstance(data, dict) and "files" in data:
            issues = data["files"][0]["issues"]
        elif isinstance(data, dict):
            issues = data.get("issues", [])
        else:
            issues = data
        rule_ids = {i.get("ruleId", i.get("rule_id", "")) for i in issues}
        assert "DD020" not in rule_ids


# ===========================================================================
# Exit codes
# ===========================================================================

class TestExitCodes:
    def test_exit_0_clean(self, tmp_dockerfile):
        content = (
            "FROM alpine:3.19\n"
            "WORKDIR /app\n"
            "USER nobody\n"
            "HEALTHCHECK CMD wget -q http://localhost/\n"
            'CMD ["echo", "hello"]\n'
        )
        path = tmp_dockerfile(content)
        exit_code = _run_cli([str(path)])
        assert exit_code == 0

    def test_exit_1_with_error_issues(self, tmp_dockerfile):
        # DD020 secrets is ERROR severity
        content = "FROM ubuntu:22.04\nENV password=secret123\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        exit_code = _run_cli([str(path)])
        assert exit_code == 1

    def test_exit_code_nonexistent_file(self):
        exit_code = _run_cli(["/nonexistent/Dockerfile"])
        assert exit_code != 0


# ===========================================================================
# Directory scanning
# ===========================================================================

class TestDirectoryScanning:
    def test_scan_directory(self, tmp_path, capsys):
        (tmp_path / "Dockerfile").write_text(
            "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n", encoding="utf-8"
        )
        exit_code = _run_cli([str(tmp_path)])
        # Should scan and find issues
        assert exit_code == 1


# ===========================================================================
# --quiet mode
# ===========================================================================

class TestQuietMode:
    def test_quiet_suppresses_output(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        exit_code = _run_cli(["--quiet", str(path)])
        captured = capsys.readouterr()
        # Exit code should still reflect issues
        assert exit_code == 1
        # stdout should be minimal
        assert len(captured.out.strip()) < 100


# ===========================================================================
# --output file
# ===========================================================================

class TestOutputFile:
    def test_output_to_file(self, tmp_dockerfile, tmp_path):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        out_file = tmp_path / "report.txt"
        _run_cli(["--format", "json", "-o", str(out_file), str(path)])
        assert out_file.exists()
        text = out_file.read_text(encoding="utf-8")
        data = json.loads(text)
        assert "files" in data

    def test_sarif_output_to_file(self, tmp_dockerfile, tmp_path):
        content = "FROM ubuntu:22.04\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        out_file = tmp_path / "report.sarif"
        _run_cli(["--format", "sarif", "-o", str(out_file), str(path)])
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["version"] == "2.1.0"


# ===========================================================================
# --no-color
# ===========================================================================

class TestNoColor:
    def test_no_color_flag(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        _run_cli(["--no-color", str(path)])
        captured = capsys.readouterr()
        # ANSI escape codes should NOT be present
        assert "\033[" not in captured.out


# ===========================================================================
# --format sarif via CLI
# ===========================================================================

class TestSarifCli:
    def test_sarif_output_valid(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD [\"bash\"]\n"
        path = tmp_dockerfile(content)
        _run_cli(["--format", "sarif", str(path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert len(data["runs"]) == 1


# ===========================================================================
# Multiple files
# ===========================================================================

class TestMultipleFiles:
    def test_scan_multiple_files(self, tmp_path, capsys):
        (tmp_path / "Dockerfile.dev").write_text(
            "FROM ubuntu:22.04\nCMD [\"bash\"]\n", encoding="utf-8"
        )
        (tmp_path / "Dockerfile.prod").write_text(
            "FROM alpine:3.19\nUSER nobody\nHEALTHCHECK CMD wget -q http://localhost/\nCMD [\"sh\"]\n",
            encoding="utf-8",
        )
        exit_code = _run_cli(["--format", "json", str(tmp_path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["totals"]["files"] >= 2


# ===========================================================================
# --version
# ===========================================================================

class TestVersion:
    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


# ===========================================================================
# Edge cases
# ===========================================================================

class TestCLIEdgeCases:
    def test_fix_with_json_format(self, tmp_dockerfile, capsys):
        """--fix + --format json should fix and report."""
        content = "FROM alpine:3.19\nMAINTAINER dev@example.com\n"
        path = tmp_dockerfile(content)
        _run_cli(["--fix", "--format", "json", str(path)])
        fixed = path.read_text(encoding="utf-8")
        assert "MAINTAINER" not in fixed

    def test_ignore_multiple_rules(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu\nENV password=secret\nCMD bash\n"
        path = tmp_dockerfile(content)
        _run_cli(["--ignore", "DD001,DD020,DD019", "--format", "json", str(path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        if isinstance(data, dict) and "files" in data:
            issues = data["files"][0]["issues"]
        else:
            issues = data.get("issues", []) if isinstance(data, dict) else data
        rule_ids = {i.get("ruleId", i.get("rule_id", "")) for i in issues}
        assert "DD001" not in rule_ids
        assert "DD020" not in rule_ids
        assert "DD019" not in rule_ids

    def test_severity_warning_includes_errors(self, tmp_dockerfile, capsys):
        content = "FROM ubuntu:22.04\nENV password=secret\nCMD bash\n"
        path = tmp_dockerfile(content)
        _run_cli(["--severity", "warning", "--format", "json", str(path)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        if isinstance(data, dict) and "files" in data:
            issues = data["files"][0]["issues"]
        else:
            issues = data.get("issues", []) if isinstance(data, dict) else data
        rule_ids = {i.get("ruleId", i.get("rule_id", "")) for i in issues}
        # ERROR severity DD020 should still be included
        assert "DD020" in rule_ids

    def test_empty_dockerfile_no_crash(self, tmp_dockerfile, capsys):
        path = tmp_dockerfile("")
        exit_code = _run_cli([str(path)])
        assert exit_code == 0

    def test_fix_idempotent_via_cli(self, tmp_dockerfile):
        """Running --fix twice should produce same result."""
        content = (
            "FROM ubuntu:22.04\n"
            "MAINTAINER dev@example.com\n"
            "ADD . /app\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "CMD python app.py\n"
        )
        path = tmp_dockerfile(content)
        _run_cli(["--fix", str(path)])
        fixed1 = path.read_text(encoding="utf-8")
        _run_cli(["--fix", str(path)])
        fixed2 = path.read_text(encoding="utf-8")
        assert fixed1 == fixed2
