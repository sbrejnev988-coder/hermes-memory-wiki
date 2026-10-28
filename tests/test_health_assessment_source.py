"""Инертные prepared SOURCE-регрессии расчёта health, не native/SDK suite.

Обычная collection не читает, не импортирует и не исполняет продукт; классы
TestCase создаются только явной build_suite. Parent сначала сверяет raw SHA
полного frozen __init__.py и AST fidelity двух owners, затем под audit вызывает:

    build_suite(owners_source: str, helper_source: str | None = None,
                scratch: Path | None = None) -> unittest.TestSuite

owners_source: только точные MemoryWikiProvider._health и _evaluate_retrieval,
в этом порядке. Предпочтительный carrier: строка "if True:\\n" + оба исходных
raw spans с сохранённым отступом (без dedent/переписывания multiline literals).
Допустимы также два module-level def с доказанной parent AST fidelity.
helper_source должен быть None: дополнительного product helper нет.
scratch задаёт только synthetic db_path; SQLite всегда :memory:, файлов нет.

Исполняются настоящие тела owners. Receiver, clock/env, content classifiers,
redaction и search/pack callbacks явно synthetic; это не проверка настоящих
ACL/Injection Guard, SDK, моделей, сети, cold connect/migration или runtime ОС.
Фабрика не заменяет controller: запуск только существующим parent SOURCE runner.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sqlite3
from types import MethodType, SimpleNamespace
from typing import Any, Dict
import unittest


__test__ = False

CASE_NAMES = (
    "test_01_health_has_no_evaluation_or_repair",
    "test_02_display_limit_changes_only_samples",
    "test_03_bounded_scan_discloses_unexamined_tail",
    "test_04_observed_defects_stay_degraded_with_unknowns",
    "test_05_empty_metadata_is_not_overall_health",
    "test_06_hygiene_coefficients_and_finding_units",
    "test_07_json_and_legacy_key_compatibility",
    "test_08_no_eval_cases_are_unknown_not_zero",
    "test_09_evaluated_zero_is_genuine_failure",
    "test_10_evaluated_pass_partial_and_clamps",
    "test_11_eval_leak_checks_and_recall_free_callbacks",
    "test_12_eval_failure_propagates_without_substitute",
    "test_13_top_window_is_not_whole_active_corpus",
)


def build_suite(owners_source: str, helper_source: str | None = None,
                scratch: Path | None = None) -> unittest.TestSuite:
    """Явная stdlib suite; inputs уже exact-bound родителем, не loader продукта."""
    if not isinstance(owners_source, str) or helper_source is not None:
        raise ValueError("exact_selected_owners_and_no_helper_required")
    tree = ast.parse(owners_source, filename="<health-selected-owners>")
    declarations = tree.body
    if (len(declarations) == 1 and isinstance(declarations[0], ast.If)
            and isinstance(declarations[0].test, ast.Constant)
            and declarations[0].test.value is True and not declarations[0].orelse):
        declarations = declarations[0].body
    if (len(declarations) != 2
            or any(not isinstance(node, ast.FunctionDef) for node in declarations)
            or [node.name for node in declarations] != ["_health", "_evaluate_retrieval"]
            or any(node.decorator_list for node in declarations)):
        raise ValueError("only_health_and_evaluate_retrieval_owners_required")
    synthetic_root = Path(scratch) if scratch is not None else Path("synthetic-health-source")

    class HealthAssessmentSource(unittest.TestCase):
        __test__ = False

        def setUp(self):
            self.conn = sqlite3.connect(":memory:")
            self.addCleanup(self.conn.close)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript("""
                CREATE TABLE claims (
                    id TEXT PRIMARY KEY, status TEXT, topic TEXT, claim TEXT,
                    evidence TEXT, type TEXT, trust_class TEXT, updated_at INTEGER,
                    salience REAL, confidence REAL, normalized_claim TEXT,
                    source_type TEXT, last_verified_at INTEGER,
                    verification_status TEXT, quality_flags TEXT, source_ref TEXT,
                    derived_from TEXT, review_state TEXT
                );
                CREATE TABLE contradictions (status TEXT);
                CREATE TABLE index_outbox (status TEXT, created_at INTEGER);
                CREATE TABLE memory_consumers (updated_at INTEGER);
                CREATE TABLE retrieval_eval_cases (
                    id TEXT PRIMARY KEY, query TEXT, must_topics TEXT,
                    must_not_topics TEXT, must_include TEXT, must_not_include TEXT,
                    updated_at INTEGER
                );
            """)
            self.events = []
            self.statements = []
            self.conn.set_trace_callback(self.statements.append)
            self.env = {}
            self.namespace = {
                "Dict": Dict, "Any": Any, "Path": Path, "json": json,
                "sqlite3": sqlite3, "os": SimpleNamespace(environ=self.env),
                "PLUGIN_VERSION": "synthetic-version",
                "VALID_CLAIM_STATUSES": {"active", "archived", "uncertain"},
                "BAD_TOPICS": {"bad-topic", "broken/topic"}, "CANONICAL_TOPICS": {"general"},
                "now": lambda: 200000,
                "short": lambda value, n=240: str(value or "")[:n],
                "topic_integrity_reason": lambda topic: "synthetic_invalid_slug" if topic == "broken/topic" else "",
                "claim_quality": lambda text, topic: 0.1 if "LOW_QUALITY" in text else 0.9,
                "is_bad_claim_fragment": lambda text: ("FRAGMENT" in text, "synthetic_fragment" if "FRAGMENT" in text else ""),
                "is_ephemeral_fragment": lambda text: "SYNTHETIC_ARTIFACT" in text,
                "redact_secrets": lambda text: str(text).replace("SYNTHETIC_SECRET", "[REDACTED]"),
                "secret_scan": lambda text: {"raw_secret": "SYNTHETIC_SECRET" in text},
                "_background_jobs": SimpleNamespace(enabled=lambda: False),
                "_online_metrics": SimpleNamespace(enabled=lambda: False),
            }
            # Execute the supplied source verbatim, not an independently copied
            # health algorithm. No namespace copy after function creation.
            exec(compile(owners_source, "<health-selected-owners>", "exec"), self.namespace)
            self.assertIs(self.namespace["_health"].__globals__, self.namespace)
            self.assertIs(self.namespace["_evaluate_retrieval"].__globals__, self.namespace)
            self.provider = SimpleNamespace(
                db_path=synthetic_root / "synthetic-memory.sqlite",
                bot_id="synthetic-bot", session_id="synthetic-session", project_scope="",
                _connect=lambda: self.conn,
                _cols=lambda table: [row["name"] for row in self.conn.execute("PRAGMA table_info(claims)")],
                _meta_text=lambda key: "synthetic-instance",
                _meta_int=lambda key: 0,
                _last_seen_revision=lambda session: 0,
                _chat_hash=lambda session: "synthetic-chat-hash",
                _infer_topic=lambda text: "general",
                _contains_eval_terms=lambda text, terms: all(str(term).lower() in text.lower() for term in terms),
            )
            self.provider._health = MethodType(self.namespace["_health"], self.provider)
            self.provider._evaluate_retrieval = self._trap("evaluate_retrieval")
            for name in ("_search", "_pack_context", "_semantic_available", "_embed",
                         "_embed_document", "_rerank_rows", "_repair", "_rebuild_fts"):
                setattr(self.provider, name, self._trap(name))

        def _trap(self, name):
            def denied(*args, **kwargs):
                self.events.append((name, args, kwargs))
                raise AssertionError("unexpected_synthetic_callback:" + name)
            return denied

        def _claims(self, rows):
            values = []
            for number, overrides in enumerate(rows):
                row = dict(id=f"c_{number:06d}", status="active", topic="general",
                           claim="Synthetic durable fact", evidence="", type="fact",
                           trust_class="user", updated_at=number, salience=1.0, confidence=0.9)
                row.update(overrides)
                values.append(tuple(row[key] for key in (
                    "id", "status", "topic", "claim", "evidence", "type",
                    "trust_class", "updated_at", "salience", "confidence")))
            self.conn.executemany("""INSERT INTO claims
                (id,status,topic,claim,evidence,type,trust_class,updated_at,salience,confidence)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", values)
            self.conn.commit()

        def _case(self, case_id="case", query="synthetic query", **requirements):
            fields = ("must_topics", "must_not_topics", "must_include", "must_not_include")
            self.conn.execute("INSERT INTO retrieval_eval_cases VALUES(?,?,?,?,?,?,?)", (
                case_id, query, *(json.dumps(requirements.get(key, [])) for key in fields), 1))
            self.conn.commit()

        def _callbacks(self, rows=(), context="", *, chunks=0):
            def search(query, limit, include_stale, *, record_retrieval):
                self.events.append(("search", query, limit, include_stale, record_retrieval))
                self.assertIs(record_retrieval, False)
                return list(rows)
            def pack(query, max_chars, *, record_retrieval):
                self.events.append(("pack", query, max_chars, record_retrieval))
                self.assertIs(record_retrieval, False)
                return {"context": context, "chunk_count": chunks}
            self.provider._search = search
            self.provider._pack_context = pack

        def _evaluate(self, limit=10, max_chars=3800):
            return self.namespace["_evaluate_retrieval"](self.provider, limit, max_chars)

        def test_01_health_has_no_evaluation_or_repair(self):
            self._claims([{}])
            self._case()  # Existing cases must not cause implicit evaluation.
            before = self.conn.total_changes
            result = self.provider._health(1)
            self.assertEqual(self.events, [])
            self.assertEqual(self.conn.total_changes, before)
            self.assertIsNone(result["health_score"])
            self.assertIsNone(result["metrics"]["health_components"]["retrieval_quality"])
            self.assertEqual(result["assessment"]["status"], "UNKNOWN")
            self.assertIn("retrieval_quality", result["assessment"]["unknown_components"])

        def test_02_display_limit_changes_only_samples(self):
            self._claims([dict(topic="broken/topic", claim="{LOW_QUALITY SYNTHETIC_ARTIFACT\n}",
                               evidence="SYNTHETIC_SECRET") for _ in range(120)])
            self.statements.clear()
            one = self.provider._health(1)
            first_queries = list(self.statements)
            self.statements.clear()
            hundred = self.provider._health(100)
            self.assertEqual(first_queries, self.statements)
            self.assertEqual(one["metrics"], hundred["metrics"])
            self.assertEqual(one["assessment"], hundred["assessment"])
            self.assertEqual(one["issues"], hundred["issues"])
            self.assertIsNone(one["health_score"])
            self.assertEqual(one["health_score"], hundred["health_score"])
            for key in ("schema_anomalies", "low_quality", "bad_topics", "raw_blobs", "secret_hits"):
                self.assertEqual(len(one[key]), 1)
                self.assertEqual(len(hundred[key]), 100)
                self.assertEqual(one[key], hundred[key][:1])
            self.assertEqual(one["metrics"]["schema_anomalies"], 120)
            self.assertEqual(one["metrics"]["low_quality"], 120)
            self.assertEqual(one["metrics"]["bad_topics"], 120)
            self.assertEqual(one["metrics"]["raw_blobs"], 120 * 2)
            self.assertEqual(one["metrics"]["secret_hits"], 120)
            self.assertEqual(self.events, [])

        def test_03_bounded_scan_discloses_unexamined_tail(self):
            self._claims([dict(claim="LOW_QUALITY", topic="broken/topic")] + [{} for _ in range(20000)])
            result = self.provider._health(1)
            metrics = result["metrics"]
            self.assertEqual(metrics["claims"], 20001)
            self.assertEqual(metrics["active_claims"], 20001)
            for key in ("metadata", "active"):
                self.assertEqual(metrics["scan_coverage"][key], {
                    "population_total": 20001, "scanned": 20000, "scan_limit": 20000,
                    "denominator": 20000, "complete": False, "window_complete": True,
                    "truncated": True})
            self.assertEqual(metrics["schema_anomalies"], 0)  # Tail is NOT counted as examined.
            self.assertEqual(metrics["low_quality"], 0)
            self.assertIsNone(metrics["health_components"]["db_health"])
            self.assertIsNone(metrics["health_components"]["semantic_quality"])
            self.assertIn("bounded_scan_incomplete", result["assessment"]["reasons"])
            self.assertIn("semantic_quality", result["assessment"]["unknown_components"])
            self.assertIsNone(result["health_score"])
            # Exact-boundary counterpart: the remaining 20000 are genuinely scanned.
            self.conn.execute("DELETE FROM claims WHERE id='c_000000'")
            self.conn.commit()
            boundary = self.provider._health(100)
            self.assertTrue(boundary["metrics"]["scan_coverage"]["active"]["complete"])
            self.assertEqual(boundary["metrics"]["health_components"]["semantic_quality"], 1.0)
            self.assertEqual(boundary["assessment"]["status"], "UNKNOWN")

        def test_04_observed_defects_stay_degraded_with_unknowns(self):
            self._claims([dict(topic="broken/topic", claim="LOW_QUALITY")])
            self.provider._cols = lambda table: {"type"}  # Synthetic incomplete migration metadata.
            result = self.provider._health(1)
            assessment = result["assessment"]
            self.assertEqual(assessment["version"], "memory-wiki.health-assessment/v1")
            self.assertEqual(assessment["status"], "DEGRADED")
            self.assertIs(assessment["complete"], False)
            self.assertIn("schema_missing", assessment["reasons"])
            self.assertIn("schema_anomalies_observed", assessment["reasons"])
            self.assertEqual(assessment["components"]["db_health"]["status"], "DEGRADED")
            self.assertTrue({"retrieval_quality", "extraction", "persistence", "fts_integrity",
                             "vector_coverage", "document_retrieval", "rerank"}.issubset(assessment["unknown_components"]))
            self.assertIsNone(result["health_score"])
            self.assertEqual(self.events, [])

        def test_05_empty_metadata_is_not_overall_health(self):
            result = self.provider._health()
            self.assertEqual(result["metrics"]["claims"], 0)
            self.assertEqual(result["assessment"]["status"], "UNKNOWN")
            self.assertIn("no_active_claim_observations", result["assessment"]["reasons"])
            self.assertIsNone(result["health_score"])
            for key in ("secret_health", "semantic_quality", "artifact_pollution", "retrieval_quality"):
                self.assertIsNone(result["metrics"]["health_components"][key])
            for key in ("secret_health", "semantic_quality", "artifact_pollution"):
                self.assertIsNone(result["assessment"]["components"][key]["observed_score"])
            for key in ("metadata", "active", "top_active"):
                self.assertEqual(result["metrics"]["scan_coverage"][key]["denominator"], 0)
            self.assertEqual(self.events, [])

        def test_06_hygiene_coefficients_and_finding_units(self):
            self._claims([dict(status="invalid", topic="broken/topic"),
                          dict(topic="bad-topic", claim="{LOW_QUALITY SYNTHETIC_ARTIFACT\n}",
                               evidence="SYNTHETIC_SECRET")])
            self.conn.execute("INSERT INTO contradictions VALUES('open')")
            self.conn.execute("INSERT INTO index_outbox VALUES('failed',1)")
            self.conn.commit()
            result = self.provider._health(1)
            metrics = result["metrics"]
            self.assertEqual(metrics["schema_anomalies"], 2)  # Two fields, one metadata row.
            self.assertEqual(metrics["raw_blobs"], 2)  # Two finding kinds, one active row.
            self.assertEqual(metrics["bad_topics"], 1)
            self.assertEqual(metrics["low_quality"], 1)
            self.assertEqual(metrics["secret_hits"], 1)
            components = metrics["health_components"]
            self.assertAlmostEqual(components["db_health"], 1.0 - 2 * 0.10)
            self.assertAlmostEqual(components["secret_health"], 1.0 - 0.10)
            self.assertAlmostEqual(components["semantic_quality"], 1.0 - (0.03 + 0.02 + 2 * 0.04))
            self.assertAlmostEqual(components["artifact_pollution"], 1.0 - 0.06)
            self.assertAlmostEqual(components["contradiction_health"], 1.0 - 0.015)
            self.assertIn("failed_outbox_jobs_observed", result["assessment"]["reasons"])
            self.assertEqual(result["assessment"]["status"], "DEGRADED")
            self.assertNotIn("SYNTHETIC_SECRET", json.dumps(result["secret_hits"]))

        def test_07_json_and_legacy_key_compatibility(self):
            self._claims([{}])
            result = self.provider._health()
            decoded = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
            self.assertEqual(decoded, result)
            self.assertTrue({"version", "health_score", "metrics", "shared_memory", "issues",
                             "schema_anomalies", "low_quality", "bad_topics", "raw_blobs", "secret_hits"}.issubset(decoded))
            self.assertEqual(decoded["version"], "synthetic-version")
            self.assertIsNone(decoded["health_score"])
            self.assertEqual(set(decoded["metrics"]["health_components"]), {
                "db_health", "secret_health", "semantic_quality", "artifact_pollution",
                "retrieval_quality", "contradiction_health"})
            self.assertEqual(decoded["shared_memory"]["status"], "unverified")
            self.assertIn("latest_qdrant_revision", decoded["shared_memory"])

        def test_08_no_eval_cases_are_unknown_not_zero(self):
            result = self._evaluate()
            self.assertEqual(result["cases"], 0)
            self.assertIsNone(result["score"])
            self.assertEqual(result["summary"], {"passed": 0, "failed": 0})
            self.assertEqual(result["results"], [])
            self.assertEqual(result["assessment"]["status"], "UNKNOWN")
            self.assertEqual(result["assessment"]["denominator"], 0)
            self.assertEqual(result["assessment"]["reasons"], ["no_cases"])
            self.assertEqual(result["assessment"]["unknown_components"], ["retrieval_quality"])
            self.assertEqual(self.events, [])
            self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

        def test_09_evaluated_zero_is_genuine_failure(self):
            self._case(must_include=["required evidence"])
            self._callbacks()
            result = self._evaluate(5, 2500)
            self.assertIsInstance(result["score"], float)
            self.assertEqual(result["score"], 0.0)
            self.assertEqual((result["cases"], result["passed"], result["failed"]), (1, 0, 1))
            self.assertEqual(result["assessment"]["status"], "FAIL")
            self.assertEqual(result["results"][0]["missing_text"], ["required evidence"])
            self.assertEqual(self.events, [("search", "synthetic query", 5, False, False),
                                           ("pack", "synthetic query", 2500, False)])

        def test_10_evaluated_pass_partial_and_clamps(self):
            self._case("pass", must_topics=["calibration"], must_include=["durable"])
            self._callbacks([{"id": "safe", "topic": "calibration", "claim": "durable evidence"}], chunks=1)
            passed = self._evaluate(500, 50000)
            self.assertEqual(passed["score"], 1.0)
            self.assertEqual(passed["assessment"]["status"], "PASS")
            self.assertEqual(passed["results"][0]["pack_chunks"], 1)
            self.assertEqual(self.events, [("search", "synthetic query", 50, False, False),
                                           ("pack", "synthetic query", 12000, False)])
            self.events.clear()
            self._case("fail", must_include=["absent phrase"])
            partial = self._evaluate()
            self.assertEqual(partial["score"], 0.5)
            self.assertEqual((partial["cases"], partial["passed"], partial["failed"]), (2, 1, 1))
            self.assertEqual(partial["assessment"]["status"], "FAIL")
            self.assertEqual(partial["assessment"]["denominator"], 2)
            self.assertEqual(partial["assessment"]["scope"], "selected_cases")
            self.assertEqual(len(self.events), 4)

        def test_11_eval_leak_checks_and_recall_free_callbacks(self):
            self._case(must_not_topics=["blocked"], must_not_include=["FORBIDDEN"])
            self._callbacks([{"id": "artifact", "topic": "blocked", "trust_class": "tool_log",
                              "claim": "SYNTHETIC_ARTIFACT SYNTHETIC_SECRET FORBIDDEN"}])
            result = self._evaluate()
            self.assertEqual(result["score"], 0.0)
            self.assertEqual(result["leak_cases"], 1)
            row = result["results"][0]
            self.assertFalse(row["ok"])
            self.assertEqual(row["bad_topics"], ["blocked"])
            self.assertEqual(row["forbidden"], ["FORBIDDEN"])
            self.assertEqual(row["artifact_hits"], ["artifact"])
            self.assertIs(row["secret_leak"], True)
            self.assertEqual(len(self.events), 2)
            # Callback asserts the exact False keyword, not mere falsiness.
            self.assertTrue(all(event[-1] is False for event in self.events))

        def test_12_eval_failure_propagates_without_substitute(self):
            self._case()
            primary = RuntimeError("synthetic search unavailable")
            def fail(*args, **kwargs):
                self.events.append("search_failed")
                raise primary
            self.provider._search = fail
            with self.assertRaises(RuntimeError) as caught:
                self._evaluate()
            self.assertIs(caught.exception, primary)
            self.assertEqual(self.events, ["search_failed"])
            # Default health neither retries the evaluator nor substitutes 0.75.
            self.events.clear()
            result = self.provider._health()
            self.assertEqual(self.events, [])
            self.assertIsNone(result["health_score"])
            self.assertIsNone(result["metrics"]["health_components"]["retrieval_quality"])

        def test_13_top_window_is_not_whole_active_corpus(self):
            self._claims([dict(id=f"c_{i:06d}", salience=1.0) for i in range(80)] + [
                dict(id="c_tail", salience=0.0, trust_class="tool_log")])
            result = self.provider._health()
            top = result["metrics"]["scan_coverage"]["top_active"]
            self.assertEqual(top["scanned"], 80)
            self.assertEqual(top["population_total"], 81)
            self.assertEqual(top["denominator"], 80)
            self.assertIs(top["window_complete"], True)
            self.assertIs(top["complete"], False)
            self.assertIs(top["truncated"], True)
            self.assertEqual(result["metrics"]["top_artifacts"], 0)
            component = result["assessment"]["components"]["artifact_pollution"]
            self.assertEqual(component["scope"], "top_active")
            self.assertEqual(component["status"], "OBSERVED")
            self.assertIsNone(result["health_score"])
            self.assertEqual(result["assessment"]["status"], "UNKNOWN")

    return unittest.TestSuite(HealthAssessmentSource(name) for name in CASE_NAMES)
