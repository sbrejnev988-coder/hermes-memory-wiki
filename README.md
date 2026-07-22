# Hermes Memory Wiki v1.18.3

Native structured long-term memory provider for Hermes Agent. SQLite claims are the source of truth; FTS5 and Qdrant are rebuildable retrieval indexes. 88 MCP tools.

## Architecture

```
Write path (transactional):
  _add_claim → with c: (единая SQLite TX)
    → INSERT/UPDATE claim + evidence + history
    → _audit(conn=c)
    → _record_mutation(conn=c)
    → _outbox_enqueue("embed_and_upsert", conn=c)  — задача без вектора
    → _resolve_temporal + _apply_supersession(conn=c)
    → COMMIT всех 7 частей

Outbox worker (async):
  → читает pending embed_and_upsert
  → _embed_document(text)
  → _qdrant_upsert → memory_wiki_claims_active alias
  → статус: completed / failed (5 попыток)

Retrieval pipeline:
  FTS5/BM25 + Qdrant/PPLX → RRF → Cohere rerank → diversity → structured XML
```

## Requirements

- Python 3.11+
- SQLite 3.35+ (FTS5)
- Qdrant (optional, for semantic search)
- OpenRouter API key (for embeddings + Cohere rerank)

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_WIKI_EMBED_PROVIDER` | `openrouter` | `openrouter` or `stub` |
| `MEMORY_WIKI_EMBED_MODEL` | `perplexity/pplx-embed-v1-4b` | Embedding model |
| `MEMORY_WIKI_EMBED_DIMENSIONS` | `2560` | Vector dimensions |
| `MEMORY_WIKI_QDRANT_COLLECTION` | `memory_wiki_claims` | Collection name prefix |
| `MEMORY_WIKI_VECTOR_SIZE` | `2560` | Must match EMBED_DIMENSIONS |
| `MEMORY_WIKI_RERANK_ENABLED` | `true` | Enable Cohere rerank |
| `MEMORY_WIKI_RERANK_MODEL` | `cohere/rerank-4-pro` | Reranker model ID |
| `MEMORY_WIKI_RERANK_API_KEY` | (uses `OPENROUTER_API_KEY`) | API key for reranker |
| `MEMORY_WIKI_QDRANT_API_KEY` | (empty) | Qdrant API key if auth enabled |
| `MEMORY_WIKI_CONTEXT_MAX_TOKENS` | `4000` | Token budget for context packer |
| `MEMORY_WIKI_CONTEXT_MAX_CLAIMS` | `16` | Max claims in packed context |
| `HERMES_HOME` | `~/.hermes` | Hermes data directory (DB at `{HERMES_HOME}/memory-wiki/memory_wiki.sqlite3`) |

## Installation

```bash
# Clone into Hermes plugins directory
cd ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git memory-wiki

# Restart Hermes gateway
glinomes restart
```

On first init the plugin creates:
- `{HERMES_HOME}/memory-wiki/memory_wiki.sqlite3` — SQLite database (source of truth)
- Qdrant collection `memory_wiki_claims_{manifest_hash_12chars}`
- Qdrant alias `memory_wiki_claims_active` → physical collection

## Key MCP tools

### Write tools
| Tool | Description |
|---|---|
| `memory_wiki_add_claim` | Add/update a structured durable claim |
| `memory_wiki_add_evidence` | Attach evidence to a claim |
| `memory_wiki_add_secret` | Store credential/secret index entry (redacted at rest) |
| `memory_wiki_update_claim` | Update claim fields |
| `memory_wiki_apply_user_correction` | Apply user correction |

### Retrieval tools
| Tool | Description |
|---|---|
| `memory_wiki_query` | FTS5 + Qdrant hybrid search with RRF + Cohere rerank + diversity |
| `memory_wiki_pack_context` | Budget-aware context packer with structured XML output |
| `memory_wiki_debug_search` | Full breakdown: FTS rank, vector rank, RRF score per claim |
| `memory_wiki_compare_search` | Compare FTS-only vs vector-only vs hybrid |
| `memory_wiki_semantic_status` | Qdrant health and point count |
| `memory_wiki_recent_changes` | Recently modified claims |
| `memory_wiki_preference_layer` | Prioritized durable user preferences |

### Lifecycle tools
| Tool | Description |
|---|---|
| `memory_wiki_reindex` | Resumable reindex with checkpointing and atomic alias switch |
| `memory_wiki_decay_scan` | Exponential decay scoring for stale claims |
| `memory_wiki_decay_archive` | Archive claims below decay threshold |
| `memory_wiki_gc` | Garbage collect stale/low-salience claims |
| `memory_wiki_doctor` | Self-diagnostic: journal, schema, orphan detection |
| `memory_wiki_health` | Database statistics and FTS index status |
| `memory_wiki_snapshot` | Full DB snapshot export |

### Code intelligence (Phase 4)
| Tool | Description |
|---|---|
| `memory_wiki_code_claim_add` | Code-linked claim with repository/symbol/revision metadata |
| `memory_wiki_code_claim_query` | Query by repository_id, file_path, or symbol_id |
| `memory_wiki_symbol_history` | Revision history for a specific symbol |
| `memory_wiki_repository_context` | All code-linked claims for a repository |
| `memory_wiki_invalidate_revision` | Mark claims stale after symbol/file change |
| `memory_wiki_patch_outcome_add` | Record patch application outcome |

### Graph & entity tools
| Tool | Description |
|---|---|
| `memory_wiki_add_entity` | Add named entity with aliases |
| `memory_wiki_add_relation` | Add directed relation between entities |
| `memory_wiki_graph_query` | Query entity graph |

Full list: 88 tools in `plugin.yaml`.

## Usage examples

### Basic write → read cycle
```python
# Hermes auto-uses these; shown for reference
memory_wiki_add_claim({
    "claim": "OpenClaw proxy uses port 18089 for DeepSeek models",
    "topic": "proxy",
    "confidence": 0.9,
    "evidence": "verified via curl http://127.0.0.1:18089/health"
})

