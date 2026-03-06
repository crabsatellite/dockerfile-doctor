"""Edge case tests for DD061-DD080 rules."""
from __future__ import annotations
from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from tests.conftest import has_rule, count_rule, get_issues_for_rule


# ===========================================================================
# DD061 — gem install without --no-document
# ===========================================================================

class TestDD061GemNoDocument:
    def test_triggers_on_plain_gem_install(self):
        df = parse("FROM ruby:3.2\nRUN gem install rails\n")
        issues = analyze(df)
        assert has_rule(issues, "DD061")

    def test_clean_with_no_document(self):
        df = parse("FROM ruby:3.2\nRUN gem install --no-document rails\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD061")

    def test_clean_with_no_doc(self):
        df = parse("FROM ruby:3.2\nRUN gem install --no-doc bundler\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD061")

    def test_clean_with_no_ri(self):
        df = parse("FROM ruby:3.2\nRUN gem install --no-ri rake\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD061")

    def test_multiple_gem_installs_both_trigger(self):
        content = (
            "FROM ruby:3.2\n"
            "RUN gem install rails\n"
            "RUN gem install bundler\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD061") == 2

    def test_gem_in_chain_command(self):
        df = parse("FROM ruby:3.2\nRUN apt-get update && gem install puma\n")
        issues = analyze(df)
        assert has_rule(issues, "DD061")

    def test_no_trigger_on_gem_other_subcommand(self):
        df = parse("FROM ruby:3.2\nRUN gem update --system\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD061")

    def test_fix_available(self):
        df = parse("FROM ruby:3.2\nRUN gem install rails\n")
        issues = get_issues_for_rule(analyze(df), "DD061")
        assert issues[0].fix_available


# ===========================================================================
# DD062 — Go build without CGO_ENABLED=0
# ===========================================================================

class TestDD062GoCGO:
    def test_triggers_on_go_build_without_cgo(self):
        df = parse("FROM golang:1.22\nRUN go build -o app .\n")
        issues = analyze(df)
        assert has_rule(issues, "DD062")

    def test_clean_with_cgo_in_run(self):
        df = parse("FROM golang:1.22\nRUN CGO_ENABLED=0 go build -o app .\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")

    def test_clean_with_cgo_in_env(self):
        df = parse("FROM golang:1.22\nENV CGO_ENABLED=0\nRUN go build -o app .\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")

    def test_no_trigger_on_non_go_image(self):
        df = parse("FROM python:3.12\nRUN go build -o app .\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")

    def test_no_trigger_without_go_build(self):
        df = parse("FROM golang:1.22\nRUN go test ./...\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")


# ===========================================================================
# DD063 — apk add without --virtual for build deps
# ===========================================================================

class TestDD063ApkVirtual:
    def test_triggers_on_dev_packages_without_virtual(self):
        df = parse("FROM alpine:3.19\nRUN apk add gcc g++ make\n")
        issues = analyze(df)
        assert has_rule(issues, "DD063")

    def test_clean_with_virtual_flag(self):
        df = parse("FROM alpine:3.19\nRUN apk add --virtual .build-deps gcc g++ make\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD063")

    def test_clean_with_build_deps_name(self):
        df = parse("FROM alpine:3.19\nRUN apk add .build-deps gcc g++\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD063")

    def test_no_trigger_for_non_dev_packages(self):
        df = parse("FROM alpine:3.19\nRUN apk add curl wget\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD063")

    def test_triggers_on_build_base(self):
        df = parse("FROM alpine:3.19\nRUN apk add build-base\n")
        issues = analyze(df)
        assert has_rule(issues, "DD063")

    def test_triggers_on_single_dev_package(self):
        df = parse("FROM alpine:3.19\nRUN apk add musl-dev\n")
        issues = analyze(df)
        assert has_rule(issues, "DD063")


# ===========================================================================
# DD064 — Too many layers (>20 layer-creating instructions)
# ===========================================================================

