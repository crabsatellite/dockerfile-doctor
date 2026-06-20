"""Matrix-driven rule and fixer contract tests."""

from __future__ import annotations

import pytest

from dockerfile_doctor.fixer import _fix_with_review_only, fix
from dockerfile_doctor.models import Category, Severity
from dockerfile_doctor.parser import parse
from dockerfile_doctor.rules import analyze

from tests.rule_cases import RULE_CASES
from tests.rule_matrix import FixPolicy, RULE_MATRIX, RULE_MATRIX_BY_ID


def _issues_for(content: str, rule_id: str):
    return [issue for issue in analyze(parse(content)) if issue.rule_id == rule_id]


@pytest.mark.parametrize("entry", RULE_MATRIX, ids=lambda entry: entry.rule_id)
def test_rule_contract_trigger_case_reports_rule(entry):
    issues = _issues_for(RULE_CASES[entry.rule_id].trigger, entry.rule_id)
    assert issues, f"{entry.rule_id} trigger case did not report the rule"

    for issue in issues:
        assert issue.title
        assert issue.description
        assert isinstance(issue.severity, Severity)
        assert isinstance(issue.category, Category)
        assert issue.line_number >= 0

    expects_fix = entry.fix_policy is not FixPolicy.ADVISORY
    assert all(issue.fix_available is expects_fix for issue in issues)


@pytest.mark.parametrize("entry", RULE_MATRIX, ids=lambda entry: entry.rule_id)
def test_rule_contract_clean_case_suppresses_rule(entry):
    issues = _issues_for(RULE_CASES[entry.rule_id].clean, entry.rule_id)
    assert not issues, f"{entry.rule_id} clean case still reported the rule: {issues}"


@pytest.mark.parametrize(
    "entry",
    [entry for entry in RULE_MATRIX if entry.fix_policy is FixPolicy.SAFE],
    ids=lambda entry: entry.rule_id,
)
def test_safe_fix_contract_public_fix_applies_and_converges(entry):
    case = RULE_CASES[entry.rule_id]
    dockerfile = parse(case.trigger)
    issues = [issue for issue in analyze(dockerfile) if issue.rule_id == entry.rule_id]

    fixed_content, fixes = fix(dockerfile, issues)

    assert any(applied.rule_id == entry.rule_id for applied in fixes), (
        f"{entry.rule_id} is marked safe but public fix() did not apply it"
    )
    assert not _issues_for(fixed_content, entry.rule_id), (
        f"{entry.rule_id} was still reported after public fix()"
    )

    fixed_again, fixes_again = fix(parse(fixed_content), analyze(parse(fixed_content)))
    assert fixed_again == fixed_content
    assert not any(applied.rule_id == entry.rule_id for applied in fixes_again)


@pytest.mark.parametrize(
    "entry",
    [entry for entry in RULE_MATRIX if entry.fix_policy is FixPolicy.REVIEW_ONLY],
    ids=lambda entry: entry.rule_id,
)
def test_review_only_contract_public_fix_skips_but_targeted_helper_applies(entry):
    case = RULE_CASES[entry.rule_id]
    dockerfile = parse(case.trigger)
    issues = [issue for issue in analyze(dockerfile) if issue.rule_id == entry.rule_id]

    public_fixed, public_fixes = fix(dockerfile, issues)
    assert not any(applied.rule_id == entry.rule_id for applied in public_fixes)
    assert _issues_for(public_fixed, entry.rule_id), (
        f"{entry.rule_id} is review-only but public fix() removed it"
    )

    targeted_fixed, targeted_fixes = _fix_with_review_only(dockerfile, issues)
    assert any(applied.rule_id == entry.rule_id for applied in targeted_fixes), (
        f"{entry.rule_id} has a review-only handler but targeted helper did not apply it"
    )
    assert not _issues_for(targeted_fixed, entry.rule_id), (
        f"{entry.rule_id} was still reported after targeted review-only fix"
    )


@pytest.mark.parametrize(
    "entry",
    [entry for entry in RULE_MATRIX if entry.fix_policy is FixPolicy.ADVISORY],
    ids=lambda entry: entry.rule_id,
)
def test_advisory_contract_reports_without_fix(entry):
    issues = _issues_for(RULE_CASES[entry.rule_id].trigger, entry.rule_id)
    assert issues
    assert all(not issue.fix_available for issue in issues)


def test_rule_cases_cover_matrix_exactly():
    assert set(RULE_CASES) == set(RULE_MATRIX_BY_ID)
