#!/usr/bin/env python3
"""Local deterministic embedding fallback for Hermes Memory Wiki.

This is not a machine-learning model and must not be labelled as PPLX/Qwen/etc.
It provides normalized character n-gram hashing vectors through an
OpenAI-compatible /embeddings endpoint.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from socket import SOL_SOCKET, SO_REUSEADDR
from socketserver import ThreadingMixIn
from typing import Any

VERSION = "1.2"
ALGORITHM = "character-ngram-hashing"
MIN_VECTOR_SIZE = 8
MAX_VECTOR_SIZE = 65536
NGRAM_SIZES = (2, 3, 4)
MAX_TEXT_LEN = max(256, int(os.environ.get("EMBED_MAX_TEXT_CHARS", "32768")))
ERROR_LOG = os.environ.get("EMBED_STUB_LOG", "/tmp/embed_stub.log")


def _bounded_dimension(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if not MIN_VECTOR_SIZE <= parsed <= MAX_VECTOR_SIZE:
        raise ValueError(
            f"embedding dimensions must be {MIN_VECTOR_SIZE}..{MAX_VECTOR_SIZE}, got {parsed}"
        )
    return parsed


DEFAULT_VECTOR_SIZE = _bounded_dimension(
    os.environ.get("EMBED_VECTOR_SIZE")
    or os.environ.get("MEMORY_WIKI_VECTOR_SIZE")
    or "2560",
    2560,
)
DEFAULT_MODEL = f"hash-ngram-{DEFAULT_VECTOR_SIZE}"
QWEN_QUERY_INSTRUCTION = os.environ.get(
    "QWEN_QUERY_INSTRUCTION",
    "Retrieve durable personal infrastructure facts, preferences, decisions "
    "and operational context relevant to the user's request.",
)
QWEN_DOCUMENT_PREFIX = os.environ.get("QWEN_DOCUMENT_PREFIX", "")

idf_cache: dict[str, float] = {}
idf_lock = threading.Lock()


def stub_log(message: str) -> None:
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} EMBED {message}\n")
    except Exception:
        pass


def check_memory() -> bool:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            mem: dict[str, int] = {}
            for line in handle:
                key, sep, value = line.partition(":")
                if sep:
                    mem[key.strip()] = int(value.strip().split()[0])
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0) or mem.get("MemFree", 0)
        return total == 0 or (available / total) >= 0.15
    except Exception:
        return True


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower(), flags=re.UNICODE)


def extract_ngrams(word: str, size: int) -> list[str]:
    if len(word) < size:
        return [word]
    return [word[index:index + size] for index in range(len(word) - size + 1)]


def hash_ngram(ngram: str, vector_size: int) -> int:
    digest = hashlib.md5(ngram.encode("utf-8"), usedforsecurity=False).digest()
    return int.from_bytes(digest[:4], "big") % vector_size


def text_to_vector(
    text: str,
    *,
    vector_size: int = DEFAULT_VECTOR_SIZE,
    idf: dict[str, float] | None = None,
    instruction: str = "",
    task_type: str = "search_document",
) -> list[float]:
    vector_size = _bounded_dimension(vector_size, DEFAULT_VECTOR_SIZE)
    if task_type == "search_query" and instruction:
        text = instruction + "\n\n" + text
    elif task_type == "search_document" and QWEN_DOCUMENT_PREFIX:
        text = QWEN_DOCUMENT_PREFIX + text

    words = tokenize(text)
    if not words:
        return [0.0] * vector_size

    counts: Counter[str] = Counter()
    for word in words:
        for size in NGRAM_SIZES:
            counts.update(extract_ngrams(word, size))
    if not counts:
        return [0.0] * vector_size

    vector = [0.0] * vector_size
    max_tf = max(counts.values())
    for ngram, count in counts.items():
        index = hash_ngram(ngram, vector_size)
        weight = count / max_tf
        if idf and ngram in idf:
            weight *= idf[ngram]
        vector[index] += weight

    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm > 0 else vector


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        super().server_bind()


class EmbedHandler(BaseHTTPRequestHandler):
    server_version = f"MemoryWikiEmbedStub/{VERSION}"

    def log_message(self, fmt: str, *args: Any) -> None:
        if args and len(args) >= 2 and isinstance(args[1], int) and args[1] >= 400:
            stub_log(f"HTTP {args[1]} {self.path}")

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _read_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        if length > 5_000_000:
            raise ValueError(f"request body too large: {length}")
        raw = self.rfile.read(length)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "version": VERSION,
                    "algorithm": ALGORITHM,
                    "model": DEFAULT_MODEL,
                    "vector_size": DEFAULT_VECTOR_SIZE,
                    "supports_dimensions": True,
                    "min_dimensions": MIN_VECTOR_SIZE,
                    "max_dimensions": MAX_VECTOR_SIZE,
                }
            )
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path.rstrip("/") not in ("/v1/embeddings", "/embeddings"):
            self._send_json({"error": "not found"}, 404)
            return
        if not check_memory():
            self._send_json({"error": "server under memory pressure; retry later"}, 503)
            return
        try:
            body = self._read_body()
            vector_size = _bounded_dimension(body.get("dimensions"), DEFAULT_VECTOR_SIZE)
            raw_inputs = body.get("input", "")
            texts = raw_inputs if isinstance(raw_inputs, list) else [raw_inputs]
            texts = [str(text)[:MAX_TEXT_LEN] for text in texts]
            if not texts:
                raise ValueError("input must not be empty")
            task_type = str(body.get("task_type", body.get("input_type", "search_document")))
            instruction = str(body.get("instruction", ""))
            if task_type == "search_query" and not instruction:
                instruction = QWEN_QUERY_INSTRUCTION
            with idf_lock:
                current_idf = dict(idf_cache) if idf_cache else None
            embeddings = [
                text_to_vector(
                    text,
                    vector_size=vector_size,
                    idf=current_idf,
                    instruction=instruction,
                    task_type=task_type,
                )
                for text in texts
            ]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            stub_log(f"BAD_REQUEST {type(exc).__name__}: {exc}")
            self._send_json({"error": str(exc)}, 400)
            return
        except Exception as exc:
            stub_log(f"VECTORIZE_ERROR {type(exc).__name__}: {exc}")
            self._send_json({"error": "embedding generation failed"}, 500)
            return

        token_count = sum(len(tokenize(text)) for text in texts)
        self._send_json(
            {
                "object": "list",
                "data": [
                    {"object": "embedding", "index": index, "embedding": embedding}
                    for index, embedding in enumerate(embeddings)
                ],
                "model": DEFAULT_MODEL,
                "dimensions": vector_size,
                "usage": {"prompt_tokens": token_count, "total_tokens": token_count},
            }
        )


def run(port: int | None = None) -> None:
    port = int(port or os.environ.get("EMBED_PORT", "4000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), EmbedHandler)
    print(
        f"Embed stub v{VERSION}: http://127.0.0.1:{port} "
        f"model={DEFAULT_MODEL} vector_size={DEFAULT_VECTOR_SIZE}",
        flush=True,
    )

    def shutdown(_signum: int, _frame: Any) -> None:
        stub_log("SHUTDOWN")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    stub_log(f"START port={port} model={DEFAULT_MODEL} vector_size={DEFAULT_VECTOR_SIZE}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        stub_log("STOPPED")


if __name__ == "__main__":
    run()
