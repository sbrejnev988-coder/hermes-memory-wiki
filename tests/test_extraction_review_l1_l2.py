"""L1/L2 contracts against real native modules; all inputs and transport are offline."""
from pathlib import Path
import importlib.util
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = 'mw_l1_l2_extractor_test'
    spec = importlib.util.spec_from_file_location(name, ROOT / 'extractor.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _configure(home, provider):
    import hermes_yaml
    home.mkdir(parents=True, exist_ok=True)
    model = 'gpt-6-luna' if provider == 'openai-codex' else 'xiaomi/mimo-v2.6-flash'
    section = dict(enabled=True, provider=provider, model=model, timeout=3,
                   max_tokens=900, reasoning_effort='low')
    # JSON is valid YAML, consumed by the actual Hermes parser in production.
    payload = {'plugins': {'entries': {'memory-wiki': {'settings': {'extraction': section}}}}}
    (home / 'config.yaml').write_text(json.dumps(payload), encoding='utf-8')
    assert hermes_yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8')) == payload
    return home


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('provider', ['openai-codex', 'openrouter'])
@pytest.mark.parametrize('fault', ['helper_absent', 'dependency_missing', 'runtime_fault'])
@pytest.mark.parametrize('with_yaml', [False, True])
def test_unproven_launch_preserves_owner_yaml_but_denies_ambient_legacy(
        tmp_path, monkeypatch, explicit, provider, fault, with_yaml):
    import hermes_constants as core
    module = _load()
    own = tmp_path / 'owner'
    own.mkdir()
    if with_yaml:
        _configure(own, provider)
    # Launch equals owner: otherwise legacy could be denied merely by a mismatch.
    monkeypatch.setenv('HERMES_HOME', str(own))
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('MW_EXTRACTION_API_KEY', 'synthetic-ambient-extraction-key')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-openrouter-key')
    if fault == 'helper_absent':
        monkeypatch.delattr(core, 'get_routing_process_hermes_home')
    else:
        def broken():
            if fault == 'dependency_missing':
                raise ModuleNotFoundError('synthetic helper dependency', name='synthetic_optional_dependency')
            raise RuntimeError('synthetic launch identity fault')
        monkeypatch.setattr(core, 'get_routing_process_hermes_home', broken)
    token = core.set_hermes_home_override(own)
    try:
        settings = module.read_extraction_settings(own) if explicit else module.read_extraction_settings()
        assert settings.home == own.resolve()
        assert settings.enabled is with_yaml, 'Optional launch discovery must not disable valid owner YAML'
        assert settings.provider == (provider if with_yaml else 'openai-codex')
        assert not settings.api_key and not settings.endpoint
        if with_yaml:
            assert not settings.error
            assert settings.model == ('gpt-6-luna' if provider == 'openai-codex' else 'xiaomi/mimo-v2.6-flash')
    finally:
        core.reset_hermes_home_override(token)


def _tokens(label):
    import base64
    import time
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    access = part({'alg': 'none'}) + '.' + part({
        'sub': 'synthetic-l1l2-' + label, 'exp': time.time() + 7200,
    }) + '.synthetic'
    return {'access_token': access, 'refresh_token': 'synthetic-refresh-' + label}


@pytest.mark.parametrize('mode', ['blocked_exact', 'blocked_then_healthy', 'other_model', 'expired'])
@pytest.mark.parametrize('bench', ['rate_limit', 'model_entitlement'])
def test_native_model_cooldown_controls_read_only_exact_model_selection(tmp_path, monkeypatch, mode, bench):
    import os
    import time
    import httpx
    import openai
    import hermes_constants as constants
    from agent import auxiliary_client, credential_pool, secret_scope
    from agent.credential_pool import PooledCredential
    from agent.credential_pool_model_cooldowns import model_cooldown_until, MODEL_ENTITLEMENT_BENCH_SECONDS
    from hermes_cli import auth, auth_codex
    module = _load()
    own = _configure(tmp_path / 'owner', 'openai-codex')
    first, second = _tokens('first'), _tokens('second')
    model = 'gpt-other-model' if mode == 'other_model' else 'gpt-6-luna'
    duration = MODEL_ENTITLEMENT_BENCH_SECONDS if bench == 'model_entitlement' else 7200
    until = time.time() - 10 if mode == 'expired' else time.time() + duration
    row = PooledCredential.from_dict('openai-codex', dict(
        first, id='synthetic-first', auth_type='oauth', source='manual:device_code',
        last_status='ok', model_cooldowns={model: until}))
    native_blocked = model_cooldown_until(row, 'gpt-6-luna') is not None
    rows = [row.to_dict()]
    assert rows[0]['last_status'] == 'ok' and rows[0]['model_cooldowns'] == {model: until}
    if mode == 'blocked_then_healthy':
        rows.append(PooledCredential.from_dict('openai-codex', dict(
            second, id='synthetic-second', auth_type='oauth', source='manual:device_code',
            last_status='ok')).to_dict())
    # A healthy singleton mirror cannot revive an authoritative blocked pool.
    payload = {'credential_pool': {'openai-codex': rows},
               'providers': {'openai-codex': {'auth_mode': 'chatgpt', 'tokens': second}}}
    path = own / 'auth.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    before = path.read_bytes()
    calls, clients = [], []

    def forbidden(*args, **kwargs):
        pytest.fail('grant selection must not resolve/heal/refresh/probe/persist or use legacy HTTP')

    monkeypatch.setattr(auxiliary_client, 'resolve_provider_client', forbidden)
    monkeypatch.setattr(credential_pool, 'load_pool', forbidden)
    monkeypatch.setattr(credential_pool.CredentialPool, '_persist', forbidden)
    monkeypatch.setattr(auth, 'resolve_codex_runtime_credentials', forbidden)
    monkeypatch.setattr(auth, 'get_codex_auth_status', forbidden)
    monkeypatch.setattr(auth_codex, '_codex_http_client', forbidden)
    monkeypatch.setattr(module, '_urlopen_no_redirect', forbidden)

    def serve(request):
        assert str(request.url) == 'https://chatgpt.com/backend-api/codex/responses'
        wire = json.loads(request.content)
        assert wire['model'] == 'gpt-6-luna' and wire['stream'] is True and wire['store'] is False
        assert not wire.get('tools')
        bearer = request.headers['Authorization']
        assert bearer in ['Bearer ' + first['access_token'], 'Bearer ' + second['access_token']]
        calls.append('first' if bearer == 'Bearer ' + first['access_token'] else 'second')
        events = [
            {'type': 'response.output_item.done', 'output_index': 0, 'item': {
                'id': 'synthetic-message', 'type': 'message', 'status': 'completed', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': '{"claims":[]}', 'annotations': []}]}},
            {'type': 'response.completed', 'response': {'id': 'synthetic-response', 'status': 'completed',
                'output': None, 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}},
        ]
        body = ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n' for event in events)
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=body.encode())

    def factory(**kwargs):
        client = httpx.Client(transport=httpx.MockTransport(serve), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(openai, 'DefaultHttpxClient', factory)
    prior_home, prior_scope = constants.get_hermes_home(), secret_scope.current_secret_scope_home()
    result = module.extract_session_claims(
        [{'role': 'user', 'content': 'Project Saffron uses an amber channel.'}],
        extraction_settings=module.read_extraction_settings(own))
    assert path.read_bytes() == before and not list(own.glob('*.lock'))
    assert all(client.is_closed for client in clients)
    assert constants.get_hermes_home() == prior_home and secret_scope.current_secret_scope_home() == prior_scope
    assert auxiliary_client._current_aux_stream_deadline() is None
    assert first['access_token'] not in str(result) and second['access_token'] not in str(result)
    evidence = os.environ.get('REVIEW_EVIDENCE_DIR')
    if evidence:
        with (Path(evidence) / 'observations.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'mode': mode, 'bench': bench, 'native_blocked': native_blocked,
                                  'mock_requests': calls, 'error': result['error'],
                                  'clients_closed': all(client.is_closed for client in clients),
                                  'auth_unchanged': path.read_bytes() == before}) + '\n')
    if mode == 'blocked_exact':
        assert native_blocked and not calls and not clients and result['error'] == 'ValueError'
    elif mode == 'blocked_then_healthy':
        assert native_blocked and calls == ['second'] and not result['error']
    else:
        assert not native_blocked and calls == ['first'] and not result['error']
