"""Tests for new fixer handlers: DD008, DD015, DD046, DD068."""

from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze
from dockerfile_doctor.fixer import fix


# ===== DD008 — No USER instruction =====

def test_dd008_fix_adds_user_before_cmd():
    content = "FROM python:3.12\nRUN pip install flask\nCMD [\"python\", \"app.py\"]\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "USER nobody" in fixed
    assert any(f.rule_id == "DD008" for f in fixes)
    # USER should appear before CMD
    lines = fixed.splitlines()
    user_idx = next(i for i, l in enumerate(lines) if l.strip() == "USER nobody")
    cmd_idx = next(i for i, l in enumerate(lines) if "CMD" in l)
    assert user_idx < cmd_idx


def test_dd008_fix_adds_user_before_entrypoint():
    content = "FROM python:3.12\nRUN pip install flask\nENTRYPOINT [\"python\", \"app.py\"]\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "USER nobody" in fixed
    assert any(f.rule_id == "DD008" for f in fixes)


def test_dd008_fix_appends_when_no_cmd():
    content = "FROM python:3.12\nRUN pip install flask\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "USER nobody" in fixed
    assert fixed.strip().endswith("USER nobody")


def test_dd008_no_fix_when_user_exists():
    content = "FROM python:3.12\nUSER app\nCMD [\"python\", \"app.py\"]\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert not any(f.rule_id == "DD008" for f in fixes)


def test_dd008_no_fix_for_root_user():
    """The root USER case (line_number != 0) should NOT be auto-fixed."""
    content = "FROM python:3.12\nUSER root\nCMD [\"python\", \"app.py\"]\n"
    df = parse(content)
    issues = analyze(df)
    # There should be a DD008 issue for root, but no fix applied
    assert any(i.rule_id == "DD008" for i in issues)
    fixed, fixes = fix(df, issues)
    assert not any(f.rule_id == "DD008" for f in fixes)


# ===== DD015 — Missing Python env vars =====

def test_dd015_fix_adds_python_env():
    content = "FROM python:3.12\nRUN pip install flask\nCMD [\"python\", \"app.py\"]\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "PYTHONUNBUFFERED=1" in fixed
    assert "PYTHONDONTWRITEBYTECODE=1" in fixed
    assert any(f.rule_id == "DD015" for f in fixes)


def test_dd015_no_fix_when_env_exists():
    content = "FROM python:3.12\nENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1\nCMD [\"python\", \"app.py\"]\n"
    df = parse(content)
    issues = analyze(df)
    assert not any(i.rule_id == "DD015" for i in issues)
    fixed, fixes = fix(df, issues)
    assert not any(f.rule_id == "DD015" for f in fixes)


def test_dd015_no_fix_for_non_python():
    content = "FROM node:20\nRUN npm install\nCMD [\"node\", \"app.js\"]\n"
    df = parse(content)
    issues = analyze(df)
    assert not any(i.rule_id == "DD015" for i in issues)


# ===== DD046 — No LABEL instructions =====

def test_dd046_auto_fixed():
    """DD046 (no LABEL) is reported and auto-fixed with LABEL after FROM."""
    content = "FROM python:3.12\nRUN pip install flask\n"
    df = parse(content)
    issues = analyze(df)
    assert any(i.rule_id == "DD046" for i in issues)
    assert any(i.rule_id == "DD046" and i.fix_available for i in issues)
    fixed, fixes = fix(df, issues)
    assert any(f.rule_id == "DD046" for f in fixes)
    assert "LABEL" in fixed


def test_dd046_no_fix_when_label_exists():
    content = 'FROM python:3.12\nLABEL maintainer="me"\nRUN pip install flask\n'
    df = parse(content)
    issues = analyze(df)
    assert not any(i.rule_id == "DD046" for i in issues)
    fixed, fixes = fix(df, issues)
    assert not any(f.rule_id == "DD046" for f in fixes)


# ===== DD068 — Java without container flags =====

