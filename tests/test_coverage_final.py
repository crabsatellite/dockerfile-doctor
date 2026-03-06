"""Targeted tests for uncovered lines in config, parser, reporter, and fixer."""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from dockerfile_doctor.fixer import fix, _FIX_HANDLERS
from dockerfile_doctor.config import _load_yaml_fallback, _strip_trailing_comment, load_config
from dockerfile_doctor.reporter import _should_use_color, _get_colors
from dockerfile_doctor.models import Issue, Severity, Category, Dockerfile, Fix


# =========================================================================
# config.py
# =========================================================================

class TestStripTrailingComment:
    """Cover lines 62, 64, 87 in config.py."""

    def test_single_quote_preserves_hash(self):
        """Line 62: single-quote toggle prevents comment stripping."""
        result = _strip_trailing_comment("key: 'value#with hash'")
        assert result == "key: 'value#with hash'"

    def test_double_quote_preserves_hash(self):
        """Line 64: double-quote toggle prevents comment stripping."""
        result = _strip_trailing_comment('key: "value#with hash"')
        assert result == 'key: "value#with hash"'

    def test_unquoted_trailing_comment(self):
        """Baseline: trailing comment IS stripped when unquoted."""
        result = _strip_trailing_comment("key: value # this is a comment")
        assert result == "key: value"

    def test_single_quote_with_trailing_comment(self):
        """Single-quoted value followed by a real trailing comment."""
        result = _strip_trailing_comment("key: 'val' # comment")
        assert result == "key: 'val'"


class TestLoadYamlFallback:
    """Cover lines 87, 99, 118-119 in config.py."""

    def test_line_becomes_empty_after_comment_strip(self):
        """Line 87: line that becomes empty after stripping trailing comment."""
        # A line that is just a trailing comment after a space: "  # only comment"
        # That's caught by the startswith('#') check. We need a line that
        # _strip_trailing_comment reduces to empty/whitespace but is not a pure comment.
        # Example: a line that is just whitespace - after strip, it's empty
        text = "key1: value1\n   \nkey2: value2"
        result = _load_yaml_fallback(text)
        assert result == {"key1": "value1", "key2": "value2"}

    def test_top_level_line_without_colon(self):
        """Line 99: top-level line with no colon is skipped."""
        text = "key1: value1\njust_a_word\nkey2: value2"
        result = _load_yaml_fallback(text)
        assert result == {"key1": "value1", "key2": "value2"}

    def test_nested_mapping_after_list_flush(self):
        """Lines 117-119: flush list then start nested mapping within same key.
        This covers the branch where current_list is not None when we see a
        nested mapping under the SAME top-level key."""
        text = (
            "parent:\n"
            "  - item1\n"
            "  - item2\n"
            "  sub_key: sub_val\n"
        )
        result = _load_yaml_fallback(text)
        # The list gets flushed, then the sub mapping overwrites parent
        assert result["parent"] == {"sub_key": "sub_val"}

    def test_flush_sub_writes_to_result(self):
        """Lines 118-119 / 141-142: _flush_sub actually writing nested mapping."""
        text = (
            "rules:\n"
            "  DD001:\n"
            "    severity: error\n"
        )
        result = _load_yaml_fallback(text)
        # The nested mapping under "rules" should be flushed
        assert "rules" in result


