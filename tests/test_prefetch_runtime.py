#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Verify runtime hard caps while using a complete current recall-row fixture.
os.environ["MEMORY_WIKI_RERANK_ENABLED"] = "1"
os.environ["MEMORY_WIKI_RERANK_API_KEY"] = "test-only"
os.environ["MEMORY_WIKI_RERANK_MIN_CANDIDATES"] = "3"
os.environ["MEMORY_WIKI_RERANK_TOP_K"] = "5"
os.environ["MEMORY_WIKI_RERANK_TIMEOUT"] = "9"
os.environ["MEMORY_WIKI_RERANK_RETRY_COUNT"] = "4"
os.environ["MEMORY_WIKI_PREFETCH_DEADLINE_SECONDS"] = "5.5"
os.environ["MEMORY_WIKI_EMBED_PROVIDER"] = "openrouter"
os.environ["MEMORY_WIKI_EMBED_API_KEY"] = "test-only"
os.environ["MEMORY_WIKI_EMBED_DIMENSIONS"] = "8"
os.environ["MEMORY_WIKI_VECTOR_SIZE"] = "8"

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location(
    "memory_wiki_prefetch_test", str(PLUGIN), submodule_search_locations=[str(PLUGIN.parent)]
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def sample_rows() -> list[dict]:
    now = int(time.time())
    return [
        {
            "id": f"c_{i}",
            "claim": f"Durable preference-safe memory claim {i}",
            "topic": "memory-wiki",
            "status": "active",
            "risk": "low",
            "quarantined_at": 0,
            "trust_class": "fact",
            "score": float(10 - i),
            "score_parts": {"bm25": 0.2},
            "updated_at": now - i,
            # R21: fields consumed by current prefetch/retrieval rendering.
            "freshness_at": now - i,
            "pinned": 0,
            "memory_class": "fact",
            "trust_score": 0.95,
            "why_believe": "verified test fixture",
            "source": "test:prefetch",
            "evidence_count": 0,
            "memory_revision": i + 1,
            "visibility_scope": "global",
            "confidence": 0.9,
            "salience": 0.8,
        }
        for i in range(5)
    ]


def test_runtime_caps() -> None:
    assert 5.0 <= mod.PREFETCH_DEADLINE_SECONDS <= 6.0
    assert mod.RERANK_RETRY_COUNT == 1
    assert mod.RERANK_TIMEOUT <= 3.0


def test_health_stale_while_revalidate() -> None:
    calls = []
    def slow_probe() -> bool:
        calls.append(time.monotonic())
        time.sleep(0.12)
        return True
    setattr(mod, "_openrouter_available", slow_probe)
    mod._OPENROUTER_HEALTH_CACHE.update({"checked_at": time.time() - 999, "available": False, "refreshing": False})
    started = time.monotonic()
    stale = mod._openrouter_health_swr()
    elapsed = time.monotonic() - started
    assert stale is False
    assert elapsed < 0.05
    deadline = time.monotonic() + 1.0
    while mod._OPENROUTER_HEALTH_CACHE.get("refreshing") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls and mod._OPENROUTER_HEALTH_CACHE["available"] is True


def test_prefetch_embedding_uses_one_bounded_attempt() -> None:
    calls = []
    def fail_urlopen(_request, timeout=0):
        calls.append(float(timeout))
        raise TimeoutError("synthetic network timeout")
    original_urlopen = mod.urllib.request.urlopen
    mod.urllib.request.urlopen = fail_urlopen
    try:
        started = time.monotonic()
        with mod._prefetch_budget(0.35):
            result = mod._openrouter_embed("deadline test", input_type="search_query", timeout=9.0)
        elapsed = time.monotonic() - started
    finally:
        mod.urllib.request.urlopen = original_urlopen
    assert result is None
    assert len(calls) == 1
    assert 0 < calls[0] <= 0.35
    assert elapsed < 0.55


def test_hybrid_failure_falls_back_to_local_fts() -> None:
    provider = mod.MemoryWikiProvider()
    modes = []
    def fake_search(_query, limit=10, include_stale=True, topic=None, session_id="", retrieval_mode="hybrid", record_retrieval=True):
        modes.append(retrieval_mode)
        if retrieval_mode == "hybrid":
            raise TimeoutError("synthetic semantic timeout")
        return sample_rows()[:limit]
    provider._search = fake_search
    provider._revision_delta = lambda *_a, **_k: {"rows": [], "watermark": 0}
    selected = provider._select_recall_rows("memory latency", limit=3, record_retrieval=False)
    assert modes == ["hybrid", "fts"]
    assert [row["id"] for row in selected["rows"]] == ["c_0", "c_1", "c_2"]


def test_prefetch_row_fixture_matches_current_renderer_contract() -> None:
    provider = mod.MemoryWikiProvider()
    row = sample_rows()[0]
    required = {
        "id", "claim", "topic", "status", "freshness_at", "confidence", "salience",
        "memory_revision", "visibility_scope", "trust_score", "source", "evidence_count",
    }
    assert required <= row.keys()
    # This specifically guards the previous fixture defect: rendering must not KeyError.
    assert provider._format_claim_time(row)


def test_reranker_timeout_is_single_attempt_and_fail_open() -> None:
    provider = mod.MemoryWikiProvider()
    calls = []
    def fail_urlopen(_request, timeout=0):
        calls.append(float(timeout))
        raise TimeoutError("synthetic reranker timeout")
    original_urlopen = mod.urllib.request.urlopen
    mod.urllib.request.urlopen = fail_urlopen
    setattr(mod, "RERANK_ENABLED", True)
    mod._RERANK_CACHE.clear()
    try:
        with mod._prefetch_budget(0.45):
            original = sample_rows()
            result = provider._rerank_rows("semantic memory latency query", original, "semantic")
    finally:
        mod.urllib.request.urlopen = original_urlopen
    assert [row["id"] for row in result] == [row["id"] for row in original]
    assert len(calls) == 1
    assert 0 < calls[0] <= 0.45


def test_trusted_preferences_are_real_system_prompt_content() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-pref-system-") as tmp:
        root = Path(tmp)
        provider = mod.MemoryWikiProvider()
        provider.root = root
        provider.spool_dir = root / "spool"
        provider.recovery_dir = root / "recovery"
        provider.db_path = root / "memory.sqlite3"
        conn = provider._connect()
        conn.execute("""CREATE TABLE preference_rules(
            id TEXT PRIMARY KEY, rule TEXT NOT NULL, priority INTEGER NOT NULL,
            scope TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE
        )""")
        rows = [
            ("pref_system", "Current explicit user instruction wins.", 1000, "global", "system", "active", 1, 1, "h1"),
            ("pref_user", "Всегда отвечать на русском языке.", 100, "language", "user: Kekl", "active", 1, 2, "h2"),
            ("pref_auto", "This auto-extracted text must stay untrusted.", 999, "global", "extractor:auto", "active", 1, 3, "h3"),
        ]
        conn.executemany("INSERT INTO preference_rules VALUES(?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        prompt = provider.system_prompt_block()
        assert "# Trusted User Preference Layer" in prompt
        assert "Всегда отвечать на русском языке." in prompt
        assert "Current explicit user instruction wins." in prompt
        assert "auto-extracted text" not in prompt
        assert "ordinary recalled claims" in prompt


def main() -> None:
    tests = [
        test_runtime_caps,
        test_health_stale_while_revalidate,
        test_prefetch_embedding_uses_one_bounded_attempt,
        test_hybrid_failure_falls_back_to_local_fts,
        test_prefetch_row_fixture_matches_current_renderer_contract,
        test_reranker_timeout_is_single_attempt_and_fail_open,
        test_trusted_preferences_are_real_system_prompt_content,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(json.dumps({"ok": True, "tests": len(tests)}))


if __name__ == "__main__":
    main()
