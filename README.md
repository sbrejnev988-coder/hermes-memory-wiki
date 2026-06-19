# Hermes Memory-Wiki

**Native long-term memory for AI agents on [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

SQLite FTS5 + Qdrant vectors + RRF hybrid search. 72 tools. Zero external dependencies — pure Python stdlib.

---

## Table of Contents

- [What It Is](#what-it-is)
- [Why Not Regular RAG](#why-not-regular-rag)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Quick Start](#quick-start)
- [Hybrid Search](#hybrid-search)
- [Tool Catalog](#tool-catalog)
- [Verification Pipeline](#verification-pipeline)
- [Write Firewall](#write-firewall)
- [Journal & Recovery](#journal--recovery)
- [Environment Variables](#environment-variables)
- [Smoke Tests](#smoke-tests)
- [Requirements](#requirements)
- [Development](#development)
- [License](#license)

---

## What It Is

Memory-wiki is not a note-taking app. It is an **operational memory subsystem** that lives inside Hermes as a native `MemoryProvider` and plugin:

- **Every fact (claim)** is stored with confidence, salience, freshness, trust class, and evidence
- **FTS5** provides exact lexical search — code, paths, endpoints, config keys, commands
- **Qdrant vectors** provide semantic search — similar concepts even with different words
- **RRF (Reciprocal Rank Fusion)** merges both layers into a single ranked result
- **Auto query mode detection**: technical queries → higher lexical weight; conceptual → higher vector weight
- **Memory Diff Before Answer**: compares recalled memory against verified facts before the agent responds
- **Write Firewall 2.0**: source policy + quality lint + secret scan before durable writes
- **Preference Priority Layer**: explicit user instructions trump stale background facts
- **Append-only JSONL journal** with hash-chain integrity + logical checkpoints for recovery
- **Verification pipeline**: curated sources → auto-verified; conversation sources → unverified
- **Contradiction handling**: conflicting claims are recorded explicitly, not silently coexisting
- **Secret firewall**: secrets detected → quarantined → redacted recall

> This is a **source-only repository**. Runtime data (SQLite DB, backups, secrets, sessions, logs) is excluded via `.gitignore`.

---

## Why Not Regular RAG

**Short version:** RAG retrieves documents. Memory-wiki manages agent memory.

| Dimension | Typical RAG | Memory-wiki |
|---|---|---|
| **Storage unit** | Chunk / document | Claim, evidence, preference, task capsule, decision, secret metadata, graph relation |
| **Lifecycle** | Usually none | Active / retired / superseded / uncertain / queued / review |
| **Trust / quality** | Source-level score | Confidence + salience + freshness + trust class + evidence + usage feedback |
| **Conflicts** | Both texts returned as-is | Explicit contradiction rows → policy / manual resolution |
| **Secrets** | Often unprotected | Secret scan → quarantine → redacted recall |
| **Operations memory** | None | Task capsules, project profiles, mistakes, decisions, mutation log |
| **Output** | Matching chunks | Sectioned `pack_context`: preferences / procedures / projects / diff / contradictions |
| **Maintenance** | Reindexing | Doctor / repair / backup / restore / FTS rebuild / topic normalization / compiler |
| **Integration** | External retriever | Native Hermes MemoryProvider + plugin tools |
| **Recovery** | Reindex from scratch | Journal replay + SQLite rebuild from checkpoints |
| **Feedback loop** | Rarely | `memory_wiki_mark_used` → usage telemetry → ranking improvement |

Memory-wiki **uses** RAG techniques internally (FTS5, semantic search, RRF fusion), but its job is broader: keep months of agent memory useful, auditable, curated, recoverable, and safe.

### Comparison with other Hermes memory subsystems

| Subsystem | What it stores | Search | Lifetime | Verification |
|---|---|---|---|---|
| **Memory-wiki** | Facts, lessons, preferences, configs | Lexical + Semantic + RRF | Permanent | ✅ curated→verified |
| `memory` tool | Raw profile text | Prompt injection only | Sessions | ❌ |
| `distill` | Compressed conversation capsules | FTS by key | Sessions + TTL | ❌ |
| `plur` | Episodic engrams | Cosine similarity | Seasonal (ACT-R decay) | ❌ |
| `secret-vault` | Credentials, tokens, keys | By ID | Permanent (encrypted) | ❌ |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Hermes Agent                        │
│  ┌───────────────────────────────────────────────┐  │
│  │          MemoryWikiProvider                    │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │           Recall Planner                 │  │  │
│  │  │  query → detect mode → plan topics/types │  │  │
│  │  └──────────────┬──────────────────────────┘  │  │
│  │                 │                              │  │
│  │     ┌───────────┴───────────┐                  │  │
│  │     ▼                       ▼                  │  │
│  │  ┌─────────┐          ┌──────────┐             │  │
│  │  │  FTS5   │          │ Qdrant   │             │  │
│  │  │ lexical │          │ semantic │             │  │
│  │  │ BM25    │          │ cosine   │             │  │
│  │  └────┬────┘          └────┬─────┘             │  │
│  │       │                    │                   │  │
│  │       └────────┬───────────┘                   │  │
│  │                ▼                               │  │
│  │         ┌─────────────┐                        │  │
│  │         │ RRF fusion  │                        │  │
│  │         │ k=60, auto  │                        │  │
│  │         │ weights     │                        │  │
│  │         └──────┬──────┘                        │  │
│  │                ▼                               │  │
│  │     ┌─────────────────────┐                    │  │
│  │     │  pack_context       │                    │  │
│  │     │  sectioned output   │                    │  │
│  │     │  → agent prompt     │                    │  │
│  │     └─────────────────────┘                    │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  Write path (tool result / explicit write)     │  │
│  │  scrub → redact → firewall → SQLite + journal  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘

Optional semantic services:
  semantic/embed_stub.py  →  :4000  character n-gram hashing (768-dim)
  semantic/qdrant_stub.py →  :6333  JSON vector store (cosine similarity)
```

**Key SQLite tables:** `claims`, `evidence`, `contradictions`, `secret_index`, `secret_quarantine`, `entities`, `relations`, `task_capsules`, `decisions`, `mistakes`, `project_profiles`, `preference_rules`, `recall_events`, `review_queue`, `mutation_log`, `audit_log`

**No AI required.** Embedding-stub and Qdrant-stub are pure Python stdlib — character n-gram hashing + cosine similarity. No GPU, no neural networks, no external APIs.

---

## Repository Structure

```
hermes-memory-wiki/
├── __init__.py              # MemoryProvider plugin (~3900 lines)
├── plugin.yaml              # Plugin metadata (v1.4.0, Hermes)
│
├── scripts/
│   ├── smoke_test.py        # End-to-end test suite (72 schemas, 6 audit events)
│   └── memory_wiki_cli.py   # Standalone CLI for maintenance without Hermes
│
├── semantic/                # Semantic search backends (stdlib-only)
│   ├── embed_stub.py        # Embedding server (:4000), char n-gram hashing, 768-dim
│   └── qdrant_stub.py       # Qdrant-compatible vector DB (:6333), JSON storage
│
├── README.md
├── LICENSE                  # MIT
└── .gitignore               # Excludes runtime DB, backups, secrets
```

---

## Quick Start

### Install the plugin

```bash
# Clone into Hermes plugins directory
mkdir -p ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-memory-wiki.git \
  ~/.hermes/plugins/memory-wiki
```

### Start semantic services (optional)

```bash
cd ~/.hermes/plugins/memory-wiki/semantic

# Both are pure Python stdlib — no dependencies
python3 embed_stub.py &    # → http://127.0.0.1:4000
python3 qdrant_stub.py &   # → http://127.0.0.1:6333
```

Without these, memory-wiki runs in FTS-only mode.

### Enable in Hermes

Add to `~/.hermes/config.yaml`:

```yaml
memory:
  provider: memory-wiki

plugins:
  enabled:
    - memory-wiki
```

Restart Hermes to reload the plugin registry.

### Verify installation

```bash
cd ~/.hermes/plugins/memory-wiki

# Syntax check
python3 -m py_compile __init__.py \
  scripts/smoke_test.py \
  scripts/memory_wiki_cli.py \
  semantic/embed_stub.py \
  semantic/qdrant_stub.py

# Smoke test (no LLM, no CDP, fully offline)
MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py
```

Expected output:

```json
{
  "ok": true,
  "home": "removed",
  "backup": "/tmp/memorywiki_smoke_xxxxxx/memory-wiki/backups/bak_...zip",
  "schemas": 72,
  "audit_events": 6
}
```

### Standalone CLI (without Hermes)

```bash
cd ~/.hermes/plugins/memory-wiki

# Full diagnostics
python3 scripts/memory_wiki_cli.py --home ~/.hermes doctor

# Search
python3 scripts/memory_wiki_cli.py --home ~/.hermes query "project configuration" --limit 10

# Context packing for LLM
python3 scripts/memory_wiki_cli.py --home ~/.hermes pack \
  "what context is relevant for this task" --max-chars 3800

# Backup
python3 scripts/memory_wiki_cli.py --home ~/.hermes backup --reason manual

# Dashboard
python3 scripts/memory_wiki_cli.py --home ~/.hermes dashboard

# Repair
python3 scripts/memory_wiki_cli.py --home ~/.hermes repair --target fts --apply
```

---

## Hybrid Search

```
user query
  │
  ├─► query mode detection (technical / semantic / mixed)
  │     technical: words, codes, paths → lexical weight 0.85
  │     semantic:  ideas, concepts     → vector weight  0.85
  │     mixed:     both                → balanced (0.5 / 0.5)
  │
  ├─► FTS5 top-200 (lexical, BM25 rank)
  │     Exact word/code/path matches
  │
  ├─► Qdrant vector top-200 (semantic, cosine)
  │     Meaning-level matches even with different words
  │
  ├─► RRF fusion (k=60, auto-weights per mode)
  │     RRF_score = Σ 1/(k + rank_i) for each source
  │
  └─► score_breakdown per claim
        confidence, salience, verified_boost, freshness, rrf
```

### Query mode debug logging

```bash
MEMORY_WIKI_DEBUG=1
# → /tmp/memory_wiki_debug.log
# Contents: query, query_mode, FTS candidates, vector candidates, RRF fused count
```

---

## Tool Catalog

Version 1.4.0 — **72 tools**. Organized by category below.

### Search & Context

| Tool | Description |
|---|---|
| `memory_wiki_query` | Hybrid search (FTS5 + Qdrant + RRF) |
| `memory_wiki_pack_context` | Collect relevant context for LLM |
| `memory_wiki_memory_diff` | Compare recalled memory vs verified facts |
| `memory_wiki_recall_plan` | Plan which topics/types/secrets to recall |
| `memory_wiki_preference_layer` | User preference priority layer |
| `memory_wiki_mark_used` | Feedback loop: usefulness scoring |
| `memory_wiki_debug_search` | Search with per-layer breakdown |
| `memory_wiki_compare_search` | FTS-only vs hybrid comparison |
| `memory_wiki_query_mode` | Detect query type |
| `memory_wiki_evaluate_retrieval` | Recall@k, MRR, NDCG metrics |

### Write & Update

| Tool | Description |
|---|---|
| `memory_wiki_add_claim` | Store a fact |
| `memory_wiki_add_evidence` | Attach evidence to a claim |
| `memory_wiki_update_claim` | Update confidence / salience / freshness |
| `memory_wiki_rewrite_claim` | Rewrite claim in-place |
| `memory_wiki_merge_claims` | Merge duplicates |
| `memory_wiki_pin_claim` | Pin a claim |

### Quality Control

| Tool | Description |
|---|---|
| `memory_wiki_review_queue` | Review queue (list / approve / reject / rewrite) |
| `memory_wiki_lint_claim` | Lint a candidate claim |
| `memory_wiki_write_firewall` | Pre-write quality check |
| `memory_wiki_source_policy` | Ingestion policy by source type |
| `memory_wiki_normalize_topics` | Topic alias normalization |
| `memory_wiki_immune_scan` | Auto-detect: secrets, blobs, bad topics, low-quality |
| `memory_wiki_compile_topic` | Compile micro-claims into curated summary |
| `memory_wiki_compress_topic` | Compress topic + supersede old claims |

### Contradictions & Provenance

| Tool | Description |
|---|---|
| `memory_wiki_contradict` | Record a contradiction |
| `memory_wiki_resolve_contradiction` | Manual resolution |
| `memory_wiki_resolve_by_policy` | Auto-resolve (prefer_explicit_user / prefer_recent / prefer_verified) |
| `memory_wiki_why_believe` | Provenance card: evidence, trust, contradictions |

### Operational Memory

| Tool | Description |
|---|---|
| `memory_wiki_add_decision` | Record a decision |
| `memory_wiki_add_mistake` | Record a mistake + fix + prevention |
| `memory_wiki_add_project_profile` | Project profile |
| `memory_wiki_get_project_context` | Project context |
| `memory_wiki_add_task_capsule` | Task capsule (plan, files, commands, verification) |
| `memory_wiki_add_preference_rule` | User preference rule |

### Graph Memory

| Tool | Description |
|---|---|
| `memory_wiki_add_entity` | Create an entity |
| `memory_wiki_add_relation` | Create a relation |
| `memory_wiki_graph_query` | Query the graph |

### Secrets

| Tool | Description |
|---|---|
| `memory_wiki_add_secret` | Add to secret index (redacted by default) |
| `memory_wiki_query_secrets` | Query secret index (reveal=false → redacted) |
| `memory_wiki_secret_quarantine` | Secret quarantine management |

### Maintenance & Recovery

| Tool | Description |
|---|---|
| `memory_wiki_health` | Quick health check |
| `memory_wiki_doctor` | Full diagnostics (tables, FTS, WAL, topics, journal) |
| `memory_wiki_repair` | Repair (fts / integrity / dashboards / all) |
| `memory_wiki_backup` | Backup SQLite + vault |
| `memory_wiki_list_backups` | List backups |
| `memory_wiki_restore` | Restore from backup |
| `memory_wiki_snapshot` | Human-readable snapshot |
| `memory_wiki_audit_log` | Audit log |
| `memory_wiki_mutation_log` | Mutation journal (before / after) |
| `memory_wiki_undo_last` | Undo last mutation |
| `memory_wiki_transaction` | Batch operations with dry-run |
| `memory_wiki_journal_status` | JSONL journal status + hash-chain |
| `memory_wiki_journal_checkpoint` | Create logical checkpoint |
| `memory_wiki_rebuild_from_journal` | Rebuild SQLite from journal |
| `memory_wiki_semantic_status` | Embedding / Qdrant health |
| `memory_wiki_reindex` | Re-index into Qdrant |
| `memory_wiki_export` | Export claims/evidence/contradictions JSON |
| `memory_wiki_export_bundle` | Export redacted sync bundle |
| `memory_wiki_import_bundle` | Import redacted sync bundle |
| `memory_wiki_recent_changes` | Show mutations since N seconds ago |

---

## Verification Pipeline

```
Claim source
  │
  ├─► curated (post_task, task_capsule, decision, mistake, project)
  │     → auto-verified ✅ (scoring boost +0.35)
  │
  ├─► tool (verified command output, config)
  │     → probable (boost +0.15)
  │
  ├─► explicit_user (direct instruction)
  │     → verified ✅ (boost +0.50)
  │
  └─► conversation / unknown
        → unverified ⚠️ (no boost, flagged for review)
```

Verified claims receive a scoring boost and are treated as authoritative during conflict resolution.

---

## Write Firewall

Before a durable write, every claim passes through:

1. **Source policy** — tool/task/decision → allow; raw/blob → queue
2. **Quality lint** — detects:
   - Artifacts (truncation markers, prompt wrappers, gateway noise)
   - Empty claims
   - System junk (interim_assistant fragments, tool output truncation markers)
3. **Secret scan** — if a key/password is found → quarantine, do not store in claims
4. **Deduplication** — check for near-duplicate claims before writing

Modes: `check` (dry-run), `queue` (into review_queue), `apply` (direct write).

---

## Journal & Recovery

```
Every mutation (write / update / delete)
  │
  ▼
append-only JSONL journal  (hash-chain: prev_hash → row_hash)
  │
  ▼  (periodic)
logical checkpoint (SQLite-compatible table snapshot with redacted secrets)
```

### Recovery procedure

```bash
# Step 1: check journal integrity
python3 scripts/memory_wiki_cli.py --home ~/.hermes doctor

# Step 2: if SQLite is corrupted — rebuild from latest checkpoint + journal
# (via Hermes tool):
# memory_wiki_rebuild_from_journal apply=true

# Step 3: verify
python3 scripts/memory_wiki_cli.py --home ~/.hermes doctor
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_WIKI_SEMANTIC` | `1` | Enable/disable semantic search |
| `MEMORY_WIKI_RRF_K` | `60` | RRF fusion constant |
| `MEMORY_WIKI_FTS_TOP_K` | `200` | Lexical candidates before fusion |
| `MEMORY_WIKI_VECTOR_TOP_K` | `200` | Semantic candidates before fusion |
| `MEMORY_WIKI_HYBRID_TOP_K` | `100` | Hybrid candidates after fusion |
| `MEMORY_WIKI_EMBED_URL` | `http://127.0.0.1:4000` | Embedding-stub endpoint |
| `MEMORY_WIKI_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant-stub endpoint |
| `MEMORY_WIKI_DEBUG` | `0` | Debug log → `/tmp/memory_wiki_debug.log` |
| `MEMORY_WIKI_LLM_PACK` | `0` | Optional LLM context refinement |
| `MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK` | `0` | Include session history in pack_context |
| `MEMORY_WIKI_STRICT_RECALL` | `1` | Strict active/non-stale recall |
| `MEMORY_WIKI_MAX_PREFETCH_CHARS` | `12000` | Max chars in provider prefetch |

---

## Smoke Tests

The smoke test requires no LLM, no CDP, and no network:

```bash
cd ~/.hermes/plugins/memory-wiki

# Basic
MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py

# Isolated home (no effect on real database)
tmp_home=$(mktemp -d)
HERMES_HOME="$tmp_home" MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py
```

**What it checks:**
- Plugin loading via `importlib`
- 72 tool schemas registered
- Claim CRUD: add → query → update → merge
- Evidence: add → `why_believe`
- Contradictions: detect → resolve (manual + policy)
- Secrets: add → redacted query → revealed query → no leak in any output path
- Lint, review_queue, decisions, mistakes, project profiles
- Task capsules, graph memory (entities + relations)
- Preference layer, `memory_diff`
- Journal: status → checkpoint → hash-chain verification
- Import/export bundles
- Backup, snapshot, audit_log, mutation_log
- `doctor`, `health`, `repair`
- Semantic status
- Zip-slip protection in backup restore
- Secret redaction verified in every output path (query, pack, diff, export, graph, dashboard)

---

## Requirements

- **Python 3.10+** — stdlib only, zero external pip dependencies
- **SQLite 3.35+** — required for FTS5
- **Hermes Agent** — as MemoryProvider plugin runtime
- **semantic/embed_stub.py + semantic/qdrant_stub.py** — optional, for hybrid search

---

## Development

```bash
# Syntax check
python3 -m py_compile __init__.py \
  scripts/smoke_test.py \
  scripts/memory_wiki_cli.py \
  semantic/embed_stub.py \
  semantic/qdrant_stub.py

# Smoke test
MEMORY_WIKI_LLM_PACK=0 python3 scripts/smoke_test.py

# Quick schema count
python3 - <<'PY'
import importlib.util, os, tempfile
spec = importlib.util.spec_from_file_location('mw', '__init__.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
os.environ['HERMES_HOME'] = tempfile.mkdtemp(prefix='mw_dev_')
p = mod.MemoryWikiProvider()
p.initialize('dev')
print(len(p.get_tool_schemas()))  # → 72
PY
```

**When changing schema fields, update all of these together:**
- SQLite migrations
- Import/export/sync bundle paths
- FTS rebuild/upsert logic
- `pack_context` rendering
- `doctor`/`repair` checks
- Smoke tests

---

## License

MIT. See [`LICENSE`](LICENSE).
