"""AU01: exact selected bodies on synthetic records/connection control flow.

Collection is inert. Only source_suite() under the original SOURCE fence admits
extraction. No provider/SDK import, SQLite connection, worker, native file handle
or genuine apply/rollback/UNKNOWN. _connect, content policy, trigger and rendering
observers have NO provider authority. Actual _claim_transaction, writer/rollback/
quarantine bodies and model row ACL are retained, not permissive owner mocks.
Full-module identity and unchanged guards are separately checked as STATIC.
The correction also selects the complete public handler, recursive retry and
journal decision bodies. Transport uses the exact product's standalone JSON
fallback, NOT tools.registry/SDK. Connect/migrate/close, journal persistence,
policy inputs and rendering remain explicitly synthetic SOURCE observers.
"""
from __future__ import annotations

import __future__
import ast
import contextvars
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import PurePosixPath
import re
import sqlite3
import sys
import textwrap
import threading
import types
import unittest
import urllib.error

__test__ = False
OPERATIONS = ('_normalize_topics', '_immune_scan', '_vacuum')
CASE_IDS = (
    'test_normalize_apply', 'test_immune_apply', 'test_vacuum_apply',
    'test_normalize_suggest', 'test_immune_suggest', 'test_vacuum_suggest',
    'test_normalize_noop', 'test_immune_noop', 'test_vacuum_noop',
    'test_normalize_rollback', 'test_immune_rollback', 'test_vacuum_rollback',
    'test_normalize_unknown', 'test_immune_unknown', 'test_vacuum_unknown',
    'test_required_change_log_failure_rolls_back',
    'test_commit_before_and_after_effect_faults',
    'test_nested_owner_is_not_committed_or_published',
    'test_model_acl_batch_preflight_and_private_positive',
    'test_vacuum_partition_and_endpoint_acl',
    'test_postcommit_fts_and_render_failures_are_not_success',
    'test_STATIC_owning_conn_and_postcommit_order',
    'test_STATIC_original_guards_and_journal_preserved',
    'test_public_postcommit_sqlite_fts_limit_one',
    'test_public_postcommit_render_limit_one',
    'test_public_healthy_apply_limit_one_and_journal',
    'test_public_precommit_rollback_reconnect_retry',
    'test_public_unknown_never_reconnects',
    'test_public_fatal_primary_identity',
    'test_public_next_attempt_and_foreign_owner_are_not_tainted',
    'test_commit_receipt_requires_actual_success_and_standalone_owner',
    'test_STATIC_correction_wiring_and_source_ownership',
)


class SyntheticFault(BaseException):
    pass


class ObservedLock:
    """Deterministic nesting observer, NOT a concurrency/OS-lock proof."""
    def __init__(self):
        self.depth = 0

    def __enter__(self):
        self.depth += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1


class Rows:
    def __init__(self, rows=(), rowcount=0):
        self.rows, self.rowcount = list(rows), rowcount

    def fetchall(self):
        return copy.deepcopy(self.rows)

    def fetchone(self):
        return copy.deepcopy(self.rows[0]) if self.rows else None

    def __iter__(self):
        return iter(copy.deepcopy(self.rows))


class SyntheticConnection:
    """Finite authored command observer, never sqlite3.Connection or a DB engine.

    Only declared command shapes are accepted. In-memory snapshots describe the
    fixture, not native atomicity, trigger execution, durable journal or FTS parity.
    """
    def __init__(self, receiver, rows, stale=()):
        self.owner = receiver
        self.claims = {row['id']: dict(row) for row in rows}
        self.stale = copy.deepcopy(list(stale))
        self.changes, self.evidence, self.projection = [], [], []
        self.in_transaction, self.total_changes = False, 0
        self.autocommit = False
        self._prefetch_terminal = self._document_commit_image = None
        self._graph_commit_image = self._event_job_commit_image = None
        self.commands, self.commits, self.rollbacks = [], [], 0
        self.fail_fragment = self.primary = self.rollback_primary = None
        self.commit_fault = None
        self.snapshot = None
        self.ordinary_fault_once = False
        self.closed = False

    def state(self):
        return copy.deepcopy((self.claims, self.stale, self.changes, self.evidence, self.projection))

    def owned(self):
        p = self.owner
        assert p._claim_tx_connection is self
        assert p._claim_tx_thread == threading.get_ident()
        assert p._lock.depth > 0

    def __enter__(self):
        raise AssertionError('raw_connection_context_is_not_a_registered_owner')

    def execute(self, sql, params=()):
        sql = ' '.join(sql.split())
        self.commands.append((sql, tuple(params), self.in_transaction))
        if self.fail_fragment is not None and self.fail_fragment in sql:
            if self.ordinary_fault_once:
                self.fail_fragment = None
            raise self.primary
        if sql.startswith('BEGIN'):
            self.owned()
            assert not self.in_transaction
            self.snapshot = self.state()
            self.in_transaction = True
            return Rows()
        if sql == 'SELECT 1':
            return Rows([(1,)])
        if sql == ('SELECT visibility_scope,origin_bot_id,origin_chat_hash,'
                   'origin_session_id,project_id FROM claims'):
            keys = ('visibility_scope', 'origin_bot_id', 'origin_chat_hash', 'origin_session_id', 'project_id')
            return Rows([{key: row[key] for key in keys} for row in self.claims.values()])
        if sql.startswith('SELECT * FROM claims WHERE id='):
            row = self.claims.get(params[0])
            return Rows([row] if row is not None else [])
        if sql.startswith('SELECT * FROM contradictions WHERE status='):
            return Rows(self.stale)
        if sql.startswith(('SELECT id,claim,topic FROM claims', 'SELECT * FROM claims WHERE status=',
                           'SELECT id,claim,normalized_claim,topic,evidence FROM claims')):
            return Rows([row for row in self.claims.values() if row['status'] == 'active'])
        self.owned()
        assert self.in_transaction, 'synthetic_write_before_registered_BEGIN'
        if sql.startswith('UPDATE claims SET'):
            conditional = 'AND topic=?' in sql
            row = self.claims[params[-2] if conditional else params[-1]]
            if conditional and row['topic'] != params[-1]:
                return Rows(rowcount=0)
            if 'SET topic=?' in sql:
                row['topic'] = params[0]
            elif "status='superseded'" in sql:
                row['status'] = 'superseded'
            elif "status='retired'" in sql:
                row['status'] = 'retired'
                if 'salience=0.0' in sql:
                    row.update(salience=0.0, quality=0.0)
            elif "status='uncertain'" in sql:
                row.update(status='uncertain', salience=row['salience'] * .8)
            else:
                raise AssertionError('unexpected_claim_command:' + sql)
        elif sql.startswith('UPDATE contradictions SET'):
            row = next(row for row in self.stale if row['id'] == params[-1])
            row['status'] = 'resolved'
        elif sql.startswith('INSERT OR IGNORE INTO memory_changes'):
            self.changes.append(tuple(params))
        elif sql.startswith('INSERT OR IGNORE INTO evidence'):
            self.evidence.append(tuple(params))
        elif sql.startswith(('DROP TABLE IF EXISTS claims_fts', 'CREATE VIRTUAL TABLE claims_fts_rebuild',
                             'INSERT INTO claims_fts_rebuild', 'ALTER TABLE claims_fts_rebuild',
                             'INSERT OR REPLACE INTO meta')):
            self.projection.append((sql, tuple(params)))
        else:
            raise AssertionError('unexpected_synthetic_command:' + sql)
        self.total_changes += 1
        return Rows(rowcount=1)

    def commit(self):
        self.owned()
        assert self.in_transaction
        if self.commit_fault == 'before':
            raise self.primary
        self.in_transaction = False
        self.commits.append(self.state())
        if self.commit_fault == 'after':
            raise self.primary

    def rollback(self):
        self.owned()
        self.rollbacks += 1
        if self.rollback_primary is not None:
            raise self.rollback_primary
        if self.in_transaction:
            (self.claims, self.stale, self.changes, self.evidence, self.projection) = copy.deepcopy(self.snapshot)
        self.in_transaction = False

    def close(self):
        # An authored close observation, NOT a genuine SQLite/native close.
        assert not self.in_transaction and not self.closed
        self.closed = True
        self.owner.closed_connections.append(self)


