#!/usr/bin/env python3
"""Recovery must reject a published checkpoint whose manifest digest no longer matches."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_checkpoint_manifest_digest_mismatch_blocks_rebuild_before_swap() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-checkpoint-manifest-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_checkpoint_manifest_test")
            provider = module.MemoryWikiProvider(); provider.initialize("checkpoint-manifest", hermes_home=tmp, agent_context="test")
            try:
                sentinel = "c_checkpoint_manifest_sentinel"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                           created_at,updated_at,freshness_at,access_count,last_accessed,hash)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sentinel, "Live state must survive a mismatched checkpoint manifest.", "tests", "active", .9, .9,
                         "test", "", 1, 1, 1, 0, 0, "checkpoint-manifest-sentinel-hash"),
                    )
                checkpoint = provider._journal_checkpoint("valid-checkpoint")
                path = Path(checkpoint["path"])
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["name"] = "tampered-but-still-parseable"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=str(path))
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("checkpoint with a mismatched manifest digest was accepted")
                assert provider._connect().execute("SELECT 1 FROM claims WHERE id=?", (sentinel,)).fetchone()
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_checkpoint_manifest_digest_mismatch_blocks_rebuild_before_swap()
    print("PASS test_checkpoint_manifest_digest_mismatch_blocks_rebuild_before_swap")
