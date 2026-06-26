# Hermes Memory-Wiki v1.4.1

**Native durable memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — SQLite FTS5 + TF-IDF + qdrant/embed semantic search.**

24 database tables, 35+ tools, zero external Python dependencies. Works on Android/Termux proot, Linux VPS, and desktop.

---

## 🔍 Hybrid Search: Three-Layer Architecture

Memory-Wiki uses **Reciprocal Rank Fusion (RRF)** to merge three independent search layers:

| Layer | Mechanism | Weight | Always Available |
|---|---|---|---|
| **FTS5** | SQLite full-text search with BM25 ranking | Primary | ✅ Yes |
| **TF-IDF** | Local word-level vectors → SQLite cosine similarity (6000 features) | ×0.7 | ✅ Yes |
| **qdrant/embed** | HTTP stubs (:4000 + :6333) with character n-gram vectors | ×0.5 | When running |

Query mode auto-detection (technical vs semantic vs mixed) adjusts lexical/semantic weights dynamically.

### Why Three Layers?

- **FTS5**: exact matches, keyword search, phrase queries — always correct
- **TF-IDF**: word-level semantic similarity without neural networks — fast, local, stdlib-only
- **qdrant/embed**: broader vector search using character n-grams — different angle, more diversity

If any layer fails: graceful degradation to remaining layers. No single point of failure.

---

## 📦 Quick Start

### 1. Install Plugin

```bash
cp -r memory-wiki/ ~/.hermes/plugins/memory-wiki/
```

### 2. Enable in config

```yaml
# ~/.hermes/config.yaml
memory:
  provider: memory-wiki
plugins:
  enabled:
    - memory-wiki
```

### 3. (Optional) Start semantic stubs

```bash
# Start embed stub (character n-gram vectorization)
python3 semantic/embed_stub.py &
# Start qdrant stub (vector storage/search)
python3 semantic/qdrant_stub.py &
```

Or via glinomes-infra:
```bash
glinomes-infra ensure-embed
glinomes-infra ensure-qdrant
```

### 4. Restart Hermes

