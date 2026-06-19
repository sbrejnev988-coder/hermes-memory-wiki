#!/usr/bin/env python3
"""
embed_stub.py — Лёгкий embedding-сервер, совместимый с OpenAI/LiteLLM API.
Использует character n-gram hashing (без ML-зависимостей).
Размерность вектора: 768 (как arctic-embed).
"""
import json
import hashlib
import math
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import Counter

VECTOR_SIZE = 768
NGRAM_SIZES = [2, 3, 4]  # какие n-граммы извлекаем

# Глобальный IDF (заполняется при индексации)
idf_cache = {}
idf_lock = threading.Lock()

def tokenize(text):
    """Разбивает текст на слова (простейшая токенизация)."""
    return re.findall(r'\w+', text.lower())

def extract_ngrams(word, n):
    """Извлекает character n-граммы из слова."""
    if len(word) < n:
        return [word]
    return [word[i:i+n] for i in range(len(word) - n + 1)]

def hash_ngram(ngram):
    """Хеширует n-грамму в индекс вектора (0..VECTOR_SIZE-1)."""
    h = hashlib.md5(ngram.encode()).digest()
    # Берём первые 4 байта как integer
    val = int.from_bytes(h[:4], 'big')
    return val % VECTOR_SIZE

def text_to_vector(text, idf=None):
    """
    Превращает текст в вектор размерности VECTOR_SIZE.
    Использует character n-gram hashing + TF или TF-IDF.
    """
    words = tokenize(text)
    if not words:
        return [0.0] * VECTOR_SIZE

    # Собираем все n-граммы
    ngram_counts = Counter()
    for word in words:
        for n in NGRAM_SIZES:
            for ng in extract_ngrams(word, n):
                ngram_counts[ng] += 1

    if not ngram_counts:
        return [0.0] * VECTOR_SIZE

    # Строим вектор (TF или TF-IDF)
    vector = [0.0] * VECTOR_SIZE
    max_tf = max(ngram_counts.values())

    for ng, count in ngram_counts.items():
        idx = hash_ngram(ng)
        tf = count / max_tf  # нормализованный TF
        if idf and ng in idf:
            tf *= idf[ng]  # применяем IDF
        vector[idx] += tf

    # L2-нормализация
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]

    return vector


class EmbedHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/health":
            return self._send_json({"status": "ok"})
        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path == "/v1/embeddings" or self.path == "/embeddings":
            body = self._read_body()
            text_input = body.get("input", "")

            # Если input — список, берём первый (или обрабатываем все)
            if isinstance(text_input, list):
                texts = text_input
            else:
                texts = [str(text_input)]

            with idf_lock:
                current_idf = dict(idf_cache) if idf_cache else None

            embeddings = []
            for text in texts:
                vec = text_to_vector(text, idf=current_idf)
                embeddings.append(vec)

            return self._send_json({
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": emb}
                    for i, emb in enumerate(embeddings)
                ],
                "model": body.get("model", "arctic-embed"),
                "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": sum(len(t) for t in texts)},
            })

        self._send_json({"error": "Not found"}, 404)


def run(port=4000):
    server = HTTPServer(("127.0.0.1", port), EmbedHandler)
    print(f"Embed stub: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
