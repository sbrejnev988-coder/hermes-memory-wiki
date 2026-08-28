#!/usr/bin/env python3
"""Regression: recovery artifact registry stores only locator and integrity metadata."""
from __future__ import annotations

import importlib.util
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


def test_recovery_artifact_registry_excludes_payload_text() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-artifact-registry-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_artifact_registry_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("artifact-registry", hermes_home=tmp, agent_context="test")
            try:
                marker = "ARTIFACT_PAYLOAD_MUST_NOT_ENTER_SQLITE_4321"
                ref = provider._store_recovery_artifact("code_claim_request", {"claim": marker})
                row = provider._connect().execute(
                    "SELECT kind,sha256,size_bytes,relative_locator FROM recovery_artifacts WHERE sha256=?",
                    (ref["sha256"],),
                ).fetchone()
                assert row is not None
                assert tuple(row[:3]) == ("code_claim_request", ref["sha256"], ref["size_bytes"])
                dump = "\n".join(str(value) for value in row)
                assert marker not in dump
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_recovery_artifact_registry_excludes_payload_text()
    print("PASS test_recovery_artifact_registry_excludes_payload_text")
