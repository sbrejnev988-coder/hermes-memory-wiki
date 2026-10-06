#!/usr/bin/env python
"""Read-only checker for the author audit bundle, never a native acceptance gate.

Internal checksums are not authentication. The author's 66 tests execute complete
small guard/decay modules but only selected/truncated recall ASTs, not full SQL,
ACL, Hermes integration or the repository's native suite. No automatic apply,
restart, commit or push is provided.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import re
import stat
import sys
import tempfile
import shutil
import importlib.util
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 1_000_000
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def safe_relative(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", name):
        raise BundleError("unsafe path")
    parts = name.split("/")
    if (PurePosixPath(name).is_absolute() or any(p in {"", ".", "..", ".git", ".env", "auth.json", "config.yaml"}
            or p.endswith((".", " ")) or p.split(".")[0].upper() in _RESERVED for p in parts)):
        raise BundleError("unsafe path: " + name)
    return name


def checked_path(path: Path) -> Path:
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BundleError("symlink/reparse path refused")
    return path


def regular_bytes(path: Path, *, limit: int = MAX_FILE_BYTES) -> bytes:
    path = checked_path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise BundleError("regular file required")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise BundleError("file size budget exceeded")
    return data


class BundleError(ValueError):
    """Invalid or unsafe checker input."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def literal_hash(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BundleError("invalid literal SHA256 hash")
    return value


def strict_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BundleError("duplicate JSON key")
            result[key] = value
        return result
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BundleError("invalid JSON") from error
    if not isinstance(result, dict):
        raise BundleError("JSON object required")
    return result


def validate_bundle(bundle: Path, expected_manifest_sha256: str | None = None) -> dict:
    bundle = checked_path(bundle)
    raw = regular_bytes(bundle / "manifest.json")
    if expected_manifest_sha256 is not None and sha256(raw) != literal_hash(expected_manifest_sha256):
        raise BundleError("manifest hash pin mismatch")
    manifest = strict_json(raw)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > 256:
        raise BundleError("invalid manifest files")
    for name in files:
        safe_relative(name)
    if len({name.casefold() for name in files}) != len(files):
        raise BundleError("duplicate case-insensitive path")
    hashes = {}
    total = len(raw)
    for name, entry in files.items():
        if name in {"manifest.json", "SHA256SUMS"} or not isinstance(entry, dict):
            raise BundleError("invalid manifest member")
        expected = literal_hash(entry.get("sha256"))
        size = entry.get("bytes")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise BundleError("invalid manifest size")
        data = regular_bytes(bundle / name)
        total += len(data)
        if total > 2_000_000:
            raise BundleError("bundle size budget exceeded")
        if sha256(data) != expected or len(data) != size:
            raise BundleError("bundle hash/size mismatch: " + name)
        hashes[name] = sha256(data)
    hashes["manifest.json"] = sha256(raw)
    sums_raw = regular_bytes(bundle / "SHA256SUMS")
    declared = {}
    for line in sums_raw.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if not match:
            raise BundleError("invalid checksum line/hash")
        value, name = match.groups()
        safe_relative(name)
        if name.casefold() in {n.casefold() for n in declared}:
            raise BundleError("duplicate checksum path")
        declared[name] = value
    if declared != hashes:
        raise BundleError("checksum list/manifest hash mismatch")
    stack, inventory, visited = [bundle], set(), 0
    while stack:
        for path in stack.pop().iterdir():
            checked_path(path)
            visited += 1
            if visited > 512:
                raise BundleError("bundle member budget exceeded")
            if path.is_dir():
                stack.append(path)
            else:
                inventory.add(safe_relative(path.relative_to(bundle).as_posix()))
    if inventory != set(hashes) | {"SHA256SUMS"}:
        raise BundleError("unlisted bundle member")
    return {
        "files_verified": len(hashes), "sha256": hashes,
        "manifest_sha256": sha256(raw), "checksum_list_sha256": sha256(sums_raw),
        "upstream_commit_sha": manifest.get("upstream_commit_sha"),
        "checksum_scope": "included local bytes only; not authentication or remote Git proof",
        "full_native_proof": False, "ast66_is_native_proof": False,
    }


