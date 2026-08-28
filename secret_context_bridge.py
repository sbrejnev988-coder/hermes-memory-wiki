"""Read-through bridge from Memory Wiki to secret-context and Vault Registry.

The bridge never persists or intentionally exposes plaintext secrets. It first
tries the installed plugin search handler, then independently reads safe metadata
from ``~/.hermes/vault/secrets_registry.json`` so a SQLite-only plugin index cannot
make vault-only records invisible.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    from .vault_registry_adapter import (
        registry_status as _registry_status,
        search_registry_metadata as _search_registry_metadata,
    )
except Exception:
    try:
        from vault_registry_adapter import (
            registry_status as _registry_status,
            search_registry_metadata as _search_registry_metadata,
        )
    except Exception:
        def _search_registry_metadata(*args, **kwargs): return []
        def _registry_status(*args, **kwargs):
            return {"available": False, "error": "adapter_import_failed", "entries": 0}

_TARGET_TOOLS = {"secret_context_lookup", "secret_context_search"}
_CACHE_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {
    "path": "",
    "mtime_ns": 0,
    "handlers": {},
    "error": "",
}

# Exact names that may contain plaintext.  Identifier/policy fields such as
# secret_id, secret_type and has_value are deliberately not included.
_SENSITIVE_KEYS = {
    "value", "plaintext", "plain", "password", "passwd", "passphrase",
    "token", "api_key", "apikey", "access_key", "secret_access_key",
    "private_key", "client_secret", "credential", "credentials", "auth",
    "authorization", "cookie", "session_cookie", "totp_seed", "seed",
}
_SAFE_IDENTIFIER_KEYS = {
    "id", "key", "name", "context_key", "lookup_key", "secret_id",
    "secret_type", "subject", "scope", "service", "server", "locator",
    "purpose", "description", "source", "status", "has_value", "aliases",
    "alias", "policy", "allowed_executors", "require_user_approval",
    "namespace", "environment", "host", "url", "endpoint", "metadata",
}

_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|token|api[_-]?key|client[_-]?secret|"
    r"secret[_-]?access[_-]?key|authorization|cookie|totp[_-]?seed)\b\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDS_RE = re.compile(r"(?i)(https?://)([^/@:\s]+):([^/@\s]+)@")
_PEM_RE = re.compile(r"-----BEGIN [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----[\s\S]*?-----END [^-]+-----", re.I)


def _redact_string(value: Any, max_chars: int = 1200) -> str:
    text = str(value or "")
    text = _PEM_RE.sub("<redacted-private-key>", text)
    text = _URL_CREDS_RE.sub(r"\1<redacted>:<redacted>@", text)
    text = _ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def _safe_value(value: Any, key: str = "", depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    key_l = str(key or "").strip().lower()
    if key_l in _SENSITIVE_KEYS:
        return "<redacted>" if value not in (None, "", False) else value
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= 100:
                out["_truncated"] = True
                break
            child_key = str(raw_key)[:120]
            child_key_l = child_key.lower()
            # Unknown fields whose names strongly imply plaintext are redacted.
            if child_key_l not in _SAFE_IDENTIFIER_KEYS and any(
                marker in child_key_l
                for marker in ("password", "passwd", "token", "api_key", "apikey", "private_key", "secret_value", "client_secret", "credential_value")
            ):
                out[child_key] = "<redacted>" if raw_value not in (None, "", False) else raw_value
            else:
                out[child_key] = _safe_value(raw_value, child_key, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(v, key, depth + 1) for v in list(value)[:100]]
    if isinstance(value, bytes):
        return _redact_string(value.decode("utf-8", "replace"))
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_string(value)


class _CaptureContext:
    """Minimal PluginContext substitute used only to capture tool handlers."""

    def __init__(self, plugin_dir: Path, home: Path):
        self.plugin_dir = plugin_dir
        self.hermes_home = home
        self.plugin_id = plugin_dir.name
        self.config: Dict[str, Any] = {}
        self.tools: Dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, schema: Any, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if name in _TARGET_TOOLS and callable(handler):
            self.tools[name] = handler

    def __getattr__(self, name: str) -> Callable[..., None]:
        # Other registrations (hooks, commands, middleware) are irrelevant here.
        def _noop(*args: Any, **kwargs: Any) -> None:
            return None
        return _noop


def _candidate_files(home: Path) -> Iterable[Path]:
    explicit = os.environ.get("MEMORY_WIKI_SECRET_CONTEXT_PLUGIN", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        yield p / "__init__.py" if p.is_dir() else p
        return
    # Hermes profiles are intentionally isolated.  Cross-profile discovery can
    # import inactive-profile plugin code into the current provider; callers who
    # intentionally need a non-default location must set the explicit path above.
    roots = [home / "plugins"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/__init__.py")):
            if "memory-wiki" in str(path.parent.name).lower():
                continue
            yield path


def discover_secret_context_plugin(home: Optional[Path] = None) -> Optional[Path]:
    home = Path(home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    for path in _candidate_files(home):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "secret_context_lookup" in text and "secret_context_search" in text and "register_tool" in text:
            return path
    return None


def _loaded_module_for(path: Path) -> Any:
    try:
        target = path.resolve()
    except OSError:
        target = path
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if Path(module_file).resolve() == target:
                return module
        except OSError:
            continue
    return None


def _load_handlers(path: Path, home: Path) -> Tuple[Dict[str, Callable[..., Any]], str]:
    try:
        stat = path.stat()
    except OSError as exc:
        return {}, f"plugin_stat_failed:{type(exc).__name__}"
    with _CACHE_LOCK:
        if _CACHE["path"] == str(path) and _CACHE["mtime_ns"] == stat.st_mtime_ns:
            return dict(_CACHE["handlers"]), str(_CACHE["error"])

    module_name = "_memory_wiki_secret_context_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    lib_dir = home / "lib"
    inserted: List[str] = []
    for candidate in (str(lib_dir), str(path.parent.parent), str(path.parent)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
            inserted.append(candidate)
    try:
        module = _loaded_module_for(path)
        if module is None:
            spec = importlib.util.spec_from_file_location(
                module_name,
                path,
                submodule_search_locations=[str(path.parent)] if path.name == "__init__.py" else None,
            )
            if spec is None or spec.loader is None:
                raise ImportError("spec_unavailable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if not callable(register):
            raise AttributeError("register_missing")
        capture = _CaptureContext(path.parent, home)
        register(capture)
        handlers = {name: handler for name, handler in capture.tools.items() if name in _TARGET_TOOLS}
        missing = sorted(_TARGET_TOOLS - set(handlers))
        error = "" if not missing else "handlers_missing:" + ",".join(missing)
    except Exception as exc:
        handlers = {}
        error = f"plugin_load_failed:{type(exc).__name__}:{_redact_string(exc, 240)}"
    finally:
        for candidate in inserted:
            try:
                sys.path.remove(candidate)
            except ValueError:
                pass

    with _CACHE_LOCK:
        _CACHE.update({"path": str(path), "mtime_ns": stat.st_mtime_ns, "handlers": handlers, "error": error})
    return handlers, error


def _run_awaitable(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    # MemoryProvider retrieval is synchronous; do not nest a running event loop.
    raise RuntimeError("async_secret_context_handler_in_running_loop")


def _invoke(handler: Callable[..., Any], args: Dict[str, Any]) -> Any:
    last: Optional[Exception] = None
    for invoke in (lambda: handler(args), lambda: handler(**args)):
        try:
            result = invoke()
            if inspect.isawaitable(result):
                result = _run_awaitable(result)
            return result
        except TypeError as exc:
            last = exc
    if last is not None:
        raise last
    raise RuntimeError("handler_invocation_failed")


def _decode_payload(payload: Any) -> Any:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
    return payload


def _extract_matches(payload: Any) -> List[Any]:
    payload = _decode_payload(payload)
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("matches", "results", "items", "contexts", "entries", "secrets"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    if any(k in payload for k in ("context_key", "lookup_key", "key", "name", "id", "subject")):
        return [payload]
    return []


def _pick(item: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _normalize_match(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        raw = {"context_key": raw, "name": raw}
    if not isinstance(raw, dict):
        return None
    safe = _safe_value(raw)
    if not isinstance(safe, dict):
        return None
    lookup_key = _redact_string(_pick(safe, "context_key", "lookup_key", "key", "name", "id"), 300).strip()
    if not lookup_key:
        return None
    secret_id = str(_pick(safe, "secret_id", "id", default="")).strip()
    stable_id = secret_id if secret_id.startswith("sec_") else "ctx_" + hashlib.sha256(lookup_key.encode("utf-8", "replace")).hexdigest()[:12]
    subject = _redact_string(_pick(safe, "subject", "service", "server", "name", default=lookup_key), 300)
    scope = _redact_string(_pick(safe, "scope", "namespace", "environment", "context_key", default=lookup_key), 300)
    locator = _redact_string(_pick(safe, "locator", "host", "url", "endpoint"), 500)
    purpose = _redact_string(_pick(safe, "purpose", "description"), 500)
    secret_type = _redact_string(_pick(safe, "secret_type", "type", default="credential"), 80)
    username = _redact_string(_pick(safe, "username", "user", "login", "email"), 300)
    origin = _redact_string(_pick(safe, "origin", default="secret_context"), 80)
    source = _redact_string(_pick(safe, "source", default="secret_context_plugin"), 120)
    aliases = safe.get("aliases") if isinstance(safe.get("aliases"), list) else []
    policy = safe.get("policy") if isinstance(safe.get("policy"), dict) else {}
    return {
        "id": stable_id,
        "lookup_key": lookup_key,
        "origin": origin,
        "subject": subject,
        "scope": scope,
        "secret_type": secret_type,
        "locator": locator,
        "purpose": purpose,
        "username": username,
        "source": source,
        "confidence": 1.0,
        "salience": 0.9,
        "status": "active",
        "has_value": bool(safe.get("has_value", True)),
        "aliases": [_redact_string(v, 200) for v in aliases[:30]],
        "policy": _safe_value(policy),
    }


def search_safe_secret_context(query: str, limit: int = 10, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    if os.environ.get("MEMORY_WIKI_SECRET_CONTEXT_BRIDGE", "1").strip().lower() in {"0", "false", "no", "off"}:
        return []
    query = str(query or "").strip()
    if len(query) < 2:
        return []
    limit = max(1, min(int(limit or 10), 50))
    home = Path(home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    out: List[Dict[str, Any]] = []
    seen = set()

    # Best-effort plugin search. Older secret-context versions may only search
    # Memory Wiki's SQLite secret_index and legitimately return no matches.
    path = discover_secret_context_plugin(home)
    if path is not None:
        handlers, error = _load_handlers(path, home)
        if not error and "secret_context_search" in handlers:
            try:
                payload = _invoke(handlers["secret_context_search"], {"query": query, "limit": limit})
            except Exception:
                payload = []
            for raw in _extract_matches(payload):
                item = _normalize_match(raw)
                if not item:
                    continue
                dedup = (str(item.get("lookup_key") or ""), str(item.get("id") or ""))
                if dedup in seen:
                    continue
                seen.add(dedup); out.append(item)
                if len(out) >= limit:
                    return out

    # Independent registry fallback: safe metadata only, no plaintext fields.
    try:
        registry_rows = _search_registry_metadata(query, limit=limit, home=home)
    except Exception:
        registry_rows = []
    for raw in registry_rows:
        item = _normalize_match(raw)
        if not item:
            continue
        item["origin"] = "vault_registry"
        dedup = (str(item.get("lookup_key") or ""), str(item.get("id") or ""))
        if dedup in seen:
            continue
        seen.add(dedup); out.append(item)
        if len(out) >= limit:
            break
    return out

def secret_context_bridge_status(home: Optional[Path] = None) -> Dict[str, Any]:
    home = Path(home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    path = discover_secret_context_plugin(home)
    plugin_status: Dict[str, Any]
    if path is None:
        plugin_status = {"available": False, "reason": "plugin_not_found"}
    else:
        handlers, error = _load_handlers(path, home)
        plugin_status = {
            "available": not bool(error) and "secret_context_search" in handlers,
            "plugin": path.parent.name,
            "path": str(path),
            "lookup_handler": "secret_context_lookup" in handlers,
            "search_handler": "secret_context_search" in handlers,
            "error": error,
        }
    registry = _registry_status(home)
    return {
        "available": bool(plugin_status.get("available") or registry.get("available")),
        "plugin": plugin_status,
        "registry": registry,
        "lookup_handler": bool(plugin_status.get("lookup_handler")),
        "search_handler": bool(plugin_status.get("search_handler")),
        "error": str(plugin_status.get("error") or registry.get("error") or ""),
        "readthrough_mode": "plugin_plus_registry_fallback",
    }

