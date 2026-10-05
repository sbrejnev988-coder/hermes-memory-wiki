"""R02 source-slice regressions; NOT a native SDK/package integration gate.

Execute the exact supplied recall function, exact production SQLite DDL and
actual provider ACL methods. No provider/package initialization or SDK double.
The runner selects BASE for RED and the separate overlay for GREEN.
"""
from __future__ import annotations

import ast
import hashlib
import sqlite3
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(globals().get("BASE", ROOT))
SOURCE_PATH = Path(globals().get("SOURCE_PATH", BASE / "recall_orchestrator.py"))
INIT_PATH = Path(globals().get("INIT_PATH", BASE / "__init__.py"))
PROOF_RECORDS = []


def source_functions(tree, names, namespace, filename):
    found = {
        name: [node for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef) and node.name == name]
        for name in names
    }
    assert all(len(nodes) == 1 for nodes in found.values())
    nodes = [ast.ImportFrom(module="__future__",
                            names=[ast.alias(name="annotations")], level=0)]
    for name in names:
        node = found[name][0]
        assert not node.decorator_list
        nodes.append(node)
    compiled = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                       str(filename), "exec")
    exec(compiled, namespace)
    return namespace


class NullPaginationRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recall_tree = ast.parse(SOURCE_PATH.read_bytes(), filename=str(SOURCE_PATH))
        init_tree = ast.parse(INIT_PATH.read_bytes(), filename=str(INIT_PATH))
        cls.recall = source_functions(
            recall_tree, ["_detect_conflicts", "_answer_policy"],
            {"time": time, "sqlite3": sqlite3}, SOURCE_PATH,
        )
        for node in recall_tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "_CONFLICT_PAGE_SIZE", "_CONFLICT_MAX_ROWS", "_CONFLICT_TIMEOUT_SECONDS",
                    }:
                        cls.recall[target.id] = ast.literal_eval(node.value)
        assert cls.recall["_CONFLICT_PAGE_SIZE"] == 40
        assert cls.recall["_CONFLICT_MAX_ROWS"] == 200
        assert cls.recall["_CONFLICT_TIMEOUT_SECONDS"] == 0.25
        cls.acl = source_functions(
            init_tree, ["_chat_hash", "_claim_visible", "_contradiction_visible"],
            {"hashlib": hashlib}, INIT_PATH,
        )
        strings = [node.value for node in ast.walk(init_tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        cls.claim_ddl = next(value for value in strings
                             if value.startswith("CREATE TABLE IF NOT EXISTS claims("))
        cls.contradiction_ddl = next(value for value in strings
                                     if value.startswith("CREATE TABLE IF NOT EXISTS contradictions("))
        # Use the actual additive column declarations, without running _migrate,
        # imports, lifecycle workers, provider initialization or any private IO.
        declarations = []
        for node in ast.walk(init_tree):
            if (isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
                    and [part.id for part in node.target.elts if isinstance(part, ast.Name)]
                    == ["col", "typ", "default"]):
                try:
                    candidate = ast.literal_eval(node.iter)
                except (ValueError, TypeError):
                    continue
                columns = {part[0] for part in candidate}
                if {"origin_chat_hash", "normalized_claim", "decay_policy"} <= columns:
                    declarations.append(candidate)
        assert len(declarations) == 1
        cls.claim_columns = declarations[0]

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute(self.claim_ddl)
        existing = {row["name"] for row in self.connection.execute("PRAGMA table_info(claims)")}
        for name, type_name, default in self.claim_columns:
            if name not in existing:
                self.connection.execute(
                    f"ALTER TABLE claims ADD COLUMN {name} {type_name} NOT NULL DEFAULT {default}"
                )
        self.connection.execute(self.contradiction_ddl)
        self.provider = types.SimpleNamespace(
            _connect=lambda: self.connection,
            bot_id="r02-fixture-bot", session_id="r02-fixture-chat",
            project_scope="r02-fixture-project", database_instance_id="r02-fixture-instance",
        )
        for name, function in self.acl.items():
            if name.startswith("_") and callable(function):
                setattr(self.provider, name, types.MethodType(function, self.provider))
        for claim_id, visible in [("selected", True), ("visible", True), ("hidden", False),
                                  ("unrelated", True)]:
            self.connection.execute(
                "INSERT INTO claims(id,claim,topic,created_at,updated_at,freshness_at,hash,"
                "visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (claim_id, "Synthetic fixture claim.", "fixture", 1000, 1000, 1000, claim_id,
                 "chat", self.provider.bot_id,
                 self.provider._chat_hash() if visible else "PRIVATE_CHAT_SENTINEL",
                 self.provider.session_id if visible else "PRIVATE_SESSION_SENTINEL"),
            )
        self.connection.commit()

    def add_conflict(self, conflict_id, endpoint="hidden", *, stamp=1000, status="open",
                     selected="selected", reason="PRIVATE_REASON_SENTINEL"):
        self.connection.execute(
            "INSERT INTO contradictions(id,claim_a,claim_b,reason,status,created_at) "
            "VALUES(?,?,?,?,?,?)", (conflict_id, selected, endpoint, reason, status, stamp),
        )

    def add_hidden(self, count):
        for index in range(count):
            self.add_conflict(f"hidden_{index:04d}")

    def snapshot(self):
        return [tuple(row) for row in self.connection.execute(
            "SELECT rowid,* FROM contradictions ORDER BY rowid"
        )]

    def detect(self):
        return self.recall["_detect_conflicts"](self.provider, ["selected"])

    def assert_private_omitted(self, status):
        import json
        policy = self.recall["_answer_policy"](["[M:C:selected]"], status)
        rendered = json.dumps((status, policy))
        for marker in ["hidden_", "PRIVATE_", "ERROR_SENTINEL", "_conflict_rowid", "opaque_"]:
            self.assertNotIn(marker, rendered)
        self.assertEqual(policy["conflict_status"], status)
        return policy

    def test_exact_null_id_off_page_is_present(self):
        # The independently reproduced exact R02 boundary: 40 hidden + row 41
        # with NULL TEXT PRIMARY KEY, same timestamp, both endpoints visible.
        self.add_hidden(40)
        self.add_conflict(None, "visible")
        self.connection.commit()
        info = next(row for row in self.connection.execute("PRAGMA table_info(contradictions)")
                    if row["name"] == "id")
        self.assertEqual((info["type"], info["pk"], info["notnull"]), ("TEXT", 1, 0))
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        rows = self.connection.execute(
            "SELECT * FROM contradictions ORDER BY created_at DESC,id DESC"
        ).fetchall()
        self.assertEqual(len(rows), 41)
        self.assertIsNone(rows[-1]["id"])
        self.assertFalse(any(self.provider._contradiction_visible(row, self.connection)
                             for row in rows[:40]))
        self.assertTrue(self.provider._contradiction_visible(rows[-1], self.connection))
        before = self.snapshot()
        actual = self.detect()
        PROOF_RECORDS.append({"case": self._testMethodName, "actual": actual,
                              "exact_ddl_nullable_pk": True, "foreign_key_errors": 0,
                              "exhaustive_actual_acl_visible": True,
                              "borrowed_connection_queryable": self.connection.execute(
                                  "SELECT 1").fetchone()[0] == 1,
                              "snapshot_released": not self.connection.in_transaction})
        self.assertEqual(actual, "present", "R02 exact SQL-valid NULL key must not prove absence")
        self.assertEqual(self.snapshot(), before, "Read-only fix must not assign or repair IDs")
        self.assertFalse(self.connection.in_transaction)
        self.assertIs(self.provider._connect(), self.connection)
        policy = self.assert_private_omitted(actual)
        self.assertNotIn("No visible open contradictions were found", policy["instruction"])

    def observe_acl(self, after=None):
        visited = []
        actual_acl = self.provider._contradiction_visible

        def observed(row, connection):
            self.assertIs(connection, self.connection)
            visited.append((row["id"], row["created_at"], row["reason"]))
            visible = actual_acl(row, connection)
            if after is not None:
                after()
            return visible

        self.provider._contradiction_visible = observed
        return visited

    def verify_read(self, expected, *, visits=None, visited=None):
        self.connection.commit()
        before = self.snapshot()
        actual = self.detect()
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)
        self.assertIs(self.provider._connect(), self.connection)
        self.assertFalse(self.connection.in_transaction)
        PROOF_RECORDS.append({"case": self._testMethodName, "actual": actual,
                              "rows": len(before), "acl_calls": len(visited) if visited is not None else None,
                              "snapshot_released": True, "foreign_key_errors": 0,
                              "borrowed_connection_queryable": True, "data_unchanged": True})
        self.assertEqual(actual, expected)
        if visited is not None:
            self.assertEqual(len(visited), visits)
            self.assertEqual(len(set(visited)), visits, "No NULL page may replay or skip rows")
        policy = self.assert_private_omitted(actual)
        if actual == "unknown":
            self.assertIn("Do not claim there are no contradictions", policy["instruction"])
        return actual

    def test_multiple_null_ids_paginate_across_two_null_pages(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible", reason="PRIVATE_VISIBLE_SENTINEL")
        for index in range(80):
            self.add_conflict(None, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        visited = self.observe_acl()
        self.verify_read("present", visits=121, visited=visited)
        self.assertTrue(all(row["id"] is None for row in self.connection.execute(
            "SELECT id FROM contradictions WHERE reason LIKE 'PRIVATE_REASON_SENTINEL_%'"
        )))

    def test_null_only_scope_is_exhausted_without_skips(self):
        for index in range(81):
            self.add_conflict(None, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        visited = self.observe_acl()
        self.verify_read("absent", visits=81, visited=visited)

    def test_empty_id_visible_after_full_nonnull_page(self):
        self.add_hidden(40)
        self.add_conflict("", "visible")
        self.verify_read("present")
        self.assertEqual(self.connection.execute(
            "SELECT id FROM contradictions WHERE claim_b='visible'"
        ).fetchone()[0], "")

    def test_null_after_empty_id_page_boundary_is_present(self):
        self.add_hidden(39)
        self.add_conflict("")
        self.add_conflict(None, "visible")
        self.verify_read("present")

    def test_ordinary_valid_id_positive_with_same_timestamps(self):
        self.add_hidden(40)
        self.add_conflict("a_visible", "visible")
        visited = self.observe_acl()
        self.verify_read("present", visits=41, visited=visited)

    def test_null_lower_timestamp_is_not_skipped(self):
        for index in range(40):
            self.add_conflict(f"hidden_{index:04d}", stamp=1001)
        self.add_conflict(None, "visible", stamp=1000)
        self.verify_read("present")

    def test_paging_from_null_cursor_reaches_lower_timestamp_valid_id(self):
        for index in range(40):
            self.add_conflict(None, stamp=1001, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        self.add_conflict("a_visible", "visible", stamp=1000)
        visited = self.observe_acl()
        self.verify_read("present", visits=41, visited=visited)

    def test_exhausted_199_null_rows_can_prove_absent(self):
        for index in range(199):
            self.add_conflict(None, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        visited = self.observe_acl()
        self.verify_read("absent", visits=199, visited=visited)

    def test_exact_200_null_rows_require_unknown(self):
        for index in range(200):
            self.add_conflict(None, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        visited = self.observe_acl()
        self.verify_read("unknown", visits=200, visited=visited)

    def test_201_mixed_hidden_rows_require_unknown_with_200_acl_checks(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible", reason="PRIVATE_VISIBLE_SENTINEL")
        for index in range(161):
            self.add_conflict(None, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        visited = self.observe_acl()
        self.verify_read("unknown", visits=200, visited=visited)

    def test_ordinary_201_valid_hidden_rows_preserve_budget_unknown(self):
        self.add_hidden(201)
        self.add_conflict("a_visible", "visible")
        visited = self.observe_acl()
        self.verify_read("unknown", visits=200, visited=visited)

    def test_visible_null_row_at_200th_check_is_present(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible", reason="PRIVATE_VISIBLE_SENTINEL")
        for index in range(159):
            self.add_conflict(None, reason=f"PRIVATE_REASON_SENTINEL_{index:04d}")
        visited = self.observe_acl()
        self.verify_read("present", visits=200, visited=visited)

    def test_unrelated_open_and_relevant_resolved_null_rows_do_not_count(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible", selected="unrelated")
        self.add_conflict(None, "visible", status="resolved")
        visited = self.observe_acl()
        self.verify_read("absent", visits=40, visited=visited)

    def test_foreign_key_declarations_reject_orphan_endpoint(self):
        foreign_keys = self.connection.execute("PRAGMA foreign_key_list(contradictions)").fetchall()
        self.assertEqual({(row["from"], row["table"], row["to"], row["on_delete"])
                          for row in foreign_keys}, {
            ("claim_a", "claims", "id", "CASCADE"), ("claim_b", "claims", "id", "CASCADE"),
        })
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_conflict(None, "missing-fixture-endpoint")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM contradictions").fetchone()[0], 0)
        self.add_conflict(None, "visible")
        self.verify_read("present")

    def test_zero_deadline_is_unknown_before_any_conflict_query(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible")
        original = self.recall["_CONFLICT_TIMEOUT_SECONDS"]
        self.addCleanup(self.recall.__setitem__, "_CONFLICT_TIMEOUT_SECONDS", original)
        self.recall["_CONFLICT_TIMEOUT_SECONDS"] = 0
        traced = []
        self.connection.set_trace_callback(traced.append)
        self.addCleanup(self.connection.set_trace_callback, None)
        self.verify_read("unknown")
        # Exclude the fixture snapshot/inspection reads, which lack status='open'.
        self.assertFalse(any("FROM contradictions WHERE status='open'" in sql for sql in traced))

    def test_cooperative_deadline_stops_after_actual_acl_and_releases(self):
        self.add_hidden(2)
        clock = [0.0]
        original = self.recall["time"]
        self.addCleanup(self.recall.__setitem__, "time", original)
        self.recall["time"] = types.SimpleNamespace(monotonic=lambda: clock[0])
        visited = self.observe_acl(after=lambda: clock.__setitem__(0, 1.0))
        self.verify_read("unknown", visits=1, visited=visited)

    def test_cooperative_deadline_after_sql_stops_before_acl(self):
        self.add_hidden(2)
        clock = [0.0]
        original = self.recall["time"]
        self.addCleanup(self.recall.__setitem__, "time", original)
        self.recall["time"] = types.SimpleNamespace(monotonic=lambda: clock[0])
        def advance_on_query(sql):
            if "FROM contradictions WHERE status='open'" in sql:
                clock[0] = 1.0
        self.connection.set_trace_callback(advance_on_query)
        self.addCleanup(self.connection.set_trace_callback, None)
        visited = self.observe_acl()
        self.verify_read("unknown", visits=0, visited=visited)

    def deny_release(self, once):
        denied = []
        def authorizer(action, operation, name, *_unused):
            if (action == sqlite3.SQLITE_SAVEPOINT and operation == "RELEASE"
                    and str(name).startswith("memory_wiki_conflicts_")
                    and (not once or not denied)):
                denied.append(True)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.connection.set_authorizer(authorizer)
        self.addCleanup(self.connection.set_authorizer, None)
        return denied

    def test_one_shot_release_failure_promotes_confirmed_null_presence_to_unknown(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible")
        self.connection.commit()
        denied = self.deny_release(once=True)
        self.assertEqual(self.detect(), "unknown")
        self.assertTrue(denied)
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)
        self.assert_private_omitted("unknown")

    def test_persistent_release_refusal_keeps_borrowed_connection_open(self):
        self.add_conflict(None, "visible")
        self.connection.commit()
        denied = self.deny_release(once=False)
        actual = self.detect()
        self.assertEqual(actual, "unknown")
        self.assertTrue(denied)
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)
        self.assertTrue(self.connection.in_transaction)
        PROOF_RECORDS.append({"case": self._testMethodName, "actual": actual,
                              "borrowed_connection_queryable": True,
                              "persistent_release_refusal_leaves_transaction_open": True,
                              "inherited_limit_not_cleanup_success": True})
        self.assert_private_omitted(actual)
        # Fixture owner cleanup, AFTER observing the production result/state.
        self.connection.set_authorizer(None)
        self.connection.rollback()

    def test_release_failure_does_not_commit_or_rollback_outer_caller_work(self):
        self.add_conflict(None, "visible")
        self.connection.execute("CREATE TABLE fixture_pending(value TEXT)")
        self.connection.commit()
        self.connection.execute("BEGIN")
        self.connection.execute("INSERT INTO fixture_pending VALUES('caller-owned-uncommitted')")
        denied = self.deny_release(once=True)
        actual = self.detect()
        self.assertEqual(actual, "unknown")
        self.assertTrue(denied)
        self.assertTrue(self.connection.in_transaction)
        self.assertEqual(self.connection.execute("SELECT value FROM fixture_pending").fetchone()[0],
                         "caller-owned-uncommitted")
        self.assertIs(self.provider._connect(), self.connection)
        self.assert_private_omitted(actual)
        self.connection.set_authorizer(None)
        self.connection.rollback()
        self.assertEqual(self.connection.execute("SELECT count(*) FROM fixture_pending").fetchone()[0], 0)

    def test_successful_conflict_read_preserves_outer_caller_transaction(self):
        self.add_hidden(40)
        self.add_conflict(None, "visible")
        self.connection.execute("CREATE TABLE fixture_pending(value TEXT)")
        self.connection.commit()
        self.connection.execute("SAVEPOINT fixture_owner")
        self.connection.execute("INSERT INTO fixture_pending VALUES('caller-owned-uncommitted')")
        self.assertEqual(self.detect(), "present")
        self.assertTrue(self.connection.in_transaction)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM fixture_pending").fetchone()[0], 1)
        self.connection.execute("ROLLBACK TO fixture_owner")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM fixture_pending").fetchone()[0], 0)
        self.connection.execute("RELEASE fixture_owner")
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)

    def test_connection_failure_returns_unknown_without_exception_detail(self):
        def unavailable():
            raise sqlite3.OperationalError("ERROR_SENTINEL hidden_ PRIVATE_REASON_SENTINEL")
        self.provider._connect = unavailable
        actual = self.detect()
        self.assertEqual(actual, "unknown")
        self.assert_private_omitted(actual)
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)

    def test_sql_read_refusal_returns_unknown_without_false_absence(self):
        self.add_conflict(None, "visible")
        self.connection.commit()
        def authorizer(action, table, *_unused):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == "contradictions" else sqlite3.SQLITE_OK
        self.connection.set_authorizer(authorizer)
        self.addCleanup(self.connection.set_authorizer, None)
        actual = self.detect()
        self.assertEqual(actual, "unknown")
        self.assert_private_omitted(actual)
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)

    def test_acl_failure_returns_unknown_without_exception_detail(self):
        self.add_conflict(None, "visible")
        self.connection.commit()
        def unavailable(*_unused):
            raise ValueError("ERROR_SENTINEL hidden_ PRIVATE_REASON_SENTINEL")
        self.provider._contradiction_visible = unavailable
        actual = self.detect()
        self.assertEqual(actual, "unknown")
        self.assert_private_omitted(actual)
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(self.connection.execute("SELECT 1").fetchone()[0], 1)

    def test_empty_selected_scope_does_not_open_connection(self):
        called = []
        self.provider._connect = lambda: called.append(True)
        actual = self.recall["_detect_conflicts"](self.provider, [])
        self.assertEqual(actual, "absent")
        self.assertEqual(called, [])
        self.assert_private_omitted(actual)
