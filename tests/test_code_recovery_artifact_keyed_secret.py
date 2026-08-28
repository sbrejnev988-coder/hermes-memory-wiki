#!/usr/bin/env python3
"""Regression: keyed secrets in Code Shrinker event metadata never enter recovery artifacts."""
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


def test_code_graph_recovery_artifact_redacts_keyed_metadata_secrets() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-keyed-secret-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_keyed_secret_test")
            provider = module.MemoryWikiProvider(); provider.initialize("keyed-secret", hermes_home=tmp, agent_context="test")
            try:
                secret = "api-secret-SENTINEL-9e38a"
                camel_secret = "camel-api-secret-SENTINEL-b11f"
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"; inbox.mkdir(parents=True, exist_ok=True)
                event = {
                    "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
                    "producer": "code-shrinker", "repository_id": "repo-keyed-secret", "event_id": "keyed-secret-event",
                    "snapshot_mode": "full", "snapshot_hash": "keyed-secret-hash",
                    "metadata": {"api_key": secret, "apiKey": camel_secret, "authorization": f"Bearer {secret}"},
                    "lines": [{"file_path": "src/a.py", "line_no": 1, "line_id": "line:repo-keyed-secret:src/a.py:1", "line_text": "x = 1"}],
                }
                (inbox / "event.json").write_text(json.dumps(event), encoding="utf-8")
                result = provider._drain_code_shrinker_events(limit=1)
                assert result["processed"] == 1, result
                artifact = next((home / "memory-wiki" / "recovery-artifacts" / "code-graph-inbox").glob("*.json"))
                saved = artifact.read_text(encoding="utf-8")
                assert secret not in saved
                assert camel_secret not in saved
                assert "<REDACTED_KEYED_VALUE>" in saved
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_code_graph_recovery_artifact_redacts_keyed_metadata_secrets()
    print("PASS test_code_graph_recovery_artifact_redacts_keyed_metadata_secrets")
