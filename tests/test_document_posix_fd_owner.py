"""Standalone POSIX real-FD regression; no package/SDK bootstrap or SQL.

Run: python -B tests/test_document_posix_fd_owner.py
Also collectable by ordinary unittest/pytest. Collection is inert. The script
entry adds a process-wide offline audit fence BEFORE importing the full product.
Fault seams are local module os/hashlib bindings; native opens, closes,
fstat, symlinks and file contents remain real. No platform skip on Linux.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "f31176f2c4233b0f8fa185106351257ded8e1027"
BASELINE_MODULE_SHA256 = "d99921f9adfef892ae1e928f70e6bc308187ce0f1fdc1c9632fa1b7f7de9434d"
BASELINE_FIXTURE_SHA256 = "32bfe93777db165a60c3ae8d641cde1ad9205d849ae1a10d23c851b6ffde6df6"
BASELINE_SPANS = {
    "_open_posix_directory": (616, 631, "fd3ad43bdcca571ddd601897de81a8155b491d235412575f7849a0029b487fb2"),
    "_open_posix_allowed_file": (634, 652, "f1c538cadc63d1e25e4ef686b4bd6f711d9a4279a85a7502f0162f847818ba69"),
}
CURRENT_COMMON_COMMIT = 'a4e118e921f5708ead87d834187805900b08b493'
CURRENT_MODULE_SHA256 = '4a8f993a2ece5a5c2484d2c5e1be1202586fa2c67023fca674678aa53c966524'
CURRENT_DEFINITION_SHA256 = {'_open_posix_directory': 'fa81e3852e0fe0124a23634bb5f58b4e21c7b03ebad2eaf84ab576264225e49b', '_open_posix_allowed_file': '70e048ac1856798566ef53bedf2953e41feb06c783c2dacff8911b9118d93057', '_snapshot_allowed_file': '3130ea9d81097862464b4694e6b754b1880972545fff0ca724fe8d65b09928f4'}
A4_SNAPSHOT_FIXTURE_SHA256 = '29811021644b605de9bc1b46237b8087d4f8c800f0ea143ff789df870c8772f3'
UNCHANGED_GAPS_SHA256 = ['75a11da44c802486bc6f65640aa48a730f0f684c5c07a42ba3cd1735eb3fb070', '90032fc7f7c85064377310af8f016bd3d350f1d08545b66887257464088dd59c']
UNCHANGED_PREFIX_SHA256 = '7922de5143cc512331c7d793c3d2909cb431cfa98bb6754fd39f79bde81c1abe'
UNCHANGED_SUFFIX_SHA256 = '066828dfe8b795b0feb7a6cc6f258462444b376feec2ce3e02313e5e1b94fccc'
AUDIT_DENIALS = []
OBSERVATIONS = []


def identity(fd):
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino, info.st_mode)


class FatalWalk(BaseException):
    pass


class FDTrace:
    """Owned test IO seam, not an OS/SDK replacement or production guard."""

    def __init__(self, sentinel_path):
        self.entries = []
        self.closes = []
        self.last = None
        self.open_error = None
        self.close_error = None
        self.before_effect = False
        self.reuse = False
        self.triggered = False
        self.trigger_close_index = None
        self.cleanup_error = None
        self.open_failed = False
        self.before_open = None
        self.sentinel_path = sentinel_path

    def __getattr__(self, name):
        return getattr(os, name)

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        if self.before_open is not None:
            self.before_open(path)
        if str(path) == "missing" and self.open_error is not None:
            self.open_failed = True
            raise self.open_error
        fd = os.open(path, flags, mode, dir_fd=dir_fd)
        row = {"fd": fd, "identity": identity(fd), "part": str(path),
               "flags": flags, "dir_fd": dir_fd, "role": "walker"}
        self.entries.append(row)
        self.last = row
        return fd

    def close(self, fd):
        self.closes.append(fd)
        trigger = (not self.triggered and self.last is not None
                   and self.last["part"] == "a" and self.last["dir_fd"] == fd
                   and (self.close_error is not None or self.reuse))
        if trigger:
            self.triggered = True
            self.trigger_close_index = len(self.closes) - 1
            if not self.before_effect:
                os.close(fd)
                if self.reuse:
                    sentinel = os.open(self.sentinel_path, os.O_RDONLY | os.O_CLOEXEC)
                    self.entries.append({"fd": sentinel, "identity": identity(sentinel),
                                         "part": "sentinel", "role": "sentinel"})
                    if sentinel != fd:
                        raise AssertionError("fixture failed to reuse its released descriptor")
            if self.close_error is not None:
                raise self.close_error
            return
        os.close(fd)
        if self.open_failed and self.cleanup_error is not None:
            error, self.cleanup_error = self.cleanup_error, None
            raise error

    def states(self):
        rows = []
        for entry in self.entries:
            try:
                current = identity(entry["fd"])
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
                current = None
            rows.append({**entry, "state": "closed" if current is None else
                         "matching" if current == entry["identity"] else "reused"})
        return rows

    def live(self, role="walker"):
        return [row for row in self.states() if row["state"] == "matching" and row["role"] == role]

    def emergency_cleanup(self):
        # Never close a foreign integer, even after an assertion/fatal failure.
        recovered = []
        for row in reversed(self.entries):
            try:
                current = identity(row["fd"])
            except OSError as exc:
                if exc.errno == errno.EBADF:
                    continue
                raise
            if current == row["identity"]:
                os.close(row["fd"])
                recovered.append({"fd": row["fd"], "identity": current, "role": row["role"]})
        return recovered


@unittest.skipUnless(os.name == "posix", "POSIX descriptor-relative walkers only")
class DocumentPosixFDOwner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ordinary full standalone module and real shipped dependencies, no __init__.
        sys.path.insert(0, str(ROOT))
        cls.product = importlib.import_module("document_knowledge_graph")
        if Path(cls.product.__file__).resolve() != ROOT / "document_knowledge_graph.py":
            raise AssertionError("wrong product origin")
        raw = (ROOT / "tests/fixtures/document_posix_fd_owner_baseline.py.txt").read_bytes()
        if hashlib.sha256(raw).hexdigest() != BASELINE_FIXTURE_SHA256:
            raise AssertionError("baseline fixture drift")
        cls.baseline = types.ModuleType("document_posix_fd_owner_f311_baseline")
        cls.baseline.__dict__.update(os=os, Path=Path)
        exec(compile(raw, "document_posix_fd_owner_baseline.py.txt", "exec"), cls.baseline.__dict__)
        # Partial historical a4 snapshot witness, NOT an entire baseline module.
        # Real current reader/guards/identity/home/stdlib; only snapshot body old.
        raw = (ROOT / "tests/fixtures/document_snapshot_fd_owner_a4_baseline.py.txt").read_bytes()
        if hashlib.sha256(raw).hexdigest() != A4_SNAPSHOT_FIXTURE_SHA256:
            raise AssertionError("a4 snapshot fixture drift")
        cls.a4_snapshot = types.ModuleType("document_snapshot_a4_body_current_reader")
        cls.a4_snapshot.__dict__.update({name: getattr(cls.product, name) for name in (
            "os", "stat", "Path", "tempfile", "hashlib", "Optional", "Callable", "Tuple", "Dict", "Any",
            "_open_allowed_file", "_file_identity", "_hermes_home")})
        exec(compile(raw, "document_snapshot_fd_owner_a4_baseline.py.txt", "exec"), cls.a4_snapshot.__dict__)


    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="posix-owner-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.root = self.work / "root"
        (self.root / "a/b").mkdir(parents=True)
        self.file = self.root / "a/b/file.txt"
        self.payload = b"owned POSIX file\n\x00bytes\n"
        self.file.write_bytes(self.payload)
        self.sentinel = self.work / "sentinel.txt"
        self.sentinel.write_bytes(b"caller-owned sentinel")
        saved = {key: os.environ.get(key) for key in ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_ROOTS")}
        os.environ["HERMES_HOME"] = str(self.work / "home")
        os.environ["MEMORY_WIKI_DOCUMENT_ROOTS"] = str(self.root)
        def restore_env():
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.addCleanup(restore_env)

    @contextmanager
    def traced(self, label, module):
        trace = FDTrace(self.sentinel)
        previous = module.os
        module.os = trace
        try:
            yield trace
        finally:
            module.os = previous
            # Evidence first, exact-owned recovery second; recovery is NOT product closure.
            observation = {"main": self._testMethodName, "label": label,
                           "before_emergency_cleanup": trace.states(), "closes": trace.closes,
                           "trigger_close_index": trace.trigger_close_index}
            OBSERVATIONS.append(observation)
            observation["fixture_recovered"] = trace.emergency_cleanup()

    def call(self, module, kind, relative=None):
        if kind == "directory":
            return module._open_posix_directory(self.root / (relative or Path("a/b")))
        relative = relative or Path("a/b/file.txt")
        return module._open_posix_allowed_file(self.root / relative, self.root, relative)

    def test_01_healthy_returned_ownership_and_flags(self):
        for kind in ("directory", "file"):
            with self.subTest(kind=kind), self.traced("healthy-" + kind, self.product) as io:
                fd = self.call(self.product, kind)
                self.assertEqual([row["fd"] for row in io.live()], [fd])
                expected = os.stat(self.root / "a/b" if kind == "directory" else self.file)
                self.assertEqual(identity(fd)[:2], (expected.st_dev, expected.st_ino))
                self.assertFalse(os.get_inheritable(fd))
                if kind == "file":
                    self.assertEqual(os.read(fd, 1024), self.payload)
                else:
                    self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))
                for row in io.entries:
                    self.assertEqual(row["flags"] & os.O_ACCMODE, os.O_RDONLY)
                    self.assertTrue(row["flags"] & os.O_NOFOLLOW)
                    self.assertTrue(row["flags"] & os.O_CLOEXEC)
                    if row["fd"] != fd or kind == "directory":
                        self.assertTrue(row["flags"] & os.O_DIRECTORY)
                os.close(fd)  # successful return transfers exactly this live FD to caller
                self.assertEqual(io.live(), [])
        for kind in ("directory", "file"):
            with self.subTest(nofollow=kind), self.traced("no-nofollow-" + kind, self.product) as io:
                io.O_NOFOLLOW = 0
                with self.assertRaisesRegex(RuntimeError, "O_NOFOLLOW"):
                    self.call(self.product, kind)
                self.assertEqual(io.entries, [])

    def test_02_real_missing_descendant_and_stale_root_witness(self):
        for module, name in ((self.product, "candidate"), (self.baseline, "expected-baseline-violation")):
            with self.subTest(source=name), self.traced(name + "-missing", module) as io:
                with self.assertRaises(FileNotFoundError):
                    self.call(module, "file", Path("a/missing/leaf.txt"))
                self.assertEqual(len(io.live()), 0 if module is self.product else 1)
            with self.subTest(source=name, sentinel=True), self.traced(name + "-released-root-reuse", module) as io:
                io.reuse = True
                with self.assertRaises(FileNotFoundError):
                    self.call(module, "file", Path("a/missing/leaf.txt"))
                self.assertTrue(io.triggered)
                self.assertEqual(len(io.live()), 0 if module is self.product else 1)
                self.assertEqual(len(io.live("sentinel")), 1 if module is self.product else 0)
        with self.traced("candidate-real-directory-missing", self.product) as io:
            with self.assertRaises(FileNotFoundError):
                self.call(self.product, "directory", Path("a/missing"))
            self.assertEqual(io.live(), [])

    def test_03_ordinary_and_fatal_open_failure(self):
        for kind in ("directory", "file"):
            for error in (OSError(errno.EIO, "injected open"), FatalWalk("injected fatal open")):
                with self.subTest(kind=kind, error=type(error).__name__), self.traced("candidate-open-" + kind + "-" + type(error).__name__, self.product) as io:
                    io.open_error = error
                    with self.assertRaises(type(error)) as raised:
                        self.call(self.product, kind, Path("a/missing/leaf.txt"))
                    self.assertIs(raised.exception, error)
                    self.assertEqual(io.live(), [])
            with self.traced("expected-baseline-fatal-leak-" + kind, self.baseline) as io:
                error = FatalWalk("baseline witness")
                io.open_error = error
                with self.assertRaises(FatalWalk) as raised:
                    self.call(self.baseline, kind, Path("a/missing/leaf.txt"))
                self.assertIs(raised.exception, error)
                self.assertEqual(len(io.live()), 1)

    def test_04_after_effect_close_error_and_reused_sentinel(self):
        for module, name in ((self.product, "candidate"), (self.baseline, "expected-baseline-violation")):
            for kind in ("directory", "file"):
                for error in (OSError(errno.EINTR, "injected AFTER release"), FatalWalk("fatal AFTER release")):
                    with self.subTest(source=name, kind=kind, error=type(error).__name__), self.traced(name + "-after-close-" + kind + "-" + type(error).__name__, module) as io:
                        io.close_error, io.reuse = error, True
                        with self.assertRaises(type(error)) as raised:
                            self.call(module, kind)
                        self.assertIs(raised.exception, error)
                        self.assertTrue(io.triggered)
                        self.assertEqual(len(io.live()), 0 if module is self.product else 1)
                        sentinel_expected = module is self.product or isinstance(error, FatalWalk)
                        self.assertEqual(len(io.live("sentinel")), int(sentinel_expected))
                        if module is self.product:
                            sentinel = io.live("sentinel")[0]["fd"]
                            self.assertEqual(io.closes[io.trigger_close_index:].count(sentinel), 1)  # this lifetime only
                            self.assertEqual(os.read(sentinel, 1024), b"caller-owned sentinel")

    def test_05_before_effect_ambiguity_and_cleanup_error_semantics(self):
        for kind in ("directory", "file"):
            with self.subTest(before_effect=kind), self.traced("candidate-BEFORE-close-UNKNOWN-" + kind, self.product) as io:
                error = OSError(errno.EINTR, "injected BEFORE release")
                io.close_error, io.before_effect = error, True
                with self.assertRaises(OSError) as raised:
                    self.call(self.product, kind)
                self.assertIs(raised.exception, error)
                self.assertTrue(io.triggered)
                # Genuine retained previous owner, not a closed/healthy claim.
                self.assertEqual(len(io.live()), 1)
                previous = io.live()[0]["fd"]
                self.assertEqual(io.closes[io.trigger_close_index:].count(previous), 1)
                self.assertEqual(io.states()[-1]["state"], "closed")  # acquired child recovered by product
            with self.subTest(cleanup=kind), self.traced("candidate-cleanup-error-semantics-" + kind, self.product) as io:
                primary = OSError(errno.EIO, "primary open failure")
                cleanup = OSError(errno.EINTR, "cleanup AFTER release")
                io.open_error, io.cleanup_error = primary, cleanup
                with self.assertRaises(OSError) as raised:
                    self.call(self.product, kind, Path("a/missing/leaf.txt"))
                # Existing directory cleanup can mask primary; file suppresses OSError.
                self.assertIs(raised.exception, cleanup if kind == "directory" else primary)
                self.assertEqual(io.live(), [])

    def test_06_symlink_and_validation_to_open_swap_refused(self):
        outside = self.work / "outside.txt"
        outside.write_bytes(b"outside-root")
        (self.root / "leaf-link.txt").symlink_to(outside)
        (self.root / "dir-link").symlink_to(self.root / "a", target_is_directory=True)
        for relative in (Path("leaf-link.txt"), Path("dir-link/b/file.txt")):
            with self.subTest(relative=str(relative)), self.traced("candidate-symlink-" + relative.parts[0], self.product) as io:
                with self.assertRaises(OSError):
                    self.call(self.product, "file", relative)
                self.assertEqual(io.live(), [])
                with self.assertRaises(ValueError):
                    self.product._allowed_path(self.root / relative)
        with self.assertRaises(ValueError):
            self.product._allowed_path(outside)
        for point in ("file.txt", "b"):
            with self.subTest(swap=point), self.traced("candidate-validated-swap-" + point, self.product) as io:
                self.product._allowed_path(self.file)  # real normal validation first
                swapped = []
                old = (self.file if point == "file.txt" else self.root / "a/b")
                moved = old.with_name(old.name + ".saved")
                def swap(part):
                    if str(part) == point and not swapped:
                        old.rename(moved)
                        old.symlink_to(outside if point == "file.txt" else moved, target_is_directory=point == "b")
                        swapped.append(True)
                io.before_open = swap
                try:
                    with self.assertRaises(OSError):
                        self.product._open_allowed_file(self.file)
                    self.assertEqual(swapped, [True])
                    self.assertEqual(io.live(), [])
                finally:
                    if swapped:
                        old.unlink()
                        moved.rename(old)

    def test_07_real_snapshot_bytes_hash_and_source_identity(self):
        # Local named early-fault seam: no authorization/identity/security replacement.
        # Both descriptors are acquired by the real composed Linux path before fault.
        for module, name in ((self.product, "candidate"), (self.a4_snapshot, "historical-a4-snapshot-current-reader")):
            for point in ("digest", "source-constructor"):
                for error in (OSError(errno.EIO, "early snapshot ordinary"), FatalWalk("early snapshot fatal")):
                    with self.subTest(snapshot_source=name, fault=point, error=type(error).__name__), self.traced(name + "-" + point + "-" + type(error).__name__, self.product) as io:
                        original_os, original_hashlib = module.os, module.hashlib
                        native_open = io.open
                        acquired, reached, authorized = {}, [], []
                        def snapshot_open(path, flags, mode=0o777, *, dir_fd=None):
                            fd = native_open(path, flags, mode, dir_fd=dir_fd)
                            row = io.entries[-1]
                            if stat.S_ISREG(os.fstat(fd).st_mode):
                                role = "target" if flags & os.O_CREAT else "source"
                                self.assertNotIn(role, acquired)
                                acquired[role] = {**row, "close_index": len(io.closes)}
                            return fd
                        def early_snapshot_fault():
                            self.assertEqual(set(acquired), {"source", "target"})
                            self.assertNotEqual(acquired["source"]["fd"], acquired["target"]["fd"])
                            for role in ("source", "target"):
                                self.assertEqual(identity(acquired[role]["fd"]), acquired[role]["identity"])
                            reached.append(point)
                            raise error
                        def source_constructor(fd, mode, *args, **kwargs):
                            if mode == "rb" and point == "source-constructor":
                                self.assertEqual(fd, acquired["source"]["fd"])
                                self.assertIs(kwargs.get("closefd"), False)
                                early_snapshot_fault()
                            return os.fdopen(fd, mode, *args, **kwargs)
                        def digest_constructor(*args, **kwargs):
                            if point == "digest":
                                early_snapshot_fault()
                            return hashlib.sha256(*args, **kwargs)
                        io.open, io.fdopen = snapshot_open, source_constructor
                        module.os = io
                        module.hashlib = types.SimpleNamespace(sha256=digest_constructor)
                        try:
                            with self.assertRaises(type(error)) as raised:
                                module._snapshot_allowed_file(self.file, max_bytes=4096, authorize_identity=authorized.append)
                            self.assertIs(raised.exception, error)
                            self.assertEqual(reached, [point])
                            before_recovery = []
                            for role, row in acquired.items():
                                try:
                                    current = identity(row["fd"])
                                except OSError as exc:
                                    self.assertEqual(exc.errno, errno.EBADF)
                                    current = None
                                closed = current is None
                                expected_closed = role == "source" or module is self.product
                                before_recovery.append({"role": role, "fd": row["fd"], "identity": row["identity"], "closed": closed})
                                self.assertEqual(closed, expected_closed)
                                self.assertEqual(io.closes[row["close_index"]:].count(row["fd"]), int(expected_closed))
                            self.assertEqual(len(io.live()), 0 if module is self.product else 1)
                            source_info = self.file.stat()
                            self.assertEqual(authorized, [(source_info.st_dev, source_info.st_ino)])
                            self.assertEqual(self.file.read_bytes(), self.payload)
                            target_exists = Path(acquired["target"]["part"]).exists()
                            self.assertEqual(target_exists, isinstance(error, FatalWalk) or (module is self.a4_snapshot and point == "digest"))
                            OBSERVATIONS.append({"main": self._testMethodName, "early_snapshot": name,
                                "fault": point, "error": type(error).__name__, "reached_after_both_acquired": reached,
                                "before_emergency_cleanup": before_recovery, "target_exists": target_exists,
                                "roles": "full-current-module" if module is self.product else "exact-a4-snapshot-body+current-reader-guards"})
                        finally:
                            module.os, module.hashlib = original_os, original_hashlib
        # Original healthy bytes/hash/metadata/authorizer controls remain intact.
        before = self.file.stat()
        authorized = []
        with self.traced("candidate-full-snapshot", self.product) as io:
            snapshot, metadata = self.product._snapshot_allowed_file(
                self.file, max_bytes=4096, authorize_identity=authorized.append)
            self.assertEqual(io.live(), [])
            self.assertEqual(snapshot.read_bytes(), self.payload)
            self.assertEqual(metadata["size_bytes"], len(self.payload))
            self.assertEqual(metadata["file_hash"], hashlib.sha256(self.payload).hexdigest())
            self.assertEqual(metadata["mtime_ns"], before.st_mtime_ns)
            self.assertEqual(metadata["file_identity"], (before.st_dev, before.st_ino))
            self.assertEqual(authorized, [(before.st_dev, before.st_ino)])
            self.assertEqual(Path(metadata["snapshot_dir"]), snapshot.parent)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(snapshot.parent.stat().st_mode), 0o700)
            self.assertEqual(snapshot.stat().st_uid, os.getuid())
            self.file.write_bytes(b"edited original after snapshot")
            self.assertNotEqual(self.file.read_bytes(), self.payload)
            self.assertEqual(snapshot.read_bytes(), self.payload)
            self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), metadata["file_hash"])
            OBSERVATIONS.append({"main": self._testMethodName, "snapshot": str(snapshot),
                                 "metadata": metadata, "source_edited": True})

    def test_08_static_baseline_scope_imports_and_audit(self):
        raw = (ROOT / "document_knowledge_graph.py").read_bytes()
        lines = raw.splitlines(keepends=True)
        nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name in CURRENT_DEFINITION_SHA256]
        self.assertEqual([n.name for n in nodes], list(CURRENT_DEFINITION_SHA256))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CURRENT_MODULE_SHA256)
        self.assertEqual(hashlib.sha256(b"".join(lines[:nodes[0].lineno - 1])).hexdigest(), UNCHANGED_PREFIX_SHA256)
        self.assertEqual(hashlib.sha256(b"".join(lines[nodes[-1].end_lineno:])).hexdigest(), UNCHANGED_SUFFIX_SHA256)
        self.assertEqual([hashlib.sha256(b"".join(lines[a.end_lineno:b.lineno - 1])).hexdigest()
                          for a, b in zip(nodes, nodes[1:])], UNCHANGED_GAPS_SHA256)
        for node in nodes:
            self.assertEqual(hashlib.sha256(b"".join(lines[node.lineno - 1:node.end_lineno])).hexdigest(), CURRENT_DEFINITION_SHA256[node.name])
        snapshot_fixture = (ROOT / "tests/fixtures/document_snapshot_fd_owner_a4_baseline.py.txt").read_bytes()
        self.assertEqual(hashlib.sha256(snapshot_fixture).hexdigest(), A4_SNAPSHOT_FIXTURE_SHA256)
        snapshot_nodes = ast.parse(snapshot_fixture).body
        self.assertEqual(len(snapshot_nodes), 1)
        self.assertIsInstance(snapshot_nodes[0], ast.FunctionDef)
        self.assertEqual(snapshot_nodes[0].name, "_snapshot_allowed_file")

        fixture = (ROOT / "tests/fixtures/document_posix_fd_owner_baseline.py.txt").read_bytes()
        self.assertEqual(hashlib.sha256(fixture).hexdigest(), BASELINE_FIXTURE_SHA256)
        fixture_lines = fixture.splitlines(keepends=True)
        baseline_nodes = ast.parse(fixture).body
        self.assertEqual(len(baseline_nodes), 2)
        for node in baseline_nodes:
            self.assertIsInstance(node, ast.FunctionDef)
            span = b"".join(fixture_lines[node.lineno - 1:node.end_lineno])
            self.assertEqual(hashlib.sha256(span).hexdigest(), BASELINE_SPANS[node.name][2])
        origins = {}
        for name in ("document_knowledge_graph", "document_extractors", "guard"):
            path = Path(sys.modules[name].__file__).resolve()
            self.assertEqual(path, ROOT / (name + ".py"))
            origins[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        self.assertFalse(any(n.split(".")[0] in {"agent", "hermes_cli", "hermes_sdk"} for n in sys.modules))
        self.assertNotIn("spreadsheet_formulas", sys.modules)
        self.assertFalse((ROOT / "spreadsheet_formulas.py").exists())
        self.assertEqual(AUDIT_DENIALS, [])
        OBSERVATIONS.append({"main": self._testMethodName, "STATIC": "outside three defs byte-identical to common a4",
                             "imports": origins, "audit_denials": list(AUDIT_DENIALS)})


def install_offline_fence():
    def audit(event, args):
        denied = (event.startswith(("socket.", "ctypes.")) or event in
                  {"subprocess.Popen", "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "sqlite3.connect"})
        if event == "import" and str(args[0]).split(".")[0] in {"agent", "hermes_cli", "hermes_sdk"}:
            denied = True
        paths = []
        if event == "open":
            path, mode, flags = args
            if isinstance(path, (str, bytes)) and ((isinstance(mode, str) and any(c in mode for c in "wax+")) or
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                paths.append(path)
        elif event in {"os.mkdir", "os.rmdir", "os.remove", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
            if isinstance(args[0], (str, bytes)):
                paths.append(args[0])
        elif event in {"os.rename", "os.link"}:
            paths.extend(args[:2])
        elif event == "os.symlink":
            paths.append(args[1])
        for path in paths:
            absolute = os.path.abspath(os.fsdecode(path))
            if not absolute.startswith("/work/"):
                denied = True
        if denied:
            AUDIT_DENIALS.append(event)
            raise PermissionError("standalone offline fence: " + event)
    sys.addaudithook(audit)


def main():
    # Real interpreter identity emitted before product imports/tests.
    executable = Path(sys.executable).resolve()
    input_names = ("document_knowledge_graph.py", "document_extractors.py", "guard.py",
                   "tests/test_document_posix_fd_owner.py", "tests/fixtures/document_posix_fd_owner_baseline.py.txt",
                   "tests/fixtures/document_snapshot_fd_owner_a4_baseline.py.txt")
    print("LINUX_IDENTITY " + json.dumps({"executable": sys.executable, "real_executable": str(executable),
          "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "version": sys.version,
          "platform": sys.platform, "uid": os.getuid() if os.name == "posix" else None,
          "isolated": sys.flags.isolated, "dont_write_bytecode": sys.flags.dont_write_bytecode,
          "inputs": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in input_names},
          "roster": unittest.defaultTestLoader.getTestCaseNames(DocumentPosixFDOwner)}), file=sys.stderr, flush=True)
    offline = os.environ.get("DOCUMENT_POSIX_FD_OFFLINE") == "1"
    if offline:
        if sys.platform != "linux" or Path.cwd() != Path("/work"):
            raise RuntimeError("offline packet requires Linux and owned /work")
        install_offline_fence()
    class Report(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.rows = []
            self.current = None
        def startTest(self, test):
            self.current = {"id": test._testMethodName, "outcome": "unknown", "subtests": 0, "subcase_results": []}
            self.rows.append(self.current)
            print("DEVTOOLS_CASE_STARTED " + test._testMethodName, file=sys.stderr, flush=True)
            super().startTest(test)
        def addSuccess(self, test):
            super().addSuccess(test)
            self.current["outcome"] = "passed"
        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.current["outcome"] = "failed"
        def addError(self, test, err):
            super().addError(test, err)
            if self.current is not None:
                self.current["outcome"] = "error"
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.current["outcome"] = "skipped"
        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            self.current["subtests"] += 1
            self.current["subcase_results"].append({"parameters": dict(subtest.params),
                "outcome": "passed" if err is None else "failed" if issubclass(err[0], test.failureException) else "error"})
            if err is not None:
                self.current["outcome"] = "failed" if issubclass(err[0], test.failureException) else "error"
    result = unittest.TextTestRunner(verbosity=2, resultclass=Report).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DocumentPosixFDOwner))
    report = {"schema": "memory-stack.cases/v1", "cases": result.rows, "observations": OBSERVATIONS,
              "audit_denials": AUDIT_DENIALS, "offline_fence": offline, "testsRun": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped)}
    print(json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if result.wasSuccessful() and not AUDIT_DENIALS else 1


if __name__ == "__main__":
    raise SystemExit(main())
