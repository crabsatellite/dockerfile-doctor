#!/usr/bin/env python3
"""Check status of tracked PRs and update pr_tracker.json."""

import json
import subprocess
import sys
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent / "pr_tracker.json"


def gh_pr_state(repo: str, pr_number: int) -> dict:
    """Query GitHub for PR state."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "state,mergedAt"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {"state": "UNKNOWN", "mergedAt": None}


def main():
    if not TRACKER.exists():
        print("No pr_tracker.json found")
        sys.exit(1)

    data = json.loads(TRACKER.read_text(encoding="utf-8"))
    prs = data["prs"]
    threshold = data.get("display_threshold", 5)

    print("Checking PR statuses...\n")

    merged = open_count = closed = 0

    for pr in prs:
        info = gh_pr_state(pr["repo"], pr["pr_number"])
        state = info.get("state", "UNKNOWN")
        merged_at = info.get("mergedAt")

        if state == "MERGED":
            print(f"  [MERGED] {pr['repo']} #{pr['pr_number']}")
            pr["status"] = "merged"
            pr["merged"] = merged_at[:10] if merged_at else None
            merged += 1
        elif state == "OPEN":
            print(f"  [OPEN]   {pr['repo']} #{pr['pr_number']}")
            pr["status"] = "open"
            open_count += 1
        elif state == "CLOSED":
            print(f"  [CLOSED] {pr['repo']} #{pr['pr_number']}")
            pr["status"] = "closed"
            closed += 1
        else:
            print(f"  [?]      {pr['repo']} #{pr['pr_number']} ({state})")

    # Write back
    TRACKER.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    total = len(prs)
    print(f"\nSummary: {merged} merged, {open_count} open, {closed} closed (total: {total})")

    if merged >= threshold:
        print(f"\n*** {merged} merged PRs >= threshold ({threshold}) — ready to showcase! ***")


if __name__ == "__main__":
    main()
