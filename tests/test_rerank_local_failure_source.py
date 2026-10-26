"""SEM-F03 PREPARED / NOT_RUN. Explicit SOURCE factory; inert collection.

Reuse AU05's exact fixture/codec/owning rerank loop and SEM-F01's synthetic
stdlib transport selection seams. The actual selected urlopen_no_redirect body
owns the final callback. No plugin import, real HTTP, SQLite, SDK or native
execution is permitted by this file. Inherited historical cases are NOT selected
or silently rewritten; only the literal new roster belongs to this suite.
"""
from __future__ import annotations

import __future__
import contextvars
from contextlib import contextmanager
import hashlib
import http.client
import io
import ipaddress
import json
import math
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
    'test_F03_lone_surrogate_query_local_once_no_circuit',
    'test_F03_lone_surrogate_document_local_once_no_retry',
    'test_F03_request_construction_fault_preserves_original_args',
    'test_F03_opener_preparation_fault_is_local',
    'test_F03_route_and_final_admission_failures_are_local',
    'test_F03_disabled_broken_observation_preserves_effect_classification',
    'test_F03_normal_cyrillic_payload_and_rank_styles',
    'test_F03_genuine_transport_retry_success_unknown_usage',
    'test_F03_genuine_exhaustion_circuit_and_next_healthy',
    'test_F03_http_status_cleanup_retry_policy',
    'test_F03_invalid_remote_response_still_provider_failure',
    'test_F03_cancel_after_response_local_discard_no_circuit',
    'test_F03_cache_and_disclosure_late_fences',
    'test_F03_optional_usage_unknown_zero_and_independent_fields',
    'test_F03_fatal_identity_and_diagnostic_precedence',
    'test_F03_local_status_foreign_profile_and_generation',
    'test_F03_remote_then_local_retry_preparation_stops_once',
    'test_F03_late_receipt_error_no_double_accounting',
    'test_F03_content_and_secret_gates_unchanged',
)


