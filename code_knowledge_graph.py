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
import math
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import nullcontext
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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
_SENSITIVE_EVENT_KEY_RE = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|token|password|passwd|secret|authorization|credential|private[_-]?key)(?:$|[_-])"
)
_OPAQUE_GRAPH_ID_RE = re.compile(r"redacted-graph-id-[0-9a-f]{64}\Z")
_OPAQUE_GRAPH_ID_PREFIX = "redacted-graph-id-"
# v1 was the first deterministic identity redaction domain.  A token that
# merely *looks* like one is not evidence that this module minted it, so v2
# is a one-way provenance migration for every pre-registry opaque value.
_GRAPH_IDENTITY_PROVENANCE_VERSION = 2
_GRAPH_IDENTITY_MIGRATION_VERSION = 2
_GRAPH_IDENTITY_PROVENANCE_TABLE = "code_graph_identity_provenance"
_GRAPH_IDENTITY_MIGRATIONS_TABLE = "code_graph_identity_migrations"
_GRAPH_INTEGRITY_FIELDS = frozenset({
    "anchor_hash", "commit_sha", "content_hash", "file_hash", "graph_payload_hash",
    "new_content_hash", "old_content_hash", "payload_hash", "snapshot_hash", "text_hash",
})
_GRAPH_IDENTITY_FIELDS = frozenset({
    "changed_files", "changed_symbols", "chunk_id", "deleted_files", "edge_id", "event_id",
    "file_path", "line_id", "patch_id", "producer", "repository_id", "source_file",
    "source_event_id", "source_id", "symbol_id", "target_file", "target_id",
})
# A provider connection is deliberately shared between some Hermes worker
# threads.  SQLite serializes independent connections, but two callers cannot
# safely start overlapping top-level transactions on the *same* connection.
# Keep the short graph lifecycle transaction single-file in-process; BEGIN
# IMMEDIATE below provides the corresponding cross-provider/process boundary.
_GRAPH_INGEST_LOCK = threading.RLock()


def _provider_claim_lock(provider: Any):
    """Return the provider claim lock, or a no-op context for small test doubles.

    Graph embedding must always take this in-process lock before taking a
    private SQLite writer.  Ordinary claim writes take the same lock before
    their SQLite mutations; reversing that order causes a 30-second SQLite
    busy wait/deadlock under concurrent embedding.
    """
    lock = getattr(provider, "_lock", None)
    return lock if hasattr(lock, "__enter__") and hasattr(lock, "__exit__") else nullcontext()


def _now() -> int:
    return int(time.time())


