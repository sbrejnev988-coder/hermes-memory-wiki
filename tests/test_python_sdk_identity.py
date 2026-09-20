"""The external Python SDK gives each MCP process an explicit scope."""

from __future__ import annotations

import json
import queue
import threading

from sdk import MemoryWikiClient


def test_sdk_ignores_late_response_after_timeout():
    client = object.__new__(MemoryWikiClient)
    client._lock = threading.RLock()
    client._responses = queue.Queue()
    client._next_id = 2
    client.timeout = 1.0
    sent = []
    client._write = sent.append
    client._responses.put({"jsonrpc": "2.0", "id": 1, "result": {"late": True}})
    client._responses.put({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})
    client._responses.put({"jsonrpc": "2.0", "id": 2, "result": {"ok": True}})
    assert client._request("tools/list", {}) == {"ok": True}
    assert sent[0]["id"] == 2


def test_sdk_sessions_do_not_share_chat_claims(tmp_path):
    options = {
        "hermes_home": tmp_path,
        "env": {"HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"},
    }
    with MemoryWikiClient(session_id="sdk-chat-a", bot_id="sdk-bot-a", **options) as client:
        written = client.add_claim(
            "The Helios deployment runbook uses the synthetic marker Vireo.",
            topic="deployment",
        )
        assert written.get("success") is True
        assert written.get("state") == "stored"
        assert written.get("immediately_recallable") is True
        own = client.call_tool("memory_wiki_export", limit=10)
        assert "Vireo" in json.dumps(own, ensure_ascii=False)
        own_text = json.dumps(own, ensure_ascii=False)
        assert '"verification_status": "unverified"' in own_text
        assert '"visibility_scope": "chat"' in own_text

    with MemoryWikiClient(session_id="sdk-chat-b", bot_id="sdk-bot-b", **options) as client:
        foreign = client.call_tool("memory_wiki_export", limit=10)
        assert "Vireo" not in json.dumps(foreign, ensure_ascii=False)
