"""Standalone stdlib SOURCE packet; execute only after separate admission.

No plugin/Core/SDK import, YAML parser, SQL, worker, HTTP or model execution.
Actual product auth bodies and exact native root/JWT helper bodies are extracted
from bound sources. Only their three native import statements become lexical
SOURCE bindings (not sys.modules SDK substitutes). Files/clock are synthetic.
Reader/caller/transport checks below are STATIC, not native execution evidence.
The ordinary pytest module/class are inert and deliberately not collected.
"""
from __future__ import annotations

import ast
import base64
import datetime as _dt
from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import unittest
from unittest.mock import patch

__test__ = False
NOW = 2_000_000_000
MODEL = "gpt-6-luna-900k"
CORE_SOURCE_PINS = {
    "hermes_constants.py": "870ad9935a62968636d6a14d160c0269dfbefd8091ab3cb71be78b30bef6360f",
    "auth_constants.py": "eaaab33840ab6bfb5b0bd86bf1c7e58b7645b52c59b8caf6b2553a165080432b",
    "codex_headers.py": "54d165f64bb3988c16254f587a5dccac2efa988e57e86027714bf98f16bbbca9",
}
PRODUCT_BODIES = (
    "ExtractionSettings", "ExtractionBoundaryError", "_validate_codex_auth_source",
    "_validate_extraction_settings", "_codex_official_issuer", "_codex_official_metadata", "_codex_row_ready",
    "_codex_stored_expiry",
    "_codex_grant_from_auth", "_read_codex_authority", "_own_codex_grant",
)
ROOT_BODIES = (
    "_expand_hermes_home", "_platform_default_hermes_home", "_get_platform_default_hermes_home",
    "_hermes_root_of", "get_default_hermes_root",
)
SOURCE_IMPORT_BINDINGS = {
    "agent.codex_headers": {"CODEX_AUX_BASE_URL"},
    "hermes_cli.auth_constants": {"_decode_jwt_claims"},
    "hermes_constants": {"get_default_hermes_root"},
}


def _jwt(label="shared", expires=NOW + 7200, **metadata):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    # Authored unsigned input, never authentication/server-acceptance evidence.
    return part({"alg": "none"}) + "." + part({"sub": "synthetic-" + label, "exp": expires, **metadata}) + ".synthetic"


def _row(label="shared", **changes):
    row = dict(auth_type="oauth", source="manual:device_code", access_token=_jwt(label),
               refresh_token="synthetic-refresh-" + label, expires_at=NOW + 7200,
               base_url="https://chatgpt.com/backend-api/codex", last_status="ok")
    row.update(changes)
    return row


def _pool(*rows):
    return {"credential_pool": {"openai-codex": list(rows)}}


def _singleton(label="owner", **state):
    return {"providers": {"openai-codex": {
        "auth_mode": "chatgpt", "tokens": _row(label), **state}}}


def _node(tree, name):
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)


def _compile_bodies(tree, names, namespace, filename, *, source_bindings=False):
    class BindSourceImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module not in SOURCE_IMPORT_BINDINGS:
                raise AssertionError("unreviewed SOURCE import dependency")
            assert {a.name for a in node.names} == SOURCE_IMPORT_BINDINGS[node.module]
            assert all(a.asname is None for a in node.names)
            return ast.copy_location(ast.Pass(), node)
    # Parse afresh so import seams never mutate the retained comparison trees.
    selected = [_node(tree, name) for name in names]
    body = ast.Module(body=selected, type_ignores=[])
    if source_bindings:
        body = BindSourceImports().visit(body)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    body.body.insert(0, future)
    exec(compile(ast.fix_missing_locations(body), filename, "exec", dont_inherit=True), namespace)


