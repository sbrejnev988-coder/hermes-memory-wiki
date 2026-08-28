#!/usr/bin/env python3
"""Sensitive reference-capture errors must not leak into the journal."""
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


def test_sensitive_recovery_reference_capture_error_is_redacted_and_fail_closed() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-reference-error-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_reference_capture_error_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("reference-error", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-reference-capture-error")
                marker = "RECOVERY_REFERENCE_CAPTURE_SECRET_SENTINEL"
                source_path = str(Path(tmp) / marker / "source.md")
                provider._build_recovery_reference = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(marker))
                try:
                    provider._journal_operation(
                        "memory_wiki_document_ingest", {"path": source_path},
                        lambda: json.dumps({"success": True, "status": "indexed"}),
                    )
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("reference-capture failure unexpectedly completed")
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal
                assert source_path not in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["incomplete_events"] >= 1, plan
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_sensitive_recovery_reference_capture_error_is_redacted_and_fail_closed()
    print("PASS test_sensitive_recovery_reference_capture_error_is_redacted_and_fail_closed")
