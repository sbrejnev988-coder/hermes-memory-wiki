#!/usr/bin/env python3
"""Regression: valid JSON values that are not objects cannot kill MCP stdio."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "mcp-wrapper" / "server.py"


def test_mcp_returns_invalid_request_and_keeps_running_for_json_null() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-mcp-invalid-request-") as tmp:
        env = os.environ.copy()
        env["HERMES_HOME"] = tmp
        env["HERMES_SECURITY_STRICT"] = "0"
        env["MEMORY_WIKI_SEMANTIC"] = "0"
        proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        assert proc.stdin and proc.stdout
        try:
            proc.stdin.write("null\n")
            proc.stdin.flush()
            invalid_line = proc.stdout.readline()
            assert invalid_line, "MCP process exited instead of returning Invalid Request"
            invalid = json.loads(invalid_line)
            assert invalid["id"] is None
            assert invalid["error"]["code"] == -32600

            proc.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"},
                    }
                )
                + "\n"
            )
            proc.stdin.flush()
            initialized = json.loads(proc.stdout.readline())
            assert initialized["id"] == 1
            assert initialized["result"]["protocolVersion"] == "2024-11-05"
        finally:
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    test_mcp_returns_invalid_request_and_keeps_running_for_json_null()
    print("PASS test_mcp_returns_invalid_request_and_keeps_running_for_json_null")
