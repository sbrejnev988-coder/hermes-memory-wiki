#!/usr/bin/env python3
"""Patch secret-context handlers with Vault Registry fallback and string results."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

TARGET_TOOLS = {"secret_context_lookup", "secret_context_search"}
WRAPPER = "_hermes_vault_registry_tool_handler"
MARKER = "# HERMES-SECRET-CONTEXT-VAULT-REGISTRY-r8"
HELPER = r'''
# HERMES-SECRET-CONTEXT-VAULT-REGISTRY-r8
# Registry fallback with robust adapter discovery. Both search and exact lookup
# return metadata-only records; private fields must use a local executor.
def _hermes_vault_registry_adapter():
    import importlib.util as _importlib_util
    import os as _os
    import pathlib as _pathlib

    _candidates = []
    _explicit = str(_os.environ.get("MEMORY_WIKI_VAULT_REGISTRY_ADAPTER") or "").strip()
    if _explicit:
        _candidates.append(_pathlib.Path(_explicit).expanduser())

    _here = _pathlib.Path(__file__).resolve().parent
    _candidates.extend([
        _here / "vault_registry_adapter.py",
        _here.parent / "memory-wiki" / "vault_registry_adapter.py",
        _here.parent / "memory_wiki" / "vault_registry_adapter.py",
    ])

    _home = _pathlib.Path(
        _os.environ.get("HERMES_HOME") or (_pathlib.Path.home() / ".hermes")
    ).expanduser()
    _candidates.extend([
        _home / "plugins" / "memory-wiki" / "vault_registry_adapter.py",
        _home / "plugins" / "memory_wiki" / "vault_registry_adapter.py",
    ])
    _profiles = _home / "profiles"
    if _profiles.is_dir():
        for _profile in _profiles.iterdir():
            if _profile.is_dir():
                _candidates.extend([
                    _profile / "plugins" / "memory-wiki" / "vault_registry_adapter.py",
                    _profile / "plugins" / "memory_wiki" / "vault_registry_adapter.py",
                ])

    _seen = set()
    _errors = []
    for _path in _candidates:
        try:
            _path = _path.resolve()
        except Exception:
            continue
        if str(_path) in _seen:
            continue
        _seen.add(str(_path))
        if not _path.is_file():
            continue
        try:
            _spec = _importlib_util.spec_from_file_location(
                "_secret_context_vault_registry_adapter_" + str(abs(hash(str(_path)))), _path
            )
            if _spec is None or _spec.loader is None:
                raise RuntimeError("adapter_spec_unavailable")
            _adapter = _importlib_util.module_from_spec(_spec)
            _spec.loader.exec_module(_adapter)
            if not callable(getattr(_adapter, "search_registry_metadata", None)):
                raise RuntimeError("adapter_missing_search_registry_metadata")
            if not callable(getattr(_adapter, "lookup_registry_exact", None)):
                raise RuntimeError("adapter_missing_lookup_registry_exact")
            setattr(_adapter, "ADAPTER_AVAILABLE", True)
            setattr(_adapter, "ADAPTER_PATH", str(_path))
            return _adapter
        except Exception as _exc:
            _errors.append(type(_exc).__name__ + ":" + str(_exc))

    class _NoRegistryAdapter:
        ADAPTER_AVAILABLE = False
        ADAPTER_PATH = ""
        ADAPTER_ERROR = "vault_registry_adapter_not_found"
        if _errors:
            ADAPTER_ERROR += ":" + ";".join(_errors[-3:])

        @staticmethod
        def search_registry_metadata(*args, **kwargs): return []
        @staticmethod
        def lookup_registry_exact(*args, **kwargs): return None
    return _NoRegistryAdapter


def _hermes_json_result(payload):
    import json as _json
    if isinstance(payload, str):
        try:
            _json.loads(payload)
            return payload
        except Exception:
            return _json.dumps({"text": payload}, ensure_ascii=False, default=str, separators=(",", ":"))
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8", "replace")
    return _json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def _hermes_decode_result(payload):
    import json as _json
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            return _json.loads(payload)
        except Exception:
            return {"text": payload}
    return payload


def _hermes_handler_args(args, kwargs):
    if args and isinstance(args[0], dict):
        return dict(args[0])
    if args and hasattr(args[0], "model_dump"):
        try:
            return dict(args[0].model_dump())
        except Exception:
            pass
    return dict(kwargs or {})


def _hermes_extract_matches(payload):
    payload = _hermes_decode_result(payload)
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for _key in ("matches", "results", "items", "contexts", "entries", "secrets"):
            if isinstance(payload.get(_key), list):
                return list(payload[_key])
        if any(_key in payload for _key in ("context_key", "lookup_key", "key", "id", "name")):
            return [payload]
    return []


def _hermes_merge_search(original, registry_rows, limit, adapter=None):
    payload = _hermes_decode_result(original)
    merged = []
    seen = set()
    for item in _hermes_extract_matches(payload) + list(registry_rows or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("context_key") or item.get("lookup_key") or item.get("key") or item.get("id") or item.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key); merged.append(item)
        if len(merged) >= limit:
            break
    if isinstance(payload, dict):
        out = dict(payload)
        target = next((_key for _key in ("matches", "results", "items", "contexts", "entries", "secrets") if isinstance(payload.get(_key), list)), "matches")
        out[target] = merged
    else:
        out = {"matches": merged}
    if adapter is not None:
        out["registry_fallback"] = {
            "available": bool(getattr(adapter, "ADAPTER_AVAILABLE", True)),
            "adapter_path": str(getattr(adapter, "ADAPTER_PATH", "")),
        }
        if not out["registry_fallback"]["available"]:
            out["registry_fallback"]["error"] = str(getattr(adapter, "ADAPTER_ERROR", "adapter_unavailable"))
    return out


def _hermes_is_missing_lookup(payload):
    value = _hermes_decode_result(payload)
    if value in (None, "", [], {}):
        return True
    if isinstance(value, dict):
        if value.get("found") is False or str(value.get("status") or "").lower() in {"not_found", "missing", "empty"}:
            return True
        if value.get("error") and not any(k in value for k in ("value", "password", "token", "secret", "credential")):
            return True
    return False


def _hermes_vault_registry_tool_handler(tool_name, handler):
    import functools as _functools
    import inspect as _inspect

    async def _finish_async(result, call_args):
        if _inspect.isawaitable(result):
            result = await result
        return _finish(result, call_args)

    def _finish(result, call_args):
        _adapter = _hermes_vault_registry_adapter()
        if tool_name == "secret_context_search":
            query = str(call_args.get("query") or call_args.get("q") or call_args.get("text") or "").strip()
            try:
                limit = max(1, min(int(call_args.get("limit") or 10), 100))
            except Exception:
                limit = 10
            registry_rows = _adapter.search_registry_metadata(query, limit=limit)
            return _hermes_json_result(_hermes_merge_search(result, registry_rows, limit, _adapter))
        key = str(call_args.get("secret_id") or call_args.get("context_key") or call_args.get("lookup_key") or call_args.get("key") or call_args.get("id") or "").strip()
        if key and _hermes_is_missing_lookup(result):
            if not bool(getattr(_adapter, "ADAPTER_AVAILABLE", True)):
                return _hermes_json_result({
                    "status": "registry_adapter_unavailable",
                    "key": key,
                    "error": str(getattr(_adapter, "ADAPTER_ERROR", "adapter_unavailable")),
                })
            registry_record = _adapter.lookup_registry_exact(key)
            if registry_record is not None:
                result = registry_record
        return _hermes_json_result(_hermes_decode_result(result))

    if _inspect.iscoroutinefunction(handler):
        @_functools.wraps(handler)
        async def _async_handler(*args, **kwargs):
            call_args = _hermes_handler_args(args, kwargs)
            return _finish(await handler(*args, **kwargs), call_args)
        return _async_handler

    @_functools.wraps(handler)
    def _sync_handler(*args, **kwargs):
        call_args = _hermes_handler_args(args, kwargs)
        result = handler(*args, **kwargs)
        if _inspect.isawaitable(result):
            return _finish_async(result, call_args)
        return _finish(result, call_args)
    return _sync_handler
'''.rstrip() + "\n"


def _candidate_files(home: Path) -> Iterable[Path]:
    explicit = os.environ.get("MEMORY_WIKI_SECRET_CONTEXT_PLUGIN", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        yield path / "__init__.py" if path.is_dir() else path
        return
    roots = [home / "plugins"]
    profiles = home / "profiles"
    if profiles.is_dir():
        roots.extend(p / "plugins" for p in profiles.iterdir() if p.is_dir())
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("__init__.py")):
            try:
                relative_parts = path.relative_to(root).parts
            except ValueError:
                continue
            # Support nested runtime plugin layouts while avoiding unbounded scans.
            if len(relative_parts) > 5:
                continue
            if not any("memory-wiki" in part.lower() or "memory_wiki" in part.lower() for part in relative_parts):
                yield path


def discover(home: Optional[Path] = None) -> Optional[Path]:
    home = Path(home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    matches: List[Path] = []
    for path in _candidate_files(home):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if all(name in text for name in TARGET_TOOLS) and "register_tool" in text:
            matches.append(path)
    # Prefer the conventional user plugin path over profile/project duplicates.
    matches.sort(key=lambda p: (0 if p.parent.name in {"secret-context", "secret_context"} and p.parent.parent == home / "plugins" else 1, len(str(p)), str(p)))
    return matches[0] if matches else None


def discover_all(home: Optional[Path] = None) -> List[Path]:
    home = Path(home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    out=[]
    for path in _candidate_files(home):
        try: text=path.read_text(encoding="utf-8", errors="replace")
        except OSError: continue
        if all(name in text for name in TARGET_TOOLS) and "register_tool" in text:
            out.append(path)
    return sorted(set(out), key=str)


def _const_string(node: ast.AST) -> str:
    return str(node.value) if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def _call_name(call: ast.Call) -> str:
    for keyword in call.keywords:
        if keyword.arg == "name":
            return _const_string(keyword.value)
    return _const_string(call.args[0]) if call.args else ""


def _is_register_tool(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == "register_tool"


def _handler_node(call: ast.Call, function_names: set[str]) -> Optional[ast.AST]:
    for keyword in call.keywords:
        if keyword.arg == "handler":
            return keyword.value
    for node in reversed(list(call.args[1:])):
        if isinstance(node, ast.Name) and node.id in function_names:
            return node
        if isinstance(node, (ast.Lambda, ast.Attribute, ast.Call)):
            return node
    return call.args[-1] if len(call.args) > 1 else None


def _line_data(text: str) -> Tuple[List[str], List[int]]:
    lines = text.splitlines(keepends=True) or [""]
    starts=[]; cursor=0
    for line in lines:
        starts.append(cursor); cursor += len(line)
    return lines, starts


def _char_column(line: str, byte_column: int) -> int:
    return len(line.encode("utf-8")[:max(0, int(byte_column))].decode("utf-8", "ignore"))


def _span(node: ast.AST, lines: Sequence[str], starts: Sequence[int]) -> Tuple[int, int]:
    start_line=int(node.lineno)-1; end_line=int(node.end_lineno)-1
    return (
        starts[start_line] + _char_column(lines[start_line], int(node.col_offset)),
        starts[end_line] + _char_column(lines[end_line], int(node.end_col_offset)),
    )


def analyze_text(text: str) -> Dict[str, Any]:
    tree=ast.parse(text)
    function_names={node.name for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    lines,starts=_line_data(text); found={}
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not _is_register_tool(node): continue
        name=_call_name(node)
        if name not in TARGET_TOOLS: continue
        handler=_handler_node(node,function_names)
        if handler is None:
            found[name]={"found":True,"error":"handler_not_resolved"}; continue
        start,end=_span(handler,lines,starts); segment=text[start:end]
        found[name]={"found":True,"wrapped":segment.lstrip().startswith(WRAPPER+"("),"handler":segment[:240],"start":start,"end":end}
    missing=sorted(TARGET_TOOLS-set(found))
    return {"tools":found,"missing":missing,"helper_present":MARKER in text,"complete":not missing,"patched":not missing and MARKER in text and all(v.get("wrapped") for v in found.values())}


def _remove_legacy_helper(text: str) -> str:
    for marker in (
        "# HERMES-SECRET-CONTEXT-VAULT-REGISTRY-r6",
        "# HERMES-SECRET-CONTEXT-VAULT-REGISTRY-r7",
        "# HERMES-SECRET-CONTEXT-VAULT-REGISTRY-r8",
    ):
        pos = text.find(marker)
        if pos >= 0:
            return text[:pos].rstrip() + "\n"
    return text


def patch_text(text: str) -> Tuple[str, Dict[str, Any]]:
    if MARKER not in text:
        text = _remove_legacy_helper(text)
    report=analyze_text(text)
    if report["missing"]: raise RuntimeError("target_tool_registration_missing:"+",".join(report["missing"]))
    unresolved=[name for name,item in report["tools"].items() if item.get("error")]
    if unresolved: raise RuntimeError("target_handler_unresolved:"+",".join(unresolved))
    replacements=[]
    for name,item in report["tools"].items():
        if item.get("wrapped"): continue
        start,end=int(item["start"]),int(item["end"])
        replacements.append((start,end,f'{WRAPPER}("{name}", {text[start:end]})'))
    patched=text
    for start,end,replacement in sorted(replacements,reverse=True):
        patched=patched[:start]+replacement+patched[end:]
    if MARKER not in patched: patched=patched.rstrip()+HELPER
    final=analyze_text(patched)
    if not final["patched"]: raise RuntimeError("post_patch_validation_failed")
    final["changed"]=patched!=text
    return patched,final


def patch_file(path: Path, apply: bool) -> Dict[str, Any]:
    text=path.read_text(encoding="utf-8")
    if apply:
        patched,report=patch_text(text)
        if patched!=text:
            tmp=path.with_name(path.name+".r7.tmp")
            tmp.write_text(patched,encoding="utf-8")
            compile(patched,str(path),"exec")
            os.replace(tmp,path)
        report.update({"path":str(path),"mode":"apply"}); return report
    report=analyze_text(text); report.update({"path":str(path),"mode":"check","needs_patch":not report["patched"]}); return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--path")
    parser.add_argument("--home")
    parser.add_argument("--find",action="store_true")
    parser.add_argument("--find-all",action="store_true")
    mode=parser.add_mutually_exclusive_group(); mode.add_argument("--apply",action="store_true"); mode.add_argument("--check",action="store_true")
    args=parser.parse_args(argv); home=Path(args.home).expanduser() if args.home else None
    if args.find_all:
        print(json.dumps([str(p) for p in discover_all(home)],ensure_ascii=False)); return 0
    path=Path(args.path).expanduser() if args.path else discover(home)
    if path and path.is_dir(): path=path/"__init__.py"
    if path is None:
        print(json.dumps({"ok":False,"error":"secret_context_plugin_not_found"},ensure_ascii=False)); return 2
    if args.find: print(str(path)); return 0
    try:
        report=patch_file(path,apply=bool(args.apply)); report["ok"]=True
        print(json.dumps(report,ensure_ascii=False,sort_keys=True)); return 0 if (args.apply or report.get("patched")) else 3
    except Exception as exc:
        print(json.dumps({"ok":False,"path":str(path),"error":f"{type(exc).__name__}:{exc}"},ensure_ascii=False)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
