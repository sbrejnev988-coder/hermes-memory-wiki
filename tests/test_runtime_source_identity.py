"""Focused SOURCE unit packet; no provider/Core/SDK bootstrap or stand-ins.

Use exact CodeTypes from a full-source compile, not recompiled sliced AST.
Small real imported fixture modules exercise the import binding; the two real
identity producer bodies run against an explicitly synthetic SQLite owner.
These tests do not execute the whole plugin's native import/manager lifecycle.
"""
from __future__ import annotations

import ast
import builtins
import contextvars
import functools
import hashlib
import importlib.util
import inspect
import json
import marshal
import os
from pathlib import Path
import sqlite3
import stat
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock
import zlib

# A real CPython audit observer, left installed and inert outside each owned
# observation. Calibration proves the three offending getters are not hidden.
AUDIT = {"mode": None, "events": [], "refusals": 0}
OBSERVATIONS = {}


def identity_audit_observer(event, args):
    mode = AUDIT["mode"]
    if mode is None:
        return
    sensitive = event == "object.__getattr__" and len(args) > 1 and args[1] in (
        "__code__", "__defaults__", "__kwdefaults__")
    if mode == "refuse_introspection" and not sensitive:
        return
    if len(AUDIT["events"]) < 32:
        AUDIT["events"].append((event, args[1] if sensitive else None))
    if mode in ("refuse", "refuse_introspection"):
        AUDIT["refusals"] += 1
        raise RuntimeError("source_identity_owned_audit_refusal")


sys.addaudithook(identity_audit_observer)

SOURCE = Path(__file__).resolve().parents[1] / "__init__.py"
if "DEVTOOLS_INPUTS" in globals():
    RAW = zlib.decompress(devtools_read_bound(DEVTOOLS_INPUTS["entrypoint.zlib"]))
else:
    RAW = SOURCE.read_bytes()
COMPILED = compile(RAW, str(SOURCE), "exec", dont_inherit=True, optimize=sys.flags.optimize)


def code_at(qualname, code=COMPILED):
    found = []
    def visit(node):
        if getattr(node, "co_qualname", node.co_name) == qualname:
            found.append(node)
        for item in node.co_consts:
            if type(item) is types.CodeType:
                visit(item)
    visit(code)
    assert len(found) == 1, (qualname, len(found))
    return found[0]


IMPL = {"__name__": "runtime_source_identity_unit_impl", "Path": Path,
        "MappingProxyType": types.MappingProxyType, "CodeType": types.CodeType,
        "FunctionType": types.FunctionType, "ModuleType": types.ModuleType,
        "struct": struct, "sys": sys, "os": os, "stat": stat, "hashlib": hashlib}
for name in ("_source_code_content", "_pin_loaded_source_identity"):
    IMPL[name] = types.FunctionType(code_at(name), IMPL, name)
project = IMPL["_source_code_content"]
pin = IMPL["_pin_loaded_source_identity"]

# CPython 3.14 emits annotation thunks; they must not run during attestation.
FIXTURE = b'''def target(value: annotation_probe() = 2, *, option=True):
    return (value, option, (1, "fixture"), frozenset({1, 2}))
class Witness:
    def method(self, value=3):
        return value
    @staticmethod
    def static(value=4):
        return value
    @property
    def prop(self):
        return 5
capture = sys._getframe().f_code
'''


class SourceIdentityCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="source-identity-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.modules = []
        self.addCleanup(self.remove_modules)
        self.path = self.root / "entry.py"
        self.path.write_bytes(FIXTURE)
        name = "identity_fixture_" + self._testMethodName
        self.module = types.ModuleType(name)
        self.module.__file__ = str(self.path)
        self.module.__spec__ = importlib.util.spec_from_file_location(name, self.path)
        self.module.sys = sys
        self.annotation_calls = []
        self.module.annotation_probe = lambda: self.annotation_calls.append(True) or int
        code = compile(FIXTURE, str(self.path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
        exec(code, self.module.__dict__)
        self.assertIs(self.module.capture, code)
        self.code = code
        self.namespace = self.module.__dict__
        # Use actual source producer bodies, without calling any native provider.
        self.namespace.update(_IMPORT_HERMES_HOME=self.root, _native_home=lambda: self.root,
            _REQUEST_HOME=contextvars.ContextVar("identity_owner", default=None),
            _QDRANT_PROFILE_SCOPE=contextvars.ContextVar("identity_config", default=None),
            _LOADED_CODE_IDENTITY="unit-observed-marshal-metadata", _EMBED_PROFILE_STATES={},
            _RERANK_DEFAULT_STATE={}, _RERANK_PROFILE_STATES={}, _OPENROUTER_HEALTH_CACHE={},
            _OPENROUTER_HEALTH_BY_PROFILE={}, _profile_configuration_generation=lambda: "unit-generation",
            Path=Path, sqlite3=sqlite3, ModuleType=types.ModuleType)
        self.identity = types.FunctionType(code_at("MemoryWikiProvider._runtime_identity"), self.namespace)
        self.context = types.FunctionType(code_at("MemoryWikiProvider._disclosure_context"), self.namespace)
        self.context.__kwdefaults__ = {"terminal": False}
        self.owner = types.SimpleNamespace(home=self.root, db_path=self.root / "identity.sqlite3")
        self.owner._conn = sqlite3.connect(self.owner.db_path)
        self.addCleanup(self.owner._conn.close)
        self.owner._runtime_identity = lambda: self.identity(self.owner)
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)

    def remove_modules(self):
        for name in self.modules:
            sys.modules.pop(name, None)

    def both(self):
        normal = self.identity(self.owner)
        authority_normal, before = self.context(self.owner)
        terminal, generation = self.context(self.owner, terminal=True)
        self.assertEqual(normal, authority_normal)
        self.assertEqual(normal, terminal)
        self.assertEqual(before, generation)
        self.assertEqual(json.dumps(authority_normal, sort_keys=True), json.dumps(terminal, sort_keys=True))
        self.assertEqual(generation, ("unit-generation", 0, 0, 0))
        self.assertIs(normal["conn_path_matches"], True)
        return normal

    def assert_status(self, status, reason=None):
        identity = self.both()
        self.assertEqual(identity["loaded_source_binding"]["status"], status)
        self.assertIs(identity["loaded_source_revision_known"], False)
        self.assertIs(identity["loaded_source_binding"]["current_callable_fields_known"], False)
        self.assertIs(identity["loaded_source_binding"]["import_snapshot_known"], status in ("import_snapshot", "drifted"))
        if reason:
            self.assertEqual(identity["loaded_source_binding"]["reason"], reason)
        return identity["loaded_source_binding"]

    def test_healthy_registered_module_binding(self):
        sys.modules[self.module.__name__] = self.module
        self.modules.append(self.module.__name__)
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        report = self.assert_status("import_snapshot", "current_callable_fields_not_checked")
        self.assertEqual(report["version"], 2)
        self.assertEqual(report["observation"], "import_time")
        self.assertEqual(report["unchecked_callable_fields"], ("code", "defaults", "kwdefaults_binding", "annotation_binding"))
        self.assertEqual(report["source_sha256"], hashlib.sha256(FIXTURE).hexdigest())
        self.assertEqual(report["revision_kind"], "code_matched_source_sha256")
        self.assertEqual(report["scope"], "compiled_entrypoint")
        self.assertIsNone(report["git_revision"])
        self.assertFalse(report["full_bundle_known"])
        self.assertFalse(report["exact_loader_bytes_known"])
        self.assertEqual(report["disk_freshness"], "not_checked_after_import")
        json.dumps(self.both())

    def test_unregistered_module_proxy_contract(self):
        proxy = types.FunctionType(code_at("_RuntimeModuleProxy.__getattr__"), self.namespace)
        self.assertIs(proxy(None, "target"), self.module.target)
        self.assert_status("import_snapshot")

    def test_same_file_wrong_registered_module_refuses_before_source_read(self):
        foreign = types.ModuleType(self.module.__name__)
        foreign.__file__ = self.module.__file__
        sys.modules[self.module.__name__] = foreign
        self.modules.append(self.module.__name__)
        with mock.patch.object(os, "open", side_effect=AssertionError("unexpected source read")):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "module_registration_mismatch")

    def test_registered_module_replaced_after_import_drifts(self):
        sys.modules[self.module.__name__] = types.ModuleType(self.module.__name__)
        self.modules.append(self.module.__name__)
        self.assert_status("drifted", "runtime_binding_changed")

    def test_source_changed_before_attestation_is_not_loaded_proof(self):
        self.path.write_bytes(FIXTURE.replace(b"return 5", b"return 6"))
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        report = self.assert_status("unavailable", "compiled_entrypoint_mismatch")
        self.assertIsNone(report["source_sha256"])

    def test_source_replaced_after_import_retains_old_loaded_binding(self):
        old = self.assert_status("import_snapshot")
        self.path.write_bytes(FIXTURE.replace(b"return 5", b"return 6"))
        with mock.patch.object(os, "open", side_effect=AssertionError("request re-read source")):
            self.assertEqual(self.assert_status("import_snapshot"), old)

    def test_source_removed_after_import_does_not_invent_new_revision(self):
        old = self.assert_status("import_snapshot")
        self.path.unlink()
        self.assertEqual(self.assert_status("import_snapshot"), old)

    def test_missing_source_refuses(self):
        self.path.unlink()
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "source_missing")

    def test_nonregular_source_refuses(self):
        self.path.unlink()
        self.path.mkdir()
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "source_not_regular")

    def test_unreadable_source_reports_safe_reason(self):
        with mock.patch.object(os, "open", side_effect=PermissionError("synthetic-private-detail")):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        report = self.assert_status("unavailable", "source_read_refused")
        self.assertNotIn("synthetic-private-detail", json.dumps(report))

    def test_source_changed_during_read_refuses(self):
        real = os.fstat
        calls = []
        def observed(fd):
            calls.append(fd)
            if len(calls) == 2:
                self.path.write_bytes(FIXTURE + b"# mutation after sampled read\n")
            return real(fd)
        with mock.patch.object(os, "fstat", side_effect=observed):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "source_changed_during_read")
        self.assertEqual(len(calls), 2)

    def test_wrong_spec_name_refuses(self):
        self.module.__spec__.name += "_wrong"
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "module_spec_mismatch")

    def test_wrong_code_filename_refuses(self):
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code.replace(co_filename="foreign.py"), self.namespace)
        self.assert_status("unavailable", "module_code_identity_unproven")

    def test_runtime_code_drift_preserves_observed_marshal_metadata(self):
        # The original live-code oracle is deliberately NOT claimed: audited
        # current fields are UNKNOWN, while the honest import snapshot survives.
        old = self.assert_status("import_snapshot")
        self.module.target.__code__ = self.module.target.__code__.replace(co_consts=(None, 99))
        self.assertEqual(self.assert_status("import_snapshot", "current_callable_fields_not_checked"), old)
        self.assertEqual(self.both()["loaded_code_identity"], "unit-observed-marshal-metadata")

    def test_runtime_global_callable_replacement_drifts(self):
        self.module.target = lambda value=2: 42
        self.assert_status("drifted")

    def test_runtime_class_descriptor_replacement_drifts(self):
        self.module.Witness.static = staticmethod(lambda value=4: 42)
        self.assert_status("drifted")

    def test_runtime_wrapper_original_replacement_drifts(self):
        text = b'''def original():
    return 1
def wrapper(*, original=original):
    return original()
wrapper.__wrapped__ = original
capture = sys._getframe().f_code
'''
        self.path.write_bytes(text)
        code = compile(text, str(self.path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
        exec(code, self.namespace)
        # Remove the previous fixture's declarations before this new import pin.
        self.namespace.pop("target")
        self.namespace.pop("Witness")
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(code, self.namespace)
        self.assert_status("import_snapshot")
        self.module.wrapper.__dict__["__wrapped__"] = lambda: 2
        self.assert_status("drifted")

    def test_runtime_kwdefault_mutation_drifts(self):
        self.module.target.__kwdefaults__["option"] = False
        self.assert_status("drifted")

    def test_runtime_positional_default_replacement_stays_unknown(self):
        old = self.assert_status("import_snapshot")
        self.module.target.__defaults__ = (7,)
        self.assertEqual(self.assert_status("import_snapshot", "current_callable_fields_not_checked"), old)

    def test_annotation_thunk_not_called_and_current_code_stays_unknown(self):
        if not hasattr(self.module.target, "__annotate__"):
            self.skipTest("annotation thunks are CPython 3.14+")
        self.assertEqual(self.annotation_calls, [])
        annotation = self.module.target.__annotate__
        self.assertIsInstance(annotation, types.FunctionType)
        old = self.assert_status("import_snapshot")
        annotation.__code__ = annotation.__code__.replace(co_consts=annotation.__code__.co_consts + ("drift",))
        self.assertEqual(self.assert_status("import_snapshot", "current_callable_fields_not_checked"), old)
        self.assertEqual(self.annotation_calls, [])

    def test_code_modified_before_import_pin_refuses(self):
        self.module.target.__code__ = self.module.target.__code__.replace(co_consts=(None, 100))
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "runtime_code_not_in_entrypoint")

    def test_identical_payload_different_docs_git_pin_never_claims_commit(self):
        old = self.assert_status("import_snapshot")
        (self.root / "README.md").write_text("authored docs PIN A\n", encoding="utf-8")
        (self.root / "HEAD").write_text("1" * 40, encoding="ascii")
        (self.root / "README.md").write_text("authored docs PIN B\n", encoding="utf-8")
        (self.root / "HEAD").write_text("2" * 40, encoding="ascii")
        self.assertEqual(self.assert_status("import_snapshot"), old)
        self.assertIsNone(old["git_revision"])

    def test_compile_equivalent_comment_bytes_are_explicitly_not_exact_loader_receipt(self):
        self.path.write_bytes(FIXTURE + b"# same compiled code, different raw SHA\n")
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        report = self.assert_status("import_snapshot")
        self.assertNotEqual(report["source_sha256"], hashlib.sha256(FIXTURE).hexdigest())
        self.assertFalse(report["exact_loader_bytes_known"])

    def test_absent_binding_stays_false_with_reason(self):
        self.namespace.pop("_LOADED_SOURCE_BINDING")
        self.assert_status("unavailable", "import_attestation_unavailable")

    def test_audit_observer_and_refusal_are_live(self):
        fields = ("__code__", "__defaults__", "__kwdefaults__")
        AUDIT.update(mode="observe", events=[], refusals=0)
        try:
            for field in fields:
                getattr(self.module.target, field)
        finally:
            AUDIT["mode"] = None
        self.assertEqual(AUDIT["events"], [("object.__getattr__", field) for field in fields])
        hits = 0
        for field in fields:
            AUDIT.update(mode="refuse_introspection", events=[], refusals=0)
            raised = False
            try:
                getattr(self.module.target, field)
            except RuntimeError:
                raised = True
            finally:
                AUDIT["mode"] = None
            self.assertTrue(raised)
            self.assertEqual(AUDIT["events"], [("object.__getattr__", field)])
            self.assertEqual(AUDIT["refusals"], 1)
            hits += AUDIT["refusals"]
        OBSERVATIONS["calibration"] = {"getter_events": len(fields), "refused_getters": hits}

    def observe_producer(self, mode, *, terminal):
        sql = []
        self.owner._conn.set_trace_callback(sql.append)
        AUDIT.update(mode=mode, events=[], refusals=0)
        try:
            identity = self.context(self.owner, terminal=True)[0] if terminal else self.identity(self.owner)
        finally:
            AUDIT["mode"] = None
            OBSERVATIONS[("terminal_" if terminal else "normal_") + mode] = {
                "audit_events": len(AUDIT["events"]), "refusals": AUDIT["refusals"], "sql": list(sql)}
        self.assertEqual(AUDIT["events"], [])
        self.assertEqual(AUDIT["refusals"], 0)
        self.assertEqual(sql, ["PRAGMA database_list"])
        self.assertFalse(identity["loaded_source_revision_known"])
        self.assertEqual(identity["loaded_source_binding"]["status"], "import_snapshot")
        self.assertTrue(identity["loaded_source_binding"]["import_snapshot_known"])
        self.assertEqual(self.annotation_calls, [])
        return identity

    def test_terminal_observer_reports_zero_new_audit_events(self):
        expected = self.identity(self.owner)
        self.assertEqual(self.observe_producer("observe", terminal=True), expected)

    def test_terminal_refusal_hook_has_no_getter_to_refuse(self):
        expected = self.identity(self.owner)
        self.assertEqual(self.observe_producer("refuse", terminal=True), expected)

    def test_normal_observer_and_refusal_match_terminal_snapshot(self):
        observed = self.observe_producer("observe", terminal=False)
        refused = self.observe_producer("refuse", terminal=False)
        terminal, _ = self.context(self.owner, terminal=True)
        self.assertEqual(observed, refused)
        self.assertEqual(refused, terminal)

    def test_import_audit_refusal_is_safe_unavailable_not_current_proof(self):
        AUDIT.update(mode="refuse_introspection", events=[], refusals=0)
        try:
            binding = pin(self.code, self.namespace)
        finally:
            AUDIT["mode"] = None
        self.namespace["_LOADED_SOURCE_BINDING"] = binding
        self.assertEqual(AUDIT["events"], [("object.__getattr__", "__code__")])
        self.assertEqual(AUDIT["refusals"], 1)
        report = self.assert_status("unavailable", "import_introspection_refused")
        self.assertIsNone(report["source_sha256"])
        self.assertNotIn("source_identity_owned_audit_refusal", json.dumps(report))
        OBSERVATIONS["import_refusal"] = {"getter_events": len(AUDIT["events"]), "refusals": AUDIT["refusals"]}

    def test_runtime_kwdefault_object_replacement_stays_unknown(self):
        old = self.assert_status("import_snapshot")
        self.module.target.__kwdefaults__ = {"option": False}
        self.assertEqual(self.assert_status("import_snapshot", "current_callable_fields_not_checked"), old)

    def test_runtime_annotation_binding_replacement_stays_unknown(self):
        if not hasattr(self.module.target, "__annotate__"):
            self.skipTest("annotation thunks are CPython 3.14+")
        old = self.assert_status("import_snapshot")
        self.module.target.__annotate__ = lambda format: int
        self.assertEqual(self.assert_status("import_snapshot", "current_callable_fields_not_checked"), old)
        self.assertEqual(self.annotation_calls, [])

    def test_receipt_is_detached_from_pin(self):
        receipt = self.both()
        receipt["loaded_source_binding"]["status"] = "spoofed"
        self.assert_status("import_snapshot")
        with self.assertRaises(TypeError):
            self.namespace["_LOADED_SOURCE_BINDING"]["report"]["status"] = "spoofed"

    def test_terminal_no_io_no_diagnostic_callback_one_original_pragma(self):
        sql = []
        self.owner._conn.set_trace_callback(sql.append)
        self.owner._runtime_identity = lambda: (_ for _ in ()).throw(AssertionError("diagnostic callback"))
        with mock.patch.object(os, "open", side_effect=AssertionError("terminal open")), \
                mock.patch.object(builtins, "open", side_effect=AssertionError("terminal open")), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("terminal read")):
            identity, _ = self.context(self.owner, terminal=True)
        self.assertFalse(identity["loaded_source_revision_known"])
        self.assertTrue(identity["loaded_source_binding"]["import_snapshot_known"])
        self.assertEqual(sql, ["PRAGMA database_list"])

    def test_late_callable_drift_changes_terminal_anchor(self):
        normal, generation = self.context(self.owner)
        self.module.target.__kwdefaults__["option"] = False
        terminal, after = self.context(self.owner, terminal=True)
        self.assertEqual(generation, after)
        self.assertFalse(normal["loaded_source_revision_known"])
        self.assertFalse(terminal["loaded_source_revision_known"])
        self.assertEqual(normal["loaded_source_binding"]["status"], "import_snapshot")
        self.assertEqual(terminal["loaded_source_binding"]["status"], "drifted")
        self.assertNotEqual(json.dumps(normal, sort_keys=True), json.dumps(terminal, sort_keys=True))

    def test_owner_and_configuration_fields_still_change_at_terminal(self):
        normal, generation = self.context(self.owner)
        self.owner.home = self.root / "foreign"
        self.namespace["_QDRANT_PROFILE_SCOPE"].set({"__semantic_compatible": "0", "__semantic_reason": "unit-refused"})
        terminal, after = self.context(self.owner, terminal=True)
        self.assertEqual(generation, after)
        self.assertNotEqual(normal["provider_home"], terminal["provider_home"])
        self.assertTrue(normal["profile_ready"])
        self.assertFalse(terminal["profile_ready"])
        self.assertEqual(terminal["profile_reason"], "unit-refused")

    def test_environment_cannot_force_true(self):
        self.namespace["_LOADED_SOURCE_BINDING"] = None
        with mock.patch.dict(os.environ, {"LOADED_SOURCE_REVISION_KNOWN": "true", "MEMORY_WIKI_LOADED_SOURCE_REVISION_KNOWN": "1"}):
            self.assert_status("unavailable")

    def test_full_typed_code_fields_not_only_code_equality(self):
        code = self.module.target.__code__
        changes = {"co_argcount": 0, "co_posonlyargcount": 1, "co_kwonlyargcount": 0,
            "co_stacksize": code.co_stacksize + 1, "co_flags": code.co_flags ^ 2,
            "co_code": code.co_code + b"\x09\x00", "co_consts": code.co_consts + ("new",),
            "co_names": code.co_names + ("new",), "co_varnames": code.co_varnames[:-1] + ("new",),
            "co_filename": "other.py", "co_name": "other", "co_qualname": "other.target",
            "co_firstlineno": code.co_firstlineno + 1, "co_linetable": b"", "co_exceptiontable": b"\x00",
            "co_freevars": ("new",), "co_cellvars": ("new",)}
        for field, value in changes.items():
            self.assertNotEqual(project(code), project(code.replace(**{field: value})), field)
        more_locals = code.replace(co_nlocals=code.co_nlocals + 1, co_varnames=code.co_varnames + ("extra",))
        self.assertNotEqual(project(code), project(more_locals))
        self.assertEqual(project(code), project(marshal.loads(marshal.dumps(code))))

    def test_nested_constant_types_slices_float_bits_and_unknown_refusal(self):
        self.assertNotEqual(project((True,)), project((1,)))
        self.assertNotEqual(project(frozenset({True})), project(frozenset({1})))
        self.assertNotEqual(project(slice(1, 2, None)), project(slice(1, 2, 1)))
        self.assertNotEqual(project(-0.0), project(0.0))
        self.assertNotEqual(project(complex(1, -0.0)), project(complex(1, 0.0)))
        nan_a = struct.unpack("!d", bytes.fromhex("7ff8000000000001"))[0]
        nan_b = struct.unpack("!d", bytes.fromhex("7ff8000000000002"))[0]
        self.assertNotEqual(project(nan_a), project(nan_b))
        with self.assertRaises(ValueError):
            project(object())
        self.assertNotEqual(project(self.code), project(self.code.replace(co_consts=self.code.co_consts + ((frozenset({1}), slice(None, 2)),))))

    def test_windows_ctime_domains_do_not_false_refuse_healthy_source(self):
        real = os.fstat
        def handle_domain(fd):
            info = real(fd)
            fields = ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            values = {field: getattr(info, field) for field in fields}
            values["st_ctime_ns"] += 1_000_000  # same stable fd domain, unlike path domain
            return types.SimpleNamespace(**values)
        with mock.patch.object(os, "fstat", side_effect=handle_domain):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("import_snapshot")

    def test_cross_api_physical_identity_mismatch_still_refuses(self):
        real = os.fstat
        def foreign_handle(fd):
            info = real(fd)
            fields = ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            values = {field: getattr(info, field) for field in fields}
            values["st_ino"] += 1
            return types.SimpleNamespace(**values)
        with mock.patch.object(os, "fstat", side_effect=foreign_handle):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "source_changed_during_read")

    def test_source_size_cap_refuses_before_unbounded_read(self):
        real = os.fstat
        def oversized(fd):
            info = real(fd)
            return types.SimpleNamespace(st_mode=info.st_mode, st_size=2_000_001)
        with mock.patch.object(os, "fstat", side_effect=oversized):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "source_size_or_type_unproven")

    def test_runtime_closure_cell_drift_is_retained(self):
        text = FIXTURE + b'''def factory():
    selected = target
    def callback():
        return selected()
    return callback
callback = factory()
'''
        self.path.write_bytes(text)
        code = compile(text, str(self.path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
        exec(code, self.namespace)
        self.namespace["_LOADED_SOURCE_BINDING"] = pin(code, self.namespace)
        self.assert_status("import_snapshot")
        self.module.callback.__closure__[0].cell_contents = lambda: 8
        self.assert_status("drifted")

    def test_actual_python314_slice_code_constant_is_not_discarded(self):
        if sys.version_info < (3, 14):
            self.skipTest("actual compiler slice constants are CPython 3.14+")
        code = compile("def sliced(text):\n    return text[1:5]\n", "owned-slice.py", "exec", dont_inherit=True)
        body = next(item for item in code.co_consts if type(item) is types.CodeType)
        self.assertTrue(any(type(item) is slice for item in body.co_consts))
        constants = tuple(slice(1, 6) if type(item) is slice else item for item in body.co_consts)
        self.assertNotEqual(project(body), project(body.replace(co_consts=constants)))

    def test_fdopen_constructor_refusal_closes_owned_native_descriptor(self):
        real_open = os.open
        descriptors = []
        def owned_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            descriptors.append(fd)
            return fd
        with mock.patch.object(os, "open", side_effect=owned_open), \
                mock.patch.object(os, "fdopen", side_effect=OSError("authored constructor refusal")):
            self.namespace["_LOADED_SOURCE_BINDING"] = pin(self.code, self.namespace)
        self.assert_status("unavailable", "source_binding_unavailable")
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_initializer_uses_actual_executing_module_not_loader_get_code(self):
        tree = ast.parse(RAW)
        last = tree.body[-1]
        self.assertIsInstance(last, ast.Assign)
        self.assertEqual(last.targets[0].id, "_LOADED_SOURCE_BINDING")
        self.assertEqual(ast.unparse(last.value), "_pin_loaded_source_identity(sys._getframe().f_code, globals())")
        helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_pin_loaded_source_identity")
        self.assertNotIn("marshal.dumps", ast.unparse(helper))
        self.assertNotIn("get_code", [getattr(node, "attr", "") for node in ast.walk(helper)])


def run_source_packet():
    rows = []
    loader = unittest.TestLoader()
    for name in loader.getTestCaseNames(SourceIdentityCases):
        case_id = "source_identity." + name.removeprefix("test_")
        devtools_case_started(case_id)
        result = unittest.TestResult()
        SourceIdentityCases(name).run(result)
        outcome = "error" if result.errors else "failed" if result.failures else "skipped" if result.skipped else "passed"
        row = {"id": case_id, "outcome": outcome}
        if result.errors or result.failures:
            # Bounded actual traceback, kept only in this owned SOURCE log.
            row["diagnostic"] = (result.errors + result.failures)[0][1][-4000:]
        rows.append(row)
    counts = {outcome: sum(row["outcome"] == outcome for row in rows) for outcome in ("passed", "failed", "error", "skipped")}
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": rows, "total": len(rows),
        "passed": counts["passed"], "failed": counts["failed"], "errors": counts["error"], "skipped": counts["skipped"],
        "boundary": "SOURCE units, real fixture imports/SQLite only; no native provider or manager bootstrap",
        "observations": OBSERVATIONS,
        "raw_source_sha256": hashlib.sha256(RAW).hexdigest(), "subprocess_invocations": 0}))
    raise SystemExit(1 if counts["failed"] or counts["error"] else 0)


if __name__ == "__main__":
    if "devtools_case_started" in globals():
        run_source_packet()
    else:
        unittest.main()
