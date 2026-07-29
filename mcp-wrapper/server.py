#!/usr/bin/env python3
"""Robust MCP stdio wrapper for Hermes Memory Wiki.

Keeps tools/list instant through a generated cache, but refreshes the in-memory
schema map after lazy provider loading so a stale cache can never permanently
block a tool that the provider actually supports.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SERVER_VERSION = "1.20.1-audit-fix-r1"
_PROVIDER = None
_SCHEMA_FILE = Path(__file__).with_name("tool_schemas.json")
_SCHEMAS: List[Dict[str, Any]] = []
_SCHEMA_MAP: Dict[str, Dict[str, Any]] = {}


def log(message: str) -> None:
    sys.stderr.write(f"[mw-mcp] {message}\n")
    sys.stderr.flush()


def send(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def error(request_id: Any, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": str(message)[:1000]}})


def _validate_schemas(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("tool schema cache must be a JSON array")
    result: List[Dict[str, Any]] = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each cached tool schema must be an object")
        name = str(item.get("name") or "").strip()
        params = item.get("parameters")
        if not name or name in seen or not isinstance(params, dict):
            raise ValueError(f"invalid or duplicate cached schema: {name!r}")
        seen.add(name)
        result.append(item)
    return result


def load_cached_schemas() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    with _SCHEMA_FILE.open("r", encoding="utf-8") as handle:
        schemas = _validate_schemas(json.load(handle))
    return schemas, {schema["name"]: schema for schema in schemas}


def _plugin_path() -> Path:
    configured = os.environ.get("MW_PLUGIN_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return (home / "plugins" / "memory-wiki" / "__init__.py").resolve()


def ensure_plugin() -> None:
    global _PROVIDER, _SCHEMAS, _SCHEMA_MAP
    if _PROVIDER is not None:
        return
    plugin_path = _plugin_path()
    if not plugin_path.is_file():
        raise FileNotFoundError(f"memory-wiki plugin not found: {plugin_path}")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_mcp", plugin_path,
        submodule_search_locations=[str(plugin_path.parent)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create import spec for {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "mcp_server",
        hermes_home=os.environ.get("HERMES_HOME"),
        agent_context="mcp_stdio",
    )
    live = _validate_schemas(provider.get_tool_schemas())
    _PROVIDER = provider
    live_map = {schema["name"]: schema for schema in live}
    if set(live_map) != set(_SCHEMA_MAP):
        missing = sorted(set(live_map) - set(_SCHEMA_MAP))
        stale = sorted(set(_SCHEMA_MAP) - set(live_map))
        log(f"Schema cache drift detected: missing={len(missing)} stale={len(stale)}; using live schemas")
    _SCHEMAS, _SCHEMA_MAP = live, live_map
    log(f"Plugin loaded ({len(live)} tools)")


def handle(req: Any) -> None:
    if not isinstance(req, dict) or req.get("jsonrpc") not in (None, "2.0"):
        error(req.get("id") if isinstance(req, dict) else None, -32600, "Invalid Request")
        return
    request_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    if not isinstance(params, dict):
        error(request_id, -32602, "params must be an object")
        return
    notification = request_id is None

    if method == "initialize":
        if not notification:
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memory-wiki", "version": SERVER_VERSION},
            }})
        return
    if method == "notifications/initialized":
        return
    if method == "ping":
        if not notification:
            send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        return
    if method == "tools/list":
        if not notification:
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": _SCHEMAS}})
        return
    if method != "tools/call":
        if not notification:
            error(request_id, -32601, f"Unknown method: {method}")
        return

    tool_name = str(params.get("name") or "")
    tool_args = params.get("arguments") or {}
    if not isinstance(tool_args, dict):
        error(request_id, -32602, "tool arguments must be an object")
        return
    # For an unknown cached name, lazy-load once before rejecting it. This
    # prevents a stale cache from hiding newly shipped provider tools.
    if tool_name not in _SCHEMA_MAP:
        try:
            ensure_plugin()
        except Exception as exc:
            if not notification:
                error(request_id, -32000, exc)
            return
    if tool_name not in _SCHEMA_MAP:
        if not notification:
            error(request_id, -32601, f"Unknown tool: {tool_name}")
        return
    try:
        ensure_plugin()
        result = _PROVIDER.handle_tool_call(tool_name, tool_args)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if not notification:
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": text}], "isError": False,
            }})
    except Exception as exc:
        if not notification:
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": str(exc)[:1000]}], "isError": True,
            }})


def main() -> int:
    global _SCHEMAS, _SCHEMA_MAP
    try:
        _SCHEMAS, _SCHEMA_MAP = load_cached_schemas()
    except Exception as exc:
        log(f"Schema cache load failed: {exc}; lazy provider load required")
        _SCHEMAS, _SCHEMA_MAP = [], {}
    log(f"Ready: {len(_SCHEMAS)} tools from cache")
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            error(None, -32700, f"Parse error: {exc.msg}")
            continue
        try:
            handle(request)
        except Exception as exc:
            log(f"Unhandled request error: {type(exc).__name__}: {exc}")
            request_id = request.get("id") if isinstance(request, dict) else None
            if request_id is not None:
                error(request_id, -32603, "Internal error")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