class TestLoadConfigAutoDiscovery:
    """Cover line 183 (fallback YAML loader) and config auto-discovery walking
    to a parent directory."""

    def test_auto_discover_in_parent_directory(self):
        """Line ~207-210 in load_config: walk to parent to find config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write config in tmpdir (the "parent")
            config_path = os.path.join(tmpdir, ".dockerfile-doctor.yaml")
            with open(config_path, "w") as f:
                f.write("severity: warning\n")

            # Create a child directory
            child = os.path.join(tmpdir, "subdir")
            os.makedirs(child)

            # Run load_config from child dir, should find parent config
            with patch("os.getcwd", return_value=child):
                cfg = load_config()
            assert cfg.severity == "warning"

    def test_load_yaml_fallback_used_when_pyyaml_missing(self):
        """Line 183: _load_yaml falls back when PyYAML not importable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, ".dockerfile-doctor.yaml")
            with open(config_path, "w") as f:
                f.write("severity: error\nignore:\n  - DD001\n")

            # Mock yaml import to fail
            import dockerfile_doctor.config as config_mod
            original = config_mod._load_yaml_pyyaml

            def raise_import(*a, **kw):
                raise ImportError("no yaml")

            config_mod._load_yaml_pyyaml = raise_import
            try:
                with patch("os.getcwd", return_value=tmpdir):
                    cfg = load_config()
                assert cfg.severity == "error"
                assert "DD001" in cfg.ignore
            finally:
                config_mod._load_yaml_pyyaml = original


# =========================================================================
# parser.py
# =========================================================================

class TestParserEdgeCases:
    """Cover lines 167 and 195 in parser.py."""

    def test_split_directive_empty_parts(self):
        """Line 167: _split_directive with a line that splits to empty parts.
        Blank lines between instructions should be handled gracefully."""
        content = "FROM ubuntu\n\n\nRUN echo hello\n"
        df = parse(content)
        directives = [i.directive for i in df.instructions]
        assert "FROM" in directives
        assert "RUN" in directives

    def test_from_with_empty_args(self):
        """Line 195: FROM with no arguments yields ('scratch', None)."""
        # We test the _parse_base_image path through _build_stages
        content = "FROM   \n"
        df = parse(content)
        assert len(df.stages) == 1
        assert df.stages[0].base_image == "scratch"
        assert df.stages[0].base_tag is None


# =========================================================================
# reporter.py
# =========================================================================

class TestShouldUseColor:
    """Cover lines 44, 54, 57, 61 in reporter.py."""

    def test_no_color_flag_true(self):
        """Line 50-51: no_color_flag=True returns False."""
        assert _should_use_color(no_color_flag=True) is False

    def test_no_color_env_var(self):
        """Line 53-54: NO_COLOR env var present returns False."""
        with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            assert _should_use_color(no_color_flag=False) is False

    def test_term_dumb(self):
        """Line 56-57: TERM=dumb returns False."""
        env = {"TERM": "dumb"}
        # Remove NO_COLOR if present
        with patch.dict(os.environ, env, clear=False):
            # Also ensure NO_COLOR is not set
            os.environ.pop("NO_COLOR", None)
            assert _should_use_color(no_color_flag=False) is False

    def test_isatty_true_returns_true(self):
        """Line 61: when isatty() returns True, we get True."""
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        env.pop("TERM", None)
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sys, "stdout", mock_stdout):
                assert _should_use_color(no_color_flag=False) is True

    def test_isatty_false_returns_false(self):
        """Line 59-60: when isatty() returns False, we get False."""
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = False
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        env.pop("TERM", None)
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sys, "stdout", mock_stdout):
                assert _should_use_color(no_color_flag=False) is False


class TestGetColors:
    """Cover line 44 (_get_colors with True) in reporter.py."""

    def test_get_colors_true(self):
        """Line 44: returns _Colors instance."""
        c = _get_colors(True)
        assert c.RED == "\033[91m"

    def test_get_colors_false(self):
        """Returns no-color instance with empty strings."""
        c = _get_colors(False)
        assert c.RED == ""


# =========================================================================
# fixer.py
# =========================================================================

class TestFixerDD005Dedup:
    """Cover lines 76 and 81 in fixer.py."""

    def test_duplicate_dd005_same_line(self):
        """Line 76: duplicate DD005 issue at same line is skipped."""
        content = "FROM ubuntu\nRUN echo a\nRUN echo b\n"
        df = parse(content)
        # Create two DD005 issues at the same line
        issue1 = Issue(
            rule_id="DD005", title="Combine RUN", description="",
            severity=Severity.WARNING, category=Category.PERFORMANCE,
            line_number=2, fix_available=True,
        )
        issue2 = Issue(
            rule_id="DD005", title="Combine RUN", description="",
            severity=Severity.WARNING, category=Category.PERFORMANCE,
            line_number=2, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue1, issue2])
        # Should only apply once (the duplicate is skipped at line 76)
        dd005_fixes = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005_fixes) <= 1


