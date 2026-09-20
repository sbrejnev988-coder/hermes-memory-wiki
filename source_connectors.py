"""Scoped, incremental external-source adapters backed by document ingestion.

Local files use the document worker's allowlisted snapshot path. Text records
from a future remote connector are first redacted and staged under the Hermes
document cache. The durable connector key binds URI and scope without storing
credentials, query strings, or raw record bodies in the journal.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from . import document_knowledge_graph as documents
except ImportError:
    import document_knowledge_graph as documents


MAX_RECORD_BYTES = 1_000_000


@dataclass(frozen=True)
class SourceRecord:
    """Connector-neutral text revision supplied by an authorized adapter."""

    uri: str
    revision: str
    text: str
    scope_id: str = ""
    repository_id: str = ""
    title: str = ""
    source_type: str = "record"
    embed: bool = False


def install_source_connector_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS external_sources(
        source_key TEXT PRIMARY KEY,
        owner_bot_id TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL,
        display_uri TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        repository_id TEXT NOT NULL,
        document_source_id TEXT NOT NULL,
        revision_key TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        etag TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        FOREIGN KEY(document_source_id) REFERENCES document_sources(source_id)
    )""")
    if "etag" not in {row[1] for row in conn.execute("PRAGMA table_info(external_sources)")}:
        conn.execute("ALTER TABLE external_sources ADD COLUMN etag TEXT NOT NULL DEFAULT ''")
    if "owner_bot_id" not in {row[1] for row in conn.execute("PRAGMA table_info(external_sources)")}:
        conn.execute("ALTER TABLE external_sources ADD COLUMN owner_bot_id TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_external_sources_scope ON external_sources(scope_id,repository_id,status)")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_key(provider: Any, uri: str, scope_id: str, repository_id: str,
                namespace: str = "record") -> str:
    salt = str(provider.database_instance_id or provider._meta_text("database_instance_id") or "")
    if not salt:
        raise ValueError("connector_identity_unavailable")
    # Separate unverified caller-supplied records from trusted fetchers. A
    # record claiming a GitHub URI cannot overwrite a verified GitHub row.
    if namespace not in {"record", "local_file", "github", "google_drive", "api"}:
        raise ValueError("unsupported_source_namespace")
    return "ext_" + _sha(f"{salt}\0{_owner(provider)}\0{namespace}\0{scope_id}\0{repository_id}\0{uri}")[:20]


def _display_uri(uri: str) -> str:
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme.lower() == "file":
        return "file:///<local-file>"
    if parsed.scheme.lower() in {"https", "http"} and parsed.hostname:
        host = parsed.hostname.lower()
        if parsed.port:
            host += f":{parsed.port}"
        return urllib.parse.urlunsplit((parsed.scheme.lower(), host, parsed.path[:240], "", ""))
    if parsed.scheme.lower() == "urn":
        return f"urn:{parsed.path[:240]}"
    raise ValueError("unsupported_source_uri")


def _scope(provider: Any, scope_id: str, repository_id: str) -> tuple[str, str]:
    return documents._document_access_scope(provider, scope_id, repository_id)


def _owner(provider: Any) -> str:
    owner = str(getattr(provider, "bot_id", "") or "").strip()
    if not owner:
        raise PermissionError("connector_identity_unavailable")
    return owner


def authorize_write(provider: Any, source_key: str) -> None:
    row = provider._connect().execute(
        "SELECT owner_bot_id FROM external_sources WHERE source_key=?", (source_key,)
    ).fetchone()
    if row is not None and str(row["owner_bot_id"] or "") != _owner(provider):
        raise PermissionError("connector_source_not_owned")


def _put_source(provider: Any, *, source_key: str, source_type: str,
                display_uri: str, scope_id: str, repository_id: str,
                document_source_id: str, revision_key: str,
                content_hash: str) -> None:
    conn = provider._connect()
    authorize_write(provider, source_key)
    stamp = int(time.time())
    with conn:
        cursor = conn.execute("""INSERT INTO external_sources
            (source_key,owner_bot_id,source_type,display_uri,scope_id,repository_id,
             document_source_id,revision_key,content_hash,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,'active',?,?)
            ON CONFLICT(source_key) DO UPDATE SET
              source_type=excluded.source_type, display_uri=excluded.display_uri,
              document_source_id=excluded.document_source_id,
              revision_key=excluded.revision_key, content_hash=excluded.content_hash,
              status='active',updated_at=excluded.updated_at
            WHERE external_sources.owner_bot_id=excluded.owner_bot_id""",
            (source_key, _owner(provider), source_type, display_uri, scope_id, repository_id,
             document_source_id, revision_key, content_hash, stamp, stamp))
        if cursor.rowcount != 1:
            raise PermissionError("connector_source_not_owned")


