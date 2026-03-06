"""Rule engine for Dockerfile Doctor — 80 lint rules, pure Python."""

from __future__ import annotations

import re
from typing import Callable

from .models import Category, Dockerfile, Issue, Severity

_KNOWN_DIRECTIVES = frozenset({
    "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV",
    "ADD", "COPY", "ENTRYPOINT", "VOLUME", "USER", "WORKDIR",
    "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL",
})

# ---------------------------------------------------------------------------
# Type alias for a rule function
# ---------------------------------------------------------------------------
RuleFn = Callable[[Dockerfile], list[Issue]]

# Registry populated by @rule decorator
ALL_RULES: list[RuleFn] = []


def rule(fn: RuleFn) -> RuleFn:
    """Register a rule function."""
    ALL_RULES.append(fn)
    return fn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(dockerfile: Dockerfile) -> list[Issue]:
    """Run all registered rules against a parsed Dockerfile."""
    issues: list[Issue] = []
    for rule_fn in ALL_RULES:
        issues.extend(rule_fn(dockerfile))
    issues.sort(key=lambda i: i.line_number)
    return issues


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

_LARGE_BASE_IMAGES = {
    "ubuntu", "debian", "centos", "fedora", "amazonlinux",
    "python", "node", "ruby", "golang", "openjdk", "java",
    "php", "perl", "rust", "sdk",
}

_SLIM_ALPINE_PATTERN = re.compile(r"(slim|alpine|distroless|minimal|tiny|busybox)", re.IGNORECASE)

_SECRET_PATTERNS = re.compile(
    r"\b(password|passwd|secret|api_key|apikey|access_key|"
    r"private_key|auth_token|aws_secret|db_pass)\b",
    re.IGNORECASE,
)
# Variable names that commonly use "secret"/"token" legitimately
_SECRET_FALSE_POSITIVE = re.compile(
    r"(SECRET_KEY_BASE|TOKEN_BUCKET|TOKEN_LIMIT|TOKEN_TYPE|REFRESH_TOKEN_URL)",
    re.IGNORECASE,
)

_INSECURE_PORTS = {"21", "23"}


def _image_basename(image: str) -> str:
    """Extract the short image name: 'docker.io/library/python' -> 'python'."""
    return image.rsplit("/", 1)[-1].lower()


def _has_tag_that_is_slim_or_alpine(tag: str | None) -> bool:
    if tag is None:
        return False
    return bool(_SLIM_ALPINE_PATTERN.search(tag))


def _instructions_by_directive(dockerfile: Dockerfile, directive: str):
    return [i for i in dockerfile.instructions if i.directive == directive]


