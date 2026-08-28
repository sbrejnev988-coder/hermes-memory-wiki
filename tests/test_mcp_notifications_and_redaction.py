#!/usr/bin/env python3
"""Regression: MCP notifications are silent and error redaction covers common secrets."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-wrapper" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_mcp_redaction_test", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_error_redaction_hides_sk_proj_and_quoted_password() -> None:
    module = load_server_module()
    raw = 'OpenAI rejected sk-proj-abcdefghijklmnopqrstuvwxyz0123456789 password="multi word passphrase"'
    safe = module.redact_error_message(raw)
    assert "sk-proj-" not in safe
    assert "multi word passphrase" not in safe


def test_mcp_notification_does_not_emit_a_response() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-mcp-notification-") as tmp:
        env = os.environ.copy()
        env.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
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
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "unknown/notification"}) + "\n")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
            proc.stdin.flush()
            response = json.loads(proc.stdout.readline())
            assert response["id"] == 1
            assert "result" in response
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    test_mcp_error_redaction_hides_sk_proj_and_quoted_password()
    test_mcp_notification_does_not_emit_a_response()
    print("PASS test_mcp_error_redaction_hides_sk_proj_and_quoted_password")
    print("PASS test_mcp_notification_does_not_emit_a_response")
