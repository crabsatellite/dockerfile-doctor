"""Shared fixtures and helpers for Dockerfile Doctor tests."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from dockerfile_doctor.models import Issue, Severity, Category
from dockerfile_doctor.parser import parse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dockerfile(tmp_path):
    """Factory fixture: write content to a temp Dockerfile and return its path."""
    def _make(content: str, name: str = "Dockerfile") -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p
    return _make


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_rule_ids(issues: list[Issue]) -> set[str]:
    """Extract the set of rule IDs from a list of issues."""
    return {i.rule_id for i in issues}


def get_issues_for_rule(issues: list[Issue], rule_id: str) -> list[Issue]:
    """Filter issues to those matching a specific rule ID."""
    return [i for i in issues if i.rule_id == rule_id]


def has_rule(issues: list[Issue], rule_id: str) -> bool:
    """Check if a specific rule triggered."""
    return any(i.rule_id == rule_id for i in issues)


def count_rule(issues: list[Issue], rule_id: str) -> int:
    """Count how many times a rule triggered."""
    return sum(1 for i in issues if i.rule_id == rule_id)


def assert_issue(
    issue: Issue,
    rule_id: str,
    severity: Optional[Severity] = None,
    category: Optional[Category] = None,
    line_number: Optional[int] = None,
):
    """Assert properties of a single issue."""
    assert issue.rule_id == rule_id
    if severity is not None:
        assert issue.severity == severity
    if category is not None:
        assert issue.category == category
    if line_number is not None:
        assert issue.line_number == line_number
