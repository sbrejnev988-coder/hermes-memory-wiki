#!/usr/bin/env python3
"""Regression: recovery copies of Code Shrinker events retain redacted navigation text only."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_code_graph_recovery_artifact_redacts_pem_source_before_persistence() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-artifact-redact-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_artifact_redact_test")
            provider = module.MemoryWikiProvider(); provider.initialize("artifact-redact", hermes_home=tmp, agent_context="test")
            try:
                pem = "-----BEGIN PRIVATE KEY-----\nvery-secret-material\n-----END PRIVATE KEY-----"
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"; inbox.mkdir(parents=True, exist_ok=True)
                event = {
                    "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
                    "producer": "code-shrinker", "repository_id": "repo-artifact-redact", "event_id": "artifact-redact-event",
                    "snapshot_mode": "full", "snapshot_hash": "artifact-redact-hash",
                    "lines": [{"file_path": "src/key.py", "line_no": 1, "line_id": "line:repo-artifact-redact:src/key.py:1", "line_text": pem}],
                }
                (inbox / "event.json").write_text(json.dumps(event), encoding="utf-8")
                result = provider._drain_code_shrinker_events(limit=1)
                assert result["processed"] == 1, result
                artifact = next((home / "memory-wiki" / "recovery-artifacts" / "code-graph-inbox").glob("*.json"))
                saved = artifact.read_text(encoding="utf-8")
                assert pem not in saved
                assert "very-secret-material" not in saved
                assert "<REDACTED_PEM_BLOCK>" in saved
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_secret_scrub_rewrites_legacy_terminal_code_shrinker_event() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-terminal-redact-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_terminal_redact_test")
            provider = module.MemoryWikiProvider(); provider.initialize("terminal-redact", hermes_home=tmp, agent_context="test")
            try:
                secret = "short-secret-SENTINEL-9e38a"
                filename_secret = "ghp_" + "a" * 36
                terminal = home / "context-coordination" / "done" / "code-shrinker" / f"legacy-{filename_secret}.json"
                terminal.parent.mkdir(parents=True, exist_ok=True)
                terminal.write_text(
                    json.dumps({"metadata": {"api_key": secret}, "notes": f"Bearer {secret}"}),
                    encoding="utf-8",
                )

                result = provider._scrub_secrets(apply=True, limit=25)

                migrated = list(terminal.parent.glob("*.json"))
                assert not terminal.exists()
                assert len(migrated) == 1
                assert module._CODE_SHRINKER_TERMINAL_NAME_RE.fullmatch(migrated[0].name)
                saved = migrated[0].read_text(encoding="utf-8")
                assert secret not in saved
                assert filename_secret not in migrated[0].name
                assert "<REDACTED_KEYED_VALUE>" in saved
                assert result["code_graph_terminal"]["redacted"] == 1
                assert result["code_graph_terminal"]["renamed"] == 1
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_code_shrinker_terminal_names_never_retain_producer_filename() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-terminal-filename-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_terminal_filename_test")
            provider = module.MemoryWikiProvider(); provider.initialize("terminal-filename", hermes_home=tmp, agent_context="test")
            try:
                filename_secret = "ghp_" + "d" * 36
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                valid_event = {
                    "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
                    "producer": "code-shrinker", "repository_id": "repo-terminal-name",
                    "event_id": "terminal-name-event", "snapshot_mode": "full",
                    "snapshot_hash": "terminal-name-snapshot",
                    "lines": [{"file_path": "src/main.py", "line_no": 1,
                               "line_id": "line:repo-terminal-name:src/main.py:1", "line_text": "pass"}],
                }
                (inbox / f"valid-{filename_secret}.json").write_text(
                    json.dumps(valid_event), encoding="utf-8"
                )
                (inbox / f"invalid-{filename_secret}.json").write_text(
                    "not-json", encoding="utf-8"
                )

                result = provider._drain_code_shrinker_events(limit=2)

                assert result["processed"] == 1, result
                assert result["failed"] == 1, result
                terminal_files = list(
                    (home / "context-coordination" / "done" / "code-shrinker").glob("*.json")
                ) + list(
                    (home / "context-coordination" / "dead-letter" / "code-shrinker").glob("*.json")
                )
                assert len(terminal_files) == 3
                for artifact in terminal_files:
                    assert module._CODE_SHRINKER_TERMINAL_NAME_RE.fullmatch(artifact.name), artifact.name
                    assert filename_secret not in artifact.name
                    assert filename_secret not in artifact.read_text(encoding="utf-8")
                error_meta = next(path for path in terminal_files if path.name.endswith(".error.json"))
                assert json.loads(error_meta.read_text(encoding="utf-8"))["error"] == (
                    "event_processing_failed:JSONDecodeError"
                )
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_live_code_shrinker_event_rehashes_digest_shaped_producer_filename() -> None:
    """An inbox producer must not be able to select a terminal artifact name."""
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-terminal-rehash-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_terminal_rehash_test")
            provider = module.MemoryWikiProvider(); provider.initialize("terminal-rehash", hermes_home=tmp, agent_context="test")
            try:
                producer_name = "event-" + "a" * 64 + ".json"
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                event = {
                    "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
                    "producer": "code-shrinker", "repository_id": "repo-terminal-rehash",
                    "event_id": "terminal-rehash-event", "snapshot_mode": "full",
                    "files": [{"file_path": "src/main.py", "file_hash": "a" * 64}],
                }
                (inbox / producer_name).write_text(json.dumps(event), encoding="utf-8")

                result = provider._drain_code_shrinker_events(limit=1)
                assert result["processed"] == 1, result
                terminal_files = list((home / "context-coordination" / "done" / "code-shrinker").glob("*.json"))
                assert len(terminal_files) == 1
                assert terminal_files[0].name != producer_name
                assert module._CODE_SHRINKER_TERMINAL_NAME_RE.fullmatch(terminal_files[0].name)
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_code_shrinker_failure_logs_do_not_include_producer_filename() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-terminal-log-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_terminal_log_test")
            provider = module.MemoryWikiProvider(); provider.initialize("terminal-log", hermes_home=tmp, agent_context="test")
            original_debug = module._debug_log
            original_replace = module.os.replace
            original_atomic_write = module.atomic_write
            messages: list[str] = []
            try:
                filename_secret = "ghp_" + "e" * 36
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)

                module._debug_log = lambda message: messages.append(str(message))

                def fail_claim(source, _destination):
                    raise OSError(f"cannot claim {source}")

                (inbox / f"claim-{filename_secret}.json").write_text("{}", encoding="utf-8")
                module.os.replace = fail_claim
                provider._drain_code_shrinker_events(limit=1)
                module.os.replace = original_replace

                def fail_dead_letter(path, _text):
                    raise OSError(f"cannot write {path}")

                (inbox / f"dead-letter-{filename_secret}.json").write_text("not-json", encoding="utf-8")
                module.atomic_write = fail_dead_letter
                result = provider._drain_code_shrinker_events(limit=1)
                assert result["failed"] == 1, result

                log_text = "\n".join(messages)
                assert filename_secret not in log_text
                assert "terminal_ref=event-" in log_text
                assert "error=OSError" in log_text
            finally:
                module._debug_log = original_debug
                module.os.replace = original_replace
                module.atomic_write = original_atomic_write
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_code_graph_recovery_artifact_redacts_pem_source_before_persistence()
    test_secret_scrub_rewrites_legacy_terminal_code_shrinker_event()
    test_code_shrinker_terminal_names_never_retain_producer_filename()
    test_live_code_shrinker_event_rehashes_digest_shaped_producer_filename()
    test_code_shrinker_failure_logs_do_not_include_producer_filename()
    print("PASS test_code_graph_recovery_artifact_redacts_pem_source_before_persistence")
