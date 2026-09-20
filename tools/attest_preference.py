#!/usr/bin/env python3
"""Review and activate one scoped preference candidate from a trusted host shell.

Dry run is the default. This script is intentionally outside the model-facing
tool registry. It never assigns or widens a row's existing owner or scope.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any


ATTESTATION = "I reviewed this exact preference rule"
BUILTIN_IDS = {
    "pref_current_instruction", "pref_user_correction", "pref_pinned_durable",
    "pref_verified_state", "pref_stale_memory",
}
OWNER_COLUMNS = (
    "visibility_scope", "origin_bot_id", "origin_session_id",
    "origin_chat_hash", "project_id",
)
DIGEST_FIELDS = (
    "rule", "priority", "scope", "visibility_scope", "origin_bot_id",
    "origin_session_id", "origin_chat_hash", "project_id",
)
REQUIRED_OWNER = {
    "global": (),
    "bot": ("origin_bot_id",),
    "chat": ("origin_bot_id", "origin_chat_hash"),
    "private": ("origin_bot_id", "origin_session_id"),
    "project": ("project_id",),
}


def _secret_scan(rule: str) -> bool:
    """Use the plugin's own secret detector, so the CLI cannot drift from it."""
    plugin = Path(__file__).resolve().parents[1] / "__init__.py"
    module_name = "memory_wiki_host_preference_validation"
    spec = importlib.util.spec_from_file_location(
        module_name, plugin, submodule_search_locations=[str(plugin.parent)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Memory Wiki secret scanner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return bool(module.secret_scan(rule).get("raw_secret"))
    finally:
        sys.modules.pop(module_name, None)


def _fetch(conn: sqlite3.Connection, row_id: str) -> sqlite3.Row:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(preference_rules)")}
    required = {
        "id", "rule", "priority", "scope", "source", "status",
        "created_at", "updated_at", "hash", *OWNER_COLUMNS,
    }
    if not required.issubset(columns):
        raise ValueError("preference_rules ownership schema is incomplete")
    row = conn.execute("SELECT * FROM preference_rules WHERE id=?", (row_id,)).fetchone()
    if row is None:
        raise ValueError("preference rule not found")
    return row


def _review(row: sqlite3.Row) -> dict[str, Any]:
    row_id = str(row["id"] or "")
    if row_id in BUILTIN_IDS or str(row["source"] or "") == "system":
        raise ValueError("built-in preference rules cannot be attested here")
    if str(row["status"] or "") == "retired":
        raise ValueError("retired preference rules cannot be attested")
    if str(row["status"] or "") != "pending" or str(row["source"] or "") != "model_candidate":
        raise ValueError("only pending model candidates can be attested")
    scope = str(row["visibility_scope"] or "").lower()
    if scope not in REQUIRED_OWNER:
        raise ValueError("legacy or unknown preference ownership cannot be attested")
    owner = {column: str(row[column] or "") for column in OWNER_COLUMNS}
    for column in REQUIRED_OWNER[scope]:
        if not owner[column]:
            raise ValueError(f"preference owner is missing {column}")
    if scope == "chat" and not re.fullmatch(r"[0-9a-f]{32}", owner["origin_chat_hash"]):
        raise ValueError("preference chat owner hash is malformed")
    rule = str(row["rule"] or "")
    if not rule.strip():
        raise ValueError("empty preference rule cannot be attested")
    if _secret_scan(rule):
        raise ValueError("preference rule contains raw secret-like material")
    return {
        "id": row_id,
        "rule": rule,
        "priority": int(row["priority"]),
        "scope": str(row["scope"]),
        "source_before": str(row["source"]),
        "status_before": str(row["status"]),
        "hash": str(row["hash"]),
        "owner": owner,
        "created_at": int(row["created_at"]),
        "updated_at_before": int(row["updated_at"]),
    }


def _backup(conn: sqlite3.Connection, database: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = database.with_name(
        f"{database.name}.pre-preference-attestation-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
    )
    with closing(sqlite3.connect(backup)) as destination:
        conn.backup(destination)
    backup.chmod(0o600)
    return backup


def _attestation_digest(reviewed: dict[str, Any]) -> str:
    payload = {
        "rule": reviewed["rule"],
        "priority": reviewed["priority"],
        "scope": reviewed["scope"],
        **reviewed["owner"],
    }
    canonical = json.dumps(
        {field: payload[field] for field in DIGEST_FIELDS},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_attestation_table(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(preference_attestations)")
    }
    if not {"rule_id", "rule_digest", "attested_at", "attested_by"}.issubset(columns):
        raise ValueError("preference_attestations schema is missing; initialize the updated plugin first")


def attest(
    conn: sqlite3.Connection, database: Path, row_id: str, expected_digest: str,
) -> dict[str, Any]:
    """Back up first; activate only if the exact reviewed row is still present."""
    reviewed = _review(_fetch(conn, row_id))
    _require_attestation_table(conn)
    if _attestation_digest(reviewed) != expected_digest:
        raise ValueError("preference rule changed since dry-run; review it again")
    backup = _backup(conn, database)
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = _review(_fetch(conn, row_id))
        if current != reviewed or _attestation_digest(current) != expected_digest:
            raise RuntimeError("preference rule changed after review; no update applied")
        digest = _attestation_digest(reviewed)
        attested_at = int(time.time())
        attested_by = "host_cli:" + getpass.getuser()
        conn.execute(
            """INSERT INTO preference_attestations(rule_id,rule_digest,attested_at,attested_by)
               VALUES(?,?,?,?)
               ON CONFLICT(rule_id) DO UPDATE SET
                 rule_digest=excluded.rule_digest,
                 attested_at=excluded.attested_at,
                 attested_by=excluded.attested_by""",
            (row_id, digest, attested_at, attested_by),
        )
        updated = conn.execute(
            """UPDATE preference_rules
               SET source='host_attested:user',status='active',updated_at=?
               WHERE id=? AND source='model_candidate' AND status='pending' AND updated_at=?""",
            (attested_at, row_id, reviewed["updated_at_before"]),
        )
        if updated.rowcount != 1:
            raise RuntimeError("preference rule changed; no update applied")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {**reviewed, "applied": True, "backup": str(backup),
            "attestation_digest": digest, "attested_at": attested_at,
            "attested_by": attested_by,
            "source_after": "host_attested:user", "status_after": "active"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Memory Wiki SQLite database")
    parser.add_argument("--id", required=True, help="Exact preference_rules.id")
    parser.add_argument("--apply", action="store_true", help="Activate the reviewed candidate")
    parser.add_argument("--attest", default="", help=f"With --apply, pass: {ATTESTATION!r}")
    parser.add_argument("--expected-digest", default="", help="SHA-256 digest printed by a prior dry-run")
    args = parser.parse_args()
    if args.apply and args.attest != ATTESTATION:
        parser.error("--apply requires the exact attestation phrase")
    if args.apply and not re.fullmatch(r"[0-9a-f]{64}", args.expected_digest):
        parser.error("--apply requires --expected-digest from a prior dry-run")
    database = args.database.expanduser().resolve(strict=True)
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if args.apply:
            result = attest(conn, database, args.id, args.expected_digest)
        else:
            reviewed = _review(_fetch(conn, args.id))
            _require_attestation_table(conn)
            result = {**reviewed, "applied": False, "backup": None,
                      "attestation_digest": _attestation_digest(reviewed)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
