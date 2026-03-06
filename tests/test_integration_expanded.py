"""Expanded integration and cross-rule tests for Dockerfile Doctor."""
from __future__ import annotations
import json
from pathlib import Path
from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from dockerfile_doctor.fixer import fix
from dockerfile_doctor.models import Issue, Fix, Severity, Category
from dockerfile_doctor.score import compute_scores, format_score_json, format_score_text
from dockerfile_doctor.diff import _parse_diff_hunks, filter_issues_by_diff
from dockerfile_doctor.models import AnalysisResult
from tests.conftest import has_rule, count_rule, get_issues_for_rule


def _analyze_and_fix(content: str) -> tuple[str, list[Issue], list[Fix]]:
    df = parse(content)
    issues = analyze(df)
    fixed_content, fixes = fix(df, issues)
    return fixed_content, issues, fixes


# =========================================================================
# 1. Real-world Dockerfile patterns (15+ tests)
# =========================================================================

class TestRealWorldPythonDjango:
    """Python/Django Dockerfile patterns."""

    DOCKERFILE = """\
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD gunicorn myapp.wsgi:application --bind 0.0.0.0:8000
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD018: large base image (python not slim/alpine)
        assert has_rule(issues, "DD018")
        # DD009: pip without --no-cache-dir
        assert has_rule(issues, "DD009")
        # DD008: no USER instruction
        assert has_rule(issues, "DD008")
        # DD019: shell form CMD
        assert has_rule(issues, "DD019")
        # DD015: missing PYTHONUNBUFFERED / PYTHONDONTWRITEBYTECODE
        assert has_rule(issues, "DD015")
        # DD012: no HEALTHCHECK
        assert has_rule(issues, "DD012")

    def test_fix_produces_valid_output(self):
        fixed, issues, fixes = _analyze_and_fix(self.DOCKERFILE)
        # Should have applied some fixes
        assert len(fixes) > 0
        # Fixed content should still be parseable
        df2 = parse(fixed)
        assert len(df2.instructions) > 0
        # pip --no-cache-dir should be present after fix
        assert "--no-cache-dir" in fixed


class TestRealWorldNodeExpress:
    """Node.js/Express Dockerfile patterns."""

    DOCKERFILE = """\
FROM node:18
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD node server.js
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD018: large base image
        assert has_rule(issues, "DD018")
        # DD067: missing NODE_ENV
        assert has_rule(issues, "DD067")
        # DD008: no USER
        assert has_rule(issues, "DD008")
        # DD019: shell form CMD
        assert has_rule(issues, "DD019")
        # DD010: npm install instead of npm ci
        assert has_rule(issues, "DD010")

    def test_fix_produces_valid_output(self):
        fixed, issues, fixes = _analyze_and_fix(self.DOCKERFILE)
        assert len(fixes) > 0
        df2 = parse(fixed)
        assert len(df2.instructions) > 0
        # npm ci should replace npm install
        assert "npm ci" in fixed


class TestRealWorldGoMultistage:
    """Go microservice with multi-stage build."""

    DOCKERFILE = """\
FROM golang:1.22 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o /app ./cmd/server

FROM alpine:3.19
COPY --from=builder /app /app
EXPOSE 8080
USER nobody
CMD ["/app"]
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD062: go build without CGO_ENABLED=0
        assert has_rule(issues, "DD062")
        # DD018: large base image (golang)
        assert has_rule(issues, "DD018")
        # Should not fire DD008 since USER is set in final stage
        assert not has_rule(issues, "DD008")
        # Should not fire DD066 since COPY --from is used
        assert not has_rule(issues, "DD066")

    def test_multistage_parsed_correctly(self):
        df = parse(self.DOCKERFILE)
        assert df.is_multistage
        assert len(df.stages) == 2
        assert df.stages[0].name == "builder"


class TestRealWorldJavaMaven:
    """Java/Maven multi-stage build."""

    DOCKERFILE = """\
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline
COPY src ./src
RUN mvn package -DskipTests

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD068: Java without container-aware JVM flags
        assert has_rule(issues, "DD068")
        # DD008: no USER in final stage
        assert has_rule(issues, "DD008")

    def test_fix_produces_valid_output(self):
        fixed, issues, fixes = _analyze_and_fix(self.DOCKERFILE)
        df2 = parse(fixed)
        assert df2.is_multistage
        assert len(df2.stages) == 2


