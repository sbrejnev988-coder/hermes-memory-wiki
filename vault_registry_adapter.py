"""Safe adapter for Hermes metadata-only secret registries.

Search and exact lookup expose only safe identifiers and policy metadata. Nothing
in this module writes to SQLite, FTS, Qdrant, logs, or markdown, and it never
returns a private registry field."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_MAX_REGISTRY_BYTES = 16 * 1024 * 1024
_CACHE_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {
    "path": "",
    "mtime_ns": -1,
    "size": -1,
    "payload": None,
    "error": "",
}

_CONTAINER_KEYS = {
    "secrets", "entries", "contexts", "items", "registry", "records",
    "credentials", "servers", "accounts", "vault", "data",
}
_ID_KEYS = (
    "context_key", "lookup_key", "key", "secret_id", "id", "name",
    "slug", "ref", "reference",
)
_ALIAS_KEYS = ("aliases", "alias", "aka", "synonyms", "tags")
_SAFE_META_KEYS = {
    "subject", "title", "label", "description", "purpose", "scope",
    "namespace", "environment", "service", "server", "host", "hostname",
    "url", "endpoint", "locator", "type", "secret_type", "username",
    "user", "login", "email", "port", "protocol", "status", "source",
    "allowed_executors", "require_user_approval", "policy",
}
_SENSITIVE_EXACT = {
    "value", "plaintext", "plain", "password", "passwd", "passphrase",
    "token", "access_token", "refresh_token", "api_key", "apikey",
    "secret", "secret_value", "client_secret", "private_key",
    "secret_access_key", "authorization", "auth", "cookie",
    "session_cookie", "totp_seed", "seed", "credential", "credentials",
}
_SENSITIVE_MARKERS = (
    "password", "passwd", "passphrase", "token", "api_key", "apikey",
    "secret_value", "client_secret", "private_key", "access_key",
    "credential_value", "totp_seed", "session_cookie",
)
_TOKEN_RE = re.compile(r"[\w@.+:/-]+", re.UNICODE)
_URL_CREDENTIALS_RE = re.compile(r"(?i)(https?://)([^/@:\s]+):([^/@\s]+)@")
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|token|api[_-]?key|client[_-]?secret|"
    r"secret[_-]?access[_-]?key|authorization|cookie|totp[_-]?seed)\b\s*[:=]\s*([^\s,;]+)"
)
_PEM_RE = re.compile(
    r"-----BEGIN [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----[\s\S]*?-----END [^-]+-----",
    re.I,
)


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _home(home: Optional[Path] = None) -> Path:
    if home is not None:
        return Path(home).expanduser()
    configured = os.environ.get("HERMES_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def registry_path(home: Optional[Path] = None) -> Path:
    explicit = (
        os.environ.get("MEMORY_WIKI_SECRET_REGISTRY")
        or os.environ.get("SECRET_CONTEXT_REGISTRY")
        or os.environ.get("HERMES_SECRET_REGISTRY")
        or os.environ.get("HERMES_VAULT_REGISTRY")
        or ""
    ).strip()
    # The new DPAPI store owns a separate metadata-only registry. Legacy
    # $HERMES_HOME/vault registries are never read implicitly because they may
    # predate the no-plaintext registry contract.
    return Path(explicit).expanduser() if explicit else _home(home) / "secret-vault" / "secrets_registry.json"


def _is_sensitive_key(key: Any) -> bool:
    value = str(key or "").strip().lower().replace("-", "_")
    if value in {"secret_id", "secret_type", "has_value", "secret_ref", "vault_ref"}:
        return False
    return value in _SENSITIVE_EXACT or any(marker in value for marker in _SENSITIVE_MARKERS)


def _load_registry(home: Optional[Path] = None) -> Tuple[Any, str, Path]:
    path = registry_path(home)
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode):
            return None, "registry_not_regular_file", path
        if st.st_size > _MAX_REGISTRY_BYTES:
            return None, "registry_too_large", path
        with _CACHE_LOCK:
            if (
                _CACHE["path"] == str(path)
                and _CACHE["mtime_ns"] == st.st_mtime_ns
                and _CACHE["size"] == st.st_size
            ):
                return _CACHE["payload"], str(_CACHE["error"]), path
        payload = json.loads(path.read_text(encoding="utf-8"))
        error = ""
    except FileNotFoundError:
        payload, error = None, "registry_not_found"
    except PermissionError:
        payload, error = None, "registry_permission_denied"
    except json.JSONDecodeError as exc:
        payload, error = None, f"registry_invalid_json:{exc.lineno}:{exc.colno}"
    except OSError as exc:
        payload, error = None, f"registry_read_failed:{type(exc).__name__}"
    with _CACHE_LOCK:
        try:
            st = path.stat()
            mtime_ns, size = st.st_mtime_ns, st.st_size
        except OSError:
            mtime_ns, size = -1, -1
        _CACHE.update({
            "path": str(path), "mtime_ns": mtime_ns, "size": size,
            "payload": payload, "error": error,
        })
    return payload, error, path


def _record_identifier(record: Dict[str, Any], fallback: str = "") -> str:
    for key in _ID_KEYS:
        value = record.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return str(fallback or "").strip()


def _looks_like_record(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    lowered = {str(k).lower() for k in value}
    return bool(lowered.intersection(_ID_KEYS) or lowered.intersection(_SAFE_META_KEYS) or any(_is_sensitive_key(k) for k in value))


def _iter_records(payload: Any) -> Iterator[Tuple[str, Any]]:
    """Yield ``(lookup_key, raw_record)`` for common registry schemas."""
    seen: set[Tuple[str, int]] = set()

    def walk(node: Any, fallback: str = "", depth: int = 0) -> Iterator[Tuple[str, Any]]:
        if depth > 7:
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                yield from walk(item, fallback=f"{fallback}.{index}" if fallback else str(index), depth=depth + 1)
            return
        if not isinstance(node, dict):
            if fallback:
                marker = (fallback, id(node))
                if marker not in seen:
                    seen.add(marker)
                    yield fallback, node
            return

        ident = _record_identifier(node, fallback)
        if ident and _looks_like_record(node):
            marker = (ident, id(node))
            if marker not in seen:
                seen.add(marker)
                yield ident, node

        for raw_key, child in node.items():
            key = str(raw_key)
            key_l = key.lower()
            if key_l in _CONTAINER_KEYS:
                yield from walk(child, fallback="", depth=depth + 1)
                continue
            if isinstance(child, (dict, list)):
                child_fallback = key if not fallback else f"{fallback}.{key}"
                yield from walk(child, fallback=child_fallback, depth=depth + 1)
            elif depth <= 1 and key_l not in _SAFE_META_KEYS and not _is_sensitive_key(key):
                # A top-level mapping of key -> scalar secret.
                yield key, child

    yield from walk(payload)


def _aliases(record: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in _ALIAS_KEYS:
        value = record.get(key)
        if isinstance(value, str):
            out.extend(part.strip() for part in re.split(r"[,;\n]", value) if part.strip())
        elif isinstance(value, (list, tuple, set)):
            out.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            out.extend(str(item).strip() for item in value.keys() if str(item).strip())
    return list(dict.fromkeys(out))[:50]


def _safe_string(value: Any, max_chars: int = 500) -> str:
    text = str(value or "")
    text = _PEM_RE.sub("<redacted-private-key>", text)
    text = _URL_CREDENTIALS_RE.sub(r"\1<redacted>:<redacted>@", text)
    text = _ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _safe_policy(value: Any, depth: int = 0) -> Dict[str, Any]:
    """Return the small policy subset that is safe for model-visible metadata."""
    _ = depth
    if not isinstance(value, dict):
        return {}
    executors = value.get("allowed_executors")
    if isinstance(executors, (list, tuple, set)):
        allowed = [_safe_string(item, 64) for item in list(executors)[:50] if _safe_string(item, 64)]
    else:
        allowed = []
    return {
        "allowed_executors": list(dict.fromkeys(allowed)),
        "require_user_approval": bool(value.get("require_user_approval", True)),
    }


def _field(record: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _has_secret_value(record: Any) -> bool:
    # The secure vault publishes an explicit Boolean. Never inspect legacy value
    # fields merely to infer this bit: that would load private material into the
    # Memory Wiki process for no retrieval benefit.
    return isinstance(record, dict) and record.get("has_value") is True


def safe_metadata(lookup_key: str, raw: Any) -> Dict[str, Any]:
    record = raw if isinstance(raw, dict) else {}
    key = _record_identifier(record, lookup_key) or lookup_key
    aliases = _aliases(record)
    # Only registry-controlled identifiers and type/status policy may cross this
    # boundary. In particular, do not trust a legacy registry's title, host,
    # login, locator or free-form description as safe metadata.
    subject = key
    scope = key
    locator = ""
    purpose = ""
    secret_type = _safe_string(_field(record, "secret_type", "type", default="credential"), 100)
    username = ""
    policy_raw = _field(record, "policy", default={})
    stable = str(_field(record, "secret_id", "id", default=""))
    stable_id = stable if stable.startswith("sec_") else "ctx_" + hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:12]
    return {
        "id": stable_id,
        "lookup_key": key,
        "origin": "vault_registry",
        "subject": subject,
        "scope": scope,
        "secret_type": secret_type,
        "locator": locator,
        "purpose": purpose,
        "username": username,
        "source": "secrets_registry.json",
        "confidence": 1.0,
        "salience": 0.95,
        "status": _safe_string(_field(record, "status", default="active"), 50) or "active",
        "has_value": _has_secret_value(raw),
        "aliases": aliases,
        "policy": _safe_policy(policy_raw) if isinstance(policy_raw, dict) else {},
    }


def _query_terms(query: str) -> List[str]:
    return [token.lower() for token in _TOKEN_RE.findall(str(query or "")) if len(token) >= 2]


def search_registry_metadata(query: str, limit: int = 10, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    if not _truthy("MEMORY_WIKI_VAULT_REGISTRY_SEARCH", True):
        return []
    terms = _query_terms(query)
    if not terms:
        return []
    payload, error, _ = _load_registry(home)
    if error or payload is None:
        return []
    candidates: List[Tuple[int, str, Dict[str, Any]]] = []
    seen: set[str] = set()
    for lookup_key, raw in _iter_records(payload):
        meta = safe_metadata(lookup_key, raw)
        key = str(meta["lookup_key"])
        if key in seen:
            continue
        hay_parts = [
            key, meta.get("subject", ""), meta.get("scope", ""),
            meta.get("locator", ""), meta.get("purpose", ""),
            meta.get("username", ""), " ".join(meta.get("aliases", [])),
        ]
        hay = " ".join(str(part) for part in hay_parts).lower()
        score = sum(5 if term == key.lower() else 3 if term in key.lower() else 1 for term in terms if term in hay)
        if score <= 0:
            continue
        seen.add(key)
        candidates.append((score, key, meta))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [meta for _, _, meta in candidates[:max(1, min(int(limit or 10), 100))]]


def lookup_registry_exact(lookup_key: str, home: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return metadata for one record; never return private registry fields."""
    key = str(lookup_key or "").strip()
    if not key:
        return None
    payload, error, _ = _load_registry(home)
    if error or payload is None:
        return None
    key_l = key.casefold()
    for candidate_key, raw in _iter_records(payload):
        meta = safe_metadata(candidate_key, raw)
        identifiers = {
            str(candidate_key).casefold(),
            str(meta.get("id") or "").casefold(),
            str(meta.get("lookup_key") or "").casefold(),
            *(str(alias).casefold() for alias in meta.get("aliases") or []),
        }
        if key_l in identifiers:
            return meta
    return None


