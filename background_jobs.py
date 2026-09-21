"""Durable, content-free jobs for optional memory consolidation and extraction.

Only opaque row IDs and a database rowid high watermark enter payload_json.
The event and claim tables remain authoritative.  In particular, a deleted
source cannot be reconstructed from this queue or retried from old text.
"""
from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping


JOB_TYPES = frozenset({
    "consolidate_observations", "extract_session_events", "enrich_claim_graph",
})
_EVENT_ID = re.compile(r"evt_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"c_[A-Za-z0-9_.:-]{1,96}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OWNER_HASH = re.compile(r"[0-9a-f]{32}\Z")
_ERROR_CODES = frozenset({
    "dependency", "provider", "network", "database", "timeout", "unknown",
    "budget_deferred", "source_missing", "owner_mismatch", "invalid_source",
})


def enabled() -> bool:
    return os.environ.get("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _limit(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8", "ignore")).hexdigest()


def profile_key(provider: Any) -> str:
    return _digest(str(Path(provider.home).resolve()).casefold())


def owner_key(provider: Any) -> str:
    return _digest(str(provider.bot_id or ""))


def partition_key(event: Mapping[str, Any]) -> str:
    return _digest(
        str(event["owner_bot_id"]), str(event["owner_chat_hash"]),
        str(event["owner_session_hash"]), str(event["visibility_scope"]),
        str(event["project_id"]),
    )