FIX_PATCHES = (
    "patches/0001-guard-social-fullmatch.patch", "patches/0002-decay-preserve-zero.patch",
    "patches/0003-decay-linear-membership.patch", "patches/0004-decay-close-connections.patch",
    "patches/0005-recall-fail-closed.patch", "patches/0006-recall-timestamp-overflow.patch",
)
_COVERAGE = {name: {index} for index, name in enumerate(FIX_PATCHES, 1)}
_COVERAGE.update({"core.patch": {1, 2, 3, 4}, "hardening.patch": {5, 6},
    "all-code.patch": {1, 2, 3, 4, 5, 6}, "all.patch": {1, 2, 3, 4, 5, 6, 7},
    "install-tests.patch": {7}, "patches/0007-add-offline-regression-runner.patch": {7}})
_TARGETS = {1: "guard.py", 2: "decay.py", 3: "decay.py", 4: "decay.py",
            5: "recall_orchestrator.py", 6: "recall_orchestrator.py",
            7: "scripts/audit_regressions_20261003.py"}


def select_patches(integrity: dict, selection: list[str] | None) -> list[str]:
    chosen = list(FIX_PATCHES if selection is None else selection)
    if not chosen or len(chosen) > 7:
        raise BundleError("select one non-overlapping patch representation")
    seen_fixes, seen_hashes = set(), set()
    for name in chosen:
        safe_relative(name)
        if name not in _COVERAGE or name not in integrity["sha256"]:
            raise BundleError("unknown patch input")
        fixes = _COVERAGE[name]
        value = literal_hash(integrity["sha256"][name])
        if seen_fixes & fixes or value in seen_hashes:
            raise BundleError("duplicate/overlapping patch inputs; never combine all.patch with components")
        seen_fixes |= fixes
        seen_hashes.add(value)
    return chosen


def patch_targets(payload: bytes, allowed: set[str]) -> set[str]:
    text = payload.decode("utf-8")
    old, targets = None, set()
    for line in text.splitlines():
        if line.startswith(("GIT binary patch", "Binary files", "old mode", "new mode", "rename ", "copy ", "new file mode", "deleted file mode")):
            raise BundleError("patch mode/binary operation refused")
        if line.startswith("--- "):
            value = line[4:]
            old = None if value == "/dev/null" else safe_relative(value.removeprefix("a/"))
        elif line.startswith("+++ "):
            if not line.startswith("+++ b/"):
                raise BundleError("unsafe patch path")
            name = safe_relative(line[6:])
            if name not in allowed or name in targets or (old is not None and old != name):
                raise BundleError("unexpected/duplicate patch target")
            targets.add(name)
    if targets != allowed:
        raise BundleError("patch target set mismatch")
    return targets


def clean_environment() -> dict[str, str]:
    # No ambient credential, profile, proxy, Python or Git configuration fallback.
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return env


def git_arguments(git: str, source: Path, repo: Path) -> list[str]:
    # apply does not chdir merely because --work-tree is set. Bind its logical
    # CWD to source while retaining the caller's owned Git metadata explicitly.
    git_dir = repo / ".git"
    if git_dir.is_file():
        pointer = regular_bytes(git_dir).decode("utf-8").strip()
        if not pointer.startswith("gitdir: ") or "\n" in pointer:
            raise BundleError("invalid local Git worktree pointer")
        git_dir = checked_path(repo / pointer[len("gitdir: "):])
    return [git, "--no-optional-locks", "-C", str(source), "--git-dir=" + str(git_dir),
            "--work-tree=" + str(source), "-c", "core.autocrlf=false", "-c", "core.whitespace=cr-at-eol",
            "-c", "core.sparseCheckout=false"]


