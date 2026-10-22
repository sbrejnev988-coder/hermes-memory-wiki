"""Prepared genuine pytest/native component regressions, never a SOURCE packet.

Requires the real memory_wiki package, current Hermes Core, OpenAI/httpx and the
native YAML reader in a separately admitted credential-free environment. All
stores/replies are authored synthetic data; only HTTPX MockTransport is replaced.
No SDK, auth validator, native root helper or response guard is made permissive.
The current Core adapter lacks refusal provenance: a completed offline response
must still yield response_refusal_unconfirmed, not fabricated extractor success.
No SQL/provider initialization or live network is needed by these new cases.
"""
from __future__ import annotations

import base64
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

MODEL = "gpt-6-luna-900k"
TEXT = "Orion runs on Atlas."
ROOT = Path(__file__).absolute().parents[1]


def _jwt(label, expires=None):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return part({"alg": "none"}) + "." + part({
        "sub": "synthetic-" + label, "exp": time.time() + 7200 if expires is None else expires,
    }) + ".synthetic"


def _row(label="shared", **changes):
    row = dict(auth_type="oauth", source="manual:device_code", access_token=_jwt(label),
               refresh_token="synthetic-refresh-" + label, base_url="https://chatgpt.com/backend-api/codex")
    row.update(changes)
    return row


def _pool(row):
    return {"credential_pool": {"openai-codex": [row]}}


def _write(home, document):
    (home / "auth.json").write_text(json.dumps(document), encoding="utf-8")


def _config(home, session=None, graph=None):
    sections = {}
    if session is not None:
        sections["extraction"] = session
    if graph is not None:
        sections["graph_extraction"] = graph
    (home / "config.yaml").write_text(json.dumps({
        "plugins": {"entries": {"memory-wiki": {"settings": sections}}}
    }), encoding="utf-8")  # JSON is valid input for the genuine native YAML parser.


def _section(**changes):
    return dict(enabled=True, provider="openai-codex", model=MODEL, timeout=17, **changes)


