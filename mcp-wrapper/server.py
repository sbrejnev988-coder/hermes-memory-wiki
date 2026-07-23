#!/usr/bin/env python3
"""MCP stdio wrapper for hermes-memory-wiki — instant tools/list via cached schemas."""
import sys, json, os

_provider = None
_SCHEMA_MAP = None
_SCHEMAS_FILE = os.path.join(os.path.dirname(__file__), "tool_schemas.json")

def log(msg):
    sys.stderr.write(f"[mw-mcp] {msg}\n")
    sys.stderr.flush()

def send(data):
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def load_schemas():
    """Instant — reads pre-generated JSON."""
    with open(_SCHEMAS_FILE) as f:
        return json.load(f), {s["name"]: s for s in json.load(open(_SCHEMAS_FILE))}

def ensure_plugin():
    """Lazy-load plugin on first tool call — 17s, only when actually used."""
    global _provider
    if _provider is not None:
        return
    import importlib.util
    from pathlib import Path
    plugin_path = os.environ.get("MW_PLUGIN_PATH",
        str(Path(os.environ.get("HERMES_HOME", str(Path.home()/".hermes"))) / "plugins" / "memory-wiki" / "__init__.py"))
    spec = importlib.util.spec_from_file_location("memory_wiki_mcp", plugin_path,
        submodule_search_locations=[str(Path(plugin_path).parent)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _provider = mod.MemoryWikiProvider()
    _provider.initialize("mcp_server", hermes_home=os.environ.get("HERMES_HOME"), agent_context="mcp_stdio")
    log(f"Plugin loaded ({len(_provider.get_tool_schemas())} tools)")

# Load schemas at startup — instant from JSON cache
_SCHEMAS, _SCHEMA_MAP = load_schemas()
log(f"Ready: {len(_SCHEMAS)} tools from cache")

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
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": _SCHEMAS}})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            if tool_name not in _SCHEMA_MAP:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown: {tool_name}"}})
                continue
            ensure_plugin()
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
        log(f"Error: {e}")
