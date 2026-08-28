#!/usr/bin/env python3
"""Isolated document extraction worker.

Reads one JSON object from stdin and writes one JSON object to stdout. The parent
process is responsible for path allowlisting and applies OS resource limits before
starting this worker. Keeping parsers out of the Hermes gateway process prevents a
malformed office/PDF file from taking the agent down.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
try:
    from .document_extractors import extract_document
except ImportError:
    from document_extractors import extract_document


def _limit(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _apply_resource_limits() -> None:
    """Install parser limits inside the worker before it reads untrusted input."""
    if os.name != "posix":
        return
    try:
        import resource
    except ImportError:  # pragma: no cover - nonstandard POSIX Python
        return
    memory_mb = _limit("MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB", 1024, 128, 16_384)
    cpu_seconds = _limit("MEMORY_WIKI_DOCUMENT_WORKER_CPU_SECONDS", 120, 5, 3600)
    output_mb = _limit("MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB", 512, 8, 4096)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_mb * 1024 * 1024, output_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except OSError as exc:
        raise RuntimeError(f"unable to install document worker resource limits: {exc}") from exc


def main() -> int:
    try:
        _apply_resource_limits()
        raw = sys.stdin.buffer.read(int(os.environ.get("MEMORY_WIKI_DOCUMENT_WORKER_INPUT_MAX", "1048576")) + 1)
        if len(raw) > int(os.environ.get("MEMORY_WIKI_DOCUMENT_WORKER_INPUT_MAX", "1048576")):
            raise ValueError("worker input exceeds configured limit")
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("worker request must be an object")
        path = Path(str(request.get("path") or ""))
        options = request.get("options") or {}
        if not isinstance(options, dict):
            raise ValueError("options must be an object")
        payload = extract_document(path, options)
        response = {"ok": True, "document": payload}
    except BaseException as exc:
        response = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if os.environ.get("MEMORY_WIKI_DOCUMENT_WORKER_DEBUG", "0").lower() not in {"", "0", "false", "no", "off"}:
            response["traceback"] = traceback.format_exc(limit=8)[-6000:]
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str)
    max_output = max(1, int(os.environ.get("MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB", "512"))) * 1024 * 1024
    if len(encoded.encode("utf-8")) > max_output:
        response = {"ok": False, "error": "document worker output exceeds configured limit"}
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    # The parent decodes stdout as UTF-8. Write bytes directly so the worker
    # remains protocol-safe under Windows console code pages such as cp1251.
    sys.stdout.buffer.write(encoded.encode("utf-8"))
    return 0 if response.get("ok") else 2

if __name__ == "__main__":
    raise SystemExit(main())
