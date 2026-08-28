#!/usr/bin/env python3
"""Regression: MCP wrapper errors never echo credential-shaped values."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "mcp-wrapper" / "server.py"


def load_server(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_mcp_error_response_redacts_bearer_and_assignment_secrets() -> None:
    module = load_server("memory_wiki_mcp_error_redaction_test")
    sent: list[dict] = []
    module.send = sent.append
    secret = "test-redaction-value"
    module.error_response(
        7,
        -32000,
        f"Authorization: Bearer {secret}; api_key={secret}; password={secret}",
    )

    message = sent[0]["error"]["message"]
    assert secret not in message
    assert "<redacted>" in message


if __name__ == "__main__":
    test_mcp_error_response_redacts_bearer_and_assignment_secrets()
    print("PASS test_mcp_error_response_redacts_bearer_and_assignment_secrets")
