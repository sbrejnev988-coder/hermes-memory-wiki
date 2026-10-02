"""Negative security regressions using real native imports and synthetic owner stores."""
import base64
import json
import time
from types import SimpleNamespace

import pytest

from test_session_extractor_codex import _extractor, _configure, _auth, _native

TEXT = [{'role': 'user', 'content': 'Project Aster uses a violet release channel.'}]


def _jwt(label, *, expires=None):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    claims = {'sub': 'synthetic-' + label}
    if expires is not None:
        claims['exp'] = expires
    return part({'alg': 'none'}) + '.' + part(claims) + '.synthetic'


@pytest.mark.parametrize('hazard', ['offhost_quota_probe', 'forked_root_lineage'])
def test_owner_grant_resolution_never_probes_or_mutates_auth(tmp_path, monkeypatch, hazard):
    from agent import auxiliary_client as aux
    from hermes_cli import auth_codex
    module = _extractor()
    own = _configure(tmp_path / 'own')
    root = _configure(tmp_path / 'root')
    _auth(own)
    _auth(root, 'foreign')
    owner = json.loads((own / 'auth.json').read_text())
    foreign = json.loads((root / 'auth.json').read_text())
    exhausted = hazard == 'offhost_quota_probe'
    owner_access = _jwt('owner', expires=time.time() + 7200)
    owner['credential_pool'] = {'openai-codex': [{
        'id': 'synthetic-shared-lineage', 'source': 'manual:device_code', 'auth_type': 'oauth',
        'access_token': owner_access, 'refresh_token': 'synthetic-refresh-owner',
        'expires_at': time.time() + 7200,
        'base_url': ('https://wrong.invalid/backend-api/codex' if exhausted
                     else 'https://chatgpt.com/backend-api/codex'),
        'last_status': 'exhausted' if exhausted else 'ok',
        'last_status_at': time.time(),
        'last_error_code': 429 if exhausted else None,
        'last_error_reason': 'quota' if exhausted else None,
        'last_error_reset_at': time.time() + 3600 if exhausted else None,
    }]}
    foreign['credential_pool'] = {'openai-codex': [{
        'id': 'synthetic-distinct-root' if exhausted else 'synthetic-shared-lineage',
        'source': 'manual:device_code', 'auth_type': 'oauth',
        'access_token': _jwt('foreign', expires=time.time() + 3600),
        'refresh_token': 'synthetic-refresh-foreign', 'expires_at': time.time() + 3600,
        'base_url': 'https://chatgpt.com/backend-api/codex',
    }]}
    (own / 'auth.json').write_text(json.dumps(owner), encoding='utf-8')
    (root / 'auth.json').write_text(json.dumps(foreign), encoding='utf-8')
    before = [(h / 'auth.json').read_bytes() for h in (own, root)]
    monkeypatch.setenv('HERMES_HOME', str(root))
    select = aux._select_pool_entry
    calls = _native(monkeypatch, own)
    monkeypatch.setattr(aux, '_select_pool_entry', select)  # Actual native resolver, no pool mock.
    probes = []

    class ProbeHttp:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def get(self, url, headers):
            probes.append((url, headers.get('Authorization') == 'Bearer ' + owner_access))
            return SimpleNamespace(status_code=200, json=lambda: {
                'rate_limit': {'primary_window': {'used_percent': 100}}})

    monkeypatch.setattr(auth_codex, '_codex_http_client', lambda **_kw: ProbeHttp())
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(own))
    assert probes == [], 'OAuth must never reach a pre-resolution usage probe'
    assert [(h / 'auth.json').read_bytes() for h in (own, root)] == before
    assert not list(own.glob('*.lock')) and not list(root.glob('*.lock'))
    if exhausted:
        assert not calls and not result['entries'] and result['error']
    else:
        assert len(calls) == 1 and len(result['entries']) == 1 and not result['error']
    assert owner_access not in str(result)


