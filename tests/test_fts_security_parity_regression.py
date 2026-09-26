"""FTS parity and raw-evidence isolation on disposable Memory Wiki databases."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    name = "memory_wiki_fts_security_parity_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("fts-parity-session", hermes_home=str(tmp_path), agent_context="test")
    try:
        yield provider, module
    finally:
        provider.shutdown()


def _seed(provider, module, cid="c-marigold", *,
          text="Synthetic marigold lattice calibration is stable.", evidence=""):
    stamp = module.now()
    with provider._connect() as conn:
        conn.execute(
            """INSERT INTO claims(id,claim,normalized_claim,topic,status,confidence,salience,
               source,evidence,created_at,updated_at,freshness_at,hash,quality,risk,
               quarantined_at,scope,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, text, text, "calibration", "active", .9, .9, "test:fts", evidence,
             stamp, stamp, stamp, cid, .9, "low", 0, "global", "chat",
             provider.bot_id, provider.session_id, provider._chat_hash(provider.session_id)),
        )
    provider._upsert_fts(cid)
    return cid


def _matches(conn, query):
    return {row[0] for row in conn.execute(
        "SELECT id FROM claims_fts WHERE claims_fts MATCH ?", (query,)
    )}


def test_equal_counts_with_different_ids_force_rebuild(wiki):
    provider, module = wiki
    cid = _seed(provider, module)
    conn = provider._connect()
    with conn:
        conn.execute("DELETE FROM claims_fts WHERE id=?", (cid,))
        conn.execute(
            "INSERT INTO claims_fts(id,claim,normalized,topic,evidence,search_text) "
            "VALUES(?,?,?,?,?,?)",
            ("phantom-fts-id", "phantom", "", "", "", "phantom"),
        )
    assert conn.execute("SELECT count(*) FROM claims WHERE status='active'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM claims_fts").fetchone()[0] == 1
    assert provider._ensure_fts_current() == "rebuilt"
    assert _matches(conn, "marigold") == {cid}
    assert _matches(conn, "phantom") == set()


def test_equal_ids_with_stale_search_document_force_rebuild(wiki):
    provider, module = wiki
    cid = _seed(provider, module)
    conn = provider._connect()
    with conn:
        conn.execute(
            "UPDATE claims_fts SET claim='',normalized='',topic='',evidence='',"
            "search_text='obsolete-only' WHERE id=?", (cid,)
        )
    assert provider._ensure_fts_current() == "rebuilt"
    assert _matches(conn, "marigold") == {cid}
    assert _matches(conn, "obsolete") == set()


def test_upsert_indexes_redacted_document_not_raw_evidence(wiki):
    provider, module = wiki
    canary = "FtsSyntheticCredentialViolet935"
    evidence = f"cedar observation api_key={canary}"
    assert canary not in module.claim_search_text("calibration note", "", "calibration", evidence)
    cid = _seed(provider, module, text="Synthetic cedar calibration note remains searchable.",
                evidence=evidence)
    conn = provider._connect()
    assert _matches(conn, canary) == set()
    assert _matches(conn, "cedar") == {cid}


def test_rebuild_does_not_reindex_raw_evidence(wiki):
    provider, module = wiki
    canary = "FtsSyntheticCredentialTopaz936"
    cid = _seed(provider, module, evidence=f"fir observation token={canary}")
    conn = provider._connect()
    assert _matches(conn, canary) == set()
    provider._rebuild_fts()
    assert _matches(conn, canary) == set()
    assert _matches(conn, "fir") == {cid}


def test_sql_content_trigger_matches_canonical_search_document(wiki):
    provider, module = wiki
    cid = _seed(provider, module)
    conn = provider._connect()
    canary = "FtsSyntheticCredentialBeryl937"
    revised = "Synthetic periwinkle lattice calibration is stable."
    with conn:
        conn.execute(
            "UPDATE claims SET claim=?,normalized_claim=?,topic=?,evidence=? WHERE id=?",
            (revised, revised, "garden", f"maple evidence password={canary}", cid),
        )
    assert _matches(conn, "marigold") == set()
    assert _matches(conn, "periwinkle") == {cid}
    assert _matches(conn, "maple") == {cid}
    assert _matches(conn, canary) == set()
    assert provider._ensure_fts_current() == "current"


