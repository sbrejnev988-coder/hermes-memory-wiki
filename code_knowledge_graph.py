"""Repository-scale code knowledge graph for Hermes Memory Wiki.

This module is intentionally stdlib-only.  It stores every exported source line as
an addressable record, while embeddings are created only for semantic chunks.
Code Shrinker remains the source of truth for exact, unredacted source retrieval.

Graph schema v1:
  repository -> file -> symbol -> chunk -> line
  typed edges: contains, defines, imports, calls, references, inherits,
               implements, tests, configures, reads, writes

Retrieval:
  SQLite FTS5/BM25 ranks symbols, chunks and lines
  Memory Wiki/Qdrant contributes semantic chunk ranks
  Reciprocal Rank Fusion combines the lists
  existing Memory Wiki reranker may reorder the fused top-K
  graph-neighbour boosts preserve structural context
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
EVENT_VERSION = 2
_ALLOWED_PREDICATES = {
    "contains", "defines", "imports", "calls", "references", "inherits",
    "implements", "tests", "configures", "reads", "writes", "exports",
    "instantiates", "overrides", "depends_on",
}
_CODE_HINT = re.compile(
    r"(?:[A-Za-z0-9_.-]+[/\\][A-Za-z0-9_./\\-]+|\b(?:function|class|method|symbol|"
    r"функц(?:ия|ии|ию)|класс|метод|символ|строк(?:а|и|у)|файл|код|репозитор|"
    r"callers?|callees?|import|traceback|stack|bug|ошибк|patch|diff|commit)\b)",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[\w./:@#$+-]+", re.UNICODE)
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN (?P<label>[A-Z0-9][A-Z0-9 _-]{0,79})-----"
    r"[\s\S]{0,200000}?"
    r"-----END (?P=label)-----",
    re.IGNORECASE,
)


def _now() -> int:
    return int(time.time())


def _sha(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", "replace")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"", "0", "false", "no", "off"}


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _canonical_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").strip()
    value = re.sub(r"/+", "/", value)
    while value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("/") or value == ".." or value.startswith("../"):
        raise ValueError(f"invalid repository-relative path: {path!r}")
    if any(part == ".." for part in value.split("/")):
        raise ValueError(f"path traversal rejected: {path!r}")
    return value


def _clean_text(value: Any, limit: int = 12000) -> str:
    text = str(value or "").replace("\x00", "")
    # The exporter already redacts likely secrets. Fail closed for common key forms.
    # PEM blocks are often multiline and do not have assignment syntax, so redact
    # them before materializing code text in SQLite/FTS or derived checkpoints.
    text = _PEM_BLOCK_RE.sub("<REDACTED_PEM_BLOCK>", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization)\b\s*[:=]\s*"
        r"([\"']?)[^\s,;\"']{8,}\2",
        lambda m: f"{m.group(1)}=<REDACTED>",
        text,
    )
    return text[: max(0, limit)]


def _fts_query(query: str) -> str:
    tokens = []
    for token in _TOKEN_RE.findall(str(query or "")):
        token = token.strip("./:@#$+-_")
        if len(token) < 2:
            continue
        token = token.replace('"', '""')
        if token.lower() not in {t.lower() for t in tokens}:
            tokens.append(token)
        if len(tokens) >= 16:
            break
    return " OR ".join(f'"{token}"' for token in tokens)


def install_code_graph_schema(conn: sqlite3.Connection) -> None:
    """Install graph tables and independent FTS5 indexes."""
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS code_graph_repositories(
            repository_id TEXT PRIMARY KEY,
            root TEXT NOT NULL DEFAULT '',
            commit_sha TEXT NOT NULL DEFAULT '',
            graph_revision TEXT NOT NULL DEFAULT '',
            snapshot_hash TEXT NOT NULL DEFAULT '',
            generated_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            stats_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS code_graph_files(
            repository_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT '',
            file_hash TEXT NOT NULL DEFAULT '',
            line_count INTEGER NOT NULL DEFAULT 0,
            imports_json TEXT NOT NULL DEFAULT '[]',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(repository_id,file_path)
        );
        CREATE TABLE IF NOT EXISTS code_graph_symbols(
            repository_id TEXT NOT NULL,
            symbol_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            qualified_name TEXT NOT NULL DEFAULT '',
            short_name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT '',
            signature TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT '',
            start_line INTEGER NOT NULL DEFAULT 0,
            end_line INTEGER NOT NULL DEFAULT 0,
            symbol_revision TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            contract_json TEXT NOT NULL DEFAULT '{}',
            search_text TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(repository_id,symbol_id)
        );
        CREATE TABLE IF NOT EXISTS code_graph_chunks(
            repository_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            symbol_id TEXT NOT NULL DEFAULT '',
            qualified_name TEXT NOT NULL DEFAULT '',
            chunk_kind TEXT NOT NULL DEFAULT 'semantic',
            start_line INTEGER NOT NULL DEFAULT 0,
            end_line INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            embedding_claim_id TEXT NOT NULL DEFAULT '',
            token_estimate INTEGER NOT NULL DEFAULT 0,
            chunk_text TEXT NOT NULL DEFAULT '',
            embedding_text TEXT NOT NULL DEFAULT '',
            search_text TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(repository_id,chunk_id)
        );
        CREATE TABLE IF NOT EXISTS code_graph_lines(
            repository_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_no INTEGER NOT NULL,
            line_id TEXT NOT NULL DEFAULT '',
            anchor_hash TEXT NOT NULL DEFAULT '',
            text_hash TEXT NOT NULL DEFAULT '',
            line_text TEXT NOT NULL DEFAULT '',
            symbol_id TEXT NOT NULL DEFAULT '',
            chunk_id TEXT NOT NULL DEFAULT '',
            flags TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(repository_id,file_path,line_no)
        );
        CREATE TABLE IF NOT EXISTS code_graph_edges(
            repository_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            target_id TEXT NOT NULL,
            source_file TEXT NOT NULL DEFAULT '',
            source_line INTEGER NOT NULL DEFAULT 0,
            target_file TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(repository_id,edge_id)
        );
        CREATE TABLE IF NOT EXISTS code_graph_events(
            event_id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            snapshot_mode TEXT NOT NULL DEFAULT 'full',
            status TEXT NOT NULL DEFAULT 'completed',
            stats_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cgf_repo_path ON code_graph_files(repository_id,file_path);
        CREATE INDEX IF NOT EXISTS idx_cgs_repo_file ON code_graph_symbols(repository_id,file_path,start_line);
        CREATE INDEX IF NOT EXISTS idx_cgs_repo_name ON code_graph_symbols(repository_id,qualified_name);
        CREATE INDEX IF NOT EXISTS idx_cgc_repo_file ON code_graph_chunks(repository_id,file_path,start_line);
        CREATE INDEX IF NOT EXISTS idx_cgc_repo_symbol ON code_graph_chunks(repository_id,symbol_id);
        CREATE INDEX IF NOT EXISTS idx_cgc_claim ON code_graph_chunks(embedding_claim_id);
        CREATE INDEX IF NOT EXISTS idx_cgl_repo_symbol ON code_graph_lines(repository_id,symbol_id);
        CREATE INDEX IF NOT EXISTS idx_cgl_repo_chunk ON code_graph_lines(repository_id,chunk_id);
        CREATE INDEX IF NOT EXISTS idx_cge_source ON code_graph_edges(repository_id,source_id,predicate);
        CREATE INDEX IF NOT EXISTS idx_cge_target ON code_graph_edges(repository_id,target_id,predicate);
        """
    )
    try:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(code_graph_lines)").fetchall()}
        if "anchor_hash" not in columns:
            conn.execute("ALTER TABLE code_graph_lines ADD COLUMN anchor_hash TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS code_graph_symbols_fts USING fts5("
            "repository_id UNINDEXED,symbol_id UNINDEXED,file_path,qualified_name,signature,search_text,"
            "tokenize='unicode61 tokenchars ''_./:@#$-''')"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS code_graph_chunks_fts USING fts5("
            "repository_id UNINDEXED,chunk_id UNINDEXED,file_path,symbol_id,qualified_name,search_text,chunk_text,"
            "tokenize='unicode61 tokenchars ''_./:@#$-''')"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS code_graph_lines_fts USING fts5("
            "repository_id UNINDEXED,file_path UNINDEXED,line_no UNINDEXED,line_text,"
            "tokenize='unicode61 tokenchars ''_./:@#$-''')"
        )
    except sqlite3.OperationalError:
        # Minimal SQLite builds remain usable through LIKE fallback.
        pass


def _delete_fts_for_files(conn: sqlite3.Connection, repository_id: str, files: Sequence[str]) -> None:
    for table in ("code_graph_symbols_fts", "code_graph_chunks_fts", "code_graph_lines_fts"):
        try:
            if files:
                placeholders = ",".join("?" for _ in files)
                conn.execute(
                    f"DELETE FROM {table} WHERE repository_id=? AND file_path IN ({placeholders})",
                    [repository_id, *files],
                )
            else:
                conn.execute(f"DELETE FROM {table} WHERE repository_id=?", (repository_id,))
        except sqlite3.OperationalError:
            pass


def _delete_files(conn: sqlite3.Connection, repository_id: str, files: Sequence[str]) -> None:
    if not files:
        return
    placeholders = ",".join("?" for _ in files)
    params: List[Any] = [repository_id, *files]
    _delete_fts_for_files(conn, repository_id, files)
    for table in ("code_graph_lines", "code_graph_chunks", "code_graph_symbols", "code_graph_files"):
        conn.execute(
            f"DELETE FROM {table} WHERE repository_id=? AND file_path IN ({placeholders})",
            params,
        )
    conn.execute(
        f"DELETE FROM code_graph_edges WHERE repository_id=? AND (source_file IN ({placeholders}) OR target_file IN ({placeholders}))",
        [repository_id, *files, *files],
    )


def _insert_graph_rows(conn: sqlite3.Connection, event: Dict[str, Any], repository_id: str, ts: int) -> Dict[str, int]:
    counts = {"files": 0, "symbols": 0, "chunks": 0, "lines": 0, "edges": 0}
    for raw in event.get("files") or []:
        if not isinstance(raw, dict):
            continue
        path = _canonical_path(raw.get("file_path") or "")
        imports = raw.get("imports") if isinstance(raw.get("imports"), list) else []
        conn.execute(
            "INSERT OR REPLACE INTO code_graph_files(repository_id,file_path,language,file_hash,line_count,imports_json,updated_at) VALUES(?,?,?,?,?,?,?)",
            (repository_id, path, str(raw.get("language") or "")[:64], str(raw.get("file_hash") or "")[:80],
             max(0, int(raw.get("line_count") or 0)), _json(imports)[:200000], ts),
        )
        counts["files"] += 1

    for raw in event.get("symbols") or []:
        if not isinstance(raw, dict):
            continue
        symbol_id = str(raw.get("symbol_id") or "").strip()[:512]
        if not symbol_id:
            continue
        path = _canonical_path(raw.get("file_path") or "")
        qname = _clean_text(raw.get("qualified_name") or raw.get("name"), 1000)
        signature = _clean_text(raw.get("signature"), 4000)
        contract = raw.get("contract") if isinstance(raw.get("contract"), dict) else {}
        search_text = _clean_text(raw.get("search_text") or f"{path} {qname} {signature} {_json(contract)}", 12000)
        content_hash = str(raw.get("content_hash") or _sha(search_text)).lower().removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            content_hash = _sha(search_text)
        conn.execute(
            """INSERT OR REPLACE INTO code_graph_symbols(
               repository_id,symbol_id,file_path,qualified_name,short_name,kind,language,signature,visibility,
               start_line,end_line,symbol_revision,content_hash,contract_json,search_text,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (repository_id, symbol_id, path, qname, _clean_text(raw.get("short_name") or qname.rsplit(".", 1)[-1], 300),
             str(raw.get("kind") or "")[:100], str(raw.get("language") or "")[:64], signature,
             str(raw.get("visibility") or "")[:64], max(0, int(raw.get("start_line") or 0)),
             max(0, int(raw.get("end_line") or 0)), str(raw.get("symbol_revision") or "")[:160],
             content_hash, _json(contract)[:20000], search_text, ts),
        )
        try:
            conn.execute(
                "INSERT INTO code_graph_symbols_fts(repository_id,symbol_id,file_path,qualified_name,signature,search_text) VALUES(?,?,?,?,?,?)",
                (repository_id, symbol_id, path, qname, signature, search_text),
            )
        except sqlite3.OperationalError:
            pass
        counts["symbols"] += 1

    for raw in event.get("chunks") or []:
        if not isinstance(raw, dict):
            continue
        chunk_id = str(raw.get("chunk_id") or "").strip()[:512]
        if not chunk_id:
            continue
        path = _canonical_path(raw.get("file_path") or "")
        chunk_text = _clean_text(raw.get("chunk_text"), _env_int("MEMORY_WIKI_CODE_GRAPH_CHUNK_MAX_CHARS", 12000, 1000, 40000))
        embed_text = _clean_text(raw.get("embedding_text") or chunk_text, 12000)
        qname = _clean_text(raw.get("qualified_name"), 1000)
        search_text = _clean_text(raw.get("search_text") or f"{path} {qname} {embed_text}", 14000)
        content_hash = str(raw.get("content_hash") or _sha(chunk_text)).lower().removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            content_hash = _sha(chunk_text)
        old = conn.execute(
            "SELECT embedding_claim_id FROM code_graph_chunks WHERE repository_id=? AND chunk_id=?",
            (repository_id, chunk_id),
        ).fetchone()
        embedding_claim_id = str(old[0] if old else "")
        conn.execute(
            """INSERT OR REPLACE INTO code_graph_chunks(
               repository_id,chunk_id,file_path,symbol_id,qualified_name,chunk_kind,start_line,end_line,
               content_hash,embedding_claim_id,token_estimate,chunk_text,embedding_text,search_text,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (repository_id, chunk_id, path, str(raw.get("symbol_id") or "")[:512], qname,
             str(raw.get("chunk_kind") or "semantic")[:80], max(0, int(raw.get("start_line") or 0)),
             max(0, int(raw.get("end_line") or 0)), content_hash, embedding_claim_id,
             max(0, int(raw.get("token_estimate") or max(1, len(chunk_text) // 4))),
             chunk_text, embed_text, search_text, ts),
        )
        try:
            conn.execute(
                "INSERT INTO code_graph_chunks_fts(repository_id,chunk_id,file_path,symbol_id,qualified_name,search_text,chunk_text) VALUES(?,?,?,?,?,?,?)",
                (repository_id, chunk_id, path, str(raw.get("symbol_id") or "")[:512], qname, search_text, chunk_text),
            )
        except sqlite3.OperationalError:
            pass
        counts["chunks"] += 1

    max_lines = _env_int("MEMORY_WIKI_CODE_GRAPH_MAX_LINES_PER_EVENT", 750000, 0, 5000000)
    for raw in (event.get("lines") or [])[:max_lines]:
        if not isinstance(raw, dict):
            continue
        path = _canonical_path(raw.get("file_path") or "")
        line_no = int(raw.get("line_no") or 0)
        if line_no < 1:
            continue
        line_text = _clean_text(raw.get("line_text"), 2000)
        line_id = str(raw.get("line_id") or f"line:{repository_id}:{path}:{line_no}")[:700]
        text_hash = str(raw.get("text_hash") or _sha(line_text)).lower().removeprefix("sha256:")
        conn.execute(
            """INSERT OR REPLACE INTO code_graph_lines(
               repository_id,file_path,line_no,line_id,anchor_hash,text_hash,line_text,symbol_id,chunk_id,flags,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (repository_id, path, line_no, line_id, str(raw.get("anchor_hash") or "")[:80], text_hash[:80], line_text,
             str(raw.get("symbol_id") or "")[:512], str(raw.get("chunk_id") or "")[:512],
             str(raw.get("flags") or "")[:500], ts),
        )
        if line_text.strip():
            try:
                conn.execute(
                    "INSERT INTO code_graph_lines_fts(repository_id,file_path,line_no,line_text) VALUES(?,?,?,?)",
                    (repository_id, path, line_no, line_text),
                )
            except sqlite3.OperationalError:
                pass
        counts["lines"] += 1

    # Edges are supplied as a full repository set even for delta snapshots.
    for raw in event.get("edges") or []:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or "").strip()[:700]
        target_id = str(raw.get("target_id") or "").strip()[:700]
        predicate = str(raw.get("predicate") or "references").strip().lower()[:80]
        if not source_id or not target_id:
            continue
        if predicate not in _ALLOWED_PREDICATES:
            predicate = "references"
        source_file = str(raw.get("source_file") or "").strip()
        target_file = str(raw.get("target_file") or "").strip()
        if source_file:
            source_file = _canonical_path(source_file)
        if target_file:
            target_file = _canonical_path(target_file)
        edge_id = str(raw.get("edge_id") or "edge_" + _sha(f"{repository_id}\0{source_id}\0{predicate}\0{target_id}")[:32])[:512]
        conn.execute(
            """INSERT OR REPLACE INTO code_graph_edges(
               repository_id,edge_id,source_id,predicate,target_id,source_file,source_line,target_file,confidence,evidence,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (repository_id, edge_id, source_id, predicate, target_id, source_file,
             max(0, int(raw.get("source_line") or 0)), target_file,
             max(0.0, min(float(raw.get("confidence") or 0.5), 1.0)),
             _clean_text(raw.get("evidence"), 2000), ts),
        )
        counts["edges"] += 1
    return counts


def _embed_graph_chunks(provider: Any, repository_id: str, commit_sha: str, event_id: str,
                        file_filter: Sequence[str], *, unit_limit: Optional[int] = None,
                        pending_only: bool = False) -> Dict[str, Any]:
    if not _env_bool("MEMORY_WIKI_CODE_GRAPH_EMBED", True):
        return {"enabled": False, "processed": 0, "created": 0, "reused": 0, "failed": 0}
    limit = (_env_int("MEMORY_WIKI_CODE_GRAPH_EMBED_MAX_UNITS", 2000, 0, 10000)
             if unit_limit is None else max(0, min(int(unit_limit), 10000)))
    if limit <= 0 or not hasattr(provider, "_code_claim_add"):
        return {"enabled": False, "processed": 0, "created": 0, "reused": 0, "failed": 0}
    conn = provider._connect()
    where = ["repository_id=?"]
    params: List[Any] = [repository_id]
    if file_filter:
        placeholders = ",".join("?" for _ in file_filter)
        where.append(f"file_path IN ({placeholders})")
        params.extend(file_filter)
    if pending_only:
        where.append("embedding_claim_id=''")
    rows = conn.execute(
        "SELECT chunk_id,file_path,symbol_id,qualified_name,start_line,end_line,content_hash,embedding_claim_id,embedding_text "
        "FROM code_graph_chunks WHERE " + " AND ".join(where) +
        " ORDER BY CASE WHEN symbol_id<>'' THEN 0 ELSE 1 END, token_estimate DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    stats = {"enabled": True, "processed": 0, "created": 0, "reused": 0, "failed": 0, "errors": []}
    for row in rows:
        item = dict(row)
        stats["processed"] += 1
        try:
            existing = ""
            if item.get("embedding_claim_id"):
                found = conn.execute(
                    "SELECT c.id FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id "
                    "WHERE c.id=? AND c.status='active' AND m.repository_id=? AND m.content_hash=?",
                    (item["embedding_claim_id"], repository_id, item["content_hash"]),
                ).fetchone()
                existing = str(found[0]) if found else ""
            if not existing:
                found = conn.execute(
                    "SELECT c.id FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id "
                    "WHERE c.status='active' AND m.repository_id=? AND m.file_path=? AND m.symbol_id=? "
                    "AND m.content_hash=? AND m.claim_type='code_graph_chunk' ORDER BY c.updated_at DESC LIMIT 1",
                    (repository_id, item["file_path"], item["symbol_id"], item["content_hash"]),
                ).fetchone()
                existing = str(found[0]) if found else ""
            if existing:
                conn.execute(
                    "UPDATE code_graph_chunks SET embedding_claim_id=? WHERE repository_id=? AND chunk_id=?",
                    (existing, repository_id, item["chunk_id"]),
                )
                conn.commit()
                stats["reused"] += 1
                continue
            label = item.get("qualified_name") or item.get("symbol_id") or "top-level"
            claim = (
                f"Code semantic chunk in repository {repository_id}. "
                f"File {item['file_path']} lines {item['start_line']}-{item['end_line']}; "
                f"symbol {label}.\n{item['embedding_text']}"
            )[:7800]
            result = provider._code_claim_add({
                "claim": claim,
                "topic": "code-intelligence",
                "repository_id": repository_id,
                "commit_sha": commit_sha,
                "file_path": item["file_path"],
                "symbol_id": item["symbol_id"] or item["chunk_id"],
                "symbol_revision": item["content_hash"][:32],
                "content_hash": item["content_hash"],
                "claim_type": "code_graph_chunk",
                "confidence": 0.88,
                "salience": 0.78,
                "evidence": f"Code Shrinker graph event {event_id}; chunk={item['chunk_id']}",
                "source_event_id": f"kg:{repository_id}:{item['chunk_id']}:{item['content_hash']}",
                "producer": "mcp-code-shrinker-knowledge-graph",
                "phase_sep_version": "kg-v1",
            })
            claim_id = str(result.get("id") or "")
            if claim_id:
                conn.execute(
                    "UPDATE code_graph_chunks SET embedding_claim_id=? WHERE repository_id=? AND chunk_id=?",
                    (claim_id, repository_id, item["chunk_id"]),
                )
                conn.commit()
                stats["created"] += 1
            else:
                stats["failed"] += 1
        except Exception as exc:  # one malformed unit must not abort the snapshot
            stats["failed"] += 1
            if len(stats["errors"]) < 12:
                stats["errors"].append(f"{item.get('chunk_id')}: {type(exc).__name__}: {exc}")
    return stats


def ingest_code_graph_event(provider: Any, event: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a Code Shrinker full or delta graph event idempotently."""
    if not isinstance(event, dict):
        raise ValueError("code graph event must be an object")
    if int(event.get("event_version") or 0) != EVENT_VERSION:
        raise ValueError(f"unsupported code graph event_version: {event.get('event_version')}")
    if str(event.get("type") or "") != "code_graph_snapshot":
        raise ValueError("event type must be code_graph_snapshot")
    if int(event.get("graph_schema_version") or 0) != SCHEMA_VERSION:
        raise ValueError("unsupported graph_schema_version")
    producer = str(event.get("producer") or "")
    if producer not in {"mcp-code-shrinker", "code-shrinker"}:
        raise ValueError("unexpected code graph producer")
    repository_id = str(event.get("repository_id") or "").strip()
    event_id = str(event.get("event_id") or "").strip()
    if not repository_id or not event_id:
        raise ValueError("repository_id and event_id are required")
    snapshot_mode = str(event.get("snapshot_mode") or "full").lower()
    if snapshot_mode not in {"full", "delta"}:
        raise ValueError("snapshot_mode must be full or delta")
    payload_hash = str(event.get("snapshot_hash") or _sha(_json(event)))
    conn = provider._connect()
    install_code_graph_schema(conn)
    prior = conn.execute("SELECT payload_hash,stats_json FROM code_graph_events WHERE event_id=?", (event_id,)).fetchone()
    if prior:
        if str(prior[0]) != payload_hash:
            raise ValueError("event_id reuse with different code graph payload")
        previous = json.loads(prior[1] or "{}")
        return {"status": "deduplicated", "deduplicated": True, **previous}

    ts = _now()
    changed_files = []
    for item in event.get("files") or []:
        if isinstance(item, dict) and item.get("file_path"):
            changed_files.append(_canonical_path(item["file_path"]))
    deleted_files = [_canonical_path(p) for p in (event.get("deleted_files") or []) if str(p or "").strip()]
    touched = sorted(set(changed_files + deleted_files))

    # Invalidate old semantic claims before replacing graph rows.
    invalidated = 0
    if hasattr(provider, "_invalidate_revision"):
        for path in touched:
            try:
                result = provider._invalidate_revision({
                    "repository_id": repository_id,
                    "file_path": path,
                    "new_commit_sha": str(event.get("commit_sha") or ""),
                    "new_content_hash": next((
                        str(f.get("file_hash") or "") for f in event.get("files") or []
                        if isinstance(f, dict) and str(f.get("file_path") or "") == path
                    ), ""),
                })
                invalidated += int(result.get("invalidated") or 0)
            except Exception:
                pass

    with conn:
        if snapshot_mode == "full":
            _delete_fts_for_files(conn, repository_id, [])
            for table in ("code_graph_edges", "code_graph_lines", "code_graph_chunks", "code_graph_symbols", "code_graph_files"):
                conn.execute(f"DELETE FROM {table} WHERE repository_id=?", (repository_id,))
        else:
            _delete_files(conn, repository_id, touched)
            if bool(event.get("edges_full", True)):
                conn.execute("DELETE FROM code_graph_edges WHERE repository_id=?", (repository_id,))
        counts = _insert_graph_rows(conn, event, repository_id, ts)
        repo_stats = event.get("stats") if isinstance(event.get("stats"), dict) else counts
        conn.execute(
            """INSERT INTO code_graph_repositories(repository_id,root,commit_sha,graph_revision,snapshot_hash,generated_at,updated_at,stats_json)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(repository_id) DO UPDATE SET root=excluded.root,commit_sha=excluded.commit_sha,
               graph_revision=excluded.graph_revision,snapshot_hash=excluded.snapshot_hash,
               generated_at=excluded.generated_at,updated_at=excluded.updated_at,stats_json=excluded.stats_json""",
            (repository_id, str(event.get("root") or "")[:2000], str(event.get("commit_sha") or "")[:64],
             str(event.get("graph_revision") or payload_hash[:20])[:160], payload_hash[:128],
             int(event.get("generated_at") or ts), ts, _json(repo_stats)[:100000]),
        )

    embed_stats = _embed_graph_chunks(
        provider, repository_id, str(event.get("commit_sha") or ""), event_id,
        changed_files if snapshot_mode == "delta" else [], pending_only=True,
    )
    result = {
        "repository_id": repository_id,
        "event_id": event_id,
        "snapshot_mode": snapshot_mode,
        "counts": counts,
        "deleted_files": len(deleted_files),
        "invalidated_claims": invalidated,
        "embedding": embed_stats,
        "snapshot_hash": payload_hash,
    }
    with conn:
        conn.execute(
            "INSERT INTO code_graph_events(event_id,repository_id,payload_hash,snapshot_mode,status,stats_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (event_id, repository_id, payload_hash, snapshot_mode, "completed", _json(result), ts),
        )
    return {"status": "completed", "deduplicated": False, **result}


def embed_pending_chunks(provider: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    """Create/reuse semantic claims for graph chunks left pending by bounded ingestion."""
    repository_id = str(args.get("repository_id") or "").strip()
    if not repository_id:
        raise ValueError("repository_id is required")
    limit = max(1, min(int(args.get("limit") or 1000), 10000))
    conn = provider._connect(); install_code_graph_schema(conn)
    repo = conn.execute(
        "SELECT commit_sha,snapshot_hash FROM code_graph_repositories WHERE repository_id=?",
        (repository_id,),
    ).fetchone()
    if not repo:
        raise ValueError(f"unknown repository_id: {repository_id}")
    before = conn.execute(
        "SELECT COUNT(*) FROM code_graph_chunks WHERE repository_id=? AND embedding_claim_id=''",
        (repository_id,),
    ).fetchone()
    stats = _embed_graph_chunks(
        provider, repository_id, str(repo[0] or ""),
        f"manual-backfill:{repository_id}:{str(repo[1] or '')[:20]}", [],
        unit_limit=limit, pending_only=True,
    )
    after = conn.execute(
        "SELECT COUNT(*) FROM code_graph_chunks WHERE repository_id=? AND embedding_claim_id=''",
        (repository_id,),
    ).fetchone()
    return {
        "repository_id": repository_id,
        "pending_before": int(before[0] if before else 0),
        "pending_after": int(after[0] if after else 0),
        "batch_limit": limit,
        "embedding": stats,
    }


def _fts_rows(conn: sqlite3.Connection, table: str, repository_id: str, query: str,
              fields: str, limit: int) -> List[Dict[str, Any]]:
    fts = _fts_query(query)
    if not fts:
        return []
    try:
        rows = conn.execute(
            f"SELECT {fields}, bm25({table}) AS bm25 FROM {table} "
            f"WHERE {table} MATCH ? AND (?='' OR repository_id=?) ORDER BY bm25({table}) LIMIT ?",
            (fts, repository_id, repository_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []


def _like_rows(conn: sqlite3.Connection, repository_id: str, query: str, limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    token = next((t for t in _TOKEN_RE.findall(query) if len(t) >= 3), query[:80])
    pat = f"%{token}%"
    repo_sql = "repository_id=?" if repository_id else "1=1"
    params: List[Any] = [repository_id] if repository_id else []
    symbols = [dict(r) for r in conn.execute(
        f"SELECT repository_id,symbol_id,file_path,qualified_name,signature,0.0 bm25 FROM code_graph_symbols WHERE {repo_sql} AND (qualified_name LIKE ? OR signature LIKE ? OR search_text LIKE ?) LIMIT ?",
        [*params, pat, pat, pat, limit],
    ).fetchall()]
    chunks = [dict(r) for r in conn.execute(
        f"SELECT repository_id,chunk_id,file_path,symbol_id,qualified_name,0.0 bm25 FROM code_graph_chunks WHERE {repo_sql} AND (search_text LIKE ? OR chunk_text LIKE ?) LIMIT ?",
        [*params, pat, pat, limit],
    ).fetchall()]
    lines = [dict(r) for r in conn.execute(
        f"SELECT repository_id,file_path,line_no,line_text,0.0 bm25 FROM code_graph_lines WHERE {repo_sql} AND line_text LIKE ? LIMIT ?",
        [*params, pat, limit],
    ).fetchall()]
    return symbols, chunks, lines


def _rrf_add(scores: Dict[str, float], parts: Dict[str, Dict[str, Any]], keys: Sequence[str],
             source: str, weight: float = 1.0, k: int = 60) -> None:
    for rank, key in enumerate(keys, start=1):
        scores[key] += weight / (k + rank)
        parts[key][source] = {"rank": rank, "weight": weight}


def _candidate_key(kind: str, repository_id: str, object_id: str) -> str:
    # NUL is not valid in SQLite text exported by this integration and avoids
    # ambiguity when repository IDs or symbol IDs themselves contain colons.
    return f"{kind}:{repository_id}\0{object_id}"


def _load_candidate(conn: sqlite3.Connection, key: str) -> Optional[Dict[str, Any]]:
    kind, _, rest = key.partition(":")
    if kind in {"symbol", "chunk"}:
        if "\0" in rest:
            repo, object_id = rest.split("\0", 1)
        else:  # backward compatibility for early v0.1 preview keys
            repo, _, object_id = rest.partition(":")
    if kind == "symbol":
        sid = object_id
        row = conn.execute("SELECT * FROM code_graph_symbols WHERE repository_id=? AND symbol_id=?", (repo, sid)).fetchone()
        if not row:
            return None
        out = dict(row); out["candidate_type"] = "symbol"; out["id"] = sid
        out["excerpt"] = out.get("signature") or out.get("search_text")
        return out
    if kind == "chunk":
        cid = object_id
        row = conn.execute("SELECT * FROM code_graph_chunks WHERE repository_id=? AND chunk_id=?", (repo, cid)).fetchone()
        if not row:
            return None
        out = dict(row); out["candidate_type"] = "chunk"; out["id"] = cid
        out["excerpt"] = out.get("chunk_text")
        return out
    if kind == "line":
        # rest = repo\0path\0line to avoid colon ambiguity in repository IDs.
        parts = rest.split("\0")
        if len(parts) != 3:
            return None
        repo, path, line_no = parts
        row = conn.execute("SELECT * FROM code_graph_lines WHERE repository_id=? AND file_path=? AND line_no=?", (repo, path, int(line_no))).fetchone()
        if not row:
            return None
        out = dict(row); out["candidate_type"] = "line"; out["id"] = out.get("line_id")
        out["start_line"] = out["end_line"] = out.get("line_no"); out["excerpt"] = out.get("line_text")
        return out
    return None


def query_code_graph(provider: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    repository_id = str(args.get("repository_id") or "").strip()
    limit = max(1, min(int(args.get("limit") or 12), 50))
    lexical_limit = max(20, min(int(args.get("candidate_limit") or limit * 8), 300))
    conn = provider._connect()
    install_code_graph_schema(conn)

    symbol_rows = _fts_rows(conn, "code_graph_symbols_fts", repository_id, query,
                            "repository_id,symbol_id,file_path,qualified_name,signature", lexical_limit)
    chunk_rows = _fts_rows(conn, "code_graph_chunks_fts", repository_id, query,
                           "repository_id,chunk_id,file_path,symbol_id,qualified_name", lexical_limit)
    line_rows = _fts_rows(conn, "code_graph_lines_fts", repository_id, query,
                          "repository_id,file_path,line_no,line_text", lexical_limit)
    if not symbol_rows and not chunk_rows and not line_rows:
        symbol_rows, chunk_rows, line_rows = _like_rows(conn, repository_id, query, lexical_limit)

    scores: Dict[str, float] = defaultdict(float)
    score_parts: Dict[str, Dict[str, Any]] = defaultdict(dict)
    symbol_keys = [_candidate_key("symbol", str(r["repository_id"]), str(r["symbol_id"])) for r in symbol_rows]
    chunk_keys = [_candidate_key("chunk", str(r["repository_id"]), str(r["chunk_id"])) for r in chunk_rows]
    line_keys = [f"line:{r['repository_id']}\0{r['file_path']}\0{r['line_no']}" for r in line_rows]
    _rrf_add(scores, score_parts, symbol_keys, "fts_symbol", 1.15)
    _rrf_add(scores, score_parts, chunk_keys, "fts_chunk", 1.0)
    _rrf_add(scores, score_parts, line_keys, "fts_line", 0.75)

    semantic_count = 0
    try:
        # Search the dedicated code-intelligence topic so unrelated personal
        # memories cannot consume Memory Wiki's bounded semantic top-K.
        semantic_rows = provider._search(query, limit=min(50, lexical_limit), include_stale=False,
                                         topic="code-intelligence",
                                         session_id=str(args.get("session_id") or ""))
        claim_ids = [str(r.get("id") or "") for r in semantic_rows if str(r.get("id") or "")]
        if claim_ids:
            placeholders = ",".join("?" for _ in claim_ids)
            sql = (
                "SELECT repository_id,chunk_id,embedding_claim_id FROM code_graph_chunks "
                f"WHERE embedding_claim_id IN ({placeholders})"
            )
            params: List[Any] = list(claim_ids)
            if repository_id:
                sql += " AND repository_id=?"; params.append(repository_id)
            mapping = {str(r["embedding_claim_id"]): dict(r) for r in conn.execute(sql, params).fetchall()}
            semantic_keys = []
            for row in semantic_rows:
                hit = mapping.get(str(row.get("id") or ""))
                if hit:
                    semantic_keys.append(_candidate_key("chunk", str(hit["repository_id"]), str(hit["chunk_id"])))
            semantic_count = len(semantic_keys)
            _rrf_add(scores, score_parts, semantic_keys, "semantic", 1.25)
    except Exception as exc:
        semantic_error = f"{type(exc).__name__}: {exc}"
    else:
        semantic_error = ""

    # Exact file/symbol/path boosts are deterministic and intentionally small.
    q_lower = query.lower()
    for key in list(scores):
        candidate = _load_candidate(conn, key)
        if not candidate:
            continue
        exact_blob = " ".join(str(candidate.get(k) or "") for k in ("file_path", "qualified_name", "short_name", "signature", "symbol_id")).lower()
        exact_tokens = [t.lower() for t in _TOKEN_RE.findall(query) if len(t) >= 3]
        matches = sum(1 for token in exact_tokens if token in exact_blob)
        if matches:
            boost = min(0.035, matches * 0.007)
            scores[key] += boost
            score_parts[key]["exact"] = {"matches": matches, "boost": boost}

    # Structural propagation: a strong symbol/chunk lends a bounded boost to one-hop neighbours.
    seed_keys = sorted(scores, key=scores.get, reverse=True)[: min(20, lexical_limit)]
    seed_symbols = []
    for key in seed_keys:
        item = _load_candidate(conn, key)
        sid = str((item or {}).get("symbol_id") or "")
        repo = str((item or {}).get("repository_id") or "")
        if sid and repo:
            seed_symbols.append((repo, sid, scores[key]))
    for repo, sid, seed_score in seed_symbols:
        for edge in conn.execute(
            "SELECT source_id,predicate,target_id FROM code_graph_edges WHERE repository_id=? AND (source_id=? OR target_id=?) LIMIT 80",
            (repo, sid, sid),
        ).fetchall():
            neighbour = str(edge["target_id"] if edge["source_id"] == sid else edge["source_id"])
            if not neighbour or neighbour.startswith("external:"):
                continue
            neighbour_key = _candidate_key("symbol", repo, neighbour)
            exists = conn.execute("SELECT 1 FROM code_graph_symbols WHERE repository_id=? AND symbol_id=?", (repo, neighbour)).fetchone()
            if exists:
                boost = min(0.012, max(0.003, seed_score * 0.12))
                scores[neighbour_key] += boost
                score_parts[neighbour_key].setdefault("graph", []).append({"via": sid, "predicate": edge["predicate"], "boost": boost})

    ordered = sorted(scores, key=scores.get, reverse=True)[: max(limit * 3, 20)]
    candidates = []
    for key in ordered:
        item = _load_candidate(conn, key)
        if not item:
            continue
        item["score"] = round(scores[key], 8)
        item["score_parts"] = score_parts[key]
        item["excerpt"] = _clean_text(item.get("excerpt"), int(args.get("max_chars_per_hit") or 2400))
        # Attach a compact one-hop graph view.
        sid = str(item.get("symbol_id") or (item.get("id") if item.get("candidate_type") == "symbol" else ""))
        if sid:
            item["relations"] = [dict(r) for r in conn.execute(
                "SELECT predicate,source_id,target_id,source_file,source_line,target_file,confidence "
                "FROM code_graph_edges WHERE repository_id=? AND (source_id=? OR target_id=?) "
                "ORDER BY confidence DESC LIMIT 12",
                (item["repository_id"], sid, sid),
            ).fetchall()]
        candidates.append(item)

    # Reuse the installed Voyage/Cohere reranker without making it mandatory.
    # All candidate kinds participate, not only chunks with persistent claim IDs.
    # _rerank_rows already performs an RRF blend with the input order, so exact
    # symbols and line hits are not discarded by a semantic-only hard reorder.
    reranked = False
    rerank_error = ""
    if candidates and _env_bool("MEMORY_WIKI_CODE_GRAPH_RERANK", True) and hasattr(provider, "_rerank_rows"):
        pseudo = []
        candidate_by_rerank_id: Dict[str, Dict[str, Any]] = {}
        for idx, candidate in enumerate(candidates):
            rerank_id = f"codegraph:{idx}:{candidate.get('candidate_type','')}:{candidate.get('id','')}"
            pseudo_row = {
                "id": rerank_id,
                "claim": candidate.get("embedding_text") or candidate.get("excerpt") or candidate.get("search_text") or "",
                "status": "active", "risk": "low", "trust_class": "code_claim",
                "score": candidate["score"], "score_parts": {},
                "updated_at": int(candidate.get("updated_at") or 0),
            }
            pseudo.append(pseudo_row)
            candidate_by_rerank_id[rerank_id] = candidate
        if len(pseudo) >= 3:
            try:
                reranked_rows = provider._rerank_rows(query, pseudo, "technical")
                ordered_candidates = [candidate_by_rerank_id[str(row.get("id"))]
                                      for row in reranked_rows
                                      if str(row.get("id")) in candidate_by_rerank_id]
                used = {id(item) for item in ordered_candidates}
                ordered_candidates.extend(item for item in candidates if id(item) not in used)
                candidates = ordered_candidates
                reranked = any("rerank_rank" in row for row in reranked_rows)
            except Exception as exc:
                rerank_error = f"{type(exc).__name__}: {exc}"

    return {
        "repository_id": repository_id,
        "query": query,
        "results": candidates[:limit],
        "retrieval": {
            "fts_symbols": len(symbol_rows), "fts_chunks": len(chunk_rows), "fts_lines": len(line_rows),
            "semantic_chunks": semantic_count, "semantic_error": semantic_error,
            "fusion": "weighted_rrf_k60", "reranked": reranked, "rerank_error": rerank_error,
        },
    }


def code_line_context(provider: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    repository_id = str(args.get("repository_id") or "").strip()
    line_id = str(args.get("line_id") or "").strip()
    radius = max(0, min(int(args["radius"] if "radius" in args else 12), 100))
    if not repository_id:
        raise ValueError("repository_id is required")
    conn = provider._connect(); install_code_graph_schema(conn)
    if line_id:
        target = conn.execute(
            "SELECT file_path,line_no FROM code_graph_lines WHERE repository_id=? AND line_id=? LIMIT 1",
            (repository_id, line_id),
        ).fetchone()
        if not target:
            raise ValueError(f"unknown line_id for repository: {line_id}")
        file_path, line_no = str(target[0]), int(target[1])
    else:
        file_path = _canonical_path(args.get("file_path") or "")
        line_no = int(args.get("line_no") or 0)
        if line_no < 1:
            raise ValueError("provide line_id or file_path + line_no")
    rows = [dict(r) for r in conn.execute(
        "SELECT line_no,line_id,anchor_hash,line_text,text_hash,symbol_id,chunk_id,flags FROM code_graph_lines "
        "WHERE repository_id=? AND file_path=? AND line_no BETWEEN ? AND ? ORDER BY line_no",
        (repository_id, file_path, max(1, line_no - radius), line_no + radius),
    ).fetchall()]
    symbol_ids = sorted({str(r.get("symbol_id") or "") for r in rows if str(r.get("symbol_id") or "")})
    symbols = []
    if symbol_ids:
        placeholders = ",".join("?" for _ in symbol_ids)
        symbols = [dict(r) for r in conn.execute(
            f"SELECT symbol_id,qualified_name,kind,signature,start_line,end_line FROM code_graph_symbols WHERE repository_id=? AND symbol_id IN ({placeholders})",
            [repository_id, *symbol_ids],
        ).fetchall()]
    return {"repository_id": repository_id, "file_path": file_path, "target_line": line_no,
            "range": [max(1, line_no - radius), line_no + radius], "lines": rows, "symbols": symbols,
            "line_id": line_id or next((str(r.get("line_id") or "") for r in rows if int(r.get("line_no") or 0) == line_no), ""),
            "note": "Stored lines are redacted navigation copies; use Code Shrinker file.lines or symbol.source for exact source."}


def code_graph_neighbors(provider: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    repository_id = str(args.get("repository_id") or "").strip()
    node_id = str(args.get("node_id") or args.get("symbol_id") or "").strip()
    hops = max(1, min(int(args.get("hops") or 1), 3))
    limit = max(1, min(int(args.get("limit") or 50), 500))
    if not repository_id or not node_id:
        raise ValueError("repository_id and node_id are required")
    conn = provider._connect(); install_code_graph_schema(conn)
    frontier = {node_id}; seen = {node_id}; edges: List[Dict[str, Any]] = []
    for depth in range(1, hops + 1):
        if not frontier or len(edges) >= limit:
            break
        placeholders = ",".join("?" for _ in frontier)
        rows = conn.execute(
            f"SELECT * FROM code_graph_edges WHERE repository_id=? AND (source_id IN ({placeholders}) OR target_id IN ({placeholders})) "
            "ORDER BY confidence DESC LIMIT ?",
            [repository_id, *frontier, *frontier, limit - len(edges)],
        ).fetchall()
        next_frontier = set()
        for row in rows:
            item = dict(row); item["depth"] = depth; edges.append(item)
            for candidate in (str(item["source_id"]), str(item["target_id"])):
                if candidate not in seen and not candidate.startswith("external:"):
                    seen.add(candidate); next_frontier.add(candidate)
        frontier = next_frontier
    nodes = []
    symbol_nodes = [n for n in seen if not n.startswith(("file:", "repo:", "external:"))]
    if symbol_nodes:
        placeholders = ",".join("?" for _ in symbol_nodes)
        nodes = [dict(r) for r in conn.execute(
            f"SELECT symbol_id,file_path,qualified_name,kind,signature,start_line,end_line FROM code_graph_symbols WHERE repository_id=? AND symbol_id IN ({placeholders})",
            [repository_id, *symbol_nodes],
        ).fetchall()]
    return {"repository_id": repository_id, "node_id": node_id, "hops": hops, "nodes": nodes, "edges": edges[:limit]}


def code_graph_status(provider: Any, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = args or {}
    repository_id = str(args.get("repository_id") or "").strip()
    conn = provider._connect(); install_code_graph_schema(conn)
    repos = [dict(r) for r in conn.execute(
        "SELECT * FROM code_graph_repositories " + ("WHERE repository_id=? " if repository_id else "") + "ORDER BY updated_at DESC",
        (repository_id,) if repository_id else (),
    ).fetchall()]
    totals = {}
    for table, label in (("code_graph_files", "files"), ("code_graph_symbols", "symbols"),
                         ("code_graph_chunks", "chunks"), ("code_graph_lines", "lines"),
                         ("code_graph_edges", "edges")):
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table}" + (" WHERE repository_id=?" if repository_id else ""),
            (repository_id,) if repository_id else (),
        ).fetchone()
        totals[label] = int(row[0] if row else 0)
    embedded = conn.execute(
        "SELECT COUNT(*) FROM code_graph_chunks WHERE embedding_claim_id<>''" + (" AND repository_id=?" if repository_id else ""),
        (repository_id,) if repository_id else (),
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) FROM code_graph_chunks WHERE embedding_claim_id=''" + (" AND repository_id=?" if repository_id else ""),
        (repository_id,) if repository_id else (),
    ).fetchone()
    totals["embedded_chunks"] = int(embedded[0] if embedded else 0)
    totals["pending_embedding_chunks"] = int(pending[0] if pending else 0)
    return {
        "enabled": _env_bool("MEMORY_WIKI_CODE_GRAPH", True),
        "schema_version": SCHEMA_VERSION,
        "repositories": repos,
        "totals": totals,
        "embedding_enabled": _env_bool("MEMORY_WIKI_CODE_GRAPH_EMBED", True),
        "rerank_enabled": _env_bool("MEMORY_WIKI_CODE_GRAPH_RERANK", True),
    }


def maybe_prefetch_code_context(provider: Any, query: str, max_chars: int = 8000) -> str:
    if not _env_bool("MEMORY_WIKI_CODE_GRAPH_PREFETCH", True) or not _CODE_HINT.search(str(query or "")):
        return ""
    conn = provider._connect(); install_code_graph_schema(conn)
    repos = [str(r[0]) for r in conn.execute("SELECT repository_id FROM code_graph_repositories ORDER BY updated_at DESC LIMIT 20").fetchall()]
    if not repos:
        return ""
    inferred = ""
    q = str(query or "")
    for repo in repos:
        if repo.lower() in q.lower() or repo.rsplit("/", 1)[-1].lower() in q.lower():
            inferred = repo; break
    if not inferred and len(repos) == 1:
        inferred = repos[0]
    result = query_code_graph(provider, {"query": q, "repository_id": inferred, "limit": 6, "max_chars_per_hit": 1200})
    if not result.get("results"):
        return ""
    lines = ["## Repository code knowledge graph", "Stored excerpts are redacted navigation copies; request exact source from Code Shrinker before editing."]
    for item in result["results"]:
        location = f"{item.get('file_path','')}:{item.get('start_line') or item.get('line_no') or 0}-{item.get('end_line') or item.get('line_no') or 0}"
        label = item.get("qualified_name") or item.get("symbol_id") or item.get("id")
        lines.append(f"- [{item.get('candidate_type')}] {location} {label} score={item.get('score',0):.5f}")
        excerpt = re.sub(r"\s+", " ", str(item.get("excerpt") or "")).strip()
        if excerpt:
            lines.append("  " + excerpt[:900])
        relations = item.get("relations") or []
        if relations:
            compact = ", ".join(f"{r.get('source_id')} -{r.get('predicate')}→ {r.get('target_id')}" for r in relations[:4])
            lines.append("  graph: " + compact[:1000])
    return "\n".join(lines)[: max(1000, min(int(max_chars), 24000))]


__all__ = [
    "install_code_graph_schema", "ingest_code_graph_event", "query_code_graph",
    "code_line_context", "code_graph_neighbors", "code_graph_status",
    "embed_pending_chunks", "maybe_prefetch_code_context",
]
