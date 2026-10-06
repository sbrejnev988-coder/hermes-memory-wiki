"""CI-resource stdlib controls, not native/SDK or hosted acceptance proof."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).absolute().parents[2] / "scripts/ci_owned/ci_output_admission.py"
SYMLINK_CONTROL = "not_exercised"


class OutputAdmission(unittest.TestCase):
    def helper(self):
        self.assertTrue(SCRIPT.is_file(), "Missing fail-closed artifact byte contract")
        spec = importlib.util.spec_from_file_location("ci_output_admission_unit", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, members=None):
        root = Path(tempfile.mkdtemp(prefix="output-unit-", dir=os.environ.get("MW_OUTPUT_FIXTURES")))
        for name, data in (members or {}).items():
            (root / name).write_bytes(data)
        return root

    def lane(self):
        return self.fixture({"receipt.json": b"{}", "source-inventory.json": b"{}"})

    def refused(self, module, root, mode, code, **kwargs):
        opened = []
        enabled = [True]
        def audit(event, args):
            if enabled[0] and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(args[0])).absolute()
                if path == root or root in path.parents:
                    opened.append(str(path))
        sys.addaudithook(audit)
        try:
            with self.assertRaises(module.AdmissionError) as caught:
                module.admit(root, mode, **kwargs)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(opened, [], "Payload opened before metadata admission")
        finally:
            enabled[0] = False

    def test_public_snapshot_limits_and_optional_members(self):
        module = self.helper()
        self.assertEqual(module.DEFAULT_LIMITS, {"lane_total": 24000000,
            "json_member": 4000000, "junit_member": 8000000, "log_member": 8000000,
            "aggregate_total": 4000000, "decision": 4096})
        root = self.lane()
        result = module.admit(root, "native", limits={"json_member": 2, "lane_total": 4})
        self.assertEqual((result["files"], result["bytes"]), (2, 4))
        self.assertNotIn("accepted", result)
        self.refused(module, self.fixture({"receipt.json": b"{}"}), "native", "missing_required")
        with self.assertRaises(module.AdmissionError):
            module.admit(root, "native", limits={"json_member": 4000001})

    def test_member_and_total_caps_before_any_payload_open(self):
        module = self.helper()
        caps = {"json_member": 4, "junit_member": 4, "log_member": 4, "lane_total": 12}
        for name in ("receipt.json", "junit.xml", "pytest.log"):
            root = self.lane()
            (root / name).write_bytes(b"xxxxx")
            self.refused(module, root, "native", "member_too_large", limits=caps)
        root = self.fixture({name: b"xxxx" for name in
            ("receipt.json", "source-inventory.json", "execution.json", "junit.xml")})
        self.refused(module, root, "native", "total_too_large", limits=caps)

    def test_unknown_nonregular_duplicate_and_unsafe_paths(self):
        global SYMLINK_CONTROL
        module = self.helper()
        root = self.lane()
        (root / "unknown.json").write_bytes(b"x")
        self.refused(module, root, "native", "unknown_member")
        root = self.lane()
        (root / "execution.json").mkdir()
        self.refused(module, root, "native", "nonregular_member")
        root = self.lane()
        os.link(root / "receipt.json", root / "execution.json")
        self.refused(module, root, "native", "duplicate_or_linked_member")
        root = self.lane()
        with self.assertRaises(module.AdmissionError) as caught:
            module.admit(root / ".." / root.name, "native")
        self.assertEqual(caught.exception.code, "unsafe_path")
        link = root.parent / (root.name + "-link")
        try:
            os.symlink(root, link, target_is_directory=True)
        except OSError as exc:
            SYMLINK_CONTROL = "creation_unavailable:" + str(exc.errno)
        else:
            self.refused(module, link, "native", "unsafe_path")
            SYMLINK_CONTROL = "real_link_refused"

    def test_downloaded_exact_groups_and_refusal_are_metadata_only(self):
        module = self.helper()
        root = self.fixture()
        expected = {f"native-{os_name}-{version}-{stage}"
            for os_name in ("ubuntu-latest", "windows-latest")
            for version in ("3.11", "3.12", "3.13", "3.14")
            for stage in ("full", "recovery")}
        self.assertEqual(set(module.GROUPS), expected)
        for group in sorted(expected):
            directory = root / group
            directory.mkdir()
            for name in ("receipt.json", "source-inventory.json", "launches.json", "bindings.json", "native-origins.json"):
                (directory / name).write_bytes(b"{}")
        result = module.admit(root, "downloaded")
        self.assertEqual((result["groups"], result["files"], result["bytes"]), (16, 80, 160))
        group = root / sorted(expected)[0]
        (group / "ci-output-admission.json").write_bytes(b"not parsed")
        self.refused(module, root, "downloaded", "producer_refused")
        self.refused(module, self.fixture(), "downloaded", "group_set_mismatch")
        other = self.fixture()
        (other / "native-unexpected").mkdir()
        self.refused(module, other, "downloaded", "group_set_mismatch")

    def test_aggregate_actual_nonuploaded_inventory_is_bounded(self):
        module = self.helper()
        root = self.fixture({"matrix-coverage.json": b"{}", "receipt.json": b"{}", "source-inventory.json": b"{}"})
        self.assertEqual(module.admit(root, "aggregate", limits={"aggregate_total": 6})["bytes"], 6)
        self.refused(module, root, "aggregate", "total_too_large", limits={"aggregate_total": 5})
        self.refused(module, self.fixture({"receipt.json": b"{}"}), "aggregate", "missing_required")

    def test_cli_failure_receipt_and_literal_outputs_do_not_make_native_green(self):
        module = self.helper()
        root = self.lane()
        (root / "unknown.json").write_bytes(b"x")
        output = root.parent / (root.name + "-github-output")
        output.write_bytes(b"")
        decision = root.parent / (root.name + "-decision") / "ci-output-admission.json"
        # In-process CLI seam: no -S child or expected nonzero launch can
        # contaminate the unchanged native recorder's launch/binding proof.
        status = module.main(["native", "--root", str(root), "--decision", str(decision),
            "--github-output", str(output)])
        self.assertEqual(status, 1)
        self.assertEqual(output.read_bytes(), b"admitted=false\nrefusal=true\n")
        raw = decision.read_bytes()
        self.assertLessEqual(len(raw), 4096)
        receipt = json.loads(raw)
        self.assertFalse(receipt["capacity_admitted"])
        self.assertFalse(receipt["native_proof"])
        self.assertTrue(receipt["detailed_evidence_withheld"])
        self.assertEqual(receipt["code"], "unknown_member")
        self.assertEqual((root / "unknown.json").read_bytes(), b"x")
        good = self.lane()
        good_output = good.parent / (good.name + "-github-output")
        good_output.write_bytes(b"")
        absent_decision = good.parent / (good.name + "-decision") / "ci-output-admission.json"
        status = module.main(["native", "--root", str(good), "--decision", str(absent_decision),
            "--github-output", str(good_output)])
        self.assertEqual(status, 0)
        self.assertEqual(good_output.read_bytes(), b"admitted=true\nrefusal=false\n")
        self.assertFalse(absent_decision.exists())
        self.assertEqual(json.loads((good / "receipt.json").read_bytes()), {})


if __name__ == "__main__":
    unittest.main()
