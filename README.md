# Hermes Memory-Wiki v1.5.0

**Hermes Memory Wiki — native long-term agent memory: 72 tools, hybrid search (FTS5 lexical + Qdrant semantic + RRF fusion), structured claims & evidence, write firewall, secret redaction, graph/project memory, task capsules, append-only journal with recovery, transactions, undo, backups & self-healing. Stdlib-only Python.**

An agent that forgets everything between sessions is not a collaborator — it's a CLI wrapper. Memory-Wiki gives Hermes a real memory: structured claims with confidence scoring, hybrid semantic search, a verification pipeline, an append-only journal with replay recovery, and automatic session extraction via LLM. Every session adds durable knowledge instead of evaporating.

**40+ tools. 24 database tables. Zero external Python dependencies.** Runs on Android/Termux proot, Linux VPS, or desktop — anywhere Python 3.10 and SQLite 3.35 live.

---

## Quick Start

### Requirements

- **Hermes Agent** 0.14.0 or later
- **Python** 3.10+ (stdlib only — no pip needed)
- **SQLite** 3.35+ (for FTS5, VACUUM INTO, RETURNING)

### Installation

**Step 1 — Copy the plugin**

```bash
git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git /tmp/memory-wiki
cp -r /tmp/memory-wiki ~/.hermes/plugins/memory-wiki
```

Or download manually and extract into `~/.hermes/plugins/memory-wiki/`.

**Step 2 — Enable in Hermes config**

Edit `~/.hermes/config.yaml`:

```yaml
memory:
  provider: memory-wiki

plugins:
  enabled:
    - memory-wiki
```

**Step 3 — (Optional) Start semantic stubs**

Two pure-Python HTTP servers that enhance search with character n-gram vector similarity:

```bash
python3 ~/.hermes/plugins/memory-wiki/semantic/embed_stub.py &   # port 4000
python3 ~/.hermes/plugins/memory-wiki/semantic/qdrant_stub.py &   # port 6333
```

These are optional — memory-wiki works fully without them. FTS5 and TF-IDF layers are always available. The stubs add a third search angle. Both use zero external dependencies.

**Step 4 — Restart Hermes**

```bash
hermes gateway restart
```

On Android/Termux proot, use your gateway launcher (e.g., `glinomes restart`).

**Step 5 — Verify**

Ask Hermes: "show me memory_wiki_active_dashboard"

Or run the smoke test:

```bash
python3 ~/.hermes/plugins/memory-wiki/scripts/smoke_test.py
```

---

## What Problem Does This Solve?

Stock Hermes has `memory` tool entries and `state.db` — both useful, neither sufficient for a long-running agent that should compound knowledge over time. You spend hours teaching it your stack, solving hard problems. Next session: blank slate. It rediscovers decisions you made last week.

Memory-Wiki turns every session into durable, structured knowledge — claims with provenance, confidence, verification status, and contradiction tracking. The agent doesn't just store facts; it knows why it believes them and whether anything disagrees.

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
│  │  │  Cross-source salience ranking + corroboration boost   │  │  │
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

| Layer | Mechanism | Weight | Always Available |
|---|---|---|---|
| **FTS5** | SQLite full-text search with BM25 ranking | 1.0 | ✅ Yes |
| **TF-IDF** | Local 6000-feature word vectors → cosine similarity in SQLite | 0.7 | ✅ Yes |
| **qdrant/embed** | HTTP stubs (:4000 + :6333) with character n-gram hashing | 0.5 | When running |

Query mode auto-detection (technical vs semantic vs mixed) adjusts lexical/semantic weights dynamically. Any layer failure → graceful degradation to remaining layers. No single point of failure.

### v1.5.0: Cross-Source Collapse

Before v1.5.0, recall emitted everything from every source — noise, duplicates, and weak signal all consumed context budget equally. Now, all candidates from memory-wiki, knowledge_search, and distill capsules flow through a single salience-ranked collapse:

1. **Prune** — weak paths removed relative to the strongest (not an absolute floor)
2. **Amplify** — cross-source agreement boosts salience: a fact surfaced by memory-wiki AND knowledge_search outranks a lone strong hit ("fire together, wire together")
3. **Budget** — single cross-source budget (default 6 survivors)
4. **Dedup** — near-duplicate suppression by token overlap

The collapse is fail-open: any error returns inputs unchanged.

---

## Durable Claims, Not Dead Documents

Every memory is a structured claim — not a chunked paragraph. Each claim carries:

