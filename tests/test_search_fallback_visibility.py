#!/usr/bin/env python3
"""Regression: FTS fallback never exposes a private claim from another session."""
from __future__ import annotations

import importlib.util
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


def test_fallback_search_honors_private_visibility() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-fallback-visibility-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_fallback_visibility_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("other-session", hermes_home=tmp, agent_context="test")
            try:
                claim_id = "c_fallback_private"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash,
                            scope,visibility_scope,origin_session_id,quality,risk,quarantined_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            claim_id,
                            "Verified fallback isolation sentinel belongs only to another session.",
                            "tests", "active", 0.9, 0.9, "test", "private fallback regression fixture",
                            1, 1, 1, 0, 0, "fallback-private-claim-hash",
                            "private", "private", "other-session", 0.9, "low", 0,
                        ),
                    )
                provider.session_id = "viewer-session"
                rows = provider._search_fallback("fallback isolation sentinel", include_stale=True)
                assert claim_id not in {row["id"] for row in rows}
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
    test_fallback_search_honors_private_visibility()
    print("PASS test_fallback_search_honors_private_visibility")
