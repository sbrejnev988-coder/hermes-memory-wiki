"""PREPARED / NOT_RUN: addressed retry policy + separate AST/JSON controls.

Collection is inert: no product imports, source reads, exec, SQL, SDK, workers,
network, native calls or environment changes. __test__ is false deliberately.
After separate admission, the existing SOURCE controller may load the exact
small policy and pass it to make_policy_suite. make_metadata_suite takes raw
main/cache/baseline bytes for AST/JSON ONLY; it never executes the large main.
Neither suite proves public/native repair, COMMIT, ACL or lease enforcement.
"""
from __future__ import annotations

import ast
import copy
import json
import unittest

__test__ = False

POLICY_CASE_IDS = (
    "test_healthy_real_producer_shape_preserves_hint",
    "test_ids_are_bounded_unique_and_literal",
    "test_malformed_and_untyped_hints_never_become_online",
    "test_explicit_current_target_and_bound_alias_only",
    "test_historical_delete_refused_without_retarget",
    "test_failed_idle_row_required",
    "test_canonical_revision_text_and_owner_must_match",
    "test_complete_job_image_detects_every_race",
    "test_original_epoch_allows_only_counted_own_updates",
    "test_diagnostics_never_include_retained_errors_or_text",
)
METADATA_CASE_IDS = (
    "test_schema_and_cache_additive_parity",
    "test_public_caller_forwards_exact_ids",
    "test_native_acl_source_and_target_guards_are_connected",
    "test_conditional_update_and_postcommit_wake_structure",
    "test_worker_and_authority_owners_are_unchanged",
    "test_removed_forwarding_is_distinguished",
)


def _method(tree, name):
    provider = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == "MemoryWikiProvider")
    return next(node for node in provider.body if isinstance(node, ast.FunctionDef) and node.name == name)


def _calls(node, name):
    return [call for call in ast.walk(node) if isinstance(call, ast.Call)
            and ((isinstance(call.func, ast.Attribute) and call.func.attr == name)
                 or (isinstance(call.func, ast.Name) and call.func.id == name))]


def _forwarded(call):
    return any(keyword.arg == "outbox_job_ids" for keyword in call.keywords)


