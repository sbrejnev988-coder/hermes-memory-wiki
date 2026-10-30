"""SOURCE tooling regressions for G1 failed-setup cleanup, not native SDK proof.

The explicit factory receives the exact, definition-only G1 module and source
bytes. Original G1 setup/provider methods are never called. ContextVar/ENV and
cleanup fault callbacks below are authored seams, never SDK substitutes.
"""
from __future__ import annotations
import ast
from contextlib import ExitStack
import contextvars
import hashlib
import os
import unittest
from unittest import mock

__test__ = False
_G1 = _RAW = _BASELINE = None
ORACLE_MIGRATION = (
    ("        self.visible('PRIVACYBOOK', a['revision_id'])\n",
     "        # Retained links to erased/missing claims must veto public disclosure.\n        # A nonempty result here would contradict the privacy fixture itself.\n        withheld = self.d.query_documents(self.p, {'query': 'PRIVACYBOOK', 'limit': 20})\n        self.assertEqual(withheld.get('disclosure'), 'withheld', withheld)\n        self.assertEqual(withheld['results'], [], withheld)\n"),
    ("        archive, retire, erase = [row['embedding_claim_id'] for row in linked]\n",
     "        # Positive visibility belongs to the healthy cohort, before erasure.\n        self.visible('PRIVACYBOOK', a['revision_id'])\n        archive, retire, erase = [row['embedding_claim_id'] for row in linked]\n"),
)
METHODS = (
    'test_keyboard_interrupt_unwinds_before_unittest_cleanup',
    'test_primary_identity_cause_and_secondary_evidence',
    'test_failed_diagnostic_note_preserves_primary',
    'test_cleanup_error_is_visible_and_not_retried',
    'test_successful_cleanup_restores_context_and_runs_once',
    'test_static_acquisition_is_inside_local_fatal_unwind',
    'test_static_original_eight_business_contracts_preserved',
)


def fixture():
    item = _G1.DocumentStateG1('test_aba_exact_identity_history_fts_and_repeat')
    item.p = None  # No provider/SQL/SDK role is instantiated or substituted.
    item.stack = ExitStack()
    item._fixture_closed = False
    item._setup_cleanup_error = None
    return item


def pending(primary, item):
    try:
        raise primary
    except BaseException as caught:
        _G1._cleanup_failed_setup(item, caught)
        raise


