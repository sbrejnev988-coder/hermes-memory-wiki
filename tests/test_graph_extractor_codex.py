"""Graph-only Codex: настоящий native SDK, синтетические auth/HTTP/SQLite."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-6-luna-900k"
TEXT = "Orion runs on Atlas."
RELATION = {"subject": "Orion", "predicate": "runs_on", "object": "Atlas",
            "evidence": "Orion runs on Atlas", "confidence": .92}


def _configure(home, graph=None, *, extraction=None):
    home.mkdir(parents=True, exist_ok=True)
    settings = {"graph_extraction": graph if graph is not None else {
        "enabled": True, "provider": "openai-codex", "model": MODEL, "timeout": 17}}
    if extraction is not None:
        settings["extraction"] = extraction
    (home / "config.yaml").write_text(json.dumps({
        "plugins": {"entries": {"memory-wiki": {"settings": settings}}}
    }), encoding="utf-8")
    return home


def _auth(home):
    (home / "auth.json").write_text(json.dumps({"providers": {"openai-codex": {
        "auth_mode": "chatgpt", "tokens": {"access_token": "synthetic-owner-only",
        "refresh_token": "synthetic-refresh-only", "expires_at": time.time() + 7200}}}}), encoding="utf-8")


def _plugin(home, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    name = "mw_graph_codex_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from agent.memory_provider import MemoryProvider
    assert issubclass(module.MemoryWikiProvider, MemoryProvider), "Standalone SDK substitute запрещён"
    return module


def _seed(provider, module, *, claim_id="c_graph_codex", text=TEXT, source="test"):
    with provider._connect() as conn:
        conn.execute("""INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
            created_at,updated_at,freshness_at,access_count,last_accessed,hash,
            visibility_scope,origin_session_id,origin_bot_id,origin_chat_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claim_id, text, "graph", "active", .9, .9, source, "", module.now(), module.now(),
             module.now(), 0, 0, claim_id, "chat", provider.session_id, provider.bot_id,
             provider._chat_hash(provider.session_id)))
    return claim_id


def _call(provider, tool="memory_wiki_graph_extract_claim", **kwargs):
    return json.loads(provider.handle_tool_call(tool, kwargs))


def _transport(monkeypatch, home, *, content=None, status=200, timeout=False):
    import httpx
    import openai
    from agent.secret_scope import current_secret_scope_home
    from hermes_constants import get_hermes_home
    calls, closed = [], []
    native_http = openai.DefaultHttpxClient

    def handle(request):
        assert get_hermes_home().resolve() == home.resolve()
        assert Path(current_secret_scope_home()).resolve() == home.resolve()
        assert request.headers["Authorization"] == "Bearer synthetic-owner-only"
        assert not request.headers.get("OpenAI-Organization") and not request.headers.get("OpenAI-Project")
        calls.append({"url": str(request.url), "body": json.loads(request.content)})
        if timeout:
            raise httpx.ReadTimeout("synthetic-private-timeout", request=request)
        if status != 200:
            return httpx.Response(status, headers={"Location": "https://foreign.invalid/"},
                                  json={"error": {"message": "synthetic-private-error"}})
        item = {"type": "message", "id": "msg_synthetic", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": content if content is not None else
                             json.dumps({"relations": [RELATION]}), "annotations": []}]}
        events = [
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp_synthetic", "model": "gpt-6-luna",
                "status": "completed", "output": [item], "usage": {"input_tokens": 20,
                "output_tokens": 30, "total_tokens": 50}}},
        ]
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body.encode())

    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        client = native_http(**kwargs, transport=httpx.MockTransport(handle))
        close = client.close
        def checked_close():
            close()
            closed.append(client.is_closed)
        client.close = checked_close
        return client

    monkeypatch.setattr(openai, "DefaultHttpxClient", factory)
    return calls, closed