```bash
glinomes restart
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│              Hermes Agent                        │
│  ┌───────────────────────────────────────────┐  │
│  │         Memory Provider (Lifecycle)        │  │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────┐ │  │
│  │  │  FTS5    │ │  TF-IDF  │ │  qdrant    │ │  │
│  │  │  BM25    │ │  cosine  │ │  HTTP      │ │  │
│  │  └────┬─────┘ └────┬─────┘ └─────┬──────┘ │  │
│  │       │             │              │        │  │
│  │       └─────────┬───┴──────────────┘        │  │
│  │            RRF Fusion                       │  │
│  │                 │                           │  │
│  │          ┌──────┴──────┐                    │  │
│  │          │   Scoring    │                    │  │
│  │          │ confidence   │                    │  │
│  │          │ salience     │                    │  │
│  │          │ freshness    │                    │  │
│  │          │ trust        │                    │  │
│  │          │ verified     │                    │  │
│  │          └──────────────┘                    │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### Core Tables

| Table | Purpose |
|---|---|
| `claims` | Main memory — 35 columns including confidence, salience, freshness, trust, verification |
| `claims_fts` | FTS5 full-text index over claims |
| `claims_simhash` | 64-bit SimHash fingerprints for near-duplicate detection |
| `semantic_vectors` | TF-IDF vectors (BLOB) for local cosine similarity search |

### Knowledge Graph

| Table | Purpose |
|---|---|
| `entities` | Named entities with aliases |
| `relations` | `subject → predicate → object` with confidence scores |

### Quality & Review

| Table | Purpose |
|---|---|
| `review_queue` | Claims awaiting human review |
| `contradictions` | Detected contradictions between claims |
| `source_artifacts` | Archived raw tool outputs |
| `retrieval_eval_cases` | Evaluation benchmarks for retrieval quality |

### Secrets

| Table | Purpose |
|---|---|
| `secret_index` | Redacted credential index |
| `secret_quarantine` | Quarantined secret-like material |

### Operations & Audit

| Table | Purpose |
|---|---|
| `memory_changes` | Change log |
| `memory_mutations` | Append-only mutation ledger with undo support |
| `audit_log` | Operation audit trail |
| `recall_events` | Recall history with scores |

### Tasks & Decisions

| Table | Purpose |
|---|---|
| `task_capsules` | Task outcome capsules (plan, errors, fixes, verification) |
| `post_task_log` | Post-task summaries |
| `decisions` | Architectural decisions with rationale and alternatives |
| `mistakes` | Anti-regression lessons |

### Configuration

| Table | Purpose |
|---|---|
| `preference_rules` | Priority rules: current > explicit_correction > pinned > verified > stale |
| `source_policies` | Ingestion policies per source type |
| `topic_aliases` | Topic name aliases |
| `project_profiles` | Project metadata |
| `sync_bundles` | Export/import bundles |

---

## 🛡️ Security & Integrity

### Write Firewall 2.0
- Claims pass through `memory_gate_decision()` — rejects tool output, raw blobs, system artifacts
- Source-aware policies: `explicit > curated > conversation > tool > unknown`
- Secret scanning: 16 regex patterns + quarantine

### Context Capsule Ban
- API-level: `ValueError` on `"context capsule"` in claim
- DB-level: SQL triggers `BEFORE INSERT/UPDATE` → `RAISE(FAIL)`

### Data Integrity
- **SHA256 backup checksum**: streaming hash → `.zip.sha256`, validated at restore
- **VACUUM INTO**: atomic hot backup without blocking
- **Atomic write**: `tempfile + fsync + os.replace` for all JSON/MD files
- **Append-only journal**: JSONL with replay recovery and checkpoints

### Input Limits
- `trg_min_claim_length`: claims must be ≥ 10 characters
- `trg_max_claim_length`: claims must be ≤ 8000 characters (DoS protection)

---

## 🧪 Scoring Formula

```
score = 3.2·lexical + exact + 1.0·confidence + 1.2·salience 
      + 0.65·freshness + 0.25·recency + access 
      + 0.95·quality + min(0.30, 0.55·usefulness) 
      + min(0.40, 0.90·trust) + 0.45·pinned + 0.35·verified
      + stale_penalty + risk_penalty + artifact_penalty
```

### Verified Immunity
Verified claims (`verification_status='verified'`) are protected:
- `stale_penalty = 0` (no decay penalty)
- `risk_penalty = 0` (risk category ignored)
- `freshness = max(freshness, 0.70)` (floor at 0.70)

### Freshness Decay
`freshness = exp(-age_days / 45.0)` — exponential decay with 45-day half-life

---

## 🔧 Deduplication

### Two-Tier System

| Tier | Method | Action |
|---|---|---|
| **Exact** | SHA256 of normalized claim | Merge if hash matches |
| **Near-duplicate** | 64-bit SimHash + Hamming distance ≤ 12 | Merge metadata (max conf/salience/quality) |

SimHash uses 4-gram character hashing — pure Python stdlib, no external libraries. Skip for claims < 50 characters.

---

## 🧪 Testing

### Fault Injection
| Variable | Effect |
|---|---|
| `MW_FAULT_INJECT_FTS_CORRUPT=1` | Simulates FTS5 index corruption |
| `MW_FAULT_INJECT_STALE=1` | Forces all claims to appear stale |
| `MW_FAULT_INJECT_BACKUP_CHECKSUM_MISMATCH=1` | Simulates backup checksum failure |

### Smoke Test
```bash
python3 scripts/smoke_test.py
```

### FTS5 Runtime Auto-Repair
On `sqlite3.DatabaseError` during FTS5 search: automatic `_rebuild_fts()` + retry with audit logging. No restart needed.

---

## 🌐 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_WIKI_SEMANTIC` | `1` | Enable semantic search |
| `MEMORY_WIKI_EMBED_URL` | `http://127.0.0.1:4000` | Embed stub URL |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant stub URL |
| `MEMORY_WIKI_RRF_K` | `60` | RRF fusion constant |
| `MEMORY_WIKI_FTS_TOP_K` | `200` | FTS5 candidates for rerank |
| `MEMORY_WIKI_VECTOR_TOP_K` | `200` | Vector search candidates |
| `MEMORY_WIKI_STRICT_RECALL` | `1` | Filter low-quality claims |
| `MEMORY_WIKI_DEBUG` | `0` | Debug logging to `/tmp` |
| `MW_FAULT_INJECT_FTS_CORRUPT` | `0` | Test: FTS corruption |
| `MW_FAULT_INJECT_STALE` | `0` | Test: force stale |
| `MW_FAULT_INJECT_BACKUP_CHECKSUM_MISMATCH` | `0` | Test: checksum fail |

