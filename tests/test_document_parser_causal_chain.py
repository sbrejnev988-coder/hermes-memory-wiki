"""PDF-CHAIN01: observed causal projection; original whole67 packet retained.

Reuse the shipped suite/record seams and bounded reporter, not inherited tests.
Genuine PDF/OCR/SDK/SQL/native execution is outside this SOURCE contract.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest

INPUTS = globals().get("DEVTOOLS_INPUTS", {})
COMPOSITION_PATH = Path(INPUTS.get("test_document_parser_veto_composition.py",
                                  Path(__file__).with_name("test_document_parser_veto_composition.py")))


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


_spec = importlib.util.spec_from_file_location("parser_causal_composition_source", str(COMPOSITION_PATH))
composition = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = composition
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        composition.__dict__[_name] = globals()[_name]
exec(compile(read_source(COMPOSITION_PATH), str(COMPOSITION_PATH), "exec", dont_inherit=True), composition.__dict__)
cleanup, terminal, review = composition.cleanup, composition.terminal, composition.review
OBSERVATIONS = []


class IdentityOnlyError(cleanup.UnprintableError):
    def __eq__(self, other):
        raise AssertionError("foreign exception equality must not run")

    def __hash__(self):
        raise AssertionError("foreign exception hash must not run")


class IdentityOnlyFatal(cleanup.Cancellation):
    def __eq__(self, other):
        raise AssertionError("foreign fatal equality must not run")

    def __hash__(self):
        raise AssertionError("foreign fatal hash must not run")


class CausalChainSourceTests(unittest.TestCase):
    def setUp(self):
        self.e = review.peer.load_source(review.peer.EXTRACTOR, "document_extractors")

    def assert_chain(self, error, expected):
        self.assertEqual([id(node) for node in composition.context_nodes(error)], [id(node) for node in expected])

    def test_chain_final_cleanup_is_selected_fatal_with_explicit_causes(self):
        for veto in (False, True):
            for with_body in (False, True):
                first, second, fatal = IdentityOnlyError(), IdentityOnlyError(), IdentityOnlyFatal()
                primary = IdentityOnlyError() if with_body else None
                errors = [first, second, fatal, *([primary] if with_body else [])]
                causes = [ValueError("authored explicit cause") for _ in errors]
                for error, cause in zip(errors, causes):
                    error.__cause__ = cause
                seam = composition.reader_records(self.e, [review.PageRecords(""),
                    terminal.withheld_page("table_failure") if veto else cleanup.healthy_page()],
                    faults=(first, second, fatal), body_error=primary)
                with self.assertRaises(cleanup.Cancellation) as caught:
                    seam.run()
                self.assertIs(caught.exception, fatal)
                self.assertIs(seam.errors[0], fatal)
                self.assert_chain(fatal, [fatal, second, first, *([primary] if with_body else [])])
                self.assertEqual([id(error) for error in seam.stack.cleanup_errors], [id(first), id(second), id(fatal)])
                for error, cause in zip(errors, causes):
                    self.assertIs(error.__cause__, cause)
                    self.assertIsNone(cause.__context__)
                self.assertEqual(seam.calls, ["pymupdf"])
                self.assertEqual(seam.cleanups, ["reader", "stream", "doc"])
                self.assertFalse(any(seam.closed.values()))
                self.assertEqual(seam.stack.diagnostics, {"cleanup": "unknown", "ownership": "unknown"})
                self.assertEqual(len(seam.stack._exit_callbacks), 0)
        OBSERVATIONS.append({"case": self._testMethodName, "final_selected_fatal": True, "reverse_LIFO_body_tail_and_explicit_causes": True})

    def test_chain_repeated_observed_identity_keeps_occurrence_ledger_without_cycle(self):
        for arrangement in ("ordinary_repeated", "fatal_repeated", "ordinary_prefix"):
            ordinary, fatal = IdentityOnlyError(), IdentityOnlyFatal()
            faults = {"ordinary_repeated": (ordinary, fatal, ordinary),
                      "fatal_repeated": (fatal, ordinary, fatal),
                      "ordinary_prefix": (ordinary, ordinary, fatal)}[arrangement]
            # The body object itself is raised again in two distinct callbacks.
            primary = ordinary if arrangement == "ordinary_repeated" else None
            seam = composition.reader_records(self.e, [review.PageRecords(""), terminal.withheld_page("table_failure")],
                                               faults=faults, body_error=primary)
            with self.assertRaises(cleanup.Cancellation) as caught:
                seam.run()
            self.assertIs(caught.exception, fatal)
            self.assert_chain(fatal, [fatal, ordinary])
            self.assertEqual([id(error) for error in seam.stack.cleanup_errors], [id(error) for error in faults])
            self.assertEqual(seam.cleanups, ["reader", "stream", "doc"])
            self.assertFalse(any(seam.closed.values()))
            self.assertEqual(len(seam.stack._exit_callbacks), 0)
            self.assertEqual(seam.stack.diagnostics, {"cleanup": "unknown", "ownership": "unknown"})
            self.assertIsNone(ordinary.__cause__)
            self.assertIsNone(fatal.__cause__)
        OBSERVATIONS.append({"case": self._testMethodName, "identity_only_dedup": True, "private_repeated_occurrences_retained": True})

    def test_chain_suppressed_cleanup_still_projects_body_and_drains(self):
        for kind in ("absent", "ordinary", "fatal"):
            primary = None if kind == "absent" else (IdentityOnlyError() if kind == "ordinary" else IdentityOnlyFatal())
            fatal, events = IdentityOnlyFatal(), []
            owner = self.e._PdfReaderOwner(self.e._PdfOutput(self.e.effective_extraction_options({})))

            def close_last():
                events.append("last")

            def suppress(exc_type, error, traceback):
                events.append("suppress")
                self.assertIs(error, fatal)
                return True

            def close_fatal():
                events.append("fatal")
                raise fatal

            owner.callback(close_last)
            owner.push(suppress)
            owner.callback(close_fatal)
            selected = primary if kind == "fatal" else fatal
            with self.assertRaises(cleanup.Cancellation) as caught:
                with owner:
                    if primary is not None:
                        raise primary
            self.assertIs(caught.exception, selected)
            expected = [primary, fatal] if kind == "fatal" else [fatal, *([primary] if primary is not None else [])]
            self.assert_chain(selected, expected)
            self.assertEqual(events, ["fatal", "suppress", "last"])
            self.assertEqual([id(error) for error in owner.cleanup_errors], [id(fatal)])
            self.assertEqual(len(owner._exit_callbacks), 0)
            self.assertEqual(owner.diagnostics, {"cleanup": "unknown", "ownership": "unknown"})
        OBSERVATIONS.append({"case": self._testMethodName, "suppression_cannot_erase_fatal_or_observed_body": True})

    def test_chain_healthy_and_ordinary_inverse_preserve_original_policy(self):
        for veto in (False, True):
            seam = composition.reader_records(self.e, [review.PageRecords(""),
                terminal.withheld_page("table_failure") if veto else cleanup.healthy_page()])
            result = seam.run()
            self.assertEqual(seam.cleanups, ["reader", "stream", "doc"])
            self.assertTrue(all(seam.closed.values()))
            self.assertEqual(seam.stack.cleanup_errors, [])
            self.assertEqual(seam.stack.diagnostics, {"cleanup": "complete", "ownership": "complete"})
            self.assertNotIn(terminal.CANARY, json.dumps(self.e.asdict(result)))
            self.assertNotIn(terminal.CANARY, json.dumps(result.to_dict()))
            primary, first, second, last = (IdentityOnlyError() for _ in range(4))
            owner = self.e._PdfReaderOwner(self.e._PdfOutput(self.e.effective_extraction_options({})))
            if veto:
                owner.output.fallback_veto = "incomplete_table_context"
            events = []

            def close(label, error):
                events.append(label)
                raise error

            for label, error in (("doc", last), ("stream", second), ("reader", first)):
                owner.callback(close, label, error)
            with self.assertRaises(self.e._PdfPrivacyVetoError if veto else IdentityOnlyError) as caught:
                with owner:
                    raise primary
            error = caught.exception
            if veto:
                self.assertIs(error.primary_error, primary)
                self.assertIs(error.cleanup_error, last)
                self.assertIs(error.__cause__, last)
                self.assertEqual(error.diagnostics["ownership"], "unknown")
            else:
                self.assertIs(error, last)
            self.assert_chain(last, [last, second, first, primary])
            self.assertEqual(events, ["reader", "stream", "doc"])
            self.assertEqual([id(error) for error in owner.cleanup_errors], [id(first), id(second), id(last)])
            self.assertEqual(len(owner._exit_callbacks), 0)
            self.assertEqual(owner.diagnostics, {"cleanup": "unknown", "ownership": "unknown"})
        OBSERVATIONS.append({"case": self._testMethodName, "healthy_and_ordinary_veto_nonveto_inverses": True})

    def test_chain_identity_invalidates_previous_3_1_4(self):
        previous = review.clone_function(self.e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.4")
        path = Path("fixture.pdf")
        self.assertEqual(self.e.EXTRACTOR_VERSION, "3.1.8")
        self.assertEqual(self.e.SECRET_POLICY_VERSION, "3.0.0")
        for options in ({}, {"ocr": True}, {"pdf_parser": "pypdf"}):
            current = self.e.extraction_options_fingerprint(path, options)
            self.assertNotEqual(current, previous(path, options))
            self.assertEqual(current, self.e.extraction_options_fingerprint(path, self.e.effective_extraction_options(options)))
        self.assertEqual(self.e.ExtractedDocument("none", "application/pdf", "Fixture", []).to_dict()["extractor_version"], "3.1.8")


def packet_suite():
    return unittest.TestSuite([composition.packet_suite(),
                              unittest.defaultTestLoader.loadTestsFromTestCase(CausalChainSourceTests)])


def metadata_preflight():
    old_ids = composition.metadata_preflight()
    ids = old_ids + [case._testMethodName for case in unittest.defaultTestLoader.loadTestsFromTestCase(CausalChainSourceTests)]
    assert len(ids) == len(set(ids))
    assert OBSERVATIONS == []
    return ids


if __name__ == "__main__" and "devtools_case_started" in globals():
    peer_tree = ast.parse(read_source(review.PEER_PATH))
    reporter = next(n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(review.PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "terminal_compositions": terminal.OBSERVATIONS, "cleanup_compositions": cleanup.OBSERVATIONS,
        "pdf_compositions": composition.OBSERVATIONS, "causal_compositions": OBSERVATIONS,
        "baseline_binding": {"commit": composition.BASELINE_COMMIT, "blob": composition.BASELINE_BLOB,
            "sha256": composition.BASELINE_SHA256, "bytes": 95837, "role": "exact_expected_defect_not_healthy_baseline"},
        "qualification": "SOURCE actual owner/ExitStack/emitter/readers/selection/finish/dispatcher/redactor/serializer; original whole roster/setup/cleanup plus causal projection controls; authored records/transport; genuine engine/SDK/SQL/native NOT_RUN"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(packet_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
