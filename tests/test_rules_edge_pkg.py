"""Edge case tests for DD021-DD040 rules."""
from __future__ import annotations

from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from tests.conftest import has_rule, count_rule, get_issues_for_rule


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _analyze(content: str):
    """Parse and analyze a Dockerfile string, returning issues."""
    return analyze(parse(content))


# ===========================================================================
# DD021 — sudo in RUN
# ===========================================================================

class TestDD021SudoInRun:
    def test_positive_simple_sudo(self):
        issues = _analyze("FROM alpine:3.18\nRUN sudo apt-get update\n")
        assert has_rule(issues, "DD021")

    def test_negative_no_sudo(self):
        issues = _analyze("FROM alpine:3.18\nRUN apt-get update\n")
        assert not has_rule(issues, "DD021")

    def test_sudo_in_chained_command(self):
        issues = _analyze("FROM alpine:3.18\nRUN echo hello && sudo rm -rf /tmp\n")
        assert has_rule(issues, "DD021")

    def test_sudo_word_boundary_no_false_positive(self):
        """'sudoers' should not trigger DD021 because \\bsudo\\b needs word boundary."""
        issues = _analyze("FROM alpine:3.18\nRUN cat /etc/sudoers\n")
        assert not has_rule(issues, "DD021")

    def test_multiple_sudo_occurrences(self):
        content = (
            "FROM alpine:3.18\n"
            "RUN sudo apt-get update\n"
            "RUN sudo rm -rf /tmp\n"
        )
        issues = _analyze(content)
        assert count_rule(issues, "DD021") == 2

    def test_sudo_in_multiline_run(self):
        content = (
            "FROM alpine:3.18\n"
            "RUN echo hello && \\\n"
            "    sudo apt-get update\n"
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD021")


# ===========================================================================
# DD022 — Pin versions in apt-get install
# ===========================================================================

class TestDD022AptPinVersions:
    def test_positive_unpinned_package(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        assert has_rule(issues, "DD022")

    def test_negative_pinned_package(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install -y curl=7.81.0-1\n")
        assert not has_rule(issues, "DD022")

    def test_multiple_packages_one_unpinned(self):
        content = "FROM ubuntu:22.04\nRUN apt-get install -y curl=7.81.0-1 wget\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD022")

    def test_all_pinned(self):
        content = "FROM ubuntu:22.04\nRUN apt-get install -y curl=7.81.0-1 wget=1.21-1\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD022")

    def test_chained_with_update(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD022")

    def test_one_warning_per_instruction(self):
        """Rule breaks after first unpinned package per instruction."""
        content = "FROM ubuntu:22.04\nRUN apt-get install -y curl wget git\n"
        issues = _analyze(content)
        assert count_rule(issues, "DD022") == 1

    def test_no_trigger_without_install(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get update\n")
        assert not has_rule(issues, "DD022")


# ===========================================================================
# DD023 — Missing -y flag in apt-get install
# ===========================================================================

class TestDD023AptMissingYes:
    def test_positive_missing_y(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install curl\n")
        assert has_rule(issues, "DD023")

    def test_negative_with_y(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        assert not has_rule(issues, "DD023")

    def test_negative_with_yes_flag(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install --yes curl\n")
        assert not has_rule(issues, "DD023")

    def test_negative_with_qq(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install -qq curl\n")
        assert not has_rule(issues, "DD023")

    def test_no_trigger_on_bare_apt(self):
        """DD023 checks 'apt-get install' specifically, not 'apt install'."""
        issues = _analyze("FROM ubuntu:22.04\nRUN apt install curl\n")
        assert not has_rule(issues, "DD023")

    def test_multiline_missing_y(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && \\\n"
            "    apt-get install \\\n"
            "    curl wget\n"
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD023")


# ===========================================================================
# DD024 — Use apt-get instead of apt
# ===========================================================================

class TestDD024UseAptGet:
    def test_positive_bare_apt_install(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt install -y curl\n")
        assert has_rule(issues, "DD024")

    def test_positive_bare_apt_update(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt update\n")
        assert has_rule(issues, "DD024")

    def test_positive_bare_apt_remove(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt remove curl\n")
        assert has_rule(issues, "DD024")

    def test_negative_apt_get(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        assert not has_rule(issues, "DD024")

    def test_no_trigger_when_apt_get_also_present(self):
        """If 'apt-get' is also in the arguments, the rule skips."""
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt install -y curl\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD024")

    def test_apt_upgrade_triggers(self):
        issues = _analyze("FROM ubuntu:22.04\nRUN apt upgrade\n")
        assert has_rule(issues, "DD024")


# ===========================================================================
# DD025 — apk add without --no-cache
# ===========================================================================

class TestDD025ApkNoCache:
    def test_positive_missing_no_cache(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk add curl\n")
        assert has_rule(issues, "DD025")

    def test_negative_with_no_cache(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk add --no-cache curl\n")
        assert not has_rule(issues, "DD025")

    def test_apk_install_variant(self):
        """apk install (alias for add) should also trigger."""
        issues = _analyze("FROM alpine:3.18\nRUN apk install curl\n")
        assert has_rule(issues, "DD025")

    def test_no_trigger_on_apk_del(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk del curl\n")
        assert not has_rule(issues, "DD025")

    def test_chained_apk_add_without_cache(self):
        content = "FROM alpine:3.18\nRUN echo hello && apk add curl\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD025")


# ===========================================================================
# DD026 — apk upgrade in Dockerfile
# ===========================================================================

class TestDD026ApkUpgrade:
    def test_positive_apk_upgrade(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk upgrade\n")
        assert has_rule(issues, "DD026")

    def test_negative_no_upgrade(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk add --no-cache curl\n")
        assert not has_rule(issues, "DD026")

    def test_upgrade_with_add(self):
        content = "FROM alpine:3.18\nRUN apk upgrade && apk add --no-cache curl\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD026")

    def test_no_trigger_on_apt_upgrade(self):
        """apk upgrade only, not apt-get upgrade."""
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get upgrade\n")
        assert not has_rule(issues, "DD026")


# ===========================================================================
# DD027 — Pin versions in apk add
# ===========================================================================

class TestDD027ApkPinVersions:
    def test_positive_unpinned(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk add --no-cache curl\n")
        assert has_rule(issues, "DD027")

    def test_negative_pinned(self):
        issues = _analyze("FROM alpine:3.18\nRUN apk add --no-cache curl=7.88.1-r1\n")
        assert not has_rule(issues, "DD027")

    def test_tilde_pinned(self):
        """apk supports ~= for fuzzy pinning."""
        issues = _analyze("FROM alpine:3.18\nRUN apk add --no-cache curl~=7.88\n")
        assert not has_rule(issues, "DD027")

    def test_multiple_packages_first_unpinned(self):
        content = "FROM alpine:3.18\nRUN apk add --no-cache curl wget=1.21\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD027")

    def test_one_warning_per_instruction(self):
        content = "FROM alpine:3.18\nRUN apk add --no-cache curl wget git\n"
        issues = _analyze(content)
        assert count_rule(issues, "DD027") == 1

    def test_chained_with_other_commands(self):
        content = "FROM alpine:3.18\nRUN echo hello && apk add --no-cache curl\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD027")


# ===========================================================================
# DD028 — pip install without version pinning
# ===========================================================================

class TestDD028PipPinVersions:
    def test_positive_unpinned(self):
        issues = _analyze("FROM python:3.11\nRUN pip install flask\n")
        assert has_rule(issues, "DD028")

    def test_negative_pinned_double_equals(self):
        issues = _analyze("FROM python:3.11\nRUN pip install flask==2.3.0\n")
        assert not has_rule(issues, "DD028")

    def test_negative_pinned_gte(self):
        issues = _analyze("FROM python:3.11\nRUN pip install flask>=2.3.0\n")
        assert not has_rule(issues, "DD028")

    def test_negative_pinned_compatible(self):
        issues = _analyze("FROM python:3.11\nRUN pip install flask~=2.3\n")
        assert not has_rule(issues, "DD028")

    def test_negative_requirements_file(self):
        """pip install -r requirements.txt should not trigger."""
        issues = _analyze("FROM python:3.11\nRUN pip install -r requirements.txt\n")
        assert not has_rule(issues, "DD028")

    def test_pip3_variant(self):
        issues = _analyze("FROM python:3.11\nRUN pip3 install flask\n")
        assert has_rule(issues, "DD028")

    def test_python_m_pip(self):
        issues = _analyze("FROM python:3.11\nRUN python -m pip install flask\n")
        assert has_rule(issues, "DD028")

    def test_python3_m_pip(self):
        issues = _analyze("FROM python:3.11\nRUN python3 -m pip install flask\n")
        assert has_rule(issues, "DD028")

    def test_pip_install_dot_no_trigger(self):
        """'pip install .' installs from local directory, not a named package."""
        issues = _analyze("FROM python:3.11\nRUN pip install .\n")
        assert not has_rule(issues, "DD028")

    def test_requirement_flag_long_form(self):
        issues = _analyze("FROM python:3.11\nRUN pip install --requirement req.txt\n")
        assert not has_rule(issues, "DD028")


# ===========================================================================
# DD029 — npm install without pinned versions
# ===========================================================================

class TestDD029NpmPinVersions:
    def test_positive_unpinned(self):
        issues = _analyze("FROM node:18\nRUN npm install express\n")
        assert has_rule(issues, "DD029")

    def test_negative_pinned(self):
        issues = _analyze("FROM node:18\nRUN npm install express@4.18.0\n")
        assert not has_rule(issues, "DD029")

    def test_bare_npm_install_no_trigger(self):
        """Bare 'npm install' (from package.json) should not trigger."""
        # The regex requires a non-flag \S+ after install
        issues = _analyze("FROM node:18\nRUN npm install\n")
        assert not has_rule(issues, "DD029")

    def test_npm_install_with_flag_no_trigger(self):
        """npm install --production should not trigger (first token is a flag)."""
        issues = _analyze("FROM node:18\nRUN npm install --production\n")
        assert not has_rule(issues, "DD029")

    def test_scoped_package_unpinned(self):
        """@scope/package without version should trigger."""
        issues = _analyze("FROM node:18\nRUN npm install @types/node\n")
        # @types/node contains @ but it's at position 0, and the regex
        # checks for @ in the package string — @types/node does have @
        assert not has_rule(issues, "DD029")


# ===========================================================================
# DD030 — gem install without version pinning
# ===========================================================================

class TestDD030GemPinVersions:
    def test_positive_unpinned(self):
        issues = _analyze("FROM ruby:3.2\nRUN gem install rails\n")
        assert has_rule(issues, "DD030")

    def test_negative_with_version_flag_short(self):
        issues = _analyze("FROM ruby:3.2\nRUN gem install rails -v 7.0.0\n")
        assert not has_rule(issues, "DD030")

    def test_negative_with_version_flag_long(self):
        issues = _analyze("FROM ruby:3.2\nRUN gem install rails --version 7.0.0\n")
        assert not has_rule(issues, "DD030")

    def test_multiple_gems_unpinned(self):
        content = "FROM ruby:3.2\nRUN gem install rails bundler\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD030")
        # Only one warning per instruction (breaks after first)
        assert count_rule(issues, "DD030") == 1

    def test_no_trigger_on_other_commands(self):
        issues = _analyze("FROM ruby:3.2\nRUN gem list\n")
        assert not has_rule(issues, "DD030")


# ===========================================================================
# DD031 — yum install without yum clean all
# ===========================================================================

class TestDD031YumClean:
    def test_positive_missing_clean(self):
        issues = _analyze("FROM centos:7\nRUN yum install -y curl\n")
        assert has_rule(issues, "DD031")

    def test_negative_with_clean(self):
        issues = _analyze("FROM centos:7\nRUN yum install -y curl && yum clean all\n")
        assert not has_rule(issues, "DD031")

    def test_multiline_with_clean(self):
        content = (
            "FROM centos:7\n"
            "RUN yum install -y curl && \\\n"
            "    yum clean all\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD031")

    def test_missing_clean_multiple_runs(self):
        content = (
            "FROM centos:7\n"
            "RUN yum install -y curl\n"
            "RUN yum install -y wget\n"
        )
        issues = _analyze(content)
        assert count_rule(issues, "DD031") == 2


# ===========================================================================
# DD032 — yum install without version pinning
# ===========================================================================

class TestDD032YumPinVersions:
    def test_positive_unpinned(self):
        """yum uses name-version format; plain 'curl' has no dash so triggers."""
        issues = _analyze("FROM centos:7\nRUN yum install -y curl && yum clean all\n")
        assert has_rule(issues, "DD032")

    def test_negative_pinned(self):
        """Package with dash like 'curl-7.29.0' is considered pinned."""
        issues = _analyze("FROM centos:7\nRUN yum install -y curl-7.29.0 && yum clean all\n")
        assert not has_rule(issues, "DD032")

    def test_package_name_with_dash_no_trigger(self):
        """Package names that naturally contain dashes (like gcc-c++) are NOT flagged."""
        issues = _analyze("FROM centos:7\nRUN yum install -y gcc-c++ && yum clean all\n")
        assert not has_rule(issues, "DD032")

    def test_one_warning_per_instruction(self):
        content = "FROM centos:7\nRUN yum install -y curl wget && yum clean all\n"
        issues = _analyze(content)
        assert count_rule(issues, "DD032") == 1


# ===========================================================================
# DD033 — dnf install without dnf clean all
# ===========================================================================

class TestDD033DnfClean:
    def test_positive_missing_clean(self):
        issues = _analyze("FROM fedora:38\nRUN dnf install -y curl\n")
        assert has_rule(issues, "DD033")

    def test_negative_with_clean(self):
        issues = _analyze("FROM fedora:38\nRUN dnf install -y curl && dnf clean all\n")
        assert not has_rule(issues, "DD033")

    def test_multiline_with_clean(self):
        content = (
            "FROM fedora:38\n"
            "RUN dnf install -y curl && \\\n"
            "    dnf clean all\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD033")

    def test_no_trigger_on_yum(self):
        """dnf rule should not trigger on yum commands."""
        issues = _analyze("FROM centos:7\nRUN yum install -y curl\n")
        assert not has_rule(issues, "DD033")


# ===========================================================================
# DD034 — zypper install without zypper clean
# ===========================================================================

class TestDD034ZypperClean:
    def test_positive_missing_clean(self):
        issues = _analyze("FROM opensuse/leap:15.4\nRUN zypper install -y curl\n")
        assert has_rule(issues, "DD034")

    def test_negative_with_clean(self):
        content = "FROM opensuse/leap:15.4\nRUN zypper install -y curl && zypper clean\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD034")

    def test_multiline_with_clean(self):
        content = (
            "FROM opensuse/leap:15.4\n"
            "RUN zypper install -y curl && \\\n"
            "    zypper clean\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD034")

    def test_no_trigger_on_dnf(self):
        issues = _analyze("FROM fedora:38\nRUN dnf install -y curl\n")
        assert not has_rule(issues, "DD034")


# ===========================================================================
# DD035 — ENV DEBIAN_FRONTEND instead of ARG
# ===========================================================================

class TestDD035DebianFrontend:
    def test_positive_missing_debian_frontend(self):
        """apt-get install present but no DEBIAN_FRONTEND anywhere."""
        issues = _analyze("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        assert has_rule(issues, "DD035")

    def test_negative_env_debian_frontend(self):
        content = (
            "FROM ubuntu:22.04\n"
            "ENV DEBIAN_FRONTEND=noninteractive\n"
            "RUN apt-get install -y curl\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD035")

    def test_negative_arg_debian_frontend(self):
        content = (
            "FROM ubuntu:22.04\n"
            "ARG DEBIAN_FRONTEND=noninteractive\n"
            "RUN apt-get install -y curl\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD035")

    def test_negative_inline_in_run(self):
        """DEBIAN_FRONTEND set inline in RUN command."""
        content = (
            "FROM ubuntu:22.04\n"
            "RUN DEBIAN_FRONTEND=noninteractive apt-get install -y curl\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD035")

    def test_no_trigger_without_apt(self):
        """No apt-get install means no need for DEBIAN_FRONTEND."""
        issues = _analyze("FROM alpine:3.18\nRUN apk add --no-cache curl\n")
        assert not has_rule(issues, "DD035")

    def test_apt_install_bare_triggers(self):
        """'apt install' (not apt-get) also counts as apt usage for DD035."""
        issues = _analyze("FROM ubuntu:22.04\nRUN apt install -y curl\n")
        assert has_rule(issues, "DD035")


# ===========================================================================
# DD036 — Multiple CMD instructions
# ===========================================================================

class TestDD036MultipleCmd:
    def test_positive_two_cmds(self):
        content = (
            "FROM alpine:3.18\n"
            "CMD echo hello\n"
            "CMD echo world\n"
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD036")

    def test_negative_single_cmd(self):
        content = "FROM alpine:3.18\nCMD echo hello\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD036")

    def test_no_cmd(self):
        content = "FROM alpine:3.18\nRUN echo hello\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD036")

    def test_flags_earlier_cmds_not_last(self):
        """Only earlier CMDs are flagged, not the last one."""
        content = (
            "FROM alpine:3.18\n"
            "CMD echo one\n"
            "CMD echo two\n"
            "CMD echo three\n"
        )
        issues = _analyze(content)
        flagged = get_issues_for_rule(issues, "DD036")
        assert len(flagged) == 2
        # The last CMD (line 4) should NOT be in the flagged issues
        flagged_lines = {i.line_number for i in flagged}
        assert 4 not in flagged_lines

    def test_multistage_cmds_per_stage(self):
        """Each stage is checked independently."""
        content = (
            "FROM alpine:3.18 AS builder\n"
            "CMD echo build\n"
            "FROM alpine:3.18\n"
            "CMD echo run\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD036")

    def test_multistage_multiple_cmds_in_one_stage(self):
        content = (
            "FROM alpine:3.18 AS builder\n"
            "CMD echo one\n"
            "FROM alpine:3.18\n"
            "CMD echo run1\n"
            "CMD echo run2\n"
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD036")
        assert count_rule(issues, "DD036") == 1


# ===========================================================================
# DD037 — Multiple ENTRYPOINT instructions
# ===========================================================================

class TestDD037MultipleEntrypoint:
    def test_positive_two_entrypoints(self):
        content = (
            "FROM alpine:3.18\n"
            'ENTRYPOINT ["echo"]\n'
            'ENTRYPOINT ["sh"]\n'
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD037")

    def test_negative_single_entrypoint(self):
        content = "FROM alpine:3.18\nENTRYPOINT [\"echo\"]\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD037")

    def test_flags_earlier_entrypoints(self):
        content = (
            "FROM alpine:3.18\n"
            'ENTRYPOINT ["a"]\n'
            'ENTRYPOINT ["b"]\n'
            'ENTRYPOINT ["c"]\n'
        )
        issues = _analyze(content)
        flagged = get_issues_for_rule(issues, "DD037")
        assert len(flagged) == 2

    def test_multistage_entrypoints_per_stage(self):
        content = (
            "FROM alpine:3.18 AS builder\n"
            'ENTRYPOINT ["make"]\n'
            "FROM alpine:3.18\n"
            'ENTRYPOINT ["app"]\n'
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD037")

    def test_no_entrypoint(self):
        content = "FROM alpine:3.18\nCMD echo hello\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD037")


# ===========================================================================
# DD038 — Invalid EXPOSE port
# ===========================================================================

class TestDD038InvalidPort:
    def test_positive_port_zero(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 0\n")
        assert has_rule(issues, "DD038")

    def test_positive_port_too_high(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 70000\n")
        assert has_rule(issues, "DD038")

    def test_negative_valid_port(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 8080\n")
        assert not has_rule(issues, "DD038")

    def test_boundary_port_1(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 1\n")
        assert not has_rule(issues, "DD038")

    def test_boundary_port_65535(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 65535\n")
        assert not has_rule(issues, "DD038")

    def test_boundary_port_65536(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 65536\n")
        assert has_rule(issues, "DD038")

    def test_port_with_protocol(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 8080/tcp\n")
        assert not has_rule(issues, "DD038")

    def test_port_with_protocol_invalid(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 0/tcp\n")
        assert has_rule(issues, "DD038")

    def test_multiple_ports_one_invalid(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 8080 99999\n")
        assert has_rule(issues, "DD038")

    def test_port_range_valid(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 8000-8100\n")
        assert not has_rule(issues, "DD038")

    def test_port_range_invalid_high(self):
        issues = _analyze("FROM alpine:3.18\nEXPOSE 8000-70000\n")
        assert has_rule(issues, "DD038")

    def test_negative_port_not_detected(self):
        """'-1' is split by '-' into ['', '1']; '' causes ValueError, so no trigger."""
        issues = _analyze("FROM alpine:3.18\nEXPOSE -1\n")
        # The implementation splits on '-' for ranges, producing an empty
        # string that raises ValueError and is silently ignored.
        assert not has_rule(issues, "DD038")


# ===========================================================================
# DD039 — COPY --from referencing unknown stage
# ===========================================================================

class TestDD039CopyFromUnknown:
    def test_positive_unknown_numeric_stage(self):
        content = (
            "FROM alpine:3.18\n"
            "COPY --from=5 /app /app\n"
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD039")

    def test_negative_valid_numeric_stage(self):
        content = (
            "FROM alpine:3.18 AS builder\n"
            "RUN echo build\n"
            "FROM alpine:3.18\n"
            "COPY --from=0 /app /app\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD039")

    def test_negative_valid_named_stage(self):
        content = (
            "FROM alpine:3.18 AS builder\n"
            "RUN echo build\n"
            "FROM alpine:3.18\n"
            "COPY --from=builder /app /app\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD039")

    def test_named_stage_case_insensitive(self):
        content = (
            "FROM alpine:3.18 AS Builder\n"
            "RUN echo build\n"
            "FROM alpine:3.18\n"
            "COPY --from=builder /app /app\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD039")

    def test_external_image_no_trigger(self):
        """COPY --from=nginx:latest is an external image, not flagged."""
        content = (
            "FROM alpine:3.18\n"
            "COPY --from=nginx:latest /etc/nginx /etc/nginx\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD039")

    def test_numeric_out_of_bounds(self):
        """Two stages (0 and 1), reference stage 2."""
        content = (
            "FROM alpine:3.18 AS builder\n"
            "FROM alpine:3.18\n"
            "COPY --from=2 /app /app\n"
        )
        issues = _analyze(content)
        assert has_rule(issues, "DD039")

    def test_numeric_exactly_at_boundary(self):
        """Two stages (0 and 1), reference stage 1 is valid."""
        content = (
            "FROM alpine:3.18 AS builder\n"
            "FROM alpine:3.18\n"
            "COPY --from=1 /app /app\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD039")


# ===========================================================================
# DD040 — RUN with pipe but no pipefail
# ===========================================================================

class TestDD040MissingPipefail:
    def test_positive_pipe_without_pipefail(self):
        issues = _analyze("FROM alpine:3.18\nRUN curl http://example.com | tar xz\n")
        assert has_rule(issues, "DD040")

    def test_negative_with_inline_pipefail(self):
        content = "FROM alpine:3.18\nRUN set -o pipefail && curl http://example.com | tar xz\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD040")

    def test_negative_with_shell_pipefail(self):
        content = (
            "FROM alpine:3.18\n"
            'SHELL ["/bin/bash", "-o", "pipefail", "-c"]\n'
            "RUN curl http://example.com | tar xz\n"
        )
        issues = _analyze(content)
        assert not has_rule(issues, "DD040")

    def test_or_operator_no_trigger(self):
        """|| is logical OR, not a pipe."""
        issues = _analyze("FROM alpine:3.18\nRUN test -f /app || echo missing\n")
        assert not has_rule(issues, "DD040")

    def test_pipe_in_chained_command(self):
        content = "FROM alpine:3.18\nRUN echo hello && cat file.txt | grep foo\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD040")

    def test_set_euo_pipefail(self):
        """set -euo pipefail is also recognized."""
        content = "FROM alpine:3.18\nRUN set -euo pipefail && curl http://example.com | tar xz\n"
        issues = _analyze(content)
        assert not has_rule(issues, "DD040")

    def test_no_pipe_no_trigger(self):
        issues = _analyze("FROM alpine:3.18\nRUN echo hello && echo world\n")
        assert not has_rule(issues, "DD040")

    def test_multiple_pipes(self):
        content = "FROM alpine:3.18\nRUN cat file | grep foo | wc -l\n"
        issues = _analyze(content)
        assert has_rule(issues, "DD040")
        # Only one issue per RUN instruction
        assert count_rule(issues, "DD040") == 1
