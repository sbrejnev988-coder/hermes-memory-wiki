#!/usr/bin/env python3
"""Self-healing MCP wrapper for Hermes Memory Wiki.

Unlike the old wrapper, this server does not fail at process start when
`tool_schemas.json` is missing. It can build a synchronized schema cache from
MemoryWikiProvider.get_tool_schemas().
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_PROVIDER = None
_SCHEMAS: list[dict[str, Any]] | None = None
_SCHEMA_MAP: dict[str, dict[str, Any]] = {}
BASE_DIR = Path(__file__).resolve().parent
PACKAGED_SCHEMAS_FILE = BASE_DIR / "tool_schemas.json"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
SCHEMAS_FILE = Path(
    os.environ.get(
        "MW_MCP_SCHEMA_CACHE",
        str(HERMES_HOME / "cache" / "memory-wiki" / "mcp-tool-schemas.json"),
    )
).expanduser()
PLUGIN_PATH = Path(
    os.environ.get(
        "MW_PLUGIN_PATH",
        str(HERMES_HOME / "plugins" / "memory-wiki" / "__init__.py"),
    )
).expanduser()


def manifest_version() -> str:
    """Read the co-located plugin version without importing the provider."""
    manifest = PLUGIN_PATH.parent / "plugin.yaml"
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.partition(":")[2].strip().strip('"\'')
    except OSError:
        pass
    return "unknown"


def log(message: str) -> None:
    sys.stderr.write(f"[mw-mcp] {message}\n")
    sys.stderr.flush()


def send(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def redact_error_message(message: Any) -> str:
    """Keep wrapper failures useful without leaking common credential forms."""
    text = str(message or "")
    text = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"(?i)(\bbearer\s+)([^\s,;]+)", r"\1<redacted>", text)
    text = re.sub(
        r"(?i)(\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*)(?:\"[^\"]*\"|\x27[^\x27]*\x27|[^\s,;]+)",
        r"\1<redacted>",
        text,
    )
    return re.sub(
        r"(?<![A-Za-z0-9_-])(?:sk-(?:proj-)?|sk_|ghp_)[A-Za-z0-9_-]{16,}",
        "<redacted>",
        text,
    )[:1000]


def ensure_plugin():
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    if not PLUGIN_PATH.is_file():
        raise FileNotFoundError(f"Memory Wiki plugin not found: {PLUGIN_PATH}")
    spec = importlib.util.spec_from_file_location(
        "mw_mcp",
        PLUGIN_PATH,
        submodule_search_locations=[str(PLUGIN_PATH.parent)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to create import spec for {PLUGIN_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "mw_mcp",
        hermes_home=str(HERMES_HOME),
        agent_context="mcp",
    )
    _PROVIDER = provider
    log("Plugin loaded")
    return provider


def mcp_name(plugin_name: str) -> str:
    if plugin_name.startswith("memory_wiki_"):
        return "mw_" + plugin_name[len("memory_wiki_"):]
    return plugin_name


def plugin_name(mcp_tool_name: str) -> str:
    if mcp_tool_name.startswith("mw_"):
        return "memory_wiki_" + mcp_tool_name[3:]
    return mcp_tool_name


def normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    name = mcp_name(str(schema.get("name") or ""))
    parameters = schema.get("inputSchema")
    if not isinstance(parameters, dict):
        parameters = schema.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}, "required": []}
    parameters.setdefault("type", "object")
    parameters.setdefault("properties", {})
    parameters.setdefault("required", [])
    return {
        "name": name,
        "description": str(schema.get("description") or ""),
        "inputSchema": parameters,
    }


def load_schemas() -> list[dict[str, Any]]:
    global _SCHEMAS, _SCHEMA_MAP
    if _SCHEMAS is not None:
        return _SCHEMAS

    provider = ensure_plugin()
    raw = provider.get_tool_schemas()
    native_schemas = [item for item in raw if isinstance(item, dict)]
    schemas = [normalize_schema(item) for item in native_schemas]
    schemas = [item for item in schemas if item.get("name")]
    if not schemas:
        raise RuntimeError("MemoryWikiProvider.get_tool_schemas() returned no tools")

    temporary = SCHEMAS_FILE.with_suffix(".json.tmp")
    try:
        SCHEMAS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(native_schemas, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(SCHEMAS_FILE)
    except OSError as exc:
        # Discovery must remain usable for immutable plugin installs.
        log(f"Schema cache was not persisted: {type(exc).__name__}")

    _SCHEMAS = schemas
    _SCHEMA_MAP = {item["name"]: item for item in schemas}
    log(f"Ready: {len(schemas)} synchronized tools")
    return schemas


def error_response(message_id, code: int, message: str) -> None:
    send({
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": redact_error_message(message)},
    })


def main() -> int:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            error_response(None, -32700, "Parse error")
            continue

        if not isinstance(request, dict):
            error_response(None, -32600, "Invalid Request")
            continue
        if request.get("jsonrpc") != "2.0":
            error_response(request.get("id"), -32600, "Invalid Request")
            continue
        message_id = request.get("id")
        is_notification = "id" not in request

        def respond(data: dict[str, Any]) -> None:
            if not is_notification:
                send(data)

        def respond_error(code: int, message: str) -> None:
            if not is_notification:
                error_response(message_id, code, message)

        method = request.get("method")
        if not isinstance(method, str) or not method:
            respond_error(-32600, "Invalid Request")
            continue
        raw_params = request.get("params")
        if raw_params is None:
            params = {}
        elif not isinstance(raw_params, dict):
            respond_error(-32602, "Invalid params")
            continue
        else:
            params = raw_params
        try:
            if method == "initialize":
                respond({
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mw", "version": manifest_version()},
                    },
                })
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                respond({
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {"tools": load_schemas()},
                })
            elif method == "tools/call":
                schemas = load_schemas()
                tool_name = str(params.get("name") or "")
                if tool_name not in _SCHEMA_MAP:
                    respond_error(-32601, f"Unknown tool: {tool_name}")
                    continue
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    respond_error(-32602, "Invalid params")
                    continue
                result = ensure_plugin().handle_tool_call(plugin_name(tool_name), arguments)
                text = (
                    json.dumps(result, ensure_ascii=False, default=str)
                    if isinstance(result, (dict, list))
                    else str(result)
                )
                respond({
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {"content": [{"type": "text", "text": text}]},
                })
            else:
                respond_error(-32601, f"Unknown method: {method}")
        except Exception as exc:
            safe_error = redact_error_message(f"{type(exc).__name__}: {exc}")
            log(f"Error: {safe_error}")
            respond_error(-32000, safe_error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
