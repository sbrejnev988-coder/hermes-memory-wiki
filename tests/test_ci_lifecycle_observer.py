"""SOURCE regressions: exact observer bodies, stdlib and real temporary files.

Do not import helpers/conftest.py: its module initialization requires pytest and
Memory Wiki. Only hook decorators are omitted; the executed bodies are unedited.
This checks the observer seam, not pytest dispatch or native provider lifecycle.
"""
from __future__ import annotations

import __main__
import ast
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest


def _load_observer():
    source = Path(globals().get(
        'LIFECYCLE_OBSERVER_SOURCE',
        Path(__file__).parent / 'helpers' / 'conftest.py',
    ))
    tree = ast.parse(source.read_bytes(), filename=str(source))
    names = ('_metadata', '_emit', '_inventory',
             'pytest_runtest_protocol', 'pytest_sessionfinish')
    definitions = []
    for name in names:
        matches = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == name]
        if len(matches) != 1:
            raise AssertionError('Observer definition must be unique: ' + name)
        node = matches[0]
        node.decorator_list = []
        definitions.append(node)
    namespace = {
        '__main__': __main__, 'json': json, 'os': os, 'Path': Path,
        'stat': stat, 'sys': sys, 'time': time,
        '_OWNER_SOURCE': os.path.normcase(str(source.with_name('provider_lifecycle.py'))),
        # These filters are inert here: no provider code or SDK is executed.
        '_PROVIDER_SOURCE': os.path.normcase(str(source.parent / '__init__.py')),
        '_SHUTIL_SOURCE': os.path.normcase(str(Path(shutil.__file__).resolve())),
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]),
                 str(source), 'exec', dont_inherit=True), namespace)
    return namespace


