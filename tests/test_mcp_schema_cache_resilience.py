#!/usr/bin/env python3
"""Regression: MCP discovery must not depend on a writable source checkout."""
from __future__ import annotations

import importlib.util
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


def test_schema_discovery_survives_unwritable_cache_location() -> None:
    module = load_server("memory_wiki_mcp_cache_resilience_test")

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

    with tempfile.TemporaryDirectory(prefix="mw-mcp-cache-") as tmp:
        module._SCHEMAS = None
        module._SCHEMA_MAP = {}
        module.SCHEMAS_FILE = Path(tmp) / "nonexistent-parent" / "tool_schemas.json"
        module.ensure_plugin = lambda: Provider()
        schemas = module.load_schemas()

    assert [schema["name"] for schema in schemas] == ["mw_query"]
    assert module._SCHEMA_MAP["mw_query"]["inputSchema"]["required"] == ["query"]


if __name__ == "__main__":
    test_schema_discovery_survives_unwritable_cache_location()
    print("PASS test_schema_discovery_survives_unwritable_cache_location")