| Field | Description |
|---|---|
| **confidence** (0–1) | How sure we are this claim is true |
| **salience** (0–1) | How important this claim is |
| **freshness** | Exponential decay with 45-day half-life |
| **trust_score** | Bayesian estimate from helpful/unhelpful feedback |
| **verification_status** | none → unverified → verified → disputed |
| **contradictions** | Automated detection of conflicting claims |
| **evidence** | Linked proof: file paths, command output, URLs |

### Scoring Formula

```
score = 3.2·lexical + exact + 1.0·confidence + 1.2·salience
      + 0.65·freshness + 0.25·recency + access
      + 0.95·quality + min(0.30, 0.55·usefulness)
      + min(0.40, 0.90·trust) + 0.45·pinned + 0.35·verified
      + staleness_penalty + risk_penalty + artifact_penalty
```

**Verified Immunity**: verified claims are protected — no staleness penalty, no risk penalty, freshness floor at 0.70.

---

## Key Subsystems

### Write Firewall 2.0

Not everything should become memory. The firewall rejects:
- Raw tool output, JSON blobs, log dumps
- System/injection artifacts (`[IMPORTANT:...]`, `<script>`, etc.)
- Path-only fragments, non-semantic blobs
- Secret-like material (16 regex patterns → quarantine)
- Claims below quality threshold

### Secret Handling

Credentials never land in active claims. The pipeline: **scan** (16 patterns) → **quarantine** (flag for review) → **vault** (encrypted storage) → **redacted recall** (returns `[REDACTED_SECRET:<id>]` markers unless `reveal=true`).

### Append-Only Journal + Recovery

Every mutation writes to an append-only JSONL journal with hash-chained event IDs. Logical checkpoints capture full SQLite state. Recovery replays: latest checkpoint → all after-events → current state. The journal is both audit trail and disaster recovery.

### Session Extraction (v1.5.0)

At session end, the last 32 message exchanges are sent to an LLM (configurable: DeepSeek, OpenRouter, or custom endpoint) with a specialized "session archivist" prompt. The LLM extracts decisions, resolutions, and discoveries as structured claims. Sessions below a significance threshold are skipped. Disable with `MW_EXTRACTION_ENABLED=0`.

### Exponential Decay Scanner (v1.5.0)

Claims age. The decay scanner applies `exp(-ln(2) · age_days / half_life)`:

| Confidence × Salience | Half-life |
|---|---|
| ≥ 0.7 | 180 days |
| 0.4–0.7 | 90 days |
| < 0.4 | 30 days |

High-confidence claims (≥0.7) are **never** auto-archived — only flagged for review.

### Deduplication

| Tier | Method | Action |
|---|---|---|
| **Exact** | SHA256 of normalized claim | Merge if hash matches |
| **Near-duplicate** | 64-bit SimHash + Hamming distance ≤ 12 | Merge metadata, keep max confidence/salience |

### Structured Data Types

Beyond flat claims, memory-wiki supports typed records:

| Type | Schema | Example |
|---|---|---|
| **Decision** | decision, rationale, alternatives | "Use SQLite for memory — faster than Postgres for <100K rows" |
| **Mistake** | trigger, mistake, fix, prevention | "sed -i destroyed YAML — use Node.js script + SCP instead" |
| **Task Capsule** | intent, plan, files, errors, fixes, verification | Full post-mortem of completed task |
| **Project Profile** | project_id, root, purpose, commands, services | Repository metadata for context injection |

### Knowledge Graph (Lightweight)

Named entities with aliases + `subject → predicate → object` edges with confidence scores. Graph queries traverse entity neighborhoods.

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
| `memory_wiki_doctor` | Full diagnostics: schema, FTS, secrets, contradictions |
| `memory_wiki_curate` | Review queue management |
| `memory_wiki_lint_claim` | Validate claim against quality rules |

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
| `memory_wiki_reindex` | Re-index all active claims into Qdrant |
| `memory_wiki_undo_last` | Undo most recent mutation |

### v1.5.0
| Tool | Purpose |
|---|---|
| `memory_wiki_decay_scan` | Scan claims with exponential decay scoring |
| `memory_wiki_decay_stats` | Decay statistics: total/active/archived |
| `memory_wiki_decay_archive` | Archive stale claims (high-conf protected) |
| `memory_wiki_context_sanitize` | Sanitize text: strip injection patterns |
| `memory_wiki_is_social_close` | Check if message is a trivial social closer |

---

## Comparison: Memory-Wiki vs Classic RAG

