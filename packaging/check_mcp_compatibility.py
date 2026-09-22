#!/usr/bin/env python3
"""Check the public MCP input contract against the pinned major-version API."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "compatibility" / "mcp-api-v1.json"
CURRENT = ROOT / "mcp-wrapper" / "tool_schemas.json"
MCP_API_MAJOR = 1

_ANNOTATIONS = frozenset({"title", "description", "examples", "$comment", "readOnly", "writeOnly"})
_VALIDATION_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "items",
    "enum", "const", "default", "pattern", "format", "minLength", "maxLength",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties",
    "multipleOf", "nullable",
})


def _types(schema: dict[str, Any]) -> set[str]:
    value = schema.get("type")
    if value is None:
        result = {"null", "boolean", "integer", "number", "string", "array", "object"}
    elif isinstance(value, str):
        result = {value}
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        result = set(value)
    else:
        raise ValueError("invalid MCP schema type")
    if schema.get("nullable"):
        result.add("null")
    return result


def _accepted_types(types: set[str]) -> set[str]:
    # JSON Schema number accepts integers too.
    return types | ({"integer"} if "number" in types else set())


def _lower_bound(schema: dict[str, Any]) -> tuple[float, bool] | None:
    if "exclusiveMinimum" in schema and isinstance(schema["exclusiveMinimum"], (int, float)):
        return float(schema["exclusiveMinimum"]), True
    if "minimum" in schema:
        return float(schema["minimum"]), False
    return None


def _upper_bound(schema: dict[str, Any]) -> tuple[float, bool] | None:
    if "exclusiveMaximum" in schema and isinstance(schema["exclusiveMaximum"], (int, float)):
        return float(schema["exclusiveMaximum"]), True
    if "maximum" in schema:
        return float(schema["maximum"]), False
    return None


def _schema_errors(old: dict[str, Any], new: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    for label, schema in (("baseline", old), ("current", new)):
        unsupported = set(schema) - _VALIDATION_KEYS - _ANNOTATIONS
        if unsupported:
            errors.append(f"{path}: {label} uses unsupported validation keywords {sorted(unsupported)}")
    if errors:
        return errors
    try:
        if not _accepted_types(_types(old)).issubset(_accepted_types(_types(new))):
            errors.append(f"{path}: accepted types narrowed")
    except ValueError as exc:
        errors.append(f"{path}: {exc}")
    old_allowed = old.get("enum")
    new_allowed = new.get("enum")
    if old_allowed is None and new_allowed is not None:
        errors.append(f"{path}: enum restriction added")
    elif old_allowed is not None and new_allowed is not None:
        if any(value not in new_allowed for value in old_allowed):
            errors.append(f"{path}: enum values removed")
    if "const" in old:
        if "const" in new and old["const"] != new["const"]:
            errors.append(f"{path}: const changed")
        elif new_allowed is not None and old["const"] not in new_allowed:
            errors.append(f"{path}: const excluded by enum")
    elif "const" in new:
        errors.append(f"{path}: const restriction added")
    if "default" in old and old.get("default") != new.get("default"):
        errors.append(f"{path}: default changed or removed")
    elif "default" not in old and "default" in new:
        errors.append(f"{path}: default added to existing argument")
    for key in ("pattern", "format", "multipleOf"):
        if key in new and old.get(key) != new[key]:
            errors.append(f"{path}: {key} added or changed")
    for key in ("minLength", "minItems", "minProperties"):
        if key in new and (key not in old or new[key] > old[key]):
            errors.append(f"{path}: {key} increased")
    for key in ("maxLength", "maxItems", "maxProperties"):
        if key in new and (key not in old or new[key] < old[key]):
            errors.append(f"{path}: {key} decreased")
    for bound_fn, direction in ((_lower_bound, "lower"), (_upper_bound, "upper")):
        prior, current = bound_fn(old), bound_fn(new)
        if current is not None and (prior is None or
                (current[0] > prior[0] if direction == "lower" else current[0] < prior[0]) or
                (current[0] == prior[0] and current[1] and not prior[1])):
            errors.append(f"{path}: {direction} bound tightened")
    if new.get("uniqueItems", False) and not old.get("uniqueItems", False):
        errors.append(f"{path}: uniqueItems restriction added")

    old_required = set(old.get("required") or ())
    new_required = set(new.get("required") or ())
    if new_required - old_required:
        errors.append(f"{path}: new required arguments {sorted(new_required - old_required)}")
    old_props = old.get("properties") or {}
    new_props = new.get("properties") or {}
    if not isinstance(old_props, dict) or not isinstance(new_props, dict):
        return errors + [f"{path}: properties must be objects"]
    for name, old_schema in old_props.items():
        if name not in new_props:
            errors.append(f"{path}.{name}: argument removed or renamed")
        elif not isinstance(old_schema, dict) or not isinstance(new_props[name], dict):
            errors.append(f"{path}.{name}: argument schema must be an object")
        else:
            errors.extend(_schema_errors(old_schema, new_props[name], f"{path}.{name}"))

    old_extra = old.get("additionalProperties", True)
    new_extra = new.get("additionalProperties", True)
    if new_extra is False and old_extra is not False:
        errors.append(f"{path}: additionalProperties now prohibited")
    elif isinstance(new_extra, dict):
        if old_extra is True:
            errors.append(f"{path}: additionalProperties now restricted")
        elif isinstance(old_extra, dict):
            errors.extend(_schema_errors(old_extra, new_extra, f"{path}.*"))
    old_items, new_items = old.get("items"), new.get("items")
    if new_items is not None and old_items is None:
        errors.append(f"{path}: item schema added")
    elif isinstance(old_items, dict) and isinstance(new_items, dict):
        errors.extend(_schema_errors(old_items, new_items, f"{path}[]"))
    elif old_items is not None and new_items is not None and old_items != new_items:
        errors.append(f"{path}: item schema changed")
    return errors


def check_contract(baseline: dict[str, Any], current: list[dict[str, Any]]) -> list[str]:
    if baseline.get("api_major") != MCP_API_MAJOR:
        return ["MCP baseline major does not match this checker"]
    previous = baseline.get("tools")
    if not isinstance(previous, dict) or not previous:
        return ["MCP baseline has no tool contract"]
    names = [tool.get("name") for tool in current if isinstance(tool, dict)]
    if len(names) != len(current) or len(names) != len(set(names)):
        return ["current MCP tool names are malformed or duplicated"]
    current_by_name = {tool["name"]: tool for tool in current}
    errors: list[str] = []
    for name, parameters in previous.items():
        tool = current_by_name.get(name)
        if tool is None:
            errors.append(f"{name}: tool removed or renamed")
        elif not isinstance(parameters, dict) or not isinstance(tool.get("parameters"), dict):
            errors.append(f"{name}: parameters schema is missing")
        else:
            errors.extend(_schema_errors(parameters, tool["parameters"], name))
    return errors


def main() -> int:
    try:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        current = json.loads(CURRENT.read_text(encoding="utf-8"))
        errors = check_contract(baseline, current)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"MCP_COMPATIBILITY_FAIL: {type(exc).__name__}", file=sys.stderr)
        return 2
    if errors:
        for error in errors[:40]:
            print(f"MCP_COMPATIBILITY_FAIL: {error}", file=sys.stderr)
        return 2
    print(f"MCP_COMPATIBILITY_OK major={MCP_API_MAJOR} tools={len(baseline['tools'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
