#!/usr/bin/env python3
"""Regression: optional secret metadata must not discard semantic recall."""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location(
    "memory_wiki_prefetch_secret_context_regression",
    str(PLUGIN),
    submodule_search_locations=[str(PLUGIN.parent)],
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def sample_row() -> dict:
    timestamp = int(time.time())
    return {
        "id": "c_prefetch_regression",
        "claim": "Durable semantic recall survives unavailable optional secret metadata.",
        "topic": "memory-wiki",
        "status": "active",
        "confidence": 0.9,
        "salience": 0.8,
        "score": 1.0,
        "score_parts": {"bm25": 1.0, "rrf": 0.1},
        "freshness_at": timestamp,
        "updated_at": timestamp,
        "memory_revision": 1,
        "visibility_scope": "global",
        "memory_class": "fact",
        "trust_score": 0.95,
        "why_believe": "regression fixture",
        "source": "test:prefetch",
        "evidence_count": 0,
        "pinned": 0,
    }


def test_prefetch_keeps_semantic_context_when_secret_store_is_unavailable() -> None:
    provider = mod.MemoryWikiProvider()
    row = sample_row()

    provider._select_recall_rows = lambda *_a, **_k: {
        "rows": [row],
        "delta_rows": [],
        "watermark": 0,
    }
    provider._recall_plan = lambda *_a, **_k: {"topics": [], "types": []}
    provider._env_metadata_context = lambda *_a, **_k: ""

    def unavailable_secret_context(*_a, **_k):
        raise RuntimeError("hermes_secret_core_unavailable: test fixture")

    provider._secret_context = unavailable_secret_context
    provider._inspect_recall_item = lambda item, **_k: {
        "status": "safe",
        "content": item["claim"],
        "trust_level": "trusted",
        "guard_disagreement": False,
    }
    provider._inspect_recall_text = lambda text, **_k: {
        "status": "safe",
        "content": str(text),
        "guard_disagreement": False,
    }
    provider._top_evidence = lambda *_a, **_k: []
    provider._related_contradictions = lambda *_a, **_k: []
    provider._memory_cache_state_contract = lambda *_a, **_k: {
        "state_revision": 1,
        "state_token": "test",
        "index_revision": "test",
        "partition": "global",
        "state_consistent": True,
    }
    provider._record_prefetch_rows = lambda *_a, **_k: None
    provider._mark_seen_revision = lambda *_a, **_k: None
    provider._finish_prefetch_diagnostics = lambda *_a, **_k: None
    provider._lexical_prefetch_fallback = lambda *_a, **_k: "FALLBACK"
    mod._maybe_prefetch_code_context = lambda *_a, **_k: ""
    mod._maybe_prefetch_document_context = lambda *_a, **_k: ""

    output = provider.prefetch("semantic recall regression", session_id="test")

    assert output != "FALLBACK"
    assert '<memory-context source="memory-wiki"' in output
    assert row["claim"] in output


if __name__ == "__main__":
    test_prefetch_keeps_semantic_context_when_secret_store_is_unavailable()
    print("PASS test_prefetch_keeps_semantic_context_when_secret_store_is_unavailable")