def deny_private_writer(*_args):
    # Deny-only: no fabricated factory-issued private connection capability.
    return False


def synthetic_lint(claim, topic):
    if claim.startswith('fixture-secret'):
        return {'issues': ['contains secret-like material'], 'quality': .9, 'topic': topic}
    if claim.startswith('fixture-low'):
        return {'issues': ['raw blob/log; summarize first'], 'quality': .1, 'topic': topic}
    return {'issues': [], 'quality': .9, 'topic': 'canonical'}


class ReceiverObservers:
    """Read/derivative seams only. These do not grant SQL/provider authority."""
    def _connect(self):
        if self._conn is None:
            # Reconnect/migration transport is synthetic. Keep the full fixture
            # committed image so a wrongly repeated public apply finds cohort 2.
            old = self.closed_connections[-1]
            conn = SyntheticConnection(self, old.claims.values(), old.stale)
            conn.changes, conn.evidence, conn.projection = copy.deepcopy(
                (old.changes, old.evidence, old.projection))
            self._conn = self._owned_conn = conn
            self.connections.append(conn)
            self.events.append(('reconnect_observer', len(self.connections)))
        self.events.append(('connect_observer', self._conn.in_transaction))
        return self._conn

    def _migrate(self):
        # The real public caller must invoke this after reconnect. Warm schema
        # success is an authored premise, not migration/SDK compatibility proof.
        self.events.append(('migrate_observer', self._conn.in_transaction))

    @contextmanager
    def _journal_operation_scope(self):
        # No real file lock, fsync, recovery authority or durable journal here.
        self.events.append(('journal_scope_observer', 'enter'))
        try:
            yield
        finally:
            self.events.append(('journal_scope_observer', 'exit'))

    def _journal_payload_for_operation(self, op, payload):
        return dict(payload)

    def _append_journal_event(self, op, payload, *, phase, **metadata):
        assert self._lock.depth > 0
        record = {'seq': len(self.journal_events) + 1, 'op': op, 'phase': phase, **metadata}
        self.journal_events.append(record)
        return record

    def _journal_after_result(self, op, payload, result):
        self.events.append(('journal_after_result_observer', op))
        return self._journal_result_dict(result)

    def _trusted_opaque_graph_ids_for_journal_result(self, op, result):
        return set()

    def _checkpoint_after_journal_mutation(self, op, result, seq):
        self.events.append(('checkpoint_observer', seq))
        return {}

    def _topic_alias(self, topic, claim=''):
        return 'canonical'

    def _canonical_topic_for_claim(self, claim, topic):
        return 'canonical'

    def _rowdict(self, row):
        return dict(row)  # authored nonsensitive records, not genuine sanitation

    def _drop_index_sync_triggers(self, conn):
        conn.owned()
        self.events.append(('drop_trigger_observer', conn.in_transaction))

    def _install_index_sync_triggers(self, conn):
        conn.owned()
        self.events.append(('install_trigger_observer', conn.in_transaction))

    def _meta_int(self, key):
        conn = self._connect()
        conn.owned()
        return 7

    def _set_meta_max(self, key, value, *, conn):
        conn.owned()
        self.events.append(('fts_watermark_observer', conn.in_transaction))

    def _render_all(self):
        assert not self._conn.in_transaction
        assert self._claim_tx_connection is None
        assert self._lock.depth > 0
        self.events.append(('render_observer', len(self._conn.commits)))
        if self.render_primary is not None:
            if getattr(self, 'render_fault_once', False):
                primary, self.render_primary = self.render_primary, None
                raise primary
            raise self.render_primary


def row(cid, text='fixture ordinary claim', *, topic='old', status='active', scope='private',
        bot='bot-a', session='session-a', pinned=0):
    return {'id': cid, 'claim': text, 'normalized_claim': text, 'topic': topic,
            'status': status, 'salience': .8, 'confidence': .8, 'quality': .9,
            'updated_at': 2, 'pinned': pinned, 'evidence': '',
            'visibility_scope': scope, 'origin_bot_id': bot, 'origin_session_id': session,
            'origin_chat_hash': '', 'project_id': ''}