---

## 📊 Comparison: Memory-Wiki vs Regular RAG

| Aspect | Regular RAG | Memory-Wiki |
|---|---|---|
| **Storage** | Vector DB + chunked documents | Structured claims with metadata |
| **Search** | Single vector similarity | 3-layer RRF fusion |
| **Quality** | No quality gates | Write firewall + review queue |
| **Contradictions** | None | Automatic detection + resolution |
| **Verification** | None | Verification pipeline + trust scores |
| **Secrets** | Stored as-is | Redaction + quarantine |
| **Recovery** | DB backup only | Journal replay + checkpoints |
| **Dependencies** | numPy, transformers, ONNX | **Zero** — pure Python stdlib |
| **Disk** | 500MB+ for embeddings | ~10MB for 3000 claims |
| **Platform** | Server only | Android/Termux/Linux |

---

## 📁 Repository Structure

```
memory-wiki/
├── __init__.py          # Main plugin (4240 lines, 310KB)
├── plugin.yaml           # Hermes plugin manifest
├── LICENSE               # CC0-1.0
├── README.md             # This file
├── .gitignore
├── scripts/
│   ├── smoke_test.py     # Plugin smoke test
│   └── memory_wiki_cli.py # CLI tools
└── semantic/
    ├── embed_stub.py     # HTTP embed stub (:4000)
    └── qdrant_stub.py    # HTTP qdrant stub (:6333)
```

---

## 🛠️ Requirements

- **Python**: 3.10+ (stdlib only — no pip install needed)
- **SQLite**: 3.35+ (for FTS5, VACUUM INTO, RETURNING)
- **Platform**: Linux, macOS, Android/Termux proot

Optional (for semantic stubs):
- `embed_stub.py` and `qdrant_stub.py` — pure Python HTTP servers

---

## 🤝 Contributing

1. Fork the repository
2. Make changes
3. Run `python3 scripts/smoke_test.py`
4. Run `python3 -m py_compile __init__.py`
5. Submit a pull request

---

## 📜 License

CC0-1.0 — Public Domain Dedication.

---

## ⚡ Version History

| Version | Date | Changes |
|---|---|---|
| **1.4.1** | 2026-06-26 | TF-IDF semantic search (6000 features), SimHash dedup, VACUUM INTO backup, SHA256 checksum, FTS5 runtime auto-repair, SQL triggers, verified immunity, fault injection hooks, 3-layer RRF fusion |
| 1.4.0 | 2026-06-18 | Journal recovery, mutation log, preference rules, secret firewall, verification pipeline |
| 1.3.0 | 2026-05-19 | Quality gate, review queue, source policies, topic hierarchy |
| 1.2.0 | 2026-05-01 | FTS5 integration, hybrid search, qdrant/embed stubs |
| 1.0.0 | 2026-04-15 | Initial release — SQLite claims + markdown vault |
