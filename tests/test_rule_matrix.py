"""Tests for the rule coverage matrix."""

from __future__ import annotations

import re
from pathlib import Path

from dockerfile_doctor.fixer import _FIX_HANDLERS, _REVIEW_ONLY_RULES
from dockerfile_doctor.rules import ALL_RULES

from tests.rule_matrix import (
    BASE_CONTRACTS,
    POLICY_CONTRACTS,
    FixPolicy,
    RULE_MATRIX,
)
from tests.rule_cases import RULE_CASES


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _PROJECT_ROOT / "tests"


def _registered_rule_ids() -> set[str]:
    rule_ids = set()
    for fn in ALL_RULES:
        match = re.match(r"dd(\d{3})_", fn.__name__)
        assert match, f"Rule function {fn.__name__!r} does not use dd###_ naming"
        rule_ids.add(f"DD{match.group(1)}")
    return rule_ids


def _matrix_ids(policy: FixPolicy | None = None) -> set[str]:
    return {
        entry.rule_id
        for entry in RULE_MATRIX
        if policy is None or entry.fix_policy is policy
    }


def _readme_rule_ids(section_title: str) -> set[str]:
    readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    pattern = (
        rf"^### {re.escape(section_title)}\n\n"
        r"(?P<body>.*?)(?=^### |^## |\Z)"
    )
    match = re.search(pattern, readme, flags=re.MULTILINE | re.DOTALL)
    assert match, f"README section not found: {section_title}"
    return set(re.findall(r"DD\d{3}", match.group("body")))


def test_matrix_has_one_entry_per_registered_rule():
    assert _matrix_ids() == _registered_rule_ids()
    assert len(RULE_MATRIX) == len(_registered_rule_ids())


def test_matrix_is_sorted_and_unique():
    ids = [entry.rule_id for entry in RULE_MATRIX]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def test_matrix_policy_partitions_match_fixer_registry():
    registered = _registered_rule_ids()
    handler_ids = set(_FIX_HANDLERS)
    review_only = set(_REVIEW_ONLY_RULES)

    assert _matrix_ids(FixPolicy.SAFE) == handler_ids - review_only
    assert _matrix_ids(FixPolicy.REVIEW_ONLY) == review_only
    assert _matrix_ids(FixPolicy.ADVISORY) == registered - handler_ids


def test_matrix_policy_partitions_match_readme():
    assert _matrix_ids(FixPolicy.SAFE) == _readme_rule_ids(
        "Research Safe-Fix Bucket"
    )
    assert _matrix_ids(FixPolicy.REVIEW_ONLY) == _readme_rule_ids(
        "Review-Only Suggestions"
    )
    assert _matrix_ids(FixPolicy.ADVISORY) == _readme_rule_ids(
        "Advisory / Non-Fix Rules"
    )


def test_every_matrix_entry_has_required_contracts():
    for entry in RULE_MATRIX:
        assert entry.domain
        assert BASE_CONTRACTS <= entry.contracts
        assert POLICY_CONTRACTS[entry.fix_policy] <= entry.contracts


def test_matrix_entries_have_canonical_cases():
    assert set(RULE_CASES) == _matrix_ids()
    for entry in RULE_MATRIX:
        case = RULE_CASES[entry.rule_id]
        assert case.trigger
        assert case.clean
        assert case.trigger != case.clean


def test_primary_legacy_test_files_exist_and_reference_rule_classes():
    for entry in RULE_MATRIX:
        test_file = _TESTS_DIR / entry.primary_test_file
        assert test_file.exists(), f"{entry.rule_id} points to missing {test_file}"

        source = test_file.read_text(encoding="utf-8-sig")
        class_pattern = rf"class\s+Test{entry.rule_id}\w*"
        assert re.search(class_pattern, source), (
            f"{entry.primary_test_file} should expose a Test{entry.rule_id}* "
            f"class for {entry.rule_id}"
        )
