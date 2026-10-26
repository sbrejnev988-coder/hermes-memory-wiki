"""AU05 pure SOURCE regressions; no plugin import, SQL, SDK or actual HTTP.

Only the unchanged project harness may execute this explicit entry. The bounded
carrier contains exact selected definitions, not an oversized main binding.
Transport replies, principals, content decisions and disclosure finish are
synthetic: they prove control flow, NOT provider/ACL/native authority. Codec,
rank fusion, wrapper/cancel gates, usage observer and accounting are exact source.
The existing SourceResult reporter/compile-span recipe is reused unchanged.
"""
from __future__ import annotations
import __future__
import ast
import contextvars
from contextlib import contextmanager
import hashlib
import http.client
import io
import json
import math
import re
import sys
import textwrap
import threading
import types
import unittest
import urllib.error
import urllib.request

# Explicit SOURCE entry only; ordinary pytest must never instantiate this class.
__test__ = False

CASE_IDS = (
    'test_baseline_conditional_double_accounting_witness',
    'test_healthy_numeric_usage_and_payload_styles',
    'test_missing_and_malformed_usage_containers',
    'test_malformed_search_units_independent_of_cost',
    'test_malformed_cost_independent_of_units',
    'test_true_zero_and_numeric_bounds',
    'test_partial_unknown_stays_unknown_after_next_healthy',
    'test_known_totals_add_once',
    'test_unknown_usage_caches_valid_order_without_redispatch',
    'test_failure_before_http_is_one_helper_not_transport',
    'test_invalid_rank_matrix_is_one_failure',
    'test_transport_retry_success_has_two_attempts_one_helper',
    'test_exhausted_transport_circuit_and_next_healthy',
    'test_http_status_retry_policy_unchanged',
    'test_generation_drift_success_does_not_cache_or_reset_new_circuit',
    'test_generation_drift_failure_does_not_open_new_circuit',
    'test_disclosure_revoke_initial_and_predispatch',
    'test_disclosure_revoke_after_response_no_provider_failure',
    'test_disclosure_revoke_after_cache_identity_guard',
    'test_disclosure_revoke_on_cache_hit_no_dispatch',
    'test_content_refusal_and_secret_gate_not_bypassed',
    'test_cancel_early_and_after_response',
    'test_deadline_reclamp_and_late_response',
    'test_fatal_primary_identity_survives_optional_diagnostic_failure',
    'test_ordinary_cancellation_diagnostic_still_propagates',
    'test_next_healthy_after_fatal_and_unknown_usage',
    'test_snapshot_null_serialization_detachment_and_foreign_defaults',
    'test_late_optional_receipt_failure_cannot_count_again',
    'test_STATIC_scope_and_consumer_wiring',
    'test_STATIC_fixed_safety_wrappers',
    'test_STATIC_pytest_collection_opt_out',
)
OBSERVATIONS = {}
SQL_CONNECT_ATTEMPTS = 0


def compile_span(item, namespace):
    assert hashlib.sha256(item['source'].encode('utf-8')).hexdigest() == item['sha256']
    tree = ast.parse(textwrap.dedent(item['source']))
    assert len(tree.body) == 1
    ast.increment_lineno(tree, item['start_line'] - 1)
    exec(compile(tree, item['path'], 'exec', flags=__future__.annotations.compiler_flag,
                 dont_inherit=True), namespace)
    return namespace.get(item['name'])


class Clock:
    def __init__(self):
        self.now, self.sleeps = 100.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Profile:
    def __init__(self, name):
        self.name = name

    def resolve(self):
        return self

    def __str__(self):
        return self.name


class Fatal(BaseException):
    pass


class Disclosure:
    """Synthetic finish seam only. No SQL or real read-set authority."""
    def __init__(self, provider):
        self.provider, self.ok, self.valid, self.calls = provider, True, True, 0
        self.on_finish = None

    def finish(self):
        self.calls += 1
        if self.on_finish is not None:
            self.on_finish(self)
        return self.valid


