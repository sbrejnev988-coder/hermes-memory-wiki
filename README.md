# Hermes Memory Wiki v1.21.0

Native structured long-term memory provider for Hermes Agent. SQLite claims are the source of truth; FTS5 and Qdrant are rebuildable retrieval indexes. 101 MCP tools.

## Cache identity (r19 + r20)

- **r19 token governor**: exact embedding reuse inside the provider process; tool-cache contract 2.4.0 with smart initial tool mode (≤24 tools), exact-cache with tools enabled, shadow semantic mode by default.
- **r20 partitioned cache**: cache signature is scoped per visibility component (`shared` / `bot:` / `project:` / `private:<chat_hash>`). A write in project B no longer invalidates project A / private / bot cache entries. Contract: `memory-cache-state-v3-r20-partitioned` with per-component revisions bumped on upsert / add_evidence / update_claim / set_status_by_text.

- **r21 repository scope + FTS repair**: code-claim search is project-scoped with `include_all_projects` opt-in — the classifier (not SQL) decides `foreign_repository` / `exact_content_hash_match` suppression; code-claim manifest guard rejects stale/invalid manifests; automatic FTS5 corruption detection and rebuild.

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
  → embedding-вызовы: 3 попытки с экспоненциальным backoff (1s/2s) на 429/5xx;
    curl-fallback проверяет HTTP-статус (rc=0 на 4xx/5xx больше не считается успехом)

Retrieval pipeline:
  FTS5/BM25 + Qdrant embeddings → hydrate Qdrant-only claims from SQLite → RRF → Voyage/Cohere instruction-aware rerank → configurable diversity → structured XML
