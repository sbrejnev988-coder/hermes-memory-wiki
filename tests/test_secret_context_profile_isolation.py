#!/usr/bin/env python3
"""Regression: secret-context discovery respects Hermes profile isolation."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "secret_context_bridge.py"
sys.path.insert(0, str(MODULE.parent))


def load_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_secret_context_discovery_does_not_cross_profile_boundaries() -> None:
    previous = os.environ.get("MEMORY_WIKI_SECRET_CONTEXT_PLUGIN")
    previous_home = os.environ.get("HERMES_HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="mw-secret-profile-") as tmp:
            home = Path(tmp) / "active"
            foreign = home / "profiles" / "other" / "plugins" / "secret-context"
            foreign.mkdir(parents=True)
            plugin = foreign / "__init__.py"
            plugin.write_text(
                "def register_tool(): pass\n"
                "secret_context_lookup = None\n"
                "secret_context_search = None\n",
                encoding="utf-8",
            )
            os.environ.pop("MEMORY_WIKI_SECRET_CONTEXT_PLUGIN", None)
            os.environ["HERMES_HOME"] = str(home)
            module = load_module("memory_wiki_secret_profile_isolation_test")

            assert module.discover_secret_context_plugin(home) is None

            os.environ["MEMORY_WIKI_SECRET_CONTEXT_PLUGIN"] = str(foreign)
            assert module.discover_secret_context_plugin(home) == plugin

            # The override belongs to the ambient profile, not to an
            # independently hosted provider with another HERMES_HOME.
            os.environ["HERMES_HOME"] = str(Path(tmp) / "ambient")
            assert module.discover_secret_context_plugin(home) is None
    finally:
        if previous is None:
            os.environ.pop("MEMORY_WIKI_SECRET_CONTEXT_PLUGIN", None)
        else:
            os.environ["MEMORY_WIKI_SECRET_CONTEXT_PLUGIN"] = previous
        if previous_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous_home


if __name__ == "__main__":
    test_secret_context_discovery_does_not_cross_profile_boundaries()
    print("PASS test_secret_context_discovery_does_not_cross_profile_boundaries")
