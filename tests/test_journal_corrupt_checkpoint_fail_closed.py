#!/usr/bin/env python3
"""Regression: invalid historical checkpoints cannot be swapped into the live DB."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def insert_sentinel(provider) -> str:
    claim_id = "c_corrupt_checkpoint_sentinel"
    with provider._connect() as conn:
        conn.execute(
            """INSERT INTO claims(
                id,claim,topic,status,confidence,salience,source,evidence,
                created_at,updated_at,freshness_at,access_count,last_accessed,hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claim_id, "Original DB survives corrupt checkpoint.", "tests", "active", 0.9, 0.9,
             "test", "", 1, 1, 1, 0, 0, "corrupt-checkpoint-sentinel-hash"),
        )
    return claim_id


def test_corrupt_checkpoint_fails_before_live_database_swap() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-corrupt-checkpoint-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_corrupt_checkpoint_test")
            provider = module.MemoryWikiProvider()
            try:
                provider.initialize("corrupt-checkpoint-test", hermes_home=tmp, agent_context="test")
                sentinel = insert_sentinel(provider)
                original_db = provider.db_path
                checkpoint = provider._journal_checkpoint("corrupt-checkpoint")
                checkpoint_path = Path(checkpoint["path"])
                payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                for row in payload["tables"]["meta"]:
                    if row["key"] == "memory_revision":
                        row["value"] = "<redacted>"
                checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")

                provider._backup = lambda *_a, **_k: {}
                provider._preserve_db_files = lambda *_a, **_k: []
                provider._rebuild_fts = lambda: None
                provider._render_all = lambda: None
                provider._render_active_dashboard = lambda: None
                provider._audit = lambda *_a, **_k: None

                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=str(checkpoint_path))
                except (RuntimeError, ValueError):
                    pass
                else:
                    raise AssertionError("corrupt checkpoint was accepted for live database replacement")

                assert provider.db_path == original_db
                assert provider._connect().execute("SELECT 1 FROM claims WHERE id=?", (sentinel,)).fetchone()
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_corrupt_checkpoint_fails_before_live_database_swap()
    print("PASS test_corrupt_checkpoint_fails_before_live_database_swap")