```

## Secret-context bridge (r5)

Memory Wiki keeps `secret_index` as its local safe metadata index, but it can now also read through an installed secret-context plugin when a context exists only in that plugin or its vault. External search results are recursively redacted and are not copied into SQLite, FTS5, Qdrant, dashboards, or markdown pages.

- `memory_wiki_query_secrets` merges local `sec_*` metadata with safe external matches.
- External matches include `origin=secret_context` and `lookup_key`; use the dedicated `secret_context_lookup` tool for the actual context.
- `secret_context_lookup` and `secret_context_search` are patched at registration time to serialize non-string results as JSON strings, as required by Hermes/OpenAI-compatible tool messages.
- The bridge invokes only `secret_context_search`; it never calls lookup/reveal itself.
- Disable read-through with `MEMORY_WIKI_SECRET_CONTEXT_BRIDGE=0`.
- Set an explicit plugin path with `MEMORY_WIKI_SECRET_CONTEXT_PLUGIN=/root/.hermes/plugins/<plugin>/__init__.py`.
- Automatic plugin discovery stays inside the active Hermes profile. A plugin in a different profile is used only through that explicit path setting.

Plaintext returned intentionally by `secret_context_lookup` can still enter the model's tool history. For login flows, a domain-bound executor that consumes a secret reference directly remains safer than revealing plaintext to the model.

## Requirements

- Python 3.11+
- SQLite 3.35+ (FTS5)
- Qdrant (optional, for semantic search)
- OpenRouter API key (only when embeddings or rerank are enabled)
- `NOUS_API_KEY` (only when `MEMORY_WIKI_EMBED_PROVIDER=nous` — https://inference-api.nousresearch.com)
- `hermes_trust_core` and `hermes_core_loader` in `{HERMES_HOME}/lib` for the strict security-integrated build

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_WIKI_EMBED_PROVIDER` | `openrouter` | `openrouter`, `nous`, or local `stub` fallback |
| `MEMORY_WIKI_EMBED_URL` | provider-dependent | OpenRouter for `openrouter`, Nous inference API for `nous`, otherwise `http://127.0.0.1:4000` |
| `MEMORY_WIKI_EMBED_MODEL` | provider-dependent | `qwen/qwen3-embedding-8b` for `openrouter`/`nous`; `hash-ngram-4096` for `stub` |
| `MEMORY_WIKI_EMBED_DIMENSIONS` | `4096` | Embedding response dimensions; must equal `MEMORY_WIKI_VECTOR_SIZE` |
| `MEMORY_WIKI_EMBED_INPUT_MAX_CHARS` | `12000` | Maximum document/query characters sent to the embedding endpoint; included in the embedding manifest |
| `MEMORY_WIKI_QDRANT_COLLECTION` | `memory_wiki_claims` | Collection name prefix |
| `MEMORY_WIKI_VECTOR_SIZE` | `4096` | Qdrant vector size; the local stub and provider response are validated against it |
| `MEMORY_WIKI_RERANK_ENABLED` | `false` | Enable second-stage reranking |
| `MEMORY_WIKI_RERANK_TIMEOUT` | `3.0` | Per-request rerank timeout; runtime hard-caps it at 3 seconds |
| `MEMORY_WIKI_RERANK_RETRY_COUNT` | `1` | Compatibility setting; prompt-time reranking is always single-attempt |
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
| `MEMORY_WIKI_PREFETCH_DEADLINE_SECONDS` | `5.5` | Hard prompt-time budget, clamped to 5–6 seconds |
| `MEMORY_WIKI_PREFETCH_NETWORK_RESERVE_SECONDS` | `0.25` | Time reserved after every bounded network operation |
| `MEMORY_WIKI_PREFETCH_FALLBACK_RESERVE_SECONDS` | `0.45` | Tail budget reserved for local FTS/SQLite fallback |
| `MEMORY_WIKI_MAX_PREFETCH_CHARS` | `24000` | Character budget for automatic prompt-time recall |
| `MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CLAIMS` | `4` | Soft minimum of relevant, guard-safe claims; never pads with unrelated/quarantined rows |
| `MEMORY_WIKI_PREFETCH_MIN_RELEVANT_CHARS` | `2000` | Soft relevant-content target used for shortfall diagnostics |
| `MEMORY_WIKI_PREFETCH_EXPANSION_FACTOR` | `3` | Candidate-pool multiplier, capped at 50 rows |
| `MEMORY_WIKI_PREFETCH_DIAGNOSTICS` | `anomalies` | `off`, `anomalies`, or `always`; records searched/rendered/quarantined/size |
| `MEMORY_WIKI_PREFETCH_CLAIM_MAX_CHARS` | `1200` | Maximum sanitized text per rendered claim |
| `MEMORY_WIKI_PREFETCH_EVIDENCE_MAX_CHARS` | `600` | Maximum guard-safe evidence text per claim |
| `MEMORY_WIKI_DIVERSITY_MAX_PER_TOPIC` | `8` | Maximum claims retained from one topic after reranking |
| `MEMORY_WIKI_DIVERSITY_MAX_SOURCE_SHARE` | `0.65` | Source-share threshold that applies a soft score penalty |
| `MEMORY_WIKI_CONTEXT_MAX_TOKENS` | `6000` | Token budget for structured context packer |
| `MEMORY_WIKI_CONTEXT_MAX_CLAIMS` | `24` | Max claims in structured context packer |
| `MEMORY_WIKI_CONTEXT_MAX_PER_TOPIC` | `8` | Max claims from one topic in structured context packer |
| `MEMORY_WIKI_SIMHASH_MAX_DISTANCE` | `3` | Conservative 64-bit near-duplicate threshold |
| `HERMES_SECURITY_STRICT` | `1` | Quarantine recalled content if the shared trust core fails |
| `HERMES_HOME` | `~/.hermes` | Hermes data directory (DB at `{HERMES_HOME}/memory-wiki/memory_wiki.sqlite3`) |

## Bounded prompt-time recall

- `prefetch()` returns within the configured 5–6 second hard budget. A daemon worker is cancelled logically at the deadline, and a small guard-checked local FTS/SQLite result is returned instead.
- OpenRouter `/models`/embedding health is **stale-while-revalidate**: prefetch immediately uses the last known state while a daemon thread refreshes stale health in the background. Cold start is optimistic and the bounded embedding call remains authoritative.
- Embedding and Qdrant HTTP timeouts are clamped to the remaining prefetch budget. Prompt-time embedding is single-attempt; any failure continues through lexical SQLite/FTS retrieval.
- Prompt-time reranking is one attempt with a hard maximum of 3 seconds. Timeout/error returns the local RRF order rather than empty recall.
- First-class active `preference_rules` with `system`, `user*`, `explicit*`, or `correction*` provenance are rendered separately in `# Trusted User Preference Layer` inside the real provider `system_prompt_block`. Ordinary recalled claims remain untrusted data and are never promoted into directives.
- A cancelled late worker does not acknowledge the revision watermark, so claims that were not injected remain eligible on the next turn.


