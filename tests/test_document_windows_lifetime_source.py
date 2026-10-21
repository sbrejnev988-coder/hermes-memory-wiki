"""NON-NATIVE lifetime/oracle regression; execute only via devtools/harness.py.

Exact small product carriers, not a full-module/native import. All OS roles below
are explicitly synthetic. Local __import__ dependency injection never touches
sys.modules, global builtins, Core or the unchanged SOURCE audit envelope.
"""
from __future__ import annotations

import ast
import builtins
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import sys
import types
import unittest

ROSTER = (
    "test_01_exact_binding_static",
    "test_02_healthy_and_preacquire_source",
    "test_03_postacquire_lifetime_source",
    "test_04_acquire_refusals_source",
    "test_05_native_refusal_oracle_source",
    "test_06_simultaneous_cascade_source",
)
PINS = {
    "candidate": "da2637d031556dfe82688ebed0118428cbad19a9fd67d7fc33de9eb240b5833f",
    "b0cd": "46672a02467ac0aa4b801299f88c89ccb3d4daf973f0693cb040d996bedd5f6b",
    "e6": "c6beb960d1b45f34bce220325ccc5bebe667f44a1cca7579f62931b89132ebb0",
}
PRODUCT_SHA = "09d4dbd04d258f692b57884b8aaca157c3aaf1fcdfba4542044fc3ab29a6b68c"
SOURCES = {}
OBSERVATIONS = []


class FatalLifetime(BaseException):
    pass


def variant(label, **observation):
    if len(OBSERVATIONS) >= 64 or any(r["id"] == label for r in OBSERVATIONS):
        raise AssertionError("synthetic_variant_cap_or_duplicate")
    OBSERVATIONS.append(dict(id=label, **observation))


class Lifetime:
    """Logical lease observer only: no DLL, Win32, CRT or real FD operation."""
    def __init__(self, point=None, primary=None, *, invalid=False, attrs=0,
                 info_ok=True, root_ok=True):
        self.point, self.primary = point, primary
        self.invalid, self.attrs = invalid, attrs
        self.info_ok, self.root_ok = info_ok, root_ok
        self.events = []
        self.raw_owned = self.crt_owned = False
        self.closes = self.acquires = self.transfers = 0
        self.create_args = self.transfer_args = None
        state = self

        class Handle(int):
            def __eq__(self, other):
                state.events.append("postacquire-compare")
                state.fault("compare")
                return int.__eq__(self, other)

            def __ne__(self, other):
                return int.__ne__(self, other)

        class Structure:
            def __init__(self):
                state.events.append("info-constructor")
                state.fault("info-constructor")
                self.dwFileAttributes = state.attrs

        class Function:
            def __init__(self, target):
                self.target = target

            def __call__(self, *args):
                return self.target(*args)

        self.handle = Handle(123)
        kernel = types.SimpleNamespace(CreateFileW=Function(self.create),
            GetFileInformationByHandle=Function(self.get_info), CloseHandle=Function(self.close))
        wintypes = types.SimpleNamespace(**{name: object for name in
            ("DWORD", "FILETIME", "LPCWSTR", "LPVOID", "HANDLE", "BOOL")})

        def library(name, *, use_last_error):
            if name != "kernel32" or use_last_error is not True:
                raise AssertionError("literal_library_contract")
            return kernel

        self.dependencies = {
            "ctypes": types.SimpleNamespace(Structure=Structure, WinDLL=library,
                POINTER=lambda value: object, byref=lambda value: value,
                c_void_p=self.sentinel, WinError=self.win_error,
                get_last_error=lambda: 2, wintypes=wintypes),
            "msvcrt": types.SimpleNamespace(open_osfhandle=self.transfer),
        }

    def fault(self, point):
        if self.point == point:
            raise self.primary

    def sentinel(self, value):
        self.events.append("sentinel")
        self.fault("sentinel")
        if value != -1:
            raise AssertionError("invalid_sentinel_literal")
        return types.SimpleNamespace(value=-1)

    @staticmethod
    def win_error(code):
        error = OSError("synthetic Win32 error")
        error.winerror = code
        return error

    def create(self, *args):
        self.events.append("acquire-entry")
        self.create_args = args
        self.fault("acquire")  # before-effect refusal; lost-return is NOT proved
        if self.invalid:
            return -1
        self.acquires += 1
        self.raw_owned = True
        return self.handle

    def get_info(self, handle, info):
        self.events.append("get-info")
        if handle is not self.handle or not self.raw_owned:
            raise AssertionError("synthetic_info_owner")
        self.fault("get-info")
        return self.info_ok

    def final(self, handle):
        self.events.append("final-path")
        self.fault("final")
        if handle is not self.handle:
            raise AssertionError("synthetic_final_owner")
        return "synthetic-final-path"

    def root(self, path):
        self.events.append("root-check")
        self.fault("root")
        if path != "synthetic-final-path":
            raise AssertionError("synthetic_root_input")
        return self.root_ok

    def transfer(self, handle, flags):
        self.events.append("CRT-entry")
        self.fault("handoff")
        if handle is not self.handle or not self.raw_owned:
            raise AssertionError("synthetic_transfer_owner")
        self.transfer_args = (int(handle), flags)
        self.transfers += 1
        self.raw_owned, self.crt_owned = False, True
        return 456

    def close(self, handle):
        self.events.append("raw-close")
        if handle is not self.handle or not self.raw_owned or self.closes:
            raise AssertionError("invalid_unacquired_or_double_close")
        self.closes += 1
        self.raw_owned = False
        return 1

    def function(self, source="candidate"):
        # Imports stay in THIS function's builtins namespace, not sys.modules.
        def synthetic_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level or name not in self.dependencies:
                raise AssertionError("undeclared_synthetic_dependency")
            return self.dependencies[name]

        local_builtins = dict(vars(builtins), __import__=synthetic_import)
        namespace = dict(__builtins__=local_builtins, __name__="synthetic_lifetime",
            Path=Path, os=types.SimpleNamespace(O_RDONLY=0, O_BINARY=32768),
            _windows_final_path_from_handle=self.final, _path_within_allowed_roots=self.root)
        exec(compile(SOURCES[source], "<exact-" + source + "-reader>", "exec", dont_inherit=True), namespace)
        return namespace["_open_windows_allowed_file"]


