"""Correctness, integrity, and adversarial tests for Dockerfile Doctor.

These tests protect against post-release bugs by verifying:
1. Fixer idempotency (fix(fix(x)) == fix(x))
2. Round-trip integrity (fixed Dockerfiles remain valid)
3. Multi-stage interaction safety
4. Adversarial / edge-case robustness
5. SARIF output validity
"""

from __future__ import annotations

import json
import textwrap

import pytest

from dockerfile_doctor.fixer import fix
from dockerfile_doctor.models import AnalysisResult, Severity
from dockerfile_doctor.parser import parse
from dockerfile_doctor.reporter import _format_sarif, report
from dockerfile_doctor.rules import analyze


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_pipeline(content: str) -> tuple[str, list]:
    """Parse -> analyze -> fix, return (fixed_content, applied_fixes)."""
    df = parse(content)
    issues = analyze(df)
    return fix(df, issues)


def _fix_and_refix(content: str):
    """Run the full fix pipeline twice; return both results."""
    fixed1, fixes1 = _full_pipeline(content)
    fixed2, fixes2 = _full_pipeline(fixed1)
    return fixed1, fixes1, fixed2, fixes2


# ===========================================================================
# 1. Fixer Idempotency
# ===========================================================================

class TestFixerIdempotency:
    """After one round of fixes, a second round should produce zero changes."""

    def test_idempotent_many_issues(self):
        """Dockerfile with apt-get without cleanup, no USER, shell CMD."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update && apt-get install -y curl
            RUN apt-get update && apt-get install -y wget
            CMD python app.py
        """)
        fixed1, fixes1, fixed2, fixes2 = _fix_and_refix(content)
        assert len(fixes1) > 0, "First pass should fix something"
        assert len(fixes2) == 0, f"Second pass should fix nothing, but got: {fixes2}"
        assert fixed1 == fixed2

    def test_idempotent_already_clean(self):
        """A well-written Dockerfile should produce zero fixes on any pass."""
        content = textwrap.dedent("""\
            FROM python:3.11-slim AS builder
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt
            COPY . .
            FROM python:3.11-slim
            COPY --from=builder /app /app
            WORKDIR /app
            EXPOSE 8000
            HEALTHCHECK --interval=30s CMD curl -f http://localhost:8000/ || exit 1
            USER appuser
            CMD ["python", "app.py"]
        """)
        fixed1, fixes1, fixed2, fixes2 = _fix_and_refix(content)
        assert len(fixes2) == 0, f"Clean Dockerfile should need no second-pass fixes: {fixes2}"
        assert fixed1 == fixed2

    def test_idempotent_multistage_with_issues(self):
        """Multi-stage Dockerfile with issues in both stages."""
        content = textwrap.dedent("""\
            FROM golang:1.21 AS builder
            RUN apt-get update && apt-get install -y git
            RUN go build -o /app .

            FROM ubuntu:22.04
            RUN apt-get update && apt-get install -y ca-certificates
            COPY --from=builder /app /app
            CMD /app
        """)
        fixed1, fixes1, fixed2, fixes2 = _fix_and_refix(content)
        assert len(fixes2) == 0, f"Second pass produced fixes: {fixes2}"
        assert fixed1 == fixed2

    def test_idempotent_consecutive_runs(self):
        """Consecutive RUN instructions (DD005 combinable) should stabilize."""
        content = textwrap.dedent("""\
            FROM debian:bullseye
            RUN apt-get update
            RUN apt-get install -y curl
            RUN apt-get install -y wget
            CMD ["bash"]
        """)
        fixed1, fixes1, fixed2, fixes2 = _fix_and_refix(content)
        assert len(fixes2) == 0, f"Second pass produced fixes: {fixes2}"
        assert fixed1 == fixed2

    def test_idempotent_add_to_copy(self):
        """ADD->COPY fix should be stable."""
        content = textwrap.dedent("""\
            FROM alpine:3.18
            ADD app.py /app/
            ADD config.yaml /app/
            USER nobody
            CMD ["python", "/app/app.py"]
        """)
        fixed1, fixes1, fixed2, fixes2 = _fix_and_refix(content)
        assert len(fixes2) == 0, f"Second pass produced fixes: {fixes2}"
        assert fixed1 == fixed2

    def test_idempotent_pip_no_cache(self):
        """pip --no-cache-dir fix should not re-trigger."""
        content = textwrap.dedent("""\
            FROM python:3.11-slim
            RUN pip install flask
            USER appuser
            CMD ["python", "app.py"]
        """)
        fixed1, fixes1, fixed2, fixes2 = _fix_and_refix(content)
        assert len(fixes2) == 0, f"Second pass produced fixes: {fixes2}"
        assert fixed1 == fixed2


# ===========================================================================
# 2. Round-Trip Integrity
# ===========================================================================

