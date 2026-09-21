"""Bounded embedding reuse lowers network cost without changing retrieval semantics."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(name: str, tmp_path: Path, monkeypatch, *, max_entries: int = 8, ttl: int = 60):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_PROVIDER", "openrouter")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_MODEL", "test/embed-v1")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_DIMENSIONS", "8")
    monkeypatch.setenv("MEMORY_WIKI_VECTOR_SIZE", "8")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES", str(max_entries))
    monkeypatch.setenv("MEMORY_WIKI_EMBED_QUERY_CACHE_TTL_SECONDS", str(ttl))
    monkeypatch.setenv("MEMORY_WIKI_EMBED_DOCUMENT_CACHE_TTL_SECONDS", str(ttl))
    monkeypatch.setenv("MEMORY_WIKI_EMBED_CACHE_SINGLEFLIGHT_WAIT_SECONDS", "5")
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module._embedding_cache_clear(reset_metrics=True)
    return module


def _vector(module, value: float = 0.25):
    return [value] * module.QDRANT_VECTOR_SIZE


def test_normalized_query_reuses_one_http_embedding_and_preserves_copy_isolation(
    tmp_path, monkeypatch,
):
    module = _module("memory_wiki_embed_cache_normalized", tmp_path, monkeypatch)
    calls = []

    def embed(text, *, input_type, timeout=30.0):
        calls.append((text, input_type))
        return _vector(module)

    monkeypatch.setattr(module, "_openrouter_embed", embed)
    first = module._embed_query("  Ａｔｌａｓ\n\tlaunch   status  ")
    second = module._embed_query("Atlas launch status")
    assert calls == [("Atlas launch status", "search_query")]
    assert first == second == _vector(module)
    assert first is not second
    first[0] = 99.0
    assert module._embed_query("Atlas launch status")[0] == 0.25
    assert module._EMBED_CACHE_METRICS["hits"] == 2
    assert module._EMBED_CACHE_METRICS["stores"] == 1


def test_query_cache_key_preserves_case_and_punctuation(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_semantics", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or _vector(module),
    )
    module._embed_query("US")
    module._embed_query("us")
    module._embed_query("US?")
    assert calls == ["US", "us", "US?"]


def test_config_and_manifest_change_clear_cached_query(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_config", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append((module.EMBED_MODEL, text)) or _vector(module),
    )
    module._embed_query("Atlas status")
    module._embed_query("Atlas status")
    assert len(calls) == 1

    module.QWEN_QUERY_INSTRUCTION = module.QWEN_QUERY_INSTRUCTION + " Current facts only."
    module._embed_query("Atlas status")
    assert len(calls) == 2
    module.EMBED_MODEL = "test/embed-v2"
    module._embed_query("Atlas status")
    assert len(calls) == 3
    original_manifest = module._embedding_manifest
    monkeypatch.setattr(
        module, "_embedding_manifest",
        lambda: {**original_manifest(), "normalization_version": 999},
    )
    module._embed_query("Atlas status")
    assert len(calls) == 4
    assert module._EMBED_CACHE_METRICS["config_resets"] == 3
    assert len(module._EMBED_CACHE) == 1


def test_ttl_expiry_and_lru_capacity_trigger_only_required_calls(tmp_path, monkeypatch):
    module = _module(
        "memory_wiki_embed_cache_lru", tmp_path, monkeypatch, max_entries=2, ttl=60,
    )
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or _vector(module),
    )
    module._embed_query("alpha")
    module._embed_query("beta")
    module._embed_query("alpha")  # alpha is now most recently used
    module._embed_query("gamma")  # evicts beta
    module._embed_query("beta")   # network again; evicts alpha
    assert calls == ["alpha", "beta", "gamma", "beta"]
    assert len(module._EMBED_CACHE) == 2
    assert module._EMBED_CACHE_METRICS["evictions"] == 2

    with module._EMBED_CACHE_LOCK:
        key = module._embedding_cache_key("gamma", "search_query")
        _expiry, vector = module._EMBED_CACHE[key]
        module._EMBED_CACHE[key] = (-1.0, vector)
    module._embed_query("gamma")
    assert calls[-1] == "gamma"
    assert module._EMBED_CACHE_METRICS["expired"] == 1


def test_failed_embedding_is_never_cached(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_error", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or None,
    )
    assert module._embed_query("retry this query") is None
    assert module._embed_query("retry this query") is None
    assert calls == ["retry this query", "retry this query"]
    assert len(module._EMBED_CACHE) == 0
    assert module._EMBED_CACHE_METRICS["stores"] == 0


def test_secret_bearing_query_never_reaches_embedding_or_cache(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_privacy", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or _vector(module),
    )

    assert module._embed_query("find pass correct-horse-92841") is None
    assert module._embed_query("lookup token sk-test-1234567890abcdef") is None

    assert calls == []
    assert len(module._EMBED_CACHE) == 0
    assert module._EMBED_CACHE_METRICS["stores"] == 0


def test_concurrent_identical_queries_share_one_inflight_request(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_singleflight", tmp_path, monkeypatch)
    worker_count = 8
    barrier = threading.Barrier(worker_count + 1)
    producer_started = threading.Event()
    release_producer = threading.Event()
    calls = []
    call_lock = threading.Lock()

    def embed(text, **kwargs):
        with call_lock:
            calls.append(text)
        producer_started.set()
        assert release_producer.wait(3.0)
        return _vector(module, 0.75)

    monkeypatch.setattr(module, "_openrouter_embed", embed)
    results = [None] * worker_count

    def worker(index):
        barrier.wait()
        results[index] = module._embed_query("  shared\nquery ")

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(worker_count)]
    for thread in threads:
        thread.start()
    barrier.wait()
    assert producer_started.wait(2.0)
    deadline = time.time() + 2.0
    while module._EMBED_CACHE_METRICS["coalesced"] < worker_count - 1 and time.time() < deadline:
        time.sleep(0.005)
    release_producer.set()
    for thread in threads:
        thread.join(3.0)
        assert not thread.is_alive()

    assert calls == ["shared query"]
    assert results == [_vector(module, 0.75)] * worker_count
    assert module._EMBED_CACHE_METRICS["coalesced"] == worker_count - 1


def test_singleflight_follower_respects_active_prefetch_deadline(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_prefetch_budget", tmp_path, monkeypatch)
    producer_started = threading.Event()
    release_producer = threading.Event()
    calls = []

    def embed(text, **kwargs):
        calls.append(text)
        producer_started.set()
        assert release_producer.wait(3.0)
        return _vector(module, 0.5)

    monkeypatch.setattr(module, "_openrouter_embed", embed)
    owner_result = []
    owner = threading.Thread(
        target=lambda: owner_result.append(module._embed_query("budgeted shared query")),
    )
    owner.start()
    assert producer_started.wait(1.0)
    started = time.monotonic()
    with module._prefetch_budget(0.20):
        follower = module._embed_query("budgeted shared query")
    elapsed = time.monotonic() - started
    assert follower is None
    assert elapsed < 0.15
    assert calls == ["budgeted shared query"]
    assert module._EMBED_CACHE_METRICS["wait_timeouts"] == 1
    release_producer.set()
    owner.join(3.0)
    assert owner_result == [_vector(module, 0.5)]


def test_document_cache_is_exact_but_reuses_duplicate_index_work(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_document", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or _vector(module),
    )
    module._embed_document("table: A  B")
    module._embed_document("table: A  B")
    module._embed_document("table: A B")
    assert calls == ["table: A  B", "table: A B"]


def test_secret_bearing_document_never_reaches_embedding_or_cache(tmp_path, monkeypatch):
    module = _module("memory_wiki_embed_cache_document_privacy", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or _vector(module),
    )

    assert module._embed_document("service password=correct-horse-92841") is None

    assert calls == []
    assert len(module._EMBED_CACHE) == 0
    assert module._EMBED_CACHE_METRICS["stores"] == 0


def test_remote_plain_http_embedding_endpoint_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_EMBED_URL", "http://192.0.2.10/v1")
    module = _module("memory_wiki_embed_endpoint_privacy", tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "_openrouter_embed",
        lambda text, **kwargs: calls.append(text) or _vector(module),
    )

    assert module.EMBED_CONTRACT_VALID is False
    assert module._embed_query("safe lookup") is None
    assert module._embed_document("safe document") is None
    assert calls == []
