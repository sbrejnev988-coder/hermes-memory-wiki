#!/usr/bin/env python3
"""Operator-attested, per-row ownership migration for legacy auxiliary rows.

Dry run is the default. Applying creates an SQLite online backup first and
never guesses an owner from the process's current chat or project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


TABLES = {"entities", "relations", "preference_rules", "review_queue", "secret_index"}
SCOPES = {"global", "bot", "chat", "private", "project"}
ATTESTATION = "I verified every graph row owner"


def _owner(record: dict[str, Any], instance_id: str) -> dict[str, str]:
    scope = str(record.get("visibility_scope") or "").lower()
    if scope not in SCOPES:
        raise ValueError("each row needs a valid visibility_scope")
    session_id = str(record.get("origin_session_id") or "")
    bot_id = str(record.get("origin_bot_id") or "")
    project_id = str(record.get("project_id") or "")
    if scope in {"chat", "private"} and not session_id:
        raise ValueError("chat/private row needs origin_session_id")
    if scope in {"bot", "chat", "private"} and not bot_id:
        raise ValueError("bot/chat/private row needs origin_bot_id")
    if scope == "project" and not project_id:
        raise ValueError("project row needs project_id")
    return {
        "visibility_scope": scope,
        "origin_bot_id": bot_id if scope in {"bot", "chat", "private"} else "",
        "origin_session_id": session_id if scope == "private" else "",
        "origin_chat_hash": hashlib.sha256(f"{instance_id}\0{session_id}".encode()).hexdigest()[:32] if scope == "chat" else "",
        "project_id": project_id if scope == "project" else "",
    }


def prepare(conn: sqlite3.Connection, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    records = mapping.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("mapping must contain a nonempty records array")
    salt_row = conn.execute("SELECT value FROM meta WHERE key='database_instance_id'").fetchone()
    if not salt_row:
        raise ValueError("database_instance_id is missing; run plugin migration first")
    instance_id = str(salt_row[0])
    seen: set[tuple[str, str]] = set()
    plan = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each record must be an object")
        table = str(record.get("table") or "")
        row_id = str(record.get("id") or "")
        if table not in TABLES or not row_id or (table, row_id) in seen:
            raise ValueError("invalid or duplicate graph table/id")
        seen.add((table, row_id))
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if row is None or str(row["visibility_scope"]) != "legacy":
            raise ValueError(f"{table}/{row_id} is missing or no longer legacy")
        owner = _owner(record, instance_id)
        source_claim_id = str(record.get("source_claim_id") or "")
        if source_claim_id and table not in {"entities", "relations"}:
            raise ValueError("source_claim_id applies only to graph rows")
        if source_claim_id:
            claim = conn.execute("SELECT * FROM claims WHERE id=?", (source_claim_id,)).fetchone()
            if claim is None or str(claim["visibility_scope"]) != owner["visibility_scope"]:
                raise ValueError("source claim is missing or has a different scope")
            for field in ("origin_bot_id", "origin_session_id", "origin_chat_hash", "project_id"):
                if owner[field] and str(claim[field] or "") != owner[field]:
                    raise ValueError("source claim belongs to a different owner")
        valid_from = max(0, int(record.get("valid_from") or 0))
        valid_to = max(0, int(record.get("valid_to") or 0))
        if valid_to and valid_to <= valid_from:
            raise ValueError("valid_to must exceed valid_from")
        if table not in {"entities", "relations"} and (valid_from or valid_to):
            raise ValueError("validity interval applies only to graph rows")
        plan.append({"table": table, "id": row_id, **owner,
                     "source_claim_id": source_claim_id,
                     "valid_from": valid_from, "valid_to": valid_to})
    return plan


def apply(conn: sqlite3.Connection, plan: list[dict[str, Any]]) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        count = 0
        for item in plan:
            fields = ["visibility_scope", "origin_bot_id", "origin_session_id", "origin_chat_hash", "project_id"]
            if item["table"] in {"entities", "relations"}:
                fields.extend(["source_claim_id", "valid_from", "valid_to"])
            result = conn.execute(
                f"UPDATE {item['table']} SET " + ",".join(f"{field}=?" for field in fields)
                + " WHERE id=? AND visibility_scope='legacy'",
                [item[field] for field in fields] + [item["id"]],
            )
            if result.rowcount != 1:
                raise RuntimeError("graph row changed since preflight")
            count += 1
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--attest", default="", help=f"Required with --apply: {ATTESTATION!r}")
    args = parser.parse_args()
    database = args.database.expanduser().resolve(strict=True)
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    if args.apply and args.attest != ATTESTATION:
        parser.error("--apply requires exact per-row ownership attestation")
    with sqlite3.connect(database.as_uri() + "?mode=rw", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        plan = prepare(conn, mapping)
        backup = None
        if args.apply:
            backup = database.with_name(database.name + ".pre-graph-migration-" + uuid.uuid4().hex[:12] + ".sqlite3")
            with sqlite3.connect(str(backup)) as destination:
                conn.backup(destination)
            count = apply(conn, plan)
        else:
            count = 0
    print(json.dumps({"rows_planned": len(plan), "rows_applied": count,
                      "backup": str(backup) if backup else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
