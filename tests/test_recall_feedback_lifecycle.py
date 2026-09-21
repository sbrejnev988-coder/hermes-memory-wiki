"""Recall feedback stays neutral until an explicit answer outcome arrives."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_feedback_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_retrieval_is_neutral_and_terminal_feedback_learns(tmp_path, monkeypatch):
    module = _module(tmp_path, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(tmp_path), bot_id="bot-a")
    try:
        claim_id = provider._add_claim(
            "The Atlas service listens on port 7331.",
            "atlas", "operator observation", "phase6_curated_summary:test",
            0.9, 0.9, visibility_scope="chat",
        )
        assert str(claim_id).startswith("c_")

        results = provider._search(
            "Atlas service port 7331", limit=3, retrieval_mode="fts",
        )
        selected = next(row for row in results if row["id"] == claim_id)
        conn = provider._connect()
        neutral = conn.execute(
            "SELECT * FROM recall_feedback WHERE claim_id=? ORDER BY created_at,id",
            (claim_id,),
        ).fetchall()
        assert neutral and neutral[-1]["retrieved"] == 1
        assert neutral[-1]["injected"] == 0
        assert neutral[-1]["irrelevant"] == 0
        stats = provider._recall_feedback_stats(claim_id)
        assert stats["successful_recall_count"] == 0
        assert stats["irrelevant_recall_count"] == 0

        provider._record_prefetch_rows("Atlas service port", [selected])
        injected = conn.execute(
            "SELECT * FROM recall_feedback WHERE claim_id=? AND injected=1",
            (claim_id,),
        ).fetchall()
        assert len(injected) == 1 and injected[0]["irrelevant"] == 0

        baseline = float(stats["usefulness"])
        updated_at = conn.execute(
            "SELECT updated_at FROM claims WHERE id=?", (claim_id,),
        ).fetchone()[0]
        helpful = provider._mark_used(
            [claim_id], 0.9, outcome="helpful", answer_id="answer-1",
            notes="The answer was accepted.",
        )
        assert helpful["outcome"] == "helpful"
        learned = provider._recall_feedback_stats(claim_id)
        assert learned["successful_recall_count"] == 1
        assert float(learned["usefulness"]) > baseline
        duplicate = provider._mark_used(
            [claim_id], 0.9, outcome="helpful", answer_id="answer-1",
        )
        assert duplicate["updated"] == 0 and duplicate["duplicates"] == 1
        assert duplicate["feedback_ids"] == helpful["feedback_ids"]
        assert provider._recall_feedback_stats(claim_id) == learned

        provider._record_recall_rows([selected], injected=True, source="test")
        provider._mark_used([claim_id], 0.0, outcome="irrelevant")
        provider._record_recall_rows([selected], injected=True, source="test")
        provider._mark_used(
            [claim_id], 0.0, outcome="harmful",
            notes="api_key=sk-test-123456789012345678901234",
        )
        final = provider._recall_feedback_stats(claim_id)
        assert final["irrelevant_recall_count"] == 1
        assert final["harmful_recall_count"] == 1
        stored_notes = "\n".join(
            str(row[0] or "") for row in conn.execute(
                "SELECT notes FROM recall_feedback WHERE claim_id=?", (claim_id,),
            )
        )
        assert "sk-test" not in stored_notes
        assert conn.execute(
            "SELECT updated_at FROM claims WHERE id=?", (claim_id,),
        ).fetchone()[0] == updated_at
    finally:
        provider.shutdown()


def test_feedback_schema_and_checkpoint_contract(tmp_path, monkeypatch):
    module = _module(tmp_path, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(tmp_path), bot_id="bot-a")
    try:
        schema = next(
            item for item in provider.get_tool_schemas()
            if item["name"] == "memory_wiki_mark_used"
        )
        outcome = schema["parameters"]["properties"]["outcome"]
        assert set(outcome["enum"]) == {
            "used", "helpful", "irrelevant", "contradicted", "harmful",
        }
        assert "recall_feedback" in provider._checkpoint_tables()
        assert {"answer_id", "outcome"}.issubset(provider._cols("recall_events"))
        assert {"outcome", "idempotency_key"}.issubset(
            provider._cols("recall_feedback")
        )
        wrapper = json.loads(
            (PLUGIN.parent / "mcp-wrapper" / "tool_schemas.json").read_text(
                encoding="utf-8"
            )
        )
        wrapper_schema = next(
            item for item in wrapper if item["name"] == "memory_wiki_mark_used"
        )
        assert "recall_event_ids" in wrapper_schema["parameters"]["properties"]
        assert "recall_event_ids" in schema["parameters"]["properties"]
    finally:
        provider.shutdown()


def test_mark_used_v1_arguments_remain_usable_without_pending_recall(
    tmp_path, monkeypatch,
):
    module = _module(tmp_path, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(tmp_path), bot_id="bot-a")
    try:
        claim_id = provider._add_claim(
            "The Orion service listens on port 7553.", "orion", "observed",
            "phase6_curated_summary:test", 0.9, 0.9, visibility_scope="chat",
        )
        before = provider._connect().execute(
            "SELECT usefulness FROM claims WHERE id=?", (claim_id,),
        ).fetchone()[0]
        assert provider._mark_used([], 2.0) == {"updated": 0, "usefulness": 1.0}
        assert provider._mark_used([claim_id], 2.0) == {
            "updated": 1, "usefulness": 1.0,
        }
        after = provider._connect().execute(
            "SELECT usefulness FROM claims WHERE id=?", (claim_id,),
        ).fetchone()[0]
        assert float(after) > float(before)
        with pytest.raises(ValueError, match="no pending recall event"):
            provider._mark_used([claim_id], 1.0, outcome="helpful")
    finally:
        provider.shutdown()


def test_terminal_feedback_targets_one_event_and_is_answer_idempotent(
    tmp_path, monkeypatch
):
    module = _module(tmp_path, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(tmp_path), bot_id="bot-a")
    try:
        claim_id = provider._add_claim(
            "The Vega service listens on port 7442.", "vega", "observed",
            "phase6_curated_summary:test", 0.9, 0.9, visibility_scope="chat",
        )
        conn = provider._connect()
        row = dict(conn.execute(
            "SELECT * FROM claims WHERE id=?", (claim_id,),
        ).fetchone())
        first = provider._record_recall_rows(
            [row], injected=True, source="unified_recall",
        )[claim_id]
        second = provider._record_recall_rows(
            [row], injected=True, source="unified_recall",
        )[claim_id]
        original_updated_at = conn.execute(
            "SELECT updated_at FROM claims WHERE id=?", (claim_id,),
        ).fetchone()[0]

        applied = provider._mark_used(
            [claim_id], 0.9, outcome="helpful", answer_id="answer-explicit",
            recall_event_ids=[first],
        )
        assert applied["updated"] == 1
        assert applied["recall_event_ids"] == [first]
        assert tuple(conn.execute(
            "SELECT used,outcome,answer_id FROM recall_events WHERE id=?", (first,),
        ).fetchone()) == (0.9, "helpful", "answer-explicit")
        assert conn.execute(
            "SELECT used FROM recall_events WHERE id=?", (second,),
        ).fetchone()[0] == -1

        third = provider._record_recall_rows(
            [row], injected=True, source="unified_recall",
        )[claim_id]
        replay = provider._mark_used(
            [claim_id], 0.9, outcome="helpful", answer_id="answer-explicit",
        )
        assert replay["updated"] == 0 and replay["duplicates"] == 1
        assert replay["feedback_ids"] == applied["feedback_ids"]
        assert conn.execute(
            "SELECT used FROM recall_events WHERE id=?", (third,),
        ).fetchone()[0] == -1

        pending_latest = conn.execute(
            "SELECT id FROM recall_events WHERE claim_id=? AND used<0 "
            "ORDER BY created_at DESC,id DESC LIMIT 1", (claim_id,),
        ).fetchone()[0]
        latest = provider._mark_used(
            [claim_id], 0.0, outcome="irrelevant", answer_id="answer-latest",
        )
        assert latest["recall_event_ids"] == [pending_latest]
        remaining = {
            row[0] for row in conn.execute(
                "SELECT id FROM recall_events WHERE claim_id=? AND used<0", (claim_id,),
            )
        }
        assert ({second, third} - {pending_latest}).issubset(remaining)

        event_keyed = provider._record_recall_rows(
            [row], injected=True, source="unified_recall",
        )[claim_id]
        first_event_keyed = provider._mark_used(
            [claim_id], 0.8, outcome="helpful", recall_event_ids=[event_keyed],
        )
        repeated_event_keyed = provider._mark_used(
            [claim_id], 0.8, outcome="helpful", recall_event_ids=[event_keyed],
        )
        assert first_event_keyed["updated"] == 1
        assert repeated_event_keyed["updated"] == 0
        assert repeated_event_keyed["duplicates"] == 1
        assert repeated_event_keyed["feedback_ids"] == first_event_keyed["feedback_ids"]

        with pytest.raises(ValueError, match="not found"):
            provider._mark_used(
                [claim_id], outcome="helpful",
                recall_event_ids=["re_missing"],
            )
        assert conn.execute(
            "SELECT updated_at FROM claims WHERE id=?", (claim_id,),
        ).fetchone()[0] == original_updated_at
    finally:
        provider.shutdown()


def test_unified_recall_records_only_final_selected_claims(
    tmp_path, monkeypatch
):
    module = _module(tmp_path, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("chat-a", hermes_home=str(tmp_path), bot_id="bot-a")
    try:
        first = provider._add_claim(
            "Atlas observatory uses a violet telescope lens.", "atlas", "observed",
            "phase6_curated_summary:test", 0.9, 0.9, visibility_scope="chat",
        )
        second = provider._add_claim(
            "Atlas observatory stores a violet calibration lamp.", "atlas", "observed",
            "phase6_curated_summary:test", 0.9, 0.9, visibility_scope="chat",
        )
        result = module._recall_orchestrator.recall(
            provider, "Atlas observatory violet", mode="fast", limit=1,
            max_chars=500,
            query_expander=lambda *_args, **_kwargs: ["Atlas observatory violet"],
        )
        assert len(result["items"]) == 1
        selected = result["items"][0]
        assert selected["kind"] == "claim"
        assert selected["id"] in {first, second}
        event_id = selected["recall_event_id"]
        assert result["recall_tracking"]["status"] == "ok"
        assert result["recall_tracking"]["answer_linkage"] == {
            "claim_ids": [selected["id"]],
            "recall_event_ids": [event_id],
            "requires_answer_id_for_cross_retry_idempotency": True,
        }
        conn = provider._connect()
        event = conn.execute(
            "SELECT * FROM recall_events WHERE id=?", (event_id,),
        ).fetchone()
        assert event["claim_id"] == selected["id"]
        assert event["used"] == -1 and event["outcome"] == "pending"
        assert conn.execute("SELECT COUNT(*) FROM recall_events").fetchone()[0] == 1
        feedback = conn.execute(
            "SELECT * FROM recall_feedback WHERE recall_event_id=?", (event_id,),
        ).fetchone()
        assert feedback["feedback_source"] == "unified_recall"
        assert feedback["outcome"] == "neutral"
        assert feedback["helpful"] == 0 and feedback["irrelevant"] == 0
    finally:
        provider.shutdown()
