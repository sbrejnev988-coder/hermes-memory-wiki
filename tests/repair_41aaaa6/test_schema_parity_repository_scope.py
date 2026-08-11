from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("memory_wiki_schema_parity", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_native_and_wrapper_patch_outcome_require_repository_id(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = load_module()
    provider = module.MemoryWikiProvider()
    provider.initialize(None)
    native = next(item for item in provider.get_tool_schemas() if item.get("name") == "memory_wiki_patch_outcome_add")
    assert "repository_id" in native["parameters"]["required"]
    wrapper = json.loads((root / "mcp-wrapper" / "tool_schemas.json").read_text(encoding="utf-8"))
    wrapped = next(item for item in wrapper if item.get("name") == "memory_wiki_patch_outcome_add")
    assert "repository_id" in wrapped["parameters"]["required"]
