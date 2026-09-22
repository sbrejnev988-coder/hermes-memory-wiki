"""Explicit, auditable sharing of claim-backed context between Hermes actors.

The tables contain claim IDs and content digests, never copied claim bodies.
An owner grants a named bot or project access; the recipient must attach the
grant before it is eligible for context packing. Source edits invalidate the
shared reference until the owner creates a new block.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any


MAX_BLOCK_CLAIMS = 12
MAX_BLOCK_CHARS = 2400
MAX_ATTACHED_BLOCKS = 8


def install_shared_block_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS shared_blocks(
        id TEXT PRIMARY KEY,
        owner_bot_id TEXT NOT NULL,
        owner_chat_hash TEXT NOT NULL,
        title TEXT NOT NULL,
        claim_refs_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shared_block_grants(
        block_id TEXT NOT NULL REFERENCES shared_blocks(id) ON DELETE CASCADE,
        principal_type TEXT NOT NULL CHECK(principal_type IN ('bot','project')),
        principal_id TEXT NOT NULL,
        granted_at INTEGER NOT NULL,
        revoked_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(block_id, principal_type, principal_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shared_block_attachments(
        block_id TEXT NOT NULL,
        principal_type TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        attached_at INTEGER NOT NULL,
        detached_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(block_id, principal_type, principal_id),
        FOREIGN KEY(block_id, principal_type, principal_id)
            REFERENCES shared_block_grants(block_id, principal_type, principal_id)
            ON DELETE CASCADE
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shared_block_events(
        id TEXT PRIMARY KEY,
        block_id TEXT NOT NULL REFERENCES shared_blocks(id),
        action TEXT NOT NULL,
        actor_bot_id TEXT NOT NULL,
        actor_chat_hash TEXT NOT NULL,
        principal_type TEXT NOT NULL DEFAULT '',
        principal_id TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shared_block_grant_principal ON shared_block_grants(principal_type,principal_id,revoked_at)")


def _principal_key(provider: Any, principal_type: str, principal_id: str) -> str:
    salt = str(provider.database_instance_id or provider._meta_text("database_instance_id") or "")
    if not salt:
        raise ValueError("shared_block_actor_unavailable")
    material = f"{salt}\0{principal_type}\0{principal_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:20]


def _actor(provider: Any) -> tuple[str, str, str]:
    bot_id = str(provider.bot_id or "").strip()
    chat_hash = str(provider._chat_hash(provider.session_id) or "").strip()
    project_id = str(provider.project_scope or "").strip()
    if not bot_id or not chat_hash:
        raise ValueError("shared_block_actor_unavailable")
    return (
        _principal_key(provider, "bot", bot_id), chat_hash,
        _principal_key(provider, "project", project_id) if project_id else "",
    )


def _identifier(value: Any, *, field: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 200 or any(ord(ch) < 32 for ch in result):
        raise ValueError(f"invalid_{field}")
    return result


def _digest(row: sqlite3.Row) -> str:
    # 80 bits avoids the generic checkpoint secret detector's long-token
    # replacement while still making accidental source drift collisions tiny.
    return hashlib.sha256(str(row["claim"] or "").encode("utf-8")).hexdigest()[:20]


def _source_claim(provider: Any, claim_id: str, *, require_owner_visible: bool) -> sqlite3.Row | None:
    conn = provider._connect()
    row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    if row is None or (require_owner_visible and not provider._claim_visible(row)):
        return None
    if (str(row["status"] or "") != "active"
            or str(row["risk"] or "").lower() == "secret"
            or str(row["secrecy_level"] or "").lower() != "public"
            or int(row["quarantined_at"] or 0)):
        return None
    return row


def _event(conn: sqlite3.Connection, provider: Any, block_id: str,
           action: str, principal_type: str = "", principal_id: str = "") -> None:
    bot_id, chat_hash, _ = _actor(provider)
    conn.execute("""INSERT INTO shared_block_events
        (id,block_id,action,actor_bot_id,actor_chat_hash,principal_type,principal_id,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        ("sbe_" + uuid.uuid4().hex[:20], block_id, action, bot_id, chat_hash,
         principal_type, principal_id, int(time.time())))


