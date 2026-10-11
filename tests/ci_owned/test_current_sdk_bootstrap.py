"""Carrier unit package: no root conftest, SDK fakes or native subprocesses.

Loaded explicitly by current_sdk_bootstrap.worker before the separately guarded
actual-SDK component. Unit-injected audit calls test tooling only, not Core.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import unittest

CARRIER = None  # assigned by the exact real carrier, not a semantic helper


class CurrentSdkCarrierTests(unittest.TestCase):
    def ledger(self, cap=128):
        root = Path(os.environ["HERMES_HOME"]).absolute().parent
        return CARRIER.Ledger((("fixture", root), ("source", CARRIER.SOURCE)), row_cap=cap)

    def test_phase_unwinds_after_exception_and_nesting(self):
        ledger = self.ledger()
        with ledger.phase("register"):
            with self.assertRaises(ValueError):
                with ledger.phase("bootstrap.config_load"):
                    self.assertEqual(ledger.phase_path.get(), ("setup", "register", "bootstrap.config_load"))
                    raise ValueError("owned-test")
            self.assertEqual(ledger.phase_path.get(), ("setup", "register"))
        self.assertEqual(ledger.phase_path.get(), ("setup",))

    def test_all_refusals_count_past_bounded_sidecar(self):
        ledger = self.ledger(cap=2)
        for _ in range(26):
            with self.assertRaises(PermissionError):
                ledger.audit("socket.gethostname", ())
        report = ledger.report()
        self.assertEqual(report["refused_total"], 26)
        self.assertEqual(len(report["refusals"]), 2)
        self.assertTrue(report["refusal_rows_truncated"])
        self.assertEqual(report["counts"][0]["count"], 26)
        # Only primitive bounded identities; no frames/locals/args/providers.
        for row in report["refusals"]:
            self.assertEqual(set(row), {"event", "phase", "callers"})
            for caller in row["callers"]:
                self.assertEqual(set(caller), {"file", "name", "line"})
                self.assertIs(type(caller["line"]), int)
        json.dumps(report)

    def test_process_and_network_denied_in_every_phase_no_arg_retention(self):
        ledger = self.ledger()
        class CannotRender:
            def __repr__(self):
                raise AssertionError("foreign_repr_must_not_run")
            __str__ = __repr__
        for phase in ("bootstrap.config_import", "register", "initialize", "shutdown", "origin_readback"):
            with ledger.phase(phase):
                for event in ("socket.gethostname", "socket.__new__", "socket.connect", "subprocess.Popen",
                              "_winapi.CreateProcess", "os.system", "os.spawn", "os.fork"):
                    with self.assertRaises(PermissionError):
                        ledger.audit(event, (CannotRender(),))
        self.assertEqual(ledger.report()["refused_total"], 40)
        self.assertNotIn("CannotRender", json.dumps(ledger.report()))

    def test_foreign_file_write_and_sqlite_are_refused_before_effect(self):
        ledger = self.ledger()
        foreign = Path(os.environ["HERMES_HOME"]).absolute().parent.parent / "owned-inert-foreign" / "sentinel"
        self.assertFalse(foreign.exists())
        for event, args in (("open", (str(foreign), "r", 0)),
                            ("open", (str(foreign), "w", os.O_WRONLY | os.O_CREAT)),
                            ("sqlite3.connect", (str(foreign),)),
                            ("os.mkdir", (str(foreign),)),
                            ("os.replace", (str(foreign), str(foreign)))):
            with self.assertRaises(PermissionError):
                ledger.audit(event, args)
        self.assertFalse(foreign.exists())
        self.assertEqual(ledger.report()["refused_total"], 5)

    def test_allowed_reads_do_not_admit_source_writes(self):
        ledger = self.ledger()
        fixture = Path(os.environ["HERMES_HOME"]) / "owned-only.sqlite3"
        ledger.audit("open", (str(CARRIER.SCRIPT), "r", 0))
        ledger.audit("open", (str(fixture), "w", os.O_WRONLY | os.O_CREAT))
        ledger.audit("sqlite3.connect", (str(fixture),))
        with self.assertRaises(PermissionError):
            ledger.audit("open", (str(CARRIER.SCRIPT), "w", os.O_WRONLY | os.O_CREAT))
        self.assertEqual(ledger.report()["refused_total"], 1)

    def test_profile_boundary_keeps_only_primitive_frame_id_and_restores(self):
        ledger = self.ledger()
        observer = CARRIER.PhaseObserver(ledger, CARRIER.SOURCE)
        frame = sys._getframe()
        try:
            key = (os.path.normcase(frame.f_code.co_filename), frame.f_code.co_name)
            observer.targets[key] = "bootstrap.unit-observer-boundary"
            with ledger.phase("register"):
                observer(frame, "call", None)
                self.assertEqual(ledger.phase_path.get()[-1], "bootstrap.unit-observer-boundary")
                self.assertIs(type(observer.stack[0][0]), int)
                self.assertIs(type(observer.stack[0][1]), tuple)
                observer(frame, "return", None)
                self.assertEqual(ledger.phase_path.get(), ("setup", "register"))
            self.assertEqual(observer.stack, [])
        finally:
            del frame

    def test_functional_pass_never_erases_denials_exit_or_missing_capture(self):
        state = {"capture_complete": True, "ownership_complete": True,
                 "deadline_state": "completed_before_deadline", "exit_code": 0}
        cases = [{"id": name, "outcome": "passed"} for name in CARRIER.COMPONENT_CASES]
        payload = {"schema": CARRIER.SCHEMA, "cases": cases, "tests": CARRIER.summarize(cases),
                   "audit": {"refused_total": 26, "diagnostic_failures": 0,
                             "counts": [{"count": 26, "refused": True}]},
                   "alive_threads": [], "unit": {"total": 9, "failed": 0, "errors": 0}}
        self.assertEqual(CARRIER.qualify(state, payload, True), ("blocked", "admission"))
        payload["audit"]["refused_total"] = 0
        payload["audit"]["counts"] = []
        self.assertEqual(CARRIER.qualify(state, payload, True), ("passed", "none"))
        self.assertEqual(CARRIER.qualify(dict(state, exit_code=1), payload, True), ("failed", "fixture"))
        self.assertEqual(CARRIER.qualify(dict(state, capture_complete=False), payload, True), ("unknown", "capture"))
        self.assertEqual(CARRIER.qualify(state, None, True), ("unknown", "capture"))
        self.assertEqual(CARRIER.qualify(state, payload, False), ("blocked", "admission"))
        payload["audit"]["diagnostic_failures"] = 1
        self.assertEqual(CARRIER.qualify(state, payload, True), ("blocked", "admission"))

    def test_case_counts_have_exact_unique_ids_not_projection_totals(self):
        cases = [{"id": "a", "outcome": "passed"}, {"id": "b", "outcome": "error"},
                 {"id": "c", "outcome": "skipped"}]
        report = CARRIER.summarize(cases)
        self.assertEqual((report["total"], report["passed"], report["errors"], report["skipped"]), (3, 1, 1, 1))
        self.assertEqual(report["case_ids"], ["a", "b", "c"])
        with self.assertRaises(ValueError):
            CARRIER.summarize(cases + [cases[0]])
        with self.assertRaises(ValueError):
            CARRIER.summarize([{"id": "a", "outcome": "nativegreen"}])

    def test_current_descriptor_is_source_rebind_not_native_permission(self):
        descriptor = json.loads((CARRIER.SOURCE / "docs/CURRENT_SDK_COMPONENT_CONTRACT.json").read_bytes())
        self.assertEqual(descriptor["schema"], CARRIER.SCHEMA)
        self.assertEqual(descriptor["source_root"], str(CARRIER.SOURCE))
        self.assertFalse(descriptor["permission"]["native_admission"])
        self.assertIsNone(descriptor["permission"]["full_bootstrap"])
        self.assertEqual(descriptor["bootstrap_policy"]["process_creation_allowance"], 0)
        self.assertFalse(descriptor["bootstrap_policy"]["preload_Core_before_audit"])
        self.assertEqual(descriptor["bootstrap_policy"]["refusal_handling"], "retain_and_block_even_if_caught")
        self.assertEqual(descriptor["historical_refusal"]["counts"], {"socket.gethostname": 1, "open": 24, "subprocess.Popen": 1})
