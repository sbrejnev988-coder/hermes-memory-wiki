"""Drive connector HTTP is mocked; no live account or credential is used."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
FILE_ID = "file_abcdefgh123456"


def _module():
    name = "memory_wiki_drive_connector_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _isolate(monkeypatch, home):
    cache = home / "cache" / "documents"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", str(cache))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ROOTS", str(cache))
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID", raising=False)
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)


def _call(provider, **args):
    return json.loads(provider.handle_tool_call("memory_wiki_source_drive_sync", args))


class _Response:
    def __init__(self, body):
        self.status = 200
        self.headers = {}
        self.stream = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stream.close()

    def read(self, n=-1):
        return self.stream.read(n)


def test_drive_blob_fetch_checksum_and_incremental_metadata(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    module = _module()
    adapter = sys.modules[module._sync_google_drive_source.__module__]
    provider = module.MemoryWikiProvider()
    provider.initialize("drive-test", hermes_home=str(tmp_path), bot_id="drive-test",
                        project_id="project-a", agent_context="test")
    body = b"Drive connector text.\n"
    metadata = json.dumps({"id": FILE_ID, "name": "note.txt", "mimeType": "text/plain",
                           "size": str(len(body)), "md5Checksum": hashlib.md5(body).hexdigest(),
                           "version": "123", "trashed": False,
                           "capabilities": {"canDownload": True}}).encode("utf-8")
    seen = []

    def fake_open(request, timeout):
        seen.append((request.full_url, dict(request.header_items())))
        return _Response(body if "alt=media" in request.full_url else metadata)

    monkeypatch.setattr(adapter, "_open", fake_open)
    try:
        assert _call(provider, file_id=FILE_ID).get("error") == "drive_access_token_required"
        assert seen == []
        monkeypatch.setenv("MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN", "mock-oauth-token")
        first = _call(provider, file_id=FILE_ID)
        assert first.get("success") is True, first
        assert first["source_type"] == "google_drive"
        assert len(seen) == 3  # metadata, content, revision check
        assert all(dict((k.lower(), v) for k, v in headers.items())["authorization"]
                   == "Bearer mock-oauth-token" for _, headers in seen)
        second = _call(provider, file_id=FILE_ID)
        assert second["status"] == "unchanged"
        assert second["source_key"] == first["source_key"]
        assert len(seen) == 4  # metadata only on the unchanged revision
        assert "mock-oauth-token" not in provider.journal_path.read_text(encoding="utf-8")
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_drive_connector_refuses_foreign_profile_token(tmp_path, monkeypatch):
    home = tmp_path / "default"
    _isolate(monkeypatch, home)
    module = _module()
    adapter = sys.modules[module._sync_google_drive_source.__module__]
    provider = module.MemoryWikiProvider()
    provider.initialize("drive-test", hermes_home=str(home), bot_id="drive-test",
                        project_id="project-a", agent_context="test")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "learning"))
    monkeypatch.setenv("MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN", "synthetic-foreign-token")
    calls = []
    monkeypatch.setattr(adapter, "_open", lambda *_args: calls.append("network"))
    try:
        assert _call(provider, file_id=FILE_ID).get("error") == "drive_access_token_required"
        assert calls == []
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_drive_refuses_bad_checksum_before_provenance(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN", "mock-oauth-token")
    module = _module()
    adapter = sys.modules[module._sync_google_drive_source.__module__]
    provider = module.MemoryWikiProvider()
    provider.initialize("drive-test", hermes_home=str(tmp_path), bot_id="drive-test",
                        project_id="project-a", agent_context="test")
    body = b"changed body"
    metadata = json.dumps({"id": FILE_ID, "name": "note.txt", "mimeType": "text/plain",
                           "size": str(len(body)), "md5Checksum": "0" * 32,
                           "version": "123", "trashed": False,
                           "capabilities": {"canDownload": True}}).encode("utf-8")

    def fake_open(request, timeout):
        return _Response(body if "alt=media" in request.full_url else metadata)

    monkeypatch.setattr(adapter, "_open", fake_open)
    try:
        result = _call(provider, file_id=FILE_ID)
        assert result.get("error") == "drive_checksum_mismatch"
        assert provider._connect().execute("SELECT COUNT(*) FROM external_sources").fetchone()[0] == 0
    finally:
        if provider._conn is not None:
            provider._conn.close()
