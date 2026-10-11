"""Carrier unit package: no root conftest, SDK fakes or native subprocesses.

Load with the existing stdlib unittest API and an explicit CARRIER binding for
UNIT-only execution. Do not invoke worker: it also runs the actual SDK component.
Unit-injected audit calls and authored supervisor states test tooling, not Core
or an actual supervisor cleanup failure.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
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
                 "deadline_state": "completed_before_deadline", "exit_code": 0,
                 "errors": [], "primary_error": None}
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
        self.assertEqual(CARRIER.qualify(dict(state, ownership_complete=False), payload, True), ("unknown", "capture"))
        self.assertEqual(CARRIER.qualify(dict(state, deadline_state="expired"), payload, True), ("unknown", "capture"))
        self.assertEqual(CARRIER.qualify(state, None, True), ("unknown", "capture"))
        self.assertEqual(CARRIER.qualify(state, payload, False), ("blocked", "admission"))
        payload["audit"]["diagnostic_failures"] = 1
        self.assertEqual(CARRIER.qualify(state, payload, True), ("blocked", "admission"))

    def qualification_fixture(self):
        # Authored evidence at the qualifier seam; no actual SDK/supervisor run.
        state = {"capture_complete": True, "ownership_complete": True,
                 "deadline_state": "completed_before_deadline", "exit_code": 0,
                 "errors": [], "primary_error": None}
        cases = [{"id": name, "outcome": "passed"} for name in CARRIER.COMPONENT_CASES]
        payload = {"schema": CARRIER.SCHEMA, "cases": cases, "tests": CARRIER.summarize(cases),
                   "audit": {"refused_total": 0, "diagnostic_failures": 0, "counts": []},
                   "alive_threads": [], "unit": {"total": 1, "failed": 0, "errors": 0}}
        return state, payload

    def assert_supervisor_refusal(self, state, expected):
        _, payload = self.qualification_fixture()
        before_state, before_payload = deepcopy(state), deepcopy(payload)
        self.assertEqual(CARRIER.qualify(state, payload, True), expected)
        # A refusal must preserve the ledger/primary and raw child evidence.
        self.assertEqual(state, before_state)
        self.assertEqual(payload, before_payload)

    def test_supervisor_explicit_empty_errors_and_null_primary_are_healthy(self):
        state, payload = self.qualification_fixture()
        before_state, before_payload = deepcopy(state), deepcopy(payload)
        self.assertEqual(CARRIER.qualify(state, payload, True), ("passed", "none"))
        self.assertEqual(state, before_state)
        self.assertEqual(payload, before_payload)

    def test_supervisor_errors_only_refuse_complete_child_success(self):
        state, _ = self.qualification_fixture()
        state["errors"] = ["cleanup_log_stdout_OSError"]
        self.assert_supervisor_refusal(state, ("failed", "harness"))

    def test_supervisor_primary_only_refuses_complete_child_success(self):
        state, _ = self.qualification_fixture()
        state["primary_error"] = "cleanup_pipe_stdout_OSError"
        self.assert_supervisor_refusal(state, ("failed", "harness"))

    def test_supervisor_errors_and_primary_refuse_complete_child_success(self):
        state, _ = self.qualification_fixture()
        state["errors"] = ["cleanup_log_stdout_OSError", "cleanup_pipe_stdout_OSError"]
        state["primary_error"] = state["errors"][0]
        self.assert_supervisor_refusal(state, ("failed", "harness"))

    def test_supervisor_malformed_errors_never_count_as_empty_list(self):
        # Each falsey/non-list shape must refuse; these are variants, not subtests.
        for errors in (None, "", "cleanup_log_stdout_OSError", {}, (), False, 0,
                       {"cleanup_log_stdout_OSError": 1}):
            state, _ = self.qualification_fixture()
            state["errors"] = errors
            self.assert_supervisor_refusal(state, ("unknown", "capture"))

    def test_supervisor_nonnull_primary_never_counts_as_null(self):
        for primary in ("", False, 0, [], {}, (), ["cleanup_pipe_stdout_OSError"]):
            state, _ = self.qualification_fixture()
            state["primary_error"] = primary
            self.assert_supervisor_refusal(state, ("failed", "harness"))

    def test_supervisor_missing_errors_refuses_complete_child_success(self):
        state, _ = self.qualification_fixture()
        del state["errors"]
        self.assert_supervisor_refusal(state, ("unknown", "capture"))

    def test_supervisor_missing_primary_refuses_complete_child_success(self):
        state, _ = self.qualification_fixture()
        del state["primary_error"]
        self.assert_supervisor_refusal(state, ("unknown", "capture"))

    def test_supervisor_missing_both_health_fields_refuses_complete_child_success(self):
        state, _ = self.qualification_fixture()
        del state["errors"], state["primary_error"]
        self.assert_supervisor_refusal(state, ("unknown", "capture"))

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
        derivative = descriptor["current_metadata_derivative"]
        self.assertEqual(derivative["kind"], "current_source_metadata_only_UNIT")
        self.assertTrue(derivative["historical_execution_unchanged"])
        self.assertFalse(derivative["new_component_or_native_admission"])
        self.assertEqual(descriptor["qualifier_contract"]["healthy_supervisor"],
                         {"errors": [], "primary_error": None, "both_fields_required": True})
        bindings = {row["path"]: row["sha256"] for row in descriptor["source_bindings"]}
        for path in (CARRIER.SCRIPT, CARRIER.SOURCE / "tests/ci_owned/test_current_sdk_bootstrap.py"):
            self.assertEqual(bindings[str(path)], CARRIER.sha(path))
        self.assertNotIn(str(CARRIER.SOURCE / "docs/CURRENT_SDK_COMPONENT_CONTRACT.json"), bindings)