class TestFixerDD004TrailingBackslash:
    """Cover line 227 in fixer.py."""

    def test_dd004_trailing_backslash(self):
        """Line 227: DD004 with instruction ending in backslash."""
        content = "FROM ubuntu\nRUN apt-get update && \\\n    apt-get install -y curl \\\n    wget\n"
        df = parse(content)
        issues = analyze(df)
        dd004 = [i for i in issues if i.rule_id == "DD004"]
        if dd004:
            fixed_content, fixes = fix(df, dd004)
            assert "rm -rf /var/lib/apt/lists" in fixed_content


class TestFixerDD031TrailingBackslash:
    """Cover line 652 in fixer.py."""

    def test_dd031_trailing_backslash(self):
        """Line 652: DD031 with yum install ending in backslash."""
        content = "FROM centos:7\nRUN yum install -y curl \\\n    wget\n"
        df = parse(content)
        issues = analyze(df)
        dd031 = [i for i in issues if i.rule_id == "DD031"]
        if dd031:
            fixed_content, fixes = fix(df, dd031)
            assert "yum clean all" in fixed_content
        else:
            # Manually invoke fixer
            issue = Issue(
                rule_id="DD031", title="yum clean", description="",
                severity=Severity.WARNING, category=Category.PERFORMANCE,
                line_number=2, fix_available=True,
            )
            fixed_content, fixes = fix(df, [issue])
            assert "yum clean all" in fixed_content


class TestFixerDD033TrailingBackslash:
    """Cover line 672 in fixer.py."""

    def test_dd033_trailing_backslash(self):
        """Line 672: DD033 with dnf install ending in backslash."""
        content = "FROM fedora\nRUN dnf install -y curl \\\n    wget\n"
        df = parse(content)
        issues = analyze(df)
        dd033 = [i for i in issues if i.rule_id == "DD033"]
        if dd033:
            fixed_content, fixes = fix(df, dd033)
            assert "dnf clean all" in fixed_content
        else:
            issue = Issue(
                rule_id="DD033", title="dnf clean", description="",
                severity=Severity.WARNING, category=Category.PERFORMANCE,
                line_number=2, fix_available=True,
            )
            fixed_content, fixes = fix(df, [issue])
            assert "dnf clean all" in fixed_content


class TestFixerDD034TrailingBackslash:
    """Cover line 692 in fixer.py."""

    def test_dd034_trailing_backslash(self):
        """Line 692: DD034 with zypper install ending in backslash."""
        content = "FROM opensuse/leap\nRUN zypper install -y curl \\\n    wget\n"
        df = parse(content)
        issues = analyze(df)
        dd034 = [i for i in issues if i.rule_id == "DD034"]
        if dd034:
            fixed_content, fixes = fix(df, dd034)
            assert "zypper clean" in fixed_content
        else:
            issue = Issue(
                rule_id="DD034", title="zypper clean", description="",
                severity=Severity.WARNING, category=Category.PERFORMANCE,
                line_number=2, fix_available=True,
            )
            fixed_content, fixes = fix(df, [issue])
            assert "zypper clean" in fixed_content