def test_sql_reactivation_trigger_uses_same_safe_document(wiki):
    provider, module = wiki
    cid = _seed(provider, module)
    conn = provider._connect()
    canary = "FtsSyntheticCredentialIndigo938"
    with conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (cid,))
        conn.execute(
            "UPDATE claims SET evidence=?, status='active' WHERE id=?",
            (f"lichen evidence secret={canary}", cid),
        )
    assert _matches(conn, "marigold") == {cid}
    assert _matches(conn, "lichen") == {cid}
    assert _matches(conn, canary) == set()
    assert provider._ensure_fts_current() == "current"


def test_external_sqlite_writer_needs_no_private_udf_and_repairs_on_next_read(wiki):
    provider, module = wiki
    cid = _seed(provider, module)
    canary = "FtsSyntheticCredentialOnyx939"
    with sqlite3.connect(str(provider.db_path)) as private:
        private.execute(
            "UPDATE claims SET claim=?,normalized_claim=?,evidence=? WHERE id=?",
            ("Synthetic azalea lattice calibration is stable.",
             "Synthetic azalea lattice calibration is stable.",
             f"birch evidence api_key={canary}", cid),
        )
    conn = provider._connect()
    assert _matches(conn, "marigold") == set()
    assert _matches(conn, canary) == set()
    assert provider._ensure_fts_current() == "rebuilt"
    assert _matches(conn, "azalea") == {cid}
    assert _matches(conn, "birch") == {cid}
    assert _matches(conn, canary) == set()


def test_legacy_v2_raw_index_is_migrated_even_with_equal_ids_and_safe_search_text(wiki):
    provider, module = wiki
    canary = "FtsSyntheticCredentialCobalt940"
    evidence = f"lilac observation token={canary}"
    cid = _seed(provider, module, evidence=evidence)
    conn = provider._connect()
    with conn:
        conn.execute("UPDATE claims_fts SET evidence=? WHERE id=?", (evidence, cid))
        conn.execute("UPDATE meta SET value='v2' WHERE key='claims_fts_format'")
    assert _matches(conn, canary) == {cid}
    assert provider._ensure_fts_current() == "rebuilt"
    assert _matches(conn, canary) == set()
    assert _matches(conn, "lilac") == {cid}


def test_like_fallback_treats_percent_as_literal(wiki):
    provider, module = wiki
    exact = _seed(provider, module, "c-percent", text="Synthetic calibration uses prism%lattice terminology.")
    _seed(provider, module, "c-near", text="Synthetic calibration uses prismXlattice terminology.")
    rows = provider._search_fallback("prism%lattice", limit=10)
    assert {row["id"] for row in rows} == {exact}


def test_fts_search_like_expansion_treats_underscore_as_literal(wiki):
    provider, module = wiki
    exact = _seed(provider, module, "c-underscore",
                  text="Synthetic calibration uses sable_fern terminology.")
    _seed(provider, module, "c-near",
          text="Synthetic calibration uses sableXfern terminology.")
    rows = provider._search("sable_fern", limit=10, retrieval_mode="fts",
                            record_retrieval=False, apply_rerank=False)
    assert {row["id"] for row in rows} == {exact}


def test_search_repairs_external_writer_stale_index_before_matching(wiki):
    provider, module = wiki
    cid = _seed(provider, module)
    with sqlite3.connect(str(provider.db_path)) as private:
        private.execute(
            "UPDATE claims SET claim=?,normalized_claim=? WHERE id=?",
            ("Synthetic hellebore lattice calibration is stable.",
             "Synthetic hellebore lattice calibration is stable.", cid),
        )
    conn = provider._connect()
    assert _matches(conn, "hellebore") == set()
    rows = provider._search("hellebore", limit=10, retrieval_mode="fts",
                            record_retrieval=False, apply_rerank=False)
    assert {row["id"] for row in rows} == {cid}
    assert _matches(conn, "hellebore") == {cid}
    assert provider._ensure_fts_current() == "current"


@pytest.mark.parametrize("punctuation", ["%", "_"])
def test_like_fallback_short_wildcards_are_literal(wiki, punctuation):
    provider, module = wiki
    exact = _seed(provider, module, "c-symbol",
                  text=f"Synthetic calibration uses prism{punctuation}lattice terminology.")
    _seed(provider, module, "c-plain",
          text="Synthetic calibration uses prismlattice terminology.")
    rows = provider._search_fallback(punctuation, limit=10)
    assert {row["id"] for row in rows} == {exact}
