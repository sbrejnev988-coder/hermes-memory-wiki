"""Pure stdlib whole-module SOURCE cases, без SDK/package __init__/XLSX I/O.

Обычный unittest/pytest import поддержан; SOURCE entry использует тот же TestCase
и постоянный devtools/source_bootstrap.py, не собственный test framework.
"""
import ast
from collections import UserDict
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

_SOURCE = Path(__file__).absolute().parents[1] / "spreadsheet_formulas.py"
_SPEC = importlib.util.spec_from_file_location("bounded_spreadsheet_formulas", str(_SOURCE))
_MODULE = importlib.util.module_from_spec(_SPEC)
if "devtools_read_bound" in globals():
    _RAW = devtools_read_bound(str(_SOURCE))
    exec(compile(_RAW, str(_SOURCE), "exec", dont_inherit=True), _MODULE.__dict__)
else:
    _RAW = _SOURCE.read_bytes()
    _SPEC.loader.exec_module(_MODULE)
evaluate_cells = _MODULE.evaluate_cells


def cell(value=None, formula="", ctype=""):
    return {"value": value, "formula": formula, "type": ctype}


class BoundedFormulas(unittest.TestCase):
    def computed(self, formula, expected, *, cells=None, kind="number", **bounds):
        book = {"S": dict(cells or {})}
        book["S"]["Z1"] = cell(None, formula)
        result = evaluate_cells(book, **bounds)["S"]["Z1"]
        self.assertEqual(result["status"], "computed", (formula, result))
        self.assertEqual(result["value_origin"], "evaluated")
        self.assertEqual(result["value_type"], kind)
        self.assertEqual(result["value"], expected)
        self.assertIsNone(result["error"])
        self.assertEqual(result["formula"], formula)
        return result

    def refused(self, formula, status="unsupported", *, cells=None, reason=None, **bounds):
        book = {"S": dict(cells or {})}
        book["S"]["Z1"] = cell(98765, formula, "n")
        result = evaluate_cells(book, **bounds)["S"]["Z1"]
        self.assertEqual(result["status"], status, (formula, result))
        self.assertIsNone(result["value"])
        self.assertEqual(result["value_origin"], "none")
        self.assertEqual(result["cached_value"], 98765)
        self.assertEqual(result["cache_status"], "available")
        self.assertLessEqual(len(result["reason"]), 64)
        if reason is not None:
            self.assertEqual(result["reason"], reason)
        return result

    def formula_error(self, formula, error, *, cells=None):
        book = {"S": dict(cells or {})}
        book["S"]["Z1"] = cell(999, formula, "n")
        result = evaluate_cells(book)["S"]["Z1"]
        self.assertEqual(result["status"], "error", (formula, result))
        self.assertEqual(result["value_type"], "error")
        self.assertEqual(result["value_origin"], "evaluated")
        self.assertIsNone(result["value"])
        self.assertEqual(result["error"], error)
        self.assertEqual(result["cached_value"], 999)

    def test_arithmetic_precedence_and_excel_power(self):
        for formula, expected in (("1+2*3", 7), ("=(1+2)*3", 9), ("10-3-2", 5),
                                  ("8/4/2", 1), ("-2^2", 4), ("2^3^2", 64),
                                  ("2^-2", 0.25), ("2^(-2)", 0.25),
                                  ("ABS(-4.5)+5%", 4.55), ("50%%", 0.005),
                                  ("1.5e2+.5-2E-1", 150.3), ("+3+-2", 1)):
            self.computed(formula, expected)

    def test_booleans_text_numeric_coercion_and_inert_strings(self):
        self.computed('TRUE+FALSE+"2.5"', 3.5)
        self.computed('"a""b"', 'a"b', kind="text")
        self.computed('"[Book]Sheet!A1 https://example.invalid cmd|x"',
                      "[Book]Sheet!A1 https://example.invalid cmd|x", kind="text")
        self.computed("FALSE", False, kind="boolean")
        self.formula_error('"not a number"+1', "#VALUE!")
        self.formula_error('""+1', "#VALUE!")

    def test_typed_literals_match_current_ooxml_raw_cells(self):
        source = {"S": {"A1": cell("42", ctype="n"), "A2": cell("TRUE", ctype="b"),
                        "A3": cell("00123", ctype="s"), "A4": cell("text", ctype="inlineStr"),
                        "A5": cell("", ctype="str"), "A6": cell(""), "A7": cell(False),
                        "A8": cell(0), "A9": cell("1", ctype="b"), "A10": cell(None)}}
        result = evaluate_cells(source)["S"]
        expected = [("number", 42), ("boolean", True), ("text", "00123"), ("text", "text"),
                    ("text", ""), ("blank", None), ("boolean", False), ("number", 0),
                    ("boolean", True), ("blank", None)]
        for coordinate, (kind, value) in zip(source["S"], expected):
            row = result[coordinate]
            self.assertEqual((row["status"], row["value_type"], row["value"]), ("literal", kind, value))
            self.assertEqual(row["value_origin"], "input")
            self.assertEqual(row["cache_status"], "not_applicable")

    def test_absolute_reference_chain_and_formula_without_equals(self):
        cells = {"A1": cell("12", ctype="n"), "A2": cell(None, "$A$1*2"),
                 "A3": cell(None, "$A2+A$1"), "A4": cell(None, "=A3")}
        self.computed("A4", 36, cells=cells)
        self.computed("A1", 12, cells=cells)

    def test_forward_dependencies_and_diamond_reuse(self):
        book = {"S": {"A1": cell(None, "B1+C1"), "B1": cell(None, "D1*2"),
                       "C1": cell(None, "D1+1"), "D1": cell(None, "6*7")}}
        result = evaluate_cells(book)["S"]
        self.assertEqual([r["value"] for r in result.values()], [127, 84, 43, 42])
        self.assertTrue(all(r["status"] == "computed" for r in result.values()))

    def test_blank_missing_zero_false_and_empty_text_are_distinct(self):
        cells = {"A1": cell(None), "A2": cell(0), "A3": cell(False), "A4": cell("", ctype="str")}
        for formula in ("A1", "B9", "A1+0", "B9+0"):
            self.computed(formula, 0, cells=cells)
        self.computed("A3", False, cells=cells, kind="boolean")
        self.computed("A4", "", cells=cells, kind="text")
        self.computed("COUNT(A1:A4)", 1, cells=cells)
        self.computed("COUNTA(A1:A4)", 3, cells=cells)

    def test_common_aggregates_rectangles_reverse_sparse_and_nested(self):
        cells = {"A1": cell(1), "B1": cell(2), "A2": cell(3), "B2": cell(4)}
        for formula, expected in (("SUM(A1:B2)", 10), ("SUM(B2:A1)", 10),
                                  ("AVERAGE(A1:B2)", 2.5), ("MIN(A1:B2)", 1),
                                  ("MAX(A1:B2)", 4), ("COUNT(A1:C3)", 4),
                                  ("COUNTA(A1:C3)", 4), ("PRODUCT(A1:B2)", 24),
                                  ("SUM(SUM(A1:A2),MAX(B1:B2),5)", 13),
                                  ("sum($A$1:$B$2)", 10)):
            self.computed(formula, expected, cells=cells)

    def test_aggregate_reference_vs_direct_scalar_coercion(self):
        cells = {"A1": cell("2", ctype="s"), "A2": cell(True), "A3": cell(3),
                 "A4": cell("hello", ctype="str")}
        self.computed('SUM(A1:A4,"2",TRUE)', 6, cells=cells)
        self.computed('AVERAGE(A1:A4,"2",TRUE)', 2, cells=cells)
        self.computed('COUNT(A1:A4,"2",TRUE,"not numeric")', 3, cells=cells)
        self.computed("COUNTA(A1:A5)", 4, cells=cells)
        self.computed("A1+A2", 3, cells=cells)
        self.formula_error('SUM("not numeric")', "#VALUE!")

    def test_empty_aggregates_and_all_text_ranges(self):
        for formula in ("SUM()", "COUNT()", "COUNTA()", "MIN()", "MAX()", "PRODUCT()",
                        "SUM(A1:A3)", "MIN(A1:A3)", "PRODUCT(A1:A3)"):
            self.computed(formula, 0)
        self.formula_error("AVERAGE()", "#DIV/0!")
        self.formula_error("AVERAGE(A1:A3)", "#DIV/0!")
        self.formula_error("AVERAGE(A1:A3)", "#DIV/0!", cells={"A1": cell("text", ctype="s")})

    def test_inter_sheet_exact_unicode_whitespace_and_apostrophes(self):
        book = {"Totals": {"A1": cell(None, "' Данные '!$B$2+Data!A1+'O''Brien'!A1")},
                " Данные ": {"B2": cell(10)}, "Data": {"A1": cell(2)},
                "O'Brien": {"A1": cell(3)}}
        result = evaluate_cells(book)
        self.assertEqual(result["Totals"]["A1"]["value"], 15)
        self.assertEqual(list(result), list(book))
        self.assertEqual(list(result[" Данные "]), ["B2"])
        book["Totals"]["A1"]["formula"] = "'Данные'!B2"
        self.assertEqual(evaluate_cells(book)["Totals"]["A1"]["error"], "#REF!")

    def test_inter_sheet_aggregates_and_dependency_chains(self):
        book = {"Summary": {"A1": cell(None, "SUM('Raw data'!$A$1:$B$2)+Next!A1")},
                "Raw data": {"A1": cell(1), "B1": cell(2), "A2": cell(3), "B2": cell(4)},
                "Next": {"A1": cell(None, "'Raw data'!A1*5")}}
        row = evaluate_cells(book)["Summary"]["A1"]
        self.assertEqual((row["status"], row["value"]), ("computed", 15))
        book["Summary"]["A1"]["formula"] = "SUM('Raw data'!A1:'Raw data'!B2)"
        self.assertEqual(evaluate_cells(book)["Summary"]["A1"]["value"], 10)

    def test_sheet_ids_are_not_casefolded_or_unicode_normalized(self):
        book = {"S": {"A1": cell(None, "'é'!A1+'é'!A1"), "A2": cell(None, "data!A1")},
                "é": {"A1": cell(2)}, "é": {"A1": cell(3)}, "Data": {"A1": cell(9)}}
        result = evaluate_cells(book)
        self.assertEqual(result["S"]["A1"]["value"], 5)
        self.assertEqual(result["S"]["A2"]["error"], "#REF!")
        self.assertEqual(list(result), list(book))

    def test_errors_propagate_and_counta_counts_actual_input_errors(self):
        cells = {"A1": cell("#N/A", ctype="e"), "A2": cell(None, "1/0"), "A3": cell(2)}
        for formula, error in (("A1+1", "#N/A"), ("SUM(A1:A3)", "#N/A"),
                               ("A2", "#DIV/0!"), ("ABS(A1)", "#N/A")):
            self.formula_error(formula, error, cells=cells)
        self.computed("COUNT(A1:A3)", 1, cells=cells)
        self.computed("COUNTA(A1:A3)", 3, cells=cells)
        self.formula_error("#REF!+1", "#REF!")
        self.computed("COUNT(#N/A)", 0)
        self.computed("COUNT(1,1/0,2,#REF!)", 2)
        self.computed("COUNT(ABS(A1),A1+0,A2)", 0, cells=cells)
        self.computed("COUNTA(1/0,#REF!)", 2)
        row = evaluate_cells({"S": {"A1": cells["A1"]}})["S"]["A1"]
        self.assertEqual((row["status"], row["error"], row["value_origin"]), ("error", "#N/A", "input"))

    def test_division_power_domains_and_finite_overflow(self):
        for formula, error in (("1/0", "#DIV/0!"), ("0^-1", "#DIV/0!"),
                               ("0^0", "#NUM!"), ("(-1)^.5", "#NUM!"),
                               ("1e309", "#NUM!"), ("1e308*10", "#NUM!"),
                               ("2^999999999", "#NUM!"), ("SUM(1e308,1e308)", "#NUM!"),
                               ("PRODUCT(1e308,10)", "#NUM!")):
            self.formula_error(formula, error)
        self.computed("1e-309*1e-309", 0)

    def test_nonfinite_inputs_and_malformed_typed_values(self):
        for value, ctype, error in ((math.inf, "n", "#NUM!"), (math.nan, "", "#NUM!"),
                                    (10**1000, "n", "#NUM!"), ("NaN", "n", "#VALUE!"),
                                    ("2", "b", "#VALUE!"), (True, "n", "#VALUE!"),
                                    ("unknown", "e", "#VALUE!"), (42, "s", "#VALUE!")):
            row = evaluate_cells({"S": {"A1": cell(value, ctype=ctype)}})["S"]["A1"]
            self.assertEqual((row["status"], row["error"], row["value"]), ("error", error, None))
            json.dumps(row, allow_nan=False)

    def test_cached_values_do_not_override_computation(self):
        book = {"S": {"A1": cell("999", "1+2", "n"), "A2": cell("FALSE", "TRUE", "b"),
                       "A3": cell("old", '"new"', "str"), "A4": cell("#REF!", "4", "e")}}
        result = evaluate_cells(book)["S"]
        for coordinate, expected, cached in (("A1", 3, 999), ("A2", True, False),
                                             ("A3", "new", "old"), ("A4", 4, "#REF!")):
            row = result[coordinate]
            self.assertEqual((row["status"], row["value"], row["cached_value"]), ("computed", expected, cached))
            self.assertEqual(row["cache_status"], "available")

    def test_missing_and_invalid_cache_are_not_fabricated(self):
        for raw, ctype, cache_status in ((None, "n", "absent"), ("", "", "absent"),
                                         (math.inf, "n", "invalid"), ("oops", "n", "invalid"),
                                         ("not-an-error-code", "e", "invalid"), (math.inf, "e", "invalid")):
            row = evaluate_cells({"S": {"A1": cell(raw, "2+3", ctype)}})["S"]["A1"]
            self.assertEqual((row["status"], row["value"], row["cache_status"]), ("computed", 5, cache_status))
            self.assertIsNone(row["cached_value"])
            json.dumps(row, allow_nan=False)

    def test_unsupported_functions_names_arrays_and_operators_no_cache_fallback(self):
        for formula in ("IF(TRUE,1,2)", "ROUND(1.25,1)", "_xlfn.SUM(1,2)", "NamedRange+1",
                        "SUM(A:A)", "SUM(1:2)", "SUM(Table[Column])", "{1,2}", "A1#",
                        "A1&A2", "A1=2", "A1>0", "SUM(1;2)", "R1C1", "@A1", "a1", "A01"):
            status = "external_refused" if "[" in formula else "unsupported"
            self.refused(formula, status=status)
        self.refused("ABS(1,2)", reason="function_arity_unsupported")
        self.refused("A1:A2", reason="range_requires_aggregate")
        self.refused("SUM(S!A1:T!A2)", reason="cross_sheet_range_unsupported")

    def test_external_links_dde_paths_and_network_functions_refused(self):
        for formula in ("'[Book.xlsx]Sheet'!A1", "[1]Sheet1!A1", "'C:\\Book.xlsx'!A1",
                        "'https://example.invalid/Book.xlsx'!A1", "cmd|'x'!A1", "'S:T'!A1"):
            self.refused(formula, status="external_refused")
        for formula in ('WEBSERVICE("https://example.invalid")', 'HYPERLINK("https://example.invalid")',
                        'INDIRECT("A1")', 'EXEC("cmd")', 'CALL("library")', 'RTD("server",,"x")'):
            self.refused(formula)

    def test_malformed_formula_is_not_partial_success(self):
        for formula in ("=", "  ", "1+", "1+2 trailing", "(1+2", "1+2)", '"unterminated',
                        "'unterminated", "SUM(1,)", "SUM(,1)", "SUM(1 2)", "A1 B1", "A1!",
                        "S!", "1..2", "1e", "==1", "1/", "()", "A1::A2", "1+2+[]"):
            self.refused(formula, status="external_refused" if "[" in formula else "unsupported")

    def test_dependency_refusals_never_become_numeric_or_count_success(self):
        for function in ("SUM", "COUNT", "COUNTA"):
            book = {"S": {"A1": cell(99, "INDIRECT(\"A2\")"),
                           "A2": cell(888, function + "(A1:A1)")}}
            result = evaluate_cells(book)["S"]
            self.assertEqual(result["A1"]["status"], "unsupported")
            self.assertEqual(result["A2"]["status"], "unsupported")
            self.assertIsNone(result["A2"]["value"])
            self.assertEqual(result["A2"]["value_origin"], "none")
        book = {"S": {"A1": cell(99, "'[Book]S'!A1"), "A2": cell(888, "A1+1")}}
        self.assertEqual(evaluate_cells(book)["S"]["A2"]["status"], "external_refused")

    def test_self_cycle_mutual_cycle_and_unrelated_healthy_cell(self):
        for cells in ({"A1": cell(7, "A1+1")},
                      {"A1": cell(7, "A2+1"), "A2": cell(8, "A1+1")},
                      {"A1": cell(7, "SUM(A1:A2)"), "A2": cell(2)}):
            cells["Z1"] = cell(None, "2+2")
            result = evaluate_cells({"S": cells})["S"]
            self.assertEqual(result["A1"]["status"], "cycle")
            self.assertIsNone(result["A1"]["value"])
            self.assertEqual((result["Z1"]["status"], result["Z1"]["value"]), ("computed", 4))
            self.assertEqual(result["A1"]["cached_value"], 7)

    def test_inter_sheet_cycle_and_dependent_cycle(self):
        book = {"S": {"A1": cell(4, "T!A1"), "A2": cell(5, "A1+1")},
                "T": {"A1": cell(6, "S!A1")}}
        result = evaluate_cells(book)
        for sheet in result.values():
            for row in sheet.values():
                self.assertEqual(row["status"], "cycle")
                self.assertEqual(row["value_origin"], "none")
                self.assertIsNone(row["value"])

    def test_range_exact_bound_plus_one_and_sparse_work_limit(self):
        self.computed("SUM(A1:B2)", 4, cells={"A1": cell(4)}, max_range_cells=4)
        self.refused("SUM(A1:B2)", status="resource_limit", reason="range_cell_limit", max_range_cells=3)
        self.refused("SUM(A1:XFD1048576)", status="resource_limit", reason="range_cell_limit")
        self.refused("SUM(A1:A100001)", status="resource_limit", reason="range_cell_limit")
        self.refused("SUM(A1:A100000)", status="resource_limit", reason="operation_limit", max_operations=25)

    def test_operations_are_global_not_reset_per_formula(self):
        # Каждый '1' расходует cell + token + AST = 3 operations.
        book = {"S": {"A1": cell(None, "1"), "A2": cell(99, "1"), "A3": cell(7)}}
        result = evaluate_cells(book, max_operations=3)["S"]
        self.assertEqual((result["A1"]["status"], result["A1"]["value"]), ("computed", 1))
        self.assertEqual((result["A2"]["status"], result["A2"]["reason"]), ("resource_limit", "operation_limit"))
        self.assertEqual((result["A3"]["status"], result["A3"]["value"]), ("literal", 7))
        self.assertEqual(result["A2"]["cached_value"], 99)
        self.computed("1", 1, max_operations=3)
        self.refused("1", status="resource_limit", reason="operation_limit", max_operations=2)

    def test_depth_parser_evaluation_and_dependency_limits(self):
        self.computed("((1))", 1, max_depth=2)
        self.refused("(((1)))", status="resource_limit", reason="depth_limit", max_depth=2)
        self.refused("+" * 200 + "1", status="resource_limit", reason="depth_limit")
        self.refused("+".join(["1"] * 200), status="resource_limit", reason="depth_limit")
        self.refused("SUM(" * 100 + "1" + ")" * 100, status="resource_limit", reason="depth_limit")
        cells = {"A" + str(i): cell(None, "A" + str(i + 1)) for i in range(1, 80)}
        cells["A80"] = cell(5)
        result = evaluate_cells({"S": cells}, max_depth=8)["S"]
        self.assertEqual(result["A1"]["status"], "resource_limit")
        self.assertEqual(result["A79"]["status"], "computed")
        self.assertEqual(result["A79"]["value"], 5)

    def test_formula_token_argument_and_text_limits(self):
        self.refused("1" * 8193, status="resource_limit", reason="formula_length_limit")
        self.refused("+".join(["1"] * 2050), status="resource_limit", reason="token_limit")
        self.computed("SUM(" + ",".join(["1"] * 255) + ")", 255)
        self.refused("SUM(" + ",".join(["1"] * 256) + ")", status="resource_limit", reason="argument_limit")
        book = {"S": {"A1": cell("x" * 32768, ctype="s"), "A2": cell("x" * 32767, ctype="s")}}
        result = evaluate_cells(book)["S"]
        self.assertEqual((result["A1"]["status"], result["A1"]["reason"]), ("resource_limit", "text_length_limit"))
        self.assertEqual(result["A2"]["status"], "literal")
        self.assertEqual(len(result["A2"]["value"]), 32767)

    def test_cell_cap_is_atomic_no_silent_drop(self):
        book = {"S": {"A1": cell(1), "A2": cell(None, "A1+1")}, "Empty": {}}
        self.assertEqual(len(evaluate_cells(book, max_cells=2)["S"]), 2)
        before = copy.deepcopy(book)
        with self.assertRaisesRegex(ValueError, "max_cells_exceeded"):
            evaluate_cells(book, max_cells=1)
        self.assertEqual(book, before)
        self.assertEqual(evaluate_cells({}), {})
        self.assertEqual(evaluate_cells({"Empty": {}}), {"Empty": {}})

    def test_bad_bounds_never_coerced_or_clamped(self):
        for name, ceiling in (("max_cells", 100000), ("max_range_cells", 100000),
                              ("max_operations", 250000), ("max_depth", 64)):
            for bad in (0, -1, True, 1.0, "1", None, ceiling + 1):
                with self.assertRaisesRegex(ValueError, "invalid_" + name):
                    evaluate_cells({}, **{name: bad})

    def test_invalid_ids_and_record_shapes_refuse_without_repair(self):
        for identifier in ("a1", "A01", "$A$1", " A1", "A1 ", "XFE1", "A1048577", "A0", "А1", 1):
            with self.assertRaisesRegex(ValueError, "invalid_literal_cell_id"):
                evaluate_cells({"S": {identifier: cell(1)}})
        for book in ([], {"": {}}, {1: {}}, {"S": []}, {"S": {"A1": []}},
                     {"S": {"A1": {"value": 1}}}, {"S": {"A1": cell([], "")}},
                     {"S": {"A1": {"value": 1, "formula": None, "type": ""}}}):
            with self.assertRaises(ValueError):
                evaluate_cells(book)
        result = evaluate_cells({"S": {"XFD1048576": cell(5)}})
        self.assertEqual(list(result["S"]), ["XFD1048576"])

    def test_mappings_supported_no_mutation_or_result_aliases(self):
        record = cell("12", "  =A2+1  ", "n")
        record["caller_metadata"] = {"not": ["owned"]}
        # '=' обязателен в начале, не после whitespace: не чинить literal formula.
        record["formula"] = "= A2+1  "
        book = UserDict({" S ": UserDict({"A1": record, "A2": cell(3)})})
        before = copy.deepcopy(book)
        result = evaluate_cells(book)
        self.assertEqual(book, before)
        self.assertEqual(result[" S "]["A1"]["formula"], "= A2+1  ")
        self.assertEqual(result[" S "]["A1"]["value"], 4)
        self.assertIsNot(result[" S "]["A1"], record)
        result[" S "]["A1"]["value"] = 100
        result[" S "]["A2"]["formula"] = "malicious change"
        self.assertEqual(book, before)
        self.assertNotIn("caller_metadata", result[" S "]["A1"])

    def test_unknown_date_type_and_resource_dependency_are_explicit(self):
        for ctype in ("d", "custom"):
            book = {"S": {"A1": cell("2026-10-19", ctype=ctype), "A2": cell(123, "A1")}}
            result = evaluate_cells(book)["S"]
            self.assertEqual(result["A1"]["status"], "unsupported")
            self.assertEqual(result["A2"]["status"], "unsupported")
            self.assertIsNone(result["A2"]["value"])
        book = {"S": {"A1": cell(None, "SUM(A3:A8)"), "A2": cell(123, "A1")}}
        result = evaluate_cells(book, max_range_cells=5)["S"]
        self.assertEqual(result["A2"]["status"], "resource_limit")
        self.assertIsNone(result["A2"]["value"])

    def test_shared_refusal_fanout_and_repeat_calls_do_not_leak_state(self):
        cells = {"A1": cell(9, "A1")}
        cells.update({"A" + str(i): cell(99, "A1+1") for i in range(2, 1002)})
        book = {"S": cells}
        before = copy.deepcopy(book)
        first = evaluate_cells(book)
        second = evaluate_cells(book)
        self.assertEqual(first, second)
        self.assertEqual(book, before)
        self.assertTrue(all(row["status"] == "cycle" for row in first["S"].values()))
        self.assertTrue(all(row["value"] is None for row in first["S"].values()))
        # Ошибка во входе не должна переживать отдельный здоровый вызов.
        book["S"]["A1"]["formula"] = "1"
        healthy = evaluate_cells(book)
        self.assertEqual(healthy["S"]["A1001"]["value"], 2)
        self.assertEqual(healthy["S"]["A1001"]["status"], "computed")

    def test_refusal_error_and_cycle_preserve_original_records(self):
        book = {" S ": {"A1": cell(99, "1/0"), "A2": cell(88, "A2"),
                         "A3": cell(77, "UNKNOWN_FUNCTION()"),
                         "A4": cell(66, "'[Book]Sheet'!A1")}}
        before = copy.deepcopy(book)
        result = evaluate_cells(book)
        self.assertEqual(book, before)
        self.assertEqual([row["status"] for row in result[" S "].values()],
                         ["error", "cycle", "unsupported", "external_refused"])
        for coordinate, record in result[" S "].items():
            self.assertIsNot(record, book[" S "][coordinate])
            self.assertEqual(record["formula"], book[" S "][coordinate]["formula"])
            self.assertIsNone(record["value"])

    def test_regression_no_python_execution_or_unlisted_runtime_imports(self):
        tree = ast.parse(_RAW)
        forbidden = {"eval", "exec", "compile", "open", "__import__", "getattr", "setattr"}
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertEqual(calls & forbidden, set())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {"__future__", "collections.abc", "math", "re"})
        for payload in ('__import__("os").system("x")', 'open("x","w")',
                        'exec("x")', 'eval("1+1")', '(lambda:1)()', '[x for x in y]'):
            self.refused(payload, status="external_refused" if payload.startswith("[") else "unsupported")

    def test_regression_output_is_strict_json_and_reasons_no_source_echo(self):
        book = {"S": {"A1": cell(None, "1+2"), "A2": cell(math.nan, "DANGEROUS_SOURCE_MARKER()", "n"),
                       "A3": cell(None, "A3"), "A4": cell(None, "1/0"),
                       "A5": cell(None, "'[ForeignBook]Sheet'!A1")}}
        result = evaluate_cells(book)
        json.dumps(result, allow_nan=False)
        for row in result["S"].values():
            self.assertLessEqual(len(row["reason"]), 64)
            self.assertNotIn("DANGEROUS_SOURCE_MARKER", row["reason"])
            self.assertNotIn("ForeignBook", row["reason"])
        self.assertEqual(result["S"]["A2"]["formula"], "DANGEROUS_SOURCE_MARKER()")
        self.assertEqual(result["S"]["A2"]["cache_status"], "invalid")

    def _boundary_refused(self, formula, reason):
        book = {"S": {"A1": cell(99, formula, "n"), "B1": cell(777, "=1+1", "n")}}
        before = copy.deepcopy(book)
        result = evaluate_cells(book)
        self.assertEqual(book, before)
        self.assertEqual(list(result), ["S"])
        self.assertEqual(list(result["S"]), ["A1", "B1"])
        bad, healthy = result["S"]["A1"], result["S"]["B1"]
        self.assertEqual((bad["status"], bad["value_origin"], bad["value_type"]),
                         ("unsupported", "none", "unknown"))
        self.assertEqual(bad["reason"], reason)
        self.assertLessEqual(len(bad["reason"]), 64)
        self.assertIsNone(bad["value"])
        self.assertIsNone(bad["error"])
        self.assertEqual((bad["formula"], bad["type"]), (formula, "n"))
        self.assertEqual((bad["cached_value"], bad["cached_value_type"], bad["cache_status"]),
                         (99, "number", "available"))
        self.assertEqual((healthy["status"], healthy["value_origin"], healthy["value_type"], healthy["value"]),
                         ("computed", "evaluated", "number", 2))
        self.assertEqual((healthy["formula"], healthy["cached_value"], healthy["cache_status"]),
                         ("=1+1", 777, "available"))
        self.assertEqual(healthy["reason"], "")
        self.assertIsNone(healthy["error"])
        json.dumps(result, allow_nan=False)

    def test_regression_trailing_range_eof_is_cell_local(self):
        for formula in ("A1:", "=A1:", "A1: \t\r\n", "$A$1:", "S!A1:", "'Данные'!A1:"):
            self._boundary_refused(formula, "invalid_formula")

    def test_regression_aggregate_range_eof_is_cell_local(self):
        for formula in ("SUM(A1:", "=SUM(A1:", "SUM($A$1: \t", "SUM(SUM(A1:",
                        "SUM('Данные'!A1:", "SUM(A1:S!", "SUM(A1:'Данные'!"):
            self._boundary_refused(formula, "invalid_formula")

    def test_regression_unicode_numeric_lookahead_is_cell_local(self):
        # Arabic-Indic decimal, superscript digit, fullwidth и Devanagari:
        # Unicode isdigit не является ASCII numeric grammar.
        for formula in (".١", ".²", ".１", ".१", "=.١", ".² \t", "1+.²", "SUM(.١)"):
            self._boundary_refused(formula, "operator_or_syntax_unsupported")

    def test_regression_ascii_decimal_scientific_after_refusal(self):
        formulas = (("B1", ".5", 0.5), ("C1", "2E-3", 0.002),
                    ("D1", ".5e+2", 50), ("E1", "5.e-1", 0.5))
        book = {"S": {"A1": cell(99, ".²", "n")}}
        book["S"].update({key: cell(777, formula, "n") for key, formula, _ in formulas})
        before = copy.deepcopy(book)
        result = evaluate_cells(book)["S"]
        self.assertEqual(book, before)
        self.assertEqual(result["A1"]["status"], "unsupported")
        self.assertEqual(list(result), list(book["S"]))
        for key, formula, expected in formulas:
            row = result[key]
            self.assertEqual((row["status"], row["value_origin"], row["value_type"], row["value"]),
                             ("computed", "evaluated", "number", expected))
            self.assertEqual((row["formula"], row["cached_value"], row["cache_status"]),
                             (formula, 777, "available"))

    def test_regression_legal_ranges_after_truncated_range(self):
        book = {"S": {"A1": cell(99, "A1:", "n"), "B1": cell(777, "SUM(D1:E2)", "n"),
                       "C1": cell(888, "SUM('Данные١²'!A1:'Данные١²'!A2)", "n"),
                       "D1": cell(1), "E1": cell(2), "D2": cell(3), "E2": cell(4)},
                "Данные١²": {"A1": cell(2), "A2": cell(3)}}
        before = copy.deepcopy(book)
        result = evaluate_cells(book)
        self.assertEqual(book, before)
        self.assertEqual(list(result), list(book))
        self.assertEqual((result["S"]["A1"]["status"], result["S"]["A1"]["reason"]),
                         ("unsupported", "invalid_formula"))
        for key, expected, cached in (("B1", 10, 777), ("C1", 5, 888)):
            row = result["S"][key]
            self.assertEqual((row["status"], row["value_origin"], row["value"]),
                             ("computed", "evaluated", expected))
            self.assertEqual(row["cached_value"], cached)
            self.assertEqual(row["formula"], book["S"][key]["formula"])

    def test_regression_unicode_text_and_sheet_tokens_remain_inert(self):
        book = {"S": {"A1": cell(99, ".١", "n"), "B1": cell(777, '".١ .²"', "n"),
                       "C1": cell(888, "'.١²'!A1", "n"), "D1": cell(999, "Данные١²!A1", "n"),
                       "E1": cell(".١ .²", ctype="s")},
                ".١²": {"A1": cell(7)}, "Данные١²": {"A1": cell(9)}}
        before = copy.deepcopy(book)
        result = evaluate_cells(book)
        self.assertEqual(book, before)
        self.assertEqual(list(result), list(book))
        self.assertEqual(result["S"]["A1"]["status"], "unsupported")
        for key, kind, expected in (("B1", "text", ".١ .²"), ("C1", "number", 7), ("D1", "number", 9)):
            row = result["S"][key]
            self.assertEqual((row["status"], row["value_origin"], row["value_type"], row["value"]),
                             ("computed", "evaluated", kind, expected))
            self.assertEqual(row["formula"], book["S"][key]["formula"])
            self.assertEqual(row["cached_value"], book["S"][key]["value"])
        literal = result["S"]["E1"]
        self.assertEqual((literal["status"], literal["value_origin"], literal["value_type"], literal["value"]),
                         ("literal", "input", "text", ".١ .²"))

    def test_regression_boundary_refusal_dependencies_no_cache_fallback(self):
        for formula, reason in (("A1:", "invalid_formula"), ("SUM(A1:", "invalid_formula"),
                                (".١", "operator_or_syntax_unsupported"), (".²", "operator_or_syntax_unsupported")):
            book = {"S": {"A1": cell(99, formula, "n"), "B1": cell(777, "1+1", "n"),
                           "C1": cell(888, "A1+1", "n"), "D1": cell(123, "COUNT(A1:A1)", "n"),
                           "E1": cell(456, "COUNTA(A1:A1)", "n"), "F1": cell(789, "SUM(A1:A1)", "n"),
                           "G1": cell(987, "B1*2", "n")}}
            before = copy.deepcopy(book)
            result = evaluate_cells(book)["S"]
            self.assertEqual(book, before)
            self.assertEqual(list(result), list(book["S"]))
            for key in ("A1", "C1", "D1", "E1", "F1"):
                row = result[key]
                self.assertEqual((row["status"], row["reason"], row["value_origin"]),
                                 ("unsupported", reason, "none"))
                self.assertIsNone(row["value"])
                self.assertEqual((row["cached_value"], row["cache_status"]),
                                 (book["S"][key]["value"], "available"))
            for key, expected in (("B1", 2), ("G1", 4)):
                self.assertEqual((result[key]["status"], result[key]["value_origin"], result[key]["value"]),
                                 ("computed", "evaluated", expected))


