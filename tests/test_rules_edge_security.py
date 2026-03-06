"""Edge case tests for DD041-DD060 rules."""
from __future__ import annotations

from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from tests.conftest import has_rule, count_rule, get_issues_for_rule


# ===========================================================================
# DD041 — COPY with relative destination (no leading /)
# ===========================================================================

class TestDD041CopyRelativeDest:
    def test_relative_dest_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD041")

    def test_absolute_dest_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD041")

    def test_workdir_before_copy_clean(self):
        df = parse("FROM ubuntu:22.04\nWORKDIR /app\nCOPY app.py .\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD041")

    def test_variable_dest_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py $APP_DIR/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD041")

    def test_add_relative_dest_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD archive.tar.gz data/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD041")

    def test_copy_with_chown_relative_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY --chown=1000:1000 app.py app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD041")

    def test_multistage_resets_workdir(self):
        """Second stage has no WORKDIR, so relative dest should trigger."""
        content = (
            "FROM node:18 AS build\n"
            "WORKDIR /app\n"
            "COPY package.json .\n"
            "FROM nginx:alpine\n"
            "COPY --from=build dist/ html/\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD041")

    def test_multistage_second_has_workdir_clean(self):
        content = (
            "FROM node:18 AS build\n"
            "WORKDIR /app\n"
            "COPY package.json .\n"
            "FROM nginx:alpine\n"
            "WORKDIR /usr/share/nginx\n"
            "COPY --from=build dist/ html/\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD041")


# ===========================================================================
# DD042 — ONBUILD instruction
# ===========================================================================

class TestDD042Onbuild:
    def test_onbuild_triggers(self):
        df = parse("FROM ubuntu:22.04\nONBUILD RUN echo hello\n")
        issues = analyze(df)
        assert has_rule(issues, "DD042")

    def test_no_onbuild_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD042")

    def test_multiple_onbuild_count(self):
        content = (
            "FROM ubuntu:22.04\n"
            "ONBUILD COPY . /app\n"
            "ONBUILD RUN make\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD042") == 2

    def test_onbuild_copy(self):
        df = parse("FROM ubuntu:22.04\nONBUILD COPY . /app\n")
        issues = analyze(df)
        assert has_rule(issues, "DD042")


# ===========================================================================
# DD043 — SHELL not in exec form
# ===========================================================================

class TestDD043ShellExecForm:
    def test_shell_string_form_triggers(self):
        df = parse('FROM ubuntu:22.04\nSHELL /bin/bash -c\n')
        issues = analyze(df)
        assert has_rule(issues, "DD043")

    def test_shell_exec_form_clean(self):
        df = parse('FROM ubuntu:22.04\nSHELL ["/bin/bash", "-c"]\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD043")

    def test_no_shell_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD043")

    def test_shell_powershell_exec_form_clean(self):
        df = parse('FROM mcr.microsoft.com/windows/servercore\nSHELL ["powershell", "-Command"]\n')
        issues = analyze(df)
        assert not has_rule(issues, "DD043")

    def test_shell_powershell_string_form_triggers(self):
        df = parse('FROM mcr.microsoft.com/windows/servercore\nSHELL powershell -Command\n')
        issues = analyze(df)
        assert has_rule(issues, "DD043")


# ===========================================================================
# DD044 — Duplicate ENV keys
# ===========================================================================

class TestDD044DuplicateEnv:
    def test_duplicate_env_triggers(self):
        content = "FROM ubuntu:22.04\nENV FOO=bar\nENV FOO=baz\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD044")

    def test_unique_env_clean(self):
        content = "FROM ubuntu:22.04\nENV FOO=bar\nENV BAR=baz\n"
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD044")

    def test_case_insensitive_duplicate(self):
        """ENV keys are compared case-insensitively."""
        content = "FROM ubuntu:22.04\nENV foo=bar\nENV FOO=baz\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD044")

    def test_duplicate_in_multikey_line(self):
        content = "FROM ubuntu:22.04\nENV A=1 B=2\nENV A=3\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD044")

    def test_env_space_form_duplicate(self):
        """ENV KEY VALUE form (no equals sign)."""
        content = "FROM ubuntu:22.04\nENV MY_VAR hello\nENV MY_VAR world\n"
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD044")

    def test_env_space_form_unique_clean(self):
        content = "FROM ubuntu:22.04\nENV MY_VAR hello\nENV OTHER_VAR world\n"
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD044")

    def test_multistage_separate_scopes(self):
        """Each stage has its own ENV scope."""
        content = (
            "FROM ubuntu:22.04 AS build\n"
            "ENV FOO=bar\n"
            "FROM ubuntu:22.04\n"
            "ENV FOO=baz\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD044")