def dry_run_patch(repo: Path, source: Path, git: str, payload: bytes,
                  allowed: set[str], *, run=None) -> dict:
    targets = patch_targets(payload, allowed)
    repo, source = checked_path(repo), checked_path(source)
    for target in targets:
        path = source / target
        if path.exists():
            regular_bytes(path)
        else:
            checked_path(path.parent)
    args = git_arguments(git, source, repo) + ["apply", "--check", "--whitespace=error", "--", "-"]
    result = (subprocess.run if run is None else run)(args, input=payload, cwd=str(repo),
        env=clean_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    return {"applicable": result.returncode == 0, "exit_code": result.returncode,
            "targets": sorted(targets), "stderr": result.stderr.decode("utf-8", "replace")[:2000],
            "mode": "git apply --check only; independent unchanged-source check"}


SOURCE_FILES = ("guard.py", "decay.py", "recall_orchestrator.py")
REVIEWED_RUNNER_SHA256 = "b785bf4506ed7d929a38cd1e00b7cff279bf7fb907515b77438512f6a302b859"


def validate_source(source: Path, pin: dict | None = None, head: str | None = None) -> dict:
    source = checked_path(source)
    expected = pin.get("source_sha256") if pin is not None else {name: None for name in SOURCE_FILES}
    if not isinstance(expected, dict) or not set(SOURCE_FILES) <= expected.keys() or len(expected) > 512:
        raise BundleError("source pin must cover all three actual modules")
    if pin is not None:
        commit = pin.get("baseline_commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) or head != commit:
            raise BundleError("literal source commit pin mismatch")
        if "source_files" in pin and (type(pin["source_files"]) is not int or pin["source_files"] != len(expected)):
            raise BundleError("source pin count mismatch")
    for name, value in expected.items():
        safe_relative(name)
        if pin is not None:
            literal_hash(value)
    if len({name.casefold() for name in expected}) != len(expected):
        raise BundleError("duplicate source pin path")
    actual, total = {}, 0
    for name, value in expected.items():
        data = regular_bytes(source / name, limit=10_000_000)
        total += len(data)
        if total > 20_000_000:
            raise BundleError("source read budget exceeded")
        actual[name] = sha256(data)
        if value is not None and value != actual[name]:
            raise BundleError("source hash pin mismatch: " + name)
    return {"source_files_verified": len(actual), "source_pin_verified": pin is not None,
            "source_hashes": {name: actual[name] for name in SOURCE_FILES},
            "verified_source_digest": sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()),
            "source_pin_scope": "exact local byte hashes and Git context HEAD; not a remote-origin attestation",
            "head": head}


def scan_runner(payload: bytes) -> dict:
    tree = ast.parse(payload.decode("utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    reviewed = sha256(payload) == REVIEWED_RUNNER_SHA256
    return {"sha256": sha256(payload), "imports": sorted(imports),
            "execution_eligible": reviewed, "statically_reviewed_exact_bytes": reviewed,
            "runner_static_live_profile_or_network_calls": False if reviewed else None,
            "scope": "complete guard/decay; selected recall ASTs and truncated connection prefix only",
            "full_native_proof": False,
            "notice": "hash allowlist records separate static review, not bundle self-certification; source modules must be pinned too"}


def check_bundle(bundle: Path, repo: Path, source: Path, *, pin: dict | None = None,
                 expected_manifest_sha256: str | None = None, patch_names=None, git="git", run=None) -> dict:
    bundle, repo, source = checked_path(bundle), checked_path(repo), checked_path(source)
    integrity = validate_bundle(bundle, expected_manifest_sha256)
    chosen = select_patches(integrity, patch_names)
    boundary = subprocess.run if run is None else run
    result = boundary(git_arguments(git, source, repo) + ["rev-parse", "HEAD"], cwd=str(repo),
        env=clean_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    head = result.stdout.decode("ascii").strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise BundleError("cannot verify local Git context HEAD")
    before = validate_source(source, pin, head)
    checks = []
    for name in chosen:
        data = regular_bytes(bundle / name)
        if sha256(data) != integrity["sha256"][name]:
            raise BundleError("patch changed after checksum verification")
        check = dry_run_patch(repo, source, git, data, {_TARGETS[i] for i in _COVERAGE[name]}, run=run)
        check.update(patch=name, sha256=sha256(data), fixes=[f"F{i:02}" for i in sorted(_COVERAGE[name]) if i <= 6])
        checks.append(check)
    runner = regular_bytes(bundle / "run_regressions.py")
    if sha256(runner) != integrity["sha256"]["run_regressions.py"]:
        raise BundleError("runner changed after checksum verification")
    after = validate_source(source, pin, head)
    if before != after:
        raise BundleError("source changed during read-only check")
    return {"bundle": str(bundle), "git_context_repo": str(repo), "checked_source": str(source),
            "integrity": integrity, "source": before, "patch_checks": checks,
            "all_selected_applicable": all(check["applicable"] for check in checks),
            "source_unchanged": True, "subset_executed": False, "full_native_proof": False,
            "runner_static_scan": scan_runner(runner),
            "limitations": ["Internal checksums cannot authenticate ZIP or pin remote upstream; upstream commit unverified.",
                "Independent dry runs do not apply patches, validate a cumulative series or certify behavior.",
                "AST66 is explicitly NOT full native proof: recall SQL/ACL suffix, prefetch, native suite and strict policy untested.",
                "R01: conflict failures return False; R02: LIMIT 40 precedes visibility; R03: benign security text may be filtered."]}


def make_audit_guard(scratch: Path, read_roots: list[Path]):
    scratch = Path(scratch).resolve()
    roots = [Path(root).resolve() for root in read_roots]
    def inside(value, root):
        return Path(os.fsdecode(value)).resolve().is_relative_to(root)
    def audit(event, values):
        if (event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn",
                "os.fork", "os.forkpty", "os.exec", "os.spawn", "ctypes.dlopen"}):
            raise PermissionError("subset denies network, nested processes and ctypes")
        if event == "sqlite3.connect" and str(values[0]) != ":memory:" and not inside(values[0], scratch):
            raise PermissionError("subset denies non-fixture database")
        if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
            value, mode, flags = values[:3]
            writes = ((isinstance(mode, str) and any(ch in mode for ch in "wax+")) or
                      (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))))
            if not inside(value, scratch) and (writes or not any(inside(value, root) for root in roots)):
                raise PermissionError("subset denies non-fixture IO")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.replace", "os.chmod", "os.utime", "os.symlink", "os.link"}:
            targets = values[:2] if event in {"os.rename", "os.replace", "os.symlink", "os.link"} else values[:1]
            if any(isinstance(v, (str, bytes, os.PathLike)) and not inside(v, scratch) for v in targets):
                raise PermissionError("subset denies non-fixture mutation")
    return audit


_BOOTSTRAP = """import hashlib, importlib.util, json, pathlib, sys
cfg = json.loads(sys.argv[1])
p = pathlib.Path(cfg['checker'])
assert hashlib.sha256(p.read_bytes()).hexdigest() == cfg['checker_sha256']
spec = importlib.util.spec_from_file_location('_trusted_bundle_checker_child', p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
raise SystemExit(m.execute_subset_child(cfg))
"""


def execute_subset_child(cfg: dict) -> int:
    # Trusted bootstrap; only three pinned public files are copied, never a full
    # checkout/profile. The reviewed runner then gets no access to source paths.
    scratch, source = checked_path(Path(cfg["scratch"])), checked_path(Path(cfg["source"]))
    suite = cfg["suite"]
    if suite not in {"core", "diagnostics"}:
        raise BundleError("only core/diagnostics subset permitted")
    runner = regular_bytes(Path(cfg["runner"]))
    if sha256(runner) != REVIEWED_RUNNER_SHA256:
        raise BundleError("unreviewed runner")
    for name in SOURCE_FILES:
        data = regular_bytes(source / name)
        if sha256(data) != literal_hash(cfg["source_hashes"][name]):
            raise BundleError("child source pin mismatch")
        if name in {"guard.py", "decay.py"}:
            permitted = {"__future__", "re", "typing", "math", "sqlite3", "time", "pathlib", "contextlib"}
            tree = ast.parse(data.decode("utf-8"))
            for node in ast.walk(tree):
                imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
                if any(value not in permitted for value in imports):
                    raise BundleError("source module import requires separate review")
        if suite == "diagnostics" or name != "recall_orchestrator.py":
            (scratch / name).write_bytes(data)
    copied_runner = scratch / "run_regressions.py"
    copied_runner.write_bytes(runner)
    os.chdir(scratch)
    sys.dont_write_bytecode = True
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # -I -S excludes user/site packages; audited reads are limited to scratch
    # and stdlib. Audit hooks supervise this known code, not hostile-code sandboxes.
    sys.addaudithook(make_audit_guard(scratch, [Path(sys.base_prefix) / "Lib", Path(sys.base_prefix) / "DLLs"]))
    spec = importlib.util.spec_from_file_location("_author_audit_runner", copied_runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.argv = [str(copied_runner), "--repo", str(scratch), "--suite", suite,
                "--json-out", str(scratch / "subset-result.json")]
    return module.main()


def run_subset(bundle: Path, source: Path, suite: str, scratch_root: Path,
               source_report: dict, runner: bytes) -> dict:
    if suite not in {"core", "diagnostics"} or not source_report.get("source_pin_verified"):
        raise BundleError("only explicitly selected core/diagnostics with independent source pin may run")
    if not scan_runner(runner)["execution_eligible"]:
        raise BundleError("runner bytes were not independently reviewed")
    if set(source_report.get("source_hashes", {})) != set(SOURCE_FILES):
        raise BundleError("missing exact child source hashes")
    bundle, source, scratch_root = checked_path(bundle), checked_path(source), checked_path(scratch_root)
    if scratch_root.is_relative_to(source) or scratch_root.is_relative_to(bundle):
        raise BundleError("scratch must be outside source and bundle")
    runner_path = bundle / "run_regressions.py"
    if regular_bytes(runner_path) != runner:
        raise BundleError("runner changed before subprocess")
    env = clean_environment()
    with tempfile.TemporaryDirectory(prefix="bundle-check-", dir=scratch_root) as folder:
        scratch = checked_path(Path(folder))
        env.update(HOME=str(scratch), USERPROFILE=str(scratch), HERMES_HOME=str(scratch),
                   APPDATA=str(scratch), LOCALAPPDATA=str(scratch), TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch),
                   PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1")
        cfg = {"checker": str(checked_path(Path(__file__))), "checker_sha256": sha256(regular_bytes(Path(__file__))),
               "scratch": str(scratch), "source": str(source), "runner": str(runner_path),
               "source_hashes": source_report["source_hashes"], "suite": suite}
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", _BOOTSTRAP, json.dumps(cfg)],
            cwd=str(scratch), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
        output = scratch / "subset-result.json"
        payload = strict_json(regular_bytes(output)) if output.exists() else None
        allocated = sum(path.stat().st_size for path in scratch.rglob("*") if path.is_file())
        if allocated > 150_000:
            raise BundleError("subset fixture budget exceeded")
        report = {"suite": suite, "exit_code": result.returncode, "result": payload,
                  "stdout": result.stdout.decode("utf-8", "replace")[:2000],
                  "stderr": result.stderr.decode("utf-8", "replace")[:16000],
                  "fixture_bytes": allocated, "python": sys.executable,
                  "supervision": "fresh -I -S process; credential-free synthetic home; Python audit denies network, subprocesses and non-fixture IO",
                  "full_native_proof": False, "strict_policy_proof": False}
    report["fixtures_removed"] = not scratch.exists()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--bundle", required=True, type=Path, help="already safely extracted author bundle; no ZIP extraction or execution by default")
    parser.add_argument("--repo", required=True, type=Path, help="local Git context; no index mutation")
    parser.add_argument("--source", type=Path, help="optional immutable byte source for sparse-overlay dry checks")
    parser.add_argument("--source-pin", type=Path, help="independent owner JSON: baseline_commit + source_sha256; never use archive as authority")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--patch", action="append", help="non-overlapping alternative; default six independent checks")
    parser.add_argument("--git", default="git")
    parser.add_argument("--run-subset", choices=("core", "diagnostics"), help="opt-in diagnostic execution, NEVER full native proof")
    parser.add_argument("--scratch-root", type=Path, help="existing owned temporary directory, required for subset")
    args = parser.parse_args(argv)
    try:
        pin = None
        if args.source_pin:
            pin_path = checked_path(args.source_pin)
            if pin_path.is_relative_to(checked_path(args.bundle)):
                raise BundleError("source pin must be independent of bundle")
            pin = strict_json(regular_bytes(pin_path))
        if args.run_subset and (pin is None or args.scratch_root is None):
            raise BundleError("subset requires independent source pin and explicit owned scratch root")
        if pin is not None and "minimum_free_C_bytes" in pin:
            reserve = pin["minimum_free_C_bytes"]
            if type(reserve) is not int or reserve < 0 or shutil.disk_usage(Path(args.repo).anchor).free < reserve:
                raise BundleError("minimum free-disk reserve reached")
        source = args.source or args.repo
        report = check_bundle(args.bundle, args.repo, source, pin=pin,
            expected_manifest_sha256=args.expected_manifest_sha256, patch_names=args.patch, git=args.git)
        if args.run_subset:
            report["subset"] = run_subset(args.bundle, source, args.run_subset, args.scratch_root,
                report["source"], regular_bytes(args.bundle / "run_regressions.py"))
            report["subset_executed"] = True
            if validate_source(source, pin, report["source"]["head"]) != report["source"]:
                raise BundleError("source changed during subset")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_selected_applicable"] and (not args.run_subset or report["subset"]["exit_code"] == 0) else 1
    except (BundleError, OSError, UnicodeError, SyntaxError, subprocess.SubprocessError) as error:
        print(json.dumps({"error_type": type(error).__name__, "error": str(error)[:2000], "full_native_proof": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
