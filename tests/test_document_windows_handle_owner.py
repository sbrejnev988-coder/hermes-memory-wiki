"""Genuine Windows early-HANDLE component; inert collection, no SDK/SQL.

Explicit standalone entry: selected Python -I -S -B -u THIS --owned-root NEWDIR.
The supervised entry additionally takes --plan FILE and its SHA256 on stdin.
No external peer/fixture is needed: the exact e6 function ships beside this test.
Ordinary collection is inert; execution requires the explicit offline envelope.
The envelope is for reviewed Python, NOT an OS sandbox or process-tree proof.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import types
import unittest

ROOT = Path(__file__).absolute().parents[1]
FIXTURE = ROOT / "tests/fixtures/document_windows_handle_owner_baseline.py.txt"
BASELINE_COMMIT = "e6e721e0b33b1a6f64b2c4751ed7ffd2a9487ed7"
BASELINE_MODULE_SHA256 = "4a8f993a2ece5a5c2484d2c5e1be1202586fa2c67023fca674678aa53c966524"
BASELINE_FIXTURE_SHA256 = "c6beb960d1b45f34bce220325ccc5bebe667f44a1cca7579f62931b89132ebb0"
CANDIDATE_MODULE_SHA256 = "3640c616f89199def1f9a1cde7ae7aef6530116ee915b7bd6ff941f80c54338f"
ROSTER = (
    "test_01_native_readonly_transfer_and_close",
    "test_02_ordinary_pretransfer_cleanup",
    "test_03_fatal_final_path_cleanup",
    "test_04_fatal_root_check_cleanup",
    "test_05_fatal_handle_to_fd_entry_cleanup",
    "test_06_native_refusal_paths_and_closure",
    "test_07_repeat_healthy_after_fatal",
    "test_08_two_simultaneous_owned_readers",
)
PAYLOAD = b"new synthetic Windows document\r\n\x00owned bytes\n"
OTHER_PAYLOAD = b"new still-owned negative-root document\n"
PUBLIC_FILES = ("document_knowledge_graph.py", "document_extractors.py", "guard.py",
                "tests/test_document_windows_handle_owner.py",
                "tests/fixtures/document_windows_handle_owner_baseline.py.txt")
# Import-time closure seeds of the full standalone product and this fixture.
# The few lazy seeds are source-reviewed ctypes layout / annotations / reporting.
STDLIB_SEEDS = (
    "__future__", "ast", "contextlib", "hashlib", "importlib", "importlib.util",
    "json", "os", "ntpath", "pathlib", "stat", "sys", "types", "unittest",
    "contextvars", "heapq", "re", "sqlite3", "subprocess", "tempfile", "threading",
    "time", "collections", "typing", "csv", "email", "html", "io", "ipaddress",
    "itertools", "mimetypes", "urllib.error", "urllib.parse", "urllib.request",
    "zipfile", "dataclasses", "email.policy", "html.parser", "xml.etree.ElementTree",
    "unicodedata", "ctypes", "ctypes.wintypes", "ctypes._endian", "ctypes._layout",
    "sysconfig", "struct", "msvcrt", "_ctypes", "annotationlib", "inspect",
    "traceback", "linecache", "tokenize", "encodings.utf_8_sig", "encodings.idna",
)
SESSION = None
OBSERVATIONS = []


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def no_links(path):
    path = Path(os.path.abspath(os.fspath(path)))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise PermissionError("reparse_or_link")
    return path


def stdlib_closure(base):
    """Metadata-only static import-time closure; never import ctypes/product.

    Follow imports in module/class/conditional bodies, not arbitrary function
    bodies. Resolve from-import submodules only if actual public files exist.
    The exact returned files, not a directory-prefix grant, are used at runtime.
    """
    base = no_links(base)
    lib = base / "Lib"
    queue, seen, files = list(STDLIB_SEEDS), set(), {}

    def location(name):
        if not name or any(not part.isidentifier() for part in name.split(".")):
            return None
        stem = lib.joinpath(*name.split("."))
        for p in (stem / "__init__.py", stem.with_suffix(".py"), base / "DLLs" / (name + ".pyd")):
            if p.is_file():
                return p
        return None

    def imports(nodes):
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node
            elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for field in ("body", "orelse", "finalbody", "handlers"):
                    yield from imports(getattr(node, field, ()))

    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if len(seen) > 1200:
            raise RuntimeError("stdlib_static_closure_cap")
        for i in range(1, len(name.split("."))):
            queue.append(".".join(name.split(".")[:i]))
        path = location(name)
        if path is None:
            continue  # frozen/builtin/non-Windows optional module, not read authority
        path = no_links(path)
        raw = path.read_bytes()
        files[str(path)] = {"path": str(path), "sha256": sha(raw), "bytes": len(raw),
                            "role": "stdlib-import-time" if path.suffix == ".py" else "native-runtime-extension"}
        if path.suffix != ".py":
            continue
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in imports(ast.parse(raw).body):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names)
            else:
                if node.level:
                    parts = package.split(".") if package else []
                    if node.level > len(parts):
                        continue
                    parent = ".".join(parts[:len(parts) - node.level + 1])
                    module = ".".join(p for p in (parent, node.module) if p)
                else:
                    module = node.module or ""
                queue.append(module)
                queue.extend(module + "." + a.name for a in node.names
                             if a.name != "*" and location(module + "." + a.name) is not None)
    # OS loader dependencies of the selected extensions; read-only provenance,
    # not arbitrary ctypes LoadLibrary authority. Missing files aren't grants.
    for p in [base / "python.exe", base / "python314.dll", base / "python3.dll",
              base / "vcruntime140.dll", base / "vcruntime140_1.dll",
              *(base / "DLLs").glob("*.dll")]:
        if p.is_file():
            raw = no_links(p).read_bytes()
            files[str(p)] = dict(path=str(p), bytes=len(raw), sha256=sha(raw), role="native-runtime-loader")
    return sorted(files.values(), key=lambda r: r["path"])


def fixture_files(work):
    """Only NEW synthetic files. No deletes, retries, symlinks or ambient homes."""
    work = no_links(work)
    work.mkdir(parents=True, exist_ok=False)
    allowed, negative = work / "allowed", work / "negative"
    for directory in (allowed, negative, allowed / "directory", work / "empty-pycache"):
        directory.mkdir()
    for p, payload in ((allowed / "input.txt", PAYLOAD), (negative / "other.txt", OTHER_PAYLOAD)):
        with p.open("xb") as stream:
            stream.write(payload)
    return [allowed / "input.txt", negative / "other.txt"]


class OfflineFence:
    """Exact readonly inputs + reviewed ctypes roles; default deny effects.

    Native _FuncPtr calls do not expose all arguments to Python audit. The exact
    source-bound owning CodeType profile admits paths before CreateFileW, while
    literal arguments remain byte-pinned. This is a trusted-code component fence.
    """
    def __init__(self, rows, work):
        self.work = no_links(work)
        self.reads = {os.path.normcase(r["path"]): r for r in rows}
        self.dirs = {os.path.normcase(str(Path(r["path"]).parent)) for r in rows}
        self.dirs.update(os.path.normcase(str(p)) for p in
                         (ROOT, Path(sys.base_prefix), Path(sys.base_prefix) / "Lib",
                          Path(sys.base_prefix) / "DLLs", self.work / "empty-pycache"))
        self.cache_reads = set()
        sys.pycache_prefix = str(self.work / "empty-pycache")
        for r in rows:
            if r["path"].endswith(".py"):
                self.cache_reads.add(os.path.normcase(importlib.util.cache_from_source(r["path"])))
        self.denials, self.expected_denials, self.native_events = [], [], []
        self.expected_reason = None
        self.active = None
        self.fds = set()
        self.calls = 0
        self.origins = {}
        self.generated = {}
        self.generated_count = 0
        self.stderr_write = sys.stderr.write
        self.allowed_compile_hashes = {r["sha256"] for r in rows if r["path"].endswith((".py", ".txt"))}

    def deny(self, event, reason, path=None):
        row = {"event": event[:80], "reason": reason}
        if type(path) is str:
            p = Path(path)
            for root, role in ((ROOT, "public-source"), (Path(sys.base_prefix), "selected-runtime"), (self.work, "owned-fixture")):
                if p.is_relative_to(root):
                    row.update(role=role, relative=p.relative_to(root).as_posix()[:240])
                    break
        expected = self.expected_reason == reason
        (self.expected_denials if expected else self.denials).append(row)
        # Prebound primitive carrier exists before any product/native import.
        if not expected:
            self.stderr_write("DEVTOOLS_REFUSAL " + json.dumps(row, separators=(",", ":")) + "\n")
        raise PermissionError(reason)

    def generator(self):
        # Actual stdlib generators, not blanket <string> exec authority.
        frame = sys._getframe(2)
        collections = sys.modules.get("collections")
        dataclasses = sys.modules.get("dataclasses")
        builder = getattr(dataclasses, "_FuncBuilder", None)
        for _ in range(4):
            if frame is None:
                break
            if collections is not None and frame.f_code is collections.namedtuple.__code__:
                return frame, frame.f_locals.get("code")
            if builder is not None and frame.f_code is builder.add_fns_to_class.__code__:
                cls = frame.f_locals.get("cls")
                if getattr(cls, "__module__", None) == "document_extractors":
                    return frame, frame.f_locals.get("txt")
            frame = frame.f_back
        return None, None

    def native_role(self):
        frame = sys._getframe(2)
        for _ in range(12):
            if frame is None:
                break
            path, name = frame.f_code.co_filename, frame.f_code.co_name
            if path == str(Path(sys.base_prefix) / "Lib/ctypes/__init__.py") and name == "<module>":
                return "cold-stdlib-bootstrap"
            if path == str(Path(__file__).absolute()) and name in {"bind_oracle", "state", "observe"}:
                return "physical-oracle-or-exact-owned-emergency"
            if SESSION is not None and hasattr(SESSION, "product") and hasattr(SESSION, "baseline") and frame.f_code in {
                SESSION.product._open_windows_allowed_file.__code__,
                SESSION.product._windows_final_path_from_handle.__code__,
                SESSION.baseline._open_windows_allowed_file.__code__}:
                return "exact-source-reader"
            frame = frame.f_back
        return None

    def audit(self, event, args):
        if event == "open":
            path, mode, flags = args
            if type(path) is int:
                return self.deny(event, "integer_fd_open")
            if not isinstance(path, (str, bytes)):
                return self.deny(event, "non_literal_path")
            text = os.path.abspath(os.fsdecode(path))
            key = os.path.normcase(text)
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return self.deny(event, "write_open", text)
            if key not in self.reads and key not in self.cache_reads:
                return self.deny(event, "outside_exact_read_set", text)
            no_links(text)
            return
        if event in {"os.listdir", "os.scandir"}:
            if type(args[0]) is not str or os.path.normcase(os.path.abspath(args[0])) not in self.dirs:
                return self.deny(event, "outside_exact_import_dirs")
            return
        if event == "import":
            name, origin = args[:2]
            if name.split(".")[0] in {"agent", "hermes_cli", "hermes_sdk", "memory_wiki", "tools", "dotenv"}:
                return self.deny(event, "SDK_Core_config_import")
            if origin is not None and os.path.normcase(os.path.abspath(origin)) not in self.reads:
                return self.deny(event, "unbound_native_import", origin)
            return
        if event == "compile":
            raw, filename = args[:2]
            if isinstance(raw, ast.AST):
                return self.deny(event, "unbound_AST_compile")
            if type(raw) is str:
                raw = raw.encode("utf-8")
            if filename == "<string>":
                frame, generated = self.generator()
                if type(generated) is str and raw == generated.encode("utf-8") and len(raw) <= 24000:
                    self.generated[id(frame)] = sha(raw)
                    self.generated_count += 1
                    return
            if type(raw) is not bytes or sha(raw) not in self.allowed_compile_hashes:
                return self.deny(event, "unbound_compile")
            return
        if event == "exec":
            filename = args[0].co_filename
            if filename == "<string>":
                frame, generated = self.generator()
                if type(generated) is str and self.generated.pop(id(frame), None) == sha(generated.encode("utf-8")):
                    return
            if filename.startswith("<frozen "):
                return
            if os.path.normcase(os.path.abspath(filename)) not in self.reads:
                return self.deny(event, "unbound_exec", filename)
            return
        if event == "ctypes.dlopen":
            if args != ("kernel32",) or self.native_role() is None:
                return self.deny(event, "arbitrary_ctypes_library")
            self.native_events.append({"event": event, "role": "kernel32-reader-or-oracle"})
            return
        if event == "ctypes.dlsym":
            library, symbol = args
            if self.native_role() is None or getattr(library, "_name", None) != "kernel32" or symbol not in {
                "GetLastError", "CreateFileW", "GetFileInformationByHandle", "CloseHandle", "GetFinalPathNameByHandleW"
            }:
                return self.deny(event, "arbitrary_ctypes_symbol")
            self.native_events.append({"event": event, "symbol": symbol})
            return
        if event == "ctypes.create_unicode_buffer":
            if args[0] is not None or type(args[1]) is not int or not 0 < args[1] <= 32769 or self.active is None:
                return self.deny(event, "unbound_unicode_buffer")
            return
        if event in {"ctypes.get_last_error", "ctypes.set_last_error"}:
            if self.native_role() is None or args != (() if event == "ctypes.get_last_error" else (0,)):
                return self.deny(event, "unbound_last_error")
            return
        if event.startswith("ctypes."):
            return self.deny(event, "arbitrary_ctypes_operation")
        if event == "msvcrt.open_osfhandle":
            handle, flags = args
            if self.active is None or self.active["handle"] != handle or flags != os.O_RDONLY | os.O_BINARY:
                return self.deny(event, "unbound_HANDLE_to_FD")
            self.active["transfer_admissions"] += 1
            return
        if event == "msvcrt.get_osfhandle":
            if args[0] not in self.fds:
                return self.deny(event, "unowned_FD_query")
            return
        if event.startswith(("socket.", "subprocess.", "_winapi.", "winreg.", "sqlite3.connect")) or event in {
            "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile", "os.fork", "os.forkpty"
        }:
            return self.deny(event, "network_process_registry_SQL")
        if event in {"sys._getframe", "sys._getframemodulename", "sys.setprofile", "object.__getattr__",
                     "object.__setattr__", "builtins.id", "marshal.loads"}:
            return
        return self.deny(event, "undeclared_audit_event")


class FatalHandle(BaseException):
    pass


def bind_oracle():
    # Cold ctypes import happens under the installed fence, not before it.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Information(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info, close = kernel.GetFileInformationByHandle, kernel.CloseHandle
    get_info.argtypes, get_info.restype = [wintypes.HANDLE, ctypes.POINTER(Information)], wintypes.BOOL
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL

    def state(handle, expected=None):
        info = Information()
        ctypes.set_last_error(0)
        if not get_info(handle, ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error != 6:  # ERROR_INVALID_HANDLE is an actual physical observation.
                raise AssertionError("native_oracle_not_invalid_handle")
            return {"state": "closed", "winerror": error}
        identity = [info.volume, (info.index_high << 32) | info.index_low,
                    (info.creation.dwHighDateTime << 32) | info.creation.dwLowDateTime]
        if expected is not None and identity != expected:
            return {"state": "foreign_or_reused", "identity": identity}
        return {"state": "live", "identity": identity,
                "size": (info.size_high << 32) | info.size_low, "attributes": info.attributes}

    return types.SimpleNamespace(ctypes=ctypes, msvcrt=msvcrt, state=state, close=close)


class NativeCall:
    """Exact-CodeType injector; separate prebound physical oracle survives it."""
    def __init__(self, function, path, *, point=None, primary=None):
        self.function, self.path = function, Path(path)
        self.point, self.primary = point, primary
        self.code = function.__code__
        self.final_code = function.__globals__["_windows_final_path_from_handle"].__code__
        self.root_code = function.__globals__["_path_within_allowed_roots"].__code__
        self.row = dict(handle=None, identity=None, transfer_admissions=0,
                        pretransfer_calls=0, injected=False, source="candidate" if function is SESSION.product._open_windows_allowed_file else "baseline")
        self.fd = None

    def profile(self, frame, event, arg):
        owner = frame if frame.f_code is self.code else frame.f_back
        if owner is not None and owner.f_code is self.code:
            self.pin_handle(owner)
        if frame.f_code is self.code:
            if event == "call":
                if Path(frame.f_locals["path"]) != self.path or self.path not in SESSION.paths:
                    raise PermissionError("native_path_not_owned_exact_fixture")
                no_links(self.path)
                SESSION.fence.calls += 1
                if SESSION.fence.calls > 96:
                    raise PermissionError("native_reader_call_cap")
                SESSION.fence.active = self.row
            if event == "c_call" and arg is SESSION.oracle.msvcrt.open_osfhandle:
                self.row["pretransfer_calls"] += 1
                if self.point == "handoff":
                    self.inject()
            if event == "return" and type(arg) is int:
                self.fd = arg
                SESSION.fence.fds.add(arg)
                if SESSION.oracle.msvcrt.get_osfhandle(arg) != self.row["handle"]:
                    raise AssertionError("handoff_not_same_handle")
        elif event == "call" and frame.f_back is not None and frame.f_back.f_code is self.code:
            if (self.point == "final" and frame.f_code is self.final_code) or (self.point == "root" and frame.f_code is self.root_code):
                self.inject()

    def pin_handle(self, frame):
        handle = frame.f_locals.get("handle")
        if type(handle) is int and handle != SESSION.oracle.ctypes.c_void_p(-1).value and self.row["handle"] is None:
            initial = SESSION.oracle.state(handle)
            if initial["state"] != "live":
                raise AssertionError("acquisition_not_live")
            disk = self.path.lstat()
            if initial["identity"][:2] != [disk.st_dev & 0xffffffff, disk.st_ino & ((1 << 64) - 1)]:
                raise AssertionError("native_file_identity_not_disk_fixture")
            self.row.update(handle=handle, identity=initial["identity"], acquired=initial)

    def inject(self):
        if self.row["handle"] is None or self.row["injected"]:
            raise AssertionError("fault_not_exact_live_pretransfer")
        self.row["live_at_fault"] = SESSION.oracle.state(self.row["handle"], self.row["identity"])
        if self.row["live_at_fault"]["state"] != "live" or self.row["transfer_admissions"]:
            raise AssertionError("fault_not_before_transfer")
        self.row["injected"] = True
        raise self.primary  # CPython disables this throwing profile. Oracle is separate.

    @contextmanager
    def observe(self, main, label, *, retain_return=False):
        if sys.getprofile() is not None or SESSION.fence.active is not None:
            raise AssertionError("foreign_profile_or_native_owner")
        completed = False
        try:
            sys.setprofile(self.profile)
            yield self
            completed = True
        finally:
            sys.setprofile(None)
            observation = {"main": main, "label": label, **self.row}
            handle = self.row["handle"]
            # No successor acquisition has occurred: persist physical state BEFORE recovery.
            if handle is not None:
                observation["before_emergency_cleanup"] = SESSION.oracle.state(handle, self.row["identity"])
            else:
                observation["before_emergency_cleanup"] = {"state": "no_acquired_handle_observed"}
            OBSERVATIONS.append(observation)
            before = observation["before_emergency_cleanup"]
            observation["fixture_emergency_cleanup"] = False
            observation["retained_successful_CRT_owner"] = bool(retain_return and completed and self.fd is not None)
            if before["state"] == "live" and not observation["retained_successful_CRT_owner"]:
                # Revalidate exact identity, never close stale/unknown numbers.
                if SESSION.oracle.state(handle, self.row["identity"])["state"] != "live":
                    raise AssertionError("emergency_identity_changed")
                if self.fd is None:
                    if not SESSION.oracle.close(handle):
                        raise AssertionError("emergency_CloseHandle_failed")
                else:
                    os.close(self.fd)
                    SESSION.fence.fds.discard(self.fd)
                observation["fixture_emergency_cleanup"] = True
                observation["after_emergency_cleanup"] = SESSION.oracle.state(handle, self.row["identity"])
                if observation["after_emergency_cleanup"]["state"] != "closed":
                    raise AssertionError("emergency_closure_not_proved")
            elif before["state"] == "foreign_or_reused":
                raise AssertionError("UNKNOWN_handle_no_cleanup")
            SESSION.fence.active = None


@unittest.skipUnless(os.name == "nt", "Windows component only")
class DocumentWindowsHandleOwner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SESSION is None:
            raise RuntimeError("explicit_offline_component_entry_required")
        raw = (ROOT / "document_knowledge_graph.py").read_bytes()
        fixture = FIXTURE.read_bytes()
        if sha(raw) != CANDIDATE_MODULE_SHA256 or sha(fixture) != BASELINE_FIXTURE_SHA256:
            raise AssertionError("product_or_shipped_baseline_drift")
        nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == "_open_windows_allowed_file"]
        if len(nodes) != 1:
            raise AssertionError("non_unique_owning_function")
        n = nodes[0]
        span = b"".join(raw.splitlines(keepends=True)[n.lineno-1:n.end_lineno])
        if span != fixture.replace(b"    except Exception:\n", b"    except BaseException:\n"):
            raise AssertionError("not_minimal_owning_handler_delta")
        if sha(raw.replace(span, fixture)) != BASELINE_MODULE_SHA256:
            raise AssertionError("bytes_outside_owning_function_changed")
        sys.path.insert(0, str(ROOT))
        SESSION.product = importlib.import_module("document_knowledge_graph")
        for name in ("document_knowledge_graph", "document_extractors", "guard"):
            p = Path(sys.modules[name].__file__).absolute()
            if p != ROOT / (name + ".py"):
                raise AssertionError("wrong_full_standalone_origin")
            SESSION.fence.origins[name] = dict(path=str(p), sha256=sha(p.read_bytes()))
        SESSION.baseline = types.ModuleType("windows_handle_exact_e6_body")
        SESSION.baseline.__dict__.update({k: getattr(SESSION.product, k) for k in
            ("Path", "os", "_windows_final_path_from_handle", "_path_within_allowed_roots")})
        exec(compile(fixture, str(FIXTURE), "exec"), SESSION.baseline.__dict__)
        SESSION.oracle = bind_oracle()
        if "ctypes" not in sys.modules or "_ctypes" not in sys.modules:
            raise AssertionError("missing_real_native_runtime")

    def fault_matrix(self, point, kinds):
        for module, source in ((SESSION.product, "candidate"), (SESSION.baseline, "baseline")):
            for kind in kinds:
                primary = kind("exact primary")
                label = source + "." + point + "." + kind.__name__
                with self.subTest(id=label):
                    call = NativeCall(module._open_windows_allowed_file, SESSION.input, point=point, primary=primary)
                    with call.observe(self._testMethodName, label):
                        with self.assertRaises(kind) as caught:
                            call.function(SESSION.input)
                        self.assertIs(caught.exception, primary)
                        self.assertTrue(call.row["injected"])
                        self.assertIsNone(sys.getprofile())  # throwing profile disabled; NOT a closure oracle
                        self.assertEqual(call.row["transfer_admissions"], 0)
                        state = SESSION.oracle.state(call.row["handle"], call.row["identity"])
                        expected = "live" if source == "baseline" and not issubclass(kind, Exception) else "closed"
                        self.assertEqual(state["state"], expected)
                        call.row.update(primary_identity_preserved=True, expected_baseline_violation=expected == "live")

    def healthy(self, label):
        call = NativeCall(SESSION.product._open_windows_allowed_file, SESSION.input)
        with call.observe(self._testMethodName, label):
            validated = SESSION.product._allowed_path(SESSION.input)
            self.assertEqual(validated, SESSION.input)
            fd = SESSION.product._open_allowed_file(validated)
            self.assertEqual(call.fd, fd)
            self.assertEqual(call.row["pretransfer_calls"], 1)
            self.assertEqual(call.row["transfer_admissions"], 1)
            info = os.fstat(fd)
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(info.st_ino, SESSION.input.lstat().st_ino)
            self.assertEqual(os.read(fd, 4096), PAYLOAD)
            with self.assertRaises(OSError):
                os.write(fd, b"must-not-write")  # genuine CRT readonly refusal, original remains immutable
            os.lseek(fd, 0, os.SEEK_SET)
            self.assertEqual(os.read(fd, 4096), PAYLOAD)
            self.assertEqual(SESSION.oracle.state(call.row["handle"], call.row["identity"])["state"], "live")
            os.close(fd)
            SESSION.fence.fds.remove(fd)
            self.assertEqual(SESSION.oracle.state(call.row["handle"], call.row["identity"])["state"], "closed")
            call.row["readonly_refusal_and_same_HANDLE_transfer"] = True

    def test_01_native_readonly_transfer_and_close(self):
        self.healthy("first-healthy")

    def test_02_ordinary_pretransfer_cleanup(self):
        for point in ("final", "root", "handoff"):
            self.fault_matrix(point, (RuntimeError,))

    def test_03_fatal_final_path_cleanup(self):
        self.fault_matrix("final", (FatalHandle, KeyboardInterrupt, SystemExit))

    def test_04_fatal_root_check_cleanup(self):
        self.fault_matrix("root", (FatalHandle, KeyboardInterrupt, SystemExit))

    def test_05_fatal_handle_to_fd_entry_cleanup(self):
        self.fault_matrix("handoff", (FatalHandle, KeyboardInterrupt, SystemExit))

    def test_06_native_refusal_paths_and_closure(self):
        for name, path in (("outside-owned-allowlist", SESSION.other), ("missing", SESSION.missing),
                           ("directory", SESSION.directory)):
            with self.subTest(id="validated." + name):
                with self.assertRaises(ValueError):
                    SESSION.product._allowed_path(path)
            with self.subTest(id="native." + name):
                call = NativeCall(SESSION.product._open_windows_allowed_file, path)
                with call.observe(self._testMethodName, "native." + name):
                    with self.assertRaises((OSError, ValueError)):
                        call.function(path)
                    if name == "outside-owned-allowlist":
                        self.assertIsNotNone(call.row["handle"])
                        self.assertEqual(SESSION.oracle.state(call.row["handle"], call.row["identity"])["state"], "closed")
                    else:
                        self.assertIsNone(call.fd)
                    self.assertEqual(call.row["transfer_admissions"], 0)
        with self.subTest(id="audit.integer-fd-open-refused"):
            SESSION.fence.expected_reason = "integer_fd_open"
            try:
                with self.assertRaises(PermissionError):
                    open(123456, "rb")
            finally:
                SESSION.fence.expected_reason = None
        self.assertEqual(SESSION.fence.denials, [])

    def test_07_repeat_healthy_after_fatal(self):
        self.healthy("repeat-healthy-after-matrix")

    def test_08_two_simultaneous_owned_readers(self):
        # Nested observation is deliberately avoided; both returned CRT owners
        # coexist, each bound to its genuine HANDLE before the second acquire.
        records = []
        try:
            for index in range(2):
                with self.subTest(id="reader." + str(index)):
                    call = NativeCall(SESSION.product._open_windows_allowed_file, SESSION.input)
                    with call.observe(self._testMethodName, "simultaneous-acquire." + str(index), retain_return=True):
                        fd = call.function(SESSION.input)
                    records.append((fd, call.row))
                    self.assertEqual(call.row["transfer_admissions"], 1)
                    self.assertEqual(os.read(fd, 4096), PAYLOAD)
            self.assertNotEqual(records[0][0], records[1][0])
            self.assertNotEqual(records[0][1]["handle"], records[1][1]["handle"])
            for fd, row in records:
                self.assertEqual(SESSION.oracle.state(row["handle"], row["identity"])["state"], "live")
            for fd, row in records:
                os.close(fd)
                SESSION.fence.fds.remove(fd)
                self.assertEqual(SESSION.oracle.state(row["handle"], row["identity"])["state"], "closed")
                OBSERVATIONS.append({"main": self._testMethodName, "label": "simultaneous." + str(fd), **row,
                                     "before_emergency_cleanup": {"state": "closed", "winerror": 6},
                                     "fixture_emergency_cleanup": False})
        finally:
            sys.setprofile(None)
            SESSION.fence.active = None
            # Cleanup only still-registered returned FDs with matching physical identity.
            for fd, row in records:
                if fd in SESSION.fence.fds:
                    live = SESSION.oracle.state(row["handle"], row["identity"])
                    OBSERVATIONS.append({"main": self._testMethodName, "label": "simultaneous-emergency",
                                         "before_emergency_cleanup": live})
                    if live["state"] == "live":
                        os.close(fd)
                        SESSION.fence.fds.remove(fd)
                    elif live["state"] != "closed":
                        raise AssertionError("UNKNOWN_no_stale_cleanup")


class Results(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None

    def startTest(self, test):
        super().startTest(test)
        self.current = {"id": test._testMethodName, "outcome": "unknown", "subcase_results": []}
        self.rows.append(self.current)
        sys.stderr.write("DEVTOOLS_CASE_STARTED " + test._testMethodName + "\n")

    def addSuccess(self, test):
        super().addSuccess(test)
        self.current["outcome"] = "passed"

    def addFailure(self, test, err):
        self.current.update(outcome="failed", error_type=err[0].__name__)
        self.failures.append((test, err[0].__name__))

    def addError(self, test, err):
        if self.current is not None:
            self.current.update(outcome="error", error_type=err[0].__name__)
        self.errors.append((test, err[0].__name__))
        frames = []
        trace = err[2]
        while trace is not None:
            path = Path(trace.tb_frame.f_code.co_filename)
            if path.is_relative_to(ROOT) or path.is_relative_to(Path(sys.base_prefix)):
                frames.append([path.name, trace.tb_frame.f_code.co_name, trace.tb_lineno])
            trace = trace.tb_next
        sys.stderr.write("CASE_ERROR " + json.dumps({"type": err[0].__name__, "frames": frames[-8:]}, separators=(",", ":")) + "\n")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.current["outcome"] = "skipped"

    def addSubTest(self, test, subtest, err):
        row = {"id": test._testMethodName + "." + subtest.params["id"],
               "outcome": "passed" if err is None else "failed" if issubclass(err[0], test.failureException) else "error"}
        if err is not None:
            row["error_type"] = err[0].__name__
            self.current["outcome"] = row["outcome"]
            (self.failures if row["outcome"] == "failed" else self.errors).append((subtest, row["error_type"]))
        self.current["subcase_results"].append(row)


def main():
    global SESSION
    if not (os.name == "nt" and sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError("requires_Windows_python_I_S_B")
    if "ctypes" in sys.modules or "document_knowledge_graph" in sys.modules:
        raise RuntimeError("native_or_product_prewarm_refused")
    args = sys.argv[1:]
    plan = None
    if len(args) == 2 and args[0] == "--plan":
        raw = no_links(args[1]).read_bytes()
        digest = sys.stdin.buffer.read(65).decode("ascii")
        if len(digest) != 64 or sha(raw) != digest:
            raise RuntimeError("plan_digest_handoff")
        plan = json.loads(raw)
        work = no_links(plan["work"])
        rows = plan["read_bindings"]
        if Path(sys.executable) != Path(plan["selected_python"]) or plan["roster"] != list(ROSTER):
            raise RuntimeError("runtime_or_roster_drift")
    elif len(args) == 2 and args[0] == "--owned-root":
        work = no_links(args[1])
        fixture_files(work)
        rows = stdlib_closure(Path(sys.base_prefix))
        # Initial fence grants these exact public inputs; all product reads and
        # compilation, including hashes, happen only AFTER installation.
        rows += [dict(path=str(ROOT / rel), sha256="", role="public-source") for rel in PUBLIC_FILES]
    else:
        raise RuntimeError("explicit_owned_root_or_supervised_plan_required")
    os.environ["MEMORY_WIKI_DOCUMENT_ROOTS"] = str(work / "allowed")
    os.environ["HERMES_HOME"] = str(work / "home")
    input_path, other_path = work / "allowed/input.txt", work / "negative/other.txt"
    for p, payload in ((input_path, PAYLOAD), (other_path, OTHER_PAYLOAD)):
        rows.append(dict(path=str(p), sha256=sha(payload), bytes=len(payload), role="immutable-synthetic-input"))
    fence = OfflineFence(rows, work)
    sys.addaudithook(fence.audit)  # BEFORE first product read/import/exec and cold ctypes.
    # Verify exact row bytes under the fence. Bootstrap stdlib was trusted, not
    # counted as product execution; no source/SDK imports have occurred yet.
    for row in rows:
        raw = no_links(row["path"]).read_bytes()
        if row["sha256"] and sha(raw) != row["sha256"]:
            raise RuntimeError("input_binding_drift")
        if not row["sha256"]:
            row["sha256"] = sha(raw)
            fence.allowed_compile_hashes.add(row["sha256"])
    SESSION = types.SimpleNamespace(fence=fence, work=work, input=input_path, other=other_path,
        missing=work / "allowed/missing.txt", directory=work / "allowed/directory",
        paths={input_path, other_path, work / "allowed/missing.txt", work / "allowed/directory"})
    suite = unittest.TestSuite(DocumentWindowsHandleOwner(name) for name in ROSTER)
    result = Results()
    suite.run(result)
    cases = result.rows
    subs = [s for r in cases for s in r["subcase_results"]]
    if len({s["id"] for s in subs}) != len(subs):
        raise AssertionError("duplicate_subtest_identity")
    for p, payload in ((input_path, PAYLOAD), (other_path, OTHER_PAYLOAD)):
        if p.read_bytes() != payload:
            raise AssertionError("synthetic_input_mutated")
    if any((work / "empty-pycache").iterdir()):
        raise AssertionError("bytecode_write")
    report = dict(schema="memory-stack.cases/v1", cases=cases, observations=OBSERVATIONS,
        total=len(cases), passed=sum(r["outcome"] == "passed" for r in cases),
        failed=sum(r["outcome"] == "failed" for r in cases), errors=sum(r["outcome"] == "error" for r in cases),
        skipped=sum(r["outcome"] == "skipped" for r in cases), subtests=len(subs),
        native_reader_calls=fence.calls, native_events=fence.native_events, origins=fence.origins,
        stdlib_generated_code_count=fence.generated_count,
        audit_denials=fence.denials, expected_audit_refusals=fence.expected_denials,
        remaining_registered_fds=sorted(fence.fds), finished=True,
        baseline_expected_violations=sum(o.get("expected_baseline_violation", False) for o in OBSERVATIONS),
        before_effect_CloseHandle="UNKNOWN_NOT_INJECTED", scope="component", full_standalone_module=True,
        SDK_SQL_snapshot_FULL_live="NOT_RUN")
    raw = json.dumps(report, separators=(",", ":"), ensure_ascii=True)
    if len(raw.encode("utf-8")) > 48000:
        raise RuntimeError("case_report_capacity")
    sys.stdout.write(raw + "\n")
    return 0 if [r["id"] for r in cases] == list(ROSTER) and all(r["outcome"] == "passed" for r in cases) and not fence.denials and not fence.fds else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as error:
        # Fail-closed bounded secret-safe carrier, without formatting foreign objects.
        sys.stderr.write("DEVTOOLS_REFUSAL entry_" + type(error).__name__ + "\n")
        raise SystemExit(2)
