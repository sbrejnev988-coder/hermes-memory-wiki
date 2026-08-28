#!/usr/bin/env python3
"""MCP release contract: initialize reports the installed plugin version."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-wrapper" / "server.py"
MANIFEST = ROOT / "plugin.yaml"


def manifest_version() -> str:
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.partition(":")[2].strip().strip('"\'')
    raise AssertionError("plugin.yaml has no version")


def test_mcp_initialize_version_matches_manifest() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-mcp-version-") as tmp:
        env = os.environ.copy()
        env.update(
            {
                "HERMES_HOME": tmp,
                "HERMES_SECURITY_STRICT": "0",
                "MEMORY_WIKI_SEMANTIC": "0",
                "MW_PLUGIN_PATH": str(ROOT / "__init__.py"),
            }
        )
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "memory-wiki-test", "version": "1"},
            },
        }
        result = subprocess.run(
            [sys.executable, str(SERVER)],
            input=json.dumps(request) + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env=env,
        )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["result"]["serverInfo"]["version"] == manifest_version()


if __name__ == "__main__":
    test_mcp_initialize_version_matches_manifest()
    print("PASS test_mcp_initialize_version_matches_manifest")
