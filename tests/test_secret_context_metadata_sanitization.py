from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "secret_context_bridge.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_secret_context_sanitize_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bridge_does_not_render_connection_metadata_from_external_plugin() -> None:
    module = _load_module()
    password = "SYNTHETIC_EXTERNAL_PASSWORD_891d"
    host = "203.0.113.77"
    username = "external-user"
    match = module._normalize_match(
        {
            "secret_id": "sec_external_safety_test",
            "lookup_key": "safe-test/external/ssh",
            "host": host,
            "username": username,
            "password": password,
            "description": "private server connection",
            "has_value": True,
            "policy": {
                "target_locator": f"ssh://{username}@{host}:22",
                "allowed_executors": ["ssh"],
                "require_user_approval": True,
            },
        }
    )
    rendered = json.dumps(match, ensure_ascii=False)
    assert match is not None
    assert match["lookup_key"] == "safe-test/external/ssh"
    assert match["subject"] == "safe-test/external/ssh"
    assert match["scope"] == "safe-test/external/ssh"
    assert match["locator"] == ""
    assert match["username"] == ""
    assert match["purpose"] == ""
    assert match["policy"] == {"allowed_executors": ["ssh"], "require_user_approval": True}
    assert host not in rendered
    assert username not in rendered
    assert password not in rendered