# ---------------------------------------------------------------------------
# DD001 — latest tag or no tag on base image
# ---------------------------------------------------------------------------
@rule
def dd001_no_tag_or_latest(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    # Collect known stage names so "FROM builder" isn't flagged
    stage_names: set[str] = set()
    for instr in _instructions_by_directive(dockerfile, "FROM"):
        args = instr.arguments.strip()
        # Remove --platform flag first
        clean = re.sub(r"--platform=\S+\s*", "", args).strip()
        # Extract and record AS alias (even for scratch)
        as_match = re.search(r"\bAS\s+(\S+)", clean, re.IGNORECASE)
        if as_match:
            stage_names.add(as_match.group(1).lower())
        # Skip scratch
        if clean.lower().startswith("scratch"):
            continue
        # Skip variable references like $BASE_IMAGE or ${BASE_IMAGE}
        if clean.startswith("$"):
            continue
        # Remove AS alias (already recorded above)
        clean = re.sub(r"\s+AS\s+\S+", "", clean, flags=re.IGNORECASE).strip()

        # Skip references to previously-defined build stages
        if clean.lower() in stage_names:
            continue
        # Numeric stage references (FROM 0) are also valid
        if clean.isdigit():
            continue

        # Skip digest-pinned images (more reproducible than tags)
        if "@" in clean:
            continue

        # Parse image:tag, handling registry:port/image patterns
        # Use the same logic as parser._parse_base_image
        image_part = clean.split("@")[0]  # strip digest
        colon_idx = image_part.rfind(":")
        if colon_idx <= 0:
            # No colon at all, or colon at start — no tag
            tag = None
        else:
            after_colon = image_part[colon_idx + 1:]
            if "/" in after_colon:
                # It's a registry port (e.g., registry:5000/image), not a tag
                tag = None
            else:
                tag = after_colon

        if tag is None:
            issues.append(Issue(
                rule_id="DD001",
                title="No tag specified on base image",
                description=f"Image '{clean}' has no tag; it defaults to 'latest', "
                            "making builds non-reproducible.",
                severity=Severity.WARNING,
                category=Category.MAINTAINABILITY,
                line_number=instr.line_number,
                fix_available=False,
            ))
        elif tag.lower() == "latest":
                issues.append(Issue(
                    rule_id="DD001",
                    title="Using 'latest' tag on base image",
                    description=f"Image '{clean}' uses the 'latest' tag, "
                                "making builds non-reproducible.",
                    severity=Severity.WARNING,
                    category=Category.MAINTAINABILITY,
                    line_number=instr.line_number,
                    fix_available=False,
                ))
    return issues


# ---------------------------------------------------------------------------
# DD002 — apt-get update not combined with apt-get install
# ---------------------------------------------------------------------------
@rule
def dd002_apt_update_not_combined(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        has_update = "apt-get update" in args or re.search(r"\bapt\s+update\b", args)
        has_install = "apt-get install" in args or re.search(r"\bapt\s+install\b", args)
        if has_update and not has_install:
            issues.append(Issue(
                rule_id="DD002",
                title="apt-get update not combined with install",
                description="Running 'apt-get update' in a separate RUN layer from "
                            "'apt-get install' causes caching issues. Combine them "
                            "in a single RUN instruction.",
                severity=Severity.ERROR,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD003 — Missing --no-install-recommends
# ---------------------------------------------------------------------------
@rule
def dd003_no_install_recommends(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        has_apt_install = "apt-get install" in args or bool(re.search(r"\bapt\s+install\b", args))
        if has_apt_install and "--no-install-recommends" not in args:
            issues.append(Issue(
                rule_id="DD003",
                title="Missing --no-install-recommends",
                description="Use 'apt-get install --no-install-recommends' to avoid "
                            "installing unnecessary packages and reduce image size.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Add --no-install-recommends to apt-get install.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD004 — Missing apt cache cleanup
# ---------------------------------------------------------------------------
@rule
def dd004_apt_cache_cleanup(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        has_apt_install = "apt-get install" in args or bool(re.search(r"\bapt\s+install\b", args))
        if has_apt_install and "rm -rf /var/lib/apt/lists" not in args:
            issues.append(Issue(
                rule_id="DD004",
                title="Missing apt cache cleanup",
                description="After 'apt-get install', add "
                            "'&& rm -rf /var/lib/apt/lists/*' to reduce layer size.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Append '&& rm -rf /var/lib/apt/lists/*'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD005 — Multiple consecutive RUN instructions
# ---------------------------------------------------------------------------
@rule
def dd005_consecutive_run(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        run_streak_start: int | None = None
        run_count = 0
        for instr in stage.instructions:
            if instr.directive == "RUN":
                if run_streak_start is None:
                    run_streak_start = instr.line_number
                run_count += 1
            else:
                if run_count >= 2:
                    issues.append(Issue(
                        rule_id="DD005",
                        title="Multiple consecutive RUN instructions",
                        description=f"{run_count} consecutive RUN instructions starting "
                                    f"at line {run_streak_start} could be combined to "
                                    "reduce layers.",
                        severity=Severity.INFO,
                        category=Category.PERFORMANCE,
                        line_number=run_streak_start,  # type: ignore[arg-type]
                        fix_available=True,
                        fix_description="Combine consecutive RUN instructions with &&.",
                    ))
                run_streak_start = None
                run_count = 0
        # Check at end of stage
        if run_count >= 2:
            issues.append(Issue(
                rule_id="DD005",
                title="Multiple consecutive RUN instructions",
                description=f"{run_count} consecutive RUN instructions starting "
                            f"at line {run_streak_start} could be combined to "
                            "reduce layers.",
                severity=Severity.INFO,
                category=Category.PERFORMANCE,
                line_number=run_streak_start,  # type: ignore[arg-type]
                fix_available=True,
                fix_description="Combine consecutive RUN instructions with &&.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD006 — COPY . . before dependency install (cache bust)
# ---------------------------------------------------------------------------
@rule
def dd006_copy_all_before_deps(dockerfile: Dockerfile) -> list[Issue]:
    """Detect COPY . . or ADD . . appearing before a dependency install step."""
    issues: list[Issue] = []
    dep_install_patterns = [
        "pip install", "npm install", "npm ci", "yarn install",
        "bundle install", "composer install", "go mod download",
        "cargo build", "apt-get install", "apk add",
    ]

    for stage in dockerfile.stages:
        copy_all_instr = None
        for instr in stage.instructions:
            if instr.directive in ("COPY", "ADD"):
                args = instr.arguments.strip()
                # Detect patterns like ". .", ". /app", ". /app/"
                # We look for source=. specifically
                parts = args.split()
                # Remove --chown=..., --chmod=..., --from=... flags
                cleaned = [p for p in parts if not p.startswith("--")]
                if len(cleaned) >= 2 and cleaned[0] in (".", "./"):
                    copy_all_instr = instr
            elif instr.directive == "RUN" and copy_all_instr is not None:
                for pat in dep_install_patterns:
                    if pat in instr.arguments:
                        issues.append(Issue(
                            rule_id="DD006",
                            title="COPY/ADD all files before dependency install",
                            description=f"'{copy_all_instr.directive} . ...' at line "
                                        f"{copy_all_instr.line_number} copies all files "
                                        "before dependency installation, busting the "
                                        "Docker cache on every code change. Copy "
                                        "dependency files first.",
                            severity=Severity.WARNING,
                            category=Category.PERFORMANCE,
                            line_number=copy_all_instr.line_number,
                        ))
                        copy_all_instr = None  # report once per stage
                        break
    return issues


# ---------------------------------------------------------------------------
# DD007 — ADD instead of COPY (when not extracting archives)
# ---------------------------------------------------------------------------
@rule
def dd007_add_instead_of_copy(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    archive_exts = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".zip", ".gz", ".bz2", ".xz")
    for instr in _instructions_by_directive(dockerfile, "ADD"):
        args = instr.arguments.strip()
        # Skip URLs (ADD http://...)
        if re.search(r"https?://", args):
            continue
        # Check if source looks like an archive
        parts = args.split()
        sources = [p for p in parts if not p.startswith("--")]
        # Last element is destination
        if len(sources) < 2:
            continue
        src_parts = sources[:-1]
        is_archive = any(
            any(s.lower().endswith(ext) for ext in archive_exts)
            for s in src_parts
        )
        if not is_archive:
            issues.append(Issue(
                rule_id="DD007",
                title="ADD used instead of COPY",
                description="Use COPY instead of ADD when not extracting a local "
                            "tar archive. ADD has extra behavior (URL fetch, auto-"
                            "extraction) that can be surprising.",
                severity=Severity.WARNING,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Replace ADD with COPY.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD008 — No USER instruction (running as root)
# ---------------------------------------------------------------------------
@rule
def dd008_no_user(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    if not dockerfile.stages:
        return issues
    # Only check the final stage (the one that ships)
    final_stage = dockerfile.stages[-1]
    user_instrs = [i for i in final_stage.instructions if i.directive == "USER"]
    if not user_instrs:
        issues.append(Issue(
            rule_id="DD008",
            title="No USER instruction - running as root",
            description="The final stage does not set a USER. The container will "
                        "run as root, which is a security risk.",
            severity=Severity.WARNING,
            category=Category.SECURITY,
            line_number=0,
            fix_available=True,
        ))
    elif user_instrs[-1].arguments.strip().lower() in ("root", "0"):
        # Last USER instruction sets root — still a risk
        issues.append(Issue(
            rule_id="DD008",
            title="Last USER instruction sets root",
            description="The final USER instruction sets 'root'. The container will "
                        "run as root, which is a security risk.",
            severity=Severity.WARNING,
            category=Category.SECURITY,
            line_number=user_instrs[-1].line_number,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD009 — pip install without --no-cache-dir
# ---------------------------------------------------------------------------
@rule
def dd009_pip_no_cache(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        has_pip = bool(re.search(r"\b(pip3?|python3?\s+-m\s+pip)\s+install\b", args))
        if has_pip and "--no-cache-dir" not in args:
            issues.append(Issue(
                rule_id="DD009",
                title="pip install without --no-cache-dir",
                description="Use 'pip install --no-cache-dir' to avoid storing "
                            "the pip cache in the image layer.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Add --no-cache-dir to pip install.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD010 — npm install instead of npm ci
# ---------------------------------------------------------------------------
@rule
def dd010_npm_ci(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        # Match "npm install" but not "npm ci" or "npm install --save-dev" in dev stages
        # We use a simple heuristic: if "npm install" appears and "npm ci" does not
        # Match bare "npm install" (no package args) but not "npm install <pkg>"
        # Bare npm install ends with line-end, &&, ;, |, or backslash continuation
        if re.search(r"\bnpm\s+install\s*($|&&|;|\\\\|\|)", args) and not re.search(r"\bnpm\s+ci\b", args):
            issues.append(Issue(
                rule_id="DD010",
                title="npm install instead of npm ci",
                description="Use 'npm ci' instead of 'npm install' for reproducible "
                            "production builds. 'npm ci' uses package-lock.json.",
                severity=Severity.INFO,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Replace 'npm install' with 'npm ci'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD011 — WORKDIR with relative path
# ---------------------------------------------------------------------------
@rule
def dd011_workdir_relative(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "WORKDIR"):
        path = instr.arguments.strip()
        # Absolute paths start with / or a variable
        if not path.startswith("/") and not path.startswith("$"):
            issues.append(Issue(
                rule_id="DD011",
                title="WORKDIR with relative path",
                description=f"WORKDIR '{path}' is a relative path. Use an absolute "
                            "path for clarity and predictability.",
                severity=Severity.WARNING,
                category=Category.MAINTAINABILITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Prepend '/' to make WORKDIR absolute.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD012 — No HEALTHCHECK instruction
# ---------------------------------------------------------------------------
@rule
def dd012_no_healthcheck(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    has_healthcheck = any(i.directive == "HEALTHCHECK" for i in dockerfile.instructions)
    if not has_healthcheck and dockerfile.stages:
        issues.append(Issue(
            rule_id="DD012",
            title="No HEALTHCHECK instruction",
            description="Consider adding a HEALTHCHECK instruction so Docker can "
                        "monitor the container's health.",
            severity=Severity.INFO,
            category=Category.BEST_PRACTICE,
            line_number=0,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD013 — apt-get upgrade / dist-upgrade
# ---------------------------------------------------------------------------
@rule
def dd013_apt_upgrade(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"apt(?:-get)?\s+(?:-\w+\s+)*(upgrade|dist-upgrade)", args):
            issues.append(Issue(
                rule_id="DD013",
                title="apt-get upgrade in Dockerfile",
                description="Running 'apt-get upgrade' or 'apt-get dist-upgrade' "
                            "in a Dockerfile makes builds non-reproducible. "
                            "Pin package versions instead.",
                severity=Severity.WARNING,
                category=Category.MAINTAINABILITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Remove 'apt-get upgrade' / 'apt-get dist-upgrade'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD014 — EXPOSE with insecure ports
# ---------------------------------------------------------------------------
@rule
def dd014_insecure_ports(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "EXPOSE"):
        # EXPOSE can list multiple ports: "80 443 23/tcp"
        for token in instr.arguments.split():
            port = token.split("/")[0]
            if port in _INSECURE_PORTS:
                issues.append(Issue(
                    rule_id="DD014",
                    title=f"Exposing insecure port {port}",
                    description=f"Port {port} (FTP/Telnet) is commonly considered "
                                "insecure. Verify this is intentional.",
                    severity=Severity.INFO,
                    category=Category.SECURITY,
                    line_number=instr.line_number,
                ))
    return issues


# ---------------------------------------------------------------------------
# DD015 — Missing PYTHONUNBUFFERED / PYTHONDONTWRITEBYTECODE for Python
# ---------------------------------------------------------------------------
@rule
def dd015_python_env(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    # Detect if this is a Python image
    is_python = False
    for stage in dockerfile.stages:
        basename = _image_basename(stage.base_image)
        if basename.split(":")[0] == "python":
            is_python = True
            break
    if not is_python:
        # Also check if pip/pip3/python -m pip install is used
        for instr in _instructions_by_directive(dockerfile, "RUN"):
            if re.search(r"\b(pip3?|python3?\s+-m\s+pip)\s+install\b", instr.arguments):
                is_python = True
                break

    if not is_python:
        return issues

    all_env_text = " ".join(
        instr.arguments for instr in _instructions_by_directive(dockerfile, "ENV")
    )
    missing = []
    if "PYTHONUNBUFFERED" not in all_env_text:
        missing.append("PYTHONUNBUFFERED=1")
    if "PYTHONDONTWRITEBYTECODE" not in all_env_text:
        missing.append("PYTHONDONTWRITEBYTECODE=1")

    if missing:
        issues.append(Issue(
            rule_id="DD015",
            title="Missing Python environment variables",
            description=f"Consider setting {', '.join(missing)} via ENV for "
                        "better Docker behavior (unbuffered logs, no .pyc files).",
            severity=Severity.INFO,
            category=Category.BEST_PRACTICE,
            line_number=0,
            fix_available=True,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD016 — curl/wget without cleanup in same RUN
# ---------------------------------------------------------------------------
@rule
def dd016_curl_wget_cleanup(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        has_download = bool(re.search(r"\b(curl|wget)\b", args))
        if not has_download:
            continue
        # Check if there's a cleanup: rm of the downloaded file, or piping
        has_pipe = "|" in args
        has_rm = bool(re.search(r"\brm\s", args))
        # curl -o file ... && rm file  or wget ... && rm ...
        if not has_pipe and not has_rm:
            issues.append(Issue(
                rule_id="DD016",
                title="curl/wget without cleanup",
                description="Downloaded files via curl/wget are not cleaned up in "
                            "the same RUN instruction. Either pipe directly or "
                            "remove the file after use.",
                severity=Severity.INFO,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD017 — Deprecated MAINTAINER instruction
# ---------------------------------------------------------------------------
@rule
def dd017_deprecated_maintainer(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "MAINTAINER"):
        issues.append(Issue(
            rule_id="DD017",
            title="Deprecated MAINTAINER instruction",
            description="MAINTAINER is deprecated. Use "
                        "'LABEL maintainer=\"name\"' instead.",
            severity=Severity.WARNING,
            category=Category.MAINTAINABILITY,
            line_number=instr.line_number,
            fix_available=True,
            fix_description="Convert MAINTAINER to LABEL maintainer=...",
        ))
    return issues


# ---------------------------------------------------------------------------
# DD018 — Large base image when slim/alpine exists
# ---------------------------------------------------------------------------
@rule
def dd018_large_base_image(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        basename = _image_basename(stage.base_image)
        if basename in _LARGE_BASE_IMAGES:
            tag = stage.base_tag
            if not _has_tag_that_is_slim_or_alpine(tag):
                issues.append(Issue(
                    rule_id="DD018",
                    title="Large base image",
                    description=f"Image '{stage.base_image}"
                                f"{':{}'.format(tag) if tag else ''}' may have a "
                                "slim or alpine variant that is significantly smaller.",
                    severity=Severity.INFO,
                    category=Category.PERFORMANCE,
                    line_number=stage.instructions[0].line_number if stage.instructions else 0,
                ))
    return issues


# ---------------------------------------------------------------------------
# DD019 — Shell form CMD/ENTRYPOINT instead of exec form
# ---------------------------------------------------------------------------
@rule
def dd019_shell_form(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in dockerfile.instructions:
        if instr.directive not in ("CMD", "ENTRYPOINT"):
            continue
        args = instr.arguments.strip()
        # Exec form starts with [
        if not args.startswith("["):
            issues.append(Issue(
                rule_id="DD019",
                title=f"Shell form used for {instr.directive}",
                description=f"{instr.directive} uses shell form. Prefer exec form "
                            "(JSON array) so signals are properly forwarded to the "
                            "process.",
                severity=Severity.WARNING,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description=f"Convert {instr.directive} to exec form.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD020 — Secrets in ENV/ARG
# ---------------------------------------------------------------------------
@rule
def dd020_secrets_in_env(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in dockerfile.instructions:
        if instr.directive not in ("ENV", "ARG"):
            continue
        args = instr.arguments
        if _SECRET_PATTERNS.search(args) and not _SECRET_FALSE_POSITIVE.search(args):
            # Only flag if a value is actually assigned
            # ARG PASSWORD (no =) is a legitimate build-arg declaration
            # ENV PASSWORD=hunter2 or ENV PASSWORD hunter2 are hardcoded secrets
            has_eq_value = "=" in args
            # Old-style ENV: "ENV KEY value" (space-separated, only ENV not ARG)
            has_space_value = (
                instr.directive == "ENV"
                and len(args.split()) >= 2
                and "=" not in args.split()[0]
            )
            if not has_eq_value and not has_space_value:
                continue
            issues.append(Issue(
                rule_id="DD020",
                title=f"Possible secret in {instr.directive}",
                description=f"{instr.directive} at line {instr.line_number} may "
                            "contain sensitive data (password, token, key). "
                            "Use Docker build secrets (--mount=type=secret) or "
                            "runtime environment variables instead.",
                severity=Severity.ERROR,
                category=Category.SECURITY,
                line_number=instr.line_number,
            ))
    return issues


# ===========================================================================
# DD021–DD035: Package manager best practices
# ===========================================================================

# ---------------------------------------------------------------------------
# DD021 — Do not use sudo
# ---------------------------------------------------------------------------
@rule
def dd021_no_sudo(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if re.search(r"\bsudo\b", instr.arguments):
            issues.append(Issue(
                rule_id="DD021",
                title="Do not use sudo in RUN",
                description="Avoid using 'sudo' in Dockerfiles. If you need root "
                            "permissions, use USER root before the command and "
                            "switch back afterward.",
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Remove 'sudo' from the command.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD022 — Pin versions in apt-get install
# ---------------------------------------------------------------------------
@rule
def dd022_apt_pin_versions(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if not ("apt-get install" in args or re.search(r"\bapt\s+install\b", args)):
            continue
        # Find package names (tokens after install flags)
        # Packages without = are unpinned
        # Split on && to isolate the apt-get install segment
        for segment in re.split(r"&&|;", args):
            if "install" not in segment:
                continue
            tokens = segment.split()
            in_packages = False
            for tok in tokens:
                if tok == "install":
                    in_packages = True
                    continue
                if not in_packages:
                    continue
                if tok.startswith("-") or tok.startswith("\\"):
                    continue
                if "=" not in tok and tok not in ("&&", ";", "\\", "|"):
                    issues.append(Issue(
                        rule_id="DD022",
                        title="Pin versions in apt-get install",
                        description=f"Package '{tok}' is not version-pinned. "
                                    "Use 'package=version' for reproducible builds.",
                        severity=Severity.INFO,
                        category=Category.MAINTAINABILITY,
                        line_number=instr.line_number,
                    ))
                    break  # one warning per instruction
    return issues


# ---------------------------------------------------------------------------
# DD023 — Missing -y in apt-get install
# ---------------------------------------------------------------------------
@rule
def dd023_apt_missing_yes(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        has_apt_install = "apt-get install" in args
        if has_apt_install and "-y" not in args and "--yes" not in args and "-qq" not in args:
            issues.append(Issue(
                rule_id="DD023",
                title="Missing -y in apt-get install",
                description="Use 'apt-get install -y' to avoid interactive prompts "
                            "that block the build.",
                severity=Severity.ERROR,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Add -y to apt-get install.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD024 — Use apt-get instead of apt
# ---------------------------------------------------------------------------
@rule
def dd024_use_apt_get(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        # Match bare "apt install" / "apt update" but not "apt-get"
        if re.search(r"\bapt\s+(install|update|upgrade|remove|purge)\b", instr.arguments):
            if "apt-get" not in instr.arguments:
                issues.append(Issue(
                    rule_id="DD024",
                    title="Use apt-get instead of apt",
                    description="'apt' is designed for interactive use. Use 'apt-get' "
                                "in Dockerfiles for stable, scriptable behavior.",
                    severity=Severity.WARNING,
                    category=Category.BEST_PRACTICE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Replace 'apt' with 'apt-get'.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD025 — apk add without --no-cache
# ---------------------------------------------------------------------------
@rule
def dd025_apk_no_cache(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\bapk\s+(add|install)\b", args) and "--no-cache" not in args:
            issues.append(Issue(
                rule_id="DD025",
                title="apk add without --no-cache",
                description="Use 'apk add --no-cache' to avoid caching the index "
                            "and reduce image size.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Add --no-cache to apk add.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD026 — apk upgrade in Dockerfile
# ---------------------------------------------------------------------------
@rule
def dd026_apk_upgrade(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if re.search(r"\bapk\s+upgrade\b", instr.arguments):
            issues.append(Issue(
                rule_id="DD026",
                title="apk upgrade in Dockerfile",
                description="Running 'apk upgrade' makes builds non-reproducible. "
                            "Pin package versions instead.",
                severity=Severity.WARNING,
                category=Category.MAINTAINABILITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Remove 'apk upgrade'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD027 — Pin versions in apk add
# ---------------------------------------------------------------------------
@rule
def dd027_apk_pin_versions(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if not re.search(r"\bapk\s+add\b", args):
            continue
        for segment in re.split(r"&&|;", args):
            if "apk" not in segment or "add" not in segment:
                continue
            tokens = segment.split()
            in_packages = False
            for tok in tokens:
                if tok == "add":
                    in_packages = True
                    continue
                if not in_packages:
                    continue
                if tok.startswith("-") or tok.startswith("\\"):
                    continue
                # apk uses = or ~= for pinning
                if "=" not in tok and tok not in ("&&", ";", "\\", "|"):
                    issues.append(Issue(
                        rule_id="DD027",
                        title="Pin versions in apk add",
                        description=f"Package '{tok}' is not version-pinned. "
                                    "Use 'package=version' for reproducible builds.",
                        severity=Severity.INFO,
                        category=Category.MAINTAINABILITY,
                        line_number=instr.line_number,
                    ))
                    break
    return issues


# ---------------------------------------------------------------------------
# DD028 — Pin versions in pip install
# ---------------------------------------------------------------------------
@rule
def dd028_pip_pin_versions(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if not re.search(r"\b(pip3?|python3?\s+-m\s+pip)\s+install\b", args):
            continue
        # Skip if using -r requirements.txt (versions pinned there)
        if re.search(r"-r\s+\S+", args):
            continue
        # Look for unpinned packages (no ==, >=, ~=)
        for segment in re.split(r"&&|;", args):
            if "install" not in segment:
                continue
            tokens = segment.split()
            in_packages = False
            for tok in tokens:
                if tok == "install":
                    in_packages = True
                    continue
                if not in_packages:
                    continue
                if tok.startswith("-") or tok.startswith("\\"):
                    if tok in ("-r", "--requirement"):
                        break  # requirements file handles pinning
                    continue
                if "==" not in tok and ">=" not in tok and "~=" not in tok and tok not in ("&&", ";", "\\", "|", "."):
                    issues.append(Issue(
                        rule_id="DD028",
                        title="Pin versions in pip install",
                        description=f"Package '{tok}' is not version-pinned. "
                                    "Use 'package==version' for reproducible builds.",
                        severity=Severity.INFO,
                        category=Category.MAINTAINABILITY,
                        line_number=instr.line_number,
                    ))
                    break
    return issues


# ---------------------------------------------------------------------------
# DD029 — Pin versions in npm install (specific packages)
# ---------------------------------------------------------------------------
@rule
def dd029_npm_pin_versions(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        # Match npm install <package> (not bare npm install)
        m = re.search(r"\bnpm\s+install\s+(?!-\s)(\S+)", args)
        if m:
            pkg = m.group(1)
            if pkg.startswith("-"):
                continue
            # Check if version is pinned (package@version)
            if "@" not in pkg and pkg not in ("&&", ";", "\\"):
                issues.append(Issue(
                    rule_id="DD029",
                    title="Pin versions in npm install",
                    description=f"Package '{pkg}' is not version-pinned. "
                                "Use 'package@version' for reproducible builds.",
                    severity=Severity.INFO,
                    category=Category.MAINTAINABILITY,
                    line_number=instr.line_number,
                ))
    return issues


# ---------------------------------------------------------------------------
# DD030 — Pin versions in gem install
# ---------------------------------------------------------------------------
@rule
def dd030_gem_pin_versions(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if not re.search(r"\bgem\s+install\b", args):
            continue
        # Check for -v or --version flag
        if re.search(r"(-v|--version)\s+", args):
            continue
        for segment in re.split(r"&&|;", args):
            if "gem" not in segment or "install" not in segment:
                continue
            tokens = segment.split()
            in_packages = False
            for tok in tokens:
                if tok == "install":
                    in_packages = True
                    continue
                if not in_packages:
                    continue
                if tok.startswith("-") or tok.startswith("\\"):
                    continue
                if tok not in ("&&", ";", "\\", "|"):
                    issues.append(Issue(
                        rule_id="DD030",
                        title="Pin versions in gem install",
                        description=f"Gem '{tok}' is not version-pinned. "
                                    "Use 'gem install name -v version'.",
                        severity=Severity.INFO,
                        category=Category.MAINTAINABILITY,
                        line_number=instr.line_number,
                    ))
                    break
    return issues


# ---------------------------------------------------------------------------
# DD031 — yum install without yum clean all
# ---------------------------------------------------------------------------
@rule
def dd031_yum_clean(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\byum\s+install\b", args) and "yum clean all" not in args:
            issues.append(Issue(
                rule_id="DD031",
                title="yum install without yum clean all",
                description="After 'yum install', add '&& yum clean all' "
                            "to reduce image size.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Append '&& yum clean all'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD032 — Pin versions in yum install
# ---------------------------------------------------------------------------
@rule
def dd032_yum_pin_versions(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if not re.search(r"\byum\s+install\b", args):
            continue
        for segment in re.split(r"&&|;", args):
            if "yum" not in segment or "install" not in segment:
                continue
            tokens = segment.split()
            in_packages = False
            for tok in tokens:
                if tok == "install":
                    in_packages = True
                    continue
                if not in_packages:
                    continue
                if tok.startswith("-") or tok.startswith("\\"):
                    continue
                if "-" not in tok and tok not in ("&&", ";", "\\", "|"):
                    # yum uses name-version format
                    issues.append(Issue(
                        rule_id="DD032",
                        title="Pin versions in yum install",
                        description=f"Package '{tok}' is not version-pinned. "
                                    "Use 'package-version' for reproducible builds.",
                        severity=Severity.INFO,
                        category=Category.MAINTAINABILITY,
                        line_number=instr.line_number,
                    ))
                    break
    return issues


# ---------------------------------------------------------------------------
# DD033 — dnf install without dnf clean all
# ---------------------------------------------------------------------------
@rule
def dd033_dnf_clean(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\bdnf\s+install\b", args) and "dnf clean all" not in args:
            issues.append(Issue(
                rule_id="DD033",
                title="dnf install without dnf clean all",
                description="After 'dnf install', add '&& dnf clean all' "
                            "to reduce image size.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Append '&& dnf clean all'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD034 — zypper install without zypper clean
# ---------------------------------------------------------------------------
@rule
def dd034_zypper_clean(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\bzypper\s+install\b", args) and "zypper clean" not in args:
            issues.append(Issue(
                rule_id="DD034",
                title="zypper install without zypper clean",
                description="After 'zypper install', add '&& zypper clean' "
                            "to reduce image size.",
                severity=Severity.WARNING,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Append '&& zypper clean'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD035 — Missing DEBIAN_FRONTEND=noninteractive
# ---------------------------------------------------------------------------
@rule
def dd035_debian_frontend(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    has_apt = any(
        "apt-get install" in i.arguments or re.search(r"\bapt\s+install\b", i.arguments)
        for i in _instructions_by_directive(dockerfile, "RUN")
    )
    if not has_apt:
        return issues
    all_env = " ".join(i.arguments for i in _instructions_by_directive(dockerfile, "ENV"))
    all_arg = " ".join(i.arguments for i in _instructions_by_directive(dockerfile, "ARG"))
    all_run = " ".join(i.arguments for i in _instructions_by_directive(dockerfile, "RUN"))
    if "DEBIAN_FRONTEND" not in all_env and "DEBIAN_FRONTEND" not in all_arg and "DEBIAN_FRONTEND" not in all_run:
        issues.append(Issue(
            rule_id="DD035",
            title="Missing DEBIAN_FRONTEND=noninteractive",
            description="Set 'ENV DEBIAN_FRONTEND=noninteractive' or use "
                        "'ARG DEBIAN_FRONTEND=noninteractive' to prevent "
                        "interactive prompts during apt-get install.",
            severity=Severity.INFO,
            category=Category.BEST_PRACTICE,
            line_number=0,
            fix_available=True,
            fix_description="Add ARG DEBIAN_FRONTEND=noninteractive.",
        ))
    return issues


# ===========================================================================
# DD036–DD050: Docker instruction best practices
# ===========================================================================

# ---------------------------------------------------------------------------
# DD036 — Multiple CMD instructions
# ---------------------------------------------------------------------------
@rule
def dd036_multiple_cmd(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        cmds = [i for i in stage.instructions if i.directive == "CMD"]
        if len(cmds) > 1:
            for cmd in cmds[:-1]:
                issues.append(Issue(
                    rule_id="DD036",
                    title="Multiple CMD instructions",
                    description="Only the last CMD instruction takes effect. "
                                "Earlier CMD instructions are ignored.",
                    severity=Severity.WARNING,
                    category=Category.BEST_PRACTICE,
                    line_number=cmd.line_number,
                    fix_available=True,
                    fix_description="Remove earlier CMD instruction.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD037 — Multiple ENTRYPOINT instructions
# ---------------------------------------------------------------------------
@rule
def dd037_multiple_entrypoint(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        eps = [i for i in stage.instructions if i.directive == "ENTRYPOINT"]
        if len(eps) > 1:
            for ep in eps[:-1]:
                issues.append(Issue(
                    rule_id="DD037",
                    title="Multiple ENTRYPOINT instructions",
                    description="Only the last ENTRYPOINT instruction takes effect. "
                                "Earlier ENTRYPOINT instructions are ignored.",
                    severity=Severity.WARNING,
                    category=Category.BEST_PRACTICE,
                    line_number=ep.line_number,
                    fix_available=True,
                    fix_description="Remove earlier ENTRYPOINT instruction.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD038 — Invalid UNIX port number
# ---------------------------------------------------------------------------
@rule
def dd038_invalid_port(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "EXPOSE"):
        for token in instr.arguments.split():
            port_str = token.split("/")[0]
            # Handle ranges like 8000-8100
            parts = port_str.split("-")
            for part in parts:
                try:
                    port = int(part)
                    if port < 1 or port > 65535:
                        issues.append(Issue(
                            rule_id="DD038",
                            title=f"Invalid port number {part}",
                            description=f"Port {part} is not a valid UNIX port. "
                                        "Valid range is 1-65535.",
                            severity=Severity.ERROR,
                            category=Category.BEST_PRACTICE,
                            line_number=instr.line_number,
                        ))
                except ValueError:
                    pass
    return issues


# ---------------------------------------------------------------------------
# DD039 — COPY --from references unknown stage
# ---------------------------------------------------------------------------
@rule
def dd039_copy_from_unknown(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    stage_names = set()
    stage_count = 0
    for stage in dockerfile.stages:
        if stage.name:
            stage_names.add(stage.name.lower())
        stage_count += 1

    for instr in _instructions_by_directive(dockerfile, "COPY"):
        m = re.search(r"--from=(\S+)", instr.arguments, re.IGNORECASE)
        if m:
            ref = m.group(1)
            # Numeric references
            if ref.isdigit():
                if int(ref) >= stage_count:
                    issues.append(Issue(
                        rule_id="DD039",
                        title=f"COPY --from references unknown stage {ref}",
                        description=f"Stage index {ref} does not exist. "
                                    f"There are only {stage_count} stages.",
                        severity=Severity.ERROR,
                        category=Category.BEST_PRACTICE,
                        line_number=instr.line_number,
                    ))
            elif ref.lower() not in stage_names:
                # Could be an external image, not an error
                pass
    return issues


# ---------------------------------------------------------------------------
# DD040 — Missing pipefail for pipe in RUN
# ---------------------------------------------------------------------------
@rule
def dd040_missing_pipefail(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    # Check if SHELL is set with pipefail
    has_pipefail_shell = any(
        "pipefail" in i.arguments
        for i in _instructions_by_directive(dockerfile, "SHELL")
    )
    if has_pipefail_shell:
        return issues

    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        # Check for pipe usage (but not || which is OR)
        if re.search(r"(?<!\|)\|(?!\|)", args):
            # Check if pipefail is set inline
            if "set -o pipefail" not in args and "set -euo pipefail" not in args:
                issues.append(Issue(
                    rule_id="DD040",
                    title="Pipe without pipefail",
                    description="Using a pipe (|) in RUN without 'set -o pipefail' "
                                "means the exit code of the last command is used. "
                                "A failure in earlier commands will be silently ignored.",
                    severity=Severity.WARNING,
                    category=Category.BEST_PRACTICE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Add 'set -o pipefail &&' to RUN.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD041 — COPY to relative destination without WORKDIR
# ---------------------------------------------------------------------------
@rule
def dd041_copy_relative_dest(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        has_workdir = False
        for instr in stage.instructions:
            if instr.directive == "WORKDIR":
                has_workdir = True
            elif instr.directive in ("COPY", "ADD") and not has_workdir:
                args = instr.arguments.strip()
                parts = [p for p in args.split() if not p.startswith("--")]
                if len(parts) >= 2:
                    dest = parts[-1]
                    if not dest.startswith("/") and not dest.startswith("$"):
                        issues.append(Issue(
                            rule_id="DD041",
                            title="COPY/ADD to relative path without WORKDIR",
                            description=f"Destination '{dest}' is relative but no "
                                        "WORKDIR has been set. Use an absolute path "
                                        "or set WORKDIR first.",
                            severity=Severity.WARNING,
                            category=Category.MAINTAINABILITY,
                            line_number=instr.line_number,
                            fix_available=True,
                            fix_description="Prepend '/' to make destination absolute.",
                        ))
    return issues


# ---------------------------------------------------------------------------
# DD042 — ONBUILD instruction
# ---------------------------------------------------------------------------
@rule
def dd042_onbuild(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "ONBUILD"):
        issues.append(Issue(
            rule_id="DD042",
            title="ONBUILD instruction found",
            description="ONBUILD triggers can lead to surprising behavior "
                        "in downstream images. Avoid unless building base images.",
            severity=Severity.INFO,
            category=Category.MAINTAINABILITY,
            line_number=instr.line_number,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD043 — SHELL should use JSON/exec form
# ---------------------------------------------------------------------------
@rule
def dd043_shell_exec_form(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "SHELL"):
        args = instr.arguments.strip()
        if not args.startswith("["):
            issues.append(Issue(
                rule_id="DD043",
                title="SHELL instruction not in exec form",
                description="SHELL must use JSON array form, e.g. "
                            'SHELL ["/bin/bash", "-c"].',
                severity=Severity.ERROR,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Convert SHELL to JSON exec form.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD044 — Duplicate ENV keys
# ---------------------------------------------------------------------------
@rule
def dd044_duplicate_env(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        seen_keys: dict[str, int] = {}
        for instr in stage.instructions:
            if instr.directive != "ENV":
                continue
            args = instr.arguments.strip()
            # Parse ENV KEY=VALUE or ENV KEY VALUE
            if "=" in args:
                for part in re.findall(r"(\w+)=", args):
                    key = part.upper()
                    if key in seen_keys:
                        issues.append(Issue(
                            rule_id="DD044",
                            title=f"Duplicate ENV key '{part}'",
                            description=f"ENV key '{part}' was already set at line "
                                        f"{seen_keys[key]}. This overwrites the "
                                        "previous value.",
                            severity=Severity.INFO,
                            category=Category.MAINTAINABILITY,
                            line_number=instr.line_number,
                            fix_available=True,
                            fix_description="Remove duplicate ENV instruction.",
                        ))
                    seen_keys[key] = instr.line_number
            else:
                key = args.split()[0].upper() if args.split() else ""
                if key:
                    if key in seen_keys:
                        issues.append(Issue(
                            rule_id="DD044",
                            title=f"Duplicate ENV key '{args.split()[0]}'",
                            description=f"ENV key '{args.split()[0]}' was already set "
                                        f"at line {seen_keys[key]}.",
                            severity=Severity.INFO,
                            category=Category.MAINTAINABILITY,
                            line_number=instr.line_number,
                            fix_available=True,
                            fix_description="Remove duplicate ENV instruction.",
                        ))
                    seen_keys[key] = instr.line_number
    return issues


# ---------------------------------------------------------------------------
# DD045 — RUN with cd instead of WORKDIR
# ---------------------------------------------------------------------------
@rule
def dd045_run_cd(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments.strip()
        # Match "cd /path &&" at start of RUN
        if re.match(r"cd\s+\S+\s*(&&|;)", args):
            issues.append(Issue(
                rule_id="DD045",
                title="RUN with cd instead of WORKDIR",
                description="Use WORKDIR to change directories instead of "
                            "'RUN cd /path && ...'. WORKDIR persists across "
                            "instructions.",
                severity=Severity.INFO,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Convert to WORKDIR + RUN.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD046 — Missing LABEL
# ---------------------------------------------------------------------------
@rule
def dd046_missing_label(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    has_label = any(i.directive == "LABEL" for i in dockerfile.instructions)
    if not has_label and dockerfile.stages:
        issues.append(Issue(
            rule_id="DD046",
            title="No LABEL instructions",
            description="Consider adding LABEL instructions for metadata "
                        "(maintainer, version, description).",
            severity=Severity.INFO,
            category=Category.MAINTAINABILITY,
            line_number=0,
            fix_available=False,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD047 — Empty RUN instruction
# ---------------------------------------------------------------------------
@rule
def dd047_empty_run(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if not instr.arguments.strip():
            issues.append(Issue(
                rule_id="DD047",
                title="Empty RUN instruction",
                description="RUN instruction has no commands. Remove it.",
                severity=Severity.ERROR,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Remove empty RUN instruction.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD048 — Duplicate EXPOSE ports
# ---------------------------------------------------------------------------
@rule
def dd048_duplicate_expose(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    seen_ports: dict[str, int] = {}
    for instr in _instructions_by_directive(dockerfile, "EXPOSE"):
        for token in instr.arguments.split():
            port = token.split("/")[0]
            if port in seen_ports:
                issues.append(Issue(
                    rule_id="DD048",
                    title=f"Duplicate EXPOSE port {port}",
                    description=f"Port {port} is already exposed at line "
                                f"{seen_ports[port]}.",
                    severity=Severity.INFO,
                    category=Category.MAINTAINABILITY,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Remove duplicate EXPOSE.",
                ))
            else:
                seen_ports[port] = instr.line_number
    return issues


# ---------------------------------------------------------------------------
# DD049 — Multiple HEALTHCHECK instructions (per stage)
# ---------------------------------------------------------------------------
@rule
def dd049_multiple_healthcheck(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        hcs = [i for i in stage.instructions if i.directive == "HEALTHCHECK"]
        if len(hcs) > 1:
            for hc in hcs[:-1]:
                issues.append(Issue(
                    rule_id="DD049",
                    title="Multiple HEALTHCHECK instructions",
                    description="Only the last HEALTHCHECK takes effect. "
                                "Remove earlier HEALTHCHECK instructions.",
                    severity=Severity.WARNING,
                    category=Category.BEST_PRACTICE,
                    line_number=hc.line_number,
                    fix_available=True,
                    fix_description="Remove earlier HEALTHCHECK.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD050 — FROM ... AS with uppercase name
# ---------------------------------------------------------------------------
@rule
def dd050_stage_name_case(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        if stage.name and stage.name != stage.name.lower():
            issues.append(Issue(
                rule_id="DD050",
                title="Stage name should be lowercase",
                description=f"Stage name '{stage.name}' should be lowercase "
                            "for consistency with Docker conventions.",
                severity=Severity.INFO,
                category=Category.MAINTAINABILITY,
                line_number=stage.instructions[0].line_number if stage.instructions else 0,
                fix_available=True,
                fix_description=f"Change '{stage.name}' to '{stage.name.lower()}'.",
            ))
    return issues


# ===========================================================================
# DD051–DD060: Security rules
# ===========================================================================

# ---------------------------------------------------------------------------
# DD051 — chmod 777 in RUN
# ---------------------------------------------------------------------------
@rule
def dd051_chmod_777(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if re.search(r"\bchmod\s+777\b", instr.arguments):
            issues.append(Issue(
                rule_id="DD051",
                title="chmod 777 gives excessive permissions",
                description="chmod 777 grants read, write, and execute to everyone. "
                            "Use more restrictive permissions (e.g. 755, 644).",
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Change chmod 777 to chmod 755.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD052 — SSH keys or .git directory in COPY/ADD
# ---------------------------------------------------------------------------
_SSH_GIT_PATTERNS = re.compile(
    r"(\.ssh|id_rsa|id_ed25519|id_ecdsa|\.git)\b", re.IGNORECASE
)

@rule
def dd052_ssh_git_copy(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in dockerfile.instructions:
        if instr.directive not in ("COPY", "ADD"):
            continue
        if _SSH_GIT_PATTERNS.search(instr.arguments):
            issues.append(Issue(
                rule_id="DD052",
                title="SSH key or .git directory in COPY/ADD",
                description="Copying SSH keys or .git directories into the image "
                            "is a security risk. Use .dockerignore or multi-stage "
                            "builds to exclude them.",
                severity=Severity.ERROR,
                category=Category.SECURITY,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD053 — .env file in COPY/ADD
# ---------------------------------------------------------------------------
@rule
def dd053_env_file_copy(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in dockerfile.instructions:
        if instr.directive not in ("COPY", "ADD"):
            continue
        args = instr.arguments.strip()
        parts = [p for p in args.split() if not p.startswith("--")]
        sources = parts[:-1] if len(parts) >= 2 else []
        for src in sources:
            if src == ".env" or src.endswith("/.env"):
                issues.append(Issue(
                    rule_id="DD053",
                    title=".env file copied into image",
                    description="Copying .env files into images may expose "
                                "secrets. Use Docker build secrets or runtime "
                                "environment variables instead.",
                    severity=Severity.ERROR,
                    category=Category.SECURITY,
                    line_number=instr.line_number,
                ))
    return issues


# ---------------------------------------------------------------------------
# DD054 — curl | bash (piped install scripts)
# ---------------------------------------------------------------------------
@rule
def dd054_curl_pipe_bash(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", args):
            issues.append(Issue(
                rule_id="DD054",
                title="Piping remote script to shell",
                description="Piping a downloaded script directly to a shell "
                            "(curl | sh) is dangerous. Download, verify, then "
                            "execute in separate steps.",
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD055 — wget --no-check-certificate
# ---------------------------------------------------------------------------
@rule
def dd055_wget_no_check(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if "--no-check-certificate" in instr.arguments:
            issues.append(Issue(
                rule_id="DD055",
                title="wget with --no-check-certificate",
                description="Disabling certificate verification makes downloads "
                            "vulnerable to MITM attacks.",
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Remove --no-check-certificate from wget.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD056 — curl -k (insecure)
# ---------------------------------------------------------------------------
@rule
def dd056_curl_insecure(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\bcurl\b", args) and (re.search(r"\s-k\b", args) or "--insecure" in args):
            issues.append(Issue(
                rule_id="DD056",
                title="curl with -k/--insecure",
                description="Using curl with -k or --insecure disables SSL "
                            "certificate verification.",
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Remove -k/--insecure from curl.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD057 — git clone with embedded credentials
# ---------------------------------------------------------------------------
@rule
def dd057_git_credentials(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        # git clone https://user:pass@host or token@host
        if re.search(r"git\s+clone\s+https?://[^/]*:[^/]*@", args):
            issues.append(Issue(
                rule_id="DD057",
                title="git clone with embedded credentials",
                description="Credentials in git URLs are stored in the image "
                            "layer history. Use SSH keys or build secrets.",
                severity=Severity.ERROR,
                category=Category.SECURITY,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD058 — Hardcoded token/password in RUN
# ---------------------------------------------------------------------------
_RUN_SECRET_PATTERNS = re.compile(
    r"(--password[= ]\S+|--token[= ]\S+|-p\s+\S+password|"
    r"MYSQL_ROOT_PASSWORD=\S+|POSTGRES_PASSWORD=\S+)",
    re.IGNORECASE,
)

@rule
def dd058_hardcoded_run_secret(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if _RUN_SECRET_PATTERNS.search(instr.arguments):
            issues.append(Issue(
                rule_id="DD058",
                title="Hardcoded credentials in RUN",
                description="Passwords or tokens in RUN commands are stored "
                            "in the image layer history. Use build secrets "
                            "(--mount=type=secret) instead.",
                severity=Severity.ERROR,
                category=Category.SECURITY,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD059 — ADD from remote URL
# ---------------------------------------------------------------------------
@rule
def dd059_add_remote_url(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "ADD"):
        if re.search(r"https?://", instr.arguments):
            issues.append(Issue(
                rule_id="DD059",
                title="ADD with remote URL",
                description="Using ADD to fetch remote URLs is unreliable and "
                            "doesn't support authentication. Use RUN with "
                            "curl/wget instead for better control.",
                severity=Severity.INFO,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Replace ADD URL with RUN curl.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD060 — Using --privileged in RUN (Docker-in-Docker)
# ---------------------------------------------------------------------------
@rule
def dd060_run_privileged(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if "--privileged" in instr.arguments:
            issues.append(Issue(
                rule_id="DD060",
                title="--privileged flag in RUN",
                description="Using --privileged grants full host access. "
                            "This is rarely needed and is a security risk.",
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=instr.line_number,
            ))
    return issues


# ===========================================================================
# DD061–DD070: Performance rules
# ===========================================================================

# ---------------------------------------------------------------------------
# DD061 — gem install without --no-document
# ---------------------------------------------------------------------------
@rule
def dd061_gem_no_document(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if re.search(r"\bgem\s+install\b", args):
            if "--no-document" not in args and "--no-doc" not in args and "--no-ri" not in args:
                issues.append(Issue(
                    rule_id="DD061",
                    title="gem install without --no-document",
                    description="Use 'gem install --no-document' to skip installing "
                                "documentation and reduce image size.",
                    severity=Severity.INFO,
                    category=Category.PERFORMANCE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Add --no-document to gem install.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD062 — go build without CGO_ENABLED=0
# ---------------------------------------------------------------------------
@rule
def dd062_go_cgo(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    # Detect Go images
    is_go = any("golang" in _image_basename(s.base_image) for s in dockerfile.stages)
    if not is_go:
        return issues
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        if "go build" in instr.arguments:
            all_env = " ".join(i.arguments for i in _instructions_by_directive(dockerfile, "ENV"))
            if "CGO_ENABLED=0" not in instr.arguments and "CGO_ENABLED=0" not in all_env:
                issues.append(Issue(
                    rule_id="DD062",
                    title="go build without CGO_ENABLED=0",
                    description="Set CGO_ENABLED=0 for static binaries that work "
                                "in scratch/distroless images.",
                    severity=Severity.INFO,
                    category=Category.PERFORMANCE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Add CGO_ENABLED=0 before go build.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD063 — Missing --virtual for apk add dev dependencies
# ---------------------------------------------------------------------------
@rule
def dd063_apk_virtual(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    dev_packages = {"gcc", "g++", "make", "cmake", "build-base", "musl-dev",
                    "linux-headers", "python3-dev", "libffi-dev", "openssl-dev"}
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if not re.search(r"\bapk\s+add\b", args):
            continue
        if "--virtual" in args or ".build-deps" in args:
            continue
        tokens = set(args.split())
        if tokens & dev_packages:
            issues.append(Issue(
                rule_id="DD063",
                title="apk add dev packages without --virtual",
                description="Use 'apk add --virtual .build-deps' for build "
                            "dependencies so they can be removed after compilation.",
                severity=Severity.INFO,
                category=Category.PERFORMANCE,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD064 — Large number of layers (>20 instructions creating layers)
# ---------------------------------------------------------------------------
@rule
def dd064_too_many_layers(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    _LAYER_DIRECTIVES = {"RUN", "COPY", "ADD"}
    for stage in dockerfile.stages:
        layer_count = sum(1 for i in stage.instructions if i.directive in _LAYER_DIRECTIVES)
        if layer_count > 20:
            issues.append(Issue(
                rule_id="DD064",
                title=f"Too many layers ({layer_count})",
                description=f"Stage has {layer_count} layer-creating instructions. "
                            "Consider combining RUN instructions to reduce layers.",
                severity=Severity.INFO,
                category=Category.PERFORMANCE,
                line_number=stage.instructions[0].line_number if stage.instructions else 0,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD065 — Duplicate RUN commands
# ---------------------------------------------------------------------------
@rule
def dd065_duplicate_run(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        seen: dict[str, int] = {}
        for instr in stage.instructions:
            if instr.directive != "RUN":
                continue
            cmd = instr.arguments.strip()
            if cmd in seen:
                issues.append(Issue(
                    rule_id="DD065",
                    title="Duplicate RUN instruction",
                    description=f"This RUN command is identical to the one at line "
                                f"{seen[cmd]}.",
                    severity=Severity.WARNING,
                    category=Category.PERFORMANCE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Remove duplicate RUN instruction.",
                ))
            else:
                seen[cmd] = instr.line_number
    return issues


# ---------------------------------------------------------------------------
# DD066 — Multi-stage build without COPY --from
# ---------------------------------------------------------------------------
@rule
def dd066_multistage_no_copy_from(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    if not dockerfile.is_multistage:
        return issues
    has_copy_from = any(
        "--from=" in i.arguments
        for i in _instructions_by_directive(dockerfile, "COPY")
    )
    if not has_copy_from:
        issues.append(Issue(
            rule_id="DD066",
            title="Multi-stage build without COPY --from",
            description="Multi-stage build defined but no COPY --from is used. "
                        "Artifacts from earlier stages are not being copied.",
            severity=Severity.INFO,
            category=Category.PERFORMANCE,
            line_number=0,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD067 — Node.js without NODE_ENV=production
# ---------------------------------------------------------------------------
@rule
def dd067_node_env(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    is_node = any(_image_basename(s.base_image).split(":")[0] == "node" for s in dockerfile.stages)
    if not is_node:
        return issues
    all_env = " ".join(i.arguments for i in _instructions_by_directive(dockerfile, "ENV"))
    if "NODE_ENV" not in all_env:
        issues.append(Issue(
            rule_id="DD067",
            title="Missing NODE_ENV=production",
            description="Set 'ENV NODE_ENV=production' for Node.js images to "
                        "optimize runtime behavior and skip dev dependencies.",
            severity=Severity.INFO,
            category=Category.BEST_PRACTICE,
            line_number=0,
            fix_available=True,
            fix_description="Add ENV NODE_ENV=production after FROM.",
        ))
    return issues


# ---------------------------------------------------------------------------
# DD068 — Java without container-aware JVM flags
# ---------------------------------------------------------------------------
@rule
def dd068_java_container_flags(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    is_java = any(
        _image_basename(s.base_image) in ("openjdk", "java", "eclipse-temurin", "amazoncorretto")
        for s in dockerfile.stages
    )
    if not is_java:
        return issues
    all_text = " ".join(i.arguments for i in dockerfile.instructions)
    if "UseContainerSupport" not in all_text and "MaxRAMPercentage" not in all_text:
        issues.append(Issue(
            rule_id="DD068",
            title="Java without container-aware JVM flags",
            description="Consider setting -XX:+UseContainerSupport or "
                        "-XX:MaxRAMPercentage for proper container memory limits.",
            severity=Severity.INFO,
            category=Category.PERFORMANCE,
            line_number=0,
            fix_available=True,
        ))
    return issues


# ---------------------------------------------------------------------------
# DD069 — RUN with apt-get install and wildcard
# ---------------------------------------------------------------------------
@rule
def dd069_apt_wildcard(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        args = instr.arguments
        if "apt-get install" in args and "*" in args:
            issues.append(Issue(
                rule_id="DD069",
                title="apt-get install with wildcard",
                description="Using wildcards in apt-get install makes builds "
                            "non-reproducible. Pin specific packages.",
                severity=Severity.WARNING,
                category=Category.MAINTAINABILITY,
                line_number=instr.line_number,
            ))
    return issues


# ---------------------------------------------------------------------------
# DD070 — Missing .dockerignore hint
# ---------------------------------------------------------------------------
@rule
def dd070_dockerignore_hint(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in dockerfile.instructions:
        if instr.directive in ("COPY", "ADD"):
            parts = [p for p in instr.arguments.split() if not p.startswith("--")]
            if len(parts) >= 2 and parts[0] in (".", "./"):
                issues.append(Issue(
                    rule_id="DD070",
                    title="Copying entire build context",
                    description=f"'{instr.directive} . ...' copies the entire "
                                "build context. Ensure a .dockerignore file "
                                "excludes unnecessary files.",
                    severity=Severity.INFO,
                    category=Category.PERFORMANCE,
                    line_number=instr.line_number,
                ))
    return issues


# ===========================================================================
# DD071–DD080: Maintainability rules
# ===========================================================================

# ---------------------------------------------------------------------------
# DD071 — Inconsistent instruction casing
# ---------------------------------------------------------------------------
@rule
def dd071_instruction_casing(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for line_idx, raw_line in enumerate(dockerfile.lines, 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if not parts:
            continue
        word = parts[0]
        if word.upper() in _KNOWN_DIRECTIVES and word != word.upper():
            issues.append(Issue(
                rule_id="DD071",
                title="Instruction not uppercase",
                description=f"'{word}' should be '{word.upper()}' for consistency.",
                severity=Severity.INFO,
                category=Category.MAINTAINABILITY,
                line_number=line_idx,
                fix_available=True,
                fix_description=f"Change '{word}' to '{word.upper()}'.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD072 — TODO/FIXME comments in Dockerfile
# ---------------------------------------------------------------------------
@rule
def dd072_todo_fixme(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for line_idx, raw_line in enumerate(dockerfile.lines, 1):
        if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", raw_line, re.IGNORECASE):
            issues.append(Issue(
                rule_id="DD072",
                title="TODO/FIXME comment found",
                description="Resolve TODO/FIXME comments before shipping.",
                severity=Severity.INFO,
                category=Category.MAINTAINABILITY,
                line_number=line_idx,
                fix_available=True,
                fix_description="Remove TODO/FIXME comment line.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD073 — Missing final newline
# ---------------------------------------------------------------------------
@rule
def dd073_missing_final_newline(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    if dockerfile.raw_content and not dockerfile.raw_content.endswith("\n"):
        issues.append(Issue(
            rule_id="DD073",
            title="Missing final newline",
            description="File should end with a newline character.",
            severity=Severity.INFO,
            category=Category.MAINTAINABILITY,
            line_number=len(dockerfile.lines),
            fix_available=True,
            fix_description="Add a trailing newline.",
        ))
    return issues


# ---------------------------------------------------------------------------
# DD074 — Very long RUN instruction
# ---------------------------------------------------------------------------
@rule
def dd074_long_run(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "RUN"):
        # Check the raw original line (without continuations)
        for line_idx, raw_line in enumerate(dockerfile.lines):
            if line_idx + 1 == instr.line_number:
                if len(raw_line) > 200 and "\\" not in raw_line:
                    issues.append(Issue(
                        rule_id="DD074",
                        title="Very long RUN line (>200 chars)",
                        description="Break long RUN instructions into multiple "
                                    "lines using backslash continuations for "
                                    "readability.",
                        severity=Severity.INFO,
                        category=Category.MAINTAINABILITY,
                        line_number=instr.line_number,
                    ))
                break
    return issues


# ---------------------------------------------------------------------------
# DD075 — Trailing whitespace
# ---------------------------------------------------------------------------
@rule
def dd075_trailing_whitespace(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for line_idx, raw_line in enumerate(dockerfile.lines, 1):
        # Skip lines that use backslash continuation (trailing space before \ is valid)
        if raw_line.rstrip() != raw_line.rstrip("\n\r") and not raw_line.rstrip().endswith("\\"):
            # Only flag non-blank lines with trailing whitespace
            if raw_line.strip():
                issues.append(Issue(
                    rule_id="DD075",
                    title="Trailing whitespace",
                    description="Line has trailing whitespace.",
                    severity=Severity.INFO,
                    category=Category.MAINTAINABILITY,
                    line_number=line_idx,
                    fix_available=True,
                    fix_description="Remove trailing whitespace.",
                ))
    return issues


# ---------------------------------------------------------------------------
# DD076 — Empty continuation line
# ---------------------------------------------------------------------------
@rule
def dd076_empty_continuation(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for line_idx, raw_line in enumerate(dockerfile.lines, 1):
        if raw_line.rstrip() == "\\":
            issues.append(Issue(
                rule_id="DD076",
                title="Empty continuation line",
                description="A line containing only a backslash is confusing. "
                            "Either add content or remove the continuation.",
                severity=Severity.INFO,
                category=Category.MAINTAINABILITY,
                line_number=line_idx,
                fix_available=True,
                fix_description="Remove empty continuation line.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD077 — Using deprecated base image
# ---------------------------------------------------------------------------
_DEPRECATED_IMAGES = {
    "centos": "CentOS is EOL. Use AlmaLinux, Rocky Linux, or UBI.",
    "ubuntu:14.04": "Ubuntu 14.04 is EOL. Upgrade to a supported version.",
    "ubuntu:16.04": "Ubuntu 16.04 is EOL. Upgrade to a supported version.",
    "ubuntu:18.04": "Ubuntu 18.04 is EOL. Upgrade to a supported version.",
    "debian:jessie": "Debian Jessie is EOL. Use a newer release.",
    "debian:stretch": "Debian Stretch is EOL. Use a newer release.",
    "debian:buster": "Debian Buster is nearing EOL. Consider upgrading.",
    "python:2": "Python 2 is EOL. Upgrade to Python 3.",
    "python:2.7": "Python 2.7 is EOL. Upgrade to Python 3.",
    "node:8": "Node.js 8 is EOL. Upgrade to a supported version.",
    "node:10": "Node.js 10 is EOL. Upgrade to a supported version.",
    "node:12": "Node.js 12 is EOL. Upgrade to a supported version.",
    "node:14": "Node.js 14 is EOL. Upgrade to a supported version.",
    "node:16": "Node.js 16 is EOL. Upgrade to a supported version.",
}

@rule
def dd077_deprecated_image(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for stage in dockerfile.stages:
        basename = _image_basename(stage.base_image)
        tag = stage.base_tag or ""
        # Check full image:tag first, then basename alone
        full = f"{basename}:{tag}" if tag else basename
        msg = _DEPRECATED_IMAGES.get(full) or _DEPRECATED_IMAGES.get(basename)
        if msg:
            issues.append(Issue(
                rule_id="DD077",
                title="Deprecated or EOL base image",
                description=msg,
                severity=Severity.WARNING,
                category=Category.SECURITY,
                line_number=stage.instructions[0].line_number if stage.instructions else 0,
                fix_available=True,
                fix_description="Replace deprecated base image with supported alternative.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD078 — Missing LABEL version
# ---------------------------------------------------------------------------
@rule
def dd078_label_version(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    labels = _instructions_by_directive(dockerfile, "LABEL")
    if not labels or not dockerfile.stages:
        return issues
    all_label_text = " ".join(i.arguments for i in labels)
    if "version" not in all_label_text.lower():
        issues.append(Issue(
            rule_id="DD078",
            title="Missing version LABEL",
            description="Consider adding a 'version' LABEL for image metadata.",
            severity=Severity.INFO,
            category=Category.MAINTAINABILITY,
            line_number=0,
            fix_available=True,
            fix_description='Add LABEL version="1.0.0".',
        ))
    return issues


# ---------------------------------------------------------------------------
# DD079 — STOPSIGNAL with invalid signal
# ---------------------------------------------------------------------------
_VALID_SIGNALS = {
    "SIGABRT", "SIGALRM", "SIGBUS", "SIGCHLD", "SIGCONT", "SIGFPE",
    "SIGHUP", "SIGILL", "SIGINT", "SIGIO", "SIGIOT", "SIGKILL",
    "SIGPIPE", "SIGPOLL", "SIGPROF", "SIGPWR", "SIGQUIT", "SIGSEGV",
    "SIGSTKFLT", "SIGSTOP", "SIGSYS", "SIGTERM", "SIGTRAP", "SIGTSTP",
    "SIGTTIN", "SIGTTOU", "SIGURG", "SIGUSR1", "SIGUSR2", "SIGVTALRM",
    "SIGWINCH", "SIGXCPU", "SIGXFSZ",
}

@rule
def dd079_stopsignal_invalid(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "STOPSIGNAL"):
        sig = instr.arguments.strip().upper()
        # Accept numeric signals (1-31)
        if sig.isdigit():
            if int(sig) < 1 or int(sig) > 64:
                issues.append(Issue(
                    rule_id="DD079",
                    title=f"Invalid STOPSIGNAL: {sig}",
                    description=f"Signal number {sig} is out of range (1-64).",
                    severity=Severity.ERROR,
                    category=Category.BEST_PRACTICE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Replace invalid STOPSIGNAL with SIGTERM.",
                ))
            continue
        if sig not in _VALID_SIGNALS:
            issues.append(Issue(
                rule_id="DD079",
                title=f"Invalid STOPSIGNAL: {sig}",
                description=f"'{sig}' is not a recognized signal name.",
                severity=Severity.ERROR,
                category=Category.BEST_PRACTICE,
                line_number=instr.line_number,
                fix_available=True,
                fix_description="Replace invalid STOPSIGNAL with SIGTERM.",
            ))
    return issues


# ---------------------------------------------------------------------------
# DD080 — VOLUME with JSON syntax error
# ---------------------------------------------------------------------------
@rule
def dd080_volume_syntax(dockerfile: Dockerfile) -> list[Issue]:
    issues: list[Issue] = []
    for instr in _instructions_by_directive(dockerfile, "VOLUME"):
        args = instr.arguments.strip()
        if args.startswith("["):
            # Should be valid JSON array
            import json
            try:
                json.loads(args)
            except json.JSONDecodeError:
                issues.append(Issue(
                    rule_id="DD080",
                    title="VOLUME with invalid JSON syntax",
                    description="VOLUME uses JSON array syntax but contains "
                                "invalid JSON. Use proper JSON or space-separated form.",
                    severity=Severity.ERROR,
                    category=Category.BEST_PRACTICE,
                    line_number=instr.line_number,
                    fix_available=True,
                    fix_description="Convert VOLUME to proper JSON array syntax.",
                ))
    return issues
