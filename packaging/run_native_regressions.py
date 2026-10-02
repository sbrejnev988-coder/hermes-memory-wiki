"""Run plugin regressions against the immutable official Hermes source checkout.

Only the import dependencies of this offline native integration gate are needed;
never install the unrelated PyPI hermes-agent distribution or optional tool stacks.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
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
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(core))
    for name, exports in EXPORTS.items():
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(core):
            raise RuntimeError(f"Native module did not load from pinned checkout: {name}")
        for export in exports:
            getattr(module, export)
    print(f"Native Hermes contract verified: NousResearch/hermes-agent@{sha}", flush=True)
    import pytest
    # Explicit plugin test directory prevents discovery of the core's own tests.
    return pytest.main(["-q", "tests", *pytest_args])


if __name__ == "__main__":
    raise SystemExit(main())