memory_wiki_query({
    "query": "What port does the proxy use?"
})
# → returns matching claim via FTS5 + Qdrant hybrid search
```

### Code-linked claims
```python
memory_wiki_code_claim_add({
    "claim": "parseFile uses enhanced regex parser v0.4.0 with parser metadata",
    "repository_id": "sbrejnev988-coder/mcp-code-shrinker",
    "commit_sha": "1d07c47abc123",
    "file_path": "src/core/ast-engine.js",
    "symbol_id": "sym_parseFile",
    "claim_type": "code_claim"
})

memory_wiki_code_claim_query({
    "repository_id": "sbrejnev988-coder/mcp-code-shrinker",
    "limit": 5
})
```

### Temporal supersession
```python
# Old claim
memory_wiki_add_claim({
    "claim": "Hermes uses Qwen3-Embedding-8B model",
    "topic": "embeddings"
})

# New claim — auto-supersedes old
memory_wiki_add_claim({
    "claim": "Hermes now uses perplexity/pplx-embed-v1-4b instead of Qwen",
    "topic": "embeddings"
})
# → old claim: temporal_status='superseded', status='archived'
# → new claim: temporal_status='current'
```

### Reindex after embedding model change
```python
# After changing MEMORY_WIKI_EMBED_MODEL or dimensions:
# Manifest auto-detects change → logs migration hint on init

# Run resumable reindex:
memory_wiki_reindex({"force": True})
# → creates new collection memory_wiki_claims_{new_hash}
# → batches of 20 with checkpointing
# → atomic alias switch on completion (95%+ success)
# → old collection preserved for rollback

# For incremental (process N claims at a time):
memory_wiki_reindex({"limit": 100})
# → resumes from last checkpoint
```

### Feedback loop
```python
# Record feedback on retrieved claims after actual usage
memory_wiki_query({"query": "proxy port"})
# → retrieval counts updated (recall_count++, no usefulness penalty)

# After answer evaluation (manual or via answer evaluator):
# recall_feedback table has full lifecycle:
# retrieved → injected → used → helpful/irrelevant/harmful
```

## Recovery

### After process crash during write
The transactional outbox ensures claim writes and index tasks are atomic:
- Claim + evidence + history + outbox → one SQLite COMMIT
- If process crashes before COMMIT → nothing saved (rollback)
- If process crashes after COMMIT → all 4 parts persisted
- Outbox worker picks up pending tasks on next run

### After Qdrant/OpenRouter outage
- FTS5 search continues working without Qdrant
- Outbox tasks remain pending (retry up to 5 times)
- Cohere reranker has circuit breaker + cache + fallback to RRF scoring
- `memory_wiki_reindex` has resumable checkpoints

### Database maintenance
```python
memory_wiki_doctor()  # Self-diagnostic
memory_wiki_gc({"dry_run": True})  # Preview stale claims
memory_wiki_gc({"dry_run": False})  # Archive stale claims
```

## Schema versioning

Database migrations are fully automated via `_migrate()`:
- All schema changes via `ALTER TABLE ADD COLUMN` (safe for existing DBs)
- Schema compatibility checks on startup
- `schema.sql` serves as canonical reference

## Advanced: Embedding manifest

When embedding model, dimensions, or query instruction changes:
1. `_check_manifest_change()` detects the difference on init
2. Logs: `Embedding manifest changed. Run memory_wiki_reindex to migrate.`
3. Old collection preserved, new collection named `memory_wiki_claims_{new_hash}`
4. After reindex: `_switch_alias()` atomically switches `memory_wiki_claims_active`
5. Old collection can be deleted manually after verification

## Performance

- FTS5 retrieval: ~1-5ms per query
- Qdrant search: ~50-200ms (depends on collection size and network)
- Cohere rerank: ~200-500ms (cached for repeated queries)
- Structured XML packing: ~5-10ms
- Full reindex (2000 claims): ~10-15 minutes with batch size 20

## License

MIT
