"""Tests for the Dockerfile parser."""

from __future__ import annotations

import pytest

from dockerfile_doctor.parser import parse
from dockerfile_doctor.models import Dockerfile, Instruction, Stage


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------

class TestParseSimple:
    """Parse simple single-stage Dockerfiles."""

    def test_single_from_cmd(self):
        content = "FROM alpine:3.19\nCMD [\"echo\", \"hello\"]\n"
        df = parse(content)
        assert isinstance(df, Dockerfile)
        assert len(df.instructions) == 2
        assert df.instructions[0].directive == "FROM"
        assert df.instructions[0].arguments == "alpine:3.19"
        assert df.instructions[0].line_number == 1
        assert df.instructions[1].directive == "CMD"
        assert df.instructions[1].line_number == 2

    def test_all_directives_recognized(self):
        content = (
            "FROM scratch\n"
            "RUN echo hi\n"
            "CMD [\"sh\"]\n"
            "LABEL key=value\n"
            "EXPOSE 80\n"
            "ENV FOO=bar\n"
            "ADD . /app\n"
            "COPY . /app\n"
            "ENTRYPOINT [\"sh\"]\n"
            "VOLUME /data\n"
            "USER nobody\n"
            "WORKDIR /app\n"
            "ARG VERSION=1\n"
            "STOPSIGNAL SIGTERM\n"
            "HEALTHCHECK CMD curl -f http://localhost/\n"
            "SHELL [\"/bin/bash\", \"-c\"]\n"
        )
        df = parse(content)
        directives = [i.directive for i in df.instructions]
        assert "FROM" in directives
        assert "RUN" in directives
        assert "CMD" in directives
        assert "LABEL" in directives
        assert "EXPOSE" in directives
        assert "ENV" in directives
        assert "ADD" in directives
        assert "COPY" in directives
        assert "ENTRYPOINT" in directives
        assert "VOLUME" in directives
        assert "USER" in directives
        assert "WORKDIR" in directives
        assert "ARG" in directives
        assert "STOPSIGNAL" in directives
        assert "HEALTHCHECK" in directives
        assert "SHELL" in directives

    def test_case_insensitive_directives(self):
        content = "from alpine:3.19\nrun echo hello\ncmd [\"sh\"]\n"
        df = parse(content)
        assert df.instructions[0].directive == "FROM"
        assert df.instructions[1].directive == "RUN"
        assert df.instructions[2].directive == "CMD"

    def test_stages_single(self):
        content = "FROM python:3.11\nRUN pip install flask\n"
        df = parse(content)
        assert len(df.stages) == 1
        assert df.stages[0].base_image == "python"
        assert df.stages[0].base_tag == "3.11"
        assert not df.is_multistage

    def test_empty_dockerfile(self):
        df = parse("")
        assert len(df.instructions) == 0
        assert len(df.stages) == 0

    def test_only_comments(self):
        content = "# This is a comment\n# Another comment\n"
        df = parse(content)
        assert len(df.instructions) == 0
        assert len(df.stages) == 0

    def test_original_line_preserved(self):
        content = "FROM  python:3.11-slim\n"
        df = parse(content)
        assert df.instructions[0].original_line == "FROM  python:3.11-slim"

    def test_raw_content_and_lines(self):
        content = "FROM alpine:3.19\nRUN echo hi\n"
        df = parse(content)
        assert df.raw_content == content
        assert df.lines == ["FROM alpine:3.19", "RUN echo hi"]


# ---------------------------------------------------------------------------
# Multi-stage builds
# ---------------------------------------------------------------------------

class TestParseMultiStage:
    """Parse multi-stage build Dockerfiles."""

    def test_two_stages(self):
        content = (
            "FROM golang:1.22 AS builder\n"
            "RUN go build -o /app\n"
            "FROM alpine:3.19\n"
            "COPY --from=builder /app /app\n"
        )
        df = parse(content)
        assert df.is_multistage
        assert len(df.stages) == 2
        assert df.stages[0].name == "builder"
        assert df.stages[0].base_image == "golang"
        assert df.stages[0].base_tag == "1.22"
        assert df.stages[1].name is None
        assert df.stages[1].base_image == "alpine"
        assert df.stages[1].base_tag == "3.19"

    def test_three_stages(self):
        content = (
            "FROM node:20 AS deps\n"
            "RUN npm ci\n"
            "FROM node:20 AS build\n"
            "RUN npm run build\n"
            "FROM node:20-alpine\n"
            "COPY --from=build /app /app\n"
        )
        df = parse(content)
        assert len(df.stages) == 3
        assert df.stages[0].name == "deps"
        assert df.stages[1].name == "build"
        assert df.stages[2].name is None

    def test_stage_index_on_instructions(self):
        content = (
            "FROM alpine:3.19 AS first\n"
            "RUN echo first\n"
            "FROM alpine:3.19 AS second\n"
            "RUN echo second\n"
        )
        df = parse(content)
        assert df.instructions[0].stage_index == 0
        assert df.instructions[1].stage_index == 0
        assert df.instructions[2].stage_index == 1
        assert df.instructions[3].stage_index == 1

    def test_stage_instructions_list(self):
        content = (
            "FROM alpine:3.19 AS builder\n"
            "RUN echo build\n"
            "RUN echo test\n"
            "FROM alpine:3.19\n"
            "COPY --from=builder /out /out\n"
        )
        df = parse(content)
        # Stage 0 has FROM + 2 RUNs
        assert len(df.stages[0].instructions) == 3
        # Stage 1 has FROM + 1 COPY
        assert len(df.stages[1].instructions) == 2


