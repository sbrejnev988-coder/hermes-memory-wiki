"""Bounded stdlib/SOURCE packet for ADJ-REINDEX-FOREIGN-01.

No SDK/plugin bootstrap, profile_ready override, native permission, network or
PUT receiver. Whole real fence/ledger modules are loaded from bound source;
only fixed metadata/epoch/prediction units run on generic owned SQLite. A real
owner refusal is retained, never replaced by a synthetic permitting fence.
Static forwarding/baseline controls do NOT execute the reindex/HTTP composition.

Entry: permanent devtools/harness.py run_source, with FOREIGN_REINDEX_INPUTS.zlib
(a lossless {repo_path: UTF-8 source} carrier), COLD_LANES.json, cold_lane_entry.py,
and COLD_TEST_INPUTS*.zlib/COLD_ENTRY_INPUTS.zlib for the independent file census.
See docs/FOREIGN_REINDEX_ADMISSION.md. No external peer is needed by the tests.
"""
from __future__ import annotations
import __future__
import ast
from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import types
import unittest
import urllib.parse
import zlib

INPUTS = json.loads(zlib.decompress(devtools_read_bound(DEVTOOLS_INPUTS['FOREIGN_REINDEX_INPUTS.zlib'])))
RAW = {name: text.encode('utf-8') for name, text in INPUTS.items()}
TREE = ast.parse(RAW['__init__.py'])
BEFORE = ast.parse(RAW['BEFORE/__init__.py'])
ROOT = Path(DEVTOOLS_SCRATCH)
GENERIC_ONLY = 'generic SQLite read/prediction units; not SQL/native writer authority or actual PUT prevention'


def node(tree, *scope):
    current = tree
    for name in scope:
        found = [n for n in current.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == name]
        if len(found) != 1:
            raise AssertionError('source_scope_not_unique:' + '.'.join(scope))
        current = found[0]
    return current


def calls(owner, name):
    return [n for n in ast.walk(owner) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == name]


def forwarded(call, keyword, value):
    return any(k.arg == keyword and ast.unparse(k.value) == value for k in call.keywords)


def foreign_put_forwarded(tree):
    # This oracle also runs on the ACTUAL old code. It fails its known conditional
    # forwarding, independently of whether any new helper exists in that version.
    owner = node(tree, 'MemoryWikiProvider', '_reindex', 'index_row')
    upserts = calls(owner, '_qdrant_upsert')
    return len(upserts) == 1 and forwarded(upserts[0], '_admit', 'disclosure.admit_index')


def source_module(name, path):
    module = types.ModuleType(name)
    module.__file__ = path
    module.__package__ = name.rpartition('.')[0]
    sys.modules[name] = module
    exec(compile(RAW[path], path, 'exec', dont_inherit=True), module.__dict__)
    return module


# These are exact product modules, not SDK stand-ins or a replacement fence.
package = types.ModuleType('_foreign_source')
package.__path__ = []
sys.modules[package.__name__] = package
shared = source_module('_foreign_source.shared_blocks', 'shared_blocks.py')
fencing = source_module('_foreign_source.disclosure_fence', 'disclosure_fence.py')
privacy = source_module('_foreign_source.privacy_erasure', 'privacy_erasure.py')
FENCE = fencing.DisclosureFence

# No route/profile is fabricated: these units always receive explicit endpoint,
# manifest and collection. Their default config branches must not be reached.
UNIT_NAMES = ('_validated_http_endpoint', '_normalized_qdrant_endpoint',
              '_claim_vector_target_hash', '_claim_target_payload', '_record_claim_vector_target')
units = {'__name__': '_foreign_sql_units', 'hashlib': hashlib, 'json': json,
         'ipaddress': ipaddress, 'urllib': urllib, 'time': time, 'sqlite3': sqlite3,
         'contextmanager': contextmanager, 'nullcontext': nullcontext,
         '_DisclosureFence': FENCE, '_DeliveryWithheld': fencing.DeliveryWithheld}