def test_dd068_fix_adds_java_opts():
    content = "FROM openjdk:17\nCOPY app.jar /app.jar\nCMD [\"java\", \"-jar\", \"/app.jar\"]\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "UseContainerSupport" in fixed
    assert "MaxRAMPercentage" in fixed
    assert any(f.rule_id == "DD068" for f in fixes)


def test_dd068_fix_with_eclipse_temurin():
    content = "FROM eclipse-temurin:21\nCOPY app.jar /app.jar\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "JAVA_OPTS" in fixed
    assert any(f.rule_id == "DD068" for f in fixes)


def test_dd068_no_fix_when_flags_exist():
    content = "FROM openjdk:17\nENV JAVA_OPTS=\"-XX:+UseContainerSupport\"\nCMD [\"java\", \"-jar\", \"/app.jar\"]\n"
    df = parse(content)
    issues = analyze(df)
    assert not any(i.rule_id == "DD068" for i in issues)
    fixed, fixes = fix(df, issues)
    assert not any(f.rule_id == "DD068" for f in fixes)


def test_dd068_no_fix_for_non_java():
    content = "FROM python:3.12\nRUN pip install flask\n"
    df = parse(content)
    issues = analyze(df)
    assert not any(i.rule_id == "DD068" for i in issues)


# ===== Bug fix regression tests =====

def test_dd041_does_not_rewrite_dot_dest():
    """COPY . . should NOT become COPY . /. — dot means current WORKDIR."""
    content = "FROM ubuntu:22.04\nCOPY . .\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "COPY . /." not in fixed
    assert not any(f.rule_id == "DD041" for f in fixes)


def test_dd041_rewrites_real_relative_path():
    """COPY app.py app.py → COPY app.py /app.py (genuine relative path)."""
    content = "FROM ubuntu:22.04\nCOPY app.py app.py\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "COPY app.py /app.py" in fixed
    assert any(f.rule_id == "DD041" for f in fixes)


def test_dd059_directory_dest_extracts_filename():
    """ADD URL /app/ should produce curl -o /app/file.tar.gz, not -o /app/."""
    content = "FROM ubuntu:22.04\nADD https://example.com/file.tar.gz /app/\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "/app/file.tar.gz" in fixed
    assert "/app/ " not in fixed  # no trailing slash as dest


def test_dd059_file_dest_unchanged():
    """ADD URL /app/file.tar.gz should keep dest as-is."""
    content = "FROM ubuntu:22.04\nADD https://example.com/file.tar.gz /app/file.tar.gz\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    assert "curl -fsSL -o /app/file.tar.gz" in fixed


def test_dd015_multistage_inserts_in_python_stage():
    """DD015 should insert ENV in the Python stage, not the Node builder stage."""
    content = "FROM node:18 AS builder\nRUN npm install\n\nFROM python:3.12\nRUN pip install flask\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    lines = fixed.splitlines()
    env_idx = next(i for i, l in enumerate(lines) if "PYTHONUNBUFFERED" in l)
    python_from_idx = next(i for i, l in enumerate(lines) if "python:3.12" in l)
    node_from_idx = next(i for i, l in enumerate(lines) if "node:18" in l)
    # ENV should be right after the Python FROM, not the Node FROM
    assert env_idx == python_from_idx + 1
    assert env_idx > node_from_idx


def test_dd035_multistage_inserts_in_apt_stage():
    """DD035 should insert ARG in the stage that uses apt-get, not the first stage."""
    content = "FROM node:18 AS builder\nRUN npm install\n\nFROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
    df = parse(content)
    issues = analyze(df)
    fixed, fixes = fix(df, issues)
    lines = fixed.splitlines()
    arg_idx = next(i for i, l in enumerate(lines) if "DEBIAN_FRONTEND" in l)
    ubuntu_from_idx = next(i for i, l in enumerate(lines) if "ubuntu:22.04" in l)
    node_from_idx = next(i for i, l in enumerate(lines) if "node:18" in l)
    # ARG should be right after the Ubuntu FROM, not the Node FROM
    assert arg_idx == ubuntu_from_idx + 1
    assert arg_idx > node_from_idx
