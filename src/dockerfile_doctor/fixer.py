"""Auto-fixer for Dockerfile Doctor — applies deterministic fixes."""

from __future__ import annotations

import re
import shlex
from typing import Any, Optional

from .models import Dockerfile, Fix, Instruction, Issue


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fix(
    dockerfile: Dockerfile,
    issues: list[Issue],
    *,
    exclude_rules: set[str] | None = None,
) -> tuple[str, list[Fix]]:
    """Apply auto-fixes for fixable issues.

    Returns (fixed_content, list_of_applied_fixes).

    Runs the fix pipeline in a convergence loop (max 3 passes) so that
    multi-line fixes (DD005) that consume lines don't prevent single-line
    fixes from applying on the combined result.

    If *exclude_rules* is given, those rule IDs are never applied — even if
    the re-analysis in the convergence loop discovers them.
    """
    from .parser import parse as _parse
    from .rules import analyze as _analyze

    _exclude = exclude_rules or set()

    all_applied: list[Fix] = []
    current_df = dockerfile
    current_issues = issues

    for _ in range(3):  # converge in at most 3 passes
        fixed_content, fixes = _fix_once(current_df, current_issues)
        if not fixes:
            break
        all_applied.extend(fixes)
        # Re-parse and re-analyze for remaining fixable issues
        current_df = _parse(fixed_content)
        current_issues = [
            i for i in _analyze(current_df) if i.rule_id not in _exclude
        ]

    return current_df.raw_content, all_applied


def _fix_once(dockerfile: Dockerfile, issues: list[Issue]) -> tuple[str, list[Fix]]:
    """Single pass of fix application.

    Multi-line fixes (DD005) are applied first to claim their line ranges,
    then single-line fixes are applied in reverse order, skipping any lines
    already consumed by multi-line fixes.
    """
    fixable = [i for i in issues if i.fix_available]
    if not fixable:
        return dockerfile.raw_content, []

    # Build a mutable list of lines (1-indexed via padding)
    lines = [""] + list(dockerfile.lines)  # lines[1] = first line

    applied: list[Fix] = []

    # Group issues by rule_id and line for dedup
    seen: set[tuple[str, int]] = set()

    # Track line ranges consumed by multi-line fixes (DD005)
    consumed_lines: set[int] = set()

    # --- Phase 1: Apply multi-line fixes (DD005) first ---
    multi_line_rules = {"DD005"}
    multi_fixes = [i for i in fixable if i.rule_id in multi_line_rules]
    single_fixes = [i for i in fixable if i.rule_id not in multi_line_rules]

    # Process DD005 fixes in descending order
    multi_fixes.sort(key=lambda i: i.line_number, reverse=True)
    for issue in multi_fixes:
        key = (issue.rule_id, issue.line_number)
        if key in seen:
            continue
        seen.add(key)

        handler = _FIX_HANDLERS.get(issue.rule_id)
        if handler is None:
            continue

        # Determine the line range DD005 will consume
        run_instrs = _find_consecutive_runs(dockerfile, issue.line_number)
        if len(run_instrs) >= 2:
            first_line = run_instrs[0].line_number
            _, last_end = _find_instruction_lines(lines, run_instrs[-1].line_number)
            for ln in range(first_line, last_end + 1):
                consumed_lines.add(ln)

        result = handler(lines, issue, dockerfile)
        if result is not None:
            applied.append(result)

    # --- Phase 2: Apply single-line fixes, skipping consumed lines ---
    # Removal rules (DD013) must run before additive rules (DD003, DD004)
    # on the same line to avoid regex failures on modified text.
    _RULE_PRIORITY = {"DD013": 0}  # lower = runs first
    single_fixes.sort(key=lambda i: (-i.line_number, _RULE_PRIORITY.get(i.rule_id, 1)))
    for issue in single_fixes:
        key = (issue.rule_id, issue.line_number)
        if key in seen:
            continue
        seen.add(key)

        # Skip if this line was already consumed by a multi-line fix
        if issue.line_number in consumed_lines:
            continue

        handler = _FIX_HANDLERS.get(issue.rule_id)
        if handler is None:
            continue

        result = handler(lines, issue, dockerfile)
        if result is not None:
            applied.append(result)

    # Reconstruct content (skip the padding element at index 0)
    fixed_content = "\n".join(lines[1:])
    # Preserve trailing newline if original had one
    if dockerfile.raw_content.endswith("\n"):
        fixed_content += "\n"

    applied.reverse()  # return in original line order
    return fixed_content, applied


# ---------------------------------------------------------------------------
# Fix handler type and registry
# ---------------------------------------------------------------------------

_FIX_HANDLERS: dict[str, Any] = {}


def _handler(rule_id: str):
    """Register a fix handler for a rule."""
    def decorator(fn):
        _FIX_HANDLERS[rule_id] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_instruction_lines(lines: list[str], start_line: int) -> tuple[int, int]:
    """Find the range of lines for an instruction starting at start_line.

    Returns (start, end) inclusive, 1-based indices.
    Lines use backslash continuation.
    """
    end = start_line
    while end < len(lines) - 1 and lines[end].rstrip().endswith("\\"):
        end += 1
    return start_line, end


