"""Tests for GitHub Dockerfile corpus collection helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "collect_github_dockerfiles.py"
SPEC = importlib.util.spec_from_file_location("collect_github_dockerfiles", SCRIPT)
assert SPEC and SPEC.loader
collect_github_dockerfiles = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collect_github_dockerfiles
SPEC.loader.exec_module(collect_github_dockerfiles)


def test_is_dockerfile_path_handles_common_names():
    assert collect_github_dockerfiles.is_dockerfile_path(
        "docker/api/Dockerfile",
        include_containerfile=False,
    )
    assert collect_github_dockerfiles.is_dockerfile_path(
        "build/Dockerfile.py3",
        include_containerfile=False,
    )
    assert collect_github_dockerfiles.is_dockerfile_path(
        "Containerfile",
        include_containerfile=True,
    )
    assert not collect_github_dockerfiles.is_dockerfile_path(
        "Containerfile",
        include_containerfile=False,
    )


def test_collect_repo_files_respects_per_repo_cap_and_query(monkeypatch, tmp_path):
    def fake_request_json(url, token):
        if "/commits/" in url:
            return {"sha": "abc123"}
        if "/git/trees/" in url:
            return {
                "tree": [
                    {"type": "blob", "path": "Dockerfile", "sha": "a", "size": 12},
                    {"type": "blob", "path": "docker/Dockerfile", "sha": "b", "size": 12},
                    {"type": "blob", "path": "test/Dockerfile", "sha": "c", "size": 12},
                ],
                "truncated": False,
            }
        raise AssertionError(url)

    monkeypatch.setattr(collect_github_dockerfiles, "request_json", fake_request_json)
    monkeypatch.setattr(
        collect_github_dockerfiles,
        "request_bytes",
        lambda url, token: b"FROM scratch\n",
    )
    repo = {
        "full_name": "example/project",
        "default_branch": "main",
        "id": 1,
        "html_url": "https://github.com/example/project",
        "license": {"spdx_id": "MIT"},
    }

    entries = collect_github_dockerfiles.collect_repo_files(
        repo,
        token=None,
        out_dir=tmp_path,
        max_file_bytes=1024,
        max_files_per_repo=2,
        include_containerfile=False,
        query="language:Dockerfile stars:>100",
    )

    assert len(entries) == 2
    assert {entry["discovered_by_query"] for entry in entries} == {
        "language:Dockerfile stars:>100"
    }
    assert all((tmp_path / entry["local_path"]).exists() for entry in entries)
