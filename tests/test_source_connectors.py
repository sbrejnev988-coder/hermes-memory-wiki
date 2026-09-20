"""Connector records retain stable scoped identity across revisions and deletes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_source_connector_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, name, **arguments):
    return json.loads(provider.handle_tool_call(name, arguments))


def _provider(module, home, session, project):
    provider = module.MemoryWikiProvider()
    provider.initialize(session, hermes_home=str(home), bot_id=session,
                        project_id=project, agent_context="test")
    return provider


def _isolate_document_env(monkeypatch, home):
    cache = home / "cache" / "documents"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", str(cache))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ROOTS", str(cache))
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID", raising=False)
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE", "0")


def test_record_incremental_update_conflict_scope_and_delete(tmp_path, monkeypatch):
    _isolate_document_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    owner = _provider(module, tmp_path, "bot-a", "project-a")
    other = _provider(module, tmp_path, "bot-b", "project-b")
    uri = "https://example.test/records/42?token=do-not-store"
    try:
        assert _call(owner, "memory_wiki_source_record_upsert", source_uri=uri,
                     revision="rev-1", content="spoofed provenance",
                     source_type="github").get("error") == "unverified_source_type_denied"
        first = _call(owner, "memory_wiki_source_record_upsert", source_uri=uri,
                      revision="rev-1", content="copper lantern connector revision one",
                      title="Connector note")
        assert first.get("success") is True, first
        key = first["source_key"]
        assert key.startswith("ext_")
        source_id = first["source_id"]
        assert _call(owner, "memory_wiki_source_record_upsert", source_uri=uri,
                     revision="rev-1", content="copper lantern connector revision one",
                     title="Connector note")["status"] == "unchanged"
        assert _call(owner, "memory_wiki_source_record_upsert", source_uri=uri,
                     revision="rev-1", content="changed under same revision",
                     title="Connector note").get("error") == "source_revision_conflict"
        updated = _call(owner, "memory_wiki_source_record_upsert", source_uri=uri,
                        revision="rev-2", content="copper lantern connector revision two",
                        title="Connector note")
        assert updated.get("success") is True, updated
        assert updated["source_key"] == key and updated["source_id"] == source_id
        listed = _call(owner, "memory_wiki_source_list")["sources"]
        assert len(listed) == 1
        assert listed[0]["display_uri"] == "https://example.test/records/42"
        assert "do-not-store" not in json.dumps(listed)
        checkpoint = owner._journal_checkpoint("connector-test")
        table = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))["tables"]["external_sources"]
        assert table[0]["source_key"] == key and table[0]["document_source_id"] == source_id
        assert table[0]["content_hash"] == owner._connect().execute(
            "SELECT content_hash FROM external_sources WHERE source_key=?", (key,)
        ).fetchone()[0]
        assert _call(other, "memory_wiki_source_list")["sources"] == []
        journal = owner.journal_path.read_text(encoding="utf-8")
        assert "connector revision" not in journal and "do-not-store" not in journal
        assert _call(other, "memory_wiki_source_delete", source_key=key).get("error") == "connector_source_not_found"
        assert _call(owner, "memory_wiki_source_delete", source_key=key)["status"] == "deleted"
        assert owner._connect().execute("SELECT status FROM external_sources WHERE source_key=?", (key,)).fetchone()[0] == "deleted"
        assert owner._connect().execute("SELECT active FROM document_sources WHERE source_id=?", (source_id,)).fetchone()[0] == 0
    finally:
        for provider in (owner, other):
            if provider._conn is not None:
                provider._conn.close()


def test_local_file_sync_uses_allowlisted_snapshot_and_stable_key(tmp_path, monkeypatch):
    _isolate_document_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    owner = _provider(module, tmp_path, "local-owner", "project-a")
    cache = tmp_path / "cache" / "documents"
    cache.mkdir(parents=True)
    path = cache / "update.txt"
    path.write_text("Local connector source revision one.\n", encoding="utf-8")
    try:
        first = _call(owner, "memory_wiki_source_file_sync", path=str(path))
        assert first.get("success") is True, first
        second = _call(owner, "memory_wiki_source_file_sync", path=str(path))
        assert second["source_key"] == first["source_key"]
        path.write_text("Local connector source revision two.\n", encoding="utf-8")
        third = _call(owner, "memory_wiki_source_file_sync", path=str(path))
        assert third["source_key"] == first["source_key"]
        assert third["revision_id"] != first["revision_id"]
        assert _call(owner, "memory_wiki_source_delete", source_key=first["source_key"])["status"] == "deleted"
        assert path.exists()  # Connector deletion never deletes the user's file.
    finally:
        if owner._conn is not None:
            owner._conn.close()