## Recall expansion (v1.18.5 — historical notes)

> Текущий контракт по умолчанию — **4096D** (`qwen/qwen3-embedding-8b` для `openrouter`/`nous`). Секция ниже описывает поведение, добавленное в v1.18.5; рекомендации по конфигу обновлены под актуальные дефолты.

- Qdrant-only matches are now hydrated from SQLite before scoring. SQLite remains the source of truth; Qdrant contributes IDs and similarity scores.
- Automatic `prefetch()` now uses configurable claim and character budgets instead of fixed `10` and `12000` limits.
- The hard three-claims-per-topic diversity cap is configurable and defaults to eight, preserving coherent PPLX result sets while retaining a bounded context.
- Existing reindex and atomic alias-switch behavior is unchanged. Reindex is still required after changing embedding model or vector dimensions.

Recommended starting values (4096-dim contract):

```env
MEMORY_WIKI_EMBED_PROVIDER=nous            # или openrouter
MEMORY_WIKI_EMBED_MODEL=qwen/qwen3-embedding-8b
MEMORY_WIKI_EMBED_DIMENSIONS=4096
MEMORY_WIKI_VECTOR_SIZE=4096
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
hermes gateway restart

# Windows (PowerShell):
#   cd $env:USERPROFILE\.hermes\plugins
#   git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git memory-wiki
#   hermes gateway restart
```

Before restart, run `python3 -m py_compile __init__.py collapse.py extractor.py decay.py`.

On first init the plugin creates:
- `{HERMES_HOME}/memory-wiki/memory_wiki.sqlite3` — SQLite database (source of truth)
- Qdrant collection `memory_wiki_claims_{manifest_hash_12chars}`
- Qdrant alias `memory_wiki_claims_active` → physical collection

## Optional external MCP wrapper

The normal Hermes integration is the **exclusive `memory-wiki` memory provider**;
it is activated by `memory.provider: memory-wiki` and already exposes the native
tool schemas. Do **not** add the wrapper as another MCP server in that same
Hermes process unless duplicate tools are intentional.

Use `mcp-wrapper/server.py` only when a different MCP client needs access to
Memory Wiki. Configure that client to launch the wrapper over stdio and pass
the active profile paths explicitly (Hermes filters child environments, and the
Windows profile home is not necessarily `~/.hermes`):

```json
{
  "command": "python",
  "args": ["/absolute/path/to/memory-wiki/mcp-wrapper/server.py"],
  "env": {
    "HERMES_HOME": "/absolute/path/to/active/hermes-home",
    "MW_PLUGIN_PATH": "/absolute/path/to/memory-wiki/__init__.py"
  }
}
```

- Wrapper names are `mw_*` (for example, `memory_wiki_query` becomes
  `mw_query`); native provider names remain `memory_wiki_*`.
- `tools/list` rebuilds a **runtime** schema cache at
  `{HERMES_HOME}/cache/memory-wiki/mcp-tool-schemas.json`; it never rewrites
  the packaged `mcp-wrapper/tool_schemas.json`. Set `MW_MCP_SCHEMA_CACHE` only
  when a different runtime-cache location is required.
- The wrapper implements stdio JSON-RPC initialization, tool discovery and tool
  calls. Its actual tool schemas are still sourced from
  `MemoryWikiProvider.get_tool_schemas()`.

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


## Vector-dimension contract

The current defaults use a strict `4096 = 4096` dimensional contract for both `MEMORY_WIKI_EMBED_DIMENSIONS` and `MEMORY_WIKI_VECTOR_SIZE`. Here `4096` is the length of every vector, not the number of Qdrant points. If you intentionally select a 2560-dimensional embedding model, set both values to `2560` and run a manifest reindex. The local `stubs/embed_stub.py` reports its dimension and actual hashing model in `/health`; Memory Wiki refuses semantic indexing when the provider/Qdrant dimensions differ or the bundled hash-stub model identity is inconsistent. Embedding values are also rejected when they are non-numeric or contain `NaN`/`Inf`.

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

