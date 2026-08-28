#!/usr/bin/env python3
"""Regression: ordinary provider initialization/tool calls cannot mutate code graph via implicit inbox draining."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_regular_tool_call_does_not_implicitly_drain_code_shrinker_events() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-no-implicit-code-drain-", ignore_cleanup_errors=True) as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_no_implicit_drain_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("no-implicit-drain", hermes_home=tmp, agent_context="test")
            calls = []
            provider._drain_code_shrinker_events = lambda limit=25: calls.append(limit) or {"processed": 0}
            provider.handle_tool_call("memory_wiki_dashboard", {})
            assert calls == [], "ordinary tool calls must not mutate graph through unjournaled inbox drain"
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_initialize_does_not_implicitly_drain_code_shrinker_events() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-no-init-drain-", ignore_cleanup_errors=True) as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_no_init_drain_test")

            class Provider(module.MemoryWikiProvider):
                def __init__(self):
                    super().__init__()
                    self.calls = []

                def _drain_code_shrinker_events(self, limit=25):
                    self.calls.append(limit)
                    return {"processed": 0}

            provider = Provider()
            provider.initialize("no-init-drain", hermes_home=tmp, agent_context="test")
            assert provider.calls == []
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_regular_tool_call_does_not_implicitly_drain_code_shrinker_events()
    test_initialize_does_not_implicitly_drain_code_shrinker_events()
    print("PASS test_code_graph_drain_is_explicit_and_journalable")