class SharedCodexAuthSourceTests(unittest.TestCase):
    __test__ = False

    def setUp(self):
        started = getattr(type(self), "case_started", None)
        if started is not None:
            started("SharedCodexAuthSourceTests." + self._testMethodName)
        temporary = tempfile.TemporaryDirectory(prefix="shared-codex-source-", dir=str(self.scratch))
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.account = self.base / "account"
        self.account.mkdir()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"HOME": str(self.account), "USERPROFILE": str(self.account),
                               "LOCALAPPDATA": str(self.account / "AppData" / "Local"),
                               "HERMES_HOME": str(self.base / "foreign")}).start()
        native = {"Path": Path, "os": os, "sys": sys, "_default_hermes_root_memo": None}
        _compile_bodies(ast.parse(self.raw["hermes_constants.py"]), ROOT_BODIES, native,
                        self.paths["hermes_constants.py"])
        jwt = {"base64": base64, "json": json}
        _compile_bodies(ast.parse(self.raw["auth_constants.py"]), ("_decode_jwt_claims",), jwt,
                        self.paths["auth_constants.py"])
        self.root = native["_get_platform_default_hermes_home"]()
        self.owner = self.root / "profiles" / "alpha"
        self.other = self.root / "profiles" / "beta"
        self.owner.mkdir(parents=True)
        self.other.mkdir()
        headers = ast.parse(self.raw["codex_headers.py"])
        official = next(ast.literal_eval(n.value) for n in headers.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "CODEX_AUX_BASE_URL" for t in n.targets))
        name = "_shared_codex_SOURCE_product"
        module = ModuleType(name)
        previous = sys.modules.get(name)
        sys.modules[name] = module  # Actual extracted product, not a fake native module.
        def cleanup_module():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        self.addCleanup(cleanup_module)
        module.__dict__.update({"dataclass": dataclass, "field": field, "Path": Path,
            "json": json, "math": math, "re": re, "_dt": _dt, "time": SimpleNamespace(time=lambda: NOW),
            "_decode_jwt_claims": jwt["_decode_jwt_claims"],
            "CODEX_AUX_BASE_URL": official, "get_default_hermes_root": native["get_default_hermes_root"]})
        _compile_bodies(ast.parse(self.raw["extractor.py"]), PRODUCT_BODIES, module.__dict__,
                        self.paths["extractor.py"], source_bindings=True)
        self.api = module
        self.settings = module.ExtractionSettings(enabled=True, home=self.owner, model=MODEL, timeout=17,
                                                   codex_auth_source="owner_or_default")
        self.write(self.root, _pool(_row()))

    def write(self, home, value):
        (home / "auth.json").write_text(json.dumps(value), encoding="utf-8")

    def grant(self, settings=None):
        return self.api._own_codex_grant(settings or self.settings)

    def root_reads(self, operation):
        real_read, seen = Path.read_text, []
        root_file = self.root / "auth.json"
        def observed(path, *args, **kwargs):
            if path == root_file:
                seen.append(path)
            return real_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", observed):
            operation()
        return seen

    def test_default_policy_and_constructed_snapshots_are_strict(self):
        default = replace(self.settings, codex_auth_source="owner_only")
        self.assertEqual(self.api.ExtractionSettings().codex_auth_source, "owner_only")
        self.assertEqual(self.root_reads(lambda: self.assertRaises(ValueError, self.grant, default)), [])
        for value in (None, True, 1, [], "", "OWNER_ONLY", "owner_or_default ", "/tmp/auth"):
            with self.subTest(policy=value):
                with self.assertRaises(self.api.ExtractionBoundaryError):
                    self.grant(replace(self.settings, codex_auth_source=value))
        with self.assertRaises(self.api.ExtractionBoundaryError):
            self.grant(replace(self.settings, provider="openrouter", model="openai/gpt-4.1-mini"))

    def test_absence_optin_and_owner_pool_singleton_precedence(self):
        self.assertEqual(self.grant(), _jwt())
        # Well-formed other-provider-only store is not a local Codex authority.
        self.write(self.owner, {"providers": {"openrouter": {"auth_mode": "api_key"}},
                               "credential_pool": {"other": []}, "suppressed_sources": {"other": []}})
        self.assertEqual(self.grant(), _jwt())
        for empty in ([], {}):
            self.write(self.owner, {"providers": {"openrouter": {}},
                                   "suppressed_sources": {"openai-codex": empty}})
            self.assertEqual(self.grant(), _jwt())
        self.write(self.owner, _singleton())
        self.assertEqual(self.root_reads(lambda: self.assertEqual(self.grant(), _jwt("owner"))), [])
        data = _singleton()
        data.update(_pool(_row("pool")))
        self.write(self.owner, data)
        self.assertEqual(self.root_reads(lambda: self.assertEqual(self.grant(), _jwt("pool"))), [])

        # Missing/null/empty/other-provider remain lawful absence, not malformed.
        (self.owner / "auth.json").unlink()
        states = ({}, {"active_provider": None}, {"active_provider": ""}, {"active_provider": "openrouter"})
        for state in states:
            with self.subTest(absent_discriminator=state):
                self.write(self.owner, {"providers": {}, "credential_pool": {}, "suppressed_sources": {}, **state})
                self.assertEqual(self.root_reads(lambda: self.assertEqual(self.grant(), _jwt())),
                                 [self.root / "auth.json"])
        (self.owner / "auth.json").unlink()
        for home in (self.owner, self.root):
            for state in states:
                with self.subTest(source=home.name, healthy_discriminator=state):
                    self.write(home, dict(_pool(_row("typed")), **state))
                    self.assertEqual(self.root_reads(lambda: self.assertEqual(self.grant(), _jwt("typed"))),
                                     [] if home == self.owner else [self.root / "auth.json"])
            if home == self.owner:
                (home / "auth.json").unlink()

    def test_local_authority_refusals_never_bypass_to_shared(self):
        refusals = [
            [], {"providers": None}, {"credential_pool": []}, {"suppressed_sources": None},
            {"providers": {"openai-codex": None}}, {"providers": {"openai-codex": {}}},
            _singleton(auth_mode="api_key"), _singleton(last_status="exhausted"),
            _pool(), {"credential_pool": {"openai-codex": None}}, _pool(_row(last_status="dead")),
            _pool(_row(auth_type="api_key")), _pool(_row(), None),
            {"suppressed_sources": {"openai-codex": ["device_code"]}},
            {"suppressed_sources": {"openai-codex": {"device_code": False}}},
            {"suppressed_sources": {"openai-codex": None}},
            {"active_provider": "openai-codex"},
            _singleton(tokens=_row(expires_at=NOW - 1)),
        ]
        for data in refusals:
            with self.subTest(data_shape=list(data) if isinstance(data, dict) else "list"):
                self.write(self.owner, data)
                self.assertEqual(self.root_reads(lambda: self.assertRaises(ValueError, self.grant)), [])
        # A good singleton must not revive a present empty authoritative pool.
        data = _singleton()
        data.update(_pool())
        self.write(self.owner, data)
        self.assertEqual(self.root_reads(lambda: self.assertRaises(ValueError, self.grant)), [])

        for home in (self.owner, self.root):
            for active in (False, 0, 1, 1.5, [], ["openai-codex"], {}, {"provider": "openai-codex"}):
                with self.subTest(source=home.name, malformed_discriminator=active):
                    (self.owner / "auth.json").unlink(missing_ok=True)
                    self.write(self.root, _pool(_row()))
                    # A live healthy root witness makes owner refusal distinguishing.
                    self.assertEqual(self.grant(replace(self.settings, home=self.root)), _jwt())
                    data = {"providers": {}, "credential_pool": {}, "suppressed_sources": {},
                            "active_provider": active}
                    if home == self.root:
                        data.update(_pool(_row()))  # Root cannot accept malformed metadata either.
                    self.write(home, data)
                    self.assertEqual(self.root_reads(lambda: self.assertRaises(ValueError, self.grant)),
                                     [] if home == self.owner else [self.root / "auth.json"])

    def test_malformed_unreadable_and_duplicate_local_documents_are_terminal(self):
        for raw in ("{", "null", '{"providers":{"openai-codex":{}},"providers":{}}',
                    '{"suppressed_sources":NaN}', '{"providers":{},"providers":{}}'):
            with self.subTest(raw=raw):
                (self.owner / "auth.json").write_text(raw, encoding="utf-8")
                self.assertEqual(self.root_reads(lambda: self.assertRaises(ValueError, self.grant)), [])
        real_read = Path.read_text
        def denied(path, *args, **kwargs):
            if path == self.owner / "auth.json":
                raise PermissionError("synthetic private read failure")
            if path == self.root / "auth.json":
                self.fail("unreadable owner is not absence")
            return real_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", denied):
            with self.assertRaises(PermissionError):
                self.grant()

    def test_shared_failures_and_expiry_cover_the_entire_timeout(self):
        for changes in ({"expires_at": NOW + 17}, {"expires_at": NOW + 16},
                        {"access_token": _jwt(expires=NOW - 1)},
                        {"expires_at": "future"}, {"expires_at": True},
                        {"expires_at_ms": (NOW - 1) * 1000}, {"expires_at_ms": True},
                        {"expires_at": "2033-05-18T03:33:38"},
                        {"access_token": "synthetic-opaque", "expires_at": None},
                        {"refresh_token": ""}, {"access_token": ""},
                        {"last_error_code": 401}, {"last_error_reason": "quota"},
                        {"last_error_message": "synthetic-private"}, {"last_error_reset_at": NOW - 1},
                        {"model_cooldowns": {MODEL: "invalid"}}, {"model_cooldowns": []}):
            with self.subTest(changes=list(changes)):
                self.write(self.root, _pool(_row(**changes)))
                with self.assertRaises(ValueError):
                    self.grant()
        self.write(self.root, _pool(_row(expires_at=NOW + 18)))
        self.assertEqual(self.grant(), _jwt())
        for expiry in ({"expires_at_ms": (NOW + 18) * 1000},
                       {"expires_at": (NOW + 18) * 1000},
                       {"expires_at": _dt.datetime.fromtimestamp(NOW + 18, _dt.timezone.utc).isoformat()}):
            self.write(self.root, _pool(_row(**expiry)))
            self.assertEqual(self.grant(), _jwt())
        # Unknown/missing/unreadable/malformed shared authority never heals itself.
        (self.root / "auth.json").unlink()
        with self.assertRaises(ValueError):
            self.grant()
        (self.root / "auth.json").write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.grant()
        real_read = Path.read_text
        def denied(path, *args, **kwargs):
            if path == self.root / "auth.json":
                raise PermissionError("synthetic shared read failure")
            return real_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", denied):
            with self.assertRaises(PermissionError):
                self.grant()

    def test_manual_pool_suppression_and_exact_model_cooldowns_are_shared_rules(self):
        for home in (self.owner, self.root):
            for suppressed in (["device_code"], {"device_code": False}):
                with self.subTest(home=home.name, suppression=type(suppressed).__name__):
                    data = _pool(_row(source="manual:loopback_pkce"))
                    data["suppressed_sources"] = {"openai-codex": suppressed}
                    self.write(home, data)
                    self.assertEqual(self.grant(), _jwt())
            for cooldown in ({MODEL: NOW - 1}, {"other-model": NOW + 900}):
                self.write(home, _pool(_row(model_cooldowns=cooldown)))
                self.assertEqual(self.grant(), _jwt())
            self.write(home, _pool(_row(model_cooldowns={MODEL: NOW + 900})))
            with self.assertRaises(ValueError):
                self.grant()
            self.write(home, _pool(_row(model_cooldowns={MODEL: NOW + 900}), _row("healthy")))
            self.assertEqual(self.grant(), _jwt("healthy"))
            if home == self.owner:
                (home / "auth.json").unlink()

        for home in (self.owner, self.root):
            for until in (None, False, True, "invalid", [], {}, float("inf"), -float("inf"), float("nan")):
                with self.subTest(source=home.name, exact_cooldown=until):
                    (self.owner / "auth.json").unlink(missing_ok=True)
                    self.write(self.root, _pool(_row()))
                    self.assertEqual(self.grant(replace(self.settings, home=self.root)), _jwt())
                    row = _row("benched", model_cooldowns={MODEL: until})
                    data = _singleton("must-not-revive")
                    data.update(_pool(row))
                    self.write(home, data)
                    self.assertEqual(self.root_reads(lambda: self.assertRaises(ValueError, self.grant)),
                                     [] if home == self.owner else [self.root / "auth.json"])
                    # Nonfinite JSON is refused by the reader too; check row eligibility independently.
                    self.assertFalse(self.api._codex_row_ready(row, self.settings, NOW))
            for changes in ({}, {"model_cooldowns": None}, {"model_cooldowns": {}},
                            {"model_cooldowns": {MODEL: NOW}}, {"model_cooldowns": {MODEL: NOW - 0.5}},
                            {"model_cooldowns": {"other-model": NOW + 900}},
                            {"model_cooldowns": {"other-model": None}}):
                with self.subTest(source=home.name, lawful_cooldown=changes):
                    (self.owner / "auth.json").unlink(missing_ok=True)
                    self.write(home, _pool(_row("eligible", **changes)))
                    self.assertEqual(self.grant(), _jwt("eligible"))
            for until in (None, NOW + 900):
                with self.subTest(source=home.name, eligible_pool_sibling_after=until):
                    (self.owner / "auth.json").unlink(missing_ok=True)
                    data = _singleton("must-not-revive")
                    data.update(_pool(_row("benched", model_cooldowns={MODEL: until}), _row("eligible")))
                    self.write(home, data)
                    self.assertEqual(self.grant(), _jwt("eligible"))

    def test_selected_credential_metadata_cannot_reroute_proxy_to_official(self):
        changes = ({"base_url": "https://proxy.invalid/codex"},
                   {"inference_base_url": "https://proxy.invalid/codex"},
                   {"base_url": "https://chatgpt.com.evil.invalid/backend-api/codex"},
                   {"base_url": "https://chatgpt.com/backend-api/codex?x=1"},
                   {"provider": "openrouter"}, {"source": "model_config"},
                   {"source": "manual:api_key"}, {"auth_mode": "api_key"},
                   {"issuer": "https://proxy.invalid"}, {"iss": None},
                   {"access_token": _jwt(iss="https://proxy.invalid")})
        for home in (self.owner, self.root):
            for change in changes:
                with self.subTest(home=home.name, field=list(change)):
                    self.write(home, _pool(_row(**change)))
                    with self.assertRaises(ValueError):
                        self.grant()
                    self.write(home, _singleton(tokens=_row(**change)) if "access_token" in change
                               else _singleton(**change))
                    with self.assertRaises(ValueError):
                        self.grant()
            # Legacy official singleton without optional source/URL metadata stays compatible.
            self.write(home, {"providers": {"openai-codex": {"auth_mode": "chatgpt", "tokens": {
                "access_token": "synthetic-opaque", "refresh_token": "synthetic-refresh", "expires_at": NOW + 99}}}})
            self.assertEqual(self.grant(), "synthetic-opaque")
            if home == self.owner:
                (home / "auth.json").unlink()

    def test_atomic_rotation_reads_fresh_shared_snapshot_without_owner_mutation(self):
        first = (self.root / "auth.json").read_bytes()
        owners = (self.settings, replace(self.settings, home=self.other))
        for settings in owners:
            self.assertEqual(self.grant(settings), _jwt())
            self.assertEqual(settings.home, self.owner if settings is self.settings else self.other)
        self.assertEqual((self.root / "auth.json").read_bytes(), first)
        pending = self.root / "native-rotation.synthetic"
        pending.write_text(json.dumps(_pool(_row("rotated"))), encoding="utf-8")
        pending.replace(self.root / "auth.json")  # Authored replacement, not native refresh execution.
        second = (self.root / "auth.json").read_bytes()
        for settings in owners:
            self.assertEqual(self.grant(settings), _jwt("rotated"))
            self.assertEqual(list(settings.home.iterdir()), [])
        self.assertEqual((self.root / "auth.json").read_bytes(), second)
        with self.assertRaises(Exception):
            self.settings.home = self.root

    def test_source_root_helper_is_explicit_and_never_guessed(self):
        os.environ["HERMES_HOME"] = str(self.base / "foreign" / "profiles" / "gamma")
        self.assertEqual(self.api.get_default_hermes_root(home=self.owner), self.root)
        self.assertEqual(self.grant(), _jwt())
        # Missing native capability is represented by an absent lexical SOURCE binding,
        # not a fake helper that authorizes a path. Genuine ImportError has a native test.
        actual_source_helper = self.api.get_default_hermes_root
        del self.api.get_default_hermes_root
        with self.assertRaises(NameError):
            self.grant()
        # Default-home identity needs only its first read; no recursive fallback.
        self.api.get_default_hermes_root = actual_source_helper
        (self.root / "auth.json").unlink()
        seen = self.root_reads(lambda: self.assertRaises(ValueError, self.grant, replace(self.settings, home=self.root)))
        self.assertEqual(seen, [self.root / "auth.json"])

    def test_static_readers_callers_and_transport_keep_owner_context(self):
        session = ast.parse(self.raw["extractor.py"])
        graph = ast.parse(self.raw["entity_relation_extractor.py"])
        for tree, name in ((session, "read_extraction_settings"), (graph, "read_graph_extraction_settings")):
            reader = _node(tree, name)
            self.assertTrue(any(isinstance(n, ast.Constant) and n.value == "codex_auth_source" for n in ast.walk(reader)))
            self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                and n.func.id == "_validate_codex_auth_source" for n in ast.walk(reader)))
        content = ast.unparse(_node(session, "_codex_content"))
        for expected in ("_own_codex_grant(settings)", "set_hermes_home_override(settings.home)",
                         "profile_home=str(settings.home)", "max_retries=0"):
            self.assertIn(expected, content)
        self.assertIn("_codex_content(extraction_settings", ast.unparse(_node(graph, "extract_relations")))
        provider = ast.parse(self.raw["__init__.py"])
        jobs = ast.parse(self.raw["background_jobs.py"])
        # Actual untouched callers, without executing package initialization, SQL or jobs.
        self.assertIn("extraction_settings=read_extraction_settings(self.home)", ast.unparse(provider))
        self.assertIn("extraction_settings=module.read_extraction_settings(worker.home)", ast.unparse(jobs))
        self.assertIn("read_graph_extraction_settings(self.home, model_override=override)", ast.unparse(provider))

        def same(node, statement):
            return ast.dump(node) == ast.dump(ast.parse(statement).body[0])

        def plain_try(node):
            return isinstance(node, ast.Try) and not node.handlers and not node.orelse

        def fixture_lifetime(raw):
            # Actual top-level pytest fixture, read/AST only; never import or emulate it.
            fixtures = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == "native"]
            if len(fixtures) != 1:
                return False
            body = fixtures[0].body
            bindings = [i for i, n in enumerate(body)
                        if same(n, "token = constants.set_hermes_home_override(foreign)")]
            if len(bindings) != 1 or bindings[0] != len(body) - 2:
                return False
            outer = body[-1]
            if (not plain_try(outer) or len(outer.body) != 2 or len(outer.finalbody) != 1
                    or not same(outer.finalbody[0], "constants.reset_hermes_home_override(token)")):
                return False
            if not same(outer.body[0], "secret_token = secret_scope.set_secret_scope("
                        "{'HERMES_CODEX_BASE_URL': 'https://foreign.invalid/codex'}, profile_home=str(foreign))"):
                return False
            inner = outer.body[1]
            if (not plain_try(inner) or len(inner.body) != 1 or len(inner.finalbody) != 1
                    or not isinstance(inner.body[0], ast.Expr) or not isinstance(inner.body[0].value, ast.Yield)):
                return False
            checks = inner.finalbody[0]
            expected = ast.parse("assert all(client.is_closed for client in traffic.clients)\n"
                "assert constants.get_hermes_home() == foreign\n"
                "assert secret_scope.current_secret_scope_home() == str(foreign)\n"
                "assert auxiliary_client._current_aux_stream_deadline() is None\n"
                "assert os.environ['HERMES_HOME'] == str(foreign)\n").body
            return (plain_try(checks) and [ast.dump(n) for n in checks.body] == [ast.dump(n) for n in expected]
                    and len(checks.finalbody) == 1
                    and same(checks.finalbody[0], "secret_scope.reset_secret_scope(secret_token)"))

        self.assertTrue(fixture_lifetime(self.raw["test_extractor_shared_codex_auth.py"]))
        self.assertFalse(fixture_lifetime(self.raw["native_baseline_fixture.py"]))