# ===========================================================================
# DD045 — RUN cd instead of WORKDIR
# ===========================================================================

class TestDD045RunCd:
    def test_cd_and_chain_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN cd /app && make\n")
        issues = analyze(df)
        assert has_rule(issues, "DD045")

    def test_cd_semicolon_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN cd /app ; make\n")
        issues = analyze(df)
        assert has_rule(issues, "DD045")

    def test_workdir_clean(self):
        df = parse("FROM ubuntu:22.04\nWORKDIR /app\nRUN make\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD045")

    def test_cd_alone_no_chain_clean(self):
        """cd without && or ; at start does not trigger."""
        df = parse("FROM ubuntu:22.04\nRUN echo cd /app\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD045")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN cd /app && make\n")
        issues = get_issues_for_rule(analyze(df), "DD045")
        assert issues[0].fix_available


# ===========================================================================
# DD046 — Missing LABEL
# ===========================================================================

class TestDD046MissingLabel:
    def test_no_label_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert has_rule(issues, "DD046")

    def test_has_label_clean(self):
        df = parse("FROM ubuntu:22.04\nLABEL maintainer=\"me\"\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD046")

    def test_label_in_later_stage_clean(self):
        content = (
            "FROM node:18 AS build\n"
            "RUN npm install\n"
            "FROM nginx:alpine\n"
            "LABEL version=\"1.0\"\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD046")

    def test_empty_dockerfile_no_crash(self):
        df = parse("")
        issues = analyze(df)
        # No stages means no trigger
        assert not has_rule(issues, "DD046")


# ===========================================================================
# DD047 — Empty RUN instruction
# ===========================================================================

class TestDD047EmptyRun:
    def test_empty_run_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN \n")
        issues = analyze(df)
        assert has_rule(issues, "DD047")

    def test_run_with_command_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD047")

    def test_run_whitespace_only_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN   \n")
        issues = analyze(df)
        assert has_rule(issues, "DD047")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN \n")
        issues = get_issues_for_rule(analyze(df), "DD047")
        assert issues[0].fix_available


# ===========================================================================
# DD048 — Duplicate EXPOSE ports
# ===========================================================================

