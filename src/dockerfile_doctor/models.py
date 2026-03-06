"""Data models for Dockerfile Doctor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Category(Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    BEST_PRACTICE = "best-practice"


@dataclass
class Instruction:
    """A single Dockerfile instruction."""
    directive: str          # e.g., "FROM", "RUN", "COPY"
    arguments: str          # raw argument string
    line_number: int        # 1-based line number in original file
    original_line: str      # the full original line(s) including continuations
    stage_index: int = 0    # which build stage (0-based)
    stage_name: Optional[str] = None  # e.g., "builder" in FROM ... AS builder


@dataclass
class Stage:
    """A build stage in a multi-stage Dockerfile."""
    index: int
    name: Optional[str]
    base_image: str
    base_tag: Optional[str]
    instructions: list[Instruction] = field(default_factory=list)


@dataclass
class Dockerfile:
    """Parsed representation of a Dockerfile."""
    raw_content: str
    lines: list[str]
    instructions: list[Instruction] = field(default_factory=list)
    stages: list[Stage] = field(default_factory=list)

    @property
    def is_multistage(self) -> bool:
        return len(self.stages) > 1


@dataclass
class Issue:
    """A detected issue in a Dockerfile."""
    rule_id: str            # e.g., "DD001"
    title: str              # short description
    description: str        # detailed explanation
    severity: Severity
    category: Category
    line_number: int        # where the issue is (0 = file-level)
    fix_available: bool = False
    fix_description: Optional[str] = None


@dataclass
class Fix:
    """A proposed fix for an issue."""
    rule_id: str
    description: str
    # line-level replacements: (line_number, old_text, new_text)
    # line_number=0 means append to file
    replacements: list[tuple[int, str, str]] = field(default_factory=list)
    # lines to insert: (after_line_number, text)
    insertions: list[tuple[int, str]] = field(default_factory=list)
    # lines to delete
    deletions: list[int] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Complete analysis result for a Dockerfile."""
    filepath: str
    issues: list[Issue] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.INFO)