| Aspect | Classic RAG | Memory-Wiki |
|---|---|---|
| **Storage model** | Chunked documents in vector DB | Structured claims in SQLite (24 tables) |
| **Metadata** | Source filename, chunk index | confidence, salience, freshness, trust, verification |
| **Search** | Single cosine similarity | 3-layer RRF fusion (FTS5 + TF-IDF + qdrant) |
| **Search resilience** | Vector DB down = dead | Any 1-2 layers alive = works |
| **Quality control** | None — anything chunked is retrievable | Write firewall + review queue + quality scoring |
| **Contradictions** | None — identical facts in different chunks | Automatic detection + resolution tracking |
| **Verification** | None | Full pipeline: unverified → verified → disputed |
| **Secrets** | Stored as-is in text chunks | Scanned → quarantined → vaulted → redacted at recall |
| **Provenance** | None | Every claim: source, evidence, why_believe, audit trail |
| **Recovery** | Vector DB backup | Append-only JSONL journal + checkpoints + replay |
| **Dependencies** | numpy, transformers, ONNX, 500MB+ | **Zero** — pure Python stdlib |
| **Disk usage** (3000 items) | 500MB+ | ~10MB |
| **Platform** | Server only | Android/Termux/Linux/desktop |
| **Session extraction** | N/A | LLM archivist: transcript → structured claims |
| **Decay/archival** | N/A | Exponential decay: 3-tier half-life |

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
| `MW_EXTRACTION_BASE_URL` | `http://127.0.0.1:18089/v1/chat/completions` | LLM endpoint for extraction |
| `MW_EXTRACTION_API_KEY` | — | API key for extraction endpoint |
| `MW_FAULT_INJECT_FTS_CORRUPT` | `0` | Test: FTS corruption |
| `MW_FAULT_INJECT_STALE` | `0` | Test: force stale |
| `MW_FAULT_INJECT_BACKUP_CHECKSUM_MISMATCH` | `0` | Test: checksum fail |

---

## Repository Structure

```
memory-wiki/
├── __init__.py         # Main plugin (v1.5.0, ~4400 lines)
├── plugin.yaml          # Hermes plugin manifest
├── collapse.py          # Cross-source salience ranking
├── guard.py             # Social closer + injection sanitizer
├── decay.py             # Exponential decay scanner
├── extractor.py         # LLM-powered session archivist
├── LICENSE              # CC0-1.0
├── README.md            # This file
├── .gitignore
├── scripts/
│   ├── smoke_test.py    # Plugin smoke test
│   └── cli.py           # CLI tools
└── semantic/
    ├── embed_stub.py    # HTTP embed stub (:4000)
    └── qdrant_stub.py   # HTTP qdrant stub (:6333)
```

---

## Troubleshooting

**Plugin not loading after install?**
```bash
python3 -m py_compile ~/.hermes/plugins/memory-wiki/__init__.py
hermes gateway restart
```

**FTS5 search returning errors?**
Memory-wiki auto-repairs FTS5 indices on failure. If persistent:
```bash
memory_wiki_doctor repair=true
```

**Semantic stubs not working?**
Check they're running:
```bash
curl -s http://127.0.0.1:4000/health
curl -s http://127.0.0.1:6333/health
```
Memory-wiki works fully without them — only the third search layer is affected.

---

## Testing

```bash
# Smoke test
python3 scripts/smoke_test.py

# Compile check
python3 -m py_compile __init__.py collapse.py guard.py decay.py extractor.py

# Fault injection tests
MW_FAULT_INJECT_FTS_CORRUPT=1 python3 scripts/smoke_test.py
MW_FAULT_INJECT_STALE=1 python3 scripts/smoke_test.py
```

---

## Version History

| Version | Date | Changes |
|---|---|---|
| **1.5.0** | 2026-06-27 | Cross-source collapse (salience + corroboration), social closer gate, context sanitization, LLM session extraction, exponential decay scanner, 5 new tools |
| 1.4.1 | 2026-06-26 | TF-IDF semantic search (6000 features), SimHash dedup, VACUUM INTO backup, SHA256 checksum, FTS5 auto-repair, verified immunity, fault injection, 3-layer RRF |
| 1.4.0 | 2026-06-18 | JSONL journal, hash-chained events, checkpoints, replay recovery, mutation log with undo, preference rules, secret firewall |
| 1.3.0 | 2026-05-19 | Quality gate, review queue, source policies, topic hierarchy, contradiction detection |
| 1.2.0 | 2026-05-01 | FTS5 integration, hybrid search, qdrant/embed stubs, knowledge graph |
| 1.0.0 | 2026-04-15 | Initial release — SQLite claims + markdown vault |

---

## License

CC0-1.0 — Public Domain Dedication. No attribution required.
