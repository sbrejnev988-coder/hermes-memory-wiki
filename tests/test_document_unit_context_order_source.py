"""Finite N2 SOURCE row-projection regression, not a public/SQLite test.

Ordinary import is inert: no product reads, imports, exec or fixtures. The explicit
five-case suite requires the original source_bootstrap bound-reader envelope and
its separate finite admission. It reuses the full frozen XLSX peer for its loader,
OOXML fixture and unittest lifecycle, but selects NONE of its old test bodies.
Historical whole-source witnesses are external, uniquely named, hash-bound inputs;
this entry does not reconstruct or import a fake provider/SQL/SDK authority.
Pytest markers are intentional; actual ordinary pytest nonselection is NOT_RUN.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

__test__ = False

CASE_IDS = (
    "test_order_ordinary_compatibility_matrix",
    "test_order_unfixed_boundary_witness",
    "test_order_typed_xlsx_literal_identity",
    "test_order_generic_and_refusal_controls",
    "test_order_STATIC_outside_loop_and_terminal_fences",
)


# Frozen document346 inverse, metadata only. Original bodies are literal Git
# witnesses from 028fe5f; they are never compiled, imported or executed here.
# Full current owner hashes bind helper/SELECT/predicates/output as intended;
# arbitrary edits inside those owners cannot disappear behind an AST projection.
REVISION_ORIGINAL_028 = {'document_unit_context': ('0c55fe0fd37e1fc8cb26684730a2189a9e56ddc1c7f2b2cd15d4348c58ea05cd',
                           'def document_unit_context(provider: Any, args: Dict[str, Any]) -> '
                           'Dict[str, Any]:\n'
                           '    source_id = str(args.get("source_id") or "").strip()\n'
                           '    unit_id = str(args.get("unit_id") or "").strip()\n'
                           '    anchor = str(args.get("anchor") or "").strip()\n'
                           '    radius = max(0, min(int(args.get("radius") or 5), 100))\n'
                           '    if not source_id: raise ValueError("source_id is required")\n'
                           '    conn = provider._connect(); install_document_graph_schema(conn)\n'
                           '    disclosure = _document_disclosure(provider, conn)\n'
                           '    source = conn.execute("SELECT '
                           'scope_id,repository_id,parser,extension,metadata_json FROM '
                           'document_sources WHERE source_id=? AND active=1", '
                           '(source_id,)).fetchone()\n'
                           '    if not source: raise ValueError("document source not found")\n'
                           '    disclosure.documents(disclosure.watch("document_sources", '
                           '"source_id", [source_id]))\n'
                           '    _assert_source_access(provider, source)\n'
                           '    _assert_connector_owner(provider, source_id)\n'
                           '    xlsx_context = _stored_xlsx_context(source)\n'
                           '    if unit_id:\n'
                           '        target = conn.execute("SELECT ordinal FROM document_units '
                           'WHERE source_id=? AND unit_id=? AND active=1", (source_id, '
                           'unit_id)).fetchone()\n'
                           '    elif anchor:\n'
                           '        target = conn.execute("SELECT ordinal FROM document_units '
                           'WHERE source_id=? AND anchor=? AND active=1", (source_id, '
                           'anchor)).fetchone()\n'
                           '    else:\n'
                           '        raise ValueError("unit_id or anchor is required")\n'
                           '    if not target: raise ValueError("document unit not found")\n'
                           '    ordinal = int(target[0]); rows = conn.execute(\n'
                           '        "SELECT '
                           'unit_id,parent_unit_id,unit_type,anchor,ordinal,title,unit_text,locator_json,metadata_json '
                           'FROM document_units "\n'
                           '        "WHERE source_id=? AND active=1 AND ordinal BETWEEN ? AND ? '
                           'ORDER BY ordinal",\n'
                           '        (source_id, max(0, ordinal-radius), ordinal+radius),\n'
                           '    ).fetchall()\n'
                           '    units = []\n'
                           '    disclosure.documents(disclosure.watch("document_units", "unit_id", '
                           "[r['unit_id'] for r in rows]))\n"
                           '    for raw in rows:\n'
                           '        item = _row(raw)\n'
                           '        item["unit_text"] = _clean(item.get("unit_text"), 20_000)\n'
                           '        item = _hydrate_document_unit(item, xlsx_context)\n'
                           '        units.append(item)\n'
                           '    out = {"source_id": source_id, "target_ordinal": ordinal, "units": '
                           'units}\n'
                           '    if source["parser"] == "stdlib-xlsx-ooxml" and xlsx_context is '
                           'None:\n'
                           '        out["xlsx_identity_state"] = "legacy_or_withheld"\n'
                           '    return _disclosed_document_output(provider, out, disclosure)\n'),
 'document_neighbors': ('671857cb4e35941c11bd91e4f4ae3f9c1bb24bc6aba1d90483202d5448526d88',
                        'def document_neighbors(provider: Any, args: Dict[str, Any]) -> Dict[str, '
                        'Any]:\n'
                        '    source_id = str(args.get("source_id") or "").strip(); anchor = '
                        'str(args.get("anchor") or "").strip()\n'
                        '    hops = max(1, min(int(args.get("hops") or 1), 3)); limit = max(1, '
                        'min(int(args.get("limit") or 100), 1000))\n'
                        '    if not source_id or not anchor: raise ValueError("source_id and '
                        'anchor are required")\n'
                        '    conn = provider._connect(); install_document_graph_schema(conn)\n'
                        '    disclosure = _document_disclosure(provider, conn)\n'
                        '    source = conn.execute("SELECT scope_id,repository_id FROM '
                        'document_sources WHERE source_id=? AND active=1", '
                        '(source_id,)).fetchone()\n'
                        '    if not source: raise ValueError("document source not found")\n'
                        '    disclosure.documents(disclosure.watch("document_sources", '
                        '"source_id", [source_id]))\n'
                        '    _assert_source_access(provider, source)\n'
                        '    _assert_connector_owner(provider, source_id)\n'
                        '    queue = deque([(anchor, 0)]); seen = {anchor}; found = []\n'
                        '    while queue and len(found) < limit:\n'
                        '        node, depth = queue.popleft()\n'
                        '        if depth >= hops: continue\n'
                        '        rows = conn.execute(\n'
                        '            "SELECT '
                        'edge_id,source_anchor,predicate,target_anchor,evidence,confidence FROM '
                        'document_edges WHERE source_id=? AND active=1 AND (source_anchor=? OR '
                        'target_anchor=?) LIMIT ?",\n'
                        '            (source_id, node, node, limit-len(found)),\n'
                        '        ).fetchall()\n'
                        '        for raw in rows:\n'
                        '            edge = _row(raw); found.append(edge)\n'
                        '            other = edge["target_anchor"] if edge["source_anchor"] == '
                        'node else edge["source_anchor"]\n'
                        '            if other not in seen: seen.add(other); queue.append((other, '
                        'depth+1))\n'
                        '    disclosure.watch("document_edges", "edge_id", [r[\'edge_id\'] for r '
                        'in found])\n'
                        '    return _disclosed_document_output(provider, {\n'
                        '        "source_id": source_id, "anchor": anchor, "hops": hops,\n'
                        '        "edges": found[:limit], "nodes": sorted(seen),\n'
                        '    }, disclosure)\n')}
REVISION_HELPER_SHA256 = '13661192ae369c4ccaf2673380b4674d8fee6045e527fc756dfb48fcdcff2770'


def document_revision_inverse(raw):
    if (type(raw) is not bytes or hashlib.sha256(raw).hexdigest() !=
            'b7aaa8cbcfdcc44bbd8d0061214f5fa81324753ad01d6083222c41392e59003c'):
        raise ValueError('exact_document346_graph_required')
    tree = ast.parse(raw)
    lines = raw.splitlines(keepends=True)
    edits = []
    for name in ('_document_lookup_revision', *REVISION_ORIGINAL_028):
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(nodes) != 1:
            raise ValueError('unique_revision_inverse_owner')
        node = nodes[0]
        span = b''.join(lines[node.lineno - 1:node.end_lineno])
        if name == '_document_lookup_revision':
            expected, replacement = REVISION_HELPER_SHA256, b''
            end = node.end_lineno + 2
            if lines[node.end_lineno:end] != [b'\n', b'\n']:
                raise ValueError('revision_helper_boundary')
        else:
            expected, original = REVISION_ORIGINAL_028[name]
            replacement, end = original.encode('utf-8'), node.end_lineno
        if hashlib.sha256(span).hexdigest() != expected:
            raise ValueError('revision_inverse_owner_bytes')
        edits.append((node.lineno - 1, end, replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    inverse = b''.join(lines)
    if hashlib.sha256(inverse).hexdigest() != '8835f2df870a6aee67a99634d7c5b4681e30bf91174fa0bffbe95fe3918fa8ee':
        raise ValueError('revision_inverse_whole_graph')
    return inverse


def row_loop(raw, filename):
    """Select the exact direct row loop, never execute the public SQL wrapper."""
    tree = ast.parse(raw, filename=filename)
    owners = [n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "document_unit_context"]
    if len(owners) != 1:
        raise RuntimeError("unique_real_context_owner_required")
    loops = [n for n in owners[0].body if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == "raw"
             and isinstance(n.iter, ast.Name) and n.iter.id == "rows"]
    if len(loops) != 1:
        raise RuntimeError("unique_real_context_row_loop_required")
    return tree, owners[0], loops[0]


class OrderSourceCases:
    __test__ = False

    @classmethod
    def setUpClass(cls):
        # This is the original class setup, loader and SOURCE helper-SHA contract.
        super().setUpClass()
        cls.observations = {}
        cls.source_raw, cls.source_trees, cls.projections = {}, {}, {}
        cls.source_modules = {"corrected": cls.g}
        reader = globals()["devtools_read_bound"]
        for role, key, name in (
            ("d93", "d93_document_knowledge_graph.py", "order_d93_kg"),
            ("3dc", "3dc_document_knowledge_graph.py", "order_3dc_kg"),
        ):
            if name in sys.modules:
                raise RuntimeError("fresh_historical_namespace_required")
            # Cleanup is registered before a possibly failing source load.
            cls.addClassCleanup(lambda name=name: sys.modules.pop(name, None))
            cls.source_modules[role] = cls.peer.load_source(Path(cls.inputs[key]), name)
        for role, key in (("corrected", "document_knowledge_graph.py"),
                          ("d93", "d93_document_knowledge_graph.py"),
                          ("3dc", "3dc_document_knowledge_graph.py")):
            path = cls.inputs[key]
            raw = reader(str(path))
            tree, owner, loop = row_loop(raw, str(path))
            cls.source_raw[role] = raw
            cls.source_trees[role] = (tree, owner, loop)
            # Exact AST node and original locations, with the real version's globals.
            cls.projections[role] = compile(ast.Module(body=[copy.deepcopy(loop)], type_ignores=[]),
                                            str(path), "exec", dont_inherit=True)
        cls.runtime_bindings = {"row_loop_modules": [], "shared_modules": []}
        for role, module in cls.source_modules.items():
            path = cls.projections[role].co_filename
            if (module.__file__ != path or module._clean.__code__.co_filename != path
                    or module._sanitize_extracted_json is not cls.e.sanitize_json
                    or module._sanitize_untrusted_text is not sys.modules["guard"].sanitize_context_text):
                raise RuntimeError("actual_standalone_helper_origin_mismatch")
            cls.runtime_bindings["row_loop_modules"].append({
                "role": role, "path": path, "sha256": hashlib.sha256(cls.source_raw[role]).hexdigest(),
                "real_helper_identity": True, "exact_loop_code_filename": True})
        for name in ("xlsx_identity_original_loader", "document_extractors", "spreadsheet_formulas", "guard"):
            cls.runtime_bindings["shared_modules"].append({"name": name, "path": sys.modules[name].__file__})
        if cls.e.evaluate_cells is not sys.modules["spreadsheet_formulas"].evaluate_cells:
            raise RuntimeError("actual_formula_helper_identity_mismatch")

    def setUp(self):
        super().setUp()
        self.observations[self._testMethodName] = {"per_case_cleanup": False}
        self.addCleanup(self.observations[self._testMethodName].__setitem__, "per_case_cleanup", True)

    def project(self, role, rows, context=None):
        """SOURCE seam: exact loop + actual standalone helpers; no fake SQL."""
        before = copy.deepcopy(rows)
        namespace = dict(self.source_modules[role].__dict__)
        namespace.update(rows=rows, units=[], xlsx_context=context)
        exec(self.projections[role], namespace)
        self.assertEqual(rows, before, "row projection must not mutate input")
        return namespace["units"]

    def ordinary_row(self, text):
        return {"unit_id": "authored-unit", "parent_unit_id": None,
                "unit_type": "paragraph", "anchor": "paragraph:1", "ordinal": 1,
                "title": "Ordinary title  ", "unit_text": text,
                "locator_json": json.dumps({"line": 1, "label": "literal  "}),
                "metadata_json": json.dumps({"note": "line  \nsecond  ", "nested": ["value  "]})}

    def stored_row(self, unit, context, text="Plain body  "):
        return {"unit_id": "authored-" + str(unit["ordinal"]), "parent_unit_id": None,
                "unit_type": unit["kind"], "anchor": unit["anchor"], "ordinal": unit["ordinal"],
                "title": unit["title"], "unit_text": text,
                "locator_json": self.g._safe_json(unit["locator"], xlsx_shape="locator",
                                                   xlsx_context=context, xlsx_unit=unit),
                "metadata_json": self.g._safe_json(unit["metadata"])}

    def test_order_ordinary_compatibility_matrix(self):
        samples = (
            ("short", "  Ordinary prose.  ", None),
            ("empty", "", None),
            ("null", None, None),
            ("short_lines", "Alpha  \nBeta \t\n\n\n\nGamma \r\nDelta  ", None),
            ("exact_cap", "A" * 20000, None),
            ("over_cap", "A" * 20001, None),
            ("long_tabs", "B" + "\t" * 20000 + "Z", None),
            ("long_spaces_lines", "Line  \r\n" * 3000 + "End", None),
            ("long_newlines", "A\n" * 12000 + "Z", None),
            ("short_nul", "Alpha\x00Beta  ", None),
            ("long_nul", "a\x00" * 20001 + "End", None),
            ("labelled_secret", "password=AuthoredCanary9988  \nBody", "AuthoredCanary9988"),
            ("secret_boundary", "A" * 19980 + "\npassword=AuthoredCanary9988", "AuthoredCanary9988"),
            ("quoted_secret", "Password: 'AuthoredCanary9988' \nBody", "AuthoredCanary9988"),
            ("url_secret", "https://authored:AuthoredCanary9988@example.invalid/path  ", "AuthoredCanary9988"),
            ("provider_shape", "sk-" + "X" * 24 + " \nBody", "X" * 24),
        )
        seen = []
        for label, text, canary in samples:
            rows = [self.ordinary_row(text)]
            expected = self.project("d93", rows)
            actual = self.project("corrected", rows)
            old = self.project("3dc", rows)
            self.assertEqual(actual, expected, label)
            value = actual[0]["unit_text"]
            self.assertLessEqual(len(value), 20000, label)
            self.assertNotIn("\x00", value, label)
            self.assertNotIn("locator_json", actual[0])
            self.assertNotIn("metadata_json", actual[0])
            self.assertEqual(actual[0]["locator"], {"line": 1, "label": "literal"})
            if canary:
                self.assertNotIn(canary, json.dumps(actual), label)
            if label == "short":
                self.assertEqual(value, "  Ordinary prose.")
            if label in ("exact_cap", "over_cap"):
                self.assertEqual(value, "A" * 20000)
            seen.append({"id": label, "corrected_chars": len(value), "d93_equal": True,
                         "old3dc_equal": old == actual})
        self.observations[self._testMethodName]["variants"] = seen

    def test_order_unfixed_boundary_witness(self):
        text = "A" + " " * 20000 + "Z"
        boundary = "A" + " " * 19999
        redacted, findings = self.e.redact_secret_text(text, 20000)
        self.assertEqual(findings, [])
        self.assertEqual(redacted, boundary)
        self.assertEqual(self.e.sanitize_json(text), boundary)
        rows = [self.ordinary_row(text)]
        d93 = self.project("d93", rows)
        old = self.project("3dc", rows)
        corrected = self.project("corrected", rows)
        self.assertEqual(d93[0]["unit_text"], "A")
        self.assertEqual(corrected, d93)
        self.assertEqual(old[0]["unit_text"], boundary)
        self.assertNotEqual(old, corrected)
        self.observations[self._testMethodName].update(
            input_chars=len(text), d93_chars=len(d93[0]["unit_text"]),
            old3dc_chars=len(old[0]["unit_text"]), corrected_chars=len(corrected[0]["unit_text"]),
            secret_findings=0, classification="expected_old_order_difference_in_SOURCE_projection_only",
            production_incident=False, public_SQL_or_ACL_bypass_claim=False)

    def test_order_typed_xlsx_literal_identity(self):
        payload, context = self.g._document_extraction_payload(self.workbook())
        self.assertIsNotNone(context)
        stored_source = {"parser": payload["parser"], "extension": payload["extension"],
                         "metadata_json": self.g._safe_json(payload["metadata"], xlsx_shape="metadata",
                                                            xlsx_context=context)}
        context = self.g._stored_xlsx_context(stored_source)
        self.assertIsNotNone(context)
        self.assertEqual(list(context.sheets), self.names)
        rows = [self.stored_row(unit, context) for unit in payload["units"]]
        actual = self.project("corrected", rows, context)
        self.assertEqual(actual, self.project("3dc", rows, context))
        for unit, hydrated in zip(payload["units"], actual):
            self.assertEqual(hydrated["anchor"], unit["anchor"])
            self.assertEqual(hydrated["locator"], unit["locator"])
            self.assertEqual(hydrated["metadata"], unit["metadata"])
            self.assertEqual(hydrated["unit_text"], "Plain body")
            if unit["kind"] == "sheet":
                self.assertEqual(hydrated["title"], unit["title"])
        sheets = [u for u in actual if u["unit_type"] == "sheet"]
        self.assertEqual([u["title"] for u in sheets], self.names)
        self.assertEqual(len({u["locator"]["sheet"] for u in sheets}), len(self.names))
        self.assertNotEqual(sheets[0]["locator"], sheets[1]["locator"])
        generic = self.project("d93", rows)
        spaced_index = next(i for i, u in enumerate(payload["units"])
                            if u["kind"] == "sheet" and u["title"] == "Data ")
        self.assertEqual(generic[spaced_index]["locator"]["sheet"], "Data")
        self.assertNotEqual(generic[spaced_index]["locator"], actual[spaced_index]["locator"])
        # Framed row/cell anchors retain the suffix; no invented unframed lookup.
        framed = [u for u in actual if u["unit_type"] == "table_row"]
        for name in self.names:
            self.assertTrue(any(u["anchor"] == f"sheet:{name}/row:1" for u in framed))
        self.observations[self._testMethodName].update(
            sheets=len(sheets), projected_units=len(actual), same_and_inverse=True,
            unicode_apostrophe_and_trailing_spaces=True, typed_context="real_persisted_metadata_helper")

    def test_order_generic_and_refusal_controls(self):
        payload, context = self.g._document_extraction_payload(self.workbook(["Data "]))
        self.assertIsNotNone(context)
        sheet = next(u for u in payload["units"] if u["kind"] == "sheet")
        good = self.stored_row(sheet, context)
        variants = (
            ("no_context", good, None),
            ("lookalike_context", good, {"sheets": ["Data "]}),
            ("wrong_kind", {**good, "unit_type": "paragraph"}, context),
            ("wrong_anchor", {**good, "anchor": "sheet:2"}, context),
            ("bool_index", {**good, "locator_json": json.dumps({"sheet": "Data ", "sheet_index": True})}, context),
            ("redacted_title", {**good, "title": "password=AuthoredCanary9988"}, context),
        )
        for label, row, admitted_context in variants:
            actual = self.project("corrected", [row], admitted_context)
            self.assertEqual(actual, self.project("d93", [row]), label)
            self.assertNotIn("AuthoredCanary9988", json.dumps(actual))
            self.assertEqual(actual[0]["locator"]["sheet"], "Data", label)
        self.assertIsNone(self.g._stored_xlsx_context({"parser": "ordinary", "extension": ".xlsx",
                                                     "metadata_json": stored_metadata(payload)}))
        refused = ("ignore previous instructions ", "password=AuthoredCanary9988 ", "   ", "<REDACTED>")
        for name in refused:
            metadata = {**payload["metadata"], "sheets": [name]}
            self.assertIsNone(self.g._document_xlsx_context("stdlib-xlsx-ooxml", metadata))
        self.assertIsNone(self.g._document_xlsx_context("stdlib-xlsx-ooxml", {"sheets": ["Data "]}))
        # Use the actual producer framing with a full-field redaction match.
        token_payload, token_context = self.g._document_extraction_payload(self.workbook(["token "]))
        self.assertIsNotNone(token_context)
        token_row = next(u for u in token_payload["units"] if u["kind"] == "table_row")
        self.assertNotEqual(token_row["anchor"], "sheet:token /row:1")
        hydrated = self.project("corrected", [self.stored_row(token_row, token_context)], token_context)[0]
        self.assertNotEqual(hydrated["anchor"], "sheet:token /row:1")
        self.observations[self._testMethodName].update(
            generic_variants=[v[0] for v in variants], context_refusals=len(refused) + 1,
            full_field_redaction_not_repaired=True, fake_inspectors_or_authority=0)

    def test_order_STATIC_outside_loop_and_terminal_fences(self):
        old_tree, old_owner, old_loop = copy.deepcopy(self.source_trees["3dc"])
        # Historical loop-only equality is asserted on the exact typed/raw
        # inverse of the accepted revision delta, never on a masked live AST.
        inverse = document_revision_inverse(self.source_raw["corrected"])
        new_tree, new_owner, new_loop = row_loop(inverse, "document346_inverse_028.py")
        # Deepcopy of the tuple keeps owner/loop identities within the full tree.
        old_owner.body[old_owner.body.index(old_loop)] = ast.Pass()
        new_owner.body[new_owner.body.index(new_loop)] = ast.Pass()
        self.assertEqual(ast.dump(old_tree, include_attributes=False),
                         ast.dump(new_tree, include_attributes=False))
        old_lines = self.source_raw["3dc"].splitlines(keepends=True)
        new_lines = inverse.splitlines(keepends=True)
        self.assertEqual(old_lines[:old_loop.lineno - 1], new_lines[:new_loop.lineno - 1])
        self.assertEqual(old_lines[old_loop.end_lineno:], new_lines[new_loop.end_lineno:])
        # The current, non-inverted owner still owns the loop and every fence.
        current_tree, current_owner, current_loop = self.source_trees["corrected"]
        self.assertEqual(ast.dump(current_loop, include_attributes=False),
                         ast.dump(new_loop, include_attributes=False))
        new_tree, new_owner, new_loop = current_tree, current_owner, current_loop
        expected = ast.parse('for raw in rows:\n'
                             '    item = _row(raw)\n'
                             '    item["unit_text"] = _clean(item.get("unit_text"), 20_000)\n'
                             '    item = _hydrate_document_unit(item, xlsx_context)\n'
                             '    units.append(item)\n').body[0]
        self.assertEqual(ast.dump(new_loop, include_attributes=False),
                         ast.dump(expected, include_attributes=False))
        calls = {name: [n.lineno for n in ast.walk(new_owner) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name) and n.func.id == name]
                 for name in ("_document_disclosure", "_assert_source_access", "_assert_connector_owner",
                              "_stored_xlsx_context", "_disclosed_document_output")}
        for name, locations in calls.items():
            self.assertEqual(len(locations), 1, name)
        self.assertLess(calls["_document_disclosure"][0], calls["_assert_source_access"][0])
        self.assertLess(calls["_assert_source_access"][0], calls["_assert_connector_owner"][0])
        self.assertLess(calls["_assert_connector_owner"][0], calls["_stored_xlsx_context"][0])
        revisions = [n.lineno for n in ast.walk(new_owner) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "_document_lookup_revision"]
        self.assertEqual(len(revisions), 1)
        self.assertLess(calls["_assert_connector_owner"][0], revisions[0])
        self.assertLess(revisions[0], calls["_stored_xlsx_context"][0])
        self.assertLess(calls["_stored_xlsx_context"][0], new_loop.lineno)
        self.assertGreater(calls["_disclosed_document_output"][0], new_loop.end_lineno)
        watches = [n for n in ast.walk(new_owner) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "watch"]
        self.assertEqual([n.args[0].value for n in sorted(watches, key=lambda n: n.lineno)],
                         ["document_sources", "document_units"])
        self.assertTrue(all(n.lineno < new_loop.lineno for n in watches))
        terminal = next(n for n in new_tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "_disclosed_document_output")
        guard = [n.lineno for n in ast.walk(terminal) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_guard_document_output"]
        finish = [n.lineno for n in ast.walk(terminal) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "finish"]
        self.assertEqual((len(guard), len(finish)), (1, 1))
        self.assertLess(guard[0], finish[0])
        self.observations[self._testMethodName].update(
            revision_inverse_outside_exact_loop_equal=True, inverse_byte_prefix_suffix_equal=True,
            current_loop_and_terminal_fences_preserved=True,
            scope="STATIC_document346_intended_delta_only_no_guard_or_terminal_SQL_execution")


def stored_metadata(payload):
    return json.dumps(payload["metadata"])


def main():
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        raise RuntimeError("original_isolated_source_bootstrap_required")
    required_globals = ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound", "devtools_case_started")
    if any(key not in globals() for key in required_globals):
        raise RuntimeError("finite_source_admission_and_original_bound_reader_required")
    inputs = globals()["DEVTOOLS_INPUTS"]
    carrier_name = "caller04_order_frozen_xlsx_peer"
    if carrier_name in sys.modules:
        raise RuntimeError("fresh_frozen_peer_namespace_required")
    path = inputs["test_document_xlsx_identity_source.py"]
    spec = importlib.util.spec_from_file_location(carrier_name, path)
    carrier = importlib.util.module_from_spec(spec)
    for key in ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound"):
        carrier.__dict__[key] = globals()[key]
    opt_in = "MEMORY_WIKI_XLSX_IDENTITY_SOURCE_OPT_IN"
    previous = os.environ.get(opt_in)
    result = None
    try:
        sys.modules[carrier_name] = carrier
        exec(compile(devtools_read_bound(path), path, "exec", dont_inherit=True), carrier.__dict__)
        # Full original peer, no inherited old8 or SQL method is selected or called.
        class OrderSourceTests(OrderSourceCases, carrier.XlsxIdentitySourceTests):
            __test__ = False

        peer_path = inputs["test_document_parser_pdf_ocr.py"]
        peer_tree = ast.parse(devtools_read_bound(peer_path), filename=peer_path)
        reporters = [n for n in ast.walk(peer_tree) if isinstance(n, ast.ClassDef) and n.name == "PacketResult"]
        if len(reporters) != 1:
            raise RuntimeError("unique_original_PacketResult_required")
        namespace = {"__name__": "caller04_order_reporter", "unittest": unittest,
                     "devtools_case_started": devtools_case_started}
        exec(compile(ast.Module(body=reporters, type_ignores=[]), peer_path, "exec", dont_inherit=True), namespace)
        result = namespace["PacketResult"]()
        os.environ[opt_in] = "1"
        unittest.TestSuite(OrderSourceTests(name) for name in CASE_IDS).run(result)
    finally:
        sys.modules.pop(carrier_name, None)
        if previous is None:
            os.environ.pop(opt_in, None)
        else:
            os.environ[opt_in] = previous
    clean_names = (carrier_name, "xlsx_identity_original_loader", "spreadsheet_formulas",
                   "document_extractors", "guard", "document_knowledge_graph", "order_d93_kg", "order_3dc_kg")
    modules_released = all(name not in sys.modules for name in clean_names)
    observations = OrderSourceTests.observations
    case_cleanups = sum(value["per_case_cleanup"] is True for value in observations.values())
    cleanup_complete = modules_released and case_cleanups == len(CASE_IDS)
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": result.rows,
        "observations": observations, "runtime_bindings": OrderSourceTests.runtime_bindings,
        "lifecycle": {"module_cleanup_complete": modules_released, "per_case_cleanups": case_cleanups,
                      "opt_in_restored": os.environ.get(opt_in) == previous},
        "qualification": "4 exact-real-loop SOURCE mains plus1 STATIC preservation main; old3dc expected difference is not a production incident; public/SQL/SDK/native/FULL NOT_RUN"},
        separators=(",", ":")))
    return 0 if result.wasSuccessful() and cleanup_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