# ---------------------------------------------------------------------------
# Multi-line continuations
# ---------------------------------------------------------------------------

class TestMultiLineContinuation:
    """Handle multi-line RUN with backslash continuations."""

    def test_backslash_continuation(self):
        content = "FROM alpine:3.19\nRUN apt-get update && \\\n    apt-get install -y curl\n"
        df = parse(content)
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "apt-get update" in run_instr.arguments
        assert "apt-get install" in run_instr.arguments
        assert run_instr.line_number == 2

    def test_three_line_continuation(self):
        content = (
            "FROM alpine:3.19\n"
            "RUN apt-get update && \\\n"
            "    apt-get install -y \\\n"
            "    curl wget git\n"
        )
        df = parse(content)
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "curl wget git" in run_instr.arguments
        assert run_instr.line_number == 2

    def test_original_line_includes_continuations(self):
        content = "FROM alpine:3.19\nRUN echo a && \\\n    echo b\n"
        df = parse(content)
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "\n" in run_instr.original_line
        assert "echo a" in run_instr.original_line
        assert "echo b" in run_instr.original_line

    def test_custom_escape_char(self):
        content = "# escape=`\nFROM alpine:3.19\nRUN echo a && `\n    echo b\n"
        df = parse(content)
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "echo a" in run_instr.arguments
        assert "echo b" in run_instr.arguments


# ---------------------------------------------------------------------------
# Comments and blank lines
# ---------------------------------------------------------------------------

class TestCommentsAndBlanks:
    """Handle comments and blank lines correctly."""

    def test_comments_skipped(self):
        content = (
            "# Comment before FROM\n"
            "FROM alpine:3.19\n"
            "# Comment in middle\n"
            "RUN echo hello\n"
            "# Trailing comment\n"
        )
        df = parse(content)
        assert len(df.instructions) == 2
        assert df.instructions[0].directive == "FROM"
        assert df.instructions[1].directive == "RUN"

    def test_blank_lines_skipped(self):
        content = "\n\nFROM alpine:3.19\n\n\nRUN echo hello\n\n"
        df = parse(content)
        assert len(df.instructions) == 2

    def test_inline_hash_not_treated_as_comment(self):
        content = "FROM alpine:3.19\nRUN echo 'hello # world'\n"
        df = parse(content)
        # The # inside the RUN should not be treated as a comment
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "hello # world" in run_instr.arguments

    def test_mixed_comments_blanks_instructions(self):
        content = (
            "# header\n"
            "\n"
            "FROM alpine:3.19\n"
            "\n"
            "# install deps\n"
            "RUN apk add curl\n"
            "\n"
            "CMD [\"sh\"]\n"
        )
        df = parse(content)
        assert len(df.instructions) == 3


# ---------------------------------------------------------------------------
# ARG before FROM
# ---------------------------------------------------------------------------

class TestArgBeforeFrom:
    """Handle ARG instructions before the first FROM."""

    def test_arg_before_from(self):
        content = "ARG BASE_TAG=3.19\nFROM alpine:${BASE_TAG}\nRUN echo hi\n"
        df = parse(content)
        assert len(df.instructions) == 3
        assert df.instructions[0].directive == "ARG"
        assert df.instructions[0].arguments == "BASE_TAG=3.19"
        # ARG before FROM gets stage_index 0 (clamped)
        assert df.instructions[0].stage_index == 0

    def test_multiple_args_before_from(self):
        content = (
            "ARG REGISTRY=docker.io\n"
            "ARG BASE_IMAGE=python\n"
            "ARG BASE_TAG=3.11\n"
            "FROM ${REGISTRY}/${BASE_IMAGE}:${BASE_TAG}\n"
        )
        df = parse(content)
        assert len(df.instructions) == 4
        for i in range(3):
            assert df.instructions[i].directive == "ARG"
        assert df.instructions[3].directive == "FROM"

    def test_arg_not_in_any_stage(self):
        """ARGs before FROM should not appear in any stage's instructions list."""
        content = "ARG VERSION=1\nFROM alpine:3.19\n"
        df = parse(content)
        assert len(df.stages) == 1
        # The stage's instructions list starts with FROM
        stage_directives = [i.directive for i in df.stages[0].instructions]
        assert "ARG" not in stage_directives