def test_graph_only_yaml_codex_uses_real_native_adapter_without_openrouter_key(tmp_path, monkeypatch):
    home = _configure(tmp_path / "own", extraction={"enabled": False})
    _auth(home)
    for key in ("OPENROUTER_API_KEY", "MEMORY_WIKI_GRAPH_EXTRACT_API_KEY", "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED",
                "MEMORY_WIKI_GRAPH_EXTRACT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, closed = _transport(monkeypatch, home)
    auth_before = (home / "auth.json").read_bytes()
    try:
        claim_id = _seed(provider, module)
        result = _call(provider, claim_id=claim_id, apply=False)
        assert result.get("success") is True, result
        assert result["proposals"] == [RELATION] and result["applied"] == 0
        assert provider._connect().execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
        assert len(calls) == 1 and calls[0]["url"] == "https://chatgpt.com/backend-api/codex/responses"
        wire = calls[0]["body"]
        assert wire["model"] == "gpt-6-luna"  # literal requested variant сохраняется до native wire conversion
        assert wire["store"] is False and not wire.get("tools")
        assert "relations" in wire["instructions"] and "claims" not in wire["instructions"]
        assert wire["input"][0]["content"] == [{"type": "input_text", "text": TEXT}]
        assert not {"temperature", "max_output_tokens", "response_format"} & set(wire)
        assert closed == [True]
        assert (home / "auth.json").read_bytes() == auth_before
    finally:
        provider.shutdown()


def test_graph_model_environment_override_preserves_requested_literal(tmp_path, monkeypatch):
    from agent import auxiliary_client as aux
    home = _configure(tmp_path / "own", graph={"enabled": True, "provider": "openai-codex",
                                               "model": "gpt-6-sol", "timeout": 17})
    _auth(home)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", MODEL)
    monkeypatch.setenv("MW_EXTRACTION_MODEL", "unrelated-conversation-model")
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, closed = _transport(monkeypatch, home)
    native_client = aux.CodexAuxiliaryClient
    requested = []
    def observe(client, model):
        requested.append(model)
        return native_client(client, model)
    monkeypatch.setattr(aux, "CodexAuxiliaryClient", observe)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert result.get("success") is True, result
        assert requested == [MODEL]  # Не ручная смена на базовый slug.
        assert calls[0]["body"]["model"] == "gpt-6-luna" and closed == [True]
    finally:
        provider.shutdown()


@pytest.mark.parametrize("changes", [
    {"enabled": "false"}, {"enabled": 1}, {"provider": "openai"},
    {"provider": "unknown"}, {"model": " gpt-6-luna-900k"}, {"model": ""},
    {"timeout": True}, {"timeout": 61}, {"reasoning_effort": "ultra"},
    {"api_key": "synthetic-unallowed-key"}, {"endpoint": "https://wrong.invalid"},
    {"provider": None},
])
def test_malformed_graph_yaml_fails_before_transport_even_with_paid_key(tmp_path, monkeypatch, changes):
    from entity_relation_extractor import read_graph_extraction_settings
    settings = {"enabled": True, "provider": "openai-codex", "model": MODEL, "timeout": 17, **changes}
    home = _configure(tmp_path / "own", graph=settings)
    _auth(home)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-paid-key")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    paid = []
    import urllib.request
    def paid_call(*_args, **_kwargs):
        paid.append(True)
        raise RuntimeError("paid route forbidden")
    monkeypatch.setattr(urllib.request, "urlopen", paid_call)
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, _closed = _transport(monkeypatch, home)
    try:
        with pytest.raises(ValueError, match="invalid graph extraction settings"):
            read_graph_extraction_settings(home)
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert result.get("success") is not True and calls == paid == []
    finally:
        provider.shutdown()


@pytest.mark.parametrize("mode", ["own-file", "foreign-env", "empty-env"])
def test_graph_model_override_is_owner_scoped_and_present_empty_is_invalid(tmp_path, monkeypatch, mode):
    from agent import auxiliary_client as aux
    from hermes_constants import pin_process_hermes_home
    own = _configure(tmp_path / "own", graph={"enabled": True, "provider": "openai-codex",
                                               "model": "gpt-6-sol", "timeout": 17})
    _auth(own)
    module = _plugin(own, monkeypatch)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    if mode == "own-file":
        (own / ".env").write_text("MEMORY_WIKI_GRAPH_EXTRACT_MODEL=" + MODEL + "\n", encoding="utf-8")
        monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", "ambient-ignored-model")
    elif mode == "foreign-env":
        pin_process_hermes_home(foreign)
        monkeypatch.setenv("HERMES_HOME", str(foreign))
        monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", MODEL)
    else:
        monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", "")
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(own), bot_id="graph-owner-bot", agent_context="test")
    calls, _closed = _transport(monkeypatch, own)
    ctor = aux.CodexAuxiliaryClient
    requested = []
    def observe(client, model):
        requested.append(model)
        return ctor(client, model)
    monkeypatch.setattr(aux, "CodexAuxiliaryClient", observe)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        if mode == "empty-env":
            assert result.get("success") is not True and requested == calls == []
        else:
            assert result.get("success") is True, result
            assert requested == [MODEL if mode == "own-file" else "gpt-6-sol"]
        assert not (foreign / "auth.json").exists()
    finally:
        pin_process_hermes_home(None)
        provider.shutdown()


