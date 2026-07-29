#!/usr/bin/env python3
"""
embed_stub.py — Лёгкий embedding-сервер, совместимый с OpenAI/LiteLLM API.
Использует character n-gram hashing (без ML-зависимостей).
Размерность вектора: 768 (как arctic-embed).

v1.1 — HARDFENING (2026-06-27):
  + ThreadingMixIn — многопоточная обработка запросов
  + Логирование ошибок в /tmp/embed_stub.log
  + Graceful shutdown по SIGTERM
  + Memory guard: проверка свободной RAM перед большими запросами
"""
import json
import hashlib
import math
import os
import re
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from collections import Counter
from socket import SOL_SOCKET, SO_REUSEADDR

VECTOR_SIZE = int(os.environ.get("EMBED_VECTOR_SIZE", "768"))  # matches Qdrant collection
NGRAM_SIZES = [2, 3, 4]
MAX_TEXT_LEN = 32768  # pplx-embed-v1-4b context: 32768 tokens (~4 chars/tok)

idf_cache = {}
idf_lock = threading.Lock()
ERROR_LOG = "/tmp/embed_stub.log"

def stub_log(msg: str) -> None:
    try:
        with open(ERROR_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} EMBED {msg}\n")
    except Exception: pass

def check_memory(file_size_hint: int = 0) -> bool:
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0) or mem.get("MemFree", 0)
        if total == 0: return True
        return (available / total) >= 0.15
    except Exception: return True

# Qwen3-Embedding: retrieval instruction (только для search_query, не для document)
QWEN_QUERY_INSTRUCTION = os.environ.get(
    "QWEN_QUERY_INSTRUCTION",
    "Retrieve durable personal infrastructure facts, preferences, "
    "decisions and operational context relevant to the user's request."
)
QWEN_DOCUMENT_PREFIX = os.environ.get(
    "QWEN_DOCUMENT_PREFIX",
    ""
)

def tokenize(text): return re.findall(r'\w+', text.lower())
def extract_ngrams(word, n): return [word] if len(word) < n else [word[i:i+n] for i in range(len(word) - n + 1)]
def hash_ngram(ngram): return int.from_bytes(hashlib.md5(ngram.encode()).digest()[:4], 'big') % VECTOR_SIZE

def text_to_vector(text, idf=None, instruction: str = "", task_type: str = "search_document"):
    """Векторизация текста с опциональной retrieval-инструкцией.
    - task_type="search_query": instruction добавляется к тексту
    - task_type="search_document": текст индексируется без instruction
    """
    # Qwen3-style: document prefix для индексации, query instruction для поиска
    if task_type == "search_query" and instruction:
        text = instruction + "\n\n" + text
    elif task_type == "search_document" and QWEN_DOCUMENT_PREFIX:
        text = QWEN_DOCUMENT_PREFIX + text
    words = tokenize(text)
    if not words: return [0.0] * VECTOR_SIZE
    ngram_counts = Counter()
    for word in words:
        for n in NGRAM_SIZES:
            for ng in extract_ngrams(word, n): ngram_counts[ng] += 1
    if not ngram_counts: return [0.0] * VECTOR_SIZE
    vector = [0.0] * VECTOR_SIZE
    max_tf = max(ngram_counts.values())
    for ng, count in ngram_counts.items():
        idx = hash_ngram(ng)
        tf = count / max_tf
        if idf and ng in idf: tf *= idf[ng]
        vector[idx] += tf
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0: vector = [v / norm for v in vector]
    return vector

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True; daemon_threads = True
    def server_bind(self):
        self.socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

class EmbedHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if args and len(args) >= 2 and isinstance(args[1], int) and args[1] >= 400:
            stub_log(f"HTTP {args[1]} {self.path}")
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0: return {}
        if length > 5_000_000: stub_log(f"BODY_TOO_LARGE {length}b"); return {}
        try: return json.loads(self.rfile.read(length))
        except Exception as e: stub_log(f"JSON_PARSE_ERROR {e}"); return {}
    def do_GET(self):
        if self.path == "/health": return self._send_json({"status": "ok", "version": "1.1"})
        self._send_json({"error": "Not found"}, 404)
    def do_POST(self):
        if self.path in ("/v1/embeddings", "/embeddings"):
            if not check_memory(): return self._send_json({"error": "Server under memory pressure, retry later"}, 503)
            body = self._read_body()
            texts = body.get("input", "")
            if isinstance(texts, list): pass
            else: texts = [str(texts)]
            texts = [str(t)[:MAX_TEXT_LEN] for t in texts]
            task_type = body.get("task_type", body.get("input_type", "search_document"))
            instruction = body.get("instruction", "")
            if task_type == "search_query" and not instruction:
                instruction = QWEN_QUERY_INSTRUCTION
            with idf_lock: current_idf = dict(idf_cache) if idf_cache else None
            embeddings = []
            for text in texts:
                try: embeddings.append(text_to_vector(text, idf=current_idf, instruction=instruction, task_type=task_type))
                except Exception as e: stub_log(f"VECTORIZE_ERROR {e}"); embeddings.append([0.0] * VECTOR_SIZE)
            return self._send_json({"object": "list", "data": [{"object": "embedding", "index": i, "embedding": emb} for i, emb in enumerate(embeddings)], "model": body.get("model", "arctic-embed"), "usage": {"prompt_tokens": sum(len(re.findall(r'\w+', t.lower())) for t in texts), "total_tokens": sum(len(re.findall(r'\w+', t.lower())) for t in texts)}})
        self._send_json({"error": "Not found"}, 404)

def run(port=4000):
    server = ThreadingHTTPServer(("127.0.0.1", port), EmbedHandler)
    print(f"Embed stub v1.1: http://127.0.0.1:{port}")
    def shutdown(signum, frame): stub_log("SHUTDOWN"); server.shutdown()
    signal.signal(signal.SIGTERM, shutdown)
    stub_log(f"START port={port}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); stub_log("STOPPED")

if __name__ == "__main__": run()