class TestRealWorldRubyRails:
    """Ruby/Rails Dockerfile."""

    DOCKERFILE = """\
FROM ruby:3.2
RUN apt-get update && apt-get install -y nodejs
WORKDIR /app
COPY Gemfile Gemfile.lock ./
RUN gem install bundler && bundle install
COPY . .
EXPOSE 3000
CMD rails server -b 0.0.0.0
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD003: no --no-install-recommends
        assert has_rule(issues, "DD003")
        # DD004: no apt cache cleanup
        assert has_rule(issues, "DD004")
        # DD018: large base image (ruby)
        assert has_rule(issues, "DD018")
        # DD061: gem install without --no-document
        assert has_rule(issues, "DD061")
        # DD019: shell form CMD
        assert has_rule(issues, "DD019")

    def test_fix_applies_apt_and_gem_fixes(self):
        fixed, issues, fixes = _analyze_and_fix(self.DOCKERFILE)
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists" in fixed
        assert "--no-document" in fixed


class TestRealWorldNginxStatic:
    """Nginx static site Dockerfile."""

    DOCKERFILE = """\
FROM nginx:1.25-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY dist/ /usr/share/nginx/html/
EXPOSE 80
HEALTHCHECK CMD curl -f http://localhost/ || exit 1
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # Should NOT fire DD018 since alpine tag
        assert not has_rule(issues, "DD018")
        # DD008: no USER
        assert has_rule(issues, "DD008")
        # Should have HEALTHCHECK, so DD012 not fired
        assert not has_rule(issues, "DD012")

    def test_minimal_issues_for_good_dockerfile(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # Should have relatively few issues for a well-structured Dockerfile
        errors = [i for i in issues if i.severity == Severity.ERROR]
        assert len(errors) == 0


class TestRealWorldPHPLaravel:
    """PHP/Laravel Dockerfile."""

    DOCKERFILE = """\
FROM php:8.2-fpm
RUN apt-get update && apt-get install -y libpng-dev libjpeg-dev
RUN docker-php-ext-install gd pdo pdo_mysql
WORKDIR /var/www/html
COPY . .
RUN curl -sS https://getcomposer.org/installer | php
EXPOSE 9000
CMD ["php-fpm"]
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD003: missing --no-install-recommends
        assert has_rule(issues, "DD003")
        # DD004: no apt cache cleanup
        assert has_rule(issues, "DD004")
        # DD005: consecutive RUN
        assert has_rule(issues, "DD005")
        # DD040: missing pipefail (pipe in RUN)
        assert has_rule(issues, "DD040")


class TestRealWorldRustMultistage:
    """Rust multi-stage build."""

    DOCKERFILE = """\
FROM rust:1.75 AS builder
WORKDIR /usr/src/app
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo 'fn main(){}' > src/main.rs && cargo build --release
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=builder /usr/src/app/target/release/myapp /usr/local/bin/myapp
USER nobody
CMD ["/usr/local/bin/myapp"]
"""

    def test_expected_rules_fire(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD018: large base image (rust)
        assert has_rule(issues, "DD018")
        # Should NOT fire DD008 since USER is set in final stage
        assert not has_rule(issues, "DD008")

    def test_multistage_structure(self):
        df = parse(self.DOCKERFILE)
        assert df.is_multistage
        assert len(df.stages) == 2
        assert df.stages[0].name == "builder"


class TestRealWorldAlpineMinimal:
    """Minimal Alpine-based Dockerfile with best practices."""

    DOCKERFILE = """\
FROM python:3.12-alpine
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
EXPOSE 8000
HEALTHCHECK CMD wget -q --spider http://localhost:8000/health || exit 1
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
"""

    def test_few_issues_for_best_practice_dockerfile(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # Should not fire DD018 (alpine tag)
        assert not has_rule(issues, "DD018")
        # Should not fire DD009 (has --no-cache-dir)
        assert not has_rule(issues, "DD009")
        # Should not fire DD008 (has USER)
        assert not has_rule(issues, "DD008")
        # Should not fire DD015 (has PYTHONUNBUFFERED + PYTHONDONTWRITEBYTECODE)
        assert not has_rule(issues, "DD015")
        # Should not fire DD012 (has HEALTHCHECK)
        assert not has_rule(issues, "DD012")
        # Should not fire DD019 (exec form CMD)
        assert not has_rule(issues, "DD019")

    def test_well_formed_dockerfile_has_no_errors(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        errors = [i for i in issues if i.severity == Severity.ERROR]
        assert len(errors) == 0


class TestRealWorldMultipleFrom:
    """Dockerfile with many ecosystem-specific patterns."""

    DOCKERFILE = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
USER appuser
HEALTHCHECK CMD curl -f http://localhost/ || exit 1
CMD ["./start.sh"]
"""

    def test_well_formed_ubuntu_dockerfile(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # Should not fire DD003 (has --no-install-recommends)
        assert not has_rule(issues, "DD003")
        # Should not fire DD004 (has apt cleanup)
        assert not has_rule(issues, "DD004")
        # Should not fire DD023 (has -y)
        assert not has_rule(issues, "DD023")


class TestRealWorldDockerfileWithSecrets:
    """Dockerfile with secret patterns."""

    DOCKERFILE = """\
FROM python:3.11-slim
ENV SECRET=supersecret123
ENV API_KEY=abcdef
WORKDIR /app
COPY . .
CMD ["python", "app.py"]
"""

    def test_secrets_detected(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        # DD020: secrets in ENV
        assert has_rule(issues, "DD020")
        secret_issues = get_issues_for_rule(issues, "DD020")
        assert len(secret_issues) >= 1
        # All secret issues should be ERROR severity
        for si in secret_issues:
            assert si.severity == Severity.ERROR


class TestRealWorldMaintainerDeprecated:
    """Dockerfile using deprecated MAINTAINER."""

    DOCKERFILE = """\
FROM node:18-slim
MAINTAINER john@example.com
WORKDIR /app
COPY . .
CMD ["node", "index.js"]
"""

    def test_maintainer_detected(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        assert has_rule(issues, "DD017")

    def test_maintainer_fix(self):
        fixed, issues, fixes = _analyze_and_fix(self.DOCKERFILE)
        assert "LABEL maintainer=" in fixed
        assert "MAINTAINER" not in fixed


class TestRealWorldAddInsteadOfCopy:
    """Dockerfile using ADD for non-archive files."""

    DOCKERFILE = """\
FROM ubuntu:22.04
ADD app.py /app/
ADD config.yaml /app/
CMD ["python", "/app/app.py"]
"""

    def test_add_detected(self):
        df = parse(self.DOCKERFILE)
        issues = analyze(df)
        assert has_rule(issues, "DD007")
        assert count_rule(issues, "DD007") == 2

    def test_add_fixed_to_copy(self):
        fixed, issues, fixes = _analyze_and_fix(self.DOCKERFILE)
        assert "ADD" not in fixed
        assert "COPY app.py /app/" in fixed
        assert "COPY config.yaml /app/" in fixed


# =========================================================================
# 2. Multi-stage build interactions (10+ tests)
# =========================================================================

class TestMultiStageBuilds:
    """Multi-stage build interaction tests."""

    def test_three_stages_different_bases(self):
        content = """\
FROM node:18 AS frontend
WORKDIR /app
COPY package.json .
RUN npm install
RUN npm run build

FROM golang:1.22 AS backend
WORKDIR /src
COPY . .
RUN go build -o /server

FROM alpine:3.19
COPY --from=frontend /app/dist /usr/share/nginx/html
COPY --from=backend /server /server
USER nobody
CMD ["/server"]
"""
        df = parse(content)
        assert len(df.stages) == 3
        assert df.stages[0].name == "frontend"
        assert df.stages[1].name == "backend"
        assert df.stages[2].name is None
        issues = analyze(df)
        # DD018 should fire for node and golang (large base images)
        dd018_issues = get_issues_for_rule(issues, "DD018")
        assert len(dd018_issues) >= 2

    def test_copy_from_across_stages(self):
        content = """\
FROM golang:1.22 AS builder
RUN go build -o /app

FROM scratch
COPY --from=builder /app /app
CMD ["/app"]
"""
        df = parse(content)
        issues = analyze(df)
        # DD066 should NOT fire - COPY --from is used
        assert not has_rule(issues, "DD066")

    def test_multistage_without_copy_from(self):
        content = """\
FROM golang:1.22 AS builder
RUN echo "building"

FROM alpine:3.19
RUN echo "running"
CMD ["echo", "hello"]
"""
        df = parse(content)
        issues = analyze(df)
        # DD066 should fire
        assert has_rule(issues, "DD066")

    def test_stage_specific_fixes_dont_corrupt_other_stages(self):
        content = """\
FROM python:3.11 AS builder
RUN pip install build
RUN python -m build

FROM python:3.11-slim
COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl
CMD ["python", "-m", "myapp"]
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        df2 = parse(fixed)
        assert df2.is_multistage
        assert len(df2.stages) == 2
        # Both stages should still have FROM
        from_instrs = [i for i in df2.instructions if i.directive == "FROM"]
        assert len(from_instrs) == 2

    def test_rules_fire_per_stage(self):
        content = """\
FROM python:3.11 AS stage1
RUN pip install flask

FROM python:3.11 AS stage2
RUN pip install django

FROM python:3.11-slim
COPY --from=stage1 /app /app
CMD ["python", "app.py"]
"""
        df = parse(content)
        issues = analyze(df)
        # DD009 fires per-stage RUN with pip
        dd009 = get_issues_for_rule(issues, "DD009")
        assert len(dd009) >= 2

    def test_four_stage_build(self):
        content = """\
FROM node:18 AS deps
RUN npm ci

FROM node:18 AS build
COPY --from=deps /app/node_modules ./node_modules
RUN npm run build

FROM node:18 AS test
COPY --from=build /app/dist ./dist
RUN npm test

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
CMD ["nginx", "-g", "daemon off;"]
"""
        df = parse(content)
        assert len(df.stages) == 4
        issues = analyze(df)
        # Should parse and analyze without errors
        assert isinstance(issues, list)

    def test_consecutive_run_per_stage(self):
        """DD005 fires per stage, not across stages."""
        content = """\
FROM alpine AS stage1
RUN echo "a"
RUN echo "b"

FROM alpine AS stage2
RUN echo "c"
RUN echo "d"
"""
        df = parse(content)
        issues = analyze(df)
        dd005 = get_issues_for_rule(issues, "DD005")
        # Should fire once per stage (2 total)
        assert len(dd005) == 2

    def test_user_only_matters_in_final_stage(self):
        """DD008 only checks the final stage."""
        content = """\
FROM golang:1.22 AS builder
RUN go build -o /app

FROM scratch
COPY --from=builder /app /app
CMD ["/app"]
"""
        df = parse(content)
        issues = analyze(df)
        # DD008 fires for final stage with no USER
        assert has_rule(issues, "DD008")

    def test_user_in_final_stage_no_dd008(self):
        content = """\
FROM golang:1.22 AS builder
RUN go build -o /app

FROM alpine:3.19
COPY --from=builder /app /app
USER nobody
CMD ["/app"]
"""
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD008")

    def test_healthcheck_anywhere_suppresses_dd012(self):
        content = """\
FROM node:18 AS builder
RUN echo "build"

FROM node:18-slim
COPY --from=builder /app /app
HEALTHCHECK CMD curl -f http://localhost:3000 || exit 1
CMD ["node", "app.js"]
"""
        df = parse(content)
        issues = analyze(df)
        assert not has_rule(issues, "DD012")


# =========================================================================
# 3. Score integration (10+ tests)
# =========================================================================

class TestScoreIntegration:
    """Score computation and formatting tests."""

    def _make_result(self, content: str, filepath: str = "Dockerfile") -> AnalysisResult:
        df = parse(content)
        issues = analyze(df)
        return AnalysisResult(filepath=filepath, issues=issues)

    def test_score_perfect_dockerfile(self):
        content = """\
FROM python:3.12-alpine
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
EXPOSE 8000
HEALTHCHECK CMD wget -q --spider http://localhost:8000/health || exit 1
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
"""
        result = self._make_result(content)
        scores = compute_scores([result])
        assert len(scores) == 1
        # Should be high score (A or B)
        assert scores[0].points >= 80

    def test_score_bad_dockerfile(self):
        content = """\
FROM python
RUN pip install flask
RUN pip install django
RUN pip install requests
ENV API_KEY=secret123
CMD python app.py
"""
        result = self._make_result(content)
        scores = compute_scores([result])
        assert len(scores) == 1
        # Should be low score due to many issues including errors
        assert scores[0].points < 80
        assert scores[0].errors > 0

    def test_score_improves_after_fix(self):
        content = """\
FROM python:3.11
RUN pip install flask
CMD python app.py
"""
        result_before = self._make_result(content)
        scores_before = compute_scores([result_before])

        fixed, _, _ = _analyze_and_fix(content)
        result_after = self._make_result(fixed)
        scores_after = compute_scores([result_after])

        # Score should improve (or stay same if all remaining are unfixable)
        assert scores_after[0].points >= scores_before[0].points

    def test_score_all_severity_levels(self):
        content = """\
FROM ubuntu
ENV API_KEY=secret
RUN apt-get update
RUN apt-get install -y curl
CMD echo hello
"""
        result = self._make_result(content)
        scores = compute_scores([result])
        s = scores[0]
        # Should have all three severity levels
        assert s.errors > 0    # DD020 (secret)
        assert s.warnings > 0  # DD001, DD003, etc.
        assert s.infos > 0     # DD005, DD012, etc.

    def test_score_with_multistage(self):
        content = """\
FROM golang:1.22 AS builder
RUN go build -o /app

FROM scratch
COPY --from=builder /app /app
CMD ["/app"]
"""
        result = self._make_result(content)
        scores = compute_scores([result])
        assert len(scores) == 1
        assert scores[0].grade in ("A", "B", "C", "D", "F")

    def test_score_json_structure(self):
        content = "FROM alpine:3.19\nCMD [\"echo\", \"hello\"]\n"
        result = self._make_result(content)
        scores = compute_scores([result])
        data = format_score_json(scores)
        assert "scores" in data
        assert "average" in data
        assert len(data["scores"]) == 1
        score_entry = data["scores"][0]
        assert "filepath" in score_entry
        assert "grade" in score_entry
        assert "points" in score_entry
        assert "errors" in score_entry
        assert "warnings" in score_entry
        assert "infos" in score_entry
        assert "totalIssues" in score_entry
        assert "deductions" in score_entry
        assert isinstance(score_entry["deductions"], list)

    def test_score_json_average(self):
        content1 = "FROM alpine:3.19\nCMD [\"echo\", \"hello\"]\n"
        content2 = "FROM ubuntu\nRUN echo hi\nCMD echo bye\n"
        r1 = self._make_result(content1, "Dockerfile.a")
        r2 = self._make_result(content2, "Dockerfile.b")
        scores = compute_scores([r1, r2])
        data = format_score_json(scores)
        avg = data["average"]
        assert "points" in avg
        assert "grade" in avg
        expected_avg = (scores[0].points + scores[1].points) / 2
        assert abs(avg["points"] - expected_avg) < 0.01

    def test_score_text_format(self):
        content = "FROM alpine:3.19\nCMD [\"echo\", \"hello\"]\n"
        result = self._make_result(content)
        scores = compute_scores([result])
        text = format_score_text(scores)
        assert "Grade:" in text
        assert "/100" in text
        assert "Issues:" in text

    def test_score_text_multiple_files(self):
        r1 = self._make_result("FROM alpine:3.19\nCMD [\"echo\", \"a\"]\n", "Dockerfile.1")
        r2 = self._make_result("FROM alpine:3.19\nCMD [\"echo\", \"b\"]\n", "Dockerfile.2")
        scores = compute_scores([r1, r2])
        text = format_score_text(scores)
        assert "Dockerfile.1" in text
        assert "Dockerfile.2" in text
        assert "Overall:" in text
        assert "average across 2 files" in text

    def test_score_grade_boundaries(self):
        # Create results with controlled issue counts to test grade boundaries
        from dockerfile_doctor.score import _points_to_grade
        assert _points_to_grade(100) == "A"
        assert _points_to_grade(90) == "A"
        assert _points_to_grade(89) == "B"
        assert _points_to_grade(80) == "B"
        assert _points_to_grade(79) == "C"
        assert _points_to_grade(70) == "C"
        assert _points_to_grade(69) == "D"
        assert _points_to_grade(60) == "D"
        assert _points_to_grade(59) == "F"
        assert _points_to_grade(0) == "F"

    def test_score_floor_at_zero(self):
        """Score should never go below 0."""
        content = """\
FROM ubuntu
ENV DB_PASSWORD=secret1
ENV API_KEY=secret2
ENV ACCESS_KEY=secret3
ENV PRIVATE_KEY=secret4
ENV AUTH_TOKEN=secret5
ENV AWS_SECRET=secret6
ENV DB_PASS=secret7
RUN apt-get update
RUN apt-get install curl
CMD echo hello
"""
        result = self._make_result(content)
        scores = compute_scores([result])
        assert scores[0].points >= 0


# =========================================================================
# 4. Diff filtering integration (10+ tests)
# =========================================================================

class TestDiffFiltering:
    """Diff hunk parsing and issue filtering tests."""

    def test_parse_single_hunk(self):
        diff = """\
--- a/Dockerfile
+++ b/Dockerfile
@@ -1,3 +1,4 @@
 FROM python:3.11
+RUN pip install flask
 WORKDIR /app
 CMD ["python", "app.py"]
"""
        lines = _parse_diff_hunks(diff)
        assert 1 in lines
        assert 2 in lines
        assert 3 in lines
        assert 4 in lines

    def test_parse_multiple_hunks(self):
        diff = """\
--- a/Dockerfile
+++ b/Dockerfile
@@ -1,2 +1,3 @@
 FROM python:3.11
+RUN pip install flask
 WORKDIR /app
@@ -5,2 +6,3 @@
 EXPOSE 8000
+HEALTHCHECK CMD curl -f http://localhost:8000
 CMD ["python", "app.py"]
"""
        lines = _parse_diff_hunks(diff)
        # First hunk: lines 1-3
        assert 1 in lines
        assert 2 in lines
        assert 3 in lines
        # Second hunk: lines 6-8
        assert 6 in lines
        assert 7 in lines
        assert 8 in lines

    def test_parse_deletion_only_hunk(self):
        diff = """\
--- a/Dockerfile
+++ b/Dockerfile
@@ -3,2 +3,0 @@
"""
        lines = _parse_diff_hunks(diff)
        # count=0 means deletion only, no new lines
        assert len(lines) == 0

    def test_parse_single_line_addition(self):
        diff = """\
@@ -0,0 +1 @@
"""
        lines = _parse_diff_hunks(diff)
        assert lines == {1}

    def test_parse_empty_diff(self):
        lines = _parse_diff_hunks("")
        assert lines == set()

    def test_filter_issues_none_changed_lines(self):
        """None means untracked file - all issues pass through."""
        issues = [
            Issue("DD001", "test", "desc", Severity.WARNING, Category.MAINTAINABILITY, 5),
            Issue("DD009", "test", "desc", Severity.WARNING, Category.PERFORMANCE, 10),
        ]
        filtered = filter_issues_by_diff(issues, None)
        assert len(filtered) == 2

    def test_filter_issues_file_level_always_pass(self):
        """File-level issues (line_number=0) always pass through."""
        issues = [
            Issue("DD012", "test", "desc", Severity.INFO, Category.BEST_PRACTICE, 0),
            Issue("DD009", "test", "desc", Severity.WARNING, Category.PERFORMANCE, 10),
        ]
        changed = {5, 6, 7}
        filtered = filter_issues_by_diff(issues, changed)
        # DD012 passes (line_number=0), DD009 filtered out (line 10 not in changed)
        assert len(filtered) == 1
        assert filtered[0].rule_id == "DD012"

    def test_filter_issues_only_changed_lines(self):
        issues = [
            Issue("DD001", "t", "d", Severity.WARNING, Category.MAINTAINABILITY, 1),
            Issue("DD009", "t", "d", Severity.WARNING, Category.PERFORMANCE, 3),
            Issue("DD019", "t", "d", Severity.WARNING, Category.BEST_PRACTICE, 5),
        ]
        changed = {1, 3}
        filtered = filter_issues_by_diff(issues, changed)
        assert len(filtered) == 2
        assert filtered[0].rule_id == "DD001"
        assert filtered[1].rule_id == "DD009"

    def test_filter_empty_changed_lines(self):
        """Empty set means no lines changed - only file-level issues pass."""
        issues = [
            Issue("DD001", "t", "d", Severity.WARNING, Category.MAINTAINABILITY, 1),
            Issue("DD012", "t", "d", Severity.INFO, Category.BEST_PRACTICE, 0),
        ]
        changed: set[int] = set()
        filtered = filter_issues_by_diff(issues, changed)
        assert len(filtered) == 1
        assert filtered[0].rule_id == "DD012"

    def test_filter_all_lines_changed(self):
        """All lines changed - all issues pass."""
        issues = [
            Issue("DD001", "t", "d", Severity.WARNING, Category.MAINTAINABILITY, 1),
            Issue("DD009", "t", "d", Severity.WARNING, Category.PERFORMANCE, 3),
        ]
        changed = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
        filtered = filter_issues_by_diff(issues, changed)
        assert len(filtered) == 2

    def test_parse_diff_hunks_large_range(self):
        diff = "@@ -10,5 +10,100 @@\n"
        lines = _parse_diff_hunks(diff)
        assert len(lines) == 100
        assert 10 in lines
        assert 109 in lines
        assert 110 not in lines


# =========================================================================
# 5. Full pipeline end-to-end (10+ tests)
# =========================================================================

class TestFullPipeline:
    """parse -> analyze -> fix -> re-analyze -> verify improvement."""

    def test_fix_reduces_issue_count(self):
        content = """\
FROM python:3.11
RUN pip install flask
RUN pip install django
CMD python app.py
"""
        df = parse(content)
        issues_before = analyze(df)
        fixed, fixes = fix(df, issues_before)
        df2 = parse(fixed)
        issues_after = analyze(df2)
        # Fewer issues after fix
        assert len(issues_after) <= len(issues_before)

    def test_fix_does_not_introduce_same_category_issues(self):
        """Fixing should not introduce new issues in the same categories that were fixed."""
        content = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y curl
CMD ["echo", "hello"]
"""
        df = parse(content)
        issues_before = analyze(df)
        fixed, fixes = fix(df, issues_before)
        df2 = parse(fixed)
        issues_after = analyze(df2)

        fixed_rule_ids = {f.rule_id for f in fixes}
        for rule_id in fixed_rule_ids:
            after_count = count_rule(issues_after, rule_id)
            before_count = count_rule(issues_before, rule_id)
            assert after_count <= before_count, (
                f"Rule {rule_id} increased from {before_count} to {after_count} after fix"
            )

    def test_empty_dockerfile(self):
        content = ""
        df = parse(content)
        issues = analyze(df)
        # Should not crash on empty
        assert isinstance(issues, list)

    def test_comment_only_dockerfile(self):
        content = """\
# This is a comment
# Another comment
"""
        df = parse(content)
        issues = analyze(df)
        assert isinstance(issues, list)
        # No instructions, so limited rules can fire
        assert len(df.instructions) == 0

    def test_single_instruction_dockerfile(self):
        content = "FROM alpine:3.19\n"
        df = parse(content)
        issues = analyze(df)
        assert isinstance(issues, list)
        # DD012 and DD008 should fire
        assert has_rule(issues, "DD012")
        assert has_rule(issues, "DD008")

    def test_pipeline_convergence(self):
        """Multiple fix passes should converge."""
        content = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install curl
RUN apt-get update && apt-get install wget
CMD echo hello
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        # Re-analyze should have fewer fixable issues
        df2 = parse(fixed)
        issues2 = analyze(df2)
        fixable_after = [i for i in issues2 if i.fix_available]
        fixable_before = [i for i in issues if i.fix_available]
        assert len(fixable_after) <= len(fixable_before)

    def test_fix_roundtrip_parseable(self):
        """Fixed content should always be parseable."""
        content = """\
FROM python:3.11
MAINTAINER test@example.com
RUN sudo apt-get update && apt-get install -y curl
RUN pip install flask
ADD README.md /app/
CMD python app.py
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        # Must be parseable
        df2 = parse(fixed)
        assert len(df2.instructions) > 0
        # Must still start with FROM
        assert df2.instructions[0].directive == "FROM"

    def test_multiple_fix_types_in_one_dockerfile(self):
        """Various fixable rules in a single Dockerfile."""
        content = """\
FROM python:3.11
RUN sudo pip install flask
RUN pip install django
ADD config.py /app/
CMD python app.py
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        fix_rule_ids = {f.rule_id for f in fixes}
        # Should have multiple fix types
        assert len(fix_rule_ids) >= 2
        # DD021 (sudo), DD009 (pip cache), DD005 (consecutive RUN), DD007 (ADD->COPY), DD019 (CMD)
        # At least some of these should be fixed

    def test_fix_preserves_trailing_newline(self):
        content = "FROM alpine:3.19\nCMD echo hello\n"
        fixed, issues, fixes = _analyze_and_fix(content)
        assert fixed.endswith("\n")

    def test_fix_on_clean_dockerfile_produces_no_fixes(self):
        content = """\
FROM python:3.12-alpine
LABEL maintainer="me" description="test" version="1.0.0"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
EXPOSE 8000
HEALTHCHECK CMD wget -q --spider http://localhost:8000/health || exit 1
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
"""
        df = parse(content)
        issues = analyze(df)
        _, fixes = fix(df, issues)
        # Most fixable rules should not fire on a clean Dockerfile
        # (some unfixable rules may still fire)
        fixable_issues = [i for i in issues if i.fix_available]
        assert len(fixable_issues) == 0

    def test_reanalyze_after_fix_shows_improvement(self):
        """Full pipeline: parse -> analyze -> fix -> reparse -> reanalyze."""
        content = """\
FROM ruby:3.2
RUN gem install bundler
RUN apt-get update && apt-get install -y nodejs
ADD Gemfile /app/
CMD rails server
"""
        df1 = parse(content)
        issues1 = analyze(df1)
        fixed, fixes = fix(df1, issues1)
        df2 = parse(fixed)
        issues2 = analyze(df2)
        # Should have fewer issues
        assert len(issues2) < len(issues1)


# =========================================================================
# 6. CLI integration (8+ tests)
# =========================================================================

class TestCLIIntegration:
    """CLI integration tests using tmp_dockerfile fixture."""

    def test_cli_basic_analysis(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"hi\"]\n")
        ret = main([str(p)])
        captured = capsys.readouterr()
        # Should run without crashing
        assert ret == 0 or ret == 1  # depends on whether errors found
        assert len(captured.out) > 0

    def test_cli_json_format(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"hi\"]\n")
        ret = main([str(p), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "version" in data
        assert "files" in data
        assert "totals" in data
        assert len(data["files"]) == 1

    def test_cli_score_flag(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"hi\"]\n")
        ret = main([str(p), "--score"])
        captured = capsys.readouterr()
        assert "Grade:" in captured.out
        assert "/100" in captured.out

    def test_cli_score_with_json_format(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"hi\"]\n")
        ret = main([str(p), "--score", "--format", "json"])
        captured = capsys.readouterr()
        # JSON output comes first, then score
        assert "Grade:" in captured.out

    def test_cli_fix_flag(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        content = "FROM python:3.11\nRUN pip install flask\nCMD python app.py\n"
        p = tmp_dockerfile(content)
        ret = main([str(p), "--fix"])
        # Read back the fixed file
        fixed = p.read_text(encoding="utf-8")
        assert "--no-cache-dir" in fixed

    def test_cli_severity_error_filter(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        content = """\
FROM ubuntu
ENV API_KEY=mysecret
RUN apt-get install curl
CMD echo hello
"""
        p = tmp_dockerfile(content)
        ret = main([str(p), "--severity", "error", "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        issues = data["files"][0]["issues"]
        # All issues should be error severity
        for issue in issues:
            assert issue["severity"] == "error"

    def test_cli_ignore_rules(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        content = "FROM ubuntu\nCMD echo hello\n"
        p = tmp_dockerfile(content)
        ret = main([str(p), "--ignore", "DD001,DD008,DD012", "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        issues = data["files"][0]["issues"]
        rule_ids = {i["ruleId"] for i in issues}
        assert "DD001" not in rule_ids
        assert "DD008" not in rule_ids
        assert "DD012" not in rule_ids

    def test_cli_multiple_files(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p1 = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"a\"]\n", "Dockerfile.a")
        p2 = tmp_dockerfile("FROM ubuntu\nCMD echo b\n", "Dockerfile.b")
        ret = main([str(p1), str(p2), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["totals"]["files"] == 2

    def test_cli_quiet_mode(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"hi\"]\n")
        ret = main([str(p), "-q"])
        captured = capsys.readouterr()
        # Quiet mode should produce minimal output
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        assert len(lines) <= 3

    def test_cli_no_color(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM ubuntu\nCMD echo hi\n")
        ret = main([str(p), "--no-color"])
        captured = capsys.readouterr()
        # No ANSI escape codes
        assert "\033[" not in captured.out

    def test_cli_output_to_file(self, tmp_dockerfile, tmp_path, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM alpine:3.19\nCMD [\"echo\", \"hi\"]\n")
        outfile = tmp_path / "output.json"
        ret = main([str(p), "--format", "json", "-o", str(outfile)])
        assert outfile.exists()
        data = json.loads(outfile.read_text(encoding="utf-8"))
        assert "files" in data

    def test_cli_sarif_format(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        p = tmp_dockerfile("FROM ubuntu\nCMD echo hello\n")
        ret = main([str(p), "--format", "sarif"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert "runs" in data
        assert len(data["runs"]) == 1

    def test_cli_returns_1_on_errors(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        # DD020 creates ERROR severity issues (API_KEY matches secret pattern)
        content = "FROM python:3.11\nENV API_KEY=secret123\nCMD [\"python\", \"app.py\"]\n"
        p = tmp_dockerfile(content)
        ret = main([str(p)])
        assert ret == 1

    def test_cli_returns_0_no_errors(self, tmp_dockerfile, capsys):
        from dockerfile_doctor.cli import main
        content = """\
FROM python:3.12-alpine
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
EXPOSE 8000
HEALTHCHECK CMD wget -q --spider http://localhost:8000/health || exit 1
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
"""
        p = tmp_dockerfile(content)
        ret = main([str(p)])
        assert ret == 0


# =========================================================================
# 7. Cross-rule interaction tests (bonus)
# =========================================================================

class TestCrossRuleInteractions:
    """Tests where multiple rules interact on the same instruction."""

    def test_apt_install_triggers_multiple_rules(self):
        """A single apt-get install can trigger DD003, DD004, DD023, DD035."""
        content = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install curl
CMD ["echo", "hello"]
"""
        df = parse(content)
        issues = analyze(df)
        # DD003: no --no-install-recommends
        assert has_rule(issues, "DD003")
        # DD004: no apt cache cleanup
        assert has_rule(issues, "DD004")
        # DD023: no -y flag
        assert has_rule(issues, "DD023")
        # DD035: no DEBIAN_FRONTEND
        assert has_rule(issues, "DD035")

    def test_all_apt_fixes_applied_together(self):
        """All apt-related fixes should work together without conflict."""
        content = """\
FROM ubuntu:22.04
RUN apt-get update && apt-get install curl
CMD ["echo", "hello"]
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "--no-install-recommends" in fixed
        assert "rm -rf /var/lib/apt/lists" in fixed
        assert "-y" in fixed

    def test_sudo_removal_and_pip_cache(self):
        """DD021 (sudo) and DD009 (pip cache) fix together."""
        content = """\
FROM python:3.11
RUN sudo pip install flask
CMD ["python", "app.py"]
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "sudo" not in fixed
        assert "--no-cache-dir" in fixed

    def test_consecutive_run_and_individual_fixes(self):
        """DD005 (combine RUN) should work alongside per-RUN fixes."""
        content = """\
FROM python:3.11
RUN pip install flask
RUN pip install django
CMD ["python", "app.py"]
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        df2 = parse(fixed)
        # Either runs are combined or individual fixes apply
        assert len(df2.instructions) > 0

    def test_add_to_copy_and_shell_form(self):
        """DD007 (ADD->COPY) and DD019 (shell form) fixes together."""
        content = """\
FROM python:3.11
ADD app.py /app/
CMD python app.py
"""
        fixed, issues, fixes = _analyze_and_fix(content)
        assert "COPY app.py /app/" in fixed
        assert "ADD" not in fixed

    def test_duplicate_cmd_and_shell_form(self):
        """DD036 (duplicate CMD) and DD019 (shell form) on same file."""
        content = """\
FROM python:3.11
CMD echo first
CMD echo second
"""
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD036")
        assert has_rule(issues, "DD019")

    def test_instruction_casing_fix(self):
        """DD071: lowercase instructions should be uppercased."""
        content = """\
from python:3.11
run pip install flask
cmd python app.py
"""
        df = parse(content)
        issues = analyze(df)
        assert has_rule(issues, "DD071")
        fixed, _, fixes = _analyze_and_fix(content)
        assert "FROM" in fixed
        assert "RUN" in fixed
        assert "CMD" in fixed