def test_auto_graph_yaml_codex_preserves_acl_dry_run_journal_and_replay(tmp_path, monkeypatch):
    home = _configure(tmp_path / "own")
    _auth(home)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "1")
    monkeypatch.delenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", raising=False)
    module = _plugin(home, monkeypatch)
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    viewer.initialize("other-chat", hermes_home=str(home), bot_id="other-bot", agent_context="test")
    calls, _closed = _transport(monkeypatch, home)
    try:
        auto_text = "Orion runs on Atlas for reliable vector search."
        assert len(module.tokens(auto_text)) >= 4
        claim_id = _seed(owner, module, source="extractor:llm", text=auto_text)
        evidence = {"schema": "memory-wiki-extraction-evidence-v1", "session_id": owner.session_id,
                    "speaker": "user", "message_index": 0, "evidence_quote": auto_text,
                    "event_at": 0, "event_timezone": "UTC", "extractor": "extractor:llm"}
        with owner._connect() as conn:
            conn.execute("INSERT INTO evidence(id,claim_id,text,source,created_at) VALUES(?,?,?,?,?)",
                         ("ev_graph_codex", claim_id, json.dumps(evidence), "extractor:llm", module.now()))
        checkpoint = owner._journal_checkpoint("before-codex-graph")
        dry = _call(owner, claim_id=claim_id, apply=False)
        assert dry.get("success") is True and dry["applied"] == 0
        assert owner._connect().execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
        result = owner._auto_graph_enrich_extracted_claims([claim_id])
        assert result["attempted"] == result["relations_applied"] == 1, result
        assert result["errors"] == 0 and len(calls) == 2
        relation = dict(owner._connect().execute("SELECT * FROM relations").fetchone())
        claim = dict(owner._connect().execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone())
        for key in ("visibility_scope", "origin_bot_id", "origin_chat_hash"):
            assert relation[key] == claim[key]
        assert relation["source_claim_id"] == claim_id
        assert _call(viewer, "memory_wiki_graph_query", query="Orion")["relations"] == []
        assert _call(viewer, claim_id=claim_id, apply=False).get("success") is not True
        again = owner._auto_graph_enrich_extracted_claims([claim_id])
        assert again["attempted"] == 0 and len(calls) == 2
        journal = owner.journal_path.read_text(encoding="utf-8")
        assert "memory_wiki_add_relation" in journal and "memory_wiki_graph_extract_claim" not in journal
        viewer.shutdown()  # Own fixture must release its independent SQLite handle before a file swap.
        rebuilt = owner._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        assert rebuilt["failed"] == 0 and len(calls) == 2
        assert _call(owner, "memory_wiki_graph_query", query="Orion")["relations"][0]["id"] == relation["id"]
        for field, unsafe in (("risk", "secret"), ("quarantined_at", 123)):
            with owner._connect() as conn:
                conn.execute(f"UPDATE claims SET {field}=? WHERE id=?", (unsafe, claim_id))
            assert _call(owner, claim_id=claim_id, apply=False).get("success") is not True
            assert _call(owner, "memory_wiki_graph_query", query="Orion")["relations"] == []
            assert len(calls) == 2
            with owner._connect() as conn:
                conn.execute(f"UPDATE claims SET {field}=? WHERE id=?", ("low" if field == "risk" else 0, claim_id))
    finally:
        viewer.shutdown()
        owner.shutdown()


