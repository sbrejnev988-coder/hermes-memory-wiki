#!/usr/bin/env python3
"""Lifecycle regressions for full and delta Code Shrinker snapshots."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
REPOSITORY_ID = "repo-snapshot-lifecycle"


def load_provider(module_name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "0")
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(module_name, hermes_home=str(tmp_path), agent_context="test")
    return module, provider


def snapshot(event_id: str, mode: str, files, *, deleted=()):
    return {
        "event_version": 2,
        "type": "code_graph_snapshot",
        "graph_schema_version": 1,
        "producer": "code-shrinker",
        "repository_id": REPOSITORY_ID,
        "event_id": event_id,
        "snapshot_mode": mode,
        "snapshot_hash": hashlib.sha256(event_id.encode()).hexdigest(),
        "commit_sha": hashlib.sha1(event_id.encode()).hexdigest(),
        "files": [
            {"file_path": path, "file_hash": file_hash, "language": "python", "line_count": 1}
            for path, file_hash in files
        ],
        "deleted_files": list(deleted),
    }


def add_code_claim(provider, file_path: str, content_hash: str) -> str:
    result = provider._code_claim_add({
        "claim": (
            f"Verified snapshot lifecycle for {file_path}: the indexed implementation, exact content "
            "hash, and repository recovery behavior were reviewed."
        ),
        "topic": "code-shrinker",
        "repository_id": REPOSITORY_ID,
        "file_path": file_path,
        "content_hash": content_hash,
        "evidence": "verified exact source revision and lifecycle behavior",
        "confidence": 0.95,
        "salience": 0.9,
    })
    assert result.get("id"), result
    return str(result["id"])


def claim_status(provider, claim_id: str) -> str:
    row = provider._connect().execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()
    assert row is not None
    return str(row[0])


def graph_paths(provider) -> set[str]:
    rows = provider._connect().execute(
        "SELECT file_path FROM code_graph_files WHERE repository_id=?", (REPOSITORY_ID,)
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_full_snapshot_archives_implicit_deletions_and_preserves_matching_canonical_hash(
    tmp_path, monkeypatch
) -> None:
    module, provider = load_provider("memory_wiki_full_snapshot_lifecycle_test", tmp_path, monkeypatch)
    keep_hash = hashlib.sha256(b"stable keep body").hexdigest()
    gone_hash = hashlib.sha256(b"removed body").hexdigest()
    try:
        module._ingest_code_graph_event(
            provider,
            snapshot("full-before", "full", [("src/keep.py", keep_hash), ("src/gone.py", gone_hash)]),
        )
        keep_claim = add_code_claim(provider, "src/keep.py", keep_hash)
        gone_claim = add_code_claim(provider, "src/gone.py", gone_hash)

        result = module._ingest_code_graph_event(
            provider,
            snapshot("full-after", "full", [(r".\src\keep.py", keep_hash)]),
        )

        assert result["invalidated_claims"] == 1, result
        assert claim_status(provider, keep_claim) == "active"
        assert claim_status(provider, gone_claim) == "archived"
        assert graph_paths(provider) == {"src/keep.py"}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_delta_omission_preserves_file_until_explicitly_deleted(tmp_path, monkeypatch) -> None:
    module, provider = load_provider("memory_wiki_delta_snapshot_lifecycle_test", tmp_path, monkeypatch)
    keep_hash = hashlib.sha256(b"delta keep body").hexdigest()
    gone_hash = hashlib.sha256(b"delta removed body").hexdigest()
    try:
        module._ingest_code_graph_event(
            provider,
            snapshot("delta-base", "full", [("src/keep.py", keep_hash), ("src/gone.py", gone_hash)]),
        )
        gone_claim = add_code_claim(provider, "src/gone.py", gone_hash)

        omitted = module._ingest_code_graph_event(
            provider,
            snapshot("delta-omits-gone", "delta", [(r".\src\keep.py", keep_hash)]),
        )
        assert omitted["invalidated_claims"] == 0, omitted
        assert claim_status(provider, gone_claim) == "active"
        assert graph_paths(provider) == {"src/keep.py", "src/gone.py"}

        deleted = module._ingest_code_graph_event(
            provider,
            snapshot("delta-deletes-gone", "delta", [], deleted=[r".\src\gone.py"]),
        )
        assert deleted["deleted_files"] == 1, deleted
        assert deleted["invalidated_claims"] == 1, deleted
        assert claim_status(provider, gone_claim) == "archived"
        assert graph_paths(provider) == {"src/keep.py"}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_full_snapshot_rejects_invalid_commit_before_replacing_graph_or_claims(
    tmp_path, monkeypatch
) -> None:
    module, provider = load_provider("memory_wiki_invalid_snapshot_commit_test", tmp_path, monkeypatch)
    keep_hash = hashlib.sha256(b"valid keep body").hexdigest()
    gone_hash = hashlib.sha256(b"valid gone body").hexdigest()
    try:
        module._ingest_code_graph_event(
            provider,
            snapshot("invalid-commit-before", "full", [("src/keep.py", keep_hash), ("src/gone.py", gone_hash)]),
        )
        keep_claim = add_code_claim(provider, "src/keep.py", keep_hash)
        gone_claim = add_code_claim(provider, "src/gone.py", gone_hash)
        malformed = snapshot("invalid-commit-after", "full", [("src/keep.py", keep_hash)])
        malformed["commit_sha"] = "not-a-git-sha"

        try:
            module._ingest_code_graph_event(provider, malformed)
        except ValueError as exc:
            assert "commit_sha" in str(exc)
        else:  # pragma: no cover - asserts the mutation boundary below
            raise AssertionError("malformed snapshot must fail before replacing graph rows")

        assert claim_status(provider, keep_claim) == "active"
        assert claim_status(provider, gone_claim) == "active"
        assert graph_paths(provider) == {"src/keep.py", "src/gone.py"}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_full_snapshot_rejects_malformed_rows_before_replacing_graph_or_claims(
    tmp_path, monkeypatch
) -> None:
    module, provider = load_provider("memory_wiki_malformed_snapshot_rows_test", tmp_path, monkeypatch)
    keep_hash = hashlib.sha256(b"malformed keep body").hexdigest()
    gone_hash = hashlib.sha256(b"malformed gone body").hexdigest()
    malformed_rows = (
        ("files-object", lambda event: event.__setitem__("files", {})),
        ("missing-file-path", lambda event: event.__setitem__("files", [{"line_count": 1}])),
        ("symbols-object", lambda event: event.__setitem__("symbols", {})),
        ("chunks-object", lambda event: event.__setitem__("chunks", {})),
        ("lines-object", lambda event: event.__setitem__("lines", {})),
        ("edges-object", lambda event: event.__setitem__("edges", {})),
        (
            "invalid-file-line-count",
            lambda event: event.__setitem__(
                "files", [{"file_path": "src/keep.py", "line_count": "not-an-int"}]
            ),
        ),
        (
            "invalid-symbol-line",
            lambda event: event.__setitem__(
                "symbols", [{"symbol_id": "keep", "file_path": "src/keep.py", "start_line": "bad"}]
            ),
        ),
        (
            "invalid-chunk-token-estimate",
            lambda event: event.__setitem__(
                "chunks", [{"chunk_id": "keep", "file_path": "src/keep.py", "token_estimate": "bad"}]
            ),
        ),
        (
            "invalid-line-number",
            lambda event: event.__setitem__(
                "lines", [{"file_path": "src/keep.py", "line_no": "bad"}]
            ),
        ),
        (
            "invalid-edge-source-line",
            lambda event: event.__setitem__(
                "edges", [{"source_id": "keep", "target_id": "gone", "source_line": "bad"}]
            ),
        ),
        (
            "invalid-edge-confidence",
            lambda event: event.__setitem__(
                "edges", [{"source_id": "keep", "target_id": "gone", "confidence": "not-a-float"}]
            ),
        ),
        ("invalid-generated-at", lambda event: event.__setitem__("generated_at", "not-an-int")),
    )
    try:
        module._ingest_code_graph_event(
            provider,
            snapshot("malformed-before", "full", [("src/keep.py", keep_hash), ("src/gone.py", gone_hash)]),
        )
        keep_claim = add_code_claim(provider, "src/keep.py", keep_hash)
        gone_claim = add_code_claim(provider, "src/gone.py", gone_hash)

        for event_id, corrupt in malformed_rows:
            malformed = snapshot(event_id, "full", [("src/keep.py", keep_hash)])
            corrupt(malformed)
            try:
                module._ingest_code_graph_event(provider, malformed)
            except ValueError:
                pass
            else:  # pragma: no cover - asserts the mutation boundary below
                raise AssertionError(f"{event_id} must fail before replacing graph rows")
            assert claim_status(provider, keep_claim) == "active"
            assert claim_status(provider, gone_claim) == "active"
            assert graph_paths(provider) == {"src/keep.py", "src/gone.py"}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None