def sync_local_file(provider: Any, args: dict[str, Any]) -> dict[str, Any]:
    path = documents._allowed_path(args.get("path"))
    scope_id, repository_id = _scope(provider, str(args.get("scope_id") or ""),
                                     str(args.get("repository_id") or ""))
    path = path.resolve(strict=True)
    uri = path.as_uri()
    key = _source_key(provider, uri, scope_id, repository_id, "local_file")
    authorize_write(provider, key)
    result = documents.ingest_document(provider, {
        "path": str(path), "scope_id": scope_id,
        "repository_id": repository_id, "embed": False,
    })
    source_id = str(result.get("source_id") or "")
    row = provider._connect().execute(
        "SELECT file_hash,revision_id,active FROM document_sources WHERE source_id=?", (source_id,)
    ).fetchone()
    if row is None or not int(row["active"] or 0):
        raise RuntimeError("connector_document_ingest_incomplete")
    content_hash = str(row["file_hash"] or "")
    _put_source(provider, source_key=key, source_type="local_file",
                display_uri=_display_uri(uri), scope_id=scope_id,
                repository_id=repository_id, document_source_id=source_id,
                revision_key=content_hash[:20], content_hash=content_hash)
    if bool(args.get("embed", False)):
        documents.embed_pending_documents(provider, {
            "source_id": source_id, "scope_id": scope_id,
            "repository_id": repository_id, "limit": 200,
        })
    return {"status": str(result.get("status") or "indexed"), "source_key": key,
            "source_id": source_id, "revision_id": str(row["revision_id"] or ""),
            "scope_id": scope_id, "repository_id": repository_id}


def _record_snapshot_path(provider: Any, source_key: str) -> Path:
    # Bind staging to the actual provider instance. A process-wide cache env
    # may refer to another Hermes profile while this provider has an explicit
    # ``hermes_home`` override (including isolated tests).
    cache = Path(provider.home) / "cache" / "documents"
    if not documents._path_within_allowed_roots(cache):
        raise ValueError("connector cache is outside MEMORY_WIKI_DOCUMENT_ROOTS")
    documents._reject_link_or_reparse_components(cache)
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    documents._reject_link_or_reparse_components(cache)
    folder = cache / "connectors"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    documents._reject_link_or_reparse_components(folder)
    return folder / f"{source_key}.txt"