@pytest.mark.parametrize("with_conversation", [False, True])
def test_codex_model_alone_never_selects_paid_legacy_graph(tmp_path, monkeypatch, with_conversation):
    home = tmp_path / "own"
    home.mkdir()
    if with_conversation:
        (home / "config.yaml").write_text(json.dumps({"plugins": {"entries": {"memory-wiki": {
            "settings": {"extraction": {"enabled": True, "provider": "openai-codex", "model": MODEL}}
        }}}}), encoding="utf-8")
    _auth(home)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", MODEL)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-paid-key")
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, _closed = _transport(monkeypatch, home)
    paid = []
    import io
    import urllib.request
    def paid_response(request, **_kwargs):
        paid.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content":
            json.dumps({"relations": [RELATION]})}}]}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", paid_response)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert result.get("success") is not True and paid == calls == [], result
    finally:
        provider.shutdown()


def _deny_paid_and_auth_mutation(monkeypatch):
    from agent import credential_pool, auxiliary_client
    from hermes_cli import auth
    import urllib.request
    attempts = []
    def forbidden(*_args, **_kwargs):
        attempts.append(True)
        raise RuntimeError("owner auth resolution, refresh or paid fallback forbidden")
    monkeypatch.setattr(credential_pool, "load_pool", forbidden)
    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", forbidden)
    for name in ("resolve_codex_runtime_credentials", "get_codex_auth_status", "refresh_codex_oauth_pure"):
        monkeypatch.setattr(auth, name, forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    return attempts


@pytest.mark.parametrize("state", ["missing", "expired", "unknown-expiry", "empty-pool", "malformed-pool",
    "suppressed-list", "suppressed-mapping", "native-blocked", "native-cooldown", "native-healthy",
    "native-healthy-second", "native-other-cooldown", "native-expired-cooldown"])
def test_graph_grant_preflight_obeys_native_owner_authority_without_resolution(tmp_path, monkeypatch, state):
    from agent.credential_pool import PooledCredential
    from agent.secret_scope import set_secret_scope, reset_secret_scope, current_secret_scope_home
    from hermes_constants import get_hermes_home, pin_process_hermes_home
    own = _configure(tmp_path / "own")
    foreign = _configure(tmp_path / "foreign")
    _auth(own)
    _auth(foreign)
    data = json.loads((own / "auth.json").read_text(encoding="utf-8"))
    tokens = data["providers"]["openai-codex"]["tokens"]
    if state == "expired":
        tokens["expires_at"] = time.time() - 1
    elif state == "unknown-expiry":
        del tokens["expires_at"]
    elif state in {"empty-pool", "malformed-pool"}:
        data["credential_pool"] = {"openai-codex": [] if state == "empty-pool" else None}
    elif state.startswith("suppressed"):
        data["suppressed_sources"] = {"openai-codex": ["device_code"] if state == "suppressed-list"
                                      else {"device_code": False}}
    elif state.startswith("native-"):
        row = PooledCredential.from_dict("openai-codex", dict(tokens, id="synthetic-native-owner",
            auth_type="oauth", source="manual:device_code", last_status="ok")).to_dict()
        if state == "native-blocked":
            row.update(last_status="exhausted", last_error_code=429, last_error_reset_at=time.time() + 300)
        if state in {"native-cooldown", "native-healthy-second", "native-other-cooldown", "native-expired-cooldown"}:
            key = "different-native-model" if state == "native-other-cooldown" else MODEL
            row["model_cooldowns"] = {key: time.time() + (-1 if state == "native-expired-cooldown" else 300)}
        rows = [row]
        if state == "native-healthy-second":
            rows.append(PooledCredential.from_dict("openai-codex", dict(tokens, id="synthetic-native-second",
                auth_type="oauth", source="manual:device_code", last_status="ok")).to_dict())
        data["credential_pool"] = {"openai-codex": rows}
        data["suppressed_sources"] = {"openai-codex": ["device_code"]}  # Не подавляет независимый manual pool.
    (own / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    if state == "missing":
        (own / "auth.json").unlink()
    own_before = (own / "auth.json").read_bytes() if (own / "auth.json").exists() else None
    foreign_before = (foreign / "auth.json").read_bytes()
    module = _plugin(own, monkeypatch)
    pin_process_hermes_home(foreign)
    monkeypatch.setenv("HERMES_HOME", str(foreign))
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-paid-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-paid-openai")
    monkeypatch.setenv("OPENAI_ORG_ID", "synthetic-foreign-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "synthetic-foreign-project")
    monkeypatch.setenv("HERMES_CODEX_BASE_URL", "https://ambient.invalid/")
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(own), bot_id="graph-owner-bot", agent_context="test")
    calls, closed = _transport(monkeypatch, own)
    attempts = _deny_paid_and_auth_mutation(monkeypatch)
    scope = set_secret_scope({"OPENAI_API_KEY": "synthetic-foreign-scope"}, profile_home=str(foreign))
    usable = state in {"native-healthy", "native-healthy-second", "native-other-cooldown", "native-expired-cooldown"}
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert (result.get("success") is True) is usable, result
        if not usable:
            assert result.get("error"), result
        assert len(calls) == int(usable) and closed == ([True] if usable else [])
        assert attempts == []
        assert current_secret_scope_home() == str(foreign)
        assert get_hermes_home().resolve() == foreign.resolve()
        if own_before is not None:
            assert (own / "auth.json").read_bytes() == own_before
        else:
            assert not (own / "auth.json").exists()
        assert (foreign / "auth.json").read_bytes() == foreign_before
        assert not list(own.glob("*.lock")) and not list(foreign.glob("*.lock"))
        assert "synthetic-owner-only" not in str(result)
    finally:
        reset_secret_scope(scope)
        pin_process_hermes_home(None)
        provider.shutdown()


@pytest.mark.parametrize("mode", ["401", "429", "503", "302", "timeout"])
def test_graph_codex_transport_errors_close_client_without_retry_or_paid_fallback(tmp_path, monkeypatch, mode):
    home = _configure(tmp_path / "own")
    _auth(home)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-paid-key")
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, closed = _transport(monkeypatch, home, status=200 if mode == "timeout" else int(mode), timeout=mode == "timeout")
    attempts = _deny_paid_and_auth_mutation(monkeypatch)
    before = (home / "auth.json").read_bytes()
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=True)
        assert result.get("success") is not True and len(calls) == 1 and closed == [True], result
        assert attempts == [] and (home / "auth.json").read_bytes() == before
        assert "synthetic-private" not in str(result) and "synthetic-owner-only" not in str(result)
        assert provider._connect().execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
    finally:
        provider.shutdown()


@pytest.mark.parametrize("content", [
    "not JSON", json.dumps({"claims": []}), json.dumps({"relations": [dict(RELATION, subject="Atlas", object="Orion")]}),
    json.dumps({"relations": [dict(RELATION, object="Unstated")]}),
    json.dumps({"relations": [dict(RELATION, confidence=.2)]}),
    json.dumps({"relations": [dict(RELATION, predicate="related_to")]}),
    json.dumps({"relations": [RELATION] * 9}),
    json.dumps({"relations": [RELATION, dict(RELATION, confidence=True)]}),
], ids=["bad-json", "session-schema", "reversed", "hallucinated", "low-confidence", "bad-predicate", "too-many", "mixed-invalid"])
def test_graph_codex_response_validation_never_partially_applies(tmp_path, monkeypatch, content):
    home = _configure(tmp_path / "own")
    _auth(home)
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, closed = _transport(monkeypatch, home, content=content)
    attempts = _deny_paid_and_auth_mutation(monkeypatch)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=True)
        assert result.get("success") is not True and len(calls) == 1 and closed == [True], result
        assert attempts == [] and provider._connect().execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
        assert "memory_wiki_add_relation" not in provider.journal_path.read_text(encoding="utf-8")
    finally:
        provider.shutdown()


