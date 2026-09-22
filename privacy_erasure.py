"""Host-local, content-free erasure intents that survive older SQLite restores.

The file lives outside Memory Wiki ZIP backups and journal checkpoints.  Each
record contains only keyed digests of source IDs, owner partitions and removal
text.  An intent is fsynced before the corresponding SQLite transaction commits.
The in-database applied sequence is deliberately restored with old databases,
so an old restore must replay newer intents before it can serve reads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Iterable


_MASK = (1 << 64) - 1
_LOCAL_LOCK = threading.RLock()


@contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCAL_LOCK, open(path, "a+b") as handle:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ErasureLedger:
    """Authenticated local tombstones with no persisted user text or raw IDs."""

    def __init__(self, root: Path):
        self.dir = Path(root) / "privacy-erasure"
        self.key_path = self.dir / "key.bin"
        self.log_path = self.dir / "intents.jsonl"
        self.lock_path = self.dir / "intents.lock"
        self.dir.mkdir(parents=True, exist_ok=True)
        with _file_lock(self.lock_path):
            key_exists = self.key_path.exists()
            log_exists = self.log_path.exists()
            if key_exists != log_exists:
                raise RuntimeError("privacy erasure ledger is incomplete")
            if not key_exists:
                key = os.urandom(32)
                with open(self.key_path, "xb") as out:
                    out.write(key)
                    out.flush()
                    os.fsync(out.fileno())
                with open(self.log_path, "xb") as out:
                    out.flush()
                    os.fsync(out.fileno())
                _fsync_dir(self.dir)
        self.key = self.key_path.read_bytes()
        if len(self.key) != 32:
            raise RuntimeError("privacy erasure key is invalid")
        self._base = (int.from_bytes(hmac.digest(self.key, b"rolling-base", "sha256")[:8], "big") | 1) & _MASK
        if self._base < 257:
            self._base += 257
        self.load()

    def digest(self, kind: str, value: str) -> str:
        return hmac.new(self.key, kind.encode() + b"\0" + str(value).encode("utf-8"), hashlib.sha256).hexdigest()

    def _rolling(self, value: str) -> int:
        acc = 0
        for char in value:
            acc = (acc * self._base + ord(char) + 1) & _MASK
        return acc

    def _contains_digest(self, value: str, marker: dict[str, Any], kind: str, *, boundary: bool = False) -> bool:
        length = int(marker.get("length") or 0)
        if not length or len(value) < length:
            return False
        expected = str(marker.get("digest") or "")
        if len(value) == length:
            return hmac.compare_digest(self.digest(kind, value), expected)
        if not bool(marker.get("substring")):
            return False
        expected_rolling = int(marker.get("rolling") or -1)
        power = pow(self._base, length - 1, 1 << 64)
        rolling = self._rolling(value[:length])
        for offset in range(len(value) - length + 1):
            if rolling == expected_rolling:
                end = offset + length
                if ((not boundary or ((offset == 0 or not re.match(r"\w", value[offset - 1]))
                                     and (end == len(value) or not re.match(r"\w", value[end]))))
                        and hmac.compare_digest(self.digest(kind, value[offset:end]), expected)):
                    return True
            if offset + length < len(value):
                rolling = ((rolling - ((ord(value[offset]) + 1) * power)) * self._base
                           + ord(value[offset + length]) + 1) & _MASK
        return False

    def _marker(self, kind: str, value: str, *, substring: bool) -> dict[str, Any]:
        return {
            "digest": self.digest(kind, value), "length": len(value),
            "rolling": self._rolling(value), "substring": bool(substring),
        }

    def _load_unlocked(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        previous = "0" * 64
        with open(self.log_path, "rb") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                    if (not isinstance(record, dict) or int(record.get("seq") or 0) != len(entries) + 1
                            or str(record.get("prev") or "") != previous):
                        raise ValueError("invalid sequence")
                    mac = str(record.pop("mac", ""))
                    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                    expected = hmac.new(self.key, canonical, hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(mac, expected):
                        raise ValueError("invalid authenticator")
                    record["mac"] = mac
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    raise RuntimeError("privacy erasure ledger integrity failed") from exc
                entries.append(record)
                previous = mac
        return entries

    def load(self) -> list[dict[str, Any]]:
        with _file_lock(self.lock_path):
            return self._load_unlocked()

    def append(self, provider: Any, normalized: str, *, claim_ids: Iterable[str],
               event_ids: Iterable[str], episode_ids: Iterable[str],
               episode_surface: str) -> int:
        """Durably append an intent while caller still owns SQLite write lock."""
        owner = {
            "bot": self.digest("owner-bot", provider.bot_id),
            "chat": self.digest("owner-chat", provider._chat_hash(provider.session_id)),
            "project": self.digest("owner-project", provider.project_scope or ""),
            "raw_session": self.digest("owner-raw-session", provider.session_id),
            "trusted_bot": bool(getattr(provider, "_bot_scope_trusted", False)),
        }
        try:
            from . import memory_events
        except ImportError:
            import memory_events
        principal = memory_events._principal(provider, provider.session_id)
        owner["session"] = self.digest("owner-session", principal["session_hash"])
        normalized = str(normalized or "").casefold()
        episode_surface = str(episode_surface or "")
        body = {
            "v": 1,
            "created_at": int(time.time()),
            "owner": owner,
            "claims": sorted({self.digest("claim-id", value) for value in claim_ids}),
            "events": sorted({self.digest("event-id", value) for value in event_ids}),
            "episodes": sorted({self.digest("episode-id", value) for value in episode_ids}),
            "claim_text": self._marker("claim-text", normalized, substring=False),
            "event_text": self._marker(
                "event-text", normalized,
                substring=len(normalized) >= 16 and len(normalized.split()) >= 3,
            ),
            "episode_text": self._marker("episode-text", episode_surface, substring=True),
        }
        with _file_lock(self.lock_path):
            previous = self._load_unlocked()
            body["seq"] = len(previous) + 1
            body["prev"] = previous[-1]["mac"] if previous else "0" * 64
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            body["mac"] = hmac.new(self.key, canonical, hashlib.sha256).hexdigest()
            with open(self.log_path, "ab") as out:
                out.write(json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n")
                out.flush()
                os.fsync(out.fileno())
            _fsync_dir(self.dir)
            return int(body["seq"])

    def _owner_allows(self, owner: dict[str, Any], row: Any, kind: str) -> bool:
        scope = str(row["visibility_scope"] or "chat").lower()
        if scope == "global" and kind == "claim":
            return True
        if scope == "project" and kind == "claim":
            project = self.digest("owner-project", str(row["project_id"] or ""))
            return bool(row["project_id"] and hmac.compare_digest(project, str(owner.get("project") or "")))
        bot = self.digest("owner-bot", str(row["owner_bot_id"] if kind != "claim" else row["origin_bot_id"]))
        if not hmac.compare_digest(bot, str(owner.get("bot") or "")):
            return False
        if scope == "private" and kind == "claim":
            session = self.digest("owner-raw-session", str(row["origin_session_id"] or ""))
            return hmac.compare_digest(session, str(owner.get("raw_session") or ""))
        if scope == "chat":
            chat_field = "origin_chat_hash" if kind == "claim" else "owner_chat_hash"
            chat = self.digest("owner-chat", str(row[chat_field] or ""))
            if not hmac.compare_digest(chat, str(owner.get("chat") or "")):
                return False
            if kind == "event":
                session = self.digest("owner-session", str(row["owner_session_hash"] or ""))
                return hmac.compare_digest(session, str(owner.get("session") or ""))
            return True
        if scope == "bot":
            return kind == "claim" or bool(owner.get("trusted_bot"))
        if scope == "project":
            project = self.digest("owner-project", str(row["project_id"] or ""))
            return bool(row["project_id"] and hmac.compare_digest(project, str(owner.get("project") or "")))
        return False

    def replay(self, provider: Any, module: Any, *, force: bool = False,
               conn: Any = None) -> dict[str, int]:
        """Apply all unapplied intents in one SQLite transaction before reads."""
        conn = conn or provider._connect()
        counts = {"claims": 0, "events": 0, "episodes": 0}
        with provider._lock:
            with (nullcontext(conn) if conn.in_transaction else conn):
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                entries = self.load()
                row = conn.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()
                applied = int(row[0]) if row else 0
                if applied > len(entries):
                    raise RuntimeError("privacy erasure ledger is older than database")
                pending = entries if force else entries[applied:]
                if not pending:
                    return counts
                for entry in pending:
                    owner = entry["owner"]
                    stamp = int(entry["created_at"])
                    claim_ids: list[str] = []
                    linked_claim_ids: list[str] = []
                    for record in conn.execute(
                        "SELECT id,claim,normalized_claim,visibility_scope,origin_bot_id,"
                        "origin_chat_hash,origin_session_id,project_id,created_at,status FROM claims"
                    ):
                        if not self._owner_allows(owner, record, "claim"):
                            continue
                        ident = self.digest("claim-id", str(record["id"]))
                        exact = ident in entry["claims"]
                        older = int(record["created_at"] or 0) <= stamp
                        text = str(module.normalize_claim(str(record["normalized_claim"] or record["claim"])) or "").casefold()
                        if exact or (older and self._contains_digest(text, entry["claim_text"], "claim-text")):
                            linked_claim_ids.append(str(record["id"]))
                            if str(record["status"] or "") == "active":
                                claim_ids.append(str(record["id"]))
                    for ident in claim_ids:
                        conn.execute(
                            "UPDATE claims SET status='retired',temporal_status='historical',updated_at=? "
                            "WHERE id=? AND status='active'", (stamp, ident),
                        )
                    counts["claims"] += len(claim_ids)
                    event_ids: list[str] = []
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='memory_events'").fetchone():
                        linked_event_ids: set[str] = set()
                        if linked_claim_ids and conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE name='memory_event_evidence'"
                        ).fetchone():
                            for offset in range(0, len(linked_claim_ids), 400):
                                chunk = linked_claim_ids[offset:offset + 400]
                                linked_event_ids.update(
                                    str(link[0]) for link in conn.execute(
                                        "SELECT DISTINCT event_id FROM memory_event_evidence "
                                        "WHERE target_type='claim' AND target_id IN ("
                                        + ",".join("?" for _ in chunk) + ")", chunk,
                                    )
                                )
                        for record in conn.execute(
                            "SELECT event_id,content,visibility_scope,owner_bot_id,owner_chat_hash,"
                            "owner_session_hash,project_id,created_at FROM memory_events"
                        ):
                            if not self._owner_allows(owner, record, "event"):
                                continue
                            ident = self.digest("event-id", str(record["event_id"]))
                            exact = ident in entry["events"]
                            older = int(record["created_at"] or 0) <= stamp
                            text = str(module.normalize_claim(str(record["content"] or "")) or "").casefold()
                            if (exact or str(record["event_id"]) in linked_event_ids
                                    or (older and self._contains_digest(text, entry["event_text"], "event-text"))):
                                event_ids.append(str(record["event_id"]))
                        for offset in range(0, len(event_ids), 400):
                            chunk = event_ids[offset:offset + 400]
                            conn.execute("DELETE FROM memory_events WHERE event_id IN (" + ",".join("?" for _ in chunk) + ")", chunk)
                    counts["events"] += len(event_ids)
                    episode_ids: list[str] = []
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='episodic_turns'").fetchone():
                        for record in conn.execute(
                            "SELECT id,content,visibility_scope,owner_bot_id,owner_chat_hash,created_at "
                            "FROM episodic_turns"
                        ):
                            if not self._owner_allows(owner, record, "episode"):
                                continue
                            ident = self.digest("episode-id", str(record["id"]))
                            exact = ident in entry["episodes"]
                            older = int(record["created_at"] or 0) <= stamp
                            text = module._episodic_memory._removal_surface(str(record["content"] or ""))
                            if exact or (older and self._contains_digest(text, entry["episode_text"], "episode-text", boundary=True)):
                                episode_ids.append(str(record["id"]))
                        for ident in episode_ids:
                            if (module._episodic_memory._semantic_enabled(module)
                                    or module._episodic_memory._semantic_was_enabled(conn)
                                    or module._episodic_memory._episode_has_vector_history(conn, ident)):
                                module._episodic_memory._enqueue_episode_delete(module, conn, ident)
                        for offset in range(0, len(episode_ids), 400):
                            chunk = episode_ids[offset:offset + 400]
                            conn.execute("DELETE FROM episodic_turns WHERE id IN (" + ",".join("?" for _ in chunk) + ")", chunk)
                    counts["episodes"] += len(episode_ids)
                conn.execute(
                    "INSERT INTO meta(key,value) VALUES('privacy_erasure_applied_seq',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(len(entries)),),
                )
                if any(counts.values()):
                    conn.execute("UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='cache_state_revision'")
        return counts
