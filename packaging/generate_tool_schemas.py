#!/usr/bin/env python3
"""Generate or verify the packaged MCP schema cache from the native provider."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "mcp-wrapper" / "tool_schemas.json"


def _manifest_tool_names() -> list[str]:
    names: list[str] = []
    in_tools = False
    for raw_line in (ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines():
        if raw_line.strip() == "provides_tools:":
            in_tools = True
            continue
        if not in_tools:
            continue
        if raw_line.startswith("  - "):
            names.append(raw_line[4:].strip())
            continue
        if raw_line and not raw_line.startswith((" ", "\t")):
            break
    return names


def _runtime_schemas() -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="mw-schema-build-") as temp_home:
        previous = {key: os.environ.get(key) for key in (
            "HERMES_HOME",
            "HERMES_SECURITY_STRICT",
            "MEMORY_WIKI_SEMANTIC",
            "MEMORY_WIKI_EPISODIC_SEMANTIC",
            "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE",
            "MEMORY_WIKI_GRAPH_AUTO_EXTRACT",
            "MW_EXTRACTION_ENABLED",
        )}
        os.environ.update({
            "HERMES_HOME": temp_home,
            "HERMES_SECURITY_STRICT": "0",
            "MEMORY_WIKI_SEMANTIC": "0",
            "MEMORY_WIKI_EPISODIC_SEMANTIC": "0",
            "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
            "MEMORY_WIKI_GRAPH_AUTO_EXTRACT": "0",
            "MW_EXTRACTION_ENABLED": "0",
        })
        module_name = "memory_wiki_schema_build"
        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                ROOT / "__init__.py",
                submodule_search_locations=[str(ROOT)],
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("could not load native provider")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            schemas = module.MemoryWikiProvider().get_tool_schemas()
        finally:
            sys.modules.pop(module_name, None)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    if not isinstance(schemas, list) or not all(isinstance(item, dict) for item in schemas):
        raise RuntimeError("provider returned an invalid schema list")
    return schemas


def _render(schemas: list[dict[str, Any]]) -> str:
    names = [str(item.get("name") or "") for item in schemas]
    if not names or any(not name for name in names):
        raise RuntimeError("runtime schema contains an empty tool name")
    if len(names) != len(set(names)):
        raise RuntimeError("runtime schema contains duplicate tool names")
    manifest_names = _manifest_tool_names()
    if names != manifest_names:
        raise RuntimeError("plugin.yaml tool list differs from runtime schemas")
    return json.dumps(schemas, ensure_ascii=False, indent=2) + "\n"


def _generation_failed(stage: str) -> int:
    # A setup/import/validation/I/O failure is not evidence of cache staleness.
    print(f"MCP_SCHEMA_GENERATION_FAILED stage={stage}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the packaged schema cache is stale instead of rewriting it",
    )
    args = parser.parse_args(argv)
    try:
        schemas = _runtime_schemas()
    except Exception:
        return _generation_failed("native_export")
    try:
        rendered = _render(schemas)
    except Exception:
        return _generation_failed("schema_validation")
    if args.check:
        try:
            current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        except (OSError, UnicodeError):
            return _generation_failed("cache_read")
        if current != rendered:
            print("MCP_SCHEMA_CACHE_STALE", file=sys.stderr)
            return 2
        print(f"MCP_SCHEMA_CACHE_OK tools={len(schemas)}")
        return 0
    try:
        TARGET.write_text(rendered, encoding="utf-8", newline="\n")
    except (OSError, UnicodeError):
        return _generation_failed("cache_write")
    print(f"MCP_SCHEMA_CACHE_WRITTEN tools={len(schemas)} path={TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