def _snapshot_tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def native(tmp_path, monkeypatch):
    # Imports stay in own fixture setup, never at ordinary collection time.
    session = importlib.import_module("memory_wiki.extractor")
    graph = importlib.import_module("memory_wiki.entity_relation_extractor")
    import hermes_constants as constants
    from agent import auxiliary_client, credential_pool, secret_scope
    from hermes_cli import auth, auth_codex
    import httpx
    import openai
    import hermes_yaml
    assert Path(session.__file__).resolve() == (ROOT / "extractor.py").resolve()
    assert Path(graph.__file__).resolve() == (ROOT / "entity_relation_extractor.py").resolve()
    assert Path(constants.__file__).name == "hermes_constants.py"
    assert callable(hermes_yaml.safe_load) and openai.OpenAI.__module__.startswith("openai")

    root = tmp_path / "shared"
    home, other = root / "profiles" / "alpha", root / "profiles" / "beta"
    home.mkdir(parents=True)
    other.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(foreign))
    assert constants.get_default_hermes_root(home=home).resolve() == root.resolve()
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-ambient-paid-key")
    monkeypatch.setenv("HERMES_CODEX_BASE_URL", "https://foreign.invalid/codex")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "0")

    def forbidden(*_args, **_kwargs):
        pytest.fail("forbidden auth lifecycle/resolution/paid fallback")
    for module, names in (
        (auth, ("resolve_codex_runtime_credentials", "get_codex_auth_status", "_save_auth_store")),
        (auth_codex, ("_codex_http_client", "_save_codex_tokens")),
        (credential_pool, ("load_pool",)),
        (auxiliary_client, ("resolve_provider_client", "_select_pool_entry")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(credential_pool.CredentialPool, "_persist", forbidden)
    monkeypatch.setattr(session, "_urlopen_no_redirect", forbidden)
    monkeypatch.setattr(session, "_openrouter_content", forbidden)
    monkeypatch.setattr(graph, "_urlopen_no_redirect", forbidden)

    row = _row()
    _write(root, _pool(row))
    _config(home, _section(codex_auth_source="owner_or_default"), _section())
    settings = session.read_extraction_settings(home)
    assert not settings.error and settings.home == home.resolve()
    traffic = SimpleNamespace(requests=[], clients=[], expected_home=home,
                              expected_access=row["access_token"], failure=None)
    real_http = openai.DefaultHttpxClient
    real_openai = openai.OpenAI

    def serve(request):
        assert constants.get_hermes_home().resolve() == traffic.expected_home.resolve()
        assert Path(secret_scope.current_secret_scope_home()).resolve() == traffic.expected_home.resolve()
        assert str(request.url) == "https://chatgpt.com/backend-api/codex/responses"
        assert request.headers["Authorization"] == "Bearer " + traffic.expected_access
        assert not request.headers.get("OpenAI-Organization") and not request.headers.get("OpenAI-Project")
        wire = json.loads(request.content)
        assert wire["store"] is False and wire["stream"] is True and not wire.get("tools")
        assert wire["model"] == "gpt-6-luna"  # Native normalization, not a model fallback.
        assert wire["reasoning"]["effort"] == "low"
        assert "max_output_tokens" not in wire
        traffic.requests.append({"owner": traffic.expected_home.name, "wire_model": wire["model"]})
        if traffic.failure == "timeout":
            raise httpx.ReadTimeout("synthetic-private-error", request=request)
        if traffic.failure is not None:
            return httpx.Response(traffic.failure, headers={"Location": "https://foreign.invalid/"},
                                  json={"error": {"message": "synthetic-private-error"}})
        item = {"type": "message", "id": "msg_synthetic", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": '{"claims":[]}', "annotations": []}]}
        events = [
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp_synthetic", "model": "gpt-6-luna",
                "status": "completed", "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
        ]
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body.encode())

    def http_factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        client = real_http(transport=httpx.MockTransport(serve), **kwargs)
        traffic.clients.append(client)
        return client

    def openai_factory(**kwargs):
        assert kwargs["max_retries"] == 0 and kwargs["timeout"] <= 17
        assert kwargs["base_url"] == "https://chatgpt.com/backend-api/codex"
        return real_openai(**kwargs)

    monkeypatch.setattr(openai, "DefaultHttpxClient", http_factory)
    monkeypatch.setattr(openai, "OpenAI", openai_factory)
    token = constants.set_hermes_home_override(foreign)
    secret_token = secret_scope.set_secret_scope({"HERMES_CODEX_BASE_URL": "https://foreign.invalid/codex"},
                                                 profile_home=str(foreign))
    try:
        yield SimpleNamespace(session=session, graph=graph, constants=constants, scope=secret_scope,
            root=root, home=home, other=other, settings=settings, traffic=traffic, row=row)
    finally:
        assert all(client.is_closed for client in traffic.clients)
        assert constants.get_hermes_home() == foreign
        assert secret_scope.current_secret_scope_home() == str(foreign)
        assert auxiliary_client._current_aux_stream_deadline() is None
        assert os.environ["HERMES_HOME"] == str(foreign)
        secret_scope.reset_secret_scope(secret_token)
        constants.reset_hermes_home_override(token)


def _session_call(native, settings=None):
    return native.session.extract_session_claims([{"role": "user", "content": TEXT}],
        add_claim_callback=None, extraction_settings=settings or native.settings)


def _graph_call(native, settings):
    return native.graph.extract_relations(TEXT, endpoint="https://foreign.invalid/", api_key="synthetic-unused",
        model=MODEL, predicates=frozenset({"runs_on"}), extraction_settings=settings, timeout=17)


def test_native_readers_keep_session_and_graph_optins_independent(native):
    n = native
    before = _snapshot_tree(n.root)
    session = n.session.read_extraction_settings(n.home)
    graph = n.graph.read_graph_extraction_settings(n.home)
    assert session.codex_auth_source == "owner_or_default" and graph.codex_auth_source == "owner_only"
    assert graph.max_tokens == 700 and graph.home == session.home == n.home.resolve()
    with pytest.raises(ValueError):
        n.session._own_codex_grant(graph)
    _config(n.home, _section(), _section(codex_auth_source="owner_or_default"))
    session = n.session.read_extraction_settings(n.home)
    graph = n.graph.read_graph_extraction_settings(n.home)
    assert session.codex_auth_source == "owner_only" and graph.codex_auth_source == "owner_or_default"
    assert n.session._own_codex_grant(graph) == n.row["access_token"]
    assert not n.traffic.clients and not n.traffic.requests
    assert set(_snapshot_tree(n.root)) == set(before)


@pytest.mark.parametrize("policy", [None, True, "", "owner_or_default ", "shared"],
                         ids=["null", "bool", "empty", "whitespace", "unknown"])
def test_native_readers_reject_invalid_policy_even_when_disabled(native, policy):
    n = native
    for enabled in (False, True):
        section = _section(codex_auth_source=policy)
        section["enabled"] = enabled
        _config(n.home, section, section)
        assert n.session.read_extraction_settings(n.home).error == "invalid extraction settings"
        with pytest.raises(ValueError):
            n.graph.read_graph_extraction_settings(n.home)
    _config(n.home, dict(enabled=False, provider="openrouter", model="openai/gpt-4.1-mini",
                        codex_auth_source="owner_or_default"))
    assert n.session.read_extraction_settings(n.home).error == "invalid extraction settings"
    assert not n.traffic.requests and not n.traffic.clients


@pytest.mark.parametrize("local", ["missing", "other-provider"])
def test_native_shared_grant_reaches_only_official_transport_without_faking_response_success(native, local):
    n = native
    if local == "other-provider":
        _write(n.home, {"providers": {"openrouter": {}}, "credential_pool": {"other": []},
                        "suppressed_sources": {"openai-codex": []}})
    before = _snapshot_tree(n.root)
    result = _session_call(n)
    assert len(n.traffic.requests) == 1
    assert result["entries"] == [] and result["persisted"] == 0
    assert result["error"] == "response_refusal_unconfirmed"  # Retain current genuine Core limitation.
    assert n.row["access_token"] not in str(result) and "synthetic-private-error" not in str(result)
    assert _snapshot_tree(n.root) == before


@pytest.mark.parametrize("authority", ["singleton", "pool"])
def test_native_owner_priority_does_not_even_read_invalid_root(native, authority):
    n = native
    row = _row("own")
    _write(n.home, _pool(row) if authority == "pool" else {
        "providers": {"openai-codex": {"auth_mode": "chatgpt", "tokens": row}}})
    (n.root / "auth.json").write_text("{", encoding="utf-8")
    before = _snapshot_tree(n.root)
    assert n.session._own_codex_grant(n.settings) == row["access_token"]
    assert _snapshot_tree(n.root) == before
    assert not n.traffic.requests and not n.traffic.clients


@pytest.mark.parametrize("refusal", ["empty-pool", "invalid-pool", "provider", "suppression", "expired", "unreadable"])
def test_native_local_refusal_is_final_before_any_http(native, monkeypatch, refusal):
    n = native
    document = {
        "empty-pool": {"credential_pool": {"openai-codex": []}},
        "invalid-pool": {"credential_pool": {"openai-codex": None}},
        "provider": {"providers": {"openai-codex": {}}},
        "suppression": {"suppressed_sources": {"openai-codex": {"device_code": False}}},
        "expired": _pool(_row("expired", access_token=_jwt("expired", time.time() - 1))),
        "unreadable": _pool(_row("owner")),
    }[refusal]
    _write(n.home, document)
    before = _snapshot_tree(n.root)
    actual = Path.read_text
    def read(path, *args, **kwargs):
        assert path != n.root / "auth.json", "local refusal must not read shared grant"
        if refusal == "unreadable" and path == n.home / "auth.json":
            raise PermissionError("synthetic-private-read-error")
        return actual(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    result = _session_call(n)
    assert result["error"] and not result["entries"] and result["persisted"] == 0
    assert not n.traffic.requests and not n.traffic.clients
    assert _snapshot_tree(n.root) == before and "synthetic-private" not in str(result)


@pytest.mark.parametrize("refusal", ["missing", "malformed", "non-oauth", "expired", "ttl", "proxy", "source", "cooldown"])
def test_native_shared_authority_reuses_strict_validator_before_http(native, refusal):
    n = native
    row = _row()
    changes = {
        "non-oauth": {"auth_type": "api_key"}, "expired": {"access_token": _jwt("expired", time.time() - 1)},
        "ttl": {"expires_at": time.time() + 2}, "proxy": {"base_url": "https://proxy.invalid/codex"},
        "source": {"source": "model_config"}, "cooldown": {"model_cooldowns": {MODEL: time.time() + 3600}},
    }
    row.update(changes.get(refusal, {}))
    _write(n.root, _pool(row))
    if refusal == "missing":
        (n.root / "auth.json").unlink()
    elif refusal == "malformed":
        (n.root / "auth.json").write_text("{", encoding="utf-8")
    before = _snapshot_tree(n.root)
    result = _session_call(n)
    assert result["error"] and not result["entries"] and result["persisted"] == 0
    assert not n.traffic.clients and not n.traffic.requests
    assert _snapshot_tree(n.root) == before


def test_native_serialized_manual_pool_survives_singleton_suppression_and_exact_model_bench(native):
    from agent.credential_pool import PooledCredential
    n = native
    blocked = PooledCredential.from_dict("openai-codex", dict(_row("blocked"), id="synthetic-blocked",
        model_cooldowns={MODEL: time.time() + 3600})).to_dict()
    healthy = PooledCredential.from_dict("openai-codex", dict(_row("healthy"), id="synthetic-healthy", source="manual:loopback_pkce",
        model_cooldowns={"other-model": time.time() + 3600})).to_dict()
    for suppressed in (["device_code"], {"device_code": False}):
        _write(n.root, {"credential_pool": {"openai-codex": [blocked, healthy]},
                        "suppressed_sources": {"openai-codex": suppressed}})
        before = _snapshot_tree(n.root)
        assert n.session._own_codex_grant(n.settings) == healthy["access_token"]
        assert _snapshot_tree(n.root) == before
    assert not n.traffic.requests and not n.traffic.clients


def test_native_atomic_shared_rotation_preserves_two_owner_contexts_and_graph_guard(native):
    n = native
    first = _session_call(n)
    assert first["error"] == "response_refusal_unconfirmed"
    rotated = _row("rotated")
    pending = n.root / "native-rotation.synthetic"
    pending.write_text(json.dumps(_pool(rotated)), encoding="utf-8")
    pending.replace(n.root / "auth.json")  # Synthetic atomic source update, no native refresh.
    _config(n.other, _section(codex_auth_source="owner_or_default"),
            _section(codex_auth_source="owner_or_default"))
    n.traffic.expected_home, n.traffic.expected_access = n.other, rotated["access_token"]
    before = _snapshot_tree(n.root)
    session = n.session.read_extraction_settings(n.other)
    graph = n.graph.read_graph_extraction_settings(n.other)
    assert n.session._own_codex_grant(session) == rotated["access_token"]
    assert _session_call(n, session)["error"] == "response_refusal_unconfirmed"
    with pytest.raises(n.session.ExtractionBoundaryError, match="response_refusal_unconfirmed"):
        _graph_call(n, graph)
    assert [request["owner"] for request in n.traffic.requests] == ["alpha", "beta", "beta"]
    assert session.home == graph.home == n.other.resolve() and n.settings.home == n.home.resolve()
    assert not (n.home / "auth.json").exists() and not (n.other / "auth.json").exists()
    assert _snapshot_tree(n.root) == before


def test_native_bare_worker_uses_explicit_owner_snapshot_without_sql_jobs(native):
    n = native
    before = _snapshot_tree(n.root)
    outcomes, failures = [], []
    def work():
        try:
            snapshot = n.session.read_extraction_settings(n.home)
            assert snapshot.home == n.home.resolve() and snapshot.codex_auth_source == "owner_or_default"
            outcomes.append(_session_call(n, snapshot))
        except BaseException as exc:
            failures.append(exc)
    worker = threading.Thread(target=work)
    worker.start()
    worker.join(timeout=20)
    assert not worker.is_alive() and failures == [] and len(outcomes) == 1
    assert outcomes[0]["error"] == "response_refusal_unconfirmed" and outcomes[0]["persisted"] == 0
    assert len(n.traffic.requests) == 1 and _snapshot_tree(n.root) == before


@pytest.mark.parametrize("route,failure", [
    ("session", 401), ("session", 429), ("session", 503), ("session", 302), ("session", "timeout"),
    ("graph", 401), ("graph", 429), ("graph", 503), ("graph", 302), ("graph", "timeout"),
], ids=["session-401", "session-429", "session-503", "session-302", "session-timeout",
        "graph-401", "graph-429", "graph-503", "graph-302", "graph-timeout"])
def test_native_transport_failure_has_no_retry_refresh_paid_fallback_or_partial_edges(native, failure, route):
    n = native
    n.traffic.failure = failure
    before = _snapshot_tree(n.root)
    if route == "session":
        result = _session_call(n)
        assert result["error"] and result["entries"] == [] and result["persisted"] == 0
        assert "synthetic-private-error" not in str(result) and n.row["access_token"] not in str(result)
    else:
        with pytest.raises(Exception):
            _graph_call(n, replace(n.settings, max_tokens=700))
    assert len(n.traffic.requests) == 1 and _snapshot_tree(n.root) == before
    assert all(client.is_closed for client in n.traffic.clients)


def test_native_missing_root_capability_and_final_admission_both_fail_closed(native, monkeypatch):
    n = native
    with monkeypatch.context() as missing:
        missing.delattr(n.constants, "get_default_hermes_root")
        result = _session_call(n)
        assert result["error"] == "extraction_capability_unavailable" and not result["entries"]
    before = _snapshot_tree(n.root)
    admissions = []
    def admit():
        admissions.append("checked")
        if len(admissions) == 2:
            raise ValueError("synthetic-private-admission-refusal")
    with pytest.raises(Exception):
        n.session._codex_content(n.settings, [{"role": "user", "content": TEXT}], _admit=admit)
    assert len(admissions) == 2 and not n.traffic.requests
    assert _snapshot_tree(n.root) == before and all(client.is_closed for client in n.traffic.clients)
