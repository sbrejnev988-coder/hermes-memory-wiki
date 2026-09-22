"""Opt-in graph extraction is source-grounded and replay-safe."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_graph_extraction_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, tool_name, **kwargs):
    return json.loads(provider.handle_tool_call(tool_name, kwargs))


def test_relation_grounding_rejects_reversed_endpoints():
    from entity_relation_extractor import _grounded_relation_clause as grounded
    assert grounded("Orion", "runs_on", "Atlas", "Orion runs on Atlas.")
    assert not grounded("Atlas", "runs_on", "Orion", "Orion runs on Atlas.")


class _Response:
    def __init__(self, relations):
        self.payload = json.dumps({"choices": [{"message": {"content": json.dumps({"relations": relations})}}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self.payload


def test_graph_extraction_is_explicit_grounded_and_journals_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", "test-model")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_API_KEY", "test-key")
    monkeypatch.delenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", raising=False)
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    try:
        with provider._connect() as conn:
            conn.execute(
                """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                   created_at,updated_at,freshness_at,access_count,last_accessed,hash,
                   visibility_scope,origin_session_id,origin_bot_id,origin_chat_hash)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("c_graph_extract", "Orion runs on Atlas.", "graph", "active", .9, .9, "test", "",
                 module.now(), module.now(), module.now(), 0, 0, "c-graph-extract", "chat",
                 "owner-chat", "owner-bot", provider._chat_hash("owner-chat")),
            )
        assert not _call(provider, "memory_wiki_graph_extract_claim", claim_id="c_graph_extract").get("success")
        checkpoint = provider._journal_checkpoint("before-graph-extraction")
        monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
        extractor = sys.modules.get("entity_relation_extractor")
        if extractor is None:
            spec = importlib.util.spec_from_file_location("entity_relation_extractor", PLUGIN.parent / "entity_relation_extractor.py")
            assert spec and spec.loader
            extractor = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = extractor
            spec.loader.exec_module(extractor)
        observed = []

        def response(request, timeout):
            observed.append(json.loads(request.data))
            return _Response([{"subject": "Orion", "predicate": "runs_on", "object": "Atlas",
                              "evidence": "Orion runs on Atlas", "confidence": .92}])

        monkeypatch.setattr(extractor.urllib.request, "urlopen", response)
        for field, value in (("risk", "secret"), ("quarantined_at", 123)):
            with provider._connect() as conn:
                conn.execute(f"UPDATE claims SET {field}=? WHERE id='c_graph_extract'", (value,))
            refused = _call(provider, "memory_wiki_graph_extract_claim", claim_id="c_graph_extract")
            assert refused.get("success") is not True, refused
            assert observed == []
            with provider._connect() as conn:
                conn.execute(f"UPDATE claims SET {field}=? WHERE id='c_graph_extract'",
                             ("low" if field == "risk" else 0,))
        dry = _call(provider, "memory_wiki_graph_extract_claim", claim_id="c_graph_extract", apply=False)
        assert dry["success"] and dry["applied"] == 0 and len(dry["proposals"]) == 1
        assert _call(provider, "memory_wiki_graph_query", query="Orion")["relations"] == []
        applied = _call(provider, "memory_wiki_graph_extract_claim", claim_id="c_graph_extract", apply=True)
        assert applied["success"] and applied["applied"] == 1, applied
        assert observed and observed[0]["messages"][-1]["content"] == "Orion runs on Atlas."
        assert "memory_wiki_graph_extract_claim" in provider._nonmutating_journal_tools()
        assert "memory_wiki_add_relation" in provider._replayable_journal_ops()
        journal = provider.journal_path.read_text(encoding="utf-8")
        assert "memory_wiki_add_relation" in journal
        assert "memory_wiki_graph_extract_claim" not in journal
        rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        assert rebuilt["failed"] == 0, rebuilt
        assert {row["id"] for row in _call(provider, "memory_wiki_graph_query", query="Orion")["relations"]} == set(applied["relation_ids"])
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET risk='secret' WHERE id='c_graph_extract'")
        assert _call(provider, "memory_wiki_graph_query", query="Orion")["relations"] == []
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET risk='low',quarantined_at=123 WHERE id='c_graph_extract'")
        assert _call(provider, "memory_wiki_graph_query", query="Orion")["relations"] == []
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET status='superseded' WHERE id='c_graph_extract'")
        assert _call(provider, "memory_wiki_graph_query", query="Orion")["relations"] == []
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_graph_extractor_rejects_unbacked_relation(monkeypatch):
    spec = importlib.util.spec_from_file_location("entity_relation_extractor", PLUGIN.parent / "entity_relation_extractor.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: _Response([
        {"subject": "Orion", "predicate": "runs_on", "object": "invented planet",
         "evidence": "Orion runs on Atlas", "confidence": .9}
    ]))
    import pytest
    with pytest.raises(ValueError, match="not grounded"):
        module.extract_relations("Orion runs on Atlas", endpoint="https://openrouter.ai/api/v1/chat/completions",
                                 api_key="test", model="test", predicates=frozenset({"runs_on"}))


def test_graph_extractor_rejects_cross_clause_and_low_confidence_links(monkeypatch):
    spec = importlib.util.spec_from_file_location("entity_relation_extractor", PLUGIN.parent / "entity_relation_extractor.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    import pytest

    source = "Alice owns Atlas. Bob uses Qdrant."
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: _Response([{
        "subject": "Alice", "predicate": "uses_provider", "object": "Qdrant",
        "evidence": source, "confidence": .95,
    }]))
    with pytest.raises(ValueError, match="one evidence clause"):
        module.extract_relations(
            source, endpoint="https://openrouter.ai/api/v1/chat/completions",
            api_key="test", model="test", predicates=frozenset({"uses_provider"}),
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: _Response([{
        "subject": "Bob", "predicate": "uses_provider", "object": "Qdrant",
        "evidence": "Bob uses Qdrant", "confidence": 0.2,
    }]))
    with pytest.raises(ValueError, match="confidence"):
        module.extract_relations(
            source, endpoint="https://openrouter.ai/api/v1/chat/completions",
            api_key="test", model="test", predicates=frozenset({"uses_provider"}),
        )


def test_graph_extractor_rejects_loopback_userinfo_spoof(monkeypatch):
    spec = importlib.util.spec_from_file_location("entity_relation_extractor", PLUGIN.parent / "entity_relation_extractor.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    requests = []
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: requests.append(args))
    import pytest
    with pytest.raises(ValueError, match="endpoint"):
        module.extract_relations("Orion runs on Atlas", endpoint="http://127.0.0.1:80@evil.example/collect",
                                 api_key="test-key", model="test", predicates=frozenset({"runs_on"}))
    assert requests == []
