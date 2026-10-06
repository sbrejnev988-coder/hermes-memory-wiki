"""Run plugin regressions against the immutable official Hermes source checkout.

Only the import dependencies of this offline native integration gate are needed;
never install the unrelated PyPI hermes-agent distribution or optional tool stacks.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

CORE_SHA = "5307e93252ac655cd13fadbd561c0995142138c6"
# Keep in sync with --with requirements in both CI workflows. These SDK versions
# match the native runtime; ruamel.yaml is required by the real hermes_yaml module.
DEPENDENCIES = {
    "openai": "2.24.0",
    "httpx": "0.28.1",
    "pydantic": "2.13.4",
    "PyYAML": "6.0.3",
    "ruamel.yaml": "0.18.16",
}
EXPORTS = {
    "agent.auxiliary_client": (
        "CodexAuxiliaryClient", "_CodexCompletionsAdapter", "_CodexStreamGuard",
        "aux_stream_deadline", "_current_aux_stream_deadline", "_select_pool_entry",
    ),
    "agent.codex_headers": ("CODEX_AUX_BASE_URL", "codex_cloudflare_headers"),
    "agent.secret_scope": (
        "set_secret_scope", "reset_secret_scope", "current_secret_scope_home",
        "build_profile_secret_scope",
    ),
    "agent.credential_pool": ("load_pool",),
    "gateway.config_loader": ("bridged_allow_all_users",),
    "hermes_cli.auth": ("get_codex_auth_status", "resolve_codex_runtime_credentials"),
    "hermes_cli.auth_constants": ("_decode_jwt_claims", "DEFAULT_CODEX_BASE_URL"),
    "hermes_constants": (
        "get_hermes_home", "get_routing_process_hermes_home",
        "set_hermes_home_override", "reset_hermes_home_override",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    args, pytest_args = parser.parse_known_args()
    core = args.core.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    if Path.cwd().resolve() != root:
        raise RuntimeError("Run this gate from the plugin repository root")
    sha = subprocess.check_output(
        ["git", "-C", str(core), "rev-parse", "HEAD"], text=True,
    ).strip()
    if sha != CORE_SHA:
        raise RuntimeError(f"Unexpected native Hermes revision: {sha}")
    subprocess.run(["git", "-C", str(core), "diff", "--exit-code", "HEAD", "--"], check=True)
    for package, expected in DEPENDENCIES.items():
        version = importlib.metadata.version(package)
        if version != expected:
            raise RuntimeError(f"{package}: expected {expected}, found {version}")
    importlib.metadata.version("pytest")  # Missing test dependencies must fail, not skip.
    # Proposed S2 caller repair: only the two declared legacy workflow homes.
    # This producer is not a containment controller or a release receipt.
    fixture_home = Path(os.environ["HERMES_HOME"]).absolute()
    if fixture_home.parent != root or fixture_home.name not in {".hermes-ci", ".hermes-release"}:
        raise RuntimeError("Legacy native receipt requires a declared isolated workflow home")
    receipt_path = fixture_home.parent / "native-origins.json"
    for path in [*reversed(fixture_home.parents), fixture_home, receipt_path]:
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise RuntimeError("Native receipt path must not follow links or reparse points")
    if receipt_path.exists():
        raise RuntimeError("Refuse to overwrite previous native origin evidence")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(core))
    origins = {}
    for name, exports in {**EXPORTS, "agent.memory_provider": ("MemoryProvider",)}.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        if path != core / (name.replace(".", "/") + ".py"):
            raise RuntimeError(f"Native module did not load from pinned checkout: {name}")
        for export in exports:
            getattr(module, export)
        origins[name] = str(path)
    # Load the actual whole package before ordinary collection. Do not install
    # a standalone SDK shim or replace an already-loaded foreign package.
    plugin = sys.modules.get("memory_wiki")
    if plugin is None:
        spec = importlib.util.spec_from_file_location(
            "memory_wiki", root / "__init__.py", submodule_search_locations=[str(root)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Native plugin source loader unavailable")
        plugin = importlib.util.module_from_spec(spec)
        sys.modules["memory_wiki"] = plugin
        spec.loader.exec_module(plugin)
    native_base = importlib.import_module("agent.memory_provider").MemoryProvider
    if (Path(plugin.__file__).resolve() != root / "__init__.py"
            or plugin.MemoryProvider is not native_base
            or plugin.MemoryWikiProvider.__mro__[1] is not native_base):
        raise RuntimeError("Memory Wiki source or native MemoryProvider MRO mismatch")
    raw = (json.dumps({"origins": origins}, indent=2) + "\n").encode("utf-8")
    if len(raw) > 32768:
        raise RuntimeError("Native origin receipt exceeds the bounded fixture contract")
    # Exactly the existing ci_child.py:41 consumer schema, actual verified paths.
    # Exclusive creation preserves prior failed receipts; no fake preload field.
    with receipt_path.open("xb") as receipt:
        receipt.write(raw)
    if receipt_path.read_bytes() != raw:
        raise RuntimeError("Native origin receipt readback mismatch")
    print(f"Native Hermes contract verified: NousResearch/hermes-agent@{sha}", flush=True)
    import pytest
    # Explicit plugin test directory prevents discovery of the core's own tests.
    return pytest.main(["-q", "tests", *pytest_args])


if __name__ == "__main__":
    raise SystemExit(main())