class Response:
    """Explicit BytesIO seam supported by the ORIGINAL bounded response codec."""
    def __init__(self, body):
        raw = json.dumps(body, separators=(',', ':')).encode('utf-8')
        self.headers = {'Content-Length': str(len(raw))}
        self.fp = io.BytesIO(raw)

    def read(self, amount):
        return self.fp.read(amount)

    def close(self):
        self.fp.close()


class RerankUsageAccountingSource(unittest.TestCase):
    __test__ = False

    def setUp(self):
        self.fresh()

    def fresh(self):
        self.clock = Clock()
        self.profile = Profile('synthetic-import-owner')
        self.configuration = 'generation-A'
        self.actions, self.dispatches, self.events, self.routes, self.closes = [], [], [], [], []
        self.before_route = self.after_response = self.receipt_hook = None
        self.settings = {
            'reason': '', 'signature': 'authored-settings-v1', 'RERANK_ENABLED': True,
            'RERANK_ENDPOINT_VALID': True, 'RERANK_MODEL': 'synthetic/model',
            'RERANK_URL': 'https://synthetic.invalid/rerank', 'RERANK_API_STYLE': 'openrouter',
            'RERANK_TOP_K': 3, 'RERANK_MIN_CANDIDATES': 2, 'RERANK_TIMEOUT': 3.0,
            'RERANK_USER_QUERY_MAX_CHARS': 5000, 'RERANK_DOCUMENT_MAX_CHARS': 2600,
            'RERANK_SKIP_EXACT_TECHNICAL': True, 'RERANK_CACHE_TTL': 0,
            'RERANK_CACHE_MAX': 8, 'RERANK_CIRCUIT_FAILURES': 2, 'RERANK_CIRCUIT_SECONDS': 30,
            'RERANK_RULES_ENABLED': False, 'RERANK_RULES_POSITION': 'prepend', 'RERANK_RULES': {},
            'RERANK_WEIGHT_TECHNICAL': .45, 'RERANK_WEIGHT_SEMANTIC': .75,
            'RERANK_WEIGHT_MIXED': .60, 'OPENROUTER_TITLE': '', 'OPENROUTER_REFERER': '',
        }
        self.ns = {
            '__name__': 'au05_exact_selected_source', 'threading': threading, 'contextvars': contextvars,
            'contextmanager': contextmanager, 'time': self.clock, 'math': math,
            'json': json, 'hashlib': hashlib, 're': re, 'urllib': urllib, 'http': http, 'io': io,
            'RRF_K': 60, 'PREFETCH_NETWORK_RESERVE_SECONDS': .25,
            '_bound_profile_home': lambda: self.profile,
            '_IMPORT_HERMES_HOME': Profile('synthetic-import-owner'),
            '_profile_configuration_generation': lambda: self.configuration,
            '_rerank_settings': lambda: self.settings,
            '_rerank_api_key': lambda: 'synthetic-not-a-credential',
            '_hybrid_note': lambda *_a, **_k: None, '_debug_log': lambda *_a: None,
            'secret_scan': lambda text: {'raw_secret': 'SYNTHETIC_SECRET' in text},
            'redact_secrets': lambda text: text, 'is_ephemeral_fragment': lambda text: False,
            '_DisclosureFence': Disclosure,
        }
        for item in SOURCE_CARRIER['definitions']:
            compile_span(item, self.ns)
        self.ns['_SemanticIOError'] = self.ns['SemanticIOError']
        self.ns['_semantic_request_bytes'] = self.ns['request_bytes']
        self.ns['_semantic_response_json'] = self.ns['response_json']
        self.ns['_HYBRID_WORK'] = contextvars.ContextVar('authored-work', default=None)
        self.ns['_HYBRID_PURPOSE'] = contextvars.ContextVar('authored-purpose', default='request')
        self.work = {'lock': threading.RLock(), 'started': self.clock.now, 'http': [], 'phases': [],
                     'decision': False, 'truncated': False, 'trace_id': None}
        self.ns['_HYBRID_WORK'].set(self.work)
        self.ns.update(_stage_receipt=self.receipt, _health_http_check=self.route,
                       _urlopen_no_redirect=self.adapter, _semantic_close_http_error=self.close_http)
        product = type('SelectedRerankReceiver', (), {name: self.ns[name] for name in ('_rerank_rows', '_rerank_status')})
        self.actor = product()
        self.actor._claim_visible = lambda row: not row.get('invisible')
        self.actor._inspect_recall_item = lambda row, **_k: {'status': 'refused' if row.get('deny') else 'safe'}
        self.actor._inspect_recall_text = lambda text, **_k: {'status': 'safe', 'content': text}
        self.actor._connect = self.no_sql
        self.state = self.ns['_rerank_scope_state'](self.settings)
        self.rows = [{'id': name, 'claim': 'Authored durable observation ' + name, 'status': 'active',
                      'risk': 'low', 'visibility_scope': 'global', 'updated_at': 1} for name in ('a', 'b', 'c')]
        self.query = 'Which authored observation should be ranked first?'
        assert self.ns['_rerank_rows'].__globals__ is self.ns
        assert self.ns['_observed_semantic_http'].__wrapped__.__globals__ is self.ns

    def no_sql(self):
        raise RuntimeError('synthetic metadata reader unavailable; SQL NOT_RUN')

    def receipt(self, stage, status, reason='', **fields):
        self.events.append((stage, status, reason))
        if self.receipt_hook is not None:
            self.receipt_hook(stage, status, reason)

    def route(self, method, url, headers, data):
        self.routes.append((method, url, json.loads(data)))
        if self.before_route is not None:
            self.before_route()

    def close_http(self, exc, stage):
        self.closes.append((exc.code, stage))
        exc.close()
        return True  # Synthetic cleanup observer, not actual HTTPError I/O proof.

    @contextmanager
    def adapter(self, request, *, timeout, _before_dispatch=None):
        if _before_dispatch is not None:
            timeout = _before_dispatch()
        payload = json.loads(request.data)
        self.dispatches.append({'payload': payload, 'timeout': timeout})
        action = self.actions.pop(0) if self.actions else self.body(n=len(payload['documents']))
        if isinstance(action, BaseException):
            raise action
        response = Response(action)
        try:
            yield response
        finally:
            response.close()
            if self.after_response is not None:
                self.after_response()

    @staticmethod
    def body(usage='healthy', n=3):
        out = {'results': [{'index': i, 'relevance_score': .875 - rank * .125}
                           for rank, i in enumerate(reversed(range(n)))]}
        if usage == 'healthy':
            out['usage'] = {'search_units': 2, 'cost': .125}
        elif usage != 'missing':
            out['usage'] = usage
        return out

    def call(self, *, disclosure=None):
        return self.actor._rerank_rows(self.query, self.rows, 'semantic', _disclosure=disclosure)

    def counts(self, requests, successes, failures, attempts):
        self.assertEqual([self.state['stats'][k] for k in ('requests', 'successes', 'failures')],
                         [requests, successes, failures])
        self.assertEqual(len(self.dispatches), attempts)
        self.assertEqual(sum(r['http_issued'] for r in self.work['http']), attempts)

    def ordered(self, rows):
        self.assertEqual([row['id'] for row in rows], ['c', 'b', 'a'])
        self.assertEqual([row['rerank_rank'] for row in rows], [1, 2, 3])
        self.assertEqual([row['rerank_score'] for row in rows], [.875, .75, .625])
        self.assertEqual(len({row['_rerank_order'] for row in rows}), 1)

    def usage(self, units, cost):
        self.assertEqual(self.state['stats']['search_units'], units)
        self.assertEqual(self.state['stats']['cost_usd'], cost)
        status = self.actor._rerank_status()
        self.assertEqual(status['search_units'], units)
        self.assertEqual(status['cost_usd'], round(cost, 6) if cost is not None else None)
        json.dumps(status, allow_nan=False)

    def drift(self):
        self.configuration = 'generation-B'
        self.ns['_rerank_scope_state'](self.settings)
        self.state['failure_count'] = 1
        self.state['circuit_until'] = 117.0

    def test_baseline_conditional_double_accounting_witness(self):
        # One synthetic counterfactual, in this admitted packet, not native RED.
        baseline = dict(self.ns)
        old = compile_span(SOURCE_CARRIER['baseline_rerank'], baseline)
        self.actions = [self.body(['malformed-usage'])]
        old_result = old(self.actor, self.query, self.rows, 'semantic')
        self.assertEqual(old_result, self.rows)
        self.counts(2, 1, 1, 1)
        self.assertEqual(self.state['failure_count'], 1)
        witness = {'baseline': {'requests': 2, 'successes': 1, 'failures': 1, 'transport_seam_attempts': 1}}
        self.fresh()
        self.actions = [self.body(['malformed-usage'])]
        self.ordered(self.call())
        self.counts(1, 1, 0, 1)
        self.usage(None, None)
        witness['candidate'] = {'requests': 1, 'successes': 1, 'failures': 0, 'transport_seam_attempts': 1}
        OBSERVATIONS[self._testMethodName] = witness

    def test_healthy_numeric_usage_and_payload_styles(self):
        for style in ('openrouter', 'voyage'):
            self.fresh()
            self.settings.update(RERANK_API_STYLE=style, RERANK_MODEL='voyageai/authored-model')
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.usage(2, .125)
            payload = self.dispatches[0]['payload']
            self.assertEqual(len(payload['documents']), 3)
            self.assertEqual(payload['model'], 'authored-model' if style == 'voyage' else 'voyageai/authored-model')
            self.assertEqual(payload.get('top_k' if style == 'voyage' else 'top_n'), 3)
            self.assertIs(self.work['http'][0]['response_valid'], True)
            self.assertEqual(self.work['http'][0]['provider_search_units'], 2)
            self.assertEqual(self.work['http'][0]['provider_cost_usd'], .125)

    def test_missing_and_malformed_usage_containers(self):
        cases = ('missing', None, {}, [], ['bad'], True, False, 1, -1, 1.25, 'bad', '')
        for value in cases:
            self.fresh()
            self.actions = [self.body(value)]
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.usage(None, None)
            self.assertEqual(self.state['failure_count'], 0)
            self.assertEqual(self.state['circuit_until'], 0.0)
            self.assertIs(self.work['http'][0]['response_valid'], True)
        OBSERVATIONS[self._testMethodName] = {'authored_variants': len(cases)}

    def test_malformed_search_units_independent_of_cost(self):
        cases = (None, True, False, [], {}, '2', 'bad', 2.0, .5, -1, 10 ** 12 + 1, 10 ** 400,
                 float('nan'), float('inf'), float('-inf'))
        for value in cases:
            self.fresh()
            self.actions = [self.body({'search_units': value, 'cost': .125})]
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.usage(None, .125)
        OBSERVATIONS[self._testMethodName] = {'authored_variants': len(cases)}

    def test_malformed_cost_independent_of_units(self):
        cases = (None, True, False, [], {}, '.125', 'bad', -1, 10 ** 12 + 1, 10 ** 400,
                 float('nan'), float('inf'), float('-inf'))
        for value in cases:
            self.fresh()
            self.actions = [self.body({'search_units': 2, 'cost': value})]
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.usage(2, None)
        OBSERVATIONS[self._testMethodName] = {'authored_variants': len(cases)}

    def test_true_zero_and_numeric_bounds(self):
        for units, cost in ((0, 0), (0, 0.0), (10 ** 12, 1e12), (1, 1)):
            self.fresh()
            self.actions = [self.body({'search_units': units, 'cost': cost})]
            self.ordered(self.call())
            self.counts(1, 1, 0, 1)
            self.usage(units, cost)
            self.assertEqual(self.work['http'][0]['provider_search_units'], units)
            self.assertEqual(self.work['http'][0]['provider_cost_usd'], cost)

    def test_partial_unknown_stays_unknown_after_next_healthy(self):
        self.actions = [self.body({'cost': .125}), self.body()]
        self.ordered(self.call())
        self.usage(None, .125)
        self.ordered(self.call())
        self.counts(2, 2, 0, 2)
        self.usage(None, .25)
        self.actions = [self.body({'search_units': 2})]
        self.ordered(self.call())
        self.counts(3, 3, 0, 3)
        self.usage(None, None)
        self.assertEqual(self.state['failure_count'], 0)

    def test_known_totals_add_once(self):
        self.ordered(self.call())
        self.ordered(self.call())
        self.counts(2, 2, 0, 2)
        self.usage(4, .25)

    def test_unknown_usage_caches_valid_order_without_redispatch(self):
        self.settings['RERANK_CACHE_TTL'] = 60
        self.actions = [self.body('missing')]
        self.ordered(self.call())
        self.ordered(self.call())
        self.counts(1, 1, 0, 1)
        self.usage(None, None)
        self.assertEqual(self.state['stats']['cache_hits'], 1)
        self.assertEqual(len(self.state['cache']), 1)

    def test_failure_before_http_is_one_helper_not_transport(self):
        primary = self.ns['_SemanticIOError']('request_too_large')
        def denied(*_a, **_k):
            raise primary
        self.ns['_semantic_request_bytes'] = denied
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 0, 0)  # SEM-F03: local preparation is not provider failure.
        self.usage(None, None)
        self.assertEqual(self.state['stats']['local_failures'], 1)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['circuit_until'], 0.0)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.routes, [])

    def test_invalid_rank_matrix_is_one_failure(self):
        cases = (None, {}, [], [{'index': True, 'relevance_score': .5}],
                 [{'index': 0, 'relevance_score': True}],
                 [{'index': 0, 'relevance_score': float('nan')}],
                 [{'index': 0, 'relevance_score': .5}] * 3,
                 [{'index': 99, 'relevance_score': .5}], ['not-a-result'])
        for results in cases:
            self.fresh()
            body = self.body()
            body['results'] = results
            self.actions = [body]
            self.assertEqual(self.call(), self.rows)
            self.counts(1, 0, 1, 1)
            self.usage(2, .125)
            self.assertIs(self.work['http'][0]['response_valid'], False)
            self.assertEqual(self.state['failure_count'], 1)
            self.assertEqual(self.state['cache'], {})

    def test_transport_retry_success_has_two_attempts_one_helper(self):
        self.ns['RERANK_RETRY_COUNT'] = 2  # Synthetic loop probe; shipped policy is 1.
        self.actions = [OSError('authored-transport-fault'), self.body()]
        self.ordered(self.call())
        self.counts(1, 1, 0, 2)
        self.usage(None, None)  # Last response cannot prove earlier attempt billing.
        self.assertEqual(self.clock.sleeps, [.5])
        self.assertEqual([r['terminal'] for r in self.work['http']], ['transport_error', 'response'])
        self.assertEqual([r['physical_attempt'] for r in self.work['http']], [1, 2])
        self.assertEqual(self.state['failure_count'], 0)

    def test_exhausted_transport_circuit_and_next_healthy(self):
        self.ns['RERANK_RETRY_COUNT'] = 2  # Synthetic loop probe, not a policy change.
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
        self.clock.now += 31
        self.ordered(self.call())
        self.counts(3, 1, 2, 5)
        self.usage(None, None)
        self.assertEqual(self.state['circuit_until'], 0.0)

    def test_http_status_retry_policy_unchanged(self):
        for code, limit, attempts, successes, failures in ((400, 1, 1, 0, 1), (503, 1, 1, 0, 1), (503, 2, 2, 1, 0)):
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
            self.usage(None, None)
            self.assertEqual(self.closes, [(code, 'rerank')])
            self.assertEqual(len(self.clock.sleeps), attempts - 1)

    def test_generation_drift_success_does_not_cache_or_reset_new_circuit(self):
        self.settings['RERANK_CACHE_TTL'] = 60
        self.after_response = self.drift
        self.ordered(self.call())
        self.counts(1, 1, 0, 1)
        self.usage(2, .125)
        self.assertEqual(self.state['cache'], {})
        self.assertEqual(self.state['failure_count'], 1)
        self.assertEqual(self.state['circuit_until'], 117.0)

    def test_generation_drift_failure_does_not_open_new_circuit(self):
        self.after_response = self.drift
        self.actions = [{'results': []}]
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 1, 1)
        self.usage(None, None)
        self.assertEqual(self.state['failure_count'], 1)
        self.assertEqual(self.state['circuit_until'], 117.0)

    def test_disclosure_revoke_initial_and_predispatch(self):
        fence = Disclosure(self.actor)
        fence.valid = False
        with self.assertRaises(self.ns['_SemanticIOError']) as caught:
            self.call(disclosure=fence)
        self.assertEqual(caught.exception.code, 'document_disclosure_changed')
        self.counts(0, 0, 0, 0)
        self.fresh()
        fence = Disclosure(self.actor)
        self.before_route = lambda: setattr(fence, 'valid', False)
        self.assertEqual(self.call(disclosure=fence), [])
        self.counts(0, 0, 0, 0)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['skip_reasons']['document_disclosure_changed'], 1)

    def test_disclosure_revoke_after_response_no_provider_failure(self):
        fence = Disclosure(self.actor)
        self.after_response = lambda: setattr(fence, 'valid', False)
        self.assertEqual(self.call(disclosure=fence), [])
        self.counts(1, 0, 0, 1)
        self.usage(None, None)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['cache'], {})
        self.assertFalse(fence.ok)

    def test_disclosure_revoke_after_cache_identity_guard(self):
        for replace in (False, True):
            self.fresh()
            self.settings['RERANK_CACHE_TTL'] = 60
            fence = Disclosure(self.actor)
            replacement = (999.0, [])
            def revoke(_stage, status, _reason):
                if status == 'executed':
                    self.assertEqual(len(self.state['cache']), 1)
                    if replace:
                        key = next(iter(self.state['cache']))
                        self.state['cache'][key] = replacement
                    fence.valid = False
            self.receipt_hook = revoke
            self.actions = [self.body('missing')]
            self.assertEqual(self.call(disclosure=fence), [])
            self.counts(1, 1, 0, 1)
            self.usage(None, None)
            self.assertEqual(len(self.state['cache']), int(replace))
            if replace:
                self.assertIs(next(iter(self.state['cache'].values())), replacement)
            self.assertEqual(self.state['failure_count'], 0)

    def test_disclosure_revoke_on_cache_hit_no_dispatch(self):
        self.settings['RERANK_CACHE_TTL'] = 60
        self.ordered(self.call())
        fence = Disclosure(self.actor)
        fence.on_finish = lambda f: setattr(f, 'valid', f.calls < 2)
        with self.assertRaises(self.ns['_SemanticIOError']):
            self.call(disclosure=fence)
        self.counts(1, 1, 0, 1)
        self.assertFalse(fence.ok)

    def test_content_refusal_and_secret_gate_not_bypassed(self):
        self.rows[1]['deny'] = True
        out = self.call()
        self.assertEqual([r['id'] for r in out], ['c', 'a'])
        self.assertEqual(len(self.dispatches[0]['payload']['documents']), 2)
        self.counts(1, 1, 0, 1)
        self.fresh()
        self.query += ' SYNTHETIC_SECRET'
        self.assertEqual(self.call(), self.rows)
        self.counts(0, 0, 0, 0)
        self.assertEqual(self.state['skip_reasons']['secret_query'], 1)

    def test_cancel_early_and_after_response(self):
        event = threading.Event()
        self.ns['_PREFETCH_LOCAL'].cancel_event = event
        event.set()
        self.assertEqual(self.call(), self.rows)
        self.counts(0, 0, 0, 0)
        self.assertEqual(self.state['skip_reasons']['cancelled'], 1)
        event.clear()
        self.after_response = event.set
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 0, 1)  # SEM-F03: late cancellation is a local discard.
        self.assertEqual(self.state['stats']['local_failures'], 1)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['circuit_until'], 0.0)
        self.assertEqual(self.clock.sleeps, [])
        self.usage(None, None)
        self.assertEqual(self.state['cache'], {})
        self.assertIsNone(self.work['http'][0]['response_valid'])
        self.assertIn(('rerank', 'failed', 'cancelled'), self.events)

    def test_deadline_reclamp_and_late_response(self):
        self.ns['_PREFETCH_LOCAL'].deadline = 102.0
        self.before_route = lambda: setattr(self.clock, 'now', 101.875)
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 0, 0)  # Local final-admission refusal, no admitted attempt.
        self.assertEqual(self.state['stats']['local_failures'], 1)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['circuit_until'], 0.0)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.state['cache'], {})
        self.fresh()
        self.ns['_PREFETCH_LOCAL'].deadline = 102.0
        self.after_response = lambda: setattr(self.clock, 'now', 102.0)
        self.assertEqual(self.call(), self.rows)
        self.counts(1, 0, 0, 1)  # Admitted response discarded at the local deadline.
        self.assertEqual(self.state['stats']['local_failures'], 1)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['circuit_until'], 0.0)
        self.assertEqual(self.clock.sleeps, [])
        self.usage(None, None)
        self.assertIn(('rerank', 'failed', 'deadline'), self.events)

    def test_fatal_primary_identity_survives_optional_diagnostic_failure(self):
        for diagnostic_type in (RuntimeError, Fatal):
            self.fresh()
            self.settings['RERANK_CACHE_TTL'] = 60
            fence = Disclosure(self.actor)
            primary, secondary = Fatal('authored pending primary'), diagnostic_type('authored diagnostic')
            def fail(_stage, status, _reason):
                if status == 'executed':
                    raise primary
                if status == 'skipped':
                    raise secondary
            self.receipt_hook = fail
            self.actions = [self.body('missing')]
            with self.assertRaises(Fatal) as caught:
                self.call(disclosure=fence)
            self.assertIs(caught.exception, primary)
            self.counts(1, 1, 0, 1)
            self.usage(None, None)
            self.assertEqual(self.state['cache'], {})
            self.assertEqual(self.state['failure_count'], 0)
            self.assertEqual(self.state['skip_reasons']['document_disclosure_changed'], 1)

    def test_ordinary_cancellation_diagnostic_still_propagates(self):
        fence = Disclosure(self.actor)
        self.after_response = lambda: setattr(fence, 'valid', False)
        diagnostic = Fatal('authored ordinary cancellation diagnostic')
        def fail(_stage, status, _reason):
            if status == 'skipped':
                raise diagnostic
        self.receipt_hook = fail
        with self.assertRaises(Fatal) as caught:
            self.call(disclosure=fence)
        self.assertIs(caught.exception, diagnostic)
        self.counts(1, 0, 0, 1)
        self.assertEqual(self.state['failure_count'], 0)

    def test_next_healthy_after_fatal_and_unknown_usage(self):
        fence = Disclosure(self.actor)
        primary = Fatal('authored primary')
        def fail(_stage, status, _reason):
            if status == 'executed':
                raise primary
        self.receipt_hook = fail
        self.actions = [self.body('missing')]
        with self.assertRaises(Fatal) as caught:
            self.call(disclosure=fence)
        self.assertIs(caught.exception, primary)
        self.receipt_hook = None
        self.ordered(self.call())
        self.counts(2, 2, 0, 2)
        self.usage(None, None)
        self.assertEqual(self.state['failure_count'], 0)

    def test_snapshot_null_serialization_detachment_and_foreign_defaults(self):
        self.actions = [self.body('missing')]
        self.ordered(self.call())
        first = self.actor._rerank_status()
        self.assertIsNone(first['search_units'])
        self.assertIsNone(first['cost_usd'])
        first['skip_reasons']['disabled'] = 999
        first['requests'] = 999
        self.assertEqual(self.state['stats']['requests'], 1)
        self.assertEqual(self.state['skip_reasons']['disabled'], 0)
        original = self.state
        self.profile = Profile('synthetic-foreign')
        self.state = self.ns['_rerank_scope_state'](self.settings)
        self.assertIsNot(self.state, original)
        self.usage(0, 0)
        self.actions = [self.body('missing')]
        self.ordered(self.call())
        self.usage(None, None)
        self.profile = Profile('synthetic-import-owner')
        self.assertEqual(self.actor._rerank_status()['requests'], 1)
        self.assertIsNone(self.actor._rerank_status()['cost_usd'])
        for bad in (float('nan'), float('inf'), 'bad', True):
            original['stats']['cost_usd'] = bad
            self.assertIsNone(self.actor._rerank_status()['cost_usd'])
            json.dumps(self.actor._rerank_status(), allow_nan=False)

    def test_late_optional_receipt_failure_cannot_count_again(self):
        def fail(_stage, status, _reason):
            if status == 'executed':
                raise RuntimeError('authored optional receipt failure')
        self.receipt_hook = fail
        self.assertEqual(self.call(), self.rows)  # Preserve the existing fallback.
        self.counts(1, 1, 0, 1)
        self.usage(2, .125)
        self.assertEqual(self.state['failure_count'], 0)
        self.assertEqual(self.state['circuit_until'], 0.0)

    def test_STATIC_scope_and_consumer_wiring(self):
        # Current SEM scope; original AU05 carrier/gold remain historical.
        static = SOURCE_CARRIER['static']['sem_boundaries']
        self.assertTrue(static['outside_three_product_spans_raw_equal'])
        self.assertEqual(static['changed_product_definitions'],
                         ['_observed_semantic_http', 'assignment:_RERANK_STATS', 'MemoryWikiProvider._rerank_rows'])
        self.assertTrue(static['full_logical_tree_changed_paths_exact'])
        self.assertTrue(static['usage_consumer_AST_equal_to_SEM_baseline'])
        self.assertFalse(static['large_main_runtime_binding'])

    def test_STATIC_fixed_safety_wrappers(self):
        static = SOURCE_CARRIER['static']['sem_boundaries']
        self.assertTrue(static['lower_helpers_raw_equal'])
        self.assertTrue(static['disclosure_body_raw_equal'])
        self.assertTrue(static['retry_loop_AST_equal_to_SEM_baseline'])
        self.assertTrue(static['rank_validation_AST_equal'])
        self.assertTrue(static['predispatch_prefix_raw_equal'])
        self.assertTrue(static['semantic_io_raw_equal'])

    def test_STATIC_pytest_collection_opt_out(self):
        # AST-only proof of the ordinary collection declaration, not pytest run.
        self.assertTrue(SOURCE_CARRIER['static']['module_pytest_opt_out'])
        self.assertTrue(SOURCE_CARRIER['static']['class_pytest_opt_out'])
        self.assertTrue(SOURCE_CARRIER['static']['explicit_unittest_roster_preserved'])


