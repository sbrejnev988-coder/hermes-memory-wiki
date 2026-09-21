"""Secondary context packing enforces its outbound privacy boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, text: str):
        self.payload = json.dumps({
            "choices": [{"message": {"content": text}}],
        }).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


def test_llm_pack_redacts_query_and_context_before_remote_request(tmp_path, monkeypatch):
    module = _module("memory_wiki_llm_pack_privacy", tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_LLM_PACK", "1")
    monkeypatch.setenv("MEMORY_WIKI_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("MEMORY_WIKI_LLM_API_KEY", "transport-key")
    monkeypatch.setenv("MEMORY_WIKI_LLM_MODEL", "test-model")
    requests = []

    def request(request, *, timeout):
        requests.append((request, timeout, json.loads(request.data)))
        return _Response("- Atlas is the active deployment target.")

    monkeypatch.setattr(module, "_urlopen_no_redirect", request)
    provider = module.MemoryWikiProvider.__new__(module.MemoryWikiProvider)
    result = provider._llm_pack_context(
        "Find Atlas using password=correct-horse-92841",
        "Atlas is active; api_key=sk-or-v1-1234567890abcdefghijklmnop",
        1200,
    )

    assert result == "- Atlas is the active deployment target."
    assert len(requests) == 1
    request_obj, timeout, body = requests[0]
    outbound = json.dumps(body, ensure_ascii=False)
    assert "correct-horse-92841" not in outbound
    assert "sk-or-v1-1234567890abcdefghijklmnop" not in outbound
    assert "Atlas" in outbound
    assert request_obj.full_url == "https://llm.example.test/v1/chat/completions"
    assert 1 <= timeout <= 60


def test_llm_pack_rejects_non_loopback_http_before_network(tmp_path, monkeypatch):
    module = _module("memory_wiki_llm_pack_endpoint", tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_LLM_PACK", "1")
    monkeypatch.setenv("MEMORY_WIKI_LLM_BASE_URL", "http://192.0.2.10/v1")
    monkeypatch.setenv("MEMORY_WIKI_LLM_API_KEY", "transport-key")
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    provider = module.MemoryWikiProvider.__new__(module.MemoryWikiProvider)
    assert provider._llm_pack_context("Atlas", "Atlas is active", 1200) == ""