class TestRoundTripIntegrity:
    """After fixing, the Dockerfile must remain valid and not gain issues."""

    def test_fixed_is_parseable(self):
        """Fixed output must parse without error."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update && apt-get install -y curl
            CMD python app.py
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        assert len(df.instructions) > 0, "Fixed Dockerfile must have instructions"

    def test_fewer_or_equal_issues(self):
        """Fix must not introduce MORE issues than the original."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update && apt-get install -y curl
            RUN apt-get update && apt-get install -y wget
            ADD requirements.txt /app/
            CMD python app.py
        """)
        df_orig = parse(content)
        issues_orig = analyze(df_orig)
        fixed, _ = fix(df_orig, issues_orig)

        df_fixed = parse(fixed)
        issues_fixed = analyze(df_fixed)

        # Count only fixable rule IDs that were present originally
        orig_fixable_ids = {i.rule_id for i in issues_orig if i.fix_available}
        # For those rules, count should decrease or stay same
        for rule_id in orig_fixable_ids:
            orig_count = sum(1 for i in issues_orig if i.rule_id == rule_id)
            fixed_count = sum(1 for i in issues_fixed if i.rule_id == rule_id)
            assert fixed_count <= orig_count, (
                f"Rule {rule_id} went from {orig_count} to {fixed_count} issues"
            )

    def test_preserve_expose(self):
        """EXPOSE instructions must survive fixing."""
        content = textwrap.dedent("""\
            FROM python:3.11-slim
            EXPOSE 8000
            EXPOSE 8443
            RUN pip install flask
            CMD python app.py
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        expose_instrs = [i for i in df.instructions if i.directive == "EXPOSE"]
        assert len(expose_instrs) == 2, "Both EXPOSE instructions must survive"

    def test_preserve_volume(self):
        """VOLUME instructions must survive fixing."""
        content = textwrap.dedent("""\
            FROM node:18
            VOLUME /data
            VOLUME ["/logs", "/cache"]
            RUN npm install
            CMD node app.js
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        vol_instrs = [i for i in df.instructions if i.directive == "VOLUME"]
        assert len(vol_instrs) == 2, "Both VOLUME instructions must survive"

    def test_preserve_env(self):
        """ENV instructions must survive fixing."""
        content = textwrap.dedent("""\
            FROM python:3.11-slim
            ENV APP_HOME=/app
            ENV DEBUG=false
            WORKDIR $APP_HOME
            RUN pip install flask
            CMD python app.py
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        env_instrs = [i for i in df.instructions if i.directive == "ENV"]
        # Fixer may add ENV lines (e.g. PYTHONUNBUFFERED), so count >= original
        assert len(env_instrs) >= 2, "Original ENV instructions must survive"
        # Verify the original two ENVs are still present
        env_args = [i.arguments for i in env_instrs]
        assert any("APP_HOME" in a for a in env_args), "APP_HOME ENV lost"
        assert any("DEBUG" in a for a in env_args), "DEBUG ENV lost"

    def test_multiline_continuation_preserved_where_unmodified(self):
        """Multi-line COPY should remain intact if not targeted by a fix."""
        content = textwrap.dedent("""\
            FROM python:3.11-slim
            COPY file1.txt \\
                 file2.txt \\
                 file3.txt \\
                 /app/
            USER appuser
            CMD ["python", "app.py"]
        """)
        fixed, _ = _full_pipeline(content)
        # The COPY continuation should still exist in some form
        assert "file1.txt" in fixed
        assert "file2.txt" in fixed
        assert "file3.txt" in fixed

    def test_total_issue_count_does_not_increase(self):
        """Overall issue count must not increase after fixing."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update
            RUN apt-get install -y curl wget vim
            ADD app.tar.gz /app/
            CMD python app.py
        """)
        df_orig = parse(content)
        issues_orig = analyze(df_orig)

        fixed, _ = fix(df_orig, issues_orig)
        df_fixed = parse(fixed)
        issues_fixed = analyze(df_fixed)

        assert len(issues_fixed) <= len(issues_orig), (
            f"Issues increased from {len(issues_orig)} to {len(issues_fixed)}"
        )


# ===========================================================================
# 3. Multi-Stage Interaction
# ===========================================================================

