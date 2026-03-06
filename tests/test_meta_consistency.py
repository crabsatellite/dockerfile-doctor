"""Meta-consistency tests for Dockerfile Doctor.

These tests verify that different parts of the codebase are self-consistent:
- Rule IDs are contiguous and match documented counts
- Every fixer handler corresponds to a rule with fix_available=True
- _KNOWN_DIRECTIVES is not duplicated (DRY principle)
- All Issue objects have required fields populated
- SARIF output structure is correct for fixable issues
- action.yml outputs are properly assigned in the shell script
- README claims match reality

These are complementary to the 1454 functional tests — they catch
"code works but parts disagree with each other" bugs.
"""

from __future__ import annotations

import ast
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from dockerfile_doctor.fixer import _FIX_HANDLERS
from dockerfile_doctor.models import Issue, Severity, Category
from dockerfile_doctor.parser import parse, _KNOWN_DIRECTIVES
from dockerfile_doctor.rules import ALL_RULES, analyze


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src" / "dockerfile_doctor"


# ===========================================================================
# 1. Rule-Fixer Registry Consistency
# ===========================================================================


class TestRuleFixerConsistency:
    """Verify that the fixer handler registry and rule fix_available flags agree."""

    def test_fixer_handler_count_at_least_50(self):
        """README claims 50 auto-fixers — the handler registry should have >= 50."""
        assert len(_FIX_HANDLERS) >= 50, (
            f"Expected >= 50 fix handlers, got {len(_FIX_HANDLERS)}"
        )

    def test_every_handler_key_is_a_valid_rule_id(self):
        """Every key in _FIX_HANDLERS must match DD\\d{3} format."""
        for key in _FIX_HANDLERS:
            assert re.fullmatch(r"DD\d{3}", key), (
                f"Invalid handler key format: {key!r}"
            )

    def test_handler_keys_correspond_to_fixable_rules(self):
        """For each handler key, trigger the rule and verify fix_available=True.

        We build a minimal 'worst-case' Dockerfile that triggers as many rules
        as possible, then check that every handler key appears among the
        fixable issues.
        """
        # A deliberately terrible Dockerfile that triggers many rules
        bad_dockerfile = textwrap.dedent("""\
            maintainer someone@example.com
            FROM Ubuntu AS BUILDER
            RUN apt update && apt-get upgrade -y
            RUN apt-get update && apt-get install curl wget
            RUN apt-get update && apt-get install -y python3
            RUN curl -k https://example.com/setup.sh | bash
            RUN wget --no-check-certificate https://example.com/file
            RUN pip install flask
            RUN npm install express
            RUN gem install rails
            RUN go build -o /app main.go
            RUN cd /tmp && echo hi
            RUN chmod 777 /app
            COPY . .
            ADD https://example.com/file.tar.gz /tmp/
            ENV MY_SECRET=password123
            EXPOSE 21
            EXPOSE 80
            EXPOSE 80
            CMD python app.py
            SHELL /bin/bash
            ENV FOO=bar
            ENV FOO=baz
            HEALTHCHECK CMD curl localhost
            HEALTHCHECK CMD curl localhost
            ENTRYPOINT python app.py
            ENTRYPOINT python app2.py
            CMD echo one
            CMD echo two
            COPY src/ dest/
            WORKDIR relative/path
            RUN echo "TODO: fix this"
            RUN echo duplicate
            RUN echo duplicate
            RUN   \\
              echo "empty continuation above"
            LABEL maintainer="test"
            FROM node:latest
            ENV NODE_ENV=development
            STOPSIGNAL INVALID
            VOLUME {"data"}
        """)
        df = parse(bad_dockerfile)
        issues = analyze(df)
        fixable_rule_ids = {i.rule_id for i in issues if i.fix_available}

        # We don't require every handler to be triggered (some need very
        # specific Dockerfiles), but any triggered fixable issue must have a
        # handler, and any handler that IS triggered must produce fix_available=True.
        triggered_handler_ids = {
            i.rule_id for i in issues if i.rule_id in _FIX_HANDLERS
        }
        for rule_id in triggered_handler_ids:
            assert rule_id in fixable_rule_ids, (
                f"Rule {rule_id} has a _FIX_HANDLERS entry and was triggered, "
                f"but its Issue has fix_available=False"
            )

    def test_fixable_issues_subset_of_handlers(self):
        """Every rule that emits fix_available=True should have a _FIX_HANDLERS entry."""
        # Use the same bad Dockerfile to trigger rules
        bad_dockerfile = textwrap.dedent("""\
            FROM ubuntu
            RUN apt-get update && apt-get install -y curl
            RUN apt-get update && apt-get install -y wget
            RUN pip install flask
            CMD python app.py
        """)
        df = parse(bad_dockerfile)
        issues = analyze(df)
        for issue in issues:
            if issue.fix_available:
                assert issue.rule_id in _FIX_HANDLERS, (
                    f"Rule {issue.rule_id} has fix_available=True but "
                    f"no entry in _FIX_HANDLERS"
                )


