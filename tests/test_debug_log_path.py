#!/usr/bin/env python3
"""Regression: debug logs remain inside the active Hermes profile."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_module(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_debug_log_uses_active_hermes_home() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DEBUG")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-debug-log-") as tmp:
            home = Path(tmp) / "profile"
            os.environ["HERMES_HOME"] = str(home)
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            os.environ["MEMORY_WIKI_DEBUG"] = "1"
            module = load_module("memory_wiki_debug_log_path_test")
            log_path = Path(module.DEBUG_LOG)
            assert log_path.is_relative_to(home)
            module._debug_log("profile-scoped debug smoke test")
            assert log_path.is_file()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_debug_log_uses_active_hermes_home()
    print("PASS test_debug_log_uses_active_hermes_home")