class TestDD048DuplicateExpose:
    def test_duplicate_port_triggers(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080\nEXPOSE 8080\n")
        issues = analyze(df)
        assert has_rule(issues, "DD048")

    def test_unique_ports_clean(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080\nEXPOSE 3000\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD048")

    def test_same_port_different_protocol_triggers(self):
        """Port number is extracted before /, so 8080/tcp and 8080/udp match."""
        df = parse("FROM ubuntu:22.04\nEXPOSE 8080/tcp\nEXPOSE 8080/udp\n")
        issues = analyze(df)
        assert has_rule(issues, "DD048")

    def test_multiple_ports_on_one_line_duplicate(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 80 443\nEXPOSE 80\n")
        issues = analyze(df)
        assert has_rule(issues, "DD048")

    def test_multiple_ports_on_one_line_unique_clean(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 80 443 8080\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD048")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nEXPOSE 80\nEXPOSE 80\n")
        issues = get_issues_for_rule(analyze(df), "DD048")
        assert issues[0].fix_available


# ===========================================================================
# DD049 — Multiple HEALTHCHECK instructions
# ===========================================================================

class TestDD049MultipleHealthcheck:
    def test_two_healthchecks_triggers(self):
        content = (
            "FROM ubuntu:22.04\n"
            "HEALTHCHECK CMD curl -f http://localhost/\n"
            "HEALTHCHECK CMD curl -f http://localhost/health\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD049")

    def test_single_healthcheck_clean(self):
        df = parse("FROM ubuntu:22.04\nHEALTHCHECK CMD curl -f http://localhost/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD049")

    def test_no_healthcheck_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD049")

    def test_three_healthchecks_flags_first_two(self):
        content = (
            "FROM ubuntu:22.04\n"
            "HEALTHCHECK CMD curl -f http://localhost/a\n"
            "HEALTHCHECK CMD curl -f http://localhost/b\n"
            "HEALTHCHECK CMD curl -f http://localhost/c\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert count_rule(issues, "DD049") == 2

    def test_healthcheck_per_stage_clean(self):
        """One HEALTHCHECK per stage is fine."""
        content = (
            "FROM ubuntu:22.04 AS build\n"
            "HEALTHCHECK CMD curl -f http://localhost/\n"
            "FROM nginx:alpine\n"
            "HEALTHCHECK CMD curl -f http://localhost/\n"
        )
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD049")


# ===========================================================================
# DD050 — Stage name not lowercase
# ===========================================================================

class TestDD050StageNameCase:
    def test_uppercase_stage_name_triggers(self):
        df = parse("FROM ubuntu:22.04 AS Build\n")
        issues = analyze(df)
        assert has_rule(issues, "DD050")

    def test_lowercase_stage_name_clean(self):
        df = parse("FROM ubuntu:22.04 AS build\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD050")

    def test_no_stage_name_clean(self):
        df = parse("FROM ubuntu:22.04\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD050")

    def test_allcaps_triggers(self):
        df = parse("FROM ubuntu:22.04 AS BUILD\n")
        issues = analyze(df)
        assert has_rule(issues, "DD050")

    def test_mixed_case_triggers(self):
        df = parse("FROM golang:1.21 AS goBuilder\n")
        issues = analyze(df)
        assert has_rule(issues, "DD050")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04 AS Build\n")
        issues = get_issues_for_rule(analyze(df), "DD050")
        assert issues[0].fix_available


# ===========================================================================
# DD051 — chmod 777 in RUN
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

    def test_chmod_777_in_chain(self):
        df = parse("FROM ubuntu:22.04\nRUN mkdir /data && chmod 777 /data\n")
        issues = analyze(df)
        assert has_rule(issues, "DD051")

    def test_chmod_644_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN chmod 644 /etc/config\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD051")

    def test_fix_available(self):
        df = parse("FROM ubuntu:22.04\nRUN chmod 777 /app\n")
        issues = get_issues_for_rule(analyze(df), "DD051")
        assert issues[0].fix_available


# ===========================================================================
# DD052 — COPY of .ssh or .git directories
# ===========================================================================

class TestDD052SshGitCopy:
    def test_copy_ssh_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY .ssh /root/.ssh\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_copy_git_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY .git /app/.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_copy_id_rsa_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY id_rsa /root/.ssh/id_rsa\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_copy_id_ed25519_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY id_ed25519 /root/.ssh/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_copy_normal_files_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY app.py /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD052")

    def test_add_git_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD .git /app/.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")

    def test_copy_id_ecdsa_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY id_ecdsa /root/.ssh/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD052")


# ===========================================================================
# DD053 — COPY of .env file
# ===========================================================================

class TestDD053EnvFileCopy:
    def test_copy_dotenv_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY .env /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD053")

    def test_copy_normal_file_clean(self):
        df = parse("FROM ubuntu:22.04\nCOPY requirements.txt /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD053")

    def test_copy_env_in_subdir_triggers(self):
        df = parse("FROM ubuntu:22.04\nCOPY config/.env /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD053")

    def test_copy_dotenv_example_clean(self):
        """.env.example is not .env."""
        df = parse("FROM ubuntu:22.04\nCOPY .env.example /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD053")

    def test_add_dotenv_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD .env /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD053")


# ===========================================================================
# DD054 — curl | bash pattern
# ===========================================================================

class TestDD054CurlPipeBash:
    def test_curl_pipe_sh_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -fsSL https://example.com/install.sh | sh\n")
        issues = analyze(df)
        assert has_rule(issues, "DD054")

    def test_curl_pipe_bash_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -fsSL https://example.com/install.sh | bash\n")
        issues = analyze(df)
        assert has_rule(issues, "DD054")

    def test_wget_pipe_sh_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN wget -qO- https://example.com/install.sh | sh\n")
        issues = analyze(df)
        assert has_rule(issues, "DD054")

    def test_curl_to_file_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -fsSL https://example.com/install.sh -o install.sh\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD054")

    def test_wget_to_file_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN wget -O install.sh https://example.com/install.sh\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD054")


# ===========================================================================
# DD055 — wget --no-check-certificate
# ===========================================================================

class TestDD055WgetNoCheck:
    def test_no_check_cert_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN wget --no-check-certificate https://example.com/file.tar.gz\n")
        issues = analyze(df)
        assert has_rule(issues, "DD055")

    def test_wget_normal_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN wget https://example.com/file.tar.gz\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD055")

    def test_no_check_cert_in_chain(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get update && wget --no-check-certificate https://example.com/a\n")
        issues = analyze(df)
        assert has_rule(issues, "DD055")

    def test_no_wget_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN curl https://example.com/file.tar.gz\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD055")


# ===========================================================================
# DD056 — curl -k (insecure)
# ===========================================================================

class TestDD056CurlInsecure:
    def test_curl_dash_k_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -k https://example.com/file\n")
        issues = analyze(df)
        assert has_rule(issues, "DD056")

    def test_curl_insecure_flag_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN curl --insecure https://example.com/file\n")
        issues = analyze(df)
        assert has_rule(issues, "DD056")

    def test_curl_normal_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN curl -fsSL https://example.com/file\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD056")

    def test_curl_k_in_chain(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get update && curl -k https://example.com/a\n")
        issues = analyze(df)
        assert has_rule(issues, "DD056")

    def test_no_curl_with_k_word_clean(self):
        """The word 'k' elsewhere should not trigger without curl."""
        df = parse("FROM ubuntu:22.04\nRUN echo -k something\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD056")


# ===========================================================================
# DD057 — git credentials in RUN
# ===========================================================================

class TestDD057GitCredentials:
    def test_git_clone_user_pass_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone https://user:pass@github.com/repo.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD057")

    def test_git_clone_token_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone https://oauth2:ghp_abc123@github.com/repo.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD057")

    def test_git_clone_ssh_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone git@github.com:user/repo.git\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD057")

    def test_git_clone_https_no_creds_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN git clone https://github.com/user/repo.git\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD057")

    def test_git_clone_creds_in_chain(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get update && git clone https://user:token@gitlab.com/repo.git\n")
        issues = analyze(df)
        assert has_rule(issues, "DD057")


# ===========================================================================
# DD058 — Hardcoded secrets in RUN
# ===========================================================================

class TestDD058HardcodedSecrets:
    def test_password_flag_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN mysql --password=secret123 -e 'SELECT 1'\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_token_flag_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN some-tool --token=abc123def\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_mysql_root_password_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN MYSQL_ROOT_PASSWORD=hunter2 mysql setup\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_postgres_password_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN POSTGRES_PASSWORD=secret123 psql setup\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_no_secrets_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y curl\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD058")

    def test_token_space_form_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN some-tool --token mysecret\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")

    def test_password_space_form_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN some-tool --password secret\n")
        issues = analyze(df)
        assert has_rule(issues, "DD058")


# ===========================================================================
# DD059 — ADD with remote URL
# ===========================================================================

class TestDD059AddRemoteUrl:
    def test_add_http_url_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD http://example.com/file.tar.gz /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD059")

    def test_add_https_url_triggers(self):
        df = parse("FROM ubuntu:22.04\nADD https://example.com/file.tar.gz /app/\n")
        issues = analyze(df)
        assert has_rule(issues, "DD059")

    def test_add_local_file_clean(self):
        df = parse("FROM ubuntu:22.04\nADD archive.tar.gz /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD059")

    def test_copy_url_in_argument_clean(self):
        """COPY is not ADD — this rule only applies to ADD."""
        df = parse("FROM ubuntu:22.04\nCOPY https-helper.txt /app/\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD059")

    def test_run_curl_clean(self):
        """Using curl in RUN is fine — this rule only checks ADD."""
        df = parse("FROM ubuntu:22.04\nRUN curl -fsSL https://example.com/file.tar.gz -o /app/file.tar.gz\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD059")


# ===========================================================================
# DD060 — --privileged flag in RUN
# ===========================================================================

class TestDD060RunPrivileged:
    def test_privileged_flag_triggers(self):
        df = parse("FROM ubuntu:22.04\nRUN --privileged apt-get install -y docker\n")
        issues = analyze(df)
        assert has_rule(issues, "DD060")

    def test_no_privileged_clean(self):
        df = parse("FROM ubuntu:22.04\nRUN apt-get install -y docker\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD060")

    def test_privileged_in_docker_run(self):
        df = parse("FROM ubuntu:22.04\nRUN docker run --privileged myimage\n")
        issues = analyze(df)
        assert has_rule(issues, "DD060")

    def test_privileged_in_chain(self):
        df = parse("FROM ubuntu:22.04\nRUN echo hi && docker run --privileged test\n")
        issues = analyze(df)
        assert has_rule(issues, "DD060")

    def test_privileged_word_in_comment_clean(self):
        """A comment with --privileged is not a RUN instruction."""
        df = parse("FROM ubuntu:22.04\n# don't use --privileged\nRUN echo hello\n")
        issues = analyze(df)
        assert not has_rule(issues, "DD060")