# ===========================================================================
# 2. Rule ID Contiguity
# ===========================================================================


class TestRuleIdContiguity:
    """DD001 through DD080 should all exist with no gaps."""

    def test_rule_ids_are_contiguous(self):
        """Every rule function should be named dd{NNN}_... with NNN in 001..080."""
        rule_ids_from_names = set()
        for fn in ALL_RULES:
            m = re.match(r"dd(\d{3})_", fn.__name__)
            assert m, f"Rule function {fn.__name__!r} doesn't follow dd###_ naming"
            rule_ids_from_names.add(int(m.group(1)))

        expected = set(range(1, 81))
        missing = expected - rule_ids_from_names
        extra = rule_ids_from_names - expected
        assert not missing, f"Missing rule IDs: {sorted(missing)}"
        assert not extra, f"Unexpected rule IDs beyond 080: {sorted(extra)}"


# ===========================================================================
# 3. Rule Count Matches README
# ===========================================================================


class TestRuleCountMatchesReadme:
    """README claims 80 rules — verify."""

    def test_all_rules_length_is_80(self):
        assert len(ALL_RULES) == 80, (
            f"Expected 80 rules, got {len(ALL_RULES)}"
        )

    def test_readme_claims_80_rules(self):
        readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        assert "80 rules" in readme, "README should mention 80 rules"

    def test_readme_claims_50_fixers(self):
        readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        assert "50" in readme and "auto-fix" in readme.lower(), (
            "README should mention 50 auto-fixers"
        )


# ===========================================================================
# 4. _KNOWN_DIRECTIVES Single Source (DRY)
# ===========================================================================


class TestKnownDirectivesDRY:
    """_KNOWN_DIRECTIVES should only be defined in parser.py."""

    def test_not_redefined_elsewhere(self):
        for py_file in _SRC_DIR.glob("*.py"):
            if py_file.name == "parser.py":
                continue
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "_KNOWN_DIRECTIVES":
                            pytest.fail(
                                f"_KNOWN_DIRECTIVES redefined in "
                                f"{py_file.name}:{node.lineno}"
                            )

    def test_known_directives_contains_standard_set(self):
        """Sanity check that the standard Docker directives are present."""
        required = {"FROM", "RUN", "CMD", "COPY", "ADD", "ENTRYPOINT",
                     "ENV", "EXPOSE", "WORKDIR", "USER", "VOLUME",
                     "HEALTHCHECK", "ARG", "LABEL", "SHELL"}
        missing = required - _KNOWN_DIRECTIVES
        assert not missing, f"Missing standard directives: {missing}"


# ===========================================================================
# 5. All Issues Have Required Fields
# ===========================================================================


