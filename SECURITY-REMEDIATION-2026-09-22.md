# Security remediation — 22 September 2026

The formal working-tree diff scan against `5982a96eeeff127e495cb259d9faeacbcf54a42c` reported nine findings. Its immutable report is stored outside this repository in the Codex security scan artifacts. The table records the corresponding implementation and focused regression coverage; the original scan predates these fixes and is not a post-fix clearance certificate.

| Finding | Remediation | Regression coverage |
| --- | --- | --- |
| Old checkpoint/ZIP can reactivate removed content | Authenticated, content-free erasure intent ledger outside backups; replay before restored data becomes readable | `test_privacy_erasure_replay.py` |
| Stale claim outbox points to an obsolete vector target | Retarget current upserts; queue historical deletion | `test_qdrant_payload_acl.py` |
| Current Qdrant API key reaches a historical endpoint | Never send current key to a different historical endpoint | `test_qdrant_payload_acl.py` |
| Short host removal leaves event evidence | Word-boundary removal covers all matching authorized rows | `test_host_memory_remove_privacy.py` |
| Graph extraction reverses subject and object | Require grounded subject, relation cue and object in order | `test_entity_graph_extraction.py` |
| One shared platform bot lets a chat evict peers | Partition event, observation and episode quotas by visibility owner | `test_event_scale_retention.py`, `test_memory_observations.py`, `test_episodic_memory.py` |
| Benchmark sends unscanned context to OpenRouter | Scan the complete outbound question and context; fail closed, sanitize errors | `test_longmemeval_adapter.py`, `test_locomo_adapter.py` |
| Claim extractor reverses participants | Ordered grounding for overlapping actor/object tokens | `test_session_extractor_grounding.py` |
| Legacy event FTS docid migration duplicates rows | Idempotent mapping backfill | `test_event_scale_retention.py` |

Additional audit repairs: loopback-only Tika requests bypass environment proxies and refuse redirects; query logs and FTS diagnostic records omit raw input/exception text; default episode deletion affects the caller's chat, with broad deletion requiring a trusted host bot identity. The original 119-tool MCP v1 schema is pinned to the base revision and verified by the compatibility checker.

The erasure ledger prevents removed content from returning to **active** memory. Previously created archives may still physically contain that content; operators must apply a separate archival deletion policy when physical erasure is required. Qdrant deletions from an old authenticated endpoint stay queued until endpoint-specific access is supplied. These are operational follow-ups, not reasons to expose current credentials to that endpoint.
