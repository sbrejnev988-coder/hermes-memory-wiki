"""Standalone stdlib regressions for first-generation filesystem publication.

Run without importing the plugin package or any peer fixture:
  python -I -B -S tests/test_erasure_atomic_bootstrap.py --scratch <owned-dir>

The SOURCE packet executes these same bytes through the generic audit bootstrap.
Each test executes the COMPLETE privacy_erasure.py in its own ordinary module.
Faults are scoped to that module's open/os seams, never process-global patches.
Real filesystem xb/fsync failures and authored rename seams are distinguished.
No provider, SQLite, SDK, replay, hard-crash or historical continuity proof.
"""
from __future__ import annotations

import argparse
import builtins
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import threading
import types
import unittest


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _snapshot(directory):
    if not directory.exists():
        return {"exists": False, "files": {}}
    files = {}
    for path in sorted(directory.iterdir()):
        info = path.stat()
        files[path.name] = ({"bytes": info.st_size, "sha256": _sha(path.read_bytes()),
                             "mtime_ns": info.st_mtime_ns}
                            if path.is_file() else {"directory": True})
    return {"exists": True, "files": files}


def _record(key, seq=1, previous="0" * 64):
    body = {"v": 1, "seq": seq, "prev": previous, "fixture": "content-free-synthetic"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["mac"] = hmac.new(key, raw, hashlib.sha256).hexdigest()
    return body


def _line(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n"


class InjectedPublicationFailure(OSError):
    pass


class _Probe:
    """Pass-through FS observer/injector owned by one isolated source module."""
    def __init__(self, mode=None):
        self.mode = mode
        self.fired = False
        self.primary = None
        self.handles = []
        self.fd_paths = {}
        self.key_fsynced = False
        self.syncs = []
        self.dir_syncs = []
        self.renames = []
        self.generated = []
        self.xb_failure_after_key_fsync = False
        self.thread_lock = threading.Lock()

    def open(self, path, mode="r", *args, **kwargs):
        path = Path(path)
        if (mode == "xb" and path.name == "intents.jsonl"
                and self.mode == "log_xb" and not self.fired):
            self.fired = True
            self.xb_failure_after_key_fsync = self.key_fsynced
            # A transient, test-owned file really refuses the production
            # xb open. Remove only this fixture obstruction, not authority.
            with builtins.open(path, "xb"):
                pass
            try:
                return builtins.open(path, mode, *args, **kwargs)
            except OSError as exc:
                self.primary = exc
                path.unlink()
                raise
        stream = builtins.open(path, mode, *args, **kwargs)
        with self.thread_lock:
            self.handles.append((path, stream))
            self.fd_paths[stream.fileno()] = path
        return stream

    def fsync(self, fd):
        path = self.fd_paths.get(fd)
        if (path is not None and path.name == "intents.jsonl"
                and self.mode == "log_fsync" and not self.fired):
            self.fired = True
            # Real EBADF from fsync, without corrupting/closing the production
            # stream or making its context-manager cleanup mask the primary.
            stale = os.dup(fd)
            os.close(stale)
            try:
                os.fsync(stale)
            except OSError as exc:
                self.primary = exc
                raise
        os.fsync(fd)
        if path is not None:
            self.syncs.append(path.name)
            if path.name == "key.bin":
                self.key_fsynced = True

    def urandom(self, length):
        raw = os.urandom(length)
        self.generated.append(_sha(raw))
        return raw

    def rename(self, source, destination):
        source, destination = Path(source), Path(destination)
        event = {"stage": _snapshot(source), "canonical_before": _snapshot(destination),
                 "closed_stage_handles": all(h.closed for p, h in self.handles if p.parent == source),
                 "synced_files": list(self.syncs), "stage_dir_sync_returned": str(source) in self.dir_syncs,
                 "published": False}
        self.renames.append(event)
        if self.mode == "prepublish" and not self.fired:
            self.fired = True
            self.primary = InjectedPublicationFailure("authored-prepublication")
            raise self.primary
        os.rename(source, destination)
        event["published"] = True
        event["canonical_after"] = _snapshot(destination)
        if self.mode == "postpublish" and not self.fired:
            self.fired = True
            self.primary = InjectedPublicationFailure("authored-postpublication")
            raise self.primary

    def install(self, module):
        # Only this full-source module's explicit FS bindings change. Imports,
        # _file_lock, parser, HMAC, threading and stdlib globals stay genuine.
        probe = self
        class ModuleOS:
            def __getattr__(self, name):
                if name in ("fsync", "rename", "urandom"):
                    return getattr(probe, name)
                return getattr(os, name)
        original_sync = module._fsync_dir
        def dir_sync(path):
            original_sync(path)
            self.dir_syncs.append(str(path))
        module.open = self.open
        module.os = ModuleOS()
        module._fsync_dir = dir_sync

    def witness(self):
        return {"fault": self.mode, "fired": self.fired, "key_fsynced": self.key_fsynced,
                "xb_failure_after_key_fsync": self.xb_failure_after_key_fsync,
                "synced_files": self.syncs, "renames": self.renames,
                "generated_key_hashes": self.generated,
                "all_module_handles_closed": all(h.closed for _, h in self.handles)}


class AtomicBootstrapTests(unittest.TestCase):
    source_raw = None
    source_path = None
    scratch = None

    def setUp(self):
        self.work = Path(self.scratch) / self._testMethodName
        self.work.mkdir(parents=True, exist_ok=False)
        self.root = self.work / "store"
        self.root.mkdir()
        self.canonical = self.root / "privacy-erasure"

    def module(self, probe=None):
        module = types.ModuleType("erasure_atomic_standalone")
        module.__file__ = str(self.source_path)
        module.__package__ = ""
        exec(compile(self.source_raw, str(self.source_path), "exec", dont_inherit=True), module.__dict__)
        if probe is not None:
            probe.install(module)
        return module

    def note(self, label, **values):
        # Durable, hash-only source/state witnesses always precede assertions.
        row = {"label": label, "source_sha256": _sha(self.source_raw), **values}
        raw = (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
        with (self.work / "witnesses.jsonl").open("ab") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())

    def attempt(self, module):
        try:
            return module.ErasureLedger(self.root), None
        except BaseException as exc:
            return None, exc

    def stages(self):
        return {p.name: _snapshot(p) for p in sorted(self.root.glob(".privacy-erasure-stage-*"))}

    def seed(self, *, key=None, records=2, lock=True):
        key = os.urandom(32) if key is None else key
        self.canonical.mkdir()
        (self.canonical / "key.bin").write_bytes(key)
        previous, data = "0" * 64, b""
        for seq in range(1, records + 1):
            record = _record(key, seq, previous)
            data += _line(record)
            previous = record["mac"]
        (self.canonical / "intents.jsonl").write_bytes(data)
        if lock:
            (self.canonical / "intents.lock").write_bytes(b"\0")
        return key, previous

    def test_fresh_restart(self):
        probe = _Probe()
        module = self.module(probe)
        first = module.ErasureLedger(self.root)
        empty = first.load()
        fresh = _snapshot(self.canonical)
        # An authenticated synthetic record exercises constructor/load continuity;
        # this is NOT a provider append or SQL replay control.
        record = _record(first.key)
        first.log_path.write_bytes(_line(record))
        before = _snapshot(self.canonical)
        second = module.ErasureLedger(self.root)
        entries = second.load()
        after = _snapshot(self.canonical)
        self.note("fresh-restart", fresh=fresh, before=before, after=after,
                  entry_count=len(entries), probe=probe.witness())
        self.assertEqual(empty, [])
        self.assertEqual(set(fresh["files"]), {"key.bin", "intents.jsonl", "intents.lock"})
        self.assertEqual(fresh["files"]["key.bin"]["bytes"], 32)
        self.assertEqual(fresh["files"]["intents.jsonl"]["bytes"], 0)
        self.assertTrue(first.key == second.key, "restart_rotated_key")
        self.assertTrue(entries == [record], "restart_changed_tip")
        self.assertEqual(before, after)
        self.assertEqual(len(probe.generated), 1)
        self.assertEqual(len(probe.renames), 1)
        self.assertTrue(probe.renames[0]["closed_stage_handles"])
        self.assertTrue(probe.renames[0]["stage_dir_sync_returned"])
        self.assertTrue({"key.bin", "intents.jsonl", "intents.lock"}.issubset(probe.renames[0]["synced_files"]))
        self.assertTrue((self.root / "privacy-erasure.init.lock").is_file())

    def test_legacy_pair_restart(self):
        key, tip = self.seed()
        before = _snapshot(self.canonical)
        probe = _Probe()
        module = self.module(probe)
        first, second = module.ErasureLedger(self.root), module.ErasureLedger(self.root)
        entries = second.load()
        after = _snapshot(self.canonical)
        self.note("legacy-restart", before=before, after=after, tip=entries[-1]["mac"], probe=probe.witness())
        self.assertTrue(first.key == second.key == key, "legacy_rotated_key")
        self.assertEqual(entries[-1]["mac"], tip)
        self.assertEqual(len(entries), 2)
        self.assertEqual(before, after)
        self.assertEqual(probe.generated, [])
        self.assertEqual(probe.renames, [])

    def unpublished_failure(self, mode):
        probe = _Probe(mode)
        module = self.module(probe)
        _, primary = self.attempt(module)
        failed = _snapshot(self.canonical)
        stages_before = self.stages()
        first_witness = probe.witness()
        self.note("failed-before-retry", canonical=failed, stages=stages_before,
                  exact_primary=primary is probe.primary, probe=first_witness)
        retried, retry_error = self.attempt(module)
        after = _snapshot(self.canonical)
        stages_after = self.stages()
        self.note("retry", canonical=after, stages=stages_after,
                  retry_error=None if retry_error is None else {"type": type(retry_error).__name__, "message": str(retry_error)},
                  exact_primary=primary is probe.primary, probe=probe.witness())
        self.assertTrue(primary is not None and primary is probe.primary, "primary_was_masked")
        self.assertTrue(probe.fired and probe.key_fsynced, "failure_seam_not_reached_after_key_fsync")
        if mode == "log_xb":
            self.assertIs(type(primary), FileExistsError)
            self.assertTrue(probe.xb_failure_after_key_fsync)
        if mode == "log_fsync":
            self.assertIs(type(primary), OSError)
        self.assertFalse(failed["exists"], "unpublished_failure_exposed_canonical")
        self.assertIsNone(retry_error, "healthy_retry_remained_blocked")
        self.assertIsNotNone(retried)
        self.assertEqual(retried.load(), [])
        self.assertEqual(len(stages_before), 1)
        self.assertEqual(stages_before, stages_after, "retry_changed_or_adopted_orphan")
        old_key = next(iter(stages_before.values()))["files"]["key.bin"]["sha256"]
        self.assertNotEqual(old_key, after["files"]["key.bin"]["sha256"], "retry_reused_unpublished_stage")
        self.assertEqual(len(probe.generated), 2)
        self.assertTrue(probe.witness()["all_module_handles_closed"])

    def test_log_xb_failure_retry(self):
        self.unpublished_failure("log_xb")

    def test_log_fsync_failure_retry(self):
        self.unpublished_failure("log_fsync")

    def test_prepublish_failure_retry(self):
        self.unpublished_failure("prepublish")

    def test_postpublish_failure_restart(self):
        probe = _Probe("postpublish")
        module = self.module(probe)
        _, primary = self.attempt(module)
        before = _snapshot(self.canonical)
        self.note("postpublication-failure", canonical=before, exact_primary=primary is probe.primary,
                  probe=probe.witness())
        ledger, error = self.attempt(module)
        after = _snapshot(self.canonical)
        self.note("postpublication-retry", before=before, after=after, retry_ok=error is None,
                  probe=probe.witness())
        self.assertTrue(primary is not None and primary is probe.primary)
        self.assertIs(type(primary), InjectedPublicationFailure)
        self.assertTrue(probe.renames[0]["published"])
        self.assertTrue(probe.renames[0]["closed_stage_handles"])
        self.assertEqual(set(before["files"]), {"key.bin", "intents.jsonl", "intents.lock"})
        self.assertIsNone(error)
        self.assertEqual(ledger.load(), [])
        self.assertEqual(before, after)
        self.assertEqual(len(probe.generated), 1)
        self.assertEqual(self.stages(), {})

    def incomplete(self, kind):
        self.canonical.mkdir()
        if kind == "key":
            (self.canonical / "key.bin").write_bytes(os.urandom(32))
        if kind == "ledger":
            (self.canonical / "intents.jsonl").write_bytes(b"unverifiable-synthetic-history\n")
        if kind == "lock":
            (self.canonical / "intents.lock").write_bytes(b"historical-lock-marker")
        before = _snapshot(self.canonical)
        probe = _Probe()
        module = self.module(probe)
        first, error1 = self.attempt(module)
        second, error2 = self.attempt(module)
        after = _snapshot(self.canonical)
        self.note("incomplete-untouched", kind=kind, before=before, after=after,
                  errors=[None if e is None else {"type": type(e).__name__, "message": str(e)} for e in (error1, error2)],
                  probe=probe.witness())
        self.assertTrue(first is None and second is None)
        self.assertTrue(type(error1) is RuntimeError and type(error2) is RuntimeError)
        self.assertEqual(str(error1), "privacy erasure ledger is incomplete")
        self.assertEqual(str(error2), str(error1))
        self.assertEqual(before, after, "incomplete_canonical_mutated")
        self.assertEqual(probe.generated, [])
        self.assertEqual(probe.handles and [p.parent == self.canonical for p, _ in probe.handles], [False, False])
        self.assertEqual(self.stages(), {})

    def test_existing_key_only_untouched(self):
        self.incomplete("key")

    def test_existing_ledger_only_untouched(self):
        self.incomplete("ledger")

    def test_existing_neither_untouched(self):
        self.incomplete("neither")

    def test_existing_lock_only_untouched(self):
        self.incomplete("lock")

    def invalid(self, kind):
        key, _ = self.seed(key=b"short" if kind == "key" else None)
        if kind in ("mac", "seq", "prev"):
            record = _record(key, seq=2 if kind == "seq" else 1,
                             previous="1" * 64 if kind == "prev" else "0" * 64)
            if kind == "mac":
                record["mac"] = "0" * 64
            (self.canonical / "intents.jsonl").write_bytes(_line(record))
        before = _snapshot(self.canonical)
        probe = _Probe()
        module = self.module(probe)
        ledger, error = self.attempt(module)
        after = _snapshot(self.canonical)
        self.note("invalid-untouched", kind=kind, before=before, after=after,
                  error=None if error is None else {"type": type(error).__name__, "message": str(error)}, probe=probe.witness())
        self.assertIsNone(ledger)
        self.assertIs(type(error), RuntimeError)
        self.assertEqual(str(error), "privacy erasure key is invalid" if kind == "key" else "privacy erasure ledger integrity failed")
        self.assertEqual(before, after)
        self.assertEqual(probe.generated, [])
        self.assertEqual(probe.renames, [])

    def test_invalid_key(self):
        self.invalid("key")

    def test_invalid_mac(self):
        self.invalid("mac")

    def test_invalid_sequence(self):
        self.invalid("seq")

    def test_invalid_previous(self):
        self.invalid("prev")

    def test_orphan_stage_is_not_authority(self):
        stage = self.root / ".privacy-erasure-stage-untrusted"
        stage.mkdir()
        key = os.urandom(32)
        (stage / "key.bin").write_bytes(key)
        (stage / "intents.jsonl").write_bytes(_line(_record(key)))
        (stage / "intents.lock").write_bytes(b"\0")
        before = self.stages()
        probe = _Probe()
        ledger = self.module(probe).ErasureLedger(self.root)
        after = self.stages()
        entries = ledger.load()
        self.note("orphan-ignored", before=before, after=after, canonical=_snapshot(self.canonical),
                  entry_count=len(entries), probe=probe.witness())
        self.assertTrue(key != ledger.key, "orphan_became_authority")
        self.assertEqual(entries, [])
        self.assertEqual(before, after)
        self.assertEqual(len(probe.generated), 1)

    def test_two_cooperating_initializers(self):
        probe = _Probe()
        module = self.module(probe)
        barrier = threading.Barrier(3, timeout=5)
        ledgers, errors = [], []
        result_lock = threading.Lock()
        def initialize():
            try:
                barrier.wait()
                ledger = module.ErasureLedger(self.root)
                with result_lock:
                    ledgers.append(ledger)
            except BaseException as exc:
                with result_lock:
                    errors.append(type(exc).__name__)
        threads = [threading.Thread(target=initialize, name="erasure-initializer-" + str(i), daemon=True) for i in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        before = _snapshot(self.canonical)
        restarted, error = self.attempt(module)
        after = _snapshot(self.canonical)
        alive = [thread.name for thread in threads if thread.is_alive()]
        self.note("cooperating-initializers", before=before, after=after, completed=len(ledgers),
                  errors=errors, alive=alive, restart_ok=error is None, probe=probe.witness())
        self.assertEqual(alive, [])
        self.assertEqual(errors, [])
        self.assertEqual(len(ledgers), 2)
        self.assertIsNone(error)
        self.assertTrue(all(ledger.key == restarted.key for ledger in ledgers), "initializers_chose_different_keys")
        self.assertEqual([ledger.load() for ledger in ledgers], [[], []])
        self.assertEqual(before, after)
        self.assertEqual(len(probe.generated), 1)
        self.assertEqual(len(probe.renames), 1)
        self.assertTrue(probe.renames[0]["closed_stage_handles"])


CASE_IDS = tuple(unittest.defaultTestLoader.getTestCaseNames(AtomicBootstrapTests))


def make_suite(source_raw, source_path, scratch, case_ids=None):
    AtomicBootstrapTests.source_raw = source_raw
    AtomicBootstrapTests.source_path = Path(source_path)
    AtomicBootstrapTests.scratch = Path(scratch)
    selected = CASE_IDS if case_ids is None else tuple(case_ids)
    if not selected or len(selected) != len(set(selected)) or any(name not in CASE_IDS for name in selected):
        raise ValueError("invalid_exact_case_roster")
    return unittest.TestSuite(AtomicBootstrapTests(name) for name in selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).absolute().parent.parent / "privacy_erasure.py")
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=False)
    suite = make_suite(args.source.read_bytes(), args.source, args.scratch)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