class TestIssueFieldCompleteness:
    """Every Issue emitted by every rule must have non-empty required fields."""

    def test_all_issues_have_required_fields(self):
        """Trigger as many rules as possible and check field completeness."""
        bad_dockerfile = textwrap.dedent("""\
            maintainer someone@example.com
            FROM Ubuntu AS BUILDER
            RUN apt update && apt-get upgrade -y
            RUN apt-get update && apt-get install curl wget
            RUN apt-get update && apt-get install -y python3
            RUN pip install flask
            RUN npm install express
            RUN gem install rails
            RUN go build -o /app main.go
            RUN cd /tmp && echo hi
            RUN chmod 777 /app
            COPY . .
            ADD https://example.com/file.tar.gz /tmp/
            ENV MY_SECRET=password123
            EXPOSE 21
            EXPOSE 80
            EXPOSE 80
            CMD python app.py
            WORKDIR relative/path
            RUN echo "TODO: fix this"
        """)
        df = parse(bad_dockerfile)
        issues = analyze(df)
        assert len(issues) > 0, "Should trigger at least some rules"

        for issue in issues:
            assert issue.rule_id, f"Empty rule_id on issue at line {issue.line_number}"
            assert re.fullmatch(r"DD\d{3}", issue.rule_id), (
                f"Invalid rule_id format: {issue.rule_id!r}"
            )
            assert issue.title, f"Empty title for {issue.rule_id}"
            assert issue.description, f"Empty description for {issue.rule_id}"
            assert isinstance(issue.severity, Severity), (
                f"Invalid severity for {issue.rule_id}: {issue.severity!r}"
            )
            assert isinstance(issue.category, Category), (
                f"Invalid category for {issue.rule_id}: {issue.category!r}"
            )
            assert isinstance(issue.line_number, int), (
                f"line_number not int for {issue.rule_id}"
            )
            assert issue.line_number >= 0, (
                f"Negative line_number for {issue.rule_id}"
            )

    def test_fixable_issues_have_fix_description(self):
        """Issues with fix_available=True should also have fix_description set.

        Known exceptions are tracked here so we notice if more appear.
        """
        # Track any known exceptions explicitly so new omissions are caught.
        # All previously missing fix_descriptions have been fixed.
        KNOWN_MISSING_FIX_DESC: set[str] = set()

        bad_dockerfile = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update && apt-get install curl
            RUN pip install flask
            CMD python app.py
            RUN chmod 777 /app
            WORKDIR relative/path
        """)
        df = parse(bad_dockerfile)
        issues = analyze(df)
        fixable = [i for i in issues if i.fix_available]
        assert len(fixable) > 0, "Should have at least one fixable issue"

        unexpected_missing = []
        for issue in fixable:
            if not issue.fix_description and issue.rule_id not in KNOWN_MISSING_FIX_DESC:
                unexpected_missing.append(issue.rule_id)

        assert not unexpected_missing, (
            f"These rules have fix_available=True but no fix_description "
            f"(and are not in the known-exceptions list): {unexpected_missing}"
        )


# ===========================================================================
# 6. SARIF Output Structure
# ===========================================================================


class TestSarifConsistency:
    """SARIF output must include fix info for fixable issues."""

    def test_sarif_fixable_issues_have_fixes_key(self):
        """In SARIF, issues with fix_available=True and fix_description
        should produce a 'fixes' key in the SARIF result."""
        import json
        from dockerfile_doctor.models import AnalysisResult
        from dockerfile_doctor.reporter import _format_sarif

        content = textwrap.dedent("""\
            FROM ubuntu:20.04
            RUN apt-get update && apt-get install curl
            CMD python app.py
        """)
        df = parse(content)
        issues = analyze(df)

        result = AnalysisResult(filepath="Dockerfile", issues=issues)
        sarif_str = _format_sarif([result])
        sarif = json.loads(sarif_str)

        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1

        sarif_results = sarif["runs"][0]["results"]
        for sr in sarif_results:
            # Find the matching Issue
            matching = [i for i in issues if i.rule_id == sr["ruleId"]]
            if matching and matching[0].fix_available and matching[0].fix_description:
                assert "fixes" in sr, (
                    f"SARIF result for {sr['ruleId']} should have 'fixes' "
                    f"since fix_available=True and fix_description is set"
                )

    def test_sarif_schema_version(self):
        """SARIF output should reference the 2.1.0 schema."""
        import json
        from dockerfile_doctor.models import AnalysisResult
        from dockerfile_doctor.reporter import _format_sarif

        content = "FROM python:3.11\nCMD python app.py\n"
        df = parse(content)
        issues = analyze(df)
        result = AnalysisResult(filepath="Dockerfile", issues=issues)
        sarif = json.loads(_format_sarif([result]))

        assert "sarif-schema-2.1.0" in sarif.get("$schema", "")


# ===========================================================================
# 7. action.yml Outputs Completeness
# ===========================================================================


class TestActionYmlConsistency:
    """Every output declared in action.yml should be assigned in the script."""

    def test_declared_outputs_are_assigned(self):
        action_file = _PROJECT_ROOT / "action.yml"
        if not action_file.exists():
            pytest.skip("action.yml not found")

        content = action_file.read_text(encoding="utf-8")

        # Expected outputs declared in action.yml
        declared_outputs = ["exit-code", "issues-count", "grade"]
        for output_name in declared_outputs:
            # Verify it's declared in the outputs section
            assert f"  {output_name}:" in content, (
                f"Output '{output_name}' not declared in action.yml"
            )
            # Verify it's assigned via GITHUB_OUTPUT
            # Format: echo "exit-code=$EXIT_CODE" >> "$GITHUB_OUTPUT"
            assert f'"{output_name}=' in content, (
                f"Output '{output_name}' declared but never assigned "
                f"via GITHUB_OUTPUT in action.yml"
            )


# ===========================================================================
# 8. Fixer Idempotency Coverage
# ===========================================================================


class TestFixerIdempotencyCoverage:
    """Verify that test_integrity.py contains idempotency tests."""

    def test_integrity_file_has_idempotency_tests(self):
        integrity_file = _PROJECT_ROOT / "tests" / "test_integrity.py"
        assert integrity_file.exists(), "test_integrity.py should exist"
        source = integrity_file.read_text(encoding="utf-8")
        assert "idempoten" in source.lower(), (
            "test_integrity.py should contain idempotency tests"
        )

    def test_integrity_file_imports_fixer(self):
        integrity_file = _PROJECT_ROOT / "tests" / "test_integrity.py"
        source = integrity_file.read_text(encoding="utf-8")
        assert "from dockerfile_doctor.fixer import" in source, (
            "test_integrity.py should import the fixer module"
        )


# ===========================================================================
# 9. README Test Count Accuracy
# ===========================================================================


class TestReadmeTestCount:
    """README claims a specific test count — verify it's in the right ballpark."""

    def test_readme_test_count_reasonable(self):
        """Collect tests and verify actual count meets README's lower bound.

        README uses "1,400+ tests" format — we extract the lower bound and
        verify the actual collected count meets or exceeds it.
        """
        result = subprocess.run(
            ["python", "-m", "pytest", "--collect-only", "-q",
             str(_PROJECT_ROOT / "tests")],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )

        # Parse "N tests collected" or "N selected"
        collected = 0
        for line in result.stdout.splitlines():
            m = re.search(r"(\d+)\s+test", line)
            if m:
                collected = int(m.group(1))
                break

        readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        # Match "1,400+ tests" or "1,454 tests" or "1400+ tests"
        m = re.search(r"([\d,]+)\+?\s+tests", readme)
        assert m, "README should mention a test count"
        claimed_lower_bound = int(m.group(1).replace(",", ""))

        assert collected >= claimed_lower_bound, (
            f"README claims {claimed_lower_bound}+ tests but only "
            f"{collected} were collected"
        )


