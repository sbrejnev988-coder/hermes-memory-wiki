"""Explicit profile OpenRouter routing: synthetic credentials and offline SDK only."""
from types import SimpleNamespace

import pytest

from test_session_extractor_codex import ROOT, _extractor, _configure, _candidate, _auth, _native


def _or_home(home, **changes):
    home = _configure(home, provider='openrouter', model='xiaomi/mimo-v2.6-flash', **changes)
    (home / '.env').write_text('OPENROUTER_API_KEY=synthetic-own-or-key\n', encoding='utf-8')
    return home


def _sdk(monkeypatch, *, failure=False):
    import json
    import httpx
    import openai
    calls, clients = [], []
    native_client = openai.OpenAI

    def serve(request):
        assert str(request.url) == 'https://openrouter.ai/api/v1/chat/completions'
        if failure:
            raise TimeoutError('synthetic-private-provider-error')
        return httpx.Response(200, json={
            'id': 'synthetic-response', 'object': 'chat.completion', 'created': 0,
            'model': json.loads(request.content)['model'],
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': json.dumps({'claims': [_candidate()]})}}],
        })

    def http_client(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(serve), **kwargs)

    def factory(**kwargs):
        client = native_client(**kwargs)
        if kwargs['base_url'] != 'https://openrouter.ai/api/v1':
            return client  # Codex still exercises its own native adapter.
        create = client.chat.completions.create
        close = client.close
        item = {'kwargs': kwargs, 'closed': False}
        clients.append(item)

        def tracked_create(**body):
            calls.append(body)
            if failure:
                raise TimeoutError('synthetic-private-provider-error')
            return create(**body)

        def tracked_close():
            close()
            item['closed'] = client.is_closed()

        client.chat.completions.create = tracked_create
        client.close = tracked_close
        return client

    monkeypatch.setattr(openai, 'DefaultHttpxClient', http_client)
    monkeypatch.setattr(openai, 'OpenAI', factory)
    return calls, clients


TEXT = [{'role': 'user', 'content': 'Project Aster uses a violet release channel.'}]


def test_yaml_openrouter_consumed_with_exact_model_and_profile_key(tmp_path, monkeypatch):
    module = _extractor()
    home = _or_home(tmp_path / 'own')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-foreign-ambient-key')
    monkeypatch.setenv('MW_EXTRACTION_MODEL', 'foreign/alternate')
    monkeypatch.setattr(module, '_codex_content', lambda *_a: pytest.fail('cross-provider fallback'))
    calls, clients = _sdk(monkeypatch)
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(home))
    assert result['error'] == '' and len(result['entries']) == 1
    body = calls[0]
    assert body['model'] == 'xiaomi/mimo-v2.6-flash'
    assert body['max_tokens'] == 900 and body['timeout'] == 17
    assert body['response_format']['json_schema'] == module._response_schema()
    assert body['extra_body'] == {'reasoning': {'effort': 'low'}}
    assert 'tools' not in body and clients[0]['closed']
    client = clients[0]['kwargs']
    assert client['api_key'] == 'synthetic-own-or-key'
    assert client['base_url'] == 'https://openrouter.ai/api/v1'
    assert client['max_retries'] == 0 and client['http_client'].follow_redirects is False
    assert 'synthetic-own-or-key' not in str(result)


@pytest.mark.parametrize('mode', ['missing_key', 'disabled', 'provider_error'])
def test_openrouter_no_ambient_key_no_cross_provider_fallback(tmp_path, monkeypatch, mode):
    module = _extractor()
    home = _or_home(tmp_path / 'own', enabled=mode != 'disabled')
    if mode == 'missing_key':
        (home / '.env').unlink()
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-foreign-ambient-key')
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setattr(module, '_codex_content', lambda *_a: pytest.fail('cross-provider fallback'))
    monkeypatch.setattr(module, '_urlopen_no_redirect', lambda *_a, **_kw: pytest.fail('legacy fallback'))
    calls, clients = _sdk(monkeypatch, failure=mode == 'provider_error')
    result = module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(home))
    assert not result['entries']
    if mode == 'disabled':
        assert result['heuristic_only']
    else:
        assert result['error']
    assert 'synthetic-private-provider-error' not in str(result)
    if mode == 'provider_error':
        assert len(calls) == 1 and result['error'] == 'TimeoutError' and clients[0]['closed']
    else:
        assert not calls and not clients


