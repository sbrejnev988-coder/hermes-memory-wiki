#!/usr/bin/env python3
"""Regression: successful document mutations create a recovery baseline after journal after-event."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_document_mutation_checkpoints_after_the_after_event() -> None:
    previous = {key: os.environ.get(key) for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-journal-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_document_journal_checkpoint_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("document-journal-test", hermes_home=tmp, agent_context="test")
            try:
                result, journal = provider._journal_operation(
                    "memory_wiki_document_ingest",
                    {"path": "fixture.txt"},
                    lambda: json.dumps({"success": True, "status": "indexed"}),
                )
                assert json.loads(result)["status"] == "indexed"
                checkpoint = provider._latest_journal_checkpoint()
                assert checkpoint is not None
                payload = json.loads(checkpoint.read_text(encoding="utf-8"))
                assert payload["journal_seq"] == journal["after"]["seq"]
            finally:
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
    test_document_mutation_checkpoints_after_the_after_event()
    print("PASS test_document_mutation_checkpoints_after_the_after_event")