@pytest.mark.parametrize('mirrored', [False, True])
@pytest.mark.parametrize('explicit', [False, True])
def test_legacy_settings_follow_launch_home_not_routed_foreign_home(tmp_path, monkeypatch, mirrored, explicit):
    import hermes_constants as constants
    module = _extractor()
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(a))
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-launch-paid-key')
    monkeypatch.setattr(constants, '_PINNED_PROCESS_HERMES_HOME', str(a) if mirrored else None)
    for home in (a, b, a):
        if mirrored:
            monkeypatch.setenv('HERMES_HOME', str(home))
        token = constants.set_hermes_home_override(home)
        try:
            snapshot = module.read_extraction_settings(home) if explicit else module.read_extraction_settings()
            assert snapshot.home == home.resolve()
            assert snapshot.enabled is (home == a)
            assert snapshot.api_key == ('synthetic-launch-paid-key' if home == a else '')
        finally:
            constants.reset_hermes_home_override(token)


def test_openrouter_slow_drip_is_closed_at_deadline_without_late_acceptance(tmp_path, monkeypatch):
    import httpx
    import openai
    from test_session_extractor_codex import _candidate
    from test_session_extractor_openrouter import _or_home
    module = _extractor()
    own = _or_home(tmp_path / 'own', timeout=1)
    payload = json.dumps({'id': 'synthetic-response', 'object': 'chat.completion',
                          'created': 0, 'model': 'xiaomi/mimo-v2.6-flash',
                          'choices': [{'index': 0, 'finish_reason': 'stop',
                                       'message': {'role': 'assistant', 'content': json.dumps({'claims': [_candidate()]})}}]}).encode()
    streams, requests = [], []

    class SlowDrip(httpx.SyncByteStream):
        def __init__(self):
            self.count = 0
            self.closed = False
        def __iter__(self):
            for index in range(10):
                time.sleep(.15)  # Every read is below the SDK's read-idle timeout.
                self.count += 1
                yield payload[len(payload) * index // 10:len(payload) * (index + 1) // 10]
        def close(self):
            self.closed = True

    def serve(request):
        assert all(stream.closed for stream in streams), 'No overlapping previous request'
        assert str(request.url) == 'https://openrouter.ai/api/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer synthetic-own-or-key'
        requests.append(request)
        stream = SlowDrip()
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Type': 'application/json'}, stream=stream)

    def http_client(**kwargs):
        kwargs['transport'] = httpx.MockTransport(serve)
        kwargs['trust_env'] = False
        return httpx.Client(**kwargs)

    monkeypatch.setattr(openai, 'DefaultHttpxClient', http_client)
    for _ in range(2):
        started = time.monotonic()
        result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(own))
        elapsed = time.monotonic() - started
        assert not result['entries'] and result['error'], 'Late provider output must not be accepted'
        assert streams[-1].closed and streams[-1].count < 10
        assert elapsed < 1.4, 'Stop at the next bounded transport yield, not full response completion'
    assert len(requests) == 2  # SDK/transport retries remain off.


