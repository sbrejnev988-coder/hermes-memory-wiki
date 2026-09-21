"""Optional graph enrichment consumes only new grounded session claims."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_graph_auto_enrichment_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MW_EXTRACTION_ENABLED", "0")
    module = _module()
    monkeypatch.setattr(module, "memory_gate_decision", lambda *_a, **_k: {"action": "accept"})
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-auto-chat", hermes_home=str(tmp_path), bot_id="graph-auto-bot", agent_context="test")
    return provider, module


def _grounded_evidence(session_id: str, quote: str, source: str = "extractor:llm") -> str:
    return json.dumps({
        "schema": "memory-wiki-extraction-evidence-v1",
        "session_id": session_id,
        "speaker": "user",
        "message_index": 0,
        "evidence_quote": quote,
        "event_at": 0,
        "event_timezone": "UTC",
        "extractor": source,
    }, sort_keys=True)


def _seed(provider, text: str, *, grounded: bool = True, source: str = "extractor:llm") -> str:
    evidence = _grounded_evidence(provider.session_id, text, source) if grounded else "{}"
    return provider._add_claim(
        text, "systems", evidence, source, .82, .75, visibility_scope="chat",
    )


def test_session_integration_is_opt_in_new_only_idempotent_and_inherits_acl(tmp_path, monkeypatch):
    provider, module = _provider(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "0")
    current = {"text": "User states Project Cedar uses Qdrant for vector search."}

    def fake_session_extract(_exchanges, session_id="", add_claim_callback=None, **_kwargs):
        assert add_claim_callback is not None
        claim_id = add_claim_callback(
            current["text"], topic="systems",
            evidence=_grounded_evidence(session_id, current["text"]),
            source="extractor:llm", confidence=.9, salience=.8,
            visibility_scope="chat",
        )
        return {"extracted": 1, "persisted": 1, "persisted_ids": [claim_id], "errors": [], "error": ""}

    calls = []

    def fake_graph_extract(args):
        calls.append(dict(args))
        claim_id = args["claim_id"]
        relation = provider._add_relation({
            "subject": "Project Cedar", "predicate": "uses_provider", "object": "Qdrant",
            "evidence": "Project Cedar uses Qdrant", "confidence": .9,
            "source_claim_id": claim_id,
        })
        return {"claim_id": claim_id, "applied": 1, "relation_ids": [relation["id"]], "errors": []}

    monkeypatch.setattr(module, "extract_session_claims", fake_session_extract)
    monkeypatch.setattr(provider, "_graph_extract_claim", fake_graph_extract)
    messages = [{"role": "user", "content": "bounded source message"}]
    try:
        provider._extract_session_claims(messages)
        assert calls == []

        monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "1")
        monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "0")
        current["text"] = "User states Project Fir uses Qdrant for vector search."
        provider._extract_session_claims(messages)
        assert calls == []

        monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
        current["text"] = "User states Project Birch uses Qdrant for vector search."
        provider._extract_session_claims(messages)
        assert len(calls) == 1 and calls[0]["apply"] is True
        assert 1.0 <= float(calls[0]["_auto_timeout_seconds"]) <= 30.0

        claim_id = calls[0]["claim_id"]
        with provider._connect() as conn:
            claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            relation = conn.execute("SELECT * FROM relations WHERE source_claim_id=?", (claim_id,)).fetchone()
        assert relation is not None
        for field in ("visibility_scope", "origin_bot_id", "origin_chat_hash"):
            assert relation[field] == claim[field]
        # Session IDs are not part of a chat partition identity; the chat hash
        # is the authoritative boundary and graph rows avoid redundant identity.
        assert relation["origin_session_id"] == ""
        assert relation["project_id"] == ""

        # The extractor can return an existing persisted ID, but it is no
        # longer new and must not trigger another remote call.
        provider._extract_session_claims(messages)
        assert len(calls) == 1
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_eligibility_requires_grounded_safe_current_relation_likely_claim(tmp_path, monkeypatch):
    provider, _module_obj = _provider(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "1")
    eligible = _seed(provider, "User states Project Orion depends on Qdrant for retrieval.")
    preference = _seed(provider, "User prefers and uses dark mode for the interface theme.")
    invalid_evidence = _seed(provider, "User states Project Atlas runs on Server Nova.", grounded=False)
    archived = _seed(provider, "User states Project Maple uses OpenRouter for embeddings.")
    unsafe = _seed(provider, "User states Project Aspen hosts the application service.")
    already_linked = _seed(provider, "User states Project Elm uses Qdrant for vectors.")
    with provider._connect() as conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (archived,))
        conn.execute("UPDATE claims SET risk='secret' WHERE id=?", (unsafe,))
    provider._add_relation({
        "subject": "Project Elm", "predicate": "uses_provider", "object": "Qdrant",
        "evidence": "Project Elm uses Qdrant", "source_claim_id": already_linked,
    })
    calls = []
    monkeypatch.setattr(provider, "_graph_extract_claim", lambda args: calls.append(dict(args)) or {
        "claim_id": args["claim_id"], "applied": 0, "relation_ids": [], "errors": [],
    })
    try:
        result = provider._auto_graph_enrich_extracted_claims([
            eligible, preference, invalid_evidence, archived, unsafe, already_linked,
        ])
        assert [call["claim_id"] for call in calls] == [eligible]
        assert result["attempted"] == 1 and result["skipped_unrelated"] == 0
        assert result["skipped_existing"] == 1 and result["skipped_ineligible"] == 4
        with provider._connect() as conn:
            audit = conn.execute(
                "SELECT detail FROM audit_log WHERE op='graph_auto_extract' ORDER BY created_at DESC,id DESC LIMIT 1"
            ).fetchone()
        assert audit is not None
        assert all(text not in audit["detail"] for text in ("Project Orion", "Qdrant", eligible))
        assert json.loads(audit["detail"])["attempted"] == 1
    finally:
        provider._conn.close()


def test_caps_failures_and_total_deadline_are_nonfatal(tmp_path, monkeypatch):
    provider, _module_obj = _provider(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "1")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT_MAX_CLAIMS", "99")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT_TOTAL_DEADLINE_SECONDS", "99")
    claim_ids = [_seed(provider, f"User states Project Auto{i} uses Qdrant for vectors.") for i in range(6)]
    calls = []

    def flaky(args):
        calls.append(dict(args))
        if len(calls) == 1:
            raise RuntimeError("synthetic remote failure with claim text that must not be audited")
        return {"claim_id": args["claim_id"], "applied": 0, "relation_ids": [], "errors": []}

    monkeypatch.setattr(provider, "_graph_extract_claim", flaky)
    try:
        result = provider._auto_graph_enrich_extracted_claims(claim_ids)
        assert len(calls) == 4 and result["attempted"] == 4
        assert result["skipped_limit"] == 2 and result["errors"] == 1
        assert all(1.0 <= float(call["_auto_timeout_seconds"]) <= 30.0 for call in calls)

        deadline_claims = [_seed(provider, f"User states Project Slow{i} depends on Qdrant for search.") for i in range(2)]
        slow_calls = []
        monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT_TOTAL_DEADLINE_SECONDS", "1.1")

        def slow(args):
            slow_calls.append(dict(args))
            time.sleep(0.2)
            return {"claim_id": args["claim_id"], "applied": 0, "relation_ids": [], "errors": []}

        monkeypatch.setattr(provider, "_graph_extract_claim", slow)
        deadline_result = provider._auto_graph_enrich_extracted_claims(deadline_claims)
        assert len(slow_calls) == 1
        assert deadline_result["deadline_exhausted"] == 1
    finally:
        provider._conn.close()
