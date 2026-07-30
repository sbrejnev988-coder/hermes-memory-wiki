# Hermes Memory Wiki v1.20.2

Native structured long-term memory provider for Hermes Agent. SQLite claims are the source of truth; FTS5 and Qdrant are rebuildable retrieval indexes. 101 MCP tools.

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
  FTS5/BM25 + Qdrant embeddings → hydrate Qdrant-only claims from SQLite → RRF → Voyage/Cohere instruction-aware rerank → configurable diversity → structured XML
```

## Requirements

- Python 3.11+
- SQLite 3.35+ (FTS5)
- Qdrant (optional, for semantic search)
- OpenRouter API key (only when embeddings or rerank are enabled)
- `hermes_trust_core` and `hermes_core_loader` in `{HERMES_HOME}/lib` for the strict security-integrated build

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_WIKI_EMBED_PROVIDER` | `stub` | `openrouter` or local `stub` fallback |
| `MEMORY_WIKI_EMBED_URL` | provider-dependent | `https://openrouter.ai/api/v1` for `openrouter`, otherwise `http://127.0.0.1:4000` |
| `MEMORY_WIKI_EMBED_MODEL` | provider-dependent | `hash-ngram-2560` for `stub`; `qwen/qwen3-embedding-8b` for `openrouter` |
| `MEMORY_WIKI_EMBED_DIMENSIONS` | `2560` | Embedding response dimensions; must equal `MEMORY_WIKI_VECTOR_SIZE` |
| `MEMORY_WIKI_EMBED_INPUT_MAX_CHARS` | `12000` | Maximum document/query characters sent to the embedding endpoint; included in the embedding manifest |
| `MEMORY_WIKI_QDRANT_COLLECTION` | `memory_wiki_claims` | Collection name prefix |
| `MEMORY_WIKI_VECTOR_SIZE` | `2560` | Qdrant vector size; the local stub and provider response are validated against it |
| `MEMORY_WIKI_RERANK_ENABLED` | `false` | Enable second-stage reranking |
| `MEMORY_WIKI_RERANK_MODEL` | `voyageai/rerank-2.5` | Reranker model ID |
| `MEMORY_WIKI_RERANK_API_STYLE` | `auto` | `openrouter` or direct `voyage` payload style |
| `MEMORY_WIKI_RERANK_RULES_ENABLED` | auto for Voyage 2.5 | Prepend/append ranking rules to the query |
| `MEMORY_WIKI_RERANK_RULES_FILE` | (empty) | Relative/absolute JSON or text file with `default`, `technical`, `semantic`, `mixed` rules |
| `MEMORY_WIKI_RERANK_RULES_POSITION` | `prepend` | `prepend` or `append` |
| `MEMORY_WIKI_RERANK_SKIP_EXACT_TECHNICAL` | `false` with rules | Allow exact technical searches to bypass reranking |
| `MEMORY_WIKI_REINDEX_BATCH_SIZE` | `20` | Reindex checkpoint batch size |
| `MEMORY_WIKI_RERANK_API_KEY` | (uses `OPENROUTER_API_KEY`) | API key for reranker |
| `MEMORY_WIKI_QDRANT_API_KEY` | (empty) | Qdrant API key if auth enabled |
| `MEMORY_WIKI_PREFETCH_CLAIM_LIMIT` | `20` | Maximum main claims in automatic prompt-time recall |
| `MEMORY_WIKI_MAX_PREFETCH_CHARS` | `24000` | Character budget for automatic prompt-time recall |
| `MEMORY_WIKI_DIVERSITY_MAX_PER_TOPIC` | `8` | Maximum claims retained from one topic after reranking |
| `MEMORY_WIKI_DIVERSITY_MAX_SOURCE_SHARE` | `0.65` | Source-share threshold that applies a soft score penalty |
| `MEMORY_WIKI_CONTEXT_MAX_TOKENS` | `6000` | Token budget for structured context packer |
| `MEMORY_WIKI_CONTEXT_MAX_CLAIMS` | `24` | Max claims in structured context packer |
| `MEMORY_WIKI_CONTEXT_MAX_PER_TOPIC` | `8` | Max claims from one topic in structured context packer |
| `MEMORY_WIKI_SIMHASH_MAX_DISTANCE` | `3` | Conservative 64-bit near-duplicate threshold |
| `HERMES_SECURITY_STRICT` | `1` | Quarantine recalled content if the shared trust core fails |
| `HERMES_HOME` | `~/.hermes` | Hermes data directory (DB at `{HERMES_HOME}/memory-wiki/memory_wiki.sqlite3`) |


## Recall expansion in v1.18.5