@pytest.mark.parametrize('pool_only', [False, True])
def test_real_native_oauth_adapter_uses_only_owner_grant_without_resolving_pool(tmp_path, monkeypatch, pool_only):
    import httpx
    import openai
    from agent import auxiliary_client, credential_pool
    from hermes_cli import auth
    from test_session_extractor_codex import _candidate
    module = _extractor()
    own = _configure(tmp_path / 'own')
    foreign = _configure(tmp_path / 'foreign')
    _auth(foreign, 'foreign')
    access = _jwt('owner', expires=time.time() + 7200)
    tokens = {'access_token': access, 'refresh_token': 'synthetic-refresh-owner'}
    data = ({'credential_pool': {'openai-codex': [dict(tokens, auth_type='oauth', last_status='ok')]}}
            if pool_only else {'providers': {'openai-codex': {'tokens': tokens, 'auth_mode': 'chatgpt'}}})
    (own / 'auth.json').write_text(json.dumps(data), encoding='utf-8')
    before = [(h / 'auth.json').read_bytes() for h in (own, foreign)]
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    seen = []

    def forbidden(*_a, **_kw):
        pytest.fail('no native auth selection/healing/refresh even for pool-only grants')

    monkeypatch.setattr(auxiliary_client, 'resolve_provider_client', forbidden)
    monkeypatch.setattr(credential_pool, 'load_pool', forbidden)
    monkeypatch.setattr(auth, 'resolve_codex_runtime_credentials', forbidden)

    def serve(request):
        assert str(request.url) == 'https://chatgpt.com/backend-api/codex/responses'
        assert request.headers['Authorization'] == 'Bearer ' + access
        assert request.headers['originator'] == 'hermes-agent'
        assert request.headers['User-Agent'].startswith('HermesAgent/')
        wire = json.loads(request.content)
        assert wire['model'] == 'gpt-6-luna' and wire['store'] is False and wire['stream'] is True
        assert not wire.get('tools') and wire['reasoning']['effort'] == 'low'
        seen.append(wire)
        events = [
            {'type': 'response.output_item.done', 'output_index': 0, 'item': {
                'id': 'synthetic-message', 'type': 'message', 'status': 'completed', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': json.dumps({'claims': [_candidate()]}), 'annotations': []}]}},
            {'type': 'response.completed', 'response': {
                'id': 'synthetic-response', 'status': 'completed', 'output': None,
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}},
        ]
        body = ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n' for event in events)
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=body.encode())

    def http_client(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(serve), **kwargs)

    monkeypatch.setattr(openai, 'DefaultHttpxClient', http_client)
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(own))
    assert not result['error'] and len(result['entries']) == 1 and len(seen) == 1
    assert result['persisted'] == 0 and access not in str(result)
    assert [(h / 'auth.json').read_bytes() for h in (own, foreign)] == before


@pytest.mark.parametrize('pool_only', [False, True])
@pytest.mark.parametrize('expiry', [None, -1, True, 'invalid', float('nan')])
def test_unusable_owner_expiry_fails_closed_without_refresh(tmp_path, monkeypatch, pool_only, expiry):
    from agent import credential_pool
    module = _extractor()
    own = _configure(tmp_path / 'own')
    access = _jwt('expired-owner', expires=expiry)
    row = {'access_token': access, 'refresh_token': 'synthetic-refresh-expired'}
    data = ({'credential_pool': {'openai-codex': [dict(row, auth_type='oauth')]}}
            if pool_only else {'providers': {'openai-codex': {'auth_mode': 'chatgpt', 'tokens': row}}})
    (own / 'auth.json').write_text(json.dumps(data), encoding='utf-8')
    before = (own / 'auth.json').read_bytes()
    calls = _native(monkeypatch, own)
    monkeypatch.setattr(credential_pool, 'load_pool', lambda *_a, **_kw: pytest.fail('refresh/heal prohibited'))
    snapshot = module.read_extraction_settings(own)
    result = module.extract_session_claims(TEXT, extraction_settings=snapshot)
    assert not calls and not result['entries'] and result['error'] == 'ValueError'
    assert (own / 'auth.json').read_bytes() == before
    assert access not in str(result) + repr(snapshot)


@pytest.mark.parametrize('boundary', [
    {'credential_pool': {'openai-codex': []}},
    {'credential_pool': {'openai-codex': []}, 'suppressed_sources': {'openai-codex': ['device_code']}},
    {'suppressed_sources': {'openai-codex': ['device_code']}},
    {'suppressed_sources': {'openai-codex': {'device_code': False}}},
    {'suppressed_sources': None},
    {'suppressed_sources': []},
    {'suppressed_sources': {'openai-codex': None}},
    {'suppressed_sources': {'openai-codex': 'device_code'}},
    {'suppressed_sources': {'openai-codex': [17]}},
    {'credential_pool': None},
    {'credential_pool': []},
    {'credential_pool': {'openai-codex': None}},
    {'credential_pool': {'openai-codex': 'invalid'}},
], ids=['empty', 'empty-suppressed', 'missing-suppressed', 'legacy-suppressed',
        'suppression-null', 'suppression-list', 'sources-null', 'sources-string',
        'sources-nonstring', 'pool-null', 'pool-list', 'rows-null', 'rows-string'])
