"""Finished OOXML consumer cohort; original72 run through their shipped suite.

Real stdlib ZIP/XML + exact approved evaluator + actual extractor/redactors.
No spreadsheet engine, SDK, SQL, network, manual test methods or inherited cases.
The only lowered-budget seam delegates once to the genuine bounded helper.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET
import zipfile

INPUTS = globals().get("DEVTOOLS_INPUTS", {})
ROOT = Path(__file__).absolute().parents[1]
HELPER = Path(INPUTS.get("spreadsheet_formulas.py", ROOT / "spreadsheet_formulas.py"))
CHAIN = Path(INPUTS.get("test_document_parser_causal_chain.py", Path(__file__).with_name("test_document_parser_causal_chain.py")))


def read_source(path):
    return devtools_read_bound(str(path)) if "devtools_read_bound" in globals() else path.read_bytes()


# Bind the shipped helper BEFORE the shared original loader imports its consumer.
# Preloaded exact module identity, not ambient sys.path or a package fallback.
_spec = importlib.util.spec_from_file_location("spreadsheet_formulas", str(HELPER))
formulas = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = formulas
_raw = read_source(HELPER)
assert hashlib.sha256(_raw).hexdigest() == "c27cf8175b9561d6028c1c69919196cadf8b2348f52ed88d6a148c3ca39078ac"
exec(compile(_raw, str(HELPER), "exec", dont_inherit=True), formulas.__dict__)
_spec = importlib.util.spec_from_file_location("parser_xlsx_chain_source", str(CHAIN))
chain = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = chain
for _name in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
    if _name in globals():
        chain.__dict__[_name] = globals()[_name]
exec(compile(read_source(CHAIN), str(CHAIN), "exec", dont_inherit=True), chain.__dict__)
review = chain.review
OBSERVATIONS = []
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ZIP_LIMITS = {"max_entries": 100, "max_uncompressed": 2000000, "max_ratio": 200, "max_member": 1000000}
ABSENT = object()


def cell(coord, value=ABSENT, *, formula=ABSENT, ctype="n", attrs=None, cell_attrs=None):
    e = ET.Element("c", {"r": coord, "t": ctype, **(cell_attrs or {})})
    if formula is not ABSENT:
        f = ET.SubElement(e, "f", attrs or {})
        f.text = formula
    if ctype == "inlineStr":
        if value is not ABSENT:
            ET.SubElement(ET.SubElement(e, "is"), "t").text = value
    elif value is not ABSENT:
        ET.SubElement(e, "v").text = value
    return e


def worksheet(rows):
    root = ET.Element("worksheet")
    data = ET.SubElement(root, "sheetData")
    for number, cells in rows:
        ET.SubElement(data, "row", {"r": str(number)}).extend(cells)
    return ET.tostring(root, encoding="utf-8")


def workbook(path, sheets, *, shared=(), omitted=()):
    """Authored actual OOXML parts with deliberately non-positional targets."""
    book, rels = ET.Element("workbook"), ET.Element("Relationships")
    sheet_list = ET.SubElement(book, "sheets")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, (name, rows) in enumerate(sheets, 1):
            rid, target = "r" + str(index), "worksheets/sheet" + str(99 - index) + ".xml"
            ET.SubElement(sheet_list, "sheet", {"name": name, "sheetId": str(index), "{" + REL_NS + "}id": rid})
            ET.SubElement(rels, "Relationship", {"Id": rid, "Target": target, "Type": REL_NS + "/worksheet"})
            if name not in omitted:
                archive.writestr("xl/" + target, worksheet(rows))
        archive.writestr("xl/workbook.xml", ET.tostring(book, encoding="utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(rels, encoding="utf-8"))
        if shared:
            strings = ET.Element("sst")
            for text in shared:
                ET.SubElement(ET.SubElement(strings, "si"), "t").text = text
            archive.writestr("xl/sharedStrings.xml", ET.tostring(strings, encoding="utf-8"))


def cells_by_id(payload):
    return {(unit["locator"]["sheet"], c["coordinate"]): c for unit in payload["units"]
            if unit["kind"] == "table_row" for c in unit["metadata"]["cells"]}


class XlsxFormulaSourceTests(unittest.TestCase):
    def setUp(self):
        self.e = review.peer.load_source(review.peer.EXTRACTOR, "document_extractors")
        self.assertIs(self.e.evaluate_cells, formulas.evaluate_cells)
        self.path = review.peer.fixture_root() / (self._testMethodName + ".xlsx")

    def extract(self, sheets, *, shared=(), options=None, omitted=(), extractor=None):
        workbook(self.path, sheets, shared=shared, omitted=omitted)
        before = self.path.read_bytes()
        payload = (extractor or self.e.extract_document)(self.path, options or {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(payload["file_hash"], hashlib.sha256(before).hexdigest())
        self.assertLessEqual(len(payload["units"]), (options or {}).get("max_units", 100000))
        return payload, cells_by_id(payload)

    def test_xlsx_forward_cross_sheet_aggregates_and_literal_unicode_ids(self):
        name = " Данные O'Brien "
        ref = "' Данные O''Brien '!"
        expression = "SUM(" + ref + "$A$2:$A$3)+B1"
        payload, cells = self.extract([
            ("Итог", [(1, [cell("A1", "999", formula=expression), cell("B1", formula=".5+2E1"),
                            cell("C1", formula="AVERAGE(" + ref + "A2:A3)"),
                            cell("D1", formula="MIN(4,2)+MAX(3,7)+PRODUCT(2,3)+ABS(-2)"),
                            cell("E1", formula='"Текст .١ .² A1"', ctype="str")])]),
            (name, [(2, [cell("A2", "2")]), (3, [cell("A3", "3")])])])
        self.assertEqual(payload["status"], "ok")
        a = cells["Итог", "A1"]
        self.assertEqual((a["value"], a["value_type"], a["status"], a["value_origin"]), ("25.5", "number", "computed", "evaluated"))
        self.assertEqual((a["cached_value"], a["cache_status"], a["cached_present"], a["formula"]), ("999", "available", True, expression))
        self.assertEqual(cells["Итог", "B1"]["value"], "20.5")
        self.assertEqual(cells["Итог", "C1"]["value"], "2.5")
        self.assertEqual(cells["Итог", "D1"]["value"], "17")
        self.assertEqual(cells["Итог", "E1"]["value"], "Текст .١ .² A1")
        row = payload["units"][1]
        self.assertEqual((row["anchor"], row["parent_anchor"], row["locator"]), ("sheet:Итог/row:1", "sheet:1", {"sheet": "Итог", "row": 1}))
        self.assertEqual(payload["metadata"]["sheets"], ["Итог", name])
        refs = [e for e in payload["edges"] if e["predicate"] == "formula_ref"]
        self.assertTrue(any(e["target_anchor"] == "sheet:" + name + "/cell:A2" and e["evidence"] == expression for e in refs))
        self.assertTrue(any(e["target_anchor"] == "sheet:" + name + "/cell:A3" and e["evidence"] == expression for e in refs))
        self.assertFalse(any(e["source_anchor"] == "sheet:Итог/cell:E1" for e in refs))
        OBSERVATIONS.append({"case": self._testMethodName, "real_zip_complete_workbook": True, "exact_ids_and_locator": True})

    def test_xlsx_scalar_coercion_and_absent_empty_zero_false_invalid_cache(self):
        payload, c = self.extract([("Data", [
            (1, [cell("A1"), cell("B1", "0"), cell("C1", "0", ctype="b"), cell("D1", "", ctype="str"),
                 cell("E1", "0", ctype="s"), cell("F1", "Книги", ctype="inlineStr"), cell("G1", "#N/A", ctype="e"), cell("H1", "1", ctype="b")]),
            (2, [cell("A2", formula="A1+1"), cell("B2", "0", formula="C1"), cell("C2", "broken", formula="E1+2"),
                 cell("D2", formula="COUNT(A1:H1)"), cell("E2", formula="COUNTA(A1:H1)"),
                 cell("F2", "", formula="D1", ctype="str"), cell("G2", "88", formula="G1"), cell("H2", "0", formula="FALSE", ctype="b")]),
            (3, [cell("A3", "", formula="1+1"), cell("B3", formula="D1", ctype="str"), cell("C3", formula="A1")])])], shared=("00123",))
        self.assertEqual((c["Data", "A1"]["value"], c["Data", "A1"]["value_type"]), (None, "blank"))
        self.assertEqual((c["Data", "B1"]["value"], c["Data", "B1"]["value_type"]), ("0", "number"))
        self.assertEqual((c["Data", "C1"]["value"], c["Data", "C1"]["value_type"]), ("FALSE", "boolean"))
        self.assertEqual((c["Data", "D1"]["value"], c["Data", "D1"]["value_type"]), ("", "text"))
        self.assertEqual(c["Data", "E1"]["value"], "00123")
        for coord, value in (("A2", "1"), ("B2", "FALSE"), ("C2", "125"), ("D2", "1"), ("E2", "7"), ("F2", ""), ("H2", "FALSE"), ("A3", "2"), ("B3", ""), ("C3", "0")):
            self.assertEqual(c["Data", coord]["value"], value)
            self.assertEqual(c["Data", coord]["status"], "computed")
        self.assertEqual((c["Data", "A2"]["cached_present"], c["Data", "A2"]["cache_status"]), (False, "absent"))
        self.assertEqual((c["Data", "F2"]["cached_present"], c["Data", "F2"]["cached_value"], c["Data", "F2"]["cache_status"]), (True, "", "available"))
        self.assertEqual((c["Data", "B3"]["cached_present"], c["Data", "B3"]["cache_status"]), (False, "absent"))
        self.assertEqual((c["Data", "A3"]["cached_present"], c["Data", "A3"]["cache_status"], c["Data", "A3"]["cached_raw_value"]), (True, "absent", ""))
        self.assertEqual((c["Data", "C2"]["cache_status"], c["Data", "C2"]["cached_value"]), ("invalid", None))
        self.assertEqual((c["Data", "G2"]["status"], c["Data", "G2"]["error"], c["Data", "G2"]["value"]), ("error", "#N/A", None))
        self.assertEqual(payload["status"], "partial")

    def test_xlsx_malformed_external_unsupported_cycle_and_healthy_inverse(self):
        formulas_in = ["A1:", "SUM(A1:", ".١", ".²", "ROUND(2,1)", "'[else.xlsx]Data'!A1", "1/0", "H1", "H1+1", ".5+2E1", "'Missing'!A1"]
        coords = [chr(65 + i) + "1" for i in range(len(formulas_in))]
        payload, c = self.extract([("Data", [(1, [cell(coord, "932", formula=f) for coord, f in zip(coords, formulas_in)]),
            (2, [cell("A2", "931", formula="A1+1"), cell("B2", "930", formula="J1+1")])])])
        for coord in ("A1", "B1", "C1", "D1", "E1", "A2"):
            self.assertEqual(c["Data", coord]["status"], "unsupported")
            self.assertEqual((c["Data", coord]["value"], c["Data", coord]["value_origin"]), (None, "none"))
            self.assertTrue(c["Data", coord]["cached_present"])
        self.assertEqual(c["Data", "F1"]["status"], "external_refused")
        self.assertEqual(c["Data", "G1"]["error"], "#DIV/0!")
        self.assertEqual(c["Data", "K1"]["error"], "#REF!")
        for coord in ("H1", "I1"):
            self.assertEqual(c["Data", coord]["status"], "cycle")
            self.assertIsNone(c["Data", coord]["value"])
        self.assertEqual((c["Data", "J1"]["value"], c["Data", "B2"]["value"]), ("20.5", "21.5"))
        self.assertEqual(payload["metadata"]["coverage"]["input_complete"], True)
        self.assertEqual(c["Data", "C1"]["formula"], ".١")
        self.assertEqual(c["Data", "B1"]["formula"], "SUM(A1:")

    def test_xlsx_ooxml_shared_array_followers_empty_formula_and_value_presence(self):
        payload, c = self.extract([("Data", [
            (1, [cell("A1", "93", formula="1+1", attrs={"t": "shared", "si": "0", "ref": "A1:A2"}),
                 cell("B1", "94", formula="1+1", attrs={"t": "array", "ref": "B1:B3"}),
                 cell("C1", "95", formula="1+1", attrs={"t": "dataTable", "ref": "C1:C2"}),
                 cell("D1", "96", formula=""), cell("E1", "97", cell_attrs={"cm": "1"}),
                 cell("F1", "99", formula="2+2", attrs={"t": "normal", "ca": "1"})]),
            (2, [cell("A2", "98", formula="", attrs={"t": "shared", "si": "0"}), cell("B2", "99"), cell("C2", "100"), cell("D2", "", formula="")]),
            (4, [cell("A4", "101", formula="A2+1"), cell("B4", "102", formula="B3+1"), cell("C4", "103", formula="C2+1"),
                 cell("D4", "104", formula="D1+1"), cell("E4", "105", formula="E1+1"), cell("F4", formula="2+3")])])])
        for coord in ("A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E1", "A4", "B4", "C4", "D4", "E4"):
            self.assertEqual(c["Data", coord]["status"], "unsupported")
            self.assertEqual((c["Data", coord]["value"], c["Data", coord]["value_origin"]), (None, "none"))
        self.assertNotIn(("Data", "B3"), c)
        self.assertFalse(c["Data", "B2"]["formula_present"])
        self.assertTrue(c["Data", "B2"]["cached_present"])
        self.assertEqual(c["Data", "B2"]["cached_value"], "99")
        self.assertTrue(c["Data", "D2"]["formula_present"])
        self.assertTrue(c["Data", "D2"]["cached_present"])
        self.assertEqual(c["Data", "D2"]["cached_raw_value"], "")
        self.assertEqual(c["Data", "A2"]["formula_attributes"], {"t": "shared", "si": "0"})
        self.assertEqual((c["Data", "F1"]["value"], c["Data", "F4"]["value"]), ("4", "5"))
        self.assertTrue(payload["metadata"]["coverage"]["evaluation_attempted"])

    def test_xlsx_output_cap_preserves_later_sheet_dependencies_input_cap_does_not_invent_blank(self):
        sheets = [("First", [(1, [cell("A1", "88", formula="'Later'!A2+1"), cell("B1", "4")])]),
                  ("Later", [(2, [cell("A2", "9")])])]
        payload, c = self.extract(sheets, options={"max_units": 2})
        self.assertEqual(c["First", "A1"]["value"], "10")
        self.assertTrue(payload["metadata"]["coverage"]["input_complete"])
        self.assertTrue(payload["metadata"]["coverage"]["output_truncated"])
        self.assertEqual(payload["metadata"]["coverage"]["collected_cells"], 3)
        for options, omitted, reason in (({"max_cells": 2}, (), "max_cells_reached"), ({}, ("Later",), "worksheet_unreadable")):
            partial, cells = self.extract(sheets, options=options, omitted=omitted)
            a = cells["First", "A1"]
            self.assertEqual((a["value"], a["status"], a["value_origin"]), (None, "incomplete_workbook", "none"))
            self.assertEqual((a["cached_value"], a["cache_status"]), ("88", "unvalidated"))
            self.assertEqual(cells["First", "B1"]["value"], "4")
            coverage = partial["metadata"]["coverage"]
            self.assertFalse(coverage["input_complete"])
            self.assertFalse(coverage["evaluation_attempted"])
            self.assertIn(reason, coverage["input_refusals"])
            self.assertEqual(partial["status"], "partial")

    def test_xlsx_limits_shared_budget_real_helper_and_default_range_depth_length(self):
        calls = []
        def lowered(workbook_input):
            calls.append(list(workbook_input))
            return formulas.evaluate_cells(workbook_input, max_operations=7)
        bounded = review.clone_function(self.e.extract_xlsx, evaluate_cells=lowered)
        dispatch = review.clone_function(self.e.extract_document, extract_xlsx=bounded)
        _, c = self.extract([("One", [(1, [cell("A1", "999", formula="1+1"), cell("B1", "4")])]),
                             ("Two", [(1, [cell("A1", "998", formula="1+1"), cell("B1", "5")])])], extractor=dispatch)
        self.assertEqual(calls, [["One", "Two"]])
        self.assertEqual(c["One", "A1"]["value"], "2")
        self.assertEqual((c["Two", "A1"]["status"], c["Two", "A1"]["reason"], c["Two", "A1"]["value"]), ("resource_limit", "operation_limit", None))
        self.assertEqual(c["Two", "B1"]["value"], "5")
        payload, c = self.extract([("Data", [(1, [cell("A1", "99", formula="SUM(A2:A100002)"),
            cell("B1", "98", formula="(" * 65 + "1" + ")" * 65), cell("C1", "97", formula="1" + " " * 8192), cell("D1", formula=".5+2E1")])])])
        for coord, reason in (("A1", "range_cell_limit"), ("B1", "depth_limit"), ("C1", "formula_length_limit")):
            self.assertEqual((c["Data", coord]["status"], c["Data", coord]["reason"], c["Data", coord]["value"]), ("resource_limit", reason, None))
        self.assertEqual(c["Data", "D1"]["value"], "20.5")
        self.assertEqual(payload["metadata"]["formula_policy"], {"engine": "bounded_subset_v1", "max_cells": 100000,
            "max_range_cells": 100000, "max_operations": 250000, "max_depth": 64, "cache_fallback": False})

    def test_xlsx_context_and_generic_redaction_cover_full_raw_and_serialized_outputs(self):
        canary, other, cached = "ContextFixture9988", "ComputedFixture9987", "CachedFixture9986"
        token = "sk-" + "a" * 24
        sheets = [("Data", [(1, [cell("A1", "Name", ctype="inlineStr"), cell("C1", "Password", ctype="inlineStr")]),
            (2, [cell("A2", "Books", ctype="inlineStr"), cell("C2", canary, ctype="str"), cell("D2", formula="C2", ctype="str")]),
            (3, [cell("A3", "Books", ctype="inlineStr"), cell("C3", cached, formula='"' + other + '"', ctype="str"),
                 cell("D3", token, formula='"' + token + '"', ctype="str")]),
            (4, [cell("A4", "Пароль", ctype="inlineStr"), cell("B4", "ContextAdjacent9985", ctype="str"),
                 cell("D4", "999", formula="6+1")])])]
        workbook(self.path, sheets)
        before = self.path.read_bytes()
        document = self.e.extract_xlsx(self.path, 100, 100, ZIP_LIMITS)
        raw, serialized = self.e.asdict(document), document.to_dict()
        for payload in (raw, serialized, self.e.extract_document(self.path, {})):
            text = json.dumps(payload, ensure_ascii=False)
            for secret in (canary, other, cached, token, "ContextAdjacent9985"):
                self.assertNotIn(secret, text)
            self.assertIn("<REDACTED>", text)
            c = cells_by_id(payload)
            self.assertEqual(c["Data", "C2"]["value"], "<REDACTED>")
            self.assertEqual(c["Data", "C3"]["value"], "<REDACTED>")
            self.assertEqual(c["Data", "C3"]["cached_value"], "<REDACTED>")
            self.assertEqual(c["Data", "D2"]["value"], "<REDACTED>")
            self.assertTrue(any(e["predicate"] == "formula_ref" for e in payload["edges"]))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn(canary, self.e.clean_text(canary))  # context, not token-pattern redaction
        self.assertEqual(cells_by_id(serialized)["Data", "D4"]["value"], "<REDACTED>")
        self.assertEqual(serialized["metadata"]["formula_context_redaction"], "workbook_conservative")
        bounded, c = self.extract([("Long", [(1, [cell("A1", "x" * 20001, ctype="inlineStr")])])])
        self.assertEqual(c["Long", "A1"]["value"], "x" * 20000)
        self.assertTrue(c["Long", "A1"]["output_truncated"])
        self.assertTrue(bounded["metadata"]["coverage"]["output_truncated"])
        self.assertEqual(bounded["status"], "partial")

    def test_xlsx_rejects_duplicate_invalid_ids_and_preserves_zip_and_source_caps(self):
        for bad in ("a1", "А1", "A01", "$A$1", "XFE1", "A1048577", ""):
            workbook(self.path, [("Data", [(1, [cell(bad, "4")])])])
            with self.assertRaises(ValueError):
                self.e.extract_document(self.path, {})
        for sheets in ([ ("Data", [(1, [cell("A1", "4"), cell("A1", "9")])]) ],
                       [ ("Data", [(1, [cell("A1", "4")]), (1, [cell("B1", "9")])]) ],
                       [ ("Same", []), ("Same", []) ]):
            workbook(self.path, sheets)
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                self.e.extract_document(self.path, {})
            self.assertEqual(self.path.read_bytes(), before)
        workbook(self.path, [("Data", [(1, [cell("A1", "4")])])])
        with self.assertRaises(ValueError):
            self.e.extract_document(self.path, {"max_bytes": 1})
        with self.assertRaises(ValueError):
            self.e.extract_xlsx(self.path, 100, 100, {**ZIP_LIMITS, "max_member": 1})
        # A declared oversized formula region does not fabricate its missing follower.
        payload, c = self.extract([("Data", [(1, [cell("A1", "99", formula="1", attrs={"t": "array", "ref": "A1:XFD1048576"}),
                                                       cell("B1", "98", formula="Z9000+1"), cell("C1", "4")])])])
        self.assertFalse(payload["metadata"]["coverage"]["evaluation_attempted"])
        self.assertEqual((c["Data", "B1"]["status"], c["Data", "B1"]["value"]), ("incomplete_workbook", None))
        self.assertEqual(c["Data", "C1"]["value"], "4")

    def test_xlsx_identity_invalidates_3_1_5_and_current_fingerprint_axes(self):
        e, path = self.e, Path("fixture.xlsx")
        self.assertEqual((e.EXTRACTOR_VERSION, e.SECRET_POLICY_VERSION), ("3.1.8", "3.0.0"))
        previous = review.clone_function(e.extraction_options_fingerprint, EXTRACTOR_VERSION="3.1.5")
        self.assertNotEqual(e.extraction_options_fingerprint(path, {}), previous(path, {}))
        for options in ({}, {"max_cells": 2}, {"max_units": 2}):
            self.assertEqual(e.extraction_options_fingerprint(path, options), e.extraction_options_fingerprint(path, e.effective_extraction_options(options)))
        self.assertNotEqual(e.extraction_options_fingerprint(path, {}), e.extraction_options_fingerprint(path, {"max_cells": 2}))
        self.assertEqual(e.effective_extraction_options({})["max_cells"], 500000)
        self.assertEqual(e.ExtractedDocument("none", "application/xlsx", "Fixture", []).to_dict()["extractor_version"], "3.1.8")


def packet_suite():
    return unittest.TestSuite([chain.packet_suite(), unittest.defaultTestLoader.loadTestsFromTestCase(XlsxFormulaSourceTests)])


def metadata_preflight():
    expected = chain.metadata_preflight() + [case._testMethodName for case in unittest.defaultTestLoader.loadTestsFromTestCase(XlsxFormulaSourceTests)]
    assert len(expected) == len(set(expected))
    assert OBSERVATIONS == []
    e = review.peer.load_source(review.peer.EXTRACTOR, "document_extractors")
    assert e.evaluate_cells is formulas.evaluate_cells
    assert Path(formulas.__file__) == HELPER
    return expected


if __name__ == "__main__" and "devtools_case_started" in globals():
    peer_tree = ast.parse(read_source(review.PEER_PATH))
    reporter = next(n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult")
    exec(compile(ast.Module(body=[reporter], type_ignores=[]), str(review.PEER_PATH), "exec", dont_inherit=True), globals())
    result = PacketResult()
    packet_suite().run(result)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "terminal_compositions": chain.terminal.OBSERVATIONS, "cleanup_compositions": chain.cleanup.OBSERVATIONS,
        "pdf_compositions": chain.composition.OBSERVATIONS, "causal_compositions": chain.OBSERVATIONS,
        "xlsx_compositions": OBSERVATIONS,
        "qualification": "SOURCE original72 setup/cleanup plus real OOXML->exact bounded helper->sanitized output; shared lowered-budget observation is actual evaluator, not engine/SDK/native/FULL"}, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
elif __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(packet_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