- Qdrant-only matches are now hydrated from SQLite before scoring. SQLite remains the source of truth; Qdrant contributes IDs and similarity scores.
- Automatic `prefetch()` now uses configurable claim and character budgets instead of fixed `10` and `12000` limits.
- The hard three-claims-per-topic diversity cap is configurable and defaults to eight, preserving coherent PPLX result sets while retaining a bounded context.
- Existing reindex and atomic alias-switch behavior is unchanged. Reindex is still required after changing embedding model or vector dimensions.

Recommended starting values for `perplexity/pplx-embed-v1-4b`:

```env
MEMORY_WIKI_EMBED_PROVIDER=openrouter
MEMORY_WIKI_EMBED_MODEL=perplexity/pplx-embed-v1-4b
MEMORY_WIKI_EMBED_DIMENSIONS=2560
MEMORY_WIKI_VECTOR_SIZE=2560
MEMORY_WIKI_VECTOR_TOP_K=200
MEMORY_WIKI_PREFETCH_CLAIM_LIMIT=20
MEMORY_WIKI_MAX_PREFETCH_CHARS=24000
MEMORY_WIKI_DIVERSITY_MAX_PER_TOPIC=8
MEMORY_WIKI_CONTEXT_MAX_TOKENS=6000
MEMORY_WIKI_CONTEXT_MAX_CLAIMS=24
MEMORY_WIKI_CONTEXT_MAX_PER_TOPIC=8
```

## Installation

```bash
# Clone into Hermes plugins directory
cd ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git memory-wiki

# The security-integrated build also requires these files:
#   ~/.hermes/lib/hermes_core_loader.py
#   ~/.hermes/lib/hermes_trust_core.py
#   ~/.hermes/lib/hermes_secret_core.py (pinned by the loader)

# Restart Hermes gateway
glinomes restart
```

Before restart, run `python3 -m py_compile __init__.py collapse.py extractor.py decay.py`.

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
| `memory_wiki_query_secrets` | Query safe secret metadata; secret writes remain local-admin only |
| `memory_wiki_update_claim` | Update claim fields |
| `memory_wiki_apply_user_correction` | Apply user correction |

### Retrieval tools
| Tool | Description |
|---|---|
| `memory_wiki_query` | FTS5 + Qdrant hybrid search with RRF + instruction-aware rerank + diversity |
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

Full list: 101 tools in `plugin.yaml` (generated from `get_tool_schemas()`).

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
# After changing the model, dimensions, input limit, document prefix or
# document template, the manifest selects a new immutable collection.

# Run resumable reindex:
memory_wiki_reindex({"force": False})
# → creates/resumes memory_wiki_claims_{new_hash}
# → retries failed claim IDs before continuing the source scan
# → reconciles claim IDs and vector-text hashes against SQLite
# → atomically switches the alias only after a complete, revision-stable build
# → old active collection remains available until the switch

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


## 2560-dimensional migration note

This build uses a strict `2560 = 2560` dimensional contract for both `MEMORY_WIKI_EMBED_DIMENSIONS` and `MEMORY_WIKI_VECTOR_SIZE`. Here `2560` is the length of every vector, not the number of Qdrant points. The local `stubs/embed_stub.py` reports its dimension and actual hashing model in `/health`; Memory Wiki refuses semantic indexing when the provider/Qdrant dimensions differ or the bundled hash-stub model identity is inconsistent. Embedding values are also rejected when they are non-numeric or contain `NaN`/`Inf`.

Do not replace plugin files while a reindex call is actively running. Let the current call finish, stop/restart the gateway, install this build, then start the new manifest reindex. The installer included in the release package checks `reindex_jobs` and refuses installation while a running job is recorded unless explicitly overridden.

The embedding manifest was upgraded to v2 and now includes the input character limit and document-prefix hash. Query-instruction changes are tracked but intentionally excluded from the physical collection hash, because they do not change stored document vectors. Therefore a reindex that started with the previous code belongs to the previous physical collection. It may finish safely and remain active, but after installing this build run `memory_wiki_reindex({"force": false})` until `status="completed"`. The alias is not switched during a partial rebuild.

`memory_wiki_semantic_status` now exposes the configured provider/model, embedding and Qdrant dimensions, contract validity, input limit and manifest hash for deployment diagnostics.

## Rerank rules

`voyageai/rerank-2.5` receives rules inside the query. Candidate documents now include safe claim metadata and, when present, `repository_id`, `file_path`, `symbol_id`, commit and content hashes from `code_claim_metadata`. Candidate text is secret-scanned/redacted before the remote call.

A rules file may be placed next to `__init__.py`:

```json
{
  "default": "Prefer current, verified and specific claims.",
  "technical": "Prefer exact repository, file, symbol, error, version and content-hash matches.",
  "semantic": "Prefer explicit user facts, corrections, active decisions and durable preferences.",
  "mixed": "Balance exact matches with semantic usefulness."
}
```

