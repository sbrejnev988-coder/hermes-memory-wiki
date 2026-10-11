"""Owned, ordinary current-SDK component carrier; never native admission.

Uses the permanent project's direct-child supervisor, not its SOURCE launcher:
that launcher deliberately refuses real SDK/site dependencies. Core imports begin
only after this child's audit hook. No SDK stand-ins, .pth execution, monkeypatch,
Git subprocess grant, monitoring lease or live-home data is introduced here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import contextvars
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
import unittest

SCHEMA = "memory-stack.current-sdk-component/v1"
SCRIPT = Path(__file__).absolute()
SOURCE = SCRIPT.parents[2]
COMPONENT_CASES = (
    "actual_sdk_mro_and_trust", "real_constructor_defaults",
    "ordinary_public_registration", "ordinary_provider_initialize",
    "registered_public_store_and_read", "ordinary_shutdown",
)
FIXTURE_YAML = (
    "memory:\n  provider: memory-wiki\n  prefetch_spill_enabled: false\n"
    "hooks:\n  output_spill:\n    enabled: false\n"
    "terminal:\n  backend: local\n"
)
CORE_INPUTS = (
    "agent/memory_provider.py", "agent/memory_manager.py", "hermes_constants.py",
    "tools/registry.py", "tools/hook_output_spill.py", "tools/tool_output_limits.py",
    "hermes_cli/config.py", "hermes_cli/config_defaults.py", "hermes_yaml.py",
    "utils.py", "hermes_cli/managed_scope.py", "hermes_cli/version_info.py",
    "hermes_cli/auth_constants.py", "hermes_platform/host/runtime.py", "pm/paths.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def no_links(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise PermissionError("link_or_reparse_refused")
    return path


class Ledger:
    """Only primitives survive callbacks; counts remain complete past row cap."""
    def __init__(self, roots, exact=(), row_cap=32):
        self.roots = tuple((name, Path(path).absolute()) for name, path in roots)
        self.exact = tuple(Path(p).absolute() for p in exact)
        self.phase_path = contextvars.ContextVar("sdk_carrier_phase", default=("setup",))
        self.counts = Counter()
        self.refusals = []
        self.row_cap = row_cap
        self.diagnostic_failures = 0

    @contextmanager
    def phase(self, name):
        token = self.phase_path.set((*self.phase_path.get(), name))
        try:
            yield
        finally:
            self.phase_path.reset(token)

    def file_id(self, filename):
        # co_filename only; no object repr, args, locals, exceptions or secrets.
        path = Path(filename).absolute()
        for role, root in self.roots:
            if path.is_relative_to(root):
                return role + "/" + path.relative_to(root).as_posix()
        if path in self.exact:
            return "exact/" + path.name
        return "unbound/" + path.name[:96]

    def callers(self):
        rows = []
        frame = sys._getframe(2)
        try:
            for _ in range(20):
                if frame is None:
                    break
                code = frame.f_code
                if not (code.co_filename == str(SCRIPT) and code.co_name in {"audit", "record", "callers"}):
                    rows.append({"file": self.file_id(code.co_filename),
                                 "name": code.co_name[:96], "line": frame.f_lineno})
                    if len(rows) == 8:
                        break
                frame = frame.f_back
        finally:
            del frame
        return rows

    def record(self, event, refused):
        phase = "/".join(self.phase_path.get())
        self.counts[(phase, event, refused)] += 1
        if refused and len(self.refusals) < self.row_cap:
            # Failure of diagnostics never permits the original event.
            try:
                callers = self.callers()
            except Exception:
                self.diagnostic_failures += 1
                callers = []
            self.refusals.append({"event": event, "phase": phase, "callers": callers})

    def audit(self, event, args):
        refused = False
        relevant = False
        fixture = dict(self.roots)["fixture"]
        if event == "open":
            relevant = True
            path, mode, flags = args
            if isinstance(path, int):
                return  # same inherited FD boundary; no OS sandbox claim
            p = Path(os.fsdecode(path)).absolute()
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            refused = ((writing and not p.is_relative_to(fixture)) or
                       (not writing and p not in self.exact and not any(
                           p.is_relative_to(root) for _, root in self.roots)))
        elif event.startswith("socket.") or event in {
            "subprocess.Popen", "_winapi.CreateProcess", "os.system", "os.spawn", "os.fork",
        }:
            relevant = refused = True
        elif event == "sqlite3.connect":
            relevant = True
            refused = not Path(args[0]).absolute().is_relative_to(fixture)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.replace",
                       "os.chmod", "os.truncate", "os.utime"}:
            relevant = True
            paths = args[:2] if event in {"os.rename", "os.replace"} else args[:1]
            refused = any(not isinstance(p, int) and not Path(os.fsdecode(p)).absolute().is_relative_to(fixture)
                          for p in paths)
        if relevant:
            self.record(event, refused)
        if refused:
            raise PermissionError("owned_fixture_audit_refusal")

    def report(self):
        counts = [{"phase": phase, "event": event, "refused": refused, "count": count}
                  for (phase, event, refused), count in sorted(self.counts.items())]
        return {"counts": counts, "refusals": self.refusals,
                "refused_total": sum(count for (_, _, refused), count in self.counts.items() if refused),
                "diagnostic_failures": self.diagnostic_failures,
                "refusal_rows_truncated": sum(count for (_, _, refused), count in self.counts.items() if refused) > len(self.refusals)}


class PhaseObserver:
    """Exact source call boundaries, not last NODE/test/report labels."""
    def __init__(self, ledger, core):
        self.ledger = ledger
        self.stack = []  # primitive frame IDs plus phase tuples, never frames
        self.targets = {}
        targets = {
            "hermes_cli/config.py": {"<module>": "bootstrap.config_import", "load_config": "bootstrap.config_load"},
            "tools/hook_output_spill.py": {"get_spill_config": "bootstrap.spill_config"},
            "hermes_cli/version_info.py": {"_run_git": "bootstrap.version_metadata"},
            "hermes_platform/host/runtime.py": {"_read_proc": "bootstrap.container_probe"},
        }
        for file, names in targets.items():
            for name, phase in names.items():
                self.targets[(os.path.normcase(str(Path(core) / file)), name)] = phase

    def __call__(self, frame, event, arg):
        key = (os.path.normcase(frame.f_code.co_filename), frame.f_code.co_name)
        if event == "call" and key in self.targets:
            old = self.ledger.phase_path.get()
            self.stack.append((id(frame), old))
            self.ledger.phase_path.set((*old, self.targets[key]))
        elif event == "return" and self.stack and self.stack[-1][0] == id(frame):
            _, old = self.stack.pop()
            self.ledger.phase_path.set(old)


def summarize(cases):
    ids = [row["id"] for row in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_case_ids")
    counts = Counter(row["outcome"] for row in cases)
    if set(counts) - {"passed", "failed", "error", "skipped"}:
        raise ValueError("invalid_outcome")
    return {"started": bool(cases), "total": len(cases),
            "passed": counts["passed"], "failed": counts["failed"],
            "errors": counts["error"], "skipped": counts["skipped"], "case_ids": ids}


def qualify(state, payload, unchanged):
    if (not state.get("capture_complete") or not state.get("ownership_complete") or
            state.get("deadline_state") != "completed_before_deadline" or payload is None):
        return "unknown", "capture"
    if not unchanged:
        return "blocked", "admission"
    try:
        if payload["schema"] != SCHEMA or summarize(payload["cases"]) != payload["tests"]:
            return "unknown", "capture"
        counts = payload["audit"]["counts"]
        if any(type(row["count"]) is not int or row["count"] < 1 or type(row["refused"]) is not bool for row in counts):
            return "unknown", "capture"
        if sum(row["count"] for row in counts if row["refused"]) != payload["audit"]["refused_total"]:
            return "unknown", "capture"
    except (KeyError, TypeError, ValueError):
        return "unknown", "capture"
    if payload.get("audit", {}).get("refused_total") or payload.get("audit", {}).get("diagnostic_failures"):
        return "blocked", "admission"
    tests = payload.get("tests", {})
    unit = payload.get("unit", {})
    if (state.get("exit_code") != 0 or tests.get("failed") or tests.get("errors") or
            not unit.get("total") or unit.get("failed") or unit.get("errors")):
        return "failed", "fixture"
    if not tests.get("started") or not tests.get("passed") or payload.get("alive_threads"):
        return "unknown", "fixture"
    return "passed", "none"


def component(contract, scratch):
    core = Path(contract["selected_sdk"]["origin"])
    trust_path = Path(contract["trust_core"]["path"])
    deps = Path(contract["dependencies"]["site_packages"])
    ledger = Ledger((("core", core), ("source", SOURCE), ("fixture", scratch),
                     ("python", Path(sys.base_prefix)), ("dependencies", deps.parent.parent)),
                    exact=(SCRIPT, trust_path))
    assert not any(name in sys.modules for name in ("agent.memory_provider", "agent.memory_manager", "hermes_cli.config")), "Core_preload_refused"
    # Only standard-library lazy codecs are prepared. No Core/config/SDK preload.
    "owned-fixture".encode("idna")
    import encodings.utf_8_sig  # noqa: F401
    sys.addaudithook(ledger.audit)
    observer = PhaseObserver(ledger, core)
    sys.setprofile(observer)
    cases, origins = [], {}
    provider = manager = None
    registration_applied = None
    facts = {"guard_armed_before_sdk": True, "dependency_site_processing": False,
             "actual_python": {"executable": sys.executable, "version": list(sys.version_info[:3]),
                               "prefix": sys.prefix, "base_prefix": sys.base_prefix}}
    failure = None

    def case(name, fn):
        with ledger.phase(name):
            started = time.monotonic()
            try:
                fn()
            except AssertionError:
                cases.append({"id": name, "outcome": "failed", "phase": "/".join(ledger.phase_path.get()), "elapsed_seconds": time.monotonic() - started})
                raise
            except BaseException:
                cases.append({"id": name, "outcome": "error", "phase": "/".join(ledger.phase_path.get()), "elapsed_seconds": time.monotonic() - started})
                raise
            cases.append({"id": name, "outcome": "passed", "elapsed_seconds": time.monotonic() - started})

    try:
        with ledger.phase("component.import"):
            sys.path.insert(0, str(deps))
            sys.path.insert(0, str(core))
            trust = load_file("hermes_trust_core", trust_path)
            from agent.memory_provider import MemoryProvider
            from agent.memory_manager import MemoryManager
            from tools.registry import tool_error
            spec = importlib.util.spec_from_file_location("memory_wiki", SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)])
            wiki = importlib.util.module_from_spec(spec)
            sys.modules["memory_wiki"] = wiki
            spec.loader.exec_module(wiki)

        def identities():
            assert wiki.MemoryProvider is MemoryProvider
            assert wiki.MemoryWikiProvider.__bases__ == (MemoryProvider,)
            assert wiki._sanitize_recalled is trust.sanitize_recalled
            assert wiki.tool_error is tool_error
            for name, file in (("agent.memory_provider", "agent/memory_provider.py"),
                               ("agent.memory_manager", "agent/memory_manager.py"),
                               ("tools.registry", "tools/registry.py")):
                assert Path(sys.modules[name].__file__).absolute() == core / file
            facts["actual_mro"] = [cls.__module__ + "." + cls.__qualname__ for cls in wiki.MemoryWikiProvider.__mro__]
            facts["trust_callable_identity"] = True
        case(COMPONENT_CASES[0], identities)

        def construct():
            nonlocal provider, manager
            provider = wiki.MemoryWikiProvider()
            manager = MemoryManager()
            assert provider.home.absolute() == Path(os.environ["HERMES_HOME"]).absolute()
            assert provider._lifecycle_state == "idle" and provider._conn is None
            assert provider._owned_conn is None and provider._transaction_quarantine is None
            assert not manager.providers
        case(COMPONENT_CASES[1], construct)

        def register():
            nonlocal registration_applied
            manager.add_provider(provider)
            registration_applied = provider in manager.providers
            assert registration_applied
            assert manager.has_tool("memory_wiki_add_claim") and manager.has_tool("memory_wiki_query")
            from hermes_cli.config import load_config, get_config_path
            assert get_config_path().absolute() == Path(os.environ["HERMES_HOME"]) / "config.yaml"
            assert load_config()["memory"]["provider"] == "memory-wiki"
            assert Path(sys.modules["hermes_cli.config"].__file__).absolute() == core / "hermes_cli/config.py"
            assert Path(sys.modules["hermes_yaml"].__file__).absolute() == core / "hermes_yaml.py"
            assert Path(sys.modules["ruamel.yaml"].__file__).absolute() == deps / "ruamel/yaml/__init__.py"
            facts["public_yaml_reader"] = "hermes_cli.config.load_config -> utils.fast_safe_load -> hermes_yaml.safe_load"
        case(COMPONENT_CASES[2], register)

        def initialize():
            manager.initialize_all("sdk-carrier-owned-session", hermes_home=os.environ["HERMES_HOME"],
                                   platform="cli", bot_id="sdk-carrier-owned-bot", visibility_scope="chat")
            assert provider._lifecycle_state == "ready"
            assert provider._conn is provider._owned_conn is not None
            assert provider._background_worker is None
        case(COMPONENT_CASES[3], initialize)

        def store_read():
            saved = json.loads(manager.handle_tool_call("memory_wiki_add_claim", {
                "claim": "Пользователь предпочитает овальные керамические этикетки для проекта Лазурный маяк.",
                "topic": "preferences", "evidence": "Синтетическое авторское предпочтение для изолированного теста.",
                "confidence": 0.8, "salience": 0.75,
            }))
            assert saved.get("state") == "stored" and saved.get("immediately_recallable") is True
            rows = json.loads(manager.handle_tool_call("memory_wiki_query", {
                "query": "Лазурный маяк керамические этикетки", "include_stale": False, "mode": "fts", "limit": 3,
            }))
            assert not rows.get("error") and rows.get("disclosure_status") != "withheld"
            assert any(row.get("id") == saved["id"] for row in rows.get("claims", []))
            assert provider._conn is provider._owned_conn and not provider._conn.in_transaction
            assert provider._transaction_quarantine is None
            facts["real_public_store_and_read"] = True
        case(COMPONENT_CASES[4], store_read)
    except BaseException as exc:
        # Safe type and own phase only; never exc repr/message/traceback or retention.
        failure = {"type": type(exc).__name__, "phase": cases[-1].get("phase", "component.import") if cases else "component.import"}
    finally:
        def close():
            if manager is not None:
                manager.shutdown_all()
            if provider is not None:
                assert provider._conn is None and provider._owned_conn is None
        try:
            case(COMPONENT_CASES[5], close)
        except BaseException as exc:
            if failure is None:
                failure = {"type": type(exc).__name__, "phase": "ordinary_shutdown"}
        # Read actual loaded origins under the same guard; no source/control objects retained.
        with ledger.phase("component.origin_readback"):
            for name, module in tuple(sys.modules.items()):
                file = getattr(module, "__file__", None)
                if type(file) is not str:
                    continue
                p = Path(file).absolute()
                if p.is_relative_to(core) or p.is_relative_to(SOURCE) or p.is_relative_to(deps) or p == trust_path:
                    origins[name] = {"path": str(p), "sha256": sha(p)}
        sys.setprofile(None)
    return {"schema": SCHEMA, "cases": cases, "tests": summarize(cases), "facts": facts,
            "registration_applied": registration_applied, "permission": {"native_admission": False, "loaded_fleet": None},
            "audit": ledger.report(), "failure": failure, "loaded_origins": origins,
            "alive_threads": [t.name for t in threading.enumerate() if t is not threading.main_thread()]}


def worker(contract_path, scratch):
    contract = json.loads(Path(contract_path).read_bytes())
    assert contract["schema"] == SCHEMA
    assert sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.no_site
    assert Path(sys.executable).absolute() == Path(contract["selected_python"]["executable"])
    assert all(sha(row["path"]) == row["sha256"] for row in contract["source_bindings"])
    assert Path(os.environ["HERMES_HOME"]).absolute().is_relative_to(scratch)
    tests_module = load_file("_current_sdk_carrier_tests", SOURCE / "tests/ci_owned/test_current_sdk_bootstrap.py")
    tests_module.CARRIER = sys.modules[__name__]
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests_module))
    unit = {"total": result.testsRun, "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped)}
    if not result.wasSuccessful():
        print(json.dumps({"schema": SCHEMA, "unit": unit, "tests": None, "failure": {"type": "carrier_unit_failure"}}))
        return 1
    payload = component(contract, scratch)
    payload["unit"] = unit
    print(json.dumps(payload, ensure_ascii=False))
    return 2 if payload["audit"]["refused_total"] else (1 if payload["failure"] else 0)


def controller(project, lane, contract_path):
    """No scope switch in the SOURCE launcher; only its reused capture primitive."""
    harness = load_file("_sdk_permanent_harness", project / "devtools/harness.py")
    harness.isolated_python()
    contract = json.loads(contract_path.read_bytes())
    python = harness.select_python()
    assert str(python) == contract["selected_python"]["executable"]
    assert Path(sys.executable).absolute() == python
    assert contract["source_root"] == str(SOURCE)
    assert contract["permission"]["native_admission"] is False
    assert contract["permission"]["ordinary_component_from_owner_request"] is True
    assert all(sha(row["path"]) == row["sha256"] for row in contract["source_bindings"])
    evidence = harness.no_links(lane / "evidence")
    scratch = harness.no_links(Path(contract["scratch_root"]))
    # Registration creates an empty evidence directory; that is not a run.
    # Exact existing receipt/log or any existing synthetic child root is a run.
    if (evidence / "RESULT.json").exists() or (evidence / "logs").exists() or scratch.exists():
        raise FileExistsError("current_block_is_once_only")
    before = harness.footprint(lane)
    if before + 2_000_000 + 10_000_000 > contract["budget"]["lane_plus_scratch_cap"]:
        raise PermissionError("lane_budget_reserve_refused")
    if __import__("shutil").disk_usage("C:/").free < contract["budget"]["C_floor"]:
        raise PermissionError("C_floor_refused")
    scratch.mkdir(parents=True)
    env = harness.clean_env(scratch)
    (Path(env["HERMES_HOME"]) / "config.yaml").write_text(FIXTURE_YAML, encoding="utf-8")
    managed = scratch / "managed-empty"
    managed.mkdir()
    env.update(contract["fixture_environment"])
    env["HERMES_MANAGED_DIR"] = str(managed)
    harness.OUTPUT = evidence
    harness.RECOVERY = evidence  # lane output binding, not admission/policy widening
    result_path = evidence / "RESULT.json"
    argv = [str(python), "-I", "-B", "-S", "-X", "utf8", "-X",
            "pycache_prefix=" + str(scratch / "empty-pycache"), str(SCRIPT), "worker",
            "--contract", str(contract_path), "--scratch", str(scratch)]
    receipt = {"schema": "memory-stack.dev-result/v1", "block_id": "B-current-sdk-runtime-integration-20261011",
               "scope": "component", "status": "unknown", "failure_layer": "capture",
               "changed_files": ["scripts/ci_owned/current_sdk_bootstrap.py", "tests/ci_owned/test_current_sdk_bootstrap.py",
                                 "docs/CURRENT_SDK_COMPONENT_CONTRACT.json"],
               "source_bindings": contract["source_bindings"], "tests": None, "errors": [], "next_step": "Parent source-bound review; no native admission."}
    if "preflight_refusal" in contract:
        receipt["preflight_refusal"] = contract["preflight_refusal"]

    def captured(state):
        receipt["execution"] = state
        receipt["logs"] = state["logs"]
        receipt["metrics"] = {"elapsed_seconds": state["elapsed_seconds"],
                              "subprocess_invocations": state["subprocess_invocations"], "tool_invocations": None,
                              "implementation_seconds": None, "infrastructure_seconds": None,
                              "closed_tasks": None, "code_parts": None, "review_seconds": None}
        # Durable actual exit/raw capture BEFORE parsing; one authoritative RESULT.
        harness.save_result(result_path, receipt)
    state, out, err = harness.supervise(argv, scratch, env, evidence / "logs", "current-sdk-component",
                                        timeout=120, stdout_cap=96_000, stderr_cap=48_000,
                                        on_captured=captured, result_path=result_path)
    try:
        payload = harness.strict_json(out)
    except Exception:
        payload = None
    same = all(sha(row["path"]) == row["sha256"] for row in contract["source_bindings"])
    status, layer = qualify(state, payload, same)
    projection = None
    if payload is not None:
        projection = {key: payload.get(key) for key in ("schema", "tests", "unit", "facts", "registration_applied", "permission", "failure", "alive_threads")}
        projection["audit"] = {key: payload.get("audit", {}).get(key) for key in
                               ("counts", "refused_total", "diagnostic_failures", "refusal_rows_truncated")}
        projection["raw_ref"] = state["logs"]["stdout"]["path"]
        projection["raw_sha256"] = state["logs"]["stdout"]["sha256"]
        projection["caller_and_loaded_origin_refs"] = {"callers": "#/audit/refusals", "origins": "#/loaded_origins"}
    receipt.update(status=status, failure_layer=layer, tests=payload.get("tests") if payload else None,
                   actual_component=projection, inputs_unchanged=same,
                   historical_refusal=contract["historical_refusal"],
                   descriptor_sha256=sha(contract_path), permission=contract["permission"],
                   source_rebind={"applied": True, "target": str(SOURCE), "historical_COLD_unchanged": True},
                   footprint={"lane_and_scratch_bytes_before_RESULT": harness.footprint(lane, scratch),
                              "lane_cap": contract["budget"]["lane_plus_scratch_cap"], "reserve_bytes": 10_000_000,
                              "global_7GB_compliance": None})
    if status == "blocked":
        receipt["errors"] = ["retained_bootstrap_audit_refusals; functional results are not native acceptance"]
        receipt["next_step"] = "Parent reviews exact captured caller/source chains. Keep hostname/proc/process denied; no native authority from descriptor."
    elif status != "passed":
        receipt["errors"] = ["actual_fixture_or_capture_failure; see raw capture"]
    harness.save_result(result_path, receipt)
    print(json.dumps({"status": status, "tests": receipt["tests"], "unit": payload.get("unit") if payload else None,
                      "exit_code": state["exit_code"], "refused_total": payload.get("audit", {}).get("refused_total") if payload else None,
                      "RESULT": str(result_path)}))
    return 0 if status in {"passed", "blocked"} else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "worker"))
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--lane", type=Path)
    args = parser.parse_args()
    if args.mode == "worker":
        return worker(args.contract, args.scratch)
    return controller(args.project, args.lane, args.contract)


if __name__ == "__main__":
    raise SystemExit(main())
