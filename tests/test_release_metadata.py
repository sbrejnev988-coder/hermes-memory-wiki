#!/usr/bin/env python3
"""Release contract: observable health metadata must match plugin.yaml."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "__init__.py"
MANIFEST = ROOT / "plugin.yaml"


def manifest_version() -> str:
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.partition(":")[2].strip().strip('"\'')
    raise AssertionError("plugin.yaml has no version")


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(ROOT)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_health_version_matches_manifest() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-release-metadata-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_release_metadata_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("release-metadata-test", hermes_home=tmp, agent_context="test")
            try:
                assert provider._health()["version"] == manifest_version()
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
    test_health_version_matches_manifest()
    print("PASS test_health_version_matches_manifest")
