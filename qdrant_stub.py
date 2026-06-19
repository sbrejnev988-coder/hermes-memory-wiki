#!/usr/bin/env python3
"""
qdrant_stub.py — Лёгкий HTTP-сервер, совместимый с Qdrant REST API.
Реализует минимальный набор эндпоинтов, нужных плагину evey-rag.
Хранит векторы в JSON-файле. Не требует внешних зависимостей.
"""
import json
import os
import math
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

STORAGE_DIR = os.path.expanduser("~/.hermes/knowledge_db")
STORAGE_FILE = os.path.join(STORAGE_DIR, "vectors.json")
os.makedirs(STORAGE_DIR, exist_ok=True)

# Загружаем или создаём хранилище
def load_store():
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE) as f:
            return json.load(f)
    return {"collections": {}}

def save_store(store):
    with open(STORAGE_FILE, "w") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

store = load_store()
store_lock = threading.Lock()

def cosine_similarity(a, b):
    """Косинусное сходство между двумя векторами."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class QdrantHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Тихий режим

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

    def _get_collection(self, name):
        with store_lock:
            if name not in store["collections"]:
                return None
            return store["collections"][name]

    def do_GET(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")

        # GET /health
        if path == "/health":
            return self._send_json({"status": "ok", "title": "qdrant-stub"})

        # GET /collections/{name}
        if len(parts) == 2 and parts[0] == "collections":
            col = self._get_collection(parts[1])
            if col is None:
                return self._send_json({"error": "Not found"}, 404)
            return self._send_json({
                "result": {
                    "status": "green",
                    "points_count": len(col["points"]),
                    "indexed_vectors_count": len(col["points"]),
                    "config": {"params": {"vectors": {"size": col["vector_size"]}}}
                }
            })

        self._send_json({"error": "Not found"}, 404)

    def do_PUT(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        body = self._read_body()

        # PUT /collections/{name} — создать коллекцию
        if len(parts) == 2 and parts[0] == "collections":
            name = parts[1]
            vector_size = 768  # дефолт
            if "vectors" in body:
                vector_size = body["vectors"].get("size", 768)
            with store_lock:
                if name not in store["collections"]:
                    store["collections"][name] = {
                        "vector_size": vector_size,
                        "points": {},  # id -> {vector, payload}
                        "next_id": 0,
                    }
                    save_store(store)
            return self._send_json({"result": True, "status": "ok"})

        # PUT /collections/{name}/points — upsert points
        if len(parts) == 3 and parts[0] == "collections" and parts[2] == "points":
            name = parts[1]
            col = self._get_collection(name)
            if col is None:
                return self._send_json({"error": "Collection not found"}, 404)

            points_data = body.get("points", [])
            with store_lock:
                for pt in points_data:
                    pid = str(pt.get("id", col["next_id"]))
                    col["points"][pid] = {
                        "vector": pt.get("vector", []),
                        "payload": pt.get("payload", {}),
                    }
                    col["next_id"] = max(col["next_id"], int(pid) if pid.isdigit() else 0) + 1
                save_store(store)
            return self._send_json({
                "result": {"operation_id": 0, "status": "completed"}
            })

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        body = self._read_body()

        # POST /collections/{name}/points/search
        if len(parts) == 4 and parts[0] == "collections" and parts[2] == "points" and parts[3] == "search":
            name = parts[1]
            col = self._get_collection(name)
            if col is None:
                return self._send_json({"error": "Collection not found"}, 404)

            query_vector = body.get("vector", [])
            limit = body.get("limit", 5)
            filter_type = None
            if "filter" in body and body["filter"]:
                filter_type = body["filter"].get("must", [{}])[0].get("match", {}).get("value")

            # Считаем сходство со всеми точками
            results = []
            for pid, pt in col["points"].items():
                if filter_type and pt["payload"].get("type") != filter_type:
                    continue
                score = cosine_similarity(query_vector, pt["vector"])
                results.append({
                    "id": pid,
                    "score": score,
                    "payload": pt["payload"],
                })

            # Сортируем по убыванию score
            results.sort(key=lambda x: x["score"], reverse=True)
            results = results[:limit]

            return self._send_json({"result": results})

        # POST /collections/{name}/points/scroll
        if len(parts) == 4 and parts[0] == "collections" and parts[2] == "points" and parts[3] == "scroll":
            name = parts[1]
            col = self._get_collection(name)
            if col is None:
                return self._send_json({"error": "Collection not found"}, 404)

            limit = body.get("limit", 500)
            points = []
            for pid, pt in list(col["points"].items())[:limit]:
                points.append({
                    "id": pid,
                    "payload": pt["payload"],
                })

            return self._send_json({"result": {"points": points}})

        self._send_json({"error": "Not found"}, 404)


def run(port=6333):
    server = HTTPServer(("127.0.0.1", port), QdrantHandler)
    print(f"Qdrant stub: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
