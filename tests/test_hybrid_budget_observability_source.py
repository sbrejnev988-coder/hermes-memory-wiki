"""Explicit stdlib SOURCE suite; collection does not read or execute the plugin.

Parent supplies exact main + semantic_io bytes via source_suite(...).
Only the admitted packet may execute this suite. Synthetic clock/profile/receiver,
content decisions and transport denial are NOT native identity, guards or provider
responses. No SDK import, SQLite connection, filesystem fixture or actual HTTP.
"""
from __future__ import annotations

import __future__
import ast
import contextvars
from contextlib import contextmanager
import hashlib
import json
import math
import re
import threading
import types
import unittest
import urllib.error
import urllib.request


CASE_METHODS = (
    "test_01_primary_after_half_keeps_result",
    "test_02_configured_reserve_and_tiny_budget",
    "test_03_primary_deadline_serial_fallback",
    "test_04_runtime_error_serial_fallback",
    "test_05_exhausted_outer_discards_late_result",
    "test_06_cancellation_never_starts_fallback",
    "test_07_nested_deadline_and_event_restoration",
    "test_08_direct_gate_reason_matrix",
    "test_09_secret_exact_and_circuit_once",
    "test_10_safe_candidate_filtering",
    "test_11_identity_and_safe_document_threshold",
    "test_12_all_predispatch_deadline_positions",
    "test_13_cache_hit_and_invalid_cache",
    "test_14_search_bypass_exact_source_slice",
    "test_15_detached_status_and_profile_isolation",
    "test_16_optional_diagnostics_and_finite_vocabulary",
    "test_17_healthy_reaches_transport_admission_without_http",
    "test_18_STATIC_preserved_safety_contracts",
    "test_19_fatal_disclosure_retains_primary_when_diagnostics_fail",
)

EXPECTED_REASONS = (
    "disabled", "invalid_profile_settings", "endpoint_invalid", "no_key",
    "query_length", "candidate_threshold", "secret_query", "exact_technical",
    "circuit_open", "safe_candidate_threshold", "candidate_identity",
    "safe_document_threshold", "deadline", "cancelled", "mode_or_disabled",
    "invalid_rerank_cache", "document_disclosure_changed", "other",
)

# Exact baseline AST fingerprints, populated from the pinned baseline, not from
# execution or from candidate behavior. These controls are STATIC only.
BASELINE_AST = {
    "_PrefetchAttempt": "7569d709b0f5ba83fb48b93fcd6e0f97feb4f7b302dbce67b8c20aa8dee602a5",
    "_bounded_prefetch_callback": "c07f80c5c4e9247a9f1c0f599b745223c4f19b25b882cf8a4cc81a5e34a4b059",
    "_prefetch_active": "7ec74e547684b63a34a247244fa665d3f0cb77a2c06d1ffd85263e7d5aa7220a",
    "_prefetch_cancelled": "fe351c3a140797d37681ee886de29ca64f762743aba221de9f3f0b6b2a9381f6",
    "_prefetch_time_remaining": "dbe1276a42cf2aac6bf381bb1d780da0d13b6f5cc061157f871fba0450ba97b9",
    "_prefetch_budget_expired": "e3a4c5e37668673689694463423810a0f6c48add33ee1ca6783e62e51cd38e6c",
    "_prefetch_network_timeout": "b59e450bea29126562c316ce8b1dcba6bbeb27b1cfa714a0b3300fd25a0c7118",
    "_prefetch_budget": "aa9bdc997fb8060349bbb9bb7ac18eaa4f79a2347ce33fd1855a3135946e9dc7",
    "_observed_semantic_http": "502ab9e1d37ce961a7911aa42c56ae8e94a64600942a7ddfa7518c2623f86eb8",
    "_semantic_io_check": "8f147c3bfb2cb324163527c83b93cdc1bcd42198a28e6ae666e211cc723fd7c7",
    "_rerank_settings": "70bc18ffbd91f67bb0933d683127454455f0a616e8b26944f2cdc07b0e0e6158",
    "_build_rerank_query": "ff924bfe7a7ff78ff3930c9d708775b9e217cdb67dac987fc7d47dd2c480fa57",
    "_serialize_rerank_document": "517af95ac47bebe38ffa75cbfa70265586d3f9b8a08de3a76335353e48458ffd",
    "_fuse_rerank_order": "9bd4a56d3906672f2c0b6366ffbc4572683d5e5567c4acd8899d5f02332979c5",
    "MemoryWikiProvider._commit_prefetch_delivery": "1806e701aeddfd9e9bca5385e80cdd55bb130271bfd5cc16119ef8daa456cfc3",
    "MemoryWikiProvider._lexical_prefetch_fallback": "d7a0caff43306ba3b68a906dd3a9603f5bf77e6a3a1d78cbf9843d94203de3d1",
    "MemoryWikiProvider._prefetch_impl": "db9f4c0ffcf6dc9a49a7f20ee6265e7d3beeda20473f5f5fa40b2b0f4f63877d",
    "MemoryWikiProvider._rerank_rows.check_document_disclosure": "e80f9d33246ae14a0cbbb8e2694db83ace6bd303ed043c94a75dfa762ea65696",
    "assignment:PREFETCH_DEADLINE_SECONDS": "62a3cd05a1a03a9e838bad3639cf2ff1fe7a084862120907d17a1ecf5c3a5c45",
    "assignment:PREFETCH_FALLBACK_RESERVE_SECONDS": "ce405144068322f35b977dfced12b7552e3174c40d6eaad9dfe168aed655f081",
    "assignment:RERANK_MIN_CANDIDATES": "e75ecc0fbb5ee93a9975abe6911b12c1b4e1d9a02294540b91591478e090d4a1",
    "assignment:_RERANK_STATS": "785b20de2a6d75b7c3322568fd6b214d4831474671d93f0233671203a502b859",
}