def make_suite(inputs, read_bound, scratch, case_started=None):
    """Use the existing controller's basename inputs, verified reads and scratch."""
    needed = ("extractor.py", "entity_relation_extractor.py", "__init__.py", "background_jobs.py",
              "hermes_constants.py", "auth_constants.py", "codex_headers.py",
              "test_extractor_shared_codex_auth.py", "native_baseline_fixture.py")
    paths = {name: str(Path(inputs[name])) for name in needed}
    raw = {name: read_bound(paths[name]) for name in needed}
    for name, expected in CORE_SOURCE_PINS.items():
        if hashlib.sha256(raw[name]).hexdigest() != expected:
            raise ValueError("native_helper_SOURCE_pin_mismatch")
    if hashlib.sha256(raw["native_baseline_fixture.py"]).hexdigest() != (
            "29d91b027350eb5769e1d654b14e74147d858a2d4278da0ab5560387ffba9694"):
        raise ValueError("native_fixture_baseline_SOURCE_pin_mismatch")
    cls = SharedCodexAuthSourceTests
    cls.paths, cls.raw, cls.scratch = paths, raw, Path(scratch)
    cls.case_started = staticmethod(case_started) if case_started is not None else None
    return unittest.defaultTestLoader.loadTestsFromTestCase(cls)


if __name__ == "__main__":
    if not all(name in globals() for name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound")):
        raise SystemExit("requires separately admitted stdlib SOURCE controller")
    suite = make_suite(DEVTOOLS_INPUTS, devtools_read_bound, DEVTOOLS_SCRATCH, devtools_case_started)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"scope": "SOURCE_EXTRACTED_AUTH_WITH_SYNTHETIC_FILES_CLOCK",
                      "main_cases": outcome.testsRun, "failures": len(outcome.failures),
                      "errors": len(outcome.errors), "native_SDK_SQL_HTTP_model": "NOT_RUN"}))
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