def _repair_schema(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        fields = {key.value: value for key, value in zip(node.keys, node.values)
                  if isinstance(key, ast.Constant) and type(key.value) is str}
        if isinstance(fields.get("name"), ast.Constant) and fields["name"].value == "memory_wiki_repair":
            parameters = fields["parameters"]
            assert isinstance(parameters, ast.Call) and parameters.func.id == "P"
            return {"type": "object", "properties": ast.literal_eval(parameters.args[0]), "required": []}
    raise AssertionError("actual repair schema missing")


class AddressedOutboxPolicyTests(unittest.TestCase):
    __test__ = False
    policy = None

    @classmethod
    def setUpClass(cls):
        if cls.policy is None:
            raise RuntimeError("NOT_RUN: separately admitted exact policy input required")

    def setUp(self):
        # Literal fields from _add_claim's real enqueue contract, not a made-up
        # provider/ACL/SDK success. Only pure policy is exercised by these cases.
        self.claim = {"id": "own-claim", "status": "active", "normalized_claim": "Benign canonical fact.",
                      "memory_revision": 17, "updated_at": 128, "event_at": 64,
                      "visibility_scope": "chat", "origin_bot_id": "own-bot",
                      "origin_session_id": "own-session", "origin_chat_hash": "own-chat",
                      "project_id": ""}
        self.payload = {key: value for key, value in self.claim.items()
                        if key not in {"id", "status", "normalized_claim"}}
        self.payload.update(text=self.claim["normalized_claim"], topic="general", collection="claims_abcdef123456")
        self.job = {"id": "0123456789abcdef", "operation": "embed_and_upsert", "object_type": "claim",
                    "object_id": "own-claim", "payload_json": json.dumps(self.payload), "payload_hash": None,
                    "attempts": 5, "status": "failed", "last_error": "private-error-sentinel",
                    "created_at": 32, "updated_at": 256, "worker_id": "", "lease_until": 0, "next_retry_at": 256}
        self.target = dict(collection="claims_abcdef123456", alias="", endpoint="https://vectors.example",
                           manifest_hash="abcdef123456", vector_target_hash="b" * 64)

    def reason(self, *, job=None, claim=None, payload=None, **target):
        current = dict(self.job if job is None else job)
        if payload is not None:
            current["payload_json"] = json.dumps(payload)
        return self.policy.retry_reason(current, self.claim if claim is None else claim,
                                        **(self.target | target))

    def test_healthy_real_producer_shape_preserves_hint(self):
        before = copy.deepcopy((self.job, self.claim, self.target))
        self.assertEqual(self.reason(), "")
        self.assertEqual(self.reason(job=self.job | {"operation": "upsert"}), "")
        self.assertEqual(self.reason(payload=self.payload | {"endpoint": self.target["endpoint"],
                             "manifest_hash": self.target["manifest_hash"],
                             "vector_target_hash": self.target["vector_target_hash"]}), "")
        self.assertEqual(self.reason(payload=self.payload | {"collection": "claims_active"}, alias="claims_active"), "")
        self.assertEqual((self.job, self.claim, self.target), before)

    def test_ids_are_bounded_unique_and_literal(self):
        ids = [f"{index:016x}" for index in range(100)]
        self.assertEqual(self.policy.validate_job_ids(ids), (tuple(ids), ""))
        self.assertEqual(self.policy.validate_job_ids(None), ((), "outbox_job_ids_required"))
        for invalid in ([], ids + ["f" * 16], [ids[0], ids[0]], tuple(ids), ids[0],
                        [True], [17], ["0123456789ABCDEF"], [" " + ids[0]], [ids[0] + "\n"], ["x" * 16]):
            with self.subTest(invalid=type(invalid).__name__):
                self.assertEqual(self.policy.validate_job_ids(invalid), ((), "outbox_job_ids_invalid"))

    def test_malformed_and_untyped_hints_never_become_online(self):
        for raw in (None, "", " ", "{bad", "null", "[]", '"text"', "1", "true",
                    '{"collection":"a","collection":"b"}', '{"collection":"a","vector":[NaN]}'):
            with self.subTest(raw_type=type(raw).__name__):
                self.assertEqual(self.policy.decode_payload(raw), (None, "outbox_payload_invalid"))
                self.assertEqual(self.reason(job=self.job | {"payload_json": raw}), "outbox_payload_invalid")
        for payload in ({}, {"collection": None}, {"collection": []}, {"collection": 1},
                        {"collection": ""}, {"collection": " claims_active"}, {"collection": "x\x00y"}):
            self.assertEqual(self.reason(payload=payload), "outbox_target_missing_or_invalid")

    def test_explicit_current_target_and_bound_alias_only(self):
        for changed in ({"collection": "claims_old"}, {"collection": "claims_active"},
                        {"endpoint": "https://other.example"}, {"endpoint": 7}, {"endpoint": ""},
                        {"manifest_hash": "old"}, {"manifest_hash": []}, {"vector_target_hash": "old"}):
            original = copy.deepcopy(self.payload | changed)
            self.assertEqual(self.reason(payload=original), "outbox_target_mismatch")
            self.assertEqual(original, self.payload | changed)
        self.assertEqual(self.reason(collection=""), "outbox_target_unproven")
        self.assertEqual(self.reason(payload=self.payload | {"collection": "claims_active"}, alias="claims_active"), "")

    def test_historical_delete_refused_without_retarget(self):
        for collection in ("claims_old", self.target["collection"], "claims_active"):
            job = self.job | {"operation": "delete", "payload_json": json.dumps({
                "collection": collection, "endpoint": "https://historical.example", "reason": "revision_invalidation"})}
            before = copy.deepcopy(job)
            self.assertEqual(self.reason(job=job), "outbox_delete_capability_required")
            self.assertEqual(self.policy.job_hint(job), (None, "outbox_delete_capability_required"))
            self.assertEqual(job, before)

    def test_failed_idle_row_required(self):
        for status in ("pending", "processing", "completed", None):
            self.assertEqual(self.reason(job=self.job | {"status": status}), "outbox_job_not_failed")
        for changed in ({"worker_id": "other-worker"}, {"lease_until": 1}, {"lease_until": -1},
                        {"lease_until": False}, {"lease_until": None}):
            self.assertEqual(self.reason(job=self.job | changed), "outbox_job_leased")
        for attempts in (True, -1, "5", None):
            self.assertEqual(self.reason(job=self.job | {"attempts": attempts}), "outbox_job_image_invalid")
        self.assertEqual(self.reason(job=self.job | {"object_type": "episode"}), "outbox_operation_unsupported")
        self.assertEqual(self.reason(job=self.job | {"operation": "other"}), "outbox_operation_unsupported")

    def test_canonical_revision_text_and_owner_must_match(self):
        for key in ("memory_revision", "updated_at", "event_at", "visibility_scope", "origin_bot_id",
                    "origin_session_id", "origin_chat_hash", "project_id", "text"):
            changed = dict(self.payload)
            changed[key] = changed[key] + (1 if type(changed[key]) is int else "-changed")
            self.assertEqual(self.reason(payload=changed), "outbox_claim_changed")
            changed = dict(self.payload)
            del changed[key]
            if key != "text":
                self.assertEqual(self.reason(payload=changed), "outbox_claim_changed")
        self.assertEqual(self.reason(payload=self.payload | {"memory_revision": True}), "outbox_claim_changed")
        self.assertEqual(self.reason(claim=self.claim | {"status": "archived"}), "outbox_claim_changed")
        self.assertEqual(self.reason(claim=self.claim | {"id": "foreign-claim"}), "outbox_claim_changed")
        self.assertEqual(self.reason(claim=self.claim | {"memory_revision": 18}), "outbox_claim_changed")

    def test_complete_job_image_detects_every_race(self):
        self.assertEqual(set(self.job), set(self.policy.JOB_FIELDS))
        self.assertTrue(self.policy.same_job(self.job, dict(self.job)))
        self.assertFalse(self.policy.same_job(self.job, None))
        for key, value in self.job.items():
            current = dict(self.job)
            current[key] = value + (1 if type(value) is int else "-changed") if value is not None else "changed"
            self.assertFalse(self.policy.same_job(self.job, current), key)
            current = dict(self.job)
            del current[key]
            self.assertFalse(self.policy.same_job(self.job, current), key)
        self.assertFalse(self.policy.same_job(self.job, self.job | {"lease_until": False}))

    def test_original_epoch_allows_only_counted_own_updates(self):
        epoch = ("original-meta-fingerprint", 7, 40)
        self.assertTrue(self.policy.same_epoch(epoch, epoch))
        self.assertTrue(self.policy.same_epoch(epoch, (epoch[0], 7, 42), 2))
        for changed, own in ((("new-meta", 7, 40), 0), ((epoch[0], 8, 40), 0),
                             ((epoch[0], 7, 41), 0), ((epoch[0], 7, 43), 2),
                             ((epoch[0], 7, 40), 1), ((epoch[0], 7, 41), True),
                             ((epoch[0], 7, 40), -1)):
            self.assertFalse(self.policy.same_epoch(epoch, changed, own))

    def test_diagnostics_never_include_retained_errors_or_text(self):
        for job in (self.job | {"payload_json": "raw-text-sentinel: bad json"},
                    self.job | {"status": "processing"}, self.job | {"operation": "delete"}):
            reason = self.reason(job=job)
            self.assertTrue(reason.startswith("outbox_"))
            for raw in (self.job["last_error"], self.claim["normalized_claim"], "raw-text-sentinel", self.job["id"]):
                self.assertNotIn(raw, reason)


class AddressedOutboxMetadataTests(unittest.TestCase):
    __test__ = False
    tree = None

    @classmethod
    def setUpClass(cls):
        if cls.tree is None:
            raise RuntimeError("NOT_RUN: separately supplied AST/JSON inputs required")

    def test_schema_and_cache_additive_parity(self):
        cached = next(record for record in self.cache if record["name"] == "memory_wiki_repair")
        self.assertEqual(_repair_schema(self.tree), cached["parameters"])
        prop = cached["parameters"]["properties"]["outbox_job_ids"]
        self.assertEqual((prop["minItems"], prop["maxItems"], prop["uniqueItems"]), (1, 100, True))
        self.assertTrue(cached["parameters"]["properties"]["dry_run"]["default"])
        self.assertNotIn("outbox_job_ids", cached["parameters"]["required"])
        unchanged = [record for record in self.cache if record["name"] != "memory_wiki_repair"]
        before = [record for record in self.baseline_cache if record["name"] != "memory_wiki_repair"]
        self.assertEqual(len(unchanged), 120)
        self.assertEqual(json.dumps(unchanged, sort_keys=True), json.dumps(before, sort_keys=True))

    def test_public_caller_forwards_exact_ids(self):
        dispatch = _method(self.tree, "handle_tool_call")
        calls = _calls(dispatch, "_repair")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(_forwarded(call) for call in calls))
        for call in calls:
            keyword = next(keyword for keyword in call.keywords if keyword.arg == "outbox_job_ids")
            self.assertEqual(ast.unparse(keyword.value), "a.get('outbox_job_ids')")
        repair = _method(self.tree, "_repair")
        retry = _calls(repair, "_repair_failed_outbox")
        self.assertEqual(len(retry), 1)
        self.assertTrue(_forwarded(retry[0]))
        for name in ("_repair", "_repair_failed_outbox"):
            method = _method(self.tree, name)
            self.assertIn("outbox_job_ids", [arg.arg for arg in method.args.kwonlyargs])
            self.assertTrue(ast.literal_eval(method.args.defaults[0 if name == "_repair_failed_outbox" else 1]))

    def test_native_acl_source_and_target_guards_are_connected(self):
        retry = _method(self.tree, "_repair_failed_outbox")
        for name in ("validate_job_ids", "job_hint", "retry_reason", "same_epoch", "same_job",
                     "_require_claim_writer", "_require_model_mutable_claim", "_claim_visibility_sql",
                     "_claim_metadata_eligibility_sql", "_DisclosureFence", "claims", "finish", "_strict_target",
                     "_profile_endpoint_allowed", "_profile_target_allowed", "_authority", "_erasures", "_read"):
            self.assertTrue(_calls(retry, name), name)
        sql = " ".join(node.value for node in ast.walk(retry) if isinstance(node, ast.Constant) and type(node.value) is str)
        for fragment in ("JOIN claims", "jobs.id IN (", "jobs.object_type='claim'", "claims.visibility_scope IN ('chat','private')"):
            self.assertIn(fragment, sql)
        self.assertFalse(_calls(retry, "_connect"))
        early = next(node for node in ast.walk(_method(self.tree, "handle_tool_call")) if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "repair_target == 'outbox'")
        self.assertLess(early.lineno, min(call.lineno for call in _calls(_method(self.tree, "handle_tool_call"), "_has_foreign_claims")))

    def test_conditional_update_and_postcommit_wake_structure(self):
        retry = _method(self.tree, "_repair_failed_outbox")
        strings = [node.value for node in ast.walk(retry) if isinstance(node, ast.Constant) and type(node.value) is str]
        update = next(value for value in strings if value.startswith("UPDATE index_outbox SET"))
        self.assertIn("WHERE status='failed' AND worker_id='' AND lease_until=0 AND ", update)
        sets = update.split("WHERE")[0]
        for untouched in ("payload_json", "payload_hash", "last_error", "worker_id", "lease_until"):
            self.assertNotIn(untouched, sets)
        self.assertIn(" IS ?", strings)
        self.assertIn("outbox_retry_no_effect", strings)
        self.assertTrue(any(isinstance(node, ast.Attribute) and node.attr == "rowcount" for node in ast.walk(retry)))
        transaction = next(node for node in ast.walk(retry) if isinstance(node, ast.With)
                           and any(_calls(item.context_expr, "_claim_transaction") for item in node.items))
        self.assertTrue(_calls(transaction, "same_job"))
        for wake in _calls(retry, "_start_outbox_worker") + _calls(retry, "_wake_outbox_worker"):
            self.assertGreater(wake.lineno, transaction.end_lineno)
            self.assertEqual(ast.unparse(wake.args[0]), "path")
        response_keys = {key.value for node in ast.walk(retry) if isinstance(node, ast.Dict)
                         for key in node.keys if isinstance(key, ast.Constant)}
        self.assertFalse(response_keys & {"id", "object_id", "payload_json", "last_error", "failed_seen", "skipped_count"} - {"id"})
        # The only id dict is an INTERNAL claim selector, never a return item.
        for returned in (node for node in ast.walk(retry) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
            self.assertFalse({key.value for key in returned.value.keys if isinstance(key, ast.Constant)}
                             & {"id", "object_id", "payload_json", "last_error", "failed_seen"})

    def test_worker_and_authority_owners_are_unchanged(self):
        for name in ("_outbox_process_scoped", "_outbox_enqueue", "_delete_claim_vector_targets"):
            current = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            before = next(node for node in self.baseline_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(ast.dump(current, include_attributes=False), ast.dump(before, include_attributes=False))
        for name in ("_claim_transaction", "_require_model_mutable_claim", "_claim_metadata_eligibility_sql", "_claim_visibility_sql"):
            self.assertEqual(ast.dump(_method(self.tree, name), include_attributes=False),
                             ast.dump(_method(self.baseline_tree, name), include_attributes=False))

    def test_removed_forwarding_is_distinguished(self):
        actual = _calls(_method(self.tree, "_repair"), "_repair_failed_outbox")[0]
        control = copy.deepcopy(actual)
        control.keywords = [keyword for keyword in control.keywords if keyword.arg != "outbox_job_ids"]
        self.assertTrue(_forwarded(actual))
        self.assertFalse(_forwarded(control))


def make_policy_suite(policy):
    """Call ONLY behind the existing separately admitted SOURCE bootstrap."""
    class BoundPolicyTests(AddressedOutboxPolicyTests):
        pass
    BoundPolicyTests.policy = policy
    return unittest.TestSuite(BoundPolicyTests(name) for name in POLICY_CASE_IDS)


def make_metadata_suite(main_raw, cache_raw, baseline_main_raw, baseline_cache_raw):
    """Raw bytes -> AST/JSON; no product compile/exec/import or test autorun."""
    class BoundMetadataTests(AddressedOutboxMetadataTests):
        pass
    BoundMetadataTests.tree = ast.parse(main_raw)
    BoundMetadataTests.cache = json.loads(cache_raw)
    BoundMetadataTests.baseline_tree = ast.parse(baseline_main_raw)
    BoundMetadataTests.baseline_cache = json.loads(baseline_cache_raw)
    return unittest.TestSuite(BoundMetadataTests(name) for name in METADATA_CASE_IDS)
