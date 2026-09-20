"""GitHub connector fetches are mocked: these tests never contact GitHub."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_github_connector_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(module, home, bot="test-bot"):
    provider = module.MemoryWikiProvider()
    provider.initialize(bot, hermes_home=str(home), bot_id=bot,
                        project_id="test-project", agent_context="test")
    return provider


def _isolate(monkeypatch, home):
    cache = home / "cache" / "documents"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", str(cache))
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ROOTS", str(cache))
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID", raising=False)
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def _call(provider, name, **arguments):
    return json.loads(provider.handle_tool_call(name, arguments))


class _Response:
    def __init__(self, status, payload=b"", headers=None):
        self.status = status
        self.headers = headers or {}
        self.stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stream.close()

    def read(self, n=-1):
        return self.stream.read(n)


def _body(path, text, *, bad_hash=False):
    raw = text.encode("utf-8")
    oid = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
    if bad_hash:
        oid = "0" * 40
    return json.dumps({"type": "file", "path": path, "size": len(raw),
                       "encoding": "base64", "sha": oid,
                       "content": base64.b64encode(raw).decode("ascii")}).encode("utf-8")


def test_github_public_incremental_etag_and_record_collision(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    module = _module()
    adapter = sys.modules[module._sync_github_source.__module__]
    provider = _provider(module, tmp_path)
    seen = []

    def fake_open(request, timeout):
        seen.append((request.full_url, dict(request.header_items()), timeout))
        if "If-none-match" not in dict(request.header_items()):
            return _Response(200, _body("docs/readme.md", "GitHub connector text.\n"),
                             {"ETag": '"v1"'})
        return _Response(304)

    monkeypatch.setattr(adapter, "_open", fake_open)
    try:
        first = _call(provider, "memory_wiki_source_github_sync", owner="example",
                      repo="wiki", path="docs/readme.md")
        assert first.get("success") is True, first
        assert first["source_type"] == "github_public"
        source_key = first["source_key"]
        assert seen[0][0] == "https://api.github.com/repos/example/wiki/contents/docs/readme.md"
        assert seen[0][2] <= 15
        row = provider._connect().execute(
            "SELECT source_type,etag FROM external_sources WHERE source_key=?", (source_key,)
        ).fetchone()
        assert tuple(row) == ("github_public", '"v1"')
        second = _call(provider, "memory_wiki_source_github_sync", owner="example",
                       repo="wiki", path="docs/readme.md")
        assert second["status"] == "unchanged"
        assert dict((k.lower(), v) for k, v in seen[1][1].items())["if-none-match"] == '"v1"'

        # A model-supplied record using the same URI cannot change the
        # verified GitHub row or its staged source.
        uri = "https://github.com/example/wiki/blob/HEAD/docs/readme.md"
        unverified = _call(provider, "memory_wiki_source_record_upsert",
                           source_uri=uri, revision="spoofed", content="spoofed text")
        assert unverified.get("success") is True, unverified
        assert unverified["source_key"] != source_key
        assert provider._connect().execute(
            "SELECT source_type FROM external_sources WHERE source_key=?", (source_key,)
        ).fetchone()[0] == "github_public"
        peer = _provider(module, tmp_path, "peer-bot")
        try:
            independent = _call(peer, "memory_wiki_source_github_sync",
                                owner="example", repo="wiki", path="docs/readme.md")
            assert independent.get("success") is True, independent
            assert independent["source_key"] != source_key
            peer_keys = {item["source_key"] for item in
                         _call(peer, "memory_wiki_source_list")["sources"]}
            assert peer_keys == {independent["source_key"]}
            status = _call(peer, "memory_wiki_document_status")
            assert first["source_id"] not in json.dumps(status)
            assert _call(peer, "memory_wiki_document_source",
                         source_id=first["source_id"]).get("error") == "connector_source_not_owned"
            query = _call(peer, "memory_wiki_document_query", query="GitHub connector",
                          source_id=first["source_id"])
            assert query.get("results") == []
            denied_delete = _call(peer, "memory_wiki_source_delete", source_key=source_key)
            assert denied_delete.get("error") == "connector_source_not_found"
            direct_delete = _call(peer, "memory_wiki_document_delete",
                                  source_id=first["source_id"])
            assert direct_delete.get("error") == "connector_source_not_owned"
            staged = tmp_path / "cache" / "documents" / "connectors" / f"{source_key}.txt"
            direct_ingest = _call(peer, "memory_wiki_document_ingest", path=str(staged))
            assert direct_ingest.get("error") == "connector_source_not_owned"
            assert provider._connect().execute(
                "SELECT status FROM external_sources WHERE source_key=?", (source_key,)
            ).fetchone()[0] == "active"
        finally:
            if peer._conn is not None:
                peer._conn.close()
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_github_rejects_untrusted_paths_hash_and_rate_limit(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    module = _module()
    adapter = sys.modules[module._sync_github_source.__module__]
    provider = _provider(module, tmp_path)
    calls = []

    def bad_hash(request, timeout):
        calls.append(request)
        return _Response(200, _body("note.txt", "source text", bad_hash=True))

    monkeypatch.setattr(adapter, "_open", bad_hash)
    try:
        denied = _call(provider, "memory_wiki_source_github_sync", owner="example",
                       repo="wiki", path="../secrets.txt")
        assert denied.get("error") == "invalid_github_text_path"
        assert calls == []
        mismatch = _call(provider, "memory_wiki_source_github_sync", owner="example",
                         repo="wiki", path="note.txt")
        assert mismatch.get("error") == "github_blob_hash_mismatch"
        assert _call(provider, "memory_wiki_source_list")["sources"] == []

        def limited(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 429, "rate limit",
                                         {"Retry-After": "120"}, None)

        monkeypatch.setattr(adapter, "_open", limited)
        limited_result = _call(provider, "memory_wiki_source_github_sync",
                               owner="example", repo="wiki", path="note.txt")
        assert limited_result.get("error", "").startswith("github_rate_limited")
        before = len(calls)
        again = _call(provider, "memory_wiki_source_github_sync",
                      owner="example", repo="wiki", path="note.txt")
        assert again.get("error", "").startswith("github_rate_limited")
        assert len(calls) == before
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_github_authenticated_provenance_only_after_verified_fetch(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-123")
    module = _module()
    adapter = sys.modules[module._sync_github_source.__module__]
    provider = _provider(module, tmp_path)
    seen = []

    def fake_open(request, timeout):
        seen.append(dict(request.header_items()))
        return _Response(200, _body("private.md", "Authenticated private text.\n"))

    monkeypatch.setattr(adapter, "_open", fake_open)
    try:
        result = _call(provider, "memory_wiki_source_github_sync", owner="example",
                       repo="private-wiki", path="private.md")
        assert result.get("success") is True, result
        assert result["source_type"] == "github_authenticated"
        assert dict((k.lower(), v) for k, v in seen[0].items())["authorization"] == "Bearer test-token-123"
        assert "test-token-123" not in provider.journal_path.read_text(encoding="utf-8")
        assert provider._connect().execute(
            "SELECT source_type FROM external_sources WHERE source_key=?",
            (result["source_key"],)
        ).fetchone()[0] == "github_authenticated"
    finally:
        if provider._conn is not None:
            provider._conn.close()