### Nous provider (v1.20.5+)

`MEMORY_WIKI_EMBED_PROVIDER=nous` подключает `qwen/qwen3-embedding-8b` через inference-api.nousresearch.com (подписка Nous):

```env
MEMORY_WIKI_EMBED_PROVIDER=nous
MEMORY_WIKI_EMBED_URL=https://inference-api.nousresearch.com/v1
MEMORY_WIKI_EMBED_MODEL=qwen/qwen3-embedding-8b
MEMORY_WIKI_EMBED_DIMENSIONS=4096
MEMORY_WIKI_VECTOR_SIZE=4096
```

Для провайдера `nous` API-ключ берётся из `NOUS_API_KEY` (приоритет) или `MEMORY_WIKI_EMBED_API_KEY`. inference-api блокирует Python urllib по TLS-отпечатку (Cloudflare 1010 `browser_signature_banned`), поэтому запросы идут через системный `curl` — он доступен в Termux, proot, Linux, macOS и Windows 10+. Модель проверяется через `GET /models?output_modalities=embeddings`; если её нет в списке, endpoint probing эмбеддингом.


## Document indexing support (v1.21.0)

The document graph distinguishes **discovered**, **metadata-only**, **unsupported**, **encrypted**, and **content-indexed** files. A supported extension no longer implies that body text was extracted.

| Format family | Body indexing | Requirements / limitations |
|---|---|---|
| TXT, Markdown, JSON/JSONL, XML/HTML, CSV/TSV, RTF, config/log/source-like text | Native | Standard-library parser with file-size, unit and worker memory/output limits. |
| DOCX/DOCM/DOTX, XLSX/XLSM/XLTX, PPTX/PPTM/POTX | Native | OOXML ZIP/XML parser; macros are not executed. XLSX sheet names are resolved through workbook relationships. |
| ODT/ODS/ODP/ODG and templates | Native | ODF ZIP/XML parser. |
| EML, EPUB | Native | Addressable headers/body/chapters where available. |
| PDF | Conditional | PyMuPDF or pypdf; scanned pages need OCR. Encrypted files are reported as `encrypted`. |
| PNG/JPEG/TIFF/BMP/WebP | Conditional | Requires OCR enabled and local Tesseract. Otherwise `metadata_only`. |
| DOC/XLS/PPT, MSG, VSD, PUB, WPS, Pages/Numbers/Keynote | Conditional | Requires an explicitly configured **loopback-only** Apache Tika server. Redirects are refused. |
| GDOC/GSHEET/GSLIDES/GDRAW pointer files | Metadata only | These local files contain links/metadata, not the remote Google document body. Export the document or add an authenticated Google Drive ingestion connector to index its content. |

Operational notes:

- Hermes attachment files are expected under `${HERMES_HOME:-~/.hermes}/cache/documents`. This directory is allowlisted by default.
- `memory_wiki_document_scan({})` scans that attachment cache when `root` is omitted. An explicit `root` remains available for other allowlisted directories.
- Optional turn-start ingestion is controlled by `MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE=1`; it is bounded, skips files younger than two seconds, never prunes missing files, and does not create embeddings unless `MEMORY_WIKI_DOCUMENT_AUTO_EMBED=1`.
- Automatic ingestion is **default-deny for visibility**: set `MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID` (and normally the matching repository ID) before enabling it. Global automatic ingestion needs the separate explicit `MEMORY_WIKI_DOCUMENT_ALLOW_GLOBAL_AUTO=1` override.
- Normal document APIs are bound to `MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID` / `MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID` (or the provider project scope). Cross-scope requests are denied unless `MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE=1` is intentionally set.
- Ingestion parses only a per-invocation snapshot copied from a no-link/no-reparse descriptor. Scans have entry, directory, depth, candidate and wall-time budgets; documents, manifests and parser-worker output are size-bounded.
- `memory_wiki_document_scan` reports missing previously indexed files; deletion is applied only with `prune_missing=true`.
- Automatic prompt-time document prefetch is restricted to global-scope material. Scoped material must be queried with an explicit scope.
- Changing `scope_id` or `repository_id` on an unchanged file updates the stored identity and queues fresh embeddings instead of silently returning `unchanged`.
- Parser metadata is recursively bounded and secret-redacted before SQLite storage or tool output.
- Document workers receive a minimal environment rather than API keys, tokens, proxy variables, and unrelated Hermes secrets.

