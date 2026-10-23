"""SOURCE regression: genuine extracted ACL/query bodies on own file SQLite.

No plugin/SDK import or provider authority. Receiver/principals/clock and the
sanitizer observer are synthetic. The original sanitizer is pinned, NOT executed.
An external SOURCE entry supplies a bound small carrier for the oversized module.
Direct stdlib execution extracts the same methods without importing the package;
set RECENT_CHANGES_TEST_ROOT to an owned scratch directory to retain fixtures.
"""
from __future__ import annotations

import __future__
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import textwrap
import types
import unittest


STAMP = 10000
DATABASE = 'synthetic-rch01-database'
METHODS = ('_recent_changes', '_claim_visibility_sql', '_claim_visible', '_chat_hash')
BASELINE_COMMIT = 'a4e118e921f5708ead87d834187805900b08b493'
BASELINE_RAW_SHA256 = '0b4fc9bc4bf914318a54237a977819d75533a1c1eaaedcc401e716703fbfc8d2'
BASELINE_METHOD = '''    def _recent_changes(self, since_seconds: int = 3600, limit: int = 50) -> Dict[str, Any]:
        cutoff=now()-max(1,int(since_seconds or 3600)); limit=max(1,min(int(limit or 50),200)); c=self._connect()
        rows=[]
        for row in c.execute("SELECT * FROM memory_changes WHERE created_at>=? ORDER BY created_at DESC LIMIT ?", (cutoff,limit)).fetchall():
            claim=c.execute("SELECT * FROM claims WHERE id=?",(row["claim_id"],)).fetchone()
            if claim is not None and self._claim_visible(claim): rows.append(self._sanitize_row(row))
        return {"since_seconds":since_seconds,"count":len(rows),"changes":rows}
'''
OBSERVATIONS = {}


def source_span(raw, node):
    data = b''.join(raw.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
    return {'source': data.decode('utf-8'), 'lineno': node.lineno,
            'end_lineno': node.end_lineno, 'sha256': hashlib.sha256(data).hexdigest()}


def local_carrier():
    path = Path(__file__).absolute().parent.parent / '__init__.py'
    raw = path.read_bytes()
    tree = ast.parse(raw)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MemoryWikiProvider')
    nodes = {n.name: n for n in owner.body if isinstance(n, ast.FunctionDef)}
    return {'candidate': {name: source_span(raw, nodes[name]) for name in (*METHODS, '_sanitize_row')},
            'now': source_span(raw, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'now')),
            'baseline_recent': {'source': BASELINE_METHOD, 'lineno': 15848, 'end_lineno': 15854,
                                'sha256': hashlib.sha256(BASELINE_METHOD.encode('utf-8')).hexdigest()}}


class FixtureClock:
    @staticmethod
    def time():
        return STAMP


