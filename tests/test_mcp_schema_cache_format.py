#!/usr/bin/env python3
"""Regression: the persisted cache keeps native provider schema names."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "mcp-wrapper" / "server.py"


def load_server(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_wrapper_cache_preserves_native_schema_names() -> None:
    module = load_server("memory_wiki_mcp_cache_format_test")

    class Provider:
        @staticmethod
        def get_tool_schemas():
            return [
                {
                    "name": "memory_wiki_query",
                    "description": "query",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ]

    with tempfile.TemporaryDirectory(prefix="mw-mcp-cache-format-") as tmp:
        cache = Path(tmp) / "tool_schemas.json"
        module._SCHEMAS = None
        module._SCHEMA_MAP = {}
        module.SCHEMAS_FILE = cache
        module.ensure_plugin = lambda: Provider()
        wrapper_schemas = module.load_schemas()
        cached_schemas = json.loads(cache.read_text(encoding="utf-8"))

    assert wrapper_schemas[0]["name"] == "mw_query"
    assert cached_schemas[0]["name"] == "memory_wiki_query"
    assert "parameters" in cached_schemas[0]
    assert "inputSchema" not in cached_schemas[0]


if __name__ == "__main__":
    test_wrapper_cache_preserves_native_schema_names()
    print("PASS test_wrapper_cache_preserves_native_schema_names")
