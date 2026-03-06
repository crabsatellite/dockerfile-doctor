"""Diff mode for Dockerfile Doctor — filter issues to changed lines only."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional


def get_changed_lines(filepath: str, diff_ref: str = "HEAD") -> Optional[set[int]]:
    """Get the set of changed line numbers in *filepath* relative to *diff_ref*.

    Returns None if the file is untracked (all lines are "changed").
    Returns an empty set if the file has no changes.
    """
    path = Path(filepath).resolve()

    try:
        # First check if the file is tracked
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            capture_output=True,
            text=True,
            cwd=str(path.parent),
        )
        if result.returncode != 0:
            # Untracked file — all lines are "new"
            return None
    except FileNotFoundError:
        # git not available
        return None

    try:
        # Get unified diff
        result = subprocess.run(
            ["git", "diff", "-U0", diff_ref, "--", str(path)],
            capture_output=True,
            text=True,
            cwd=str(path.parent),
        )
        if result.returncode != 0:
            return None
    except FileNotFoundError:
        return None

    return _parse_diff_hunks(result.stdout)


def get_changed_lines_from_diff(diff_text: str) -> set[int]:
    """Parse a unified diff and extract the changed line numbers in the new file."""
    return _parse_diff_hunks(diff_text)


def _parse_diff_hunks(diff_output: str) -> set[int]:
    """Extract changed line numbers from unified diff output.

    Parses @@ -a,b +c,d @@ hunk headers to find added/modified lines.
    """
    changed: set[int] = set()
    for match in re.finditer(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_output):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) else 1
        if count == 0:
            # Deletion only — no new lines
            continue
        for line_num in range(start, start + count):
            changed.add(line_num)
    return changed


def filter_issues_by_diff(issues: list, changed_lines: Optional[set[int]]) -> list:
    """Filter issues to only those on changed lines.

    If changed_lines is None (untracked file), all issues pass through.
    File-level issues (line_number=0) always pass through.
    """
    if changed_lines is None:
        return issues
    return [
        issue for issue in issues
        if issue.line_number == 0 or issue.line_number in changed_lines
    ]