def compile_span(item, namespace):
    assert hashlib.sha256(item['source'].encode('utf-8')).hexdigest() == item['sha256']
    tree = ast.parse(textwrap.dedent(item['source']))
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
    ast.increment_lineno(tree, item['lineno'] - 1)
    exec(compile(tree, '<source-bound-recent-changes>', 'exec',
                 flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
    return namespace[tree.body[0].name]


def prepare(carrier=None):
    """Definitions only; metadata preflight must not open SQLite or run cases."""
    carrier = carrier if carrier is not None else local_carrier()
    assert carrier['baseline_recent']['source'] == BASELINE_METHOD
    namespace = {'hashlib': hashlib, 'time': FixtureClock}
    compile_span(carrier['now'], namespace)
    functions = {name: compile_span(carrier['candidate'][name], namespace) for name in METHODS}
    baseline_namespace = dict(namespace)
    baseline = compile_span(carrier['baseline_recent'], baseline_namespace)
    product = type('ExtractedRecentChanges', (), functions)
    # Keep the unchanged full sanitizer span available, but do not replace its
    # production redactor with a permissive fake and call that native redaction.
    original_sanitizer = carrier['candidate']['_sanitize_row']
    assert hashlib.sha256(original_sanitizer['source'].encode('utf-8')).hexdigest() == original_sanitizer['sha256']
    return product, baseline, namespace, baseline_namespace


class SelectedCursor:
    """Only after a REAL SQLite SELECT/fetchall, expose a deterministic seam."""
    def __init__(self, owner, cursor):
        self.owner, self.cursor = owner, cursor

    def fetchall(self):
        rows = self.cursor.fetchall()
        self.owner.selected.append([row['id'] for row in rows])
        callback, self.owner.after_select = self.owner.after_select, None
        if callback is not None:
            callback()
        return rows


class FixtureConnection:
    """Synthetic adapter; every execute delegates unchanged to stdlib SQLite."""
    def __init__(self, conn):
        self.conn, self.calls, self.selected, self.after_select = conn, [], [], None

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        cursor = self.conn.execute(sql, params)
        if 'FROM memory_changes' in sql:
            return SelectedCursor(self, cursor)
        return cursor


class ReceiverObservers:
    """No SQL-owner/lifecycle or principal mapper authority is represented."""
    def _connect(self):
        return self.reader

    def _meta_text(self, *_args):
        raise AssertionError('synthetic nonempty database_instance_id required')

    def _claim_visibility_sql(self, *args, **kwargs):
        self.sql_visibility_calls.append((args, kwargs))
        return self.product._claim_visibility_sql(self, *args, **kwargs)

    def _claim_visible(self, row, session_id=''):
        self.visibility_calls.append(row['id'])
        return self.product._claim_visible(self, row, session_id)

    def _sanitize_row(self, row):
        self.sanitizer_calls.append(row['id'])
        result = dict(row)
        if self.mark_sanitized:
            result['detail'] = 'sanitizer-observer:' + row['id']
        return result


def receiver(product, reader, *, bot='bot-a', session='session-a', project='project-a', database=DATABASE):
    cls = type('SyntheticReceiver', (ReceiverObservers, product), {})
    value = cls()
    value.product, value.reader = product, reader
    value.bot_id, value.session_id, value.project_scope = bot, session, project
    value.database_instance_id = database
    value.visibility_calls, value.sql_visibility_calls, value.sanitizer_calls = [], [], []
    value.mark_sanitized = False
    return value


def independent_chat_hash(session, database=DATABASE):
    # Synthetic identity producer: independent expected literal inputs, not the
    # product mapper used as its own ACL oracle. This is NOT native identity proof.
    return hashlib.sha256((database + '\0' + session).encode('utf-8')).hexdigest()[:32]


class RecentChangesVisibilitySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.product, baseline, cls.namespace, cls.baseline_namespace = prepare(globals().get('SOURCE_CARRIER'))
        cls.baseline = staticmethod(baseline)

    def setUp(self):
        root = globals().get('DEVTOOLS_SCRATCH') or os.environ.get('RECENT_CHANGES_TEST_ROOT')
        if root is None:
            root = tempfile.mkdtemp(prefix='recent-changes-', dir=os.environ.get('TMPDIR'))
        self.home = Path(root) / self._testMethodName
        self.home.mkdir(parents=True, exist_ok=False)
        self.path = self.home / 'fixture.sqlite3'
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.addCleanup(self.close_fixture)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE claims(
                id TEXT PRIMARY KEY, visibility_scope TEXT, origin_bot_id TEXT,
                origin_session_id TEXT, origin_chat_hash TEXT, project_id TEXT,
                status TEXT, claim TEXT);
            CREATE TABLE memory_changes(
                id TEXT PRIMARY KEY, action TEXT NOT NULL, claim_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
            CREATE INDEX idx_memory_changes_created ON memory_changes(created_at);
        ''')
        self.reader = FixtureConnection(self.conn)
        self.actor = receiver(self.product, self.reader)

    def close_fixture(self):
        self.conn.close()
        try:
            self.conn.execute('SELECT 1')
        except sqlite3.ProgrammingError:
            OBSERVATIONS.setdefault(self._testMethodName, {})['fixture_connection_closed'] = True
        else:
            raise AssertionError('fixture connection still open')

    def claim(self, cid, *, scope='global', bot='bot-a', session='session-a', project='project-a',
              chat=None, status='active'):
        self.conn.execute('INSERT INTO claims VALUES(?,?,?,?,?,?,?,?)',
                          (cid, scope, bot, session, independent_chat_hash(session) if chat is None else chat,
                           project, status, 'synthetic claim ' + cid))

    def change(self, ident, cid, timestamp=STAMP - 1, *, detail='synthetic detail', action='update'):
        self.conn.execute('INSERT INTO memory_changes VALUES(?,?,?,?,?)',
                          (ident, action, cid, detail, timestamp))

    def ids(self, result):
        self.assertEqual(set(result), {'since_seconds', 'count', 'changes'})
        self.assertEqual(result['count'], len(result['changes']))
        return [row['id'] for row in result['changes']]

    def crowded(self):
        for i in range(7):
            self.claim('hidden-' + str(i), scope='private', session='foreign-session')
            self.change('hidden-change-' + str(i), 'hidden-' + str(i), STAMP - i)
        self.claim('tail')
        self.change('tail-change', 'tail', STAMP - 20)
        self.conn.commit()

    def scope_matrix(self, scope, principals, expected):
        self.claim('scoped', scope=scope)
        self.change('scoped-change', 'scoped')
        self.claim('tail')
        self.change('tail-change', 'tail', STAMP - 2)
        self.conn.commit()
        outcomes = []
        for kwargs, allowed in zip(principals, expected, strict=True):
            actor = receiver(self.product, self.reader, **kwargs)
            result = actor._recent_changes(3600, 1)
            expected_id = 'scoped-change' if allowed else 'tail-change'
            self.assertEqual(self.ids(result), [expected_id])
            row = self.conn.execute('SELECT * FROM claims WHERE id=?', ('scoped',)).fetchone()
            self.assertIs(self.product._claim_visible(actor, row), allowed)
            self.assertEqual(actor._chat_hash(), independent_chat_hash(actor.session_id or 'default', actor.database_instance_id))
            self.assertEqual(actor.sql_visibility_calls, [((), {'prefix': 'claims.'})])
            self.assertEqual(actor.sanitizer_calls, [expected_id])
            outcomes.append({'principal': kwargs, 'allowed': allowed, 'returned': expected_id})
        OBSERVATIONS[self._testMethodName] = {'principals': outcomes}

    def test_baseline_witness_inaccessible_prefix_omits_tail(self):
        self.crowded()
        before = self.conn.total_changes
        original = self.baseline(self.actor, 3600, 3)
        baseline_selected = self.reader.selected[-1]
        candidate = self.actor._recent_changes(3600, 3)
        self.assertEqual(self.ids(original), [])
        self.assertEqual(self.ids(candidate), ['tail-change'])
        self.assertEqual(len(baseline_selected), 3)
        self.assertTrue(all(ident.startswith('hidden-change-') for ident in baseline_selected))
        self.assertEqual(self.conn.total_changes, before)
        OBSERVATIONS[self._testMethodName] = {
            'baseline_expected_property_violation': True, 'baseline_returned': self.ids(original),
            'candidate_returned': self.ids(candidate), 'newest_inaccessible_rows': 7,
            'requested_limit': 3, 'same_real_fixture_unchanged': True}

    def test_candidate_visible_tail_before_limit(self):
        self.crowded()
        result = self.actor._recent_changes(3600, 3)
        self.assertEqual(self.ids(result), ['tail-change'])
        self.assertEqual(self.reader.selected, [['tail-change']])
        self.assertEqual(self.actor.visibility_calls, ['tail'])
        self.assertEqual(self.actor.sanitizer_calls, ['tail-change'])
        sql, params = self.reader.calls[0]
        self.assertIn('JOIN claims ON claims.id=memory_changes.claim_id', sql)
        self.assertEqual(params[0], STAMP - 3600)
        self.assertEqual(params[-1], 3)
        self.assertNotIn(self.actor.bot_id, sql)
        self.assertNotIn(self.actor.session_id, sql)
        self.assertEqual(len(params), 10)

    def test_scope_global(self):
        self.scope_matrix('GLOBAL', [{}, {'bot': 'other', 'session': 'other', 'project': ''}], [True, True])

    def test_scope_bot(self):
        self.scope_matrix('bot', [{}, {'session': 'other'}, {'bot': 'other'}], [True, True, False])

    def test_scope_chat(self):
        self.scope_matrix('chat', [{}, {'session': 'other'}, {'bot': 'other'}, {'database': 'other-database'}],
                          [True, False, False, False])

    def test_scope_private(self):
        self.scope_matrix('private', [{}, {'project': 'other'}, {'session': 'other'}, {'bot': 'other'}],
                          [True, True, False, False])

    def test_scope_project(self):
        self.scope_matrix('project', [{}, {'bot': 'other', 'session': 'other'}, {'project': 'other'}, {'project': ''}],
                          [True, True, False, False])
        self.conn.execute("UPDATE claims SET project_id='' WHERE id='scoped'")
        empty_project = receiver(self.product, self.reader, project='')
        self.assertEqual(self.ids(empty_project._recent_changes(3600, 1)), ['tail-change'])

    def test_unknown_and_orphan_do_not_crowd_tail(self):
        for i, scope in enumerate(('unknown', '', None)):
            self.claim('unknown-' + str(i), scope=scope)
            self.change('unknown-change-' + str(i), 'unknown-' + str(i), STAMP - i)
        self.change('orphan-change', 'missing-claim', STAMP)
        self.claim('tail')
        self.change('tail-change', 'tail', STAMP - 30)
        result = self.actor._recent_changes(3600, 1)
        self.assertEqual(self.ids(result), ['tail-change'])
        self.assertEqual(self.reader.selected, [['tail-change']])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM memory_changes').fetchone()[0], 5)

    def test_cutoff_and_newest_visible_order(self):
        self.claim('visible')
        self.claim('hidden', scope='bot', bot='other')
        for ident, timestamp in (('old', STAMP - 61), ('boundary', STAMP - 60),
                                 ('middle', STAMP - 20), ('newest', STAMP - 1)):
            self.change(ident, 'visible', timestamp)
        self.change('hidden-newest', 'hidden', STAMP)
        self.assertEqual(self.ids(self.actor._recent_changes(60, 2)), ['newest', 'middle'])
        self.assertEqual(self.ids(self.actor._recent_changes(60, 200)), ['newest', 'middle', 'boundary'])
        self.assertEqual(self.actor.sanitizer_calls, ['newest', 'middle', 'newest', 'middle', 'boundary'])

    def test_limit_clamps_defaults_and_invalid_inputs(self):
        self.claim('visible')
        for i in range(205):
            self.change('limit-' + str(i), 'visible', STAMP - i)
        for requested, expected in ((1, 1), (-7, 1), (0, 50), (None, 50), ('2', 2), (200, 200), (999, 200)):
            self.assertEqual(self.actor._recent_changes(3600, requested)['count'], expected)
            self.assertEqual(len(self.reader.selected[-1]), expected)
            self.assertEqual(self.reader.calls[-(expected + 1)][1][-1], expected)
        self.assertEqual(self.actor._recent_changes()['count'], 50)
        with self.assertRaises(ValueError):
            self.actor._recent_changes(3600, 'invalid')

    def test_since_seconds_clamps_and_echo(self):
        self.claim('visible')
        self.change('now', 'visible', STAMP)
        self.change('one', 'visible', STAMP - 1)
        self.change('two', 'visible', STAMP - 2)
        self.change('default-boundary', 'visible', STAMP - 3600)
        self.change('default-old', 'visible', STAMP - 3601)
        for requested, expected in ((-2, ['now', 'one']), (1, ['now', 'one']),
                                    (0, ['now', 'one', 'two', 'default-boundary']),
                                    (None, ['now', 'one', 'two', 'default-boundary'])):
            result = self.actor._recent_changes(requested, 200)
            self.assertEqual(result['since_seconds'], requested)
            self.assertEqual(self.ids(result), expected)
        self.assertEqual(self.actor._recent_changes()['since_seconds'], 3600)
        with self.assertRaises(ValueError):
            self.actor._recent_changes('invalid', 1)

    def test_empty_schema_and_history_status(self):
        self.assertEqual(self.actor._recent_changes(60, 3), {'since_seconds': 60, 'count': 0, 'changes': []})
        for i, status in enumerate(('active', 'archived', 'superseded', 'quarantined')):
            self.claim('status-' + str(i), status=status)
            self.change('status-change-' + str(i), 'status-' + str(i), STAMP - i,
                        action='history-' + status)
        result = self.actor._recent_changes(60, 200)
        self.assertEqual(self.ids(result), ['status-change-' + str(i) for i in range(4)])
        for row in result['changes']:
            self.assertEqual(set(row), {'id', 'action', 'claim_id', 'detail', 'created_at'})
            self.assertIsInstance(row['created_at'], int)
        self.assertEqual(self.conn.total_changes, 8)

    def test_final_revalidation_reads_canonical_claim(self):
        self.claim('visible')
        self.change('visible-change', 'visible')
        def revoke():
            self.conn.execute("UPDATE claims SET visibility_scope='private', origin_session_id='foreign' WHERE id='visible'")
        self.reader.after_select = revoke
        self.assertEqual(self.ids(self.actor._recent_changes(60, 1)), [])
        self.assertEqual(self.reader.selected, [['visible-change']])
        self.assertEqual(self.actor.visibility_calls, ['visible'])
        self.assertEqual(self.actor.sanitizer_calls, [])
        self.assertEqual(self.reader.calls[-1], ('SELECT * FROM claims WHERE id=?', ('visible',)))

    def test_canonical_missing_after_selection_is_skipped(self):
        self.claim('visible')
        self.change('visible-change', 'visible')
        def remove_owned_fixture_claim():
            self.conn.execute("DELETE FROM claims WHERE id='visible'")
        self.reader.after_select = remove_owned_fixture_claim
        self.assertEqual(self.ids(self.actor._recent_changes(60, 1)), [])
        self.assertEqual(self.reader.selected, [['visible-change']])
        self.assertEqual(self.actor.visibility_calls, [])
        self.assertEqual(self.actor.sanitizer_calls, [])

    def test_sanitizer_invocation_and_projection(self):
        self.claim('visible')
        self.claim('hidden', scope='private', session='other')
        self.change('visible-change', 'visible', detail='original synthetic detail')
        self.change('hidden-change', 'hidden', STAMP, detail='ineligible synthetic detail')
        self.actor.mark_sanitized = True
        result = self.actor._recent_changes(60, 2)
        self.assertEqual(self.ids(result), ['visible-change'])
        self.assertEqual(self.actor.visibility_calls, ['visible'])
        self.assertEqual(self.actor.sanitizer_calls, ['visible-change'])
        self.assertEqual(result['changes'][0]['detail'], 'sanitizer-observer:visible-change')
        self.assertEqual(self.conn.execute("SELECT detail FROM memory_changes WHERE id='visible-change'").fetchone()[0],
                         'original synthetic detail')


class SourceResult(unittest.TestResult):
    """Existing correction04/manual-index reporting pattern, no linecache I/O."""
    def __init__(self):
        super().__init__()
        self.cases = []
        self.events = []

    def startTest(self, test):
        super().startTest(test)
        self.events.append({'id': test._testMethodName, 'event': 'startTest'})
        observer = globals().get('devtools_case_started')
        if observer is not None:
            observer(test._testMethodName)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({'id': test._testMethodName, 'outcome': 'passed'})
        self.events.append({'id': test._testMethodName, 'event': 'addSuccess-after-cleanup'})

    def record(self, test, err, outcome):
        self.cases.append({'id': test._testMethodName, 'outcome': outcome})
        self.events.append({'id': test._testMethodName, 'event': outcome})
        # Exception metadata only, not traceback/source lookup under audit.
        frames = []
        tb = err[2]
        while tb is not None and len(frames) < 8:
            frames.append([tb.tb_frame.f_code.co_name, tb.tb_lineno])
            tb = tb.tb_next
        print(json.dumps({'case': test.id(), 'exception': type(err[1]).__name__,
                          'message': str(err[1])[:1000], 'frames': frames}), file=sys.stderr)

    def addFailure(self, test, err):
        self.failures.append((test, 'assertion'))
        self.record(test, err, 'failed')

    def addError(self, test, err):
        self.errors.append((test, 'fixture'))
        self.record(test, err, 'error')

    def addSkip(self, test, reason):
        self.skipped.append((test, reason))
        self.cases.append({'id': test._testMethodName, 'outcome': 'skipped'})
        self.events.append({'id': test._testMethodName, 'event': 'addSkip'})

    def stopTest(self, test):
        super().stopTest(test)
        self.events.append({'id': test._testMethodName, 'event': 'stopTest'})


if __name__ == '__main__':
    result = SourceResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(RecentChangesVisibilitySource).run(result)
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'cases': result.cases,
                      'unittest_events': result.events, 'observations': OBSERVATIONS}, separators=(',', ':')))
    raise SystemExit(0 if result.wasSuccessful() else 1)
