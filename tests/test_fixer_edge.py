"""Edge case tests for all 34 Dockerfile Doctor fixers."""
from __future__ import annotations

from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from dockerfile_doctor.fixer import fix
from dockerfile_doctor.models import Issue, Fix, Severity, Category


def _analyze_and_fix(content: str, *, unsafe: bool = True) -> tuple[str, list[Issue], list[Fix]]:
    df = parse(content)
    issues = analyze(df)
    fixed_content, fixes = fix(df, issues, unsafe=unsafe)
    return fixed_content, issues, fixes


# ===========================================================================
# 1. Fixer with multiline instructions (10+ tests)
# ===========================================================================

class TestFixerMultiline:
    """Test that fixers handle backslash continuation correctly."""

    def test_dd003_multiline_apt_install(self):
        """DD003 should add --no-install-recommends to multiline apt-get install."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && \\\n"
            "    apt-get install -y \\\n"
            "    curl \\\n"
            "    wget \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd003 = [f for f in fixes if f.rule_id == "DD003"]
        assert len(dd003) >= 1
        assert "--no-install-recommends" in fixed

    def test_dd004_multiline_missing_cleanup(self):
        """DD004 should append cleanup to multiline apt-get instruction."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && \\\n"
            "    apt-get install --no-install-recommends -y \\\n"
            "    curl wget\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd004 = [f for f in fixes if f.rule_id == "DD004"]
        assert len(dd004) >= 1
        assert "rm -rf /var/lib/apt/lists/*" in fixed

    def test_dd009_multiline_pip_install(self):
        """DD009 should add --no-cache-dir to multiline pip install."""
        content = (
            "FROM python:3.11\n"
            "RUN pip install \\\n"
            "    flask \\\n"
            "    requests \\\n"
            "    gunicorn\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd009 = [f for f in fixes if f.rule_id == "DD009"]
        assert len(dd009) >= 1
        assert "--no-cache-dir" in fixed

    def test_dd021_multiline_sudo(self):
        """DD021 should remove sudo from multiline RUN."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN sudo apt-get update && \\\n"
            "    sudo apt-get install -y curl \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd021 = [f for f in fixes if f.rule_id == "DD021"]
        assert len(dd021) >= 1
        assert "sudo" not in fixed

    def test_dd025_multiline_apk_add(self):
        """DD025 should add --no-cache to multiline apk add."""
        content = (
            "FROM alpine:3.19\n"
            "RUN apk add \\\n"
            "    curl \\\n"
            "    wget\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd025 = [f for f in fixes if f.rule_id == "DD025"]
        assert len(dd025) >= 1
        assert "--no-cache" in fixed

    def test_dd031_multiline_yum_install(self):
        """DD031 should append yum clean all to multiline yum install."""
        content = (
            "FROM centos:7\n"
            "RUN yum install -y \\\n"
            "    curl \\\n"
            "    wget\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd031 = [f for f in fixes if f.rule_id == "DD031"]
        assert len(dd031) >= 1
        assert "yum clean all" in fixed

    def test_dd040_multiline_pipe(self):
        """DD040 should add pipefail to multiline RUN with pipe."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN curl -sL https://example.com/setup.sh \\\n"
            "    | bash\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd040 = [f for f in fixes if f.rule_id == "DD040"]
        assert len(dd040) >= 1
        assert "set -o pipefail" in fixed

    def test_dd051_multiline_chmod(self):
        """DD051 should change chmod 777 to 755 in multiline RUN."""
        content = (
            "FROM alpine:3.19\n"
            "RUN mkdir -p /app && \\\n"
            "    chmod 777 /app && \\\n"
            "    echo done\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd051 = [f for f in fixes if f.rule_id == "DD051"]
        assert len(dd051) >= 1
        assert "chmod 755" in fixed
        assert "chmod 777" not in fixed

    def test_dd003_three_continuation_lines(self):
        """DD003 with many continuation lines still inserts correctly."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update \\\n"
            "    && apt-get install \\\n"
            "    -y \\\n"
            "    curl \\\n"
            "    wget \\\n"
            "    git \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd003 = [f for f in fixes if f.rule_id == "DD003"]
        assert len(dd003) >= 1
        assert "--no-install-recommends" in fixed

    def test_dd004_trailing_backslash_handled(self):
        """DD004 should handle instruction ending with trailing backslash."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install --no-install-recommends -y \\\n"
            "    curl\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd004 = [f for f in fixes if f.rule_id == "DD004"]
        assert len(dd004) >= 1
        assert "rm -rf /var/lib/apt/lists/*" in fixed


# ===========================================================================
# 2. Fixer with multi-stage builds (8+ tests)
# ===========================================================================

class TestFixerMultiStage:
    """Test that fixers work correctly across stages."""

    def test_dd007_in_both_stages(self):
        """DD007 should replace ADD with COPY in all stages."""
        content = (
            "FROM node:20 AS build\n"
            "ADD package.json /app/\n"
            "RUN npm ci\n"
            "FROM node:20-slim\n"
            "ADD . /app\n"
            "CMD [\"node\", \"app.js\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd007 = [f for f in fixes if f.rule_id == "DD007"]
        assert len(dd007) == 2
        assert "ADD" not in fixed

    def test_dd017_in_first_stage(self):
        """DD017 should convert MAINTAINER even in multi-stage build."""
        content = (
            "FROM golang:1.21 AS builder\n"
            "MAINTAINER dev@example.com\n"
            "COPY . /src\n"
            "RUN go build -o app\n"
            "FROM alpine:3.19\n"
            "COPY --from=builder /src/app /app\n"
            "CMD [\"/app\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "MAINTAINER" not in fixed
        assert "LABEL maintainer=" in fixed
        # COPY --from preserved
        assert "COPY --from=builder" in fixed

    def test_dd036_duplicate_cmd_per_stage(self):
        """DD036 removes earlier CMD in a single stage, not across stages."""
        content = (
            "FROM alpine:3.19 AS base\n"
            "CMD [\"sh\"]\n"
            "CMD [\"bash\"]\n"
            "FROM alpine:3.19\n"
            "CMD [\"echo\", \"hi\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd036 = [f for f in fixes if f.rule_id == "DD036"]
        assert len(dd036) >= 1
        # The first CMD [\"sh\"] should be removed, CMD [\"bash\"] kept in stage 0
        assert "bash" in fixed
        # Stage 1 CMD preserved
        assert "echo" in fixed

    def test_dd037_duplicate_entrypoint_per_stage(self):
        """DD037 removes earlier ENTRYPOINT within a stage."""
        content = (
            "FROM alpine:3.19\n"
            "ENTRYPOINT [\"sh\"]\n"
            "ENTRYPOINT [\"bash\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd037 = [f for f in fixes if f.rule_id == "DD037"]
        assert len(dd037) >= 1
        assert fixed.count("ENTRYPOINT") == 1
        assert "bash" in fixed

    def test_dd050_uppercase_stage_name(self):
        """DD050 lowercases stage name in FROM AS."""
        content = (
            "FROM node:20 AS Builder\n"
            "COPY . /src\n"
            "FROM alpine:3.19\n"
            "COPY --from=Builder /src/app /app\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd050 = [f for f in fixes if f.rule_id == "DD050"]
        assert len(dd050) >= 1
        assert "AS builder" in fixed or "as builder" in fixed.lower()

    def test_dd071_lowercase_from_in_second_stage(self):
        """DD071 should fix lowercase directive in any stage."""
        content = (
            "FROM alpine:3.19 AS build\n"
            "RUN echo build\n"
            "from alpine:3.19\n"
            "COPY --from=build /app /app\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd071 = [f for f in fixes if f.rule_id == "DD071"]
        assert len(dd071) >= 1
        assert "from " not in fixed.split("\n")[2].lower() or "FROM" in fixed.split("\n")[2]

    def test_dd005_not_combined_across_stages(self):
        """DD005 should not combine RUNs across different stages."""
        content = (
            "FROM alpine:3.19 AS build\n"
            "RUN echo build-step\n"
            "FROM alpine:3.19\n"
            "RUN echo run-step\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd005 = [f for f in fixes if f.rule_id == "DD005"]
        # These RUNs are in different stages, so no DD005
        assert len(dd005) == 0

    def test_dd036_multistage_each_stage_has_cmd(self):
        """Each stage can have its own CMD without DD036 across stages."""
        content = (
            "FROM alpine:3.19 AS stage1\n"
            "CMD [\"echo\", \"stage1\"]\n"
            "FROM alpine:3.19 AS stage2\n"
            "CMD [\"echo\", \"stage2\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd036 = [f for f in fixes if f.rule_id == "DD036"]
        # No duplicates since each CMD is in its own stage
        assert len(dd036) == 0


# ===========================================================================
# 3. Fixer with chained commands (10+ tests)
# ===========================================================================

class TestFixerChainedCommands:
    """Test && chains for various fixers."""

    def test_dd013_remove_upgrade_middle_of_chain(self):
        """DD013 removes upgrade from middle of && chain."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get upgrade -y && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "upgrade" not in fixed
        assert "apt-get update" in fixed
        assert "apt-get install" in fixed
        assert "rm -rf /var/lib/apt/lists" in fixed

    def test_dd021_sudo_in_chain(self):
        """DD021 removes all sudo occurrences in && chain."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN sudo mkdir /app && sudo chown user /app && echo done\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd021 = [f for f in fixes if f.rule_id == "DD021"]
        assert len(dd021) >= 1
        assert "sudo" not in fixed
        assert "mkdir /app" in fixed
        assert "chown user /app" in fixed

    def test_dd026_remove_apk_upgrade_from_chain(self):
        """DD026 removes apk upgrade from && chain."""
        content = (
            "FROM alpine:3.19\n"
            "RUN apk update && apk upgrade && apk add --no-cache curl\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd026 = [f for f in fixes if f.rule_id == "DD026"]
        assert len(dd026) >= 1
        assert "apk upgrade" not in fixed
        assert "apk add" in fixed

    def test_dd040_pipe_in_chain(self):
        """DD040 adds pipefail even when pipe is part of larger chain."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && curl -s https://example.com | bash && echo done\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd040 = [f for f in fixes if f.rule_id == "DD040"]
        assert len(dd040) >= 1
        assert "set -o pipefail" in fixed

    def test_dd045_cd_with_chain(self):
        """DD045 converts cd + chain to WORKDIR + RUN."""
        content = (
            "FROM alpine:3.19\n"
            "RUN cd /app && make && make install\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd045 = [f for f in fixes if f.rule_id == "DD045"]
        assert len(dd045) >= 1
        assert "WORKDIR /app" in fixed
        assert "make" in fixed

    def test_dd051_chmod_in_chain(self):
        """DD051 changes chmod 777 in && chain."""
        content = (
            "FROM alpine:3.19\n"
            "RUN mkdir /data && chmod 777 /data && echo done\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "chmod 755" in fixed
        assert "chmod 777" not in fixed
        assert "echo done" in fixed

    def test_dd013_upgrade_at_start_of_chain(self):
        """DD013 removes upgrade when it's the first command in chain."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get upgrade -y && apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "upgrade" not in fixed
        assert "apt-get install" in fixed

    def test_dd013_upgrade_at_end_of_chain(self):
        """DD013 removes upgrade when it's the last command in chain."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y curl && apt-get upgrade -y\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd013 = [f for f in fixes if f.rule_id == "DD013"]
        assert len(dd013) >= 1
        assert "upgrade" not in fixed

    def test_dd026_apk_upgrade_standalone_in_chain(self):
        """DD026 removes standalone apk upgrade."""
        content = (
            "FROM alpine:3.19\n"
            "COPY . /app\n"
            "RUN apk upgrade\n"
            "COPY config.yml /app/\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd026 = [f for f in fixes if f.rule_id == "DD026"]
        assert len(dd026) >= 1
        assert "apk upgrade" not in fixed

    def test_dd021_sudo_with_flags(self):
        """DD021 removes sudo even with flags in chain."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN sudo -E apt-get update && sudo apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "sudo" not in fixed


# ===========================================================================
# 4. Idempotency tests for ALL 34 fixers (34 tests)
# ===========================================================================

class TestIdempotency:
    """For each fixer, apply fix twice and verify no additional fixes on second pass."""

    def test_idempotent_dd003(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD003"]

    def test_idempotent_dd004(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install --no-install-recommends -y curl\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD004"]

    def test_idempotent_dd005(self):
        content = "FROM alpine:3.19\nRUN echo a\nRUN echo b\nRUN echo c\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD005"]

    def test_idempotent_dd007(self):
        content = "FROM alpine:3.19\nADD . /app\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD007"]

    def test_idempotent_dd009(self):
        content = "FROM python:3.11\nRUN pip install flask\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD009"]

    def test_idempotent_dd010(self):
        content = "FROM node:20\nCOPY package*.json ./\nRUN npm install\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD010"]

    def test_idempotent_dd013(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get upgrade -y && apt-get install -y curl\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD013"]

    def test_idempotent_dd017(self):
        content = "FROM alpine:3.19\nMAINTAINER user@example.com\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD017"]

    def test_idempotent_dd019(self):
        content = "FROM alpine:3.19\nCMD python app.py\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD019"]

    def test_idempotent_dd021(self):
        content = "FROM ubuntu:22.04\nRUN sudo apt-get update\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD021"]

    def test_idempotent_dd023(self):
        content = "FROM ubuntu:22.04\nRUN apt-get install curl && rm -rf /var/lib/apt/lists/*\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD023"]

    def test_idempotent_dd024(self):
        content = "FROM ubuntu:22.04\nRUN apt install -y curl && rm -rf /var/lib/apt/lists/*\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD024"]

    def test_idempotent_dd025(self):
        content = "FROM alpine:3.19\nRUN apk add curl\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD025"]

    def test_idempotent_dd026(self):
        content = "FROM alpine:3.19\nCOPY . /app\nRUN apk upgrade\nCOPY config /etc/\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD026"]

    def test_idempotent_dd031(self):
        content = "FROM centos:7\nRUN yum install -y curl\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD031"]

    def test_idempotent_dd033(self):
        content = "FROM fedora:39\nRUN dnf install -y curl\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD033"]

    def test_idempotent_dd034(self):
        content = "FROM opensuse/leap:15.5\nRUN zypper install -y curl\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD034"]

    def test_idempotent_dd035(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD035"]

    def test_idempotent_dd036(self):
        content = "FROM alpine:3.19\nCMD [\"echo\", \"first\"]\nCMD [\"echo\", \"second\"]\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD036"]

    def test_idempotent_dd037(self):
        content = "FROM alpine:3.19\nENTRYPOINT [\"sh\"]\nENTRYPOINT [\"bash\"]\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD037"]

    def test_idempotent_dd040(self):
        content = "FROM ubuntu:22.04\nRUN curl -s https://example.com | bash\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD040"]

    def test_idempotent_dd044(self):
        content = "FROM alpine:3.19\nENV FOO=bar\nCOPY . /app\nENV FOO=baz\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD044"]

    def test_idempotent_dd045(self):
        content = "FROM alpine:3.19\nRUN cd /app && make\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD045"]

    def test_idempotent_dd047(self):
        content = "FROM alpine:3.19\nCOPY . /app\nRUN \nCOPY config /etc/\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD047"]

    def test_idempotent_dd048(self):
        content = "FROM alpine:3.19\nEXPOSE 8080\nCOPY . /app\nEXPOSE 8080\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD048"]

    def test_idempotent_dd049(self):
        content = "FROM alpine:3.19\nHEALTHCHECK CMD wget -q http://localhost/\nHEALTHCHECK CMD curl http://localhost/\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD049"]

    def test_idempotent_dd050(self):
        content = "FROM alpine:3.19 AS Builder\nCOPY . /app\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD050"]

    def test_idempotent_dd051(self):
        content = "FROM alpine:3.19\nRUN chmod 777 /app\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD051"]

    def test_idempotent_dd061(self):
        content = "FROM ruby:3.2\nRUN gem install rails\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD061"]

    def test_idempotent_dd065(self):
        content = "FROM alpine:3.19\nRUN echo hello\nCOPY . /app\nRUN echo hello\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD065"]

    def test_idempotent_dd071(self):
        content = "from alpine:3.19\nCMD [\"sh\"]\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD071"]

    def test_idempotent_dd073(self):
        content = "FROM alpine:3.19\nCMD [\"sh\"]"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD073"]

    def test_idempotent_dd075(self):
        content = "FROM alpine:3.19\nCMD [\"sh\"]   \n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD075"]

    def test_idempotent_dd076(self):
        content = "FROM alpine:3.19\nRUN echo hello \\\n\\\n    && echo world\n"
        fixed1, _, _ = _analyze_and_fix(content)
        _, _, fixes2 = _analyze_and_fix(fixed1)
        assert not [f for f in fixes2 if f.rule_id == "DD076"]


