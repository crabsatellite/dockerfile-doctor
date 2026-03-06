"""Configuration loader for Dockerfile Doctor."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RuleConfig:
    """Per-rule configuration override."""
    severity: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    """Dockerfile Doctor configuration."""
    severity: str = "info"
    ignore: list[str] = field(default_factory=list)
    rules: dict[str, RuleConfig] = field(default_factory=dict)

    @classmethod
    def default(cls) -> Config:
        return cls()

    def merge_cli(
        self,
        *,
        severity: Optional[str] = None,
        ignore: Optional[list[str]] = None,
    ) -> None:
        """Merge CLI flags on top of file-based config (CLI wins)."""
        if severity is not None:
            self.severity = severity
        if ignore:
            self.ignore = list(set(self.ignore) | set(ignore))


# ---------------------------------------------------------------------------
# YAML loading — prefer PyYAML, fall back to a minimal subset parser
# ---------------------------------------------------------------------------

def _load_yaml_pyyaml(text: str) -> dict[str, Any]:
    import yaml  # type: ignore[import-untyped]
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Config file must be a YAML mapping at the top level")
    return data


def _strip_trailing_comment(line: str) -> str:
    """Remove trailing YAML comment (`` #`` preceded by whitespace) while
    respecting quoted strings."""
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and i > 0 and line[i - 1] in (" ", "\t"):
            return line[:i].rstrip()
        i += 1
    return line


def _load_yaml_fallback(text: str) -> dict[str, Any]:
    """Minimal YAML subset parser — supports scalars, lists, and one level
    of nested mappings.  Enough for .dockerfile-doctor.yaml."""
    result: dict[str, Any] = {}
    current_key: Optional[str] = None
    current_sub: Optional[dict[str, Any]] = None
    current_list: Optional[list[str]] = None

    for raw_line in text.splitlines():
        # Strip full-line comments and trailing comments (after whitespace)
        stripped_raw = raw_line.rstrip()
        if stripped_raw.lstrip().startswith("#"):
            continue
        # Remove trailing comment: find ' #' or '\t#' not inside quotes
        line = _strip_trailing_comment(stripped_raw)
        if not line or line.isspace():
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0:
            # Top-level key
            _flush_sub(result, current_key, current_sub)
            _flush_list(result, current_key, current_list)
            current_sub = None
            current_list = None

            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            current_key = key
            if val:
                result[key] = _parse_scalar(val)
            # else: value comes from indented block below

        elif indent >= 2 and current_key is not None:
            stripped = line.strip()
            if stripped.startswith("- "):
                # List item
                if current_list is None:
                    current_list = []
                current_list.append(_parse_scalar(stripped[2:].strip()))
            elif ":" in stripped:
                # Nested mapping (one level)
                if current_list is not None:
                    _flush_list(result, current_key, current_list)
                    current_list = None
                if current_sub is None:
                    current_sub = {}
                sub_key, _, sub_val = stripped.partition(":")
                sub_key = sub_key.strip()
                sub_val = sub_val.strip()
                if sub_val:
                    current_sub[sub_key] = _parse_scalar(sub_val)
                else:
                    # Could be a deeper list — for simplicity, store None
                    current_sub[sub_key] = None

    _flush_sub(result, current_key, current_sub)
    _flush_list(result, current_key, current_list)
    return result


def _flush_sub(
    result: dict[str, Any],
    key: Optional[str],
    sub: Optional[dict[str, Any]],
) -> None:
    if key and sub is not None:
        result[key] = sub


def _flush_list(
    result: dict[str, Any],
    key: Optional[str],
    lst: Optional[list[str]],
) -> None:
    if key and lst is not None:
        result[key] = lst


def _parse_scalar(value: str) -> Any:
    """Parse a YAML scalar value."""
    if value in ("true", "True", "yes", "Yes", "on", "On"):
        return True
    if value in ("false", "False", "no", "No", "off", "Off"):
        return False
    if value in ("null", "Null", "~", ""):
        return None
    # Strip surrounding quotes
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    # Try integer
    try:
        return int(value)
    except ValueError:
        pass
    # Try float
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _load_yaml(text: str) -> dict[str, Any]:
    """Load YAML text, preferring PyYAML if available."""
    try:
        return _load_yaml_pyyaml(text)
    except ImportError:
        return _load_yaml_fallback(text)
    except Exception:
        # PyYAML ScannerError or other parse errors — fall back
        try:
            return _load_yaml_fallback(text)
        except Exception:
            raise ValueError("Config file contains invalid YAML")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from a YAML file.

    If *path* is ``None``, search the current directory and parents for
    ``.dockerfile-doctor.yaml`` or ``.dockerfile-doctor.yml``.  If no
    config file is found, return the default config.
    """
    if path is not None:
        return _parse_config_file(path)

    # Auto-discover config file
    search_dir = os.getcwd()
    for _ in range(64):  # safety limit
        for name in (".dockerfile-doctor.yaml", ".dockerfile-doctor.yml"):
            candidate = os.path.join(search_dir, name)
            if os.path.isfile(candidate):
                return _parse_config_file(candidate)
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent

    return Config.default()


def _parse_config_file(path: str) -> Config:
    """Parse a config file into a :class:`Config`."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = _load_yaml(fh.read())
    except UnicodeDecodeError:
        raise ValueError(f"Config file is not valid UTF-8: {path}")

    cfg = Config()
    if "severity" in raw:
        sev = str(raw["severity"]).lower()
        if sev in ("info", "warning", "error"):
            cfg.severity = sev
    if "ignore" in raw and isinstance(raw["ignore"], list):
        cfg.ignore = [str(r) for r in raw["ignore"]]
    if "rules" in raw and isinstance(raw["rules"], dict):
        for rule_id, rule_raw in raw["rules"].items():
            rc = RuleConfig()
            if isinstance(rule_raw, dict):
                if "severity" in rule_raw:
                    rc.severity = str(rule_raw["severity"]).lower()
                rc.extra = {
                    k: v for k, v in rule_raw.items() if k != "severity"
                }
            cfg.rules[str(rule_id)] = rc
    return cfg
