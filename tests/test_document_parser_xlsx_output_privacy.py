"""Five confirmed OOXML/output mechanisms; whole original81 remains the runner.

Authored real ZIP/XML, genuine bounded helper/redactors and both serializers.
Collection is inert: no test method, fixture or parser runs during import.
"""
from __future__ import annotations
import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET

INPUTS = globals().get("DEVTOOLS_INPUTS", {})
PRIOR = Path(INPUTS.get("test_document_parser_xlsx_formulas.py", Path(__file__).with_name("test_document_parser_xlsx_formulas.py")))
_spec = importlib.util.spec_from_file_location("parser_xlsx_original81_source", str(PRIOR))
prior = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = prior
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        prior.__dict__[_name] = globals()[_name]
_raw = devtools_read_bound(str(PRIOR)) if "devtools_read_bound" in globals() else PRIOR.read_bytes()
exec(compile(_raw, str(PRIOR), "exec", dont_inherit=True), prior.__dict__)
cell, cells_by_id = prior.cell, prior.cells_by_id
OBSERVATIONS = []


class XlsxOutputPrivacySourceTests(unittest.TestCase):
    def setUp(self):
        self.e = prior.review.peer.load_source(prior.review.peer.EXTRACTOR, "document_extractors")
        self.path = prior.review.peer.fixture_root() / (self._testMethodName + ".xlsx")

    def views(self, sheets, *, shared=()):
        prior.workbook(self.path, sheets, shared=shared)
        before = self.path.read_bytes()
        doc = self.e.extract_xlsx(self.path, 100, 100, prior.ZIP_LIMITS)
        raw, serialized = self.e.asdict(doc), doc.to_dict()
        self.assertEqual([u.to_dict() for u in doc.units], serialized["units"])
        final = self.e.extract_document(self.path, {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(final["file_hash"], prior.hashlib.sha256(before).hexdigest())
        return raw, serialized, final

    def test_xout_literal_ids_all_views_and_unsafe_identity_inverse(self):
        name = " Данные O'Brien e\u0301 "
        expression = "SUM('" + name.replace("'", "''") + "'!A1:A2)"
        for payload in self.views([("Итог", [(1, [cell("A1", formula=expression)])]),
                                   (name, [(1, [cell("A1", "2")]), (2, [cell("A2", "3")])])]):
            self.assertEqual(payload["metadata"]["sheets"], ["Итог", name])
            sheet = next(u for u in payload["units"] if u["kind"] == "sheet" and u["locator"]["sheet"] == name)
            self.assertEqual(sheet["title"], name)
            self.assertEqual(cells_by_id(payload)["Итог", "A1"]["value"], "5")
            row = next(u for u in payload["units"] if u["kind"] == "table_row" and u["locator"]["sheet"] == name)
            self.assertEqual(row["anchor"], "sheet:" + name + "/row:1")
            refs = [e for e in payload["edges"] if e["predicate"] == "formula_ref"]
            self.assertEqual([e["target_anchor"] for e in refs], ["sheet:" + name + "/cell:A1", "sheet:" + name + "/cell:A2"])
            self.assertTrue(all(e["evidence"] == expression for e in refs))
        for unsafe in ("password=IdentityFixture9988 ", " bad\tID ", "x" * 1025):
            if len(unsafe) > 1024:
                prior.workbook(self.path, [(unsafe, [])])
                with self.assertRaises(ValueError):
                    self.e.extract_document(self.path, {})
                continue
            for payload in self.views([(unsafe, [(1, [cell("A1", "4")])])]):
                self.assertEqual(payload["metadata"]["sheets"], ["<REDACTED>"])
                self.assertTrue(all(u["locator"]["sheet"] == "<REDACTED>" for u in payload["units"]))
                self.assertNotIn(unsafe, json.dumps(payload, ensure_ascii=False))
                self.assertNotIn("IdentityFixture9988", json.dumps(payload))
        OBSERVATIONS.append({"case": self._testMethodName, "literal_raw_unit_document_final": True})

    def test_xout_context_withholds_encoded_transformed_attributes_and_evidence(self):
        secret, encoded, cached = 'Canary"Quoted9988', '"Canary""Quoted9988"', "PrivateCache9987"
        sheets = [("Data", [
            (1, [cell("A1", "Password", ctype="inlineStr"), cell("C1", "Name", ctype="inlineStr")]),
            (2, [cell("A2", cached, formula=encoded, ctype="str", attrs={"ca": encoded}),
                 cell("B2", "7", formula="A2", ctype="str"),
                 cell("C2", "3", formula="1+2", attrs={"opaque": encoded})]),
            (3, [cell("A3", "1234567"), cell("B3", "99", formula="A3*2"),
                 cell("C3", encoded, ctype="inlineStr")])])]
        for payload in self.views(sheets):
            text, c = json.dumps(payload, ensure_ascii=False), cells_by_id(payload)
            for private in (secret, encoded, cached, "1234567", "2469134"):
                self.assertNotIn(private, text)
            for coord in ("A2", "B2", "C2", "B3"):
                self.assertEqual(c["Data", coord]["formula"], "<REDACTED>")
                self.assertEqual(c["Data", coord]["formula_attributes"], {})
                self.assertTrue(c["Data", coord]["context_redacted"])
                for key in ("value", "cached_value", "cached_raw_value"):
                    self.assertIn(c["Data", coord][key], (None, "<REDACTED>"))
            self.assertEqual((c["Data", "B3"]["status"], c["Data", "B3"]["value_origin"]), ("computed", "evaluated"))
            refs = [e for e in payload["edges"] if e["predicate"] == "formula_ref"]
            self.assertTrue(refs)
            self.assertTrue(all(e["evidence"] == "<REDACTED>" for e in refs))
            self.assertEqual(payload["metadata"]["formula_context_redaction"], "workbook_conservative")
        # Same quote-bearing expression is lawful with no protected table context.
        for payload in self.views([("Data", [(1, [cell("A1", cached, formula=encoded, ctype="str", attrs={"ca": "1"}),
                                                   cell("B1", formula="A1", ctype="str")])])]):
            c = cells_by_id(payload)
            self.assertEqual((c["Data", "A1"]["formula"], c["Data", "A1"]["value"], c["Data", "A1"]["cached_value"]), (encoded, secret, cached))
            self.assertEqual(c["Data", "A1"]["formula_attributes"], {"ca": "1"})
            self.assertEqual(payload["edges"][0]["evidence"], "A1")
        OBSERVATIONS.append({"case": self._testMethodName, "all_formula_copies_withheld_healthy_inverse": True})

    def test_xout_context_words_are_data_not_producer_schema(self):
        reference_keys = None
        for word in ("value", "formula", "status", "computed"):
            for payload in self.views([("Data", [(1, [cell("A1", "Password", ctype="inlineStr")]),
                (2, [cell("A2", word, ctype="str"), cell("B2", formula='"' + word + '"', ctype="str"),
                     cell("C2", "6", formula="3+3")])])]):
                c = cells_by_id(payload)
                target = c["Data", "B2"]
                if reference_keys is None:
                    reference_keys = set(target)
                self.assertEqual(set(target), reference_keys)
                self.assertEqual((target["status"], target["value_origin"], target["value_type"], target["cache_status"]),
                                 ("computed", "evaluated", "text", "absent"))
                self.assertEqual((target["value"], target["formula"], c["Data", "A2"]["value"]), ("<REDACTED>",) * 3)
                self.assertEqual(payload["metadata"]["coverage"]["cell_statuses"], {"literal": 2, "computed": 2})
                self.assertEqual(payload["metadata"]["coverage"]["formula_ref_coverage"], "evaluated_lexical_endpoints_not_dependency_DAG")
                self.assertEqual(payload["metadata"]["formula_policy"]["engine"], "bounded_subset_v1")
                self.assertEqual(payload["status"], "ok")
        # Unknown XML attribute keys are document data, NOT exempt schema keys.
        key = "sk-" + "k" * 24  # valid XML name, still an untrusted document key
        for payload in self.views([("Data", [(1, [cell("A1", "9", formula="1", attrs={key: "password=AttributeValue9987"})])])]):
            attrs = cells_by_id(payload)["Data", "A1"]["formula_attributes"]
            self.assertNotIn(key, json.dumps(attrs))
            self.assertNotIn("AttributeValue9987", json.dumps(attrs))
        OBSERVATIONS.append({"case": self._testMethodName, "four_mask_words_typed_slots_schema_preserved": True})

    def test_xout_shared_cache_independent_formula_and_literal_refusals(self):
        caches = [prior.ABSENT, "", "broken", "9", "0"]
        formula_cells = [cell(chr(65 + i) + "1", v, formula="1+1", ctype="s") for i, v in enumerate(caches)]
        literals = [cell(chr(65 + i) + "2", v, ctype="s") for i, v in enumerate(caches)]
        deps = [cell(chr(65 + i) + "3", "887", formula=chr(65 + i) + "2+1") for i in range(5)]
        for payload in self.views([("Data", [(1, formula_cells), (2, literals), (3, deps)])], shared=("00123",)):
            c = cells_by_id(payload)
            for i, status in enumerate(("absent", "invalid", "invalid", "invalid", "available")):
                coord = chr(65 + i) + "1"
                result = c["Data", coord]
                self.assertEqual((result["value"], result["status"], result["value_origin"]), ("2", "computed", "evaluated"))
                self.assertEqual((result["cache_status"], result["cached_present"], result["value_present"]), (status, i != 0, i != 0))
                self.assertEqual(result["cached_value"], "00123" if i == 4 else None)
            for i in range(4):
                for row in (2, 3):
                    result = c["Data", chr(65 + i) + str(row)]
                    self.assertEqual((result["status"], result["value"], result["value_origin"]), ("unsupported", None, "none"))
            self.assertEqual((c["Data", "E2"]["value"], c["Data", "E3"]["value"]), ("00123", "124"))
            self.assertEqual(c["Data", "B1"]["cached_raw_value"], "")
            self.assertEqual(c["Data", "C1"]["cached_raw_value"], "broken")
            self.assertFalse(payload["metadata"]["formula_policy"]["cache_fallback"])
        OBSERVATIONS.append({"case": self._testMethodName, "shared_cache_five_shapes_literal_dependencies": True})

    def test_xout_complete_scalar_admission_not_prefix_and_cache_is_independent(self):
        broken_f = cell("A1", "999", formula="1")
        ET.SubElement(broken_f.find("f"), "bad").tail = "+2"
        broken_v = cell("B1", "9", formula="2+3")
        ET.SubElement(broken_v.find("v"), "bad").tail = "9"
        literal_v = cell("C1", "7")
        ET.SubElement(literal_v.find("v"), "bad").tail = "7"
        attributed_v = cell("D1", "8", formula="3+3")
        attributed_v.find("v").set("unknown", "1")
        indented = cell("E1", "0", formula="1+1")
        indented.text, indented.find("f").tail, indented.find("v").tail = "\n  ", "\n  ", "\n"
        for payload in self.views([("Data", [(1, [broken_f, broken_v, literal_v, attributed_v, indented,
            cell("F1", "", formula="1+1"), cell("G1", "0", formula="FALSE", ctype="b")]),
            (2, [cell("A2", formula="A1+1"), cell("B2", formula="B1+1"), cell("C2", formula="C1+1"),
                 cell("D2", "", formula="", ctype="str")])])]):
            c = cells_by_id(payload)
            for coord in ("A1", "A2", "C1", "C2", "D2"):
                self.assertEqual((c["Data", coord]["status"], c["Data", coord]["value"]), ("unsupported", None))
            self.assertEqual(c["Data", "A1"]["reason"], "ooxml_formula_scalar_unsupported")
            for coord, value in (("B1", "5"), ("D1", "6"), ("E1", "2"), ("F1", "2"), ("G1", "FALSE"), ("B2", "6")):
                self.assertEqual((c["Data", coord]["status"], c["Data", coord]["value"]), ("computed", value))
            for coord in ("B1", "D1"):
                self.assertEqual((c["Data", coord]["cache_status"], c["Data", coord]["cached_value"], c["Data", coord]["cached_present"]), ("invalid", None, True))
            self.assertEqual((c["Data", "E1"]["cached_value"], c["Data", "G1"]["cached_value"]), ("0", "FALSE"))
            self.assertEqual((c["Data", "F1"]["cache_status"], c["Data", "F1"]["cached_present"]), ("absent", True))
        OBSERVATIONS.append({"case": self._testMethodName, "nested_f_v_attribute_v_indentation_healthy_dependencies": True})

    def test_xout_shared_serializer_default_sanitation_limits_and_arbitrary_keys(self):
        e, key, value = self.e, "password=KeyFixture9988", "password=ValueFixture9987"
        metadata = {key: value, "nested": {"value": "password=NestedFixture9986"}, "long": "x" * 20001,
                    "deep": [[[[[[[[["tail"]]]]]]]]], "binary": b"bytes"}
        unit = e.Unit("paragraph", "label ", "body \n" + value, title="title ", parent_anchor="parent ",
                      locator={key: value, "sheet": " ordinary "}, metadata=metadata)
        actual = unit.to_dict()
        expected = e.asdict(unit)
        for field, limit in (("text", 200000), ("title", 2000), ("anchor", 2000), ("parent_anchor", 2000)):
            expected[field] = e.clean_text(expected[field], limit)
        expected["locator"], expected["metadata"] = e.sanitize_json(unit.locator), e.sanitize_json(metadata)
        self.assertEqual(actual, expected)
        document = e.ExtractedDocument("stdlib-text", "text/plain", "title ", [unit], metadata,
                                        warnings=[value], edges=[{key: value}])
        result = document.to_dict()
        self.assertEqual(result["units"], [expected])
        self.assertEqual(result["metadata"], e.sanitize_json(metadata))
        self.assertEqual(result["edges"], e.sanitize_json(document.edges, max_string=4000))
        self.assertEqual(result["warnings"], e.sanitize_json(document.warnings, max_string=4000))
        self.assertEqual((actual["anchor"], actual["title"], len(actual["metadata"]["long"])), ("label", "title", 20000))
        text = json.dumps(result)
        for private in ("KeyFixture9988", "ValueFixture9987", "NestedFixture9986"):
            self.assertNotIn(private, text)
        self.assertIn("<MAX_DEPTH>", text)
        self.assertEqual(actual["metadata"]["binary"], "<BINARY:5 bytes>")
        OBSERVATIONS.append({"case": self._testMethodName, "non_xlsx_default_and_arbitrary_keys_unchanged": True})

    def test_xtaint_protected_refusal_slots_do_not_need_values_or_cache(self):
        encoded = '"SlotCanary""NoCache9988"'
        scenarios = [
            ("A2", [(1, [cell("A1", "Password", ctype="inlineStr")]),
                    (2, [cell("A2", formula=encoded, ctype="str", attrs={"t": "array", "ca": encoded}),
                         cell("C2", formula="1+1")])]),
            ("B1", [(1, [cell("A1", "Password", ctype="inlineStr"),
                         cell("B1", formula=encoded, ctype="str", attrs={"t": "array", "ca": encoded}),
                         cell("D1", formula="1+1")])]),
        ]
        for protected, rows in scenarios:
            for payload in self.views([("Data", rows)]):
                target = cells_by_id(payload)["Data", protected]
                self.assertEqual((target["status"], target["value_origin"], target["cached_present"]),
                                 ("unsupported", "none", False))
                self.assertEqual((target["formula"], target["formula_attributes"]), ("<REDACTED>", {}))
                self.assertTrue(target["context_redacted"])
                self.assertEqual(payload["metadata"]["formula_context_redaction"], "workbook_conservative")
                self.assertEqual(payload["status"], "partial")
                self.assertNotIn("SlotCanary", json.dumps(payload))
                self.assertTrue(any(c["status"] == "computed" for c in cells_by_id(payload).values()))
        for payload in self.views([("Data", [(1, [cell("A1", "Password", ctype="inlineStr")]),
            (2, [cell("A2", formula="B2"), cell("B2", formula="A2")])])]):
            target = cells_by_id(payload)["Data", "A2"]
            self.assertEqual((target["status"], target["formula"], target["value"]),
                             ("cycle", "<REDACTED>", None))
            self.assertTrue(target["context_redacted"])
        # Incomplete input also has a protected representation without a value.
        prior.workbook(self.path, [("Data", [(1, [cell("A1", "Password", ctype="inlineStr")]),
            (2, [cell("A2", formula=encoded, ctype="str"), cell("C2", formula="1+1")])])])
        original = self.path.read_bytes()
        doc = self.e.extract_xlsx(self.path, 100, 2, prior.ZIP_LIMITS)
        for payload in (self.e.asdict(doc), doc.to_dict(), self.e.extract_document(self.path, {"max_cells": 2})):
            target = cells_by_id(payload)["Data", "A2"]
            self.assertFalse(payload["metadata"]["coverage"]["input_complete"])
            self.assertEqual((target["status"], target["formula"], target["value"]),
                             ("incomplete_workbook", "<REDACTED>", None))
            self.assertNotIn("SlotCanary", json.dumps(payload))
        self.assertEqual(self.path.read_bytes(), original)
        # Refusal alone is not a privacy label: preserve ordinary source output.
        for payload in self.views([("Data", [(1, [cell("A1", "Note", ctype="inlineStr")]),
            (2, [cell("A2", formula=encoded, ctype="str", attrs={"t": "array"})])])]):
            target = cells_by_id(payload)["Data", "A2"]
            self.assertEqual((target["status"], target["formula"]), ("unsupported", encoded))
            self.assertEqual(payload["metadata"]["formula_context_redaction"], "not_needed")
        OBSERVATIONS.append({"case": self._testMethodName, "header_adjacent_cycle_incomplete_before_values": True})

    def test_xtaint_plain_display_trim_is_not_a_secret_identity_mask(self):
        name = " Ledger O'Brien e\u0301 "
        expression = "SUM('" + name.replace("'", "''") + "'!B1:B2)"
        for payload in self.views([("Totals", [(1, [cell("A1", formula=expression)])]),
            (name, [(1, [cell("A1", name, ctype="inlineStr"), cell("B1", "2")]),
                    (2, [cell("B2", "3")])])]):
            self.assertEqual(payload["metadata"]["sheets"], ["Totals", name])
            self.assertEqual(payload["metadata"]["formula_context_redaction"], "not_needed")
            values = cells_by_id(payload)
            self.assertEqual(values[name, "A1"]["value"], name.rstrip())
            self.assertEqual(values["Totals", "A1"]["value"], "5")
            sheet = next(u for u in payload["units"] if u["kind"] == "sheet" and u["locator"]["sheet"] == name)
            self.assertEqual(sheet["title"], name)
            row = next(u for u in payload["units"] if u["kind"] == "table_row" and u["locator"]["sheet"] == name)
            self.assertEqual(row["anchor"], "sheet:" + name + "/row:1")
            refs = [e for e in payload["edges"] if e["predicate"] == "formula_ref"]
            self.assertEqual([e["target_anchor"] for e in refs], ["sheet:" + name + "/cell:B1", "sheet:" + name + "/cell:B2"])
            self.assertTrue(all(e["evidence"] == expression for e in refs))
        # A real protected value equal to an identity must still be masked.
        secret = "ProtectedIdentity9988"
        for payload in self.views([(secret, [(1, [cell("A1", "Password", ctype="inlineStr")]),
                                             (2, [cell("A2", secret, ctype="inlineStr")])])]):
            self.assertEqual(payload["metadata"]["sheets"], ["<REDACTED>"])
            self.assertNotIn(secret, json.dumps(payload))
        previous = prior.review.clone_function(self.e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.7")
        self.assertNotEqual(self.e.extraction_options_fingerprint(Path("fixture.xlsx"), {}),
                            previous(Path("fixture.xlsx"), {}))
        OBSERVATIONS.append({"case": self._testMethodName, "display_trim_identity_and_real_secret_inverse": True})

    def test_xout_version_3_1_6_inverse_and_literal_hook_bounds(self):
        e = self.e
        self.assertEqual((e.EXTRACTOR_VERSION, e.SECRET_POLICY_VERSION), ("3.1.8", "3.0.0"))
        previous = prior.review.clone_function(e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.6")
        for suffix in (".xlsx", ".pdf", ".txt"):
            path = Path("fixture" + suffix)
            self.assertNotEqual(e.extraction_options_fingerprint(path, {}), previous(path, {}))
        name = " Literal e\u0301 O'Brien "
        sheet = e.Unit("sheet", "sheet:1", name, title=name, locator={"sheet": name, "sheet_index": 1})
        self.assertEqual(sheet.to_dict()["title"], name.rstrip())  # generic default is unchanged
        sheet._xlsx_literal_output = True
        self.assertEqual(sheet.to_dict()["title"], name)
        for bad in ("password=HookFixture9988 ", "x\x00y", "x\u202ey", "x" * 1025):
            unit = e.Unit("sheet", "sheet:1", "safe", title=bad, locator={"sheet": bad, "sheet_index": 1})
            unit._xlsx_literal_output = True
            self.assertEqual((unit.to_dict()["title"], unit.to_dict()["locator"]["sheet"]), ("<REDACTED>",) * 2)
        # A familiar key alone is not a typed identity grant.
        arbitrary = e.Unit("paragraph", "a", "safe", title=name, locator={"sheet": name})
        self.assertEqual(arbitrary.to_dict()["locator"]["sheet"], name.rstrip())
        OBSERVATIONS.append({"case": self._testMethodName, "new_inverse_and_validated_identity_only": True})


def packet_suite():
    return unittest.TestSuite([prior.packet_suite(), unittest.defaultTestLoader.loadTestsFromTestCase(XlsxOutputPrivacySourceTests)])


def metadata_preflight():
    return prior.metadata_preflight() + [c._testMethodName for c in unittest.defaultTestLoader.loadTestsFromTestCase(XlsxOutputPrivacySourceTests)]


if __name__ == "__main__" and "devtools_case_started" in globals():
    reporter = next(n for n in ast.walk(ast.parse(prior.read_source(prior.review.PEER_PATH))) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(prior.review.PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "terminal_compositions": prior.chain.terminal.OBSERVATIONS, "cleanup_compositions": prior.chain.cleanup.OBSERVATIONS,
        "pdf_compositions": prior.chain.composition.OBSERVATIONS, "causal_compositions": prior.chain.OBSERVATIONS,
        "xlsx_compositions": prior.OBSERVATIONS, "xlsx_output_compositions": OBSERVATIONS,
        "qualification": "SOURCE original81 plus real OOXML/output correction; engines/SDK/SQL/native/FULL NOT_RUN"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(packet_suite()).wasSuccessful() else 1)