def validate_payload(job_type: str, payload: Mapping[str, Any]) -> str:
    """Canonical JSON with an exact allowlist; never persist free-form values."""
    if job_type not in JOB_TYPES or not isinstance(payload, dict):
        raise ValueError("invalid memory job type or payload")
    if job_type == "enrich_claim_graph":
        valid = set(payload) == {"claim_id"} and isinstance(payload.get("claim_id"), str) \
            and bool(_CLAIM_ID.fullmatch(payload["claim_id"]))
    else:
        valid = set(payload) == ({"event_id", "high_watermark"} if job_type == "extract_session_events" else {"event_id"})
        valid = valid and isinstance(payload.get("event_id"), str) \
            and bool(_EVENT_ID.fullmatch(payload["event_id"]))
        if job_type == "extract_session_events":
            valid = valid and type(payload.get("high_watermark")) is int \
                and 0 < payload["high_watermark"] < 2**63
    if not valid:
        raise ValueError("memory job payload must contain only opaque IDs and an integer watermark")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def install_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_jobs(
            job_id TEXT PRIMARY KEY,
            profile_key TEXT NOT NULL,
            owner_key TEXT NOT NULL,
            partition_key TEXT NOT NULL,
            owner_chat_hash TEXT NOT NULL DEFAULT '',
            owner_session_hash TEXT NOT NULL DEFAULT '',
            job_type TEXT NOT NULL CHECK(job_type IN (
              'consolidate_observations','extract_session_events','enrich_claim_graph')),
            payload_json TEXT NOT NULL,
            coalesce_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','leased','done','dead')),
            generation INTEGER NOT NULL DEFAULT 1,
            lease_generation INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at INTEGER NOT NULL,
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_at INTEGER NOT NULL DEFAULT 0,
            last_error_code TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_jobs_coalesce "
        "ON memory_jobs(coalesce_key) WHERE status IN ('pending','leased')"
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(memory_jobs)")}
    for column in ("owner_chat_hash", "owner_session_hash"):
        if column not in columns:
            conn.execute(f"ALTER TABLE memory_jobs ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_jobs_due "
        "ON memory_jobs(profile_key,owner_key,status,available_at,lease_expires_at)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_job_budgets(
            profile_key TEXT NOT NULL,
            day_utc INTEGER NOT NULL,
            jobs_used INTEGER NOT NULL DEFAULT 0,
            requests_used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(profile_key,day_utc)
        )"""
    )


class JobStore:
    def __init__(self, db_path: str | Path, profile: str, owner: str):
        self.db_path = str(db_path)
        if not _DIGEST.fullmatch(profile) or not _DIGEST.fullmatch(owner):
            raise ValueError("invalid memory job owner")
        self.profile, self.owner = profile, owner

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def enqueue(
        self, job_type: str, payload: dict[str, Any], partition: str, *,
        owner_chat_hash: str = "", owner_session_hash: str = "",
        available_at: int | None = None, now: int | None = None,
    ) -> str:
        canonical = validate_payload(job_type, payload)
        if not _DIGEST.fullmatch(partition):
            raise ValueError("invalid memory job partition")
        if job_type != "enrich_claim_graph" and (
            not _OWNER_HASH.fullmatch(owner_chat_hash)
            or not _OWNER_HASH.fullmatch(owner_session_hash)
        ):
            # Legacy enqueue callers may omit these metadata hints, in which
            # case deleted sources simply become no-ops as before. Runtime
            # hooks always provide both authoritative owner hashes.
            if owner_chat_hash or owner_session_hash:
                raise ValueError("invalid memory job owner hash")
        elif job_type == "enrich_claim_graph" and (owner_chat_hash or owner_session_hash):
            raise ValueError("graph jobs require a claim ID alone")
        stamp = int(time.time() if now is None else now)
        due = max(stamp, int(available_at)) if available_at is not None else stamp
        key = _digest(self.profile, self.owner, job_type, partition,
                      payload["claim_id"] if job_type == "enrich_claim_graph" else "")
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            retention = _limit("MEMORY_WIKI_BACKGROUND_HISTORY_DAYS", 30, 1, 365)
            conn.execute(
                "DELETE FROM memory_jobs WHERE job_id IN ("
                "SELECT job_id FROM memory_jobs WHERE status IN ('done','dead') "
                "AND updated_at<? ORDER BY updated_at LIMIT 1000)",
                (stamp - retention * 86400,),
            )
            conn.execute(
                "DELETE FROM memory_job_budgets WHERE profile_key=? AND day_utc<?",
                (self.profile, stamp // 86400 - retention),
            )
            old = conn.execute(
                "SELECT job_id,status,payload_json FROM memory_jobs WHERE coalesce_key=? "
                "AND status IN ('pending','leased')", (key,),
            ).fetchone()
            if old:
                if job_type == "extract_session_events":
                    previous = json.loads(old["payload_json"])
                    if int(previous["high_watermark"]) > payload["high_watermark"]:
                        canonical = str(old["payload_json"])
                conn.execute(
                    "UPDATE memory_jobs SET payload_json=?,generation=generation+1,"
                    "updated_at=?,available_at=CASE WHEN status='pending' THEN MIN(available_at,?) "
                    "ELSE available_at END WHERE job_id=?",
                    (canonical, stamp, due, old["job_id"]),
                )
                return str(old["job_id"])
            identifier = "job_" + uuid.uuid4().hex
            conn.execute(
                """INSERT INTO memory_jobs(job_id,profile_key,owner_key,partition_key,
                    owner_chat_hash,owner_session_hash,
                    job_type,payload_json,coalesce_key,status,available_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
                (identifier, self.profile, self.owner, partition,
                 owner_chat_hash, owner_session_hash, job_type,
                 canonical, key, due, stamp, stamp),
            )
            return identifier

    def lease(self, worker: str, *, now: int | None = None) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{32}", worker):
            raise ValueError("invalid worker identifier")
        stamp = int(time.time() if now is None else now)
        lease_seconds = _limit("MEMORY_WIKI_BACKGROUND_LEASE_SECONDS", 120, 30, 1800)
        max_jobs = _limit("MEMORY_WIKI_BACKGROUND_DAILY_JOBS", 500, 1, 100000)
        max_requests = _limit("MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS", 100, 1, 100000)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                """SELECT * FROM memory_jobs WHERE profile_key=? AND owner_key=?
                   AND ((status='pending' AND available_at<=?)
                        OR (status='leased' AND lease_expires_at<=?))
                   ORDER BY available_at,created_at,job_id LIMIT 1""",
                (self.profile, self.owner, stamp, stamp),
            ).fetchone()
            if job is None:
                return None
            # An expired lease consumed an attempt, but no old worker can
            # acknowledge it after a new lease token is committed here.
            max_attempts = _limit("MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS", 5, 1, 20)
            if int(job["attempts"]) >= max_attempts:
                conn.execute(
                    "UPDATE memory_jobs SET status='dead',lease_owner='',lease_expires_at=0,"
                    "last_error_code='timeout',updated_at=? WHERE job_id=?",
                    (stamp, job["job_id"]),
                )
                return None
            day = stamp // 86400
            budget = conn.execute(
                "SELECT jobs_used,requests_used FROM memory_job_budgets "
                "WHERE profile_key=? AND day_utc=?", (self.profile, day),
            ).fetchone()
            jobs_used = int(budget["jobs_used"]) if budget else 0
            requests_used = int(budget["requests_used"]) if budget else 0
            request_cost = int(job["job_type"] != "consolidate_observations")
            if jobs_used >= max_jobs or requests_used + request_cost > max_requests:
                # A still-running old lease must never be overwritten by a
                # budget deferral; only expired leases reach this branch.
                conn.execute(
                    """UPDATE memory_jobs SET status='pending',available_at=?,
                       lease_owner='',lease_expires_at=0,last_error_code='budget_deferred',
                       updated_at=? WHERE job_id=?""",
                    ((day + 1) * 86400, stamp, job["job_id"]),
                )
                return None
            conn.execute(
                """INSERT INTO memory_job_budgets(profile_key,day_utc,jobs_used,requests_used)
                   VALUES(?,?,1,?) ON CONFLICT(profile_key,day_utc) DO UPDATE SET
                   jobs_used=jobs_used+1,requests_used=requests_used+excluded.requests_used""",
                (self.profile, day, request_cost),
            )
            conn.execute(
                """UPDATE memory_jobs SET status='leased',attempts=attempts+1,
                   lease_owner=?,lease_expires_at=?,lease_generation=generation,
                   last_error_code='',updated_at=? WHERE job_id=?""",
                (worker + ":" + uuid.uuid4().hex, stamp + lease_seconds, stamp, job["job_id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM memory_jobs WHERE job_id=?", (job["job_id"],),
            ).fetchone()
            return dict(claimed)

    def finish(self, job: Mapping[str, Any], worker: str, *, error_code: str = "", now: int | None = None) -> bool:
        """Fenced ack. Error text or exception values are never stored."""
        if error_code and error_code not in _ERROR_CODES:
            error_code = "unknown"
        stamp = int(time.time() if now is None else now)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM memory_jobs WHERE job_id=?", (job["job_id"],)).fetchone()
            if not current or current["status"] != "leased" \
                    or current["lease_owner"] != job["lease_owner"] \
                    or not str(current["lease_owner"]).startswith(worker + ":") \
                    or int(current["lease_generation"]) != int(job["lease_generation"]):
                return False
            changed = int(current["generation"]) != int(job["lease_generation"])
            exhausted = int(current["attempts"]) >= _limit("MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS", 5, 1, 20)
            if changed:
                # A concurrent enqueue updated the pointer/watermark while the
                # worker ran. New generation needs another pass even on success.
                status, due, attempts = "pending", stamp, 0
            elif not error_code:
                status, due, attempts = "done", stamp, int(current["attempts"])
            elif exhausted:
                status, due, attempts = "dead", stamp, int(current["attempts"])
            else:
                exponent = min(int(current["attempts"]) - 1, 12)
                base = _limit("MEMORY_WIKI_BACKGROUND_RETRY_BASE_SECONDS", 10, 1, 3600)
                delay = min(86400, base * (2 ** exponent))
                # Stable per attempt jitter, with no untrusted input.
                fraction = int(_digest(str(job["job_id"]), str(current["attempts"]))[:8], 16) / 0xffffffff
                due = stamp + delay + int(delay * .25 * fraction)
                status, attempts = "pending", int(current["attempts"])
            conn.execute(
                """UPDATE memory_jobs SET status=?,available_at=?,attempts=?,
                   lease_owner='',lease_expires_at=0,last_error_code=?,updated_at=?
                   WHERE job_id=?""",
                (status, due, attempts, error_code, stamp, job["job_id"]),
            )
            return True

    def defer(self, job: Mapping[str, Any], worker: str, *, until: int, now: int | None = None) -> bool:
        """Expected source dependency retry; it does not exhaust failure attempts."""
        stamp = int(time.time() if now is None else now)
        due = max(stamp + 1, min(int(until), stamp + 86400))
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT lease_owner,lease_generation,generation,status FROM memory_jobs WHERE job_id=?",
                (job["job_id"],),
            ).fetchone()
            if not row or row["status"] != "leased" or row["lease_owner"] != job["lease_owner"] \
                    or not str(row["lease_owner"]).startswith(worker + ":") \
                    or int(row["lease_generation"]) != int(job["lease_generation"]):
                return False
            if int(row["generation"]) != int(job["lease_generation"]):
                due = stamp
            conn.execute(
                """UPDATE memory_jobs SET status='pending',available_at=?,attempts=0,
                   lease_owner='',lease_expires_at=0,last_error_code='dependency',updated_at=?
                   WHERE job_id=?""",
                (due, stamp, job["job_id"]),
            )
            return True

    def owns(self, job: Mapping[str, Any], worker: str, *, now: int | None = None) -> bool:
        stamp = int(time.time() if now is None else now)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT lease_owner,lease_expires_at,lease_generation,status "
                "FROM memory_jobs WHERE job_id=? AND profile_key=? AND owner_key=?",
                (job["job_id"], self.profile, self.owner),
            ).fetchone()
            return bool(row and row["status"] == "leased"
                        and row["lease_owner"] == job["lease_owner"]
                        and str(row["lease_owner"]).startswith(worker + ":")
                        and int(row["lease_generation"]) == int(job["lease_generation"])
                        and int(row["lease_expires_at"]) > stamp)

    def renew(self, job: Mapping[str, Any], worker: str, *, now: int | None = None) -> bool:
        stamp = int(time.time() if now is None else now)
        if not self.owns(job, worker, now=stamp):
            return False
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """UPDATE memory_jobs SET lease_expires_at=?,updated_at=?
                   WHERE job_id=? AND profile_key=? AND owner_key=? AND status='leased'
                     AND lease_owner=? AND lease_generation=? AND lease_expires_at>?""",
                (stamp + _limit("MEMORY_WIKI_BACKGROUND_LEASE_SECONDS", 120, 30, 1800),
                 stamp, job["job_id"], self.profile, self.owner, job["lease_owner"],
                 job["lease_generation"], stamp),
            )
            return cursor.rowcount == 1

    def health(self, *, now: int | None = None) -> dict[str, int]:
        stamp = int(time.time() if now is None else now)
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                   SUM(status='pending') AS pending,SUM(status='leased') AS leased,
                   SUM(status='dead') AS dead,
                   MIN(CASE WHEN status IN ('pending','leased') THEN created_at END) oldest
                   FROM memory_jobs WHERE profile_key=? AND owner_key=?""",
                (self.profile, self.owner),
            ).fetchone()
            budget = conn.execute(
                "SELECT jobs_used,requests_used FROM memory_job_budgets WHERE profile_key=? AND day_utc=?",
                (self.profile, stamp // 86400),
            ).fetchone()
            return {
                "total": int(row["total"] or 0), "pending": int(row["pending"] or 0),
                "leased": int(row["leased"] or 0), "dead": int(row["dead"] or 0),
                "oldest_age_seconds": max(0, stamp - int(row["oldest"])) if row["oldest"] else 0,
                "jobs_today": int(budget["jobs_used"]) if budget else 0,
                "requests_today": int(budget["requests_used"]) if budget else 0,
                "jobs_daily_limit": _limit("MEMORY_WIKI_BACKGROUND_DAILY_JOBS", 500, 1, 100000),
                "requests_daily_limit": _limit("MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS", 100, 1, 100000),
            }


def enqueue_event(provider: Any, job_type: str, event_id: str) -> str | None:
    if job_type not in {"consolidate_observations", "extract_session_events"} or not _EVENT_ID.fullmatch(event_id):
        raise ValueError("invalid event job")
    with provider._lock:
        row = provider._connect().execute(
            """SELECT e.*,d.docid AS event_sequence
               FROM memory_events e JOIN memory_event_fts_docids d
                 ON d.event_id=e.event_id WHERE e.event_id=?""",
            (event_id,),
        ).fetchone()
    if row is None or str(row["owner_bot_id"]) != str(provider.bot_id):
        return None
    payload: dict[str, Any] = {"event_id": event_id}
    if job_type == "extract_session_events":
        payload["high_watermark"] = int(row["event_sequence"])
    return JobStore(provider.db_path, profile_key(provider), owner_key(provider)).enqueue(
        job_type, payload, partition_key(row),
        owner_chat_hash=str(row["owner_chat_hash"]),
        owner_session_hash=str(row["owner_session_hash"]),
    )


def enqueue_claim(provider: Any, claim_id: str) -> str | None:
    validate_payload("enrich_claim_graph", {"claim_id": claim_id})
    with provider._lock:
        row = provider._connect().execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    if row is None or str(row["origin_bot_id"]) != str(provider.bot_id):
        return None
    partition = _digest(str(row["origin_bot_id"]), str(row["origin_chat_hash"]), claim_id)
    return JobStore(provider.db_path, profile_key(provider), owner_key(provider)).enqueue(
        "enrich_claim_graph", {"claim_id": claim_id}, partition,
    )


def reenqueue_after_logical_restore(provider: Any, module: Any) -> dict[str, int | bool]:
    """Recreate bounded, ID-only work after a checkpoint rebuild.

    Logical checkpoints intentionally omit jobs and the old docid map. This
    scan runs only after the rebuilt database has been swapped in and migrated,
    so every watermark is minted from its *new* authoritative docid map.
    Both job families are restricted to chat events with no project context;
    observation jobs retain their source event partition. This performs no network
    I/O, embedding, extraction, or consolidation.
    """
    result: dict[str, int | bool] = {
        "enabled": enabled(), "scanned": 0, "truncated": False,
        "observation_jobs": 0, "extraction_jobs": 0,
    }
    if not enabled():
        return result
    max_jobs = _limit("MEMORY_WIKI_BACKGROUND_RECOVERY_MAX_JOBS", 128, 1, 10000)
    scan_cap = _limit(
        "MEMORY_WIKI_BACKGROUND_RECOVERY_SCAN_ROWS", max(4096, max_jobs * 32),
        max_jobs, 1_000_000,
    )
    stamp = int(time.time())
    with provider._lock:
        rows = provider._connect().execute(
            """SELECT e.event_id,e.owner_bot_id,e.owner_chat_hash,
                      e.owner_session_hash,e.visibility_scope,e.project_id,
                      e.event_type,e.role,d.docid AS event_sequence,
                      r.retry_after,x.event_id AS decided_event_id
               FROM memory_events e
               JOIN memory_event_fts_docids d ON d.event_id=e.event_id
               LEFT JOIN memory_observation_event_retries r ON r.event_id=e.event_id
               LEFT JOIN memory_observation_event_decisions x ON x.event_id=e.event_id
               WHERE e.expires_at>? AND e.visibility_scope='chat'
                 AND COALESCE(e.project_id,'')=''
               ORDER BY d.docid DESC LIMIT ?""",
            (stamp, scan_cap + 1),
        ).fetchall()
    result["truncated"] = len(rows) > scan_cap
    rows = rows[:scan_cap]
    result["scanned"] = len(rows)
    observations: dict[str, tuple[Any, int]] = {}
    extractions: dict[str, Any] = {}
    observation_enabled = bool(module._memory_observations.enabled())
    for row in rows:
        owner = str(row["owner_bot_id"] or "")
        if not owner or not _OWNER_HASH.fullmatch(str(row["owner_chat_hash"] or "")) \
                or not _OWNER_HASH.fullmatch(str(row["owner_session_hash"] or "")):
            continue
        part = partition_key(row)
        if observation_enabled and (row["decided_event_id"] is None or row["retry_after"] is not None):
            due = max(stamp, int(row["retry_after"] or stamp))
            existing = observations.get(part)
            if existing is None:
                if len(observations) < max_jobs:
                    observations[part] = (row, due)
            elif due < existing[1]:
                observations[part] = (existing[0], due)
        if (row["event_type"] == "dialogue_turn"
                and row["role"] in {"user", "assistant"}
                and part not in extractions and len(extractions) < max_jobs):
            extractions[part] = row
    # Reserve room for both job families when both have eligible work. The
    # per-profile daily budget, not recovery, meters subsequent remote calls.
    observation_quota = min(len(observations), max_jobs // 2 if extractions else max_jobs)
    extraction_quota = min(len(extractions), max_jobs - observation_quota)
    observation_quota = min(len(observations), max_jobs - extraction_quota)
    profile = profile_key(provider)
    for part, (row, due) in list(observations.items())[:observation_quota]:
        store = JobStore(provider.db_path, profile, _digest(str(row["owner_bot_id"])))
        store.enqueue(
            "consolidate_observations", {"event_id": str(row["event_id"])}, part,
            owner_chat_hash=str(row["owner_chat_hash"]),
            owner_session_hash=str(row["owner_session_hash"]),
            available_at=due,
        )
        result["observation_jobs"] = int(result["observation_jobs"]) + 1
    for part, row in list(extractions.items())[:extraction_quota]:
        store = JobStore(provider.db_path, profile, _digest(str(row["owner_bot_id"])))
        store.enqueue(
            "extract_session_events", {
                "event_id": str(row["event_id"]),
                "high_watermark": int(row["event_sequence"]),
            }, part,
            owner_chat_hash=str(row["owner_chat_hash"]),
            owner_session_hash=str(row["owner_session_hash"]),
        )
        result["extraction_jobs"] = int(result["extraction_jobs"]) + 1
    return result


def _worker_provider(provider: Any, source: Mapping[str, Any]) -> Any:
    """Separate connection and synthetic session with the original hash identity."""
    worker = copy.copy(provider)
    worker._conn = None
    worker._lock = threading.RLock()
    columns = set(source.keys())
    worker.bot_id = str(source["owner_bot_id"] if "owner_bot_id" in columns else source["origin_bot_id"])
    worker.project_scope = str(source["project_id"] or "")
    worker._job_chat_hash = str(source["owner_chat_hash"] if "owner_chat_hash" in columns else source["origin_chat_hash"])
    worker._job_session_hash = str(source["owner_session_hash"] if "owner_session_hash" in columns else "")
    worker.session_id = "job_" + worker._job_session_hash if worker._job_session_hash else "job_" + worker._job_chat_hash
    # The override is scoped to this private instance. A raw session ID is
    # neither stored nor needed for the original chat ACL partition.
    from types import MethodType
    worker._chat_hash = MethodType(
        lambda self, session_id="": self._job_chat_hash if not session_id or session_id == self.session_id
        else provider._chat_hash(session_id), worker,
    )
    worker._scoped_backup_owner = MethodType(
        lambda self: {
            "bot_id": self.bot_id, "session_id": self.session_id,
            "chat_hash": self._job_chat_hash, "project_id": self.project_scope,
        }, worker,
    )
    worker._background_job_owner = {
        "bot_id": worker.bot_id, "chat_hash": worker._job_chat_hash,
        "session_hash": worker._job_session_hash, "project_id": worker.project_scope,
    }
    return worker


def _event_source(provider: Any, job: Mapping[str, Any], payload: Mapping[str, Any]) -> Any:
    with provider._lock:
        row = provider._connect().execute(
            """SELECT e.*,d.docid AS event_sequence
               FROM memory_events e JOIN memory_event_fts_docids d
                 ON d.event_id=e.event_id
               WHERE e.event_id=? AND e.expires_at>?""",
            (payload["event_id"], int(time.time())),
        ).fetchone()
    if row is None and _OWNER_HASH.fullmatch(str(job["owner_chat_hash"])) \
            and _OWNER_HASH.fullmatch(str(job["owner_session_hash"])):
        # The newest coalesced pointer may have been deleted, while older
        # retained events still need consolidation. Search this exact session
        # and verify the full partition digest before using a replacement.
        with provider._lock:
            candidates = provider._connect().execute(
                """SELECT e.*,d.docid AS event_sequence
                   FROM memory_events e JOIN memory_event_fts_docids d
                     ON d.event_id=e.event_id
                   WHERE e.owner_bot_id=? AND e.owner_chat_hash=?
                     AND e.owner_session_hash=? AND e.expires_at>?
                     AND d.docid<=? ORDER BY d.docid DESC LIMIT 128""",
                (provider.bot_id, job["owner_chat_hash"], job["owner_session_hash"],
                 int(time.time()), payload.get("high_watermark", 2**63-1)),
            ).fetchall()
        row = next((candidate for candidate in candidates
                    if partition_key(candidate) == job["partition_key"]), None)
    if row is None:
        return None
    if (partition_key(row) != job["partition_key"]
            or _digest(str(row["owner_bot_id"])) != job["owner_key"]
            or (job["owner_chat_hash"] and row["owner_chat_hash"] != job["owner_chat_hash"])
            or (job["owner_session_hash"] and row["owner_session_hash"] != job["owner_session_hash"])
            or str(row["owner_bot_id"]) != str(provider.bot_id)):
        return None
    return row


def _run_job(
    provider: Any, module: Any, job: Mapping[str, Any],
    lease_valid: Callable[[], bool] | None = None,
) -> str | tuple[str, int]:
    try:
        payload = json.loads(str(job["payload_json"]))
        if validate_payload(str(job["job_type"]), payload) != job["payload_json"]:
            return "invalid_source"
    except (ValueError, TypeError, KeyError):
        return "invalid_source"
    kind = str(job["job_type"])
    if lease_valid is not None and not lease_valid():
        return "timeout"
    if kind == "enrich_claim_graph":
        with provider._lock:
            source = provider._connect().execute(
                "SELECT * FROM claims WHERE id=? AND status='active' AND temporal_status='current'",
                (payload["claim_id"],),
            ).fetchone()
        if source is None:
            return ""
        partition = _digest(str(source["origin_bot_id"]), str(source["origin_chat_hash"]), payload["claim_id"])
        if partition != job["partition_key"] or str(source["origin_bot_id"]) != str(provider.bot_id):
            return "owner_mismatch"
        worker = _worker_provider(provider, source)
        try:
            result = worker._auto_graph_enrich_extracted_claims([payload["claim_id"]])
            if int(result.get("errors") or 0) > 0:
                return "provider"
            if int(result.get("deadline_exhausted") or 0) > 0:
                return "timeout"
        finally:
            if worker._conn:
                worker._conn.close()
        return ""

    source = _event_source(provider, job, payload)
    if source is None:
        return ""  # Deleted or expired source wins over an old job.
    worker = _worker_provider(provider, source)
    try:
        if kind == "consolidate_observations":
            scope = str(source["visibility_scope"])
            if scope not in {"chat", "bot", "project"}:
                return "invalid_source"
            if not module._memory_observations.enabled():
                return ""
            result = module._memory_observations.consolidate_events(
                worker, module, scope=scope, session_id=worker.session_id,
                project_id=str(source["project_id"] or ""),
                limit=_limit("MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH", 64, 1, 1000),
            )
            if int(result.get("events_deferred") or 0) > 0:
                return ("defer", int(result.get("next_retry_at") or (time.time() + 60)))
            return ""
        if kind != "extract_session_events":
            return "invalid_source"
        # Existing project claims are visible across bots sharing a project,
        # whereas project events require both owner bot and project. A project
        # event cannot safely become a claim until those ACLs are compatible.
        # Bot events likewise must not be narrowed into chat claims.
        source_scope = str(source["visibility_scope"])
        if source_scope != "chat":
            return ""
        source_project = str(source["project_id"] or "")
        if source_project:
            # Existing chat-claim reads use bot/chat hashes and do not apply a
            # project fence. Until that ACL supports project-bound chat rows,
            # deriving a chat claim from project-context evidence is unsafe.
            return ""
        # Rehydrate only retained rows from the exact source partition and
        # session. The same session ID may be reused across two projects.
        conn = worker._connect()
        rows = conn.execute(
            """SELECT e.*,d.docid AS event_sequence
               FROM memory_events e JOIN memory_event_fts_docids d
                 ON d.event_id=e.event_id
               WHERE e.owner_bot_id=? AND e.owner_chat_hash=?
                 AND e.owner_session_hash=?
                 AND e.visibility_scope=? AND e.project_id=?
                 AND e.event_type='dialogue_turn'
                 AND e.role IN ('user','assistant')
                 AND e.expires_at>? AND d.docid<=?
               ORDER BY d.docid DESC LIMIT 32""",
            (source["owner_bot_id"], source["owner_chat_hash"],
             source["owner_session_hash"], source_scope, source_project,
             int(time.time()), payload["high_watermark"]),
        ).fetchall()
        rows.reverse()
        if not rows:
            return ""
        preexisting = {
            str(row["id"]) for row in conn.execute(
                """SELECT id FROM claims WHERE visibility_scope='chat'
                   AND origin_bot_id=? AND origin_chat_hash=?""",
                (worker.bot_id, worker._job_chat_hash),
            )
        }

        def source_identity(row: Mapping[str, Any]) -> tuple[str, ...]:
            return tuple(str(row[key] or "") for key in (
                "content_hash", "owner_bot_id", "owner_chat_hash",
                "owner_session_hash", "visibility_scope", "project_id",
                "event_type", "role",
            ))

        originals: dict[str, tuple[str, ...]] = {}
        messages: list[dict[str, str]] = []
        for row in rows:
            raw = str(row["content"] or "")
            if module.secret_scan(raw).get("raw_secret") \
                    or hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest() != row["content_hash"]:
                continue
            checked = worker._inspect_recall_text(
                raw, source="host:background_event", mem_type="event", audit=False,
                max_len=max(4000, len(raw)),
            )
            if checked.get("status") != "safe" or str(checked.get("content") or "") != raw:
                continue
            originals[str(row["event_id"])] = source_identity(row)
            messages.append({"role": str(row["role"]), "content": raw})
        if not messages:
            return ""

        def persist_if_current(*args: Any, **kwargs: Any) -> str:
            # Guard after the remote response and immediately before every
            # claim write. A deleted/edited event invalidates this extraction.
            ids = list(originals)
            marks = ",".join("?" for _ in ids)
            if lease_valid is not None and not lease_valid():
                return ""
            if len(args) != 1 or not isinstance(args[0], str):
                return ""
            claim_text = args[0]
            evidence = str(kwargs.get("evidence") or "")
            source_label = str(kwargs.get("source") or "")
            topic = str(kwargs.get("topic") or "general")
            if (kwargs.get("visibility_scope") != "chat"
                    or source_label not in {"extractor:llm", "extractor:heuristic"}
                    or module.secret_scan(claim_text + " " + evidence).get("raw_secret")
                    or module.memory_gate_decision(claim_text, topic, source_label).get("action") != "accept"):
                # _prepare_claim may write to the review queue for weak or
                # sensitive candidates. Background extraction never emits
                # such a side effect before its retained-source fence.
                return ""
            prepared = worker._prepare_claim(
                claim_text, topic, evidence, source_label,
                kwargs.get("confidence", .72), kwargs.get("salience", .70),
                visibility_scope=source_scope, project_id=source_project,
                event_at=kwargs.get("event_at", 0),
                event_timezone=kwargs.get("event_timezone", "UTC"),
            )
            if not isinstance(prepared, dict):
                return ""
            if prepared.get("visibility_scope") != source_scope \
                    or str(prepared.get("project_id") or "") != source_project \
                    or str(prepared.get("origin_bot_id") or "") != str(source["owner_bot_id"]):
                return ""
            # SQLite's RESERVED writer lock fences event deletion against
            # validation and the claim write. The callback cannot resurrect
            # an event erased while the remote extractor was running.
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                live = conn.execute(
                    f"""SELECT event_id,content_hash,owner_bot_id,owner_chat_hash,
                               owner_session_hash,visibility_scope,project_id,event_type,role
                        FROM memory_events WHERE event_id IN ({marks})
                          AND owner_bot_id=? AND owner_chat_hash=? AND owner_session_hash=?
                          AND visibility_scope=? AND project_id=? AND expires_at>?""",
                    (*ids, source["owner_bot_id"], source["owner_chat_hash"],
                     source["owner_session_hash"], source_scope,
                     source_project, int(time.time())),
                ).fetchall()
                if {str(row["event_id"]): source_identity(row) for row in live} != originals:
                    return ""
                for original in messages:
                    if module.secret_scan(original["content"]).get("raw_secret"):
                        return ""
                    inspected = worker._inspect_recall_text(
                        original["content"], source="host:background_event",
                        mem_type="event", audit=False,
                        max_len=max(4000, len(original["content"])),
                    )
                    if inspected.get("status") != "safe" or inspected.get("content") != original["content"]:
                        return ""
                claim_id = worker._add_claim_tx(
                    conn, prepared, float(kwargs.get("confidence", .72)),
                    float(kwargs.get("salience", .70)),
                )
            if claim_id and not prepared.get("_no_op"):
                worker._after_claim_commit(claim_id, prepared["topic"], prepared["claim"])
            return str(claim_id or "")

        result = module.extract_session_claims(
            messages, session_id=worker.session_id,
            add_claim_callback=persist_if_current,
            redact_secret_callback=module.redact_secrets,
            secret_scan_callback=module.secret_scan,
        )
        # Graph jobs only refer to new, still active claims; execution repeats
        # full graph eligibility checks against authoritative current rows.
        graph_allowed = os.environ.get("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "0").strip().lower() \
            in {"1", "true", "yes", "on"}
        graph_available = os.environ.get("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "0").strip().lower() \
            in {"1", "true", "yes", "on"}
        if source_scope == "chat" and graph_allowed and graph_available:
            for claim_id in result.get("persisted_ids", [])[:4]:
                if isinstance(claim_id, str) and claim_id not in preexisting \
                        and _CLAIM_ID.fullmatch(claim_id):
                    enqueue_claim(worker, claim_id)
        if result.get("error") or result.get("errors"):
            return "provider"
        return ""
    finally:
        if worker._conn:
            worker._conn.close()


def run_once(provider: Any, module: Any, *, worker_id: str | None = None) -> bool:
    store = JobStore(provider.db_path, profile_key(provider), owner_key(provider))
    worker_id = worker_id or uuid.uuid4().hex
    job = store.lease(worker_id)
    if job is None:
        return False
    heartbeat_stop = threading.Event()
    heartbeat_interval = max(5, _limit(
        "MEMORY_WIKI_BACKGROUND_LEASE_SECONDS", 120, 30, 1800,
    ) // 3)

    def heartbeat() -> None:
        while not heartbeat_stop.wait(heartbeat_interval):
            try:
                if not store.renew(job, worker_id):
                    return
            except sqlite3.Error:
                return

    heartbeat_thread = threading.Thread(
        target=heartbeat, name="memory-wiki-job-lease", daemon=True,
    )
    heartbeat_thread.start()
    outcome: str | tuple[str, int] = ""
    try:
        outcome = _run_job(
            provider, module, job,
            lease_valid=lambda: store.owns(job, worker_id),
        )
        error_code = outcome if isinstance(outcome, str) else ""
    except sqlite3.Error:
        error_code = "database"
    except (TimeoutError, ConnectionError):
        error_code = "network"
    except Exception:
        # Deliberately never log or persist str(exc); providers sometimes
        # include a request body or bearer token in exception messages.
        error_code = "unknown"
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
    if isinstance(outcome, tuple) and outcome[0] == "defer":
        store.defer(job, worker_id, until=outcome[1])
    else:
        store.finish(job, worker_id, error_code=error_code)
    return True


class Worker:
    def __init__(self, provider: Any, module: Any):
        self.provider = provider
        self.module = module
        self.identity = uuid.uuid4().hex
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="memory-wiki-background", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def wake(self) -> None:
        self.wake_event.set()

    def stop(self) -> bool:
        self.stop_event.set()
        self.wake_event.set()
        self.thread.join(timeout=45)
        return not self.thread.is_alive()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if run_once(self.provider, self.module, worker_id=self.identity):
                    continue
            except Exception:
                # Worker stays alive; next poll/restart can reclaim leases.
                pass
            self.wake_event.wait(_limit("MEMORY_WIKI_BACKGROUND_POLL_SECONDS", 10, 1, 300))
            self.wake_event.clear()
