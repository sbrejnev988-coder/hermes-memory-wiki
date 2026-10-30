"""PREPARED / NOT_RUN: addressed retry policy + separate AST/JSON controls.

Collection is inert: no product imports, source reads, exec, SQL, SDK, workers,
network, native calls or environment changes. __test__ is false deliberately.
After separate admission, the existing SOURCE controller may load the exact
small policy and pass it to make_policy_suite. make_metadata_suite takes raw
main/cache/baseline bytes for AST/JSON ONLY; it never executes the large main.
Neither suite proves public/native repair, COMMIT, ACL or lease enforcement.
The explicit native-owner suite also stays inert until separately admitted;
it reuses the genuine shipped fixture, never a provider/SDK/authority stand-in.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import unittest

__test__ = False

# Exact CURRENT inputs, not the older donor or a native attestation.
CURRENT_BASELINE_HEAD = '4b32def39cb9272fae54f15859e82563eb78c95f'
CURRENT_BASELINE_TREE = '10d98c9efe032aafe45d04f10f4107e3b47d02d6'
CURRENT_BASELINE_SHA256 = {'__init__.py': '630df34f8e0c23ff00ade2d4d5a6dc1f54ef3bb3dccc796118d16555763bff5a', 'code_knowledge_graph.py': '795f02b73df95325db9f34212d622d846bf4d9f57334992d0abc44fb2e5525ae', 'mcp-wrapper/tool_schemas.json': '674d9e94ca1e7c0bc86561b0d217edb2a7a5d6844f296b69c05a87b43707cd14'}

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
    "test_notification_projection_preserves_deferred_intent",
    "test_notification_cannot_manufacture_commit_or_accept_unknown_codes",
)
METADATA_CASE_IDS = (
    "test_schema_and_cache_additive_parity",
    "test_public_caller_forwards_exact_ids",
    "test_native_acl_source_and_target_guards_are_connected",
    "test_conditional_update_and_postcommit_wake_structure",
    "test_worker_and_authority_owners_are_unchanged",
    "test_removed_forwarding_is_distinguished",
    "test_private_exact_stage_reaches_actual_owner",
    "test_original_admission_follows_callback_capable_owner_tail",
    "test_native_flight_covers_callback_and_commit",
    "test_late_callbacks_and_reentrant_completion_are_refused",
    "test_only_known_completion_retires_and_sets_applied",
    "test_notification_has_only_locked_live_registry_effects",
    "test_removed_native_fence_is_distinguished",
    "test_progress_bookkeeping_is_native_success_bound_and_fail_closed",
    "test_removed_progress_reconciliation_is_distinguished",
    "test_current_baseline_retained_guards_are_unchanged",
    "test_current_commit_receipt_remains_disjoint_and_native_bound",
    "test_current_schema_and_policy_module_wiring",
    "test_nested_transaction_forwards_literal_ids_in_both_modes",
    "test_nested_refusal_precedes_success_postprocessing",
)
NATIVE_OWNER_CASE_IDS = (
    "test_callback_free_real_owner_commits_and_retires",
    "test_late_journal_actor_change_refuses_original_admission",
    "test_real_authorizer_lifetime_is_refused_not_disabled",
    "test_late_trace_install_remove_cannot_hide_callback_lifetime",
    "test_premature_completion_and_mode_close_shortcuts_are_refused",
    "test_fatal_before_commit_preserves_identity_and_known_rollback",
    "test_postcommit_fatal_preserves_known_commit_not_false_rollback",
    "test_absent_dead_worker_notification_has_no_whole_store_maintenance",
    "test_failed_progress_clear_before_stage_refuses_and_rolls_back",
    "test_successful_progress_clear_reconciles_before_stage",
    "test_progress_install_remove_is_sticky_inside_stage",
    "test_ordinary_progress_callback_survives_failed_clear",
    "test_progress_index_and_bool_use_effective_native_count",
    "test_progress_nonpositive_counts_are_callback_free",
    "test_invalid_progress_counts_preserve_registration",
    "test_fatal_progress_index_preserves_identity_and_known_rollback",
    "test_failed_progress_clear_inside_stage_stays_sticky_after_clear",
    "test_current_commit_receipt_mode_is_not_borrowed_by_retry",
    "test_current_ordinary_commit_receipt_still_observes_real_owner",
)
# These public/native cases require a separately admitted actual semantic
# target/erasure fixture and independent whole-store readback. No permissive
# _strict_target/DisclosureFence replacement is provided to make them runnable.
PUBLIC_NATIVE_REQUIREMENTS = (
    "real producer-owned failed upsert + callback-free public repair + durable exact afterimage",
    "journal-tail actor/ACL/source/erasure/target/job drift + whole-batch durable rollback",
    "last native authorizer actor/ACL mutation OR explicit refusal before it can commit",
    "rollback denied/fatal + UNKNOWN keeps exact owner/stage/primary, no notify/reconnect",
    "absent and dead worker + foreign legacy completed $.text row unchanged in whole-store readback",
    "registered live worker original-path Event.set only; no bootstrap/SQL/thread creation",
    "public notification failure after known commit stays applied=true; dry-run/refusal/UNKNOWN never notify",
)


def _method(tree, name):
    provider = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == "MemoryWikiProvider")
    return next(node for node in provider.body if isinstance(node, ast.FunctionDef) and node.name == name)


def _calls(node, name):
    return [call for call in ast.walk(node) if isinstance(call, ast.Call)
            and ((isinstance(call.func, ast.Attribute) and call.func.attr == name)
                 or (isinstance(call.func, ast.Name) and call.func.id == name))]


def _definition(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name == name)


def _native_method(tree, name):
    return next(node for node in _definition(tree, "_GraphCommitConnection").body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _native_chain_present(tree):
    start = _native_method(tree, "_graph_start_commit")
    authorize = _native_method(tree, "_graph_authorizer_result")
    commit = _native_method(tree, "commit")
    fences = _calls(authorize, "_outbox_retry_commit_fence")
    callbacks = _calls(authorize, "callback")
    return bool(_calls(start, "_outbox_retry_commit_fence") and fences and callbacks
                and min(n.lineno for n in fences) > max(n.lineno for n in callbacks)
                and _calls(commit, "_graph_start_commit") and _calls(commit, "_graph_native_return"))


def _progress_reconciliation_present(tree):
    """AST-only oracle, not execution of the setter or its native dependency."""
    setter = _native_method(tree, "set_progress_handler")
    native = _calls(setter, "set_progress_handler")
    indices = _calls(setter, "index")
    if len(native) != 1 or len(indices) != 1:
        return False
    effect = native[0]
    if (ast.unparse(effect.func) != "super().set_progress_handler"
            or [ast.unparse(arg) for arg in effect.args] != ["callback", "n"]
            or ast.unparse(indices[0]) != "operator.index(n)" or indices[0].lineno >= effect.lineno):
        return False
    assignments = [n for n in ast.walk(setter) if isinstance(n, ast.Assign)
                   and any(ast.unparse(t) == "self._graph_progress" for t in n.targets)]
    before = [n for n in assignments if n.lineno < effect.lineno]
    if len(before) != 1 or ast.unparse(before[0].value) != "pending":
        return False
    handlers = [h for h in ast.walk(setter) if isinstance(h, ast.ExceptHandler)
                and ast.unparse(h.type) == "BaseException"]
    if len(handlers) != 1:
        return False
    handler = handlers[0]
    return (any(ast.unparse(n) == "self._graph_progress = pending" for n in handler.body)
            and isinstance(handler.body[-1], ast.Raise) and handler.body[-1].exc is None
            and any(ast.unparse(n.value) == "progress" and n.lineno > effect.lineno for n in assignments)
            and all(n.lineno < effect.lineno for n in ast.walk(setter) if isinstance(n, ast.Compare)
                    and any(isinstance(op, ast.Gt) for op in n.ops)))


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


    def test_notification_projection_preserves_deferred_intent(self):
        self.assertEqual(self.policy.notification_fields("notified"),
                         {"ok": True, "worker_woken": True, "notification": "notified"})
        self.assertEqual(self.policy.notification_fields("deferred_no_live_worker"),
                         {"ok": True, "worker_woken": False, "notification": "deferred_no_live_worker"})
        for code in ("deferred_context_changed", "deferred_postcommit_failed", "deferred_notification_failed"):
            self.assertEqual(self.policy.notification_fields(code),
                             {"ok": False, "worker_woken": False, "notification": code})

    def test_notification_cannot_manufacture_commit_or_accept_unknown_codes(self):
        for code in ("notified", "deferred_no_live_worker", "deferred_notification_failed"):
            fields = self.policy.notification_fields(code)
            self.assertFalse(set(fields) & {"applied", "revived_count", "eligible_count", "status"})
        for code in (None, True, 1, [], {}, "not_requested", "committed", "unknown", " notified"):
            with self.assertRaisesRegex(ValueError, "^outbox_notification_state_invalid$"):
                self.policy.notification_fields(code)


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
        self.assertFalse(_calls(retry, "_start_outbox_worker") + _calls(retry, "_wake_outbox_worker"))
        wakes = _calls(retry, "_notify_registered_outbox_worker")
        self.assertEqual(len(wakes), 1)
        for wake in wakes:
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
        for name in ("_outbox_process_scoped", "_outbox_enqueue", "_delete_claim_vector_targets",
                     "_ensure_outbox", "_start_outbox_worker", "_wake_outbox_worker", "_outbox_worker_loop"):
            current = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            before = next(node for node in self.baseline_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(ast.dump(current, include_attributes=False), ast.dump(before, include_attributes=False))
        for name in ("_require_model_mutable_claim", "_claim_metadata_eligibility_sql", "_claim_visibility_sql",
                     "_require_claim_writer", "_rollback_claim_transaction", "_claim_journal_pending_commit"):
            self.assertEqual(ast.dump(_method(self.tree, name), include_attributes=False),
                             ast.dump(_method(self.baseline_tree, name), include_attributes=False))
        # The owner body is deliberately extended by correction01, NOT claimed
        # byte-unchanged. Existing call modes/defaults remain literal prefixes.
        current = _method(self.tree, "_claim_transaction").args
        before = _method(self.baseline_tree, "_claim_transaction").args
        self.assertEqual([arg.arg for arg in current.kwonlyargs[:-1]], [arg.arg for arg in before.kwonlyargs])
        self.assertEqual(current.kwonlyargs[-1].arg, "_outbox_retry")
        self.assertEqual([ast.dump(v) for v in current.kw_defaults[:-1]], [ast.dump(v) for v in before.kw_defaults])
        for name in ("_graph_commit_fence", "_document_commit_fence", "_event_job_commit_fence",
                     "_GraphWriterConnection", "_GraphWriterCursor", "_GraphCommitCursor", "_GraphReaderConnection"):
            self.assertEqual(ast.dump(_definition(self.native_tree, name), include_attributes=False),
                             ast.dump(_definition(self.baseline_native_tree, name), include_attributes=False))

    def test_removed_forwarding_is_distinguished(self):
        actual = _calls(_method(self.tree, "_repair"), "_repair_failed_outbox")[0]
        control = copy.deepcopy(actual)
        control.keywords = [keyword for keyword in control.keywords if keyword.arg != "outbox_job_ids"]
        self.assertTrue(_forwarded(actual))
        self.assertFalse(_forwarded(control))


    def test_private_exact_stage_reaches_actual_owner(self):
        retry = _method(self.tree, "_repair_failed_outbox")
        stage = _calls(retry, "_OutboxRetryStage")
        self.assertEqual(len(stage), 1)
        self.assertEqual([ast.unparse(arg) for arg in stage[0].args], ["self", "c", "final_original_admission"])
        owner = _calls(retry, "_claim_transaction")[0]
        self.assertEqual([(k.arg, ast.unparse(k.value)) for k in owner.keywords], [("_outbox_retry", "retry_stage")])
        tx = _method(self.tree, "_claim_transaction")
        text = ast.unparse(tx)
        for condition in ("type(_outbox_retry) is not _OutboxRetryStage", "join or adopt",
                          "_outbox_retry.owner is not self", "_outbox_retry.conn is not c",
                          "_outbox_retry.thread != threading.get_ident()", "outbox_retry_owner_pending",
                          "_rollback_receipt", "outbox_retry_standalone_owner_required"):
            self.assertIn(condition, text)
        stage_type = _definition(self.native_tree, "_OutboxRetryStage")
        self.assertIn("__slots__", ast.unparse(stage_type))
        self.assertFalse(_calls(stage_type, "execute") + _calls(stage_type, "connect"))

    def test_original_admission_follows_callback_capable_owner_tail(self):
        tx = _method(self.tree, "_claim_transaction")
        admit = _calls(tx, "admit")
        original = next(call for call in admit if ast.unparse(call.func) == "_outbox_retry.admit")
        for name in ("_claim_journal_pending_commit", "_assert_graph_effects", "_assert_event_job_leases",
                     "_assert_ingest_authority", "prefetch_ready"):
            self.assertTrue(all(call.lineno < original.lineno for call in _calls(tx, name)), name)
        self.assertLess(original.lineno, _calls(tx, "commit")[0].lineno)
        retry = _method(self.tree, "_repair_failed_outbox")
        final = next(
            node for node in ast.walk(retry) if isinstance(node, ast.FunctionDef) and node.name == "final_original_admission")
        for name in ("target_current", "original_current", "same_job", "execute", "fetchall"):
            self.assertTrue(_calls(final, name), name)
        self.assertEqual(ast.unparse(next(node.value for node in final.body if isinstance(node, ast.Return))),
                         "disclosure.epoch[2] + updated")
        self.assertFalse(_calls(final, "_DisclosureFence") + _calls(final, "_epoch"))

    def test_native_flight_covers_callback_and_commit(self):
        self.assertTrue(_native_chain_present(self.native_tree))
        fence = _definition(self.native_tree, "_outbox_retry_commit_fence")
        text = ast.unparse(fence)
        for field in ("stage.owner", "stage.conn", "stage.thread", "stage.image", "stage.actor",
                      "stage.references", "stage.policy_environment", "conn.total_changes",
                      "owner._claim_tx_outbox_retry_stage", "conn._outbox_retry_commit_flight"):
            self.assertIn(field, text)
        self.assertFalse(_calls(fence, "execute") + _calls(fence, "admit") + _calls(fence, "_authority"))
        commit = _native_method(self.native_tree, "commit")
        wrapper = _calls(commit, "_graph_native_return")[0]
        self.assertEqual(ast.unparse(wrapper.args[0]), "super().commit")
        self.assertLess(_calls(commit, "_graph_start_commit")[0].lineno, wrapper.lineno)
        self.assertTrue(any(isinstance(n, ast.Assign) and any(
            ast.unparse(t) == "self._outbox_retry_commit_flight" for t in n.targets)
            and isinstance(n.value, ast.Constant) and n.value.value is None
            for node in ast.walk(commit) if isinstance(node, ast.Try) for n in node.finalbody))

    def test_late_callbacks_and_reentrant_completion_are_refused(self):
        start = ast.unparse(_native_method(self.native_tree, "_graph_start_commit"))
        for field in ("_graph_trace", "_graph_progress", "outbox_retry_native_commit_late_callback_unsupported"):
            self.assertIn(field, start)
        authorize = ast.unparse(_native_method(self.native_tree, "_graph_authorizer_result"))
        for field in ("outbox_stage.callbacks_seen = True", "_graph_authorizer_depth", "SQLITE_SAVEPOINT",
                      "a == 'ROLLBACK'", "a == 'COMMIT'", "outbox_flight is None", "'rollback'"):
            self.assertIn(field, authorize)
        for name in ("set_authorizer", "set_trace_callback", "set_progress_handler"):
            text = ast.unparse(_native_method(self.native_tree, name))
            self.assertIn("self._outbox_retry_commit_flight is not None", text)
            self.assertIn("callbacks_seen = True", text)
        self.assertIn("self._outbox_retry_stage is not None", ast.unparse(_native_method(self.native_tree, "close")))
        self.assertIn("outbox_retry_transaction_mode_unsupported", ast.unparse(_native_method(self.native_tree, "__setattr__")))
        self.assertIn("if stage.callbacks_seen:", ast.unparse(_definition(self.native_tree, "_outbox_retry_commit_fence")))

    def test_only_known_completion_retires_and_sets_applied(self):
        tx = _method(self.tree, "_claim_transaction")
        text = ast.unparse(tx)
        self.assertLess(_calls(tx, "commit")[0].lineno, next(node.lineno for node in ast.walk(tx)
            if isinstance(node, ast.Assign) and any(ast.unparse(t) == "_outbox_retry.outcome" for t in node.targets)
            and ast.unparse(node.value) == "'committed'"))
        self.assertIn("'rolled_back' if rolled_back else 'unknown'", text)
        self.assertIn("if completed and getattr(self, '_transaction_quarantine', None) is not c:", text)
        self.assertIn("outbox_retry_retirement_unknown", text)
        handler = next(node for node in ast.walk(tx) if isinstance(node, ast.ExceptHandler)
                       and ast.unparse(node.type) == "BaseException" and _calls(node, "_rollback_claim_transaction"))
        known = handler.body[0]
        self.assertIsInstance(known, ast.If)
        self.assertIn("_outbox_retry.outcome == 'committed'", ast.unparse(known.test))
        self.assertIsInstance(known.body[0], ast.Raise)
        retry = ast.unparse(_method(self.tree, "_repair_failed_outbox"))
        self.assertIn("retry_stage.outcome != 'committed'", retry)
        for fragment in ("'applied': None if unknown else False", "deferred_postcommit_failed", "deferred_notification_failed"):
            self.assertIn(fragment, retry)

    def test_notification_has_only_locked_live_registry_effects(self):
        notify = _definition(self.tree, "_notify_registered_outbox_worker")
        locks = [node for node in ast.walk(notify) if isinstance(node, ast.With)]
        self.assertEqual(len(locks), 1)
        self.assertEqual(ast.unparse(locks[0].items[0].context_expr), "_OUTBOX_WORKERS_LOCK")
        self.assertEqual({call.func.attr for call in ast.walk(notify)
                          if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)}, {"get", "is_alive", "set"})
        self.assertFalse(_calls(notify, "_outbox_db_path") + _calls(notify, "_ensure_outbox")
                         + _calls(notify, "_start_outbox_worker") + _calls(notify, "Thread"))
        self.assertEqual(len(_calls(notify, "is_alive")), 1)
        self.assertEqual(len(_calls(notify, "set")), 1)
        self.assertIn("_OUTBOX_WORKERS.get(path) is not worker", ast.unparse(notify))
        self.assertIn("deferred_no_live_worker", ast.unparse(notify))
        self.assertFalse(any(isinstance(n, ast.Delete) for n in ast.walk(notify)))
        for node in ast.walk(notify):
            if isinstance(node, ast.Assign):
                self.assertTrue(all(isinstance(target, (ast.Name, ast.Tuple)) for target in node.targets))
        for call in _calls(notify, "get"):
            if ast.unparse(call.func.value) == "_OUTBOX_WORKERS":
                self.assertEqual(ast.unparse(call.args[0]), "path")

    def test_removed_native_fence_is_distinguished(self):
        actual = self.native_tree
        control = copy.deepcopy(actual)
        authorize = _native_method(control, "_graph_authorizer_result")
        class RemoveFence(ast.NodeTransformer):
            def visit_Expr(self, node):
                return None if _calls(node, "_outbox_retry_commit_fence") else node
        RemoveFence().visit(authorize)
        self.assertTrue(_native_chain_present(actual))
        self.assertFalse(_native_chain_present(control))


    def test_progress_bookkeeping_is_native_success_bound_and_fail_closed(self):
        self.assertTrue(_progress_reconciliation_present(self.native_tree))
        setter = _native_method(self.native_tree, "set_progress_handler")
        text = ast.unparse(setter)
        self.assertIn("n = operator.index(n)", text)
        self.assertIn("progress = callback if n > 0 else None", text)
        self.assertIn("pending = object()", text)
        self.assertIn("if self._graph_progress is pending:", text)
        effect = _calls(setter, "set_progress_handler")[0]
        # User comparisons cannot run after native installation/clear. A native
        # failure leaves a non-None uncertainty marker, not asserted absence.
        self.assertLess(_calls(setter, "index")[0].lineno, effect.lineno)
        handler = next(n for n in ast.walk(setter) if isinstance(n, ast.ExceptHandler))
        self.assertIn("self._outbox_retry_stage.callbacks_seen = True", ast.unparse(handler))
        owner = ast.unparse(_method(self.tree, "_claim_transaction"))
        self.assertIn("c._graph_user_authorizer, c._graph_trace, c._graph_progress", owner)
        self.assertIn("value is not None", owner)
        start = ast.unparse(_native_method(self.native_tree, "_graph_start_commit"))
        self.assertIn("self._graph_progress is not None", start)
        # The unchanged pure fence consumes the original sticky lifetime; no
        # new SQL/ACL/lease reader or postcommit rollback claim is introduced.
        self.assertIn("if stage.callbacks_seen:", ast.unparse(_definition(self.native_tree, "_outbox_retry_commit_fence")))

    def test_removed_progress_reconciliation_is_distinguished(self):
        self.assertFalse(_progress_reconciliation_present(self.baseline_native_tree))
        control = copy.deepcopy(self.native_tree)
        setter = _native_method(control, "set_progress_handler")
        conversion = next(n for n in setter.body if isinstance(n, ast.Assign)
                          and ast.unparse(n.value) == "operator.index(n)")
        conversion.value = ast.copy_location(ast.Name(id="n", ctx=ast.Load()), conversion.value)
        self.assertTrue(_progress_reconciliation_present(self.native_tree))
        self.assertFalse(_progress_reconciliation_present(control))
        control = copy.deepcopy(self.native_tree)
        handler = next(n for n in ast.walk(_native_method(control, "set_progress_handler"))
                       if isinstance(n, ast.ExceptHandler))
        handler.body[0].value = ast.Constant(value=None)
        self.assertFalse(_progress_reconciliation_present(control))


    def test_current_baseline_retained_guards_are_unchanged(self):
        # CURRENT bodies, not the old donor; no product/helper execution.
        changed = {"__init__", "get_tool_schemas", "handle_tool_call",
                   "_claim_transaction", "_repair_failed_outbox", "_repair", "_transaction"}
        current = _definition(self.tree, "MemoryWikiProvider")
        before = _definition(self.baseline_tree, "MemoryWikiProvider")
        methods = {n.name: n for n in current.body if isinstance(n, ast.FunctionDef)}
        for node in before.body:
            if isinstance(node, ast.FunctionDef) and node.name not in changed:
                self.assertIn(node.name, methods)
                self.assertEqual(ast.dump(node, include_attributes=False),
                                 ast.dump(methods[node.name], include_attributes=False), node.name)
        for node in self.baseline_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name != "MemoryWikiProvider":
                self.assertEqual(ast.dump(node, include_attributes=False),
                                 ast.dump(_definition(self.tree, node.name), include_attributes=False), node.name)
        for name in ("_normalize_topics", "_immune_scan", "_vacuum"):
            calls = _calls(_method(self.tree, "handle_tool_call"), name)
            self.assertEqual(len(calls), 1)
            self.assertIn(("_commit_receipt", "_maintenance_commit"),
                          [(k.arg, ast.unparse(k.value)) for k in calls[0].keywords])

    def test_current_commit_receipt_remains_disjoint_and_native_bound(self):
        tx = _method(self.tree, "_claim_transaction")
        modes = [n for n in tx.body if isinstance(n, ast.If)]
        outbox = next(n for n in modes if "invalid_outbox_retry_transaction_mode" in ast.unparse(n))
        self.assertIn("_commit_receipt", ast.unparse(outbox.test))
        text = ast.unparse(tx)
        for fragment in ("invalid_claim_commit_receipt_mode",
                         "claim_commit_receipt_requires_standalone_owner",
                         "_commit_receipt.append((self, c, document_stage))"):
            self.assertIn(fragment, text)
        receipt = next(n for n in _calls(tx, "append")
                       if ast.unparse(n.func.value) == "_commit_receipt")
        self.assertGreater(receipt.lineno, _calls(tx, "commit")[0].lineno)
        self.assertLess(receipt.lineno, _calls(tx, "_claim_journal_committed")[0].lineno)
        known = ast.unparse(_method(self.tree, "_maintenance_committed_error"))
        for fragment in ("maintenance_postcommit_failed", "canonical_outcome='committed'", "retryable=False"):
            self.assertIn(fragment, known)

    def test_current_schema_and_policy_module_wiring(self):
        imported = [n for n in ast.walk(self.tree) if isinstance(n, ast.Import)]
        imported_from = [n for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)]
        self.assertTrue(any(any(a.name == "outbox_repair_policy" and a.asname == "_outbox_repair_policy"
                                for a in n.names) for n in imported))
        self.assertTrue(any(n.level == 1 and n.module is None
                            and any(a.name == "outbox_repair_policy" and a.asname == "_outbox_repair_policy"
                                    for a in n.names) for n in imported_from))
        graph = [n for n in imported_from if n.module == "code_knowledge_graph"]
        self.assertEqual(len([n for n in graph if any(a.name == "_OutboxRetryStage" for a in n.names)]), 2)
        before, after = _repair_schema(self.baseline_tree), _repair_schema(self.tree)
        self.assertEqual(after["required"], before["required"])
        self.assertEqual({k: v for k, v in after["properties"].items() if k != "outbox_job_ids"}, before["properties"])


    def test_nested_transaction_forwards_literal_ids_in_both_modes(self):
        tx = _method(self.tree, "_transaction")
        calls = _calls(tx, "_repair")
        self.assertEqual(len(calls), 2)
        self.assertEqual({ast.literal_eval(call.args[1]) for call in calls}, {True, False})
        for call in calls:
            keyword = next(k for k in call.keywords if k.arg == "outbox_job_ids")
            self.assertEqual(ast.unparse(keyword.value), "args.get('outbox_job_ids')")
            control = copy.deepcopy(call)
            control.keywords = [k for k in control.keywords if k.arg != "outbox_job_ids"]
            self.assertTrue(_forwarded(call))
            self.assertFalse(_forwarded(control))

    def test_nested_refusal_precedes_success_postprocessing(self):
        tx = _method(self.tree, "_transaction")
        classifier = next(n for n in tx.body if isinstance(n, ast.FunctionDef) and n.name == "_repair_refused")
        text = ast.unparse(classifier)
        self.assertIn("result.get('ok') is False", text)
        self.assertIn("action.get('ok') is False", text)
        self.assertIn("result.get('error')", text)
        self.assertIn("action.get('error')", text)
        self.assertEqual(len(_calls(tx, "_repair_refused")), 2)
        guarded = next(n for n in ast.walk(tx) if isinstance(n, ast.If)
                       and _calls(n.test, "_repair_refused")
                       and any(isinstance(b, ast.Continue) for b in ast.walk(n)))
        self.assertIn("name in ('memory_wiki_repair', 'repair')", ast.unparse(guarded.test))
        self.assertTrue(any(isinstance(b, ast.Break) for b in ast.walk(guarded)))
        after = next(n for n in ast.walk(tx) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "after_count" for t in n.targets))
        self.assertLess(guarded.end_lineno, after.lineno)
        self.assertLess(guarded.end_lineno, _calls(tx, "_record_mutation")[0].lineno)
        self.assertIn("repair_returned_failure", ast.unparse(guarded))


class AddressedOutboxNativeOwnerTests(unittest.TestCase):
    """NOT_RUN real owner component; NOT public admission/semantic target proof.

    After a separate native grant, pass the shipped ci_owned
    derived_claim_materialization_fixture.Fixture with its existing derived_case
    active. Its real provider/SPI/connection are reused, not replaced. The tiny
    table/admission below measures only the NEW owner/native stage contract;
    it deliberately does not impersonate DisclosureFence, ACL or _strict_target.
    """
    __test__ = False
    fixture_factory = None

    @classmethod
    def setUpClass(cls):
        if cls.fixture_factory is None:
            raise RuntimeError("NOT_RUN: separately admitted genuine native fixture required")

    def _seed(self, c):
        import sqlite3
        import sys
        self.assertIs(c.m.MemoryProvider, sys.modules['agent.memory_provider'].MemoryProvider)
        self.assertEqual(c.m.MemoryWikiProvider.__bases__, (c.m.MemoryProvider,))
        self.assertIs(type(c.p), c.m.MemoryWikiProvider)
        self.assertIs(type(c.conn), c.code._GraphCommitConnection)
        self.assertIsInstance(c.conn, sqlite3.Connection)
        self.assertIs(c.conn, c.p._conn)
        self.assertIs(c.conn, c.p._owned_conn)
        self.assertTrue(c.path.resolve().is_relative_to(c.home.resolve()))
        with c.p._claim_transaction(c.conn):
            c.conn.execute('CREATE TABLE correction01_retry_native(value TEXT NOT NULL)')
            c.conn.execute("INSERT INTO correction01_retry_native VALUES('before')")

    def _durable(self, c):
        import sqlite3
        reader = sqlite3.connect(c.path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            return reader.execute('SELECT value FROM correction01_retry_native').fetchall()
        finally:
            reader.close()

    def _stage(self, c):
        expected, actor = c.conn.total_changes + 1, c.p.session_id
        calls = []
        def original_admission():
            if c.p.session_id != actor:
                raise PermissionError('original_session_changed')
            self.assertEqual(c.conn.execute('SELECT value FROM correction01_retry_native').fetchone()[0], 'after')
            self.assertEqual(c.conn.total_changes, expected)
            calls.append('original_admission')
            return expected
        return c.code._OutboxRetryStage(c.p, c.conn, original_admission), calls

    def _update(self, c):
        self.assertEqual(c.conn.execute("UPDATE correction01_retry_native SET value='after'").rowcount, 1)

    def _retired(self, c, stage, outcome):
        self.assertEqual(stage.outcome, outcome)
        self.assertEqual(stage.phase, 'retired')
        self.assertFalse(c.conn.in_transaction)
        self.assertIsNone(c.p._transaction_quarantine)
        self.assertIsNone(c.p._claim_tx_connection)
        self.assertIsNone(c.p._claim_tx_outbox_retry_stage)
        self.assertIsNone(c.conn._outbox_retry_stage)
        self.assertIsNone(c.conn._outbox_retry_commit_image)
        self.assertIsNone(c.conn._outbox_retry_commit_flight)

    def test_callback_free_real_owner_commits_and_retires(self):
        with self.fixture_factory('outbox-correction01-native-healthy') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                self._update(c)
                self.assertEqual(self._durable(c), [('before',)])
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('after',)])
            self._retired(c, stage, 'committed')

    def test_late_journal_actor_change_refuses_original_admission(self):
        with self.fixture_factory('outbox-correction01-journal-actor') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            actor, pending = c.p.session_id, c.p._claim_journal_pending_commit
            def late(conn):
                image = pending(conn)
                c.p.session_id = 'late-withdrawn-actor'
                return image
            c._mp.setattr(c.p, '_claim_journal_pending_commit', late)
            try:
                with self.assertRaisesRegex(PermissionError, '^original_session_changed$'):
                    with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                        self._update(c)
                self.assertFalse(calls)
                self.assertEqual(self._durable(c), [('before',)])
                self._retired(c, stage, 'rolled_back')
            finally:
                c.p.session_id = actor
                c._mp.setattr(c.p, '_claim_journal_pending_commit', pending)

    def test_real_authorizer_lifetime_is_refused_not_disabled(self):
        import sqlite3
        with self.fixture_factory('outbox-correction01-native-authorizer') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            seen = []
            def authorizer(action, first, second, database, trigger):
                seen.append((action, first))
                return sqlite3.SQLITE_OK
            c.conn.set_authorizer(authorizer)
            try:
                with self.assertRaisesRegex(RuntimeError, '^outbox_retry_native_callback_lifetime_unsupported$'):
                    with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                        self._update(c)
                self.assertTrue(seen and calls)
                # Explicit early native refusal is truthful: do not claim that
                # this case executed a last SQLITE_TRANSACTION/COMMIT callback.
                self.assertNotIn((sqlite3.SQLITE_TRANSACTION, 'COMMIT'), seen)
                self.assertIs(c.conn._graph_user_authorizer, authorizer)
                self.assertEqual(self._durable(c), [('before',)])
                self._retired(c, stage, 'rolled_back')
                # Same real authorizer still works for ordinary nonoutbox TX.
                with c.p._claim_transaction(c.conn):
                    self._update(c)
                self.assertIn((sqlite3.SQLITE_TRANSACTION, 'COMMIT'), seen)
            finally:
                c.conn.set_authorizer(None)

    def test_late_trace_install_remove_cannot_hide_callback_lifetime(self):
        with self.fixture_factory('outbox-correction01-sticky-trace') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            trace = []
            with self.assertRaisesRegex(RuntimeError, '^outbox_retry_native_callback_lifetime_unsupported$'):
                with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                    self._update(c)
                    c.conn.set_trace_callback(trace.append)
                    c.conn.execute('SELECT 1').fetchone()
                    c.conn.set_trace_callback(None)
            self.assertTrue(trace and calls and stage.callbacks_seen)
            self.assertIsNone(c.conn._graph_trace)
            self.assertEqual(self._durable(c), [('before',)])
            self._retired(c, stage, 'rolled_back')

    def test_premature_completion_and_mode_close_shortcuts_are_refused(self):
        import sqlite3
        with self.fixture_factory('outbox-correction01-native-shortcuts') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            cursor = c.conn.cursor()
            try:
                with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                    self._update(c)
                    operations = (c.conn.commit, c.conn.rollback, c.conn.close,
                                  lambda: c.conn.execute('COMMIT'), lambda: cursor.execute('END'),
                                  lambda: c.conn.executescript('SELECT 1;'),
                                  lambda: setattr(c.conn, 'isolation_level', None),
                                  lambda: c.conn.execute('SAVEPOINT correction01'))
                    for operation in operations:
                        with self.assertRaises((RuntimeError, PermissionError, sqlite3.DatabaseError)):
                            operation()
                    self.assertEqual(self._durable(c), [('before',)])
            finally:
                cursor.close()
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('after',)])
            self._retired(c, stage, 'committed')

    def test_fatal_before_commit_preserves_identity_and_known_rollback(self):
        class Cancel(BaseException):
            pass
        with self.fixture_factory('outbox-correction01-native-fatal') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            primary = Cancel('original-fatal')
            pending = c.p._claim_journal_pending_commit
            def late(conn):
                raise primary
            c._mp.setattr(c.p, '_claim_journal_pending_commit', late)
            try:
                with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                    self._update(c)
            except BaseException as caught:
                self.assertIs(caught, primary)
            else:
                self.fail('fatal primary was swallowed')
            finally:
                c._mp.setattr(c.p, '_claim_journal_pending_commit', pending)
            self.assertFalse(calls)
            self.assertEqual(self._durable(c), [('before',)])
            self._retired(c, stage, 'rolled_back')

    def test_postcommit_fatal_preserves_known_commit_not_false_rollback(self):
        class Cancel(BaseException):
            pass
        with self.fixture_factory('outbox-correction01-native-postcommit-fatal') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            primary = Cancel('known-commit-postcommit-fatal')
            committed = c.p._claim_journal_committed
            def after(image):
                raise primary
            c._mp.setattr(c.p, '_claim_journal_committed', after)
            try:
                with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                    self._update(c)
            except BaseException as caught:
                self.assertIs(caught, primary)
            else:
                self.fail('fatal postcommit primary was swallowed')
            finally:
                c._mp.setattr(c.p, '_claim_journal_committed', committed)
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('after',)])
            self._retired(c, stage, 'committed')


    def test_absent_dead_worker_notification_has_no_whole_store_maintenance(self):
        import sqlite3
        import threading
        with self.fixture_factory('outbox-correction01-notify-absence') as c:
            self._seed(c)
            # Unaddressed legacy payload: the OLD starter would scrub $.text
            # on its absent/dead-worker branch. No worker is started here.
            with c.p._claim_transaction(c.conn):
                c.conn.execute('''INSERT INTO index_outbox
                    (id,operation,object_type,object_id,payload_json,payload_hash,attempts,status,
                     last_error,created_at,updated_at,worker_id,lease_until,next_retry_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    ('ffffffffffffff01', 'embed_and_upsert', 'claim', 'unaddressed-fixture-object',
                     '{"collection":"old-physical","text":"legacy-retained-sentinel"}',
                     None, 3, 'completed', 'retained-error', 1, 2, '', 0, 0))
            def whole_state():
                reader = sqlite3.connect(c.path.resolve().as_uri() + '?mode=ro', uri=True)
                try:
                    tables = [row[0] for row in reader.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                    return {name: sorted(reader.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
                            for name in tables}
                finally:
                    reader.close()
            path = str(c.path.resolve())
            with c.m._OUTBOX_WORKERS_LOCK:
                self.assertNotIn(path, c.m._OUTBOX_WORKERS)
            before, counter = whole_state(), c.conn.total_changes
            self.assertEqual(c.m._notify_registered_outbox_worker(path), 'deferred_no_live_worker')
            self.assertEqual(whole_state(), before)
            self.assertEqual(c.conn.total_changes, counter)
            dead = {'thread': threading.Thread(), 'wake': threading.Event(), 'worker_id': 'own-never-started'}
            with c.m._OUTBOX_WORKERS_LOCK:
                c.m._OUTBOX_WORKERS[path] = dead
            try:
                self.assertEqual(c.m._notify_registered_outbox_worker(path), 'deferred_no_live_worker')
                self.assertFalse(dead['wake'].is_set())
                self.assertFalse(dead['thread'].is_alive())
                self.assertEqual(whole_state(), before)
                self.assertEqual(c.conn.total_changes, counter)
                with c.m._OUTBOX_WORKERS_LOCK:
                    self.assertIs(c.m._OUTBOX_WORKERS[path], dead)
            finally:
                with c.m._OUTBOX_WORKERS_LOCK:
                    if c.m._OUTBOX_WORKERS.get(path) is dead:
                        del c.m._OUTBOX_WORKERS[path]


    def test_failed_progress_clear_before_stage_refuses_and_rolls_back(self):
        with self.fixture_factory('outbox-correction02-failed-clear-before-stage') as c:
            self._seed(c)
            seen = []
            def progress():
                seen.append('progress')
                return 0
            c.conn.set_progress_handler(progress, 1)
            try:
                # The confirmed premise: native C-int conversion rejects this
                # clear BEFORE registration changes, with H already installed.
                with self.assertRaises(OverflowError):
                    c.conn.set_progress_handler(None, 10**100)
                self.assertIsNotNone(c.conn._graph_progress)
                seen.clear()
                c.conn.execute('SELECT value FROM correction01_retry_native').fetchall()
                self.assertTrue(seen, 'native H was silently removed')
                stage, calls = self._stage(c)
                with self.assertRaisesRegex(RuntimeError, '^outbox_retry_native_commit_late_callback_unsupported$'):
                    with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                        self._update(c)
                        self.assertTrue(stage.callbacks_seen)
                self.assertEqual(calls, ['original_admission'])
                self.assertEqual(self._durable(c), [('before',)])
                self._retired(c, stage, 'rolled_back')
                before = len(seen)
                c.conn.execute('SELECT 1').fetchone()
                self.assertGreater(len(seen), before)
            finally:
                c.conn.set_progress_handler(None, 0)

    def test_successful_progress_clear_reconciles_before_stage(self):
        with self.fixture_factory('outbox-correction02-successful-clear') as c:
            self._seed(c)
            seen = []
            def progress():
                seen.append('progress')
                return 0
            c.conn.set_progress_handler(progress, 1)
            with self.assertRaises(OverflowError):
                c.conn.set_progress_handler(None, 10**100)
            self.assertIsNotNone(c.conn._graph_progress)
            # callback=None clears even with a positive, representable count.
            self.assertIsNone(c.conn.set_progress_handler(None, 1))
            self.assertIsNone(c.conn._graph_progress)
            seen.clear()
            stage, calls = self._stage(c)
            with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                self._update(c)
                self.assertFalse(stage.callbacks_seen)
            self.assertFalse(seen)
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('after',)])
            self._retired(c, stage, 'committed')

    def test_progress_install_remove_is_sticky_inside_stage(self):
        with self.fixture_factory('outbox-correction02-sticky-progress') as c:
            self._seed(c)
            seen = []
            def progress():
                seen.append('progress')
                return 0
            stage, calls = self._stage(c)
            try:
                with self.assertRaisesRegex(RuntimeError, '^outbox_retry_native_callback_lifetime_unsupported$'):
                    with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                        self._update(c)
                        c.conn.set_progress_handler(progress, 1)
                        c.conn.execute('SELECT 1').fetchone()
                        c.conn.set_progress_handler(None, 0)
                self.assertTrue(seen and stage.callbacks_seen)
                self.assertIsNone(c.conn._graph_progress)
                self.assertEqual(calls, ['original_admission'])
                self.assertEqual(self._durable(c), [('before',)])
                self._retired(c, stage, 'rolled_back')
            finally:
                c.conn.set_progress_handler(None, 0)

    def test_ordinary_progress_callback_survives_failed_clear(self):
        with self.fixture_factory('outbox-correction02-ordinary-progress') as c:
            self._seed(c)
            seen = []
            def progress():
                seen.append('progress')
                return 0
            c.conn.set_progress_handler(progress, 1)
            try:
                with self.assertRaises(OverflowError):
                    c.conn.set_progress_handler(None, 10**100)
                seen.clear()
                # Noncritical ordinary TX still uses the REAL installed H.
                with c.p._claim_transaction(c.conn):
                    self._update(c)
                self.assertTrue(seen)
                self.assertIsNotNone(c.conn._graph_progress)
                self.assertEqual(self._durable(c), [('after',)])
                self.assertIsNone(c.p._claim_tx_connection)
                self.assertIsNone(c.p._transaction_quarantine)
            finally:
                c.conn.set_progress_handler(None, 0)

    def test_progress_index_and_bool_use_effective_native_count(self):
        class Count:
            calls = 0
            def __index__(self):
                self.calls += 1
                return 1
            def __gt__(self, other):
                raise AssertionError('user comparison is not native index conversion')
        class IntCount(int):
            def __gt__(self, other):
                raise AssertionError('int-subclass comparison must not run')
            def __index__(self):
                raise AssertionError('native int conversion ignores subclass override')
        indexed = Count()
        for label, n in (('bool', True), ('index', indexed), ('int-subclass', IntCount(1))):
            with self.subTest(kind=label), self.fixture_factory('outbox-correction02-count-' + label) as c:
                self._seed(c)
                seen = []
                def progress():
                    seen.append('progress')
                    return 0
                try:
                    self.assertIsNone(c.conn.set_progress_handler(progress, n))
                    self.assertIs(c.conn._graph_progress, progress)
                    c.conn.execute('SELECT 1').fetchone()
                    self.assertTrue(seen)
                    if n is indexed:
                        self.assertEqual(indexed.calls, 1)
                finally:
                    c.conn.set_progress_handler(None, 0)
                stage, calls = self._stage(c)
                with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                    self._update(c)
                self.assertEqual(calls, ['original_admission'])
                self.assertEqual(self._durable(c), [('after',)])
                self._retired(c, stage, 'committed')

    def test_progress_nonpositive_counts_are_callback_free(self):
        class Count:
            def __init__(self, value):
                self.value, self.calls = value, 0
            def __index__(self):
                self.calls += 1
                return self.value
            def __gt__(self, other):
                raise AssertionError('must use effective native count')
        for index, n in enumerate((0, -1, False, Count(0), Count(-7))):
            with self.subTest(index=index), self.fixture_factory('outbox-correction02-nonpositive-' + str(index)) as c:
                self._seed(c)
                seen = []
                def progress():
                    seen.append('progress')
                    return 0
                c.conn.set_progress_handler(progress, 1)
                try:
                    # Non-None callback with effective n <= 0 is disabled by
                    # SQLite, not a callback installed for the critical stage.
                    self.assertIsNone(c.conn.set_progress_handler(progress, n))
                    self.assertIsNone(c.conn._graph_progress)
                    if isinstance(n, Count):
                        self.assertEqual(n.calls, 1)
                    seen.clear()
                    stage, calls = self._stage(c)
                    with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                        self._update(c)
                    self.assertFalse(seen or stage.callbacks_seen)
                    self.assertEqual(calls, ['original_admission'])
                    self.assertEqual(self._durable(c), [('after',)])
                    self._retired(c, stage, 'committed')
                finally:
                    c.conn.set_progress_handler(None, 0)

    def test_invalid_progress_counts_preserve_registration(self):
        class IntOnly:
            def __int__(self):
                return 1
        class BadIndex:
            def __index__(self):
                return '1'
        with self.fixture_factory('outbox-correction02-invalid-counts') as c:
            self._seed(c)
            seen = []
            def progress():
                seen.append('progress')
                return 0
            try:
                for n, error in ((1.0, TypeError), ('1', TypeError), (None, TypeError),
                                 (IntOnly(), TypeError), (BadIndex(), TypeError),
                                 (10**100, OverflowError), (-(10**100), OverflowError)):
                    with self.subTest(kind=type(n).__name__, error=error.__name__):
                        c.conn.set_progress_handler(progress, 1)
                        with self.assertRaises(error):
                            c.conn.set_progress_handler(None, n)
                        self.assertIsNotNone(c.conn._graph_progress)
                        seen.clear()
                        c.conn.execute('SELECT 1').fetchone()
                        self.assertTrue(seen)
            finally:
                c.conn.set_progress_handler(None, 0)

    def test_fatal_progress_index_preserves_identity_and_known_rollback(self):
        class Cancel(BaseException):
            pass
        primary = Cancel('original-progress-index-fatal')
        class FatalIndex:
            def __index__(self):
                raise primary
            def __gt__(self, other):
                raise AssertionError('wrong conversion path')
        with self.fixture_factory('outbox-correction02-fatal-index') as c:
            self._seed(c)
            seen = []
            def progress():
                seen.append('progress')
                return 0
            c.conn.set_progress_handler(progress, 1)
            stage, calls = self._stage(c)
            try:
                try:
                    with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                        self._update(c)
                        c.conn.set_progress_handler(None, FatalIndex())
                except BaseException as caught:
                    self.assertIs(caught, primary)
                else:
                    self.fail('fatal conversion primary was swallowed')
                self.assertIs(c.conn._graph_progress, progress)
                self.assertTrue(seen)
                self.assertFalse(calls)
                self.assertEqual(self._durable(c), [('before',)])
                self._retired(c, stage, 'rolled_back')
            finally:
                c.conn.set_progress_handler(None, 0)
            # A successful clear and a fresh stage retain the healthy path.
            stage, calls = self._stage(c)
            with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                self._update(c)
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('after',)])
            self._retired(c, stage, 'committed')

    def test_failed_progress_clear_inside_stage_stays_sticky_after_clear(self):
        with self.fixture_factory('outbox-correction02-sticky-unknown-progress') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            with self.assertRaisesRegex(RuntimeError, '^outbox_retry_native_callback_lifetime_unsupported$'):
                with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                    self._update(c)
                    self.assertFalse(stage.callbacks_seen)
                    with self.assertRaises(OverflowError):
                        c.conn.set_progress_handler(None, 10**100)
                    self.assertIsNotNone(c.conn._graph_progress)
                    self.assertTrue(stage.callbacks_seen)
                    c.conn.set_progress_handler(None, 0)
                    self.assertIsNone(c.conn._graph_progress)
                    self.assertTrue(stage.callbacks_seen)
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('before',)])
            self._retired(c, stage, 'rolled_back')


    def test_current_commit_receipt_mode_is_not_borrowed_by_retry(self):
        with self.fixture_factory('current-outbox-commit-receipt-exclusion') as c:
            self._seed(c)
            stage, calls = self._stage(c)
            receipt = []
            with self.assertRaisesRegex(ValueError, '^invalid_outbox_retry_transaction_mode$'):
                with c.p._claim_transaction(c.conn, _outbox_retry=stage, _commit_receipt=receipt):
                    self.fail('mixed owner mode entered')
            self.assertEqual(receipt, [])
            self.assertEqual(calls, [])
            self.assertEqual(stage.phase, 'prepared')
            self.assertIsNone(stage.outcome)
            self.assertIsNone(c.p._claim_tx_connection)
            self.assertFalse(c.conn.in_transaction)
            self.assertEqual(self._durable(c), [('before',)])
            with c.p._claim_transaction(c.conn, _outbox_retry=stage):
                self._update(c)
            self.assertEqual(calls, ['original_admission'])
            self.assertEqual(self._durable(c), [('after',)])
            self._retired(c, stage, 'committed')

    def test_current_ordinary_commit_receipt_still_observes_real_owner(self):
        with self.fixture_factory('current-outbox-ordinary-commit-receipt') as c:
            self._seed(c)
            receipt = []
            with c.p._claim_transaction(c.conn, _commit_receipt=receipt):
                self._update(c)
                self.assertEqual(receipt, [])
                self.assertEqual(self._durable(c), [('before',)])
            self.assertEqual(len(receipt), 1)
            provider, conn, stage = receipt[0]
            self.assertIs(provider, c.p)
            self.assertIs(conn, c.conn)
            self.assertIs(stage[0], c.conn)
            self.assertEqual(stage[2], [])
            self.assertEqual(self._durable(c), [('after',)])
            self.assertFalse(c.conn.in_transaction)
            self.assertIsNone(c.p._claim_tx_connection)
            self.assertIsNone(c.p._claim_tx_outbox_retry_stage)
            self.assertIsNone(c.conn._outbox_retry_stage)
            self.assertIsNone(c.p._transaction_quarantine)


def make_native_owner_suite(fixture_factory):
    """ONLY with separate native/SQL/SPI admission and existing fixture setup."""
    class BoundNativeOwnerTests(AddressedOutboxNativeOwnerTests):
        pass
    BoundNativeOwnerTests.fixture_factory = staticmethod(fixture_factory)
    return unittest.TestSuite(BoundNativeOwnerTests(name) for name in NATIVE_OWNER_CASE_IDS)


def make_policy_suite(policy):
    """Call ONLY behind the existing separately admitted SOURCE bootstrap."""
    class BoundPolicyTests(AddressedOutboxPolicyTests):
        pass
    BoundPolicyTests.policy = policy
    return unittest.TestSuite(BoundPolicyTests(name) for name in POLICY_CASE_IDS)


def make_metadata_suite(main_raw, cache_raw, baseline_main_raw, baseline_cache_raw, *, native_raw, baseline_native_raw):
    """Raw CURRENT bytes -> AST/JSON; never execute the provider.

    Baseline arguments are exact current 4b/ac8, not interchangeable donor bytes.
    """
    for path, raw in (("__init__.py", baseline_main_raw),
                      ("mcp-wrapper/tool_schemas.json", baseline_cache_raw),
                      ("code_knowledge_graph.py", baseline_native_raw)):
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != CURRENT_BASELINE_SHA256[path]:
            raise ValueError("outbox_current_baseline_binding_mismatch:" + path)
    class BoundMetadataTests(AddressedOutboxMetadataTests):
        pass
    BoundMetadataTests.tree = ast.parse(main_raw)
    BoundMetadataTests.cache = json.loads(cache_raw)
    BoundMetadataTests.baseline_tree = ast.parse(baseline_main_raw)
    BoundMetadataTests.baseline_cache = json.loads(baseline_cache_raw)
    BoundMetadataTests.native_tree = ast.parse(native_raw)
    BoundMetadataTests.baseline_native_tree = ast.parse(baseline_native_raw)
    return unittest.TestSuite(BoundMetadataTests(name) for name in METADATA_CASE_IDS)


NESTED_CALLER_CASE_IDS = (
    "test_nested_healthy_literal_ids_modes_and_aliases",
    "test_nested_typed_and_action_refusals_skip_success_tail",
    "test_nested_wrong_target_top_level_error_is_failure",
    "test_public_envelope_and_real_journal_classifier_compose",
    "test_ordinary_repair_without_ids_remains_healthy",
    "test_ordinary_nonrepair_suggest_best_effort_is_preserved",
    "test_multi_apply_repair_still_refused_before_any_effect",
    "test_ordinary_atomic_claim_batch_preserves_both_policies",
    "test_nested_fatal_primary_is_not_collected_as_ordinary_error",
)


class AddressedOutboxNestedCallerTests(unittest.TestCase):
    """PREPARED / NOT_RUN genuine owning loops and dispatcher/classifier.

    Use the SAME separately admitted derived_case/Fixture as the owner suite.
    No extracted/fake provider class or substitute transaction/journal loop.
    Authored retry/FTS/claim outcomes and audit/mutation/journal IO recorders are
    explicit seams. Native SQL, locks, SDK, ACL, public entry and _repair remain
    genuine. These controls do NOT qualify the replaced retry admission/COMMIT,
    durable journal IO, real target or any of the seven public-native obligations.
    """
    __test__ = False
    fixture_factory = None

    @classmethod
    def setUpClass(cls):
        if cls.fixture_factory is None:
            raise RuntimeError("NOT_RUN: separately admitted genuine fixture required")

    def _prepare(self, c):
        import sys
        self.assertIs(type(c.p), c.m.MemoryWikiProvider)
        self.assertIs(c.m.MemoryProvider, sys.modules['agent.memory_provider'].MemoryProvider)
        self.assertIs(c.m.tool_result, sys.modules['tools.registry'].tool_result)
        self.assertIs(c.conn, c.p._owned_conn)
        self.assertFalse(c.conn.in_transaction)
        for name in ('_transaction', '_repair', 'handle_tool_call', '_should_journal_tool',
                     '_journal_operation', '_journal_operation_locked', '_journal_operation_captured_locked'):
            self.assertIs(getattr(c.p, name).__func__, getattr(c.m.MemoryWikiProvider, name))
        events = []
        original_connect = c.p._connect
        def connect(*args, **kwargs):
            events.append(('connect',))
            return original_connect(*args, **kwargs)
        def audit(operation, status, detail):
            events.append(('audit', operation, status))
        def mutation(*args, **kwargs):
            events.append(('mutation',))
            return 'prepared-mutation-id'
        def append(operation, payload, *, phase, **kwargs):
            events.append(('journal', phase))
            return {'seq': sum(e[0] == 'journal' for e in events)}
        def checkpoint(*args, **kwargs):
            events.append(('checkpoint',))
            return {}
        # IO seams only; actual original _connect is always called.
        c._mp.setattr(c.p, '_connect', connect)
        c._mp.setattr(c.p, '_audit', audit)
        c._mp.setattr(c.p, '_record_mutation', mutation)
        c._mp.setattr(c.p, '_append_journal_event', append)
        c._mp.setattr(c.p, '_checkpoint_after_journal_mutation', checkpoint)
        return events

    def _operation(self, alias, ids, target='outbox'):
        return {'tool': alias, 'args': {'target': target, 'outbox_job_ids': ids}}

    def _assert_outcome(self, outcome, events, *, failed, dry_run):
        self.assertEqual(outcome['mode'], 'suggest' if dry_run else 'apply')
        self.assertFalse(outcome['atomic'])
        self.assertEqual(outcome['partial_commit_possible'], not dry_run)
        self.assertEqual(len(outcome['results']), 1)
        row = outcome['results'][0]
        self.assertEqual(row['result']['target'], 'outbox')
        self.assertEqual(row['result']['dry_run'], dry_run)
        self.assertEqual(outcome['errors'], [row] if failed else [])
        self.assertEqual([e for e in events if e[0] == 'audit'],
                         [('audit', 'transaction', 'partial' if failed else 'ok')])
        if failed:
            self.assertEqual(row['error'], 'repair_returned_failure')
            self.assertNotIn('mutation_id', row)
            self.assertNotIn(('mutation',), events)
            retry = next(i for i, e in enumerate(events) if e[0] == 'retry')
            audit = next(i for i, e in enumerate(events) if e[0] == 'audit')
            self.assertNotIn(('connect',), events[retry + 1:audit])
        else:
            self.assertNotIn('error', row)
            self.assertEqual('mutation_id' in row, not dry_run)
            self.assertEqual(events.count(('mutation',)), int(not dry_run))

    def test_nested_healthy_literal_ids_modes_and_aliases(self):
        with self.fixture_factory('nested-healthy') as c:
            events = self._prepare(c)
            def retry(dry_run=True, *, outbox_job_ids=None):
                events.append(('retry', dry_run, outbox_job_ids))
                return {'ok': True, 'applied': not dry_run, 'revived_count': int(not dry_run)}
            c._mp.setattr(c.p, '_repair_failed_outbox', retry)
            for mode in ('suggest', 'apply'):
                for alias in ('repair', 'memory_wiki_repair'):
                    ids = ['fedcba9876543210', '0123456789abcdef']
                    before = list(ids)
                    events.clear()
                    with self.subTest(mode=mode, alias=alias):
                        result = c.p._transaction([self._operation(alias, ids)], mode, model_scope=True)
                        self._assert_outcome(result, events, failed=False, dry_run=mode == 'suggest')
                        calls = [e for e in events if e[0] == 'retry']
                        self.assertEqual(len(calls), 1)
                        self.assertIs(calls[0][2], ids)
                        self.assertEqual(calls[0][1], mode == 'suggest')
                        self.assertEqual(ids, before)
                        self.assertEqual(result['results'][0]['operation'], alias)

    def test_nested_typed_and_action_refusals_skip_success_tail(self):
        with self.fixture_factory('nested-refusal') as c:
            events = self._prepare(c)
            state = {}
            def retry(dry_run=True, *, outbox_job_ids=None):
                events.append(('retry', dry_run, outbox_job_ids))
                return dict(state)
            c._mp.setattr(c.p, '_repair_failed_outbox', retry)
            for refusal in ({'ok': False, 'applied': False},
                            {'error': 'prepared-typed-refusal'},
                            {'ok': True, 'error': 'prepared-action-error'}):
                state.clear()
                state.update(refusal)
                for mode in ('suggest', 'apply'):
                    for alias in ('repair', 'memory_wiki_repair'):
                        for stop in (False, True):
                            ids = ['0123456789abcdef']
                            events.clear()
                            with self.subTest(refusal=refusal, mode=mode, alias=alias, stop=stop):
                                result = c.p._transaction([self._operation(alias, ids)], mode,
                                                         stop_on_error=stop, model_scope=True)
                                self._assert_outcome(result, events, failed=True, dry_run=mode == 'suggest')
                                self.assertIs(result['stop_on_error'], stop)
                                self.assertIs(next(e for e in events if e[0] == 'retry')[2], ids)
                                action = result['results'][0]['result']['actions'][0]
                                for key, value in refusal.items():
                                    self.assertEqual(action[key], value)

    def test_nested_wrong_target_top_level_error_is_failure(self):
        with self.fixture_factory('nested-wrong-target') as c:
            events = self._prepare(c)
            for mode in ('suggest', 'apply'):
                for alias in ('repair', 'memory_wiki_repair'):
                    events.clear()
                    with self.subTest(mode=mode, alias=alias):
                        result = c.p._transaction([self._operation(alias, ['0123456789abcdef'], 'fts')], mode)
                        row = result['results'][0]
                        self.assertEqual(result['errors'], [row])
                        self.assertEqual(row['error'], 'repair_returned_failure')
                        self.assertEqual(row['result']['error'], 'outbox_job_ids_only_for_outbox')
                        self.assertNotIn('mutation_id', row)
                        self.assertEqual(events.count(('connect',)), int(mode == 'apply'))
                        self.assertEqual(events[-1], ('audit', 'transaction', 'partial'))
                        self.assertNotIn(('mutation',), events)

    def test_public_envelope_and_real_journal_classifier_compose(self):
        with self.fixture_factory('nested-public-journal') as c:
            events = self._prepare(c)
            state = {'failed': False}
            def retry(dry_run=True, *, outbox_job_ids=None):
                events.append(('retry', dry_run, outbox_job_ids))
                return {'ok': not state['failed'], 'applied': not dry_run and not state['failed']}
            c._mp.setattr(c.p, '_repair_failed_outbox', retry)
            for failed in (False, True):
                state['failed'] = failed
                for mode in ('suggest', 'apply'):
                    for alias in ('repair', 'memory_wiki_repair'):
                        ids = ['fedcba9876543210', '0123456789abcdef']
                        args = {'operations': [self._operation(alias, ids)], 'mode': mode}
                        events.clear()
                        with self.subTest(failed=failed, mode=mode, alias=alias):
                            self.assertEqual(c.p._should_journal_tool('memory_wiki_transaction', args), mode == 'apply')
                            envelope = c.p.handle_tool_call('memory_wiki_transaction', args)
                            result = c.p._journal_result_dict(envelope)
                            self.assertIs(result['success'], not failed)
                            self._assert_outcome(result, events, failed=failed, dry_run=mode == 'suggest')
                            self.assertIs(next(e for e in events if e[0] == 'retry')[2], ids)
                            phases = [e[1] for e in events if e[0] == 'journal']
                            self.assertEqual(phases, [] if mode == 'suggest' else
                                             ['before', 'error' if failed else 'after'])
                            self.assertEqual(events.count(('checkpoint',)), int(mode == 'apply' and not failed))

    def test_ordinary_repair_without_ids_remains_healthy(self):
        with self.fixture_factory('nested-ordinary-repair') as c:
            events = self._prepare(c)
            def rebuild():
                events.append(('rebuild',))
            c._mp.setattr(c.p, '_rebuild_fts', rebuild)
            for mode in ('suggest', 'apply'):
                for alias in ('repair', 'memory_wiki_repair'):
                    events.clear()
                    with self.subTest(mode=mode, alias=alias):
                        result = c.p._transaction([{'operation': alias, 'args': {'target': 'fts'}}], mode)
                        self.assertEqual(result['errors'], [])
                        self.assertNotIn('ok', result['results'][0]['result'])
                        self.assertEqual(result['results'][0]['result']['actions'],
                                         [{'action': 'rebuild_claims_fts', 'applied': mode == 'apply'}])
                        self.assertEqual(events.count(('rebuild',)), int(mode == 'apply'))
                        self.assertEqual(events.count(('mutation',)), int(mode == 'apply'))
                        self.assertEqual(events[-1], ('audit', 'transaction', 'ok'))

    def test_ordinary_nonrepair_suggest_best_effort_is_preserved(self):
        with self.fixture_factory('nested-ordinary-suggest') as c:
            events = self._prepare(c)
            def compile_topic(topic, *args, **kwargs):
                events.append(('compile', topic))
                if topic == 'bad':
                    raise ValueError('authored ordinary failure')
                return {'topic': topic, 'ok': True}
            c._mp.setattr(c.p, '_compile_topic', compile_topic)
            operations = [{'tool': 'compile_topic', 'args': {'topic': topic}} for topic in ('bad', 'good')]
            for stop in (False, True):
                events.clear()
                with self.subTest(stop=stop):
                    result = c.p._transaction(operations, 'suggest', stop_on_error=stop)
                    self.assertEqual([r['operation'] for r in result['results']], ['compile_topic'] * 2)
                    self.assertEqual(result['results'][0]['error'], 'ValueError')
                    self.assertEqual(result['results'][1]['result'], {'topic': 'good', 'ok': True})
                    self.assertEqual(result['errors'], [result['results'][0]])
                    self.assertEqual([e for e in events if e[0] == 'compile'], [('compile', 'bad'), ('compile', 'good')])
                    self.assertNotIn(('mutation',), events)
                    self.assertEqual(events[-1], ('audit', 'transaction', 'partial'))

    def test_multi_apply_repair_still_refused_before_any_effect(self):
        with self.fixture_factory('nested-multi-deny') as c:
            events = self._prepare(c)
            for alias in ('repair', 'memory_wiki_repair'):
                for stop in (False, True):
                    events.clear()
                    with self.subTest(alias=alias, stop=stop):
                        operations = [self._operation(alias, ['0123456789abcdef']), {'tool': 'update_claim'}]
                        result = c.p._transaction(operations, 'apply', stop_on_error=stop)
                        self.assertEqual(result['errors'], [{'error': 'unsupported_atomic_transaction_operation'}])
                        self.assertEqual(result['results'], [])
                        self.assertFalse(result['partial_commit_possible'])
                        self.assertEqual(events, [])

    def test_ordinary_atomic_claim_batch_preserves_both_policies(self):
        with self.fixture_factory('nested-ordinary-atomic') as c:
            events = self._prepare(c)
            operations = [{'tool': 'update_claim', 'args': {'claim_id': cid}} for cid in ('a', 'b')]
            state = {'failed': False}
            def atomic(ops, batch_id, reason):
                self.assertEqual(ops, operations)
                self.assertEqual(reason, 'prepared-reason')
                events.append(('atomic',))
                if state['failed']:
                    raise ValueError('authored atomic refusal')
                return {'results': [{'operation': 'update_claim', 'id': cid} for cid in ('a', 'b')],
                        'changed_claim_ids': ['a', 'b'], 'render_error': None}
            c._mp.setattr(c.p, '_atomic_claim_batch', atomic)
            for failed in (False, True):
                state['failed'] = failed
                for stop in (False, True):
                    events.clear()
                    with self.subTest(failed=failed, stop=stop):
                        result = c.p._transaction(operations, 'apply', 'prepared-reason', stop)
                        self.assertTrue(result['atomic'])
                        self.assertIs(result['rolled_back'], failed)
                        self.assertFalse(result['partial_commit_possible'])
                        self.assertEqual(result['errors'], [{'error': 'ValueError'}] if failed else [])
                        self.assertEqual(events.count(('atomic',)), 1)
                        self.assertNotIn(('mutation',), events)
                        if failed:
                            self.assertEqual(result['results'], [])
                            self.assertFalse(any(e[0] == 'audit' for e in events))
                        else:
                            self.assertEqual(result['changed_claim_ids'], ['a', 'b'])
                            self.assertEqual(events[-1], ('audit', 'transaction', 'ok'))

    def test_nested_fatal_primary_is_not_collected_as_ordinary_error(self):
        class Cancel(BaseException):
            pass
        with self.fixture_factory('nested-fatal-primary') as c:
            events = self._prepare(c)
            primary = Cancel('authored fatal primary')
            def retry(dry_run=True, *, outbox_job_ids=None):
                events.append(('retry', dry_run, outbox_job_ids))
                raise primary
            c._mp.setattr(c.p, '_repair_failed_outbox', retry)
            for mode in ('suggest', 'apply'):
                for alias in ('repair', 'memory_wiki_repair'):
                    events.clear()
                    with self.subTest(mode=mode, alias=alias):
                        with self.assertRaises(Cancel) as caught:
                            c.p._transaction([self._operation(alias, ['0123456789abcdef'])], mode)
                        self.assertIs(caught.exception, primary)
                        self.assertFalse(any(e[0] in {'audit', 'mutation', 'journal'} for e in events))
                        self.assertEqual(events[-1][0], 'retry')


def make_nested_caller_suite(fixture_factory):
    """ONLY after native/SQL/SPI admission, with the unchanged shipped fixture."""
    class BoundNestedCallerTests(AddressedOutboxNestedCallerTests):
        pass
    BoundNestedCallerTests.fixture_factory = staticmethod(fixture_factory)
    return unittest.TestSuite(BoundNestedCallerTests(name) for name in NESTED_CALLER_CASE_IDS)