Recommended configuration for Hermes/Termux attachments:

```bash
MEMORY_WIKI_DOCUMENT_CACHE_DIR=/root/.hermes/cache/documents
MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID=hermes-state-db
MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID=hermes-state-db
MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID=hermes-state-db
MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID=hermes-state-db
MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE=1
MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS=15
MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_FILES=200
MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_CHANGED=3
MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS=2
# Enable only when automatic API-backed embedding cost/latency is acceptable:
MEMORY_WIKI_DOCUMENT_AUTO_EMBED=0
```

If `HERMES_HOME=/root/.hermes`, the explicit cache-dir line is optional.

**Windows (active default profile):** do not use `/root/.hermes/...`. The cache defaults to `C:\Users\Kekl\AppData\Local\hermes\cache\documents`, so the cache-dir setting is optional. Persist only non-secret settings for future Desktop/gateway processes:

```powershell
setx MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID "hermes-state-db"
setx MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID "hermes-state-db"
setx MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID "hermes-state-db"
setx MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID "hermes-state-db"
setx MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE "1"
setx MEMORY_WIKI_DOCUMENT_AUTO_SCAN_SECONDS "15"
setx MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_FILES "200"
setx MEMORY_WIKI_DOCUMENT_AUTO_SCAN_MAX_CHANGED "3"
setx MEMORY_WIKI_DOCUMENT_AUTO_MIN_AGE_SECONDS "2"
setx MEMORY_WIKI_DOCUMENT_AUTO_EMBED "0"
```

`setx` affects only new processes. Fully restart the Desktop/backend after setting these values, then place a non-sensitive test document in the cache and verify it with `memory_wiki_document_status` and a scoped `memory_wiki_document_query`.

### Strict security gate

Keep `HERMES_SECURITY_STRICT=0` only as the explicitly accepted temporary fallback while the official signed `hermes_trust_core` (and its documented dependencies) are unavailable. Switch it back **only after** the signed artifact has been installed into the active profile and a fresh strict process passes both plugin import/doctor and a read-only Memory Wiki health probe:

```powershell
setx HERMES_SECURITY_STRICT "1"
hermes gateway restart
```

`setx` alone never reloads an already-open Desktop chat. If strict import/doctor fails, leave the previous setting in place; do not fabricate a trust-core substitute or force a strict restart.

## Recovery

### After process crash during write
The transactional outbox ensures claim writes and index tasks are atomic:
- Claim + evidence + history + outbox → one SQLite COMMIT
- If process crashes before COMMIT → nothing saved (rollback)
- If process crashes after COMMIT → all 4 parts persisted
- Outbox worker picks up pending tasks on next run
- Completed document/code graph mutations create a post-`after` logical checkpoint containing durable graph rows but no raw source bodies. Recovery replays supported events only; unsupported, incomplete `before`, or error events fail closed before any live-database swap.

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

## Changelog