class _CaseResult(unittest.TestResult):
    """Тонкая сериализация фактических unittest outcomes для CASES_SCHEMA."""
    def __init__(self):
        super().__init__()
        self.rows = []

    def startTest(self, test):
        super().startTest(test)
        if "devtools_case_started" in globals():
            devtools_case_started(test._testMethodName)

    def _row(self, test, outcome, err=None):
        row = {"id": test._testMethodName, "outcome": outcome}
        if err is not None:
            row["exception_type"] = err[0].__name__
            # No linecache/foreign files при formatter failure под audit fence.
            frames, tb = [], err[2]
            while tb is not None:
                frames.append({"file": tb.tb_frame.f_code.co_filename,
                               "line": tb.tb_lineno, "function": tb.tb_frame.f_code.co_name})
                tb = tb.tb_next
            row["frames"] = frames[-8:]
            row["detail"] = str(err[1])[:1200]
        self.rows.append(row)

    def addSuccess(self, test):
        self._row(test, "passed")

    def addFailure(self, test, err):
        self._row(test, "failed", err)
        # Не вызывать stock traceback formatter с implicit source reads.
        self.failures.append((test, "recorded in cases JSON"))

    def addError(self, test, err):
        self._row(test, "error", err)
        self.errors.append((test, "recorded in cases JSON"))

    def addSkip(self, test, reason):
        self._row(test, "skipped")
        self.skipped.append((test, reason))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BoundedFormulas)
    actual = _CaseResult()
    suite.run(actual)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": actual.rows,
                      "total": actual.testsRun, "passed": sum(r["outcome"] == "passed" for r in actual.rows),
                      "failed": len(actual.failures), "errors": len(actual.errors), "skipped": len(actual.skipped),
                      "verification_class": "whole-module SOURCE / synthetic in-memory workbook; not parser integration"},
                     ensure_ascii=True, separators=(",", ":")))
    raise SystemExit(0 if actual.wasSuccessful() else 1)
