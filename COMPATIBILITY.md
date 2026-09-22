# Memory Wiki compatibility contract

## SQLite

`migrations.py` defines `DB_SCHEMA_VERSION = 1` and
`DB_SCHEMA_COMPAT_MIN = 1`. The `schema_migrations` table records the version,
stable migration name and checksum, plugin version, and application time. The
provider checks this ledger and SQLite `PRAGMA user_version` before its existing
schema installation runs. Unknown, corrupted, mismatched, or newer versions
fail closed. SQLite is authoritative; FTS and Qdrant remain rebuildable indexes.

An unversioned database is bootstrapped only when its core `meta` and `claims`
tables have a recognized shape. A populated claims table without scope and
ownership columns is refused because it cannot be assigned a visibility
partition safely. A fresh empty database is supported. The version marker is
written after the existing idempotent schema installation succeeds; a failed
installation can be retried. The initial bootstrap also replaces historical
prefetch audit details containing `query_hash` with a content-free marker.
SQLite backups retain the ledger. Logical checkpoint recovery initializes a
fresh database using the current runtime, then restores the data rows; it does
not overwrite the new database's schema ledger. Never edit version rows or
SQLite's `user_version` manually to force a downgrade. Back up the profile
before installing a new release. A newer database requires a compatible newer
runtime or a verified earlier backup.

Future changes to durable SQLite shape must increment the schema version,
add a named/checksummed migration, establish a conservative upgrade path for
existing ACL data, and add restore/replay tests. Only schema versions explicitly
supported by the running code may be opened.

## MCP tools

The public MCP API is currently major version 1. The pinned baseline is
[`compatibility/mcp-api-v1.json`](compatibility/mcp-api-v1.json). The release
gate regenerates the bundled tool schemas and runs
`packaging/check_mcp_compatibility.py`. Within a major version, existing tool
names and parameters remain available, previously optional arguments cannot
become required, accepted types and enum values cannot shrink, and validation
bounds cannot tighten. New tools and optional arguments may be added.
Descriptions may change. Changing a default of an existing argument requires
a new major baseline. The checker rejects unknown validation keywords until
their compatibility semantics are implemented. Output schemas and semantic
behavior are not machine-checked; integration tests remain necessary.

A deliberate breaking MCP change requires a new major baseline and an explicit
upgrade guide for callers. Editing the version label alone does not waive the
release gate.

## Python SDK

`sdk.SDK_API_VERSION` is `1.0` and identifies the client interface contract.
`sdk.__version__` matches the package/plugin release version and is sent in
the MCP `clientInfo`. Additive methods and optional parameters are compatible
within SDK API major 1. Removing or renaming public methods or required
constructor arguments requires an API major update and migration guidance.
The SDK always launches a process with explicit caller identity; caller
partition isolation must not be weakened by compatibility work.
