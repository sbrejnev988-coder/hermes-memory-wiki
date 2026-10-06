"""Native discovery controls plus merge-gating F05/R01/R02 response tests.

Run only in an owner-approved isolated package runner; all controls and merge
gates remain in ordinary collection. No SDK substitutes, wheel builds, schema
cache writes, provider.initialize(), runtime migrations, or live profile reads.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import os
import re
import sqlite3
import sys
import tomllib
from hashlib import sha256
from pathlib import Path

import pytest

from agent.memory_provider import MemoryProvider
import hermes_constants

PACKAGE = importlib.import_module("memory_wiki")
CACHE_SHA256 = "7371000445c1ead5f3a6162433d3f9d2ec6956b4c254d791b9f4a2d6b5679b12"
METADATA_SHA256 = {
    "pyproject.toml": "2183b46a908452a4b2feb7899e89511d9b9612060b295c6bf48adce3a97e4eac",
    "plugin.yaml": "51981b06b363ce2c2efbcf57405d7a2571d8ccaa60894177a1a28b567e7fbc41",
    "setup.py": "cb184df928263e32fd4015c38d41dd71345979d6cb4ecad1c4d44b9090f19780",
}
# Preserve the historical 1.24.0 gold map above. The explicitly owner-authorized
# 1.24.5 metadata derivative has its own exact pins, not a weakened hash check.
CURRENT_METADATA_SHA256_1_24_5 = {
    "pyproject.toml": "b1821cb2ddc023c2728b4aa4c2e363750a082aa28ca3be46701573c54a87dbb4",
    "plugin.yaml": "06c87f5733de9abad4520b75311bc487add4c9cf03bc746b04a4348a894d21d2",
    "setup.py": "cb184df928263e32fd4015c38d41dd71345979d6cb4ecad1c4d44b9090f19780",
}


def _source(relative: str) -> Path:
    for root in PACKAGE.__path__:
        path = Path(root) / relative
        if path.is_file():
            return path
    raise AssertionError(f"missing package source: {relative}")


def _schemas(provider):
    expected_bytes = _source("mcp-wrapper/tool_schemas.json").read_bytes()
    assert sha256(expected_bytes).hexdigest() == CACHE_SHA256, "frozen cache changed"
    expected = json.loads(expected_bytes)
    actual = provider.get_tool_schemas()
    # Compare every full native dictionary, not a lossy projection or just names.
    # Explicit failure keeps pytest from emitting two enormous schema copies.
    if actual != expected:
        old = {row["name"]: row for row in expected}
        new = {row["name"]: row for row in actual}
        changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
        pytest.fail(f"native full-dict schema drift: changed={changed}; order_equal="
                    f"{[r['name'] for r in actual] == [r['name'] for r in expected]}")
    names = [row["name"] for row in actual]
    assert len(actual) == len(set(names)) == 121
    return actual


@pytest.fixture(autouse=True)
def isolated_scope(monkeypatch):
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert os.environ.get("HERMES_SECURITY_STRICT") == "0", "not a strict acceptance gate"
    monkeypatch.setenv("MEMORY_WIKI_ONLINE_METRICS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATION_ENABLED", "0")
    monkeypatch.setattr(sys.modules["__main__"], "_memory_wiki_instance", None, raising=False)


def test_native_metadata_info_schemas_are_readonly(record_property):
    from tools.registry import tool_error, tool_result
    provider = PACKAGE.MemoryWikiProvider()
    core = Path(hermes_constants.__file__).resolve().parent
    assert Path(inspect.getfile(MemoryProvider)).resolve().is_relative_to(core)
    assert PACKAGE.tool_result is tool_result and PACKAGE.tool_error is tool_error
    assert Path(inspect.getfile(tool_result)).resolve().is_relative_to(core)
    assert PACKAGE.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    assert Path(PACKAGE.__file__).name == "__init__.py"
    for relative, digest in CURRENT_METADATA_SHA256_1_24_5.items():
        assert sha256(_source(relative).read_bytes()).hexdigest() == digest, relative
    project = tomllib.loads(_source("pyproject.toml").read_text(encoding="utf-8"))
    assert provider.name == "memory-wiki"
    assert set(project["project"]["entry-points"]["hermes_agent.memory_providers"]) == {provider.name}
    assert PACKAGE.PLUGIN_VERSION == project["project"]["version"] == "1.24.5"
    # These are the actual native setup/identity introspection APIs, not get_info().
    assert provider.get_config_schema() == []
    assert provider.identity_signature() == {}
    before = sorted(provider.home.rglob("*"))
    assert provider.is_available() is True
    schemas = _schemas(provider)
    manifest = importlib.import_module("hermes_yaml").safe_load(_source("plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["provides_tools"] == [row["name"] for row in schemas]
    from plugins.plugin_loader import read_plugin_description
    assert read_plugin_description(_source("plugin.yaml").parent) == manifest["description"]
    assert provider._conn is None and not provider.root.exists()
    assert sorted(provider.home.rglob("*")) == before
    record_property("discovery_runtime_uninitialized", "true")
    record_property("native_tool_count", len(schemas))
    record_property("provider_source", str(Path(PACKAGE.__file__).resolve()))
    record_property("native_provider_source", str(Path(inspect.getfile(MemoryProvider)).resolve()))
    record_property("native_tool_result_source", str(Path(inspect.getfile(tool_result)).resolve()))
    record_property("schema_cache_sha256", CACHE_SHA256)


def test_packaged_entrypoint_resolves_without_activation():
    project = tomllib.loads(_source("pyproject.toml").read_text(encoding="utf-8"))
    group = "hermes_agent.memory_providers"
    value = project["project"]["entry-points"][group]["memory-wiki"]
    assert value == "memory_wiki:register"
    entrypoint = importlib.metadata.EntryPoint(name="memory-wiki", value=value, group=group)
    assert entrypoint.load() is PACKAGE.register
    # Resolve through the real native loader; never enumerate installed/live providers.
    from plugins.memory import _entry_point_package_dir
    assert _entry_point_package_dir(entrypoint) == Path(PACKAGE.__file__).resolve().parent
    package_data = project["tool"]["setuptools"]["package-data"]["memory_wiki"]
    assert {"plugin.yaml", "mcp-wrapper/*.py", "mcp-wrapper/*.json", "context-coordination/*.py"} <= set(package_data)
    assert project["tool"]["setuptools"]["package-dir"] == {"memory_wiki": "."}
    sdk = importlib.import_module("memory_wiki.sdk")
    assert sdk.__version__ == PACKAGE.PLUGIN_VERSION and sdk.SDK_API_VERSION == "1.0"
    with pytest.raises(ValueError, match="session_id and bot_id must be nonempty"):
        sdk.MemoryWikiClient(hermes_home=Path(os.environ["HERMES_HOME"]), session_id="", bot_id="audit")


def test_native_directory_loader_imports_whole_provider_without_setup_side_effects():
    from plugins.memory import _load_package
    root = Path(PACKAGE.__file__).resolve().parent
    loaded = _load_package(root, "audit_package_contracts_20261003")
    assert loaded is not None and Path(loaded.__file__).resolve() == root / "__init__.py"
    assert loaded.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    provider = loaded.MemoryWikiProvider()
    _schemas(provider)
    assert provider._conn is None and not provider.root.exists()
    # Native directory discovery also imports sibling setup.py; it must stay inert.
    assert callable(loaded.setup.main)


def test_mcp_schema_translation_keeps_full_native_parameters_without_cache_writes():
    native = _schemas(PACKAGE.MemoryWikiProvider())
    path = _source("mcp-wrapper/server.py")
    spec = importlib.util.spec_from_file_location("mw_audit_contract_mcp", path)
    assert spec and spec.loader
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    for row in native:
        expected = {"name": "mw_" + row["name"][len("memory_wiki_"):],
                    "description": row["description"], "inputSchema": row["parameters"]}
        if wrapper.normalize_schema(row) != expected:
            pytest.fail("MCP full-dict translation drift: " + row["name"])
        assert wrapper.plugin_name(expected["name"]) == row["name"]
    assert wrapper._PROVIDER is None and wrapper._SCHEMAS is None
    assert sha256(_source("mcp-wrapper/tool_schemas.json").read_bytes()).hexdigest() == CACHE_SHA256


@pytest.fixture
def recall_provider():
    provider = PACKAGE.MemoryWikiProvider()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Small reference-only SQL fixture; deliberately NOT the runtime upgrade path.
    schema = _source("schema.sql").read_text(encoding="utf-8")
    for name in ("claims", "claims_fts", "contradictions", "meta", "recall_events", "recall_feedback"):
        statement = re.search(rf"CREATE (?:VIRTUAL )?TABLE {name}\b.*?;", schema, re.S)
        assert statement, name
        conn.execute(statement.group())
    for table, fields in {
        "recall_events": {"answer_id": "TEXT DEFAULT ''", "outcome": "TEXT DEFAULT 'pending'"},
        "recall_feedback": {"recall_event_id": "TEXT DEFAULT ''", "outcome": "TEXT DEFAULT 'neutral'", "idempotency_key": "TEXT DEFAULT ''"},
    }.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in fields.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    conn.execute("INSERT INTO meta VALUES('claims_fts_format','v3')")
    stamp = PACKAGE.now()
    for claim_id, text, visibility in (
        ("c_primary", "Orion runs on Atlas for the release pipeline.", "global"),
        ("c_other", "Orion uses Atlas for routine deployment testing.", "global"),
        ("c_foreign", "Orion uses Atlas in a private deployment runbook.", "private"),
    ):
        conn.execute("INSERT INTO claims(id,claim,topic,created_at,updated_at,freshness_at,hash,quality,pinned,visibility_scope,origin_bot_id,origin_session_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (claim_id, text, "deployment", stamp, stamp, stamp, claim_id, .9, 1, visibility, "foreign-bot" if visibility == "private" else "", "foreign-chat" if visibility == "private" else ""))
        conn.execute("INSERT INTO claims_fts VALUES(?,?,?,?,?,?)", (claim_id, "", "", "", "", text))
    conn.commit()
    provider._conn = conn
    try:
        yield provider
    finally:
        conn.close()
        provider._conn = None


def _contradiction(provider, *, foreign=False, identity="ct_visible", created_at=10):
    provider._conn.execute("INSERT INTO contradictions(id,claim_a,claim_b,reason,created_at) VALUES(?,?,?,?,?)",
                           (identity, "c_primary", "c_foreign" if foreign else "c_other", "PRIVATE_REASON_SENTINEL", created_at))
    provider._conn.commit()


def _public_recall(provider, query="Orion Atlas"):
    result = json.loads(provider.handle_tool_call("memory_wiki_recall", {"query": query, "mode": "fast"}))
    assert result.get("success") is True
    assert type(result["conflicts"]) is bool
    assert type(result["answer_policy"]["must_abstain_or_clarify"]) is bool
    assert type(result["answer_policy"]["require_citations"]) is bool
    assert result["evidence_count"] == len(result["items"])
    assert result["answer_policy"]["allowed_citations"] == [row["citation"] for row in result["items"]]
    assert "PRIVATE_REASON_SENTINEL" not in json.dumps(result)
    return result


@pytest.mark.parametrize("case", ["empty", "absent", "present", "foreign"])
def test_old_recall_consumers_retain_boolean_contract(recall_provider, case):
    if case in {"present", "foreign"}:
        _contradiction(recall_provider, foreign=case == "foreign")
    result = _public_recall(recall_provider, "NoSuchMemoryMarker" if case == "empty" else "Orion Atlas")
    assert result["conflicts"] is (case == "present")
    assert bool(result["items"]) is (case != "empty")
    assert result["answer_policy"]["must_abstain_or_clarify"] is (case == "empty")
    if "conflict_check" in result:
        assert result["conflict_check"] == {
            "status": "present" if case == "present" else "absent",
            "scope": "selected_claims",
        }


@pytest.mark.parametrize("case", ["absent", "present", "missing-table", "visibility-error", "beyond-page"])
def test_future_conflict_status_survives_public_tool_response(recall_provider, monkeypatch, record_property, case):
    if case != "absent":
        _contradiction(recall_provider)
    if case == "missing-table":
        recall_provider._conn.execute("DROP TABLE contradictions")
    elif case == "visibility-error":
        def fail_visibility(*_args):
            raise RuntimeError("PRIVATE_REASON_SENTINEL")
        monkeypatch.setattr(recall_provider, "_contradiction_visible", fail_visibility)
    elif case == "beyond-page":
        for index in range(40):
            _contradiction(recall_provider, foreign=True, identity=f"ct_foreign_{index:02d}", created_at=100 + index)
    result = _public_recall(recall_provider)
    record_property("observed_conflicts", str(result["conflicts"]).lower())
    record_property("observed_conflict_check_status", result.get("conflict_check", {}).get("status", "<missing>"))
    record_property("observed_must_abstain", str(result["answer_policy"]["must_abstain_or_clarify"]).lower())
    record_property("observed_evidence_count", result["evidence_count"])
    assert result["items"], "must exercise conflict checking with actual retrieved claims"
    status = "unknown" if case in {"missing-table", "visibility-error"} else "absent" if case == "absent" else "present"
    assert result.get("conflict_check") == {"status": status, "scope": "selected_claims"}
    assert result["conflicts"] is (status == "present")
    policy = result["answer_policy"]
    assert policy["conflict_status"] == status
    assert policy["allowed_citations"] == [item["citation"] for item in result["items"]]
    assert policy["require_citations"] is True
    if status == "unknown":
        # R01 requires qualification, not a false conflict-free conclusion.
        # Still-admissible cited facts do not require blanket abstention.
        assert policy["must_abstain_or_clarify"] is False
        assert "Do not claim there are no contradictions" in policy["instruction"]
        assert "qualify memory-based conclusions" in policy["instruction"]
    rendered = json.dumps(result)
    assert "ct_foreign" not in rendered
    assert "PRIVATE_REASON_SENTINEL" not in rendered


def test_future_f05_rejects_non_sqlite_provider_connection():
    provider = PACKAGE.MemoryWikiProvider()
    provider._conn = object()  # Negative boundary input, not a fake provider/SDK.
    recall = importlib.import_module(PACKAGE.__name__ + ".recall_orchestrator")
    candidate = {"kind": "episode", "_source_id": "ep_audit", "_snapshot_fingerprint": recall._snapshot_fingerprint({"id": "ep_audit"})}
    try:
        visible = recall._final_visible_nonclaims(provider, [candidate], episodic_backend=None,
                   event_backend=None, observation_backend=None, event_scope="chat", runtime_module=PACKAGE)
        assert visible == set(), "F05 merge gate; arbitrary connection cannot authorize evidence"
    finally:
        provider._conn = None


@pytest.mark.parametrize("route,model,tokens,accepted", [
    ("openai-codex", "gpt-6-luna", 9000, True),
    ("openai-codex", "gpt-6-luna", 9001, False),
    ("openrouter", "openai/gpt-4.1-mini", 3000, True),
    ("openrouter", "openai/gpt-4.1-mini", 9000, False),
])
def test_session_9000_settings_remain_provider_specific(tmp_path, route, model, tokens, accepted):
    extractor = importlib.import_module(PACKAGE.__name__ + ".extractor")
    requested = dict(enabled=True, provider=route, model=model, timeout=30, max_tokens=tokens, reasoning_effort="medium")
    path = tmp_path / "config.yaml"
    path.write_text(json.dumps({"plugins": {"entries": {"memory-wiki": {"settings": {"extraction": requested}}}}}), encoding="utf-8")
    before = path.read_bytes()
    snapshot = extractor.read_extraction_settings(tmp_path)
    assert snapshot.home == tmp_path.resolve() and path.read_bytes() == before
    if accepted:
        assert snapshot.error == "" and {key: getattr(snapshot, key) for key in requested} == requested
    else:
        assert snapshot.enabled is False and snapshot.error == "invalid extraction settings"


def test_graph_codex_yaml_is_independent_literal_and_readonly(tmp_path):
    requested = dict(enabled=True, provider="openai-codex", model="gpt-6-luna-900k", timeout=17, reasoning_effort="medium")
    path = tmp_path / "config.yaml"
    settings = {"graph_extraction": requested, "extraction": {"enabled": False}}
    config = {"plugins": {"entries": {"memory-wiki": {"settings": settings}}}}
    path.write_text(json.dumps(config), encoding="utf-8")
    before = path.read_bytes()
    provider = PACKAGE.MemoryWikiProvider()
    provider.home = tmp_path
    snapshot = provider._graph_extraction_settings()
    assert snapshot is not None and snapshot.home == tmp_path.resolve()
    assert {key: getattr(snapshot, key) for key in requested} == requested
    assert snapshot.max_tokens == 700 and path.read_bytes() == before
    assert provider._conn is None and not provider.root.exists()
