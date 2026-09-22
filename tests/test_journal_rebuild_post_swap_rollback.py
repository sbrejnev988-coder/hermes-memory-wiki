#!/usr/bin/env python3
"""Regression: a post-swap rebuild failure restores the former SQLite bundle."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest


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


def test_post_swap_render_failure_restores_preexisting_live_claim() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-post-swap-") as tmp:
            os.environ.update({
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
            })
            module = load_provider("memory_wiki_post_swap_rollback_test")
            provider = module.MemoryWikiProvider()
            try:
                provider.initialize("post-swap-rollback", hermes_home=tmp, agent_context="test")
                sentinel_id = "c_post_swap_sentinel"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            sentinel_id,
                            "Pre-swap sentinel must survive a failed rebuilt render.",
                            "tests", "active", 0.9, 0.9, "test", "", 1, 1, 1, 0, 0,
                            "post-swap-rollback-sentinel-hash",
                        ),
                    )
                original_db = provider.db_path
                provider._backup = lambda *_a, **_k: {}
                provider._rebuild_fts = lambda: None
                provider._render_active_dashboard = lambda: None
                provider._audit = lambda *_a, **_k: None

                render_calls = 0

                def fail_only_after_swap() -> None:
                    nonlocal render_calls
                    render_calls += 1
                    if render_calls == 2:
                        raise RuntimeError("synthetic post-swap render failure")

                provider._render_all = fail_only_after_swap
                with pytest.raises(RuntimeError, match="synthetic post-swap render failure"):
                    provider._rebuild_from_journal(apply=True)

                assert render_calls == 2
                assert provider.db_path == original_db
                assert provider._connect().execute(
                    "SELECT 1 FROM claims WHERE id=?", (sentinel_id,)
                ).fetchone()
                assert any(
                    "failed_journal_rebuild" in str(path)
                    for path in provider.recovery_dir.rglob("*.sqlite3")
                )
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
    test_post_swap_render_failure_restores_preexisting_live_claim()
    print("PASS test_post_swap_render_failure_restores_preexisting_live_claim")
