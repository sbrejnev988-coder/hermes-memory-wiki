"""R01/R02: real package, native SDK, in-memory SQLite; no provider stubs."""
from __future__ import annotations

import __main__
import json
import os
import sqlite3
import stat
import time
import uuid
from pathlib import Path

import pytest
import memory_wiki as wiki
from agent.memory_provider import MemoryProvider

recall_module = wiki._recall_orchestrator
QUERY = "Atlas observatory violet"
TEXT = "Atlas observatory uses a violet telescope lens."
STAMP = 1_700_000_000


@pytest.fixture
def provider(monkeypatch):
    # Constructor + authoritative schema only, never the lifecycle/restart loop.
    monkeypatch.setattr(__main__, "_memory_wiki_instance", None, raising=False)
    instance = wiki.MemoryWikiProvider()
    assert isinstance(instance, MemoryProvider)
    assert wiki.MemoryProvider is MemoryProvider
    coordination = json.loads((Path(__file__).resolve().parents[3] / "coordination.json").read_text(encoding="utf-8"))
    import sys
    assert Path(sys.modules[MemoryProvider.__module__].__file__).resolve().is_relative_to(
        Path(coordination["native_core"]).resolve()
    )
    instance.session_id = "conflicts-session"
    instance.bot_id = "conflicts-bot"
    instance.project_scope = "conflicts-project"
    instance.database_instance_id = "conflicts-fixture"
    instance._bot_scope_trusted = True
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.create_function("memory_wiki_fts_document", 4, wiki.claim_search_text)
    instance._conn = connection
    try:
        instance._migrate()
        monkeypatch.setattr(wiki, "now", lambda: STAMP)
        yield instance
    finally:
        connection.set_trace_callback(None)
        connection.close()
        instance._conn = None


