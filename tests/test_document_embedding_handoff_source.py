"""Будущий standalone SOURCE packet: ingest embedding handoff, не SQL/provider.

Импорт/collection инертны: peer и product читаются/исполняются только после main
admission под исходным source_bootstrap fence. Оба __test__ = False исключают
обычный pytest discovery по стандартному контракту; actual collection NOT_RUN.
Только полный source CodeType helper клонируется с одним dispatch observer.
Observer не writer/ACL/guard/SDK; настоящий embed_pending_documents НЕ вызывается.
Ingest callers, транзакции и output guard проверяются только STATIC.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest

__test__ = False

CASE_IDS = (
    "test_off_and_default_off_never_dispatch",
    "test_explicit_true_handoff_once_preserves_result_identity",
    "test_actual_env_and_profile_default_precedence",
    "test_exact_source_payload_and_limit_defaults",
    "test_typed_callback_outcomes_are_not_completed",
    "test_raised_primary_identity_is_preserved",
    "test_success_callers_after_transaction_before_guard_STATIC",
    "test_inverse_delta_and_unrelated_preservation_STATIC",
)
ENV_KEY = "MEMORY_WIKI_DOCUMENT_EMBED_ON_INGEST"
BASELINE_HEAD = "def9c891e0fb408804055d958ab24d952f557db2"
BASELINE_GRAPH_SHA256 = "b77de64465eb03438e8f5e5253369310763ad11d248eb7c995808caf5cae3535"
BASELINE_INGEST_AST_SHA256 = "6305b74d055e934855f97fdbb85bb579e7af7f1a57d9136eceaa8a39aa52d5a2"
BASELINE_OTHER_AST_SHA256 = "41cb1a023bb1032d9d24ffdcaade033b5ee7a59f13450ed069e34a401523d6f9"
BASELINE_TX_AST_SHA256 = (
    "24f666ab927e397846a6fb3f16b45f96ce0ac221efa37874c31564adfd601983",
    "2d9f7215be7b13207f762fc4c88fd0faadfd54545541eec49ab34e7fc4910465",
    "40499e4ef2b24cc31fd4a203c0ed74e82a458f78599aceb1ea30e3d5bc047986",
)
LEGACY_DISPATCH = '''if bool(args.get("embed", _env_bool("MEMORY_WIKI_DOCUMENT_EMBED_ON_INGEST", False))):
    result["embedding"] = embed_pending_documents(provider, {"source_id": source_id, "limit": int(args.get("embed_limit") or 200)})
'''


class DocumentEmbeddingHandoffSourceTests(unittest.TestCase):
    __test__ = False
    _admitted = False

    @classmethod
    def setUpClass(cls):
        if not cls._admitted:
            raise RuntimeError("standalone_main_admission_required_before_source_load")
        cls.inputs = globals()["DEVTOOLS_INPUTS"]
        cls.scratch = Path(globals()["DEVTOOLS_SCRATCH"])
        cls.observations = {}
        names = ("spreadsheet_formulas", "document_extractors", "guard", "document_knowledge_graph")
        if any(name in sys.modules for name in names):
            raise RuntimeError("fresh_source_namespaces_required")
        cls.addClassCleanup(cls.peer.MODULES.clear)
        for name in names:
            cls.addClassCleanup(sys.modules.pop, name, None)
        cls.e = cls.peer.load_source(cls.peer.EXTRACTOR, "document_extractors")
        cls.guard = cls.peer.load_source(Path(cls.inputs["guard.py"]), "guard")
        cls.g = cls.peer.load_source(Path(cls.inputs["document_knowledge_graph.py"]),
                                     "document_knowledge_graph")
        if cls.e.evaluate_cells is not sys.modules["spreadsheet_formulas"].evaluate_cells:
            raise RuntimeError("real_bound_formula_helper_required")
        if cls.g._sanitize_untrusted_text is not cls.guard.sanitize_context_text:
            raise RuntimeError("real_bound_guard_required")
        if cls.g._sanitize_extracted_json is not cls.e.sanitize_json:
            raise RuntimeError("real_bound_extractor_required")
        cls.original_dispatch = staticmethod(cls.g.embed_pending_documents)
        # Whole-module AST is read through the unchanged bound peer reader.
        cls.tree = ast.parse(cls.peer.read_source(Path(cls.inputs["document_knowledge_graph.py"])))

    def setUp(self):
        saved = {ENV_KEY: os.environ[ENV_KEY]} if ENV_KEY in os.environ else {}
        def restore():
            os.environ.pop(ENV_KEY, None)
            os.environ.update(saved)
        self.addCleanup(restore)
        os.environ.pop(ENV_KEY, None)
        self.assertIsNone(self.g._DOCUMENT_PROFILE_SCOPE.get())
        self.observations[self._testMethodName] = {"cleanup_complete": False}
        self.addCleanup(self.observations[self._testMethodName].__setitem__, "cleanup_complete", True)
        # Opaque dispatch identity only; no provider methods or fake authority.
        self.provider = object()
        self.source_id = " docsrc_synthetic_Ё "

    def tearDown(self):
        self.assertIs(self.g.embed_pending_documents, self.original_dispatch)
        self.assertIsNone(self.g._DOCUMENT_PROFILE_SCOPE.get())

    def handoff_observer(self, outcome=None, primary=None):
        calls = []
        def observe(provider, payload):
            calls.append((provider, payload))
            if primary is not None:
                raise primary
            return outcome
        original = self.g._embed_ingest_result
        namespace = dict(original.__globals__)
        namespace["embed_pending_documents"] = observe
        # No AST-sliced body or wrapper implementation: this is the actual
        # helper CodeType from the complete graph executed by peer.load_source.
        clone = types.FunctionType(original.__code__, namespace, original.__name__,
                                   original.__defaults__, original.__closure__)
        self.assertIs(original.__globals__, self.g.__dict__)
        self.assertIs(clone.__code__, original.__code__)
        self.assertEqual(set(namespace), set(original.__globals__))
        self.assertEqual([key for key in namespace if namespace[key] is not original.__globals__[key]],
                         ["embed_pending_documents"])
        self.assertIs(namespace["_env_bool"], self.g._env_bool)
        self.assertIs(self.g.embed_pending_documents, self.original_dispatch)
        return clone, calls

    def ingest_result(self, status="unchanged"):
        result = {"status": status, "extractor_status": "ok", "content_indexed": True,
                  "source_id": self.source_id, "revision_id": "docrev_synthetic",
                  "path": "not-opened.txt", "file_hash": "synthetic_hash", "units": 3}
        if status == "unchanged":
            result["file_identity_updated"] = False
        elif status == "scope_updated":
            result.update(archived_claims=2, embedding_pending=3)
        else:
            result.update(parser="stdlib-text", chunks=3, edges=0, archived_claims=0,
                          warnings=[], embedding_pending=3, security_status="safe",
                          secret_redactions=0, secret_categories={})
        return result

    def test_off_and_default_off_never_dispatch(self):
        handoff, calls = self.handoff_observer({"status": "must_not_be_returned"})
        for status in ("unchanged", "scope_updated", "indexed"):
            for args in ({}, {"embed": False}, {"embed": None}, {"embed": 0}, {"embed": ""}):
                result = self.ingest_result(status)
                before = copy.deepcopy(result)
                self.assertIs(handoff(self.provider, args, self.source_id, result), result)
                self.assertEqual(result, before)
                self.assertNotIn("embedding", result)
        os.environ[ENV_KEY] = "1"
        result = self.ingest_result()
        self.assertIs(handoff(self.provider, {"embed": False}, self.source_id, result), result)
        self.assertNotIn("embedding", result)
        self.assertEqual(calls, [])

    def test_explicit_true_handoff_once_preserves_result_identity(self):
        for status in ("unchanged", "scope_updated", "indexed"):
            outcome = {"status": "pending", "remaining": 3, "retryable": True}
            handoff, calls = self.handoff_observer(outcome)
            result = self.ingest_result(status)
            before = dict(result)
            self.assertIs(handoff(self.provider, {"embed": True}, self.source_id, result), result)
            self.assertEqual(calls, [(self.provider, {"source_id": self.source_id, "limit": 200})])
            self.assertIs(result["embedding"], outcome)
            self.assertEqual(set(result), set(before) | {"embedding"})
            for key, value in before.items():
                self.assertIs(result[key], value)
            self.assertEqual(result["status"], status)

    def test_actual_env_and_profile_default_precedence(self):
        # Actual _env_bool -> _document_env -> ContextVar/os.environ; no reader
        # replacement and no _document_profile_scope/.env/profile filesystem I/O.
        for value, wanted in (("1", True), ("yes", True), ("0", False), (" off ", False)):
            os.environ[ENV_KEY] = value
            handoff, calls = self.handoff_observer({"status": "pending"})
            result = self.ingest_result()
            self.assertIs(handoff(self.provider, {}, self.source_id, result), result)
            self.assertEqual(len(calls), int(wanted))
            self.assertEqual("embedding" in result, wanted)
        scenarios = (
            ("1", True, {}, {}, False),
            ("1", True, {ENV_KEY: "off"}, {}, False),
            ("0", True, {ENV_KEY: "1"}, {}, True),
            ("0", True, {ENV_KEY: "1"}, {"embed": False}, False),
            ("1", True, {ENV_KEY: "off"}, {"embed": True}, True),
            ("1", False, {ENV_KEY: "off"}, {}, True),
        )
        for ambient, strict, settings, args, wanted in scenarios:
            os.environ[ENV_KEY] = ambient
            token = self.g._DOCUMENT_PROFILE_SCOPE.set({
                "home": self.scratch / "home", "strict": strict, "settings": settings})
            try:
                handoff, calls = self.handoff_observer({"status": "pending"})
                result = self.ingest_result()
                self.assertIs(handoff(self.provider, args, self.source_id, result), result)
                self.assertEqual(len(calls), int(wanted))
                self.assertEqual("embedding" in result, wanted)
            finally:
                self.g._DOCUMENT_PROFILE_SCOPE.reset(token)

    def test_exact_source_payload_and_limit_defaults(self):
        variants = (({}, 200), ({"embed_limit": None}, 200), ({"embed_limit": 0}, 200),
                    ({"embed_limit": ""}, 200), ({"embed_limit": 7}, 7),
                    ({"embed_limit": "19"}, 19), ({"embed_limit": -2}, -2))
        for extra, wanted in variants:
            args = {"embed": True, "source_id": "ignored_request_source", "scope_id": "ignored_scope",
                    "repository_id": "ignored_repository", "limit": 999, **extra}
            before = dict(args)
            handoff, calls = self.handoff_observer({"status": "pending"})
            result = self.ingest_result()
            handoff(self.provider, args, self.source_id, result)
            self.assertEqual(args, before)
            self.assertEqual(calls, [(self.provider, {"source_id": self.source_id, "limit": wanted})])
            self.assertIs(calls[0][0], self.provider)
            self.assertIs(calls[0][1]["source_id"], self.source_id)
            self.assertIs(type(calls[0][1]["limit"]), int)
        # Preserve legacy bool(value), not a newly invented string parser.
        handoff, calls = self.handoff_observer({"status": "pending"})
        handoff(self.provider, {"embed": "false"}, self.source_id, self.ingest_result())
        self.assertEqual(len(calls), 1)
        handoff, calls = self.handoff_observer()
        result = self.ingest_result()
        before = copy.deepcopy(result)
        with self.assertRaises(ValueError):
            handoff(self.provider, {"embed": True, "embed_limit": "invalid"}, self.source_id, result)
        self.assertEqual(calls, [])
        self.assertEqual(result, before)

    def test_typed_callback_outcomes_are_not_completed(self):
        # Authored callback-shaped data, not observed SQL/claim/vector outcomes.
        outcomes = (
            {"status": "pending", "remaining": 2, "runnable_remaining": 2, "retryable": True},
            {"status": "blocked", "blocked_remaining": 2, "retryable": False,
             "skipped_reasons": {"claim_not_active_or_visible": 2}},
            {"status": "retry", "failed": 1, "retryable": True,
             "errors": [{"chunk_id": "synthetic_chunk", "error": "PermissionError"}]},
            {"status": "pending_commit", "commit_pending": True, "created": 1},
            {"status": "error", "errors": [{"error": "synthetic_callback_refusal"}]},
            {"status": "completed", "remaining": 0, "retryable": False},
        )
        for outcome in outcomes:
            handoff, calls = self.handoff_observer(outcome)
            result = self.ingest_result("scope_updated")
            before_result, before_outcome = dict(result), copy.deepcopy(outcome)
            self.assertIs(handoff(self.provider, {"embed": True}, self.source_id, result), result)
            self.assertEqual(len(calls), 1)
            self.assertIs(result["embedding"], outcome)
            self.assertEqual(outcome, before_outcome)
            self.assertEqual(result, {**before_result, "embedding": outcome})
        # Even a falsey callback return is retained verbatim, not promoted.
        for outcome in (None, False, ""):
            handoff, calls = self.handoff_observer(outcome)
            result = self.ingest_result()
            handoff(self.provider, {"embed": True}, self.source_id, result)
            self.assertEqual(len(calls), 1)
            self.assertIs(result["embedding"], outcome)

    def test_raised_primary_identity_is_preserved(self):
        for primary in (PermissionError("synthetic_denial"), RuntimeError("synthetic_retry"),
                        KeyboardInterrupt("synthetic_cancellation")):
            handoff, calls = self.handoff_observer(primary=primary)
            result = self.ingest_result()
            prior = {"status": "prior_embedding"}
            result["embedding"] = prior
            before = dict(result)
            with self.assertRaises(type(primary)) as caught:
                handoff(self.provider, {"embed": True}, self.source_id, result)
            self.assertIs(caught.exception, primary)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result, before)
            self.assertIs(result["embedding"], prior)

    def test_success_callers_after_transaction_before_guard_STATIC(self):
        functions = {n.name: n for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        ingest = functions["ingest_document"]
        helper_call = ast.parse("_embed_ingest_result(provider, args, source_id, result)").body[0]
        guard_return = ast.parse("return _guard_document_output(result, provider=provider)").body[0]
        found = []
        for branch in (n for n in ingest.body if isinstance(n, ast.If)):
            assignments = [n for n in branch.body if isinstance(n, ast.Assign)
                           and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                           and n.targets[0].id == "result" and isinstance(n.value, ast.Dict)]
            if not assignments:
                continue
            self.assertEqual(len(assignments), 1)
            assignment = assignments[0]
            fields = {k.value: v for k, v in zip(assignment.value.keys, assignment.value.values)
                      if isinstance(k, ast.Constant)}
            status = fields["status"].value
            self.assertIn(status, ("unchanged", "scope_updated"))
            found.append(status)
            self.assertIs(branch.body[-3], assignment)
            self.assertEqual(ast.dump(branch.body[-2]), ast.dump(helper_call))
            self.assertEqual(ast.dump(branch.body[-1]), ast.dump(guard_return))
            transactions = [n for n in branch.body if isinstance(n, ast.With)]
            self.assertEqual(len(transactions), 1)
            self.assertLess(transactions[0].end_lineno, assignment.lineno)
            self.assertLess(assignment.lineno, branch.body[-2].lineno)
            self.assertLess(branch.body[-2].lineno, branch.body[-1].lineno)
        self.assertEqual(found, ["unchanged", "scope_updated"])
        self.assertIsInstance(ingest.body[-3], ast.With)
        self.assertEqual(ast.dump(ingest.body[-2]), ast.dump(helper_call))
        self.assertEqual(ast.dump(ingest.body[-1]), ast.dump(guard_return))
        self.assertLess(ingest.body[-3].end_lineno, ingest.body[-2].lineno)
        calls = [n for n in ast.walk(ingest) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_embed_ingest_result"]
        self.assertEqual(len(calls), 3)
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                             and n.func.id == "embed_pending_documents" for n in ast.walk(ingest)))
        transactions = sorted([n for n in ast.walk(ingest) if isinstance(n, ast.With)
            and any(isinstance(item.context_expr, ast.Call) and isinstance(item.context_expr.func, ast.Name)
                    and item.context_expr.func.id == "_ingest_transaction" for item in n.items)],
            key=lambda n: n.lineno)
        self.assertEqual(tuple(hashlib.sha256(ast.dump(n, include_attributes=False).encode("utf-8")).hexdigest()
                               for n in transactions), BASELINE_TX_AST_SHA256)
        self.observations[self._testMethodName]["qualification"] = "STATIC; ingest/SQL/transaction/guard execution NOT_RUN"

    def test_inverse_delta_and_unrelated_preservation_STATIC(self):
        functions = {n.name: n for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        restored = copy.deepcopy(functions["ingest_document"])
        restored_statuses = []
        for branch in (n for n in restored.body if isinstance(n, ast.If)):
            if len(branch.body) < 3 or not isinstance(branch.body[-3], ast.Assign):
                continue
            assignment = branch.body[-3]
            if not isinstance(assignment.value, ast.Dict):
                continue
            fields = {k.value: v for k, v in zip(assignment.value.keys, assignment.value.values)
                      if isinstance(k, ast.Constant)}
            if not isinstance(fields.get("status"), ast.Constant):
                continue
            status = fields["status"].value
            self.assertIn(status, ("unchanged", "scope_updated"))
            original_return = copy.deepcopy(branch.body[-1])
            original_return.value.args = [assignment.value]
            branch.body[-3:] = [original_return]
            restored_statuses.append(status)
        self.assertEqual(restored_statuses, ["unchanged", "scope_updated"])
        restored.body[-2] = ast.parse(LEGACY_DISPATCH).body[0]
        digest = hashlib.sha256(ast.dump(restored, include_attributes=False).encode("utf-8")).hexdigest()
        self.assertEqual(digest, BASELINE_INGEST_AST_SHA256)
        other = ast.Module(body=[n for n in self.tree.body if not (
            isinstance(n, ast.FunctionDef) and n.name in {"ingest_document", "_embed_ingest_result"})],
            type_ignores=[])
        digest = hashlib.sha256(ast.dump(other, include_attributes=False).encode("utf-8")).hexdigest()
        self.assertEqual(digest, BASELINE_OTHER_AST_SHA256)
        # The helper contains the exact old dispatch AST and a same-object return.
        helper = functions["_embed_ingest_result"]
        self.assertEqual(ast.dump(helper.body[-2]), ast.dump(ast.parse(LEGACY_DISPATCH).body[0]))
        self.assertEqual(ast.dump(helper.body[-1]), ast.dump(ast.parse("return result").body[0]))
        self.observations[self._testMethodName]["qualification"] = "STATIC inverse delta; all other graph AST, SQL, owner/ACL/privacy/cache/fingerprint/admission and scan unchanged"


def main():
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError("original_isolated_source_bootstrap_required")
    required = ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound", "devtools_case_started")
    if any(key not in globals() for key in required):
        raise RuntimeError("finite_source_admission_and_original_bound_reader_required")
    scratch = Path(DEVTOOLS_SCRATCH)
    if not scratch.is_absolute() or not scratch.is_dir():
        raise RuntimeError("own_absolute_scratch_required")
    for key in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HERMES_HOME", "TEMP", "TMP", "TMPDIR"):
        if not Path(os.environ[key]).is_relative_to(scratch):
            raise RuntimeError("sterile_child_environment_required")
    for key in ("document_knowledge_graph.py", "document_extractors.py", "spreadsheet_formulas.py",
                "guard.py", "test_document_parser_pdf_ocr.py"):
        if key not in DEVTOOLS_INPUTS:
            raise RuntimeError("complete_bound_peer_and_product_closure_required")
    name = "embedding_handoff_original_bound_peer"
    if name in sys.modules:
        raise RuntimeError("fresh_bound_peer_required")
    path = DEVTOOLS_INPUTS["test_document_parser_pdf_ocr.py"]
    before_path, before_env = list(sys.path), dict(os.environ)
    spec = importlib.util.spec_from_file_location(name, path)
    peer = importlib.util.module_from_spec(spec)
    # Required globals are supplied only after all main admission checks.
    for key in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
        peer.__dict__[key] = globals()[key]
    try:
        sys.modules[name] = peer
        raw = devtools_read_bound(path)
        exec(compile(raw, path, "exec", dont_inherit=True), peer.__dict__)
        DocumentEmbeddingHandoffSourceTests.peer = peer
        DocumentEmbeddingHandoffSourceTests._admitted = True
        reporters = [n for n in ast.walk(ast.parse(raw, filename=path))
                     if isinstance(n, ast.ClassDef) and n.name == "PacketResult"]
        if len(reporters) != 1:
            raise RuntimeError("unique_original_peer_reporter_required")
        namespace = {"__name__": "embedding_handoff_bound_reporter", "unittest": unittest,
                     "devtools_case_started": devtools_case_started}
        exec(compile(ast.Module(body=reporters, type_ignores=[]), path, "exec", dont_inherit=True), namespace)
        result = namespace["PacketResult"]()
        unittest.TestSuite(DocumentEmbeddingHandoffSourceTests(case) for case in CASE_IDS).run(result)
    finally:
        DocumentEmbeddingHandoffSourceTests._admitted = False
        sys.modules.pop(name, None)
    released = all(key not in sys.modules for key in (
        name, "spreadsheet_formulas", "document_extractors", "guard", "document_knowledge_graph"))
    observations = DocumentEmbeddingHandoffSourceTests.observations
    clean = released and sys.path == before_path and dict(os.environ) == before_env
    clean = clean and len(observations) == len(CASE_IDS) and all(v["cleanup_complete"] for v in observations.values())
    complete = [row["id"] for row in result.rows] == list(CASE_IDS)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "observations": observations, "lifecycle": {"source_modules_released": released,
        "environment_and_path_restored": sys.path == before_path and dict(os.environ) == before_env},
        "qualification": "6 full-source helper callable mains with dispatch observer +2 STATIC mains; actual embed_pending_documents, ingest/scan/SQL/SDK/native/vector/pytest/full/installed NOT_RUN"},
        separators=(",", ":")))
    return 0 if result.wasSuccessful() and clean and complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
