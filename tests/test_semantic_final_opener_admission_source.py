"""SEM-F01 PREPARED / NOT_RUN: exact selected SOURCE, synthetic transport only.

Collection is inert. Explicit build_suite/main require the unchanged isolated
source_bootstrap and a byte-bound semantic-selected.json carrier, constructed by
AST-only extraction from the frozen candidate. Reuse AU05 compile_span and the
shipped SourceResult; do not import the plugin, SDK or connect SQLite. These
cooperative controls are NOT native HTTP, SQL authority or an atomic wire lease.
"""
from __future__ import annotations

import __future__
import ast
import contextvars
from contextlib import contextmanager
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
import textwrap
import threading
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request

__test__ = False

CASE_IDS = (
    'test_F01_original_late_read_set_revoke',
    'test_F01_original_late_owner_revoke',
    'test_F01_original_late_cancel',
    'test_F01_original_late_deadline_and_reserve',
    'test_F01_original_healthy_numeric_clamp_and_exact_args',
    'test_F01_final_read_admission_wait_reclamps_again',
    'test_F01_injected_selection_rechecks_same_gate',
    'test_F01_original_proxy_redirect_and_route_preservation',
    'test_F01_health_models_maps_timeout_to_embedding',
    'test_F01_disabled_and_broken_collector_not_authority',
    'test_F01_row_update_error_does_not_erase_attempt',
    'test_F01_pending_primary_identity_survives_collector_fault',
    'test_F01_nonfinite_timeout_never_enters_lower',
)
SQL_CONNECT_ATTEMPTS = 0


def load_packet():
    """Only the existing bootstrap may read/compile the selected-source carrier."""
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError('original isolated source_bootstrap required')
    needed = ('DEVTOOLS_INPUTS', 'DEVTOOLS_SCRATCH', 'devtools_read_bound', 'devtools_case_started')
    if any(key not in globals() for key in needed):
        raise RuntimeError('finite SOURCE bootstrap admission required')
    inputs = DEVTOOLS_INPUTS
    required = ('source_bootstrap.py', 'semantic-selected.json',
                'test_rerank_usage_accounting_source.py', 'test_semantic_final_opener_admission_source.py')
    if not isinstance(inputs, dict) or any(key not in inputs for key in required):
        raise RuntimeError('complete bound SOURCE closure required')
    bootstrap = Path(inputs['source_bootstrap.py'])
    for fn, qualname in ((devtools_read_bound, 'main.<locals>.read_bound'),
                         (devtools_case_started, 'main.<locals>.case_started')):
        if (not isinstance(fn, types.FunctionType) or fn.__qualname__ != qualname
                or Path(fn.__code__.co_filename) != bootstrap
                or fn.__globals__.get('__file__') != str(bootstrap)
                or fn.__globals__.get('__name__') != '__main__'):
            raise RuntimeError('original source_bootstrap reader/reporter required')
    if devtools_read_bound.__globals__ is not devtools_case_started.__globals__ or 'site' in sys.modules:
        raise RuntimeError('original no-site bootstrap required')
    scratch = Path(DEVTOOLS_SCRATCH)
    if not scratch.is_absolute() or not scratch.is_dir():
        raise RuntimeError('own synthetic scratch required')
    for key in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'HERMES_HOME', 'TEMP', 'TMP', 'TMPDIR'):
        value = Path(os.environ.get(key, ''))
        if not value.is_absolute() or not value.is_relative_to(scratch):
            raise RuntimeError('sterile child environment required')

    # This hook augments, never replaces, the original bootstrap fence.
    def deny_sql(event, _args):
        global SQL_CONNECT_ATTEMPTS
        if event == 'sqlite3.connect':
            SQL_CONNECT_ATTEMPTS += 1
            raise PermissionError('SEM_SOURCE_SQL_NOT_ADMITTED')
    sys.addaudithook(deny_sql)
    support_path = inputs['test_rerank_usage_accounting_source.py']
    support_raw = devtools_read_bound(support_path)
    support_tree = ast.parse(support_raw, filename=support_path)
    selected = [n for n in support_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'compile_span']
    if len(selected) != 1:
        raise RuntimeError('existing AU05 compile_span required')
    exec(compile(ast.Module(body=selected, type_ignores=[]), support_path, 'exec',
                 flags=__future__.annotations.compiler_flag, dont_inherit=True), globals())
    packet = json.loads(devtools_read_bound(inputs['semantic-selected.json']))
    if packet.get('schema') != 'memory-stack.semantic-selected/v1':
        raise RuntimeError('reviewed selected-source carrier required')
    if packet['support_sha256'] != hashlib.sha256(support_raw).hexdigest():
        raise RuntimeError('support source binding mismatch')
    # Each span retains its original source path/line and digest. Full-source
    # extraction equality and closure are metadata preconditions, not test PASS.
    for item in packet['support']:
        compile_span(item, globals())
    compile_span(packet['reporter'], globals())
    return packet