Set `MEMORY_WIKI_RERANK_RULES_FILE=rerank-rules.json` to load it. Environment variables override the file.

## Embedding provider routing (v1.18.6)

`perplexity/pplx-embed-v1-4b` is a remote OpenRouter model. It is used only when the **running Hermes gateway process** has all of the following effective values:

```env
MEMORY_WIKI_EMBED_PROVIDER=openrouter
MEMORY_WIKI_EMBED_URL=https://openrouter.ai/api/v1
MEMORY_WIKI_EMBED_MODEL=perplexity/pplx-embed-v1-4b
MEMORY_WIKI_EMBED_DIMENSIONS=2560
MEMORY_WIKI_VECTOR_SIZE=2560
```

Setting only the model slug while leaving `MEMORY_WIKI_EMBED_PROVIDER=stub` does not call PPLX. v1.18.6 detects that mismatch, disables semantic operations with an explicit diagnostic, and prevents a misleading reindex. `memory_wiki_semantic_status` now reports the effective provider, URL, API-key presence, and configuration errors.

The bundled `stubs/embed_stub.py` is a deterministic local fallback, not an ML model. It now defaults to 2560 dimensions, honors the request `dimensions` field, and reports `algorithm`, `model`, and `vector_size` from `/health`.


## Document indexing support (v1.20.2)

The document graph distinguishes **discovered**, **metadata-only**, **unsupported**, **encrypted**, and **content-indexed** files. A supported extension no longer implies that body text was extracted.

| Format family | Body indexing | Requirements / limitations |
|---|---|---|
| TXT, Markdown, JSON/JSONL, XML/HTML, CSV/TSV, RTF, config/log/source-like text | Native | Standard-library parser; CSV/TSV is streamed and bounded. |
| DOCX/DOCM/DOTX, XLSX/XLSM/XLTX, PPTX/PPTM/POTX | Native | OOXML ZIP/XML parser; macros are not executed. XLSX sheet names are resolved through workbook relationships. |
| ODT/ODS/ODP/ODG and templates | Native | ODF ZIP/XML parser. |
| EML, EPUB | Native | Addressable headers/body/chapters where available. |
| PDF | Conditional | PyMuPDF or pypdf; scanned pages need OCR. Encrypted files are reported as `encrypted`. |
| PNG/JPEG/TIFF/BMP/WebP | Conditional | Requires OCR enabled and local Tesseract. Otherwise `metadata_only`. |
| DOC/XLS/PPT, MSG, VSD, PUB, WPS, Pages/Numbers/Keynote | Conditional | Requires an explicitly configured **loopback-only** Apache Tika server. Redirects are refused. |
| GDOC/GSHEET/GSLIDES/GDRAW pointer files | Metadata only | These local files contain links/metadata, not the remote Google document body. Export the document or add an authenticated Google Drive ingestion connector to index its content. |

Operational notes:

- `memory_wiki_document_scan` reports missing previously indexed files; deletion is applied only with `prune_missing=true`.
- Automatic prompt-time document prefetch is restricted to global-scope material. Scoped material must be queried with an explicit scope.
- Changing `scope_id` or `repository_id` on an unchanged file updates the stored identity and queues fresh embeddings instead of silently returning `unchanged`.
- Parser metadata is recursively bounded and secret-redacted before SQLite storage or tool output.
- Document workers receive a minimal environment rather than API keys, tokens, proxy variables, and unrelated Hermes secrets.

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
- Remote reranker has retries, circuit breaker, cache and fallback to RRF scoring
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
- runtime `_migrate()` is authoritative; `schema.sql` is only a legacy/reference snapshot

## Advanced: Embedding manifest

When the document-vector contract changes (model, dimensions, input limit, document prefix or template):
1. `_check_manifest_change()` detects the physical document-vector difference on init
2. Logs: `Embedding manifest changed. Run memory_wiki_reindex to migrate.`
3. Old collection preserved, new collection named `memory_wiki_claims_{new_hash}`
4. After reindex: `_switch_alias()` atomically switches `memory_wiki_claims_active`
5. Old collection can be deleted manually after verification

## Performance

Latency and reindex duration depend on the embedding provider, Qdrant placement, candidate count and hardware. The bounded rerank top-K, cache, circuit breaker and resumable reindex checkpoints are intended to keep degradation controlled; measure on the actual deployment rather than relying on fixed timing estimates.

## License

MIT


## Audit fix r1 (2026-07-29)

This source package includes the runtime modules required by the advertised code and document graph tools. `plugin.yaml`, the MCP schema cache and the Python provider are generated from the same 101-schema source. `memory_wiki_compare_search` now performs real FTS-only, vector-only and hybrid runs without mutating process-wide environment variables. Backup restore validates archive entry count, uncompressed size, member size and compression ratio before creating a safety backup or writing staged files.
