# Hermes Memory Wiki v1.16.1

Native structured long-term memory provider for Hermes Agent. SQLite claims are the source of truth; FTS5 and Qdrant are rebuildable retrieval indexes.

## Retrieval pipeline

```text
SQLite FTS5/BM25 + PPLX embeddings/Qdrant
                    ↓
                 RRF fusion
                    ↓
             safe top-30 candidates
                    ↓
     optional Cohere Rerank 4 Pro via OpenRouter
                    ↓
           weighted reciprocal-rank fusion
```

The reranker is optional and **disabled by default**. It never replaces base retrieval: any timeout, malformed response, rate limit or open circuit returns the original RRF ranking.

## Enable or disable reranking

```env
# Disable completely — no rerank HTTP request is made (public default)
MEMORY_WIKI_RERANK_ENABLED=0

# Enable OpenRouter Cohere reranking
MEMORY_WIKI_RERANK_ENABLED=1
MEMORY_WIKI_RERANK_URL=https://openrouter.ai/api/v1/rerank
MEMORY_WIKI_RERANK_MODEL=cohere/rerank-4-pro
MEMORY_WIKI_RERANK_TOP_K=30
MEMORY_WIKI_RERANK_MIN_CANDIDATES=10
MEMORY_WIKI_RERANK_TIMEOUT=4
MEMORY_WIKI_RERANK_CACHE_TTL=1800
MEMORY_WIKI_RERANK_CACHE_MAX=256
MEMORY_WIKI_RERANK_CIRCUIT_FAILURES=3
MEMORY_WIKI_RERANK_CIRCUIT_SECONDS=300
```

The implementation uses the existing `OPENROUTER_API_KEY`, or `MEMORY_WIKI_RERANK_API_KEY` when explicitly provided. Environment variables are read when the plugin loads; after changing the toggle restart Hermes:

```bash
hermes gateway restart
```

OpenRouter reports `$0.0025` per `cohere/rerank-4-pro` search. Cache hits do not create a new search unit.

## Smart conditions

Reranking is skipped when disabled, no key exists, the query is shorter than 12 or longer than 1500 characters, fewer than 10 safe candidates exist, an exact/BM25-dominant technical result exists, or the circuit breaker is open. Before egress, non-active, secret-risk, quarantined, raw-log, ephemeral and raw-secret candidates are filtered again. Sent documents contain only redacted `topic + type + claim`, capped at 1400 characters.

Cohere weight is 0.75 for semantic, 0.60 for mixed and 0.35 for technical queries. The original rank always contributes to final reciprocal-rank fusion.

## Core configuration

```env
MEMORY_WIKI_SEMANTIC=1
MEMORY_WIKI_EMBED_PROVIDER=openrouter
MEMORY_WIKI_EMBED_MODEL=perplexity/pplx-embed-v1-4b
MEMORY_WIKI_EMBED_DIMENSIONS=2560
MEMORY_WIKI_VECTOR_SIZE=2560
MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333
```

## Safety and resilience

- SQLite remains authoritative; vectors are rebuildable.
- Reranker failure is fail-open.
- 30-minute bounded in-memory cache.
- Three failures open a five-minute circuit breaker.
- Secret/quarantine/raw candidates are excluded before external egress.
- All numeric environment settings use bounded safe parsers.
- `memory_wiki_semantic_status` reports reranker requests, successes, failures, cache hits, cost and circuit state.

## Tests

```bash
python3 -m py_compile __init__.py scripts/test_rerank.py
python3 scripts/test_rerank.py
```

The targeted test verifies disabled mode (zero HTTP calls), semantic reordering, cache reuse, exact technical skip, secret candidate filtering and fail-open timeout behavior.

## License

MIT.
