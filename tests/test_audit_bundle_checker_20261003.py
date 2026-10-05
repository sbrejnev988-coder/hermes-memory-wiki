"""Small authored/copied fixtures only; no processes or SDK doubles."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_memory_audit_bundle_20261003.py"


def checker():
    assert SCRIPT.is_file(), "read-only bundle checker is not implemented"
    spec = importlib.util.spec_from_file_location("bundle_checker_20261003", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture_bundle(tmp_path):
    seed = tmp_path / "seed"
    bundle = tmp_path / "bundle"
    seed.mkdir()
    bundle.mkdir()
    data = b"print('authored fixture; never executed')\n"
    (seed / "runner.py").write_bytes(data)
    (bundle / "run_regressions.py").write_bytes((seed / "runner.py").read_bytes())
    manifest = {
        "upstream_commit_sha": None,
        "source_method": "browser-transcribed fixtures, not Git blobs",
        "test_count": 66,
        "files": {"run_regressions.py": {"sha256": digest(data), "bytes": len(data)}},
    }
    manifest_bytes = (json.dumps(manifest) + "\n").encode()
    (bundle / "manifest.json").write_bytes(manifest_bytes)
    (bundle / "SHA256SUMS").write_text(
        digest(data) + "  run_regressions.py\n" + digest(manifest_bytes) + "  manifest.json\n",
        encoding="utf-8",
    )
    return bundle


def test_copied_bundle_integrity_is_not_upstream_or_native_proof(tmp_path):
    bundle = fixture_bundle(tmp_path)
    report = checker().validate_bundle(bundle)
    assert report["files_verified"] == 2
    assert report["upstream_commit_sha"] is None
    assert report["full_native_proof"] is False
    assert report["ast66_is_native_proof"] is False
    assert "authentication" in report["checksum_scope"]
    assert report["manifest_sha256"] == digest((bundle / "manifest.json").read_bytes())


@pytest.mark.parametrize("name", ["../seed/runner.py", "/absolute.py", "C:/escape.py", "a\\b.py",
                                      "./run_regressions.py", "a//b.py", "a:stream", "NUL.py"])
def test_bundle_rejects_unsafe_manifest_paths_before_reading(tmp_path, name):
    bundle = fixture_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = manifest["files"].pop("run_regressions.py")
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    module = checker()
    with pytest.raises(module.BundleError, match="path"):
        module.validate_bundle(bundle)


def test_bundle_rejects_nonregular_member(tmp_path):
    bundle = fixture_bundle(tmp_path)
    (bundle / "run_regressions.py").unlink()
    (bundle / "run_regressions.py").mkdir()
    module = checker()
    with pytest.raises(module.BundleError, match="regular"):
        module.validate_bundle(bundle)


@pytest.mark.parametrize("expected", ["0" * 64, "x" * 64, "A" * 64, "bad"])
def test_manifest_pin_is_literal_and_enforced(tmp_path, expected):
    bundle = fixture_bundle(tmp_path)
    module = checker()
    with pytest.raises(module.BundleError, match="hash"):
        module.validate_bundle(bundle, expected_manifest_sha256=expected)


@pytest.mark.parametrize("change", ["duplicate", "tamper", "escape"])
def test_checksum_list_is_strict_and_matches_manifest(tmp_path, change):
    bundle = fixture_bundle(tmp_path)
    sums = bundle / "SHA256SUMS"
    data = sums.read_text(encoding="utf-8")
    if change == "duplicate":
        data += data.splitlines()[0] + "\n"
    elif change == "tamper":
        data = "0" * 64 + data[64:]
    else:
        data += "0" * 64 + "  ../seed/runner.py\n"
    sums.write_text(data, encoding="utf-8")
    module = checker()
    with pytest.raises(module.BundleError):
        module.validate_bundle(bundle)


def test_unlisted_file_is_refused(tmp_path):
    bundle = fixture_bundle(tmp_path)
    (bundle / "extra.py").write_bytes(b"unexpected")
    module = checker()
    with pytest.raises(module.BundleError, match="unlisted"):
        module.validate_bundle(bundle)


def test_duplicate_json_keys_are_refused(tmp_path):
    bundle = fixture_bundle(tmp_path)
    raw = (bundle / "manifest.json").read_text(encoding="utf-8")
    (bundle / "manifest.json").write_text(raw.replace('{', '{"test_count": 66,', 1), encoding="utf-8")
    module = checker()
    with pytest.raises(module.BundleError, match="duplicate"):
        module.validate_bundle(bundle)


def test_changed_member_hash_fails(tmp_path):
    bundle = fixture_bundle(tmp_path)
    (bundle / "run_regressions.py").write_bytes(b"modified")
    module = checker()
    with pytest.raises(module.BundleError, match="hash"):
        module.validate_bundle(bundle)


FIX_NAMES = (
    "patches/0001-guard-social-fullmatch.patch", "patches/0002-decay-preserve-zero.patch",
    "patches/0003-decay-linear-membership.patch", "patches/0004-decay-close-connections.patch",
    "patches/0005-recall-fail-closed.patch", "patches/0006-recall-timestamp-overflow.patch",
)


def patch_catalog():
    names = (*FIX_NAMES, "all.patch", "all-code.patch", "core.patch", "hardening.patch",
             "install-tests.patch", "patches/0007-add-offline-regression-runner.patch")
    return {"sha256": {name: digest(name.encode()) for name in names}}


def test_default_patch_checks_are_six_independent_fixes():
    assert checker().select_patches(patch_catalog(), None) == list(FIX_NAMES)


@pytest.mark.parametrize("selection", [
    [FIX_NAMES[0], FIX_NAMES[0]], ["all.patch", "core.patch"],
    ["all-code.patch", "hardening.patch"], ["core.patch", FIX_NAMES[2]],
    ["install-tests.patch", "patches/0007-add-offline-regression-runner.patch"],
    ["../outside.patch"], ["unreviewed.patch"], [],
])
def test_duplicate_overlapping_unknown_patch_inputs_are_refused(selection):
    module = checker()
    with pytest.raises(module.BundleError):
        module.select_patches(patch_catalog(), selection)


def test_distinct_names_with_duplicate_patch_bytes_are_refused():
    module = checker()
    catalog = patch_catalog()
    catalog["sha256"][FIX_NAMES[1]] = catalog["sha256"][FIX_NAMES[0]]
    with pytest.raises(module.BundleError, match="duplicate"):
        module.select_patches(catalog, [FIX_NAMES[0], FIX_NAMES[1]])


def test_git_adapter_only_checks_validated_patch_stdin(tmp_path):
    import subprocess
    module = checker()
    source = tmp_path / "source"
    source.mkdir()
    (source / "guard.py").write_bytes(b"old\n")
    payload = b"--- a/guard.py\n+++ b/guard.py\n@@ -1 +1 @@\n-old\n+new\n"
    calls = []
    def boundary(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 1, b"", b"error: patch does not apply\n")
    result = module.dry_run_patch(tmp_path, source, "git", payload, {"guard.py"}, run=boundary)
    assert result["applicable"] is False
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[-5:] == ["apply", "--check", "--whitespace=error", "--", "-"]
    assert "--cached" not in args and "--index" not in args
    assert kwargs["input"] == payload
    assert kwargs["cwd"] == str(tmp_path)
    assert "--work-tree=" + str(source) in args
    assert "GIT_CONFIG_GLOBAL" in kwargs["env"]
    assert kwargs["timeout"] <= 30


@pytest.mark.parametrize("target", ["../outside.py", "config.yaml", "unexpected.py"])
def test_git_adapter_rejects_patch_paths_before_process(tmp_path, target):
    module = checker()
    payload = ("--- a/" + target + "\n+++ b/" + target + "\n@@ -1 +1 @@\n-old\n+new\n").encode()
    def boundary(*args, **kwargs):
        pytest.fail("unsafe patch reached process boundary")
    with pytest.raises(module.BundleError, match="path|target"):
        module.dry_run_patch(tmp_path, tmp_path, "git", payload, {"guard.py"}, run=boundary)


def copied_source(tmp_path):
    seed, source = tmp_path / "source-seed", tmp_path / "source"
    seed.mkdir()
    source.mkdir()
    for name in ("guard.py", "decay.py", "recall_orchestrator.py"):
        (seed / name).write_bytes(("# tiny copied fixture: " + name + "\n").encode())
        (source / name).write_bytes((seed / name).read_bytes())
    pin = {"baseline_commit": "a" * 40,
           "source_sha256": {name: digest((source / name).read_bytes()) for name in ("guard.py", "decay.py", "recall_orchestrator.py")}}
    return source, pin


def test_exact_source_pin_and_commit_are_checked_without_import(tmp_path):
    source, pin = copied_source(tmp_path)
    report = checker().validate_source(source, pin, "a" * 40)
    assert report["source_files_verified"] == 3
    assert report["source_pin_verified"] is True
    assert report["source_hashes"] == pin["source_sha256"]


@pytest.mark.parametrize("change", ["wrong_hash", "malformed_hash", "path", "commit", "missing"])
def test_bad_source_pins_are_rejected(tmp_path, change):
    source, pin = copied_source(tmp_path)
    if change == "wrong_hash":
        pin["source_sha256"]["guard.py"] = "0" * 64
    elif change == "malformed_hash":
        pin["source_sha256"]["guard.py"] = "F" * 64
    elif change == "path":
        pin["source_sha256"]["../source-seed/guard.py"] = pin["source_sha256"]["guard.py"]
    elif change == "commit":
        pin["baseline_commit"] = "b" * 40
    else:
        del pin["source_sha256"]["guard.py"]
    module = checker()
    with pytest.raises(module.BundleError):
        module.validate_source(source, pin, "a" * 40)


def test_unknown_runner_is_never_authorized_by_its_own_manifest():
    report = checker().scan_runner(b"import socket\nsocket.create_connection(('example.test', 80))\n")
    assert report["execution_eligible"] is False
    assert report["full_native_proof"] is False


def test_reviewed_runner_static_scan_keeps_ast_caveat(tmp_path):
    author = SCRIPT.parents[3] / "bundle/hermes_memory_wiki_audit_20261003/run_regressions.py"
    copied = tmp_path / "copied-runner.py"
    copied.write_bytes(author.read_bytes())
    report = checker().scan_runner(copied.read_bytes())
    assert report["execution_eligible"] is True
    assert report["sha256"] == "b785bf4506ed7d929a38cd1e00b7cff279bf7fb907515b77438512f6a302b859"
    assert report["full_native_proof"] is False
    assert "truncated" in report["scope"]


def fixture_full_bundle(tmp_path):
    bundle = fixture_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for index, name in enumerate(FIX_NAMES):
        target = "guard.py" if index == 0 else "decay.py" if index < 4 else "recall_orchestrator.py"
        data = ("--- a/" + target + "\n+++ b/" + target + "\n@@ -1 +1 @@\n-old\n+new" + str(index) + "\n").encode()
        path = bundle / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        manifest["files"][name] = {"sha256": digest(data), "bytes": len(data)}
    raw = json.dumps(manifest).encode()
    (bundle / "manifest.json").write_bytes(raw)
    hashes = {name: entry["sha256"] for name, entry in manifest["files"].items()}
    hashes["manifest.json"] = digest(raw)
    (bundle / "SHA256SUMS").write_text("".join(value + "  " + name + "\n" for name, value in hashes.items()), encoding="utf-8")
    return bundle


def test_default_wrapper_never_runs_bundle_code_or_changes_source(tmp_path):
    import subprocess
    module = checker()
    bundle = fixture_full_bundle(tmp_path)
    source, pin = copied_source(tmp_path)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    calls = []
    def boundary(args, **kwargs):
        calls.append(args)
        if args[-2:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, ("a" * 40 + "\n").encode(), b"")
        assert args[-5:] == ["apply", "--check", "--whitespace=error", "--", "-"]
        return subprocess.CompletedProcess(args, 0, b"", b"")
    report = module.check_bundle(bundle, tmp_path, source, pin=pin, run=boundary)
    assert report["source_unchanged"] is True
    assert len(report["patch_checks"]) == 6
    assert len(calls) == 7
    assert report["full_native_proof"] is False
    assert report["subset_executed"] is False
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("event,values", [
    ("socket.connect", ()), ("socket.getaddrinfo", ()), ("socket.bind", ()),
    ("subprocess.Popen", ()), ("os.system", ()), ("os.posix_spawn", ()),
])
def test_subset_guard_denies_network_and_nested_process_events(tmp_path, event, values):
    module = checker()
    guard = module.make_audit_guard(tmp_path, [])
    with pytest.raises(PermissionError):
        guard(event, values)


def test_subset_guard_denies_live_reads_writes_and_databases(tmp_path):
    module = checker()
    scratch = tmp_path / "sandbox"
    scratch.mkdir()
    live = tmp_path / "outside" / "auth.json"
    guard = module.make_audit_guard(scratch, [])
    for event, values in [("open", (str(live), "r", 0)),
                          ("open", (str(live), "w", 0)),
                          ("sqlite3.connect", (str(live),)),
                          ("os.remove", (str(live),)),
                          ("os.rename", (str(scratch / "a"), str(live)))]:
        with pytest.raises(PermissionError):
            guard(event, values)
    guard("open", (str(scratch / "synthetic.json"), "w", 0))
    guard("sqlite3.connect", (":memory:",))


@pytest.mark.parametrize("suite,pinned", [("all", True), ("hardening", True), ("core", False)])
def test_subset_refuses_broad_or_unpinned_execution(tmp_path, suite, pinned):
    module = checker()
    with pytest.raises(module.BundleError):
        module.run_subset(tmp_path, tmp_path, suite, tmp_path,
                          {"source_pin_verified": pinned, "source_hashes": {}}, b"unreviewed")


def test_cli_exposes_no_apply_switch():
    module = checker()
    with pytest.raises(SystemExit) as error:
        module.main(["--bundle", ".", "--repo", ".", "--apply"])
    assert error.value.code == 2


def test_git_adapter_binds_actual_source_cwd_and_owned_git_context(tmp_path):
    import subprocess
    module = checker()
    source = tmp_path / "source"
    source.mkdir()
    (source / "guard.py").write_bytes(b"old\n")
    payload = b"--- a/guard.py\n+++ b/guard.py\n@@ -1 +1 @@\n-old\n+new\n"
    def boundary(args, **kwargs):
        assert args[args.index("-C") + 1] == str(source)
        assert "--git-dir=" + str(tmp_path / ".git") in args
        assert kwargs["cwd"] == str(tmp_path)
        return subprocess.CompletedProcess(args, 0, b"", b"")
    assert module.dry_run_patch(tmp_path, source, "git", payload, {"guard.py"}, run=boundary)["applicable"]
