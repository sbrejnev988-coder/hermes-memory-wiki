"""Run plugin regressions against the immutable official Hermes source checkout.

Only the import dependencies of this offline native integration gate are needed;
never install the unrelated PyPI hermes-agent distribution or optional tool stacks.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import hashlib
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


def collection_reporter(source: Path, evidence_root: Path):
    """Load only the shared stdlib reporter, never tests/conftest or a package."""
    spec = importlib.util.spec_from_file_location(
        '_memory_wiki_collection_evidence', source / 'tests/helpers/collection_evidence.py',
    )
    if spec is None or spec.loader is None:
        raise RuntimeError('Collection evidence reporter source loader unavailable')
    module = importlib.util.module_from_spec(spec)
    # Execute the exact declared source, without implicit reads or writes of a
    # bytecode-cache file outside a closed offline fixture's admitted inputs.
    path = source / 'tests/helpers/collection_evidence.py'
    exec(compile(path.read_bytes(), str(path), 'exec', dont_inherit=True),
         module.__dict__)
    return module.CollectionEvidence(evidence_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--gate", choices=("tests", "startup"), default="tests")
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--trust-core", type=Path)
    parser.add_argument("--trust-sha256")
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
    sys.path.insert(0, str(root / 'scripts/ci_owned'))
    from fixture_prerequisites import clean_environment, no_links, native_pytest_args
    if args.gate == 'startup':
        if args.fixture_root is None or args.trust_core is None or args.trust_sha256 is None or pytest_args:
            parser.error('startup requires --fixture-root NEW --trust-core FILE --trust-sha256 SHA; no pytest arguments')
        fixture_root = no_links(args.fixture_root)
        if fixture_root.exists():
            raise RuntimeError('Startup fixture root must be new; no live home or reset')
        fixture_root.mkdir(parents=True)
        env = clean_environment(fixture_root, os.environ)
        fixture_home = Path(env['HERMES_HOME'])
        os.environ.clear()
        os.environ.update(env)
    else:
        fixture_home = Path(os.environ["HERMES_HOME"]).absolute()
        if fixture_home.parent != root or fixture_home.name not in {".hermes-ci", ".hermes-release"}:
            raise RuntimeError("Legacy native receipt requires a declared isolated workflow home")
        no_links(fixture_home).mkdir(exist_ok=True)
        from fixture_prerequisites import OFFLINE_SETTINGS
        for key, value in OFFLINE_SETTINGS.items():
            os.environ.setdefault(key, value)
    if (args.trust_core is None) != (args.trust_sha256 is None):
        parser.error('genuine trust delivery needs both --trust-core and --trust-sha256')
    if args.trust_core is not None:
        import re
        trust_path = no_links(args.trust_core).resolve(strict=True)
        if (trust_path.name != 'hermes_trust_core.py' or not trust_path.is_file()
                or not re.fullmatch('[0-9a-f]{64}', args.trust_sha256)
                or hashlib.sha256(trust_path.read_bytes()).hexdigest() != args.trust_sha256):
            raise RuntimeError('Genuine trust source path/SHA mismatch')
        sys.path.insert(0, str(trust_path.parent))
        os.environ['HERMES_SECURITY_STRICT'] = '1'
        os.environ['MW_REQUIRE_TRUST_CORE'] = '1'
    source_args = []
    if args.gate == 'tests':
        from source_suites import run_suites
        source_result = run_suites(root, fixture_home / 'source-prerequisites')
        source_args = native_pytest_args(root, source_result)

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
    if args.gate == 'startup':
        # Offline boundary is armed before genuine native imports, not only
        # before the happy-path callback. This is an audit guard, not OS isolation.
        sys.dont_write_bytecode = True
        def offline(event, event_args):
            if event.startswith(('socket.', 'subprocess.', 'ctypes.')) or event in {
                '_winapi.CreateProcess', 'os.system', 'os.posix_spawn', 'os.fork', 'os.exec',
            }:
                raise PermissionError('startup_offline_network_or_process_refused')
        sys.addaudithook(offline)
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
    if args.trust_core is not None:
        trust = importlib.import_module('hermes_trust_core')
        if (Path(trust.__file__).resolve() != trust_path
                or hashlib.sha256(trust_path.read_bytes()).hexdigest() != args.trust_sha256
                or not plugin._INJECTION_GUARD_AVAILABLE
                or plugin._sanitize_recalled is not trust.sanitize_recalled):
            raise RuntimeError('Genuine trust loaded origin/API mismatch')
        origins['hermes_trust_core'] = str(trust_path)
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
    if args.gate == 'startup':
        from provider_startup import run
        report = run(plugin, fixture_home)
        with (fixture_home.parent / 'provider-startup.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps(report))
        return 0
    reporter = collection_reporter(root, fixture_home)
    import pytest
    # Explicit plugin test directory prevents discovery of the core's own tests.
    return reporter.run(pytest.main, ["-q", "tests", "--confcutdir=" + str(root / "tests"), *source_args, *pytest_args])


if __name__ == "__main__":
    raise SystemExit(main())
