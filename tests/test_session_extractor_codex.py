"""Codex subscription extraction; all inputs/auth are synthetic, transport is offline."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _extractor():
    name = 'mw_codex_extractor_test'
    spec = importlib.util.spec_from_file_location(name, ROOT / 'extractor.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _configure(home, **changes):
    import yaml
    home.mkdir(parents=True, exist_ok=True)
    settings = dict(enabled=True, provider='openai-codex', model='gpt-6-luna',
                    timeout=17, max_tokens=900, reasoning_effort='low')
    settings.update(changes)
    (home / 'config.yaml').write_text(yaml.safe_dump({
        'plugins': {'entries': {'memory-wiki': {'settings': {'extraction': settings}}}}
    }), encoding='utf-8')
    return home


def _auth(home, label='owner'):
    import time
    # Deliberately not a real JWT or credential. Never copied from a real home.
    (home / 'auth.json').write_text(json.dumps({
        'version': 1, 'providers': {'openai-codex': {
            'tokens': {'access_token': 'synthetic-test-' + label, 'refresh_token': 'synthetic-refresh-' + label,
                       'expires_at': time.time() + 7200}, 'auth_mode': 'chatgpt'
        }}
    }), encoding='utf-8')


def _candidate(**changes):
    item = dict(claim='Project Aster uses a violet release channel.', type='fact',
                topic='aster', evidence_quote='Project Aster uses a violet release channel.',
                speaker='user', message_index=0, event_at='', confidence=.91)
    item.update(changes)
    return item


def _native(monkeypatch, home, *, content=None):
    from agent import auxiliary_client as aux
    from hermes_constants import get_hermes_home
    from agent.secret_scope import current_secret_scope_home
    calls = []

    def complete(adapter, **kwargs):
        assert get_hermes_home().resolve() == home.resolve()
        assert Path(current_secret_scope_home()).resolve() == home.resolve()
        wire, model, timeout = adapter._build_responses_kwargs(kwargs)
        calls.append((kwargs, wire, model, timeout))
        return SimpleNamespace(model=model, choices=[SimpleNamespace(message=SimpleNamespace(
            content=content if content is not None else json.dumps({'claims': [_candidate()]}),
            tool_calls=None))])

    monkeypatch.setattr(aux._CodexCompletionsAdapter, 'create', complete)
    return calls


def test_profile_yaml_codex_uses_native_exact_model_and_schema_instructions(tmp_path, monkeypatch):
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    calls = _native(monkeypatch, home)
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-paid-key')
    monkeypatch.setattr(module, '_urlopen_no_redirect', lambda *_a, **_kw: pytest.fail('paid fallback'))
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['error'] == '' and len(result['entries']) == 1
    assert result['entries'][0]['source'] == 'extractor:llm'
    kwargs, wire, model, timeout = calls[0]
    assert model == wire['model'] == 'gpt-6-luna' and timeout == 17
    assert wire['store'] is False and not wire.get('tools')
    assert wire['reasoning']['effort'] == 'low'
    assert 'temperature' not in wire and 'max_output_tokens' not in wire
    assert 'response_format' not in wire
    assert json.dumps(module._response_schema()['schema'], ensure_ascii=False) in wire['instructions']
    assert '{"claims":[]}' in wire['instructions']
    assert kwargs['max_tokens'] == 900


@pytest.mark.parametrize('changes', [
    {'enabled': 'false'}, {'enabled': 1}, {'enabled': None},
    {'provider': 'openrouter'}, {'model': ' gpt-6-luna'}, {'model': ''},
    {'timeout': True}, {'timeout': 61}, {'timeout': '17'},
    {'max_tokens': 99999}, {'reasoning_effort': 'ultra'},
    {'api_key': 'synthetic-yaml-secret'},
])
def test_invalid_native_settings_fail_closed_without_paid_legacy(tmp_path, monkeypatch, changes):
    module = _extractor()
    home = _configure(tmp_path / 'own', **changes)
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-paid-key')
    monkeypatch.setattr(module, '_urlopen_no_redirect', lambda *_a, **_kw: pytest.fail('paid fallback'))
    snapshot = module.read_extraction_settings(home)
    assert snapshot.enabled is False and snapshot.error == 'invalid extraction settings'
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Remember: Project Aster uses a violet release channel.'}
    ], extraction_settings=snapshot)
    assert result['heuristic_only'] is True and result['extracted'] == 1
    assert result['entries'][0]['source'] == 'extractor:heuristic'
    assert 'synthetic-yaml-secret' not in repr(snapshot) + str(result)


@pytest.mark.parametrize('raw', [
    'plugins: [broken', 'plugins: null',
    'plugins: {entries: {memory-wiki: {settings: {extraction: null}}}}',
    'plugins: {entries: {memory-wiki: {settings: {extraction: []}}}}',
])
def test_malformed_yaml_never_enables_legacy(tmp_path, monkeypatch, raw):
    module = _extractor()
    tmp_path.joinpath('config.yaml').write_text(raw, encoding='utf-8')
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    snapshot = module.read_extraction_settings(tmp_path)
    assert not snapshot.enabled and snapshot.error == 'invalid extraction settings'


def test_missing_native_settings_cannot_route_codex_model_to_paid_legacy(tmp_path, monkeypatch):
    module = _extractor()
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('MW_EXTRACTION_MODEL', 'gpt-6-luna')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-paid-key')
    snapshot = module.read_extraction_settings(tmp_path)
    assert snapshot.enabled is False


def test_missing_own_oauth_never_borrows_foreign_root_or_ambient_scope(tmp_path, monkeypatch):
    from agent.secret_scope import set_secret_scope, reset_secret_scope, current_secret_scope_home
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override, get_hermes_home
    module = _extractor()
    own = _configure(tmp_path / 'own')
    foreign = _configure(tmp_path / 'foreign')
    _auth(foreign, 'foreign')
    calls = _native(monkeypatch, own)
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    home_token = set_hermes_home_override(foreign)
    scope_token = set_secret_scope({'HERMES_CODEX_BASE_URL': 'https://foreign.invalid'}, profile_home=str(foreign))
    try:
        result = module.extract_session_claims([
            {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
        ], extraction_settings=module.read_extraction_settings(own))
        assert calls == [] and result['entries'] == [] and result['error']
        assert get_hermes_home() == foreign
        assert current_secret_scope_home() == str(foreign)
    finally:
        reset_secret_scope(scope_token)
        reset_hermes_home_override(home_token)


@pytest.mark.parametrize('violation', ['credential', 'endpoint', 'redirect'])
def test_native_route_violation_never_sends_text(tmp_path, monkeypatch, violation):
    from agent import auxiliary_client as aux
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    calls = _native(monkeypatch, home)
    native_client = aux.CodexAuxiliaryClient

    def bad_client(real_client, model):
        client = native_client(real_client, model)
        if violation == 'credential':
            client.api_key = 'synthetic-test-foreign'
        if violation == 'endpoint':
            client.base_url = 'https://api.openai.com/v1'
        if violation == 'redirect':
            client._real_client._client.follow_redirects = True
        return client

    monkeypatch.setattr(aux, 'CodexAuxiliaryClient', bad_client)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert calls == [] and result['entries'] == [] and result['error']


def test_profile_and_ambient_endpoint_overrides_are_pinned_to_official_url(tmp_path, monkeypatch):
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    (home / '.env').write_text('HERMES_CODEX_BASE_URL=https://wrong.invalid\n', encoding='utf-8')
    monkeypatch.setenv('HERMES_CODEX_BASE_URL', 'https://ambient.invalid')
    calls = _native(monkeypatch, home)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['error'] == '' and len(calls) == 1
    assert (home / '.env').read_text(encoding='utf-8').strip().endswith('https://wrong.invalid')
    import os
    assert os.environ['HERMES_CODEX_BASE_URL'] == 'https://ambient.invalid'


def test_native_stream_has_absolute_owner_deadline(tmp_path, monkeypatch):
    import time
    from agent import auxiliary_client as aux
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    _native(monkeypatch, home)
    complete = aux._CodexCompletionsAdapter.create
    started = time.monotonic()
    deadlines = []

    def checked(adapter, **kwargs):
        deadline = aux._current_aux_stream_deadline()
        assert deadline is not None
        assert started < deadline <= started + 17.5
        guard = aux._CodexStreamGuard(adapter._client, 17)
        assert guard.hard_deadline == deadline
        deadlines.append(deadline)
        return complete(adapter, **kwargs)

    monkeypatch.setattr(aux._CodexCompletionsAdapter, 'create', checked)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['error'] == '' and len(deadlines) == 1
    assert aux._current_aux_stream_deadline() is None


@pytest.mark.parametrize('mode', ['direct', 'background'])
def test_provider_paths_pass_owner_snapshot_even_from_bare_worker_thread(tmp_path, monkeypatch, mode):
    import threading
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    module = _extractor()
    own = _configure(tmp_path / 'own')
    foreign = _configure(tmp_path / 'foreign', enabled=False)
    _auth(own)
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    monkeypatch.setenv('MEMORY_WIKI_EVENT_LEDGER_ENABLED', '1')
    monkeypatch.setenv('MEMORY_WIKI_BACKGROUND_JOBS_ENABLED', '0')
    name = 'mw_codex_provider_' + mode
    spec = importlib.util.spec_from_file_location(name, ROOT / '__init__.py',
                                                submodule_search_locations=[str(ROOT)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[name] = plugin
    spec.loader.exec_module(plugin)
    provider = plugin.MemoryWikiProvider()
    provider.initialize('synthetic-owner-session', hermes_home=str(own), bot_id='synthetic-owner')
    provider.project_scope = ''
    calls = _native(monkeypatch, own)
    snapshots = []
    real_extract = plugin.extract_session_claims

    def observed(*args, **kwargs):
        snapshots.append(kwargs.get('extraction_settings'))
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(plugin, 'extract_session_claims', observed)
    text = 'Project Aster uses a violet release channel.'
    scope_token = set_secret_scope({'HERMES_CODEX_BASE_URL': 'https://foreign.invalid'}, profile_home=str(foreign))
    try:
        if mode == 'direct':
            provider._extract_session_claims([{'role': 'user', 'content': text}])
        else:
            event_id = plugin._memory_events.capture_event(
                provider, plugin, text, event_type='dialogue_turn', role='user', session_id=provider.session_id,
            )
            assert event_id and plugin._background_jobs.enqueue_event(provider, 'extract_session_events', event_id)
            worker = threading.Thread(target=plugin._background_jobs.run_once, args=(provider, plugin))
            worker.start()
            worker.join(timeout=15)
            assert not worker.is_alive()
            payload = provider._connect().execute('SELECT payload_json FROM memory_jobs').fetchone()[0]
            assert 'synthetic-test-owner' not in payload and 'api_key' not in payload
        assert len(snapshots) == 1 and snapshots[0] is not None
        assert snapshots[0].home == own.resolve() and snapshots[0].model == 'gpt-6-luna'
        assert len(calls) == 1
    finally:
        reset_secret_scope(scope_token)
        provider.shutdown()


def test_explicit_owner_without_native_section_stays_local_despite_legacy_enable(tmp_path, monkeypatch):
    module = _extractor()
    monkeypatch.setenv('MW_EXTRACTION_ENABLED', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-ambient-paid-key')
    assert not module.read_extraction_settings(tmp_path).enabled


@pytest.mark.parametrize('changes', [
    {'message_index': '0'}, {'message_index': .8}, {'message_index': True},
    {'confidence': '0.91'}, {'confidence': True}, {'confidence': 2},
    {'confidence': float('nan')}, {'event_at': 0}, {'topic': 14},
    {'type': 'FACT'}, {'speaker': 'USER'}, {'topic': ' ' * 121 + 'aster'},
    {'claim': ' ' * 2001 + 'Project Aster uses a violet release channel.'},
])
def test_codex_candidates_require_local_schema_types(tmp_path, monkeypatch, changes):
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    _native(monkeypatch, home, content=json.dumps({'claims': [_candidate(**changes)]}))
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['entries'] == []


@pytest.mark.parametrize('mode', ['tools', 'model', 'oversized_claims', 'duplicate_keys'])
def test_codex_non_text_or_schema_violating_responses_are_rejected(tmp_path, monkeypatch, mode):
    from agent import auxiliary_client as aux
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    content = None
    if mode == 'oversized_claims':
        content = json.dumps({'claims': [_candidate()] * 21})
    if mode == 'duplicate_keys':
        content = '{"claims":[],"claims":' + json.dumps([_candidate()]) + '}'
    _native(monkeypatch, home, content=content)
    complete = aux._CodexCompletionsAdapter.create

    def violating(adapter, **kwargs):
        response = complete(adapter, **kwargs)
        if mode == 'tools':
            response.choices[0].message.tool_calls = [SimpleNamespace(id='synthetic-tool')]
        if mode == 'model':
            response.model = 'gpt-other'
        return response

    monkeypatch.setattr(aux._CodexCompletionsAdapter, 'create', violating)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['entries'] == [] and result['error']


def test_unknown_owner_grant_expiry_blocks_inference(tmp_path, monkeypatch):
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    calls = _native(monkeypatch, home)
    data = json.loads((home / 'auth.json').read_text())
    data['providers']['openai-codex']['tokens'].pop('expires_at')
    (home / 'auth.json').write_text(json.dumps(data), encoding='utf-8')
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert calls == [] and result['entries'] == [] and result['error']


def test_native_yaml_reader_does_not_require_undeclared_pyyaml(tmp_path, monkeypatch):
    import builtins
    module = _extractor()
    home = _configure(tmp_path / 'own')
    real_import = builtins.__import__

    def no_pyyaml(name, *args, **kwargs):
        if name == 'yaml' or name.startswith('yaml.'):
            raise ImportError('PyYAML not installed in native Hermes runtime')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', no_pyyaml)
    snapshot = module.read_extraction_settings(home)
    assert snapshot.enabled is True and snapshot.model == 'gpt-6-luna'


def test_snapshot_is_immutable_and_reused_across_config_change(tmp_path, monkeypatch):
    from dataclasses import FrozenInstanceError
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    calls = _native(monkeypatch, home)
    snapshot = module.read_extraction_settings(home)
    with pytest.raises(FrozenInstanceError):
        snapshot.model = 'gpt-other'
    _configure(home, enabled=False, reasoning_effort='high')
    monkeypatch.setattr(module, 'read_extraction_settings', lambda *_a: pytest.fail('snapshot reread'))
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=snapshot)
    assert result['error'] == '' and calls[0][1]['reasoning']['effort'] == 'low'
    assert 'synthetic-test-owner' not in repr(snapshot) + str(result)


def test_codex_redaction_runs_before_native_transport(tmp_path, monkeypatch):
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    calls = _native(monkeypatch, home)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel. PASSWORD=synthetic-private-value'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['extracted'] == 1
    request = json.dumps(calls[0][1])
    assert 'synthetic-private-value' not in request and module._REMOTE_REDACTION_MARKER in request


@pytest.mark.parametrize('changes', [
    {'speaker': 'assistant'}, {'message_index': 7}, {'evidence_quote': 'A source quote that never appeared.'},
    {'claim': 'Project Aster does not use a violet release channel.'},
])
def test_codex_candidates_still_require_exact_source_ownership(tmp_path, monkeypatch, changes):
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    _native(monkeypatch, home, content=json.dumps({'claims': [_candidate(**changes)]}))
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['entries'] == []


def test_native_exception_is_class_only_and_client_is_closed(tmp_path, monkeypatch):
    from agent import auxiliary_client as aux
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    _native(monkeypatch, home)
    closed = []
    import openai
    create = openai.OpenAI

    def track(**kwargs):
        client = create(**kwargs)
        close = client.close
        def tracked_close():
            close()
            closed.append(client.is_closed())
        client.close = tracked_close
        return client

    def fail(*_a, **_kw):
        raise TimeoutError('synthetic-private-provider-error')

    monkeypatch.setattr(openai, 'OpenAI', track)
    monkeypatch.setattr(aux._CodexCompletionsAdapter, 'create', fail)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Remember: Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['error'] == 'TimeoutError' and result['extracted'] == 1
    assert result['entries'][0]['source'] == 'extractor:heuristic' and closed == [True]
    assert 'synthetic-private-provider-error' not in str(result)


@pytest.mark.parametrize('pool_only', [False, True])
def test_native_preflight_never_calls_resolver_pool_or_status(tmp_path, monkeypatch, pool_only):
    import hermes_cli.auth as auth
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    calls = _native(monkeypatch, home)
    from agent import credential_pool, auxiliary_client
    if pool_only:
        data = json.loads((home / 'auth.json').read_text())
        row = data['providers'].pop('openai-codex')['tokens']
        data['credential_pool'] = {'openai-codex': [dict(row, auth_type='oauth')]}
        (home / 'auth.json').write_text(json.dumps(data), encoding='utf-8')
    def forbidden(*_a, **_kw):
        pytest.fail('native resolver may heal, probe or borrow root')
    monkeypatch.setattr(auth, 'get_codex_auth_status', forbidden)
    monkeypatch.setattr(auth, 'resolve_codex_runtime_credentials', forbidden)
    monkeypatch.setattr(auxiliary_client, 'resolve_provider_client', forbidden)
    monkeypatch.setattr(credential_pool, 'load_pool', forbidden)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert result['error'] == '' and len(calls) == 1


def test_routed_singleton_without_own_pool_never_resolves_root_pool(tmp_path, monkeypatch):
    from agent import auxiliary_client as aux
    module = _extractor()
    own = _configure(tmp_path / 'own')
    foreign = _configure(tmp_path / 'foreign')
    _auth(own)
    _auth(foreign, 'foreign')
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    calls = _native(monkeypatch, own)
    resolved = []
    native_resolve = aux.resolve_provider_client

    def tracked(*args, **kwargs):
        resolved.append(True)
        return native_resolve(*args, **kwargs)

    monkeypatch.setattr(aux, 'resolve_provider_client', tracked)
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(own))
    assert not resolved and len(calls) == 1 and not result['error']


def test_incorrectly_stamped_scope_fails_before_native_resolution(tmp_path, monkeypatch):
    from agent import auxiliary_client as aux, secret_scope
    module = _extractor()
    home = _configure(tmp_path / 'own')
    _auth(home)
    _native(monkeypatch, home)
    resolved = []
    bind = secret_scope.set_secret_scope
    monkeypatch.setattr(secret_scope, 'set_secret_scope',
                        lambda secrets, **_kw: bind(secrets, profile_home=str(tmp_path / 'foreign')))
    monkeypatch.setattr(aux, 'resolve_provider_client', lambda *_a, **_kw: resolved.append(True))
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(home))
    assert not resolved and result['error'] == 'ValueError'


def test_native_real_owner_pool_shadows_foreign_root(tmp_path, monkeypatch):
    import time
    from agent import auxiliary_client as aux
    module = _extractor()
    own = _configure(tmp_path / 'own')
    foreign = _configure(tmp_path / 'foreign')
    _auth(own)
    _auth(foreign, 'foreign')
    auth = json.loads((own / 'auth.json').read_text())
    auth['credential_pool'] = {'openai-codex': [{
        'id': 'synthetic-own-pool', 'auth_type': 'oauth', 'access_token': 'synthetic-test-owner',
        'refresh_token': 'synthetic-refresh-owner', 'expires_at': time.time() + 3600,
        'base_url': 'https://chatgpt.com/backend-api/codex',
    }]}
    (own / 'auth.json').write_text(json.dumps(auth), encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    select = aux._select_pool_entry
    calls = _native(monkeypatch, own)
    monkeypatch.setattr(aux, '_select_pool_entry', select)  # Actual scoped core pool; no root borrowing.
    result = module.extract_session_claims([
        {'role': 'user', 'content': 'Project Aster uses a violet release channel.'}
    ], extraction_settings=module.read_extraction_settings(own))
    assert result['error'] == '' and len(calls) == 1 and len(result['entries']) == 1
