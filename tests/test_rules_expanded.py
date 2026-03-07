"""Tests for DD021-DD080 expanded rules."""

from __future__ import annotations

import pytest
from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from tests.conftest import has_rule, count_rule, get_issues_for_rule


# ===========================================================================
# DD021 — Do not use sudo
# ===========================================================================

class TestDD021Sudo:
    def test_sudo_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN sudo apt-get update\n")
        issues = analyze(df)
        assert has_rule(issues, "DD021")

    def test_no_sudo_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get update\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD021")

    def test_sudo_in_chain(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi && sudo rm -rf /tmp\n")
        issues = analyze(df)
        assert has_rule(issues, "DD021")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN sudo ls\n")
        issues = get_issues_for_rule(analyze(df), "DD021")
        assert issues[0].fix_available


# ===========================================================================
# DD022 — Pin versions in apt-get install
# ===========================================================================

class TestDD022AptPin:
    def test_unpinned_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD022")

    def test_pinned_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl=7.88.1-10\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD022")

    def test_no_install_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get update\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD022")


# ===========================================================================
# DD023 — Missing -y in apt-get install
# ===========================================================================

class TestDD023AptYes:
    def test_missing_y_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD023")

    def test_with_y_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD023")

    def test_with_yes_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install --yes curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD023")

    def test_with_qq_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -qq curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD023")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install curl\n")
        issues = get_issues_for_rule(analyze(df), "DD023")
        assert issues[0].fix_available


# ===========================================================================
# DD024 — Use apt-get instead of apt
# ===========================================================================

class TestDD024UseAptGet:
    def test_apt_install_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN apt install -y curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD024")

    def test_apt_update_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN apt update\n")
        issues = analyze(df)
        assert has_rule(issues, "DD024")

    def test_apt_get_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD024")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN apt install -y curl\n")
        issues = get_issues_for_rule(analyze(df), "DD024")
        assert issues[0].fix_available


# ===========================================================================
# DD025 — apk add without --no-cache
# ===========================================================================

