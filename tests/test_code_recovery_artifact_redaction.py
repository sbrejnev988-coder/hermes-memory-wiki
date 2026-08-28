#!/usr/bin/env python3
"""Regression: recovery copies of Code Shrinker events retain redacted navigation text only."""
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


def test_code_graph_recovery_artifact_redacts_pem_source_before_persistence() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-artifact-redact-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_artifact_redact_test")
            provider = module.MemoryWikiProvider(); provider.initialize("artifact-redact", hermes_home=tmp, agent_context="test")
            try:
                pem = "-----BEGIN PRIVATE KEY-----\nvery-secret-material\n-----END PRIVATE KEY-----"
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"; inbox.mkdir(parents=True, exist_ok=True)
                event = {
                    "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
                    "producer": "code-shrinker", "repository_id": "repo-artifact-redact", "event_id": "artifact-redact-event",
                    "snapshot_mode": "full", "snapshot_hash": "artifact-redact-hash",
                    "lines": [{"file_path": "src/key.py", "line_no": 1, "line_id": "line:repo-artifact-redact:src/key.py:1", "line_text": pem}],
                }
                (inbox / "event.json").write_text(json.dumps(event), encoding="utf-8")
                result = provider._drain_code_shrinker_events(limit=1)
                assert result["processed"] == 1, result
                artifact = next((home / "memory-wiki" / "recovery-artifacts" / "code-graph-inbox").glob("*.json"))
                saved = artifact.read_text(encoding="utf-8")
                assert pem not in saved
                assert "very-secret-material" not in saved
                assert "<REDACTED_PEM_BLOCK>" in saved
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_code_graph_recovery_artifact_redacts_pem_source_before_persistence()
    print("PASS test_code_graph_recovery_artifact_redacts_pem_source_before_persistence")
