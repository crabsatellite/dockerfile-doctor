"""Tests for corpus gate helper behavior."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_corpus_gate.py"
SPEC = importlib.util.spec_from_file_location("run_corpus_gate", SCRIPT)
assert SPEC and SPEC.loader
run_corpus_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_corpus_gate
SPEC.loader.exec_module(run_corpus_gate)


def test_prune_stale_fixed_files_keeps_current_outputs(tmp_path):
    corpus = tmp_path / "corpus"
    keep = corpus / "fixed" / "files" / "repo__keep" / "Dockerfile"
    stale = corpus / "fixed" / "files" / "repo__stale" / "Dockerfile"
    keep.parent.mkdir(parents=True)
    stale.parent.mkdir(parents=True)
    keep.write_text("FROM scratch\n", encoding="utf-8")
    stale.write_text("FROM scratch\n", encoding="utf-8")

    pruned = run_corpus_gate.prune_stale_fixed_files(
        corpus,
        {"files/repo__keep/Dockerfile"},
    )

    assert pruned == 1
    assert keep.exists()
    assert not stale.exists()


def test_fixed_relpath_normalizes_gate_output_path():
    assert run_corpus_gate.fixed_relpath("fixed/files/repo__app/Dockerfile") == (
        "files/repo__app/Dockerfile"
    )
    assert run_corpus_gate.fixed_relpath(None) is None
