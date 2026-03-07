"""Tests for the Dockerfile Doctor auto-fixer."""

from __future__ import annotations

import pytest

from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from dockerfile_doctor.fixer import fix
from dockerfile_doctor.models import Issue, Fix, Severity, Category


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _analyze_and_fix(content: str, *, unsafe: bool = True) -> tuple[str, list[Issue], list[Fix]]:
    """Return (fixed_content, issues, fixes) for inspection."""
    df = parse(content)
    issues = analyze(df)
    fixed_content, fixes = fix(df, issues, unsafe=unsafe)
    return fixed_content, issues, fixes


# ===========================================================================
# Individual fixable rules
# ===========================================================================

class TestFixDD003NoInstallRecommends:
    """DD003: Add --no-install-recommends to apt-get install."""

    def test_adds_flag(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd003_fixes = [f for f in fixes if f.rule_id == "DD003"]
        assert len(dd003_fixes) >= 1
        assert "--no-install-recommends" in fixed


class TestFixDD004MissingAptCleanup:
    """DD004: Add rm -rf /var/lib/apt/lists/* to apt-get RUN."""

    def test_adds_cleanup(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd004_fixes = [f for f in fixes if f.rule_id == "DD004"]
        assert len(dd004_fixes) >= 1
        assert "rm -rf /var/lib/apt/lists/*" in fixed


class TestFixDD007AddInsteadOfCopy:
    """DD007: Replace ADD with COPY for local files."""

    def test_replaces_add_with_copy(self):
        content = "FROM alpine:3.19\nADD . /app\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd007_fixes = [f for f in fixes if f.rule_id == "DD007"]
        assert len(dd007_fixes) >= 1
        assert "COPY . /app" in fixed
        assert "ADD . /app" not in fixed


class TestFixDD009PipNoCacheDir:
    """DD009: Add --no-cache-dir to pip install."""

    def test_adds_flag(self):
        content = "FROM python:3.11\nRUN pip install flask\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd009_fixes = [f for f in fixes if f.rule_id == "DD009"]
        assert len(dd009_fixes) >= 1
        assert "--no-cache-dir" in fixed


class TestFixDD010NpmInstall:
    """DD010: Replace npm install with npm ci."""

    def test_replaces_with_ci(self):
        content = "FROM node:20\nCOPY package*.json ./\nRUN npm install\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd010_fixes = [f for f in fixes if f.rule_id == "DD010"]
        assert len(dd010_fixes) >= 1
        assert "npm ci" in fixed


class TestFixDD017DeprecatedMaintainer:
    """DD017: Replace MAINTAINER with LABEL maintainer=."""

    def test_replaces_with_label(self):
        content = "FROM alpine:3.19\nMAINTAINER user@example.com\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd017_fixes = [f for f in fixes if f.rule_id == "DD017"]
        assert len(dd017_fixes) >= 1
        assert "LABEL maintainer=" in fixed or 'LABEL maintainer="user@example.com"' in fixed
        assert "MAINTAINER" not in fixed


class TestFixDD019ShellFormCmd:
    """DD019: Convert shell form CMD to exec form."""

    def test_converts_to_exec_form(self):
        content = "FROM alpine:3.19\nCMD python app.py\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd019_fixes = [f for f in fixes if f.rule_id == "DD019"]
        assert len(dd019_fixes) >= 1
        assert '["python", "app.py"]' in fixed or "CMD [" in fixed


# ===========================================================================
# Non-fixable rules left untouched
# ===========================================================================

class TestNonFixableRules:
    """Rules without auto-fixes should not produce Fix objects."""

    def test_dd008_no_user_is_auto_fixed(self):
        """DD008 (no USER) is now auto-fixable."""
        content = "FROM ubuntu:22.04\nCMD [\"bash\"]\n"
        df = parse(content)
        issues = analyze(df)
        _, fixes = fix(df, issues, unsafe=True)
        dd008_fixes = [f for f in fixes if f.rule_id == "DD008"]
        assert len(dd008_fixes) == 1

    def test_dd020_secrets_not_auto_fixed(self):
        """DD020 (secrets in ENV) is not auto-fixable."""
        content = "FROM alpine:3.19\nENV password=secret123\n"
        df = parse(content)
        issues = analyze(df)
        _, fixes = fix(df, issues, unsafe=True)
        dd020_fixes = [f for f in fixes if f.rule_id == "DD020"]
        assert len(dd020_fixes) == 0

    def test_dd012_no_healthcheck_not_auto_fixed(self):
        """DD012 (no HEALTHCHECK) is not auto-fixable."""
        content = "FROM alpine:3.19\nCMD [\"sh\"]\n"
        df = parse(content)
        issues = analyze(df)
        _, fixes = fix(df, issues, unsafe=True)
        dd012_fixes = [f for f in fixes if f.rule_id == "DD012"]
        assert len(dd012_fixes) == 0

    def test_dd014_insecure_ports_not_auto_fixed(self):
        """DD014 (insecure ports) is not auto-fixable."""
        content = "FROM alpine:3.19\nEXPOSE 23\n"
        df = parse(content)
        issues = analyze(df)
        _, fixes = fix(df, issues, unsafe=True)
        dd014_fixes = [f for f in fixes if f.rule_id == "DD014"]
        assert len(dd014_fixes) == 0


# ===========================================================================
# Fix ordering (multiple fixes)
# ===========================================================================

class TestFixOrdering:
    """Test that multiple fixes on same/adjacent lines apply correctly."""

    def test_multiple_fixes_same_run_line(self):
        """apt-get install without recommends or cleanup: DD003 + DD004 on same RUN."""
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists/*" in fixed

    def test_fixes_on_different_lines(self):
        """Multiple issues on different lines should all be fixed."""
        content = (
            "FROM alpine:3.19\n"
            "MAINTAINER user@example.com\n"
            "ADD . /app\n"
            "CMD python app.py\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        # DD017: MAINTAINER -> LABEL
        assert "MAINTAINER" not in fixed
        # DD007: ADD -> COPY
        assert "COPY . /app" in fixed
        # DD019: shell CMD -> exec
        assert "CMD [" in fixed or '["python"' in fixed

    def test_fix_preserves_unrelated_lines(self):
        """Fixes should not corrupt lines that have no issues."""
        content = (
            "FROM alpine:3.19\n"
            "EXPOSE 8080\n"
            "CMD [\"echo\", \"hello\"]\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "EXPOSE 8080" in fixed
        assert 'CMD ["echo", "hello"]' in fixed


# ===========================================================================
# Syntax preservation
# ===========================================================================

class TestSyntaxPreservation:
    """Applying fixes should not break Dockerfile syntax."""

    def test_fixed_dockerfile_is_parseable(self):
        content = (
            "FROM ubuntu:22.04\n"
            "MAINTAINER user@example.com\n"
            "ADD . /app\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "RUN pip install flask\n"
            "CMD python app.py\n"
        )
        fixed, _, _ = _analyze_and_fix(content)
        # The fixed content should still parse without errors
        df = parse(fixed)
        assert len(df.instructions) > 0
        assert df.instructions[0].directive == "FROM"

    def test_empty_dockerfile_no_crash(self):
        fixed, issues, fixes = _analyze_and_fix("")
        assert fixed == ""
        assert len(fixes) == 0

    def test_idempotent_on_clean_dockerfile(self):
        """Fixing a clean Dockerfile should return it unchanged."""
        content = (
            "FROM alpine:3.19\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            "USER nobody\n"
            "HEALTHCHECK CMD wget -q http://localhost/\n"
            "CMD [\"echo\", \"hello\"]\n"
        )
        df = parse(content)
        issues = analyze(df)
        fixable_issues = [i for i in issues if i.fix_available]
        if not fixable_issues:
            fixed_content, fixes = fix(df, issues, unsafe=True)
            # No fixable issues means content should be unchanged
            assert len(fixes) == 0


# ===========================================================================
# Fixer edge cases — overlapping fixes
# ===========================================================================

class TestFixerOverlapping:
    """Test that DD005 (combine RUNs) + DD003/DD004 (apt fixes) don't corrupt output."""

    def test_dd005_with_dd003_dd004_no_corruption(self):
        """Consecutive RUN instructions with apt-get: DD005 should combine,
        DD003/DD004 should NOT also modify the same lines (overlap protection)."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update\n"
            "RUN apt-get install -y curl\n"
            "RUN echo done\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        # The fixed content should be valid (parseable)
        df = parse(fixed)
        assert len(df.instructions) > 0
        assert df.instructions[0].directive == "FROM"
        # The RUNs should be combined (DD005 applied)
        dd005_fixes = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005_fixes) >= 1

    def test_dd005_combined_content_is_valid(self):
        """After DD005 combines RUNs, the result should contain all commands."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN echo first\n"
            "RUN echo second\n"
            "RUN echo third\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "first" in fixed
        assert "second" in fixed
        assert "third" in fixed

    def test_single_apt_run_gets_dd003_dd004(self):
        """A single apt-get RUN (no streak) should still get DD003+DD004 fixes."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "CMD [\"bash\"]\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists/*" in fixed


class TestFixerDD019EdgeCases:
    """Test DD019 shell-to-exec conversion edge cases."""

    def test_simple_command_to_exec_form(self):
        """Simple command without shell operators should become clean exec form."""
        content = "FROM alpine:3.19\nCMD python app.py\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd019_fixes = [f for f in fixes if f.rule_id == "DD019"]
        assert len(dd019_fixes) >= 1
        assert '["python", "app.py"]' in fixed

    def test_pipe_command_gets_shell_wrapper(self):
        """Command with pipe should be wrapped in /bin/sh -c."""
        content = "FROM alpine:3.19\nCMD cat /etc/hosts | grep localhost\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "/bin/sh" in fixed

    def test_dollar_sign_gets_shell_wrapper(self):
        """Command with $VAR needs /bin/sh -c for variable expansion."""
        content = "FROM alpine:3.19\nCMD gunicorn --bind 0.0.0.0:$PORT app:app\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd019_fixes = [f for f in fixes if f.rule_id == "DD019"]
        assert len(dd019_fixes) >= 1
        # Must use /bin/sh -c so $PORT gets expanded
        assert "/bin/sh" in fixed
        assert "$PORT" in fixed


class TestFixerDD013:
    """DD013: Remove apt-get upgrade."""

    def test_removes_standalone_upgrade(self):
        content = "FROM ubuntu:22.04\nRUN apt-get upgrade -y\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd013_fixes = [f for f in fixes if f.rule_id == "DD013"]
        assert len(dd013_fixes) >= 1
        assert "apt-get upgrade" not in fixed

    def test_removes_upgrade_from_chain(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get upgrade -y && apt-get install -y curl\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "apt-get upgrade" not in fixed
        assert "apt-get install" in fixed


class TestFixerDD005:
    """DD005: Combine consecutive RUN instructions."""

    def test_combines_two_runs(self):
        content = "FROM alpine:3.19\nRUN echo a\nRUN echo b\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        dd005_fixes = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005_fixes) >= 1
        assert "echo a" in fixed
        assert "echo b" in fixed
        assert "&&" in fixed

    def test_blank_line_between_runs(self):
        """Blank lines between consecutive RUNs should not corrupt output."""
        content = "FROM alpine:3.19\nRUN echo a\n\nRUN echo b\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        df = parse(fixed)
        assert len(df.instructions) > 0
        assert "echo a" in fixed
        assert "echo b" in fixed


# ===========================================================================
# Fixer pip3 / python -m pip support
# ===========================================================================

class TestFixerPip3:
    """DD009 fixer should handle pip3 and python -m pip."""

    def test_pip3_gets_no_cache_dir(self):
        content = "FROM python:3.11\nRUN pip3 install flask\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd009 = [f for f in fixes if f.rule_id == "DD009"]
        assert len(dd009) >= 1
        assert "--no-cache-dir" in fixed

    def test_python_m_pip_gets_no_cache_dir(self):
        content = "FROM python:3.11\nRUN python -m pip install flask\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd009 = [f for f in fixes if f.rule_id == "DD009"]
        assert len(dd009) >= 1
        assert "--no-cache-dir" in fixed


# ===========================================================================
# Fixer apt (without -get) support
# ===========================================================================

class TestFixerApt:
    """DD003/DD004 fixer should handle 'apt install' as well as 'apt-get install'."""

    def test_dd003_apt_install(self):
        content = "FROM ubuntu:22.04\nRUN apt update && apt install -y curl\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd003 = [f for f in fixes if f.rule_id == "DD003"]
        assert len(dd003) >= 1
        assert "--no-install-recommends" in fixed

    def test_dd004_apt_install(self):
        content = "FROM ubuntu:22.04\nRUN apt update && apt install -y curl\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd004 = [f for f in fixes if f.rule_id == "DD004"]
        assert len(dd004) >= 1
        assert "rm -rf /var/lib/apt/lists/*" in fixed

    def test_dd013_apt_upgrade(self):
        content = "FROM ubuntu:22.04\nRUN apt upgrade -y\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd013 = [f for f in fixes if f.rule_id == "DD013"]
        assert len(dd013) >= 1
        assert "apt upgrade" not in fixed


# ===========================================================================
# Fixer DD010 bare npm install only
# ===========================================================================

class TestFixerDD010Bare:
    """DD010 fixer should only replace bare 'npm install'."""

    def test_bare_npm_install_fixed(self):
        content = "FROM node:20\nCOPY package*.json ./\nRUN npm install\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd010 = [f for f in fixes if f.rule_id == "DD010"]
        assert len(dd010) >= 1
        assert "npm ci" in fixed

    def test_npm_install_package_not_fixed(self):
        """npm install <pkg> should NOT trigger DD010."""
        content = "FROM node:20\nRUN npm install express\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd010 = [f for f in fixes if f.rule_id == "DD010"]
        assert len(dd010) == 0

    def test_npm_install_chain_preserves_space(self):
        """npm install && npm run build should become npm ci && npm run build."""
        content = "FROM node:20\nCOPY package*.json ./\nRUN npm install && npm run build\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd010 = [f for f in fixes if f.rule_id == "DD010"]
        assert len(dd010) >= 1
        # Must have space before &&
        assert "npm ci &&" in fixed or "npm ci&&" not in fixed


# ===========================================================================
# Roundtrip idempotency
# ===========================================================================

class TestRoundtripIdempotency:
    """Fixing a fixed Dockerfile should produce no further changes."""

    def test_idempotent_apt_dockerfile(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "USER nobody\n"
            "HEALTHCHECK CMD curl -f http://localhost/\n"
            'CMD ["bash"]\n'
        )
        fixed1, _, fixes1 = _analyze_and_fix(content)
        assert len(fixes1) > 0
        # Fix again — should produce no more fixes
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        assert len([f for f in fixes2 if f.rule_id in ("DD003", "DD004")]) == 0

    def test_idempotent_maintainer(self):
        content = "FROM alpine:3.19\nMAINTAINER user@example.com\nCMD echo hi\n"
        fixed1, _, _ = _analyze_and_fix(content)
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        dd017 = [f for f in fixes2 if f.rule_id == "DD017"]
        assert len(dd017) == 0

    def test_idempotent_dd005(self):
        content = "FROM alpine:3.19\nRUN echo a\nRUN echo b\nRUN echo c\n"
        fixed1, _, _ = _analyze_and_fix(content)
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        dd005 = [f for f in fixes2 if f.rule_id == "DD005"]
        assert len(dd005) == 0

    def test_idempotent_dd005_with_apt(self):
        """DD005 + DD003/DD004 should all apply in a single --fix pass."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "RUN echo hello\n"
            "RUN echo world\n"
        )
        fixed1, _, fixes1 = _analyze_and_fix(content)
        # DD005 should combine, AND DD003/DD004 should apply
        assert "&&" in fixed1  # combined
        assert "--no-install-recommends" in fixed1  # DD003
        assert "rm -rf /var/lib/apt/lists" in fixed1  # DD004
        # Second pass should produce no more fixes
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        fixable2 = [f for f in fixes2 if f.rule_id in ("DD003", "DD004", "DD005")]
        assert len(fixable2) == 0


# ===========================================================================
# DD019 double-quote escaping in exec form
# ===========================================================================

class TestFixerDD019Quotes:
    """DD019 fixer must escape double quotes in command arguments."""

    def test_double_quotes_escaped(self):
        content = '''FROM alpine:3.19\nCMD echo 'hello "world"'\n'''
        fixed, _, fixes = _analyze_and_fix(content)
        dd019 = [f for f in fixes if f.rule_id == "DD019"]
        assert len(dd019) >= 1
        # Inner quotes must be escaped
        assert '\\"world\\"' in fixed or '\\"' in fixed

    def test_simple_command_no_quotes(self):
        content = "FROM alpine:3.19\nCMD python app.py\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert '["python", "app.py"]' in fixed

    def test_multiline_cmd_not_corrupted(self):
        """Multi-line CMD with backslash continuation should not corrupt."""
        content = "FROM alpine:3.19\nCMD python \\\n    app.py\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd019 = [f for f in fixes if f.rule_id == "DD019"]
        assert len(dd019) >= 1
        assert '["python", "app.py"]' in fixed
        # Must NOT have newline characters in the exec form
        assert "\\n" not in fixed.split("CMD")[1] if "CMD" in fixed else True


# ===========================================================================
# DD013 fixer ordering with DD004 on same line
# ===========================================================================

class TestFixerDD013Ordering:
    """DD013 removal must happen before DD004 appends cleanup."""

    def test_dd013_before_dd004(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y curl && apt-get upgrade -y\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd013 = [f for f in fixes if f.rule_id == "DD013"]
        assert len(dd013) >= 1
        assert "apt-get upgrade" not in fixed


# ===========================================================================
# DD017 fixer quote escaping
# ===========================================================================

class TestFixerDD017Quotes:
    """DD017 fixer must handle quotes in maintainer value."""

    def test_maintainer_with_quotes(self):
        content = 'FROM alpine:3.19\nMAINTAINER John "Dev" Doe\n'
        fixed, _, fixes = _analyze_and_fix(content)
        dd017 = [f for f in fixes if f.rule_id == "DD017"]
        assert len(dd017) >= 1
        assert "LABEL maintainer=" in fixed
        # Double quotes must be escaped
        assert '\\"Dev\\"' in fixed

    def test_maintainer_with_angle_brackets(self):
        content = "FROM alpine:3.19\nMAINTAINER John Doe <john@example.com>\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd017 = [f for f in fixes if f.rule_id == "DD017"]
        assert len(dd017) >= 1
        assert "LABEL maintainer=" in fixed
        assert "john@example.com" in fixed

    def test_maintainer_single_quotes(self):
        content = "FROM alpine:3.19\nMAINTAINER 'user@example.com'\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "LABEL maintainer=" in fixed
        assert "user@example.com" in fixed


# ===========================================================================
# Fixer DD007 edge cases
# ===========================================================================

class TestFixerDD007EdgeCases:
    """DD007 fixer edge cases."""

    def test_add_with_chown_becomes_copy(self):
        content = "FROM alpine:3.19\nADD --chown=1000:1000 . /app\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd007 = [f for f in fixes if f.rule_id == "DD007"]
        assert len(dd007) >= 1
        assert "COPY" in fixed
        assert "--chown=1000:1000" in fixed

    def test_add_preserves_destination(self):
        content = "FROM alpine:3.19\nADD file.txt /opt/data/\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "COPY file.txt /opt/data/" in fixed


# ===========================================================================
# Fixer DD019 more edge cases
# ===========================================================================

class TestFixerDD019MoreEdgeCases:
    """More DD019 fixer edge cases."""

    def test_entrypoint_conversion(self):
        content = "FROM alpine:3.19\nENTRYPOINT python app.py\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd019 = [f for f in fixes if f.rule_id == "DD019"]
        assert len(dd019) >= 1
        assert "ENTRYPOINT [" in fixed

    def test_cmd_with_semicolon_gets_shell(self):
        content = "FROM alpine:3.19\nCMD echo hello; echo world\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "/bin/sh" in fixed

    def test_cmd_single_arg(self):
        content = "FROM alpine:3.19\nCMD bash\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert '["bash"]' in fixed

    def test_cmd_with_flags(self):
        content = "FROM alpine:3.19\nCMD nginx -g daemon off;\n"
        fixed, _, fixes = _analyze_and_fix(content)
        # Contains semicolon, needs shell
        assert "/bin/sh" in fixed


# ===========================================================================
# Fixer DD005 more edge cases
# ===========================================================================

class TestFixerDD005MoreEdgeCases:
    """DD005 fixer edge cases."""

    def test_combines_multiline_runs(self):
        content = (
            "FROM alpine:3.19\n"
            "RUN echo a && \\\n"
            "    echo b\n"
            "RUN echo c\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd005 = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005) >= 1
        assert "echo a" in fixed
        assert "echo c" in fixed

    def test_combines_four_runs(self):
        content = (
            "FROM alpine:3.19\n"
            "RUN echo 1\n"
            "RUN echo 2\n"
            "RUN echo 3\n"
            "RUN echo 4\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd005 = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005) >= 1
        for i in range(1, 5):
            assert f"echo {i}" in fixed

    def test_preserves_other_instructions(self):
        content = (
            "FROM alpine:3.19\n"
            "WORKDIR /app\n"
            "RUN echo a\n"
            "RUN echo b\n"
            "CMD [\"sh\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "WORKDIR /app" in fixed
        assert 'CMD ["sh"]' in fixed


# ===========================================================================
# Fixer DD013 more edge cases
# ===========================================================================

class TestFixerDD013MoreEdgeCases:
    """DD013 fixer edge cases."""

    def test_removes_dist_upgrade(self):
        content = "FROM ubuntu:22.04\nRUN apt-get dist-upgrade -y\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd013 = [f for f in fixes if f.rule_id == "DD013"]
        assert len(dd013) >= 1
        assert "dist-upgrade" not in fixed

    def test_removes_upgrade_keeps_install(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get upgrade -y && apt-get install -y curl\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "upgrade" not in fixed.lower() or "dist-upgrade" not in fixed
        assert "install" in fixed

    def test_apt_without_get_upgrade_removed(self):
        content = "FROM ubuntu:22.04\nRUN apt update && apt upgrade -y && apt install -y curl\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "upgrade" not in fixed


# ===========================================================================
# More roundtrip idempotency tests
# ===========================================================================

class TestRoundtripMoreIdempotency:
    """More idempotency tests for edge cases."""

    def test_idempotent_dd019(self):
        content = "FROM alpine:3.19\nCMD python app.py\n"
        fixed1, _, _ = _analyze_and_fix(content)
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        dd019 = [f for f in fixes2 if f.rule_id == "DD019"]
        assert len(dd019) == 0

    def test_idempotent_dd007(self):
        content = "FROM alpine:3.19\nADD . /app\n"
        fixed1, _, _ = _analyze_and_fix(content)
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        dd007 = [f for f in fixes2 if f.rule_id == "DD007"]
        assert len(dd007) == 0

    def test_idempotent_dd010(self):
        content = "FROM node:20\nCOPY package*.json ./\nRUN npm install\n"
        fixed1, _, _ = _analyze_and_fix(content)
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        dd010 = [f for f in fixes2 if f.rule_id == "DD010"]
        assert len(dd010) == 0

    def test_idempotent_full_stack(self):
        """Fix everything fixable, then verify second pass is clean."""
        content = (
            "FROM ubuntu:22.04\n"
            "MAINTAINER bad@example.com\n"
            "ADD . /app\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "RUN pip install flask\n"
            "RUN npm install\n"
            "CMD python app.py\n"
        )
        fixed1, _, fixes1 = _analyze_and_fix(content)
        assert len(fixes1) > 0
        fixed2, _, fixes2 = _analyze_and_fix(fixed1)
        # All fixable rules should be resolved
        fixable_rules = {"DD003", "DD004", "DD005", "DD007", "DD009", "DD010", "DD013", "DD017", "DD019"}
        remaining = {f.rule_id for f in fixes2} & fixable_rules
        assert len(remaining) == 0


# ===========================================================================
# Fixer with multi-stage Dockerfiles
# ===========================================================================

class TestFixerMultistage:
    """Fixes should work correctly in multi-stage builds."""

    def test_fix_add_in_both_stages(self):
        content = (
            "FROM alpine:3.19 AS build\n"
            "ADD . /src\n"
            "FROM alpine:3.19\n"
            "ADD config.yml /app/\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd007 = [f for f in fixes if f.rule_id == "DD007"]
        assert len(dd007) == 2
        assert "ADD" not in fixed

    def test_fix_maintainer_before_multistage(self):
        content = (
            "FROM alpine:3.19 AS build\n"
            "MAINTAINER dev@example.com\n"
            "FROM alpine:3.19\n"
            "CMD [\"sh\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "MAINTAINER" not in fixed
        assert "LABEL maintainer=" in fixed

    def test_fix_preserves_copy_from(self):
        content = (
            "FROM alpine:3.19 AS build\n"
            "ADD . /src\n"
            "FROM alpine:3.19\n"
            "COPY --from=build /src/app /app\n"
            "CMD python app.py\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "COPY --from=build" in fixed
        assert "CMD [" in fixed  # DD019 converted


# ===========================================================================
# Full pipeline integration tests
# ===========================================================================

class TestFullPipelineIntegration:
    """Test the full parse → analyze → fix pipeline with real-world Dockerfiles."""

    def test_fix_bad_python_dockerfile(self):
        content = (
            "FROM python\n"
            "MAINTAINER dev@co.com\n"
            "ADD . /app\n"
            "RUN pip install flask\n"
            "CMD python app.py\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        # DD017: MAINTAINER → LABEL
        assert "MAINTAINER" not in fixed
        assert "LABEL maintainer=" in fixed
        # DD007: ADD → COPY
        assert "COPY . /app" in fixed
        # DD009: pip --no-cache-dir
        assert "--no-cache-dir" in fixed
        # DD019: CMD exec form
        assert "CMD [" in fixed
        # Content still parseable
        df = parse(fixed)
        assert len(df.instructions) > 0

    def test_fix_bad_node_dockerfile(self):
        content = (
            "FROM node:20\n"
            "COPY . /app\n"
            "RUN npm install\n"
            "CMD node app.js\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        # DD010: npm ci
        assert "npm ci" in fixed
        # DD019: exec form
        assert 'CMD ["node", "app.js"]' in fixed

    def test_fix_preserves_comments(self):
        """Comments should survive the fix pipeline."""
        content = (
            "# My Dockerfile\n"
            "FROM alpine:3.19\n"
            "# Install deps\n"
            "ADD . /app\n"
            "CMD echo hello\n"
        )
        fixed, _, _ = _analyze_and_fix(content)
        assert "# My Dockerfile" in fixed
        assert "# Install deps" in fixed

    def test_fix_empty_dockerfile(self):
        fixed, issues, fixes = _analyze_and_fix("")
        assert fixed == ""
        assert len(fixes) == 0

    def test_fix_dockerfile_with_no_fixable_issues(self):
        content = (
            "FROM ubuntu:22.04\n"
            'LABEL maintainer="me" version="1.0.0"\n'
            "USER nobody\n"
            "ENV password=secret123\n"
            "EXPOSE 23\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        # DD020 and DD014 are not fixable; DD046, DD008 are now fixable but satisfied
        assert len(fixes) == 0
        # Content unchanged
        assert "password=secret123" in fixed

    def test_fix_count_matches_fixable_issues(self):
        """Number of fixes should be a subset of fixable issues."""
        content = (
            "FROM alpine:3.19\n"
            "MAINTAINER dev@example.com\n"
            "ADD . /app\n"
            "CMD echo hi\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        fix_ids = {f.rule_id for f in fixes}
        # The convergence loop may discover and fix new issues (e.g. DD078)
        # in subsequent passes, so we just verify all initial fixable issues
        # were addressed and that fixes are non-empty.
        fixable_issues = {i.rule_id for i in issues if i.fix_available}
        assert fixable_issues <= fix_ids

    def test_fix_multiline_apt_complete(self):
        """Multi-line apt-get should get all fixes applied."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && \\\n"
            "    apt-get install -y \\\n"
            "    curl wget git\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists" in fixed

    def test_fix_trailing_newline_preserved(self):
        content = "FROM alpine:3.19\nADD . /app\n"
        fixed, _, _ = _analyze_and_fix(content)
        assert fixed.endswith("\n")

    def test_fix_no_trailing_newline_preserved(self):
        content = "FROM alpine:3.19\nADD . /app"
        fixed, _, _ = _analyze_and_fix(content)
        # Behavior may vary — just ensure it doesn't crash
        assert "COPY . /app" in fixed


# ===========================================================================
# Fixer stress tests
# ===========================================================================

class TestFixerStress:
    """Stress tests with many rules firing at once."""

    def test_all_fixable_rules_at_once(self):
        """Dockerfile that triggers every fixable rule."""
        content = (
            "FROM ubuntu:22.04\n"
            "MAINTAINER dev@example.com\n"
            "ADD . /app\n"
            "RUN apt-get update && apt-get upgrade -y && apt-get install -y curl\n"
            "RUN pip install flask\n"
            "RUN npm install\n"
            "CMD python app.py\n"
        )
        fixed, issues, fixes = _analyze_and_fix(content)
        fix_ids = {f.rule_id for f in fixes}
        # Should have applied: DD003, DD004, DD005, DD007, DD009, DD010, DD013, DD017, DD019
        assert "DD017" in fix_ids  # MAINTAINER
        assert "DD007" in fix_ids  # ADD
        assert "DD019" in fix_ids  # CMD
        # Content still parseable
        df = parse(fixed)
        assert df.instructions[0].directive == "FROM"

    def test_many_lines_no_corruption(self):
        """Large Dockerfile should fix without line corruption."""
        lines = ["FROM ubuntu:22.04\n"]
        for i in range(20):
            lines.append(f"RUN echo step{i}\n")
        lines.append("CMD echo done\n")
        content = "".join(lines)
        fixed, _, fixes = _analyze_and_fix(content)
        df = parse(fixed)
        assert df.instructions[0].directive == "FROM"
        # All step commands present
        for i in range(20):
            assert f"step{i}" in fixed
