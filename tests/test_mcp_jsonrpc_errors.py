#!/usr/bin/env python3
"""Regression: malformed MCP JSON-RPC receives a standard parse error."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "mcp-wrapper" / "server.py"


def test_mcp_returns_parse_error_for_invalid_json() -> None:
    result = subprocess.run(
        [sys.executable, str(SERVER)],
        input="{not-json}\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["id"] is None
    assert response["error"]["code"] == -32700
    assert response["error"]["message"] == "Parse error"


if __name__ == "__main__":
    test_mcp_returns_parse_error_for_invalid_json()
    print("PASS test_mcp_returns_parse_error_for_invalid_json")