def _owned_block(provider: Any, block_id: str) -> sqlite3.Row:
    bot_id, chat_hash, _ = _actor(provider)
    row = provider._connect().execute("SELECT * FROM shared_blocks WHERE id=?", (block_id,)).fetchone()
    if row is None or row["owner_bot_id"] != bot_id or row["owner_chat_hash"] != chat_hash:
        raise ValueError("shared_block_not_found")
    return row


def _recipient_identity(provider: Any, principal_type: str) -> tuple[str, str]:
    bot_id, _, project_id = _actor(provider)
    if principal_type == "bot":
        return "bot", bot_id
    if principal_type == "project" and project_id:
        return "project", project_id
    raise ValueError("shared_block_grant_not_found")


def authorize_call(provider: Any, tool_name: str, args: dict[str, Any]) -> None:
    """Reject unauthorized operations before the journal writes a before event."""
    action = str(tool_name or "").removeprefix("memory_wiki_shared_block_")
    if action == "create":
        title = str(args.get("title") or "").strip()
        if not title or len(title) > 100 or provider._shared_block_secret_scan(title):
            raise ValueError("shared_block_access_denied")
        title_check = provider._inspect_recall_text(
            title, source="memory_wiki_shared_block", mem_type="title",
            audit=False, max_len=100,
        )
        if title_check.get("status") != "safe":
            raise ValueError("shared_block_access_denied")
        claim_ids = args.get("claim_ids")
        if not isinstance(claim_ids, list) or not 1 <= len(claim_ids) <= MAX_BLOCK_CLAIMS:
            raise ValueError("shared_block_access_denied")
        if len(set(str(value) for value in claim_ids)) != len(claim_ids):
            raise ValueError("shared_block_access_denied")
        for claim_id in claim_ids:
            row = _source_claim(provider, str(claim_id), require_owner_visible=True)
            if row is None or not _safe_claim_text(provider, row):
                raise ValueError("shared_block_access_denied")
    elif action in {"grant", "revoke", "retire"}:
        _owned_block(provider, _identifier(args.get("block_id"), field="block_id"))
    elif action in {"attach", "detach"}:
        bid = _identifier(args.get("block_id"), field="block_id")
        ptype, pid = _recipient_identity(provider, str(args.get("principal_type") or "").lower())
        row = provider._connect().execute("""SELECT 1 FROM shared_block_grants g
            JOIN shared_blocks b ON b.id=g.block_id
            WHERE g.block_id=? AND g.principal_type=? AND g.principal_id=?
              AND g.revoked_at=0 AND b.status='active'""", (bid, ptype, pid)).fetchone()
        if row is None:
            raise ValueError("shared_block_access_denied")


def _safe_claim_text(provider: Any, row: sqlite3.Row) -> str:
    # Reuse the same injection/secret guard as ordinary context packing.
    inspected = provider._inspect_recall_text(
        row["claim"], source="memory_wiki_shared_block", mem_type="claim",
        item_id=str(row["id"]), audit=False, max_len=700,
    )
    if inspected.get("status") != "safe":
        return ""
    text = str(inspected.get("content") or "").strip()
    if not text or provider._shared_block_secret_scan(text):
        return ""
    return text[:700]


def create_block(provider: Any, title: Any, claim_ids: Any) -> dict[str, Any]:
    if not isinstance(claim_ids, list) or not 1 <= len(claim_ids) <= MAX_BLOCK_CLAIMS:
        raise ValueError("invalid_shared_block_claim_ids")
    ids = [_identifier(value, field="claim_id") for value in claim_ids]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_shared_block_claim")
    title_text = str(title or "").strip()
    if not title_text or len(title_text) > 100 or provider._shared_block_secret_scan(title_text):
        raise ValueError("invalid_shared_block_title")
    checked_title = provider._inspect_recall_text(
        title_text, source="memory_wiki_shared_block", mem_type="title",
        audit=False, max_len=100,
    )
    if checked_title.get("status") != "safe":
        raise ValueError("invalid_shared_block_title")
    title_text = str(checked_title.get("content") or "").strip()[:100]
    if not title_text:
        raise ValueError("invalid_shared_block_title")
    refs = []
    total_chars = 0
    for claim_id in ids:
        row = _source_claim(provider, claim_id, require_owner_visible=True)
        if row is None:
            raise ValueError("shared_block_claim_unavailable")
        content = _safe_claim_text(provider, row)
        if not content:
            raise ValueError("shared_block_claim_unavailable")
        total_chars += len(content)
        refs.append({"claim_id": claim_id, "digest80": _digest(row)})
    if total_chars > MAX_BLOCK_CHARS:
        raise ValueError("shared_block_too_large")
    bot_id, chat_hash, _ = _actor(provider)
    block_id = "sblk_" + uuid.uuid4().hex[:20]
    stamp = int(time.time())
    conn = provider._connect()
    with conn:
        conn.execute("""INSERT INTO shared_blocks
            (id,owner_bot_id,owner_chat_hash,title,claim_refs_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)""",
            (block_id, bot_id, chat_hash, title_text,
             json.dumps(refs, separators=(",", ":")), stamp, stamp))
        _event(conn, provider, block_id, "create")
    return {"block_id": block_id, "title": title_text, "claim_count": len(refs)}