class RerankLocalFailureCases:
    __test__ = False

    def fresh(self):
        super().fresh()  # Exact pre-existing AU05 fixture, not a new SDK/SQL wrapper.
        self.injected = False
        self.collector = 'enabled'
        self.after_prepare = None
        self.boundary_events, self.handlers = [], []
        self.original_transport = object()
        self.request_module = TransportModule(self)
        self.ns['urllib'] = types.SimpleNamespace(request=self.request_module, parse=urllib.parse, error=urllib.error)
        self.ns['ipaddress'] = ipaddress
        self.ns['_ORIGINAL_URLOPEN'] = self.original_transport
        self.ns['RERANK_RETRY_COUNT'] = 3  # Synthetic loop control; shipped retry policy is unchanged.

    def adapter(self, request, *, timeout, _before_dispatch=None):
        # Use the EXACT lower owner, not a lambda/contextmanager that skips its gate.
        return self.ns['urlopen_no_redirect'](request, timeout=timeout, _before_dispatch=_before_dispatch)

    def lower(self, request, *, timeout):
        return _AU05_BASE.adapter(self, request, timeout=timeout)  # Existing BytesIO reply seam only.

    def counts(self, requests, successes, failures, attempts):
        self.assertEqual([self.state['stats'][k] for k in ('requests', 'successes', 'failures')],
                         [requests, successes, failures])
        self.assertEqual(len(self.dispatches), attempts)
        if self.collector == 'enabled':
            self.assertEqual(sum(row['http_issued'] for row in self.work['http']), attempts)

    def local(self, *, attempts=0, requests=1):
        self.counts(requests, 0, 0, attempts)
        self.assertEqual(self.state['stats']['local_failures'], requests)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['circuit_until'], 0.0)
        self.assertEqual(self.state['cache'], {})
        self.assertIsNone(self.state['stats']['search_units'])
        self.assertIsNone(self.state['stats']['cost_usd'])
        self.assertEqual(self.clock.sleeps, [])

    def observation(self, mode):
        self.collector = mode
        if mode == 'disabled':
            self.ns['_HYBRID_WORK'].set(None)
        elif mode == 'broken':
            self.work['lock'] = None  # Run real best-effort collector's error branch.

    def test_F03_lone_surrogate_query_local_once_no_circuit(self):
        self.query = 'Почему локальный запрос содержит суррогат? \ud800'
        for index in range(4):
            before_rows = [dict(row) for row in self.rows]
            self.assertEqual(self.call(), before_rows)
            self.assertEqual(self.rows, before_rows)
            self.local(requests=index + 1)
            self.assertEqual(self.state['stats']['last_error'], 'UnicodeEncodeError')
        self.assertEqual(self.routes, [])
        self.query = 'Как ранжировать обычные русские наблюдения?'
        self.ordered(self.call())
        self.counts(5, 1, 0, 1)
        self.assertEqual(self.state['stats']['local_failures'], 4)
        self.usage(None, None)

    def test_F03_lone_surrogate_document_local_once_no_retry(self):
        self.rows[1]['claim'] += ' \udfff'
        self.assertEqual(self.call(), self.rows)
        self.local()
        self.assertEqual(self.routes, [])
        self.assertEqual(self.handlers, [])

    def test_F03_request_construction_fault_preserves_original_args(self):
        seen = []
        class LocalRequestError(urllib.request.Request):
            def __init__(_request, url, data=None, headers=None, method=None):
                seen.append((url, data, dict(headers), method))
                raise ValueError('synthetic local Request fault')
        self.request_module.Request = LocalRequestError
        self.assertEqual(self.call(), self.rows)
        self.local()
        self.assertEqual(len(seen), 1)
        url, data, headers, method = seen[0]
        payload = json.loads(data)
        self.assertEqual(url, self.settings['RERANK_URL'])
        self.assertEqual(payload['query'], self.query)
        self.assertEqual(len(payload['documents']), 3)
        self.assertEqual(headers['Authorization'], 'Bearer synthetic-not-a-credential')
        self.assertEqual(method, 'POST')
        self.assertEqual(self.routes, [])

    def test_F03_opener_preparation_fault_is_local(self):
        for error in (OSError, ValueError):
            self.fresh()
            def fail():
                raise error('synthetic opener construction fault')
            self.after_prepare = fail
            self.assertEqual(self.call(), self.rows)
            self.local()
            self.assertEqual(len(self.handlers), 1)
            self.assertFalse(self.work['http'][0]['http_issued'])

    def test_F03_route_and_final_admission_failures_are_local(self):
        for injected in (False, True):
            for fault in ('route', 'owner', 'cancel', 'deadline'):
                self.fresh()
                self.injected = injected
                event = threading.Event()
                self.ns['_PREFETCH_LOCAL'].cancel_event = event
                self.ns['_PREFETCH_LOCAL'].deadline = 102.0
                valid = [True]
                self.ns['_PREFETCH_LOCAL'].health_owner = lambda: valid[0]
                def revoke():
                    if fault == 'route':
                        raise OSError('synthetic route preparation fault')
                    if fault == 'owner':
                        valid[0] = False
                    elif fault == 'cancel':
                        event.set()
                    else:
                        self.clock.now = 102.0
                if fault == 'route':
                    self.before_route = revoke
                else:
                    self.after_prepare = revoke
                self.assertEqual(self.call(), self.rows)
                self.local()

    def test_F03_disabled_broken_observation_preserves_effect_classification(self):
        for mode in ('disabled', 'broken'):
            for injected in (False, True):
                self.fresh()
                self.injected = injected
                self.observation(mode)
                self.query += ' \ud800'
                self.assertEqual(self.call(), self.rows)
                self.local()
                self.fresh()
                self.injected = injected
                self.observation(mode)
                self.ns['RERANK_RETRY_COUNT'] = 1
                self.actions = [OSError('genuine admitted synthetic lower failure')]
                self.assertEqual(self.call(), self.rows)
                self.counts(1, 0, 1, 1)
                self.assertEqual(self.state['stats']['local_failures'], 0)
                self.assertEqual(self.state['failure_count'], 1)
                self.assertEqual(self.clock.sleeps, [])

    def test_F03_normal_cyrillic_payload_and_rank_styles(self):
        for style in ('openrouter', 'voyage'):
            self.fresh()
            self.settings.update(RERANK_API_STYLE=style, RERANK_MODEL='voyageai/synthetic-model')
            self.query = 'Почему порядок русских наблюдений должен сохраниться?'
            self.rows[1]['claim'] = 'Обычное кириллическое наблюдение: ёж, память и порядок.'
            original = [dict(row) for row in self.rows]
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.assertEqual(self.state['stats']['local_failures'], 0)
            payload = self.dispatches[0]['payload']
            self.assertEqual(payload['query'], self.query)
            self.assertIn(self.rows[1]['claim'], payload['documents'][1])
            self.assertEqual(payload.get('top_k' if style == 'voyage' else 'top_n'), 3)
            self.assertEqual(self.rows, original)
            self.usage(2, .125)

    def test_F03_genuine_transport_retry_success_unknown_usage(self):
        for injected in (False, True):
            self.fresh()
            self.injected = injected
            self.ns['RERANK_RETRY_COUNT'] = 2
            self.actions = [OSError('synthetic admitted lower failure'), self.body()]
            self.ordered(self.call())
            self.counts(1, 1, 0, 2)
            self.usage(None, None)
            self.assertEqual(self.state['stats']['local_failures'], 0)
            self.assertEqual(self.state['failure_count'], 0)
            self.assertEqual(self.clock.sleeps, [.5])

    def test_F03_genuine_exhaustion_circuit_and_next_healthy(self):
        self.ns['RERANK_RETRY_COUNT'] = 2
        self.actions = [OSError('one'), OSError('two'), OSError('three'), OSError('four')]
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 1, 2)
        self.assertEqual(self.state['failure_count'], 1)
        self.assertEqual(self.call(), self.rows)
        self.counts(2, 0, 2, 4)
        self.assertGreater(self.state['circuit_until'], self.clock.now)
        self.assertEqual(self.call(), self.rows)
        self.counts(2, 0, 2, 4)
        self.assertEqual(self.state['skip_reasons']['circuit_open'], 1)
        self.assertEqual(self.state['stats']['local_failures'], 0)
        self.clock.now += 31
        self.ordered(self.call())
        self.counts(3, 1, 2, 5)
        self.usage(None, None)

    def test_F03_http_status_cleanup_retry_policy(self):
        for code, limit, attempts, successes, failures in ((400, 3, 1, 0, 1), (503, 1, 1, 0, 1), (503, 2, 2, 1, 0)):
            self.fresh()
            self.ns['RERANK_RETRY_COUNT'] = limit
            error = urllib.error.HTTPError('https://synthetic.invalid', code, 'authored', {}, io.BytesIO(b''))
            self.actions = [error, self.body()]
            out = self.call()
            if successes:
                self.ordered(out)
            else:
                self.assertEqual(out, self.rows)
            self.counts(1, successes, failures, attempts)
            self.assertEqual(self.closes, [(code, 'rerank')])
            self.assertEqual(self.state['stats']['local_failures'], 0)
            self.assertEqual(len(self.clock.sleeps), attempts - 1)

    def test_F03_invalid_remote_response_still_provider_failure(self):
        for results in (None, [], {}, ['invalid'], [{'index': True, 'relevance_score': .5}],
                        [{'index': 0, 'relevance_score': True}],
                        [{'index': 0, 'relevance_score': float('nan')}],
                        [{'index': 0, 'relevance_score': .5}] * 3):
            self.fresh()
            body = self.body()
            body['results'] = results
            self.actions = [body]
            self.assertEqual(self.call(), self.rows)
            self.counts(1, 0, 1, 1)
            self.assertEqual(self.state['stats']['local_failures'], 0)
            self.assertEqual(self.state['failure_count'], 1)
            self.assertFalse(self.work['http'][0]['response_valid'])
            self.assertEqual(self.clock.sleeps, [])
            self.usage(2, .125)

    def test_F03_cancel_after_response_local_discard_no_circuit(self):
        for fault in ('cancel', 'deadline', 'owner'):
            self.fresh()
            event = threading.Event()
            self.ns['_PREFETCH_LOCAL'].cancel_event = event
            self.ns['_PREFETCH_LOCAL'].deadline = 102.0
            valid = [True]
            self.ns['_PREFETCH_LOCAL'].health_owner = lambda: valid[0]
            def revoke():
                if fault == 'cancel':
                    event.set()
                elif fault == 'deadline':
                    self.clock.now = 102.0
                else:
                    valid[0] = False
            self.after_response = revoke
            self.assertEqual(self.call(), self.rows)
            self.local(attempts=1)
            self.assertIsNone(self.work['http'][0]['response_valid'])

    def test_F03_cache_and_disclosure_late_fences(self):
        self.settings['RERANK_CACHE_TTL'] = 60
        self.actions = [self.body('missing')]
        self.ordered(self.call())
        self.ordered(self.call())
        self.counts(1, 1, 0, 1)
        self.assertEqual(self.state['stats']['cache_hits'], 1)
        self.usage(None, None)
        for phase in ('initial', 'prepare', 'response', 'cache'):
            self.fresh()
            self.settings['RERANK_CACHE_TTL'] = 60
            fence = Disclosure(self.actor)
            if phase == 'initial':
                fence.valid = False
                with self.assertRaises(self.ns['_SemanticIOError']):
                    self.call(disclosure=fence)
                self.counts(0, 0, 0, 0)
                continue
            def revoke():
                fence.valid = False
            if phase == 'prepare':
                self.after_prepare = revoke
            elif phase == 'response':
                self.after_response = revoke
            else:
                def receipt(_stage, status, _reason):
                    if status == 'executed':
                        fence.valid = False
                self.receipt_hook = receipt
            self.assertEqual(self.call(disclosure=fence), [])
            self.counts(int(phase != 'prepare'), int(phase == 'cache'), 0, int(phase != 'prepare'))
            self.assertEqual(self.state['cache'], {})
            self.assertFalse(fence.ok)
            self.assertEqual(self.state['stats']['local_failures'], 0)  # Existing disclosure skip is sole local owner.
            self.assertEqual(self.state['skip_reasons']['document_disclosure_changed'], 1)
            self.assertEqual(self.clock.sleeps, [])

    def test_F03_optional_usage_unknown_zero_and_independent_fields(self):
        for usage, units, cost in (('missing', None, None), ([], None, None), (None, None, None),
                                    ({'search_units': True, 'cost': .125}, None, .125),
                                    ({'search_units': 2, 'cost': 'bad'}, 2, None),
                                    ({'search_units': 0, 'cost': 0.0}, 0, 0.0)):
            self.fresh()
            self.actions = [self.body(usage)]
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.assertEqual(self.state['stats']['local_failures'], 0)
            self.usage(units, cost)
            self.assertTrue(self.work['http'][0]['response_valid'])

    def test_F03_fatal_identity_and_diagnostic_precedence(self):
        for phase in ('serialize', 'prepare', 'lower', 'receipt'):
            self.fresh()
            primary = Fatal('synthetic primary')
            def fail(*_a, **_k):
                raise primary
            if phase == 'serialize':
                self.ns['_semantic_request_bytes'] = fail
            elif phase == 'prepare':
                self.after_prepare = fail
            elif phase == 'lower':
                self.actions = [primary]
            else:
                self.settings['RERANK_CACHE_TTL'] = 60
                fence = Disclosure(self.actor)
                def receipt(_stage, status, _reason):
                    if status == 'executed':
                        raise primary
                    if status == 'skipped':
                        raise Fatal('synthetic secondary diagnostic')
                self.receipt_hook = receipt
            def finish(*_a):
                raise RuntimeError('synthetic optional observer')
            if phase != 'receipt':
                self.ns['_hybrid_http_finish'] = finish
            with self.assertRaises(Fatal) as caught:
                self.call(disclosure=fence if phase == 'receipt' else None)
            self.assertIs(caught.exception, primary)
            self.assertEqual(len(self.dispatches), int(phase in ('lower', 'receipt')))
            self.assertEqual(self.state['stats']['failures'], 0)
            self.assertEqual(self.state['stats']['local_failures'], 0)
            self.assertEqual(self.state['failure_count'], 0)
            self.assertEqual(self.state['cache'], {})

    def test_F03_local_status_foreign_profile_and_generation(self):
        self.query += ' \ud800'
        self.assertEqual(self.call(), self.rows)
        self.local()
        status = self.actor._rerank_status()
        self.assertEqual(status['local_failures'], 1)
        status['local_failures'] = 999
        self.assertEqual(self.state['stats']['local_failures'], 1)
        json.dumps(status, allow_nan=False)
        original = self.state
        self.profile = Profile('synthetic-foreign')
        foreign = self.ns['_rerank_scope_state'](self.settings)
        self.assertIsNot(foreign, original)
        self.assertEqual(foreign['stats']['local_failures'], 0)
        self.assertEqual(foreign['stats']['failures'], 0)
        self.profile = Profile('synthetic-import-owner')
        self.drift()
        self.assertEqual(self.call(), self.rows)  # Existing new-generation circuit is not reset by local input.
        self.assertEqual(self.state['circuit_until'], 117.0)
        self.assertEqual(self.state['stats']['local_failures'], 1)

    def test_F03_remote_then_local_retry_preparation_stops_once(self):
        seen = []
        class SecondRequestFails(urllib.request.Request):
            def __init__(request, *args, **kwargs):
                seen.append((args, dict(kwargs)))
                if len(seen) == 2:
                    raise ValueError('synthetic local second preparation')
                super().__init__(*args, **kwargs)
        self.request_module.Request = SecondRequestFails
        self.actions = [OSError('synthetic first admitted attempt')]
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 0, 1)
        self.assertEqual(self.state['stats']['local_failures'], 1)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(self.clock.sleeps, [.5])
        self.usage(None, None)

    def test_F03_late_receipt_error_no_double_accounting(self):
        def fail(_stage, status, _reason):
            if status == 'executed':
                raise RuntimeError('synthetic optional receipt')
        self.receipt_hook = fail
        self.assertEqual(self.call(), self.rows)  # Preserve historical fallback, not fabricated success.
        self.counts(1, 1, 0, 1)
        self.assertEqual(self.state['stats']['local_failures'], 0)
        self.assertEqual(self.state['failure_count'], 0)
        self.usage(2, .125)

    def test_F03_content_and_secret_gates_unchanged(self):
        self.rows[1]['deny'] = True
        self.assertEqual([row['id'] for row in self.call()], ['c', 'a'])
        self.assertEqual(len(self.dispatches[0]['payload']['documents']), 2)
        self.counts(1, 1, 0, 1)
        self.fresh()
        self.query += ' SYNTHETIC_SECRET'
        self.assertEqual(self.call(), self.rows)
        self.counts(0, 0, 0, 0)
        self.assertEqual(self.state['skip_reasons']['secret_query'], 1)