def add_claim(provider, claim_id, *, visible=True, text=None):
    connection = provider._connect()
    with connection:
        connection.execute(
            """INSERT INTO claims(
                id,claim,topic,created_at,updated_at,freshness_at,hash,
                confidence,salience,source,source_type,quality,visibility_scope,
                origin_bot_id,origin_session_id,origin_chat_hash)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claim_id, text or "The fixture endpoint needs separate verification.",
             "astronomy", STAMP, STAMP, STAMP, claim_id, .8, .8, "fixture",
             "tool", .9, "chat", provider.bot_id,
             provider.session_id if visible else "hidden-session",
             provider._chat_hash() if visible else "hidden-chat"),
        )


def add_conflict(provider, conflict_id, endpoint, *, created_at=STAMP, status="open"):
    # This models pre-existing SQL-valid rows, not the current authoring API.
    with provider._connect() as connection:
        connection.execute(
            "INSERT INTO contradictions(id,claim_a,claim_b,reason,status,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (conflict_id, "c_selected", endpoint, "PRIVATE_REASON_SENTINEL", status, created_at),
        )


def seed_scope(provider, hidden_count=0, *, visible_conflict=True, tied_dates=False):
    add_claim(provider, "c_selected", text=TEXT)
    add_claim(provider, "c_hidden_endpoint", visible=False)
    add_claim(provider, "c_visible_endpoint")
    for index in range(hidden_count):
        add_conflict(
            provider, f"k_hidden_{index:04d}", "c_hidden_endpoint",
            created_at=STAMP if tied_dates else STAMP + index + 1,
        )
    if visible_conflict:
        add_conflict(provider, "k_000_visible", "c_visible_endpoint")


def full_recall(provider):
    # Exercise the real native tool dispatcher, FTS, guard and final serialization.
    return json.loads(provider.handle_tool_call(
        "memory_wiki_recall", {"query": QUERY, "mode": "fast", "limit": 1, "max_chars": 6000},
    ))


def assert_private_conflicts_omitted(result):
    rendered = json.dumps(result, ensure_ascii=False)
    for marker in ("k_hidden_", "c_hidden_endpoint", "k_000_visible", "PRIVATE_REASON_SENTINEL"):
        assert marker not in rendered


def test_visible_contradiction_beyond_first_40_in_full_recall(provider):
    seed_scope(provider, hidden_count=40)
    connection = provider._connect()
    first_page = connection.execute(
        "SELECT * FROM contradictions ORDER BY created_at DESC LIMIT 40",
    ).fetchall()
    assert len(first_page) == 40
    assert not any(provider._contradiction_visible(row, connection) for row in first_page)
    visible = connection.execute("SELECT * FROM contradictions WHERE id='k_000_visible'").fetchone()
    assert provider._contradiction_visible(visible, connection) is True
    result = full_recall(provider)
    assert result["success"] is True
    assert [item["id"] for item in result["items"]] == ["c_selected"]
    assert result["conflicts"] is True
    assert_private_conflicts_omitted(result)


@pytest.mark.parametrize("failure", ["connect", "sql", "acl"])
def test_failures_are_unknown_in_final_native_response(provider, monkeypatch, failure):
    seed_scope(provider)
    connection = provider._connect()
    recorder = provider._record_recall_rows
    error_detail = "SQL_ERROR_SENTINEL c_hidden_endpoint PRIVATE_REASON_SENTINEL"

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError(error_detail)

    def record_then_fail(rows, **kwargs):
        result = recorder(rows, **kwargs)
        if failure == "connect":
            monkeypatch.setattr(provider, "_connect", unavailable)
        elif failure == "acl":
            monkeypatch.setattr(provider, "_contradiction_visible", unavailable)
        else:
            connection.set_authorizer(
                lambda action, table, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and table == "contradictions"
                else sqlite3.SQLITE_OK
            )
        return result

    monkeypatch.setattr(provider, "_record_recall_rows", record_then_fail)
    result = full_recall(provider)
    assert result["success"] is True
    assert [item["id"] for item in result["items"]] == ["c_selected"]
    assert result.get("conflict_check") == {"status": "unknown", "scope": "selected_claims"}
    assert result["conflicts"] is False
    assert result["answer_policy"] == {
        "must_abstain_or_clarify": False,
        "require_citations": True,
        "allowed_citations": ["[M:C:c_selected]"],
        "conflict_status": "unknown",
        "instruction": (
            "Use only the returned evidence for memory-based claims and cite only an allowed citation ID. "
            "Conflict checking is incomplete or unavailable. Do not claim there are no contradictions; "
            "qualify memory-based conclusions or ask for clarification when a conflict-free answer is required."
        ),
    }
    assert error_detail not in json.dumps(result)
    assert "SQL_ERROR_SENTINEL" not in json.dumps(result)
    assert_private_conflicts_omitted(result)


def test_row_budget_exhaustion_is_unknown_without_unbounded_acl_work(provider, monkeypatch):
    seed_scope(provider, hidden_count=201)
    inspected = []
    predicate = provider._contradiction_visible

    def observe(row, connection):
        inspected.append(str(row["id"]))
        return predicate(row, connection)

    monkeypatch.setattr(provider, "_contradiction_visible", observe)
    result = full_recall(provider)
    assert len(inspected) == 200
    assert result["conflict_check"] == {"status": "unknown", "scope": "selected_claims"}
    assert result["conflicts"] is False
    assert result["answer_policy"]["conflict_status"] == "unknown"
    assert "Do not claim there are no contradictions" in result["answer_policy"]["instruction"]
    assert_private_conflicts_omitted(result)


def test_time_budget_exhaustion_is_unknown_before_first_sql_page(provider, monkeypatch):
    seed_scope(provider)
    monkeypatch.setattr(recall_module, "_CONFLICT_TIMEOUT_SECONDS", 0, raising=False)
    statements = []
    provider._connect().set_trace_callback(statements.append)
    result = full_recall(provider)
    assert result["conflict_check"]["status"] == "unknown"
    assert not any("FROM contradictions" in sql for sql in statements)
    assert result["conflicts"] is False


def test_exhaustive_check_uses_one_snapshot_across_pages(provider, monkeypatch, tmp_path):
    # Tiny real WAL database permits a concurrent writer without SDK doubles.
    primary = provider._connect()
    path = tmp_path / "snapshot.sqlite3"
    reader = sqlite3.connect(path)
    writer = sqlite3.connect(path)
    reader.row_factory = sqlite3.Row
    try:
        reader.execute("PRAGMA journal_mode=WAL")
        reader.execute("PRAGMA wal_autocheckpoint=1")
        writer.execute("PRAGMA wal_autocheckpoint=1")
        for name in ("claims", "contradictions"):
            ddl = primary.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0]
            reader.execute(ddl)
        provider._conn = reader
        seed_scope(provider, hidden_count=40, visible_conflict=False)
        predicate = provider._contradiction_visible
        count = 0

        def concurrent_insert(row, connection):
            nonlocal count
            count += 1
            if count == 40:
                with writer:
                    writer.execute(
                        "INSERT INTO contradictions(id,claim_a,claim_b,reason,status,created_at) "
                        "VALUES('k_concurrent','c_selected','c_visible_endpoint','private','open',?)",
                        (STAMP - 1,),
                    )
            return predicate(row, connection)

        monkeypatch.setattr(provider, "_contradiction_visible", concurrent_insert)
        assert recall_module._detect_conflicts(provider, ["c_selected"]) == "absent"
        # A new call must see the committed row; the previous call's scope was exhaustive at its snapshot.
        monkeypatch.setattr(provider, "_contradiction_visible", predicate)
        assert recall_module._detect_conflicts(provider, ["c_selected"]) == "present"
        assert reader.in_transaction is False
    finally:
        provider._conn = primary
        writer.close()
        reader.close()
        for ancestor in (path, *path.parents):
            assert not ancestor.is_symlink()
            assert not getattr(ancestor.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        path.unlink()
        assert not path.exists()


@pytest.mark.parametrize("failure", ["connect", "claim_acl"])
def test_failure_before_any_evidence_is_unknown(provider, monkeypatch, failure):
    seed_scope(provider)

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("SQL_ERROR_SENTINEL c_hidden_endpoint")

    monkeypatch.setattr(provider, "_connect" if failure == "connect" else "_claim_visible", unavailable)
    result = full_recall(provider)
    assert result["success"] is True
    assert result["items"] == []
    assert result["conflict_check"] == {"status": "unknown", "scope": "selected_claims"}
    assert result["conflicts"] is False
    assert result["answer_policy"]["must_abstain_or_clarify"] is True
    assert result["answer_policy"]["conflict_status"] == "unknown"
    assert "SQL_ERROR_SENTINEL" not in json.dumps(result)


@pytest.mark.parametrize("failure", ["connect", "acl"])
def test_one_shot_final_read_failures_remain_unknown(provider, monkeypatch, failure):
    seed_scope(provider)
    inspector = provider._inspect_recall_text
    method = "_connect" if failure == "connect" else "_claim_visible"
    original = getattr(provider, method)

    def fail_once(*_args, **_kwargs):
        monkeypatch.setattr(provider, method, original)
        raise sqlite3.OperationalError("SQL_ERROR_SENTINEL c_hidden_endpoint")

    def inspect_and_arm(text, **kwargs):
        result = inspector(text, **kwargs)
        if kwargs.get("source") == "unified_recall:claim":
            monkeypatch.setattr(provider, method, fail_once)
        return result

    monkeypatch.setattr(provider, "_inspect_recall_text", inspect_and_arm)
    result = full_recall(provider)
    assert result["success"] is True
    assert result["items"] == []
    assert result["conflict_check"]["status"] == "unknown"
    assert result["answer_policy"]["conflict_status"] == "unknown"
    assert "SQL_ERROR_SENTINEL" not in json.dumps(result)


@pytest.mark.parametrize("hidden_count", [0, 40, 79, 199])
def test_absent_requires_exhaustive_relevant_scope(provider, monkeypatch, hidden_count):
    seed_scope(provider, hidden_count=hidden_count, visible_conflict=False)
    # An unrelated visible open conflict and a relevant resolved conflict do not count.
    add_claim(provider, "c_unrelated")
    with provider._connect() as connection:
        connection.execute(
            "INSERT INTO contradictions(id,claim_a,claim_b,reason,status,created_at) "
            "VALUES('k_unrelated','c_unrelated','c_visible_endpoint','private','open',?)", (STAMP,),
        )
    add_conflict(provider, "k_resolved", "c_visible_endpoint", status="resolved")
    visited = []
    predicate = provider._contradiction_visible

    def observe(row, connection):
        visited.append(str(row["id"]))
        return predicate(row, connection)

    monkeypatch.setattr(provider, "_contradiction_visible", observe)
    result = full_recall(provider)
    assert len(visited) == hidden_count == len(set(visited))
    assert result["conflict_check"] == {"status": "absent", "scope": "selected_claims"}
    assert result["conflicts"] is False
    assert result["answer_policy"]["conflict_status"] == "absent"
    assert "This check does not cover other memory or unrecorded contradictions." in result["answer_policy"]["instruction"]
    assert_private_conflicts_omitted(result)


def test_keyset_tiebreaker_does_not_skip_equal_timestamps(provider):
    seed_scope(provider, hidden_count=40, tied_dates=True)
    result = full_recall(provider)
    assert result["conflict_check"]["status"] == "present"
    assert result["conflicts"] is True


def test_current_authoring_api_rejects_mixed_visibility_partitions(provider):
    seed_scope(provider, visible_conflict=False)
    with pytest.raises(ValueError, match="share a visibility partition"):
        provider._add_contradiction("c_selected", "c_hidden_endpoint", "fixture")
    assert provider._connect().execute("SELECT count(*) FROM contradictions").fetchone()[0] == 0
    assert provider._connect().execute("PRAGMA foreign_key_check").fetchall() == []


def test_deadline_stops_between_acl_checks_and_releases_read_snapshot(provider, monkeypatch):
    seed_scope(provider, hidden_count=2, visible_conflict=False)
    monkeypatch.setattr(recall_module, "_CONFLICT_TIMEOUT_SECONDS", .01)
    predicate = provider._contradiction_visible
    visited = []

    def slow_predicate(row, connection):
        visited.append(str(row["id"]))
        value = predicate(row, connection)
        time.sleep(.03)
        return value

    monkeypatch.setattr(provider, "_contradiction_visible", slow_predicate)
    assert recall_module._detect_conflicts(provider, ["c_selected"]) == "unknown"
    assert len(visited) == 1
    assert provider._connect().in_transaction is False


@pytest.mark.parametrize("mode", ["fast", "auto", "deep"])
def test_real_dispatcher_preserves_present_state_in_every_mode(provider, mode):
    seed_scope(provider, hidden_count=40)
    result = json.loads(provider.handle_tool_call("memory_wiki_recall", {
        "query": QUERY, "mode": mode, "limit": 1, "max_chars": 6000,
    }))
    assert result["success"] is True
    assert result["conflict_check"]["status"] == "present"
    assert result["conflicts"] is True
    assert result["answer_policy"]["conflict_status"] == "present"
    assert_private_conflicts_omitted(result)


def test_conflict_read_preserves_callers_outer_transaction(provider):
    seed_scope(provider, visible_conflict=False)
    connection = provider._connect()
    connection.execute("SAVEPOINT fixture_owner")
    try:
        connection.execute("INSERT INTO meta(key,value) VALUES('fixture_uncommitted','yes')")
        assert recall_module._detect_conflicts(provider, ["c_selected"]) == "absent"
        assert connection.in_transaction is True
        connection.execute("ROLLBACK TO fixture_owner")
        assert connection.execute("SELECT value FROM meta WHERE key='fixture_uncommitted'").fetchone() is None
    finally:
        connection.execute("RELEASE fixture_owner")


@pytest.mark.parametrize("state", ["present", "absent", "unknown"])
def test_exact_final_native_recall_response(provider, monkeypatch, state):
    seed_scope(provider, hidden_count={"present": 40, "absent": 41, "unknown": 201}[state],
               visible_conflict=state != "absent")
    monkeypatch.setattr(wiki.uuid, "uuid4", lambda: uuid.UUID("11111111-1111-1111-1111-111111111111"))
    citation = "[M:C:c_selected]"
    event_id = "re_11111111111111111111"
    instructions = {
        "present": (
            "Visible open contradictions affect the selected claims. Acknowledge the conflict; "
            "do not assert that the evidence is conflict-free or choose a winner without supporting evidence."
        ),
        "absent": (
            "No visible open contradictions were found for the selected claims. "
            "This check does not cover other memory or unrecorded contradictions."
        ),
        "unknown": (
            "Conflict checking is incomplete or unavailable. Do not claim there are no contradictions; "
            "qualify memory-based conclusions or ask for clarification when a conflict-free answer is required."
        ),
    }
    result = full_recall(provider)
    assert result == {
        "success": True,
        "items": [{
            "id": "c_selected", "kind": "claim", "citation": citation, "content": TEXT,
            "source": "memory_claim", "source_kind": "tool",
            "trust": {"level": "unverified", "class": "fact", "confidence": .8},
            "timestamps": {"event_at": STAMP, "created_at": STAMP, "updated_at": STAMP},
            "rrf_score": 0.01639344, "recall_event_id": event_id,
        }],
        "intent_plan": {
            "mode": "fast", "intent": {
                "primary": "factual", "temporal": False, "current_state": False,
                "multi_hop": False, "preference": False, "procedural": False,
                "negative_premise": False, "deep_recommended": False,
            },
            "queries": [QUERY], "retrieval_mode": "fts", "sources": {
                "claims": "ok", "episodes": "disabled", "events": "not_requested",
                "observations": "not_requested", "graph": "not_requested",
            },
        },
        "evidence_count": 1, "conflicts": state == "present",
        "conflict_check": {"status": state, "scope": "selected_claims"},
        "chars_used": 47, "max_chars": 6000,
        "recall_tracking": {
            "status": "ok", "events": [{"claim_id": "c_selected", "recall_event_id": event_id}],
            "answer_linkage": {
                "claim_ids": ["c_selected"], "recall_event_ids": [event_id],
                "requires_answer_id_for_cross_retry_idempotency": True,
            },
        },
        "answer_policy": {
            "must_abstain_or_clarify": False, "require_citations": True,
            "allowed_citations": [citation], "conflict_status": state,
            "instruction": "Use only the returned evidence for memory-based claims and cite only an allowed citation ID. " + instructions[state],
        },
    }
    assert_private_conflicts_omitted(result)
    (Path(os.environ["TMPDIR"]).parent / f"recall-response-{state}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