def _sha(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", "replace")).hexdigest()


def _opaque_graph_id_v1(value: Any) -> str:
    return _OPAQUE_GRAPH_ID_PREFIX + _sha("identity-v1\0" + str(value or ""))


def _opaque_graph_id_v2(value: Any) -> str:
    """Return the deterministic migration alias for one legacy opaque ID."""
    return _OPAQUE_GRAPH_ID_PREFIX + _sha("identity-v2\0" + str(value or ""))


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
        raise ValueError("invalid repository-relative path")
    if any(part == ".." for part in value.split("/")):
        raise ValueError("repository-relative path traversal rejected")
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


def _redact_graph_text(value: Any, limit: int, redactor: Optional[Callable[[str], str]] = None) -> str:
    """Bounded graph text with the provider's complete secret redactor applied.

    ``code_knowledge_graph`` remains usable by tiny standalone test providers,
    so the local PEM/assignment guard is retained as a fail-closed fallback.
    The installed provider passes ``redact_secrets`` through a method, avoiding
    a circular import while covering all of Memory Wiki's credential patterns.
    """
    text = _clean_text(str(value or "").replace("\x00", ""), max(0, limit))
    if callable(redactor):
        try:
            text = str(redactor(text)).replace("\x00", "")
        except Exception:
            pass
    return _clean_text(text, limit)


def _redact_graph_identity(
    value: Any,
    redactor: Optional[Callable[[str], str]] = None,
    *,
    preserve_opaque_id: bool = False,
) -> str:
    """Keep graph joins stable without retaining a secret-bearing identifier.

    File paths and graph IDs are relational keys, so replacing every secret with
    one generic marker could merge unrelated files or nodes.  When the normal
    text redactor changes one, replace the *whole* identity with a deterministic
    opaque token instead.  All references to the same raw identity therefore
    still join, while SQLite, recovery records and public results never retain
    the sensitive spelling.
    """
    raw = str(value or "").replace("\x00", "")
    # The opaque form deliberately includes a 64-hex digest.  Its spelling is
    # not proof of provenance: a producer or ordinary caller can imitate it.
    # Preserve it only when the caller has already established that this is a
    # persisted graph key or a verified recovery artifact; raw ingress treats
    # an imitation as ordinary input and deterministically maps it again.
    if _OPAQUE_GRAPH_ID_RE.fullmatch(raw):
        # Never delegate this case to the generic secret redactor.  Small test
        # providers and future redactor changes may leave the spelling intact;
        # in that case a caller-controlled imitation would otherwise become a
        # durable/public graph key.  ``preserve_opaque_id`` is used only after
        # the caller has independently checked the exact ID in the provenance
        # registry below.
        return raw if preserve_opaque_id else _opaque_graph_id_v1(raw)
    safe = _redact_graph_text(raw, 40_000, redactor)
    if safe == raw:
        return raw
    return _opaque_graph_id_v1(raw)


def _is_graph_integrity_digest(key: str, value: Any) -> bool:
    """Only preserve syntactically valid generated digests verbatim.

    Producer metadata called ``snapshot_hash``/``file_hash`` is otherwise just
    free-form text.  Exempting it solely because of the field name would let a
    credential bypass the graph redactor.
    """
    text = str(value or "").strip()
    lower_key = str(key or "").lower()
    if lower_key == "commit_sha":
        return bool(re.fullmatch(r"[0-9a-fA-F]{7,64}", text))
    return bool(re.fullmatch(r"(?:sha256:)?[0-9a-fA-F]{64}", text))


def _provider_graph_redactor(provider: Any) -> Optional[Callable[[str], str]]:
    candidate = getattr(provider, "_redact_code_graph_text", None)
    return candidate if callable(candidate) else None


def _opaque_graph_id_provenance_version(
    conn: Optional[sqlite3.Connection], value: Any,
) -> int:
    """Return the exact locally-minted provenance version for one opaque ID.

    The regular expression deliberately has no authority here: an event
    producer can copy the format.  This small durable registry is the only
    source of truth used by checkpoint, recovery and public-output exceptions.
    """
    candidate = str(value or "").strip()
    if conn is None or not _OPAQUE_GRAPH_ID_RE.fullmatch(candidate):
        return 0
    try:
        row = conn.execute(
            f"SELECT provenance_version FROM {_GRAPH_IDENTITY_PROVENANCE_TABLE} "
            "WHERE opaque_id=?",
            (candidate,),
        ).fetchone()
    except sqlite3.Error:
        return 0
    try:
        return int(row[0]) if row is not None else 0
    except (TypeError, ValueError, IndexError):
        return 0


def _graph_identity_migration_complete(conn: Optional[sqlite3.Connection]) -> bool:
    if conn is None:
        return False
    try:
        row = conn.execute(
            f"SELECT 1 FROM {_GRAPH_IDENTITY_MIGRATIONS_TABLE} "
            "WHERE migration_version=? LIMIT 1",
            (_GRAPH_IDENTITY_MIGRATION_VERSION,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _register_opaque_graph_id_provenance(
    conn: Optional[sqlite3.Connection], values: Sequence[str], *, version: int,
) -> None:
    """Record only IDs that this process just deterministically minted."""
    if conn is None:
        return
    rows = sorted({
        str(value or "").strip()
        for value in values
        if _OPAQUE_GRAPH_ID_RE.fullmatch(str(value or "").strip())
    })
    if not rows:
        return
    try:
        conn.executemany(
            f"INSERT INTO {_GRAPH_IDENTITY_PROVENANCE_TABLE}("
            "opaque_id,provenance_version,created_at) VALUES(?,?,?) "
            "ON CONFLICT(opaque_id) DO UPDATE SET "
            "provenance_version=MAX(provenance_version,excluded.provenance_version)",
            [(value, int(version), _now()) for value in rows],
        )
    except sqlite3.Error:
        # Schema installation is best-effort for tiny graph-only test doubles.
        # Callers retain fail-closed redaction when the registry is unavailable.
        return


def register_code_graph_identity_provenance(
    conn: sqlite3.Connection, values: Sequence[str], *, version: Optional[int] = None,
) -> None:
    """Provider-facing atomic registration helper for code-claim/patch writes."""
    _register_opaque_graph_id_provenance(
        conn,
        values,
        version=(
            int(version)
            if version is not None
            else (
                _GRAPH_IDENTITY_PROVENANCE_VERSION
                if _graph_identity_migration_complete(conn) else 1
            )
        ),
    )


def code_graph_identity_provenance_version(conn: Optional[sqlite3.Connection]) -> int:
    """Return the version to bind to a newly persisted recovery artifact."""
    return (
        _GRAPH_IDENTITY_PROVENANCE_VERSION
        if _graph_identity_migration_complete(conn) else 1
    )


def collect_code_graph_event_opaque_ids(event: Dict[str, Any]) -> frozenset[str]:
    """Collect only schema identity-field tokens, never incidental text."""
    found: set[str] = set()

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif (
            str(key or "").lower() in _GRAPH_IDENTITY_FIELDS
            and _OPAQUE_GRAPH_ID_RE.fullmatch(str(value or "").strip())
        ):
            found.add(str(value).strip())

    if isinstance(event, dict):
        collect(event)
    return frozenset(found)


def _provider_graph_connection(provider: Any) -> Optional[sqlite3.Connection]:
    connect = getattr(provider, "_connect", None)
    if not callable(connect):
        return None
    try:
        return connect()
    except Exception:
        return None


def _canonicalize_live_graph_identity(
    value: Any,
    *,
    redactor: Optional[Callable[[str], str]],
    conn: Optional[sqlite3.Connection],
    trusted_opaque_id: bool,
) -> str:
    """Resolve an ingress/query key to the current durable graph identity.

    A trusted recovery artifact can retain an opaque spelling only when that
    exact value appears in the local provenance registry.  Old v1 artifacts
    remain replayable: once v2 migration is complete their deterministic v2
    alias is used instead.
    """
    raw = str(value or "").replace("\x00", "")
    provenance_version = _opaque_graph_id_provenance_version(conn, raw)
    if trusted_opaque_id and _OPAQUE_GRAPH_ID_RE.fullmatch(raw):
        if provenance_version >= _GRAPH_IDENTITY_PROVENANCE_VERSION:
            return raw
        # A recovered v1 event is already the redacted representation of a
        # source-side key.  It must advance to the exact v2 alias after the
        # migration, not be treated as fresh user input and hashed a second
        # time.  Before migration, only a registry-backed v1 key may remain
        # stable; an unknown legacy/artifact spelling is re-keyed below.
        if _graph_identity_migration_complete(conn):
            return _opaque_graph_id_v2(raw)
        if provenance_version > 0:
            return raw
    safe = _redact_graph_identity(
        raw,
        redactor,
        preserve_opaque_id=bool(trusted_opaque_id and provenance_version > 0),
    )
    if not _OPAQUE_GRAPH_ID_RE.fullmatch(safe):
        return safe
    # A pre-v2 generated ID is intentionally remapped with all legacy IDs.
    # A raw source-side secret still derives its former v1 value first, so its
    # v2 alias is stable across query, replay and later live ingestion.
    if _graph_identity_migration_complete(conn):
        return _opaque_graph_id_v2(safe)
    return safe


def _migrate_stored_graph_identity(
    value: Any,
    *,
    redactor: Optional[Callable[[str], str]],
    conn: Optional[sqlite3.Connection],
) -> str:
    """Re-key a persisted identity unless it is an exact v2-minted value."""
    raw = str(value or "").replace("\x00", "")
    if _OPAQUE_GRAPH_ID_RE.fullmatch(raw):
        if _opaque_graph_id_provenance_version(conn, raw) >= _GRAPH_IDENTITY_PROVENANCE_VERSION:
            return raw
        return _opaque_graph_id_v2(raw)
    safe = _redact_graph_identity(raw, redactor, preserve_opaque_id=False)
    if _OPAQUE_GRAPH_ID_RE.fullmatch(safe):
        if _opaque_graph_id_provenance_version(conn, safe) >= _GRAPH_IDENTITY_PROVENANCE_VERSION:
            return safe
        return _opaque_graph_id_v2(safe)
    return safe


def _graph_lookup_identity(
    provider: Any, value: Any, *, trusted_opaque_id: bool = False,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """Map a caller's raw graph key to the safe form used by storage."""
    return _canonicalize_live_graph_identity(
        value,
        redactor=_provider_graph_redactor(provider),
        conn=conn if conn is not None else _provider_graph_connection(provider),
        trusted_opaque_id=trusted_opaque_id,
    )


def _sanitize_graph_event_for_storage(
    event: Dict[str, Any],
    redactor: Optional[Callable[[str], str]] = None,
    *,
    preserve_opaque_ids: bool = False,
    identity_mapper: Optional[Callable[[Any], str]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Recursively redact free-form graph event data before it reaches SQLite.

    Integrity identifiers stay opaque and exact: lifecycle hashes were computed
    from the producer's raw source before this pass, so redacted secret rotation
    cannot collapse two revisions into one graph row.
    """
    changed = False

    def scrub(value: Any, key: str = "") -> Any:
        nonlocal changed
        lower_key = str(key or "").lower()
        if _SENSITIVE_EVENT_KEY_RE.search(lower_key) and lower_key != "token_estimate":
            # Do not rely on pattern recognition for a value whose field name
            # itself declares it secret: short credentials and opaque tokens
            # otherwise evade a text-only redactor.
            if value != "<REDACTED_KEYED_VALUE>":
                changed = True
            return "<REDACTED_KEYED_VALUE>"
        if isinstance(value, dict):
            return {str(child_key): scrub(child_value, str(child_key)) for child_key, child_value in value.items()}
        if isinstance(value, list):
            return [scrub(item, key) for item in value]
        if isinstance(value, str):
            if lower_key in _GRAPH_INTEGRITY_FIELDS and _is_graph_integrity_digest(lower_key, value):
                return value
            if lower_key in _GRAPH_IDENTITY_FIELDS:
                safe = (
                    identity_mapper(value)
                    if callable(identity_mapper)
                    else _redact_graph_identity(
                        value,
                        redactor,
                        preserve_opaque_id=preserve_opaque_ids,
                    )
                )
                if safe != value:
                    changed = True
                return safe
            safe = _redact_graph_text(value, 40_000, redactor)
            if safe != value:
                changed = True
            return safe
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        safe = _redact_graph_text(value, 40_000, redactor)
        if safe != str(value):
            changed = True
        return safe

    return scrub(event), changed


def _safe_graph_output(
    provider: Any, value: Any, key: str = "", *,
    _conn: Optional[sqlite3.Connection] = None,
) -> Any:
    """Redact legacy rows at the public/model boundary as defense in depth."""
    if _conn is None:
        _conn = _provider_graph_connection(provider)
    lower_key = str(key or "").lower()
    if _SENSITIVE_EVENT_KEY_RE.search(lower_key) and lower_key != "token_estimate":
        return "<REDACTED_KEYED_VALUE>"
    if isinstance(value, dict):
        return {
            str(child_key): _safe_graph_output(
                provider, child_value, str(child_key), _conn=_conn,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_safe_graph_output(provider, item, key, _conn=_conn) for item in value]
    if isinstance(value, str):
        if lower_key in _GRAPH_INTEGRITY_FIELDS and _is_graph_integrity_digest(lower_key, value):
            return value
        if lower_key in _GRAPH_IDENTITY_FIELDS:
            # Output never trusts the spelling alone.  This also prevents a
            # legacy row from leaking through before maintenance/checkpoint
            # gets a chance to rewrite it transactionally.
            return _migrate_stored_graph_identity(
                value,
                redactor=_provider_graph_redactor(provider),
                conn=_conn,
            )
        return _redact_graph_text(value, 40_000, _provider_graph_redactor(provider))
    return value


def _canonicalize_sanitized_graph_event_identities(
    event: Dict[str, Any],
    conn: Optional[sqlite3.Connection],
    *,
    trusted_opaque_ids: bool,
) -> Tuple[Dict[str, Any], set[str]]:
    """Apply the v2 alias to an already-redacted event before SQLite writes.

    The first redaction pass must happen before opening the writer because it
    is part of event-payload validation.  This second, connection-aware pass
    is deliberately narrow: it decides whether an already-safe opaque key is
    a registered v2 key, a replayable v1 key, or an untrusted legacy spelling.
    """
    minted: set[str] = set()
    migration_complete = _graph_identity_migration_complete(conn)

    def remap(value: Any, key: str = "") -> Any:
        lower_key = str(key or "").lower()
        if isinstance(value, dict):
            return {str(child_key): remap(child_value, str(child_key)) for child_key, child_value in value.items()}
        if isinstance(value, list):
            return [remap(item, key) for item in value]
        if not isinstance(value, str) or lower_key not in _GRAPH_IDENTITY_FIELDS:
            return value
        candidate = value.strip()
        if not _OPAQUE_GRAPH_ID_RE.fullmatch(candidate):
            return value
        provenance_version = _opaque_graph_id_provenance_version(conn, candidate)
        if trusted_opaque_ids and provenance_version >= _GRAPH_IDENTITY_PROVENANCE_VERSION:
            minted.add(candidate)
            return candidate
        if migration_complete:
            # A v1 artifact whose provenance row was restored is upgraded to
            # its deterministic v2 alias; an unverified legacy spelling gets
            # the same fail-closed treatment.
            mapped = _opaque_graph_id_v2(candidate)
        elif not trusted_opaque_ids:
            # Normal ingress already ran this value through
            # _redact_graph_identity(... preserve_opaque_id=False).  Thus an
            # opaque candidate here is the v1 alias just minted from raw
            # source input (including a raw imitation), not a producer token
            # that may be enrolled verbatim.
            mapped = candidate
        elif provenance_version > 0:
            # A hash-bound recovery artifact may seed an exact v1 registry
            # row before the v2 migration runs. Keep that proven legacy key
            # stable until the one-way upgrade boundary.
            mapped = candidate
        else:
            # A digest-valid artifact proves bytes, not that its producer
            # minted a token-shaped field. Never let an old artifact (or a
            # poisoned pre-registry row) enroll its spelling as provenance.
            mapped = _opaque_graph_id_v1(candidate)
        minted.add(mapped)
        return mapped

    return remap(event), minted


def canonicalize_code_graph_recovery_event(
    provider: Any, event: Dict[str, Any], *, trusted_opaque_ids: bool = True,
) -> Dict[str, Any]:
    """Return a persisted recovery event with current exact-ID aliases.

    Call this after the corresponding live graph/patch write has registered
    its minted identities.  It keeps artifact metadata and replay inputs on the
    same v2 namespace without treating a syntactic producer token as trusted.
    """
    if not isinstance(event, dict):
        raise ValueError("code graph recovery event must be an object")
    conn, owns_conn = _open_graph_reader_connection(provider)
    try:
        canonical, _ = _canonicalize_sanitized_graph_event_identities(
            dict(event), conn, trusted_opaque_ids=trusted_opaque_ids,
        )
        return canonical
    finally:
        _close_graph_writer_connection(conn, owns_conn)


def _redact_graph_storage_value(
    value: Any,
    redactor: Optional[Callable[[str], str]] = None,
    *,
    identity_mapper: Optional[Callable[[Any], str]] = None,
    key: str = "value",
) -> str:
    """Redact one persisted text column, including structured JSON fields."""
    original = str(value or "")
    try:
        parsed = json.loads(original)
    except (TypeError, ValueError):
        return _redact_graph_text(original, 40_000, redactor)
    root_key = str(key or "value")
    safe, changed = _sanitize_graph_event_for_storage(
        {root_key: parsed},
        redactor,
        preserve_opaque_ids=False,
        identity_mapper=identity_mapper,
    )
    if not changed:
        return original
    return _json(safe.get(root_key))


def _scrub_patch_outcome_storage_value(
    provider: Any,
    field: str,
    value: Any,
    *,
    redactor: Optional[Callable[[str], str]],
    identity_mapper: Optional[Callable[[Any], str]],
) -> str:
    """Apply the provider's patch-report firewall to legacy durable rows.

    ``validation_report_json`` is not a graph event: its arbitrary JSON keys
    are diagnostics and may themselves contain credentials.  The live patch
    path owns the canonical sanitizer, so maintenance uses that exact helper
    rather than the generic graph scrubber (which deliberately preserves JSON
    keys for relational graph records).
    """
    original = str(value or "")
    text_sanitizer = getattr(provider, "_safe_patch_text", None)
    report_sanitizer = getattr(provider, "_safe_patch_validation_report", None)
    if not callable(text_sanitizer) or not callable(report_sanitizer):
        # Do not pretend generic key-preserving graph cleanup made this safe.
        # The shipped provider always supplies these helpers; an incompatible
        # test double must fail closed instead of retaining a raw legacy row.
        raise RuntimeError("patch outcome scrub requires provider patch sanitizers")
    if field == "outcome":
        return str(text_sanitizer(original, 128))
    if field == "rollback_steps":
        return str(text_sanitizer(original, 20_000))
    if field == "validation_report_json":
        try:
            parsed = json.loads(original)
        except (TypeError, ValueError):
            return str(text_sanitizer(original, 12_000))
        safe = report_sanitizer(parsed)
        if safe == parsed:
            return original
        return _json(safe)
    return _redact_graph_storage_value(
        original,
        redactor,
        identity_mapper=identity_mapper,
        key=(field[:-5] if field.endswith("_json") else field),
    )


def _public_graph_candidate(provider: Any, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Remove internal full-text columns before returning a graph search hit."""
    omitted = {"chunk_text", "embedding_text", "search_text", "contract_json", "imports_json"}
    return _safe_graph_output(
        provider, {key: value for key, value in candidate.items() if key not in omitted}
    )


def _graph_event_list(event: Dict[str, Any], field: str) -> List[Any]:
    """Return a graph row list, rejecting shapes that could erase a full snapshot."""
    value = event.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"code graph {field} must be a list")
    return value


def _graph_event_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"code graph {field} must be an integer") from exc


def _graph_event_nonnegative_int(value: Any, field: str) -> int:
    return max(0, _graph_event_int(value, field))


def _graph_event_confidence(value: Any, field: str) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"code graph {field} must be a finite number") from exc
    if not math.isfinite(confidence):
        raise ValueError(f"code graph {field} must be a finite number")
    return max(0.0, min(confidence, 1.0))


def _normalize_code_graph_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Validate every graph-write conversion before claims or rows can change.

    A full snapshot treats omitted files as deleted. Consequently malformed
    collection shapes and row values must be rejected before revision
    invalidation; silently skipping them can otherwise archive valid claims and
    replace the graph with a partial view.
    """
    normalized = dict(event)

    files: List[Dict[str, Any]] = []
    for index, raw in enumerate(_graph_event_list(event, "files")):
        if not isinstance(raw, dict):
            raise ValueError(f"code graph files[{index}] must be an object")
        item = dict(raw)
        item["file_path"] = _canonical_path(item.get("file_path") or "")
        item["line_count"] = _graph_event_nonnegative_int(
            item.get("line_count") or 0, f"files[{index}].line_count"
        )
        files.append(item)
    normalized["files"] = files

    symbols: List[Dict[str, Any]] = []
    for index, raw in enumerate(_graph_event_list(event, "symbols")):
        if not isinstance(raw, dict):
            raise ValueError(f"code graph symbols[{index}] must be an object")
        item = dict(raw)
        symbol_id = str(item.get("symbol_id") or "").strip()[:512]
        item["symbol_id"] = symbol_id
        if symbol_id:
            item["file_path"] = _canonical_path(item.get("file_path") or "")
            item["start_line"] = _graph_event_nonnegative_int(
                item.get("start_line") or 0, f"symbols[{index}].start_line"
            )
            item["end_line"] = _graph_event_nonnegative_int(
                item.get("end_line") or 0, f"symbols[{index}].end_line"
            )
            supplied_hash = str(item.get("content_hash") or "").strip().lower().removeprefix("sha256:")
            if re.fullmatch(r"[0-9a-f]{64}", supplied_hash):
                item["content_hash"] = supplied_hash
            else:
                raw_search = " ".join((
                    str(item.get("search_text") or ""), str(item.get("qualified_name") or item.get("name") or ""),
                    str(item.get("signature") or ""), _json(item.get("contract") or {}),
                ))
                item["content_hash"] = _sha(raw_search.replace("\x00", ""))
        symbols.append(item)
    normalized["symbols"] = symbols

    chunks: List[Dict[str, Any]] = []
    chunk_limit = _env_int("MEMORY_WIKI_CODE_GRAPH_CHUNK_MAX_CHARS", 12000, 1000, 40000)
    for index, raw in enumerate(_graph_event_list(event, "chunks")):
        if not isinstance(raw, dict):
            raise ValueError(f"code graph chunks[{index}] must be an object")
        item = dict(raw)
        chunk_id = str(item.get("chunk_id") or "").strip()[:512]
        item["chunk_id"] = chunk_id
        if chunk_id:
            item["file_path"] = _canonical_path(item.get("file_path") or "")
            item["start_line"] = _graph_event_nonnegative_int(
                item.get("start_line") or 0, f"chunks[{index}].start_line"
            )
            item["end_line"] = _graph_event_nonnegative_int(
                item.get("end_line") or 0, f"chunks[{index}].end_line"
            )
            raw_chunk_text = str(item.get("chunk_text") or "").replace("\x00", "")[:chunk_limit]
            chunk_text = _clean_text(raw_chunk_text, chunk_limit)
            supplied_hash = str(item.get("content_hash") or "").strip().lower().removeprefix("sha256:")
            item["content_hash"] = (
                supplied_hash if re.fullmatch(r"[0-9a-f]{64}", supplied_hash)
                else _sha(raw_chunk_text)
            )
            item["token_estimate"] = _graph_event_nonnegative_int(
                item.get("token_estimate") or max(1, len(chunk_text) // 4),
                f"chunks[{index}].token_estimate",
            )
        chunks.append(item)
    normalized["chunks"] = chunks

    # The writer deliberately caps line ingestion. Dropping excess entries
    # here preserves that behavior while eliminating a validation-to-use gap.
    max_lines = _env_int("MEMORY_WIKI_CODE_GRAPH_MAX_LINES_PER_EVENT", 750000, 0, 5000000)
    lines: List[Dict[str, Any]] = []
    for index, raw in enumerate(_graph_event_list(event, "lines")[:max_lines]):
        if not isinstance(raw, dict):
            raise ValueError(f"code graph lines[{index}] must be an object")
        item = dict(raw)
        item["file_path"] = _canonical_path(item.get("file_path") or "")
        item["line_no"] = _graph_event_int(item.get("line_no") or 0, f"lines[{index}].line_no")
        supplied_hash = str(item.get("text_hash") or "").strip().lower().removeprefix("sha256:")
        item["text_hash"] = (
            supplied_hash if re.fullmatch(r"[0-9a-f]{64}", supplied_hash)
            else _sha(str(item.get("line_text") or "").replace("\x00", "")[:2000])
        )
        lines.append(item)
    normalized["lines"] = lines

    edges: List[Dict[str, Any]] = []
    for index, raw in enumerate(_graph_event_list(event, "edges")):
        if not isinstance(raw, dict):
            raise ValueError(f"code graph edges[{index}] must be an object")
        item = dict(raw)
        source_id = str(item.get("source_id") or "").strip()[:700]
        target_id = str(item.get("target_id") or "").strip()[:700]
        item["source_id"] = source_id
        item["target_id"] = target_id
        if source_id and target_id:
            source_file = str(item.get("source_file") or "").strip()
            target_file = str(item.get("target_file") or "").strip()
            item["source_file"] = _canonical_path(source_file) if source_file else ""
            item["target_file"] = _canonical_path(target_file) if target_file else ""
            item["source_line"] = _graph_event_nonnegative_int(
                item.get("source_line") or 0, f"edges[{index}].source_line"
            )
            item["confidence"] = _graph_event_confidence(
                item.get("confidence") or 0.5, f"edges[{index}].confidence"
            )
        edges.append(item)
    normalized["edges"] = edges

    deleted_files: List[str] = []
    for index, value in enumerate(_graph_event_list(event, "deleted_files")):
        if str(value or "").strip():
            try:
                deleted_files.append(_canonical_path(value))
            except ValueError as exc:
                raise ValueError(f"invalid deleted_files[{index}]: {type(exc).__name__}") from exc
    normalized["deleted_files"] = deleted_files

    # A snapshot may carry semantic rows without a separate file inventory
    # (older producers commonly sent line-only events).  Materialize a stable
    # placeholder file for every such path before the lifecycle transaction.
    # That gives the next full snapshot a durable ownership record to compare
    # and prevents a later empty snapshot from silently leaving its claims
    # alive.  Explicit file rows remain authoritative for hashes/metadata.
    declared_paths = {str(item["file_path"]) for item in files}
    for collection, identity in ((symbols, "symbol_id"), (chunks, "chunk_id")):
        for item in collection:
            if not str(item.get(identity) or ""):
                continue
            path = str(item.get("file_path") or "")
            if path and path not in declared_paths:
                files.append({"file_path": path, "file_hash": "", "line_count": 0})
                declared_paths.add(path)
    for item in lines:
        path = str(item.get("file_path") or "")
        if path and path not in declared_paths:
            files.append({"file_path": path, "file_hash": "", "line_count": 0})
            declared_paths.add(path)
    normalized["files"] = files

    # These conversions happen after claim invalidation in the writer, so make
    # them deterministic before the lifecycle mutation begins as well.
    if normalized.get("generated_at"):
        normalized["generated_at"] = _graph_event_int(normalized["generated_at"], "generated_at")
    return normalized


def normalized_code_graph_event_payload_hash(event: Dict[str, Any]) -> str:
    """Return the exact v3 digest used for a live graph-event reservation.

    Recovery artifacts retain only a redacted event view.  The live writer
    therefore captures this opaque digest before redaction and seals it into a
    separately hash-bound artifact envelope.  Keeping the calculation here
    prevents the producer and recovery paths from drifting in normalization
    details (path cleanup, derived text hashes, and synthetic file rows).
    """
    if not isinstance(event, dict):
        raise ValueError("code graph event must be an object")
    return _sha(_json(_normalize_code_graph_event(event)))


def sanitize_code_graph_event_for_recovery(
    event: Dict[str, Any],
    redactor: Optional[Callable[[str], str]] = None,
    *,
    preserve_opaque_ids: bool = False,
) -> Dict[str, Any]:
    """Return a replayable event containing only the graph's redacted text view.

    Code Shrinker is the source of truth for exact source.  Recovery artifacts
    need enough structure to rebuild the local graph, but must never become a
    second vault of unredacted code or credentials.
    """
    if not isinstance(event, dict):
        raise ValueError("code graph recovery event must be an object")

    def safe_dict_key(value: Any, existing: Dict[str, Any]) -> str:
        """Redact a producer-controlled JSON key without changing dispatch.

        Graph event payloads normally use schema-defined object names, but an
        arbitrary extra property can otherwise make its raw name durable in a
        recovery artifact.  The caller still recurses with the original name
        below, so key-sensitive validation/identity handling retains its
        established semantics.
        """
        key = _redact_graph_text(value, 256, redactor) or "<redacted_key>"
        if key not in existing:
            return key
        suffix = 2
        candidate = f"{key}_{suffix}"
        while candidate in existing:
            suffix += 1
            candidate = f"{key}_{suffix}"
        return candidate

    def scrub(value: Any, key: str = "") -> Any:
        if _SENSITIVE_EVENT_KEY_RE.search(str(key or "")) and str(key or "").lower() not in {"token_estimate"}:
            return "<REDACTED_KEYED_VALUE>"
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for child_key, item in value.items():
                raw_key = str(child_key)
                out[safe_dict_key(raw_key, out)] = scrub(item, raw_key)
            return out
        if isinstance(value, list):
            return [scrub(item, key) for item in value]
        if isinstance(value, str):
            if (
                str(key or "").lower() in _GRAPH_INTEGRITY_FIELDS
                and _is_graph_integrity_digest(str(key or "").lower(), value)
            ):
                return value
            if str(key or "").lower() in _GRAPH_IDENTITY_FIELDS:
                return _redact_graph_identity(
                    value,
                    redactor,
                    preserve_opaque_id=preserve_opaque_ids,
                )
            return _redact_graph_text(value, 40_000, redactor)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return _redact_graph_text(value, 40_000, redactor)

    return scrub(event)


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
            graph_event_id TEXT NOT NULL DEFAULT '',
            graph_payload_hash TEXT NOT NULL DEFAULT '',
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
            payload_hash_version INTEGER NOT NULL DEFAULT 1,
            snapshot_mode TEXT NOT NULL DEFAULT 'full',
            status TEXT NOT NULL DEFAULT 'completed',
            stats_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        );
        -- A matching digest-shaped token is user-controlled input until this
        -- registry says this exact value was minted by graph ingress/migration.
        CREATE TABLE IF NOT EXISTS code_graph_identity_provenance(
            opaque_id TEXT PRIMARY KEY,
            provenance_version INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        -- One durable marker makes raw source identity -> v1 -> v2 aliasing
        -- deterministic after the legacy-store migration has completed.
        CREATE TABLE IF NOT EXISTS code_graph_identity_migrations(
            migration_version INTEGER PRIMARY KEY,
            completed_at INTEGER NOT NULL
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
        event_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(code_graph_events)").fetchall()}
        if "payload_hash_version" not in event_columns:
            # Existing rows used a producer-supplied snapshot hash.  Keep that
            # marker so replays of a pre-upgrade, already-committed event remain
            # compatible while all new rows bind to the canonical payload.
            conn.execute("ALTER TABLE code_graph_events ADD COLUMN payload_hash_version INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        chunk_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(code_graph_chunks)").fetchall()}
        if "graph_event_id" not in chunk_columns:
            conn.execute("ALTER TABLE code_graph_chunks ADD COLUMN graph_event_id TEXT NOT NULL DEFAULT ''")
        if "graph_payload_hash" not in chunk_columns:
            conn.execute("ALTER TABLE code_graph_chunks ADD COLUMN graph_payload_hash TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cgc_snapshot ON "
            "code_graph_chunks(repository_id,graph_event_id,graph_payload_hash)"
        )
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


def _open_graph_writer_connection(provider: Any) -> Tuple[sqlite3.Connection, bool]:
    """Open a private SQLite writer for graph lifecycle operations.

    ``MemoryWikiProvider._connect()`` is deliberately shared by worker threads.
    A top-level transaction on that connection can be committed accidentally by
    an unrelated provider method which calls ``commit()`` (for example audit
    logging).  Graph ingestion therefore never owns its atomic lifecycle on
    that shared handle when the database is file-backed.  SQLite's write lock
    on this private connection serializes other providers/processes as well.

    Tiny standalone test providers may use ``:memory:`` databases.  Such a
    database cannot be reopened as an equivalent connection, so retain the
    legacy handle only for that non-persistent fallback.
    """
    shared = provider._connect()
    raw_path = getattr(provider, "db_path", "")
    path = str(raw_path or "")
    if not path:
        try:
            for row in shared.execute("PRAGMA database_list").fetchall():
                if str(row[1] or "") == "main":
                    path = str(row[2] or "")
                    break
        except sqlite3.Error:
            path = ""
    if not path or path == ":memory:" or path.startswith("file::memory:"):
        return shared, False

    writer = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    writer.row_factory = sqlite3.Row
    try:
        writer.execute("PRAGMA busy_timeout=30000")
        writer.execute("PRAGMA foreign_keys=ON")
        writer.execute("PRAGMA temp_store=MEMORY")
        writer.execute("PRAGMA synchronous=FULL")
        # Journal mode belongs to the database, so this read verifies the
        # private connection joins the provider's WAL/DELETE mode without
        # attempting a mode-changing PRAGMA while another writer is active.
        writer.execute("PRAGMA journal_mode").fetchone()
        # Migrations are intentionally completed before BEGIN IMMEDIATE.
        # They never share the lifecycle transaction being protected below.
        install_code_graph_schema(writer)
        if writer.in_transaction:
            writer.commit()
    except Exception:
        writer.close()
        raise
    return writer, True


def _open_graph_reader_connection(provider: Any) -> Tuple[sqlite3.Connection, bool]:
    """Open a private read handle without running DDL on a request path.

    Provider initialization and graph ingestion install the schema.  Read
    tools must not execute ``executescript`` on the provider's shared handle:
    Python's SQLite driver commits that connection's pending transaction before
    a script.  A private reader also keeps ordinary queries available against
    the last committed WAL snapshot while a graph writer is in progress.
    """
    shared = provider._connect()
    raw_path = getattr(provider, "db_path", "")
    path = str(raw_path or "")
    if not path:
        try:
            for row in shared.execute("PRAGMA database_list").fetchall():
                if str(row[1] or "") == "main":
                    path = str(row[2] or "")
                    break
        except sqlite3.Error:
            path = ""
    if not path or path == ":memory:" or path.startswith("file::memory:"):
        return shared, False
    reader = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    reader.row_factory = sqlite3.Row
    try:
        reader.execute("PRAGMA busy_timeout=30000")
        reader.execute("PRAGMA foreign_keys=ON")
        reader.execute("PRAGMA temp_store=MEMORY")
        reader.execute("PRAGMA query_only=ON")
        reader.execute("SELECT 1").fetchone()
    except Exception:
        reader.close()
        raise
    return reader, True


def _close_graph_writer_connection(conn: sqlite3.Connection, owned: bool) -> None:
    if not owned:
        return
    try:
        if conn.in_transaction:
            conn.rollback()
    finally:
        conn.close()


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


def _insert_graph_rows(
    conn: sqlite3.Connection,
    event: Dict[str, Any],
    repository_id: str,
    ts: int,
    *,
    graph_event_id: str = "",
    graph_payload_hash: str = "",
) -> Dict[str, int]:
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
               content_hash,embedding_claim_id,graph_event_id,graph_payload_hash,
               token_estimate,chunk_text,embedding_text,search_text,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (repository_id, chunk_id, path, str(raw.get("symbol_id") or "")[:512], qname,
             str(raw.get("chunk_kind") or "semantic")[:80], max(0, int(raw.get("start_line") or 0)),
             max(0, int(raw.get("end_line") or 0)), content_hash, embedding_claim_id,
             str(graph_event_id or ""), str(graph_payload_hash or "")[:80],
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


def _embed_graph_chunks(
    provider: Any,
    repository_id: str,
    commit_sha: str,
    event_id: str,
    file_filter: Sequence[str],
    *,
    unit_limit: Optional[int] = None,
    pending_only: bool = False,
    expected_event_id: str = "",
    expected_payload_hash: str = "",
) -> Dict[str, Any]:
    """Create/reuse claims only for chunks still owned by this snapshot.

    The graph state commits before embedding intentionally starts.  A newer
    snapshot can therefore replace a chunk while an older embedding task is
    waiting.  Each claim/link operation obtains its own private BEGIN IMMEDIATE
    transaction and rechecks the persisted snapshot marker under the write
    lock.  This prevents either a stale claim or a stale link from becoming
    visible for a newer chunk.
    """
    if not _env_bool("MEMORY_WIKI_CODE_GRAPH_EMBED", True):
        return {"enabled": False, "processed": 0, "created": 0, "reused": 0, "failed": 0}
    limit = (_env_int("MEMORY_WIKI_CODE_GRAPH_EMBED_MAX_UNITS", 2000, 0, 10000)
             if unit_limit is None else max(0, min(int(unit_limit), 10000)))
    if limit <= 0 or not hasattr(provider, "_code_claim_add"):
        return {"enabled": False, "processed": 0, "created": 0, "reused": 0, "failed": 0}
    conn, owns_conn = _open_graph_writer_connection(provider)
    where = ["repository_id=?"]
    params: List[Any] = [repository_id]
    if file_filter:
        placeholders = ",".join("?" for _ in file_filter)
        where.append(f"file_path IN ({placeholders})")
        params.extend(file_filter)
    if pending_only:
        where.append("embedding_claim_id=''")
    if expected_event_id:
        where.append("graph_event_id=?")
        params.append(expected_event_id)
    if expected_payload_hash:
        where.append("graph_payload_hash=?")
        params.append(expected_payload_hash)
    try:
        rows = conn.execute(
            "SELECT chunk_id,file_path,symbol_id,qualified_name,start_line,end_line,content_hash,embedding_claim_id,"
            "embedding_text,graph_event_id,graph_payload_hash "
            "FROM code_graph_chunks WHERE " + " AND ".join(where) +
            " ORDER BY CASE WHEN symbol_id<>'' THEN 0 ELSE 1 END, token_estimate DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
    finally:
        _close_graph_writer_connection(conn, owns_conn)

    stats = {
        "enabled": True, "processed": 0, "created": 0, "reused": 0,
        "failed": 0, "skipped_stale": 0, "errors": [],
    }
    post_commit_callbacks: List[Tuple[str, str, str]] = []
    for row in rows:
        candidate = dict(row)
        stats["processed"] += 1
        callbacks: List[Tuple[str, str, str]] = []
        label = candidate.get("qualified_name") or candidate.get("symbol_id") or "top-level"
        claim = (
            f"Code semantic chunk in repository {repository_id}. "
            f"File {candidate['file_path']} lines {candidate['start_line']}-{candidate['end_line']}; "
            f"symbol {label}.\n{candidate['embedding_text']}"
        )[:7800]
        snapshot_event_id = str(candidate.get("graph_event_id") or event_id or "manual-backfill")
        source_event_id = "kg:" + _sha(
            "\0".join((repository_id, snapshot_event_id, str(candidate["chunk_id"]), str(candidate["content_hash"])))
        )
        claim_args = {
            "claim": claim,
            "topic": "code-intelligence",
            "repository_id": repository_id,
            "commit_sha": commit_sha,
            "file_path": candidate["file_path"],
            "symbol_id": candidate["symbol_id"] or candidate["chunk_id"],
            "symbol_revision": candidate["content_hash"][:32],
            "content_hash": candidate["content_hash"],
            "claim_type": "code_graph_chunk",
            "confidence": 0.88,
            "salience": 0.78,
            "evidence": f"Code Shrinker graph event {snapshot_event_id}; chunk={candidate['chunk_id']}",
            "source_event_id": source_event_id,
            "producer": "mcp-code-shrinker-knowledge-graph",
            "phase_sep_version": "kg-v2",
        }
        conn = None
        owns_conn = False
        try:
            # _prepare_claim may quarantine a secret, queue review, or update
            # an index through the shared provider connection.  It must happen
            # before this worker takes its private SQLite write lock.  Taking
            # the provider lock first establishes the same lock order as every
            # ordinary claim write: provider lock -> SQLite writer.
            with _provider_claim_lock(provider):
                prepared_code_claim = provider._prepare_code_claim(
                    claim_args, trusted_opaque_graph_ids=True,
                )
                conn, owns_conn = _open_graph_writer_connection(provider)
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    predicates = [
                        "repository_id=?", "chunk_id=?", "content_hash=?",
                        "graph_event_id=?", "graph_payload_hash=?",
                    ]
                    predicate_params: List[Any] = [
                        repository_id, candidate["chunk_id"], candidate["content_hash"],
                        candidate.get("graph_event_id") or "", candidate.get("graph_payload_hash") or "",
                    ]
                    current = conn.execute(
                        "SELECT chunk_id,file_path,symbol_id,qualified_name,start_line,end_line,content_hash,"
                        "embedding_claim_id,embedding_text,graph_event_id,graph_payload_hash "
                        "FROM code_graph_chunks WHERE " + " AND ".join(predicates),
                        predicate_params,
                    ).fetchone()
                    if current is None:
                        conn.rollback()
                        stats["skipped_stale"] += 1
                        continue
                    item = dict(current)
                    # A plan prepared before the writer lock is valid only for
                    # precisely the snapshot row it was derived from.
                    if any(item.get(key) != candidate.get(key) for key in (
                        "file_path", "symbol_id", "qualified_name", "start_line", "end_line", "embedding_text",
                    )):
                        conn.rollback()
                        stats["skipped_stale"] += 1
                        continue
                    current_repo = conn.execute(
                        "SELECT commit_sha FROM code_graph_repositories WHERE repository_id=?",
                        (repository_id,),
                    ).fetchone()
                    current_commit_sha = str(current_repo[0] or "") if current_repo else ""
                    if current_commit_sha != str(commit_sha or ""):
                        conn.rollback()
                        stats["skipped_stale"] += 1
                        continue
                    existing = ""
                    if item.get("embedding_claim_id"):
                        found = conn.execute(
                            "SELECT c.id FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id "
                            "WHERE c.id=? AND c.status IN ('active','current') AND m.repository_id=? "
                            "AND m.file_path=? AND m.symbol_id=? AND m.content_hash=? "
                            "AND m.claim_type='code_graph_chunk'",
                            (item["embedding_claim_id"], repository_id, item["file_path"],
                             item["symbol_id"] or item["chunk_id"], item["content_hash"]),
                        ).fetchone()
                        existing = str(found[0]) if found else ""
                    if not existing:
                        found = conn.execute(
                            "SELECT c.id FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id "
                            "WHERE c.status IN ('active','current') AND m.repository_id=? AND m.file_path=? "
                            "AND m.symbol_id=? AND m.content_hash=? AND m.claim_type='code_graph_chunk' "
                            "ORDER BY c.updated_at DESC LIMIT 1",
                            (repository_id, item["file_path"], item["symbol_id"] or item["chunk_id"], item["content_hash"]),
                        ).fetchone()
                        existing = str(found[0]) if found else ""
                    if existing:
                        linked = conn.execute(
                            "UPDATE code_graph_chunks SET embedding_claim_id=? WHERE " + " AND ".join(predicates),
                            [existing, *predicate_params],
                        )
                        if linked.rowcount != 1:
                            raise RuntimeError("snapshot-bound embedding link was superseded")
                        conn.commit()
                        stats["reused"] += 1
                        continue

                    result = provider._code_claim_add(
                        claim_args,
                        conn=conn,
                        after_commit_callbacks=callbacks,
                        _prepared_code_claim=prepared_code_claim,
                        trusted_opaque_graph_ids=True,
                    )
                    claim_id = str(result.get("id") or "")
                    if not claim_id:
                        conn.rollback()
                        stats["failed"] += 1
                        continue
                    active = conn.execute(
                        "SELECT 1 FROM claims WHERE id=? AND status IN ('active','current')",
                        (claim_id,),
                    ).fetchone()
                    if active is None:
                        raise RuntimeError("embedding claim is not active")
                    linked = conn.execute(
                        "UPDATE code_graph_chunks SET embedding_claim_id=? WHERE " + " AND ".join(predicates),
                        [claim_id, *predicate_params],
                    )
                    if linked.rowcount != 1:
                        raise RuntimeError("snapshot-bound embedding link was superseded")
                    conn.commit()
                    post_commit_callbacks.extend(callbacks)
                    stats["created"] += 1
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise
                finally:
                    _close_graph_writer_connection(conn, owns_conn)
                    conn = None
        except Exception as exc:  # one malformed unit must not abort the snapshot
            if conn is not None and conn.in_transaction:
                conn.rollback()
            stats["failed"] += 1
            if len(stats["errors"]) < 12:
                stats["errors"].append(f"chunk failure: {type(exc).__name__}")
        finally:
            if conn is not None:
                _close_graph_writer_connection(conn, owns_conn)

    for claim_id, topic, claim in post_commit_callbacks:
        try:
            provider._after_claim_commit(claim_id, topic, claim)
        except Exception as exc:
            if len(stats["errors"]) < 12:
                stats["errors"].append(f"post_commit failure: {type(exc).__name__}")
    return stats


def ingest_code_graph_event(
    provider: Any,
    event: Dict[str, Any],
    *,
    trusted_opaque_ids: bool = False,
    recovery_payload_hash: str = "",
    recovery_payload_hash_version: int = 0,
    recovery_artifact_reference: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply a Code Shrinker full or delta graph event idempotently.

    Only replay of a previously verified recovery artifact may retain an
    existing opaque spelling.  Live producer input is always re-evaluated so
    a caller cannot forge provenance by choosing the opaque-ID format.
    """
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
    raw_repository_id = str(event.get("repository_id") or "").strip()
    raw_event_id = str(event.get("event_id") or "").strip()
    if not raw_repository_id or not raw_event_id:
        raise ValueError("repository_id and event_id are required")
    snapshot_mode = str(event.get("snapshot_mode") or "full").lower()
    if snapshot_mode not in {"full", "delta"}:
        raise ValueError("snapshot_mode must be full or delta")
    # Revision invalidation is part of the same lifecycle boundary as replacing
    # graph rows.  Validate it before touching either representation: otherwise
    # a malformed producer event could be accepted, delete graph rows, and leave
    # the associated semantic claims active.
    commit_sha = str(event.get("commit_sha") or "").strip().lower()
    if commit_sha and not re.fullmatch(r"[0-9a-f]{7,64}", commit_sha):
        raise ValueError("commit_sha must be a 7-64 character hexadecimal Git object ID")
    # Keep the pre-normalization digest as a legacy compatibility candidate.
    # v1 producers persisted raw event bytes/dicts in a few releases, while v2
    # binds the canonical normalized payload below.
    legacy_raw_payload_hash = _sha(_json(event))
    # Do this before opening a graph transaction or invalidating claims. The
    # writer otherwise converts several producer values only after a full
    # snapshot has already made implicit deletions effective.
    normalized_raw_event = _normalize_code_graph_event(event)
    # ``snapshot_hash`` is producer metadata, not a proof that two opaque
    # event bodies are identical.  Bind the deduplication key to the complete
    # normalized *raw* payload so an attacker cannot reuse an event id and a
    # claimed snapshot hash while changing a secret-only graph revision.  The
    # digest is opaque; the redacted copy below is the only payload persisted.
    calculated_payload_hash = _sha(_json(normalized_raw_event))
    supplied_snapshot_hash = str(normalized_raw_event.get("snapshot_hash") or "")
    raw_producer_snapshot_hash = supplied_snapshot_hash or calculated_payload_hash
    candidate_recovery_hash = str(recovery_payload_hash or "").strip()
    try:
        candidate_recovery_version = int(recovery_payload_hash_version or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid recovery code graph payload binding version") from exc
    if candidate_recovery_hash:
        verify_recovery_binding = getattr(provider, "_verify_code_graph_recovery_payload_binding", None)
        if not callable(verify_recovery_binding) or not bool(verify_recovery_binding(
            event,
            candidate_recovery_hash,
            candidate_recovery_version,
            recovery_artifact_reference,
        )):
            raise ValueError("recovery code graph payload binding requires a verified artifact")
        if candidate_recovery_version not in {3, 4}:
            raise ValueError("unsupported recovery code graph payload binding")
        if candidate_recovery_version >= 3:
            candidate_recovery_hash = candidate_recovery_hash.lower()
            if not re.fullmatch(r"[0-9a-f]{64}", candidate_recovery_hash):
                raise ValueError("invalid recovery code graph payload digest")
        payload_hash = candidate_recovery_hash
        payload_hash_version = candidate_recovery_version
    else:
        if candidate_recovery_version:
            raise ValueError("recovery code graph payload binding is incomplete")
        payload_hash = calculated_payload_hash
        payload_hash_version = 3
    event, _redaction_changed = _sanitize_graph_event_for_storage(
        normalized_raw_event,
        _provider_graph_redactor(provider),
        preserve_opaque_ids=trusted_opaque_ids,
    )
    # The raw identifiers above are used only while deriving the opaque event
    # fingerprint.  Every SQLite key, result and downstream claim now uses the
    # safe identity from the persisted event; otherwise a secret embedded in a
    # repository path or producer event ID would bypass text redaction.
    repository_id = str(event.get("repository_id") or "").strip()
    event_id = str(event.get("event_id") or "").strip()
    if not repository_id or not event_id:
        raise ValueError("repository_id and event_id are required")
    producer_snapshot_hash = str(event.get("snapshot_hash") or payload_hash)

    # This section intentionally contains only local SQLite work.  Keeping
    # embedding calls outside it avoids holding the writer transaction across
    # model/network work, while the event record makes the graph mutation
    # exactly-once before deferred embeddings begin.
    with _GRAPH_INGEST_LOCK:
        conn, owns_conn = _open_graph_writer_connection(provider)
        try:
            if conn.in_transaction:
                raise RuntimeError("code graph ingestion requires an idle SQLite connection")
            conn.execute("BEGIN IMMEDIATE")
            # ``event`` was structurally redacted before the transaction.  A
            # connection-aware pass now resolves its keys to v2 (or preserves
            # one exact registered v2 replay key) and records only values we
            # deterministically minted in this atomic write.
            event, minted_opaque_ids = _canonicalize_sanitized_graph_event_identities(
                event, conn, trusted_opaque_ids=trusted_opaque_ids,
            )
            repository_id = str(event.get("repository_id") or "").strip()
            event_id = str(event.get("event_id") or "").strip()
            if not repository_id or not event_id:
                raise ValueError("repository_id and event_id are required")
            _register_opaque_graph_id_provenance(
                conn,
                sorted(minted_opaque_ids),
                version=(
                    _GRAPH_IDENTITY_PROVENANCE_VERSION
                    if _graph_identity_migration_complete(conn) else 1
                ),
            )
            prior = conn.execute(
                "SELECT payload_hash,payload_hash_version,status,stats_json "
                "FROM code_graph_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if prior:
                prior_hash = str(prior[0] or "")
                prior_version = int(prior[1] or 1)
                if str(prior[2] or "") != "completed":
                    raise RuntimeError("stored code graph event is not completed")
                # Some v1 writers stored a hash of the complete raw request,
                # which can still be verified exactly.  They must not be
                # confused with v1 rows that stored only a producer-controlled
                # snapshot hash: accepting the latter would let a changed body
                # silently reuse an event ID.
                legacy_match = prior_version < 2 and prior_hash == legacy_raw_payload_hash
                if prior_hash != payload_hash and not legacy_match:
                    if prior_version == 4:
                        raise ValueError(
                            "legacy recovery artifact lacks the original raw payload digest; "
                            "send a fresh snapshot with a new event_id"
                        )
                    if prior_version < 2 and prior_hash == raw_producer_snapshot_hash:
                        raise ValueError(
                            "legacy code graph event lacks an exact payload digest; "
                            "send a fresh snapshot with a new event_id"
                        )
                    raise ValueError("event_id reuse with different code graph payload")
                previous = json.loads(prior[3] or "{}")
                if not isinstance(previous, dict):
                    raise RuntimeError("stored code graph event metadata is invalid")
                conn.rollback()
                return {"status": "deduplicated", "deduplicated": True, **previous}

            ts = _now()
            # Reserve the event before lifecycle mutations.  The reservation,
            # claim invalidation, graph rows and final metadata all commit or
            # roll back together under this BEGIN IMMEDIATE boundary.
            conn.execute(
                """INSERT INTO code_graph_events(
                       event_id,repository_id,payload_hash,payload_hash_version,snapshot_mode,status,stats_json,created_at
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (event_id, repository_id, payload_hash, payload_hash_version, snapshot_mode, "processing", "{}", ts),
            )

            new_hash_by_path: Dict[str, str] = {}
            for item in event.get("files") or []:
                path = str(item["file_path"])
                file_hash = str(item.get("file_hash") or "").strip().lower().removeprefix("sha256:")
                new_hash_by_path[path] = file_hash if re.fullmatch(r"[0-9a-f]{64}", file_hash) else ""
            changed_files = sorted(new_hash_by_path)
            deleted_files = list(event.get("deleted_files") or [])
            previous_file_hashes = {
                str(row[0]): str(row[1] or "").lower().removeprefix("sha256:")
                for row in conn.execute(
                    "SELECT file_path,file_hash FROM code_graph_files WHERE repository_id=?",
                    (repository_id,),
                ).fetchall()
            }
            implicit_deleted = set()
            if snapshot_mode == "full":
                # Legacy graph snapshots could contain chunks/symbols/lines
                # without a file row.  Claims may also predate graph indexing.
                # A full snapshot is authoritative, so derive omissions from
                # every file-bearing representation, not files alone.
                prior_paths = set(previous_file_hashes)
                for table in ("code_graph_symbols", "code_graph_chunks", "code_graph_lines"):
                    prior_paths.update(
                        str(row[0]) for row in conn.execute(
                            f"SELECT DISTINCT file_path FROM {table} WHERE repository_id=? AND file_path<>''",
                            (repository_id,),
                        ).fetchall()
                    )
                try:
                    prior_paths.update(
                        str(row[0]) for row in conn.execute(
                            "SELECT DISTINCT file_path FROM code_claim_metadata "
                            "WHERE repository_id=? AND file_path<>''",
                            (repository_id,),
                        ).fetchall()
                    )
                except sqlite3.OperationalError:
                    # Standalone graph-only databases intentionally omit the
                    # provider's semantic-claim tables.
                    pass
                implicit_deleted = prior_paths - set(changed_files)
            touched = sorted(set(changed_files + deleted_files) | implicit_deleted)

            # Do not archive semantic chunk claims for an unchanged file: a
            # chunk's content hash differs from the file hash by design.  New
            # or changed file hashes, explicit deletes and full-snapshot
            # omissions still invalidate their old code claims atomically.
            invalidation_paths = set(deleted_files) | implicit_deleted
            for path in changed_files:
                if previous_file_hashes.get(path) != new_hash_by_path.get(path, ""):
                    invalidation_paths.add(path)

            # The actual provider accepts ``conn`` so claim status, mutation
            # ledger, audit trail, outbox, graph rows and event reservation are
            # one SQLite transaction.  Do not fall back to a separate commit:
            # that was the divergence boundary this routine is closing.
            invalidated = 0
            invalidate_revision = getattr(provider, "_invalidate_revision", None)
            if callable(invalidate_revision):
                for path in sorted(invalidation_paths):
                    invalidate_result = invalidate_revision({
                        "repository_id": repository_id,
                        "file_path": path,
                        "new_commit_sha": commit_sha,
                        "new_content_hash": new_hash_by_path.get(path, ""),
                    }, conn=conn, trusted_opaque_graph_ids=True)
                    invalidated += int(invalidate_result.get("invalidated") or 0)

            if snapshot_mode == "full":
                _delete_fts_for_files(conn, repository_id, [])
                for table in ("code_graph_edges", "code_graph_lines", "code_graph_chunks", "code_graph_symbols", "code_graph_files"):
                    conn.execute(f"DELETE FROM {table} WHERE repository_id=?", (repository_id,))
            else:
                _delete_files(conn, repository_id, touched)
                if bool(event.get("edges_full", True)):
                    conn.execute("DELETE FROM code_graph_edges WHERE repository_id=?", (repository_id,))
            counts = _insert_graph_rows(
                conn, event, repository_id, ts,
                graph_event_id=event_id, graph_payload_hash=payload_hash,
            )
            repo_stats = event.get("stats") if isinstance(event.get("stats"), dict) else counts
            durable_result = {
                "repository_id": repository_id,
                "event_id": event_id,
                "snapshot_mode": snapshot_mode,
                "counts": counts,
                "deleted_files": len(deleted_files),
                "invalidated_claims": invalidated,
                "embedding": {"status": "pending"},
                "snapshot_hash": producer_snapshot_hash,
            }
            conn.execute(
                """INSERT INTO code_graph_repositories(repository_id,root,commit_sha,graph_revision,snapshot_hash,generated_at,updated_at,stats_json)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(repository_id) DO UPDATE SET root=excluded.root,commit_sha=excluded.commit_sha,
                   graph_revision=excluded.graph_revision,snapshot_hash=excluded.snapshot_hash,
                   generated_at=excluded.generated_at,updated_at=excluded.updated_at,stats_json=excluded.stats_json""",
                (repository_id, str(event.get("root") or "")[:2000], commit_sha,
                 str(event.get("graph_revision") or payload_hash[:20])[:160], producer_snapshot_hash[:128],
                 int(event.get("generated_at") or ts), ts, _json(repo_stats)[:100000]),
            )
            finalized = conn.execute(
                """UPDATE code_graph_events
                   SET status='completed',stats_json=?
                   WHERE event_id=? AND payload_hash=? AND payload_hash_version=?""",
                (_json(durable_result), event_id, payload_hash, payload_hash_version),
            )
            if finalized.rowcount != 1:
                raise RuntimeError("code graph event reservation was not finalized")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            _close_graph_writer_connection(conn, owns_conn)

    try:
        embed_stats = _embed_graph_chunks(
            provider, repository_id, commit_sha, event_id,
            changed_files if snapshot_mode == "delta" else [], pending_only=True,
            expected_event_id=event_id, expected_payload_hash=payload_hash,
        )
    except Exception as exc:
        # Graph state is already durable and can be retried through
        # embed_pending_chunks.  Preserve that success rather than making a
        # network/model issue appear to roll back a committed snapshot.
        embed_stats = {"enabled": True, "processed": 0, "created": 0, "reused": 0, "failed": 1,
                       "errors": [f"deferred embedding: {type(exc).__name__}"]}

    result = {**durable_result, "embedding": embed_stats}
    # Best effort only: failure to refresh optional embedding telemetry must
    # not alter the atomic graph/event result above.
    with _GRAPH_INGEST_LOCK:
        conn, owns_conn = _open_graph_writer_connection(provider)
        try:
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """UPDATE code_graph_events SET stats_json=?
                       WHERE event_id=? AND payload_hash=? AND payload_hash_version=?""",
                    (_json(result), event_id, payload_hash, payload_hash_version),
                )
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
        finally:
            _close_graph_writer_connection(conn, owns_conn)
    return {"status": "completed", "deduplicated": False, **result}


def embed_pending_chunks(
    provider: Any, args: Dict[str, Any], *, trusted_opaque_ids: bool = False,
) -> Dict[str, Any]:
    """Create/reuse semantic claims for graph chunks left pending by bounded ingestion."""
    limit = max(1, min(int(args.get("limit") or 1000), 10000))
    conn, owns_conn = _open_graph_writer_connection(provider)
    try:
        repository_id = _graph_lookup_identity(
            provider,
            str(args.get("repository_id") or "").strip(),
            trusted_opaque_id=trusted_opaque_ids,
            conn=conn,
        )
        if not repository_id:
            raise ValueError("repository_id is required")
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
    finally:
        _close_graph_writer_connection(conn, owns_conn)
    stats = _embed_graph_chunks(
        provider, repository_id, str(repo[0] or ""),
        f"manual-backfill:{repository_id}:{str(repo[1] or '')[:20]}", [],
        unit_limit=limit, pending_only=True,
    )
    conn, owns_conn = _open_graph_writer_connection(provider)
    try:
        after = conn.execute(
            "SELECT COUNT(*) FROM code_graph_chunks WHERE repository_id=? AND embedding_claim_id=''",
            (repository_id,),
        ).fetchone()
    finally:
        _close_graph_writer_connection(conn, owns_conn)
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
    """Query through a private connection so read-time schema checks cannot commit a writer."""
    conn, owns_conn = _open_graph_reader_connection(provider)
    try:
        return _query_code_graph_on_connection(provider, args, conn)
    finally:
        _close_graph_writer_connection(conn, owns_conn)


def _query_code_graph_on_connection(
    provider: Any, args: Dict[str, Any], conn: sqlite3.Connection
) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    repository_id = _graph_lookup_identity(
        provider, str(args.get("repository_id") or "").strip(), conn=conn,
    )
    limit = max(1, min(int(args.get("limit") or 12), 50))
    lexical_limit = max(20, min(int(args.get("candidate_limit") or limit * 8), 300))
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
                                         session_id=str(args.get("session_id") or ""),
                                         record_retrieval=False, conn=conn)
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
        semantic_error = type(exc).__name__
    else:
        semantic_error = ""

    # Exact file/symbol/path boosts are deterministic and intentionally small.
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
                # Never send the stored full chunk (including a legacy row) to
                # an external reranker.  The bounded navigation excerpt passes
                # through the same complete redactor as public graph output.
                "claim": _redact_graph_text(
                    candidate.get("excerpt") or "", 2400, _provider_graph_redactor(provider)
                ),
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
                rerank_error = type(exc).__name__

    return {
        "repository_id": repository_id,
        "query": query,
        "results": [_public_graph_candidate(provider, item) for item in candidates[:limit]],
        "retrieval": {
            "fts_symbols": len(symbol_rows), "fts_chunks": len(chunk_rows), "fts_lines": len(line_rows),
            "semantic_chunks": semantic_count, "semantic_error": semantic_error,
            "fusion": "weighted_rrf_k60", "reranked": reranked, "rerank_error": rerank_error,
        },
    }


def code_line_context(provider: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    conn, owns_conn = _open_graph_reader_connection(provider)
    try:
        return _code_line_context_on_connection(provider, args, conn)
    finally:
        _close_graph_writer_connection(conn, owns_conn)


def _code_line_context_on_connection(
    provider: Any, args: Dict[str, Any], conn: sqlite3.Connection
) -> Dict[str, Any]:
    repository_id = _graph_lookup_identity(
        provider, str(args.get("repository_id") or "").strip(), conn=conn,
    )
    line_id = _graph_lookup_identity(
        provider, str(args.get("line_id") or "").strip(), conn=conn,
    )
    radius = max(0, min(int(args["radius"] if "radius" in args else 12), 100))
    if not repository_id:
        raise ValueError("repository_id is required")
    if line_id:
        target = conn.execute(
            "SELECT file_path,line_no FROM code_graph_lines WHERE repository_id=? AND line_id=? LIMIT 1",
            (repository_id, line_id),
        ).fetchone()
        if not target:
            raise ValueError(f"unknown line_id for repository: {line_id}")
        file_path, line_no = str(target[0]), int(target[1])
    else:
        file_path = _graph_lookup_identity(
            provider, _canonical_path(args.get("file_path") or ""), conn=conn,
        )
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
            "range": [max(1, line_no - radius), line_no + radius],
            "lines": _safe_graph_output(provider, rows), "symbols": _safe_graph_output(provider, symbols),
            "line_id": line_id or next((str(r.get("line_id") or "") for r in rows if int(r.get("line_no") or 0) == line_no), ""),
            "note": "Stored lines are redacted navigation copies; use Code Shrinker file.lines or symbol.source for exact source."}


def code_graph_neighbors(provider: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    conn, owns_conn = _open_graph_reader_connection(provider)
    try:
        return _code_graph_neighbors_on_connection(provider, args, conn)
    finally:
        _close_graph_writer_connection(conn, owns_conn)


def _code_graph_neighbors_on_connection(
    provider: Any, args: Dict[str, Any], conn: sqlite3.Connection
) -> Dict[str, Any]:
    repository_id = _graph_lookup_identity(
        provider, str(args.get("repository_id") or "").strip(), conn=conn,
    )
    node_id = _graph_lookup_identity(
        provider, str(args.get("node_id") or args.get("symbol_id") or "").strip(), conn=conn,
    )
    hops = max(1, min(int(args.get("hops") or 1), 3))
    limit = max(1, min(int(args.get("limit") or 50), 500))
    if not repository_id or not node_id:
        raise ValueError("repository_id and node_id are required")
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
    return {"repository_id": repository_id, "node_id": node_id, "hops": hops,
            "nodes": _safe_graph_output(provider, nodes), "edges": _safe_graph_output(provider, edges[:limit])}


def code_graph_status(provider: Any, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    conn, owns_conn = _open_graph_reader_connection(provider)
    try:
        return _code_graph_status_on_connection(provider, args, conn)
    finally:
        _close_graph_writer_connection(conn, owns_conn)


def _code_graph_status_on_connection(
    provider: Any, args: Optional[Dict[str, Any]], conn: sqlite3.Connection
) -> Dict[str, Any]:
    args = args or {}
    repository_id = _graph_lookup_identity(
        provider, str(args.get("repository_id") or "").strip(), conn=conn,
    )
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
        "repositories": _safe_graph_output(provider, repos),
        "totals": totals,
        "embedding_enabled": _env_bool("MEMORY_WIKI_CODE_GRAPH_EMBED", True),
        "rerank_enabled": _env_bool("MEMORY_WIKI_CODE_GRAPH_RERANK", True),
    }


def _scrub_graph_identity_columns(
    provider: Any, conn: sqlite3.Connection, *, apply: bool, limit: int,
) -> Tuple[int, int, int, int, set[str]]:
    """Migrate legacy graph keys that predate ingress identity redaction.

    Key columns cannot be passed through a generic marker: references between
    files, symbols, chunks, lines, edges, events and code-claim metadata must
    retain their equality relationship.  The deterministic opaque transform
    makes the per-table updates safe to run in one caller-owned transaction.
    """
    targets = (
        ("code_graph_repositories", ("repository_id",), ""),
        ("code_graph_files", ("repository_id", "file_path"), ""),
        ("code_graph_symbols", ("repository_id", "symbol_id", "file_path"), ""),
        ("code_graph_chunks", ("repository_id", "chunk_id", "file_path", "symbol_id", "graph_event_id"), ""),
        ("code_graph_lines", ("repository_id", "file_path", "line_id", "symbol_id", "chunk_id"), ""),
        ("code_graph_edges", ("repository_id", "edge_id", "source_id", "target_id", "source_file", "target_file"), ""),
        ("code_graph_events", ("event_id", "repository_id"), ""),
        # Graph embeddings link through this provider table; preserve that
        # relationship when cleaning a database written by an older release.
        ("code_claim_metadata", ("repository_id", "file_path", "symbol_id"), ""),
        # Patch outcomes share the same graph namespace and are later used by
        # invalidation/replay, so leaving their legacy v1 keys behind would
        # fork a graph immediately after a successful scrub.
        ("patch_outcomes", ("repository_id", "patch_id", "source_event_id"), ""),
        # This table is written only by the code-claim/patch exactly-once
        # paths in this provider. Its event_id is their collision guard, so a
        # stale v1 spelling would let a post-migration raw retry fork it.
        ("integration_events", ("event_id",), ""),
    )
    changed_rows = changed_fields = scanned_rows = batches = 0
    migrated_opaque_ids: set[str] = set()
    batch_size = max(1, min(int(limit or 5000), 100_000))
    redactor = _provider_graph_redactor(provider)
    for table, columns, predicate in targets:
        # ``rowid`` is stable while an identity update changes a primary key.
        # Advance a cursor through every batch instead of repeatedly applying
        # ``LIMIT 5000`` to the first rows forever; legacy graph stores can be
        # much larger than one maintenance batch.
        last_rowid = 0
        while True:
            try:
                select_columns = ["rowid", *columns]
                if table == "integration_events":
                    select_columns.extend(("producer", "payload_hash"))
                where = "rowid>?"
                if predicate:
                    where += " AND " + predicate
                rows = conn.execute(
                    f"SELECT {','.join(select_columns)} FROM {table} "
                    f"WHERE {where} ORDER BY rowid LIMIT ?",
                    (last_rowid, batch_size),
                ).fetchall()
            except sqlite3.OperationalError:
                break
            if not rows:
                break
            batches += 1
            scanned_rows += len(rows)
            last_rowid = int(rows[-1]["rowid"])
            for row in rows:
                changes: Dict[str, str] = {}
                for column in columns:
                    original = str(row[column] or "")
                    safe = _migrate_stored_graph_identity(
                        original, redactor=redactor, conn=conn,
                    )
                    if safe != original:
                        if apply and table == "integration_events" and column == "event_id":
                            collision = conn.execute(
                                "SELECT 1 FROM integration_events "
                                "WHERE producer=? AND event_id=? AND rowid<>? LIMIT 1",
                                (str(row["producer"] or ""), safe, row["rowid"]),
                            ).fetchone()
                            if collision is not None:
                                # A collision would silently weaken the source
                                # event reuse guard. Stop the transaction rather
                                # than discard either claim's provenance.
                                raise RuntimeError("code graph integration-event identity migration collision")
                        changes[column] = safe
                        if _OPAQUE_GRAPH_ID_RE.fullmatch(safe):
                            migrated_opaque_ids.add(safe)
                if not changes:
                    continue
                changed_rows += 1
                changed_fields += len(changes)
                if apply:
                    assignments = ",".join(f"{column}=?" for column in changes)
                    conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid=?",
                        [*changes.values(), row["rowid"]],
                    )
    return changed_rows, changed_fields, scanned_rows, batches, migrated_opaque_ids


def scrub_code_graph_storage(
    provider: Any, conn: sqlite3.Connection, *, apply: bool = False, limit: int = 5000,
) -> Dict[str, Any]:
    """Redact legacy graph text and rebuild graph FTS from the safe rows.

    New ingestion never writes raw source, but existing databases can predate
    that invariant.  This maintenance helper deliberately works on the caller's
    transaction and returns counts only; it never surfaces the original text.
    """
    batch_size = max(1, min(int(limit or 5000), 100_000))
    targets = (
        ("code_graph_repositories", ("root", "graph_revision", "snapshot_hash", "stats_json")),
        ("code_graph_files", ("file_hash", "imports_json")),
        ("code_graph_symbols", ("symbol_revision", "qualified_name", "short_name", "signature", "contract_json", "search_text")),
        ("code_graph_chunks", ("qualified_name", "chunk_text", "embedding_text", "search_text")),
        ("code_graph_lines", ("anchor_hash", "line_text", "flags")),
        ("code_graph_edges", ("evidence",)),
        ("code_graph_events", ("stats_json",)),
        (
            "patch_outcomes",
            (
                "outcome", "rollback_steps", "validation_report_json",
                "changed_files_json", "changed_symbols_json",
            ),
        ),
    )
    changed_rows, changed_fields, scanned_rows, batches, migrated_opaque_ids = _scrub_graph_identity_columns(
        provider, conn, apply=apply, limit=batch_size,
    )
    for table, fields in targets:
        last_rowid = 0
        while True:
            try:
                rows = conn.execute(
                    f"SELECT rowid,{','.join(fields)} FROM {table} "
                    "WHERE rowid>? ORDER BY rowid LIMIT ?",
                    (last_rowid, batch_size),
                ).fetchall()
            except sqlite3.OperationalError:
                break
            if not rows:
                break
            batches += 1
            scanned_rows += len(rows)
            last_rowid = int(rows[-1]["rowid"])
            for row in rows:
                changes: Dict[str, str] = {}
                def identity_mapper(value: Any) -> str:
                    return _migrate_stored_graph_identity(
                        value,
                        redactor=_provider_graph_redactor(provider),
                        conn=conn,
                    )
                for field in fields:
                    original = str(row[field] or "")
                    if table == "patch_outcomes":
                        safe = _scrub_patch_outcome_storage_value(
                            provider,
                            field,
                            original,
                            redactor=_provider_graph_redactor(provider),
                            identity_mapper=identity_mapper,
                        )
                    else:
                        safe = _redact_graph_storage_value(
                            original,
                            _provider_graph_redactor(provider),
                            identity_mapper=identity_mapper,
                            key=(field[:-5] if field.endswith("_json") else field),
                        )
                    if safe != original:
                        changes[field] = safe
                        try:
                            parsed = json.loads(safe)
                        except (TypeError, ValueError):
                            parsed = None
                        if parsed is not None:
                            def collect(value: Any, key: str = "") -> None:
                                if isinstance(value, dict):
                                    for child_key, child_value in value.items():
                                        collect(child_value, str(child_key))
                                elif isinstance(value, list):
                                    for child in value:
                                        collect(child, key)
                                elif (
                                    str(key or "").lower() in _GRAPH_IDENTITY_FIELDS
                                    and _OPAQUE_GRAPH_ID_RE.fullmatch(str(value or "").strip())
                                ):
                                    migrated_opaque_ids.add(str(value).strip())
                            collect(
                                parsed,
                                field[:-5] if field.endswith("_json") else field,
                            )
                if not changes:
                    continue
                changed_rows += 1
                changed_fields += len(changes)
                if apply:
                    assignments = ",".join(f"{field}=?" for field in changes)
                    conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid=?",
                        [*changes.values(), row["rowid"]],
                    )
    if apply:
        # All v1 and unverified opaque spellings have now been deterministically
        # re-keyed in every graph-bearing column.  Record their exact v2 IDs
        # and only then flip the durable lookup-mode marker, so an interrupted
        # caller cannot leave raw-source writes pointing at a half-migration.
        _register_opaque_graph_id_provenance(
            conn,
            sorted(migrated_opaque_ids),
            version=_GRAPH_IDENTITY_PROVENANCE_VERSION,
        )
        try:
            conn.execute(
                f"DELETE FROM {_GRAPH_IDENTITY_PROVENANCE_TABLE} "
                "WHERE provenance_version<?",
                (_GRAPH_IDENTITY_PROVENANCE_VERSION,),
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {_GRAPH_IDENTITY_MIGRATIONS_TABLE}("
                "migration_version,completed_at) VALUES(?,?)",
                (_GRAPH_IDENTITY_MIGRATION_VERSION, _now()),
            )
        except sqlite3.Error:
            # Missing registry schema must never enable v2 lookup aliases.
            raise RuntimeError("code graph opaque-ID provenance migration is unavailable")
        try:
            conn.execute("DELETE FROM code_graph_symbols_fts")
            conn.execute(
                "INSERT INTO code_graph_symbols_fts(repository_id,symbol_id,file_path,qualified_name,signature,search_text) "
                "SELECT repository_id,symbol_id,file_path,qualified_name,signature,search_text FROM code_graph_symbols"
            )
            conn.execute("DELETE FROM code_graph_chunks_fts")
            conn.execute(
                "INSERT INTO code_graph_chunks_fts(repository_id,chunk_id,file_path,symbol_id,qualified_name,search_text,chunk_text) "
                "SELECT repository_id,chunk_id,file_path,symbol_id,qualified_name,search_text,chunk_text FROM code_graph_chunks"
            )
            conn.execute("DELETE FROM code_graph_lines_fts")
            conn.execute(
                "INSERT INTO code_graph_lines_fts(repository_id,file_path,line_no,line_text) "
                "SELECT repository_id,file_path,line_no,line_text FROM code_graph_lines"
            )
        except sqlite3.OperationalError:
            pass
    return {
        "rows": changed_rows,
        "fields": changed_fields,
        "scanned_rows": scanned_rows,
        "batches": batches,
        "complete": True,
        "batch_size": batch_size,
    }


def maybe_prefetch_code_context(provider: Any, query: str, max_chars: int = 8000) -> str:
    if not _env_bool("MEMORY_WIKI_CODE_GRAPH_PREFETCH", True) or not _CODE_HINT.search(str(query or "")):
        return ""
    conn, owns_conn = _open_graph_reader_connection(provider)
    try:
        repos = [str(r[0]) for r in conn.execute(
            "SELECT repository_id FROM code_graph_repositories ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()]
    finally:
        _close_graph_writer_connection(conn, owns_conn)
    if not repos:
        return ""
    inferred = ""
    q = str(query or "")
    for repo in repos:
        if repo.lower() in q.lower() or repo.rsplit("/", 1)[-1].lower() in q.lower():
            inferred = repo; break
    if not inferred and len(repos) == 1:
        inferred = repos[0]
    # Never auto-inject excerpts from every repository when the prompt cannot
    # bind the request to one repository.
    if not inferred:
        return ""
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
    "embed_pending_chunks", "maybe_prefetch_code_context", "scrub_code_graph_storage",
]
