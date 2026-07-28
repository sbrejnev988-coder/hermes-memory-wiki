import hashlib
import importlib.util
import os
from pathlib import Path


def load_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("memory_wiki_fixed", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(None)
    return provider


def code_args(repo, text, *, symbol="sym_shared", revision="rev1", content="body"):
    return {
        "claim": text,
        "topic": "shared-code-topic",
        "repository_id": repo,
        "file_path": "src/shared.py",
        "symbol_id": symbol,
        "symbol_revision": revision,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "claim_type": "code_claim",
        "confidence": 0.9,
        "salience": 0.9,
    }


def test_temporal_supersession_cannot_archive_another_repository(tmp_path, monkeypatch):
    p = load_provider(tmp_path, monkeypatch)
    b = p._code_claim_add(code_args("repo-B", "Service uses port 1234"))
    p._code_claim_add(code_args("repo-A", "Service now uses port 5678", revision="rev2", content="new"))
    row = p._connect().execute("SELECT status FROM claims WHERE id=?", (b["id"],)).fetchone()
    assert row["status"] == "active"


def test_temporal_supersession_still_works_inside_same_symbol(tmp_path, monkeypatch):
    p = load_provider(tmp_path, monkeypatch)
    old = p._code_claim_add(code_args("repo-A", "Service uses port 1234"))
    p._code_claim_add(code_args("repo-A", "Service now uses port 5678", revision="rev2", content="new"))
    row = p._connect().execute("SELECT status FROM claims WHERE id=?", (old["id"],)).fetchone()
    assert row["status"] == "archived"


def test_symbol_history_keeps_archived_revisions(tmp_path, monkeypatch):
    p = load_provider(tmp_path, monkeypatch)
    old = p._code_claim_add(code_args("repo-A", "Service uses port 1234"))
    p._code_claim_add(code_args("repo-A", "Service now uses port 5678", revision="rev2", content="new"))
    history = p._symbol_history({"repository_id": "repo-A", "symbol_id": "sym_shared"})["history"]
    assert old["id"] in {row["id"] for row in history}
    assert {row["status"] for row in history} >= {"active", "archived"}


def test_patch_outcome_identity_is_repository_scoped(tmp_path, monkeypatch):
    p = load_provider(tmp_path, monkeypatch)
    common = {"patch_id": "patch-1", "outcome": "applied", "changed_files": ["src/a.py"]}
    a = p._patch_outcome_add({**common, "repository_id": "repo-A"})
    b = p._patch_outcome_add({**common, "repository_id": "repo-B"})
    assert a["id"] != b["id"]