def test_codex_authority_boundary_never_resurrects_owner_singleton(tmp_path, monkeypatch, boundary):
    from agent import auxiliary_client, credential_pool
    from hermes_cli import auth
    module = _extractor()
    own = _configure(tmp_path / 'own')
    foreign = _configure(tmp_path / 'foreign')
    _auth(foreign, 'foreign')
    tokens = {'access_token': _jwt('owner', expires=time.time() + 7200),
              'refresh_token': 'synthetic-refresh-owner'}
    data = {'providers': {'openai-codex': {'auth_mode': 'chatgpt', 'tokens': tokens}}, **boundary}
    (own / 'auth.json').write_text(json.dumps(data), encoding='utf-8')
    before = [(home / 'auth.json').read_bytes() for home in (own, foreign)]
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-paid-key')
    calls = _native(monkeypatch, own)
    def forbidden(*_a, **_kw):
        pytest.fail('auth resolve/heal/refresh/probe or paid fallback prohibited')
    monkeypatch.setattr(credential_pool, 'load_pool', forbidden)
    monkeypatch.setattr(auxiliary_client, 'resolve_provider_client', forbidden)
    monkeypatch.setattr(auth, 'resolve_codex_runtime_credentials', forbidden)
    monkeypatch.setattr(auth, 'get_codex_auth_status', forbidden)
    monkeypatch.setattr(module, '_urlopen_no_redirect', forbidden)
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(own))
    assert not calls and not result['entries'] and result['error']
    assert [(home / 'auth.json').read_bytes() for home in (own, foreign)] == before
    assert not list(own.glob('*.lock')) and not list(foreign.glob('*.lock'))
    assert tokens['access_token'] not in str(result)


@pytest.mark.parametrize('pool_shape', [
    'bad-row', 'legacy', 'empty-pool-map', 'unrelated-pool', 'device-pool', 'manual-pool',
    'manual-legacy-suppression',
])
def test_codex_native_serialization_and_precise_source_boundary(tmp_path, monkeypatch, pool_shape):
    from agent.credential_pool import PooledCredential
    module = _extractor()
    own = _configure(tmp_path / 'own')
    access = _jwt('serialized-owner', expires=time.time() + 7200)
    tokens = {'access_token': access, 'refresh_token': 'synthetic-refresh-owner'}
    data = {'providers': {'openai-codex': {'auth_mode': 'chatgpt', 'tokens': tokens}}}
    if pool_shape == 'empty-pool-map':
        data['credential_pool'] = {}
        data['suppressed_sources'] = {'openai-codex': {}}
    if pool_shape == 'unrelated-pool':
        data['credential_pool'] = {'openrouter': []}
        data['suppressed_sources'] = {'openai-codex': ['manual:device_code']}
    if pool_shape in {'bad-row', 'device-pool', 'manual-pool', 'manual-legacy-suppression'}:
        source = 'manual:device_code' if pool_shape.startswith('manual-') else 'device_code'
        row = PooledCredential.from_dict('openai-codex', dict(
            tokens, id='synthetic-serialized-owner', auth_type='oauth', source=source, last_status='ok'))
        data['credential_pool'] = {'openai-codex': [row.to_dict()]}
        if pool_shape == 'bad-row':
            data['credential_pool']['openai-codex'].append(None)
        else:
            data.pop('providers')  # Success must come from the serialized row, not a mirror.
            if pool_shape == 'manual-pool':
                # Native suppression is exact source membership, not a suffix/account match.
                data['suppressed_sources'] = {'openai-codex': ['device_code']}
            elif pool_shape == 'manual-legacy-suppression':
                data['suppressed_sources'] = {'openai-codex': {'device_code': False}}
    (own / 'auth.json').write_text(json.dumps(data), encoding='utf-8')
    before = (own / 'auth.json').read_bytes()
    calls = _native(monkeypatch, own)
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(own))
    if pool_shape == 'bad-row':
        assert not calls and not result['entries'] and result['error']
    else:
        assert len(calls) == 1 and len(result['entries']) == 1 and not result['error']
        assert calls[0][1]['model'] == 'gpt-6-luna' and calls[0][1]['store'] is False
    assert (own / 'auth.json').read_bytes() == before
    assert access not in str(result)


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('with_yaml', [False, True])
def test_older_native_core_preserves_owner_without_ambient_legacy(tmp_path, monkeypatch, explicit, with_yaml):
    import hermes_constants as core
    module = _extractor()
    launch, own = tmp_path / 'launch', tmp_path / 'own'
    launch.mkdir()
    own.mkdir()
    if with_yaml:
        _configure(own)
    monkeypatch.setenv('HERMES_HOME', str(launch))
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-launch-paid-key')
    monkeypatch.delattr(core, 'get_routing_process_hermes_home')
    token = core.set_hermes_home_override(own)
    try:
        snapshot = module.read_extraction_settings(own) if explicit else module.read_extraction_settings()
        assert snapshot.home == own.resolve()
        assert snapshot.enabled is with_yaml
        assert snapshot.provider == 'openai-codex' and not snapshot.api_key
    finally:
        core.reset_hermes_home_override(token)


