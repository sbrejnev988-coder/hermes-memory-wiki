#!/usr/bin/env python3
"""Regression: a live MCP session must never rewrite packaged schemas."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path


SOURCE_WRAPPER = Path(__file__).resolve().parents[1] / "mcp-wrapper"


def load_server(server: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, server)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_live_schema_refresh_does_not_rewrite_packaged_cache() -> None:
    previous_home = os.environ.get("HERMES_HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="mw-mcp-runtime-cache-") as tmp:
            root = Path(tmp)
            wrapper = root / "package" / "mcp-wrapper"
            shutil.copytree(SOURCE_WRAPPER, wrapper)
            packaged_cache = wrapper / "tool_schemas.json"
            before = packaged_cache.read_bytes()
            os.environ["HERMES_HOME"] = str(root / "runtime-home")
            module = load_server(wrapper / "server.py", "memory_wiki_mcp_runtime_cache_test")

            class Provider:
                @staticmethod
                def get_tool_schemas():
                    return [
                        {
                            "name": "memory_wiki_query",
                            "description": "fresh runtime schema",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        }
                    ]

            module.ensure_plugin = lambda: Provider()
            module.load_schemas()

            assert packaged_cache.read_bytes() == before
            assert module.SCHEMAS_FILE.is_file()
            assert module.SCHEMAS_FILE.parent != wrapper
    finally:
        if previous_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous_home


if __name__ == "__main__":
    test_live_schema_refresh_does_not_rewrite_packaged_cache()
    print("PASS test_live_schema_refresh_does_not_rewrite_packaged_cache")