# ===========================================================================
# 5. Fixer interaction tests (10+ tests)
# ===========================================================================

class TestFixerInteractions:
    """Test pairs/groups of fixers that could interact."""

    def test_dd003_dd004_same_line(self):
        """DD003 + DD004 both apply to same apt-get install line."""
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        fixed, _, fixes = _analyze_and_fix(content)
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists/*" in fixed
        # Both fixes applied
        dd003 = [f for f in fixes if f.rule_id == "DD003"]
        dd004 = [f for f in fixes if f.rule_id == "DD004"]
        assert len(dd003) >= 1
        assert len(dd004) >= 1

    def test_dd005_dd003_dd004_combined_runs(self):
        """DD005 combines RUNs, then DD003 + DD004 apply to combined result."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update\n"
            "RUN apt-get install -y curl\n"
            "RUN echo done\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        # DD005 should combine
        dd005 = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005) >= 1
        # DD003 + DD004 should apply on the combined instruction
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists" in fixed

    def test_dd013_dd003_upgrade_removed_then_recommends_added(self):
        """DD013 removes upgrade, DD003 adds --no-install-recommends."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get upgrade -y && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "upgrade" not in fixed
        assert "--no-install-recommends" in fixed

    def test_dd021_dd023_sudo_removed_and_y_added(self):
        """DD021 removes sudo, DD023 adds -y to apt-get install."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN sudo apt-get install curl && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "sudo" not in fixed
        assert "-y" in fixed

    def test_dd036_dd019_cmd_deduplicated_and_converted(self):
        """DD036 removes duplicate CMD, DD019 converts remaining to exec."""
        content = (
            "FROM alpine:3.19\n"
            "CMD echo first\n"
            "CMD python app.py\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd036 = [f for f in fixes if f.rule_id == "DD036"]
        assert len(dd036) >= 1
        # Only one CMD remains, in exec form
        assert fixed.count("CMD") == 1
        assert "CMD [" in fixed

    def test_dd071_dd007_lowercase_add_fixed_and_replaced(self):
        """DD007 on lowercase 'add' replaces it with uppercase COPY, subsuming DD071."""
        content = "FROM alpine:3.19\nadd . /app\n"
        fixed, _, fixes = _analyze_and_fix(content)
        # DD007 regex is case-insensitive, so it replaces 'add' -> 'COPY' directly
        dd007 = [f for f in fixes if f.rule_id == "DD007"]
        assert len(dd007) >= 1
        assert "COPY . /app" in fixed
        # No lowercase directive remains
        assert "add " not in fixed

    def test_dd071_lowercase_run(self):
        """DD071 uppercases a lowercase 'run' directive."""
        content = "FROM alpine:3.19\nrun echo hello\n"
        fixed, _, fixes = _analyze_and_fix(content)
        dd071 = [f for f in fixes if f.rule_id == "DD071"]
        assert len(dd071) >= 1
        assert "RUN echo hello" in fixed

    def test_dd075_dd073_trailing_whitespace_and_newline(self):
        """DD075 removes trailing whitespace, DD073 adds final newline."""
        content = "FROM alpine:3.19\nCMD [\"sh\"]   "
        fixed, _, fixes = _analyze_and_fix(content)
        # DD075 should remove trailing spaces
        dd075 = [f for f in fixes if f.rule_id == "DD075"]
        assert len(dd075) >= 1
        # DD073 should add final newline
        dd073 = [f for f in fixes if f.rule_id == "DD073"]
        assert len(dd073) >= 1
        assert fixed.endswith("\n")
        # No trailing spaces on CMD line
        for line in fixed.strip().split("\n"):
            if "CMD" in line:
                assert line == line.rstrip()

    def test_dd044_dd035_env_dedup_and_debian_frontend(self):
        """DD044 deduplicates ENV, DD035 adds DEBIAN_FRONTEND."""
        content = (
            "FROM ubuntu:22.04\n"
            "ENV MY_VAR=hello\n"
            "RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
            "ENV MY_VAR=world\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd044 = [f for f in fixes if f.rule_id == "DD044"]
        dd035 = [f for f in fixes if f.rule_id == "DD035"]
        assert len(dd044) >= 1
        assert len(dd035) >= 1
        # Only one MY_VAR remains
        assert fixed.count("MY_VAR") == 1
        assert "DEBIAN_FRONTEND=noninteractive" in fixed

    def test_dd005_dd009_consecutive_pip_runs(self):
        """DD005 combines consecutive pip install RUNs, DD009 applies to combined."""
        content = (
            "FROM python:3.11\n"
            "RUN pip install flask\n"
            "RUN pip install gunicorn\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd005 = [f for f in fixes if f.rule_id == "DD005"]
        assert len(dd005) >= 1
        # After combining, --no-cache-dir should be present
        assert "--no-cache-dir" in fixed

    def test_dd024_dd003_apt_replaced_then_recommends_added(self):
        """DD024 replaces 'apt' with 'apt-get', DD003 adds --no-install-recommends."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt update && apt install -y curl && rm -rf /var/lib/apt/lists/*\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        dd024 = [f for f in fixes if f.rule_id == "DD024"]
        assert len(dd024) >= 1
        assert "apt-get install" in fixed
        assert "--no-install-recommends" in fixed

    def test_dd021_dd003_dd004_sudo_plus_apt_fixes(self):
        """DD021 removes sudo, DD003 adds recommends, DD004 adds cleanup."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN sudo apt-get update && sudo apt-get install -y curl\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        assert "sudo" not in fixed
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists/*" in fixed


# ===========================================================================
# 6. Fixer preserves structure (5+ tests)
# ===========================================================================

class TestFixerPreservesStructure:
    """Fixed content should be parseable, comments preserved, blank lines handled."""

    def test_fixed_content_is_parseable(self):
        """After fixing, the result should still parse correctly."""
        content = (
            "FROM ubuntu:22.04\n"
            "MAINTAINER dev@example.com\n"
            "ADD . /app\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "RUN pip install flask\n"
            "CMD python app.py\n"
        )
        fixed, _, _ = _analyze_and_fix(content)
        df = parse(fixed)
        assert len(df.instructions) > 0
        assert df.instructions[0].directive == "FROM"
        # All essential directives present
        directives = {i.directive for i in df.instructions}
        assert "FROM" in directives

    def test_comments_preserved_after_fix(self):
        """Comments should survive multi-fix pipeline."""
        content = (
            "# Base image\n"
            "FROM ubuntu:22.04\n"
            "# Install packages\n"
            "RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n"
            "# Copy app\n"
            "ADD . /app\n"
            "# Start\n"
            "CMD python app.py\n"
        )
        fixed, _, _ = _analyze_and_fix(content)
        assert "# Base image" in fixed
        assert "# Install packages" in fixed
        assert "# Copy app" in fixed
        assert "# Start" in fixed

    def test_blank_lines_preserved(self):
        """Blank lines between non-consecutive instructions should be preserved."""
        content = (
            "FROM alpine:3.19\n"
            "\n"
            "ADD . /app\n"
            "\n"
            "CMD [\"sh\"]\n"
        )
        fixed, _, _ = _analyze_and_fix(content)
        # ADD -> COPY change, blank lines should survive
        assert "COPY . /app" in fixed
        lines = fixed.split("\n")
        # At least one blank line should remain
        assert "" in lines

    def test_indentation_preserved(self):
        """Instructions with unusual indentation should be handled."""
        content = (
            "FROM alpine:3.19\n"
            "  ADD . /app\n"
            "  CMD echo hello\n"
        )
        fixed, _, _ = _analyze_and_fix(content)
        df = parse(fixed)
        assert len(df.instructions) > 0

    def test_trailing_newline_preserved_after_multiple_fixes(self):
        """Trailing newline in original should be preserved after fixes."""
        content = "FROM alpine:3.19\nADD . /app\nCMD echo hello\n"
        fixed, _, _ = _analyze_and_fix(content)
        assert fixed.endswith("\n")

    def test_no_trailing_newline_gets_added_by_dd073(self):
        """DD073 should add missing trailing newline."""
        content = "FROM alpine:3.19\nCMD [\"sh\"]"
        fixed, _, fixes = _analyze_and_fix(content)
        dd073 = [f for f in fixes if f.rule_id == "DD073"]
        assert len(dd073) >= 1
        assert fixed.endswith("\n")

    def test_multiple_deletions_dont_corrupt_structure(self):
        """Multiple line deletions (DD036 + DD048) should not corrupt output."""
        content = (
            "FROM alpine:3.19\n"
            "CMD [\"echo\", \"first\"]\n"
            "EXPOSE 8080\n"
            "CMD [\"echo\", \"second\"]\n"
            "COPY . /app\n"
            "EXPOSE 8080\n"
            "CMD [\"echo\", \"third\"]\n"
        )
        fixed, _, fixes = _analyze_and_fix(content)
        df = parse(fixed)
        assert len(df.instructions) > 0
        assert df.instructions[0].directive == "FROM"
        # Only one CMD should remain (the last one)
        cmd_instrs = [i for i in df.instructions if i.directive == "CMD"]
        assert len(cmd_instrs) == 1