def native_nodes():
    tree = ast.parse(SOURCES["native"])
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DocumentWindowsHandleOwner")
    results = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Results")
    return tree, cls, results


def extracted_fixture(method, namespace):
    """Execute only the exact selected method and existing Results reporter."""
    _, cls, result_node = native_nodes()
    nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method]
    if len(nodes) != 1:
        raise AssertionError("nonunique_native_fixture_method")
    namespace.update(unittest=unittest, Path=Path, json=json, ROOT=Path(__file__).absolute().parents[1])
    exec(compile(ast.Module(body=[*nodes, result_node], type_ignores=[]),
                 "<exact-native-fixture-method>", "exec", dont_inherit=True), namespace)
    receiver = type("SyntheticFixtureReceiver", (unittest.TestCase,), {method: namespace[method]})
    result = namespace["Results"]()
    unittest.TestSuite([receiver(method)]).run(result)
    return result


class DocumentWindowsLifetimeSource(unittest.TestCase):
    def primary(self, state, source="candidate"):
        try:
            state.function(source)("synthetic-input")
        except BaseException as caught:
            self.assertIs(caught, state.primary)
        else:
            self.fail("primary_not_raised")

    def test_01_exact_binding_static(self):
        for name, pin in PINS.items():
            self.assertEqual(hashlib.sha256(SOURCES[name]).hexdigest(), pin)
        self.assertEqual(SOURCES["b0cd"], SOURCES["e6"].replace(
            b"    except Exception:\n", b"    except BaseException:\n"))
        tree, cls, _ = native_nodes()
        candidate_sha = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "CANDIDATE_MODULE_SHA256" for t in n.targets))
        self.assertEqual(candidate_sha, PRODUCT_SHA)
        setup = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "setUpClass")
        expected = next(n.value for n in setup.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "expected" for t in n.targets))
        self.assertEqual(eval(compile(ast.Expression(expected), "<exact-native-inverse>", "eval"),
                              {}, {"fixture": SOURCES["e6"]}), SOURCES["candidate"])
        reader = ast.parse(SOURCES["candidate"]).body[0]
        owner = next(n for n in reader.body if isinstance(n, ast.Try))
        self.assertIsInstance(owner.handlers[0].type, ast.Name)
        self.assertEqual(owner.handlers[0].type.id, "BaseException")
        acquire = next(n for n in owner.body if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
            and n.value.func.id == "create_file")
        compare = next(n for n in owner.body if isinstance(n, ast.If))
        sentinel = next(n for n in reader.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "invalid" for t in n.targets))
        unacquired = next(n for n in reader.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "handle" for t in n.targets))
        self.assertIsNone(unacquired.value.value)
        self.assertLess(sentinel.lineno, unacquired.lineno)
        self.assertLess(unacquired.lineno, owner.lineno)
        self.assertLess(acquire.lineno, compare.lineno)
        self.assertIsInstance(owner.body[-1], ast.Return)
        self.assertIsInstance(owner.handlers[0].body[0], ast.If)

    def test_02_healthy_and_preacquire_source(self):
        healthy = Lifetime()
        self.assertEqual(healthy.function()("synthetic-input"), 456)
        self.assertEqual(healthy.create_args,
            ("synthetic-input", 0x80000000, 0x00000001, None, 3, 0x08200080, None))
        self.assertEqual(healthy.transfer_args, (123, 32768))
        self.assertEqual((healthy.acquires, healthy.transfers, healthy.closes), (1, 1, 0))
        self.assertFalse(healthy.raw_owned)
        self.assertTrue(healthy.crt_owned)
        self.assertEqual(healthy.events[:2], ["sentinel", "acquire-entry"])
        variant("healthy-transfer", logical_CRT_owner=True, raw_closes=0)
        for kind in (RuntimeError, FatalLifetime, KeyboardInterrupt, SystemExit):
            state = Lifetime("sentinel", kind("synthetic exact primary"))
            self.primary(state)
            self.assertEqual((state.acquires, state.closes), (0, 0))
            self.assertNotIn("acquire-entry", state.events)
            variant("preacquire-sentinel." + kind.__name__, acquired=0, raw_closes=0)
        baseline = Lifetime("sentinel", RuntimeError("baseline sentinel primary"))
        self.primary(baseline, "b0cd")
        self.assertEqual((baseline.acquires, baseline.closes), (1, 0))
        self.assertTrue(baseline.raw_owned)
        variant("b0cd-expected-sentinel-window", expected_logical_violation=True,
                physical_HANDLE_leak="UNKNOWN")

    def test_03_postacquire_lifetime_source(self):
        for point in ("compare", "info-constructor", "get-info", "final", "root", "handoff"):
            for kind in (RuntimeError, FatalLifetime, KeyboardInterrupt, SystemExit):
                state = Lifetime(point, kind("synthetic exact primary"))
                self.primary(state)
                self.assertEqual((state.acquires, state.closes, state.transfers), (1, 1, 0))
                self.assertFalse(state.raw_owned)
                self.assertEqual(state.events[-1], "raw-close")
                variant("postacquire." + point + "." + kind.__name__,
                        primary_identity=True, logical_raw_closes=1)
        baseline = Lifetime("compare", RuntimeError("baseline postacquire compare"))
        self.primary(baseline, "b0cd")
        self.assertTrue(baseline.raw_owned)
        self.assertEqual(baseline.closes, 0)
        variant("b0cd-expected-compare-window", expected_logical_violation=True,
                physical_HANDLE_leak="UNKNOWN")

    def test_04_acquire_refusals_source(self):
        for kind in (RuntimeError, FatalLifetime, KeyboardInterrupt, SystemExit):
            state = Lifetime("acquire", kind("synthetic before-effect refusal"))
            self.primary(state)
            self.assertEqual((state.acquires, state.closes, state.transfers), (0, 0, 0))
            variant("acquire-before-effect." + kind.__name__, logical_raw_closes=0)
        for label, options, error, message, acquired in (
            ("invalid-handle", dict(invalid=True), OSError, None, 0),
            ("get-info-false", dict(info_ok=False), OSError, None, 1),
            ("directory", dict(attrs=0x10), ValueError, "opened document is a directory or reparse point", 1),
            ("reparse", dict(attrs=0x400), ValueError, "opened document is a directory or reparse point", 1),
            ("outside-roots", dict(root_ok=False), ValueError, "opened document target escaped allowed roots", 1),
        ):
            state = Lifetime(**options)
            with self.assertRaises(error) as caught:
                state.function()("synthetic-input")
            if message is None:
                self.assertEqual(caught.exception.winerror, 2)
            else:
                self.assertEqual(str(caught.exception), message)
            self.assertEqual((state.acquires, state.closes, state.transfers), (acquired, acquired, 0))
            self.assertFalse(state.raw_owned)
            variant("refusal." + label, logical_acquires=acquired, logical_raw_closes=acquired)

    def test_05_native_refusal_oracle_source(self):
        method = "test_06_native_refusal_paths_and_closure"
        for mode in ("healthy", "directory-value", "missing-parent", "audit", "wrong-value", "wrong-winerror"):
            fence = types.SimpleNamespace(expected_reason=None, denials=[])
            session = types.SimpleNamespace(other="outside", missing="missing", directory="directory", fence=fence)

            def allowed(path):
                raise ValueError("synthetic validated refusal")

            session.product = types.SimpleNamespace(_allowed_path=allowed, _open_windows_allowed_file=object())
            session.oracle = types.SimpleNamespace(state=lambda handle, identity: {"state": "closed"})

            class Call:
                def __init__(self, function, path):
                    self.path, self.fd = path, None
                    self.row = dict(handle=101 if path == "outside" else None, identity=[101], transfer_admissions=0)

                @contextmanager
                def observe(self, *args):
                    yield self

                def function(self, path):
                    if mode == "audit":
                        raise PermissionError("synthetic audit denial, no winerror")
                    if mode == "wrong-value":
                        raise ValueError("unrelated error")
                    if mode == "wrong-winerror":
                        raise Lifetime.win_error(999)
                    if path == "outside":
                        raise ValueError("opened document target escaped allowed roots")
                    if mode == "directory-value" and path == "directory":
                        raise ValueError("opened document is a directory or reparse point")
                    raise Lifetime.win_error(3 if path == "missing" and mode == "missing-parent"
                                             else 2 if path == "missing" else 5)

            def denied_open(*args):
                if args != (123456, "rb") or fence.expected_reason != "integer_fd_open":
                    raise AssertionError("synthetic_audit_control")
                raise PermissionError("integer_fd_open")

            result = extracted_fixture(method, dict(SESSION=session, NativeCall=Call,
                open=denied_open, sys=types.SimpleNamespace(stderr=io.StringIO(), base_prefix=sys.base_prefix)))
            rows = result.rows[0]["subcase_results"]
            natives = [r for r in rows if ".native." in r["id"]]
            self.assertEqual(len(rows), 7)
            self.assertEqual(len(natives), 3)
            good = mode in ("healthy", "directory-value", "missing-parent")
            self.assertEqual(result.wasSuccessful(), good)
            self.assertEqual(result.rows[0]["outcome"], "passed" if good else "failed")
            self.assertTrue(all(r["outcome"] == ("passed" if good else "failed") for r in natives))
            self.assertEqual(result.errors, [])
            self.assertEqual(len(result.failures), 0 if good else 3)
            self.assertIsNone(fence.expected_reason)
            variant("native-oracle." + mode, actual_nested_unittest=True,
                    fixture_outcome=result.rows[0]["outcome"], synthetic_native_subtests=len(natives),
                    nested_cases=result.rows, nested_failures=len(result.failures), nested_errors=len(result.errors))

    def test_06_simultaneous_cascade_source(self):
        method = "test_08_two_simultaneous_owned_readers"
        payload = b"new synthetic Windows document\r\n\x00owned bytes\n"
        for failures in ((), (0,), (1,), (0, 1)):
            fds, live, events, observations = set(), set(), [], []
            fence = types.SimpleNamespace(fds=fds, active=None)
            session = types.SimpleNamespace(input="synthetic-input", fence=fence,
                product=types.SimpleNamespace(_open_windows_allowed_file=object()))
            calls = []

            def state(handle, identity):
                self.assertEqual(identity, [handle])
                return {"state": "live" if handle in live else "closed"}

            session.oracle = types.SimpleNamespace(state=state)

            def read(fd, size):
                self.assertIn(fd, fds)
                self.assertEqual(size, 4096)
                return payload

            def close(fd):
                self.assertIn(fd, fds)
                live.remove(fd - 200)
                events.append(("close", fd))

            class Call:
                def __init__(self, function, path):
                    self.index = len(calls)
                    calls.append(self)
                    self.row = dict(handle=100 + self.index, identity=[100 + self.index], transfer_admissions=0)

                @contextmanager
                def observe(self, main, label, *, retain_return):
                    if not retain_return:
                        raise AssertionError("healthy_retained_owner_contract")
                    fence.active = self.row
                    try:
                        yield self
                    finally:
                        fence.active = None

                def function(self, path):
                    if self.index in failures:
                        raise PermissionError("synthetic prior acquisition refusal")
                    fd = 300 + self.index
                    live.add(self.row["handle"])
                    fds.add(fd)
                    self.row["transfer_admissions"] = 1
                    events.append(("acquire", len(live)))
                    return fd

            result = extracted_fixture(method, dict(SESSION=session, NativeCall=Call,
                os=types.SimpleNamespace(read=read, close=close), PAYLOAD=payload, OBSERVATIONS=observations,
                sys=types.SimpleNamespace(stderr=io.StringIO(), base_prefix=sys.base_prefix,
                                           setprofile=lambda value: events.append(("profile-reset", value)))))
            self.assertEqual(result.testsRun, 1)
            self.assertEqual(len(result.rows), 1)
            row = result.rows[0]
            self.assertEqual(row["outcome"], "error" if failures else "passed")
            self.assertEqual(result.wasSuccessful(), not failures)
            self.assertEqual(len(result.errors), len(failures))
            self.assertEqual(result.failures, [])
            self.assertNotEqual(row.get("error_type"), "IndexError")
            self.assertTrue(all(error == "PermissionError" for _, error in result.errors))
            self.assertEqual([r["outcome"] for r in row["subcase_results"]],
                             ["error" if i in failures else "passed" for i in range(2)])
            self.assertEqual(fds, set())
            self.assertEqual(live, set())
            self.assertIsNone(fence.active)
            self.assertEqual(sum(e[0] == "close" for e in events), 2 - len(failures))
            if not failures:
                self.assertIn(("acquire", 2), events)
                self.assertEqual(len(observations), 2)
                self.assertTrue(all(o["before_emergency_cleanup"]["state"] == "closed"
                                    and o["fixture_emergency_cleanup"] is False for o in observations))
            variant("simultaneous." + ("healthy" if not failures else "fail-" + "-".join(map(str, failures))),
                    actual_nested_unittest=True, fixture_outcome=row["outcome"],
                    retained_acquisition_errors=len(result.errors), cascading_IndexError=False,
                    logical_remaining_owners=0, nested_cases=result.rows,
                    nested_error_types=[error for _, error in result.errors])


