"""Startup indexes and diagnostic reads must not rewrite normal memory state."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    name = "memory_wiki_startup_diagnostics_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("test-session", hermes_home=str(tmp_path), agent_context="test")
    return provider


def test_warm_initialize_keeps_fts_and_memory_revision(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        cid = provider._add_claim(
            "The synthetic calibration project uses a durable local index.",
            topic="calibration", source="test:startup", confidence=0.9,
        )
        conn = provider._connect()
        before = provider._meta_int("memory_revision")
        indexed = int(conn.execute("SELECT count(*) FROM claims_fts").fetchone()[0])
        assert indexed > 0
        rebuild = provider._rebuild_fts
        def unexpected_rebuild():
            raise AssertionError("warm initialization rebuilt an already current FTS index")
        monkeypatch.setattr(provider, "_rebuild_fts", unexpected_rebuild)
        provider.initialize("test-session", hermes_home=str(tmp_path), agent_context="test")
        assert provider._meta_int("memory_revision") == before
        assert provider._ensure_fts_current() == "current"
        assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (cid,)).fetchone()

        # Periodic hook maintenance should keep using the maintained index.
        render_all = provider._render_all
        monkeypatch.setattr(provider, "_detect_all_contradictions", unexpected_rebuild)
        monkeypatch.setattr(provider, "_render_all", unexpected_rebuild)
        assert provider._maintenance(full=False)["fts"] == "current"

        # A count mismatch still repairs the index at the next startup.
        monkeypatch.setattr(provider, "_rebuild_fts", rebuild)
        monkeypatch.setattr(provider, "_render_all", render_all)
        with conn:
            conn.execute("DELETE FROM claims_fts WHERE id=?", (cid,))
        provider.initialize("test-session", hermes_home=str(tmp_path), agent_context="test")
        assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (cid,)).fetchone()
    finally:
        provider.shutdown()


def test_fts_content_update_with_same_active_count_survives_restart(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        cid = provider._add_claim(
            "The synthetic calibration project uses obsoletephenomenon for a durable local index.",
            topic="calibration", source="test:fts-update", confidence=0.9,
        )
        conn = provider._connect()
        with conn:
            conn.execute(
                "UPDATE claims SET claim=?, normalized_claim=? WHERE id=?",
                ("The synthetic calibration project uses novelphenomenon for a durable local index.",
                 "The synthetic calibration project uses novelphenomenon for a durable local index.", cid),
            )
        assert conn.execute("SELECT count(*) FROM claims WHERE status='active'").fetchone()[0] == 1
        assert conn.execute(
            "SELECT id FROM claims_fts WHERE claims_fts MATCH 'novelphenomenon'"
        ).fetchone()[0] == cid
        assert not conn.execute(
            "SELECT id FROM claims_fts WHERE claims_fts MATCH 'obsoletephenomenon'"
        ).fetchone()

        def unexpected_rebuild():
            raise AssertionError("warm restart should use the synchronized FTS index")
        monkeypatch.setattr(provider, "_rebuild_fts", unexpected_rebuild)
        provider.initialize("test-session", hermes_home=str(tmp_path), agent_context="test")
        assert conn.execute(
            "SELECT id FROM claims_fts WHERE claims_fts MATCH 'novelphenomenon'"
        ).fetchone()[0] == cid
        assert not conn.execute(
            "SELECT id FROM claims_fts WHERE claims_fts MATCH 'obsoletephenomenon'"
        ).fetchone()
    finally:
        provider.shutdown()


def test_fts_archive_and_delete_remove_entries(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        archived_id = provider._add_claim(
            "The synthetic calibration project uses asterismarchive for a durable local index.",
            topic="calibration", source="test:fts-archive", confidence=0.9,
        )
        deleted_id = provider._add_claim(
            "The synthetic calibration project uses asterismdelete for a durable local index.",
            topic="calibration", source="test:fts-delete", confidence=0.9,
        )
        conn = provider._connect()
        assert conn.execute(
            "SELECT count(*) FROM claims_fts WHERE id IN (?,?)", (archived_id, deleted_id)
        ).fetchone()[0] == 2
        with conn:
            conn.execute("UPDATE claims SET status='archived' WHERE id=?", (archived_id,))
            conn.execute("DELETE FROM claims WHERE id=?", (deleted_id,))
        assert not conn.execute(
            "SELECT id FROM claims_fts WHERE id IN (?,?)", (archived_id, deleted_id)
        ).fetchall()
        assert not conn.execute(
            "SELECT id FROM claims_fts WHERE claims_fts MATCH 'asterismarchive OR asterismdelete'"
        ).fetchall()
        provider.initialize("test-session", hermes_home=str(tmp_path), agent_context="test")
        assert not conn.execute(
            "SELECT id FROM claims_fts WHERE id IN (?,?)", (archived_id, deleted_id)
        ).fetchall()
    finally:
        provider.shutdown()


def test_retrieval_evaluation_does_not_count_as_recall(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        cid = provider._add_claim(
            "The synthetic calibration project uses a durable local index.",
            topic="calibration", source="test:evaluation", confidence=0.9,
        )
        conn = provider._connect()
        with conn:
            conn.execute("DELETE FROM retrieval_eval_cases")
            conn.execute(
                """INSERT INTO retrieval_eval_cases(
                       id,query,must_topics,must_not_topics,must_include,
                       must_not_include,created_at,updated_at)
                   VALUES('synthetic','calibration project','[]','[]','[]','[]',1,1)"""
            )
        before = conn.execute(
            "SELECT access_count,recall_count FROM claims WHERE id=?", (cid,)
        ).fetchone()
        events_before = int(conn.execute("SELECT count(*) FROM recall_events").fetchone()[0])
        consumer_before = conn.execute(
            "SELECT last_seen_revision FROM memory_consumers WHERE consumer_id=?",
            (provider._consumer_id,),
        ).fetchone()
        result = provider._evaluate_retrieval(5, 2500)
        assert result["cases"] == 1
        provider._health(5)
        after = conn.execute(
            "SELECT access_count,recall_count FROM claims WHERE id=?", (cid,)
        ).fetchone()
        assert tuple(after) == tuple(before)
        assert int(conn.execute("SELECT count(*) FROM recall_events").fetchone()[0]) == events_before
        consumer_after = conn.execute(
            "SELECT last_seen_revision FROM memory_consumers WHERE consumer_id=?",
            (provider._consumer_id,),
        ).fetchone()
        assert tuple(consumer_after) == tuple(consumer_before)
    finally:
        provider.shutdown()


def test_doctor_default_is_read_only(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        conn = provider._connect()
        provider.snapshots_dir.rmdir()
        meta_before = [tuple(row) for row in conn.execute(
            "SELECT key,value FROM meta ORDER BY key"
        ).fetchall()]
        files_before = sorted(str(path.relative_to(provider.root))
                              for path in provider.root.rglob("*") if path.is_file())
        changes_before = conn.total_changes
        checkpoint_modes = []
        monkeypatch.setattr(provider, "_checkpoint_wal", checkpoint_modes.append)

        result = provider._doctor(repair=False)

        assert result["write_probes_run"] is False
        assert not checkpoint_modes
        assert conn.total_changes == changes_before
        assert [tuple(row) for row in conn.execute(
            "SELECT key,value FROM meta ORDER BY key"
        ).fetchall()] == meta_before
        assert not provider.snapshots_dir.exists()
        assert sorted(str(path.relative_to(provider.root))
                      for path in provider.root.rglob("*") if path.is_file()) == files_before
        check_names = {check["name"] for check in result["checks"]}
        assert not {"sqlite_write_probe", "wal_checkpoint", "wal_checkpoint_full",
                    "filesystem_writable"} & check_names
    finally:
        provider.shutdown()


def test_doctor_repair_keeps_write_probes(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    try:
        modes = []
        monkeypatch.setattr(provider, "_checkpoint_wal", lambda mode: modes.append(mode) or "ok")
        monkeypatch.setattr(provider, "_repair", lambda *args, **kwargs: {"actions": []})
        result = provider._doctor(repair=True)
        check_names = {check["name"] for check in result["checks"]}
        assert result["write_probes_run"] is True
        assert {"sqlite_write_probe", "wal_checkpoint", "wal_checkpoint_full",
                "filesystem_writable"} <= check_names
        assert modes == ["PASSIVE", "FULL"]
    finally:
        provider.shutdown()
