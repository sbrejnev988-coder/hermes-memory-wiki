#!/usr/bin/env python3
"""MCP stdio wrapper for hermes-memory-wiki — preloads plugin after initialize."""
import sys, json, os

_provider = None
_SCHEMAS = None
_SCHEMA_MAP = None
_loading = False

def log(msg):
    sys.stderr.write(f"[mw-mcp] {msg}\n")
    sys.stderr.flush()

def send(data):
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def load_plugin():
    global _provider, _SCHEMAS, _SCHEMA_MAP, _loading
    if _provider is not None:
        return True
    if _loading:
        return False
    _loading = True
    try:
        import importlib.util
        from pathlib import Path
        plugin_path = os.environ.get("MW_PLUGIN_PATH", str(Path(os.environ.get("HERMES_HOME", str(Path.home()/".hermes"))) / "plugins" / "memory-wiki" / "__init__.py"))
        spec = importlib.util.spec_from_file_location("memory_wiki_mcp", plugin_path, submodule_search_locations=[str(Path(plugin_path).parent)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _provider = mod.MemoryWikiProvider()
        _provider.initialize("mcp_server", hermes_home=os.environ.get("HERMES_HOME"), agent_context="mcp_stdio")
        _SCHEMAS = _provider.get_tool_schemas()
        _SCHEMA_MAP = {s["name"]: s for s in _SCHEMAS}
        log(f"Loaded {len(_SCHEMAS)} tools")
        _loading = False
        return True
    except Exception as e:
        log(f"Load failed: {e}")
        _loading = False
        return False

# Eager load on startup — before any gateway requests come in
log("Starting eager load...")
load_plugin()

while True:
    try:
        line = sys.stdin.readline()
        if not line: break
        req = json.loads(line)
        mid = req.get("id")
        method = req.get("method")
        params = req.get("params", {})
        
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memory-wiki", "version": "1.18.3"}
            }})
        elif method == "tools/list":
            if not _SCHEMAS:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": "Still loading plugin"}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                    {"name": s["name"], "description": s.get("description",""), "inputSchema": s.get("parameters", s.get("inputSchema", {"type":"object","properties":{}}))}
                    for s in _SCHEMAS
                ]}})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            if not _SCHEMA_MAP or tool_name not in _SCHEMA_MAP:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown: {tool_name}"}})
                continue
            try:
                result = _provider.handle_tool_call(tool_name, tool_args)
                text = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, dict) else str(result)
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": str(e)[:500]}})
        elif method == "notifications/initialized":
            pass
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown: {method}"}})
    except json.JSONDecodeError:
        pass
    except Exception as e:
        log(f"Loop error: {e}")
        continue
