#!/usr/bin/env python
"""Regression: document worker JSON must be UTF-8 on Windows code pages."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


WORKER = Path(__file__).resolve().parents[1] / "document_worker.py"


def test_worker_emits_utf8_json_under_cp1251() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-document-worker-") as tmp:
        document = Path(tmp) / "unicode.md"
        document.write_text("# Unicode\n\nArrow → check ✓ multiplication ×\n", encoding="utf-8")
        request = json.dumps({"path": str(document), "options": {}}).encode("utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(WORKER.parent)
        env["PYTHONIOENCODING"] = "cp1251"
        result = subprocess.run(
            [sys.executable, str(WORKER)],
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    response = json.loads(result.stdout.decode("utf-8"))
    assert response["ok"] is True
    assert response["document"]


if __name__ == "__main__":
    test_worker_emits_utf8_json_under_cp1251()
    print("PASS test_worker_emits_utf8_json_under_cp1251")
