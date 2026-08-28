#!/usr/bin/env python3
"""Regression: the embedding stub log is profile-scoped, not shared /tmp."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


STUB = Path(__file__).resolve().parents[1] / "stubs" / "embed_stub.py"


def load_stub(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, STUB)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_embed_stub_log_uses_active_hermes_home() -> None:
    previous_home = os.environ.get("HERMES_HOME")
    previous_log = os.environ.pop("EMBED_STUB_LOG", None)
    try:
        with tempfile.TemporaryDirectory(prefix="mw-embed-stub-log-") as tmp:
            home = Path(tmp) / "profile"
            os.environ["HERMES_HOME"] = str(home)
            module = load_stub("memory_wiki_embed_stub_log_path_test")
            log_path = Path(module.ERROR_LOG)
            assert log_path.is_relative_to(home)
            module.stub_log("profile-scoped log smoke test")
            assert log_path.is_file()
    finally:
        if previous_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous_home
        if previous_log is None:
            os.environ.pop("EMBED_STUB_LOG", None)
        else:
            os.environ["EMBED_STUB_LOG"] = previous_log


if __name__ == "__main__":
    test_embed_stub_log_uses_active_hermes_home()
    print("PASS test_embed_stub_log_uses_active_hermes_home")