def grant_block(provider: Any, block_id: Any, principal_type: Any,
                principal_id: Any, *, revoke: bool = False) -> dict[str, Any]:
    bid = _identifier(block_id, field="block_id")
    ptype = str(principal_type or "").strip().lower()
    if ptype not in {"bot", "project"}:
        raise ValueError("invalid_shared_block_principal_type")
    pid = _principal_key(provider, ptype, _identifier(principal_id, field="principal_id"))
    block = _owned_block(provider, bid)
    if block["status"] != "active":
        raise ValueError("shared_block_not_found")
    conn = provider._connect()
    stamp = int(time.time())
    with conn:
        if revoke:
            updated = conn.execute("""UPDATE shared_block_grants SET revoked_at=?
                WHERE block_id=? AND principal_type=? AND principal_id=? AND revoked_at=0""",
                (stamp, bid, ptype, pid)).rowcount
            conn.execute("""UPDATE shared_block_attachments SET detached_at=?
                WHERE block_id=? AND principal_type=? AND principal_id=? AND detached_at=0""",
                (stamp, bid, ptype, pid))
            if not updated:
                raise ValueError("shared_block_grant_not_found")
            action = "revoke"
        else:
            conn.execute("""INSERT INTO shared_block_grants
                (block_id,principal_type,principal_id,granted_at,revoked_at)
                VALUES(?,?,?,?,0)
                ON CONFLICT(block_id,principal_type,principal_id)
                DO UPDATE SET granted_at=excluded.granted_at,revoked_at=0""",
                (bid, ptype, pid, stamp))
            action = "grant"
        _event(conn, provider, bid, action, ptype, pid)
    return {"block_id": bid, "principal_type": ptype,
            "principal_key": pid, "status": "revoked" if revoke else "granted"}


def attach_block(provider: Any, block_id: Any, principal_type: Any,
                 *, detach: bool = False) -> dict[str, Any]:
    bid = _identifier(block_id, field="block_id")
    ptype, pid = _recipient_identity(provider, str(principal_type or "").lower())
    conn = provider._connect()
    row = conn.execute("""SELECT g.* FROM shared_block_grants g
        JOIN shared_blocks b ON b.id=g.block_id
        WHERE g.block_id=? AND g.principal_type=? AND g.principal_id=?
          AND g.revoked_at=0 AND b.status='active'""",
        (bid, ptype, pid)).fetchone()
    if row is None:
        raise ValueError("shared_block_grant_not_found")
    stamp = int(time.time())
    with conn:
        if detach:
            updated = conn.execute("""UPDATE shared_block_attachments SET detached_at=?
                WHERE block_id=? AND principal_type=? AND principal_id=? AND detached_at=0""",
                (stamp, bid, ptype, pid)).rowcount
            if not updated:
                raise ValueError("shared_block_attachment_not_found")
            action = "detach"
        else:
            count = conn.execute("""SELECT count(*) FROM shared_block_attachments a
                JOIN shared_block_grants g USING(block_id,principal_type,principal_id)
                WHERE a.principal_type=? AND a.principal_id=?
                  AND a.detached_at=0 AND g.revoked_at=0""", (ptype, pid)).fetchone()[0]
            existing = conn.execute("""SELECT 1 FROM shared_block_attachments
                WHERE block_id=? AND principal_type=? AND principal_id=? AND detached_at=0""",
                (bid, ptype, pid)).fetchone()
            if count >= MAX_ATTACHED_BLOCKS and existing is None:
                raise ValueError("shared_block_attachment_limit")
            conn.execute("""INSERT INTO shared_block_attachments
                (block_id,principal_type,principal_id,attached_at,detached_at)
                VALUES(?,?,?,?,0)
                ON CONFLICT(block_id,principal_type,principal_id)
                DO UPDATE SET attached_at=excluded.attached_at,detached_at=0""",
                (bid, ptype, pid, stamp))
            action = "attach"
        _event(conn, provider, bid, action, ptype, pid)
    return {"block_id": bid, "principal_type": ptype,
            "status": "detached" if detach else "attached"}


