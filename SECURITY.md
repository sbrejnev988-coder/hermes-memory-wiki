# Security policy

## Supported versions

Security fixes are made on the latest released minor version. Reproduce a
report against the current default branch before submitting it.

## Security properties

Memory Wiki treats model output, recalled text, tool results, documents,
session transcripts, benchmark data, and remote service responses as
untrusted input. Changes must preserve these properties:

- SQLite is the source of truth. FTS and Qdrant are disposable indexes and
  cannot grant access to a row that SQLite would reject.
- Chat, bot, private, project, and global visibility boundaries cannot be
  widened by model supplied metadata, cache reuse, graph traversal, vector
  search, migration, restore, or concurrent reindexing.
- Passwords, tokens, private keys, one time codes, and other raw credentials
  cannot enter ordinary memory tables, retrieval context, journals, logs,
  embedding requests, rerank requests, or extraction requests.
- Authenticated HTTP clients accept HTTPS or explicit loopback HTTP endpoints,
  reject credentials in URLs, and do not follow redirects.
- A completed privacy deletion is reflected immediately in SQLite, FTS,
  caches, and derived observations/events. Deletion from every recorded
  historical Qdrant target is durable and retried until successful; a stale
  vector can never authorize recall while cleanup is pending.
- Journal replay, checkpoint restore, and index cutover fail closed when
  integrity, ownership, or revision checks cannot be established.
- Recall citations must identify retained evidence and must not outlive the
  final authorization and integrity check performed for that response.

Security regression tests should use synthetic credentials and isolated
temporary profiles. Never use an active Hermes profile or a real secret in a
test fixture, issue, log, benchmark artifact, or pull request.

## Reporting a vulnerability

Use the repository's **Security** tab and its private vulnerability reporting
flow. Include the affected version, reachable attack path, minimum synthetic
reproduction, expected security property, and suggested regression test. Do
not include real memory databases, profile files, API keys, passwords, or
private conversation content.

If private reporting is unavailable, contact the maintainer privately before
opening a public issue. Public issues should contain only non-sensitive
coordination details until a fix is available.

## Review scope

Security review covers provider hooks and tools, SQLite schema and migrations,
ACL and partition identity, FTS/Qdrant synchronization, event and observation
derivation, graph traversal, extraction and embedding transports, caches,
journals, checkpoints, backup/restore, MCP schemas, and release packaging.
Compromise of the local operating-system account, intentionally malicious
administrator configuration, and vulnerabilities in an external service are
outside the plugin's direct control, but the plugin must still minimize the
data and credentials sent across those boundaries.
