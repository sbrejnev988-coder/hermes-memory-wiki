#!/usr/bin/env python3
"""memory-wiki v1.10.0: native Hermes active-memory wiki vault — real Qdrant support, Cosine distance, env-configurable — ChaCha20 RFC 8439 AEAD vault, MW_VAULT_KEY support.

Stdlib-only, Android/proot friendly. Storage: SQLite + Markdown under
$HERMES_HOME/memory-wiki, protected by an append-only JSONL journal plus
logical checkpoints for replay recovery. Runs inside MemoryProvider lifecycle,
so recall is near prompt building and session lifecycle, not bolted on as MCP.

v1.5.0 — Cross-Source Collapse & Session Intelligence (2026-06-27):
  + Cross-source collapse: salience ranking with cross-source corroboration
  + Social closer detection: skip search for trivial messages
  + Context sanitization guard: prompt-injection detection (11 patterns)
  + Session extraction hooks (disabled by default — opt-in)

v1.0.0 – v1.4.0: initial release, journal, recovery, undo, transactions, backups,
  self-healing, write firewall, secret wrapping, task capsules, graph memory,
  topic hierarchy, collapse/dedup, decay, federation.
"""
