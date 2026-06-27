# Hermes Memory-Wiki v1.5.0

**Persistent, self-curating memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — no cloud, no Docker, no pip install.**

An agent that forgets everything between sessions is not a collaborator — it's a CLI wrapper. Memory-Wiki gives Hermes a real memory: structured claims with confidence scoring, hybrid semantic search, a verification pipeline, an append-only journal with replay recovery, and automatic session extraction via LLM. Every session adds durable knowledge instead of evaporating.

**40+ tools. 24 database tables. Zero external Python dependencies.** Runs on Android/Termux proot, Linux VPS, or desktop — anywhere Python 3.10 and SQLite 3.35 live.

v1.5.0 integrates algorithms from [Memory OS](https://github.com/ClaudioDrews/memory-os): cross-source salience collapse with Hebbian corroboration, social closer detection, context injection sanitization, LLM-powered session extraction, and exponential decay scanning.

---

## The Problem

You spend hours configuring Hermes, teaching it your stack, solving hard problems together. Next session: blank slate. It asks about your project structure. It rediscovers decisions you made last week. It treats every question as novel.

Stock Hermes has `memory` tool entries and `state.db` — both useful, neither sufficient for a long-running agent that should compound knowledge over time.

---

## What Memory-Wiki Is

Not a vector database. Not a RAG pipeline. **A structured memory operating system** — each memory is a claim with provenance: who said it, why it's believed, how confident we are, whether it's been verified, whether anything contradicts it. The system tracks freshness decay, near-duplicates, contradiction clusters, and maintains an append-only journal so nothing is ever lost.

Memory-Wiki runs as a native Hermes `MemoryProvider` plugin — it hooks into session lifecycle (`prefetch`, `on_session_end`, `on_memory_write`), injects relevant context before every LLM call, and writes structured capsules after every session.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Hermes Agent                               │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Memory-Wiki Provider (v1.5.0)                  │  │
│  │                                                             │  │
│  │  ┌──────────┐  ┌───────────┐  ┌─────────────┐              │  │
│  │  │  FTS5     │  │  TF-IDF    │  │  qdrant      │             │  │
│  │  │  BM25     │  │  cosine    │  │  HTTP stub   │             │  │
│  │  │  (always) │  │  (always)  │  │  (optional)  │             │  │
│  │  └─────┬─────┘  └─────┬──────┘  └──────┬───────┘             │  │
│  │        │              │                │                      │  │
│  │        └──────┬───────┴───────┬────────┘                      │  │
│  │              RRF Fusion       │                                │  │
│  │                               │                                │  │
│  │  ┌────────────────────────────┴───────────────────────────┐  │  │
│  │  │                Collapse (v1.5.0)                       │  │  │
│  │  │  Cross-source salience ranking + Hebbian corroboration │  │  │
│  │  │  Prune weak, amplify strong, dedup, budget survivors   │  │  │
│  │  └────────────────────────────┬───────────────────────────┘  │  │
│  │                               │                                │  │
│  │  ┌────────────────────────────┴───────────────────────────┐  │  │
│  │  │  Scoring: confidence + salience + freshness + trust    │  │  │
│  │  │  + verified_immunity + staleness + pinned + quality     │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  │                                                               │  │
│  │  ┌────────────────────────────────────────────────────────┐  │  │
│  │  │  Safety: Write Firewall + Secret Scanner + Quarantine  │  │  │
│  │  │  Sanitizer + Social Closer Gate + Context Capsule Ban  │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  │                                                               │  │
│  │  Storage: SQLite (claims, entities, relations, tasks,        │  │
│  │  decisions, mistakes, secrets, audit, journal, dashboards)    │  │
│  │  + Markdown pages + Metadata JSON                             │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Three Search Layers, One Fusion

Memory-Wiki searches through three independent layers and merges results with **Reciprocal Rank Fusion (RRF)**:

| Layer | Mechanism | Weight | Always Available |
|---|---|---|---|
| **FTS5** | SQLite full-text search with BM25 ranking | 1.0 | ✅ |
| **TF-IDF** | Local 6000-feature word vectors → cosine similarity in SQLite | 0.7 | ✅ |
| **qdrant/embed** | HTTP stubs (:4000 + :6333) with character n-gram hashing | 0.5 | When services are running |

Query mode auto-detection (technical vs semantic vs mixed) adjusts lexical/semantic weights dynamically. Any layer failure → graceful degradation to remaining layers.

### v1.5.0: Cross-Source Collapse

Before v1.5.0, recall emitted everything from every source — noise, duplicates, and weak signal all consumed context budget equally. Now, all candidates from memory-wiki, knowledge_search, and distill capsules flow through a single salience-ranked collapse:

1. **Prune** — weak paths removed relative to the strongest (not an absolute floor)
2. **Amplify** — cross-source agreement boosts salience: a fact that surfaces from memory-wiki AND knowledge_search outranks a lone strong hit (Hebbian: "fire together, wire together")
3. **Budget** — single cross-source budget (default 6 survivors)
4. **Dedup** — near-duplicate suppression by token overlap

The collapse is fail-open: any error returns inputs unchanged.

---

## Key Capabilities

### Durable Claims, Not Dead Documents

Every memory is a structured claim — not a chunked paragraph. Each claim carries:

- **confidence** (0–1): how sure we are
- **salience** (0–1): how important it is
- **freshness**: exponential decay with 45-day half-life
- **trust_score**: Bayesian estimate from helpful/unhelpful feedback
- **verification_status**: none → unverified → verified → disputed
- **contradictions**: automated detection of conflicting claims
- **evidence**: linked proof (file paths, command output, URLs)

### Write Firewall 2.0

Not everything should become memory. The firewall rejects:

- Raw tool output, JSON blobs, log dumps
- System/injection artifacts (`[IMPORTANT:...]`, `<script>`, etc.)
- Path-only fragments, non-semantic blobs
- Secret-like material (16 regex patterns → quarantine)
- Context capsules (API-level ValueError + SQL trigger)

Source-aware policies: explicit corrections > curated summaries > conversation fragments > raw tool output.

### Secret Handling

Credentials never land in active claims. The pipeline:

1. **Scanner** — 16 regex patterns detect API keys, tokens, passwords
2. **Quarantine** — flagged material goes to `secret_quarantine` for review
3. **Vault** — approved secrets stored in encrypted `secret_index` with redacted recall
4. **Recall** — queries return `[REDACTED_SECRET:<id>]` markers unless `reveal=true`

### Append-Only Journal + Recovery

Every mutation (add/update/retire/verify) writes to an append-only JSONL journal with hash-chained event IDs. Logical checkpoints capture full SQLite state. Recovery replays: latest checkpoint → all after-events → current state. The journal is both audit trail and disaster recovery.

### Session Extraction (v1.5.0)

At session end, the last 32 message exchanges are assembled into a transcript and sent to an LLM (configurable: DeepSeek, OpenRouter, or custom endpoint) with a specialized "session archivist" prompt. The LLM extracts structured entries — decisions, resolutions, discoveries — and feeds them directly into the claim store. Sessions below a significance threshold (score < 0.2) are skipped. Entirely optional: disable with `MW_EXTRACTION_ENABLED=0`.

### Scoring Formula

```
score = 3.2·lexical + exact + 1.0·confidence + 1.2·salience
      + 0.65·freshness + 0.25·recency + access
      + 0.95·quality + min(0.30, 0.55·usefulness)
      + min(0.40, 0.90·trust) + 0.45·pinned + 0.35·verified
      + staleness_penalty + risk_penalty + artifact_penalty
```

**Verified Immunity**: verified claims are protected — no staleness penalty, no risk penalty, freshness floor at 0.70.

### Deduplication

| Tier | Method | Action |
|---|---|---|
| **Exact** | SHA256 of normalized claim | Merge if hash matches |
| **Near-duplicate** | 64-bit SimHash + Hamming distance ≤ 12 | Merge metadata, keep max confidence/salience |

SimHash uses 4-gram character hashing — pure Python stdlib.

### Knowledge Graph (Lightweight)

- **Entities**: named things with aliases (`{name, type, aliases, notes}`)
- **Relations**: `subject → predicate → object` edges with confidence scores
- **Graph queries**: traverse entity neighborhoods, filter by relation type

### Structured Data Types

Beyond flat claims, memory-wiki supports typed records:

| Type | Schema | Example |
|---|---|---|
| **Decision** | decision, rationale, alternatives, topic | "Use SQLite for memory store", "Faster than Postgres for <100K rows, zero setup" |
| **Mistake** | trigger, mistake, fix, prevention | "Edited config.yaml with sed", "sed -i destroyed YAML structure", "Use Node.js script + SCP" |
| **Task Capsule** | intent, plan, files, commands, errors, fixes, verification, followups | Full post-mortem of a completed task |
| **Project Profile** | project_id, root, purpose, commands, services, notes | Repository metadata for context injection |

### Exponential Decay Scanner (v1.5.0)

Claims age. The decay scanner applies `exp(-ln(2) · age_days / half_life)`:

- High confidence×salience (≥0.7) → 180-day half-life
- Medium → 90 days
- Low → 30 days

High-confidence claims (≥0.7) are **never** auto-archived — only flagged for human review. A monthly cron job reports stale candidates.

### Fault Injection for Testing

Three environment variables enable fault simulation without breaking production:

| Variable | Effect |
|---|---|
| `MW_FAULT_INJECT_FTS_CORRUPT=1` | Simulates FTS5 index corruption |
| `MW_FAULT_INJECT_STALE=1` | Forces all claims to appear stale |
| `MW_FAULT_INJECT_BACKUP_CHECKSUM_MISMATCH=1` | Simulates backup checksum failure |

FTS5 runtime auto-repair: on `DatabaseError` during search, rebuilds FTS index and retries — no restart needed.

---

## Quick Start

### 1. Install

```bash
cp -r memory-wiki/ ~/.hermes/plugins/memory-wiki/
```

### 2. Enable

```yaml
# ~/.hermes/config.yaml
memory:
  provider: memory-wiki
plugins:
  enabled:
    - memory-wiki
```

### 3. (Optional) Semantic Stubs

```bash
python3 semantic/embed_stub.py &   # :4000 — character n-gram vectors
python3 semantic/qdrant_stub.py &  # :6333 — vector storage/search
```

Both are pure Python stdlib — no Docker, no pip.

### 4. Restart

```bash
glinomes restart
```

---

## Tool Reference (40+ tools)

### Core Memory
| Tool | Purpose |
|---|---|
| `memory_wiki_query` | Search claims with FTS5 + semantic + salience scoring |
| `memory_wiki_add_claim` | Add/update a durable claim |
| `memory_wiki_recall_plan` | Plan topic/type/secret recall strategy |
| `memory_wiki_active_dashboard` | Active operational memory dashboard |

### Quality & Review
| Tool | Purpose |
|---|---|
| `memory_wiki_doctor` | Full diagnostics: schema, FTS, dashboards, secrets, contradictions |
| `memory_wiki_curate` | Review queue management |
| `memory_wiki_lint_claim` | Validate claim against quality rules |
| `memory_wiki_contradiction` | Detect and resolve contradictions |

### Secrets
| Tool | Purpose |
|---|---|
| `memory_wiki_add_secret` | Index a credential (redacted recall) |
| `memory_wiki_query_secrets` | Search secret vault (redacted by default) |
| `memory_wiki_secret_quarantine` | Review quarantined secret-like material |

### Structured Data
| Tool | Purpose |
|---|---|
| `memory_wiki_add_decision` | Record architectural decision + rationale + alternatives |
| `memory_wiki_add_mistake` | Record anti-regression lesson |
| `memory_wiki_add_task_capsule` | Post-task capsule: plan, errors, fixes, verification |
| `memory_wiki_add_project_profile` | Project metadata for context injection |
| `memory_wiki_add_entity` | Register a named entity with aliases |
| `memory_wiki_graph_query` | Query lightweight knowledge graph |

### Operations
| Tool | Purpose |
|---|---|
| `memory_wiki_backup` | Full ZIP backup with SHA256 checksum |
| `memory_wiki_restore` | Restore from backup |
| `memory_wiki_export` | Export bounded claims/evidence/contradictions JSON |
| `memory_wiki_import_bundle` | Import sync bundle |
| `memory_wiki_reindex` | Re-index all active claims into Qdrant |
| `memory_wiki_undo_last` | Undo most recent mutation |

### v1.5.0 Additions
| Tool | Purpose |
|---|---|
| `memory_wiki_decay_scan` | Scan claims with exponential decay scoring |
| `memory_wiki_decay_stats` | Decay statistics: total/active/archived |
| `memory_wiki_decay_archive` | Archive stale claims (high-conf protected) |
| `memory_wiki_context_sanitize` | Sanitize text: strip injection patterns |
| `memory_wiki_is_social_close` | Check if message is a trivial social closer |

---

## Comparison: Memory-Wiki vs RAG vs Memory OS

| Aspect | Classic RAG | Memory OS | Memory-Wiki |
|---|---|---|---|
| **Infrastructure** | Vector DB + embed model | Docker (Qdrant+Redis+ARQ) | **SQLite + stdlib stubs** |
| **Storage** | Chunked documents | 7 layers (MD → Qdrant) | Structured claims (24 tables) |
| **Search** | Single vector similarity | Collapse: 4-source ranking | **3-layer RRF + collapse** |
| **Quality gates** | None | training_value + verified | **Write firewall + review queue** |
| **Contradictions** | None | None | **Automatic detection** |
| **Verification** | None | Passive field | **Active pipeline + immunity** |
| **Secrets** | Stored as-is | Plain SQLite | **Redaction + quarantine + vault** |
| **Recovery** | DB backup | DB backup | **Journal replay + checkpoints** |
| **Dependencies** | numpy, transformers, ONNX | Docker, Redis, ARQ, fastembed | **Zero** |
| **Disk (3000 items)** | 500MB+ | 200MB+ | **~10MB** |
| **Platform** | Server only | Server only | **Android/Termux/Linux** |
| **Session extraction** | N/A | ✅ LLM archivist | ✅ **LLM archivist (v1.5.0)** |
| **Decay/archival** | N/A | ✅ Qdrant-based | ✅ **SQLite-based (v1.5.0)** |
| **Cross-agent handoff** | N/A | ✅ fabric_pending | N/A (single-agent) |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_WIKI_SEMANTIC` | `1` | Enable semantic search |
| `MEMORY_WIKI_EMBED_URL` | `http://127.0.0.1:4000` | Embed stub endpoint |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant stub endpoint |
| `MEMORY_WIKI_RRF_K` | `60` | RRF fusion constant |
| `MEMORY_WIKI_STRICT_RECALL` | `1` | Filter low-quality claims |
| `MEMORY_WIKI_DEBUG` | `0` | Debug logging to `/tmp` |
| `MW_EXTRACTION_ENABLED` | `1` | LLM session extraction |
| `MW_EXTRACTION_MODEL` | `deepseek-v4-pro` | Extraction model |
| `MW_EXTRACTION_BASE_URL` | `http://127.0.0.1:18089/v1/chat/completions` | LLM endpoint |
| `MW_EXTRACTION_API_KEY` | `godmode-internal-key` | API key for extraction |
| `MW_FAULT_INJECT_FTS_CORRUPT` | `0` | Test: FTS corruption |
| `MW_FAULT_INJECT_STALE` | `0` | Test: force stale |
| `MW_FAULT_INJECT_BACKUP_CHECKSUM_MISMATCH` | `0` | Test: checksum fail |

---

## Repository Structure

```
memory-wiki/
├── __init__.py                         # Main plugin (v1.5.0, ~4400 lines)
├── plugin.yaml                          # Hermes plugin manifest
├── memory_wiki_collapse.py              # Cross-source salience ranking
├── memory_wiki_context_guard.py         # Social closer + injection sanitizer
├── memory_wiki_decay.py                 # Exponential decay scanner
├── memory_wiki_session_extractor.py     # LLM-powered session archivist
├── LICENSE                              # CC0-1.0
├── README.md                            # This file
├── .gitignore
├── scripts/
│   ├── smoke_test.py                    # Plugin smoke test
│   └── memory_wiki_cli.py               # CLI tools
└── semantic/
    ├── embed_stub.py                    # HTTP embed stub (:4000)
    └── qdrant_stub.py                   # HTTP qdrant stub (:6333)
```

---

## Testing

```bash
# Smoke test
python3 scripts/smoke_test.py

# Compile check
python3 -m py_compile __init__.py memory_wiki_collapse.py memory_wiki_context_guard.py memory_wiki_decay.py memory_wiki_session_extractor.py

# Fault injection tests
MW_FAULT_INJECT_FTS_CORRUPT=1 python3 scripts/smoke_test.py
MW_FAULT_INJECT_STALE=1 python3 scripts/smoke_test.py
```

---

## Requirements

- **Python**: 3.10+ (stdlib only)
- **SQLite**: 3.35+ (FTS5, VACUUM INTO, RETURNING)
- **Platform**: Linux, macOS, Android/Termux proot

---

## Version History

| Version | Date | Changes |
|---|---|---|
| **1.5.0** | 2026-06-27 | Cross-source collapse (salience + Hebbian), social closer gate, context sanitization (12 injection patterns), LLM session extraction, exponential decay scanner, 5 new tools — algorithms adapted from Memory OS |
| 1.4.1 | 2026-06-26 | TF-IDF semantic search (6000 features), SimHash dedup, VACUUM INTO backup, SHA256 checksum, FTS5 runtime auto-repair, SQL triggers, verified immunity, fault injection hooks, 3-layer RRF fusion |
| 1.4.0 | 2026-06-18 | Append-only JSONL journal, hash-chained events, logical checkpoints, replay recovery, mutation log with undo, preference priority rules, secret firewall, verification pipeline |
| 1.3.0 | 2026-05-19 | Quality gate, review queue, source policies, topic hierarchy, contradiction detection |
| 1.2.0 | 2026-05-01 | FTS5 integration, hybrid search, qdrant/embed stubs, knowledge graph |
| 1.0.0 | 2026-04-15 | Initial release — SQLite claims + markdown vault |

---

## License

CC0-1.0 — Public Domain Dedication. No attribution required.

---

## Acknowledgments

v1.5.0 collapse, social closer, context sanitization, and decay scanner algorithms adapted from [Memory OS](https://github.com/ClaudioDrews/memory-os) by Claudio Drews (MIT License). Session extraction architecture inspired by Memory OS `on_session_end` → `_llm_extract_entries` pipeline.
