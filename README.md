# Hermes Memory Wiki v1.23.0

Native structured long-term memory provider for Hermes Agent. SQLite claims are the source of truth; FTS5 and Qdrant are rebuildable retrieval indexes. 120 MCP tools.

The supported security properties and private reporting path are documented in [`SECURITY.md`](SECURITY.md).

Reproducible benchmark runners live under `benchmarks/`; run `python benchmarks/audit_retrieval.py` for the offline startup/retrieval check. Ad hoc local reports and run outputs are ignored; the audited full LongMemEval evidence artifact and its provenance manifest are versioned as the release baseline.

The synthetic [quality regression suite](benchmarks/quality_eval.py) checks temporal correction, multi-hop retrieval, conflicting evidence, and chat/bot/project isolation without reading the active memory database. Run `python benchmarks/quality_eval.py` for offline FTS and hybrid results. For a live embedding/Qdrant check, run `python benchmarks/quality_eval.py --semantic --env-file PATH_TO_HERMES_ENV`; this creates a random collection, never uses the active alias, and reports whether cleanup removed the collection. The output reports Recall@5, MRR@5, scope leaks, and p50/p95 latency. These small synthetic cases do not measure answer quality or generalization on real conversations.

For an optional answer smoke test, run `python benchmarks/answer_eval.py --model openai/gpt-4.1-mini --env-file PATH_TO_HERMES_ENV --semantic`. It sends only synthetic fixture facts and questions to OpenRouter, reports transparent regex checks and token usage, and measures a separate simple RAG prompt rather than Hermes's complete prompt/prefetch path.