def build_suite():
    # Loading this inert test-support module is behind the original bootstrap
    # fence. Product spans execute only after its own SQL-denying setup.
    if 'devtools_read_bound' not in globals() or 'DEVTOOLS_INPUTS' not in globals():
        raise RuntimeError('original finite SOURCE admission required')
    path = DEVTOOLS_INPUTS['test_semantic_final_opener_admission_source.py']
    common = dict(globals(), __name__='sem_f01_support', __file__=path)
    exec(compile(devtools_read_bound(path), path, 'exec', dont_inherit=True), common)
    packet = common['load_packet']()
    common['SOURCE_CARRIER'] = packet
    global _AU05_BASE, TransportModule, Profile, Disclosure, Fatal, SOURCE_COMMON
    SOURCE_COMMON = common
    _AU05_BASE = common['RerankUsageAccountingSource']
    TransportModule = common['TransportModule']
    Profile, Disclosure, Fatal = (common[name] for name in ('Profile', 'Disclosure', 'Fatal'))
    bound = type('RerankLocalFailureSource', (RerankLocalFailureCases, _AU05_BASE), {'__test__': False})
    return unittest.TestSuite(bound(name) for name in CASE_IDS)


def main():
    suite = build_suite()
    result = SOURCE_COMMON['SourceResult']()
    suite.run(result)
    sql = SOURCE_COMMON['SQL_CONNECT_ATTEMPTS']
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'cases': result.cases,
        'unittest_events': result.events, 'sqlite_connect_attempts': sql,
        'qualification': 'selected SOURCE; exact rerank/codec/lower-owner; synthetic replies/guards, no real HTTP/SQL/SDK/native'},
        separators=(',', ':'), allow_nan=False))
    raise SystemExit(0 if result.wasSuccessful() and sql == 0 else 1)


if __name__ == '__main__':
    main()