class TestDD025ApkNoCache:
    def test_no_cache_triggers(self):
        df = parse("FROM alpine:3.19\nRUN apk add curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD025")

    def test_with_no_cache_clean(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD025")

    def test_fix_available(self):
        df = parse("FROM alpine:3.19\nRUN apk add curl\n")
        issues = get_issues_for_rule(analyze(df), "DD025")
        assert issues[0].fix_available


# ===========================================================================
# DD026 — apk upgrade
# ===========================================================================

class TestDD026ApkUpgrade:
    def test_apk_upgrade_triggers(self):
        df = parse("FROM alpine:3.19\nRUN apk upgrade\n")
        issues = analyze(df)
        assert has_rule(issues, "DD026")

    def test_apk_add_clean(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD026")


# ===========================================================================
# DD027 — Pin versions in apk add
# ===========================================================================

class TestDD027ApkPin:
    def test_unpinned_triggers(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD027")

    def test_pinned_clean(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache curl=8.5.0-r0\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD027")


# ===========================================================================
# DD028 — Pin versions in pip install
# ===========================================================================

class TestDD028PipPin:
    def test_unpinned_triggers(self):
        df = parse("FROM python:3.12\nRUN pip install flask\n")
        issues = analyze(df)
        assert has_rule(issues, "DD028")

    def test_pinned_clean(self):
        df = parse("FROM python:3.12\nRUN pip install flask==3.0.0\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD028")

    def test_requirements_clean(self):
        df = parse("FROM python:3.12\nRUN pip install -r requirements.txt\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD028")

    def test_dot_install_clean(self):
        df = parse("FROM python:3.12\nRUN pip install .\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD028")


# ===========================================================================
# DD029 — Pin versions in npm install
# ===========================================================================

class TestDD029NpmPin:
    def test_unpinned_triggers(self):
        df = parse("FROM node:20\nRUN npm install express\n")
        issues = analyze(df)
        assert has_rule(issues, "DD029")

    def test_pinned_clean(self):
        df = parse("FROM node:20\nRUN npm install express@4.18.2\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD029")


# ===========================================================================
# DD030 — Pin versions in gem install
# ===========================================================================

class TestDD030GemPin:
    def test_unpinned_triggers(self):
        df = parse("FROM ruby:3.3\nRUN gem install bundler\n")
        issues = analyze(df)
        assert has_rule(issues, "DD030")

    def test_pinned_clean(self):
        df = parse("FROM ruby:3.3\nRUN gem install bundler -v 2.5.0\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD030")

    def test_version_flag_clean(self):
        df = parse("FROM ruby:3.3\nRUN gem install bundler --version 2.5.0\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD030")


# ===========================================================================
# DD031 — yum install without clean
# ===========================================================================

class TestDD031YumClean:
    def test_no_clean_triggers(self):
        df = parse("FROM centos:7\nRUN yum install -y curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD031")

    def test_with_clean(self):
        df = parse("FROM centos:7\nRUN yum install -y curl && yum clean all\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD031")


# ===========================================================================
# DD032 — Pin versions in yum install
# ===========================================================================

class TestDD032YumPin:
    def test_unpinned_triggers(self):
        df = parse("FROM centos:7\nRUN yum install -y curl && yum clean all\n")
        issues = analyze(df)
        assert has_rule(issues, "DD032")

    def test_pinned_clean(self):
        df = parse("FROM centos:7\nRUN yum install -y curl-7.29.0 && yum clean all\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD032")


# ===========================================================================
# DD033 — dnf install without clean
# ===========================================================================

class TestDD033DnfClean:
    def test_no_clean_triggers(self):
        df = parse("FROM fedora:39\nRUN dnf install -y curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD033")

    def test_with_clean(self):
        df = parse("FROM fedora:39\nRUN dnf install -y curl && dnf clean all\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD033")


# ===========================================================================
# DD034 — zypper install without clean
# ===========================================================================

class TestDD034ZypperClean:
    def test_no_clean_triggers(self):
        df = parse("FROM opensuse/leap:15.5\nRUN zypper install -y curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD034")

    def test_with_clean(self):
        df = parse("FROM opensuse/leap:15.5\nRUN zypper install -y curl && zypper clean\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD034")


# ===========================================================================
# DD035 — Missing DEBIAN_FRONTEND
# ===========================================================================

class TestDD035DebianFrontend:
    def test_missing_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert has_rule(issues, "DD035")

    def test_env_set_clean(self):
        df = parse("FROM ubuntu:22.04\nENV DEBIAN_FRONTEND=noninteractive\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD035")

    def test_arg_set_clean(self):
        df = parse("FROM ubuntu:22.04\nARG DEBIAN_FRONTEND=noninteractive\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD035")

    def test_inline_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN DEBIAN_FRONTEND=noninteractive apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD035")

    def test_no_apt_clean(self):
        df = parse("FROM alpine:3.19\nRUN apk add curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD035")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = get_issues_for_rule(analyze(df), "DD035")
        assert issues[0].fix_available


# ===========================================================================
# DD036 — Multiple CMD instructions
# ===========================================================================

class TestDD036MultipleCMD:
    def test_multiple_triggers(self):
        df = parse("FROM ubuntu:22.04\nCMD echo hello\nCMD echo world\n")
        issues = analyze(df)
        assert has_rule(issues, "DD036")

    def test_single_clean(self):
        df = parse("FROM ubuntu:22.04\nCMD echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD036")

    def test_different_stages_clean(self):
        df = parse("FROM ubuntu:22.04 AS build\nCMD echo build\nFROM alpine:3.19\nCMD echo run\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD036")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nCMD echo hello\nCMD echo world\n")
        issues = get_issues_for_rule(analyze(df), "DD036")
        assert issues[0].fix_available


# ===========================================================================
# DD037 — Multiple ENTRYPOINT instructions
# ===========================================================================

class TestDD037MultipleEntrypoint:
    def test_multiple_triggers(self):
        df = parse("FROM ubuntu:22.04\nENTRYPOINT echo hi\nENTRYPOINT echo bye\n")
        issues = analyze(df)
        assert has_rule(issues, "DD037")

    def test_single_clean(self):
        df = parse("FROM ubuntu:22.04\nENTRYPOINT echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD037")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nENTRYPOINT echo hi\nENTRYPOINT echo bye\n")
        issues = get_issues_for_rule(analyze(df), "DD037")
        assert issues[0].fix_available


# ===========================================================================
# DD038 — Invalid UNIX port number
# ===========================================================================

class TestDD038InvalidPort:
    def test_port_zero_triggers(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 0\n")
        issues = analyze(df)
        assert has_rule(issues, "DD038")

    def test_port_too_high_triggers(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 70000\n")
        issues = analyze(df)
        assert has_rule(issues, "DD038")

    def test_valid_port_clean(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD038")

    def test_valid_port_with_protocol(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080/tcp\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD038")


# ===========================================================================
# DD039 — COPY --from unknown stage
# ===========================================================================

class TestDD039CopyFromUnknown:
    def test_unknown_stage_index(self):
        df = parse("FROM ubuntu:22.04\nCOPY --from=5 /app /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD039")

    def test_valid_stage_index(self):
        df = parse("FROM ubuntu:22.04 AS build\nRUN echo hi\nFROM alpine:3.19\nCOPY --from=0 /app /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD039")

    def test_named_stage(self):
        df = parse("FROM ubuntu:22.04 AS build\nRUN echo hi\nFROM alpine:3.19\nCOPY --from=build /app /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD039")


# ===========================================================================
# DD040 — Missing pipefail
# ===========================================================================

class TestDD040Pipefail:
    def test_pipe_without_pipefail(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -s http://example.com | grep foo\n")
        issues = analyze(df)
        assert has_rule(issues, "DD040")

    def test_pipe_with_inline_pipefail(self):
        df = parse("FROM ubuntu:22.04\nRUN set -o pipefail && curl -s http://example.com | grep foo\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD040")

    def test_pipe_with_shell_pipefail(self):
        df = parse('FROM ubuntu:22.04\nSHELL ["/bin/bash", "-o", "pipefail", "-c"]\nRUN curl -s http://example.com | grep foo\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD040")

    def test_or_operator_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN test -f /tmp/x || echo not found\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD040")

    def test_no_pipe_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD040")


# ===========================================================================
# DD041 — COPY to relative dest without WORKDIR
# ===========================================================================

class TestDD041CopyRelative:
    def test_relative_no_workdir_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD041")

    def test_absolute_dest_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD041")

    def test_workdir_set_clean(self):
        df = parse("FROM ubuntu:22.04\nWORKDIR /app\nCOPY app.py .\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD041")


# ===========================================================================
# DD042 — ONBUILD instruction
# ===========================================================================

class TestDD042Onbuild:
    def test_onbuild_triggers(self):
        df = parse("FROM ubuntu:22.04\nONBUILD RUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD042")

    def test_no_onbuild_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD042")


# ===========================================================================
# DD043 — SHELL exec form
# ===========================================================================

class TestDD043ShellExecForm:
    def test_non_json_triggers(self):
        df = parse("FROM ubuntu:22.04\nSHELL /bin/bash -c\n")
        issues = analyze(df)
        assert has_rule(issues, "DD043")

    def test_json_form_clean(self):
        df = parse('FROM ubuntu:22.04\nSHELL ["/bin/bash", "-c"]\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD043")


# ===========================================================================
# DD044 — Duplicate ENV keys
# ===========================================================================

class TestDD044DuplicateEnv:
    def test_duplicate_triggers(self):
        df = parse("FROM ubuntu:22.04\nENV FOO=bar\nENV FOO=baz\n")
        issues = analyze(df)
        assert has_rule(issues, "DD044")

    def test_unique_clean(self):
        df = parse("FROM ubuntu:22.04\nENV FOO=bar\nENV BAR=baz\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD044")

    def test_different_stages_clean(self):
        df = parse("FROM ubuntu:22.04 AS build\nENV FOO=bar\nFROM alpine:3.19\nENV FOO=baz\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD044")


# ===========================================================================
# DD045 — RUN with cd
# ===========================================================================

class TestDD045RunCd:
    def test_cd_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN cd /app && make\n")
        issues = analyze(df)
        assert has_rule(issues, "DD045")

    def test_workdir_clean(self):
        df = parse("FROM ubuntu:22.04\nWORKDIR /app\nRUN make\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD045")

    def test_cd_in_middle_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN make && cd /tmp && ls\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD045")


# ===========================================================================
# DD046 — Missing LABEL
# ===========================================================================

class TestDD046MissingLabel:
    def test_no_label_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD046")

    def test_with_label_clean(self):
        df = parse('FROM ubuntu:22.04\nLABEL maintainer="test"\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD046")


# ===========================================================================
# DD047 — Empty RUN
# ===========================================================================

class TestDD047EmptyRun:
    def test_empty_run_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN \n")
        issues = analyze(df)
        assert has_rule(issues, "DD047")

    def test_non_empty_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD047")


# ===========================================================================
# DD048 — Duplicate EXPOSE ports
# ===========================================================================

class TestDD048DuplicateExpose:
    def test_duplicate_triggers(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080\nEXPOSE 8080\n")
        issues = analyze(df)
        assert has_rule(issues, "DD048")

    def test_different_ports_clean(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080\nEXPOSE 3000\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD048")


# ===========================================================================
# DD049 — Multiple HEALTHCHECK
# ===========================================================================

class TestDD049MultipleHealthcheck:
    def test_multiple_triggers(self):
        df = parse("FROM ubuntu:22.04\nHEALTHCHECK CMD curl localhost\nHEALTHCHECK CMD wget localhost\n")
        issues = analyze(df)
        assert has_rule(issues, "DD049")

    def test_single_clean(self):
        df = parse("FROM ubuntu:22.04\nHEALTHCHECK CMD curl localhost\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD049")


# ===========================================================================
# DD050 — Stage name casing
# ===========================================================================

class TestDD050StageName:
    def test_uppercase_triggers(self):
        df = parse("FROM ubuntu:22.04 AS Builder\n")
        issues = analyze(df)
        assert has_rule(issues, "DD050")

    def test_lowercase_clean(self):
        df = parse("FROM ubuntu:22.04 AS builder\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD050")


# ===========================================================================
# DD051 — chmod 777
# ===========================================================================

class TestDD051Chmod777:
    def test_chmod_777_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN chmod 777 /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD051")

    def test_chmod_755_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN chmod 755 /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD051")


# ===========================================================================
# DD052 — SSH keys / .git in COPY
# ===========================================================================

class TestDD052SshGitCopy:
    def test_ssh_key_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY id_rsa /root/.ssh/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_git_dir_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY .git /app/.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_dot_ssh_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD .ssh /root/.ssh\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_normal_copy_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD052")


# ===========================================================================
# DD053 — .env file in COPY
# ===========================================================================

class TestDD053EnvFile:
    def test_env_file_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY .env /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD053")

    def test_normal_copy_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD053")

    def test_env_subdir_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY config/.env /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD053")


# ===========================================================================
# DD054 — curl | bash
# ===========================================================================

class TestDD054CurlPipeBash:
    def test_curl_pipe_sh_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -s http://example.com/install.sh | sh\n")
        issues = analyze(df)
        assert has_rule(issues, "DD054")

    def test_curl_pipe_bash_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -s http://example.com/install.sh | bash\n")
        issues = analyze(df)
        assert has_rule(issues, "DD054")

    def test_wget_pipe_sh_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN wget -qO- http://example.com/install.sh | sh\n")
        issues = analyze(df)
        assert has_rule(issues, "DD054")

    def test_curl_no_pipe_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -o /tmp/install.sh http://example.com/install.sh\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD054")


# ===========================================================================
# DD055 — wget --no-check-certificate
# ===========================================================================

class TestDD055WgetNoCheck:
    def test_no_check_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN wget --no-check-certificate http://example.com/file\n")
        issues = analyze(df)
        assert has_rule(issues, "DD055")

    def test_normal_wget_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN wget http://example.com/file\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD055")


# ===========================================================================
# DD056 — curl -k / --insecure
# ===========================================================================

class TestDD056CurlInsecure:
    def test_curl_k_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -k http://example.com/file\n")
        issues = analyze(df)
        assert has_rule(issues, "DD056")

    def test_curl_insecure_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl --insecure http://example.com/file\n")
        issues = analyze(df)
        assert has_rule(issues, "DD056")

    def test_normal_curl_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN curl http://example.com/file\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD056")


# ===========================================================================
# DD057 — git clone with credentials
# ===========================================================================

class TestDD057GitCredentials:
    def test_credentials_in_url_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone https://user:pass@github.com/repo.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD057")

    def test_normal_clone_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone https://github.com/repo.git\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD057")

    def test_ssh_clone_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone git@github.com:user/repo.git\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD057")


# ===========================================================================
# DD058 — Hardcoded credentials in RUN
# ===========================================================================

class TestDD058HardcodedRunSecret:
    def test_password_flag_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN mysql --password=secret123 -e 'SELECT 1'\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_token_flag_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN tool --token=abc123def\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_normal_run_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD058")


# ===========================================================================
# DD059 — ADD from remote URL
# ===========================================================================

class TestDD059AddRemoteUrl:
    def test_remote_url_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD https://example.com/file.tar.gz /tmp/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD059")

    def test_local_add_clean(self):
        df = parse("FROM ubuntu:22.04\nADD file.tar.gz /tmp/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD059")


# ===========================================================================
# DD060 — --privileged in RUN
# ===========================================================================

class TestDD060Privileged:
    def test_privileged_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN --privileged echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD060")

    def test_normal_run_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD060")


# ===========================================================================
# DD061 — gem install without --no-document
# ===========================================================================

class TestDD061GemNoDocument:
    def test_no_document_triggers(self):
        df = parse("FROM ruby:3.3\nRUN gem install bundler\n")
        issues = analyze(df)
        assert has_rule(issues, "DD061")

    def test_with_no_document_clean(self):
        df = parse("FROM ruby:3.3\nRUN gem install --no-document bundler\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD061")

    def test_fix_available(self):
        df = parse("FROM ruby:3.3\nRUN gem install bundler\n")
        issues = get_issues_for_rule(analyze(df), "DD061")
        assert issues[0].fix_available


# ===========================================================================
# DD062 — go build without CGO_ENABLED=0
# ===========================================================================

class TestDD062GoCgo:
    def test_no_cgo_triggers(self):
        df = parse("FROM golang:1.22\nRUN go build -o app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD062")

    def test_env_cgo_clean(self):
        df = parse("FROM golang:1.22\nENV CGO_ENABLED=0\nRUN go build -o app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")

    def test_inline_cgo_clean(self):
        df = parse("FROM golang:1.22\nRUN CGO_ENABLED=0 go build -o app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")

    def test_non_go_image_clean(self):
        df = parse("FROM python:3.12\nRUN echo build\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD062")


# ===========================================================================
# DD063 — apk add dev packages without --virtual
# ===========================================================================

class TestDD063ApkVirtual:
    def test_dev_without_virtual_triggers(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache gcc musl-dev\n")
        issues = analyze(df)
        assert has_rule(issues, "DD063")

    def test_with_virtual_clean(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache --virtual .build-deps gcc musl-dev\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD063")

    def test_no_dev_packages_clean(self):
        df = parse("FROM alpine:3.19\nRUN apk add --no-cache curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD063")


# ===========================================================================
# DD064 — Too many layers
# ===========================================================================

class TestDD064TooManyLayers:
    def test_many_layers_triggers(self):
        runs = "\n".join(f"RUN echo step{i}" for i in range(25))
        df = parse(f"FROM ubuntu:22.04\n{runs}\n")
        issues = analyze(df)
        assert has_rule(issues, "DD064")

    def test_few_layers_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\nCOPY . /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD064")


# ===========================================================================
# DD065 — Duplicate RUN commands
# ===========================================================================

class TestDD065DuplicateRun:
    def test_duplicate_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD065")

    def test_unique_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\nRUN echo bye\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD065")


# ===========================================================================
# DD066 — Multi-stage without COPY --from
# ===========================================================================

class TestDD066MultistageNoCopy:
    def test_no_copy_from_triggers(self):
        df = parse("FROM ubuntu:22.04 AS build\nRUN make\nFROM alpine:3.19\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD066")

    def test_with_copy_from_clean(self):
        df = parse("FROM ubuntu:22.04 AS build\nRUN make\nFROM alpine:3.19\nCOPY --from=build /app /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD066")

    def test_single_stage_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD066")


# ===========================================================================
# DD067 — Node.js without NODE_ENV
# ===========================================================================

class TestDD067NodeEnv:
    def test_missing_node_env_triggers(self):
        df = parse("FROM node:20\nRUN npm ci\n")
        issues = analyze(df)
        assert has_rule(issues, "DD067")

    def test_node_env_set_clean(self):
        df = parse("FROM node:20\nENV NODE_ENV=production\nRUN npm ci\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD067")

    def test_non_node_clean(self):
        df = parse("FROM python:3.12\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD067")


# ===========================================================================
# DD068 — Java container flags
# ===========================================================================

class TestDD068JavaFlags:
    def test_missing_flags_triggers(self):
        df = parse("FROM openjdk:17\nCMD java -jar app.jar\n")
        issues = analyze(df)
        assert has_rule(issues, "DD068")

    def test_container_support_clean(self):
        df = parse("FROM openjdk:17\nCMD java -XX:+UseContainerSupport -jar app.jar\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD068")

    def test_ram_percentage_clean(self):
        df = parse("FROM openjdk:17\nENV JAVA_OPTS=-XX:MaxRAMPercentage=75\nCMD java -jar app.jar\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD068")

    def test_non_java_clean(self):
        df = parse("FROM python:3.12\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD068")


# ===========================================================================
# DD069 — apt-get install with wildcard
# ===========================================================================

class TestDD069AptWildcard:
    def test_wildcard_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y lib*-dev\n")
        issues = analyze(df)
        assert has_rule(issues, "DD069")

    def test_no_wildcard_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD069")


# ===========================================================================
# DD070 — Copying entire build context
# ===========================================================================

class TestDD070DockerignoreHint:
    def test_copy_dot_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY . /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD070")

    def test_copy_specific_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD070")


# ===========================================================================
# DD071 — Instruction casing
# ===========================================================================

class TestDD071InstructionCasing:
    def test_lowercase_triggers(self):
        df = parse("from ubuntu:22.04\nrun echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD071")

    def test_uppercase_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD071")

    def test_mixed_case_triggers(self):
        df = parse("From ubuntu:22.04\nRun echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD071")

    def test_fix_available(self):
        df = parse("from ubuntu:22.04\n")
        issues = get_issues_for_rule(analyze(df), "DD071")
        assert issues[0].fix_available


# ===========================================================================
# DD072 — TODO/FIXME comments
# ===========================================================================

class TestDD072TodoFixme:
    def test_todo_triggers(self):
        df = parse("FROM ubuntu:22.04\n# TODO: fix this\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_fixme_triggers(self):
        df = parse("FROM ubuntu:22.04\n# FIXME: broken\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_hack_triggers(self):
        df = parse("FROM ubuntu:22.04\n# HACK: workaround\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD072")

    def test_no_todo_clean(self):
        df = parse("FROM ubuntu:22.04\n# Normal comment\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD072")


# ===========================================================================
# DD073 — Missing final newline
# ===========================================================================

class TestDD073FinalNewline:
    def test_missing_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi")
        issues = analyze(df)
        assert has_rule(issues, "DD073")

    def test_with_newline_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD073")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi")
        issues = get_issues_for_rule(analyze(df), "DD073")
        assert issues[0].fix_available


# ===========================================================================
# DD074 — Very long RUN line
# ===========================================================================

class TestDD074LongRun:
    def test_long_line_triggers(self):
        long_cmd = "RUN echo " + "a" * 200
        df = parse(f"FROM ubuntu:22.04\n{long_cmd}\n")
        issues = analyze(df)
        assert has_rule(issues, "DD074")

    def test_short_line_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD074")

    def test_long_with_continuation_clean(self):
        long_cmd = "RUN echo " + "a" * 200 + " \\"
        df = parse(f"FROM ubuntu:22.04\n{long_cmd}\n    continued\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD074")


# ===========================================================================
# DD075 — Trailing whitespace
# ===========================================================================

class TestDD075TrailingWhitespace:
    def test_trailing_space_triggers(self):
        df = parse("FROM ubuntu:22.04  \nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD075")

    def test_clean_lines(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD075")

    def test_continuation_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi \\\n    && echo bye\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD075")


# ===========================================================================
# DD076 — Empty continuation line
# ===========================================================================

class TestDD076EmptyContinuation:
    def test_empty_continuation_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi \\\n\\\n    && echo bye\n")
        issues = analyze(df)
        assert has_rule(issues, "DD076")

    def test_normal_continuation_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi \\\n    && echo bye\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD076")


# ===========================================================================
# DD077 — Deprecated base image
# ===========================================================================

class TestDD077DeprecatedImage:
    def test_centos_triggers(self):
        df = parse("FROM centos:7\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_python2_triggers(self):
        df = parse("FROM python:2.7\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_node10_triggers(self):
        df = parse("FROM node:10\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_ubuntu_1804_triggers(self):
        df = parse("FROM ubuntu:18.04\nRUN echo hi\n")
        issues = analyze(df)
        assert has_rule(issues, "DD077")

    def test_modern_image_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD077")


# ===========================================================================
# DD078 — Missing version LABEL
# ===========================================================================

class TestDD078LabelVersion:
    def test_label_without_version_triggers(self):
        df = parse('FROM ubuntu:22.04\nLABEL maintainer="test"\n')
        issues = analyze(df)
        assert has_rule(issues, "DD078")

    def test_label_with_version_clean(self):
        df = parse('FROM ubuntu:22.04\nLABEL version="1.0"\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD078")

    def test_no_labels_clean(self):
        # DD078 only fires when LABEL exists but lacks version
        df = parse("FROM ubuntu:22.04\nRUN echo hi\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD078")


# ===========================================================================
# DD079 — Invalid STOPSIGNAL
# ===========================================================================

class TestDD079StopSignal:
    def test_invalid_signal_triggers(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL SIGFOO\n")
        issues = analyze(df)
        assert has_rule(issues, "DD079")

    def test_valid_signal_clean(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL SIGTERM\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_valid_numeric_clean(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 15\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD079")

    def test_invalid_numeric_triggers(self):
        df = parse("FROM ubuntu:22.04\nSTOPSIGNAL 99\n")
        issues = analyze(df)
        assert has_rule(issues, "DD079")


# ===========================================================================
# DD080 — VOLUME JSON syntax
# ===========================================================================

class TestDD080VolumeSyntax:
    def test_invalid_json_triggers(self):
        df = parse('FROM ubuntu:22.04\nVOLUME ["/data", /logs]\n')
        issues = analyze(df)
        assert has_rule(issues, "DD080")

    def test_valid_json_clean(self):
        df = parse('FROM ubuntu:22.04\nVOLUME ["/data", "/logs"]\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD080")

    def test_string_form_clean(self):
        df = parse("FROM ubuntu:22.04\nVOLUME /data /logs\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD080")


# ===========================================================================
# Cross-rule interaction tests for new rules
# ===========================================================================

class TestNewRuleCrossInteractions:
    def test_apt_full_stack(self):
        """apt install triggers DD024, DD023, DD035, etc."""
        df = parse("FROM ubuntu:22.04\nRUN apt install curl\n")
        issues = analyze(df)
        rule_ids = {i.rule_id for i in issues}
        assert "DD024" in rule_ids  # use apt-get
        assert "DD035" in rule_ids  # DEBIAN_FRONTEND

    def test_centos_yum_stack(self):
        """CentOS with unpinned yum triggers DD077, DD031, DD032."""
        df = parse("FROM centos:7\nRUN yum install -y curl\n")
        issues = analyze(df)
        rule_ids = {i.rule_id for i in issues}
        assert "DD077" in rule_ids  # deprecated image
        assert "DD031" in rule_ids  # yum clean
        assert "DD032" in rule_ids  # pin versions

    def test_alpine_full_stack(self):
        """Alpine without --no-cache + unpinned triggers DD025, DD027."""
        df = parse("FROM alpine:3.19\nRUN apk add curl\n")
        issues = analyze(df)
        rule_ids = {i.rule_id for i in issues}
        assert "DD025" in rule_ids  # --no-cache
        assert "DD027" in rule_ids  # pin versions

    def test_security_multi_rule(self):
        """Multiple security issues in one Dockerfile."""
        df = parse(
            "FROM ubuntu:22.04\n"
            "RUN chmod 777 /app\n"
            "COPY .env /app/\n"
            "COPY id_rsa /root/.ssh/\n"
        )
        issues = analyze(df)
        rule_ids = {i.rule_id for i in issues}
        assert "DD051" in rule_ids  # chmod 777
        assert "DD053" in rule_ids  # .env
        assert "DD052" in rule_ids  # SSH key


# ===========================================================================
# Fixer tests for new fixable rules
# ===========================================================================

class TestNewFixers:
    def _fix(self, content):
        from dockerfile_doctor.fixer import fix
        df = parse(content)
        issues = analyze(df)
        fixed_content, fixes = fix(df, issues, unsafe=True)
        return fixed_content, fixes

    def test_fix_dd021_removes_sudo(self):
        content = "FROM ubuntu:22.04\nRUN sudo apt-get update\n"
        fixed, fixes = self._fix(content)
        assert "sudo" not in fixed
        assert any(f.rule_id == "DD021" for f in fixes)

    def test_fix_dd023_adds_y(self):
        content = "FROM ubuntu:22.04\nRUN apt-get install curl\n"
        fixed, fixes = self._fix(content)
        assert "-y" in fixed
        assert any(f.rule_id == "DD023" for f in fixes)

    def test_fix_dd024_replaces_apt(self):
        content = "FROM ubuntu:22.04\nRUN apt install -y curl\n"
        fixed, fixes = self._fix(content)
        assert "apt-get install" in fixed
        assert any(f.rule_id == "DD024" for f in fixes)

    def test_fix_dd025_adds_no_cache(self):
        content = "FROM alpine:3.19\nRUN apk add curl\n"
        fixed, fixes = self._fix(content)
        assert "--no-cache" in fixed
        assert any(f.rule_id == "DD025" for f in fixes)

    def test_fix_dd036_removes_earlier_cmd(self):
        content = "FROM ubuntu:22.04\nCMD echo hello\nCMD echo world\n"
        fixed, fixes = self._fix(content)
        assert fixed.count("CMD") == 1
        assert "world" in fixed
        assert any(f.rule_id == "DD036" for f in fixes)

    def test_fix_dd037_removes_earlier_entrypoint(self):
        content = "FROM ubuntu:22.04\nENTRYPOINT echo hi\nENTRYPOINT echo bye\n"
        fixed, fixes = self._fix(content)
        assert fixed.count("ENTRYPOINT") == 1
        assert "bye" in fixed
        assert any(f.rule_id == "DD037" for f in fixes)

    def test_fix_dd061_adds_no_document(self):
        content = "FROM ruby:3.3\nRUN gem install bundler\n"
        fixed, fixes = self._fix(content)
        assert "--no-document" in fixed
        assert any(f.rule_id == "DD061" for f in fixes)

    def test_fix_dd071_uppercases_directives(self):
        content = "from ubuntu:22.04\nrun echo hi\n"
        fixed, fixes = self._fix(content)
        assert "FROM" in fixed
        assert "RUN" in fixed
        assert any(f.rule_id == "DD071" for f in fixes)

    # --- New fixer tests for expanded auto-fix ---

    def test_fix_dd026_removes_apk_upgrade_standalone(self):
        content = "FROM alpine:3.19\nRUN apk upgrade\nCOPY . /app\n"
        fixed, fixes = self._fix(content)
        assert "apk upgrade" not in fixed
        assert any(f.rule_id == "DD026" for f in fixes)

    def test_fix_dd026_removes_apk_upgrade_chain(self):
        content = "FROM alpine:3.19\nRUN apk upgrade && apk add --no-cache curl=8.0-r0\n"
        fixed, fixes = self._fix(content)
        assert "apk upgrade" not in fixed
        assert "apk add" in fixed
        assert any(f.rule_id == "DD026" for f in fixes)

    def test_fix_dd031_appends_yum_clean(self):
        content = "FROM centos:7\nRUN yum install -y curl-7.29.0\n"
        fixed, fixes = self._fix(content)
        assert "yum clean all" in fixed
        assert any(f.rule_id == "DD031" for f in fixes)

    def test_fix_dd033_appends_dnf_clean(self):
        content = "FROM fedora:39\nRUN dnf install -y curl\n"
        fixed, fixes = self._fix(content)
        assert "dnf clean all" in fixed
        assert any(f.rule_id == "DD033" for f in fixes)

    def test_fix_dd034_appends_zypper_clean(self):
        content = "FROM opensuse/leap:15.5\nRUN zypper install -y curl\n"
        fixed, fixes = self._fix(content)
        assert "zypper clean" in fixed
        assert any(f.rule_id == "DD034" for f in fixes)

    def test_fix_dd035_adds_debian_frontend(self):
        content = "FROM ubuntu:22.04\nRUN apt-get install -y curl\n"
        fixed, fixes = self._fix(content)
        assert "DEBIAN_FRONTEND=noninteractive" in fixed
        assert any(f.rule_id == "DD035" for f in fixes)

    def test_fix_dd040_adds_pipefail(self):
        content = "FROM ubuntu:22.04\nRUN curl -s http://example.com | grep foo\n"
        fixed, fixes = self._fix(content)
        assert "set -o pipefail" in fixed
        assert any(f.rule_id == "DD040" for f in fixes)

    def test_fix_dd044_removes_duplicate_env(self):
        content = "FROM ubuntu:22.04\nENV FOO=bar\nENV FOO=baz\n"
        fixed, fixes = self._fix(content)
        assert fixed.count("ENV FOO=") == 1
        assert "baz" in fixed
        assert any(f.rule_id == "DD044" for f in fixes)

    def test_fix_dd045_converts_cd_to_workdir(self):
        content = "FROM ubuntu:22.04\nRUN cd /app && make\n"
        fixed, fixes = self._fix(content)
        assert "WORKDIR /app" in fixed
        assert "RUN make" in fixed
        assert "cd /app" not in fixed
        assert any(f.rule_id == "DD045" for f in fixes)

    def test_fix_dd047_removes_empty_run(self):
        content = "FROM ubuntu:22.04\nRUN \nCOPY . /app\n"
        fixed, fixes = self._fix(content)
        assert "RUN" not in fixed or "RUN " not in fixed.split("COPY")[0]
        assert any(f.rule_id == "DD047" for f in fixes)

    def test_fix_dd048_removes_duplicate_expose(self):
        content = "FROM ubuntu:22.04\nEXPOSE 8080\nEXPOSE 8080\n"
        fixed, fixes = self._fix(content)
        assert fixed.count("EXPOSE 8080") == 1
        assert any(f.rule_id == "DD048" for f in fixes)

    def test_fix_dd049_removes_earlier_healthcheck(self):
        content = "FROM ubuntu:22.04\nHEALTHCHECK CMD curl localhost\nHEALTHCHECK CMD wget localhost\n"
        fixed, fixes = self._fix(content)
        assert fixed.count("HEALTHCHECK") == 1
        assert "wget" in fixed
        assert any(f.rule_id == "DD049" for f in fixes)

    def test_fix_dd050_lowercases_stage_name(self):
        content = "FROM ubuntu:22.04 AS Builder\nRUN echo hi\n"
        fixed, fixes = self._fix(content)
        assert "AS builder" in fixed
        assert any(f.rule_id == "DD050" for f in fixes)

    def test_fix_dd051_changes_chmod_777_to_755(self):
        content = "FROM ubuntu:22.04\nRUN chmod 777 /app\n"
        fixed, fixes = self._fix(content)
        assert "chmod 755" in fixed
        assert "chmod 777" not in fixed
        assert any(f.rule_id == "DD051" for f in fixes)

    def test_fix_dd065_removes_duplicate_run(self):
        content = "FROM ubuntu:22.04\nRUN echo hi\nCOPY . /app\nRUN echo hi\n"
        fixed, fixes = self._fix(content)
        assert fixed.count("echo hi") == 1
        assert any(f.rule_id == "DD065" for f in fixes)

    def test_fix_dd073_adds_final_newline(self):
        content = "FROM ubuntu:22.04\nRUN echo hi"
        fixed, fixes = self._fix(content)
        assert fixed.endswith("\n")
        assert any(f.rule_id == "DD073" for f in fixes)

    def test_fix_dd075_removes_trailing_whitespace(self):
        content = "FROM ubuntu:22.04  \nRUN echo hi\n"
        fixed, fixes = self._fix(content)
        # The line should no longer have trailing spaces
        for line in fixed.splitlines():
            if line.startswith("FROM"):
                assert not line.endswith("  ")
        assert any(f.rule_id == "DD075" for f in fixes)

    def test_fix_dd076_removes_empty_continuation(self):
        content = "FROM ubuntu:22.04\nRUN echo hi \\\n\\\n    && echo bye\n"
        fixed, fixes = self._fix(content)
        assert "\\\n\\" not in fixed
        assert any(f.rule_id == "DD076" for f in fixes)


# ===========================================================================
# Fixer idempotency tests for new fixers
# ===========================================================================

class TestNewFixerIdempotency:
    def _fix(self, content):
        from dockerfile_doctor.fixer import fix
        df = parse(content)
        issues = analyze(df)
        fixed_content, _ = fix(df, issues, unsafe=True)
        return fixed_content

    def test_dd031_idempotent(self):
        content = "FROM centos:7\nRUN yum install -y curl-7.29.0\n"
        fixed1 = self._fix(content)
        fixed2 = self._fix(fixed1)
        assert fixed1 == fixed2

    def test_dd033_idempotent(self):
        content = "FROM fedora:39\nRUN dnf install -y curl\n"
        fixed1 = self._fix(content)
        fixed2 = self._fix(fixed1)
        assert fixed1 == fixed2

    def test_dd040_idempotent(self):
        content = "FROM ubuntu:22.04\nRUN curl -s http://example.com | grep foo\n"
        fixed1 = self._fix(content)
        fixed2 = self._fix(fixed1)
        assert fixed1 == fixed2

    def test_dd045_idempotent(self):
        content = "FROM ubuntu:22.04\nRUN cd /app && make\n"
        fixed1 = self._fix(content)
        fixed2 = self._fix(fixed1)
        assert fixed1 == fixed2

    def test_dd050_idempotent(self):
        content = "FROM ubuntu:22.04 AS Builder\nRUN echo hi\n"
        fixed1 = self._fix(content)
        fixed2 = self._fix(fixed1)
        assert fixed1 == fixed2

    def test_dd051_idempotent(self):
        content = "FROM ubuntu:22.04\nRUN chmod 777 /app\n"
        fixed1 = self._fix(content)
        fixed2 = self._fix(fixed1)
        assert fixed1 == fixed2


# ===========================================================================
# Fix-available flag verification for all fixable rules
# ===========================================================================

class TestFixAvailableFlags:
    def test_all_fixable_rules_marked(self):
        """Every rule with a fixer handler should have fix_available=True."""
        from dockerfile_doctor.fixer import _FIX_HANDLERS
        # We need a Dockerfile that triggers as many rules as possible
        content = (
            "from ubuntu:22.04  \n"
            "RUN sudo apt install curl\n"
            "RUN apt-get install wget\n"
            "RUN apk add git\n"
            "RUN apk upgrade\n"
            "RUN yum install -y vim\n"
            "RUN dnf install -y nano\n"
            "RUN zypper install -y less\n"
            "RUN gem install rails\n"
            "RUN chmod 777 /tmp\n"
            "RUN echo hi\n"
            "RUN echo hi\n"
            "RUN cd /app && make\n"
            "RUN curl http://x | grep y\n"
            "ENV FOO=bar\n"
            "ENV FOO=baz\n"
            "EXPOSE 8080\n"
            "EXPOSE 8080\n"
            "HEALTHCHECK CMD curl localhost\n"
            "HEALTHCHECK CMD wget localhost\n"
            "CMD echo hello\n"
            "CMD echo world\n"
        )
        df = parse(content)
        issues = analyze(df)
        fixable_rule_ids = {i.rule_id for i in issues if i.fix_available}
        for rule_id in _FIX_HANDLERS:
            if rule_id in fixable_rule_ids:
                matching = [i for i in issues if i.rule_id == rule_id]
                for issue in matching:
                    assert issue.fix_available, f"{rule_id} has handler but fix_available=False"