def definitions(carrier):
    namespace = {'__name__': 'au01_synthetic_selected_source', 'contextmanager': contextmanager,
        'threading': threading, 'sqlite3': sqlite3, 'hashlib': hashlib,
        '_owns_private_graph_writer': deny_private_writer,
        '_CLAIM_JOURNAL_CAPTURE': contextvars.ContextVar('au01_journal', default=None),
        '_GRAPH_EXTRACTION': contextvars.ContextVar('au01_graph', default=None),
        'now': lambda: 10000, 'short': lambda value, limit: str(value)[:limit],
        'redact_secrets': lambda value: value, 'scrub_memory_artifacts': lambda value: value,
        'lint_claim_text': synthetic_lint, 'normalize_claim': lambda value: ' '.join(value.split()),
        'tokens': lambda value: value.split(), 'BAD_TOPICS': set(),
        'is_ephemeral_fragment': lambda value: value.startswith('fixture-artifact'),
        'claim_search_text': lambda *args: ' '.join(args), '_debug_log': lambda *args: None,
        '_safe_exception_label': lambda error: type(error).__name__,
        'json': json, 're': re, 'urllib': urllib}
    methods = []
    for item in carrier['definitions']:
        raw = item['source'].encode('utf-8')
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
        if item['owner']:
            wrapped = ast.parse('class _SourceOwner:\n' + item['source'])
            assert len(wrapped.body) == len(wrapped.body[0].body) == 1
            selected = wrapped.body[0].body[0]
            ast.increment_lineno(selected, -1)
            tree = ast.Module(body=[selected], type_ignores=[])
        else:
            tree = ast.parse(item['source'])
        assert len(tree.body) == 1 and isinstance(tree.body[0], (ast.FunctionDef, ast.ClassDef, ast.Assign))
        node = tree.body[0]
        assert hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest() == item['ast_sha256']
        name = node.targets[0].id if isinstance(node, ast.Assign) else node.name
        assert name == item['name']
        ast.increment_lineno(tree, item['start_line'] - 1)
        if item['owner'] == 'MemoryWikiProvider':
            assert isinstance(node, ast.FunctionDef)
            methods.append(node)
        else:
            exec(compile(tree, '<au01-selected-module-definition>', 'exec',
                         flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
    cls = ast.ClassDef(name='MemoryWikiProvider', bases=[], keywords=[], body=methods, decorator_list=[])
    ast.fix_missing_locations(cls)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<au01-selected-provider-definitions>',
                 'exec', flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
    product = namespace['MemoryWikiProvider']
    for name in OPERATIONS:
        assert getattr(product, name).__globals__ is namespace
    return product, namespace


class MaintenanceApplyOwnerSource(unittest.TestCase):
    __test__ = False
    carrier = None

    @classmethod
    def setUpClass(cls):
        if cls.carrier is None:
            raise RuntimeError('explicit_original_fence_admission_required')
        cls.product, cls.namespace = definitions(cls.carrier)
        cls.addClassCleanup(setattr, cls, 'carrier', None)

    def receiver(self, operation, *, empty=False, rows=None, stale=None):
        if rows is None:
            if empty:
                rows = []
            elif operation == '_normalize_topics':
                rows = [row('normal-a'), row('normal-b')]
            elif operation == '_immune_scan':
                rows = [row('secret', 'fixture-secret no actual secret'),
                        row('low', 'fixture-low authored text'), row('retopic')]
            else:
                rows = [row('keep', 'fixture identical claim', pinned=1),
                        row('merge', 'fixture identical claim'),
                        row('artifact', 'fixture-artifact noise'),
                        row('topic', 'unrelated durable assertion'),
                        row('inactive', 'retired endpoint', status='retired', topic='canonical')]
        if stale is None:
            stale = ([{'id': 'contradiction', 'claim_a': 'keep', 'claim_b': 'inactive', 'status': 'open'}]
                     if operation == '_vacuum' and not empty else [])
        cls = type('SyntheticMaintenanceReceiver', (ReceiverObservers, self.product), {})
        value = cls()
        value._lock, value.events, value.render_primary = ObservedLock(), [], None
        value._conn = value._owned_conn = SyntheticConnection(value, rows, stale)
        value._lifecycle_state, value._degraded = 'ready', False
        value._transaction_quarantine = value._transaction_primary = None
        value._transaction_cleanup_notes = ()
        value._claim_tx_connection = value._claim_tx_thread = None
        value._claim_tx_document_stage = value._claim_tx_graph_stage = value._claim_tx_event_job_stage = None
        value.bot_id, value.session_id, value.project_scope = 'bot-a', 'session-a', ''
        value.dashboard_dir = PurePosixPath('synthetic-dashboard-not-opened')
        return value

    def call(self, value, operation, mode='apply', **kwargs):
        return getattr(value, operation)(mode, **kwargs)

    def healthy(self, value):
        self.assertIs(value._conn, value._owned_conn)
        self.assertFalse(value._conn.in_transaction)
        self.assertIsNone(value._claim_tx_connection)
        self.assertIsNone(value._claim_tx_thread)
        self.assertIsNone(value._claim_tx_document_stage)
        self.assertIsNone(value._claim_tx_graph_stage)
        self.assertIsNone(value._claim_tx_event_job_stage)
        self.assertIsNone(value._transaction_quarantine)
        self.assertIsNone(value._transaction_primary)
        self.assertEqual(value._lifecycle_state, 'ready')
        self.assertEqual(value._lock.depth, 0)

    def apply(self, operation):
        value = self.receiver(operation)
        result = self.call(value, operation, model_scope=True)
        conn = value._conn
        self.healthy(value)
        self.assertEqual(result['mode'], 'apply')
        self.assertEqual(len(conn.commits), 2)  # mutation, then real extracted FTS owner
        self.assertEqual([sql for sql, _, _ in conn.commands if sql.startswith('BEGIN')],
                         ['BEGIN IMMEDIATE', 'BEGIN EXCLUSIVE'])
        self.assertEqual(conn.rollbacks, 0)
        self.assertEqual(value.events[-1], ('render_observer', 2))
        if operation == '_normalize_topics':
            self.assertEqual(result['applied'], 2)
            self.assertEqual([item[1] for item in conn.changes], ['topic_normalize'] * 2)
            self.assertTrue(all(r['topic'] == 'canonical' for r in conn.claims.values()))
        elif operation == '_immune_scan':
            self.assertEqual(result['applied'], {'retired': 1, 'uncertain': 1, 'retopic': 1, 'queued': 0})
            self.assertEqual([conn.claims[cid]['status'] for cid in ('secret', 'low', 'retopic')],
                             ['retired', 'uncertain', 'active'])
            self.assertEqual([item[1] for item in conn.changes],
                             ['immune_retire_secret', 'immune_queue_or_uncertain', 'immune_retopic'])
        else:
            self.assertEqual(result['applied'], {'merged': 1, 'topic_fixes': 4,
                             'resolved_contradictions': 1, 'retired_artifacts': 1})
            self.assertEqual(conn.claims['merge']['status'], 'superseded')
            self.assertEqual(conn.claims['artifact']['status'], 'retired')
            self.assertEqual(conn.evidence[0][1:3], ('keep', 'note'))
            self.assertEqual(conn.evidence[0][4], 'memory_wiki_vacuum')
            self.assertEqual(conn.stale[0]['status'], 'resolved')
        self.assertTrue(conn.projection)

    def suggest(self, operation):
        value = self.receiver(operation)
        before = value._conn.state()
        result = self.call(value, operation, 'suggest', model_scope=True)
        self.assertEqual(result['mode'], 'suggest')
        self.assertEqual(value._conn.state(), before)
        self.assertEqual(value._conn.commits, [])
        self.assertEqual(value._conn.rollbacks, 0)
        self.assertTrue(all(sql.startswith('SELECT') for sql, _, _ in value._conn.commands))
        self.assertFalse(any(event[0] == 'render_observer' for event in value.events))
        self.healthy(value)

    def noop(self, operation):
        value = self.receiver(operation, empty=True)
        result = self.call(value, operation, model_scope=True)
        self.assertFalse(any(result['applied'].values()) if isinstance(result['applied'], dict) else result['applied'])
        self.assertEqual(value._conn.claims, {})
        self.assertEqual(value._conn.changes, [])
        self.assertEqual(value._conn.evidence, [])
        # Preserve existing empty-apply projection refresh, not an invented no-TX API.
        self.assertEqual(len(value._conn.commits), 2)
        self.healthy(value)

    def failure(self, operation, *, unknown=False, fragment=None):
        value = self.receiver(operation)
        conn = value._conn
        before = conn.state()
        primary = SyntheticFault('owned synthetic primary')
        conn.primary = primary
        conn.fail_fragment = fragment or ('INSERT OR IGNORE INTO evidence' if operation == '_vacuum'
                                          else 'INSERT OR IGNORE INTO memory_changes')
        if unknown:
            conn.rollback_primary = RuntimeError('synthetic rollback refusal')
        with self.assertRaises(SyntheticFault) as caught:
            self.call(value, operation)
        self.assertIs(caught.exception, primary)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.commits, [])
        self.assertFalse(conn.projection)
        self.assertFalse(any(event[0] == 'render_observer' for event in value.events))
        if unknown:
            self.assertIs(value._transaction_quarantine, conn)
            self.assertIs(value._transaction_primary, primary)
            self.assertIs(value._claim_tx_connection, conn)
            self.assertEqual(value._claim_tx_thread, threading.get_ident())
            self.assertTrue(conn.in_transaction)
            self.assertEqual(value._lifecycle_state, 'quarantined')
            self.assertTrue(any('outcome=UNKNOWN' in note for note in primary.__notes__))
            retained_stage = value._claim_tx_document_stage
            with self.assertRaisesRegex(RuntimeError, 'provider_lifecycle_not_ready'):
                self.call(value, operation)
            self.assertIs(value._claim_tx_document_stage, retained_stage)
            self.assertIs(value._conn, conn)
            self.assertEqual(conn.rollbacks, 1)
        else:
            self.assertEqual(conn.state(), before)
            self.healthy(value)
            conn.fail_fragment = None
            self.call(value, operation)
            self.healthy(value)

    def test_normalize_apply(self): self.apply('_normalize_topics')
    def test_immune_apply(self): self.apply('_immune_scan')
    def test_vacuum_apply(self): self.apply('_vacuum')
    def test_normalize_suggest(self): self.suggest('_normalize_topics')
    def test_immune_suggest(self): self.suggest('_immune_scan')
    def test_vacuum_suggest(self): self.suggest('_vacuum')
    def test_normalize_noop(self): self.noop('_normalize_topics')
    def test_immune_noop(self): self.noop('_immune_scan')
    def test_vacuum_noop(self): self.noop('_vacuum')
    def test_normalize_rollback(self): self.failure('_normalize_topics')
    def test_immune_rollback(self): self.failure('_immune_scan')
    def test_vacuum_rollback(self): self.failure('_vacuum')
    def test_normalize_unknown(self): self.failure('_normalize_topics', unknown=True)
    def test_immune_unknown(self): self.failure('_immune_scan', unknown=True)
    def test_vacuum_unknown(self): self.failure('_vacuum', unknown=True)

    def test_required_change_log_failure_rolls_back(self):
        # Ordinary Exception must propagate too: standalone _add_change used to
        # be best effort, while conn=c makes the log an owning-TX obligation.
        for operation in OPERATIONS[:2]:
            value = self.receiver(operation)
            conn = value._conn
            before = conn.state()
            primary = ValueError('required change-log refusal')
            conn.fail_fragment, conn.primary = 'INSERT OR IGNORE INTO memory_changes', primary
            with self.assertRaises(ValueError) as caught:
                self.call(value, operation)
            self.assertIs(caught.exception, primary)
            self.assertEqual(conn.state(), before)
            self.assertEqual(conn.rollbacks, 1)
            self.healthy(value)

    def test_commit_before_and_after_effect_faults(self):
        for operation in OPERATIONS:
            for when in ('before', 'after'):
                value = self.receiver(operation)
                conn = value._conn
                before = conn.state()
                primary = SyntheticFault('synthetic commit boundary ' + when)
                conn.primary, conn.commit_fault = primary, when
                with self.assertRaises(SyntheticFault) as caught:
                    self.call(value, operation)
                self.assertIs(caught.exception, primary)
                self.assertEqual(conn.rollbacks, 1)
                self.assertFalse(conn.projection)
                self.assertFalse(any(e[0] == 'render_observer' for e in value.events))
                if when == 'before':
                    self.assertEqual(conn.state(), before)
                    self.healthy(value)
                else:
                    self.assertIs(value._transaction_quarantine, conn)
                    self.assertIs(value._transaction_primary, primary)
                    self.assertIs(value._claim_tx_connection, conn)
                    self.assertFalse(conn.in_transaction)
                    self.assertIn('commit_outcome_UNKNOWN', value._transaction_cleanup_notes)

    def test_nested_owner_is_not_committed_or_published(self):
        for operation in OPERATIONS:
            value = self.receiver(operation)
            conn = value._conn
            before = conn.state()
            primary = SyntheticFault('outer caller cancellation')
            with self.assertRaises(SyntheticFault) as caught:
                with value._claim_transaction(conn):
                    stage = value._claim_tx_document_stage
                    self.call(value, operation, 'suggest')
                    with self.assertRaisesRegex(RuntimeError, 'claim_transaction_requires_idle_owner'):
                        self.call(value, operation)
                    self.assertIs(value._claim_tx_document_stage, stage)
                    self.assertIs(value._claim_tx_connection, conn)
                    self.assertTrue(conn.in_transaction)
                    self.assertEqual(conn.commits, [])
                    self.assertEqual(conn.rollbacks, 0)
                    raise primary
            self.assertIs(caught.exception, primary)
            self.assertEqual(conn.state(), before)
            self.assertEqual(conn.rollbacks, 1)
            self.healthy(value)

    def test_model_acl_batch_preflight_and_private_positive(self):
        for operation in OPERATIONS:
            value = self.receiver(operation)
            conn = value._conn
            target = next(iter(conn.claims.values()))
            target['visibility_scope'] = 'global'
            before = conn.state()
            with self.assertRaisesRegex(PermissionError, 'shared claim mutation requires a trusted host'):
                self.call(value, operation, model_scope=True)
            self.assertEqual(conn.state(), before)
            self.assertFalse(conn.changes or conn.evidence or conn.projection)
            self.assertEqual(conn.commits, [])
            self.healthy(value)
            self.call(value, operation, model_scope=False)  # original trusted-host path
            self.healthy(value)
        for operation in OPERATIONS:
            value = self.receiver(operation)
            value.database_instance_id = 'synthetic-au01-database'
            expected_chat = hashlib.sha256(b'synthetic-au01-database\0session-a').hexdigest()[:32]
            for claim in value._conn.claims.values():
                claim.update(visibility_scope='chat', origin_chat_hash=expected_chat)
            self.call(value, operation, model_scope=True)
            self.healthy(value)
        for operation in OPERATIONS[:2]:
            value = self.receiver(operation)
            list(value._conn.claims.values())[-1]['origin_session_id'] = 'foreign'
            before = value._conn.state()
            with self.assertRaisesRegex(ValueError, 'claim not found:'):
                self.call(value, operation, model_scope=True)
            self.assertEqual(value._conn.state(), before)
            self.healthy(value)

    def test_vacuum_partition_and_endpoint_acl(self):
        value = self.receiver('_vacuum', rows=[row('a', 'same', scope='global'),
            row('b', 'same'), row('hidden', 'same', session='foreign')], stale=[])
        result = self.call(value, '_vacuum', 'suggest')
        self.assertEqual(result['actions'], [])
        self.assertNotIn('hidden', [item['id'] for item in result['topic_fixes']])
        value = self.receiver('_vacuum')
        value._conn.claims['inactive']['visibility_scope'] = 'global'
        before = value._conn.state()
        with self.assertRaisesRegex(PermissionError, 'shared claim mutation requires a trusted host'):
            self.call(value, '_vacuum', model_scope=True)
        self.assertEqual(value._conn.state(), before)
        self.healthy(value)

    def test_postcommit_fts_and_render_failures_are_not_success(self):
        for operation in OPERATIONS:
            for failing in ('fts', 'render'):
                value = self.receiver(operation)
                conn = value._conn
                primary = SyntheticFault('postcommit synthetic ' + failing)
                if failing == 'fts':
                    conn.fail_fragment, conn.primary = 'CREATE VIRTUAL TABLE', primary
                else:
                    value.render_primary = primary
                with self.assertRaises(SyntheticFault) as caught:
                    self.call(value, operation)
                self.assertIs(caught.exception, primary)
                self.assertEqual(len(conn.commits), 1 if failing == 'fts' else 2)
                self.assertEqual(conn.rollbacks, 1 if failing == 'fts' else 0)
                # Canonical fixture mutations committed before derived failure.
                self.assertTrue(conn.changes if operation != '_vacuum' else conn.evidence)
                self.healthy(value)

    def test_STATIC_owning_conn_and_postcommit_order(self):
        for item in self.carrier['definitions']:
            if item['name'] not in OPERATIONS:
                continue
            node = ast.parse(textwrap.dedent(item['source'])).body[0]
            contexts = [w for w in ast.walk(node) if isinstance(w, ast.With)]
            self.assertFalse(any(isinstance(i.context_expr, ast.Name) and i.context_expr.id == 'c'
                                 for w in contexts for i in w.items))
            tx = [w for w in contexts if any(isinstance(i.context_expr, ast.Call)
                and isinstance(i.context_expr.func, ast.Attribute)
                and i.context_expr.func.attr == '_claim_transaction' for i in w.items)]
            self.assertEqual(len(tx), 1)
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
            for call in calls:
                if call.func.attr in {'_add_change', '_add_evidence', '_require_model_mutable_claim'}:
                    self.assertTrue(any(k.arg == 'conn' and isinstance(k.value, ast.Name) and k.value.id == 'c'
                                        for k in call.keywords))
                    self.assertLessEqual(tx[0].lineno, call.lineno)
                    self.assertLessEqual(call.end_lineno, tx[0].end_lineno)
            rebuild = next(n for n in calls if n.func.attr == '_rebuild_fts')
            render = next(n for n in calls if n.func.attr == '_render_all')
            self.assertLess(tx[0].end_lineno, rebuild.lineno)
            self.assertLessEqual(rebuild.end_lineno, render.lineno)

    def test_STATIC_original_guards_and_journal_preserved(self):
        evidence = self.carrier['static']
        self.assertEqual(evidence['base'], '028fe5f1471ee06e49261b29af9e31aade42fc80')
        self.assertTrue(evidence['outside_three_methods_raw_equal'])
        self.assertTrue(evidence['unchanged_owner_guard_journal_fts_render'])
        self.assertEqual(evidence['changed_product_definitions'], list(OPERATIONS))
        self.assertTrue(evidence['baseline_has_raw_connection_contexts'])
        self.assertTrue(evidence['baseline_missing_nested_conn'])
        self.assertEqual(evidence['level'], 'STATIC_NOT_RUNTIME')


    def public_receiver(self, operation, *, chat=False):
        # Two lawful eligible targets, one bounded intent. Vacuum uses only its
        # topic-fix lane, avoiding an invented global one-row vacuum guarantee.
        texts = (('fixture-low first', 'fixture-low second') if operation == '_immune_scan'
                 else ('alpha persistent assertion', 'beta durable fact'))
        value = self.receiver(operation, rows=[row('first', texts[0]), row('second', texts[1])], stale=[])
        value.connections, value.closed_connections, value.journal_events = [value._conn], [], []
        value._background_worker = None
        value._graph_writer_connections, value._graph_reader_connections = {}, {}
        if chat:
            value.database_instance_id = 'synthetic-au01-public-database'
            chat_hash = hashlib.sha256(b'synthetic-au01-public-database\0session-a').hexdigest()[:32]
            for claim in value._conn.claims.values():
                claim.update(visibility_scope='chat', origin_chat_hash=chat_hash)
        return value

    def public_call(self, value, operation, *, model_scope=True, mode='apply'):
        args = {'mode': mode, 'limit': 1}
        kwargs = {}
        if not model_scope:
            # Exact internal sentinel/replay path, SOURCE identity only. This is
            # NOT a fabricated SDK or native host authorization capability.
            args['__journal_replay'] = True
            kwargs = self.namespace['_internal_journal_call_kwargs']()
        return json.loads(value.handle_tool_call('memory_wiki' + operation, args, **kwargs))

    def assert_first_only(self, value, operation, second_before):
        conn = value._conn
        self.assertEqual(conn.claims['second'], second_before)
        if operation == '_immune_scan':
            self.assertEqual(conn.claims['first']['status'], 'uncertain')
            self.assertEqual([item[2] for item in conn.changes], ['first'])
        else:
            self.assertEqual(conn.claims['first']['topic'], 'canonical')
            self.assertEqual(conn.claims['first']['status'], 'active')
            if operation == '_normalize_topics':
                self.assertEqual([item[2] for item in conn.changes], ['first'])
            else:
                self.assertFalse(conn.evidence or conn.changes or conn.stale)

    def public_postcommit(self, failing):
        errors = (sqlite3.OperationalError, sqlite3.DatabaseError)
        if failing == 'render':
            errors += (ValueError,)
        for operation in OPERATIONS:
            for model_scope in (True, False):
                for error_type in errors:
                    value = self.public_receiver(operation, chat=model_scope)
                    conn = value._conn
                    second = copy.deepcopy(conn.claims['second'])
                    primary = error_type('disk I/O error; fixture-only private payload')
                    if failing == 'fts':
                        conn.fail_fragment, conn.primary = 'CREATE VIRTUAL TABLE', primary
                        conn.ordinary_fault_once = True
                    else:
                        value.render_primary, value.render_fault_once = primary, True
                    result = self.public_call(value, operation, model_scope=model_scope)
                    self.assertIs(result['success'], False)
                    self.assertEqual(result['error'], 'maintenance_postcommit_failed')
                    self.assertEqual(result['canonical_outcome'], 'committed')
                    self.assertIs(result['retryable'], False)
                    self.assertEqual(result['derived_outcome'], 'incomplete')
                    self.assertEqual(result['detail'], error_type.__name__)
                    self.assertNotIn('fixture-only private payload', json.dumps(result))
                    self.assertIs(value._conn, conn)
                    self.assertEqual(len(value.connections), 1)
                    self.assertEqual(value.closed_connections, [])
                    self.assertEqual(len(conn.commits), 1 if failing == 'fts' else 2)
                    self.assertEqual(conn.rollbacks, 1 if failing == 'fts' else 0)
                    self.assert_first_only(value, operation, second)
                    # Inspect the committed canonical snapshot, not merely
                    # an idle/closed flag or an internal retry counter.
                    self.assertEqual(conn.commits[0][0], conn.claims)
                    self.assertEqual([event['phase'] for event in value.journal_events],
                                     ['before', 'error'] if model_scope else [])
                    self.assertFalse(any(event[0] == 'journal_after_result_observer' for event in value.events))
                    self.healthy(value)

    def test_public_postcommit_sqlite_fts_limit_one(self):
        self.public_postcommit('fts')

    def test_public_postcommit_render_limit_one(self):
        self.public_postcommit('render')

    def test_public_healthy_apply_limit_one_and_journal(self):
        for operation in OPERATIONS:
            for model_scope in (True, False):
                value = self.public_receiver(operation, chat=model_scope)
                second = copy.deepcopy(value._conn.claims['second'])
                result = self.public_call(value, operation, model_scope=model_scope)
                self.assertIs(result['success'], True)
                self.assertNotIn('canonical_outcome', result)
                self.assertEqual(result['applied'], 1 if operation == '_normalize_topics' else
                    ({'retired': 0, 'uncertain': 1, 'retopic': 0, 'queued': 0} if operation == '_immune_scan' else
                     {'merged': 0, 'topic_fixes': 1, 'resolved_contradictions': 0, 'retired_artifacts': 0}))
                self.assert_first_only(value, operation, second)
                self.assertEqual(len(value._conn.commits), 2)
                self.assertEqual(value._conn.rollbacks, 0)
                self.assertEqual([event['phase'] for event in value.journal_events],
                                 ['before', 'after'] if model_scope else [])
                self.healthy(value)
                before = value._conn.state()
                result = self.public_call(value, operation, model_scope=model_scope, mode='suggest')
                self.assertIs(result['success'], True)
                self.assertEqual(value._conn.state(), before)

    def test_public_precommit_rollback_reconnect_retry(self):
        for operation in OPERATIONS:
            for model_scope in (True, False):
                for error_type in (sqlite3.OperationalError, sqlite3.DatabaseError):
                    value = self.public_receiver(operation, chat=model_scope)
                    conn = value._conn
                    before, second = conn.state(), copy.deepcopy(conn.claims['second'])
                    conn.fail_fragment, conn.primary = 'UPDATE claims SET', error_type('disk I/O error')
                    conn.ordinary_fault_once = True
                    result = self.public_call(value, operation, model_scope=model_scope)
                    self.assertIs(result['success'], True)
                    self.assertEqual(conn.state(), before)
                    self.assertEqual(conn.rollbacks, 1)
                    self.assertEqual(conn.commits, [])
                    self.assertEqual(value.closed_connections, [conn])
                    self.assertTrue(conn.closed)
                    self.assertEqual(len(value.connections), 2)
                    self.assertEqual(sum(e[0] == 'migrate_observer' for e in value.events), 1)
                    self.assert_first_only(value, operation, second)
                    self.assertEqual(len(value._conn.commits), 2)
                    self.assertEqual([e['phase'] for e in value.journal_events],
                                     ['before', 'after'] if model_scope else [])
                    self.healthy(value)

    def test_public_unknown_never_reconnects(self):
        for operation in OPERATIONS:
            for model_scope in (True, False):
                for fault in ('rollback', 'commit-after', 'fts-rollback'):
                    value = self.public_receiver(operation, chat=model_scope)
                    conn = value._conn
                    second = copy.deepcopy(conn.claims['second'])
                    primary = sqlite3.OperationalError('disk I/O error')
                    conn.primary = primary
                    if fault == 'commit-after':
                        conn.commit_fault = 'after'
                    else:
                        conn.fail_fragment = 'CREATE VIRTUAL TABLE' if fault == 'fts-rollback' else 'UPDATE claims SET'
                        conn.rollback_primary = RuntimeError('synthetic rollback refusal')
                    result = self.public_call(value, operation, model_scope=model_scope)
                    self.assertFalse(result.get('success', False))
                    if fault == 'fts-rollback':
                        self.assertEqual(result['canonical_outcome'], 'committed')
                        self.assertEqual(result['derived_outcome'], 'unknown')
                        self.assertIs(result['retryable'], False)
                        self.assert_first_only(value, operation, second)
                    else:
                        self.assertIn('UNKNOWN', result['error'])
                        self.assertNotIn('canonical_outcome', result)
                    self.assertIs(value._transaction_quarantine, conn)
                    self.assertIs(value._transaction_primary, primary)
                    self.assertEqual(value.closed_connections, [])
                    self.assertEqual(len(value.connections), 1)
                    self.assertEqual(conn.rollbacks, 1)
                    self.assertTrue(any('outcome=UNKNOWN' in note for note in primary.__notes__))
                    retained = value._claim_tx_document_stage
                    again = self.public_call(value, operation, model_scope=model_scope)
                    self.assertIn('UNKNOWN', again['error'])
                    self.assertIs(value._claim_tx_document_stage, retained)
                    self.assertEqual(conn.rollbacks, 1)
                    self.assertIs(value._conn, conn)
                    self.assertEqual(value._lock.depth, 0)

    def test_public_fatal_primary_identity(self):
        for operation in OPERATIONS:
            for model_scope in (True, False):
                for failing in ('precommit', 'fts', 'render'):
                    value = self.public_receiver(operation, chat=model_scope)
                    conn = value._conn
                    primary = SyntheticFault('fatal public synthetic ' + failing)
                    if failing == 'render':
                        value.render_primary = primary
                    else:
                        conn.fail_fragment = 'CREATE VIRTUAL TABLE' if failing == 'fts' else 'UPDATE claims SET'
                        conn.primary = primary
                    with self.assertRaises(SyntheticFault) as caught:
                        self.public_call(value, operation, model_scope=model_scope)
                    self.assertIs(caught.exception, primary)
                    self.assertEqual(len(conn.commits), {'precommit': 0, 'fts': 1, 'render': 2}[failing])
                    self.assertEqual(conn.rollbacks, int(failing != 'render'))
                    self.assertEqual(value.closed_connections, [])
                    self.assertEqual([e['phase'] for e in value.journal_events], ['before'] if model_scope else [])
                    self.healthy(value)

    def test_public_next_attempt_and_foreign_owner_are_not_tainted(self):
        for operation in OPERATIONS:
            value = self.public_receiver(operation)
            conn = value._conn
            conn.fail_fragment, conn.primary = 'CREATE VIRTUAL TABLE', sqlite3.DatabaseError('ordinary FTS fault')
            conn.ordinary_fault_once = True
            self.assertEqual(self.public_call(value, operation)['canonical_outcome'], 'committed')
            first = copy.deepcopy(conn.claims['first'])
            # A new intent encounters a safe precommit fault. Its fresh receipt
            # must allow the existing actual release/reconnect/recursive path.
            conn.fail_fragment, conn.primary = 'UPDATE claims SET', sqlite3.OperationalError('disk I/O error')
            result = self.public_call(value, operation)
            self.assertIs(result['success'], True)
            self.assertNotIn('canonical_outcome', result)
            self.assertEqual(value._conn.claims['first'], first)
            self.assertEqual(len(value.connections), 2)
            if operation == '_immune_scan':
                self.assertEqual(value._conn.claims['second']['status'], 'uncertain')
            else:
                self.assertEqual(value._conn.claims['second']['topic'], 'canonical')
            self.assertNotIn('_maintenance_commit', value.__dict__)
            self.healthy(value)
            foreign = self.public_receiver(operation)
            foreign._conn.claims['second']['origin_session_id'] = 'foreign-session'
            before = foreign._conn.state()
            result = self.public_call(foreign, operation)
            self.assertEqual(result['error'], 'shared_claim_scope_unavailable')
            self.assertEqual(foreign._conn.state(), before)
            self.assertEqual(foreign.journal_events, [])
            self.assertEqual(foreign._conn.commits, [])
            self.healthy(foreign)

    def test_commit_receipt_requires_actual_success_and_standalone_owner(self):
        for operation in OPERATIONS:
            for when in ('healthy', 'before', 'after'):
                value = self.receiver(operation)
                conn, receipt = value._conn, []
                if when == 'healthy':
                    self.call(value, operation, limit=1, _commit_receipt=receipt)
                    self.assertEqual(len(receipt), 1)
                    owner, observed, stage = receipt[0]
                    self.assertIs(owner, value)
                    self.assertIs(observed, conn)
                    self.assertIs(stage[0], conn)
                    self.assertEqual(stage[1], threading.get_ident())
                    self.assertEqual(stage[2], [])  # actual retired owner stage
                    foreign = self.receiver(operation)
                    self.assertIsNone(foreign._maintenance_committed_error(receipt, ValueError('foreign')))
                    self.assertIsNone(value._maintenance_committed_error([], ValueError('idle is not commit')))
                else:
                    conn.primary, conn.commit_fault = SyntheticFault('receipt commit ' + when), when
                    with self.assertRaises(SyntheticFault) as caught:
                        self.call(value, operation, _commit_receipt=receipt)
                    self.assertIs(caught.exception, conn.primary)
                    self.assertEqual(receipt, [])
                    if when == 'after':
                        self.assertIs(value._transaction_quarantine, conn)
        for bad, kwargs in (({}, {}), ([object()], {}), ([], {'join': True}),
                            ([], {'adopt': True}), ([], {'begin': 'EXCLUSIVE'})):
            value = self.receiver('_normalize_topics')
            with self.assertRaisesRegex(ValueError, 'invalid_claim_commit_receipt_mode'):
                with value._claim_transaction(value._conn, _commit_receipt=bad, **kwargs):
                    self.fail('invalid receipt entered owner')
            self.assertEqual(value._conn.commands, [])
            self.healthy(value)
        value = self.receiver('_normalize_topics')
        with value._claim_transaction(value._conn):
            with self.assertRaisesRegex(RuntimeError, 'claim_transaction_requires_idle_owner'):
                with value._claim_transaction(value._conn, _commit_receipt=[]):
                    self.fail('nested receipt entered owner')

    def test_STATIC_correction_wiring_and_source_ownership(self):
        evidence = self.carrier['correction_static']
        self.assertEqual(evidence['base'], 'c2a0709778dd8bfb2ea7b0f0b069e926ef637320')
        self.assertTrue(evidence['outside_changed_definitions_raw_equal'])
        self.assertTrue(evidence['release_rollback_quarantine_journal_fts_acl_raw_equal'])
        self.assertTrue(evidence['original_23_methods_raw_equal'])
        self.assertTrue(evidence['original_roster_prefix_and_assertions_preserved'])
        self.assertTrue(evidence['module_and_class_pytest_opt_out'])
        self.assertTrue(evidence['full_public_handler_and_journal_selected'])
        self.assertEqual(evidence['level'], 'STATIC_NOT_RUNTIME')
        by_name = {item['name']: ast.parse(textwrap.dedent(item['source'])).body[0]
                   for item in self.carrier['definitions'] if item['owner']}
        owner = by_name['_claim_transaction']
        commit = next(n for n in ast.walk(owner) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                      and n.func.value.id == 'c' and n.func.attr == 'commit')
        publish = next(n for n in ast.walk(owner) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                       and n.func.value.id == '_commit_receipt' and n.func.attr == 'append')
        self.assertLess(commit.lineno, publish.lineno)
        public = by_name['handle_tool_call']
        dispatch_try = next(n for n in public.body if isinstance(n, ast.Try))
        self.assertEqual(len(dispatch_try.handlers), 4)
        for handler in dispatch_try.handlers:
            self.assertIn('_maintenance_committed_error', ast.unparse(handler.body[0]))
        for operation in OPERATIONS:
            calls = [n for n in ast.walk(public) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and n.func.attr == operation]
            self.assertEqual(len(calls), 1)
            self.assertTrue(any(k.arg == '_commit_receipt' and isinstance(k.value, ast.Name)
                                and k.value.id == '_maintenance_commit' for k in calls[0].keywords))


def source_suite(carrier):
    MaintenanceApplyOwnerSource.carrier = carrier
    return unittest.TestSuite(MaintenanceApplyOwnerSource(case) for case in CASE_IDS)


def main():
    required = ('DEVTOOLS_INPUTS', 'DEVTOOLS_SCRATCH', 'devtools_read_bound', 'devtools_case_started')
    if any(key not in globals() for key in required):
        raise RuntimeError('original_source_bootstrap_required')
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError('selected_isolated_python_required')
    sql_attempts = []
    def no_sql(event, args):
        if event == 'sqlite3.connect':
            sql_attempts.append(event)
            raise PermissionError('AU01_SQL_NOT_ADMITTED')
    # Strictly additive denial; the original audit guard remains installed.
    sys.addaudithook(no_sql)
    carrier = json.loads(devtools_read_bound(DEVTOOLS_INPUTS['maintenance-selected.json']))
    reporter = carrier['reporter']
    reporter_raw = reporter['source'].encode('utf-8')
    if hashlib.sha256(reporter_raw).hexdigest() != reporter['sha256']:
        raise RuntimeError('original_reporter_span_mismatch')
    reporter_tree = ast.parse(textwrap.dedent(reporter['source']))
    if len(reporter_tree.body) != 1 or reporter_tree.body[0].name != 'SourceResult':
        raise RuntimeError('unique_bound_reporter_required')
    namespace = {'__name__': 'au01_original_reporter', 'unittest': unittest,
                 'json': json, 'sys': sys, 'devtools_case_started': devtools_case_started}
    exec(compile(reporter_tree, '<au01-original-bound-reporter>', 'exec', dont_inherit=True), namespace)
    result = namespace['SourceResult']()
    source_suite(carrier).run(result)
    complete = [case['id'] for case in result.cases] == list(CASE_IDS)
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'cases': result.cases,
                      'unittest_events': result.events, 'sqlite_connect_attempts': len(sql_attempts),
                      'qualification': '29 extracted synthetic-control-flow mains; 3 STATIC mains, '
                      'including one historical original-AU01 delta assertion. Complete selected public/retry/journal '
                      'decision bodies, synthetic connections/migration/journal storage and standalone JSON transport. '
                      'Genuine SQL/provider apply, rollback, UNKNOWN, FTS/trigger parity, journal durability, '
                      'rendering, concurrency, SDK/native public/Windows/Linux/FULL NOT_RUN.'},
                     ensure_ascii=False, separators=(',', ':')))
    return 0 if result.wasSuccessful() and complete and not sql_attempts else 1


if __name__ == '__main__':
    raise SystemExit(main())