def _one(nodes, predicate):
    found = [node for node in nodes if predicate(node)]
    if len(found) != 1:
        raise AssertionError("source_selector_not_unique")
    return found[0]


def _fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


class _Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


class _Profile:
    """Pure synthetic mapper token: resolve() performs no filesystem operation."""
    def __init__(self, name):
        self.name = name

    def resolve(self):
        return self

    def __str__(self):
        return self.name


class _TransportStop(BaseException):
    """Exact owned stop at adapter entry, not a fabricated provider failure."""


class _MetadataUnavailable(Exception):
    pass


class HybridBudgetObservabilitySource(unittest.TestCase):
    __test__ = False  # Standalone-only; explicit unittest lifecycle is preserved.
    _loader = None
    _expected_sha256 = None
    _filename = None
    _semantic_loader = None
    _semantic_sha256 = None
    _semantic_filename = None

    @classmethod
    def setUpClass(cls):
        if cls._loader is None:
            raise RuntimeError("explicit_bound_source_loader_required")
        raw = cls._loader()
        if type(raw) is not bytes or len(raw) > 2_000_000:
            raise ValueError("source_bytes_or_size_invalid")
        if hashlib.sha256(raw).hexdigest() != cls._expected_sha256:
            raise ValueError("source_sha256_mismatch")
        cls._raw = raw
        cls._tree = ast.parse(raw, filename=cls._filename)
        cls._provider = _one(cls._tree.body, lambda n: isinstance(n, ast.ClassDef) and n.name == "MemoryWikiProvider")
        semantic = cls._semantic_loader()
        if type(semantic) is not bytes or len(semantic) > 100_000:
            raise ValueError("semantic_source_bytes_or_size_invalid")
        if hashlib.sha256(semantic).hexdigest() != cls._semantic_sha256:
            raise ValueError("semantic_source_sha256_mismatch")
        cls._semantic_tree = ast.parse(semantic, filename=cls._semantic_filename)

    @classmethod
    def tearDownClass(cls):
        cls._raw = cls._tree = cls._provider = None
        cls._loader = cls._expected_sha256 = cls._filename = None
        cls._semantic_tree = cls._semantic_loader = cls._semantic_sha256 = cls._semantic_filename = None

    def _function(self, name, owner=None):
        body = self._tree.body if owner is None else owner.body
        return _one(body, lambda n: isinstance(n, ast.FunctionDef) and n.name == name)

    def _assignment(self, name):
        def matches(node):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            return any(isinstance(target, ast.Name) and target.id == name for target in targets)
        return _one(self._tree.body, matches)

    def _exec(self, nodes, namespace, *, filename=None):
        # Preserve exact extracted bodies, source locations, decorators/defaults.
        # Future annotations prevent typing/SDK evaluation, not body changes.
        module = ast.Module(body=list(nodes), type_ignores=[])
        exec(compile(module, self._filename if filename is None else filename, "exec", flags=__future__.annotations.compiler_flag,
                     dont_inherit=True), namespace)

    def setUp(self):
        self.clock = _Clock()
        self.profile = _Profile("synthetic-import-owner")
        self.configuration = "generation-A"
        self.events = []
        self.boundary = []
        self.paths = []
        self.settings = {
            "reason": "", "signature": "synthetic-settings-v1",
            "RERANK_ENABLED": True, "RERANK_ENDPOINT_VALID": True,
            "RERANK_MODEL": "synthetic/model", "RERANK_URL": "https://synthetic.invalid/rerank",
            "RERANK_API_STYLE": "openrouter", "RERANK_TOP_K": 12,
            "RERANK_MIN_CANDIDATES": 10, "RERANK_TIMEOUT": 3.0,
            "RERANK_USER_QUERY_MAX_CHARS": 5000, "RERANK_DOCUMENT_MAX_CHARS": 2600,
            "RERANK_SKIP_EXACT_TECHNICAL": True, "RERANK_CACHE_TTL": 1800,
            "RERANK_CACHE_MAX": 256, "RERANK_CIRCUIT_FAILURES": 3,
            "RERANK_CIRCUIT_SECONDS": 300, "RERANK_RULES_ENABLED": False,
            "RERANK_RULES_POSITION": "prepend", "RERANK_RULES": {},
            "RERANK_WEIGHT_TECHNICAL": .45, "RERANK_WEIGHT_SEMANTIC": .75,
            "RERANK_WEIGHT_MIXED": .60, "OPENROUTER_TITLE": "", "OPENROUTER_REFERER": "",
        }
        self.key = "synthetic-credential-not-real"
        self.ns = {
            "__name__": "explicit_synthetic_source", "threading": threading,
            "contextmanager": contextmanager, "time": self.clock,
            "math": math, "json": json, "hashlib": hashlib, "re": re, "urllib": urllib,
            "PREFETCH_NETWORK_RESERVE_SECONDS": .25, "PREFETCH_FALLBACK_RESERVE_SECONDS": .45,
            "RERANK_RETRY_COUNT": 1, "RRF_K": 60,
            "_bound_profile_home": lambda: self.profile,
            "_IMPORT_HERMES_HOME": _Profile("synthetic-import-owner"),
            "_profile_configuration_generation": lambda: self.configuration,
            "_rerank_settings": lambda: self.settings,
            "_rerank_api_key": lambda: self.key,
            "_SEARCH_RECEIPT": contextvars.ContextVar("synthetic_search", default={"rerank": {}}),
            "_RECALL_REQUEST": contextvars.ContextVar("synthetic_recall", default={"emitted_ids": []}),
            "_debug_log": lambda *_args: None, "_hybrid_note": lambda *_args, **_kwargs: None,
            "is_social_close": lambda _query: False,
            "_online_metrics": types.SimpleNamespace(record_path=lambda *_args: self.paths.append(_args)),
            # Explicit synthetic content decisions, NOT the native secret/ACL guard.
            "secret_scan": lambda text: {"raw_secret": "SYNTHETIC_RAW_SECRET" in text},
            "redact_secrets": lambda text: text,
            "is_ephemeral_fragment": lambda text: text == "SYNTHETIC_EPHEMERAL",
        }
        semantic_nodes = [
            _one(self._semantic_tree.body, lambda n: isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "REQUEST_MAX_BYTES" for t in n.targets)),
            _one(self._semantic_tree.body, lambda n: isinstance(n, ast.ClassDef) and n.name == "SemanticIOError"),
            self._function("_cap", self._semantic_tree),
            self._function("request_bytes", self._semantic_tree),
        ]
        self._exec(semantic_nodes, self.ns, filename=self._semantic_filename)
        self.ns["_SemanticIOError"] = self.ns["SemanticIOError"]
        self.ns["_semantic_request_bytes"] = self.ns["request_bytes"]
        assignment_names = ("_PREFETCH_LOCAL", "_RERANK_LOCK", "_RERANK_CACHE", "_RERANK_STATS",
                            "_RERANK_SKIP_REASONS", "_RERANK_DEFAULT_STATE", "_RERANK_PROFILE_STATES")
        functions = ("sha", "short", "_safe_exception_label", "_prefetch_active", "_prefetch_cancelled", "_prefetch_time_remaining",
                     "_prefetch_budget_expired", "_prefetch_network_timeout", "_prefetch_budget",
                     "_rerank_scope_state", "_rerank_skip", "_stage_receipt", "_rerank_meta_value",
                     "_serialize_rerank_document", "_select_rerank_rules", "_build_rerank_query",
                     "_rerank_weight", "_fuse_rerank_order", "_semantic_io_check", "_semantic_io_label", "_observed_semantic_http")
        self._exec([self._assignment(name) for name in assignment_names] +
                   [self._function(name) for name in functions] +
                   [self._function(name, self._provider) for name in ("prefetch", "_rerank_rows", "_rerank_status")], self.ns)
        stage_receipt = self.ns["_stage_receipt"]

        def observe_receipt(stage, status, reason="", **fields):
            self.events.append((stage, status, reason, fields))
            return stage_receipt(stage, status, reason, **fields)

        self.ns["_stage_receipt"] = observe_receipt
        self.ns["_hybrid_scope"] = self._hybrid_scope
        self.stop = _TransportStop("synthetic adapter denied; no HTTP")

        def deny_adapter(*args, **kwargs):
            self.boundary.append(("adapter_denied", args, kwargs))
            raise self.stop

        self.ns.update({
            "_health_http_check": lambda *_args: self.boundary.append(("synthetic_route_check",)),
            "_hybrid_http_start": lambda stage, timeout: {"stage": stage, "http_issued": False, "timeout_s": timeout},
            "_hybrid_http_finish": lambda row, exc=None: self.boundary.append(("observed_finish", dict(row), exc)),
            "_urlopen_no_redirect": deny_adapter,
        })
        self.receiver = types.SimpleNamespace(session_id="synthetic-session", db_path="no-store")
        self.receiver._prefetch_delivery_budget = lambda: 24000
        self.receiver._prefetch_impl = lambda *_args, **_kwargs: "synthetic primary"
        self.receiver._lexical_prefetch_fallback = lambda *_args, **_kwargs: "synthetic fallback"
        self.receiver._commit_prefetch_delivery = lambda _delivery: True
        self.receiver._claim_visible = lambda _row: True
        self.receiver._inspect_recall_item = lambda row, **_kw: {"status": "refused" if row.get("deny_row") else "safe"}
        self.receiver._inspect_recall_text = lambda text, **_kw: {"status": "refused" if "SYNTHETIC_DENY_DOCUMENT" in text else "safe", "content": text}

        def no_sql():
            self.boundary.append(("metadata_unavailable_no_sql",))
            raise _MetadataUnavailable("SQL is outside this SOURCE packet")

        self.receiver._connect = no_sql
        for name in ("prefetch", "_rerank_rows", "_rerank_status"):
            setattr(self.receiver, name, types.MethodType(self.ns[name], self.receiver))
        self.rows = [{"id": f"synthetic-{i:02d}", "claim": f"Synthetic durable observatory preference number {i}.",
                      "status": "active", "risk": "low", "trust_class": "fact", "updated_at": 1,
                      "score": 20.0 - i, "score_parts": {"rrf": .01}} for i in range(10)]
        self.query = "Which synthetic durable observatory preference is relevant?"
        self.state = self.ns["_rerank_scope_state"](self.settings)

    @contextmanager
    def _hybrid_scope(self, *_args, **_kwargs):
        yield


    def _budget(self, seconds=5.5, cancel=None):
        return self.ns["_prefetch_budget"](seconds, cancel)

    def _rerank(self, rows=None, mode="semantic", query=None):
        return self.receiver._rerank_rows(self.query if query is None else query,
                                          self.rows if rows is None else rows, mode)

    def _assert_skip(self, reason, *, status="skipped", safe_count=None):
        self.assertEqual(self.state["stats"]["skipped"], 1)
        self.assertEqual(self.state["skip_reasons"], {key: int(key == reason) for key in EXPECTED_REASONS})
        self.assertEqual([(stage, outcome, why) for stage, outcome, why, _fields in self.events], [("rerank", status, reason)])
        if safe_count is not None:
            self.assertEqual(self.events[0][3]["safe_candidate_count"], safe_count)
        self.assertEqual(self.state["stats"]["requests"], 0)
        self.assertEqual(self.state["stats"]["failures"], 0)
        self.assertFalse(any(row[0] == "adapter_denied" for row in self.boundary))

    def _reset_decision(self):
        self.events.clear()
        self.boundary.clear()
        self.state["stats"]["skipped"] = 0
        self.state["skip_reasons"].update(dict.fromkeys(EXPECTED_REASONS, 0))

    def test_01_primary_after_half_keeps_result(self):
        deadlines = []
        fallback = []
        def primary(*_args, **_kwargs):
            deadlines.append(self.ns["_PREFETCH_LOCAL"].deadline)
            self.clock.now += 3.1
            return "synthetic primary after half"
        self.receiver._prefetch_impl = primary
        self.receiver._lexical_prefetch_fallback = lambda *_a, **_kw: fallback.append(True)
        with self._budget():
            self.assertEqual(self.receiver.prefetch(self.query), "synthetic primary after half")
            self.assertEqual(self.ns["_PREFETCH_LOCAL"].deadline, 105.5)
        self.assertAlmostEqual(deadlines[0], 105.05)
        self.assertGreater(3.1, 5.5 / 2)
        self.assertLess(3.1, deadlines[0] - 100.0)
        self.assertEqual(fallback, [])
        self.assertEqual(len(self.paths), 1)

    def test_02_configured_reserve_and_tiny_budget(self):
        for remaining, reserve in ((5.5, .2), (5.5, .45), (5.5, 1.0), (.3, .45)):
            with self.subTest(remaining=remaining, reserve=reserve):
                self.clock.now = 100.0
                self.ns["PREFETCH_FALLBACK_RESERVE_SECONDS"] = reserve
                seen = []
                def primary(*_a, **_kw):
                    seen.append(("primary", self.ns["_PREFETCH_LOCAL"].deadline))
                    return "primary"
                def fallback(*_a, **_kw):
                    seen.append(("fallback", self.ns["_PREFETCH_LOCAL"].deadline))
                    return "fallback"
                self.receiver._prefetch_impl = primary
                self.receiver._lexical_prefetch_fallback = fallback
                with self._budget(remaining):
                    self.assertEqual(self.receiver.prefetch(self.query), "primary" if remaining > reserve else "fallback")
                kind, deadline = seen[0]
                self.assertEqual(kind, "primary" if remaining > reserve else "fallback")
                self.assertAlmostEqual(deadline, 100.0 + (remaining - reserve if remaining > reserve else remaining))
                self.assertEqual(len(seen), 1)

    def test_03_primary_deadline_serial_fallback(self):
        seen = []
        active = []
        pending = {"candidate": "not_committed"}
        def primary(*_a, **kw):
            active.append(True)
            kw["_delivery"].update(pending)
            seen.append(("primary", threading.get_ident(), self.ns["_PREFETCH_LOCAL"].deadline))
            self.clock.now = self.ns["_PREFETCH_LOCAL"].deadline + .01
            active.pop()
            return "discard prepared primary"
        def fallback(*_a, **kw):
            self.assertEqual(active, [])
            self.assertEqual(kw["reason"], "deadline")
            seen.append(("fallback", threading.get_ident(), self.ns["_PREFETCH_LOCAL"].deadline))
            self.clock.now += .1
            return "synthetic serial fallback"
        self.receiver._prefetch_impl = primary
        self.receiver._lexical_prefetch_fallback = fallback
        self.receiver._commit_prefetch_delivery = lambda _delivery: self.fail("rejected primary committed")
        with self._budget():
            self.assertEqual(self.receiver.prefetch(self.query), "synthetic serial fallback")
        self.assertEqual([row[0] for row in seen], ["primary", "fallback"])
        self.assertEqual(seen[0][1], seen[1][1])
        self.assertAlmostEqual(seen[0][2], 105.05)
        self.assertEqual(seen[1][2], 105.5)
        self.assertLess(self.clock.now, 105.5)
        self.assertEqual(self.ns["_RECALL_REQUEST"].get()["delivery_path"], "deadline_fallback")

    def test_04_runtime_error_serial_fallback(self):
        seen = []
        def primary(*_a, **_kw):
            seen.append(("primary", threading.get_ident()))
            self.clock.now += 3.0
            raise RuntimeError("synthetic primary exception")
        def fallback(*_a, **kw):
            seen.append(("fallback", threading.get_ident()))
            self.assertEqual(kw["reason"], "network_or_runtime_error")
            self.assertEqual(self.ns["_PREFETCH_LOCAL"].deadline, 105.5)
            return "serial fallback"
        self.receiver._prefetch_impl = primary
        self.receiver._lexical_prefetch_fallback = fallback
        with self._budget():
            self.assertEqual(self.receiver.prefetch(self.query), "serial fallback")
        self.assertEqual(seen, [("primary", threading.get_ident()), ("fallback", threading.get_ident())])

    def test_05_exhausted_outer_discards_late_result(self):
        for elapsed in (5.5, 6.0):
            with self.subTest(elapsed=elapsed):
                self.clock.now = 100.0
                def primary(*_a, **_kw):
                    self.clock.now += elapsed
                    return "late result must not escape"
                self.receiver._prefetch_impl = primary
                self.receiver._lexical_prefetch_fallback = lambda *_a, **_kw: self.fail("expired fallback")
                with self._budget():
                    self.assertEqual(self.receiver.prefetch(self.query), "")
        self.clock.now = 100.0
        def primary_expired(*_a, **_kw):
            self.clock.now = self.ns["_PREFETCH_LOCAL"].deadline + .01
            return "discard primary"
        def fallback_expired(*_a, **_kw):
            self.assertEqual(self.ns["_PREFETCH_LOCAL"].deadline, 105.5)
            self.clock.now = 105.51
            return "discard late fallback"
        self.receiver._prefetch_impl = primary_expired
        self.receiver._lexical_prefetch_fallback = fallback_expired
        with self._budget():
            self.assertEqual(self.receiver.prefetch(self.query), "")
        self.assertEqual(self.paths, [])

    def test_06_cancellation_never_starts_fallback(self):
        for at_entry in (False, True):
            with self.subTest(at_entry=at_entry):
                cancel = threading.Event()
                if at_entry:
                    cancel.set()
                def primary(*_a, **_kw):
                    self.assertFalse(at_entry)
                    cancel.set()
                    return "cancelled primary"
                self.receiver._prefetch_impl = primary
                self.receiver._lexical_prefetch_fallback = lambda *_a, **_kw: self.fail("cancelled fallback")
                with self._budget(cancel=cancel):
                    self.assertEqual(self.receiver.prefetch(self.query), "")
                self.assertTrue(cancel.is_set())
        self.assertEqual(self.paths, [])

    def test_07_nested_deadline_and_event_restoration(self):
        outer, inner = threading.Event(), threading.Event()
        local = self.ns["_PREFETCH_LOCAL"]
        self.assertFalse(hasattr(local, "deadline"))
        primary = RuntimeError("nested unwind")
        with self._budget(5.5, outer):
            with self._budget(20.0):
                self.assertEqual(local.deadline, 105.5)
                self.assertIs(local.cancel_event, outer)
            with self.ns["_prefetch_budget"](99.0, deadline=104.0):
                self.assertEqual(local.deadline, 104.0)
            with self.ns["_prefetch_budget"](99.0, deadline=120.0):
                self.assertEqual(local.deadline, 105.5)
            try:
                with self._budget(2.0, inner):
                    self.assertEqual(local.deadline, 102.0)
                    self.assertAlmostEqual(self.ns["_prefetch_network_timeout"](3.0), 1.75)
                    inner.set()
                    self.assertEqual(self.ns["_prefetch_network_timeout"](3.0), 0)
                    raise primary
            except RuntimeError as caught:
                self.assertIs(caught, primary)
            self.assertEqual(local.deadline, 105.5)
            self.assertIs(local.cancel_event, outer)
            self.assertFalse(self.ns["_prefetch_budget_expired"]())
        self.assertFalse(hasattr(local, "deadline"))
        self.assertFalse(hasattr(local, "cancel_event"))
        self.assertEqual(self.ns["_prefetch_time_remaining"](7.0), 7.0)

    def test_08_direct_gate_reason_matrix(self):
        cases = (
            ("disabled", {"RERANK_ENABLED": False}, self.query, 10, True),
            ("invalid_profile_settings", {"RERANK_ENABLED": False, "reason": "invalid_profile_settings"}, self.query, 10, True),
            ("endpoint_invalid", {"RERANK_ENDPOINT_VALID": False}, self.query, 10, True),
            ("no_key", {}, self.query, 10, False),
            ("query_length", {}, "short", 10, True),
            ("query_length", {}, "long " * 1001, 10, True),
            ("candidate_threshold", {}, self.query, 9, True),
        )
        original_settings = dict(self.settings)
        for reason, delta, query, count, have_key in cases:
            with self.subTest(reason=reason, query_chars=len(query)):
                self._reset_decision()
                self.settings.clear(); self.settings.update(original_settings); self.settings.update(delta)
                self.key = "synthetic-key" if have_key else ""
                rows = self.rows[:count]
                self.assertEqual(self._rerank(rows, query=query), rows)
                self._assert_skip(reason)

    def test_09_secret_exact_and_circuit_once(self):
        for reason in ("secret_query", "exact_technical", "circuit_open"):
            with self.subTest(reason=reason):
                self._reset_decision()
                rows = [dict(row) for row in self.rows]
                mode, query = "semantic", self.query
                self.state["circuit_until"] = 0.0
                if reason == "secret_query":
                    query += " SYNTHETIC_RAW_SECRET"
                elif reason == "exact_technical":
                    rows[0]["score_parts"] = {"exact": .35, "bm25": .9}
                    mode = "technical"
                else:
                    self.state["circuit_until"] = 101.0
                self.assertEqual(self._rerank(rows, mode, query), rows)
                self._assert_skip(reason)

    def test_10_safe_candidate_filtering(self):
        for delta in ({"status": "retired"}, {"risk": "secret"}, {"trust_class": "tool_log"},
                      {"claim": "SYNTHETIC_EPHEMERAL"}, {"deny_row": True}):
            with self.subTest(field=next(iter(delta))):
                self._reset_decision()
                rows = [dict(row) for row in self.rows]
                rows[0].update(delta)
                actual = self._rerank(rows)
                self.assertEqual(actual, rows[1:] if delta.get("deny_row") else rows)
                self._assert_skip("safe_candidate_threshold", safe_count=9)
                self.assertEqual(self.boundary, [])

    def test_11_identity_and_safe_document_threshold(self):
        for kind in ("duplicate", "empty", "document"):
            with self.subTest(kind=kind):
                self._reset_decision()
                rows = [dict(row) for row in self.rows]
                if kind == "duplicate":
                    rows[1]["id"] = rows[0]["id"]
                elif kind == "empty":
                    rows[0]["id"] = ""
                else:
                    rows[0]["claim"] = "SYNTHETIC_DENY_DOCUMENT"
                expected = rows[1:] if kind == "document" else rows
                self.assertEqual(self._rerank(rows), expected)
                self._assert_skip("safe_document_threshold" if kind == "document" else "candidate_identity",
                                  safe_count=9 if kind == "document" else 10)
                self.assertLessEqual(len(self.boundary), 1)  # Enrichment refused, no connection.

    def test_12_all_predispatch_deadline_positions(self):
        for position in ("entry", "cancel", "network_reserve", "cache"):
            with self.subTest(position=position):
                self._reset_decision()
                self.clock.now = 100.0
                cancel = threading.Event()
                if position == "cancel":
                    cancel.set()
                build = self.ns["_build_rerank_query"]
                if position == "cache":
                    def expire_after_query(*args, **kwargs):
                        value = build(*args, **kwargs)
                        self.clock.now = 106.0
                        return value
                    self.ns["_build_rerank_query"] = expire_after_query
                seconds = 0.0 if position == "entry" else .2 if position == "network_reserve" else 5.5
                try:
                    with self._budget(seconds, cancel):
                        self.assertEqual(self._rerank(), self.rows)
                finally:
                    self.ns["_build_rerank_query"] = build
                self._assert_skip("cancelled" if position == "cancel" else "deadline",
                                  status="skipped" if position == "network_reserve" else "timeout")

    def _prime(self, ranks):
        documents = [self.ns["_serialize_rerank_document"](row, settings=self.settings) for row in self.rows]
        fingerprint = self.ns["sha"]("\n---candidate---\n".join(f"id={cid}\n{doc}" for cid, doc in
                                      sorted((row["id"], doc) for row, doc in zip(self.rows, documents))))
        seed = "\n".join((f"generation={self.state['generation']}", f"settings={self.settings['signature']}",
                           f"model={self.settings['RERANK_MODEL']}", f"url={self.settings['RERANK_URL']}",
                           f"api_style={self.settings['RERANK_API_STYLE']}", "mode=semantic",
                           "query=" + self.ns["_build_rerank_query"](self.query, "semantic", settings=self.settings),
                           "documents=" + fingerprint,
                           "rows=" + ",".join(sorted(f"{row['id']}:{row['updated_at']}" for row in self.rows))))
        key = self.ns["sha"](seed)
        self.state["cache"][key] = (200.0, ranks)
        return key

    def test_13_cache_hit_and_invalid_cache(self):
        ranks = [(row["id"], 1.0 - i / 100.0, i) for i, row in enumerate(reversed(self.rows), 1)]
        self._prime(ranks)
        self.assertEqual([row["id"] for row in self._rerank()], [cid for cid, _score, _rank in ranks])
        self.assertEqual(self.state["stats"]["cache_hits"], 1)
        self.assertEqual(self.state["stats"]["skipped"], 0)
        self.assertEqual(self.events[0][:3], ("rerank", "cache_hit", ""))
        self.assertEqual(len(self.events), 1)
        for malformed_envelope in (False, True):
            with self.subTest(malformed_envelope=malformed_envelope):
                self._reset_decision()
                key = self._prime([("foreign-synthetic-id", .9, 1), *ranks[1:]])
                if malformed_envelope:
                    self.state["cache"][key] = ("not-a-float-expiry", ranks)
                self.assertEqual(self._rerank(), self.rows)
                self.assertNotIn(key, self.state["cache"])
                self._assert_skip("invalid_rerank_cache", status="failed", safe_count=10)
        self.assertEqual(self.state["stats"]["cache_hits"], 1)
        self.assertEqual(self.state["failure_count"], 0)

    def _search_gate(self):
        search = self._function("_search", self._provider)
        return _one(search.body, lambda node: isinstance(node, ast.If) and any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_rerank_rows"
            for statement in node.body for call in ast.walk(statement)))

    def test_14_search_bypass_exact_source_slice(self):
        for mode, apply, seconds, cancelled, expected in (
            ("fts", True, 5.5, False, "mode_or_disabled"),
            ("hybrid", False, 5.5, False, "mode_or_disabled"),
            # Exact binary below-bound control: 100.2 - 100.0 may exceed .20.
            ("hybrid", True, .125, False, "deadline"),
            ("hybrid", True, .25, False, "candidate_threshold"),
            ("hybrid", True, 5.5, True, "cancelled"),
            ("hybrid", True, 5.5, False, "candidate_threshold"),
        ):
            with self.subTest(mode=mode, apply=apply, seconds=seconds, cancelled=cancelled):
                self._reset_decision()
                self.clock.now = 100.0
                event = threading.Event()
                if cancelled:
                    event.set()
                self.ns.update(self=self.receiver, q=self.query, scored=self.rows[:9], query_mode="semantic",
                               retrieval_mode=mode, apply_rerank=apply, disclosure=None)
                with self._budget(seconds, event):
                    self._exec([self._search_gate()], self.ns)
                self.assertEqual(self.ns["scored"], self.rows[:9])
                self._assert_skip(expected)

    def test_15_detached_status_and_profile_isolation(self):
        self.ns["_rerank_skip"]("candidate_threshold", state=self.state)
        first = self.receiver._rerank_status()
        self.assertEqual(first["stats_scope"], "process_local_bound_profile")
        first["skip_reasons"]["candidate_threshold"] = 900
        first["skip_reasons"]["untrusted-key"] = 1
        first["skipped"] = 900
        self.assertEqual(self.state["skip_reasons"]["candidate_threshold"], 1)
        self.assertNotIn("untrusted-key", self.state["skip_reasons"])
        self.profile = _Profile("synthetic-foreign-B")
        other = self.ns["_rerank_scope_state"](self.settings)
        self.assertIsNot(other, self.state)
        self.assertEqual(other["stats"]["skipped"], 0)
        self.assertTrue(all(type(value) in (int, float, str) for value in other["stats"].values()))
        self.ns["_rerank_skip"]("safe_document_threshold", state=other)
        status = self.receiver._rerank_status()
        self.assertEqual(status["skip_reasons"]["safe_document_threshold"], 1)
        self.assertEqual(status["skip_reasons"]["candidate_threshold"], 0)
        other["cache"]["old"] = (200.0, [])
        other["circuit_until"] = 200.0
        self.configuration = "generation-B"
        self.assertIs(self.ns["_rerank_scope_state"](self.settings), other)
        self.assertEqual(other["cache"], {})
        self.assertEqual(other["circuit_until"], 0.0)
        self.assertEqual(other["skip_reasons"]["safe_document_threshold"], 1)
        self.profile = _Profile("synthetic-import-owner")
        self.assertEqual(self.receiver._rerank_status()["skip_reasons"]["candidate_threshold"], 1)
        self.assertEqual(self.state["skip_reasons"]["safe_document_threshold"], 0)

    def test_16_optional_diagnostics_and_finite_vocabulary(self):
        self.assertEqual(self.ns["_RERANK_SKIP_REASONS"], EXPECTED_REASONS)
        self.assertEqual(len(EXPECTED_REASONS), len(set(EXPECTED_REASONS)))
        self.ns["_rerank_skip"]("not-a-public-reason-or-user-content", state=self.state)
        self._assert_skip("other")
        self._reset_decision()
        def fail_receipt(*_args, **_kwargs):
            raise RuntimeError("synthetic optional receipt failure")
        self.ns["_stage_receipt"] = fail_receipt
        self.settings["RERANK_ENABLED"] = False
        self.assertEqual(self._rerank(), self.rows)
        self.assertEqual(self.state["stats"]["skipped"], 1)
        self.assertEqual(self.state["skip_reasons"]["disabled"], 1)
        def fail_scope(*_args):
            raise RuntimeError("synthetic optional scope failure")
        self.ns["_rerank_scope_state"] = fail_scope
        # Search's bypass must survive even when both optional sinks refuse.
        self.ns["_rerank_skip"]("mode_or_disabled")
        self.assertFalse(any(row[0] == "adapter_denied" for row in self.boundary))

    def test_17_healthy_reaches_transport_admission_without_http(self):
        with self._budget():
            with self.assertRaises(_TransportStop) as caught:
                self._rerank()
        self.assertIs(caught.exception, self.stop)
        self.assertEqual([row[0] for row in self.boundary],
                         ["metadata_unavailable_no_sql", "synthetic_route_check", "adapter_denied", "observed_finish"])
        req = self.boundary[2][1][0]
        payload = json.loads(req.data)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(len(payload["documents"]), 10)
        self.assertEqual(payload["model"], "synthetic/model")
        self.assertGreater(self.boundary[2][2]["timeout"], 0.0)
        self.assertLess(self.boundary[2][2]["timeout"], 5.5)
        self.assertTrue(self.boundary[-1][1]["http_issued"])
        self.assertIs(self.boundary[-1][2], self.stop)
        self.assertEqual(self.state["stats"]["requests"], 0)
        self.assertEqual(self.state["stats"]["skipped"], 0)
        self.assertEqual(sum(self.state["skip_reasons"].values()), 0)
        self.assertEqual(self.events, [])  # No provisional "skipped" event on healthy flow.

    def test_18_STATIC_preserved_safety_contracts(self):
        self.assertTrue(BASELINE_AST, "baseline static pins must be authored before freeze")
        for qualified, expected in BASELINE_AST.items():
            with self.subTest(qualified=qualified):
                if qualified == "MemoryWikiProvider._rerank_rows.check_document_disclosure":
                    parent = self._function("_rerank_rows", self._provider)
                    node = self._function("check_document_disclosure", parent)
                elif qualified.startswith("MemoryWikiProvider."):
                    node = self._function(qualified.split(".")[1], self._provider)
                elif qualified == "_PrefetchAttempt":
                    node = _one(self._tree.body, lambda n: isinstance(n, ast.ClassDef) and n.name == qualified)
                elif qualified.startswith("assignment:"):
                    node = self._assignment(qualified.split(":")[1])
                else:
                    node = self._function(qualified)
                self.assertEqual(_fingerprint(node), expected)
        stats = ast.literal_eval(self._assignment("_RERANK_STATS").value)
        self.assertTrue(all(type(value) in (int, float, str) for value in stats.values()))
        # Only actual exits record skips; do not reintroduce provisional events.
        rerank = self._function("_rerank_rows", self._provider)
        provisional = [node for node in ast.walk(rerank) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Name) and node.func.id == "_stage_receipt"
                       and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                       and node.args[1].value == "skipped"]
        self.assertEqual(provisional, [])


    def test_19_fatal_disclosure_retains_primary_when_diagnostics_fail(self):
        # Execute the exact outer exception handler, not a replacement privacy
        # guard or synthetic provider response. Its pending exception is owned.
        rerank = self._function("_rerank_rows", self._provider)
        outer = _one(rerank.body, lambda node: isinstance(node, ast.Try) and any(
            isinstance(h.type, ast.Name) and h.type.id == "BaseException" for h in node.handlers))
        handler = _one(outer.handlers, lambda h: isinstance(h.type, ast.Name) and h.type.id == "BaseException")
        pending = ast.copy_location(ast.Raise(exc=ast.Name(id="pending_primary", ctx=ast.Load()), cause=None), outer)
        wrapped = ast.copy_location(ast.Try(body=[pending], handlers=[handler], orelse=[], finalbody=[]), outer)
        probe = ast.copy_location(ast.FunctionDef(name="source_error_handler",
            # The original function initializes this local before its try.
            args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="request_accounted")], vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[ast.Constant(value=False)]),
            body=[wrapped], decorator_list=[], returns=None), rerank)
        ast.fix_missing_locations(probe)
        self._exec([probe], self.ns)
        for diagnostic_type in (RuntimeError, _TransportStop):
            with self.subTest(diagnostic_type=diagnostic_type.__name__):
                primary = _TransportStop("owned pending primary")
                secondary = diagnostic_type("owned optional diagnostic refusal")
                self._reset_decision()
                self.state["stats"]["requests"] = 0
                def failed_diagnostic(*_args, **_kwargs):
                    raise secondary
                self.ns.update(pending_primary=primary, _disclosure=types.SimpleNamespace(ok=False),
                    response_received=True, request_accounted=False, stored_cache_entry=None,
                    cache=self.state["cache"], cache_key="unused-synthetic-key", stats=self.state["stats"],
                    state=self.state, prefix=self.rows, original=self.rows, _stage_receipt=failed_diagnostic)
                with self.assertRaises(_TransportStop) as caught:
                    self.ns["source_error_handler"]()
                self.assertIs(caught.exception, primary)
                self.assertEqual(self.state["stats"]["requests"], 1)
                self.assertEqual(self.state["skip_reasons"]["document_disclosure_changed"], 1)
                self.assertEqual(self.state["stats"]["skipped"], 1)
                self.assertEqual(self.boundary, [])
        # With no pending primary, an actual cancellation is not swallowed.
        cancellation = _TransportStop("owned fresh cancellation")
        def cancelled_diagnostic(*_args, **_kwargs):
            raise cancellation
        self.ns["_stage_receipt"] = cancelled_diagnostic
        with self.assertRaises(_TransportStop) as caught:
            self.ns["_rerank_skip"]("mode_or_disabled", state=self.state)
        self.assertIs(caught.exception, cancellation)


def source_suite(source_loader, *, expected_sha256, filename,
                 semantic_loader, semantic_sha256, semantic_filename):
    """Explicit entry; does not call tests directly or bypass unittest fixtures."""
    if not callable(source_loader) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("bound_loader_and_sha256_required")
    if type(filename) is not str or not filename:
        raise ValueError("literal_source_filename_required")
    if (not callable(semantic_loader) or type(semantic_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", semantic_sha256)
            or type(semantic_filename) is not str or not semantic_filename):
        raise ValueError("bound_semantic_source_required")
    case = HybridBudgetObservabilitySource
    case._loader = staticmethod(source_loader)
    case._expected_sha256 = expected_sha256
    case._filename = filename
    case._semantic_loader = staticmethod(semantic_loader)
    case._semantic_sha256 = semantic_sha256
    case._semantic_filename = semantic_filename
    return unittest.TestSuite(case(name) for name in CASE_METHODS)


if __name__ == "__main__":
    raise RuntimeError("parent must bind source bytes and run source_suite with unittest.TextTestRunner")