def upsert_record(provider: Any, record: SourceRecord) -> dict[str, Any]:
    uri = str(record.uri or "").strip()
    revision = str(record.revision or "").strip()
    if not uri or len(uri) > 2000 or not revision or len(revision) > 200:
        raise ValueError("invalid_source_record_identity")
    display_uri = provider._connector_redact(_display_uri(uri))[:300]
    if provider._shared_block_secret_scan(display_uri):
        display_uri = "<redacted-source-uri>"
    scope_id, repository_id = _scope(provider, record.scope_id, record.repository_id)
    if record.source_type not in {"record", "github_public", "github_authenticated", "google_drive", "api"}:
        raise ValueError("unsupported_source_type")
    text = str(record.text or "")
    if not text.strip() or len(text.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("source_record_size_invalid")
    # Redact before persistent staging; the document worker applies its own
    # secret guard again before indexing derived chunks.
    safe_text = provider._connector_redact(text)
    if provider._shared_block_secret_scan(safe_text):
        raise ValueError("source_record_contains_secret")
    title = provider._connector_redact(str(record.title or "").strip()[:200])
    body = ((title + "\n\n") if title else "") + safe_text
    content_hash = _sha(body)
    revision_key = _sha(revision)[:20]
    namespace = "github" if record.source_type.startswith("github_") else record.source_type
    key = _source_key(provider, uri, scope_id, repository_id, namespace)
    authorize_write(provider, key)
    conn = provider._connect()
    existing = conn.execute("SELECT * FROM external_sources WHERE source_key=?", (key,)).fetchone()
    if existing is not None and str(existing["revision_key"]) == revision_key:
        if str(existing["content_hash"]) != content_hash:
            raise ValueError("source_revision_conflict")
        if existing["status"] == "active":
            path = _record_snapshot_path(provider, key)
            source = conn.execute(
                "SELECT active FROM document_sources WHERE source_id=?",
                (existing["document_source_id"],),
            ).fetchone()
            if source is not None and int(source["active"] or 0):
                try:
                    checked = documents._allowed_path(path)
                    if _sha(checked.read_text(encoding="utf-8")) == content_hash:
                        if record.embed:
                            documents.embed_pending_documents(provider, {
                                "source_id": str(existing["document_source_id"]),
                                "scope_id": scope_id,
                                "repository_id": repository_id,
                                "limit": 200,
                            })
                        return {"status": "unchanged", "source_key": key,
                                "source_id": str(existing["document_source_id"]),
                                "scope_id": scope_id, "repository_id": repository_id}
                except (OSError, ValueError, UnicodeError):
                    pass
    path = _record_snapshot_path(provider, key)
    temporary = path.with_name(f".{key}.{uuid.uuid4().hex[:12]}.tmp")
    backup = path.with_name(f".{key}.{uuid.uuid4().hex[:12]}.bak")
    had_previous = path.exists()
    try:
        if had_previous:
            documents._allowed_path(path)
            shutil.copy2(path, backup)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(temporary, flags, 0o600), "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            result = documents.ingest_document(provider, {
                "path": str(path), "scope_id": scope_id,
                "repository_id": repository_id, "embed": False,
            })
        except Exception:
            if had_previous and backup.exists():
                os.replace(backup, path)
            elif not had_previous:
                path.unlink(missing_ok=True)
            raise
    finally:
        temporary.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
    source_id = str(result.get("source_id") or "")
    source = conn.execute(
        "SELECT revision_id,active FROM document_sources WHERE source_id=?", (source_id,)
    ).fetchone()
    if source is None or not int(source["active"] or 0):
        raise RuntimeError("connector_document_ingest_incomplete")
    _put_source(provider, source_key=key, source_type=record.source_type,
                display_uri=display_uri, scope_id=scope_id,
                repository_id=repository_id, document_source_id=source_id,
                revision_key=revision_key, content_hash=content_hash)
    if record.embed:
        documents.embed_pending_documents(provider, {
            "source_id": source_id, "scope_id": scope_id,
            "repository_id": repository_id, "limit": 200,
        })
    return {"status": str(result.get("status") or "indexed"), "source_key": key,
            "source_id": source_id, "revision_id": str(source["revision_id"] or ""),
            "scope_id": scope_id, "repository_id": repository_id}


def list_sources(provider: Any, limit: int = 50) -> dict[str, Any]:
    scope_id, repository_id = _scope(provider, "", "")
    count = max(1, min(int(limit), 100))
    rows = provider._connect().execute("""SELECT source_key,source_type,display_uri,
        scope_id,repository_id,document_source_id,revision_key,status,updated_at
        FROM external_sources WHERE scope_id=? AND repository_id=? AND owner_bot_id=?
        ORDER BY updated_at DESC LIMIT ?""", (scope_id, repository_id,
                                                _owner(provider), count)).fetchall()
    return {"sources": [dict(row) for row in rows]}


def authorize_delete(provider: Any, source_key: Any) -> sqlite3.Row:
    key = str(source_key or "").strip()
    if not key or len(key) > 64:
        raise ValueError("connector_source_not_found")
    row = provider._connect().execute(
        "SELECT * FROM external_sources WHERE source_key=? AND status='active'", (key,)
    ).fetchone()
    if row is None:
        raise ValueError("connector_source_not_found")
    _scope(provider, str(row["scope_id"]), str(row["repository_id"]))
    if str(row["owner_bot_id"] or "") != _owner(provider):
        raise ValueError("connector_source_not_found")
    return row


def delete_source(provider: Any, source_key: Any) -> dict[str, Any]:
    row = authorize_delete(provider, source_key)
    source_id = str(row["document_source_id"])
    result = documents.delete_document(provider, {"source_id": source_id})
    with provider._connect() as conn:
        updated = conn.execute(
            "UPDATE external_sources SET status='deleted',updated_at=? "
            "WHERE source_key=? AND owner_bot_id=? AND status='active'",
            (int(time.time()), row["source_key"], _owner(provider)),
        )
        if updated.rowcount != 1:
            raise PermissionError("connector_source_not_owned")
    if row["source_type"] != "local_file":
        _record_snapshot_path(provider, str(row["source_key"])).unlink(missing_ok=True)
    return {"status": "deleted", "source_key": str(row["source_key"]),
            "source_id": source_id, "archived_claims": int(result.get("archived_claims") or 0)}