def test_profile_switch_openrouter_codex_openrouter_and_config_reload(tmp_path, monkeypatch):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    module = _extractor()
    a = _or_home(tmp_path / 'a')
    b = _configure(tmp_path / 'b')
    _auth(b)
    codex_calls = _native(monkeypatch, b)
    or_calls, clients = _sdk(monkeypatch)
    token = set_secret_scope({'OPENROUTER_API_KEY': 'synthetic-foreign-context-key'},
                             profile_home=str(tmp_path / 'foreign'))
    try:
        for home in (a, b):
            assert module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(home))['error'] == ''
        _configure(a, provider='openrouter', model='vendor/exact-updated-model',
                   timeout=23, max_tokens=1300, reasoning_effort='medium')
        assert module.extract_session_claims(TEXT, extraction_settings=module.read_extraction_settings(a))['error'] == ''
    finally:
        reset_secret_scope(token)
    assert len(codex_calls) == 1 and [c['model'] for c in or_calls] == [
        'xiaomi/mimo-v2.6-flash', 'vendor/exact-updated-model']
    assert or_calls[-1]['timeout'] == 23 and or_calls[-1]['max_tokens'] == 1300
    assert all(c['kwargs']['api_key'] == 'synthetic-own-or-key' and c['closed'] for c in clients)


@pytest.mark.parametrize('mode', ['direct', 'background'])
def test_openrouter_owner_snapshot_wired_in_session_paths(tmp_path, monkeypatch, mode):
    import importlib.util
    import sys
    module = _extractor()
    home = _or_home(tmp_path / 'own')
    monkeypatch.setenv('MEMORY_WIKI_EVENT_LEDGER_ENABLED', '1')
    monkeypatch.setenv('MEMORY_WIKI_BACKGROUND_JOBS_ENABLED', '0')
    calls, _ = _sdk(monkeypatch)
    name = 'mw_or_owner_paths'
    spec = importlib.util.spec_from_file_location(
        name, ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[name] = plugin
    spec.loader.exec_module(plugin)
    seen = []

    def extract(*args, **kwargs):
        seen.append(kwargs.get('extraction_settings'))
        return module.extract_session_claims(*args, **kwargs)

    monkeypatch.setattr(plugin, 'extract_session_claims', extract)
    provider = plugin.MemoryWikiProvider()
    provider.initialize('synthetic-or-session', hermes_home=str(home), bot_id='synthetic-owner')
    provider.project_scope = ''
    try:
        if mode == 'direct':
            provider._extract_session_claims(TEXT)
        else:
            event_id = plugin._memory_events.capture_event(
                provider, plugin, TEXT[0]['content'], event_type='dialogue_turn',
                role='user', session_id=provider.session_id)
            assert event_id and plugin._background_jobs.enqueue_event(provider, 'extract_session_events', event_id)
            plugin._background_jobs.run_once(provider, plugin)
    finally:
        provider.shutdown()
    assert len(calls) == 1 and len(seen) == 1
    assert seen[0].home == home.resolve() and seen[0].provider == 'openrouter'


def test_legacy_environment_openrouter_preserved_for_explicit_root_owner(tmp_path, monkeypatch):
    import json
    from contextlib import contextmanager
    module = _extractor()
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('MW_EXTRACTION_MODEL', 'xiaomi/mimo-v2.6-flash')
    monkeypatch.setenv('MW_EXTRACTION_API_KEY', 'synthetic-legacy-key')
    sent = []

    @contextmanager
    def offline(request, **_kw):
        sent.append(json.loads(request.data))
        payload = json.dumps({'choices': [{'message': {
            'content': json.dumps({'claims': [_candidate()]})}}]}).encode()
        yield SimpleNamespace(read=lambda _limit: payload)

    monkeypatch.setattr(module, '_urlopen_no_redirect', offline)
    snapshot = module.read_extraction_settings(tmp_path)
    result = module.extract_session_claims(TEXT, extraction_settings=snapshot)
    assert snapshot.provider == 'legacy' and result['error'] == '' and len(result['entries']) == 1
    assert sent[0]['model'] == 'xiaomi/mimo-v2.6-flash'
