"""Small synchronous Python client for the bundled Memory Wiki MCP server.

Each client starts its own stdio server with an explicit caller identity. This
keeps chat/bot/project visibility independent between agents sharing a home.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping


SDK_API_VERSION = "1.0"
__version__ = "1.24.0"


class MemoryWikiClientError(RuntimeError):
    """The MCP transport or provider rejected a request."""


class MemoryWikiClient:
    def __init__(
        self,
        *,
        hermes_home: str | Path,
        session_id: str,
        bot_id: str,
        project_id: str = "",
        plugin_dir: str | Path | None = None,
        timeout: float = 30.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not str(session_id).strip() or not str(bot_id).strip():
            raise ValueError("session_id and bot_id must be nonempty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        plugin = Path(plugin_dir or Path(__file__).resolve().parent).resolve()
        wrapper = plugin / "mcp-wrapper" / "server.py"
        if not (plugin / "__init__.py").is_file() or not wrapper.is_file():
            raise FileNotFoundError("Memory Wiki plugin and MCP wrapper must be colocated")

        child_env = os.environ.copy()
        child_env.update({
            "HERMES_HOME": str(Path(hermes_home).expanduser().resolve()),
            "MW_PLUGIN_PATH": str(plugin / "__init__.py"),
            "MW_MCP_SESSION_ID": str(session_id),
            "MW_MCP_BOT_ID": str(bot_id),
            "MW_MCP_PROJECT_ID": str(project_id),
            "PYTHONUTF8": "1",
        })
        if env:
            # Identity is set after caller options, so overrides cannot silently
            # collapse two clients into the same visibility principal.
            child_env.update({str(key): str(value) for key, value in env.items()})
            child_env.update({
                "HERMES_HOME": str(Path(hermes_home).expanduser().resolve()),
                "MW_PLUGIN_PATH": str(plugin / "__init__.py"),
                "MW_MCP_SESSION_ID": str(session_id),
                "MW_MCP_BOT_ID": str(bot_id),
                "MW_MCP_PROJECT_ID": str(project_id),
            })

        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self._responses: queue.Queue[dict | None] = queue.Queue()
        self._next_id = 1
        self._closed = False
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [sys.executable, "-u", str(wrapper)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            bufsize=1, env=child_env, creationflags=creationflags,
        )
        self._reader = threading.Thread(target=self._read_responses, daemon=True)
        self._reader.start()
        try:
            self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "memory-wiki-python-sdk", "version": __version__},
            })
            self._notify("notifications/initialized", {})
        except Exception:
            self.close()
            raise

    def _read_responses(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(response, dict):
                    self._responses.put(response)
        finally:
            self._responses.put(None)

    def _write(self, message: dict[str, Any]) -> None:
        if self._closed or self._process.poll() is not None:
            raise MemoryWikiClientError("Memory Wiki MCP server is closed")
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MemoryWikiClientError("Memory Wiki MCP server stopped") from exc

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MemoryWikiClientError(f"Memory Wiki MCP {method} timed out")
                try:
                    response = self._responses.get(timeout=remaining)
                except queue.Empty as exc:
                    raise MemoryWikiClientError(f"Memory Wiki MCP {method} timed out") from exc
                if response is None:
                    raise MemoryWikiClientError("Memory Wiki MCP server ended without a response")
                response_id = response.get("id")
                if response_id is None or (isinstance(response_id, int) and response_id < request_id):
                    # A notification or a late reply to a timed-out request.
                    continue
                if response_id != request_id:
                    raise MemoryWikiClientError("Memory Wiki MCP response ID mismatch")
                if "error" in response:
                    error = response["error"] or {}
                    raise MemoryWikiClientError(str(error.get("message") or "MCP request failed"))
                return response.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        return list(result.get("tools") or [])

    def call_tool(self, name: str, **arguments: Any) -> Any:
        mcp_name = "mw_" + name[len("memory_wiki_"):] if name.startswith("memory_wiki_") else name
        result = self._request("tools/call", {"name": mcp_name, "arguments": arguments})
        blocks = result.get("content") or []
        if not blocks or blocks[0].get("type") != "text":
            raise MemoryWikiClientError("Memory Wiki MCP returned no text result")
        text = str(blocks[0].get("text") or "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def query(self, text: str, *, limit: int = 10) -> Any:
        return self.call_tool("memory_wiki_query", query=text, limit=limit)

    def add_claim(self, claim: str, *, topic: str = "general", visibility_scope: str = "chat",
                  source: str = "tool", evidence: str = "", confidence: float = 0.75) -> Any:
        """Submit an unverified claim for this chat; legacy scope/source options are ignored."""
        return self.call_tool(
            "memory_wiki_add_claim", claim=claim, topic=topic,
            evidence=evidence, confidence=confidence,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)

    def __enter__(self) -> "MemoryWikiClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
