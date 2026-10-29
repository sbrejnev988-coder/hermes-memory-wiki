"""Prepared SOURCE policy/hash controls plus AST-only actual-wrapper wiring.

Collection is inert. Use the existing devtools source_bootstrap + unittest
lifecycle after a separate parent admission; this file is not an admission.
Only the small policy module executes, on authored bytes/stamps/closers. The wrapper,
SQL, document guards, descriptor open/read/close, native authority, SDK and MCP
are inspected as AST, NEVER replaced by permitting fixtures or executed here.
No __init__.py input/binding, compressed carrier, SDK stand-in or new runner.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unittest

__test__ = False


def _function(tree, name):
    matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError("unique_source_function_required")
    return matches[0]


def _calls(node, name):
    return sorted((n for n in ast.walk(node) if isinstance(n, ast.Call)
                   and ast.unparse(n.func) == name), key=lambda n: (n.lineno, n.col_offset))


def _strings(node):
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and type(n.value) is str}


class SourceFileObservationSource(unittest.TestCase):
    __test__ = False

    @classmethod
    def setUpClass(cls):
        if not (sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.no_site):
            raise RuntimeError("original_isolated_source_bootstrap_required")
        if not callable(globals().get("devtools_read_bound")) or not globals().get("DEVTOOLS_INPUTS"):
            raise RuntimeError("original_bound_source_reader_required")
        cls.trees = {name: ast.parse(raw, filename=cls.paths[name]) for name, raw in cls.raw.items()}
        # Execute exact SMALL policy bytes only, behind the original audit fence.
        # No rewriting imports, globals overlay, wrapper exec or authority mock.
        cls.policy = {"__name__": "_file_observation_SOURCE", "__file__": cls.paths["source_file_observation.py"]}
        exec(compile(cls.raw["source_file_observation.py"], cls.paths["source_file_observation.py"],
                     "exec", dont_inherit=True), cls.policy)

    @classmethod
    def tearDownClass(cls):
        cls.policy = cls.trees = cls.raw = cls.paths = None

    def setUp(self):
        started = getattr(type(self), "case_started", None)
        if started is not None:
            started(type(self).__name__ + "." + self._testMethodName)
        self.digest = hashlib.sha256(b"authored saved bytes").hexdigest()
        self.revision_id = "docrev_" + "a" * 28
        self.source = dict(source_id="docsrc_" + "b" * 24, revision_id=self.revision_id,
                           file_hash=self.digest, active=1, status="ok", parser="text", parser_version="v1")
        self.revision = dict(source_id=self.source["source_id"], revision_id=self.revision_id,
                             file_hash=self.digest, status="active", unit_count=2, parser="text", parser_version="v1")
        self.connector = dict(document_source_id=self.source["source_id"], content_hash=self.digest,
                              revision_key=self.digest[:20])
        self.indexed = self.policy["indexed_revision_evidence"](self.source, self.revision, self.connector)
        self.stamp = (1, 2, len(b"authored saved bytes"), 100, 200)

    def test_01_current_and_changed_are_explicit_point_in_time_byte_decisions(self):
        self.assertEqual(self.indexed, dict(state="available", revision_id=self.revision_id, file_hash=self.digest))
        current = self.policy["observation_result"](self.indexed, "stable", self.digest, 125.5)
        changed_hash = hashlib.sha256(b"authored other saved bytes").hexdigest()
        changed = self.policy["observation_result"](self.indexed, "stable", changed_hash, 126.5)
        self.assertEqual((current["status"], changed["status"]), ("current_at_check", "changed_at_check"))
        self.assertEqual(current["checked_at"], 125.5)
        self.assertEqual(changed["disk_at_check"], dict(state="stable", file_hash=changed_hash))
        self.assertEqual(changed["indexed_revision"], current["indexed_revision"])
        self.assertEqual(current["parser_validity"], "not_checked")
        self.assertEqual(set(current), {"status", "indexed_revision", "disk_at_check", "checked_at", "parser_validity"})

    def test_02_matching_hash_cannot_promote_incoherent_or_unusable_indexed_metadata(self):
        cases = [("source", "active", 0), ("source", "status", "unsupported"),
                 ("source", "revision_id", "docrev_bad"), ("source", "file_hash", "A" * 64),
                 ("revision", "source_id", "other"), ("revision", "revision_id", "docrev_" + "c" * 28),
                 ("revision", "file_hash", "d" * 64), ("revision", "status", "superseded"),
                 ("revision", "unit_count", 0), ("revision", "unit_count", True),
                 ("revision", "parser", "other"), ("revision", "parser_version", "v2"),
                 ("connector", "content_hash", "e" * 64), ("connector", "revision_key", "f" * 20),
                 ("connector", "document_source_id", "other")]
        for role, key, value in cases:
            with self.subTest(role=role, field=key):
                rows = {"source": dict(self.source), "revision": dict(self.revision), "connector": dict(self.connector)}
                rows[role][key] = value
                unavailable = self.policy["indexed_revision_evidence"](**rows)
                self.assertEqual(unavailable, dict(state="unavailable", revision_id=None, file_hash=None))
                out = self.policy["observation_result"](unavailable, "stable", self.digest, 1.0)
                self.assertEqual(out["status"], "indexed_revision_unavailable")
                self.assertEqual(out["disk_at_check"]["file_hash"], self.digest)
        self.assertEqual(self.policy["indexed_revision_evidence"](self.source, None, self.connector)["state"], "unavailable")

    def test_03_nonstable_disk_states_keep_indexed_revision_without_partial_hashes(self):
        before = copy.deepcopy(self.indexed)
        for state in ("missing", "locked", "unsupported", "too_large", "unavailable", "unstable"):
            with self.subTest(state=state):
                out = self.policy["observation_result"](self.indexed, state, self.digest, 4.0)
                self.assertEqual(out["status"], state + "_at_check")
                self.assertEqual(out["disk_at_check"], dict(state=state, file_hash=None))
                self.assertEqual(out["indexed_revision"], before)
        self.assertEqual(self.indexed, before)
        self.assertEqual(self.policy["observation_result"](self.indexed, "invented", self.digest, 4.0)["status"], "unavailable_at_check")
        self.assertEqual(self.policy["observation_result"](self.indexed, "stable", None, 4.0)["status"], "unstable_at_check")

    def test_04_hash_empty_exact_limit_and_multiblock_reads_are_bounded(self):
        for data in (b"", b"x", b"y" * (1024 * 1024 + 7)):
            with self.subTest(size=len(data)):
                stream, requests = io.BytesIO(data), []
                def read(count):
                    requests.append(count)
                    return stream.read(count)
                actual = self.policy["hash_exact_bytes"](read, size=len(data), max_bytes=len(data))
                self.assertEqual(actual, hashlib.sha256(data).hexdigest())
                self.assertTrue(all(0 < n <= 1024 * 1024 for n in requests))
                self.assertEqual(sum(requests), len(data))
                self.assertEqual(stream.tell(), len(data))  # no max+1 probe
        stream = io.BytesIO(b"abcdef")
        actual = self.policy["hash_exact_bytes"](lambda n: stream.read(min(n, 2)), size=6, max_bytes=6)
        self.assertEqual(actual, hashlib.sha256(b"abcdef").hexdigest())

    def test_05_partial_nonbytes_and_oversized_blocks_never_supply_hash_evidence(self):
        self.assertIsNone(self.policy["hash_exact_bytes"](io.BytesIO(b"abc").read, size=4, max_bytes=4))
        for block in (b"", "x", bytearray(b"x"), b"xx"):
            with self.subTest(block_type=type(block).__name__, size=len(block)):
                self.assertIsNone(self.policy["hash_exact_bytes"](lambda n: block, size=1, max_bytes=1))
        def forbidden(count):
            raise AssertionError("size refusal must precede reads")
        for size, limit in ((2, 1), (-1, 1), (True, 1), (1, False), (0, -1)):
            with self.subTest(size=size, limit=limit):
                with self.assertRaisesRegex(ValueError, "^observation_size_refused$"):
                    self.policy["hash_exact_bytes"](forbidden, size=size, max_bytes=limit)

    def test_06_all_six_identity_size_and_timestamp_samples_must_agree(self):
        stamps = (self.stamp,) * 6
        stable = self.policy["stable_file_hash"]
        self.assertTrue(stable(stamps, self.digest, self.digest))
        for sample in range(6):
            for field in range(5):
                with self.subTest(sample=sample, field=field):
                    changed = list(stamps)
                    values = list(changed[sample])
                    values[field] += 1
                    changed[sample] = tuple(values)
                    self.assertFalse(stable(tuple(changed), self.digest, self.digest))
        for invalid in (stamps[:-1], list(stamps), ((0, 2, 3, 4, 5),) * 6,
                        ((1, 0, 3, 4, 5),) * 6, ((1, 2, -1, 4, 5),) * 6, ((1, 2, 3, True, 5),) * 6):
            self.assertFalse(stable(invalid, self.digest, self.digest))

    def test_07_same_stat_different_hash_and_replacement_same_bytes_are_not_current(self):
        stable = self.policy["stable_file_hash"]
        self.assertFalse(stable((self.stamp,) * 6, self.digest, "f" * 64))
        self.assertFalse(stable((self.stamp,) * 6, self.digest, None))
        self.assertFalse(stable((self.stamp,) * 6, "bad", "bad"))
        replacement = (1, 999, *self.stamp[2:])
        self.assertFalse(stable((self.stamp,) * 4 + (replacement, self.stamp), self.digest, self.digest))
        # Stable observations are not a scheduler, lease or parser assertion.
        self.assertEqual(self.policy["observation_result"](self.indexed, "unstable", self.digest, 5.0)["disk_at_check"]["file_hash"], None)

    def test_08_error_classification_never_stringifies_private_paths_or_raw_errors(self):
        class PrivateError(OSError):
            def __str__(self):
                raise AssertionError("raw error disclosure")
        wrapped = ValueError("authored private path")
        wrapped.__cause__ = FileNotFoundError("authored private path")
        self.assertEqual(self.policy["file_error_state"](wrapped), "missing")
        locked = PrivateError()
        locked.winerror = 32
        self.assertEqual(self.policy["file_error_state"](locked), "locked")
        self.assertEqual(self.policy["file_error_state"](PermissionError("authored denied path")), "unavailable")
        generic = PrivateError()
        generic.__cause__ = generic
        self.assertEqual(self.policy["file_error_state"](generic), "unavailable")

    def test_09_refusal_envelopes_have_no_file_state_or_indexed_identifiers(self):
        for state in ("invalid_request", "not_authorized", "unavailable_at_check", "arbitrary raw failure"):
            out = self.policy["unobserved_result"](state, 7.0)
            self.assertEqual(out["disk_at_check"], dict(state="not_checked", file_hash=None))
            self.assertEqual(out["indexed_revision"], dict(state="unavailable", revision_id=None, file_hash=None))
            self.assertEqual(out["checked_at"], 7.0)
            self.assertNotIn("arbitrary raw failure", json.dumps(out))
            self.assertNotIn("source_id", out)

    def test_10_STATIC_real_wrapper_reaches_hash_engine_only_after_registration_and_authority(self):
        node = _function(self.trees["source_connectors.py"], "observe_local_file")
        self.assertEqual([a.arg for a in node.args.args], ["provider", "args"])
        self.assertEqual(len(_calls(node, "_observe_file_bytes")), 1)
        read = _calls(node, "_observe_file_bytes")[0]
        self.assertLess(_calls(node, "_observation_rows")[0].lineno, read.lineno)
        self.assertLess(_calls(node, "documents._document_disclosure")[0].lineno, read.lineno)
        self.assertLess(_calls(node, "_scope")[0].lineno, read.lineno)
        self.assertLess(_calls(node, "authorize")[0].lineno, read.lineno)
        self.assertGreater(_calls(node, "authorize")[-1].lineno, read.lineno)
        self.assertEqual(ast.unparse(read.args[-1]), "authorize")
        self.assertIn('with documents._document_profile_scope(Path(provider.home)):', ast.unparse(node))
        self.assertFalse(_calls(node, "documents._allowed_path"))  # only the already admitted I/O helper touches paths
        self.assertFalse(_calls(node, "args.get") and any(c.args and isinstance(c.args[0], ast.Constant)
                         and c.args[0].value == "path" for c in _calls(node, "args.get")))
        self.assertIn("set(args) - {'source_key', 'scope_id', 'repository_id'}", ast.unparse(node))

    def test_11_STATIC_cold_unowned_or_changed_provider_never_bootstraps_sql(self):
        tree = self.trees["source_connectors.py"]
        node = _function(tree, "_observation_connection_current")
        text = ast.unparse(node)
        for fragment in ("isinstance(conn, sqlite3.Connection)", "getattr(provider, '_conn', None) is conn",
                         "getattr(provider, '_owned_conn', None) is conn", "not conn.in_transaction",
                         "_observation_actor(provider) == actor", "'_transaction_quarantine'", "'_lifecycle_state'"):
            self.assertIn(fragment, text)
        actor = _function(tree, "_observation_actor")
        self.assertEqual(len(_calls(actor, "documents._document_embedding_actor")), 1)
        entry = _function(tree, "observe_local_file")
        self.assertIn("if conn is None or lock is None:", ast.unparse(entry))
        self.assertIn("with lock:", ast.unparse(entry))
        identity = _function(tree, "_source_key")
        self.assertEqual([a.arg for a in identity.args.kwonlyargs], ["_existing_only"])
        assignment = next(n for n in identity.body if isinstance(n, ast.Assign))
        self.assertIsInstance(assignment.value, ast.IfExp)
        self.assertEqual(ast.unparse(assignment.value.test), "_existing_only")
        self.assertFalse(_calls(assignment.value.body, "provider._meta_text"))
        self.assertEqual(len(_calls(assignment.value.orelse, "provider._meta_text")), 1)
        call = _calls(entry, "_source_key")[0]
        self.assertEqual([(k.arg, ast.literal_eval(k.value)) for k in call.keywords], [("_existing_only", True)])

    def test_12_STATIC_original_scope_owner_and_full_row_images_are_retained(self):
        node = _function(self.trees["source_connectors.py"], "_observation_rows")
        self.assertEqual(len(_calls(node, "documents._assert_source_access")), 1)
        owner = _calls(node, "documents._assert_connector_owner")[0]
        self.assertEqual([(k.arg, ast.unparse(k.value)) for k in owner.keywords], [("_conn", "conn")])
        self.assertEqual(len(_calls(node, "disclosure.documents")), 1)
        pairs = [(ast.literal_eval(c.args[0]), ast.literal_eval(c.args[1])) for c in _calls(node, "disclosure.watch")]
        self.assertEqual(pairs, [("external_sources", "source_key"), ("document_sources", "source_id"),
                                ("external_sources", "document_source_id"), ("document_revisions", "revision_id")])
        text = ast.unparse(node)
        for fragment in ("len(links) != 1", "link['owner_bot_id'] != owner", "link['scope_id'] != scope_id",
                         "link['repository_id'] != repository_id", "link['source_type'] != 'local_file'",
                         "link['status'] != 'active'", "source['active'] != 1", "len(all_links) != 1",
                         "all_links[0] != link", "revisions[0]['source_id'] != source['source_id']"):
            self.assertIn(fragment, text)
        entry = _function(self.trees["source_connectors.py"], "observe_local_file")
        authorize = next(n for n in ast.walk(entry) if isinstance(n, ast.FunctionDef) and n.name == "authorize")
        self.assertIn("_observation_rows(provider, conn, disclosure, key, scope_id, repository_id, owner) != original", ast.unparse(authorize))
        self.assertEqual(len(_calls(authorize, "disclosure.finish")), 1)

    def test_13_STATIC_descriptor_and_hash_stability_are_wired_not_a_detached_engine(self):
        node = _function(self.trees["source_connectors.py"], "_observe_file_bytes")
        self.assertEqual(len(_calls(node, "documents._open_allowed_file")), 1)
        self.assertEqual(len(_calls(node, "documents._allowed_path")), 2)
        self.assertEqual(len(_calls(node, "os.fstat")), 4)
        self.assertEqual(len(_calls(node, "checked.stat")), 2)
        hashes = _calls(node, "file_observation.hash_exact_bytes")
        self.assertEqual(len(hashes), 2)
        for call in hashes:
            self.assertEqual(ast.unparse(call.args[0]), "lambda count: os.read(fd, count)")
            self.assertEqual([(k.arg, ast.unparse(k.value)) for k in call.keywords], [("size", "opened[2]"), ("max_bytes", "max_bytes")])
        stable = _calls(node, "file_observation.stable_file_hash")[0]
        self.assertEqual([ast.unparse(a) for a in stable.args],
                         ["(path_before, opened, middle, after_read, path_after, final_descriptor)", "first_hash", "second_hash"])
        early = next(n for n in ast.walk(node) if isinstance(n, ast.If)
                     and ast.unparse(n.test) == "path_before[:3] != opened[:3]")
        self.assertLess(early.lineno, hashes[0].lineno)
        self.assertEqual(ast.unparse(early.body[0]), "return ('unstable', None)")
        self.assertNotIn("path_before != opened", ast.unparse(node))
        self.assertEqual([ast.unparse(a) for a in _calls(node, "os.lseek")[0].args], ["fd", "0", "os.SEEK_SET"])
        stamp = _function(self.trees["source_connectors.py"], "_observation_stamp")
        self.assertEqual(len(_calls(stamp, "documents._file_identity")), 1)
        self.assertEqual(len(_calls(stamp, "stat.S_ISREG")), 1)
        entry = _function(self.trees["source_connectors.py"], "observe_local_file")
        bounds = _calls(entry, "documents._env_int")[0]
        self.assertEqual(ast.literal_eval(bounds.args[0]), "MEMORY_WIKI_DOCUMENT_MAX_BYTES")
        self.assertEqual([ast.literal_eval(a) for a in bounds.args[2:]], [1_000_000, 2_000_000_000])

    def test_14_STATIC_observation_has_no_mutation_parser_worker_or_unsafe_opener(self):
        tree = self.trees["source_connectors.py"]
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and (n.name.startswith("_observation_") or n.name in {"observe_local_file", "_observe_file_bytes"})]
        prohibited = {"_connect", "connect", "commit", "rollback", "unlink", "write", "open", "fdopen",
                      "ingest_document", "embed_pending_documents", "_snapshot_allowed_file", "_extract",
                      "sync_local_file", "install_document_graph_schema", "install_source_connector_schema",
                      "delete_source", "delete_document", "Thread", "spawn_context_thread"}
        for node in nodes:
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
            for call in calls:
                name = ast.unparse(call.func).split(".")[-1]
                self.assertNotIn(name, prohibited)
                if name == "execute":
                    self.assertTrue(ast.literal_eval(call.args[0]).startswith("SELECT value FROM document_graph_meta WHERE key=?"))
        io_node = _function(tree, "_observe_file_bytes")
        self.assertIn("identity_owner is not None and str(identity_owner[0]) != source_id", ast.unparse(io_node))
        self.assertIn("file_identity_owner:", " ".join(_strings(io_node)))

    def test_15_STATIC_descriptor_cleanup_preserves_primary_and_never_retries_fd(self):
        node = _function(self.trees["source_connectors.py"], "_observe_file_bytes")
        self.assertEqual(len(_calls(node, "os.close")), 1)
        outer = next(n for n in node.body if isinstance(n, ast.Try))
        self.assertTrue(outer.finalbody)
        fatal = next(h for h in outer.handlers if isinstance(h.type, ast.Name) and h.type.id == "BaseException")
        authority = next(h for h in outer.handlers if isinstance(h.type, ast.Name) and h.type.id == "_ObservationAuthorityChanged")
        for handler in (fatal, authority):
            self.assertEqual(ast.unparse(handler.body[0]), "primary = error")
            self.assertIsInstance(handler.body[1], ast.Raise)
        cleanup = outer.finalbody[0]
        self.assertIsInstance(cleanup, ast.If)
        self.assertEqual(ast.unparse(cleanup.test), "fd is not None")
        finish = _calls(cleanup, "file_observation.finish_descriptor")
        self.assertEqual(len(finish), 1)
        self.assertEqual([ast.unparse(a) for a in finish[0].args], ["lambda: os.close(fd)", "primary"])
        helper = _function(self.trees["source_file_observation.py"], "finish_descriptor")
        self.assertEqual(len(_calls(helper, "close_descriptor")), 1)
        self.assertEqual(len(_calls(helper, "selected.add_note")), 1)
        self.assertIn("not isinstance(primary, Exception) or isinstance(cleanup_error, Exception)", ast.unparse(helper))
        cleanup_try = next(n for n in helper.body if isinstance(n, ast.Try))
        self.assertEqual(ast.unparse(cleanup_try.handlers[0].type), "BaseException")
        note_try = next(n for n in cleanup_try.handlers[0].body if isinstance(n, ast.Try))
        self.assertEqual(ast.unparse(note_try.handlers[0].type), "BaseException")
        self.assertIsInstance(note_try.handlers[0].body[0], ast.Pass)
        propagate = cleanup_try.handlers[0].body[-1]
        self.assertEqual(ast.unparse(propagate.test), "not preserve_primary")
        self.assertIsNone(propagate.body[0].exc)  # bare raise keeps exact cleanup identity
        entry = _function(self.trees["source_connectors.py"], "observe_local_file")
        entry_try = next(n for n in entry.body if isinstance(n, ast.Try))
        self.assertEqual([ast.unparse(h.type) for h in entry_try.handlers],
                         ["(PermissionError, _ObservationAuthorityChanged)", "Exception"])

    def test_16_STATIC_small_policy_has_no_filesystem_sql_or_product_imports(self):
        tree = self.trees["source_file_observation.py"]
        imports = [a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names]
        self.assertEqual(imports, ["hashlib", "re"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.With))])
        for name in ("open", "os.open", "sqlite3.connect", "Path", "eval", "exec"):
            self.assertFalse(_calls(tree, name))
        result = _function(tree, "observation_result")
        self.assertTrue({"current_at_check", "changed_at_check", "parser_validity", "not_checked"}.issubset(_strings(result)))


    def test_17_stable_distinct_path_and_FD_timestamp_domains_reach_current_or_changed(self):
        # Authored separate clocks, not rewritten/normalized platform samples.
        for data, expected in ((b"authored saved bytes", "current_at_check"),
                               (b"authored other saved bytes", "changed_at_check")):
            with self.subTest(status=expected):
                path_stamp = (1, 2, len(data), 100, 200)
                fd_stamp = (1, 2, len(data), 300, 900)
                self.assertNotEqual(path_stamp[3:], fd_stamp[3:])
                requests = []
                stream = io.BytesIO(data)
                def read(count):
                    requests.append(count)
                    return stream.read(count)
                first = self.policy["hash_exact_bytes"](read, size=len(data), max_bytes=len(data))
                stream.seek(0)
                second = self.policy["hash_exact_bytes"](read, size=len(data), max_bytes=len(data))
                stamps = (path_stamp, fd_stamp, fd_stamp, fd_stamp, path_stamp, fd_stamp)
                self.assertTrue(self.policy["stable_file_hash"](stamps, first, second))
                self.assertEqual(sum(requests), 2 * len(data))
                self.assertTrue(all(0 < n <= min(len(data), 1024 * 1024) for n in requests))
                result = self.policy["observation_result"](self.indexed, "stable", first, 10.0)
                self.assertEqual(result["status"], expected)
                # Every sample/field still distinguishes a mutation within its
                # own domain, including path and FD mtime AND ctime.
                for sample in range(6):
                    for field in range(5):
                        with self.subTest(sample=sample, field=field):
                            changed = list(stamps)
                            stamp = list(changed[sample])
                            stamp[field] += 1
                            changed[sample] = tuple(stamp)
                            self.assertFalse(self.policy["stable_file_hash"](tuple(changed), first, second))
                self.assertFalse(self.policy["stable_file_hash"](stamps, first, "f" * 64))

    def test_18_connected_close_fault_composition_preserves_fatal_identity_and_refusal(self):
        class Fatal(BaseException):
            pass
        # This is the real SMALL cleanup primitive, with authored callables;
        # no descriptor, wrapper exec, SQL authority or permissive owner mock.
        body_factories = (lambda: None, PermissionError, TypeError, KeyboardInterrupt, SystemExit, Fatal)
        cleanup_factories = (lambda: None, OSError, KeyboardInterrupt, SystemExit, Fatal)
        for body_factory in body_factories:
            for cleanup_factory in cleanup_factories:
                body, cleanup = body_factory(), cleanup_factory()
                with self.subTest(body=type(body).__name__, cleanup=type(cleanup).__name__):
                    closes = []
                    def close():
                        closes.append("once")
                        if cleanup is not None:
                            raise cleanup
                    def guarded_body():
                        primary = None
                        try:
                            if body is not None:
                                raise body
                            return "stable"
                        except BaseException as error:
                            primary = error
                            raise
                        finally:
                            self.policy["finish_descriptor"](close, primary)
                    def public_envelope():
                        try:
                            return guarded_body()
                        except PermissionError:
                            return "not_authorized"
                        except Exception:
                            return "unavailable_at_check"
                    selected = body
                    if cleanup is not None and (body is None or (
                            isinstance(body, Exception) and not isinstance(cleanup, Exception))):
                        selected = cleanup
                    if selected is not None and not isinstance(selected, Exception):
                        with self.assertRaises(BaseException) as raised:
                            public_envelope()
                        self.assertIs(raised.exception, selected)
                    else:
                        expected = ("stable" if selected is None else "not_authorized"
                                    if isinstance(selected, PermissionError) else "unavailable_at_check")
                        self.assertEqual(public_envelope(), expected)
                    self.assertEqual(closes, ["once"])  # UNKNOWN never retries an integer FD

    def test_19_cleanup_diagnostic_failure_never_replaces_selected_primary_or_fatal(self):
        for diagnostic in (RuntimeError("private diagnostic"), KeyboardInterrupt("private diagnostic")):
            for selected_role in ("body_fatal", "cleanup_fatal", "ordinary_authority"):
                with self.subTest(diagnostic=type(diagnostic).__name__, selected=selected_role):
                    notes, closes = [], []
                    class BadNote:
                        def add_note(self, note):
                            notes.append(note)
                            raise diagnostic
                    class BodyFatal(BadNote, BaseException):
                        pass
                    class CleanupFatal(BadNote, BaseException):
                        pass
                    class Authority(BadNote, PermissionError):
                        pass
                    body = BodyFatal() if selected_role == "body_fatal" else Authority()
                    cleanup = CleanupFatal() if selected_role == "cleanup_fatal" else OSError()
                    selected = cleanup if selected_role == "cleanup_fatal" else body
                    def close():
                        closes.append("once")
                        raise cleanup
                    def operation():
                        try:
                            raise body
                        finally:
                            self.policy["finish_descriptor"](close, body)
                    with self.assertRaises(BaseException) as raised:
                        operation()
                    self.assertIs(raised.exception, selected)
                    self.assertEqual(closes, ["once"])
                    self.assertEqual(notes, ["observation descriptor cleanup failed; outcome UNKNOWN"])
        # No pending primary: even a hostile ordinary cleanup diagnostic must
        # not replace the cleanup exception with its own fatal cancellation.
        class BadCleanup(OSError):
            def add_note(self, note):
                raise SystemExit("diagnostic only")
        cleanup = BadCleanup()
        calls = []
        def close():
            calls.append("once")
            raise cleanup
        with self.assertRaises(OSError) as raised:
            self.policy["finish_descriptor"](close, None)
        self.assertIs(raised.exception, cleanup)
        self.assertEqual(calls, ["once"])

    def test_20_STATIC_alias_guard_uses_opened_identity_and_original_scope_before_any_read(self):
        tree = self.trees["source_connectors.py"]
        entry = _function(tree, "observe_local_file")
        read = _calls(entry, "_observe_file_bytes")[0]
        self.assertEqual([ast.unparse(a) for a in read.args],
                         ["provider", "conn", "path", "source['source_id']", "scope_id", "repository_id", "max_bytes", "authorize"])
        node = _function(tree, "_observe_file_bytes")
        self.assertEqual([a.arg for a in node.args.args],
                         ["provider", "conn", "path", "source_id", "scope_id", "repository_id", "max_bytes", "authorize"])
        alias = _calls(node, "documents._assert_ingest_path_alias_owner")
        self.assertEqual(len(alias), 1)
        self.assertEqual([ast.unparse(a) for a in alias[0].args],
                         ["provider", "conn", "checked", "source_id", "scope_id", "repository_id"])
        self.assertEqual([(k.arg, ast.unparse(k.value)) for k in alias[0].keywords], [("opened_identity", "opened[:2]")])
        first_read = _calls(node, "file_observation.hash_exact_bytes")[0]
        self.assertLess(_calls(node, "os.fstat")[0].lineno, alias[0].lineno)
        self.assertLess(alias[0].lineno, first_read.lineno)
        self.assertTrue(any(alias[0].lineno < call.lineno < first_read.lineno for call in _calls(node, "authorize")))
        alias_try = next(n for n in ast.walk(node) if isinstance(n, ast.Try)
                         and any(isinstance(stmt, ast.Expr) and stmt.value is alias[0] for stmt in n.body))
        self.assertEqual(ast.unparse(alias_try.handlers[0].type), "PermissionError")
        self.assertEqual(ast.unparse(alias_try.handlers[0].body[0]), "raise _ObservationAuthorityChanged() from None")
        self.assertFalse(_calls(node, "documents._remember_file_identity"))
        self.assertFalse(_calls(node, "documents._file_identity_history"))  # real guard owns this policy

    def test_21_STATIC_real_alias_guard_retains_legacy_history_orphan_and_replacement_branches(self):
        # Structural controls of the actual guard, NOT a synthetic owner
        # classifier and NOT a runtime claim about Windows or legacy SQLite.
        tree = self.trees["document_knowledge_graph.py"]
        guard = _function(tree, "_assert_ingest_path_alias_owner")
        text = ast.unparse(guard)
        platform = guard.body[1]
        self.assertEqual(ast.unparse(platform.test), "os.name != 'nt'")
        self.assertIsInstance(platform.body[0], ast.Return)  # no silent POSIX scan
        for fragment in ("if opened_identity is None:", "candidate_identity = opened_identity",
                         "owner is not None and str(owner[0]) != source_id",
                         "WHERE source_id<>?", "(source_id,)",
                         "history = _file_identity_history(conn, str(row['source_id']))",
                         "stored_path.casefold() == str(path).casefold()",
                         "candidate_identity != live_identity and candidate_identity not in history",
                         "except FileNotFoundError as exc:", "not history and int(row['active'] or 0)",
                         "not old_volume or not new_volume or old_volume == new_volume",
                         "if candidate_identity not in history:", "except OSError as exc:",
                         "str(row['scope_id'] or '') != scope_id", "str(row['repository_id'] or '') != repository_id"):
            self.assertIn(fragment, text)
        # Live unrelated legacy replacements and retired/no-history missing
        # paths continue; active same-volume orphans and known aliases refuse.
        scan = next(n for n in guard.body if isinstance(n, ast.For))
        spelling = next(n for n in scan.body if isinstance(n, ast.If))
        live = next(n for n in ast.walk(spelling) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == "candidate_identity != live_identity and candidate_identity not in history")
        self.assertIsInstance(live.body[0], ast.Continue)
        missing = next(h for n in ast.walk(spelling) if isinstance(n, ast.Try) for h in n.handlers
                       if isinstance(h.type, ast.Name) and h.type.id == "FileNotFoundError")
        orphan = next(n for n in missing.body if isinstance(n, ast.If))
        self.assertIsInstance(orphan.body[0], ast.Raise)
        history_miss = next(n for n in missing.body if isinstance(n, ast.If)
                            and ast.unparse(n.test) == "candidate_identity not in history")
        self.assertIsInstance(history_miss.body[0], ast.Continue)
        self.assertIsInstance(scan.body[-1], ast.Raise)  # even a same-scope alias is not enrolled
        owner = _calls(guard, "_assert_connector_owner")
        self.assertEqual(len(owner), 1)
        self.assertEqual([(k.arg, ast.unparse(k.value)) for k in owner[0].keywords], [("_conn", "conn")])
        self.assertFalse(_calls(guard, "provider._connect"))
        self.assertFalse(_calls(guard, "_remember_file_identity"))
        self.assertTrue(all(ast.literal_eval(c.args[0]).startswith("SELECT ") for c in _calls(guard, "conn.execute")))
        history = _function(tree, "_file_identity_history")
        absent = next(n for n in history.body if isinstance(n, ast.If) and ast.unparse(n.test) == "row is None")
        self.assertEqual(ast.unparse(absent.body[0]), "return set()")  # supported pre-history, not blanket denial
        connector = _function(tree, "_assert_connector_owner")
        self.assertIn("provider._connect() if _conn is None else _conn", ast.unparse(connector))



# Current composition is a NEW metadata-only cohort. The donor's 21 controls
# and original factory/main below are retained, not requalified by old PASS.
CURRENT_COMPOSITION_CASES = (
    "test_CURRENT_STATIC_exact_graph_conn_handoff_and_inverse",
    "test_CURRENT_STATIC_connectors_inverse_and_late_guard_counterpart",
    "test_CURRENT_STATIC_existing_identity_default_and_no_lazy_observer",
    "test_CURRENT_STATIC_version_lookup_and_graph_owners_byte_exact",
    "test_CURRENT_STATIC_revision_read_queries_and_authorization_order",
    "test_CURRENT_STATIC_accepted_observation_closure_and_original_conn",
)
CURRENT_PARENT_STATIC_CASES = (
    "test_PARENT_STATIC_f64_native_cache_bytes_and_no_public_observer",
    "test_PARENT_STATIC_complete_revision_schema_cache_parity",
)
F64_RAW_SHA256 = {
    "source_connectors.py": "a669ae7c28e949b7b9b56b6a9e02821c92d5af4770074487e2d7df1d61af1a5b",
    "document_knowledge_graph.py": "a5df8529d087a649edb884bbb50444437393bd9a166b54f711f5686301342edf",
    "__init__.py": "630df34f8e0c23ff00ade2d4d5a6dc1f54ef3bb3dccc796118d16555763bff5a",
    "mcp-wrapper/tool_schemas.json": "674d9e94ca1e7c0bc86561b0d217edb2a7a5d6844f296b69c05a87b43707cd14",
}
# Raw complete definition lines, including the last LF (not ast.dump gold).
# Producer: exact f64 Git blob -> ast.parse -> lineno..end_lineno byte lines.
F64_OWNER_RAW_SHA256 = {
    "source_connectors.py": {
        "_RecordCommitHook": "2bcceb71b49565b49e850a5f1f110a1de6932642b986f5d96ee698bba8a51e41",
        "_managed_record_generation": "4be83b4c66aa5586f9275e452b0ccd767ef77a067074127cc34287893a8b4fcd",
        "_record_snapshot_path": "df54f335bedd287a5ebe028894e6a8b8558d25860485b858fa62b5a7fa26248f",
        "sync_local_file": "7f7b9071c83156769bb3a6c87704c66a48214622724992da4fe52f36624520c8",
        "upsert_record": "c1044835002e9fc030d35869071a93b7e46f4593d3ce4b912d337fc478122902",
        "_put_source_in_transaction": "968188fd246a0bb905a7e9624310ab0c41cd6ab395b19fb021bd83006b62f351",
        "authorize_write": "a187666e30425df9614a161f570ddaa19bce8d36544823f4ffa9d38c58ed9436",
        "install_source_connector_schema": "b5e41511073541cfaaa3d5f8ff5fe69d4a4345987d509df603af10b5b6870673",
    },
    "document_knowledge_graph.py": {
        "_document_lookup_revision": "13661192ae369c4ccaf2673380b4674d8fee6045e527fc756dfb48fcdcff2770",
        "document_unit_context": "0c55fe0fd37e1fc8cb26684730a2189a9e56ddc1c7f2b2cd15d4348c58ea05cd",
        "document_neighbors": "671857cb4e35941c11bd91e4f4ae3f9c1bb24bc6aba1d90483202d5448526d88",
        "install_document_graph_schema": "3ae011986b5303a706c48503a0c5209e86ead0c8bad7a321f18491f889c9feff",
        "_assert_source_access": "58eb914dec078c7ab259856b231c0df4b9c46bd41153b97665bd877987da2e54",
        "_assert_connector_owner": "883467b7618bb42c346668cbeca0f94bc77a61500fe93c4756aa00149f4d7fa6",
        "_document_access_scope": "3bcaccf3df6cecc5a48530390a50e2d9d6a983362a7813d54ae54372e12e4f65",
        "_document_disclosure": "490f1aa63f32520fb47b3f4b6cf78875ec0e64be390dda4404b0396f6dc82fcd",
        "_disclosed_document_output": "02bc38ba72f561330be1eb3fe37649da31fa90141927b5e89376905f4a2325da",
        "_guard_document_output": "627a5300d3cd4667d98fad65b7deef005ffe4eb5855e9a7138ca093d915bace1",
        "_hydrate_document_unit": "24af088dcf52026bf09fc906dea6e2fa906294c7a1ba99c5188146c78cdb9c8d",
        "_stored_xlsx_context": "9f9e58c2cba1cf73794d63a849b55848c930becc3f935aaa3174804499743acd",
    },
}
E5_OBSERVATION_RAW_SHA256 = {
    "_ObservationAuthorityChanged": "9fd29037085618aacbed5691f80b3afa429675e326c62096e8b5332b876bf838",
    "_observation_actor": "ffe6371d2eeae6ac398bbfa1b4c7ec42b5d577777ee144b13e0a0f01c92c4611",
    "_observation_connection_current": "94444341c1005d9a03a0e67459a071b43094da0f754469fffec6c28003c38725",
    "_observation_rows": "dac6c85f0a2e4b6ae863f2454a8c2f3ec5fd36a24151a7b98d412bcf27138509",
    "_observation_stamp": "7a155cb68a6856dc71499adf2e5902839b54adc6254aa65511017ada8297b336",
    "_observe_file_bytes": "80cf050f4f1b465f953734753a152eb8edc509b29a43faefe5a19328cc05cab9",
    "observe_local_file": "6e03f551b9c64f40402117dd226e506b7f8efb9809fef76dc14669bb7cf90c1a",
    "_source_key": "3b319dc74f2c55aa7ad967858955d1e454215e1b2708e97a799b241dce283c41",
}


class CurrentObservationCompositionStatic(unittest.TestCase):
    """Only AST/JSON/raw metadata; NEVER exec policy, wrapper, SQL or SDK.

    The original 21-case factory remains separate. Large native schema inputs
    belong ONLY to the parent-static string-input cohort, not SOURCE bindings.
    No filesystem readers, neighbor worktree, provider or permitting doubles.
    """
    __test__ = False
    _sources = _declared_inputs = None
    _parent_static = False
    case_started = None

    @classmethod
    def setUpClass(cls):
        if not (sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.no_site):
            raise RuntimeError("original_isolated_source_bootstrap_required")
        if not cls._parent_static and (not callable(globals().get("devtools_read_bound"))
                                       or not globals().get("DEVTOOLS_INPUTS")):
            raise RuntimeError("original_bound_source_reader_required")
        cls.addClassCleanup(cls._release_sources)
        cls.raw, cls.trees = {}, {}
        for name, text in cls._sources.items():
            raw = text.encode("utf-8")
            digest, filename = cls._declared_inputs[name]
            # This does NOT alter the controller's SOURCE per-input admission.
            cap = 2_000_000 if cls._parent_static and name == "__init__.py" else 1_000_000
            if len(raw) > cap or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("exact_composition_source_binding_required")
            cls.raw[name] = raw
            if not name.endswith(".json"):
                cls.trees[name] = ast.parse(raw, filename=filename)

    @classmethod
    def _release_sources(cls):
        cls.raw = cls.trees = cls._sources = cls._declared_inputs = None
        cls.case_started = None

    def setUp(self):
        started = type(self).case_started
        if started is not None:
            started(type(self).__name__ + "." + self._testMethodName)

    def _span(self, filename, name):
        owners = [n for n in self.trees[filename].body
                  if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name]
        self.assertEqual(len(owners), 1)
        owner = owners[0]
        return b"".join(self.raw[filename].splitlines(keepends=True)[owner.lineno - 1:owner.end_lineno])

    def _connector_inverse(self, text):
        # A narrow inverse, not a blanket policy/hash rebaseline. Removing the
        # observation block must leave ALL current f64 late defenses unchanged.
        start = text.index("class _ObservationAuthorityChanged(")
        end = text.index("def sync_local_file(", start)
        text = text[:start] + text[end:]
        replacements = (
            ("import re\n", ""), ("import stat\n", ""),
            ("    from . import source_file_observation as file_observation\n", ""),
            ("    import source_file_observation as file_observation\n", ""),
            ('namespace: str = "record", *, _existing_only: bool = False) -> str:',
             'namespace: str = "record") -> str:'),
            ('    # Observation must never reach the historical lazy metadata fallback, even\n'
             '    # if the provider identity changes between its preflight and this lookup.\n'
             '    salt = (str(getattr(provider, "database_instance_id", "") or "") if _existing_only\n'
             '            else str(provider.database_instance_id or provider._meta_text("database_instance_id") or ""))\n',
             '    salt = str(provider.database_instance_id or provider._meta_text("database_instance_id") or "")\n'),
        )
        for before, after in replacements:
            self.assertEqual(text.count(before), 1)
            text = text.replace(before, after, 1)
        return text.encode("utf-8")

    def test_CURRENT_STATIC_exact_graph_conn_handoff_and_inverse(self):
        name = "document_knowledge_graph.py"
        guard = _function(self.trees[name], "_assert_ingest_path_alias_owner")
        calls = _calls(guard, "_assert_connector_owner")
        self.assertEqual(len(calls), 1)
        call = calls[0]
        expected = ast.parse('_assert_connector_owner(provider, str(row["source_id"]), _conn=conn)', mode="eval").body
        self.assertEqual(ast.dump(call), ast.dump(expected))
        for replacement in ([], [ast.keyword(arg="_conn", value=ast.Name(id="other_conn", ctx=ast.Load()))]):
            mutant = copy.deepcopy(call)
            mutant.keywords = replacement
            self.assertNotEqual(ast.dump(mutant), ast.dump(expected))
        added = b'        _assert_connector_owner(provider, str(row["source_id"]), _conn=conn)\n'
        prior = b'        _assert_connector_owner(provider, str(row["source_id"]))\n'
        self.assertEqual(self.raw[name].count(added), 1)
        inverse = self.raw[name].replace(added, prior, 1)
        self.assertEqual(hashlib.sha256(inverse).hexdigest(), F64_RAW_SHA256[name])
        # Includes legacy/history/orphan/replacement and every later graph guard.
        self.assertFalse(_calls(guard, "provider._connect"))

    def test_CURRENT_STATIC_connectors_inverse_and_late_guard_counterpart(self):
        name = "source_connectors.py"
        text = self.raw[name].decode("utf-8")
        self.assertEqual(hashlib.sha256(self._connector_inverse(text)).hexdigest(), F64_RAW_SHA256[name])
        for owner, digest in F64_OWNER_RAW_SHA256[name].items():
            with self.subTest(owner=owner):
                self.assertEqual(hashlib.sha256(self._span(name, owner)).hexdigest(), digest)
        token = "_RECORD_INGEST_HOOK.get() is not hook"
        self.assertEqual(text.count(token), 1)
        mutant = text.replace(token, "_RECORD_INGEST_HOOK.get() is hook", 1)
        self.assertNotEqual(hashlib.sha256(self._connector_inverse(mutant)).hexdigest(), F64_RAW_SHA256[name])

    def test_CURRENT_STATIC_existing_identity_default_and_no_lazy_observer(self):
        tree = self.trees["source_connectors.py"]
        key = _function(tree, "_source_key")
        self.assertEqual([a.arg for a in key.args.kwonlyargs], ["_existing_only"])
        self.assertEqual([ast.literal_eval(n) for n in key.args.kw_defaults], [False])
        self.assertEqual([ast.literal_eval(n) for n in key.args.defaults], ["record"])
        salt = key.body[0].value
        self.assertIsInstance(salt, ast.IfExp)
        self.assertEqual(ast.unparse(salt.test), "_existing_only")
        self.assertFalse(_calls(salt.body, "provider._meta_text"))
        self.assertEqual(ast.dump(salt.orelse), ast.dump(ast.parse(
            'str(provider.database_instance_id or provider._meta_text("database_instance_id") or "")', mode="eval").body))
        entries = _calls(_function(tree, "observe_local_file"), "_source_key")
        self.assertEqual(len(entries), 1)
        self.assertEqual([(k.arg, ast.literal_eval(k.value)) for k in entries[0].keywords], [("_existing_only", True)])
        for owner in ("sync_local_file", "upsert_record", "_RecordCommitHook"):
            definitions = [n for n in tree.body
                           if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == owner]
            self.assertEqual(len(definitions), 1)
            calls = _calls(definitions[0], "_source_key")
            self.assertTrue(calls)
            self.assertTrue(all(not c.keywords for c in calls))

    def test_CURRENT_STATIC_version_lookup_and_graph_owners_byte_exact(self):
        name = "document_knowledge_graph.py"
        for owner, digest in F64_OWNER_RAW_SHA256[name].items():
            with self.subTest(owner=owner):
                self.assertEqual(hashlib.sha256(self._span(name, owner)).hexdigest(), digest)
        helper = _function(self.trees[name], "_document_lookup_revision")
        self.assertIn("args['expected_revision_id'] != revision_id", ast.unparse(helper))
        self.assertNotIn("strip", {ast.unparse(c.func) for c in ast.walk(helper) if isinstance(c, ast.Call)})
        # Raw-span pins deliberately do not use version-sensitive AST hashes.
        mutant = self._span(name, "document_neighbors").replace(b"revision_id=? AND ", b"", 1)
        self.assertNotEqual(hashlib.sha256(mutant).hexdigest(), F64_OWNER_RAW_SHA256[name]["document_neighbors"])

    def test_CURRENT_STATIC_revision_read_queries_and_authorization_order(self):
        tree = self.trees["document_knowledge_graph.py"]
        expected_counts = {"document_unit_context": 3, "document_neighbors": 1}
        for owner, count in expected_counts.items():
            node = _function(tree, owner)
            pin = _calls(node, "_document_lookup_revision")
            self.assertEqual(len(pin), 1)
            self.assertEqual([ast.unparse(a) for a in pin[0].args], ["source", "args"])
            for guard in ("_assert_source_access", "_assert_connector_owner"):
                self.assertLess(_calls(node, guard)[0].lineno, pin[0].lineno)
            queries = [c for c in _calls(node, "conn.execute") if c.args
                       and isinstance(c.args[0], ast.Constant)
                       and any(table in c.args[0].value for table in (" FROM document_units ", " FROM document_edges "))]
            self.assertEqual(len(queries), count)
            for query in queries:
                sql = query.args[0].value
                self.assertIn("WHERE source_id=? AND revision_id=? AND active=1" if owner == "document_neighbors"
                              or sql.startswith("SELECT unit_id,") else "WHERE source_id=? AND revision_id=? AND ", sql)
                self.assertEqual([ast.unparse(v) for v in query.args[1].elts[:2]], ["source_id", "revision_id"])
                self.assertLess(pin[0].lineno, query.lineno)
                mutant = sql.replace("revision_id=? AND ", "", 1)
                self.assertNotIn("WHERE source_id=? AND revision_id=? AND ", mutant)
            output = _calls(node, "_disclosed_document_output")
            self.assertEqual(len(output), 1)
            self.assertEqual(ast.unparse(output[0].args[-1]), "disclosure")

    def test_CURRENT_STATIC_accepted_observation_closure_and_original_conn(self):
        name = "source_connectors.py"
        for owner, digest in E5_OBSERVATION_RAW_SHA256.items():
            with self.subTest(owner=owner):
                self.assertEqual(hashlib.sha256(self._span(name, owner)).hexdigest(), digest)
        self.assertEqual(hashlib.sha256(self.raw["source_file_observation.py"]).hexdigest(),
                         "0bd9fabd5b048b146dd18bb6a0116dd31ec8afde6410c8671778d7a5d5a78e0f")
        io_node = _function(self.trees[name], "_observe_file_bytes")
        alias = _calls(io_node, "documents._assert_ingest_path_alias_owner")[0]
        self.assertEqual([ast.unparse(a) for a in alias.args],
                         ["provider", "conn", "checked", "source_id", "scope_id", "repository_id"])
        self.assertEqual([(k.arg, ast.unparse(k.value)) for k in alias.keywords], [("opened_identity", "opened[:2]")])
        self.assertLess(alias.lineno, _calls(io_node, "file_observation.hash_exact_bytes")[0].lineno)
        owner = _calls(_function(self.trees["document_knowledge_graph.py"], "_assert_ingest_path_alias_owner"),
                       "_assert_connector_owner")[0]
        self.assertEqual([(k.arg, ast.unparse(k.value)) for k in owner.keywords], [("_conn", "conn")])
        # This is an actual caller/callee AST composition, NOT SQL/FD authority.
        cleanup = _calls(io_node, "file_observation.finish_descriptor")
        self.assertEqual(len(cleanup), 1)
        self.assertEqual([ast.unparse(a) for a in cleanup[0].args], ["lambda: os.close(fd)", "primary"])

    def test_PARENT_STATIC_f64_native_cache_bytes_and_no_public_observer(self):
        for name in ("__init__.py", "mcp-wrapper/tool_schemas.json"):
            self.assertEqual(hashlib.sha256(self.raw[name]).hexdigest(), F64_RAW_SHA256[name])
        cache = json.loads(self.raw["mcp-wrapper/tool_schemas.json"])
        self.assertTrue(all("observation" not in row["name"] and "observe_local_file" not in row["name"] for row in cache))
        self.assertFalse(_calls(self.trees["__init__.py"], "source_connectors.observe_local_file"))
        self.assertFalse(_calls(self.trees["__init__.py"], "observe_local_file"))

    def test_PARENT_STATIC_complete_revision_schema_cache_parity(self):
        tree = self.trees["__init__.py"]
        provider = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MemoryWikiProvider")
        method = _function(provider, "get_tool_schemas")
        p = next(n for n in method.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "P" for t in n.targets))
        self.assertEqual(ast.unparse(p.value), "lambda props, req=(): {'type': 'object', 'properties': props, 'required': list(req)}")
        ret = next(n for n in method.body if isinstance(n, ast.Return))
        tools = {"memory_wiki_document_unit_context", "memory_wiki_document_neighbors"}
        cache = json.loads(self.raw["mcp-wrapper/tool_schemas.json"])
        records = {}
        for record in ret.value.elts:
            if not isinstance(record, ast.Dict):
                continue
            fields = {ast.literal_eval(k): v for k, v in zip(record.keys, record.values)}
            name = ast.literal_eval(fields["name"])
            if name not in tools:
                continue
            parameters = fields["parameters"]
            self.assertIsInstance(parameters, ast.Call)
            self.assertEqual(ast.unparse(parameters.func), "P")
            self.assertEqual(len(parameters.args), 2)
            self.assertEqual(parameters.keywords, [])
            records[name] = {"name": name, "description": ast.literal_eval(fields["description"]),
                             "parameters": {"type": "object", "properties": ast.literal_eval(parameters.args[0]),
                                            "required": ast.literal_eval(parameters.args[1])}}
        self.assertEqual(set(records), tools)
        for name, native in records.items():
            matches = [row for row in cache if row["name"] == name]
            self.assertEqual(matches, [native])  # FULL records, not property names/counts.
            prop = native["parameters"]["properties"]["expected_revision_id"]
            self.assertEqual({key: prop[key] for key in ("type", "minLength", "maxLength", "pattern")},
                             {"type": "string", "minLength": 35, "maxLength": 35, "pattern": "^docrev_[0-9a-f]{28}$"})
            self.assertNotIn("default", prop)
            self.assertNotIn("expected_revision_id", native["parameters"]["required"])


def make_current_composition_suite(sources, *, declared_inputs, parent_static=False, case_started=None):
    """Prepare the explicit metadata cohort using the existing unittest recipe.

    sources are frozen UTF-8 STRINGS, not paths or a loader. declared_inputs
    maps each role to (raw SHA256, immutable diagnostic filename). Parent STATIC
    uses __init__.py/cache strings ONLY; neither is a larger SOURCE binding or
    an admission bypass. No collection, readers, tests or product execute here.
    Run only after the parent's separate admission under its original envelope.
    """
    if type(parent_static) is not bool or type(sources) is not dict or type(declared_inputs) is not dict:
        raise ValueError("literal_composition_inputs_required")
    required = ({"__init__.py", "mcp-wrapper/tool_schemas.json"} if parent_static else
                {"source_connectors.py", "document_knowledge_graph.py", "source_file_observation.py"})
    if set(sources) != required or set(declared_inputs) != required:
        raise ValueError("exact_composition_roles_required")
    for name, text in sources.items():
        binding = declared_inputs[name]
        if type(text) is not str or type(binding) is not tuple or len(binding) != 2:
            raise ValueError("frozen_string_and_binding_required")
        digest, filename = binding
        if (type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or type(filename) is not str or not filename):
            raise ValueError("raw_sha256_and_immutable_filename_required")
    if case_started is not None and not callable(case_started):
        raise ValueError("original_case_reporter_required")

    class CurrentObservationComposition(CurrentObservationCompositionStatic):
        __test__ = False

    case = CurrentObservationComposition
    case._sources, case._declared_inputs = dict(sources), dict(declared_inputs)
    case._parent_static = parent_static
    case.case_started = staticmethod(case_started) if case_started is not None else None
    methods = CURRENT_PARENT_STATIC_CASES if parent_static else CURRENT_COMPOSITION_CASES
    return unittest.TestSuite(case(name) for name in methods)


def make_suite(inputs, read_bound, scratch, case_started=None):
    """Same existing controller reader/factory shape; every input stays <1 MB."""
    needed = ("source_file_observation.py", "source_connectors.py", "document_knowledge_graph.py")
    if "__init__.py" in inputs:
        raise ValueError("oversized_main_is_not_an_observation_SOURCE_input")
    paths = {name: str(Path(inputs[name])) for name in needed}
    raw = {name: read_bound(paths[name]) for name in needed}
    if any(type(value) is not bytes or len(value) > 1_000_000 for value in raw.values()):
        raise ValueError("source_input_size_refused")
    cls = SourceFileObservationSource
    cls.paths, cls.raw = paths, raw
    cls.case_started = staticmethod(case_started) if case_started is not None else None
    return unittest.defaultTestLoader.loadTestsFromTestCase(cls)


if __name__ == "__main__":
    if not all(name in globals() for name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound")):
        raise SystemExit("requires separate parent SOURCE admission and original source_bootstrap")
    suite = make_suite(DEVTOOLS_INPUTS, devtools_read_bound, DEVTOOLS_SCRATCH, devtools_case_started)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"scope": "SOURCE_PURE_HASH_DECISION_PLUS_STATIC_WRAPPER_WIRING",
                      "main_cases": outcome.testsRun, "failures": len(outcome.failures), "errors": len(outcome.errors),
                      "wrapper_SQL_descriptor_native_SDK_MCP": "NOT_RUN"}))
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
