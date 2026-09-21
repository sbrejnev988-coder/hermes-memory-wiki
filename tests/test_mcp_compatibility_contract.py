"""A public tool's older valid calls stay valid within MCP API major 1."""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import sdk


ROOT = Path(__file__).resolve().parents[1]


def _checker():
    path = ROOT / "packaging" / "check_mcp_compatibility.py"
    spec = importlib.util.spec_from_file_location("memory_wiki_mcp_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _contract():
    baseline = json.loads((ROOT / "compatibility" / "mcp-api-v1.json").read_text(encoding="utf-8"))
    current = json.loads((ROOT / "mcp-wrapper" / "tool_schemas.json").read_text(encoding="utf-8"))
    return baseline, current


def test_packaged_mcp_schemas_meet_pinned_major_contract():
    baseline, current = _contract()
    assert _checker().check_contract(baseline, current) == []


def test_tool_rename_removal_and_new_required_argument_are_breaking():
    checker = _checker()
    baseline, current = _contract()
    broken = deepcopy(current)
    broken[0]["name"] = "renamed_tool"
    assert any("removed or renamed" in error for error in checker.check_contract(baseline, broken))
    broken = deepcopy(current)
    broken[0]["parameters"]["properties"]["new_required"] = {"type": "string"}
    broken[0]["parameters"]["required"].append("new_required")
    assert any("new required" in error for error in checker.check_contract(baseline, broken))


def test_constraints_may_widen_but_cannot_narrow():
    checker = _checker()
    baseline = {"api_major": 1, "tools": {
        "memory_wiki_example": {"type": "object", "properties": {
            "query": {"type": "string", "minLength": 2, "maxLength": 300},
            "choice": {"type": "string", "enum": ["one", "two"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }, "required": ["query"], "additionalProperties": False},
    }}
    current = [{"name": "memory_wiki_example", "parameters": deepcopy(baseline["tools"]["memory_wiki_example"])}]
    props = current[0]["parameters"]["properties"]
    props["query"]["minLength"] = 1
    props["query"]["maxLength"] = 400
    props["choice"]["enum"].append("three")
    props["limit"]["type"] = "number"
    props["limit"]["maximum"] = 30
    props["optional"] = {"type": "boolean"}
    assert checker.check_contract(baseline, current) == []
    props["query"]["minLength"] = 3
    props["choice"]["enum"] = ["one"]
    props["limit"]["maximum"] = 10
    errors = checker.check_contract(baseline, current)
    assert any("minLength increased" in error for error in errors)
    assert any("enum values removed" in error for error in errors)
    assert any("upper bound tightened" in error for error in errors)


def test_sdk_declares_separate_api_and_release_versions():
    assert sdk.SDK_API_VERSION == "1.0"
    version = next(
        line.partition(":")[2].strip()
        for line in (ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version:")
    )
    assert sdk.__version__ == version