- **v1.21.0 (2026-08-28)**: Document ingestion now snapshots no-link/no-reparse handles before parsing; automatic scans are cache-only, scope-bound, streaming and bounded by traversal budgets. Parser workers use bounded concurrent stdout/stderr readers, isolated Windows Job Object CPU/memory limits, and kill-on-close cleanup. Inbox manifests are atomically claimed and size/document-count capped; document APIs deny cross-scope access by default. Journal recovery checkpoints completed document/code mutations and blocks incomplete before/error events. Release metadata now includes MIT licensing, `pyproject.toml`, `uv.lock`, SPDX SBOM generation and an attested tag-release workflow.
- **v1.20.12 (2026-08-28)**: FTS-recovery LIKE fallback now enforces visibility, project, quarantine, secret-risk and quality gates; ambiguous automatic code-graph prefetch no longer queries every repository. MCP validates JSON-RPC 2.0 envelopes, keeps notifications silent, and redacts `sk-proj-*` and quoted secret values in errors.
- **v1.20.11 (2026-08-28)**: journal recovery now serializes writers across Windows processes, avoids journaling read-only probes, preserves non-secret `value` fields and SHA-256 content identifiers, checkpoints durable code/document graph tables, replays post-checkpoint code claims with metadata, and refuses to swap the live DB when it encounters an unsupported completed mutation. PEM-shaped code content is redacted before SQLite/FTS persistence; MCP now rejects non-object JSON-RPC requests without terminating stdio.
- **v1.20.10 (2026-08-28)**: fail-closed journal replay preserves the live database when any replayed event fails; all auxiliary code/document/secret context now crosses the recall guard; quoted and Bearer-style labelled document secrets are fully redacted; secret-context auto-discovery no longer crosses Hermes profile boundaries.
- **v1.20.9 (2026-08-28)**: document-index lifecycle, provenance, Windows UTF-8 worker and optional-secret prefetch regressions covered; automatic embedding now drains pre-existing pending chunks; health and MCP handshake versions now match `plugin.yaml`; MCP schema refresh now uses a profile runtime cache (never mutating packaged schemas), returns JSON-RPC parse errors, redacts credential-shaped errors, and works from immutable installs; XML DTD/entity declarations and shared `/tmp` debug logs are rejected/removed; cross-platform pytest CI added.
- **v1.20.8 (2026-08-12)**: docs/contract sync — README 4096-dim contract, `nous` embed provider documented, plugin.yaml version aligned with runtime banner.
- **r21 (2026-08-11)**: repository-scope hardening + code-claim manifest guard + FTS corruption auto-repair; `pack_context` sees project-scoped code claims with `include_all_projects` opt-in.
- **nous embed retry (2026-08-09)**: exponential backoff (1s/2s) on inference-api burst 429/5xx; curl fallback now checks HTTP status — fixes 61 claims stuck `failed`.
- **r19+r20 (2026-08-08)**: token governor (tool-cache 2.4.0, smart initial tool mode ≤24 tools, exact cache with tools); partitioned cache identity `memory-cache-state-v3-r20-partitioned` — per-component revisions bumped on upsert / add_evidence / update_claim / set_status_by_text.
- **nous embed provider (2026-08-08)**: `NOUS_API_KEY` priority + curl fallback (Cloudflare 1010 bans urllib TLS fingerprint).
- **v1.20.6 (2026-07-30)**: secret context hardening R5 — readthrough bridge, credential quarantine, document recall sanitization.
- **v1.20.5 (2026-07-25)**: prefetch hardening R4 — observability, recall audit, active memory prefetch bounds, prefetch fallback.

## License

MIT


## Audit fix r1 (2026-07-29)

This source package includes the runtime modules required by the advertised code and document graph tools. `plugin.yaml`, the MCP schema cache and the Python provider are generated from the same 101-schema source. `memory_wiki_compare_search` now performs real FTS-only, vector-only and hybrid runs without mutating process-wide environment variables. Backup restore validates archive entry count, uncompressed size, member size and compression ratio before creating a safety backup or writing staged files.


## Automatic prefetch hardening in v1.20.4

- `MEMORY_WIKI_PREFETCH_CLAIM_LIMIT` and `MEMORY_WIKI_MAX_PREFETCH_CHARS` remain upper bounds.
- Prefetch searches an expanded pool, but only claims with an actual lexical/vector/rerank/topic signal may fill the soft minimum.
- Every main claim, revision delta, evidence item and contradiction line passes the same observable Injection Guard path.
- A plan-only `<memory-context>` is no longer emitted. If candidates exist but all are withheld, the prompt receives a compact non-content diagnostic instead of a misleading Recall plan.
- `memory_wiki_debug_search` now reports guard status/signals per post-filter candidate and does not increment recall counters.
- `memory_wiki_semantic_status` exposes `last_prefetch` telemetry. Audit events use `op=prefetch` with searched/relevant/rendered/quarantined/output size.
- Strict mode never bypasses a trust-core quarantine merely to meet the minimum. A guard disagreement is reported separately so false positives can be fixed without weakening security.
