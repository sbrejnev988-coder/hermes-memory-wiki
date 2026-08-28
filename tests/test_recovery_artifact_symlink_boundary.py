#!/usr/bin/env python3
"""Regression: recovery artifact storage rejects symlink/reparse traversal."""
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


def test_recovery_artifact_store_rejects_symlinked_kind_directory() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-artifact-symlink-") as tmp:
            home = Path(tmp); outside = home / "outside"; outside.mkdir()
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_artifact_symlink_test")
            provider = module.MemoryWikiProvider(); provider.initialize("artifact-symlink", hermes_home=tmp, agent_context="test")
            link = home / "memory-wiki" / "recovery-artifacts" / "code_claim_request"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
                return  # Windows privilege/filesystem does not permit symlink fixtures here.
            try:
                try:
                    provider._store_recovery_artifact("code_claim_request", {"claim": "safe"})
                except ValueError as exc:
                    assert "symlink" in str(exc).lower() or "reparse" in str(exc).lower()
                else:
                    raise AssertionError("recovery artifact store accepted a symlinked kind directory")
                assert not list(outside.iterdir())
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_recovery_artifact_store_rejects_symlinked_kind_directory()
    print("PASS test_recovery_artifact_store_rejects_symlinked_kind_directory")
