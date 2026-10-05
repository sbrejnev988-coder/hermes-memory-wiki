"""Seven stdlib CI-contract units; no SDK/plugin imports or native proof.

Source imports are repository-relative; --source chooses frozen RED or overlay
GREEN. Receipt writing is an AST-only projection of read-only actual file paths,
not a native MRO receipt. No full/recovery/Job/remote actions are executed.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import unittest
import xml.etree.ElementTree as ET


def nofollow(path):
    for node in [path, *path.parents]:
        if os.path.lexists(node):
            item = os.lstat(node)
            if stat.S_ISLNK(item.st_mode) or getattr(item, "st_file_attributes", 0) & 0x400:
                raise RuntimeError("Unsafe unit path")


def load_unit(relative, root):
    path = root / relative
    nofollow(path)
    spec = importlib.util.spec_from_file_location("contract_unit_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function_bytes(raw, name):
    tree = ast.parse(raw)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    return b"".join(raw.splitlines(keepends=True)[function.lineno - 1:function.end_lineno])


def guard_bytes(raw):
    lines = raw.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if b"# Native exports are the public baseline CI contract" in line)
    end = next(i for i, line in enumerate(lines) if b"raise RuntimeError('Memory Wiki fell back to a non-native SDK')" in line)
    return b"".join(lines[start:end + 1])


def projection_statements(raw):
    main = next(node for node in ast.parse(raw).body if isinstance(node, ast.FunctionDef) and node.name == "main")
    start = next(i for i, node in enumerate(main.body) if isinstance(node, ast.If) and "Memory Wiki fell back to a non-native SDK" in ast.unparse(node))
    end = next(i for i, node in enumerate(main.body) if isinstance(node, ast.Import) and node.names[0].name == "pytest")
    # Exclude the preserved structured native receipt, including its MRO flag.
    # Only the compatibility projection is executed, never main/native imports.
    return [node for node in main.body[start + 1:end] if "'modules'" not in ast.unparse(node)]


class ContractControls(unittest.TestCase):
    def runroot(self, label):
        path = OUT / "units" / label
        nofollow(path)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def test_01_explicit_dotenv_block(self):
        env = CI.clean_environment({"PYTHON_DOTENV_DISABLED": "0"}, self.runroot("dotenv"), CORE.parent.parent, SOURCE)
        self.assertEqual(env.get("PYTHON_DOTENV_DISABLED"), "1", "explicit dotenv disable missing")

    def test_02_allowlist_and_synthetic_policy_unchanged(self):
        root = self.runroot("allowlist")
        env = CI.clean_environment({"PATH": "unit-path", "SystemRoot": "unit-root", "OPENAI_API_KEY": "unit-sentinel", "HERMES_HOME": "foreign-unit-home", "AUTH_TOKEN": "unit-sentinel", "PYTHONPATH": "foreign-unit-path", "HERMES_SECURITY_STRICT": "1"}, root, CORE.parent.parent, SOURCE)
        self.assertEqual(env["PATH"], "unit-path")
        self.assertEqual(env["SystemRoot"], "unit-root")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("AUTH_TOKEN", env)
        self.assertEqual(env["HERMES_HOME"], str(root / "synthetic-home/hermes"))
        self.assertEqual(env["HERMES_SECURITY_STRICT"], "0")
        self.assertEqual(env["PYTHONPATH"], os.pathsep.join((str(SOURCE / "scripts/ci_owned"), str(CORE.parent.parent), str(SOURCE))))

    def execute_projection(self, root, home):
        statements = projection_statements(CHILD_RAW)
        namespace = {"Path": Path, "os": os, "json": json, "runroot": root, "origins": ORIGINS}
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(home)
        try:
            exec(compile(ast.Module(body=statements, type_ignores=[]), str(SOURCE / "scripts/ci_owned/ci_child.py"), "exec"), namespace)
        finally:
            if previous is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous

    def test_03_consumer_path_and_exact_source_projection(self):
        root = self.runroot("projection")
        home = root / "synthetic-home/hermes"
        home.parent.mkdir()
        self.execute_projection(root, home)
        receipt = home.parent / "native-origins.json"
        self.assertTrue(receipt.is_file(), "ordinary fixture native origin receipt missing")
        actual = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(actual, {"origins": {name: row["origin"] for name, row in ORIGINS.items()}})
        self.assertEqual(actual["origins"]["agent.memory_provider"], str(CORE.resolve(strict=True)))
        self.assertNotIn("native_MRO", actual, "projection must not create native proof")
        self.assertEqual(hashlib.sha256(CORE.read_bytes()).hexdigest(), CORE_SHA)

    def test_04_foreign_fixture_home_denied_without_receipt(self):
        root = self.runroot("foreign-home")
        expected = root / "synthetic-home"
        expected.mkdir()
        foreign = root / "foreign-unit-home"
        foreign.mkdir()
        with self.assertRaisesRegex(RuntimeError, "CI fixture home mismatch"):
            self.execute_projection(root, foreign / "hermes")
        self.assertFalse((expected / "native-origins.json").exists())
        self.assertFalse((foreign / "native-origins.json").exists())

    def test_05_native_export_origin_and_mro_guards_raw_preserved(self):
        old = (BASELINE / "scripts/ci_owned/ci_child.py").read_bytes()
        self.assertEqual(guard_bytes(CHILD_RAW), guard_bytes(old))
        self.assertIn(b"if not path.is_relative_to(core):", guard_bytes(CHILD_RAW))
        self.assertIn(b"getattr(module, export)", guard_bytes(CHILD_RAW))
        self.assertIn(b"native_base not in plugin.MemoryWikiProvider.__mro__", guard_bytes(CHILD_RAW))
        text = CHILD_RAW.decode("utf-8")
        self.assertLess(text.index("raise RuntimeError('Memory Wiki fell back"), text.index("(out / 'native-origins.json')"))
        self.assertIn("{'modules': origins, 'plugin_origin': str(Path(plugin.__file__).resolve()), 'native_MRO': True, 'executable': sys.executable}", text)
        if "(fixture_home / 'native-origins.json')" in text:
            self.assertLess(text.index("raise RuntimeError('Memory Wiki fell back"), text.index("(fixture_home / 'native-origins.json')"))
            self.assertLess(text.index("CI fixture home mismatch"), text.index("(fixture_home / 'native-origins.json')"))

    def test_06_other_ci_functions_raw_preserved(self):
        before = (BASELINE / "scripts/ci_owned/memory_wiki_ci.py").read_bytes()
        after = (SOURCE / "scripts/ci_owned/memory_wiki_ci.py").read_bytes()
        for node in ast.parse(before).body:
            if isinstance(node, ast.FunctionDef) and node.name != "clean_environment":
                self.assertEqual(function_bytes(before, node.name), function_bytes(after, node.name), node.name)
        # Real protected bootstrap/recorder bodies remain read-only, not simulated.
        self.assertEqual(hashlib.sha256((BASELINE / "scripts/ci_owned/ci_process.py").read_bytes()).hexdigest(), PROTECTED_PROCESS_SHA)
        bootstrap = (BASELINE / "scripts/ci_owned/ci_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("executable != config['executable']", bootstrap)
        self.assertIn("MemoryProvider native origin/hash mismatch", bootstrap)

    def test_07_owned_worker_plan_carries_dotenv_without_install(self):
        root = self.runroot("worker-plan")
        env = CI.clean_environment({}, root, CORE.parent.parent, SOURCE)
        process = load_unit("scripts/ci_owned/ci_process.py", BASELINE)
        config = {"runroot": str(root), "executable": str(Path(sys.executable).resolve()), "run_id": "unit-only"}
        recorder = process.LaunchRecorder(config, "unit-only-owner")
        row, effective = recorder.plan([sys.executable, "-B", "unit-only.py"], env)
        self.assertEqual(effective.get("PYTHON_DOTENV_DISABLED"), "1", "owned worker lost dotenv disable")
        self.assertTrue(row["same_interpreter"])
        self.assertTrue(row["site_enabled"])
        self.assertFalse(row["status"] == "exited", "unit plan is not native execution")
        self.assertEqual({k: v for k, v in effective.items() if k != "MW_CI_LAUNCH_ID"}, env)


class CompactResult(unittest.TestResult):
    def startTest(self, test):
        super().startTest(test)
        self.rows.append({"name": test._testMethodName})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows[-1]["status"] = "passed"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows[-1].update(status="failed", message=str(err[1])[:350])

    def addError(self, test, err):
        super().addError(test, err)
        self.rows[-1].update(status="error", message=(err[0].__name__ + ": " + str(err[1]))[:350])


def bounded_write(path, data):
    raw = data.encode("utf-8") if isinstance(data, str) else data
    assert len(raw) <= 8192, "output cap before persistence"
    nofollow(path)
    with path.open("xb") as stream:
        stream.write(raw)


def main():
    global SOURCE, BASELINE, OUT, CORE, CORE_SHA, ORIGINS, CI, CHILD_RAW, PROTECTED_PROCESS_SHA
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--core-file", type=Path, required=True)
    args = parser.parse_args()
    SOURCE, BASELINE, OUT, CORE = (value.resolve() for value in (args.source, args.baseline, args.out, args.core_file))
    for path in (SOURCE, BASELINE, OUT, CORE):
        nofollow(path)
    OUT.mkdir(parents=True, exist_ok=False)
    CORE_SHA = "a4e44a293013fff831ac136ab77c556541cd18817f53bd662e97090cd80bd5a6"
    assert hashlib.sha256(CORE.read_bytes()).hexdigest() == CORE_SHA
    contract_raw = (BASELINE / "packaging/run_native_regressions.py").read_bytes()
    exported = next(node.value for node in ast.parse(contract_raw).body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "EXPORTS" for target in node.targets))
    exports = {**ast.literal_eval(exported), "agent.memory_provider": ("MemoryProvider",)}
    ORIGINS = {}
    for module, names in exports.items():
        path = (CORE.parent.parent / (module.replace(".", "/") + ".py")).resolve(strict=True)
        nofollow(path)
        ORIGINS[module] = {"origin": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "exports": list(names)}
    # These are actual read-only source paths, not imported/verified SDK exports.
    CHILD_RAW = (SOURCE / "scripts/ci_owned/ci_child.py").read_bytes()
    CI = load_unit("scripts/ci_owned/memory_wiki_ci.py", SOURCE)
    inventory_path = BASELINE.parents[1] / "evidence/release-final-source-assembly-20261004/final-source-inventory.json"
    inventory = json.loads(inventory_path.read_bytes())
    PROTECTED_PROCESS_SHA = next(row["raw_sha256"] for row in inventory["files"] if row["path"] == "scripts/ci_owned/ci_process.py")
    result = CompactResult()
    result.rows = []
    unittest.defaultTestLoader.loadTestsFromTestCase(ContractControls).run(result)
    assert result.testsRun == len(result.rows) == 7
    failures = sum(row["status"] == "failed" for row in result.rows)
    errors = sum(row["status"] == "error" for row in result.rows)
    suite = ET.Element("testsuite", name="ASTUNIT_CI_fixture_contract", tests=str(result.testsRun), failures=str(failures), errors=str(errors), skipped="0")
    for row in result.rows:
        case = ET.SubElement(suite, "testcase", name=row["name"], classname="ASTUNIT_CI_fixture_contract")
        if row["status"] != "passed":
            ET.SubElement(case, "failure" if row["status"] == "failed" else "error", message=row["message"])
    bounded_write(OUT / "junit.xml", ET.tostring(suite, encoding="utf-8", xml_declaration=True))
    report = {"schema": "ci-fixture-contract-unit-v1", "verification_class": "ASTUNIT / CI-contract unit", "completed": True, "cases": result.rows, "tests": result.testsRun, "failed": failures, "errors": errors, "source": str(SOURCE), "source_raw_sha256": {relative: hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest() for relative in ("scripts/ci_owned/memory_wiki_ci.py", "scripts/ci_owned/ci_child.py")}, "controls_raw_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "projection_input_kind": "actual read-only SDK source paths; NOT real import/export/MRO verification", "projection_input_modules": ORIGINS, "executable": sys.executable, "version": sys.version, "native_SDK_import_attempted": False, "plugin_import_attempted": False, "native_MRO_proven": False, "native_Job_attempted": False, "hosted_environment_proven": False, "transport_proven": False, "persistence_proven": False, "release_accepted": False}
    bounded_write(OUT / "cases.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    bounded_write(OUT / "unit.log", "".join(row["name"] + ": " + row["status"] + (" " + row.get("message", "") if row["status"] != "passed" else "") + "\n" for row in result.rows))
    print(json.dumps({"completed": True, "tests": result.testsRun, "passed": result.testsRun - failures - errors, "failed": failures, "errors": errors, "class": report["verification_class"]}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