@pytest.mark.parametrize('fault', ['core_dependency', 'routing_dependency', 'routing_runtime'])
def test_native_routing_faults_never_become_standalone_legacy(tmp_path, monkeypatch, fault):
    import builtins
    import hermes_constants as core
    module = _extractor()
    own = tmp_path / 'own'
    own.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(own))
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-paid-key')
    if fault == 'core_dependency':
        real_import = builtins.__import__
        def broken_import(name, *args, **kwargs):
            if name == 'hermes_constants':
                raise ModuleNotFoundError('synthetic missing core dependency', name='synthetic_dependency')
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, '__import__', broken_import)
    else:
        def broken_routing():
            if fault == 'routing_dependency':
                raise ModuleNotFoundError('synthetic missing helper dependency', name='synthetic_dependency')
            raise RuntimeError('synthetic native routing fault')
        monkeypatch.setattr(core, 'get_routing_process_hermes_home', broken_routing)
    token = core.set_hermes_home_override(own)
    try:
        snapshot = module.read_extraction_settings()
        assert not snapshot.enabled and not snapshot.api_key
        if fault != 'core_dependency':
            assert snapshot.home == own.resolve()
    finally:
        core.reset_hermes_home_override(token)


@pytest.mark.parametrize('explicit', [False, True])
def test_genuine_standalone_still_accepts_legacy_environment(tmp_path, monkeypatch, explicit):
    import builtins
    module = _extractor()
    real_import = builtins.__import__
    def without_core(name, *args, **kwargs):
        if name == 'hermes_constants':
            raise ModuleNotFoundError('No module named hermes_constants', name='hermes_constants')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_core)
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-standalone-paid-key')
    snapshot = module.read_extraction_settings(tmp_path) if explicit else module.read_extraction_settings()
    assert snapshot.home == tmp_path.resolve() and snapshot.enabled
    assert snapshot.provider == 'legacy' and snapshot.api_key == 'synthetic-standalone-paid-key'


def test_openrouter_late_headers_are_closed_before_body_acceptance(tmp_path, monkeypatch):
    import httpx
    import openai
    from test_session_extractor_openrouter import _or_home
    module = _extractor()
    own = _or_home(tmp_path / 'own', timeout=1)
    responses = []

    def serve(request):
        assert all(0 < value <= 1 for value in request.extensions['timeout'].values())
        time.sleep(1.1)  # A blocking transport cannot be preempted by a public sync hook.
        response = httpx.Response(200, json={'choices': [{'message': {'content': '{"claims":[]}'}}]})
        responses.append(response)
        return response

    def http_client(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(serve), **kwargs)

    monkeypatch.setattr(openai, 'DefaultHttpxClient', http_client)
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(own))
    assert not result['entries'] and result['error'] and len(responses) == 1
    assert responses[0].is_closed