def _get_full_instruction(lines: list[str], start_line: int) -> str:
    """Get the full instruction text spanning continuation lines."""
    start, end = _find_instruction_lines(lines, start_line)
    return "\n".join(lines[start:end + 1])


def _set_instruction(lines: list[str], start_line: int, new_text: str) -> None:
    """Replace an instruction (possibly multi-line) with new text."""
    start, end = _find_instruction_lines(lines, start_line)
    new_lines = new_text.split("\n")
    lines[start:end + 1] = new_lines


def _find_consecutive_runs(
    dockerfile: Dockerfile, start_line: int
) -> list[Instruction]:
    """Find the streak of consecutive RUN instructions starting at start_line."""
    run_instrs: list[Instruction] = []
    in_streak = False
    for instr in dockerfile.instructions:
        if instr.directive == "RUN":
            if not in_streak and instr.line_number == start_line:
                in_streak = True
            if in_streak:
                run_instrs.append(instr)
        else:
            if in_streak:
                break
    return run_instrs


# ---------------------------------------------------------------------------
# DD003 — Add --no-install-recommends
# ---------------------------------------------------------------------------
@_handler("DD003")
def _fix_dd003(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "--no-install-recommends" in full:
        return None
    # Insert --no-install-recommends after "apt-get install" or "apt install"
    fixed = re.sub(
        r"(apt(?:-get)?\s+install)\b",
        r"\1 --no-install-recommends",
        full,
        count=1,
    )
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD003",
        description="Added --no-install-recommends to apt-get install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD004 — Add apt cache cleanup
# ---------------------------------------------------------------------------
@_handler("DD004")
def _fix_dd004(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "rm -rf /var/lib/apt/lists" in full:
        return None
    # Append cleanup at the end of the RUN instruction (handles apt and apt-get)
    # Remove trailing whitespace/backslash from last line, then append
    stripped = full.rstrip()
    if stripped.endswith("\\"):
        stripped = stripped[:-1].rstrip()
    fixed = stripped + " \\\n    && rm -rf /var/lib/apt/lists/*"
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD004",
        description="Added '&& rm -rf /var/lib/apt/lists/*' after apt-get.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD005 — Combine consecutive RUN instructions
# ---------------------------------------------------------------------------
@_handler("DD005")
def _fix_dd005(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    run_instrs = _find_consecutive_runs(dockerfile, issue.line_number)
    if len(run_instrs) < 2:
        return None

    # Extract the command part (after "RUN ") from each instruction
    commands: list[str] = []
    for instr in run_instrs:
        # Get the arguments, handling multi-line
        cmd = instr.arguments.strip()
        # Remove trailing backslash-newline artifacts
        cmd = re.sub(r"\s*\\\s*$", "", cmd)
        commands.append(cmd)

    combined = "RUN " + " \\\n    && ".join(commands)

    # Replace the entire range from first RUN to end of last RUN,
    # including any blank lines or comments between them.
    first_start = run_instrs[0].line_number
    last_instr = run_instrs[-1]
    _, last_end = _find_instruction_lines(lines, last_instr.line_number)

    new_lines = combined.split("\n")
    lines[first_start:last_end + 1] = new_lines

    return Fix(
        rule_id="DD005",
        description=f"Combined {len(run_instrs)} consecutive RUN instructions.",
        replacements=[(first_start, "<multiple lines>", combined)],
    )


# ---------------------------------------------------------------------------
# DD007 — Replace ADD with COPY
# ---------------------------------------------------------------------------
@_handler("DD007")
def _fix_dd007(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    # Replace first occurrence of ADD with COPY (preserving case of first char)
    fixed = re.sub(r"^(\s*)ADD\b", r"\1COPY", full, count=1, flags=re.IGNORECASE)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD007",
        description="Replaced ADD with COPY.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD009 — Add --no-cache-dir to pip install
# ---------------------------------------------------------------------------
@_handler("DD009")
def _fix_dd009(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "--no-cache-dir" in full:
        return None
    fixed = re.sub(
        r"((?:pip3?|python3?\s+-m\s+pip)\s+install)\b",
        r"\1 --no-cache-dir",
        full,
        count=1,
    )
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD009",
        description="Added --no-cache-dir to pip install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD010 — Replace npm install with npm ci
# ---------------------------------------------------------------------------
@_handler("DD010")
def _fix_dd010(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    fixed = re.sub(r"\bnpm\s+install\b", "npm ci", full)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD010",
        description="Replaced 'npm install' with 'npm ci'.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD013 — Remove apt-get upgrade / dist-upgrade
# ---------------------------------------------------------------------------
@_handler("DD013")
def _fix_dd013(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    # Remove "apt-get upgrade" or "apt-get dist-upgrade" and surrounding && glue
    # Cases:
    # 1) Entire RUN is just "apt-get upgrade" -> delete the line
    # 2) Part of a chain: "apt-get update && apt-get upgrade && ..." -> remove segment

    # First check if the entire instruction is just the upgrade
    args_stripped = re.sub(r"^RUN\s+", "", full.strip(), flags=re.IGNORECASE).strip()
    if re.match(r"^apt(?:-get)?\s+(?:-\w+\s+)*(upgrade|dist-upgrade)(\s+-\w+)*\s*$", args_stripped):
        # Delete entire instruction
        start, end = _find_instruction_lines(lines, issue.line_number)
        lines[start:end + 1] = []
        return Fix(
            rule_id="DD013",
            description="Removed 'apt-get upgrade' RUN instruction.",
            deletions=[issue.line_number],
        )

    # Remove the upgrade segment from a chain
    # Pattern: && apt-get upgrade -y && or apt-get dist-upgrade -y &&
    fixed = re.sub(
        r"&&\s*apt(?:-get)?\s+(?:-\w+\s+)*(upgrade|dist-upgrade)(\s+-\w+)*\s*(?=&&|$)",
        "",
        full,
    )
    # Also handle if it's the first command: apt-get upgrade -y &&
    fixed = re.sub(
        r"apt(?:-get)?\s+(?:-\w+\s+)*(upgrade|dist-upgrade)(\s+-\w+)*\s*&&\s*",
        "",
        fixed,
    )
    # Clean up any resulting double &&
    fixed = re.sub(r"&&\s*&&", "&&", fixed)
    fixed = fixed.rstrip()
    if fixed.rstrip().endswith("&&"):
        fixed = re.sub(r"\s*&&\s*$", "", fixed)

    if fixed == full:
        return None

    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD013",
        description="Removed 'apt-get upgrade' from RUN instruction.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD017 — Convert MAINTAINER to LABEL
# ---------------------------------------------------------------------------
@_handler("DD017")
def _fix_dd017(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    # Extract the maintainer value
    m = re.match(r"^\s*MAINTAINER\s+(.+)$", full, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    value = m.group(1).strip()
    # Remove surrounding quotes if present
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        inner = value[1:-1]
    else:
        inner = value
    inner = inner.replace("\\", "\\\\").replace('"', '\\"')
    fixed = f'LABEL maintainer="{inner}"'
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD017",
        description="Converted MAINTAINER to LABEL maintainer=...",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD019 — Convert shell form CMD/ENTRYPOINT to exec form
# ---------------------------------------------------------------------------
@_handler("DD019")
def _fix_dd019(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    # Use parser's pre-joined arguments to avoid backslash-continuation artifacts
    instr = next(
        (i for i in dockerfile.instructions if i.line_number == issue.line_number),
        None,
    )
    if instr is None:
        return None
    directive = instr.directive
    command = instr.arguments.strip()
    # Detect leading indent from the raw line
    indent = ""
    m = re.match(r"^(\s*)", lines[issue.line_number])
    if m:
        indent = m.group(1)

    # Already exec form
    if command.startswith("["):
        return None

    # Convert shell form to exec form
    # Shell form "python app.py" -> ["python", "app.py"]
    # But complex shell commands with pipes/redirects need /bin/sh -c
    # Also commands with $VAR need shell for variable expansion
    shell_chars = set("|&;<>()`!")
    needs_shell = any(c in command for c in shell_chars) or "$" in command

    if needs_shell:
        # Wrap in /bin/sh -c
        escaped = command.replace("\\", "\\\\").replace('"', '\\"')
        exec_form = f'["/bin/sh", "-c", "{escaped}"]'
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            # Can't parse, fall back to shell wrapper
            escaped = command.replace("\\", "\\\\").replace('"', '\\"')
            exec_form = f'["/bin/sh", "-c", "{escaped}"]'
        else:
            escaped_parts = [p.replace("\\", "\\\\").replace('"', '\\"') for p in parts]
            exec_form = "[" + ", ".join(f'"{ep}"' for ep in escaped_parts) + "]"

    fixed = f"{indent}{directive} {exec_form}"
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD019",
        description=f"Converted {directive} to exec form.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD021 — Remove sudo
# ---------------------------------------------------------------------------
@_handler("DD021")
def _fix_dd021(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    fixed = re.sub(r"\bsudo\s+", "", full)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD021",
        description="Removed 'sudo' from command.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD023 — Add -y to apt-get install
# ---------------------------------------------------------------------------
@_handler("DD023")
def _fix_dd023(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "-y" in full or "--yes" in full:
        return None
    fixed = re.sub(r"(apt-get\s+install)\b", r"\1 -y", full, count=1)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD023",
        description="Added -y to apt-get install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD024 — Replace apt with apt-get
# ---------------------------------------------------------------------------
@_handler("DD024")
def _fix_dd024(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    fixed = re.sub(r"\bapt\s+(install|update|upgrade|remove|purge)\b", r"apt-get \1", full)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD024",
        description="Replaced 'apt' with 'apt-get'.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD025 — Add --no-cache to apk add
# ---------------------------------------------------------------------------
@_handler("DD025")
def _fix_dd025(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "--no-cache" in full:
        return None
    fixed = re.sub(r"(apk\s+add)\b", r"\1 --no-cache", full, count=1)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD025",
        description="Added --no-cache to apk add.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD036 — Remove earlier CMD (keep last)
# ---------------------------------------------------------------------------
@_handler("DD036")
def _fix_dd036(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    start, end = _find_instruction_lines(lines, issue.line_number)
    lines[start:end + 1] = []
    return Fix(
        rule_id="DD036",
        description="Removed duplicate CMD instruction.",
        deletions=[issue.line_number],
    )


# ---------------------------------------------------------------------------
# DD037 — Remove earlier ENTRYPOINT (keep last)
# ---------------------------------------------------------------------------
@_handler("DD037")
def _fix_dd037(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    start, end = _find_instruction_lines(lines, issue.line_number)
    lines[start:end + 1] = []
    return Fix(
        rule_id="DD037",
        description="Removed duplicate ENTRYPOINT instruction.",
        deletions=[issue.line_number],
    )


# ---------------------------------------------------------------------------
# DD061 — Add --no-document to gem install
# ---------------------------------------------------------------------------
@_handler("DD061")
def _fix_dd061(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "--no-document" in full:
        return None
    fixed = re.sub(r"(gem\s+install)\b", r"\1 --no-document", full, count=1)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD061",
        description="Added --no-document to gem install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD071 — Fix instruction casing to uppercase
# ---------------------------------------------------------------------------
@_handler("DD071")
def _fix_dd071(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    line = lines[issue.line_number]
    parts = line.split(None, 1)
    if not parts:
        return None
    word = parts[0]
    from .parser import _KNOWN_DIRECTIVES
    if word.upper() in _KNOWN_DIRECTIVES and word != word.upper():
        fixed = line.replace(word, word.upper(), 1)
        lines[issue.line_number] = fixed
        return Fix(
            rule_id="DD071",
            description=f"Changed '{word}' to '{word.upper()}'.",
            replacements=[(issue.line_number, line, fixed)],
        )
    return None


# ---------------------------------------------------------------------------
# DD026 — Remove apk upgrade
# ---------------------------------------------------------------------------
@_handler("DD026")
def _fix_dd026(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    args_stripped = re.sub(r"^RUN\s+", "", full.strip(), flags=re.IGNORECASE).strip()
    # Entire RUN is just "apk upgrade"
    if re.match(r"^apk\s+upgrade\s*$", args_stripped):
        start, end = _find_instruction_lines(lines, issue.line_number)
        lines[start:end + 1] = []
        return Fix(
            rule_id="DD026",
            description="Removed 'apk upgrade' RUN instruction.",
            deletions=[issue.line_number],
        )
    # Part of chain: remove segment
    fixed = re.sub(r"&&\s*apk\s+upgrade\s*(?=&&|$)", "", full)
    fixed = re.sub(r"apk\s+upgrade\s*&&\s*", "", fixed)
    fixed = re.sub(r"&&\s*&&", "&&", fixed)
    fixed = fixed.rstrip()
    if fixed.rstrip().endswith("&&"):
        fixed = re.sub(r"\s*&&\s*$", "", fixed)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD026",
        description="Removed 'apk upgrade' from RUN instruction.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD031 — Append yum clean all
# ---------------------------------------------------------------------------
@_handler("DD031")
def _fix_dd031(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "yum clean all" in full:
        return None
    stripped = full.rstrip()
    if stripped.endswith("\\"):
        stripped = stripped[:-1].rstrip()
    fixed = stripped + " \\\n    && yum clean all"
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD031",
        description="Added '&& yum clean all' after yum install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD033 — Append dnf clean all
# ---------------------------------------------------------------------------
@_handler("DD033")
def _fix_dd033(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "dnf clean all" in full:
        return None
    stripped = full.rstrip()
    if stripped.endswith("\\"):
        stripped = stripped[:-1].rstrip()
    fixed = stripped + " \\\n    && dnf clean all"
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD033",
        description="Added '&& dnf clean all' after dnf install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD034 — Append zypper clean
# ---------------------------------------------------------------------------
@_handler("DD034")
def _fix_dd034(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "zypper clean" in full:
        return None
    stripped = full.rstrip()
    if stripped.endswith("\\"):
        stripped = stripped[:-1].rstrip()
    fixed = stripped + " \\\n    && zypper clean"
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD034",
        description="Added '&& zypper clean' after zypper install.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD035 — Add ARG DEBIAN_FRONTEND=noninteractive
# ---------------------------------------------------------------------------
@_handler("DD035")
def _fix_dd035(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # Find the first stage that uses apt-get install
    target_from = None
    for stage in dockerfile.stages:
        for instr in stage.instructions:
            if instr.directive == "RUN" and re.search(r"\bapt-get\s+install\b|\bapt\s+install\b", instr.arguments):
                target_from = stage.instructions[0] if stage.instructions else None
                break
        if target_from:
            break
    # Fallback to first FROM
    if target_from is None:
        for instr in dockerfile.instructions:
            if instr.directive == "FROM":
                target_from = instr
                break
    if target_from is None:
        return None
    _, end = _find_instruction_lines(lines, target_from.line_number)
    lines.insert(end + 1, "ARG DEBIAN_FRONTEND=noninteractive")
    return Fix(
        rule_id="DD035",
        description="Added ARG DEBIAN_FRONTEND=noninteractive.",
        insertions=[(target_from.line_number, "ARG DEBIAN_FRONTEND=noninteractive")],
    )


# ---------------------------------------------------------------------------
# DD040 — Add pipefail to RUN with pipe
# ---------------------------------------------------------------------------
@_handler("DD040")
def _fix_dd040(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if "set -o pipefail" in full:
        return None
    # Prepend "set -o pipefail &&" to the RUN command
    fixed = re.sub(
        r"^(\s*RUN\s+)",
        r"\1set -o pipefail && ",
        full,
        count=1,
        flags=re.IGNORECASE,
    )
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD040",
        description="Added 'set -o pipefail &&' to RUN with pipe.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD044 — Remove earlier duplicate ENV key (keep last)
# ---------------------------------------------------------------------------
@_handler("DD044")
def _fix_dd044(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # The rule fires on the SECOND occurrence. We want to keep the last
    # (active) value and remove the EARLIER one that gets overwritten.
    full = _get_full_instruction(lines, issue.line_number)
    m = re.match(r"^\s*ENV\s+(\w+)", full.strip(), re.IGNORECASE)
    if not m:
        return None
    key = m.group(1).upper()

    # Find the earlier ENV with the same key
    for instr in dockerfile.instructions:
        if instr.directive != "ENV" or instr.line_number >= issue.line_number:
            continue
        im = re.match(r"(\w+)", instr.arguments.strip())
        if im and im.group(1).upper() == key:
            start, end = _find_instruction_lines(lines, instr.line_number)
            lines[start:end + 1] = []
            return Fix(
                rule_id="DD044",
                description=f"Removed earlier duplicate ENV '{im.group(1)}' at line {instr.line_number}.",
                deletions=[instr.line_number],
            )
    return None


# ---------------------------------------------------------------------------
# DD045 — Convert RUN cd /path && ... to WORKDIR + RUN
# ---------------------------------------------------------------------------
@_handler("DD045")
def _fix_dd045(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    m = re.match(r"^(\s*)RUN\s+cd\s+(\S+)\s*(&&|;)\s*(.+)$", full, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    indent = m.group(1)
    path = m.group(2)
    rest = m.group(4).strip()
    workdir_line = f"{indent}WORKDIR {path}"
    run_line = f"{indent}RUN {rest}"
    fixed = workdir_line + "\n" + run_line
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD045",
        description=f"Converted 'RUN cd {path} && ...' to WORKDIR + RUN.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD047 — Remove empty RUN instruction
# ---------------------------------------------------------------------------
@_handler("DD047")
def _fix_dd047(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    start, end = _find_instruction_lines(lines, issue.line_number)
    lines[start:end + 1] = []
    return Fix(
        rule_id="DD047",
        description="Removed empty RUN instruction.",
        deletions=[issue.line_number],
    )


# ---------------------------------------------------------------------------
# DD048 — Remove duplicate EXPOSE port
# ---------------------------------------------------------------------------
@_handler("DD048")
def _fix_dd048(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # Remove the entire duplicate EXPOSE line
    start, end = _find_instruction_lines(lines, issue.line_number)
    lines[start:end + 1] = []
    return Fix(
        rule_id="DD048",
        description="Removed duplicate EXPOSE instruction.",
        deletions=[issue.line_number],
    )


# ---------------------------------------------------------------------------
# DD049 — Remove earlier HEALTHCHECK (keep last)
# ---------------------------------------------------------------------------
@_handler("DD049")
def _fix_dd049(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    start, end = _find_instruction_lines(lines, issue.line_number)
    lines[start:end + 1] = []
    return Fix(
        rule_id="DD049",
        description="Removed duplicate HEALTHCHECK instruction.",
        deletions=[issue.line_number],
    )


# ---------------------------------------------------------------------------
# DD050 — Lowercase stage name
# ---------------------------------------------------------------------------
@_handler("DD050")
def _fix_dd050(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    m = re.search(r"\bAS\s+(\S+)", full, re.IGNORECASE)
    if not m:
        return None
    old_name = m.group(1)
    if old_name == old_name.lower():
        return None
    fixed = full[:m.start(1)] + old_name.lower() + full[m.end(1):]
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD050",
        description=f"Changed stage name '{old_name}' to '{old_name.lower()}'.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD051 — Change chmod 777 to chmod 755
# ---------------------------------------------------------------------------
@_handler("DD051")
def _fix_dd051(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    fixed = re.sub(r"\bchmod\s+777\b", "chmod 755", full)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(
        rule_id="DD051",
        description="Changed chmod 777 to chmod 755.",
        replacements=[(issue.line_number, full, fixed)],
    )


# ---------------------------------------------------------------------------
# DD065 — Remove duplicate RUN instruction
# ---------------------------------------------------------------------------
@_handler("DD065")
def _fix_dd065(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    start, end = _find_instruction_lines(lines, issue.line_number)
    lines[start:end + 1] = []
    return Fix(
        rule_id="DD065",
        description="Removed duplicate RUN instruction.",
        deletions=[issue.line_number],
    )


# ---------------------------------------------------------------------------
# DD073 — Add missing final newline
# ---------------------------------------------------------------------------
@_handler("DD073")
def _fix_dd073(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # The fixer reconstructs content from lines and adds \n if original had one.
    # For DD073 the original does NOT end with \n. We signal the fix by appending
    # an empty line (which produces a trailing \n when joined).
    lines.append("")
    return Fix(
        rule_id="DD073",
        description="Added trailing newline.",
        insertions=[(len(lines), "")],
    )


# ---------------------------------------------------------------------------
# DD075 — Remove trailing whitespace
# ---------------------------------------------------------------------------
@_handler("DD075")
def _fix_dd075(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    line = lines[issue.line_number]
    fixed = line.rstrip()
    if fixed == line:
        return None
    lines[issue.line_number] = fixed
    return Fix(
        rule_id="DD075",
        description="Removed trailing whitespace.",
        replacements=[(issue.line_number, line, fixed)],
    )


# ---------------------------------------------------------------------------
# DD076 — Remove empty continuation line
# ---------------------------------------------------------------------------
@_handler("DD076")
def _fix_dd076(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    if lines[issue.line_number].rstrip() == "\\":
        lines[issue.line_number:issue.line_number + 1] = []
        return Fix(
            rule_id="DD076",
            description="Removed empty continuation line.",
            deletions=[issue.line_number],
        )
    return None


# ---------------------------------------------------------------------------
# DD011 — Fix relative WORKDIR to absolute
# ---------------------------------------------------------------------------
@_handler("DD011")
def _fix_dd011(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    m = re.match(r'^(\s*WORKDIR\s+)(\S+)', full, re.IGNORECASE)
    if not m or m.group(2).startswith('/'):
        return None
    path = m.group(2)
    # Don't rewrite paths starting with '.' — these are relative to current WORKDIR
    # and prepending '/' would create nonsense like '/./subdir' or '/../other'
    if path.startswith('.'):
        return None
    fixed = m.group(1) + '/' + path
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD011", description="Changed relative WORKDIR to absolute path.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD041 — Fix COPY relative destination to absolute
# ---------------------------------------------------------------------------
@_handler("DD041")
def _fix_dd041(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    # Match COPY [flags] src dest where dest doesn't start with / or $
    parts = full.split()
    if len(parts) < 3:
        return None
    dest = parts[-1]
    if dest.startswith('/') or dest.startswith('$'):
        return None
    # Don't rewrite dot-relative paths — these are relative to current WORKDIR
    # and prepending '/' would create nonsense like '/./app' or '/../other'
    if dest.startswith('.'):
        return None
    fixed = full[:full.rfind(dest)] + '/' + dest
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD041", description="Changed relative COPY destination to absolute path.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD043 — Fix SHELL to exec form
# ---------------------------------------------------------------------------
@_handler("DD043")
def _fix_dd043(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    m = re.match(r'^\s*SHELL\s+(.+)$', full, re.IGNORECASE)
    if not m:
        return None
    args = m.group(1).strip()
    if args.startswith('['):
        return None
    # Convert "SHELL /bin/bash -c" to SHELL ["/bin/bash", "-c"]
    parts = args.split()
    exec_form = '[' + ', '.join(f'"{p}"' for p in parts) + ']'
    fixed = 'SHELL ' + exec_form
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD043", description="Converted SHELL to exec form.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD055 — Remove --no-check-certificate from wget
# ---------------------------------------------------------------------------
@_handler("DD055")
def _fix_dd055(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    fixed = re.sub(r'\s*--no-check-certificate\b', '', full)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD055", description="Removed --no-check-certificate from wget.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD056 — Remove -k from curl
# ---------------------------------------------------------------------------
@_handler("DD056")
def _fix_dd056(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    fixed = re.sub(r'\s+-k\b', '', full)
    # Also handle --insecure
    fixed = re.sub(r'\s+--insecure\b', '', fixed)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD056", description="Removed -k/--insecure from curl.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD059 — Convert ADD remote URL to RUN curl
# ---------------------------------------------------------------------------
@_handler("DD059")
def _fix_dd059(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    m = re.match(r'^\s*ADD\s+(https?://\S+)\s+(\S+)', full, re.IGNORECASE)
    if not m:
        return None
    url = m.group(1)
    dest = m.group(2)
    # If dest is a directory (ends with /), extract filename from URL
    if dest.endswith('/'):
        from posixpath import basename as _posix_basename
        filename = _posix_basename(url.split('?')[0].split('#')[0])
        if filename:
            dest = dest + filename
        else:
            return None  # Can't determine filename from URL
    fixed = f'RUN curl -fsSL -o {dest} {url}'
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD059", description="Replaced ADD remote URL with RUN curl.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD062 — Prepend CGO_ENABLED=0 to go build
# ---------------------------------------------------------------------------
@_handler("DD062")
def _fix_dd062(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    if 'CGO_ENABLED=0' in full:
        return None
    fixed = re.sub(r'(\bgo\s+build\b)', r'CGO_ENABLED=0 \1', full, count=1)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD062", description="Added CGO_ENABLED=0 before go build.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD067 — Add NODE_ENV=production for Node images
# ---------------------------------------------------------------------------
@_handler("DD067")
def _fix_dd067(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # Search current lines (not stale dockerfile object) for the node FROM
    for idx in range(1, len(lines)):
        line = lines[idx].strip()
        if not re.match(r"^FROM\s+", line, re.IGNORECASE):
            continue
        image = line.split()[1] if len(line.split()) > 1 else ""
        basename = image.rsplit("/", 1)[-1].lower().split(":")[0]
        if basename == "node":
            _, end = _find_instruction_lines(lines, idx)
            lines.insert(end + 1, "ENV NODE_ENV=production")
            return Fix(rule_id="DD067", description="Added ENV NODE_ENV=production.",
                       insertions=[(end + 1, "ENV NODE_ENV=production")])
    return None


# ---------------------------------------------------------------------------
# DD072 — Remove TODO/FIXME comments
# ---------------------------------------------------------------------------
@_handler("DD072")
def _fix_dd072(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    line = lines[issue.line_number]
    if not line.strip().startswith('#'):
        return None
    # Remove the entire comment line
    lines[issue.line_number:issue.line_number + 1] = []
    return Fix(rule_id="DD072", description="Removed TODO/FIXME comment.",
               deletions=[issue.line_number])


# ---------------------------------------------------------------------------
# DD077 — Update deprecated base image
# ---------------------------------------------------------------------------
# Mapping from deprecated image to a suitable replacement image reference
_DD077_REPLACEMENTS = {
    "centos": "almalinux",
    "ubuntu:14.04": "ubuntu:22.04",
    "ubuntu:16.04": "ubuntu:22.04",
    "ubuntu:18.04": "ubuntu:22.04",
    "debian:jessie": "debian:bookworm",
    "debian:stretch": "debian:bookworm",
    "debian:buster": "debian:bookworm",
    "python:2": "python:3",
    "python:2.7": "python:3",
    "node:8": "node:20",
    "node:10": "node:20",
    "node:12": "node:20",
    "node:14": "node:20",
    "node:16": "node:20",
}

@_handler("DD077")
def _fix_dd077(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    from .rules import _DEPRECATED_IMAGES
    for old_img in _DEPRECATED_IMAGES:
        if old_img in full.lower():
            replacement = _DD077_REPLACEMENTS.get(old_img)
            if replacement:
                # Replace the image reference (case-insensitive)
                fixed = re.sub(re.escape(old_img), replacement, full, flags=re.IGNORECASE)
                if fixed != full:
                    _set_instruction(lines, issue.line_number, fixed)
                    return Fix(rule_id="DD077", description=f"Replaced deprecated image with '{replacement}'.",
                               replacements=[(issue.line_number, full, fixed)])
    return None


# ---------------------------------------------------------------------------
# DD078 — Add missing version LABEL
# ---------------------------------------------------------------------------
@_handler("DD078")
def _fix_dd078(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # Insert LABEL version="1.0.0" after the last LABEL, or after FROM if no LABEL exists
    insert_after = None
    for instr in dockerfile.instructions:
        if instr.directive == "LABEL":
            _, end = _find_instruction_lines(lines, instr.line_number)
            insert_after = end
        elif instr.directive == "FROM" and insert_after is None:
            _, end = _find_instruction_lines(lines, instr.line_number)
            insert_after = end
    if insert_after is not None:
        lines.insert(insert_after + 1, 'LABEL version="1.0.0"')
        return Fix(rule_id="DD078", description='Added LABEL version="1.0.0".',
                   insertions=[(insert_after + 1, 'LABEL version="1.0.0"')])
    return None


# ---------------------------------------------------------------------------
# DD079 — Fix invalid STOPSIGNAL
# ---------------------------------------------------------------------------
@_handler("DD079")
def _fix_dd079(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    # Replace invalid signal with SIGTERM (the default)
    fixed = re.sub(r'^(\s*STOPSIGNAL\s+)\S+', r'\g<1>SIGTERM', full, flags=re.IGNORECASE)
    if fixed == full:
        return None
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD079", description="Replaced invalid STOPSIGNAL with SIGTERM.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD080 — Convert VOLUME to JSON syntax
# ---------------------------------------------------------------------------
@_handler("DD080")
def _fix_dd080(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    full = _get_full_instruction(lines, issue.line_number)
    m = re.match(r'^\s*VOLUME\s+(.+)$', full, re.IGNORECASE)
    if not m:
        return None
    args = m.group(1).strip()
    if args.startswith('['):
        return None
    # Split paths and convert to JSON array
    paths = args.split()
    json_form = '[' + ', '.join(f'"{p}"' for p in paths) + ']'
    fixed = f'VOLUME {json_form}'
    _set_instruction(lines, issue.line_number, fixed)
    return Fix(rule_id="DD080", description="Converted VOLUME to JSON syntax.",
               replacements=[(issue.line_number, full, fixed)])


# ---------------------------------------------------------------------------
# DD008 — Add USER nobody before last CMD/ENTRYPOINT in final stage
# ---------------------------------------------------------------------------
@_handler("DD008")
def _fix_dd008(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # Only fix the "no USER" case (line_number=0), not the "root" case
    if issue.line_number != 0:
        return None
    if not dockerfile.stages:
        return None
    # Find the last CMD or ENTRYPOINT by scanning the current lines array
    # (not the original parse) to account for mutations from earlier fixes.
    last_cmd_idx = None
    for idx in range(1, len(lines)):
        stripped = lines[idx].strip().upper()
        if stripped.startswith("CMD ") or stripped.startswith("CMD\t") \
                or stripped == "CMD" \
                or stripped.startswith("ENTRYPOINT ") or stripped.startswith("ENTRYPOINT\t") \
                or stripped == "ENTRYPOINT":
            last_cmd_idx = idx
    if last_cmd_idx is not None:
        lines.insert(last_cmd_idx, "USER nobody")
        return Fix(rule_id="DD008", description="Added USER nobody before CMD/ENTRYPOINT.",
                   insertions=[(last_cmd_idx, "USER nobody")])
    else:
        # No CMD/ENTRYPOINT — append at the very end
        lines.append("USER nobody")
        return Fix(rule_id="DD008", description="Added USER nobody at end of Dockerfile.",
                   insertions=[(len(lines), "USER nobody")])


# ---------------------------------------------------------------------------
# DD015 — Add missing Python env vars after first FROM
# ---------------------------------------------------------------------------
@_handler("DD015")
def _fix_dd015(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    # Find the first stage that uses a Python base image or pip install
    target_from = None
    for stage in dockerfile.stages:
        basename = stage.base_image.rsplit("/", 1)[-1].lower().split(":")[0] if stage.base_image else ""
        if basename == "python":
            target_from = stage.instructions[0] if stage.instructions else None
            break
        for instr in stage.instructions:
            if instr.directive == "RUN" and re.search(r"\b(pip3?|python3?\s+-m\s+pip)\s+install\b", instr.arguments):
                target_from = stage.instructions[0] if stage.instructions else None
                break
        if target_from:
            break
    # Fallback to first FROM
    if target_from is None:
        for instr in dockerfile.instructions:
            if instr.directive == "FROM":
                target_from = instr
                break
    if target_from is None:
        return None
    _, end = _find_instruction_lines(lines, target_from.line_number)
    new_line = "ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1"
    lines.insert(end + 1, new_line)
    return Fix(rule_id="DD015", description="Added PYTHONUNBUFFERED and PYTHONDONTWRITEBYTECODE.",
               insertions=[(end + 1, new_line)])


# ---------------------------------------------------------------------------
# DD046 — Add LABEL instructions after first FROM
# ---------------------------------------------------------------------------
@_handler("DD046")
def _fix_dd046(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    for instr in dockerfile.instructions:
        if instr.directive == "FROM":
            _, end = _find_instruction_lines(lines, instr.line_number)
            new_line = 'LABEL maintainer="" description=""'
            lines.insert(end + 1, new_line)
            return Fix(rule_id="DD046", description="Added LABEL maintainer and description.",
                       insertions=[(end + 1, new_line)])
    return None


# ---------------------------------------------------------------------------
# DD068 — Add Java container-aware JVM flags after first Java FROM
# ---------------------------------------------------------------------------
@_handler("DD068")
def _fix_dd068(lines: list[str], issue: Issue, dockerfile: Dockerfile) -> Optional[Fix]:
    java_images = ("openjdk", "java", "eclipse-temurin", "amazoncorretto")
    for instr in dockerfile.instructions:
        if instr.directive == "FROM":
            # Check if this FROM uses a Java base image
            image = instr.arguments.split()[0] if instr.arguments.strip() else ""
            basename = image.rsplit("/", 1)[-1].lower().split(":")[0]
            if basename in java_images:
                _, end = _find_instruction_lines(lines, instr.line_number)
                new_line = 'ENV JAVA_OPTS="-XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0"'
                lines.insert(end + 1, new_line)
                return Fix(rule_id="DD068", description="Added JAVA_OPTS with container-aware flags.",
                           insertions=[(end + 1, new_line)])
    return None
