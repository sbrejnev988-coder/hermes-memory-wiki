#!/usr/bin/env python3
"""Recovery regression: tool-level error results become fail-closed journal error events."""
from __future__ import annotations

import importlib.util
import json
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


def test_sensitive_tool_error_result_is_journaled_as_redacted_error_and_blocks_rebuild() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-tool-error-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_tool_error_journal_test")
            provider = module.MemoryWikiProvider(); provider.initialize("tool-error", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-tool-error")
                marker = "SENSITIVE_TOOL_ERROR_SENTINEL_2b18"
                result, _journal = provider._journal_operation(
                    "memory_wiki_document_ingest", {"path": str(Path(tmp) / marker)},
                    lambda: json.dumps({"success": False, "error": marker}),
                )
                assert json.loads(result)["success"] is False
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["incomplete_events"] >= 1, plan
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("tool-level sensitive error result did not block recovery")
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_sensitive_tool_error_result_is_journaled_as_redacted_error_and_blocks_rebuild()
    print("PASS test_sensitive_tool_error_result_is_journaled_as_redacted_error_and_blocks_rebuild")