def main():
    if "devtools_read_bound" not in globals():
        raise RuntimeError("explicit_canonical_SOURCE_envelope_required")
    forbidden = {"ctypes", "_ctypes", "msvcrt"}
    if forbidden.intersection(sys.modules):
        raise AssertionError("unexpected_actual_native_module")
    for key, name in (("candidate", "document_windows_lifetime_candidate.py.txt"),
                      ("b0cd", "document_windows_lifetime_b0cd.py.txt"),
                      ("e6", "document_windows_handle_owner_baseline.py.txt"),
                      ("native", "test_document_windows_handle_owner.py")):
        SOURCES[key] = devtools_read_bound(DEVTOOLS_INPUTS[name])
    _, _, result_node = native_nodes()
    namespace = dict(unittest=unittest, sys=sys, Path=Path, json=json,
                     ROOT=Path(__file__).absolute().parents[1])
    exec(compile(ast.Module(body=[result_node], type_ignores=[]), "<exact-native-Results>", "exec"), namespace)
    result = namespace["Results"]()
    unittest.TestSuite(DocumentWindowsLifetimeSource(name) for name in ROSTER).run(result)
    cases = result.rows
    good = (result.wasSuccessful() and [r["id"] for r in cases] == list(ROSTER)
            and all(r["outcome"] == "passed" for r in cases)
            and not forbidden.intersection(sys.modules) and len(OBSERVATIONS) <= 64)
    report = dict(schema="memory-stack.cases/v1", cases=cases, observations=OBSERVATIONS,
        total=len(cases), passed=sum(r["outcome"] == "passed" for r in cases),
        failed=sum(r["outcome"] == "failed" for r in cases), errors=sum(r["outcome"] == "error" for r in cases),
        skipped=sum(r["outcome"] == "skipped" for r in cases), synthetic_variants=len(OBSERVATIONS),
        expected_b0cd_logical_violations=sum(r.get("expected_logical_violation", False) for r in OBSERVATIONS),
        actual_native_imports=False, process_children_inside_cases=0, SQL_SDK_network_live="NOT_RUN",
        Native_Windows_component_FULL="UNKNOWN", physical_HANDLE_FD_closure="UNKNOWN",
        scope="NON_NATIVE_SOURCE_ONLY", finished=True)
    sys.stdout.write(json.dumps(report, separators=(",", ":"), ensure_ascii=True) + "\n")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