class TestCILifecycleObserver(unittest.TestCase):
    def setUp(self):
        self.assertFalse(hasattr(__main__, '_memory_wiki_instance'),
                         'SOURCE regression requires a cold provider-free process')
        # The SOURCE controller supplies TMPDIR inside its owned scratch.
        self.temporary = tempfile.TemporaryDirectory(
            prefix='ci-lifecycle-', dir=os.environ.get('TMPDIR') or tempfile.gettempdir(),
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.events = self.root / 'not-created' / '.hermes-release' / 'lifecycle-events.jsonl'
        self.observer = _load_observer()
        self.observer['_EVENTS'] = self.events
        self.observer['_FIXTURES'] = self.root / 'fixtures'

    def rows(self):
        raw = self.events.read_text(encoding='utf-8')
        self.assertTrue(raw.endswith('\n'))
        return [json.loads(line) for line in raw.splitlines()]

    def test_emit_appends_without_truncating(self):
        self.events.parent.mkdir(parents=True)
        original = '{"event":"retained","node":"прежний"}\n'.encode('utf-8')
        self.events.write_bytes(original)
        before = time.monotonic()
        self.observer['_emit']('initialize_exception', 'new-node', error_type='RuntimeError')
        self.observer['_emit']('item_protocol_finished', 'new-node')
        after = time.monotonic()
        self.assertTrue(self.events.read_bytes().startswith(original))
        rows = self.rows()
        self.assertEqual([row['event'] for row in rows],
                         ['retained', 'initialize_exception', 'item_protocol_finished'])
        self.assertEqual(rows[0]['node'], 'прежний')
        self.assertEqual(rows[1]['error_type'], 'RuntimeError')
        for row in rows[1:]:
            self.assertEqual(row['node'], 'new-node')
            self.assertLessEqual(before, row['monotonic'])
            self.assertLessEqual(row['monotonic'], after)

    def test_emit_creates_missing_parent(self):
        self.assertFalse(self.events.parent.exists())
        self.observer['_emit']('fixture_release_return', 'owned-case', provider={'present': False})
        self.assertTrue(self.events.parent.is_dir())
        row, = self.rows()
        self.assertEqual(row['event'], 'fixture_release_return')
        self.assertEqual(row['node'], 'owned-case')
        self.assertEqual(row['provider'], {'present': False})

    def test_emit_reuses_existing_home(self):
        self.events.parent.mkdir(parents=True)
        self.assertFalse(self.events.exists())
        self.observer['_emit']('initialize_return', 'existing-home')
        row, = self.rows()
        self.assertEqual(row['event'], 'initialize_return')
        self.assertEqual(row['node'], 'existing-home')

    def test_event_path_directory_refuses(self):
        self.events.mkdir(parents=True)
        with self.assertRaises(OSError):
            self.observer['_emit']('sessionfinish', '', exit_code=2)
        self.assertTrue(self.events.is_dir())
        self.assertEqual(list(self.events.iterdir()), [])

    def test_parent_path_file_refuses(self):
        self.events.parent.parent.mkdir(parents=True)
        self.events.parent.write_bytes(b'owned collision must remain unchanged')
        with self.assertRaises(OSError):
            self.observer['_emit']('sessionfinish', '', exit_code=2)
        self.assertEqual(self.events.parent.read_bytes(), b'owned collision must remain unchanged')
        self.assertFalse(self.events.exists())

    def test_protocol_refuses_existing_trace(self):
        previous = sys.gettrace()

        def other_trace(frame, event, arg):
            return None

        sys.settrace(other_trace)
        try:
            protocol = self.observer['pytest_runtest_protocol'](
                SimpleNamespace(nodeid='conflicting-trace'), None,
            )
            with self.assertRaisesRegex(AssertionError, 'Passive observer refuses another trace'):
                next(protocol)
            self.assertIs(sys.gettrace(), other_trace)
        finally:
            sys.settrace(previous)
        self.assertFalse(self.events.parent.exists())

    def test_protocol_restores_trace_after_item_failure(self):
        self.assertIsNone(sys.gettrace())
        protocol = self.observer['pytest_runtest_protocol'](
            SimpleNamespace(nodeid='synthetic-item'), None,
        )
        primary = RuntimeError('synthetic item failure')
        try:
            self.assertIsNone(next(protocol))
            self.assertIsNotNone(sys.gettrace())
            with self.assertRaises(RuntimeError) as caught:
                protocol.throw(primary)
            self.assertIs(caught.exception, primary)
        finally:
            protocol.close()
        self.assertIsNone(sys.gettrace())
        row, = self.rows()
        self.assertEqual(row['event'], 'item_protocol_finished')
        self.assertEqual(row['node'], 'synthetic-item')

    def test_sessionfinish_before_items_preserves_collection_error(self):
        self.assertFalse(self.events.parent.exists())
        session = SimpleNamespace(testsfailed=6, exitstatus=2)
        primary = RuntimeError('synthetic original collection failure')
        with self.assertRaises(RuntimeError) as caught:
            try:
                raise primary
            finally:
                self.observer['pytest_sessionfinish'](session, session.exitstatus)
        self.assertIs(caught.exception, primary)
        self.assertEqual(vars(session), {'testsfailed': 6, 'exitstatus': 2})
        row, = self.rows()
        self.assertEqual(row['event'], 'sessionfinish')
        self.assertEqual(row['node'], '')
        self.assertEqual(row['exit_code'], 2)
        self.assertIs(type(row['exit_code']), int)
        self.assertEqual(row['provider'], {'present': False})

    def test_sessionfinish_success_without_provider(self):
        self.events.parent.mkdir(parents=True)
        session = SimpleNamespace(testsfailed=0, exitstatus=0)
        self.assertIsNone(self.observer['pytest_sessionfinish'](session, 0))
        self.assertEqual(vars(session), {'testsfailed': 0, 'exitstatus': 0})
        row, = self.rows()
        self.assertEqual(row['event'], 'sessionfinish')
        self.assertEqual(row['exit_code'], 0)
        self.assertEqual(row['provider'], {'present': False})


if __name__ == '__main__':
    unittest.main()
