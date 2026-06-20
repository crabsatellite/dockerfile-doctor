"""Rule coverage matrix for Dockerfile Doctor tests.

This file is the test-suite table of contents. It does not replace the
behavioral tests; it gives each DD rule an explicit policy bucket, domain, and
primary legacy test location so rule coverage can be audited systematically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FixPolicy(str, Enum):
    """How the public fixer is allowed to treat a rule."""

    SAFE = "safe"
    REVIEW_ONLY = "review-only"
    ADVISORY = "advisory"


BASE_CONTRACTS = frozenset({
    "positive_case",
    "negative_case",
    "issue_metadata",
})

POLICY_CONTRACTS = {
    FixPolicy.SAFE: frozenset({
        "safe_fix_applies",
        "safe_fix_idempotent",
        "public_fix_applies",
    }),
    FixPolicy.REVIEW_ONLY: frozenset({
        "review_handler_targeted",
        "public_fix_skips_review",
    }),
    FixPolicy.ADVISORY: frozenset({
        "no_fix_handler",
        "reports_only",
    }),
}


@dataclass(frozen=True)
class RuleMatrixEntry:
    rule_id: str
    domain: str
    fix_policy: FixPolicy
    primary_test_file: str
    extra_contracts: frozenset[str] = frozenset()

    @property
    def contracts(self) -> frozenset[str]:
        return (
            BASE_CONTRACTS
            | POLICY_CONTRACTS[self.fix_policy]
            | self.extra_contracts
        )


def entry(
    rule_id: str,
    domain: str,
    fix_policy: FixPolicy,
    primary_test_file: str,
    *extra_contracts: str,
) -> RuleMatrixEntry:
    return RuleMatrixEntry(
        rule_id=rule_id,
        domain=domain,
        fix_policy=fix_policy,
        primary_test_file=primary_test_file,
        extra_contracts=frozenset(extra_contracts),
    )


SAFE = FixPolicy.SAFE
REVIEW = FixPolicy.REVIEW_ONLY
ADVISORY = FixPolicy.ADVISORY

LEGACY_RULES_001_020 = "test_rules.py"
LEGACY_RULES_021_080 = "test_rules_expanded.py"


RULE_MATRIX: tuple[RuleMatrixEntry, ...] = (
    entry("DD001", "base-image", ADVISORY, LEGACY_RULES_001_020),
    entry("DD002", "apt", ADVISORY, LEGACY_RULES_001_020),
    entry("DD003", "apt", REVIEW, LEGACY_RULES_001_020),
    entry("DD004", "apt", SAFE, LEGACY_RULES_001_020),
    entry("DD005", "layers", REVIEW, LEGACY_RULES_001_020),
    entry("DD006", "build-cache", ADVISORY, LEGACY_RULES_001_020),
    entry("DD007", "copy-add", SAFE, LEGACY_RULES_001_020),
    entry("DD008", "user-security", REVIEW, LEGACY_RULES_001_020),
    entry("DD009", "pip", SAFE, LEGACY_RULES_001_020),
    entry("DD010", "npm", REVIEW, LEGACY_RULES_001_020),
    entry("DD011", "workdir", SAFE, LEGACY_RULES_001_020),
    entry("DD012", "healthcheck", ADVISORY, LEGACY_RULES_001_020),
    entry("DD013", "apt", SAFE, LEGACY_RULES_001_020),
    entry("DD014", "ports", ADVISORY, LEGACY_RULES_001_020),
    entry("DD015", "python", REVIEW, LEGACY_RULES_001_020),
    entry("DD016", "download-cleanup", ADVISORY, LEGACY_RULES_001_020),
    entry("DD017", "metadata", SAFE, LEGACY_RULES_001_020),
    entry("DD018", "base-image", ADVISORY, LEGACY_RULES_001_020),
    entry("DD019", "command-form", SAFE, LEGACY_RULES_001_020),
    entry("DD020", "secrets", ADVISORY, LEGACY_RULES_001_020),
    entry("DD021", "shell", SAFE, LEGACY_RULES_021_080),
    entry("DD022", "apt", ADVISORY, LEGACY_RULES_021_080),
    entry("DD023", "apt", SAFE, LEGACY_RULES_021_080),
    entry("DD024", "apt", SAFE, LEGACY_RULES_021_080),
    entry("DD025", "apk", SAFE, LEGACY_RULES_021_080),
    entry("DD026", "apk", SAFE, LEGACY_RULES_021_080),
    entry("DD027", "apk", ADVISORY, LEGACY_RULES_021_080),
    entry("DD028", "pip", ADVISORY, LEGACY_RULES_021_080),
    entry("DD029", "npm", ADVISORY, LEGACY_RULES_021_080),
    entry("DD030", "gem", ADVISORY, LEGACY_RULES_021_080),
    entry("DD031", "yum", SAFE, LEGACY_RULES_021_080),
    entry("DD032", "yum", ADVISORY, LEGACY_RULES_021_080),
    entry("DD033", "dnf", SAFE, LEGACY_RULES_021_080),
    entry("DD034", "zypper", SAFE, LEGACY_RULES_021_080),
    entry("DD035", "apt", REVIEW, LEGACY_RULES_021_080),
    entry("DD036", "cmd", SAFE, LEGACY_RULES_021_080),
    entry("DD037", "entrypoint", SAFE, LEGACY_RULES_021_080),
    entry("DD038", "ports", ADVISORY, LEGACY_RULES_021_080),
    entry("DD039", "multistage", ADVISORY, LEGACY_RULES_021_080),
    entry("DD040", "shell", SAFE, LEGACY_RULES_021_080),
    entry("DD041", "copy-add", SAFE, LEGACY_RULES_021_080),
    entry("DD042", "onbuild", ADVISORY, LEGACY_RULES_021_080),
    entry("DD043", "shell", SAFE, LEGACY_RULES_021_080),
    entry("DD044", "env", SAFE, LEGACY_RULES_021_080),
    entry("DD045", "workdir", SAFE, LEGACY_RULES_021_080),
    entry("DD046", "metadata", REVIEW, LEGACY_RULES_021_080),
    entry("DD047", "run", SAFE, LEGACY_RULES_021_080),
    entry("DD048", "ports", SAFE, LEGACY_RULES_021_080),
    entry("DD049", "healthcheck", SAFE, LEGACY_RULES_021_080),
    entry("DD050", "stages", SAFE, LEGACY_RULES_021_080),
    entry("DD051", "permissions", SAFE, LEGACY_RULES_021_080),
    entry("DD052", "copy-security", ADVISORY, LEGACY_RULES_021_080),
    entry("DD053", "copy-security", ADVISORY, LEGACY_RULES_021_080),
    entry("DD054", "download-security", ADVISORY, LEGACY_RULES_021_080),
    entry("DD055", "download-security", SAFE, LEGACY_RULES_021_080),
    entry("DD056", "download-security", SAFE, LEGACY_RULES_021_080),
    entry("DD057", "git-security", ADVISORY, LEGACY_RULES_021_080),
    entry("DD058", "secrets", ADVISORY, LEGACY_RULES_021_080),
    entry("DD059", "copy-add", SAFE, LEGACY_RULES_021_080),
    entry("DD060", "privilege", ADVISORY, LEGACY_RULES_021_080),
    entry("DD061", "gem", SAFE, LEGACY_RULES_021_080),
    entry("DD062", "go", SAFE, LEGACY_RULES_021_080),
    entry("DD063", "apk", ADVISORY, LEGACY_RULES_021_080),
    entry("DD064", "layers", ADVISORY, LEGACY_RULES_021_080),
    entry("DD065", "run", SAFE, LEGACY_RULES_021_080),
    entry("DD066", "multistage", ADVISORY, LEGACY_RULES_021_080),
    entry("DD067", "node", REVIEW, LEGACY_RULES_021_080),
    entry("DD068", "java", SAFE, LEGACY_RULES_021_080),
    entry("DD069", "apt", ADVISORY, LEGACY_RULES_021_080),
    entry("DD070", "build-context", ADVISORY, LEGACY_RULES_021_080),
    entry("DD071", "formatting", SAFE, LEGACY_RULES_021_080),
    entry("DD072", "comments", REVIEW, LEGACY_RULES_021_080),
    entry("DD073", "formatting", SAFE, LEGACY_RULES_021_080),
    entry("DD074", "formatting", ADVISORY, LEGACY_RULES_021_080),
    entry("DD075", "formatting", SAFE, LEGACY_RULES_021_080),
    entry("DD076", "formatting", SAFE, LEGACY_RULES_021_080),
    entry("DD077", "base-image", SAFE, LEGACY_RULES_021_080),
    entry("DD078", "metadata", REVIEW, LEGACY_RULES_021_080),
    entry("DD079", "stopsignal", SAFE, LEGACY_RULES_021_080),
    entry("DD080", "volume", SAFE, LEGACY_RULES_021_080),
)

RULE_MATRIX_BY_ID = {entry.rule_id: entry for entry in RULE_MATRIX}