for name in ('QDRANT_CLAIM_PAYLOAD_VERSION', '_CLAIM_VECTOR_TARGETS_TABLE'):
    assignments = [n for n in TREE.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    if len(assignments) != 1:
        raise AssertionError('unit_literal_binding:' + name)
    units[name] = ast.literal_eval(assignments[0].value)
exec(compile(ast.Module(body=[node(TREE, name) for name in UNIT_NAMES], type_ignores=[]),
             '__init__.py', 'exec', flags=__future__.annotations.compiler_flag, dont_inherit=True), units)
RECORD = units['_record_claim_vector_target']
TARGET_DDL = units['_CLAIM_VECTOR_TARGETS_TABLE']


class ForeignCopySourceTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / self._testMethodName
        self.root.mkdir()
        self.path = self.root / 'generic.sqlite3'
        self.conn = sqlite3.connect(self.path)
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA page_size=512')
        self.conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
        self.conn.executemany('INSERT INTO meta VALUES(?,?)', [
            ('database_instance_id', 'generic-source-db'), ('memory_revision', '7'),
            ('cache_state_revision', '3'), ('privacy_erasure_applied_seq', '0')])
        columns = {'id': 'TEXT PRIMARY KEY', 'topic': 'TEXT', 'memory_revision': 'INTEGER',
                   'updated_at': 'INTEGER', 'visibility_scope': 'TEXT', 'origin_bot_id': 'TEXT',
                   'origin_session_id': 'TEXT', 'origin_chat_hash': 'TEXT', 'project_id': 'TEXT',
                   'event_at': 'INTEGER', 'status': 'TEXT', 'created_at': 'INTEGER',
                   'claim': 'TEXT', 'normalized_claim': 'TEXT'}
        self.conn.execute('CREATE TABLE claims(' + ','.join(k + ' ' + v for k, v in columns.items()) + ')')
        self.conn.execute(TARGET_DDL)
        self.conn.execute("INSERT INTO claims VALUES('foreign','topic',7,11,'private','owner','owner-session',"
                          "'owner-chat','',9,'active',5,'FOREIGN_TEXT_CANARY','FOREIGN_TEXT_CANARY')")
        self.conn.commit()
        self.ledger = privacy.ErasureLedger(self.root)
        # This object is ONLY a generic metadata reader. It has NO ok/anchor or
        # _disclosure_context/profile_ready, and cannot pass finish/admit_index.
        self.reader = object.__new__(FENCE)
        self.reader.conn = self.conn
        self.reader.foreign, self.reader.worker = False, None
        self.reader.provider = types.SimpleNamespace(database_instance_id='generic-source-db')
        self.reader.ledger = self.ledger
        self.reader.erasure = []
        self.reader.claim_copy = self.reader._copy_metadata('foreign')[0]
        self.reader.copy_targets = self.reader._copy_targets('foreign')
        self.sql = []
        self.conn.set_trace_callback(self.sql.append)
        self.addCleanup(self.conn.set_trace_callback, None)

    def bind_targets(self):
        self.reader.copy_targets = self.reader._copy_targets('foreign')

    def record(self, collection='source', status='active', indexed_at=17):
        result = RECORD(self.conn, 'foreign', collection=collection, endpoint='https://vector.invalid',
                        manifest_hash='manifest-fixed', status=status, indexed_at=indexed_at)
        self.conn.commit()
        return result

    def external(self, statements):
        writer = sqlite3.connect(self.path)
        try:
            for sql, args in statements:
                writer.execute(sql, args)
            writer.commit()
        finally:
            writer.close()

    def add_erasure(self, *, cid='foreign', text='', owner='owner', session='owner-session', stamp=10):
        # Authenticated-format fixture producer, NOT ErasureLedger.append/native
        # principal authority. The real parser/MAC/owner matching are consumers.
        ledger = self.ledger
        body = {'v': 1, 'seq': 1, 'prev': '0' * 64, 'created_at': stamp,
                'owner': {'bot': ledger.digest('owner-bot', owner),
                          'raw_session': ledger.digest('owner-raw-session', session)},
                'claims': [ledger.digest('claim-id', cid)] if cid else [],
                'events': [], 'episodes': [], 'claim_text': ledger._marker('claim-text', text, substring=False),
                'event_text': ledger._marker('event-text', '', substring=False),
                'episode_text': ledger._marker('episode-text', '', substring=True)}
        body['mac'] = hmac.new(ledger.key, json.dumps(body, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
        ledger.log_path.write_bytes(json.dumps(body, sort_keys=True, separators=(',', ':')).encode() + b'\n')
        self.conn.execute("UPDATE meta SET value='1' WHERE key='privacy_erasure_applied_seq'")
        self.conn.commit()
        self.reader.erasure = self.reader._erasures()

    def test_static_baseline_bug_discriminated(self):
        self.assertFalse(foreign_put_forwarded(BEFORE), 'frozen_original_did_not_express_conditional_bug')
        self.assertTrue(foreign_put_forwarded(TREE), 'foreign_PUT_missing_unconditional_original_admission')

    def test_static_source_fetch_and_both_callers(self):
        verifier = node(TREE, '_qdrant_registered_claim_vector_for_reindex')
        self.assertLess(next(n.lineno for n in ast.walk(verifier) if isinstance(n, ast.Call)
                             and ast.unparse(n.func) == '_disclosure.index_copy'), calls(verifier, '_qdrant_req')[0].lineno)
        self.assertTrue(forwarded(calls(verifier, '_qdrant_req')[0], '_admit', '_disclosure.admit_index'))
        for caller in ('expected_row_state', 'index_row'):
            owner = node(TREE, 'MemoryWikiProvider', '_reindex', caller)
            selected = calls(owner, '_qdrant_registered_claim_vector_for_reindex')
            self.assertEqual(len(selected), 1)
            self.assertTrue(forwarded(selected[0], '_disclosure', 'disclosure'))
        response_call = calls(verifier, '_qdrant_req')[0]
        self.assertTrue(any(isinstance(n, ast.Call) and ast.unparse(n.func) == '_disclosure.admit_index'
                            and n.lineno > response_call.end_lineno for n in ast.walk(verifier)))

    def test_static_intent_only_after_verifier_no_epoch_rebase(self):
        owner = node(TREE, 'MemoryWikiProvider', '_reindex', 'index_row')
        intent = [c for c in calls(owner, '_record_claim_vector_target') if forwarded(c, '_disclosure', 'disclosure')]
        self.assertEqual(len(intent), 1)
        self.assertGreater(intent[0].lineno, calls(owner, '_qdrant_registered_claim_vector_for_reindex')[0].lineno)
        cls = node(ast.parse(RAW['disclosure_fence.py']), 'DisclosureFence')
        context = node(cls, 'index_copy_intent')
        self.assertFalse(any(isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
                             and n.attr in {'anchor', 'epoch', 'erasure'} for n in ast.walk(context)))
        self.assertIn('self.conn.total_changes != before + 1', ast.unparse(context))
        self.assertIn('self.admit_index()', ast.unparse(context))
        self.assertIn('self.copy_changes = 1', ast.unparse(context))

    def test_static_transport_visible_outbox_scoped_contracts_unchanged(self):
        for name in ('_qdrant_upsert', '_qdrant_req', '_observed_semantic_http'):
            self.assertEqual(ast.dump(node(TREE, name)), ast.dump(node(BEFORE, name)), name)
        owner = node(TREE, 'MemoryWikiProvider', '_reindex', 'index_row')
        visible = next(n for n in ast.walk(owner) if isinstance(n, ast.If)
                       and ast.unparse(n.test) == 'self._claim_visible(row)')
        old_visible = next(n for n in ast.walk(node(BEFORE, 'MemoryWikiProvider', '_reindex', 'index_row'))
                           if isinstance(n, ast.If) and ast.unparse(n.test) == 'self._claim_visible(row)')
        self.assertEqual([ast.dump(n) for n in visible.body], [ast.dump(n) for n in old_visible.body])
        for name in ('_outbox_process',):
            self.assertEqual(ast.dump(node(TREE, name)), ast.dump(node(BEFORE, name)))
        before_fence = node(ast.parse(RAW['BEFORE/disclosure_fence.py']), 'DisclosureFence')
        current_fence = node(ast.parse(RAW['disclosure_fence.py']), 'DisclosureFence')
        for name in ('_authority', '_erasures', 'index_claim', 'index_snapshot',
                     'claim_worker', '_eligible', '_unerased'):
            self.assertEqual(ast.dump(node(current_fence, name)), ast.dump(node(before_fence, name)), name)
        self.assertEqual(RAW['current_scope_reindex.py'], RAW['BEFORE/current_scope_reindex.py'])
        # Recorder's pre-existing callers keep default _disclosure=None. They
        # cannot acquire the new bookkeeping path merely from a matching path.
        recorder = node(TREE, '_record_claim_vector_target')
        self.assertIn('_disclosure=None', ast.unparse(recorder.args))
        self.assertIn("status != 'write_pending'", ast.unparse(recorder))

    def test_metadata_projection_never_hydrates_text(self):
        image = self.reader._copy_metadata('foreign')[0]
        self.assertNotIn('claim', image)
        self.assertNotIn('normalized_claim', image)
        self.assertEqual(image['index_nonempty'], 1)
        self.assertTrue(self.reader._copy_current())
        self.assertFalse(any('SELECT * FROM claims' in s or 'SELECT normalized_claim FROM claims' in s for s in self.sql))
        self.assertNotIn('FOREIGN_TEXT_CANARY', json.dumps(image))

    def test_metadata_late_status_and_nonempty_denied(self):
        self.conn.execute("UPDATE claims SET status='retired',normalized_claim='' WHERE id='foreign'")
        self.conn.commit()
        self.assertFalse(self.reader._copy_current())
        image = self.reader._copy_metadata('foreign')[0]
        self.assertEqual((image['status'], image['index_nonempty']), ('retired', 0))

    def test_metadata_delete_denied(self):
        self.conn.execute("DELETE FROM claims WHERE id='foreign'")
        self.conn.commit()
        self.assertFalse(self.reader._copy_current())

    def test_metadata_acl_and_revision_denied(self):
        self.conn.execute("UPDATE claims SET origin_bot_id='new',memory_revision=8 WHERE id='foreign'")
        self.conn.commit()
        self.assertFalse(self.reader._copy_current())

    def test_registry_mutation_denied(self):
        self.record()
        self.bind_targets()
        self.conn.execute("UPDATE claim_vector_targets SET status='delete_pending' WHERE claim_id='foreign'")
        self.conn.commit()
        self.assertFalse(self.reader._copy_current())

    def test_same_connection_ABA_keeps_original_epoch(self):
        before = self.reader._epoch()
        self.conn.execute("UPDATE claims SET origin_bot_id='transient' WHERE id='foreign'")
        self.conn.execute("UPDATE claims SET origin_bot_id='owner' WHERE id='foreign'")
        self.conn.commit()
        self.assertTrue(self.reader._copy_current())  # Equality ALONE is insufficient.
        after = self.reader._epoch()
        self.assertEqual(before[:2], after[:2])
        self.assertEqual(after[2], before[2] + 2)

    def test_external_ABA_not_own_intent(self):
        before = self.reader._epoch()
        self.external([("UPDATE claims SET origin_bot_id='transient' WHERE id='foreign'", ()),
                       ("UPDATE claims SET origin_bot_id='owner' WHERE id='foreign'", ())])
        after = self.reader._epoch()
        self.assertTrue(self.reader._copy_current())
        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])
        self.assertEqual(before[2], after[2])

    def test_external_registry_ABA_not_own_intent(self):
        self.record()
        self.bind_targets()
        before = self.reader._epoch()
        self.external([("UPDATE claim_vector_targets SET indexed_at=18 WHERE claim_id='foreign'", ()),
                       ("UPDATE claim_vector_targets SET indexed_at=17 WHERE claim_id='foreign'", ())])
        self.assertTrue(self.reader._copy_current())
        self.assertNotEqual(before[1], self.reader._epoch()[1])

    def test_exact_new_destination_bookkeeping_prediction(self):
        self.record()
        self.bind_targets()
        payload = units['_claim_target_payload'](collection='destination', endpoint='https://vector.invalid', manifest_hash='manifest-fixed')
        expected = self.reader._copy_intent_targets('foreign', payload, int(time.time()))
        before = self.reader._epoch()
        # Timestamp is an explicit input of the pure predictor. Capture the
        # recorder's actual timestamp from readback, never treat it as authority.
        self.record('destination', 'write_pending', 0)
        observed = self.reader._copy_targets('foreign')
        stamp = next(r['updated_at'] for r in observed if r['collection'] == 'destination')
        expected = self.reader._copy_intent_targets('foreign', payload, stamp)
        self.assertEqual(expected, observed)
        after = self.reader._epoch()
        self.assertEqual(after, (before[0], before[1], before[2] + 1))
        self.assertEqual(next(r['status'] for r in observed if r['collection'] == 'source'), 'active')

    def test_exact_sole_source_bookkeeping_prediction(self):
        payload = self.record()
        self.bind_targets()
        self.assertEqual(self.reader.copy_targets[0]['status'], 'active')
        before = self.reader._epoch()
        self.record('source', 'write_pending', 0)
        observed = self.reader._copy_targets('foreign')
        predicted = self.reader._copy_intent_targets('foreign', payload, observed[0]['updated_at'])
        self.assertEqual(predicted, observed)
        self.assertEqual((observed[0]['status'], observed[0]['indexed_at']), ('write_pending', 17))
        self.assertEqual(self.reader._epoch(), (before[0], before[1], before[2] + 1))

    def test_unaccounted_trigger_ABA_exceeds_single_effect(self):
        self.record()
        self.conn.execute("CREATE TRIGGER extra AFTER UPDATE ON claim_vector_targets BEGIN "
                          "UPDATE claims SET origin_bot_id='transient' WHERE id='foreign'; "
                          "UPDATE claims SET origin_bot_id='owner' WHERE id='foreign'; END")
        self.conn.commit()
        before = self.reader._epoch()
        self.record('source', 'write_pending', 0)
        self.assertGreater(self.reader._epoch()[2] - before[2], 1)
        self.assertEqual(self.reader._copy_metadata('foreign'), [self.reader.claim_copy])

    def test_erasure_ID_denied_without_text(self):
        self.add_erasure()
        self.assertFalse(self.reader._copy_current())

    def test_applicable_phrase_is_unproven_without_text(self):
        self.add_erasure(cid='', text='unread phrase')
        self.assertFalse(self.reader._copy_current())

    def test_unrelated_owner_erasure_preserves_copy(self):
        self.add_erasure(owner='unrelated', text='unread phrase')
        self.assertTrue(self.reader._copy_current())

    def test_newer_row_preserves_applied_phrase_control(self):
        self.add_erasure(cid='', text='unread phrase', stamp=1)
        self.assertTrue(self.reader._copy_current())

    def test_pending_erasure_and_corrupt_MAC_refused(self):
        self.add_erasure()
        self.conn.execute("UPDATE meta SET value='0' WHERE key='privacy_erasure_applied_seq'")
        self.conn.commit()
        with self.assertRaisesRegex(PermissionError, 'disclosure_erasure_replay_required'):
            self.reader._erasures()
        raw = self.ledger.log_path.read_bytes()
        self.ledger.log_path.write_bytes(raw.replace(b'"v":1', b'"v":2'))
        with self.assertRaisesRegex(RuntimeError, 'privacy erasure ledger integrity failed'):
            self.reader._erasures()

    def test_actual_owner_unknown_is_DENY_not_positive_standin(self):
        class OwnerUnknown:
            def _disclosure_context(self, *, terminal=False):
                raise PermissionError('native_owner_NOT_ADMITTED')
        owner = OwnerUnknown()
        owner.home = self.root
        owner._conn = self.conn
        owner._privacy_erasure = self.ledger
        fence = FENCE(owner, self.conn)
        self.assertFalse(fence.ok)
        with self.assertRaises(fencing.DeliveryWithheld):
            fence.index_copy({'id': 'foreign'})
        self.assertFalse(fence.finish())

    def test_cold_membership_exact_current_source(self):
        module = types.ModuleType('_foreign_cold_metadata')
        raw = devtools_read_bound(DEVTOOLS_INPUTS['cold_lane_entry.py'])
        exec(compile(raw, 'tests/cold_lane_entry.py', 'exec', dont_inherit=True), module.__dict__)
        plan = json.loads(devtools_read_bound(DEVTOOLS_INPUTS['COLD_LANES.json']))
        current = {}
        names = sorted(name for name in DEVTOOLS_INPUTS if name.startswith('COLD_TEST_INPUTS')) + ['COLD_ENTRY_INPUTS.zlib']
        for name in names:
            part = json.loads(zlib.decompress(devtools_read_bound(DEVTOOLS_INPUTS[name])))
            self.assertFalse(current.keys() & part.keys())
            current.update({p: text.encode('utf-8') for p, text in part.items()})
        result = module.validate_partition(plan, current)
        self.assertTrue(result['source_inputs_verified'])
        self.assertFalse(result['native_sdk_execution_admitted'])
        self.assertEqual(current['__init__.py'], RAW['__init__.py'])
        self.assertEqual(current['tests/ci_owned/foreign_reindex_cases.py'], devtools_read_bound(__file__))


class Results(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases = []
    def startTest(self, test):
        super().startTest(test)
        devtools_case_started(test.id())
        self.cases.append({'id': test.id(), 'outcome': 'error', 'phase': 'unittest_started'})
    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases[-1].update(outcome='passed', phase='unittest_completion_after_cleanup')
    def _problem(self, test, err, outcome):
        # No linecache/source I/O during failure reporting. Preserve exact
        # exception type and bounded primitive traceback locations, not payload.
        frames = []
        tb = err[2]
        while tb is not None:
            frames.append([tb.tb_frame.f_code.co_filename, tb.tb_frame.f_code.co_name, tb.tb_lineno])
            tb = tb.tb_next
        case = self.cases[-1]
        if case['id'] != test.id():
            raise AssertionError('unittest_report_identity_mismatch')
        case.update(outcome=outcome, phase='unittest_failure')
        case.setdefault('issues', []).append({'error_type': err[0].__name__, 'frames': frames[-12:]})
    def addFailure(self, test, err):
        self._problem(test, err, 'failed')
        self.failures.append((test, 'assertion'))
    def addError(self, test, err):
        self._problem(test, err, 'error')
        self.errors.append((test, 'error'))


if __name__ == '__main__':
    result = Results()
    unittest.defaultTestLoader.loadTestsFromTestCase(ForeignCopySourceTests).run(result)
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'cases': result.cases,
        'scope': GENERIC_ONLY, 'actual_PUT_composition': 'NOT_RUN_NATIVE_ADMISSION_REQUIRED',
        'bindings': {p: hashlib.sha256(raw).hexdigest() for p, raw in RAW.items()},
        'roles': {'payload_producer': 'STATIC_SOURCE', 'profile_identity': 'NOT_RUN_NATIVE',
                  'dispatcher_validator_transport': 'STATIC_SOURCE',
                  'metadata_epoch_prediction': 'EXECUTED_GENERIC_SQLITE', 'SDK_imports': 0},
        'subprocess_invocations': 0}, separators=(',', ':')))
    raise SystemExit(0 if result.wasSuccessful() else 1)