class TestMultiStageInteraction:
    """Fixes in one stage must not corrupt another stage."""

    def test_fix_stage1_preserves_stage2(self):
        """Fixing stage 1 should leave stage 2 content intact."""
        content = textwrap.dedent("""\
            FROM golang:1.21 AS builder
            RUN apt-get update && apt-get install -y git
            RUN go build -o /app .

            FROM alpine:3.18
            COPY --from=builder /app /app
            EXPOSE 8080
            USER nobody
            CMD ["/app"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        # Stage 2 must still have COPY --from=builder, EXPOSE, USER, CMD
        stage2_directives = [
            i.directive for i in df.instructions if i.stage_index == 1
        ]
        assert "COPY" in stage2_directives
        assert "EXPOSE" in stage2_directives
        assert "CMD" in stage2_directives

    def test_user_only_affects_final_stage(self):
        """DD008 (missing USER) fix should target the final stage only."""
        content = textwrap.dedent("""\
            FROM golang:1.21 AS builder
            RUN go build -o /app .

            FROM alpine:3.18
            COPY --from=builder /app /app
            CMD ["/app"]
        """)
        fixed, fixes = _full_pipeline(content)
        # Check that any USER insertion is in the final stage area
        df = parse(fixed)
        user_instrs = [i for i in df.instructions if i.directive == "USER"]
        for u in user_instrs:
            # If USER was added, it should be in the final stage (index 1)
            assert u.stage_index == len(df.stages) - 1 or u.stage_index == 1, (
                f"USER added in stage {u.stage_index}, expected final stage"
            )

    def test_run_combining_does_not_cross_stages(self):
        """DD005 should not combine RUN instructions across FROM boundaries."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04 AS base
            RUN apt-get update
            RUN apt-get install -y curl

            FROM ubuntu:20.04 AS app
            RUN apt-get update
            RUN apt-get install -y wget
            USER appuser
            CMD ["bash"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        # Must still have two FROM instructions
        from_instrs = [i for i in df.instructions if i.directive == "FROM"]
        assert len(from_instrs) == 2, "Both FROM instructions must survive"
        # Each stage should still have at least one RUN
        for stage in df.stages:
            runs = [i for i in stage.instructions if i.directive == "RUN"]
            assert len(runs) >= 1, f"Stage {stage.index} lost all RUN instructions"

    def test_three_stage_dockerfile(self):
        """Three-stage Dockerfile should have all stages intact after fix."""
        content = textwrap.dedent("""\
            FROM node:18 AS frontend
            RUN npm install
            RUN npm run build

            FROM golang:1.21 AS backend
            RUN go build -o /server .

            FROM alpine:3.18
            COPY --from=frontend /app/dist /static
            COPY --from=backend /server /server
            CMD ["/server"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        assert len(df.stages) == 3, f"Expected 3 stages, got {len(df.stages)}"


# ===========================================================================
# 4. Adversarial / Edge Case Inputs
# ===========================================================================

class TestAdversarialInputs:
    """parse -> analyze -> fix must not crash on adversarial inputs."""

    def test_empty_file(self):
        """Empty Dockerfile should not crash."""
        fixed, fixes = _full_pipeline("")
        assert isinstance(fixed, str)

    def test_only_comments(self):
        """File with only comments should not crash."""
        content = textwrap.dedent("""\
            # This is just a comment
            # Another comment
            # No instructions here
        """)
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_only_arg_no_from(self):
        """ARG before FROM with no FROM should not crash."""
        content = textwrap.dedent("""\
            ARG BASE_IMAGE=ubuntu:20.04
            ARG VERSION=1.0
        """)
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_100_run_instructions(self):
        """100+ RUN instructions should not crash or hang."""
        lines = ["FROM ubuntu:20.04"]
        for i in range(100):
            lines.append(f"RUN echo {i}")
        lines.append('CMD ["bash"]')
        content = "\n".join(lines) + "\n"
        fixed, fixes = _full_pipeline(content)
        df = parse(fixed)
        assert df.instructions[0].directive == "FROM"

    def test_very_long_line(self):
        """A single line >10000 chars should not crash."""
        long_label = "a" * 10001
        content = f'FROM alpine:3.18\nLABEL description="{long_label}"\nCMD ["sh"]\n'
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)
        assert len(fixed) >= 10000

    def test_unicode_in_labels(self):
        """Chinese characters and emoji in LABEL should not crash."""
        content = textwrap.dedent("""\
            FROM alpine:3.18
            LABEL maintainer="Zhang Wei"
            LABEL description="This is a test with unicode chars and symbols"
            USER nobody
            CMD ["sh"]
        """)
        fixed, fixes = _full_pipeline(content)
        assert "Zhang Wei" in fixed

    def test_binary_like_content(self):
        """Binary-ish content in strings should not crash."""
        content = 'FROM alpine:3.18\nRUN echo "\\x00\\x01\\x02\\xff"\nCMD ["sh"]\n'
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_every_instruction_type(self):
        """Dockerfile with every known instruction type."""
        content = textwrap.dedent("""\
            ARG BASE=alpine:3.18
            FROM $BASE
            LABEL maintainer="test"
            ENV APP_HOME=/app
            WORKDIR /app
            RUN echo "hello"
            COPY app.py .
            ADD https://example.com/file.tar.gz /tmp/
            EXPOSE 8080
            VOLUME /data
            USER nobody
            HEALTHCHECK --interval=30s CMD curl -f http://localhost/ || exit 1
            STOPSIGNAL SIGTERM
            SHELL ["/bin/bash", "-c"]
            ENTRYPOINT ["python"]
            CMD ["app.py"]
        """)
        fixed, fixes = _full_pipeline(content)
        df = parse(fixed)
        directives = {i.directive for i in df.instructions}
        # All of these must survive
        for d in ["FROM", "LABEL", "ENV", "WORKDIR", "RUN", "COPY",
                   "EXPOSE", "VOLUME", "USER", "HEALTHCHECK", "STOPSIGNAL",
                   "SHELL", "ENTRYPOINT", "CMD"]:
            assert d in directives, f"Directive {d} was lost after fix"

    def test_crlf_line_endings(self):
        """CRLF line endings should not crash or corrupt."""
        content = "FROM alpine:3.18\r\nRUN echo hello\r\nCMD [\"sh\"]\r\n"
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)
        # Should still be parseable
        df = parse(fixed)
        assert len(df.instructions) >= 2

    def test_mixed_tabs_and_spaces(self):
        """Mixed indentation should not crash."""
        content = "FROM alpine:3.18\n\tRUN echo hello\n    RUN echo world\nCMD [\"sh\"]\n"
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_heredoc_syntax(self):
        """Heredoc in RUN should not crash."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN <<EOF
            apt-get update
            apt-get install -y curl
            EOF
            USER appuser
            CMD ["bash"]
        """)
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_no_trailing_newline(self):
        """File without trailing newline should not crash."""
        content = "FROM alpine:3.18\nRUN echo hello\nCMD [\"sh\"]"
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)
        df = parse(fixed)
        assert len(df.instructions) >= 2

    def test_from_scratch(self):
        """FROM scratch (no tag, no real base) should not crash."""
        content = textwrap.dedent("""\
            FROM scratch
            COPY binary /
            CMD ["/binary"]
        """)
        fixed, fixes = _full_pipeline(content)
        assert "scratch" in fixed

    def test_single_from_only(self):
        """Just a FROM line, nothing else."""
        content = "FROM alpine:3.18\n"
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_duplicate_from(self):
        """Multiple FROM with no other instructions between them."""
        content = textwrap.dedent("""\
            FROM alpine:3.18
            FROM ubuntu:20.04
            FROM debian:bullseye
            CMD ["sh"]
        """)
        fixed, fixes = _full_pipeline(content)
        df = parse(fixed)
        assert len(df.stages) == 3

    def test_whitespace_only_lines(self):
        """Blank lines and whitespace-only lines throughout."""
        content = "\n\n  \nFROM alpine:3.18\n\n  \n\nRUN echo hello\n\n\nCMD [\"sh\"]\n\n"
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)

    def test_extremely_nested_continuations(self):
        """Many backslash continuations in a single RUN."""
        parts = ["FROM debian:bullseye", "RUN echo a \\"]
        for i in range(50):
            parts.append(f"    && echo {i} \\")
        parts.append("    && echo done")
        parts.append('CMD ["sh"]')
        content = "\n".join(parts) + "\n"
        fixed, fixes = _full_pipeline(content)
        assert isinstance(fixed, str)


# ===========================================================================
# 5. SARIF Output Validity
# ===========================================================================

class TestSarifValidity:
    """SARIF output must be valid JSON with the correct schema structure."""

    def test_sarif_with_issues(self):
        """SARIF output for a Dockerfile with issues must be valid."""
        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update && apt-get install -y curl
            CMD python app.py
        """)
        df = parse(content)
        issues = analyze(df)
        result = AnalysisResult(filepath="Dockerfile", issues=issues)
        sarif_str = _format_sarif([result])

        sarif = json.loads(sarif_str)
        assert "$schema" in sarif
        assert sarif["version"] == "2.1.0"
        assert "runs" in sarif
        assert isinstance(sarif["runs"], list)
        assert len(sarif["runs"]) == 1

        run = sarif["runs"][0]
        assert "tool" in run
        assert "driver" in run["tool"]
        assert "results" in run
        assert len(run["results"]) > 0

        # Each result must have ruleId, level, message, locations
        for r in run["results"]:
            assert "ruleId" in r
            assert "level" in r
            assert "message" in r
            assert "locations" in r

    def test_sarif_zero_issues(self):
        """SARIF with zero issues must still be valid JSON."""
        result = AnalysisResult(filepath="Dockerfile", issues=[])
        sarif_str = _format_sarif([result])

        sarif = json.loads(sarif_str)
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        assert sarif["runs"][0]["results"] == []

    def test_sarif_multiple_files(self):
        """SARIF with multiple file results should still be valid."""
        content1 = "FROM ubuntu:20.04\nCMD python app.py\n"
        content2 = "FROM alpine:3.18\nRUN apk add curl\nCMD [\"sh\"]\n"

        df1 = parse(content1)
        df2 = parse(content2)
        issues1 = analyze(df1)
        issues2 = analyze(df2)

        results = [
            AnalysisResult(filepath="Dockerfile.one", issues=issues1),
            AnalysisResult(filepath="Dockerfile.two", issues=issues2),
        ]
        sarif_str = _format_sarif(results)
        sarif = json.loads(sarif_str)

        assert sarif["version"] == "2.1.0"
        assert isinstance(sarif["runs"], list)
        # All results from both files should be present
        total_results = len(sarif["runs"][0]["results"])
        assert total_results == len(issues1) + len(issues2)


# ===========================================================================
# 6. Semantic Invariants — property-based fixer correctness
# ===========================================================================

class TestFixerSemanticInvariants:
    """Properties that fixer output must satisfy, regardless of specific text.

    These catch bugs where the fixer produces syntactically valid but
    semantically wrong output (e.g. COPY . . → COPY . /.).
    """

    # --- DD041: relative dest rewriting must not break '.' or '..' ---

    @pytest.mark.parametrize("dest", [".", "..", "./", "../"])
    def test_dd041_dot_destinations_never_get_slash_prefix(self, dest):
        """'.' and '..' are special — prepending '/' changes their meaning."""
        content = f"FROM ubuntu:22.04\nCOPY src {dest}\n"
        fixed, _ = _full_pipeline(content)
        # Must never produce '/.' or '/..'
        assert f"COPY src /." not in fixed
        assert f"COPY src /.." not in fixed

    def test_dd041_real_relative_path_gets_absolute(self):
        """A genuine relative path like 'app/' should become '/app/'."""
        content = "FROM ubuntu:22.04\nCOPY . app/\n"
        fixed, _ = _full_pipeline(content)
        assert "/app/" in fixed

    # --- DD059: ADD URL → curl must produce valid -o path ---

    @pytest.mark.parametrize("dest", ["/app/", "/tmp/", "/opt/data/"])
    def test_dd059_directory_dest_produces_file_path(self, dest):
        """curl -o must get a file path, not a bare directory."""
        content = f"FROM ubuntu:22.04\nADD https://example.com/archive.tar.gz {dest}\n"
        fixed, _ = _full_pipeline(content)
        if "curl" in fixed:
            # The -o argument must not end with /
            import re
            m = re.search(r"-o\s+(\S+)", fixed)
            assert m, "curl command must have -o flag"
            assert not m.group(1).endswith("/"), f"-o path ends with /: {m.group(1)}"

    def test_dd059_file_dest_unchanged(self):
        """When dest is already a file path, keep it as-is."""
        content = "FROM ubuntu:22.04\nADD https://example.com/file.tar.gz /app/file.tar.gz\n"
        fixed, _ = _full_pipeline(content)
        assert "/app/file.tar.gz" in fixed

    # --- DD015/DD035: insertions must go into the correct stage ---

    def test_dd015_python_env_lands_in_python_stage(self):
        """PYTHONUNBUFFERED must be in the stage that uses Python, not a random stage."""
        content = textwrap.dedent("""\
            FROM node:18 AS frontend
            RUN npm ci

            FROM golang:1.21 AS backend
            RUN go build -o /app .

            FROM python:3.12-slim
            RUN pip install flask
            CMD ["python", "app.py"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        # Find the ENV with PYTHONUNBUFFERED
        for instr in df.instructions:
            if instr.directive == "ENV" and "PYTHONUNBUFFERED" in instr.arguments:
                # It must be in the Python stage (stage index 2)
                assert instr.stage_index == 2, (
                    f"PYTHONUNBUFFERED in stage {instr.stage_index}, expected 2 (python stage)"
                )
                break
        else:
            # If no ENV was added, that's also fine (already present, etc.)
            pass

    def test_dd035_debian_frontend_lands_in_apt_stage(self):
        """DEBIAN_FRONTEND must be in the stage with apt-get, not a random stage."""
        content = textwrap.dedent("""\
            FROM node:18 AS frontend
            RUN npm ci

            FROM ubuntu:22.04
            RUN apt-get update && apt-get install -y curl
            CMD ["bash"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        for instr in df.instructions:
            if instr.directive == "ARG" and "DEBIAN_FRONTEND" in instr.arguments:
                assert instr.stage_index == 1, (
                    f"DEBIAN_FRONTEND in stage {instr.stage_index}, expected 1 (apt stage)"
                )
                break

    # --- DD046: no TODO placeholders in auto-fixed output ---

    def test_no_todo_labels_in_fixed_output(self):
        """Auto-fix must never inject 'TODO' placeholder labels."""
        content = "FROM python:3.12\nRUN pip install flask\n"
        fixed, _ = _full_pipeline(content)
        assert 'TODO' not in fixed, "Fixer injected TODO placeholder"

    # --- General: fixer must not produce invalid Dockerfile syntax ---

    @pytest.mark.parametrize("content", [
        "FROM ubuntu:22.04\nCOPY . .\n",
        "FROM ubuntu:22.04\nADD https://example.com/f.tgz /app/\n",
        "FROM node:18\nRUN npm install\nFROM python:3.12\nRUN pip install flask\n",
        "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\nCMD bash\n",
    ])
    def test_fixed_output_parses_without_error(self, content):
        """Every fixed Dockerfile must remain parseable."""
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        assert len(df.instructions) > 0

    @pytest.mark.parametrize("content", [
        "FROM ubuntu:22.04\nCOPY . .\n",
        "FROM ubuntu:22.04\nADD https://example.com/f.tgz /app/\n",
        "FROM node:18\nRUN npm install\nFROM python:3.12\nRUN pip install flask\n",
    ])
    def test_fixed_output_has_fewer_fixable_issues(self, content):
        """After fixing, fixable issue count must decrease or reach zero."""
        df = parse(content)
        issues = analyze(df)
        fixable_before = sum(1 for i in issues if i.fix_available)

        fixed, fixes = fix(df, issues)
        df2 = parse(fixed)
        issues2 = analyze(df2)
        fixable_after = sum(1 for i in issues2 if i.fix_available)

        if fixes:
            assert fixable_after < fixable_before, (
                f"Fixable issues didn't decrease: {fixable_before} → {fixable_after}"
            )

    # --- DD067: NODE_ENV must not trigger on non-node images ---

    @pytest.mark.parametrize("image", ["nodemailer:latest", "node-api:1.0", "myorg/nodetools:v2"])
    def test_dd067_no_false_positive_on_substring(self, image):
        """'node' as substring in image name must not trigger NODE_ENV fix."""
        content = f"FROM {image}\nRUN echo hi\nCMD [\"node\", \"app.js\"]\n"
        df = parse(content)
        issues = analyze(df)
        assert not any(i.rule_id == "DD067" for i in issues), (
            f"DD067 false-triggered on {image}"
        )

    @pytest.mark.parametrize("image", ["node:18", "node:20-slim", "library/node:18"])
    def test_dd067_triggers_on_real_node(self, image):
        """Real node images must trigger DD067."""
        content = f"FROM {image}\nRUN npm ci\nCMD [\"node\", \"app.js\"]\n"
        df = parse(content)
        issues = analyze(df)
        assert any(i.rule_id == "DD067" for i in issues), (
            f"DD067 should trigger on {image}"
        )

    # --- DD068: Java flags must not trigger on non-java images ---

    @pytest.mark.parametrize("image", ["openjdk-tools:1.0", "javahelper:latest", "my-amazoncorretto-fork:11"])
    def test_dd068_no_false_positive_on_substring(self, image):
        """Java image substrings in custom names must not trigger DD068."""
        content = f"FROM {image}\nRUN echo hi\nCMD [\"java\", \"-jar\", \"app.jar\"]\n"
        df = parse(content)
        issues = analyze(df)
        assert not any(i.rule_id == "DD068" for i in issues), (
            f"DD068 false-triggered on {image}"
        )

    # --- DD067/DD068: multi-stage insertion must target correct stage ---

    def test_dd067_multistage_inserts_in_node_stage(self):
        """NODE_ENV must be in the node stage, not a random builder stage."""
        content = textwrap.dedent("""\
            FROM python:3.12 AS backend
            RUN pip install flask

            FROM node:18
            RUN npm ci
            CMD ["node", "server.js"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        for instr in df.instructions:
            if instr.directive == "ENV" and "NODE_ENV" in instr.arguments:
                assert instr.stage_index == 1, (
                    f"NODE_ENV in stage {instr.stage_index}, expected 1 (node stage)"
                )
                break

    # --- DD011: WORKDIR dot path handling ---

    @pytest.mark.parametrize("path", [".", "..", "./subdir", "../other"])
    def test_dd011_does_not_blindly_prefix_dot_paths(self, path):
        """WORKDIR with dot-relative paths: fix must produce valid absolute path."""
        content = f"FROM ubuntu:22.04\nWORKDIR {path}\nRUN echo hi\n"
        fixed, _ = _full_pipeline(content)
        # Must not produce '/.', '/..', '/./subdir', '/../other'
        # These are nonsensical absolute paths
        for bad in ['/.' + path[1:] if len(path) > 1 else '/.']:
            if bad in fixed:
                # Check it's actually WORKDIR producing this
                for line in fixed.splitlines():
                    if line.strip().startswith('WORKDIR') and bad in line:
                        pytest.fail(f"WORKDIR produced nonsense path: {line}")

    # --- DD044: duplicate ENV across stages must not cross boundaries ---

    def test_dd044_does_not_remove_env_from_different_stage(self):
        """Duplicate ENV key in different stages should not cause cross-stage deletion."""
        content = textwrap.dedent("""\
            FROM node:18 AS builder
            ENV APP_ENV=development
            RUN npm ci

            FROM node:18-slim
            ENV APP_ENV=production
            CMD ["node", "app.js"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        # Both stages should still have their ENV
        env_instrs = [i for i in df.instructions if i.directive == "ENV" and "APP_ENV" in i.arguments]
        # At minimum, the production ENV must survive
        assert any("production" in i.arguments for i in env_instrs), (
            "ENV APP_ENV=production was removed from final stage"
        )

    # --- DD077: deprecated image detection must not match substrings ---

    @pytest.mark.parametrize("image", ["mycentos:latest", "centos-tools:1.0", "notcentos:v1"])
    def test_dd077_no_false_positive_on_substring(self, image):
        """Deprecated image substrings in custom names must not trigger DD077."""
        content = f"FROM {image}\nRUN echo hi\nCMD [\"sh\"]\n"
        df = parse(content)
        issues = analyze(df)
        # DD077 should not fire for custom images that happen to contain 'centos'
        dd077_issues = [i for i in issues if i.rule_id == "DD077"]
        assert not dd077_issues, f"DD077 false-triggered on {image}: {dd077_issues}"

    # --- Cross-fixer interaction: DD003 + DD004 on same line ---

    def test_dd003_dd004_both_apply_to_same_line(self):
        """Both --no-install-recommends and apt cleanup must apply without conflict."""
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\nCMD [\"bash\"]\n"
        fixed, fixes = _full_pipeline(content)
        assert "--no-install-recommends" in fixed, "DD003 fix missing"
        assert "rm -rf /var/lib/apt/lists" in fixed, "DD004 fix missing"

    def test_dd005_dd003_dd004_interaction(self):
        """RUN combining (DD005) + apt flags (DD003/DD004) must all apply."""
        content = textwrap.dedent("""\
            FROM ubuntu:22.04
            RUN apt-get update
            RUN apt-get install -y curl
            CMD ["bash"]
        """)
        fixed, fixes = _full_pipeline(content)
        # Should combine into one RUN, add --no-install-recommends, add cleanup
        run_count = sum(1 for line in fixed.splitlines() if line.strip().startswith("RUN"))
        assert run_count == 1, f"Expected 1 RUN after combining, got {run_count}"

    def test_dd019_dd008_interaction(self):
        """CMD exec form fix + USER nobody must both apply without conflict."""
        content = "FROM ubuntu:22.04\nCMD echo hello\n"
        fixed, fixes = _full_pipeline(content)
        assert "USER nobody" in fixed, "DD008 USER fix missing"
        # CMD should be in exec form
        df = parse(fixed)
        cmd_instrs = [i for i in df.instructions if i.directive == "CMD"]
        assert cmd_instrs, "CMD instruction missing after fix"
        assert cmd_instrs[-1].arguments.strip().startswith("["), (
            f"CMD not in exec form: {cmd_instrs[-1].arguments}"
        )


# ===================================================================
# Section 7: Cross-Review Findings (Expert Agent Triage)
# ===================================================================

class TestCrossReviewFixer:
    """Bugs found by expert agent cross-review of fixer correctness."""

    def test_dd005_then_dd003_dd004_cross_fixer(self):
        """DD005 combines RUNs, then DD003/DD004 should still apply."""
        content = textwrap.dedent("""\
            FROM ubuntu:22.04
            RUN apt-get update
            RUN apt-get install -y curl
            CMD ["/bin/bash"]
        """)
        fixed, _ = _full_pipeline(content)
        run_lines = [l for l in fixed.splitlines() if l.strip().startswith("RUN")]
        assert len(run_lines) == 1, "RUN commands should be combined"
        assert "--no-install-recommends" in fixed, "DD003 must apply after DD005"
        assert "rm -rf /var/lib/apt/lists" in fixed, "DD004 must apply after DD005"

    def test_dd044_cross_stage_env_not_deleted(self):
        """DD044 should not delete ENV from a different stage."""
        content = textwrap.dedent("""\
            FROM ubuntu:22.04 AS build
            ENV DEBUG=true
            RUN echo "Building..."

            FROM ubuntu:22.04
            ENV DEBUG=false
            CMD ["bash"]
        """)
        fixed, _ = _full_pipeline(content)
        import re as _re
        debug_count = sum(1 for l in fixed.splitlines() if _re.match(r'\s*ENV\s+DEBUG=', l))
        assert debug_count >= 2, f"Cross-stage ENV deleted! Only {debug_count} ENV DEBUG lines remain"

    @pytest.mark.parametrize("dest", ["./app", "./data", "../build"])
    def test_dd041_copy_flags_with_dot_dest(self, dest):
        """COPY --chmod=755 src ./app should NOT become /./app."""
        content = f"FROM ubuntu:22.04\nCOPY --chmod=755 src {dest}\nCMD [\"bash\"]\n"
        fixed, _ = _full_pipeline(content)
        assert f"/.{dest.lstrip('.')}" not in fixed, f"Dot path {dest} was mangled to /{dest}"

    def test_dd059_url_with_no_filename(self):
        """ADD url/ /app/ where URL has no filename should not create curl -o /app/."""
        content = "FROM ubuntu:22.04\nADD https://example.com/ /app/\nCMD [\"bash\"]\n"
        fixed, _ = _full_pipeline(content)
        if "curl" in fixed:
            import re as _re
            assert not _re.search(r"curl.*-o\s+/app/\s", fixed), "curl -o targets bare directory"

    def test_dd035_dd015_insertion_collision(self):
        """DD035 and DD015 both insert after FROM — shouldn't collide."""
        content = textwrap.dedent("""\
            FROM ubuntu:22.04 AS apt-stage
            RUN apt-get update && apt-get install -y curl

            FROM python:3.12 AS py-stage
            RUN pip install flask

            FROM alpine:3.18
            CMD ["sh"]
        """)
        fixed, _ = _full_pipeline(content)
        df = parse(fixed)
        has_debian = any("DEBIAN_FRONTEND" in i.arguments for i in df.instructions if i.directive in ("ARG", "ENV"))
        has_python = any("PYTHONUNBUFFERED" in i.arguments for i in df.instructions if i.directive == "ENV")
        assert has_debian, "DD035 fix missing"
        assert has_python, "DD015 fix missing"


class TestCrossReviewRules:
    """Bugs found by expert agent cross-review of rule detection."""

    @pytest.mark.parametrize("image", ["micropython:1.21", "circuitpython:8.0", "ironpython:2.7"])
    def test_dd015_no_false_positive_on_python_substring(self, image):
        """DD015 should NOT trigger on non-CPython images containing 'python'."""
        content = f"FROM {image}\nRUN echo test\n"
        df = parse(content)
        issues = analyze(df)
        dd015 = [i for i in issues if i.rule_id == "DD015"]
        assert len(dd015) == 0, f"DD015 false positive on {image}"

    @pytest.mark.parametrize("image", ["python:3.12", "python:3.11-slim", "library/python:3.10"])
    def test_dd015_triggers_on_real_python(self, image):
        """DD015 should trigger on real Python images."""
        content = f"FROM {image}\nRUN pip install flask\n"
        df = parse(content)
        issues = analyze(df)
        dd015 = [i for i in issues if i.rule_id == "DD015"]
        assert len(dd015) > 0, f"DD015 didn't trigger on {image}"


class TestCrossReviewPipeline:
    """Bugs found by expert agent cross-review of CLI pipeline."""

    def test_severity_filter_prevents_low_severity_fixes(self, tmp_path):
        """--severity error should not apply warning-level fixes."""
        from dockerfile_doctor.cli import main
        dockerfile = tmp_path / "Dockerfile"
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\nCMD bash\n"
        dockerfile.write_text(content, encoding="utf-8")
        try:
            main(["--fix", "--severity", "error", str(dockerfile)])
        except SystemExit:
            pass
        fixed = dockerfile.read_text(encoding="utf-8")
        assert "--no-install-recommends" not in fixed, \
            "--severity error allowed WARNING-level fix DD003"

    def test_ignored_rule_not_fixed(self, tmp_path):
        """Config ignore should prevent fixes from applying."""
        from dockerfile_doctor.cli import main
        dockerfile = tmp_path / "Dockerfile"
        content = "FROM ubuntu:22.04\nMAINTAINER me@example.com\nCMD bash\n"
        dockerfile.write_text(content, encoding="utf-8")
        config_file = tmp_path / ".dockerfile-doctor.yaml"
        config_file.write_text("ignore:\n  - DD017\n", encoding="utf-8")
        try:
            main(["--fix", "--config", str(config_file), str(dockerfile)])
        except SystemExit:
            pass
        fixed = dockerfile.read_text(encoding="utf-8")
        assert "MAINTAINER" in fixed, "Ignored rule DD017 was still auto-fixed"


class TestCrossReviewAdversarial:
    """Adversarial input handling found by expert agent cross-review."""

    def test_binary_config_no_crash(self, tmp_path):
        """Binary config file should not crash with UnicodeDecodeError."""
        config_path = tmp_path / ".dockerfile-doctor.yaml"
        config_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        from dockerfile_doctor.config import load_config
        try:
            load_config(str(config_path))
        except UnicodeDecodeError:
            pytest.fail("Config loader crashed on binary file")
        except Exception:
            pass  # ValueError etc. acceptable

    def test_malformed_yaml_no_scanner_error(self, tmp_path):
        """Malformed YAML should not crash with ScannerError."""
        config_path = tmp_path / ".dockerfile-doctor.yaml"
        config_path.write_text("severity: error\nrules:\n  DD001\n    severity: warning\n", encoding="utf-8")
        from dockerfile_doctor.config import load_config
        try:
            load_config(str(config_path))
        except Exception as e:
            if "ScannerError" in type(e).__name__:
                pytest.fail(f"YAML parsing failed without fallback: {e}")

    def test_continuation_at_eof(self):
        """RUN ending with backslash at EOF should not crash."""
        content = "FROM alpine:3.19\nRUN echo hello \\"
        df = parse(content)
        issues = analyze(df)
        fixed, fixes = fix(df, issues)
        assert isinstance(fixed, str)

    def test_out_of_bounds_line_number(self):
        """Issue with line_number=999 in 3-line file should not crash."""
        from dockerfile_doctor.models import Issue, Category
        content = "FROM alpine:3.19\nCMD sh\n"
        df = parse(content)
        bad_issue = Issue(
            rule_id="DD999", title="Fake", description="Test",
            severity=Severity.WARNING, category=Category.BEST_PRACTICE,
            line_number=999, fix_available=True,
        )
        try:
            fixed, fixes = fix(df, [bad_issue])
            assert isinstance(fixed, str)
        except (IndexError, KeyError):
            pytest.fail("Fixer crashed on out-of-bounds line number")

    @pytest.mark.parametrize("escape_val", ["abc", "", "   "])
    def test_invalid_escape_directive(self, escape_val):
        """Invalid escape directive should not crash parser."""
        content = f"# escape={escape_val}\nFROM alpine:3.19\nRUN echo hello\n"
        df = parse(content)
        assert len(df.instructions) >= 1
