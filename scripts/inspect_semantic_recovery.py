#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 4.0):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    api_key = os.environ.get("MEMORY_WIKI_QDRANT_API_KEY", "")
    if api_key:
        headers["api-key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Memory Wiki semantic recovery diagnostics")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    args = parser.parse_args()

    home = Path(args.hermes_home).expanduser().resolve()
    db_path = home / "memory-wiki" / "memory_wiki.sqlite3"
    qdrant_url = os.environ.get("MEMORY_WIKI_QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
    alias = os.environ.get("MEMORY_WIKI_QDRANT_ALIAS", "memory_wiki_claims_active").strip() or "memory_wiki_claims_active"

    report: dict = {
        "hermes_home": str(home),
        "database": str(db_path),
        "database_exists": db_path.exists(),
        "qdrant_url": qdrant_url,
        "alias": alias,
    }

    aliases = http_json("GET", f"{qdrant_url}/aliases")
    report["alias_api_supported"] = "_error" not in aliases and isinstance(((aliases.get("result") or {}).get("aliases")), list)
    report["alias_probe"] = aliases if report["alias_api_supported"] else {"error": aliases.get("_error", "unsupported response")}

    collections = http_json("GET", f"{qdrant_url}/collections")
    collection_names = []
    if "_error" not in collections:
        collection_names = [str(item.get("name") or "") for item in ((collections.get("result") or {}).get("collections") or [])]
    report["collections"] = [name for name in collection_names if name]

    if db_path.exists():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            outbox = conn.execute(
                """SELECT status,count(*) n FROM index_outbox GROUP BY status ORDER BY status"""
            ).fetchall()
            report["outbox"] = {str(row["status"]): int(row["n"] or 0) for row in outbox}
            errors = conn.execute(
                """SELECT substr(last_error,1,180) error,count(*) n
                   FROM index_outbox WHERE status='failed'
                   GROUP BY substr(last_error,1,180) ORDER BY n DESC LIMIT 20"""
            ).fetchall()
            report["failed_error_groups"] = [dict(row) for row in errors]
            meta = {str(row[0]): str(row[1]) for row in conn.execute(
                "SELECT key,value FROM meta WHERE key IN ('memory_revision','qdrant_latest_revision','semantic_enabled')"
            ).fetchall()}
            report["meta"] = meta
        finally:
            conn.close()

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