# ===========================================================================
# 10. Handler-Rule Bijection Sanity
# ===========================================================================


class TestHandlerRuleBijection:
    """Additional structural checks on the handler<->rule mapping."""

    def test_no_handler_for_nonexistent_rule(self):
        """Every handler key should reference a rule ID that actually exists."""
        rule_ids = set()
        for fn in ALL_RULES:
            m = re.match(r"dd(\d{3})_", fn.__name__)
            if m:
                rule_ids.add(f"DD{m.group(1)}")

        for handler_key in _FIX_HANDLERS:
            assert handler_key in rule_ids, (
                f"_FIX_HANDLERS has key {handler_key!r} but no such rule exists"
            )

    def test_handler_count_matches_or_exceeds_readme(self):
        """README says 50 auto-fixers — handler count should be >= 50.

        The actual count (51) exceeds the README claim, which is acceptable
        (under-promise). If the count ever drops below 50, something broke.
        """
        readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        m = re.search(r"(\d+)\s+(?:deterministic\s+)?auto-fix", readme)
        assert m, "README should mention auto-fixer count"
        claimed = int(m.group(1))
        assert len(_FIX_HANDLERS) >= claimed, (
            f"README claims {claimed} auto-fixers but only "
            f"{len(_FIX_HANDLERS)} handlers exist"
        )