def main():
    if 'devtools_read_bound' not in globals():
        raise RuntimeError('explicit unchanged h.run_source admission required')
    def deny_sql(event, _args):
        global SQL_CONNECT_ATTEMPTS
        if event == 'sqlite3.connect':
            SQL_CONNECT_ATTEMPTS += 1
            raise PermissionError('AU05_SQL_NOT_ADMITTED')
    sys.addaudithook(deny_sql)
    global SOURCE_CARRIER
    SOURCE_CARRIER = json.loads(devtools_read_bound(DEVTOOLS_INPUTS['rerank-selected.json']))
    # Original reporter runs in this same namespace, including the started hook.
    compile_span(SOURCE_CARRIER['reporter'], globals())
    suite = unittest.TestSuite(RerankUsageAccountingSource(name) for name in CASE_IDS)
    result = SourceResult()
    suite.run(result)
    report = {'schema': 'memory-stack.cases/v1', 'cases': result.cases,
              'unittest_events': result.events, 'observations': OBSERVATIONS,
              'sqlite_connect_attempts': SQL_CONNECT_ATTEMPTS,
              'qualification': 'exact extracted SOURCE + separate STATIC; synthetic responses/identity/disclosure, no real HTTP/SQL/SDK/native'}
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    raise SystemExit(0 if result.wasSuccessful() and SQL_CONNECT_ATTEMPTS == 0 else 1)


if __name__ == '__main__':
    main()