def retire_block(provider: Any, block_id: Any) -> dict[str, Any]:
    bid = _identifier(block_id, field="block_id")
    _owned_block(provider, bid)
    conn = provider._connect()
    with conn:
        conn.execute("UPDATE shared_blocks SET status='retired',updated_at=? WHERE id=?",
                     (int(time.time()), bid))
        _event(conn, provider, bid, "retire")
    return {"block_id": bid, "status": "retired"}


def list_blocks(provider: Any) -> dict[str, Any]:
    bot_id, chat_hash, project_id = _actor(provider)
    conn = provider._connect()
    owned = conn.execute("""SELECT id,title,status,created_at FROM shared_blocks
        WHERE owner_bot_id=? AND owner_chat_hash=? ORDER BY created_at DESC LIMIT 50""",
        (bot_id, chat_hash)).fetchall()
    principals = [("bot", bot_id)] + ([("project", project_id)] if project_id else [])
    received = []
    for ptype, pid in principals:
        rows = conn.execute("""SELECT b.id,b.title,g.principal_type,g.principal_id,
            CASE WHEN a.detached_at=0 THEN 1 ELSE 0 END AS attached
            FROM shared_block_grants g JOIN shared_blocks b ON b.id=g.block_id
            LEFT JOIN shared_block_attachments a
              ON a.block_id=g.block_id AND a.principal_type=g.principal_type
              AND a.principal_id=g.principal_id
            WHERE g.principal_type=? AND g.principal_id=?
              AND g.revoked_at=0 AND b.status='active'
            ORDER BY g.granted_at DESC LIMIT 50""", (ptype, pid)).fetchall()
        for row in rows:
            item = dict(row)
            item["principal_key"] = item.pop("principal_id")
            received.append(item)
    return {"owned": [dict(row) for row in owned], "received": received[:50]}


def render_attached(provider: Any, *, max_chars: int = MAX_BLOCK_CHARS) -> list[dict[str, Any]]:
    bot_id, _, project_id = _actor(provider)
    conn = provider._connect()
    rows = conn.execute("""SELECT b.id,b.title,b.claim_refs_json
        FROM shared_block_attachments a
        JOIN shared_block_grants g USING(block_id,principal_type,principal_id)
        JOIN shared_blocks b ON b.id=a.block_id
        WHERE a.detached_at=0 AND g.revoked_at=0 AND b.status='active'
          AND ((a.principal_type='bot' AND a.principal_id=?)
            OR (a.principal_type='project' AND a.principal_id=? AND ?!=''))
        ORDER BY a.attached_at DESC LIMIT ?""",
        (bot_id, project_id, project_id, MAX_ATTACHED_BLOCKS)).fetchall()
    remaining = max(0, min(int(max_chars), MAX_BLOCK_CHARS))
    rendered = []
    seen_blocks: set[str] = set()
    for block in rows:
        if remaining < 40:
            break
        if block["id"] in seen_blocks:
            continue
        seen_blocks.add(block["id"])
        try:
            refs = json.loads(block["claim_refs_json"])
        except (TypeError, ValueError):
            continue
        if not isinstance(refs, list) or len(refs) > MAX_BLOCK_CLAIMS:
            continue
        claims = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            claim_id = str(ref.get("claim_id") or "")
            row = _source_claim(provider, claim_id, require_owner_visible=False)
            if row is None or _digest(row) != ref.get("digest80"):
                continue
            content = _safe_claim_text(provider, row)
            if content and len(content) + 4 <= remaining:
                claims.append({"claim_id": claim_id, "text": content})
                remaining -= len(content) + 4
        if claims:
            rendered.append({"block_id": block["id"], "title": block["title"], "claims": claims})
    return rendered