# ---------------------------------------------------------------------------
# Heredoc syntax
# ---------------------------------------------------------------------------

class TestHeredoc:
    """Handle heredoc syntax in RUN instructions."""

    def test_simple_heredoc(self):
        content = (
            "FROM alpine:3.19\n"
            "RUN <<EOF\n"
            "echo hello\n"
            "echo world\n"
            "EOF\n"
        )
        df = parse(content)
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "echo hello" in run_instr.arguments
        assert "echo world" in run_instr.arguments
        assert run_instr.line_number == 2

    def test_heredoc_with_dash(self):
        content = (
            "FROM alpine:3.19\n"
            "RUN <<-EOF\n"
            "    echo indented\n"
            "EOF\n"
        )
        df = parse(content)
        run_instr = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "echo indented" in run_instr.arguments

    def test_heredoc_copy(self):
        content = (
            "FROM alpine:3.19\n"
            "COPY <<EOF /app/config.ini\n"
            "[settings]\n"
            "debug = false\n"
            "EOF\n"
        )
        df = parse(content)
        copy_instr = [i for i in df.instructions if i.directive == "COPY"][0]
        assert "debug = false" in copy_instr.arguments or "debug = false" in copy_instr.original_line


# ---------------------------------------------------------------------------
# FROM with AS alias
# ---------------------------------------------------------------------------

class TestFromAlias:
    """Parse FROM with AS alias."""

    def test_from_as_alias(self):
        content = "FROM python:3.11 AS builder\nRUN pip install flask\n"
        df = parse(content)
        assert df.stages[0].name == "builder"
        assert df.instructions[0].stage_name == "builder"

    def test_from_as_case_insensitive(self):
        content = "FROM python:3.11 as mybuilder\n"
        df = parse(content)
        assert df.stages[0].name == "mybuilder"

    def test_from_no_alias(self):
        content = "FROM python:3.11\n"
        df = parse(content)
        assert df.stages[0].name is None

    def test_from_with_platform_and_alias(self):
        content = "FROM --platform=linux/amd64 python:3.11 AS builder\n"
        df = parse(content)
        assert df.stages[0].name == "builder"
        assert df.stages[0].base_image == "python"
        assert df.stages[0].base_tag == "3.11"


# ---------------------------------------------------------------------------
# FROM with tag and digest
# ---------------------------------------------------------------------------

