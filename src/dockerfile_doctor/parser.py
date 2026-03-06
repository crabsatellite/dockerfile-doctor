"""Dockerfile parser — pure Python, no external dependencies."""

from __future__ import annotations

import re
from typing import Optional

from .models import Dockerfile, Instruction, Stage


# Dockerfile directives (case-insensitive in Dockerfiles, stored uppercase)
_KNOWN_DIRECTIVES = frozenset({
    "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV",
    "ADD", "COPY", "ENTRYPOINT", "VOLUME", "USER", "WORKDIR",
    "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL",
})

# Pattern for parser directives (# syntax=..., # escape=...)
_PARSER_DIRECTIVE_RE = re.compile(r"^#\s*(syntax|escape)\s*=\s*(.+)$", re.IGNORECASE)

# Pattern for heredoc in RUN instructions: <<[-]?WORD
_HEREDOC_START_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")


def parse(content: str) -> Dockerfile:
    """Parse a Dockerfile string into a structured Dockerfile model.

    Handles:
    - Multi-line instructions (backslash continuations)
    - Comments and blank lines
    - Build stages (FROM ... AS name)
    - ARG before FROM
    - Heredoc syntax (RUN <<EOF ... EOF)
    """
    # Strip UTF-8 BOM if present
    if content.startswith("\ufeff"):
        content = content[1:]
    raw_lines = content.splitlines()
    # Determine escape character (default backslash, can be set via parser directive)
    escape_char = "\\"
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            m = _PARSER_DIRECTIVE_RE.match(stripped)
            if m and m.group(1).lower() == "escape":
                escape_char = m.group(2).strip()
            continue
        break  # parser directives must appear before any instruction

    logical_lines = _join_logical_lines(raw_lines, escape_char)
    instructions = _parse_instructions(logical_lines)
    stages = _build_stages(instructions)

    return Dockerfile(
        raw_content=content,
        lines=raw_lines,
        instructions=instructions,
        stages=stages,
    )


def _join_logical_lines(
    raw_lines: list[str], escape_char: str
) -> list[tuple[int, str, str]]:
    """Join continuation lines into logical lines.

    Returns list of (start_line_number_1based, original_text, joined_text).
    Comments and blank lines are skipped.
    """
    results: list[tuple[int, str, str]] = []
    i = 0
    n = len(raw_lines)

    while i < n:
        line = raw_lines[i]
        stripped = line.strip()

        # Skip blank lines and pure comment lines (not parser directives)
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        start_line = i + 1  # 1-based
        original_parts = [line]
        joined = stripped

        # Check for heredoc
        heredoc_markers = _detect_heredoc(stripped)
        if heredoc_markers:
            # Consume until all heredoc markers are closed
            open_markers = list(heredoc_markers)
            i += 1
            while i < n and open_markers:
                hline = raw_lines[i]
                original_parts.append(hline)
                joined += "\n" + hline
                hs = hline.strip()
                if hs in open_markers:
                    open_markers.remove(hs)
                i += 1
            results.append((start_line, "\n".join(original_parts), joined))
            continue

        # Handle backslash continuations
        while joined.endswith(escape_char) and i + 1 < n:
            i += 1
            next_line = raw_lines[i]
            original_parts.append(next_line)
            # Remove the trailing escape char and append the next line
            joined = joined[:-1].rstrip() + " " + next_line.strip()

        results.append((start_line, "\n".join(original_parts), joined))
        i += 1

    return results


def _detect_heredoc(line: str) -> list[str]:
    """Detect heredoc markers in a line. Returns list of marker words."""
    markers = []
    for m in _HEREDOC_START_RE.finditer(line):
        markers.append(m.group(1))
    return markers


def _parse_instructions(
    logical_lines: list[tuple[int, str, str]],
) -> list[Instruction]:
    """Convert logical lines into Instruction objects."""
    instructions: list[Instruction] = []
    stage_index = -1  # will become 0 on first FROM
    stage_name: Optional[str] = None

    for line_num, original, joined in logical_lines:
        # Split directive from arguments
        directive, arguments = _split_directive(joined)
        if directive is None:
            continue  # not a valid instruction line

        directive_upper = directive.upper()

        if directive_upper == "FROM":
            stage_index += 1
            stage_name = _extract_stage_name(arguments)

        # ARG before first FROM gets stage_index -1; we fix to 0 below
        instr = Instruction(
            directive=directive_upper,
            arguments=arguments,
            line_number=line_num,
            original_line=original,
            stage_index=max(stage_index, 0),
            stage_name=stage_name,
        )
        instructions.append(instr)

    return instructions


def _split_directive(line: str) -> tuple[Optional[str], str]:
    """Split a line into (DIRECTIVE, arguments).

    Returns (None, "") if the line doesn't start with a known directive.
    """
    parts = line.split(None, 1)
    if not parts:
        return None, ""
    candidate = parts[0].upper()
    if candidate in _KNOWN_DIRECTIVES:
        return candidate, parts[1] if len(parts) > 1 else ""
    return None, ""


def _extract_stage_name(from_args: str) -> Optional[str]:
    """Extract stage name from FROM arguments, e.g., 'python:3.11 AS builder'."""
    # Pattern: ... AS <name> (case-insensitive)
    m = re.search(r"\bAS\s+(\S+)", from_args, re.IGNORECASE)
    return m.group(1) if m else None


def _parse_base_image(from_args: str) -> tuple[str, Optional[str]]:
    """Parse base image and tag from FROM arguments.

    E.g., 'python:3.11-slim AS builder' -> ('python', '3.11-slim')
          'ubuntu' -> ('ubuntu', None)
          '$BASE_IMAGE' -> ('$BASE_IMAGE', None)
          'docker.io/library/python:3.11@sha256:abc' -> ('docker.io/library/python', '3.11')
    """
    # Remove --platform=... flags
    args = re.sub(r"--platform=\S+\s*", "", from_args).strip()
    # Remove AS <name>
    args = re.sub(r"\s+AS\s+\S+", "", args, flags=re.IGNORECASE).strip()

    if not args:
        return ("scratch", None)

    # Handle digest (@sha256:...)
    image_part = args.split("@")[0]

    # Split image:tag
    # Be careful with registry URLs like registry.example.com:5000/image:tag
    # Strategy: split from the right on ':', but only if what follows doesn't
    # look like a port number followed by a slash.
    colon_idx = image_part.rfind(":")
    if colon_idx > 0:
        after_colon = image_part[colon_idx + 1:]
        before_colon = image_part[:colon_idx]
        # If after_colon contains '/', it's likely a port in a registry URL
        if "/" in after_colon:
            return (image_part, None)
        return (before_colon, after_colon)

    return (image_part, None)


def _build_stages(instructions: list[Instruction]) -> list[Stage]:
    """Build Stage objects from parsed instructions."""
    stages: list[Stage] = []
    current_stage: Optional[Stage] = None

    for instr in instructions:
        if instr.directive == "FROM":
            base_image, base_tag = _parse_base_image(instr.arguments)
            current_stage = Stage(
                index=len(stages),
                name=_extract_stage_name(instr.arguments),
                base_image=base_image,
                base_tag=base_tag,
                instructions=[instr],
            )
            stages.append(current_stage)
        elif current_stage is not None:
            current_stage.instructions.append(instr)
        # else: ARG before FROM — no stage yet, instruction still captured
        # in the instructions list but not in any stage

    return stages