def test_disabled_graph_yaml_cannot_inherit_legacy_enablement(tmp_path, monkeypatch):
    home = _configure(tmp_path / "own", graph={"enabled": False})
    _auth(home)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-paid-key")
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    calls, _closed = _transport(monkeypatch, home)
    attempts = _deny_paid_and_auth_mutation(monkeypatch)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert result.get("success") is not True and calls == attempts == []
    finally:
        provider.shutdown()


def test_explicit_graph_openrouter_yaml_preserves_legacy_transport(tmp_path, monkeypatch):
    import io
    import urllib.request
    home = _configure(tmp_path / "own", graph={"enabled": True, "provider": "openrouter", "model": "test-model", "timeout": 13})
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_API_KEY", "test-key")
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    codex, _closed = _transport(monkeypatch, home)
    paid = []
    def transport(request, *, timeout):
        assert request.headers["Authorization"] == "Bearer test-key"
        paid.append((json.loads(request.data), timeout))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content":
            json.dumps({"relations": [RELATION]})}}]}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert result.get("success") is True and result["proposals"] == [RELATION]
        assert codex == [] and len(paid) == 1
        assert paid[0][0]["model"] == "test-model" and paid[0][1] == 13
        assert not (home / "auth.json").exists()
    finally:
        provider.shutdown()