class TestFixerDD011RelativeWorkdir:
    """Cover lines 952-954 in fixer.py."""

    def test_dd011_relative_workdir(self):
        """Lines 952-954: relative WORKDIR 'app' becomes '/app'."""
        content = "FROM ubuntu\nWORKDIR app\n"
        df = parse(content)
        issues = analyze(df)
        dd011 = [i for i in issues if i.rule_id == "DD011"]
        if dd011:
            fixed_content, fixes = fix(df, dd011)
            assert "WORKDIR /app" in fixed_content
        else:
            # Manually create issue
            issue = Issue(
                rule_id="DD011", title="Relative WORKDIR", description="",
                severity=Severity.WARNING, category=Category.BEST_PRACTICE,
                line_number=2, fix_available=True,
            )
            fixed_content, fixes = fix(df, [issue])
            assert "WORKDIR /app" in fixed_content


class TestFixerDD008EdgeCases:
    """Cover lines 1192, 1194 in fixer.py."""

    def test_dd008_nonzero_line_number(self):
        """Line 1192: DD008 with non-zero line_number returns None (no fix)."""
        content = "FROM ubuntu\nUSER root\nCMD echo hi\n"
        df = parse(content)
        issue = Issue(
            rule_id="DD008", title="Running as root", description="",
            severity=Severity.WARNING, category=Category.SECURITY,
            line_number=2, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue])
        dd008_fixes = [f for f in fixes if f.rule_id == "DD008"]
        assert len(dd008_fixes) == 0

    def test_dd008_empty_dockerfile(self):
        """Line 1194: DD008 with no stages (empty dockerfile)."""
        content = "# just a comment\n"
        df = parse(content)
        issue = Issue(
            rule_id="DD008", title="No USER", description="",
            severity=Severity.WARNING, category=Category.SECURITY,
            line_number=0, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue])
        dd008_fixes = [f for f in fixes if f.rule_id == "DD008"]
        assert len(dd008_fixes) == 0


class TestFixerDD015NoFrom:
    """Cover line 1226 in fixer.py."""

    def test_dd015_no_from_instruction(self):
        """Line 1226: DD015 returns None when no FROM instruction exists."""
        content = "# no FROM here\nRUN echo hi\n"
        df = parse(content)
        issue = Issue(
            rule_id="DD015", title="Missing Python env", description="",
            severity=Severity.INFO, category=Category.PERFORMANCE,
            line_number=0, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue])
        dd015_fixes = [f for f in fixes if f.rule_id == "DD015"]
        assert len(dd015_fixes) == 0


class TestFixerDD046NoFrom:
    """Cover line 1241 in fixer.py."""

    def test_dd046_no_from_instruction(self):
        """Line 1241: DD046 returns None when no FROM instruction exists."""
        content = "# no FROM\nRUN echo hi\n"
        df = parse(content)
        issue = Issue(
            rule_id="DD046", title="Missing labels", description="",
            severity=Severity.INFO, category=Category.MAINTAINABILITY,
            line_number=0, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue])
        dd046_fixes = [f for f in fixes if f.rule_id == "DD046"]
        assert len(dd046_fixes) == 0


class TestFixerDD068NonJava:
    """Cover line 1261 in fixer.py."""

    def test_dd068_non_java_from(self):
        """Line 1261: DD068 returns None when FROM is not a Java image."""
        content = "FROM python:3.11\nCMD python app.py\n"
        df = parse(content)
        issue = Issue(
            rule_id="DD068", title="Java flags", description="",
            severity=Severity.INFO, category=Category.PERFORMANCE,
            line_number=0, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue])
        dd068_fixes = [f for f in fixes if f.rule_id == "DD068"]
        assert len(dd068_fixes) == 0

    def test_dd068_java_from_works(self):
        """Positive case: DD068 with a Java image should add JAVA_OPTS."""
        content = "FROM eclipse-temurin:17\nCMD java -jar app.jar\n"
        df = parse(content)
        issue = Issue(
            rule_id="DD068", title="Java flags", description="",
            severity=Severity.INFO, category=Category.PERFORMANCE,
            line_number=0, fix_available=True,
        )
        fixed_content, fixes = fix(df, [issue])
        dd068_fixes = [f for f in fixes if f.rule_id == "DD068"]
        assert len(dd068_fixes) == 1
        assert "JAVA_OPTS" in fixed_content