class TestDD064TooManyLayers:
    def test_triggers_above_threshold(self):
        lines = ["FROM ubuntu:22.04\n"]
        for i in range(21):
            lines.append(f"RUN echo {i}\n")
        df = parse("".join(lines))
        issues = analyze(df)
        assert has_rule(issues, "DD064")

    def test_clean_at_threshold(self):
        lines = ["FROM ubuntu:22.04\n"]
        for i in range(20):
            lines.append(f"RUN echo {i}\n")
        df = parse("".join(lines))
        issues = analyze(df)
        assert not has_rule(issues, "DD064")

    def test_clean_with_few_layers(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\nCOPY . /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD064")

    def test_counts_copy_and_add_as_layers(self):
        lines = ["FROM ubuntu:22.04\n"]
        for i in range(11):
            lines.append(f"RUN echo {i}\n")
        for i in range(11):
            lines.append(f"COPY file{i}.txt /app/\n")
        df = parse("".join(lines))
        issues = analyze(df)
        # 11 RUN + 11 COPY = 22 > 20
        assert has_rule(issues, "DD064")

    def test_per_stage_counting_in_multistage(self):
        """Each stage is counted independently."""
        lines = ["FROM ubuntu:22.04 AS builder\n"]
        for i in range(5):
            lines.append(f"RUN echo {i}\n")
        lines.append("FROM alpine:3.19\n")
        for i in range(5):
            lines.append(f"RUN echo {i}\n")
        df = parse("".join(lines))
        issues = analyze(df)
        assert not has_rule(issues, "DD064")


# ===========================================================================
# DD065 — Duplicate RUN instructions
# ===========================================================================

class TestDD065DuplicateRun:
    def test_triggers_on_identical_run(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update\n"
            "RUN echo hello\n"
            "RUN apt-get update\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD065")

    def test_clean_with_unique_runs(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update\n"
            "RUN apt-get install -y curl\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD065")

    def test_duplicate_across_stages_no_trigger(self):
        """Duplicates are checked within each stage, not across stages."""
        content = (
            "FROM ubuntu:22.04 AS builder\n"
            "RUN apt-get update\n"
            "FROM ubuntu:22.04\n"
            "RUN apt-get update\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD065")

    def test_three_duplicates_triggers_twice(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN echo hello\n"
            "RUN echo hello\n"
            "RUN echo hello\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD065") == 2

    def test_fix_available(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN echo a\n"
            "RUN echo a\n"
        )
        df = parse(content)
        issues = get_issues_for_rule(analyze(df), "DD065")
        assert issues[0].fix_available


# ===========================================================================
# DD066 — Multi-stage build without COPY --from
# ===========================================================================

class TestDD066MultistageNoCopyFrom:
    def test_triggers_on_multistage_without_copy_from(self):
        content = (
            "FROM golang:1.22 AS builder\n"
            "RUN go build -o app\n"
            "FROM alpine:3.19\n"
            "RUN echo hi\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD066")

    def test_clean_with_copy_from(self):
        content = (
            "FROM golang:1.22 AS builder\n"
            "RUN go build -o app\n"
            "FROM alpine:3.19\n"
            "COPY --from=builder /app /app\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD066")

    def test_no_trigger_on_single_stage(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD066")

    def test_copy_from_numeric_stage(self):
        content = (
            "FROM golang:1.22\n"
            "RUN go build -o app\n"
            "FROM alpine:3.19\n"
            "COPY --from=0 /app /app\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD066")


# ===========================================================================
# DD067 — Missing NODE_ENV=production
# ===========================================================================

class TestDD067NodeEnv:
    def test_triggers_on_node_image_without_env(self):
        df = parse("FROM node:20\nRUN npm ci\n")
        issues = analyze(df)
        assert has_rule(issues, "DD067")

    def test_clean_with_node_env(self):
        df = parse("FROM node:20\nENV NODE_ENV=production\nRUN npm ci\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD067")

    def test_no_trigger_on_non_node_image(self):
        df = parse("FROM python:3.12\nRUN pip install flask\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD067")

    def test_node_env_with_space_syntax(self):
        df = parse("FROM node:20\nENV NODE_ENV production\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD067")

    def test_triggers_on_node_alpine_variant(self):
        df = parse("FROM node:20-alpine\nRUN npm ci\n")
        issues = analyze(df)
        assert has_rule(issues, "DD067")


# ===========================================================================
# DD068 — Java without container-aware JVM flags
# ===========================================================================

class TestDD068JavaContainerFlags:
    def test_triggers_on_openjdk_without_flags(self):
        df = parse("FROM openjdk:17\nCOPY app.jar /app.jar\nCMD [\"java\", \"-jar\", \"/app.jar\"]\n")
        issues = analyze(df)
        assert has_rule(issues, "DD068")

    def test_clean_with_use_container_support(self):
        content = (
            "FROM openjdk:17\n"
            "ENV JAVA_OPTS=\"-XX:+UseContainerSupport\"\n"
            "CMD [\"java\", \"-jar\", \"/app.jar\"]\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD068")

    def test_clean_with_max_ram_percentage(self):
        content = (
            "FROM openjdk:17\n"
            "ENV JAVA_OPTS=\"-XX:MaxRAMPercentage=75.0\"\n"
            "CMD [\"java\", \"-jar\", \"/app.jar\"]\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD068")

    def test_no_trigger_on_non_java_image(self):
        df = parse("FROM python:3.12\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD068")

    def test_triggers_on_eclipse_temurin(self):
        df = parse("FROM eclipse-temurin:17\nCMD [\"java\", \"-jar\", \"app.jar\"]\n")
        issues = analyze(df)
        assert has_rule(issues, "DD068")

    def test_triggers_on_amazoncorretto(self):
        df = parse("FROM amazoncorretto:17\nCMD [\"java\", \"-jar\", \"app.jar\"]\n")
        issues = analyze(df)
        assert has_rule(issues, "DD068")


# ===========================================================================
# DD069 — apt-get install with wildcard
# ===========================================================================

class TestDD069AptWildcard:
    def test_triggers_on_wildcard_package(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y lib*-dev\n")
        issues = analyze(df)
        assert has_rule(issues, "DD069")

    def test_clean_without_wildcard(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl wget\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD069")

    def test_no_trigger_without_apt_get_install(self):
        df = parse("FROM ubuntu:22.04\nRUN echo 'test*'\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD069")

    def test_wildcard_at_end_of_package(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y python3*\n")
        issues = analyze(df)
        assert has_rule(issues, "DD069")


# ===========================================================================
# DD070 — Copying entire build context
# ===========================================================================

class TestDD070DockerignoreHint:
    def test_triggers_on_copy_dot(self):
        df = parse("FROM node:20\nCOPY . /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD070")

    def test_triggers_on_copy_dot_slash(self):
        df = parse("FROM node:20\nCOPY ./ /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD070")

    def test_clean_with_specific_file(self):
        df = parse("FROM node:20\nCOPY package.json /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD070")

    def test_triggers_on_add_dot(self):
        df = parse("FROM node:20\nADD . /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD070")

    def test_copy_with_chown_and_dot(self):
        df = parse("FROM node:20\nCOPY --chown=node:node . /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD070")

    def test_clean_with_subdirectory(self):
        df = parse("FROM node:20\nCOPY src/ /app/src/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD070")


# ===========================================================================
# DD071 — Instruction not uppercase
# ===========================================================================

class TestDD071InstructionCasing:
    def test_triggers_on_lowercase_from(self):
        df = parse("from ubuntu:22.04\n")
        issues = analyze(df)
        assert has_rule(issues, "DD071")

    def test_triggers_on_lowercase_run(self):
        df = parse("FROM ubuntu:22.04\nrun echo hello\n")
        issues = analyze(df)
        assert has_rule(issues, "DD071")

    def test_clean_with_uppercase(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD071")

    def test_triggers_on_mixed_case(self):
        df = parse("From ubuntu:22.04\n")
        issues = analyze(df)
        assert has_rule(issues, "DD071")

    def test_multiple_lowercase_instructions(self):
        content = "from ubuntu:22.04\nrun echo a\ncopy . /app\n"
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD071") == 3

    def test_fix_available(self):
        df = parse("from ubuntu:22.04\n")
        issues = get_issues_for_rule(analyze(df), "DD071")
        assert issues[0].fix_available

    def test_comment_lines_ignored(self):
        df = parse("# from is fine in a comment\nFROM ubuntu:22.04\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD071")


# ===========================================================================
# DD072 — TODO/FIXME in Dockerfile comments
# ===========================================================================

class TestDD072TodoFixme:
    def test_triggers_on_todo(self):
        df = parse("FROM ubuntu:22.04\n# TODO: fix this later\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_triggers_on_fixme(self):
        df = parse("FROM ubuntu:22.04\n# FIXME: broken\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_triggers_on_hack(self):
        df = parse("FROM ubuntu:22.04\n# HACK workaround\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_triggers_on_xxx(self):
        df = parse("FROM ubuntu:22.04\n# XXX needs review\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_clean_without_markers(self):
        df = parse("FROM ubuntu:22.04\n# Install dependencies\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD072")

    def test_case_insensitive(self):
        df = parse("FROM ubuntu:22.04\n# todo: lowercase\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_multiple_markers(self):
        content = (
            "FROM ubuntu:22.04\n"
            "# TODO: first\n"
            "# FIXME: second\n"
            "RUN echo hi\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD072") == 2


# ===========================================================================
# DD073 — Missing final newline
# ===========================================================================

class TestDD073MissingFinalNewline:
    def test_triggers_when_no_final_newline(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi")
        issues = analyze(df)
        assert has_rule(issues, "DD073")

    def test_clean_with_final_newline(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD073")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04")
        issues = get_issues_for_rule(analyze(df), "DD073")
        assert issues[0].fix_available

    def test_single_line_no_newline(self):
        df = parse("FROM ubuntu:22.04")
        issues = analyze(df)
        assert has_rule(issues, "DD073")

    def test_multiple_trailing_newlines_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD073")


# ===========================================================================
# DD074 — Very long RUN line (>200 chars)
# ===========================================================================

class TestDD074LongRun:
    def test_triggers_on_long_run_line(self):
        # "RUN " = 4 chars, need 197 more to exceed 200
        long_cmd = "a" * 197
        content = f"FROM ubuntu:22.04\nRUN {long_cmd}\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD074")

    def test_clean_at_200_chars(self):
        # "RUN " = 4 chars + 196 = 200, threshold is >200 so exactly 200 is clean
        long_cmd = "a" * 196
        content = f"FROM ubuntu:22.04\nRUN {long_cmd}\n"
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD074")

    def test_clean_with_backslash_continuation(self):
        long_cmd = "a" * 197
        content = f"FROM ubuntu:22.04\nRUN {long_cmd} \\\n  && echo done\n"
        df = parse(content)
        issues = analyze(df)
        # Has backslash so should not trigger even though >200 chars
        assert not has_rule(issues, "DD074")

    def test_clean_short_run(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD074")

    def test_exactly_201_chars_triggers(self):
        # RUN + space = 4, need 197 more = 201 total
        long_cmd = "a" * 197
        content = f"FROM ubuntu:22.04\nRUN {long_cmd}\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD074")


# ===========================================================================
# DD075 — Trailing whitespace
# ===========================================================================

class TestDD075TrailingWhitespace:
    def test_triggers_on_trailing_space(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello   \n")
        issues = analyze(df)
        assert has_rule(issues, "DD075")

    def test_triggers_on_trailing_tab(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\t\n")
        issues = analyze(df)
        assert has_rule(issues, "DD075")

    def test_clean_without_trailing_whitespace(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD075")

    def test_backslash_continuation_not_flagged(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello \\\n  && echo world\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD075")

    def test_blank_lines_not_flagged(self):
        df = parse("FROM ubuntu:22.04\n   \nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD075")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04  \n")
        issues = get_issues_for_rule(analyze(df), "DD075")
        assert issues[0].fix_available


# ===========================================================================
# DD076 — Empty continuation line
# ===========================================================================

class TestDD076EmptyContinuation:
    def test_triggers_on_lone_backslash(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello \\\n\\\n  && echo world\n")
        issues = analyze(df)
        assert has_rule(issues, "DD076")

    def test_clean_with_content_before_backslash(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello \\\n  && echo world\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD076")

    def test_backslash_with_leading_spaces_no_trigger(self):
        """Leading whitespace before backslash means rstrip() != '\\', so no trigger."""
        df = parse("FROM ubuntu:22.04\nRUN echo hello \\\n  \\\n  && echo world\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD076")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\n\\\n")
        issues = get_issues_for_rule(analyze(df), "DD076")
        assert issues[0].fix_available

    def test_no_trigger_on_normal_dockerfile(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD076")


# ===========================================================================
# DD077 — Deprecated or EOL base image
# ===========================================================================

class TestDD077DeprecatedImage:
    def test_triggers_on_centos(self):
        df = parse("FROM centos:7\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_triggers_on_python2(self):
        df = parse("FROM python:2.7\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_triggers_on_node14(self):
        df = parse("FROM node:14\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_triggers_on_ubuntu_1604(self):
        df = parse("FROM ubuntu:16.04\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_triggers_on_debian_jessie(self):
        df = parse("FROM debian:jessie\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_clean_with_current_image(self):
        df = parse("FROM ubuntu:22.04\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD077")

    def test_clean_with_alpine(self):
        df = parse("FROM alpine:3.19\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD077")

    def test_triggers_on_node8(self):
        df = parse("FROM node:8\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_multistage_both_deprecated(self):
        content = "FROM centos:7 AS builder\nRUN echo hi\nFROM python:2.7\nRUN echo hi\n"
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD077") == 2


# ===========================================================================
# DD078 — Missing version LABEL
# ===========================================================================

class TestDD078LabelVersion:
    def test_triggers_when_labels_exist_but_no_version(self):
        content = "FROM ubuntu:22.04\nLABEL maintainer=\"test@test.com\"\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD078")

    def test_clean_with_version_label(self):
        content = 'FROM ubuntu:22.04\nLABEL version="1.0"\n'
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD078")

    def test_no_trigger_without_any_labels(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD078")

    def test_version_in_key_case_insensitive(self):
        content = 'FROM ubuntu:22.04\nLABEL Version="1.0"\n'
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD078")

    def test_org_opencontainers_version_label(self):
        content = 'FROM ubuntu:22.04\nLABEL org.opencontainers.image.version="2.0"\n'
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD078")


# ===========================================================================
# DD079 — Invalid STOPSIGNAL
# ===========================================================================

class TestDD079StopsignalInvalid:
    def test_triggers_on_invalid_signal_name(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL SIGFOO\n")
        issues = analyze(df)
        assert has_rule(issues, "DD079")

    def test_clean_with_sigterm(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL SIGTERM\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_clean_with_sigkill(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL SIGKILL\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_clean_with_numeric_signal(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 9\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_triggers_on_out_of_range_signal_high(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 65\n")
        issues = analyze(df)
        assert has_rule(issues, "DD079")

    def test_triggers_on_out_of_range_signal_zero(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 0\n")
        issues = analyze(df)
        assert has_rule(issues, "DD079")

    def test_clean_with_signal_64(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 64\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_clean_with_signal_1(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 1\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_case_insensitive_signal(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL sigterm\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_clean_with_sigusr1(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL SIGUSR1\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")


# ===========================================================================
# DD080 — VOLUME with invalid JSON syntax
# ===========================================================================

class TestDD080VolumeSyntax:
    def test_triggers_on_invalid_json_array(self):
        df = parse('FROM ubuntu:22.04\nVOLUME ["/data", /logs]\n')
        issues = analyze(df)
        assert has_rule(issues, "DD080")

    def test_clean_with_valid_json_array(self):
        df = parse('FROM ubuntu:22.04\nVOLUME ["/data", "/logs"]\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD080")

    def test_clean_with_space_separated_form(self):
        df = parse("FROM ubuntu:22.04\nVOLUME /data /logs\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD080")

    def test_clean_with_single_path(self):
        df = parse("FROM ubuntu:22.04\nVOLUME /data\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD080")

    def test_triggers_on_missing_closing_bracket(self):
        df = parse('FROM ubuntu:22.04\nVOLUME ["/data"\n')
        issues = analyze(df)
        assert has_rule(issues, "DD080")

    def test_clean_with_single_element_json(self):
        df = parse('FROM ubuntu:22.04\nVOLUME ["/data"]\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD080")

    def test_triggers_on_malformed_json_no_quotes(self):
        df = parse("FROM ubuntu:22.04\nVOLUME [/data]\n")
        issues = analyze(df)
        assert has_rule(issues, "DD080")
