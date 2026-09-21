"""The MCP wrapper must not mix installed profile code and schema caches."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SERVER = Path(__file__).resolve().parents[1] / "mcp-wrapper" / "server.py"


def _server():
    spec = importlib.util.spec_from_file_location("mw_mcp_profile_paths_probe", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_colocated_wrapper_can_target_isolated_development_home(tmp_path):
    module = _server()
    module.HERMES_HOME = tmp_path
    module.PLUGIN_PATH = SERVER.parent.parent / "__init__.py"
    module.SCHEMAS_FILE = tmp_path / "cache" / "memory-wiki" / "schemas.json"
    module.assert_profile_paths_consistent()


def test_installed_other_profile_plugin_is_rejected(tmp_path):
    module = _server()
    module.HERMES_HOME = tmp_path
    target_install = tmp_path / "plugins" / "memory-wiki" / "__init__.py"
    target_install.parent.mkdir(parents=True)
    target_install.write_text("# synthetic plugin\n", encoding="utf-8")
    module.PLUGIN_PATH = SERVER.parent.parent / "__init__.py"
    module.SCHEMAS_FILE = tmp_path / "cache" / "memory-wiki" / "schemas.json"
    with pytest.raises(RuntimeError, match="profile home mismatch"):
        module.assert_profile_paths_consistent()


def test_cache_override_cannot_write_to_another_profile(tmp_path):
    module = _server()
    module.HERMES_HOME = tmp_path / "current"
    module.PLUGIN_PATH = SERVER.parent.parent / "__init__.py"
    module.SCHEMAS_FILE = tmp_path / "foreign" / "cache" / "schemas.json"
    with pytest.raises(RuntimeError, match="schema cache is outside"):
        module.assert_profile_paths_consistent()