@pytest.mark.parametrize("fault", ["absent-helper", "routing-dependency", "routing-runtime"])
def test_graph_owner_yaml_survives_unknown_launch_without_ambient_override(tmp_path, monkeypatch, fault):
    import hermes_constants as core
    from agent import auxiliary_client as aux
    home = _configure(tmp_path / "own")
    _auth(home)
    module = _plugin(home, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("graph-owner-chat", hermes_home=str(home), bot_id="graph-owner-bot", agent_context="test")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_MODEL", "ignored-ambient-model")
    if fault == "absent-helper":
        monkeypatch.delattr(core, "get_routing_process_hermes_home")
    else:
        def fail():
            if fault == "routing-dependency":
                raise ModuleNotFoundError("optional routing dependency missing", name="synthetic_optional_dependency")
            raise RuntimeError("launch identity unavailable")
        monkeypatch.setattr(core, "get_routing_process_hermes_home", fail)
    calls, closed = _transport(monkeypatch, home)
    ctor, requested = aux.CodexAuxiliaryClient, []
    def observe(client, model):
        requested.append(model)
        return ctor(client, model)
    monkeypatch.setattr(aux, "CodexAuxiliaryClient", observe)
    try:
        result = _call(provider, claim_id=_seed(provider, module), apply=False)
        assert result.get("success") is True and len(calls) == 1 and closed == [True], result
        assert requested == [MODEL]
    finally:
        provider.shutdown()