class TransportModule:
    """Synthetic stdlib selection/preparation seams; never a network capability."""
    def __init__(self, fixture):
        self.fixture = fixture
        self.Request = urllib.request.Request
        self.ProxyHandler = urllib.request.ProxyHandler
        self.HTTPRedirectHandler = urllib.request.HTTPRedirectHandler

    @property
    def urlopen(self):
        f = self.fixture
        f.boundary_events.append('select')
        if f.injected:
            if f.after_prepare is not None:
                f.after_prepare()
            return f.lower
        return f.original_transport

    def build_opener(self, *handlers):
        f = self.fixture
        f.boundary_events.append('prepare')
        f.handlers.append(handlers)
        if f.after_prepare is not None:
            f.after_prepare()
        return types.SimpleNamespace(open=f.lower)


class SemanticFinalOpenerAdmissionSource(unittest.TestCase):
    __test__ = False

    def setUp(self):
        self.fresh()

    def fresh(self, *, injected=False, collector='enabled'):
        self.clock = Clock()
        self.injected = injected
        self.after_prepare = self.on_read = self.lower_error = None
        self.boundary_events, self.handlers, self.lower_calls, self.routes, self.receipts = [], [], [], [], []
        self.owner_valid = self.read_valid = True
        self.read_calls = 0
        self.event = threading.Event()
        self.request_module = TransportModule(self)
        self.original_transport = object()  # Identity only; never invoked.
        self.ns = {
            '__name__': 'sem_f01_selected', 'contextvars': contextvars, 'threading': threading,
            'contextmanager': contextmanager, 'time': self.clock, 'math': math, 'json': json,
            'urllib': types.SimpleNamespace(request=self.request_module, parse=urllib.parse, error=urllib.error),
            'ipaddress': ipaddress, 'PREFETCH_NETWORK_RESERVE_SECONDS': .25,
            '_hybrid_note': lambda *_a, **_k: None, '_stage_receipt': self.receipt,
            '_health_http_check': self.route,
        }
        for item in SOURCE_CARRIER['definitions']:
            if item['role'] in ('http', 'prefetch', 'observation', 'semantic-error'):
                compile_span(item, self.ns)
        self.ns['_SemanticIOError'] = self.ns['SemanticIOError']
        self.ns['_urlopen_no_redirect'] = self.ns['urlopen_no_redirect']
        self.ns['_ORIGINAL_URLOPEN'] = self.original_transport
        self.ns['_HYBRID_WORK'] = contextvars.ContextVar('f01-work', default=None)
        self.ns['_HYBRID_PURPOSE'] = contextvars.ContextVar('f01-purpose', default='request')
        self.ns['_PREFETCH_LOCAL'] = types.SimpleNamespace(deadline=102.0, cancel_event=self.event,
                                                          health_owner=self.owner)
        self.work = {'lock': threading.RLock(), 'started': self.clock.now, 'http': [],
                     'decision': False, 'truncated': False}
        if collector == 'broken':
            self.work['lock'] = None  # Actual best-effort collector faults, not a replacement guard.
        self.ns['_HYBRID_WORK'].set(None if collector == 'disabled' else self.work)
        self.request = urllib.request.Request('http://localhost.:7777/embedding?keep=1',
            data=b'{"original":"body"}', headers={'Authorization': 'Bearer synthetic', 'X-Exact': 'yes'}, method='POST')
        self.assertIs(self.ns['_observed_semantic_http'].__wrapped__.__globals__, self.ns)
        self.assertIs(self.ns['urlopen_no_redirect'].__globals__, self.ns)

    def receipt(self, stage, status, reason='', **fields):
        self.receipts.append((stage, status, reason))

    def route(self, *args):
        self.routes.append(args)

    def owner(self):
        self.boundary_events.append('owner')
        return self.owner_valid

    def read_set(self):
        self.read_calls += 1
        self.boundary_events.append('read')
        if self.on_read is not None:
            self.on_read()
        if not self.read_valid:
            raise self.ns['_SemanticIOError']('original_read_set_revoked')
        return None  # Deliberately void: must NOT be passed directly as numeric gate.

    @contextmanager
    def lower(self, request, *, timeout):
        self.boundary_events.append('lower')
        self.lower_calls.append((request, timeout))
        if self.lower_error is not None:
            raise self.lower_error
        yield object()

    def call(self, *, timeout=3.0, stage='embedding', body_error=None):
        with self.ns['_observed_semantic_http'](self.request, timeout=timeout, stage=stage,
                _before_dispatch=self.read_set) as (response, row):
            if body_error is not None:
                raise body_error
            return response, row

    def refused(self, error):
        with self.assertRaises(error):
            self.call()
        self.assertEqual(self.lower_calls, [])
        self.assertTrue(all(row['http_issued'] is False for row in self.work['http']))

    def test_F01_original_late_read_set_revoke(self):
        self.after_prepare = lambda: setattr(self, 'read_valid', False)
        self.refused(self.ns['_SemanticIOError'])
        self.assertEqual(self.read_calls, 2)
        self.assertLess(self.boundary_events.index('prepare'), len(self.boundary_events) - 1)

    def test_F01_original_late_owner_revoke(self):
        self.after_prepare = lambda: setattr(self, 'owner_valid', False)
        self.refused(self.ns['_SemanticIOError'])
        self.assertEqual(self.read_calls, 2)

    def test_F01_original_late_cancel(self):
        self.after_prepare = self.event.set
        self.refused(TimeoutError)
        self.assertTrue(self.event.is_set())

    def test_F01_original_late_deadline_and_reserve(self):
        for now in (102.0, 101.75):  # Exact expiry and exact reserved boundary.
            self.fresh()
            self.after_prepare = lambda: setattr(self.clock, 'now', now)
            self.refused(TimeoutError)

    def test_F01_original_healthy_numeric_clamp_and_exact_args(self):
        self.after_prepare = lambda: setattr(self.clock, 'now', 101.5)
        before = (self.request.full_url, self.request.data, self.request.header_items(), self.request.get_method())
        _response, row = self.call()
        self.assertEqual(len(self.lower_calls), 1)
        request, timeout = self.lower_calls[0]
        self.assertIs(request, self.request)
        self.assertIs(type(timeout), float)
        self.assertTrue(math.isfinite(timeout))
        self.assertEqual(timeout, .25)
        self.assertEqual(row['timeout_s'], .25)
        self.assertIs(row['http_issued'], True)
        self.assertEqual(self.read_calls, 2)
        self.assertEqual(before, (request.full_url, request.data, request.header_items(), request.get_method()))

    def test_F01_final_read_admission_wait_reclamps_again(self):
        def wait():
            if self.read_calls == 2:
                self.clock.now = 101.5
        self.on_read = wait
        self.call()
        self.assertEqual(self.lower_calls[0][1], .25)

    def test_F01_injected_selection_rechecks_same_gate(self):
        for fault in ('read', 'owner', 'cancel', 'deadline', 'healthy'):
            self.fresh(injected=True)
            def late():
                if fault == 'read':
                    self.read_valid = False
                elif fault == 'owner':
                    self.owner_valid = False
                elif fault == 'cancel':
                    self.event.set()
                else:
                    self.clock.now = 102.0 if fault == 'deadline' else 101.5
            self.after_prepare = late
            if fault in ('read', 'owner'):
                self.refused(self.ns['_SemanticIOError'])
            elif fault != 'healthy':
                self.refused(TimeoutError)
            else:
                self.call()
                self.assertEqual(self.lower_calls, [(self.request, .25)])
            self.assertEqual(self.handlers, [])
            self.assertEqual(self.read_calls, 2)

    def test_F01_original_proxy_redirect_and_route_preservation(self):
        for host, local in (('localhost.', True), ('127.0.0.1', True), ('[::1]', True),
                            ('remote.invalid', False), ('localhost.evil.invalid', False)):
            self.fresh()
            self.request = urllib.request.Request('http://' + host + ':7777/original', data=b'unchanged', method='POST')
            self.call()
            handlers = self.handlers[0]
            self.assertEqual(len(handlers), 2 if local else 1)
            self.assertIsInstance(handlers[0], urllib.request.HTTPRedirectHandler)
            self.assertIsNone(handlers[0].redirect_request(self.request, None, 302, '', {}, 'https://other.invalid'))
            if local:
                self.assertEqual(handlers[1].proxies, {})
            self.assertIs(self.lower_calls[0][0], self.request)
            self.assertEqual(self.routes[0], ('POST', self.request.full_url, dict(self.request.header_items()), b'unchanged'))

    def test_F01_health_models_maps_timeout_to_embedding(self):
        self.after_prepare = self.event.set
        with self.assertRaises(TimeoutError):
            self.call(stage='health_models')
        self.assertEqual(self.lower_calls, [])
        self.assertIn(('embedding', 'timeout', 'cancelled'), self.receipts)
        self.assertEqual(self.work['http'][0]['stage'], 'health_models')
        self.assertFalse(self.work['http'][0]['http_issued'])

    def test_F01_disabled_and_broken_collector_not_authority(self):
        for injected in (False, True):
            for collector in ('disabled', 'broken'):
                self.fresh(injected=injected, collector=collector)
                _response, row = self.call()
                self.assertIsNone(row)
                self.assertEqual(len(self.lower_calls), 1)
                self.fresh(injected=injected, collector=collector)
                self.after_prepare = lambda: setattr(self, 'read_valid', False)
                self.refused(self.ns['_SemanticIOError'])

    def test_F01_row_update_error_does_not_erase_attempt(self):
        class BrokenRow(dict):
            def update(self, **_fields):
                raise RuntimeError('synthetic optional metadata error')
        self.ns['_hybrid_http_start'] = lambda *_a: BrokenRow()
        self.call()
        self.assertEqual(len(self.lower_calls), 1)

    def test_F01_pending_primary_identity_survives_collector_fault(self):
        for phase in ('read', 'prepare', 'lower', 'body'):
            for diagnostic in (RuntimeError, Fatal):
                self.fresh()
                primary = Fatal('synthetic primary')
                def fail():
                    raise primary
                def finish(*_args):
                    raise diagnostic('synthetic optional collector')
                self.ns['_hybrid_http_finish'] = finish
                if phase == 'read':
                    self.on_read = fail
                elif phase == 'prepare':
                    self.after_prepare = fail
                elif phase == 'lower':
                    self.lower_error = primary
                with self.assertRaises(Fatal) as caught:
                    self.call(body_error=primary if phase == 'body' else None)
                self.assertIs(caught.exception, primary)
                self.assertEqual(len(self.lower_calls), int(phase in ('lower', 'body')))

    def test_F01_nonfinite_timeout_never_enters_lower(self):
        for timeout in (float('inf'), float('nan'), 0.0, -1.0):
            self.fresh()
            # Direct/no-budget path must also refuse a nonfinite numeric gate.
            self.ns['_PREFETCH_LOCAL'].deadline = 0.0
            with self.assertRaises(TimeoutError):
                self.call(timeout=timeout)
            self.assertEqual(self.lower_calls, [])


def build_suite():
    global SOURCE_CARRIER
    SOURCE_CARRIER = load_packet()
    return unittest.TestSuite(SemanticFinalOpenerAdmissionSource(name) for name in CASE_IDS)


def main():
    suite = build_suite()
    result = SourceResult()
    suite.run(result)
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'cases': result.cases,
        'unittest_events': result.events, 'sqlite_connect_attempts': SQL_CONNECT_ATTEMPTS,
        'qualification': 'selected SOURCE; synthetic transport/owner/read-set; no actual HTTP/SQL/SDK/native'},
        separators=(',', ':'), allow_nan=False))
    raise SystemExit(0 if result.wasSuccessful() and SQL_CONNECT_ATTEMPTS == 0 else 1)


if __name__ == '__main__':
    main()
