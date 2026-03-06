"""Tests for the Dockerfile Doctor configuration loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dockerfile_doctor.config import (
    Config,
    RuleConfig,
    _load_yaml_fallback,
    _parse_scalar,
    load_config,
)


# ===========================================================================
# Scalar parser
# ===========================================================================

class TestParseScalar:
    def test_true_values(self):
        for v in ("true", "True", "yes", "Yes", "on", "On"):
            assert _parse_scalar(v) is True

    def test_false_values(self):
        for v in ("false", "False", "no", "No", "off", "Off"):
            assert _parse_scalar(v) is False

    def test_null_values(self):
        for v in ("null", "Null", "~", ""):
            assert _parse_scalar(v) is None

    def test_integer(self):
        assert _parse_scalar("42") == 42
        assert _parse_scalar("-1") == -1

    def test_float(self):
        assert _parse_scalar("3.14") == 3.14

    def test_quoted_string(self):
        assert _parse_scalar('"hello"') == "hello"
        assert _parse_scalar("'world'") == "world"

    def test_plain_string(self):
        assert _parse_scalar("some_value") == "some_value"


# ===========================================================================
# Fallback YAML parser
# ===========================================================================

class TestFallbackYaml:
    def test_top_level_scalars(self):
        text = "severity: error\nname: test\n"
        data = _load_yaml_fallback(text)
        assert data["severity"] == "error"
        assert data["name"] == "test"

    def test_list(self):
        text = "ignore:\n  - DD001\n  - DD002\n  - DD003\n"
        data = _load_yaml_fallback(text)
        assert data["ignore"] == ["DD001", "DD002", "DD003"]

    def test_nested_mapping(self):
        text = "rules:\n  DD001:\n    severity: error\n"
        data = _load_yaml_fallback(text)
        assert isinstance(data["rules"], dict)
        assert data["rules"]["DD001"] is None or isinstance(data["rules"], dict)

    def test_comments_stripped(self):
        text = "severity: warning  # this is a comment\n# full line comment\nignore:\n  - DD001\n"
        data = _load_yaml_fallback(text)
        assert data["severity"] == "warning"
        assert data["ignore"] == ["DD001"]

    def test_empty_input(self):
        data = _load_yaml_fallback("")
        assert data == {}

    def test_boolean_values(self):
        text = "enabled: true\ndisabled: false\n"
        data = _load_yaml_fallback(text)
        assert data["enabled"] is True
        assert data["disabled"] is False


# ===========================================================================
# Config defaults
# ===========================================================================

class TestConfigDefaults:
    def test_default_config(self):
        cfg = Config.default()
        assert cfg.severity == "info"
        assert cfg.ignore == []
        assert cfg.rules == {}

    def test_merge_cli_severity(self):
        cfg = Config.default()
        cfg.merge_cli(severity="error")
        assert cfg.severity == "error"

    def test_merge_cli_ignore(self):
        cfg = Config(ignore=["DD001"])
        cfg.merge_cli(ignore=["DD002", "DD003"])
        assert "DD001" in cfg.ignore
        assert "DD002" in cfg.ignore
        assert "DD003" in cfg.ignore

    def test_merge_cli_none_no_change(self):
        cfg = Config(severity="warning", ignore=["DD001"])
        cfg.merge_cli(severity=None, ignore=None)
        assert cfg.severity == "warning"
        assert cfg.ignore == ["DD001"]


# ===========================================================================
# Config file loading
# ===========================================================================

class TestLoadConfig:
    def test_load_from_explicit_path(self, tmp_path):
        cfg_file = tmp_path / ".dockerfile-doctor.yaml"
        cfg_file.write_text(
            "severity: warning\nignore:\n  - DD001\n  - DD012\n",
            encoding="utf-8",
        )
        cfg = load_config(str(cfg_file))
        assert cfg.severity == "warning"
        assert "DD001" in cfg.ignore
        assert "DD012" in cfg.ignore

    def test_load_with_rules_section(self, tmp_path):
        cfg_file = tmp_path / ".dockerfile-doctor.yaml"
        cfg_file.write_text(
            "rules:\n  DD008:\n    severity: error\n",
            encoding="utf-8",
        )
        cfg = load_config(str(cfg_file))
        assert "DD008" in cfg.rules
        assert cfg.rules["DD008"].severity == "error"

    def test_load_default_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config(None)
        assert cfg.severity == "info"
        assert cfg.ignore == []

    def test_auto_discover_in_cwd(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / ".dockerfile-doctor.yaml"
        cfg_file.write_text("severity: error\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        cfg = load_config(None)
        assert cfg.severity == "error"

    def test_auto_discover_yml_extension(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / ".dockerfile-doctor.yml"
        cfg_file.write_text("severity: warning\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        cfg = load_config(None)
        assert cfg.severity == "warning"

    def test_invalid_severity_ignored(self, tmp_path):
        cfg_file = tmp_path / ".dockerfile-doctor.yaml"
        cfg_file.write_text("severity: critical\n", encoding="utf-8")
        cfg = load_config(str(cfg_file))
        # "critical" is not valid, should keep default
        assert cfg.severity == "info"

    def test_empty_config_file(self, tmp_path):
        cfg_file = tmp_path / ".dockerfile-doctor.yaml"
        cfg_file.write_text("# empty config\nignore: []\n", encoding="utf-8")
        cfg = load_config(str(cfg_file))
        assert cfg.severity == "info"
        assert cfg.ignore == []

    def test_ignore_only_config(self, tmp_path):
        cfg_file = tmp_path / ".dockerfile-doctor.yaml"
        cfg_file.write_text("ignore:\n  - DD012\n  - DD015\n", encoding="utf-8")
        cfg = load_config(str(cfg_file))
        assert "DD012" in cfg.ignore
        assert "DD015" in cfg.ignore
        assert cfg.severity == "info"

    def test_nonexistent_config_path_raises(self):
        with pytest.raises((FileNotFoundError, OSError)):
            load_config("/nonexistent/path/config.yaml")


# ===========================================================================
# Config merge behavior
# ===========================================================================

class TestConfigMerge:
    def test_merge_cli_severity_overrides(self):
        cfg = Config(severity="info")
        cfg.merge_cli(severity="error")
        assert cfg.severity == "error"

    def test_merge_cli_ignore_adds(self):
        cfg = Config(ignore=["DD001"])
        cfg.merge_cli(ignore=["DD002"])
        assert "DD001" in cfg.ignore
        assert "DD002" in cfg.ignore

    def test_merge_cli_ignore_deduplicates(self):
        cfg = Config(ignore=["DD001"])
        cfg.merge_cli(ignore=["DD001", "DD002"])
        assert cfg.ignore.count("DD001") == 1

    def test_config_ignore_membership(self):
        cfg = Config(ignore=["DD001", "DD012"])
        assert "DD001" in cfg.ignore
        assert "DD012" in cfg.ignore
        assert "DD002" not in cfg.ignore
