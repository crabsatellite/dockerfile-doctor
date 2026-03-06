"""Tests for the Dockerfile Doctor diff mode."""

from __future__ import annotations

import pytest

from dockerfile_doctor.diff import (
    _parse_diff_hunks,
    get_changed_lines_from_diff,
    filter_issues_by_diff,
)
from dockerfile_doctor.models import Issue, Severity, Category


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_issue(line_number: int = 1, rule_id: str = "DD001") -> Issue:
    return Issue(
        rule_id=rule_id,
        title="Test",
        description="Test",
        severity=Severity.WARNING,
        category=Category.BEST_PRACTICE,
        line_number=line_number,
    )


# ===========================================================================
# Diff hunk parsing
# ===========================================================================

class TestDiffHunkParsing:
    def test_single_line_add(self):
        diff = "@@ -0,0 +5,1 @@\n+new line\n"
        assert _parse_diff_hunks(diff) == {5}

    def test_multi_line_add(self):
        diff = "@@ -0,0 +10,3 @@\n+line1\n+line2\n+line3\n"
        assert _parse_diff_hunks(diff) == {10, 11, 12}

    def test_deletion_only(self):
        diff = "@@ -5,2 +5,0 @@\n-old1\n-old2\n"
        assert _parse_diff_hunks(diff) == set()

    def test_multiple_hunks(self):
        diff = "@@ -1,1 +1,1 @@\n-old\n+new\n@@ -10,0 +10,2 @@\n+a\n+b\n"
        assert _parse_diff_hunks(diff) == {1, 10, 11}

    def test_empty_diff(self):
        assert _parse_diff_hunks("") == set()

    def test_context_ignored(self):
        diff = "@@ -1,3 +1,3 @@\n context\n-old\n+new\n context\n"
        assert _parse_diff_hunks(diff) == {1, 2, 3}

    def test_single_line_no_count(self):
        diff = "@@ -1 +1 @@\n-old\n+new\n"
        assert _parse_diff_hunks(diff) == {1}


# ===========================================================================
# Convenience wrapper
# ===========================================================================

class TestGetChangedLinesFromDiff:
    def test_basic(self):
        diff = "@@ -0,0 +1,3 @@\n+FROM ubuntu\n+RUN echo\n+CMD bash\n"
        lines = get_changed_lines_from_diff(diff)
        assert lines == {1, 2, 3}


# ===========================================================================
# Issue filtering
# ===========================================================================

class TestFilterIssuesByDiff:
    def test_filters_unchanged_lines(self):
        issues = [_make_issue(line_number=1), _make_issue(line_number=5)]
        changed = {5, 6}
        filtered = filter_issues_by_diff(issues, changed)
        assert len(filtered) == 1
        assert filtered[0].line_number == 5

    def test_file_level_always_passes(self):
        issues = [_make_issue(line_number=0)]
        changed = {5}
        filtered = filter_issues_by_diff(issues, changed)
        assert len(filtered) == 1

    def test_none_means_all_pass(self):
        issues = [_make_issue(line_number=1), _make_issue(line_number=100)]
        filtered = filter_issues_by_diff(issues, None)
        assert len(filtered) == 2

    def test_empty_changed_filters_all(self):
        issues = [_make_issue(line_number=1), _make_issue(line_number=5)]
        filtered = filter_issues_by_diff(issues, set())
        assert len(filtered) == 0

    def test_multiple_issues_same_line(self):
        issues = [
            _make_issue(line_number=3, rule_id="DD001"),
            _make_issue(line_number=3, rule_id="DD002"),
        ]
        changed = {3}
        filtered = filter_issues_by_diff(issues, changed)
        assert len(filtered) == 2
