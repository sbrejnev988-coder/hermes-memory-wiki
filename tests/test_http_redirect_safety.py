"""Credential-bearing HTTP clients must never follow redirects."""

from __future__ import annotations

import importlib.util
import sys
import threading
from types import SimpleNamespace
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path, *, package: bool = False):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2.0)


def _quiet_log(*_args, **_kwargs):
    return None


def test_session_extractor_refuses_cross_origin_redirect(monkeypatch):
    received = []

    class Sink(BaseHTTPRequestHandler):
        log_message = _quiet_log

        def do_GET(self):
            received.append((self.command, dict(self.headers)))
            self.send_response(204)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received.append((self.command, dict(self.headers), self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

    with _server(Sink) as sink:
        sink_url = f"http://127.0.0.1:{sink.server_port}/stolen"

        class Redirect(BaseHTTPRequestHandler):
            log_message = _quiet_log

            def do_POST(self):
                self.send_response(307)
                self.send_header("Location", sink_url)
                self.end_headers()

        with _server(Redirect) as redirect:
            module = _load("memory_wiki_redirect_extractor", ROOT / "extractor.py")
            monkeypatch.setenv("MW_EXTRACTION_ENABLED", "1")
            monkeypatch.setenv(
                "MW_EXTRACTION_BASE_URL",
                f"http://127.0.0.1:{redirect.server_port}/extract",
            )
            monkeypatch.setenv("MW_EXTRACTION_API_KEY", "redirect-secret-key")
            monkeypatch.setenv("MW_EXTRACTION_MODEL", "test-model")
            result = module.extract_session_claims([
                {"role": "user", "content": "I prefer quiet mechanical keyboards."},
            ])

    assert "HTTPError" in result.get("error", "")
    assert received == []


def test_graph_extractor_refuses_cross_origin_redirect():
    received = []

    class Sink(BaseHTTPRequestHandler):
        log_message = _quiet_log

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received.append((dict(self.headers), self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

    with _server(Sink) as sink:
        sink_url = f"http://127.0.0.1:{sink.server_port}/stolen"

        class Redirect(BaseHTTPRequestHandler):
            log_message = _quiet_log

            def do_POST(self):
                self.send_response(307)
                self.send_header("Location", sink_url)
                self.end_headers()

        with _server(Redirect) as redirect:
            module = _load("memory_wiki_redirect_graph", ROOT / "entity_relation_extractor.py")
            with pytest.raises(Exception) as raised:
                module.extract_relations(
                    "Orion runs on Atlas.",
                    endpoint=f"http://127.0.0.1:{redirect.server_port}/extract",
                    api_key="redirect-secret-key",
                    model="test-model",
                    predicates=frozenset({"runs_on"}),
                )

    assert raised.type.__name__ == "HTTPError"
    assert received == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.invalid/api?redirect=https://evil.invalid",
        "https://example.invalid/api#fragment",
        "https://user:pass@example.invalid/api",
        "http://192.0.2.10/api",
    ],
)
def test_graph_extractor_rejects_unsafe_endpoint_before_network(endpoint, monkeypatch):
    module = _load("memory_wiki_graph_endpoint_validation", ROOT / "entity_relation_extractor.py")
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    with pytest.raises(ValueError, match="endpoint"):
        module.extract_relations(
            "Orion runs on Atlas.", endpoint=endpoint, api_key="key", model="model",
            predicates=frozenset({"runs_on"}),
        )


def test_curl_transport_keeps_credentials_out_of_process_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _load("memory_wiki_curl_boundary", ROOT / "__init__.py", package=True)
    import subprocess

    observed = []

    def run(args, **kwargs):
        observed.append((list(args), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout=b'{"ok": true}', stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    result = module._http_json_via_curl(
        "POST", "/embeddings", {"input": "safe fixture"}, timeout=5,
        headers={"Authorization": "Bearer command-line-secret"},
    )

    assert result == {"ok": True}
    args, kwargs = observed[0]
    assert "command-line-secret" not in " ".join(args)
    assert b"command-line-secret" in kwargs["input"]
    assert args[-2:] == ["--config", "-"]


def test_local_http_never_uses_environment_proxy(monkeypatch):
    import http_safety

    handlers_seen = []

    class DummyOpener:
        def open(self, _request, timeout):
            assert timeout == 2
            return "opened"

    def fake_opener(*handlers):
        handlers_seen.append(handlers)
        return DummyOpener()

    monkeypatch.setattr(http_safety.urllib.request, "build_opener", fake_opener)
    assert http_safety.urlopen_no_redirect("http://127.0.0.1:6333/collections", timeout=2) == "opened"
    assert any(isinstance(item, http_safety.urllib.request.ProxyHandler)
               and item.proxies == {} for item in handlers_seen[-1])
    assert http_safety.urlopen_no_redirect("https://openrouter.ai/api", timeout=2) == "opened"
    assert not any(isinstance(item, http_safety.urllib.request.ProxyHandler)
                   for item in handlers_seen[-1])


def test_tika_loopback_document_upload_ignores_environment_proxy(tmp_path, monkeypatch):
    module = _load("memory_wiki_tika_proxy_boundary", ROOT / "document_extractors.py")
    source = tmp_path / "document.txt"
    source.write_text("Telescope notes", encoding="utf-8")
    handlers_seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "http://127.0.0.1:9998/tika"

        def read(self, _max_bytes):
            return b"Telescope notes"

    class Opener:
        def open(self, request, timeout):
            assert request.data == b"Telescope notes"
            assert timeout == 2
            return Response()

    def fake_opener(*handlers):
        handlers_seen.append(handlers)
        return Opener()

    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:3128")
    monkeypatch.setattr(module.urllib.request, "build_opener", fake_opener)
    result = module.extract_tika(
        source, tika_url="http://127.0.0.1:9998/tika", timeout=2,
        max_chars=1000,
    )
    assert result.parser == "apache-tika"
    assert any(isinstance(item, module.urllib.request.ProxyHandler)
               and item.proxies == {} for item in handlers_seen[0])
    assert any(isinstance(item, module._NoRedirectHandler) for item in handlers_seen[0])


def test_qdrant_rejects_remote_plain_http_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_URL", "http://192.0.2.10:6333")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_API_KEY", "qdrant-transport-secret")
    module = _load("memory_wiki_qdrant_endpoint_boundary", ROOT / "__init__.py", package=True)
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )

    assert module._qdrant_req("GET", "/collections") is None


def test_reranker_rejects_remote_plain_http_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_RERANK_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_RERANK_URL", "http://192.0.2.10/rerank")
    monkeypatch.setenv("MEMORY_WIKI_RERANK_API_KEY", "rerank-transport-secret")
    module = _load("memory_wiki_rerank_endpoint_boundary", ROOT / "__init__.py", package=True)
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    provider = module.MemoryWikiProvider.__new__(module.MemoryWikiProvider)
    rows = [
        {
            "id": f"c-{index}", "claim": f"safe candidate {index}", "status": "active",
            "risk": "low", "quarantined_at": 0, "trust_class": "fact",
            "score_parts": {}, "updated_at": 1,
        }
        for index in range(12)
    ]

    assert module.RERANK_ENDPOINT_VALID is False
    assert provider._rerank_rows("long enough safe lookup", rows, "mixed") == rows
