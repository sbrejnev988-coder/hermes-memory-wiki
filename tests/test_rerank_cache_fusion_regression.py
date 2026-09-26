"""Cached rerank fusion must use the current local candidate ordering."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def test_rerank_cache_preserves_current_rrf_fusion(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    name = "memory_wiki_rerank_cache_fusion_regression"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "RERANK_ENABLED", True)
    monkeypatch.setattr(module, "RERANK_ENDPOINT_VALID", True)
    monkeypatch.setattr(module, "RERANK_MIN_CANDIDATES", 3)
    monkeypatch.setattr(module, "RERANK_TOP_K", 3)
    monkeypatch.setattr(module, "RERANK_WEIGHT_SEMANTIC", 0.25)
    monkeypatch.setattr(module, "_rerank_api_key", lambda: "synthetic-key")
    monkeypatch.setattr(module, "_prefetch_network_timeout", lambda *_args: 1.0)
    module._RERANK_CACHE.clear()
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_open(request, timeout=1.0):
        payload = json.loads(request.data.decode("utf-8"))
        documents = payload["documents"]
        requests.append([str(item) for item in documents])
        indices = sorted(range(len(documents)), key=lambda index: str(documents[index]))
        return Response({"results": [
            {"index": index, "relevance_score": 0.9 - rank * 0.1}
            for rank, index in enumerate(indices)
        ]})

    monkeypatch.setattr(module, "_urlopen_no_redirect", fake_open)
    provider = module.MemoryWikiProvider()
    rows = [
        {"id": name, "claim": f"Synthetic {name} retrieval note with enough harmless words for reranking and cache validation.",
         "status": "active", "risk": "low", "trust_class": "fact", "updated_at": 1,
         "score_parts": {}}
        for name in ("A", "B", "C")
    ]
    query = "Which synthetic retrieval note ranks higher in the current order?"
    forward = provider._rerank_rows(query, rows, "semantic")
    cached_reverse = provider._rerank_rows(query, list(reversed(rows)), "semantic")
    assert len(requests) == 1
    module._RERANK_CACHE.clear()
    fresh_reverse = provider._rerank_rows(query, list(reversed(rows)), "semantic")
    assert len(requests) == 2
    assert [item["id"] for item in cached_reverse] == [item["id"] for item in fresh_reverse]
    assert [item["id"] for item in forward] != [item["id"] for item in fresh_reverse]
