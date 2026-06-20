#!/usr/bin/env python3
"""Collect public GitHub Dockerfiles into a local corpus.

This script performs read-only GitHub API requests. It does not open issues,
create branches, push commits, or submit pull requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


API_ROOT = "https://api.github.com"
DEFAULT_QUERY = "stars:>1000 archived:false fork:false is:public"
USER_AGENT = "dockerfile-doctor-corpus-collector"
DATASET_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def request_json(url: str, token: str | None, *, retry: int = 2) -> Any:
    for attempt in range(retry + 1):
        request = urllib.request.Request(url, headers=github_headers(token))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429} and attempt < retry:
                reset = exc.headers.get("X-RateLimit-Reset")
                if reset and reset.isdigit():
                    wait = max(1, min(60, int(reset) - int(time.time()) + 1))
                else:
                    wait = 5
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API failed {exc.code} for {url}: {body}") from exc


def request_bytes(url: str, token: str | None) -> bytes:
    request = urllib.request.Request(url, headers=github_headers(token, raw=True))
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def github_headers(token: str | None, *, raw: bool = False) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if not raw:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def api_url(path: str, **params: Any) -> str:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return f"{API_ROOT}{path}" + (f"?{query}" if query else "")


def is_dockerfile_path(path: str, *, include_containerfile: bool) -> bool:
    name = PurePosixPath(path).name.lower()
    if name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
        return True
    if include_containerfile and (name == "containerfile" or name.startswith("containerfile.")):
        return True
    return False


def raw_url(full_name: str, commit_sha: str, path: str) -> str:
    quoted = "/".join(urllib.parse.quote(part) for part in PurePosixPath(path).parts)
    return f"https://raw.githubusercontent.com/{full_name}/{commit_sha}/{quoted}"


def html_url(full_name: str, commit_sha: str, path: str) -> str:
    quoted = "/".join(urllib.parse.quote(part) for part in PurePosixPath(path).parts)
    return f"https://github.com/{full_name}/blob/{commit_sha}/{quoted}"


def local_file_path(out_dir: Path, full_name: str, source_path: str) -> Path:
    repo_dir = out_dir / "files" / full_name.replace("/", "__")
    return repo_dir.joinpath(*PurePosixPath(source_path).parts)


def search_repositories(
    token: str | None,
    queries: list[str],
    *,
    max_repos: int,
    per_page: int,
) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries:
        page = 1
        while len(repos) < max_repos:
            data = request_json(
                api_url(
                    "/search/repositories",
                    q=query,
                    sort="stars",
                    order="desc",
                    per_page=min(per_page, 100),
                    page=page,
                ),
                token,
            )
            items = data.get("items", [])
            if not items:
                break
            for repo in items:
                if repo.get("private") or repo.get("fork") or repo.get("archived"):
                    continue
                full_name = repo["full_name"]
                if full_name in seen:
                    continue
                seen.add(full_name)
                repo = dict(repo)
                repo["_dockerfile_doctor_query"] = query
                repos.append(repo)
                if len(repos) >= max_repos:
                    break
            page += 1
            if page > 10:
                break
    return repos


def collect_repo_files(
    repo: dict[str, Any],
    token: str | None,
    out_dir: Path,
    *,
    max_file_bytes: int,
    max_files_per_repo: int,
    include_containerfile: bool,
    query: str,
) -> list[dict[str, Any]]:
    full_name = repo["full_name"]
    default_branch = repo.get("default_branch") or "HEAD"
    commit = request_json(
        api_url(f"/repos/{full_name}/commits/{urllib.parse.quote(default_branch, safe='')}"),
        token,
    )
    commit_sha = commit["sha"]
    tree = request_json(
        api_url(f"/repos/{full_name}/git/trees/{urllib.parse.quote(default_branch, safe='')}", recursive=1),
        token,
    )

    entries: list[dict[str, Any]] = []
    for item in tree.get("tree", []):
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not is_dockerfile_path(path, include_containerfile=include_containerfile):
            continue
        size = item.get("size")
        if isinstance(size, int) and size > max_file_bytes:
            continue

        source_raw_url = raw_url(full_name, commit_sha, path)
        content = request_bytes(source_raw_url, token)
        if len(content) > max_file_bytes:
            continue

        local_path = local_file_path(out_dir, full_name, path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)

        content_sha256 = hashlib.sha256(content).hexdigest()
        license_info = repo.get("license") or {}
        entries.append({
            "dataset_version": DATASET_VERSION,
            "collected_at": utc_now(),
            "discovered_by_query": query,
            "repo_full_name": full_name,
            "repo_id": repo.get("id"),
            "repo_html_url": repo.get("html_url"),
            "repo_description": repo.get("description"),
            "repo_stars": repo.get("stargazers_count"),
            "repo_forks": repo.get("forks_count"),
            "repo_language": repo.get("language"),
            "repo_license_spdx": license_info.get("spdx_id"),
            "repo_default_branch": default_branch,
            "commit_sha": commit_sha,
            "source_path": path,
            "source_html_url": html_url(full_name, commit_sha, path),
            "source_raw_url": source_raw_url,
            "blob_sha": item.get("sha"),
            "blob_size": len(content),
            "content_sha256": content_sha256,
            "local_path": str(local_path.relative_to(out_dir)).replace("\\", "/"),
            "tree_truncated": bool(tree.get("truncated")),
        })
        if max_files_per_repo > 0 and len(entries) >= max_files_per_repo:
            break
    return entries


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="corpus/github_dockerfiles", help="Output corpus directory")
    parser.add_argument("--query", action="append", help="GitHub repository search query")
    parser.add_argument("--max-repos", type=int, default=25)
    parser.add_argument("--max-files", type=int, default=100)
    parser.add_argument(
        "--max-files-per-repo",
        type=int,
        default=20,
        help="Maximum Dockerfiles to collect from one repo; use 0 for no per-repo cap",
    )
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--max-file-bytes", type=int, default=256 * 1024)
    parser.add_argument("--include-containerfile", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    token = get_token()
    queries = args.query or [DEFAULT_QUERY]

    manifest_path = out_dir / "manifest.jsonl"
    metadata_path = out_dir / "metadata.json"
    manifest_entries: list[dict[str, Any]] = []

    repos = search_repositories(token, queries, max_repos=args.max_repos, per_page=args.per_page)
    for repo in repos:
        if len(manifest_entries) >= args.max_files:
            break
        query = repo.get("_dockerfile_doctor_query", queries[0])
        try:
            entries = collect_repo_files(
                repo,
                token,
                out_dir,
                max_file_bytes=args.max_file_bytes,
                max_files_per_repo=args.max_files_per_repo,
                include_containerfile=args.include_containerfile,
                query=query,
            )
        except Exception as exc:
            print(f"WARN: skipped {repo.get('full_name')}: {exc}", file=sys.stderr)
            continue
        for entry in entries:
            manifest_entries.append(entry)
            if len(manifest_entries) >= args.max_files:
                break

    with manifest_path.open("w", encoding="utf-8") as handle:
        for entry in manifest_entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    summary = {
        "dataset_version": DATASET_VERSION,
        "collected_at": utc_now(),
        "queries": queries,
        "max_files_per_repo": args.max_files_per_repo,
        "repos_scanned": len(repos),
        "files_collected": len(manifest_entries),
        "unique_repos_with_files": len({entry["repo_full_name"] for entry in manifest_entries}),
        "manifest": str(manifest_path.relative_to(out_dir)),
        "notes": [
            "Read-only GitHub API collection.",
            "This is a bounded corpus, not an exhaustive snapshot of all public GitHub Dockerfiles.",
            "Every file records repo, commit SHA, source path, immutable HTML URL, raw URL, and content hash.",
        ],
    }
    write_json(metadata_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