def known_secret_values(home: Optional[Path] = None, max_values: int = 2000) -> List[str]:
    """Return no plaintext values: registry data is metadata-only by design."""
    _ = (home, max_values)
    return []


def redact_known_values(text: Any, home: Optional[Path] = None) -> str:
    output = str(text or "")
    for value in known_secret_values(home):
        if value and value in output:
            output = output.replace(value, "<redacted-vault-secret>")
    output = _PEM_RE.sub("<redacted-private-key>", output)
    output = _URL_CREDENTIALS_RE.sub(r"\1<redacted>:<redacted>@", output)
    return output


def registry_status(home: Optional[Path] = None) -> Dict[str, Any]:
    payload, error, path = _load_registry(home)
    count = 0
    if not error and payload is not None:
        try:
            count = sum(1 for _ in _iter_records(payload))
        except Exception:
            error = "registry_enumeration_failed"
    mode = None
    try:
        mode = oct(path.stat().st_mode & 0o777)
    except OSError:
        pass
    return {
        "available": not bool(error),
        "path": str(path),
        "error": error,
        "entries": count,
        "mode": mode,
        "permissions_secure": mode in {"0o600", "0o400"},
        "search_enabled": _truthy("MEMORY_WIKI_VAULT_REGISTRY_SEARCH", True),
    }