class CleanupCases(unittest.TestCase):
    def test_keyboard_interrupt_unwinds_before_unittest_cleanup(self):
        state = contextvars.ContextVar('owned-source-context', default='original')
        primary = KeyboardInterrupt('owned-source-primary')
        events = []
        class RunnerCase(unittest.TestCase):
            close_fixture = _G1.DocumentStateG1.close_fixture
            def setUp(inner):
                inner.p = None
                inner.stack = ExitStack()
                inner._fixture_closed = False
                inner._setup_cleanup_error = None
                inner.addCleanup(inner.close_fixture)
                try:
                    token = state.set('acquired')
                    inner.stack.callback(state.reset, token)
                    inner.stack.callback(events.append, 'cleanup')
                    raise primary
                except BaseException as caught:
                    _G1._cleanup_failed_setup(inner, caught)
                    raise
            def runTest(inner):
                raise AssertionError('fatal setup cannot enter test body')
        inner = RunnerCase()
        with self.assertRaises(KeyboardInterrupt) as raised:
            unittest.TestSuite([inner]).run(unittest.TestResult())
        self.assertIs(raised.exception, primary)
        self.assertEqual(state.get(), 'original')
        self.assertEqual(events, ['cleanup'])
        inner.doCleanups()  # Deferred unittest cleanup must not reset tokens twice.
        self.assertEqual(events, ['cleanup'])

    def test_primary_identity_cause_and_secondary_evidence(self):
        for primary_type in (ValueError, KeyboardInterrupt):
            for secondary_type in (RuntimeError, KeyboardInterrupt):
                with self.subTest(primary=primary_type.__name__, secondary=secondary_type.__name__):
                    item = fixture()
                    events = []
                    cause = LookupError('owned-original-cause')
                    primary = primary_type('owned-primary')
                    primary.__cause__ = cause
                    secondary = secondary_type('owned-cleanup')
                    def fail():
                        events.append('failure')
                        raise secondary
                    item.stack.callback(events.append, 'last')
                    item.stack.callback(fail)
                    item.stack.callback(events.append, 'first')
                    with self.assertRaises(primary_type) as raised:
                        pending(primary, item)
                    self.assertIs(raised.exception, primary)
                    self.assertIs(primary.__cause__, cause)
                    self.assertIs(item._setup_cleanup_error, secondary)
                    self.assertEqual(events, ['first', 'failure', 'last'])
                    self.assertIn(secondary_type.__name__, primary.__notes__[-1])
                    item.close_fixture()
                    self.assertEqual(events, ['first', 'failure', 'last'])

    def test_failed_diagnostic_note_preserves_primary(self):
        class BrokenNote(KeyboardInterrupt):
            def add_note(self, value):
                raise SystemExit('owned-note-failure')
        item = fixture()
        primary = BrokenNote('owned-primary')
        cause = LookupError('owned-cause')
        primary.__cause__ = cause
        secondary = RuntimeError('owned-cleanup')
        def fail():
            raise secondary
        item.stack.callback(fail)
        with self.assertRaises(BrokenNote) as raised:
            pending(primary, item)
        self.assertIs(raised.exception, primary)
        self.assertIs(primary.__cause__, cause)
        self.assertIs(item._setup_cleanup_error, secondary)

    def test_cleanup_error_is_visible_and_not_retried(self):
        item = fixture()
        secondary = KeyboardInterrupt('owned-cleanup-without-primary')
        events = []
        def fail():
            events.append('attempt')
            raise secondary
        item.stack.callback(events.append, 'drained')
        item.stack.callback(fail)
        with self.assertRaises(KeyboardInterrupt) as raised:
            item.close_fixture()
        self.assertIs(raised.exception, secondary)
        self.assertEqual(events, ['attempt', 'drained'])
        self.assertTrue(item._fixture_closed)
        item.close_fixture()
        self.assertEqual(events, ['attempt', 'drained'])

    def test_successful_cleanup_restores_context_and_runs_once(self):
        item = fixture()
        state = contextvars.ContextVar('owned-cleanup-context', default='original')
        events = []
        before = os.environ.get('G1_SOURCE_UNIT_SENTINEL')
        item.stack.enter_context(mock.patch.dict(os.environ, {'G1_SOURCE_UNIT_SENTINEL': 'owned'}))
        token = state.set('acquired')
        item.stack.callback(state.reset, token)
        item.stack.callback(events.append, 'owned-callback')
        primary = KeyboardInterrupt('owned-pending-primary')
        _G1._cleanup_failed_setup(item, primary)
        self.assertIsNone(item._setup_cleanup_error)
        self.assertEqual(state.get(), 'original')
        self.assertEqual(os.environ.get('G1_SOURCE_UNIT_SENTINEL'), before)
        self.assertEqual(events, ['owned-callback'])
        item.close_fixture()
        self.assertEqual(events, ['owned-callback'])

    def test_static_acquisition_is_inside_local_fatal_unwind(self):
        tree = ast.parse(_RAW)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DocumentStateG1')
        setup = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'setUp')
        owner = next(n for n in setup.body if isinstance(n, ast.Try))
        handler = next(h for h in owner.handlers if isinstance(h.type, ast.Name) and h.type.id == 'BaseException')
        self.assertEqual(handler.name, 'primary')
        self.assertTrue(isinstance(handler.body[-1], ast.Raise) and handler.body[-1].exc is None)
        call = handler.body[0].value
        self.assertIsInstance(call, ast.Call)
        self.assertIsInstance(call.func, ast.Name)
        self.assertEqual(call.func.id, '_cleanup_failed_setup')
        self.assertEqual([ast.unparse(a) for a in call.args], ['self', 'primary'])
        self.assertIs(_G1.DocumentStateG1.setUp.__globals__, _G1.__dict__)
        self.assertIn('_cleanup_failed_setup', _G1.__dict__)
        body = ast.Module(body=owner.body, type_ignores=[])
        called = {ast.unparse(n.func) for n in ast.walk(body) if isinstance(n, ast.Call)}
        self.assertTrue({'set_hermes_home_override', 'set_secret_scope', 'load_wiki',
                         'self.m.MemoryWikiProvider', 'self.p.initialize'} <= called)

    def test_static_original_eight_business_contracts_preserved(self):
        def bodies(raw):
            text = raw.decode('utf-8')
            tree = ast.parse(text)
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DocumentStateG1')
            return {n.name: ast.get_source_segment(text, n) for n in cls.body
                    if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')}
        original, current = bodies(_BASELINE), bodies(_RAW)
        self.assertEqual(len(original), 8)
        self.assertEqual(original.keys(), current.keys())
        target = 'test_aba_partial_embeddings_preserve_archived_retired_erased_authority'
        self.assertEqual(hashlib.sha256(original[target].encode()).hexdigest(),
                         'a40c79325aa5cc2baf08f47ec1e0bc751d6198a6927c607fb3ed74809e6805f8')
        for name in original.keys() - {target}:
            self.assertEqual(original[name], current[name], name)
        expected = original[target]
        # Approved test-oracle migration from exact 1743: not a new product
        # contract. Missing erased links deliberately require fail-closed output.
        for old, new in ORACLE_MIGRATION:
            self.assertEqual(expected.count(old), 1)
            expected = expected.replace(old, new, 1)
        self.assertEqual(current[target], expected)
        # Byte-exact inverse also protects every pre-existing privacy/ledger,
        # owner-TX, pending-count and anti-resurrection assertion in this body.
        retained = current[target]
        for old, new in reversed(ORACLE_MIGRATION):
            self.assertEqual(retained.count(new), 1)
            retained = retained.replace(new, old, 1)
        self.assertEqual(retained, original[target])


def make_suite(g1, raw, baseline):
    global _G1, _RAW, _BASELINE
    _G1, _RAW, _BASELINE = g1, raw, baseline
    assert not any(name in __import__('sys').modules for name in (
        'agent.memory_provider', 'agent.memory_manager', 'hermes_constants', 'tools.registry'))
    return unittest.TestSuite(CleanupCases(name) for name in METHODS)
