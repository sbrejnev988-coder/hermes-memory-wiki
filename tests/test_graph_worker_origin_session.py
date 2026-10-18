"""Self-contained stdlib SOURCE regression; no package/SDK/SQL imports.

Execute the complete genuine private factory with stdlib copy/RLock/MethodType
on explicitly synthetic plain providers and dict rows. Producer, persistence,
consumer and job/lifetime callers below are STATIC only, never executed.
Run from a complete checkout: python -I -B -S tests/test_graph_worker_origin_session.py
The bounded evidence entry may supply the same raw source bytes to make_suite.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import threading
import types
from typing import Any, Mapping
import unittest

ENTRY_SHA256 = "57385a9fd9e7d94658a49d1eb90106346aea0c3e052a4d7110f1a8f0f8f91cc9"
EXTRACTOR_SHA256 = "6e7e9df73940c0cfd6a8eced6bc2c250d58a9f455d19a27a3caadbc62da02de2"
BASE_FACTORY_AST = "41c0ae8690c85534f8a255c36718d5ad85e8708d731b498653249477a85089c7"
UNCHANGED_NODES = {
    "_run_job": "4ee2147d24ec1c5f9cd67c92ba5a8aeb11f694c2f4a701560396633310483651",
    "profile_key": "48162afa7fc717204643778b3278b68f3d093a6e581db777c4d90c63cb26be19",
    "owner_key": "8acb57d03805871e873db147b588cda75123f81c777b6cfb3c1ba60697a694cf",
}
ENTRY_NODES = {
    "MemoryWikiProvider._prepare_claim": "2050762dbc9cad3c235133c6b165882395ce9aff56cf169e030b2e9c17c07ac3",
    "MemoryWikiProvider._add_claim_tx": "a91ee74e9f7ea49f0f1fba0c6493ee96108dfa7137e916217efb227979e3cdde",
    "MemoryWikiProvider._auto_graph_enrich_extracted_claims": "90775af5db77f524604d8ab785d75b47949bca568743c498bc8c6b2560ecd941",
    "MemoryWikiProvider._graph_owner": "5f5323c344268fc6c9a74b3b7401490ffdbe9df6c78078f146ad9433070c15ef",
}
EXTRACTOR_NODES = {"_evidence_payload": "371091b2e2ca9993cbdd507d657bafe4504ce997806c9adf9927880da28e3aa2"}
CHAT_HASH = "a1" * 16
EVENT_HASH = "b2" * 16
STORED_ORIGIN = "job_" + EVENT_HASH


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def qualified(tree, name):
    scope = tree
    for part in name.split("."):
        pending, matches = list(scope.body), []
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.name == part:
                    matches.append(node)
            else:
                pending.extend(ast.iter_child_nodes(node))
        if len(matches) != 1:
            raise AssertionError("qualified AST not unique: " + name)
        scope = matches[0]
    return scope


def ast_digest(node):
    return digest(ast.dump(node, include_attributes=False).encode("utf-8"))


def contains(node, expression):
    try:
        parsed = ast.parse(expression, mode="eval").body
    except SyntaxError:
        parsed = ast.parse(expression).body[0]
    expected = ast.dump(parsed, include_attributes=False)
    return any(ast.dump(n, include_attributes=False) == expected for n in ast.walk(node))


class SyntheticProvider:
    """Plain data receiver, NOT a MemoryProvider/SDK or SQL authority stand-in."""
    def __init__(self):
        self._conn = object()
        self._lock = threading.RLock()
        self.session_id = "synthetic-parent-session"
        self.bot_id = "synthetic-parent-bot"
        self.project_scope = "synthetic-parent-project"
        self.home = "synthetic-profile-home-label-only"
        self.db_path = "synthetic-db-label-never-opened"
        self.profile_policy = object()
        self.delegated = []

    def _chat_hash(self, session_id=""):
        self.delegated.append(session_id)
        return "synthetic-delegated:" + session_id


def claim_row():
    return {"id": "c_synthetic", "origin_bot_id": "synthetic-owner-bot",
            "origin_chat_hash": CHAT_HASH, "origin_session_id": STORED_ORIGIN,
            "project_id": "synthetic-source-project", "claim": "synthetic plain claim",
            "evidence": json.dumps({"session_id": "untrusted-evidence-session"})}


def event_row():
    return {"event_id": "evt_" + "c3" * 16, "owner_bot_id": "synthetic-owner-bot",
            "owner_chat_hash": CHAT_HASH, "owner_session_hash": EVENT_HASH,
            "project_id": "synthetic-source-project"}


class GraphWorkerOriginSessionTests(unittest.TestCase):
    def setUp(self):
        self.provider = SyntheticProvider()
        self.row = claim_row()

    def worker(self, row=None):
        return self.factory(self.provider, self.row if row is None else row)

    def test_authoritative_origin_survives_graph_worker(self):
        # Explicitly synthetic evidence/storage rows, not executions of their
        # STATIC producers. This witness is durable and hashed BEFORE assertion.
        worker = self.worker()
        evidence = {"schema": "memory-wiki-extraction-evidence-v1", "session_id": STORED_ORIGIN}
        witness = {"schema": "graph-worker-origin-witness/v1", "source_sha256": self.source_sha,
                   "test_sha256": self.test_sha, "authoritative_origin": self.row["origin_session_id"],
                   "evidence_session": evidence["session_id"], "actual_worker_session": worker.session_id,
                   "worker_event_session_hash": worker._job_session_hash,
                   "equal": worker.session_id == self.row["origin_session_id"] == evidence["session_id"],
                   "producer_storage_consumer": "STATIC_ONLY", "actual_graph_SQL": False}
        witness["outcome_sha256"] = digest(json.dumps(witness, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if self.witness_root is not None:
            self.witness_root.mkdir(parents=True, exist_ok=True)
            with (self.witness_root / "witness.json").open("xb") as out:
                out.write((json.dumps(witness, sort_keys=True) + "\n").encode("utf-8"))
                out.flush()
        self.assertEqual(worker.session_id, self.row["origin_session_id"], "authoritative_origin_session_not_preserved")
        self.assertEqual(worker.session_id, evidence["session_id"])
        self.assertEqual(worker._chat_hash(worker.session_id), CHAT_HASH)

    def test_origin_is_preserved_verbatim(self):
        self.row["origin_session_id"] = "  JoB_Сессия\tLiteral-Unnormalized  "
        worker = self.worker()
        self.assertIs(worker.session_id, self.row["origin_session_id"])
        self.assertEqual(worker._chat_hash(worker.session_id), CHAT_HASH)
        self.assertEqual(self.provider.delegated, [])

    def test_nonstring_origin_is_not_coerced(self):
        self.row["origin_session_id"] = {"session_id": STORED_ORIGIN}
        worker = self.worker()
        self.assertEqual(worker.session_id, "job_" + CHAT_HASH)
        self.assertEqual(worker._job_session_hash, "")

    def test_event_session_mapping_has_precedence(self):
        row = event_row()
        row["origin_session_id"] = "must-not-adopt-claim-column"
        worker = self.worker(row)
        self.assertEqual(worker.session_id, STORED_ORIGIN)
        self.assertEqual(worker._job_session_hash, EVENT_HASH)
        self.assertEqual(worker._background_job_owner["session_hash"], EVENT_HASH)
        self.assertEqual(worker._chat_hash(worker.session_id), CHAT_HASH)

    def test_event_empty_session_does_not_adopt_origin(self):
        row = event_row()
        row.update(owner_session_hash="", origin_session_id=STORED_ORIGIN)
        worker = self.worker(row)
        self.assertEqual(worker.session_id, "job_" + CHAT_HASH)
        self.assertEqual(worker._job_session_hash, "")

    def test_legacy_missing_origin_uses_chat_fallback(self):
        del self.row["origin_session_id"]
        self.assertEqual(self.worker().session_id, "job_" + CHAT_HASH)

    def test_legacy_null_origin_uses_chat_fallback(self):
        self.row["origin_session_id"] = None
        self.assertEqual(self.worker().session_id, "job_" + CHAT_HASH)

    def test_legacy_empty_origin_uses_chat_fallback(self):
        self.row["origin_session_id"] = ""
        self.assertEqual(self.worker().session_id, "job_" + CHAT_HASH)

    def test_evidence_and_text_never_supply_identity(self):
        del self.row["origin_session_id"]
        self.row.update(evidence=json.dumps({"session_id": STORED_ORIGIN}), claim=STORED_ORIGIN,
                        text=json.dumps({"origin_session_id": STORED_ORIGIN}))
        worker = self.worker()
        self.assertEqual(worker.session_id, "job_" + CHAT_HASH)
        self.assertEqual(worker._job_session_hash, "")

    def test_claim_origin_is_not_event_capture_authority(self):
        worker = self.worker()
        self.assertEqual(worker.session_id, STORED_ORIGIN)
        self.assertEqual(worker._job_session_hash, "")
        self.assertEqual(worker._background_job_owner, {"bot_id": self.row["origin_bot_id"],
            "chat_hash": CHAT_HASH, "session_hash": "", "project_id": self.row["project_id"]})
        self.assertFalse(hasattr(worker, "_event_job_obligation"))
        self.assertFalse(hasattr(worker, "owner_session_hash"))
        self.assertNotIn("owner_session_hash", self.row)

    def test_private_copy_connection_lock_and_parent_isolation(self):
        before, row_before = dict(vars(self.provider)), copy.deepcopy(self.row)
        worker = self.worker()
        self.assertIsNot(worker, self.provider)
        self.assertIsNone(worker._conn)
        self.assertIsNot(worker._lock, self.provider._lock)
        self.assertEqual(vars(self.provider), before)
        self.assertEqual(self.row, row_before)
        worker.session_id, worker.bot_id, worker.project_scope = "changed", "changed", "changed"
        self.assertEqual(vars(self.provider), before)
        self.assertNotIn("_job_session_hash", vars(self.provider))
        self.assertNotIn("_background_job_owner", vars(self.provider))

    def test_reentrant_lock_and_instance_bound_methods(self):
        first, second = self.worker(), self.worker()
        with first._lock:
            self.assertTrue(first._lock.acquire(blocking=False))
            first._lock.release()
        self.assertIsNot(first._lock, second._lock)
        self.assertIsInstance(first._chat_hash, types.MethodType)
        self.assertIs(first._chat_hash.__self__, first)
        self.assertIs(first._scoped_backup_owner.__self__, first)
        self.assertIs(second._chat_hash.__self__, second)
        self.assertNotIn("_chat_hash", vars(self.provider))

    def test_chat_self_override_and_foreign_delegation(self):
        worker = self.worker()
        self.assertEqual(worker._chat_hash(), CHAT_HASH)
        self.assertEqual(worker._chat_hash(""), CHAT_HASH)
        self.assertEqual(worker._chat_hash(worker.session_id), CHAT_HASH)
        self.assertEqual(self.provider.delegated, [])
        self.assertEqual(worker._chat_hash("foreign-session"), "synthetic-delegated:foreign-session")
        self.assertEqual(self.provider.delegated, ["foreign-session"])
        self.assertEqual(self.provider._chat_hash("synthetic-parent-session"),
                         "synthetic-delegated:synthetic-parent-session")

    def test_profile_bot_project_and_backup_partition(self):
        worker = self.worker()
        self.assertEqual(worker.bot_id, self.row["origin_bot_id"])
        self.assertEqual(worker.project_scope, self.row["project_id"])
        self.assertEqual(worker.home, self.provider.home)
        self.assertEqual(worker.db_path, self.provider.db_path)
        self.assertIs(worker.profile_policy, self.provider.profile_policy)
        self.assertEqual(worker._scoped_backup_owner(), {"bot_id": self.row["origin_bot_id"],
            "session_id": STORED_ORIGIN, "chat_hash": CHAT_HASH, "project_id": self.row["project_id"]})
        self.row["project_id"] = None
        self.assertEqual(self.worker().project_scope, "")

    def test_static_producer_and_storage_preserve_literal_origin(self):
        self.assertEqual(self.entry_sha, ENTRY_SHA256)
        self.assertEqual(self.extractor_sha, EXTRACTOR_SHA256)
        prepare = qualified(self.entry_tree, "MemoryWikiProvider._prepare_claim")
        add = qualified(self.entry_tree, "MemoryWikiProvider._add_claim_tx")
        payload = qualified(self.extractor_tree, "_evidence_payload")
        self.assertEqual(ast_digest(prepare), ENTRY_NODES["MemoryWikiProvider._prepare_claim"])
        self.assertEqual(ast_digest(add), ENTRY_NODES["MemoryWikiProvider._add_claim_tx"])
        self.assertEqual(ast_digest(payload), EXTRACTOR_NODES["_evidence_payload"])
        returned = next(n.value for n in prepare.body if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
        fields = {k.value: v for k, v in zip(returned.keys, returned.values) if isinstance(k, ast.Constant)}
        self.assertEqual(ast.dump(fields["origin_session_id"]), ast.dump(ast.parse("self.session_id", mode="eval").body))
        self.assertTrue(contains(add, 'p.get("origin_session_id", "")'))
        self.assertTrue(any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                            and "origin_session_id=?" in n.value for n in ast.walk(add)))
        self.assertTrue(contains(payload, 'str(session_id or "")[:300]'))

    def test_static_consumer_equality_and_all_eligibility_unchanged(self):
        name = "MemoryWikiProvider._auto_graph_enrich_extracted_claims"
        node = qualified(self.entry_tree, name)
        self.assertEqual(ast_digest(node), ENTRY_NODES[name])
        self.assertTrue(contains(node, 'str(evidence.get("session_id") or "") == str(self.session_id or "")'))
        self.assertTrue(contains(node, 'not eligible or not grounded'))
        self.assertTrue(contains(node, 'not self._claim_visible(claim)'))
        self.assertTrue(contains(node, 'str(claim["origin_chat_hash"] or "") == self._chat_hash(self.session_id)'))
        self.assertTrue(contains(node, 'str(claim["source"] or "") in {"extractor:llm", "extractor:heuristic"}'))
        self.assertTrue(contains(node, 'str(claim["secrecy_level"] or "public") == "public"'))
        self.assertTrue(contains(node, 'remaining < 1.0'))
        # Structural inequality is retained; this does NOT execute the consumer.
        comparison = next(n for n in ast.walk(node) if isinstance(n, ast.Compare)
                          and contains(n, 'str(evidence.get("session_id") or "") == str(self.session_id or "")'))
        self.assertIsInstance(comparison.ops[0], ast.Eq)

    def test_static_graph_owner_original_source_and_writer_guards(self):
        name = "MemoryWikiProvider._graph_owner"
        node = qualified(self.entry_tree, name)
        self.assertEqual(ast_digest(node), ENTRY_NODES[name])
        self.assertTrue(contains(node, 'self._require_claim_writer(c)'))
        self.assertTrue(contains(node, 'self._graph_source_eligible(claim)'))
        self.assertTrue(contains(node, 'actor != original_actor'))
        self.assertTrue(contains(node, 'tuple(claim) != tuple(original_source)'))
        self.assertTrue(contains(node, 'project_id != self.project_scope'))

    def test_static_queue_callers_and_lifetime_guards_unchanged(self):
        for name, expected in UNCHANGED_NODES.items():
            self.assertEqual(ast_digest(qualified(self.source_tree, name)), expected)
        node = qualified(self.source_tree, "_run_job")
        self.assertTrue(contains(node, '_worker_provider(provider, source)'))
        self.assertTrue(contains(node, 'raise persistence_primary'))
        self.assertTrue(contains(node, '_close_job_worker(provider, worker, primary)'))
        self.assertTrue(contains(node, 'enqueue_claim(worker, claim_id)'))
        # Exact full _run_job pin includes queue order, owner/lease/source guards,
        # BaseException primary retention and cleanup. No actual queue/SQL calls.
        self.assertEqual(self.other_source_ast, self.baseline_other_source_ast)


def make_suite(source_raw, source_path, entry_raw, entry_path, extractor_raw,
               extractor_path, witness_root=None, cases=None, *, test_raw=None):
    source_tree, entry_tree, extractor_tree = (ast.parse(raw) for raw in (source_raw, entry_raw, extractor_raw))
    factory = qualified(source_tree, "_worker_provider")
    futures = [n for n in source_tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    namespace = {"__name__": "genuine_source_factory", "copy": copy, "threading": threading,
                 "Any": Any, "Mapping": Mapping}
    # Keep original function body/signature and nested lambdas entirely intact.
    exec(compile(ast.Module(body=[*futures, factory], type_ignores=[]), str(source_path),
                 "exec", dont_inherit=True), namespace)
    cls = GraphWorkerOriginSessionTests
    cls.factory = staticmethod(namespace["_worker_provider"])
    cls.source_tree, cls.entry_tree, cls.extractor_tree = source_tree, entry_tree, extractor_tree
    cls.source_sha, cls.entry_sha, cls.extractor_sha = (digest(raw) for raw in (source_raw, entry_raw, extractor_raw))
    cls.test_sha = digest(Path(__file__).read_bytes() if test_raw is None else test_raw)
    cls.witness_root = None if witness_root is None else Path(witness_root)
    cls.other_source_ast = [ast.dump(n, include_attributes=False) for n in source_tree.body if n is not factory]
    # Hash a full original-rest AST rather than requiring any external baseline
    # peer. This frozen pin includes every unchanged JobStore/lifecycle guard.
    cls.other_source_ast = digest("\n".join(cls.other_source_ast).encode("utf-8"))
    cls.baseline_other_source_ast = "cbe50eb4a79edea9615e3de4630cca1aa4f90f215f36e28969641b0e477f1109"
    suite = (unittest.defaultTestLoader.loadTestsFromTestCase(cls) if cases is None
             else unittest.TestSuite(cls(name) for name in cases))
    bindings = []
    for label, path, parsed, names in (
            ("runtime_factory", source_path, source_tree, ["_worker_provider"]),
            ("static_job_callers", source_path, source_tree, list(UNCHANGED_NODES)),
            ("static_storage_consumer", entry_path, entry_tree, list(ENTRY_NODES)),
            ("static_evidence_producer", extractor_path, extractor_tree, list(EXTRACTOR_NODES))):
        for name in names:
            node = qualified(parsed, name)
            bindings.append({"role": label, "qualified_scope": name, "node_type": type(node).__name__,
                             "lines": [node.lineno, node.end_lineno], "ast_sha256": ast_digest(node)})
    return suite, bindings


if __name__ == "__main__":
    root = Path(__file__).absolute().parents[1]
    suite, _ = make_suite((root / "background_jobs.py").read_bytes(), root / "background_jobs.py",
                         (root / "__init__.py").read_bytes(), root / "__init__.py",
                         (root / "extractor.py").read_bytes(), root / "extractor.py")
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