class TestFromTagDigest:
    """Parse FROM with tag and digest variations."""

    def test_from_with_tag(self):
        content = "FROM python:3.11-slim\n"
        df = parse(content)
        assert df.stages[0].base_image == "python"
        assert df.stages[0].base_tag == "3.11-slim"

    def test_from_without_tag(self):
        content = "FROM ubuntu\n"
        df = parse(content)
        assert df.stages[0].base_image == "ubuntu"
        assert df.stages[0].base_tag is None

    def test_from_with_digest(self):
        content = "FROM python:3.11@sha256:abcdef1234567890\n"
        df = parse(content)
        assert df.stages[0].base_image == "python"
        assert df.stages[0].base_tag == "3.11"

    def test_from_scratch(self):
        content = "FROM scratch\n"
        df = parse(content)
        assert df.stages[0].base_image == "scratch"
        assert df.stages[0].base_tag is None

    def test_from_with_registry_port(self):
        content = "FROM registry.example.com:5000/myimage:1.0\n"
        df = parse(content)
        assert df.stages[0].base_image == "registry.example.com:5000/myimage"
        assert df.stages[0].base_tag == "1.0"

    def test_from_latest_tag(self):
        content = "FROM ubuntu:latest\n"
        df = parse(content)
        assert df.stages[0].base_image == "ubuntu"
        assert df.stages[0].base_tag == "latest"

    def test_from_variable(self):
        content = "ARG BASE=alpine:3.19\nFROM ${BASE}\n"
        df = parse(content)
        # Variable reference won't parse as a normal image:tag
        assert df.stages[0].base_image == "${BASE}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases for the parser."""

    def test_maintainer_deprecated(self):
        content = "FROM alpine:3.19\nMAINTAINER user@example.com\n"
        df = parse(content)
        assert len(df.instructions) == 2
        assert df.instructions[1].directive == "MAINTAINER"

    def test_onbuild_instruction(self):
        content = "FROM alpine:3.19\nONBUILD RUN echo trigger\n"
        df = parse(content)
        assert df.instructions[1].directive == "ONBUILD"

    def test_single_instruction_no_newline(self):
        content = "FROM alpine:3.19"
        df = parse(content)
        assert len(df.instructions) == 1

    def test_parser_directive_syntax(self):
        content = "# syntax=docker/dockerfile:1\nFROM alpine:3.19\n"
        df = parse(content)
        assert len(df.instructions) == 1
        assert df.instructions[0].directive == "FROM"

    def test_utf8_bom(self):
        content = "\ufeffFROM alpine:3.19\n"
        df = parse(content)
        assert len(df.instructions) == 1
        assert df.instructions[0].directive == "FROM"

    def test_registry_port_no_tag(self):
        """Port in registry URL should not be confused with tag."""
        content = "FROM registry.example.com:5000/myimage\n"
        df = parse(content)
        assert df.stages[0].base_image == "registry.example.com:5000/myimage"
        assert df.stages[0].base_tag is None

    def test_blank_lines_between_instructions(self):
        content = "FROM alpine:3.19\n\n\nRUN echo a\n\nRUN echo b\n"
        df = parse(content)
        assert len(df.instructions) == 3
        runs = [i for i in df.instructions if i.directive == "RUN"]
        assert len(runs) == 2

    def test_trailing_whitespace(self):
        content = "FROM alpine:3.19   \nRUN echo hello   \n"
        df = parse(content)
        assert len(df.instructions) == 2

    def test_env_with_equals(self):
        content = "FROM alpine:3.19\nENV FOO=bar BAZ=qux\n"
        df = parse(content)
        env_instr = [i for i in df.instructions if i.directive == "ENV"][0]
        assert "FOO=bar" in env_instr.arguments

    def test_env_without_equals(self):
        content = "FROM alpine:3.19\nENV FOO bar\n"
        df = parse(content)
        env_instr = [i for i in df.instructions if i.directive == "ENV"][0]
        assert "FOO" in env_instr.arguments

    def test_expose_multiple_ports(self):
        content = "FROM alpine:3.19\nEXPOSE 80 443 8080\n"
        df = parse(content)
        expose = [i for i in df.instructions if i.directive == "EXPOSE"][0]
        assert "80" in expose.arguments

    def test_label_multiline(self):
        content = (
            "FROM alpine:3.19\n"
            "LABEL version=\"1.0\" \\\n"
            "      description=\"test\"\n"
        )
        df = parse(content)
        label = [i for i in df.instructions if i.directive == "LABEL"][0]
        assert "version" in label.arguments
        assert "description" in label.arguments

    def test_from_with_platform_only(self):
        content = "FROM --platform=linux/arm64 alpine:3.19\n"
        df = parse(content)
        assert df.stages[0].base_image == "alpine"
        assert df.stages[0].base_tag == "3.19"

    def test_healthcheck_with_options(self):
        content = "FROM alpine:3.19\nHEALTHCHECK --interval=5m --timeout=3s CMD curl -f http://localhost/\n"
        df = parse(content)
        hc = [i for i in df.instructions if i.directive == "HEALTHCHECK"][0]
        assert "interval" in hc.arguments

    def test_volume_instruction(self):
        content = "FROM alpine:3.19\nVOLUME /data /logs\n"
        df = parse(content)
        vol = [i for i in df.instructions if i.directive == "VOLUME"][0]
        assert "/data" in vol.arguments

    def test_stopsignal_instruction(self):
        content = "FROM alpine:3.19\nSTOPSIGNAL SIGTERM\n"
        df = parse(content)
        ss = [i for i in df.instructions if i.directive == "STOPSIGNAL"][0]
        assert ss.arguments.strip() == "SIGTERM"

    def test_shell_instruction(self):
        content = 'FROM alpine:3.19\nSHELL ["/bin/bash", "-c"]\n'
        df = parse(content)
        shell = [i for i in df.instructions if i.directive == "SHELL"][0]
        assert "/bin/bash" in shell.arguments

    def test_from_with_platform_and_tag(self):
        content = "FROM --platform=linux/arm64 python:3.11-slim\n"
        df = parse(content)
        assert df.stages[0].base_image == "python"
        assert df.stages[0].base_tag == "3.11-slim"

    def test_four_line_continuation(self):
        content = (
            "FROM alpine:3.19\n"
            "RUN echo a && \\\n"
            "    echo b && \\\n"
            "    echo c && \\\n"
            "    echo d\n"
        )
        df = parse(content)
        run = [i for i in df.instructions if i.directive == "RUN"][0]
        assert "echo d" in run.arguments
