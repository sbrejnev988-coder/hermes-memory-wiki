#!/usr/bin/env python3
"""Regression: Windows 8.3 cache aliases retain secure allowlist containment."""
from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_short_path_alias_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def short_path(path: Path) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = kernel32.GetShortPathNameW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    fn.restype = ctypes.c_uint
    needed = fn(str(path), None, 0)
    if not needed:
        return str(path)
    out = ctypes.create_unicode_buffer(needed + 1)
    fn(str(path), out, len(out))
    return out.value or str(path)


def test_short_home_alias_and_long_child_path_share_the_same_allowed_root() -> None:
    if os.name != "nt":
        return
    keys = ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-short-alias-") as tmp:
            home = Path(tmp)
            short_home = short_path(home)
            if os.path.normcase(short_home) == os.path.normcase(str(home)):
                return
            docs = home / "cache" / "documents"
            docs.mkdir(parents=True)
            source = docs / "alias.txt"
            source.write_text("alias", encoding="utf-8")
            os.environ["HERMES_HOME"] = short_home
            for key in keys[1:]:
                os.environ.pop(key, None)
            module = load_module()
            assert module._allowed_path(source) == source.absolute()
            root, relative = module._lexical_root_for_path(docs, allow_root=True)
            assert relative == Path(".")
            assert module._scan_root({"root": str(docs)}) == docs.absolute()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_short_home_alias_and_long_child_path_share_the_same_allowed_root()
    print("PASS test_short_home_alias_and_long_child_path_share_the_same_allowed_root")