The optional [LongMemEval adapter](benchmarks/longmemeval_adapter.py) accepts an **already downloaded** [official LongMemEval JSON](https://github.com/xiaowu0162/LongMemEval) file. It never downloads the dataset or reads the active Hermes profile. Each question gets a temporary, separate Hermes database; session dates are sorted before turns are ingested. The default is a five-question FTS-only baseline, with Qdrant and OpenRouter disabled:

```shell
python benchmarks/longmemeval_adapter.py --dataset PATH_TO_LONGMEMEVAL_JSON --limit 5 --top-k 5 --output longmemeval-results.json
```

Results include the retrieved claim IDs and their source session/turn evidence IDs, session recall (all/any), reciprocal rank, available turn-label recall, ingestion outcomes, and per-question search time. Questions with `_abs` or no answer session IDs are excluded from evidence recall, following the official retrieval evaluation's abstention convention. Raw turns pass through Memory Wiki's claim quality policy; queued turns are counted but cannot be retrieved. Duplicate turns may merge into one claim, so one retrieved ID can map to several source turns. To score pre-existing answers, pass an official-format JSONL file (`{"question_id":"...","hypothesis":"..."}`) with `--hypotheses PATH`. Its normalized exact-match value is only a local proxy; use LongMemEval's official QA evaluator for the model-judged answer metric.

For an explicit hybrid check, add `--semantic --env-file PATH_TO_HERMES_ENV`. This uses the configured OpenRouter embedding model and Qdrant endpoint, creates a unique physical collection for each question, disables aliases and background outbox writes, and verifies deletion of every generated collection. To generate answers from only the retrieved claims, add `--answer-model MODEL --hypotheses-out answers.jsonl` and optionally `--answer-max-tokens 128 --answer-context-chars 4000`. Answer generation requires an explicit `--env-file` even for FTS. The JSONL has the official evaluator's `question_id`/`hypothesis` shape; token usage, reported answer cost, answer latency, errors, and a strict local exact-match proxy are reported separately. No active Hermes memory is sent to either service.

The optional [LoCoMo adapter](benchmarks/locomo_adapter.py) evaluates dialogue evidence retrieval against the [official ten-conversation dataset](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json). It can read a local `locomo10.json`, or explicitly download the pinned version and verify its SHA-256. The default processes one conversation and 50 questions; `--max-conversations 10 --questions-per-conversation 0` evaluates the complete release:

```bash
python benchmarks/locomo_adapter.py --download-official --max-conversations 10 --questions-per-conversation 0 --top-k 5 > locomo-results.json
```

Each conversation gets a temporary Hermes home, with Qdrant and model calls disabled. Dialogue text and released image captions are indexed directly as raw FTS claims, bypassing automatic memory extraction. The report includes the source commit/hash, selected sample/question counts, evidence recall/any/all at K, MRR, category breakdowns, unresolved annotation IDs, and search latency. It does **not** score generated answers, whole-agent memory quality, or semantic retrieval. The released images are not included. No active memory database is read.

The [LongMemEval-V2 adapter](benchmarks/longmemeval_v2_adapter.py) streams official web/enterprise trajectories into an isolated text FTS probe. [Its protocol and partial-run limitations](benchmarks/LONGMEMEVAL_V2.md) are separate from the dialogue LongMemEval and LoCoMo evidence benchmarks: public V2 questions do not provide gold state evidence IDs, so this adapter reports coverage and latency rather than answer accuracy or evidence recall. The complete official reader/judge run also needs the multimodal files, which the text probe does not index.

### Opt-in episodic dialogue evidence

Production `sync_turn` can preserve short, redacted user and assistant excerpts in a separate SQLite/FTS index when the **host** sets `MEMORY_WIKI_EPISODIC_ENABLED=1`. It is off by default and captures no raw turn text unless the host opts in. `memory_wiki_query_episodes` is the explicit model-facing read tool; while disabled it returns `enabled=false` and no episodes. The default query cap is eight low-trust excerpts, 350 characters each and 2,400 characters total; both caps can be lowered by the host. Results are evidence of prior dialogue, not instructions or verified facts, and they never enter the trusted claim, preference, or graph indexes.

The default `MEMORY_WIKI_EPISODIC_SCOPE=chat` confines capture and search to the exact bot/chat. A host can set `bot` **before capture** to allow cross-chat recall only with a distinct host-attested bot/account ID; platform fallback IDs such as `telegram`, `desktop`, and `default` are denied for bot-wide evidence. Changing the setting later does not widen older chat rows. The host can set `MEMORY_WIKI_EPISODIC_TTL_DAYS` (default 30, range 1–365), `MEMORY_WIKI_EPISODIC_MAX_ROWS` (default 5,000 per visibility partition, cap 20,000), and `MEMORY_WIKI_EPISODIC_MAX_BYTES` (default 8,000,000 content bytes per visibility partition, cap 32,000,000). Expired rows stop appearing immediately and are physically pruned on capture or query. Host-only `episodic_memory.delete_episodes(provider)` erases this chat; `scope='all'` requires a distinct trusted bot identity. Full host backups and checkpoints can contain redacted episodes; model-created scoped snapshots exclude them. Episodes captured after the latest checkpoint are not replayed from the journal. Host removals are replayed from the separate authenticated `memory-wiki/privacy-erasure/` ledger after an older restore. Preserve that directory with the database; ZIP files alone are intentionally insufficient to roll back a removal. Older archives may still physically contain previously removed text and need separate archival deletion when physical erasure is required.

`MEMORY_WIKI_EPISODIC_SEMANTIC=1` adds optional OpenRouter/Qdrant recall when the main semantic subsystem is enabled. Redacted episode text is embedded by the existing asynchronous SQLite outbox, never on the capture path, and is stored in a separate manifest-versioned collection controlled by `MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION`. The server query uses the exact bot, configured scope, chat hash for chat scope, and expiry filter. Every vector hit is then reloaded through the authoritative SQLite owner/scope/expiry boundary and the same secret, injection, character-budget, and paired-turn guards as FTS. Lexical and vector ranks use deterministic reciprocal-rank fusion; any embedding or Qdrant failure falls back to FTS. Enabling remote embeddings sends the already redacted bounded episode text to the configured embedding provider. Episode prune, expiry, and host deletion enqueue matching point deletes, and successful episode outbox copies are removed so they do not outlive the episode TTL.

Episode FTS uses a durable numeric docid map for indexed delete and update. Its installer migrates older ID-scan FTS tables from the canonical SQLite episodes; docids remain stable across `VACUUM`, while full logical checkpoints rebuild this derived map. A host can call `episodic_memory.erase_matching_episodes(provider, module, exact_contents, conn=...)` inside the same transaction as a memory removal. It erases matching excerpt text in the exact current chat and explicitly trusted bot partitions, then queues deletion for every known Qdrant target, including older physical collections. The function returns only counts and opaque episode IDs, never episode text.

An isolated [paired LongMemEval pilot](benchmarks/episodic_fallback_probe.py) tested 30 stratified questions using the actual `_ingest_text` path and a temporary owner-scoped episode index: claim-only top-five retrieval found a gold answer turn for 0% of questions; two episode excerpts raised that evidence-any measure to 70% and evidence-all to 36.67%, with local episode FTS p50 2.74 ms and p95 4.14 ms. The sample is small and biased toward the first five answer-labeled questions per type. It used a non-strict local guard, no Qdrant/OpenRouter, and no answer generation, so it does not establish production answer quality or security. Reproduce it against a locally obtained official oracle JSON with `python benchmarks/episodic_fallback_probe.py --dataset PATH_TO_LONGMEMEVAL_JSON --per-type 5`; it creates temporary profiles and never reads active memory. [Design and remaining gates](EPISODIC-FALLBACK-DESIGN.md) describe the quality and privacy limits.

Automatic context fallback also requires the separate host setting `MEMORY_WIKI_EPISODIC_PREFETCH=1`. It runs only when guard-safe relevant claim recall is below the configured minimum and at least 0.5 seconds remain in the bounded prefetch worker. The default quality profile can add at most five excerpts and 2,400 sanitized characters in a separate XML-escaped, explicitly untrusted block; `MEMORY_WIKI_EPISODIC_PREFETCH_MAX_RESULTS` and `MEMORY_WIKI_EPISODIC_PREFETCH_MAX_CHARS` can lower or raise those bounded caps. Every excerpt carries a stable `[M:E:<id>]` citation. It never changes claim/preference/graph state. The prefetch setting is off by default. Diagnostics report owner-scoped candidate/rejection/render counts and search time without excerpt text. The deadline path skips episodic search when time is insufficient.

The full production-path runner processed all 500 official LongMemEval oracle questions (479 with evidence labels) with the current three-claim plus five-episode allocation. Evidence-any rose from 0.84% for eight production-ingested claims to 83.92%; evidence-all rose from 0% to 56.78%, and 62.39% of all labeled source turns were recovered. Local episode search p50/p95 was 6.78/9.37 ms. This is an offline evidence-retrieval measurement with isolated databases, the non-strict local guard, and no generated answers, OpenRouter embeddings, or Qdrant, so it is not an end-to-end QA or market-ranking claim. The complete machine-readable result and its source/runtime provenance are in [`benchmarks/oracle_episode_8slot_full_planned.json`](benchmarks/oracle_episode_8slot_full_planned.json) and [`benchmarks/oracle_episode_8slot_full_planned.provenance.json`](benchmarks/oracle_episode_8slot_full_planned.provenance.json).

The full production-path LongMemEval and bounded LoCoMo runners (`benchmarks/full_oracle_episode_probe.py` and `benchmarks/locomo_episode_probe.py`) use isolated homes and never read the active memory database. See [the design note](EPISODIC-FALLBACK-DESIGN.md) for the methodology, privacy boundary, and remaining evaluation gates. Generated outputs are intentionally not committed until each result has a complete provenance manifest.

The LongMemEval, LoCoMo, hybrid, answer-evaluation, and diversity runners accept explicit local datasets and configuration. They produce local result files; no result is a release artifact without a pinned runner command, source revision, dependency/configuration manifest, and dataset checksum. No benchmark changes production ranking automatically.

### Unified evidence-first recall

`memory_wiki_recall` is the bounded model-facing facade for answer evidence. It expands the caller's query with the deterministic recall planner, searches visible claims in `fts` mode for `fast` or `hybrid` mode for `auto` and `deep`, includes owner-filtered event-backed observations and episodes when enabled, queries the append-only event ledger in `auto` and `deep`, and performs one bounded guarded entity-graph traversal only in `deep`. Event and observation recall use exactly the host-selected `MEMORY_WIKI_EVENT_SCOPE` (`chat` by default; `bot` and `project` are the other valid values). An invalid scope fails closed. Results are de-duplicated by stable source IDs and fused with deterministic reciprocal-rank scoring.

Every returned evidence string passes the provider recall guard, and claims receive a final visibility check after retrieval. Event content is guarded again after the ledger applies its owner predicate, expiry, integrity hash, secret scan, and first recall guard. Observation content is also bound to an immutable version and a live owner-filtered representative event. The response contains at most 20 items and 24,000 evidence characters. Each item has a stable citation (`[M:C:<id>]`, `[M:O:<id>]`, `[M:E:<id>]`, `[M:V:<event-id>]`, or `[M:G:<id>]`), source, trust metadata, and timestamps. Only final selected claim items create neutral `recall_events`; their IDs are returned in `recall_tracking.answer_linkage` for exact, idempotent `memory_wiki_mark_used` feedback. `answer_policy.allowed_citations` is the complete citation allowlist. An empty evidence set requires abstention from memory-based claims or a clarifying question. The facade does not replace automatic prefetch and does not accept bot, chat, project, event, or episode-scope overrides from the caller.

### Privacy-safe online retrieval metrics

Automatic prefetch and explicit `memory_wiki_recall` add one daily SQLite aggregate per fixed operation, outcome, and latency bucket. `memory_wiki_health.metrics.online_recall` reports sample counts, hit/empty/fallback/error counts, mean latency, and p50/p95 **bucket upper bounds** for up to the last seven days; `window_days` gives the actual window when retention is shorter. These are runtime measurements, not answer-quality scores. The metrics table has no query, result text, owner/session ID, trace ID, arbitrary label, or exception field. A busy database drops the sample without changing recall. Data older than the configured retention is pruned during recording. The provider cannot measure host time-to-first-token or model cost unless Hermes supplies those signals separately.

### Evidence-backed living observations

When the append-only event ledger is enabled, startup migration installs a derived observation index with current records, immutable bounded version history, and stable event links. Consolidation runs in bounded batches after host turn capture, host memory mutations, and maintenance. It is deterministic and does not call an LLM or synthesize text: every observation copies guard-safe text from a supporting event. Exact owner predicates are applied in SQL before limits, expired evidence disappears immediately, source deletion removes derived history, and transient guard failures use bounded retry state instead of permanent rejection.

Atomic `memory_mutation` and explicit `observation` events may merge only across lossless surface normalization. Raw `dialogue_turn` events are exact-only and their confidence never exceeds `0.35`; wording variants remain separate. Changed values and opposite polarity remain separate active observations. Free-text automatic supersession is intentionally absent because a safe subject/predicate/correction boundary is unavailable without structured evidence.

### Host OCR evidence for screenshots and images

Set `MEMORY_WIKI_VISUAL_EVIDENCE_ENABLED=1` together with the event ledger to allow a trusted host integration to call `provider.capture_host_ocr_evidence(text, asset_sha256=..., media_type=..., ocr_engine=...)`. The host computes the SHA-256 of its source image and runs its own OCR; Memory Wiki does not read pixels, call a vision endpoint, or offer this method as a model-callable tool. Supported media labels are PNG, JPEG, WebP, TIFF, and BMP. No file path or image bytes are stored. The full OCR text is secret-scanned and guarded before the event ledger bounds its stored excerpt.

OCR results have `visual_ocr` / `image_ocr_text` provenance and `unverified_host_report` status. The host-supplied hash identifies a source for deletion, but does not cryptographically attest to the image or make OCR text a verified fact. Retrieval keeps the normal event citation and owner ACL. Derived observations use exact-text matching and remain low-confidence. Call `provider.delete_host_ocr_source(asset_sha256=..., scope='chat')` when the source is deleted; this removes matching events in that exact owner partition, FTS entries, source links, and dependent observation history. The default visual scope is the current chat; bot or project sharing must be explicitly selected at capture and deletion. `MEMORY_WIKI_VISUAL_EVIDENCE_ENABLED` defaults to off until Hermes has a trusted attachment/OCR hook.

## Cache identity (r19 + r20)

- **r19 token governor**: exact embedding reuse inside the provider process; tool-cache contract 2.4.0 with smart initial tool mode (≤24 tools), exact-cache with tools enabled, shadow semantic mode by default.
- **r20 partitioned cache**: cache signature is scoped per visibility component (`shared` / `bot:` / `project:` / `private:<chat_hash>`). A write in project B no longer invalidates project A / private / bot cache entries. Contract: `memory-cache-state-v3-r20-partitioned` with per-component revisions bumped on upsert / add_evidence / update_claim / set_status_by_text.

- **r21 repository scope + FTS repair**: code-claim search is project-scoped; a caller-supplied coverage manifest does not widen visibility. The classifier handles duplicate and stale code claims within the authorized scope; automatic FTS5 corruption detection and rebuild remain available.

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

Memory Wiki keeps `secret_index` as its local safe metadata index and can read through an installed secret-context plugin. New local rows carry a visibility owner and are filtered like claims when `MEMORY_WIKI_ENABLE_LEGACY_SECRET_INDEX=1` enables the local index. Older ownerless rows and the external registry still require `MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA=1`, only when every agent sharing the Hermes home is authorized to see every identifier in that registry. External results remain recursively redacted and are not copied into SQLite, FTS5, Qdrant, dashboards, or markdown pages.

- `memory_wiki_query_secrets` merges local `sec_*` metadata with safe external matches.
- External matches include `origin=secret_context` and `lookup_key`; use the dedicated `secret_context_lookup` tool for the actual context.
- `secret_context_lookup` and `secret_context_search` are patched at registration time to serialize non-string results as JSON strings, as required by Hermes/OpenAI-compatible tool messages.
- The bridge invokes only `secret_context_search`; it never calls lookup/reveal itself.
- Disable read-through with `MEMORY_WIKI_SECRET_CONTEXT_BRIDGE=0`.
- The shared-metadata opt-in above enables both the local `secret_index` read and the external secret-context bridge; `MEMORY_WIKI_SECRET_CONTEXT_BRIDGE=0` still disables only the external source.
- Set an explicit plugin path with `MEMORY_WIKI_SECRET_CONTEXT_PLUGIN=/root/.hermes/plugins/<plugin>/__init__.py`.
- Automatic plugin discovery stays inside the active Hermes profile. A plugin in a different profile is used only through that explicit path setting.

Plaintext returned intentionally by `secret_context_lookup` can still enter the model's tool history. For login flows, a domain-bound executor that consumes a secret reference directly remains safer than revealing plaintext to the model.

## Requirements

- Python 3.11 or 3.12 (the supported range is `>=3.11,<3.13`)
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
| `MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES` | `512` | Process-local thread-safe LRU capacity shared by query and document embeddings; `0` disables reuse |
| `MEMORY_WIKI_EMBED_QUERY_CACHE_TTL_SECONDS` | `86400` | TTL for normalized query embeddings, range 0–2,592,000 seconds |
| `MEMORY_WIKI_EMBED_DOCUMENT_CACHE_TTL_SECONDS` | `2592000` | TTL for exact document embeddings, range 0–31,536,000 seconds |
| `MEMORY_WIKI_EMBED_CACHE_SINGLEFLIGHT_WAIT_SECONDS` | `45` | Maximum wait for an identical in-flight embedding before falling back without starting a duplicate request |
| `MEMORY_WIKI_QDRANT_COLLECTION` | `memory_wiki_claims` | Collection name prefix |
| `MEMORY_WIKI_EPISODIC_ENABLED` | `false` | Capture bounded, redacted host dialogue episodes in SQLite/FTS |
| `MEMORY_WIKI_EPISODIC_SEMANTIC` | `false` | Add asynchronous episode embeddings and hybrid episode recall; requires `MEMORY_WIKI_SEMANTIC` |
| `MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION` | `memory_wiki_episodes` | Separate episode collection prefix; the embedding manifest hash is appended |
| `MEMORY_WIKI_EPISODIC_SEMANTIC_BACKFILL_ROWS` | `5000` | Maximum owner-scoped active episodes queued per startup when enabling semantic recall or changing the embedding manifest |
| `MEMORY_WIKI_EPISODIC_SCOPE` | `chat` | Episode visibility partition: exact `chat` or host bot-wide `bot` |
| `MEMORY_WIKI_EPISODIC_QUERY_MODE` | `auto` | Bounded multilingual query planning: `fast`, `auto`, or `deep` |
| `MEMORY_WIKI_EPISODIC_QUERY_MAX_RESULTS` | `8` | Host cap for explicit episode-query results, range 1–20 |
| `MEMORY_WIKI_EPISODIC_QUERY_MAX_CHARS` | `2400` | Total sanitized episode characters returned by one query, range 350–12,000 |
| `MEMORY_WIKI_EPISODIC_PREFETCH` | `false` | Permit episode fallback when safe durable claims do not fill automatic recall |
| `MEMORY_WIKI_EPISODIC_PREFETCH_MAX_RESULTS` | `5` | Episode slots available to automatic fallback, range 1–8 |
| `MEMORY_WIKI_EPISODIC_PREFETCH_MAX_CHARS` | `2400` | Sanitized episode-character budget for automatic fallback, range 350–8,000 |
| `MEMORY_WIKI_EVENT_LEDGER_ENABLED` | `false` | Preserve a bounded append-only, sanitized event evidence ledger |
| `MEMORY_WIKI_EVENT_SCOPE` | `chat` | Exact event partition used for capture and unified recall: `chat`, `bot`, or `project` |
| `MEMORY_WIKI_EVENT_TTL_DAYS` | `90` | Event evidence retention, range 1–3,650 days |
| `MEMORY_WIKI_EVENT_MAX_ROWS` | `20000` | Maximum retained event rows per bot, cap 10,000,000; storage and cleanup costs rise with this setting |
| `MEMORY_WIKI_EVENT_MAX_BYTES` | `32000000` | Maximum retained event content/provenance bytes per bot, cap 16,000,000,000 |
| `MEMORY_WIKI_VISUAL_EVIDENCE_ENABLED` | `false` | Permit host-only OCR text evidence; requires the event ledger and an external trusted OCR hook |
| `MEMORY_WIKI_OBSERVATIONS_ENABLED` | `true` | Build deterministic, event-backed living observations during lifecycle hooks |
| `MEMORY_WIKI_OBSERVATION_TURN_BATCH` | `32` | Maximum event rows consolidated after one host turn, cap 256 |
| `MEMORY_WIKI_OBSERVATION_MUTATION_BATCH` | `16` | Maximum event rows consolidated after one host memory mutation, cap 256 |
| `MEMORY_WIKI_OBSERVATION_MAINTENANCE_BATCH` | `1000` full / `64` light | Maximum event rows consolidated per maintenance pass, cap 10,000 |
| `MEMORY_WIKI_OBSERVATION_TTL_DAYS` | `365` | Observation retention ceiling; the earliest supporting event expiry wins |
| `MEMORY_WIKI_OBSERVATION_MAX_ROWS` | `10000` | Maximum derived observation rows retained per bot |
| `MEMORY_WIKI_OBSERVATION_MAX_BYTES` | `16000000` | Maximum current observation content bytes retained per bot |
| `MEMORY_WIKI_OBSERVATION_VERSIONS_PER_RECORD` | `64` | Bounded immutable versions retained per observation, cap 512 |
| `MEMORY_WIKI_OBSERVATION_VERSION_EVIDENCE_MAX` | `128` | Deterministic oldest/recent event-link sample per version; full set remains committed by digest |
| `MEMORY_WIKI_BACKGROUND_JOBS_ENABLED` | `false` | Optional durable, content-free extraction/observation/graph queue; chat events without a project are eligible for event jobs |
| `MEMORY_WIKI_BACKGROUND_DAILY_JOBS` | `500` | Per-profile job execution budget; clamp 1–100,000 |
| `MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS` | `100` | Per-profile remote-request budget; clamp 1–100,000 |
| `MEMORY_WIKI_BACKGROUND_LEASE_SECONDS` | `120` | Lease/recovery timeout; clamp 30–1,800 seconds |
| `MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS` | `5` | Retry cap before dead-letter; clamp 1–20 |
| `MEMORY_WIKI_BACKGROUND_POLL_SECONDS` | `10` | Worker poll interval; clamp 1–300 seconds |
| `MEMORY_WIKI_VECTOR_SIZE` | `4096` | Qdrant vector size; the local stub and provider response are validated against it |
| `MEMORY_WIKI_RERANK_ENABLED` | `false` | Enable second-stage reranking |
| `MEMORY_WIKI_RERANK_TIMEOUT` | `3.0` | Per-request rerank timeout; accepts 0.25–4.0 seconds and is additionally trimmed by a shorter active prefetch budget |
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
| `MEMORY_WIKI_ONLINE_METRICS_ENABLED` | `true` | Keep fixed-dimension, content-free daily prefetch and explicit-recall aggregates; set `0` to disable |
| `MEMORY_WIKI_ONLINE_METRICS_DAYS` | `30` | Retain aggregates for 1–90 days; health shows at most the latest seven days |
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
| `MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA` | `0` | Permit old ownerless secret metadata and the external read-through registry only in one shared authorization domain; owner-tagged local metadata uses its own ACL |
| `MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH` | `0` | Permit reads of pre-migration graph rows with unknown owner only in a deliberately shared authorization domain; new graph writes are scoped |
| `MEMORY_WIKI_GRAPH_EXTRACT_ENABLED` | `0` | Enable remote relation extraction from one named, visible, bounded claim |
| `MEMORY_WIKI_GRAPH_EXTRACT_MODEL` | unset | OpenRouter chat model for graph extraction; required unless `MEMORY_WIKI_LLM_MODEL` is set |
| `MEMORY_WIKI_GRAPH_EXTRACT_URL` | OpenRouter chat completions | HTTPS or loopback endpoint; `MEMORY_WIKI_LLM_BASE_URL` is the fallback |
| `MEMORY_WIKI_GRAPH_EXTRACT_API_KEY` | `OPENROUTER_API_KEY` | Optional separate graph extraction key |
| `MEMORY_WIKI_GRAPH_AUTO_EXTRACT` | `0` | After session extraction, automatically enrich only newly persisted, grounded, relation-like chat claims; also requires `MEMORY_WIKI_GRAPH_EXTRACT_ENABLED=1` |
| `MEMORY_WIKI_GRAPH_AUTO_EXTRACT_MAX_CLAIMS` | `2` | Maximum remote graph-extraction calls per session end, clamped to 1–4 |
| `MEMORY_WIKI_GRAPH_AUTO_EXTRACT_TOTAL_DEADLINE_SECONDS` | `12` | Total automatic-enrichment budget, clamped to 1–30 seconds |
| `MW_EXTRACTION_ENABLED` | `0` | Opt in to grounded session-end LLM extraction; local explicit-memory heuristics continue while disabled |
| `MW_EXTRACTION_MODEL` | `openai/gpt-4.1-mini` | OpenRouter-compatible structured-output model used for session extraction |
| `MW_EXTRACTION_BASE_URL` | OpenRouter chat completions | HTTPS or explicit loopback endpoint; query strings, URL credentials, and remote plaintext HTTP are rejected |
| `MW_EXTRACTION_API_KEY` | `OPENROUTER_API_KEY` | Optional separate session-extraction key; loopback endpoints may omit it |
| `MW_EXTRACTION_TIMEOUT` | `30` | Session extraction timeout in seconds, clamped to 1–60; failures never abort session finalization |
| `MW_EXTRACTION_MAX_TOKENS` | `1800` | Structured response budget, clamped to 256–3000 tokens |
| `MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_PREFERENCES` | `0` | Permit reads of old preference rules with unknown owner only in one shared authorization domain; new rules are scoped |
| `MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_REVIEW_QUEUE` | `0` | Permit reads and review actions on old queue rows with unknown owner only in one shared authorization domain; new rows are scoped |
| `MEMORY_WIKI_ALLOW_SHARED_SESSION_HISTORY` | `0` | Additional authorization-domain opt-in for reading all `HERMES_HOME/sessions/session_*.json`; `MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK=1` is also required to include them in a context pack |
| `MEMORY_WIKI_ALLOW_PATH_BUNDLE_IMPORT` | `0` | Permit `memory_wiki_import_bundle(path=...)` to read a host file, including bundles from another profile; inline payload import remains available |
| `MEMORY_WIKI_ALLOW_SHARED_AUDIT_LOG` | `0` | Permit model-facing reads of the legacy audit log, which has no per-consumer owner |
| `MEMORY_WIKI_ALLOW_SHARED_RECOVERY` | `0` | Permit model-facing full-store backup, backup listing, restore, journal checkpoint, and journal rebuild only when the entire Hermes home is one trusted authorization domain |

Enabling `MW_EXTRACTION_ENABLED` sends a bounded recent transcript (at most 32 messages, 6,000 characters per message, and 48,000 characters total) to the configured endpoint at session end. Returned memories must use the strict response schema, cite an exact quote and source message, pass local support and injection checks, and are stored as unverified chat-scoped claims with session, speaker, message index, and event-time evidence. A failed or incompatible endpoint is audited and does not interrupt session shutdown.

## Bounded prompt-time recall

- `prefetch()` returns within the configured 5–6 second hard budget. A daemon worker is cancelled logically at the deadline, and a small guard-checked local FTS/SQLite result is returned instead.
- OpenRouter `/models`/embedding health is **stale-while-revalidate**: prefetch immediately uses the last known state while a daemon thread refreshes stale health in the background. Cold start is optimistic and the bounded embedding call remains authoritative.
- Embedding and Qdrant HTTP timeouts are clamped to the remaining prefetch budget. Prompt-time embedding is single-attempt; any failure continues through lexical SQLite/FTS retrieval.
- Prompt-time reranking is one attempt with a hard maximum of 3 seconds. Timeout/error returns the local RRF order rather than empty recall.
- The model-facing `memory_wiki_add_preference_rule` records a chat-scoped **pending candidate**. Caller-provided `source`, `status`, and broad visibility are ignored; the candidate does not enter recall as a trusted rule or create a curated claim. To activate one exact candidate, review it from a trusted host shell with `python tools/attest_preference.py --database PATH --id pref_ID`. The dry run prints `attestation_digest`; run again with `--apply --expected-digest DIGEST --attest "I reviewed this exact preference rule"`. The command makes an SQLite backup and binds approval to the exact text, priority, and owner. A changed candidate invalidates the reviewed digest. Only matching host approval and unchanged code-owned policy rules enter `# Trusted User Preference Layer` in `system_prompt_block`. Old `explicit`/`user` source labels alone are no longer proof of approval.
- `memory_wiki_post_task` and `memory_wiki_add_decision` reject secret-like list elements, topic, and source arguments before ordinary SQLite persistence and cap list sizes. Their auxiliary row and corresponding claim commit together, so a failed claim write rolls back the auxiliary row. Model-provided provenance is ignored; the resulting claim remains unverified and chat-scoped.
- Public `memory_wiki_add_claim` and `memory_wiki_write_firewall` mutations ignore caller-supplied curated source and broad visibility. They save unverified chat claims. Model-created mistake and task-capsule claims are unverified chat claims; project-profile claims remain limited to the active project and are unverified. Model approval of a review item and bundle imports keep untrusted provenance, while an ordinary import update revokes a former `verified` label. A one-time migration removes unsupported `verified` labels from older curated-source claims and profile timestamps.
- Model-facing edits by ID and bulk apply operations can mutate only claims owned by the current chat or private session. Model edits and new evidence revoke a prior `verified` label. Model correction text stays an unverified candidate; preference-layer claim items require host-observed user-turn provenance. Scoped backups and restores include chat/private claims only.
- A cancelled late worker does not acknowledge the revision watermark, so claims that were not injected remain eligible on the next turn.

## Explicit shared context blocks

Shared blocks let one chat deliberately expose selected claims to a named bot or project. The block stores claim IDs and short content hashes, not a second copy of the text. Bot/project identities are stored as database-salted keys in grant and audit rows. Creation requires every source claim to be visible to the creating chat, active, and free of secret/quarantine flags. The owner is the creating bot **and chat**; another chat using the same bot cannot alter its grants.

1. `memory_wiki_shared_block_create({"title":"Deployment facts","claim_ids":["c_..."]})` returns a block ID. A block accepts 1–12 claims and at most 2400 characters of checked claim text.
2. The owner calls `memory_wiki_shared_block_grant({"block_id":"sblk_...","principal_type":"bot","principal_id":"worker-bot"})` or grants a named project. The target receives metadata in `memory_wiki_shared_block_list`; its claim text remains absent from normal recall.
3. The recipient calls `memory_wiki_shared_block_attach({"block_id":"sblk_...","principal_type":"bot"})`. Only then can `memory_wiki_pack_context` and bounded automatic `prefetch()` include the block in a clearly labeled untrusted-data section. Bot and project identities are taken from the initialized provider, not from caller-supplied recipient IDs. A project attachment is active for every bot in that project. At most eight attached blocks and 2400 characters of shared claim text are considered per pack; automatic prefetch uses a smaller 1600-character slice.
4. The recipient can `memory_wiki_shared_block_detach`; the owner can `memory_wiki_shared_block_revoke` a grant or `memory_wiki_shared_block_retire` the whole block. The `shared_block_events` table records each action, actor, recipient, and timestamp without claim bodies.

Rendering rechecks active status, secret/quarantine flags, and the original text hash. Editing a source claim makes that reference disappear until the owner creates a new block and grants it again. Sharing is local to a single Memory Wiki database; it does not transfer claims between Hermes homes or grant direct claim mutation rights.

## Incremental source connectors

`source_connectors.py` defines a connector-neutral `SourceRecord` (`uri`, `revision`, `text`, `scope_id`, `repository_id`, `source_type`, optional `embed`) and persists its state in `external_sources`. GitHub and Drive use this adapter. The URI, creating bot, trust namespace and scope form a stable database-salted source key; the source revision and content hash prevent silent changes under an unchanged revision. Granting a different scope to an existing record creates a distinct key and still must pass the document access policy.

- `memory_wiki_source_file_sync({"path":"...","embed":true})` reuses the existing allowlisted, isolated document snapshot parser. The key remains stable across file revisions; deletion never removes the original file.
- `memory_wiki_source_github_sync({"owner":"org","repo":"repo","path":"docs/note.md","ref":"main","embed":true})` fetches exactly one UTF-8 text file through the [GitHub Contents API](https://docs.github.com/en/rest/repos/contents). Public repositories work without credentials. Set `GITHUB_TOKEN` in the host environment for private repositories; the token needs **Contents: read** permission for the selected repository. The connector accepts only a bounded set of text extensions and files up to 1 MB, rejects redirects and arbitrary hosts, checks the Git blob hash before marking the source as GitHub-fetched, and reuses the ETag on later calls. A `304` leaves the indexed revision untouched. GitHub [rate-limit responses](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) impose a cooldown without automatic retry. The connector does not crawl repositories or sync automatically; call it for each selected file. A `404` is treated as unavailable because private repositories can hide authorization failures this way, so deletion is always explicit.
- `memory_wiki_source_drive_sync({"file_id":"...","embed":true})` fetches one Drive UTF-8 text file or exports one Google Doc as plain text. Set `MEMORY_WIKI_GOOGLE_DRIVE_ACCESS_TOKEN` to a host-managed OAuth access token with access to that file; the token is not a tool argument or stored in the wiki. The connector checks `capabilities.canDownload`, restricts MIME types and response size to 1 MB, checks the blob's MD5 checksum, and checks the metadata version before and after download. An unchanged version uses one metadata request without redownloading. It never searches Drive or follows redirects. See Google's [download/export guide](https://developers.google.com/workspace/drive/api/guides/manage-downloads) and [export formats](https://developers.google.com/workspace/drive/api/guides/ref-export-formats).
- `memory_wiki_source_record_upsert({"source_uri":"https://...","revision":"...","content":"...","embed":true})` accepts at most 1 MB of unverified UTF-8 text. The model-facing tool always labels it `record`, so a caller cannot claim authenticated GitHub or Google Drive provenance. It redacts before staging under the **active provider's** `HERMES_HOME/cache/documents/connectors` directory and then uses the same document graph and optional OpenRouter/Qdrant embedding pipeline. That cache must be in `MEMORY_WIKI_DOCUMENT_ROOTS` when a custom document allowlist is configured.
- `memory_wiki_source_list` returns bounded metadata for the creating bot in the current scope. `memory_wiki_source_delete({"source_key":"ext_..."})` lets that bot soft-delete its graph, archive its embedding claims and remove its staged record file. A different bot in the same project cannot list, query, update or delete that connector-backed document. Connector embedding claims use bot visibility. Source keys, revisions, scopes, owner and actions remain in checkpoints; raw record bodies and full URIs are excluded from connector journal events.

The generic record tool does not fetch remote URLs itself and labels its content `record`; it cannot overwrite a verified GitHub or Drive source even when it supplies the same URI. Source keys also include the creating bot identity, isolating concurrent bots in one project. The connector stores a display URI with credentials, query and fragment stripped; full source URLs are used only transiently to derive the source key. Without a Drive access token and file access grant, export the file locally and use `memory_wiki_source_file_sync`.


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
    "MW_PLUGIN_PATH": "/absolute/path/to/memory-wiki/__init__.py",
    "MW_MCP_SESSION_ID": "stable-client-session",
    "MW_MCP_BOT_ID": "stable-client-bot",
    "MW_MCP_PROJECT_ID": "optional-project"
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
- Start one wrapper process per agent identity. The three `MW_MCP_*_ID` values
  determine chat, bot, and project visibility for that process. When session
  and bot IDs are omitted, process-specific IDs are used so separate clients
  do not silently share private memory; provide stable IDs for continuity.

Python applications can use the packaged `memory_wiki.sdk.MemoryWikiClient`:

```python
from memory_wiki.sdk import MemoryWikiClient

with MemoryWikiClient(
    hermes_home="/absolute/path/to/active/hermes-home",
    session_id="my-agent-session",
    bot_id="my-agent",
    project_id="my-project",
) as memory:
    result = memory.query("current deployment region")
```

`add_claim` submits an unverified claim scoped to the SDK client's chat. Its
legacy `source` and `visibility_scope` keyword arguments are ignored. It returns
`state` and `immediately_recallable` separately. A stored
low-quality claim may still be filtered by strict recall, so applications
should inspect both values.

## Key MCP tools

### Write tools
| Tool | Description |
|---|---|
| `memory_wiki_add_claim` | Submit an unverified chat claim; low-quality input may enter review |
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
| `memory_wiki_doctor` | Read-only checks of journal, schema, and indexes by default; `repair=true` also runs write probes, WAL checkpoints, and repairs |
| `memory_wiki_health` | Database statistics and FTS index status |
| `memory_wiki_snapshot` | Full DB snapshot export |
| `memory_wiki_maintenance` | Rebuild FTS, scan contradictions, render pages, and process one bounded semantic-outbox batch (no arguments) |

### Code intelligence (Phase 4)
| Tool | Description |
|---|---|
| `memory_wiki_code_claim_add` | Code-linked claim with repository/symbol/revision metadata |
| `memory_wiki_code_claim_query` | Query by repository_id, file_path, or symbol_id |
| `memory_wiki_symbol_history` | Revision history for a specific symbol |
| `memory_wiki_repository_context` | All code-linked claims for a repository |
| `memory_wiki_invalidate_revision` | Mark claims stale after symbol/file change |
| `memory_wiki_patch_outcome_add` | Record patch application outcome |

For code-graph ingestion, a `full` snapshot is authoritative: a previously
indexed file absent from the incoming snapshot is treated as deleted and its
active code claims are archived before graph rows are replaced. A `delta`
snapshot remains additive/non-destructive unless it explicitly names a file in
`deleted_files`. Any non-empty `commit_sha` must be a valid hexadecimal Git
object ID. Before an authoritative snapshot can invalidate any claims, every
graph collection and its write-critical paths/numeric fields are validated;
malformed input fails without replacing graph rows or changing recallable
claims. Invalidation errors also fail the event before graph replacement rather
than leaving stale claims recallable.

An event ID is a content-bound, exactly-once graph mutation: reservation,
claim invalidation, replacement rows, and the finalized event digest commit in
one SQLite transaction. Concurrent producers of the same ID therefore either
deduplicate the identical normalized snapshot or reject a conflicting payload;
embedding begins only after that commit.

### Code-graph privacy boundary

The graph is a **redacted navigation index**, not a second source checkout.
Code Shrinker remains the authority for exact source retrieval. Before any
producer text can reach graph tables, FTS, embeddings, reranking, prefetch,
recovery artifacts, or terminal `done`/`dead-letter` files, Memory Wiki applies
the common secret policy and masks values under explicitly secret field names.
Public graph results omit internal full-text columns and are redacted again at
the output boundary.

Raw inbox input is claimed privately, used only for its opaque lifecycle hash,
then replaced by a redacted terminal record; it is never moved verbatim into a
terminal directory. To migrate legacy graph rows, FTS indexes, and terminal
Code Shrinker records, run the deliberate local maintenance operation:

```python
memory_wiki_scrub_secrets({"apply": True, "limit": 1000})
```

The operation reports counts and redacted examples only; it never returns the
original secret values.

A claimed Code Shrinker event remains recoverable until its redacted artifact,
terminal record, and journal `after` record are durable. A post-commit artifact
failure therefore requeues the original private claim with the same internal
operation identity instead of silently discarding a completed mutation. An
inaccessible inbox is reported as `code_shrinker_inbox_unavailable`; it is
never treated as an empty successful poll. Patch events waiting for human
review have no authority to archive or invalidate code claims. A deterministic
fault matrix verifies every durable boundary; transient pre-commit SQLite/I/O
failures, including an unreadable claimed body, remain retryable without overwrite.
Active sibling claims report `in_progress`, and colliding retry bodies receive a
fresh operation identity before processing. Non-regular or reparse inbox entries
are left untouched, counted as pending, and reported as blocked without exposing
their contents.

### Graph & entity tools
| Tool | Description |
|---|---|
| `memory_wiki_add_entity` | Add named entity with aliases |
| `memory_wiki_add_relation` | Add a scoped, directed relation with optional source claim and validity interval |
| `memory_wiki_graph_extract_claim` | Extract grounded relations from one visible claim when explicitly enabled |
| `memory_wiki_graph_query` | Query entity graph |

New entity and relation rows carry `visibility_scope`, owner identity, optional `source_claim_id`, and a validity interval. A relation linked to a claim inherits its visibility and disappears from graph queries when the claim is superseded, retired, or expired. Graph queries can include a bounded second hop. Model-facing graph reads, exports, and context packing enforce the same boundary. Old rows acquire the `legacy` marker during schema migration; their owner cannot be inferred from the process that starts Hermes. They remain hidden unless `MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH=1` is explicitly set for one shared authorization domain. To attribute old rows individually, use `python tools/migrate_legacy_graph.py --database PATH --mapping MAP.json` for a dry run, then repeat with `--apply --attest "I verified every graph row owner"` after reviewing the mapping. The apply path creates an SQLite backup. Example mapping: `{"records":[{"table":"entities","id":"ent_existing","visibility_scope":"chat","origin_bot_id":"verified-bot-id","origin_session_id":"verified-session-id"}]}`. The same tool accepts `preference_rules`, `review_queue`, and `secret_index` rows. Every mapping entry needs a verified owner; assign `global` only when the row was intentionally shared. Ownership migration of an old preference rule does **not** attest its content for the system prompt. Imported bundle graph rows remain gated because copying owner IDs across homes requires explicit remapping. New preference candidates and review items carry owner scope; old rows remain closed unless their respective shared-domain flag is set. Local admin secret metadata defaults to private visibility; its owner-tagged rows can be queried when the local index is enabled. Bulk claim maintenance that cannot yet filter by owner is denied whenever the database contains claims hidden from the current session.

`memory_wiki_graph_extract_claim` requires `MEMORY_WIKI_GRAPH_EXTRACT_ENABLED=1`, a configured chat model and API key, and a specific visible claim ID. It sends at most 4,000 characters of that claim to the configured endpoint. Strict JSON parsing accepts up to eight directed relations whose subject, object, and evidence appear in the claim text; unsupported predicates or ungrounded output fail before any write. `apply=false` previews proposals. Applied relations go through `memory_wiki_add_relation` and the normal journal, so replay never calls the remote model. Model extraction can still misinterpret a stated relationship; review important edges and use corrections to supersede their source claim.

`MEMORY_WIKI_GRAPH_AUTO_EXTRACT=1` adds a bounded synchronous step after grounded session claims are persisted. It never sends raw transcript text: only a new active/current public chat claim with `memory-wiki-extraction-evidence-v1` provenance can qualify. A conservative local relation-verb filter skips preferences and other claims unlikely to produce an allowed edge. Claims that already own any relation are not sent again. The per-session call cap and total deadline apply before each request; request or write failures are counted in a content-free audit record and never fail session shutdown. Relations keep the source claim's ACL and lifecycle through the ordinary journaled relation writer.

Session history and path-based bundle import have the same boundary. With `MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK=1`, the default session-history path can read only `sessions/session_<current-session-id>.json` when its `session_id` matches the host-issued current session, and any present bot/project IDs match too. The ambiguous `default` session ID, links, and oversized files are skipped. Set `MEMORY_WIKI_ALLOW_SHARED_SESSION_HISTORY=1` only when all session files belong to one authorization domain and cross-session recall is intended. Path-based bundle import is disabled unless `MEMORY_WIKI_ALLOW_PATH_BUNDLE_IMPORT=1`; use an inline bundle payload when a trusted caller already has the content. Legacy session files without an exact current-session match remain unavailable by default.

Inline export/import and sync bundles bind newly imported claims to the receiving context's chat/private owner. Model-facing import cannot turn a supplied visibility field into a global or project-wide claim. Intentionally restoring global or project visibility requires a trusted host-level migration route with reviewed ownership and provenance.

The audit log returns only new owner-tagged private events to model-facing tools by default. Legacy and host-wide events have no safe owner and remain hidden. `MEMORY_WIKI_ALLOW_SHARED_AUDIT_LOG=1` exposes the complete audit log for a deliberately shared authorization domain. Journal status remains available, but malformed journal lines are reported without their raw prefixes.

Full-store recovery artifacts have the same ownership gap, including old backups and journal checkpoints that may contain data absent from the current database. Model-facing `memory_wiki_backup`, `memory_wiki_list_backups`, `memory_wiki_restore`, `memory_wiki_journal_checkpoint`, and `memory_wiki_rebuild_from_journal` require `MEMORY_WIKI_ALLOW_SHARED_RECOVERY=1`. This includes dry-run journal rebuilds and restores by backup ID or path. A checkpoint serializes shared claims and legacy rows into a JSON file and returns its path, even if it excludes secret values. Keep the flag off when chats, profiles, or agents sharing a Hermes home have different access rights; trusted internal recovery remains available. ZIP integrity checks protect archive structure, not ownership or provenance. A signed owner label on a full SQLite archive would still not make whole-store replacement safe across isolated contexts, so this host gate remains.

For model-facing recovery without that host flag, use `memory_wiki_scoped_backup`, `memory_wiki_list_scoped_backups`, and `memory_wiki_restore_scoped_backup` with the returned opaque `backup_id`. Scoped snapshots contain claims created by the same bot/session with a matching or empty project ID, plus their evidence, contradictions whose two claims are owned, and code claim metadata. Legacy rows without creator metadata, secret or quarantined claims, non-public claims, and claims with detected raw secrets in linked evidence or metadata are excluded. Remaining strings are redacted before writing. A host-local 256-bit key authenticates each JSON artifact; preserve `memory-wiki/.scoped-backup-key` together with `memory-wiki/backups/scoped/` for recovery after SQLite loss. Restore validates the signed owner and every claim/reference, rejects ID collisions with another creator, then merges the saved rows. It restores updates and physically deleted owned claims while preserving unrelated and later-created rows. It does not roll back claims added after the snapshot, restore audit/secret/graph data, or replace a whole database. The scoped backup files contain public claim content in plaintext and should receive the same filesystem protection as the SQLite database. The signing key is not a separate security boundary against code running as the same OS account. Use trusted-host full backups for excluded data.

Full list: 120 tools in `plugin.yaml` (generated from `get_tool_schemas()`).

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

# Unified recall returns exact pending event linkage for final claims:
result = memory_wiki_recall({"query": "proxy port"})
link = result["recall_tracking"]["answer_linkage"]

# After answer evaluation, bind one terminal outcome to those exact events.
# Repeating the same answer_id + claim + outcome is idempotent.
memory_wiki_mark_used({
    "claim_ids": link["claim_ids"],
    "recall_event_ids": link["recall_event_ids"],
    "answer_id": "answer-2026-09-21-001",
    "outcome": "helpful",
    "usefulness": 0.9,
})
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


## Document indexing support (v1.22.3)

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
- Reassigning an already indexed path to another scope additionally requires `MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION=1`; ordinary ingestion never transfers source ownership.
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

**Windows:** do not use `/root/.hermes/...`. The cache defaults to `%LOCALAPPDATA%\hermes\cache\documents`, so the cache-dir setting is optional. Persist only non-secret settings for future Desktop/gateway processes:

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

### Atomic claim edit batches

`memory_wiki_transaction` accepts up to 50 operations. With `mode=apply`, a batch of two or more `update_claim`, `rewrite_claim`, or `merge_claims` operations commits in one SQLite transaction. Claim rows, evidence moves, FTS/outbox triggers, cache revisions, and mutation records roll back together if any step fails. The response sets `atomic=true`, `rolled_back`, and `success` accordingly. A multi-operation batch containing any other tool is rejected before writing. `stop_on_error` applies to the legacy single-operation path; an atomic batch always rolls back on its first error. `apply_with_backup` still requires trusted-host shared-recovery authorization because its preliminary backup covers the whole store.

## Recovery

### After process crash during write
The transactional outbox ensures claim writes and index tasks are atomic:
- Claim + evidence + history + outbox → one SQLite COMMIT
- If process crashes before COMMIT → nothing saved (rollback)
- If process crashes after COMMIT → all 4 parts persisted
- Outbox worker picks up pending tasks on next run
- Completed document/code graph mutations create a post-`after` logical checkpoint containing durable graph rows but no raw source bodies. Recovery replays supported events only; unsupported, incomplete `before`, or error events fail closed before any live-database swap.
- `memory_wiki_maintenance` is a strict zero-argument maintenance operation: unsupported fields are rejected before journaling. A successful operation receives a post-operation checkpoint when it can be written. If that optional checkpoint fails, the response reports it explicitly; recovery safely ignores this derived-state operation and rebuilds FTS/pages rather than blocking a database swap.
- Post-checkpoint document writes are replayed from `document_source_ref/v1`: an allowlist-root fingerprint, relative locator, source hash, parser version, scope and structural counts. JSONL contains neither document text nor absolute source paths. Missing, changed, parser-incompatible or out-of-scope sources block the swap.
- Code graph snapshots and patch events are retained as content-addressed, sanitized immutable artifacts under `memory-wiki/recovery-artifacts/`; JSONL stores only artifact digest, size, producer/version and non-content identity metadata. Artifact hash mismatch or absence blocks the swap. New snapshot artifacts seal the normalized raw-payload digest inside their immutable redacted envelope, so an exact live retry deduplicates while a changed secret-only body conflicts. A provenance-bound legacy artifact without that raw digest can replay its safe body, but any later live producer retry must use a new event ID rather than relying on a producer-supplied snapshot hash. Graph-event reservation, claim invalidation, graph rows and final metadata still commit in one SQLite transaction.
- Journaled work is serialized across provider instances and processes for the whole `before → mutation → after → checkpoint` interval. Manual checkpoints and rebuilds use that same boundary, so they cannot checkpoint another writer's half-finished pair. A deliberately exact, non-mutating empty-inbox marker is replayable; every other unmatched `before` remains an incomplete operation that blocks a swap.
- Journal-control fields supplied by external tool arguments are rejected. Internal recursive calls use an unforgeable in-process capability, preventing a producer from suppressing required journal records.
- Document/code embedding batches recompute against the temporary recovery DB with external outbox workers suppressed. After a verified swap, the outbox is woken against the live DB; a recorded semantic reindex runs only after that swap and reports any external failure without replacing a valid recovered database.
- Recovery verifies the entire append-only journal hash chain before planning or applying events.
- A recovery checkpoint must be a published file under the local checkpoint directory; its manifest path, ID, sequence and SHA-256 digest are verified before the temporary DB is built.

### After Qdrant/OpenRouter outage
- FTS5 search continues working without Qdrant
- Outbox tasks remain pending (retry up to 5 times)
- Remote reranker has retries, circuit breaker, cache and fallback to RRF scoring
- `memory_wiki_reindex` has resumable checkpoints

### Database maintenance
```python
memory_wiki_doctor()  # Read-only diagnostic; write_probes_run=false
memory_wiki_doctor({"repair": True})  # Write probes, WAL checkpoints, and repairs
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

- **v1.23.0 (2026-09-21)**: Adds evidence-first unified recall across claims, paired dialogue episodes, append-only events, versioned observations and graph relations, with stable citations and multilingual `fast`/`auto`/`deep` planning. Episode retrieval now has an owner-scoped SQLite/FTS source of truth, an optional Qdrant hybrid index, durable vector-target cleanup and bounded context rendering. Grounded OpenRouter extraction, bounded graph enrichment, explicit recall outcomes and a TTL/LRU/single-flight embedding cache improve memory formation and feedback. Qdrant payload ACLs are rechecked against SQLite; claim and episode retargeting fan out privacy deletion to historical physical collections. Secret scanning covers complete pre-truncation inputs and outbound model/embedding boundaries, authenticated HTTP calls reject redirects, and memory removal retires exact visible matches plus derived event/observation evidence within the same ACL partition. This release also includes the earlier local hardening for journal serialization and replay, code/document graph atomicity, redaction, inbox durability, schema validation and checkpoint safety.
- **v1.22.3 (2026-08-29)**: Fixes the final Windows validation gaps: missing-source pruning now compares both lexical and canonical Windows path identities, and FTS rebuild obtains an exclusive SQLite transaction so concurrent provider initialization cannot race table replacement. Supersedes the immutable but Windows-CI-failed `v1.22.2` tag.
- **v1.22.2 (2026-08-29)**: Corrects five late recovery-audit blockers. Document scans now capture every source action beyond display caps and include `prune_missing` deletions; journal recovery rejects truncated prefixes and orphan `after` events; keyed Code Shrinker metadata secrets are redacted before artifact retention; and checkpoint restores use dependency-safe table order. Supersedes the immutable but unsafe `v1.22.1` tag.
- **v1.22.1 (2026-08-29)**: Fixes a post-release privacy regression: complex tool results (including document inbox paths) are no longer copied into journal summaries. Sensitive recovery-reference capture errors are redacted, and recovery now verifies a published local checkpoint manifest's path, ID, sequence and SHA-256 before any swap. Supersedes the immutable but CI-failed `v1.22.0` tag.
- **v1.22.0 (2026-08-29)**: Adds content-free event-specific recovery for document ingest/scan/inbox/delete/embedding and automatic attachment-cache ingestion. Code graph snapshots/patches replay from sanitized SHA-256 immutable artifacts; direct code claims and patch outcomes use verified request artifacts; revision invalidations replay from identifier/hash references. The journal payloads hide source paths/text, chain integrity is verified before rebuild, code/document embedding work stays local to the temporary DB, and semantic reindexing runs only after a verified live-DB swap.
- **v1.21.2 (2026-08-28)**: Closed the final post-release audit findings: terminal inbox manifests are exactly-once, configured ZIP member limits now fail closed for OOXML/ODF/EPUB, cross-scope source relabeling requires an explicit migration gate, and unpublished raced checkpoints cannot become recovery baselines. Every GitHub Action ref is now pinned to an immutable commit SHA.
- **v1.21.1 (2026-08-28)**: Release workflow now emits a separate SLSA build-provenance attestation in addition to the SPDX SBOM attestation; v1.21.0 remains immutable but lacks that provenance predicate.
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

This source package includes the runtime modules required by the advertised code and document graph tools. `plugin.yaml`, the MCP schema cache and the Python provider are synchronized from the same 120-schema source. `memory_wiki_compare_search` now performs real FTS-only, vector-only and hybrid runs without mutating process-wide environment variables. Backup restore validates archive entry count, uncompressed size, member size and compression ratio before creating a safety backup or writing staged files.


## Automatic prefetch hardening in v1.20.4

- `MEMORY_WIKI_PREFETCH_CLAIM_LIMIT` and `MEMORY_WIKI_MAX_PREFETCH_CHARS` remain upper bounds.
- Prefetch searches an expanded pool, but only claims with an actual lexical/vector/rerank/topic signal may fill the soft minimum.
- Every main claim, revision delta, evidence item and contradiction line passes the same observable Injection Guard path.
- A plan-only `<memory-context>` is no longer emitted. If candidates exist but all are withheld, the prompt receives a compact non-content diagnostic instead of a misleading Recall plan.
- `memory_wiki_debug_search` now reports guard status/signals per post-filter candidate and does not increment recall counters.
- `memory_wiki_semantic_status` exposes `last_prefetch` telemetry. Audit events use `op=prefetch` with searched/relevant/rendered/quarantined/output size.
- Strict mode never bypasses a trust-core quarantine merely to meet the minimum. A guard disagreement is reported separately so false positives can be fixed without weakening security.
