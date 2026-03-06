#!/usr/bin/env python3
"""Generate a real demo HTML page showing dockerfile-doctor in action.

Runs the actual Python lint engine on sample Dockerfiles and renders
before/after results into a self-contained HTML file.

Usage:
    python demo/generate_demo.py          # writes demo/index.html
    python demo/generate_demo.py -o out.html
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

# Ensure the package is importable from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dockerfile_doctor.parser import parse  # noqa: E402
from dockerfile_doctor.rules import analyze  # noqa: E402
from dockerfile_doctor.fixer import fix  # noqa: E402


# ---------------------------------------------------------------------------
# Sample Dockerfiles
# ---------------------------------------------------------------------------

SAMPLES = {
    "Bad Dockerfile (13+ issues)": (Path(__file__).resolve().parent / "Dockerfile.bad").read_text(encoding="utf-8"),

    "Multi-stage (minor issues)": """\
FROM node:18 AS Builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:18-slim
WORKDIR /app
COPY --from=Builder /app/dist ./dist
COPY --from=Builder /app/node_modules ./node_modules
EXPOSE 3000
CMD node dist/server.js
""",

    "Clean Dockerfile (0 issues)": """\
FROM python:3.12-slim AS base
LABEL maintainer="team@example.com" description="Production API" version="1.0.0"
ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
USER nobody
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD ["curl", "-f", "http://localhost:8000/health"]
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
""",
}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_sample(name: str, content: str) -> dict:
    """Run the real engine and return structured results."""
    dockerfile = parse(content)
    issues = analyze(dockerfile)

    errors = sum(1 for i in issues if i.severity.value == "error")
    warnings = sum(1 for i in issues if i.severity.value == "warning")
    infos = sum(1 for i in issues if i.severity.value == "info")
    fixable = sum(1 for i in issues if i.fix_available)

    # Auto-fix
    fixed_content, applied_fixes = fix(dockerfile, issues)
    has_fixes = len(applied_fixes) > 0

    return {
        "name": name,
        "content": content,
        "issues": issues,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "fixable": fixable,
        "fixed_content": fixed_content if has_fixes else None,
        "fix_count": len(applied_fixes),
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

SEV_COLORS = {"error": "#f85149", "warning": "#d29922", "info": "#58a6ff"}


def render_issues_html(issues) -> str:
    if not issues:
        return '<div class="no-issues">No issues found.</div>'
    rows = []
    for i in issues:
        sev = i.severity.value
        color = SEV_COLORS.get(sev, "#8b949e")
        loc = "File" if i.line_number == 0 else f"Line {i.line_number}"
        fix_tag = ' <span class="fix-tag">(fixable)</span>' if i.fix_available else ""
        rows.append(
            f'<div class="issue">'
            f'<span class="loc">{loc:>8}</span> '
            f'<span class="sev" style="color:{color}">[{sev.upper():>7}]</span> '
            f'<span class="rid">{i.rule_id}</span> '
            f'{html.escape(i.title)}{fix_tag}'
            f'</div>'
        )
    return "\n".join(rows)


def render_code(content: str, cls: str = "") -> str:
    lines = content.rstrip("\n").split("\n")
    numbered = []
    for idx, line in enumerate(lines, 1):
        numbered.append(f'<span class="ln">{idx:>3}</span>  {html.escape(line)}')
    return f'<pre class="code {cls}">{"<br>".join(numbered)}</pre>'


def build_html(results: list[dict]) -> str:
    sections = []
    for r in results:
        summary_parts = []
        if r["errors"]:
            summary_parts.append(f'{r["errors"]} error{"s" if r["errors"] != 1 else ""}')
        if r["warnings"]:
            summary_parts.append(f'{r["warnings"]} warning{"s" if r["warnings"] != 1 else ""}')
        if r["infos"]:
            summary_parts.append(f'{r["infos"]} info')
        summary = ", ".join(summary_parts) or "clean"
        fix_note = f' | {r["fixable"]} auto-fixable' if r["fixable"] else ""

        fixed_section = ""
        if r["fixed_content"]:
            fixed_section = f"""
            <div class="subsection">
              <h3>After <code>--fix</code> ({r['fix_count']} fixes applied)</h3>
              {render_code(r['fixed_content'], 'fixed')}
            </div>"""

        sections.append(f"""
        <div class="sample">
          <h2>{html.escape(r['name'])}</h2>
          <div class="columns">
            <div class="col">
              <h3>Input Dockerfile</h3>
              {render_code(r['content'])}
            </div>
            <div class="col">
              <h3>Issues ({summary}{fix_note})</h3>
              <div class="issues">{render_issues_html(r['issues'])}</div>
            </div>
          </div>
          {fixed_section}
        </div>""")

    total_rules = 80
    total_fixers = 50

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dockerfile Doctor - Live Demo</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --dim: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --mono: 'Cascadia Code','Fira Code','JetBrains Mono',Consolas,monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem; }}
  header {{ text-align: center; margin-bottom: 2.5rem; }}
  header h1 {{ font-size: 2rem; }} header h1 span {{ color: var(--accent); }}
  header p {{ color: var(--dim); margin: 0.5rem 0; }}
  .badges {{ display: flex; gap: 0.5rem; justify-content: center; margin-top: 0.75rem; }}
  .badge {{ padding: 0.2rem 0.7rem; border-radius: 1rem; font-size: 0.75rem; font-weight: 600;
            border: 1px solid var(--border); }}
  .b-rules {{ color: var(--accent); border-color: #1f3a5f; background: #0d2240; }}
  .b-fix {{ color: var(--green); border-color: #1a4028; background: #0d2818; }}
  .b-deps {{ color: #d29922; border-color: #3d2e00; background: #2a1f00; }}
  .sample {{ background: var(--surface); border: 1px solid var(--border);
             border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }}
  .sample h2 {{ font-size: 1.1rem; margin-bottom: 1rem; color: var(--accent); }}
  .sample h3 {{ font-size: 0.85rem; color: var(--dim); margin-bottom: 0.5rem; }}
  .columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
  @media (max-width: 768px) {{ .columns {{ grid-template-columns: 1fr; }} }}
  .subsection {{ margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }}
  pre.code {{ background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
              padding: 1rem; font-family: var(--mono); font-size: 0.8rem;
              line-height: 1.7; overflow-x: auto; white-space: pre-wrap; }}
  pre.code.fixed {{ border-color: #1a4028; }}
  .ln {{ color: #484f58; user-select: none; }}
  .issues {{ font-family: var(--mono); font-size: 0.8rem; line-height: 1.9; }}
  .issue {{ padding: 0.1rem 0; }}
  .loc {{ color: #484f58; display: inline-block; min-width: 8ch; }}
  .rid {{ color: var(--dim); }}
  .fix-tag {{ color: var(--green); font-size: 0.72rem; }}
  .no-issues {{ color: var(--green); font-weight: 600; padding: 1rem; }}
  .note {{ text-align: center; color: var(--dim); font-size: 0.85rem;
           margin: 2rem 0 1rem; padding: 1rem; border: 1px dashed var(--border); border-radius: 6px; }}
  .note code {{ background: var(--bg); padding: 0.15rem 0.4rem; border-radius: 3px; }}
  footer {{ text-align: center; padding: 2rem 0 1rem; color: #484f58; font-size: 0.8rem;
            border-top: 1px solid var(--border); margin-top: 2rem; }}
  footer a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Dockerfile <span>Doctor</span></h1>
    <p>Lint, analyze, and auto-fix Dockerfiles. Pure Python, zero dependencies.</p>
    <div class="badges">
      <span class="badge b-rules">{total_rules} Rules</span>
      <span class="badge b-fix">{total_fixers} Auto-fixable</span>
      <span class="badge b-deps">Zero Dependencies</span>
    </div>
  </header>

  <div class="note">
    This demo was generated by the <strong>real</strong> dockerfile-doctor engine.<br>
    Install locally: <code>pip install dockerfile-doctor</code>
  </div>

  {"".join(sections)}
</div>
<footer>
  <a href="https://github.com/crabsatellite/dockerfile-doctor">GitHub</a> &middot;
  <code>pip install dockerfile-doctor</code> &middot; Apache 2.0
</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate dockerfile-doctor demo page")
    parser.add_argument("-o", "--output", default=str(Path(__file__).resolve().parent / "index.html"))
    args = parser.parse_args()

    results = [analyze_sample(name, content) for name, content in SAMPLES.items()]

    html_content = build_html(results)
    Path(args.output).write_text(html_content, encoding="utf-8")
    print(f"Demo written to {args.output}")
    print(f"  Samples: {len(results)}")
    for r in results:
        print(f"    {r['name']}: {len(r['issues'])} issues, {r['fix_count']} fixes")


if __name__ == "__main__":
    main()
