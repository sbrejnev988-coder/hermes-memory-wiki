"""Full Windows recovery fence: old hardlink, same bytes, new physical ID.

Use the real provider/journal/rebuild boundary on an erased synthetic SQLite
store, not an in-memory reference replay that can borrow existing ID history.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _load_module(name):
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _close(provider):
    if provider._conn is not None:
        provider._conn.close()
        provider._conn = None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows physical-file alias ownership fence")
@pytest.mark.parametrize("recovery_mode", ["journal_only", "pre_index_checkpoint"])
def test_byte_identical_identity_full_rebuild(tmp_path, monkeypatch, recovery_mode):
    home = tmp_path / "fixture-home"
    documents = home / "documents"
    scan_root = documents / "current"
    scan_root.mkdir(parents=True)
    for key, value in {
        "HERMES_HOME": str(home),
        "HERMES_SECURITY_STRICT": "0",
        "MEMORY_WIKI_SEMANTIC": "0",
        "MEMORY_WIKI_BACKGROUND_JOBS_ENABLED": "0",
        "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
        "MEMORY_WIKI_DOCUMENT_ROOTS": str(documents),
        "MEMORY_WIKI_DOCUMENT_CACHE_DIR": str(documents),
        "MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS": "0",
    }.items():
        monkeypatch.setenv(key, value)
    module = _load_module("memory_wiki_full_identity_" + recovery_mode)
    graph = importlib.import_module(module.__name__ + ".document_knowledge_graph")
    provider = module.MemoryWikiProvider()
    provider.initialize("identity-recovery-owner", hermes_home=str(home),
                        bot_id="fixture-owner", project_id="owner-recovery")
    restored = None
    try:
        assert provider._connect().execute("SELECT COUNT(*) FROM document_sources").fetchone()[0] == 0
        checkpoint = None
        if recovery_mode == "pre_index_checkpoint":
            checkpoint = provider._journal_checkpoint("before-first-document-index")
            payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
            assert payload["tables"]["document_sources"] == []
            assert not any(row["key"].startswith("file_identities:")
                           for row in payload["tables"]["document_graph_meta"])
        else:
            assert provider._latest_journal_checkpoint() is None

        source = scan_root / "owned.md"
        content = b"# Synthetic ownership recovery\n\nSame bytes, different physical file.\n"
        source.write_bytes(content)
        old_alias = documents / "old-hardlink.md"
        os.link(source, old_alias)
        old_info = source.stat()
        old_identity = (old_info.st_dev, old_info.st_ino)
        live = json.loads(provider.handle_tool_call("memory_wiki_document_ingest", {
            "path": str(source), "embed": False,
        }))
        assert live["success"] is True and live["status"] == "indexed", live
        source_id = live["source_id"]

        source.unlink()
        source.write_bytes(content)
        new_info = source.stat()
        new_identity = (new_info.st_dev, new_info.st_ino)
        assert old_identity != new_identity
        assert old_alias.read_bytes() == source.read_bytes() == content
        scanned = json.loads(provider.handle_tool_call("memory_wiki_document_scan", {
            "root": str(scan_root), "recursive": False, "embed": False,
        }))
        assert scanned["success"] is True and scanned["unchanged"] == 1, scanned
        identities = {old_identity, new_identity}
        assert graph._file_identity_history(provider._connect(), source_id) == identities
        journal_bytes = provider.journal_path.read_bytes()
        db_path = provider.db_path
        _close(provider)
        # Crash-loss simulation is limited to this tmp_path store. Preserve
        # journal, pre-index checkpoint, signer and erasure ledger artifacts.
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        assert not db_path.exists()

        restored = module.MemoryWikiProvider()
        restored.initialize("identity-recovery-owner", hermes_home=str(home),
                            bot_id="fixture-owner", project_id="owner-recovery")
        conn = restored._connect()
        assert conn.execute("SELECT COUNT(*) FROM document_sources").fetchone()[0] == 0
        assert not graph._file_identity_history(conn, source_id)
        assert conn.execute("SELECT COUNT(*) FROM document_graph_meta WHERE key LIKE 'file_identity_owner:%'").fetchone()[0] == 0
        assert restored.journal_path.read_bytes() == journal_bytes
        cp_path = checkpoint["path"] if checkpoint else ""
        plan = restored._rebuild_from_journal(apply=False, checkpoint=cp_path)
        assert plan["events_to_replay"] == 2, plan
        assert plan["unrecoverable_events"] == plan["incomplete_events"] == 0, plan
        assert plan["checkpoint"] == cp_path
        if checkpoint:
            assert plan["checkpoint_seq"] == checkpoint["journal_seq"]
        else:
            assert plan["checkpoint_seq"] == 0
        rebuilt = restored._rebuild_from_journal(apply=True, checkpoint=cp_path)
        assert rebuilt["failed"] == 0 and rebuilt["replayed"] == 2, rebuilt
        conn = restored._connect()
        assert graph._file_identity_history(conn, source_id) == identities
        for dev, ino in identities:
            row = conn.execute("SELECT value FROM document_graph_meta WHERE key=?",
                               (f"file_identity_owner:{dev}:{ino}",)).fetchone()
            assert row is not None and row[0] == source_id
        row = conn.execute("SELECT scope_id,repository_id,active FROM document_sources WHERE source_id=?",
                           (source_id,)).fetchone()
        assert tuple(row) == ("owner-recovery", "owner-recovery", 1)
        assert conn.execute("SELECT COUNT(*) FROM document_units WHERE source_id=? AND active=1",
                            (source_id,)).fetchone()[0] > 0
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"

        # Another project must fail before even snapshotting the retained old
        # physical file, although the indexed path now has a new file ID.
        restored.project_scope = "foreign-recovery"
        snapshots = []
        real_snapshot = graph._snapshot_allowed_file
        def observed_snapshot(*args, **kwargs):
            snapshots.append(True)
            return real_snapshot(*args, **kwargs)
        monkeypatch.setattr(graph, "_snapshot_allowed_file", observed_snapshot)
        with pytest.raises(PermissionError, match="identity|owner|scope"):
            graph.ingest_document(restored, {"path": str(old_alias), "embed": False})
        assert snapshots == []
    finally:
        _close(provider)
        if restored is not None:
            _close(restored)
