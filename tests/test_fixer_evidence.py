"""Machine-checkable evidence for fixer confidence.

These tests define what "we trust a fixer" means for the suite. The confidence
source is not a human assertion; it is a bundle of registry, differential,
operation, convergence, and independent regression-reference checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dockerfile_doctor.fixer import _FIX_HANDLERS, _fix_with_review_only, fix
from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze

from tests.rule_cases import RULE_CASES
from tests.rule_matrix import FixPolicy, RULE_MATRIX


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _PROJECT_ROOT / "tests"
_MATRIX_LAYER_FILES = {
    "rule_cases.py",
    "rule_matrix.py",
    "test_fixer_evidence.py",
    "test_rule_contracts.py",
    "test_rule_matrix.py",
}


def _fixable_entries():
    return [entry for entry in RULE_MATRIX if entry.fix_policy is not FixPolicy.ADVISORY]


def _legacy_reference_counts(rule_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        if path.name in _MATRIX_LAYER_FILES:
            continue
        count = path.read_text(encoding="utf-8-sig").count(rule_id)
        if count:
            counts[path.name] = count
    return counts


def _rule_issues(content: str, rule_id: str):
    return [issue for issue in analyze(parse(content)) if issue.rule_id == rule_id]


@pytest.mark.parametrize("entry", _fixable_entries(), ids=lambda entry: entry.rule_id)
def test_fixers_have_independent_regression_references(entry):
    counts = _legacy_reference_counts(entry.rule_id)
    assert len(counts) >= 2, (
        f"{entry.rule_id} needs independent regression references outside "
        f"the matrix layer; found {counts}"
    )
    assert sum(counts.values()) >= 3, (
        f"{entry.rule_id} has too little non-matrix regression evidence: {counts}"
    )


@pytest.mark.parametrize(
    "entry",
    [entry for entry in RULE_MATRIX if entry.fix_policy is FixPolicy.SAFE],
    ids=lambda entry: entry.rule_id,
)
def test_safe_fixer_evidence_bundle(entry):
    case = RULE_CASES[entry.rule_id]
    before = parse(case.trigger)
    issues = [issue for issue in analyze(before) if issue.rule_id == entry.rule_id]

    fixed_content, fixes = fix(before, issues)
    applied = [applied for applied in fixes if applied.rule_id == entry.rule_id]
    fixed_again, fixes_again = fix(parse(fixed_content), analyze(parse(fixed_content)))

    assert entry.rule_id in _FIX_HANDLERS
    assert issues
    assert not _rule_issues(case.clean, entry.rule_id)
    assert all(issue.fix_available for issue in issues)
    assert applied
    assert fixed_content != case.trigger
    assert not _rule_issues(fixed_content, entry.rule_id)
    assert fixed_again == fixed_content
    assert not any(applied.rule_id == entry.rule_id for applied in fixes_again)

    for applied_fix in applied:
        assert applied_fix.description
        assert (
            applied_fix.replacements
            or applied_fix.insertions
            or applied_fix.deletions
        ), f"{entry.rule_id} fix did not record a concrete operation"


@pytest.mark.parametrize(
    "entry",
    [entry for entry in RULE_MATRIX if entry.fix_policy is FixPolicy.REVIEW_ONLY],
    ids=lambda entry: entry.rule_id,
)
def test_review_only_fixer_evidence_bundle(entry):
    case = RULE_CASES[entry.rule_id]
    before = parse(case.trigger)
    issues = [issue for issue in analyze(before) if issue.rule_id == entry.rule_id]

    public_fixed, public_fixes = fix(before, issues)
    targeted_fixed, targeted_fixes = _fix_with_review_only(before, issues)
    targeted_applied = [
        applied for applied in targeted_fixes if applied.rule_id == entry.rule_id
    ]

    assert entry.rule_id in _FIX_HANDLERS
    assert issues
    assert not _rule_issues(case.clean, entry.rule_id)
    assert all(issue.fix_available for issue in issues)
    assert not any(applied.rule_id == entry.rule_id for applied in public_fixes)
    assert _rule_issues(public_fixed, entry.rule_id)
    assert targeted_applied
    assert targeted_fixed != case.trigger
    assert not _rule_issues(targeted_fixed, entry.rule_id)

    for applied_fix in targeted_applied:
        assert applied_fix.description
        assert (
            applied_fix.replacements
            or applied_fix.insertions
            or applied_fix.deletions
        ), f"{entry.rule_id} review-only fix did not record a concrete operation"
