"""IQ25: pure SOURCE input/quote budgets and explicitly separate STATIC checks.

Import/collection is inert. An admitted existing parent SOURCE runner supplies
DEVTOOLS_INPUTS, DEVTOOLS_SCRATCH and devtools_read_bound before build_suite.
Only exact original definitions execute; no product module/bootstrap, provider,
SDK, SQL, transport, credentials, grounding authority or model is substituted.
The baseline is an immutable, separately bound source witness. Passing these
controls does not execute public persistence, the owning caller, or an LLM.
"""
from __future__ import annotations

import ast
import copy
import datetime as _dt
import math
import re
import unittest

__test__ = False

CASE_IDS = (
    "IQ25_SOURCE_baseline_and_new_admission",
    "IQ25_SOURCE_above_old_cap_intact",
    "IQ25_SOURCE_exact_25000_intact",
    "IQ25_SOURCE_unicode_counts_characters",
    "IQ25_SOURCE_plus_one_refuses_whole",
    "IQ25_SOURCE_raw_whitespace_counts",
    "IQ25_SOURCE_terminal_denial_not_cropped",
    "IQ25_SOURCE_legacy_pair_time_and_roles",
    "IQ25_SOURCE_transcript_exact_48000",
    "IQ25_SOURCE_transcript_plus_one",
    "IQ25_SOURCE_last32_whole_window",
    "IQ25_SOURCE_nonstring_and_tool_inputs",
    "IQ25_SOURCE_quote_shape_still_6000",
    "IQ25_SOURCE_response_schema_still_6000",
    "IQ25_STATIC_complete_product_delta",
    "IQ25_STATIC_public_normalizer_order",
    "IQ25_STATIC_collection_and_factory",
)

DEFINITIONS = (
    "ExtractionBoundaryError", "_coerce_event_at", "_message_event_at",
    "_normalize_exchanges", "_entry_shape_valid", "_response_schema",
)
CONSTANTS = frozenset({
    "_MAX_MESSAGES", "_MAX_MESSAGE_CHARS", "_MAX_EVIDENCE_QUOTE_CHARS",
    "_MAX_TRANSCRIPT_CHARS", "_MAX_ENTRIES", "_ENTRY_KEYS", "_VALID_TYPES",
})


def _require_bootstrap():
    if (type(globals().get("DEVTOOLS_INPUTS")) is not dict
            or type(globals().get("DEVTOOLS_SCRATCH")) is not str
            or not DEVTOOLS_SCRATCH or not callable(globals().get("devtools_read_bound"))):
        raise RuntimeError("IQ25_genuine_SOURCE_bootstrap_required")
    for name in ("extractor.py", "extractor_baseline.py", "test_extractor_input_budget_source.py"):
        if type(DEVTOOLS_INPUTS.get(name)) is not str or not DEVTOOLS_INPUTS[name]:
            raise RuntimeError("IQ25_bound_input_required")


def _definition(tree, name):
    found = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name]
    if len(found) != 1:
        raise RuntimeError("IQ25_unique_source_definition_required")
    return found[0]


def _assigned_names(node):
    targets = (node.targets if isinstance(node, ast.Assign) else
               [node.target] if isinstance(node, ast.AnnAssign) else [])
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _load_definitions(raw, path):
    if type(raw) is not bytes or len(raw) > 1_000_000:
        raise RuntimeError("IQ25_bound_source_bytes_required")
    tree = ast.parse(raw, filename=path)
    selected = [_definition(tree, name) for name in DEFINITIONS]
    if any(isinstance(node, (ast.Import, ast.ImportFrom))
           for definition in selected for node in ast.walk(definition)):
        raise RuntimeError("IQ25_unreviewed_import_dependency")
    constants = [node for node in tree.body if _assigned_names(node) & CONSTANTS]
    found = set().union(*(_assigned_names(node) & CONSTANTS for node in constants))
    if found not in (CONSTANTS, CONSTANTS - {"_MAX_EVIDENCE_QUOTE_CHARS"}):
        raise RuntimeError("IQ25_constant_closure_incomplete")
    future = [node for node in tree.body if isinstance(node, ast.ImportFrom)
              and node.module == "__future__"]
    namespace = {"__name__": "IQ25_exact_source_definitions", "__file__": path,
                 "math": math, "re": re, "_dt": _dt}
    exec(compile(ast.Module(body=[*future, *constants, *selected], type_ignores=[]),
                 path, "exec", dont_inherit=True), namespace)
    return namespace, tree


def _text(length, prefix="Ordinary context. ", tail="Complete ending."):
    if length < len(prefix) + len(tail):
        raise ValueError("IQ25_fixture_length_too_small")
    return prefix + "x" * (length - len(prefix) - len(tail)) + tail


def _structural(node):
    return ast.dump(node, include_attributes=False)


class ExtractorInputBudgetSourceTests(unittest.TestCase):
    __test__ = False

    @classmethod
    def setUpClass(cls):
        _require_bootstrap()
        cls.path = DEVTOOLS_INPUTS["extractor.py"]
        cls.baseline_path = DEVTOOLS_INPUTS["extractor_baseline.py"]
        cls.raw = devtools_read_bound(cls.path)
        cls.baseline_raw = devtools_read_bound(cls.baseline_path)
        cls.ns, cls.tree = _load_definitions(cls.raw, cls.path)
        cls.old, cls.old_tree = _load_definitions(cls.baseline_raw, cls.baseline_path)

    @classmethod
    def tearDownClass(cls):
        cls.ns = cls.old = cls.tree = cls.old_tree = None
        cls.raw = cls.baseline_raw = cls.path = cls.baseline_path = None

    def setUp(self):
        for ns, path in ((self.ns, self.path), (self.old, self.baseline_path)):
            for name in DEFINITIONS[1:]:
                self.assertIs(ns[name].__globals__, ns)
                self.assertEqual(ns[name].__code__.co_filename, path)

    def normalize(self, rows):
        return self.ns["_normalize_exchanges"](rows)

    def reject(self, rows, code):
        with self.assertRaises(self.ns["ExtractionBoundaryError"]) as caught:
            self.normalize(rows)
        self.assertEqual(caught.exception.args, (code,))

    def IQ25_SOURCE_baseline_and_new_admission(self):
        old = self.old["_normalize_exchanges"]
        self.assertEqual(self.old["_MAX_MESSAGE_CHARS"], 6000)
        self.assertEqual(self.ns["_MAX_MESSAGE_CHARS"], 25000)
        for length in (6000, 6001, 25000):
            with self.subTest(length=length):
                text = _text(length)
                rows = [{"role": "user", "content": text}]
                if length == 6000:
                    self.assertEqual(old(rows)[0]["content"], text)
                else:
                    with self.assertRaises(self.old["ExtractionBoundaryError"]) as caught:
                        old(rows)
                    self.assertEqual(caught.exception.args, ("source_message_budget_exceeded",))
                self.assertEqual(self.normalize(rows)[0]["content"], text)

    def IQ25_SOURCE_above_old_cap_intact(self):
        text = _text(6001, "Project Aster uses violet channel. ")
        self.assertEqual(self.normalize([{"role": "user", "content": text}]), [{
            "role": "user", "content": text, "message_index": 0,
            "event_at": 0, "event_timezone": "UTC",
        }])

    def IQ25_SOURCE_exact_25000_intact(self):
        text = _text(25000, "Remember: Project Aster uses violet channel. ")
        result = self.normalize([{"role": "user", "content": text}])
        self.assertEqual(len(text), 25000)
        self.assertEqual(result[0]["content"], text)
        self.assertEqual(len(result[0]["content"]), 25000)
        self.assertNotIn("_source_chars", result[0])

    def IQ25_SOURCE_unicode_counts_characters(self):
        text = "Я🙂e\u0301" * 6250
        self.assertEqual(len(text), 25000)
        self.assertGreater(len(text.encode("utf-8")), 25000)
        self.assertEqual(self.normalize([{"role": "assistant", "content": text}])[0]["content"], text)
        self.reject([{"role": "assistant", "content": text + "я"}], "source_message_budget_exceeded")

    def IQ25_SOURCE_plus_one_refuses_whole(self):
        self.reject([{"role": "user", "content": _text(25001)},
                     {"role": "user", "content": "Remember: Project Aster uses violet channel."}],
                    "source_message_budget_exceeded")

    def IQ25_SOURCE_raw_whitespace_counts(self):
        text = "Project Aster uses violet channel."
        raw = text + " " * (25000 - len(text))
        self.assertEqual(self.normalize([{"role": "user", "content": raw}])[0]["content"], text)
        self.reject([{"role": "user", "content": raw + " "}], "source_message_budget_exceeded")
        self.reject([{"role": "user", "content": " " + raw}], "source_message_budget_exceeded")

    def IQ25_SOURCE_terminal_denial_not_cropped(self):
        tail = ", but Project Aster does not use Qdrant."
        exact = _text(25000, "Project Aster uses violet channel. ", tail)
        self.assertEqual(self.normalize([{"role": "user", "content": exact}])[0]["content"], exact)
        self.assertTrue(exact.endswith(tail))
        self.reject([{"role": "user", "content": exact + "."}], "source_message_budget_exceeded")
        # This observes source fidelity, not semantic grounding/model acceptance.

    def IQ25_SOURCE_legacy_pair_time_and_roles(self):
        user, assistant = _text(25000), _text(23000)
        result = self.normalize([{
            "user": user, "assistant": assistant, "user_event_at": 1779292800,
            "assistant_timestamp": 1779292801, "user_event_timezone": "Europe/Moscow",
        }])
        self.assertEqual([row["content"] for row in result], [user, assistant])
        self.assertEqual([(row["role"], row["message_index"], row["event_at"]) for row in result],
                         [("user", 0, 1779292800), ("assistant", 1, 1779292801)])
        self.assertEqual(result[0]["event_timezone"], "Europe/Moscow")

    def IQ25_SOURCE_transcript_exact_48000(self):
        texts = [_text(25000), _text(23000)]
        self.assertEqual(sum(map(len, texts)), 48000)
        self.assertEqual([row["content"] for row in self.normalize([
            {"role": "user", "content": text} for text in texts])], texts)
        self.assertEqual(self.ns["_MAX_TRANSCRIPT_CHARS"], 48000)

    def IQ25_SOURCE_transcript_plus_one(self):
        for texts in ((_text(25000), _text(23001)),
                      (_text(24999) + " ", _text(22999) + "  ")):
            with self.subTest(lengths=tuple(map(len, texts))):
                self.assertEqual(sum(map(len, texts)), 48001)
                self.assertTrue(all(len(text) <= 25000 for text in texts))
                self.reject([{"role": "user", "content": text} for text in texts],
                            "source_transcript_budget_exceeded")

    def IQ25_SOURCE_last32_whole_window(self):
        tail = [{"role": "assistant", "content": _text(64)} for _ in range(32)]
        self.assertEqual(self.ns["_MAX_MESSAGES"], 32)
        result = self.normalize([{"role": "user", "content": _text(25001)}, *tail])
        self.assertEqual(len(result), 32)
        self.assertEqual([row["message_index"] for row in result], list(range(1, 33)))
        self.assertEqual([row["content"] for row in result], [row["content"] for row in tail])
        self.reject([*tail, {"role": "user", "content": _text(25001)}],
                    "source_message_budget_exceeded")

    def IQ25_SOURCE_nonstring_and_tool_inputs(self):
        touched = []

        class Foreign:
            def __str__(self):
                touched.append("str")
                raise AssertionError("IQ25_foreign_content_coercion")

        rows = [{"role": "user", "content": raw} for raw in ({"text": "not plain text"}, [], Foreign())]
        rows += [{"role": role, "content": _text(25001)} for role in ("tool", "system")]
        rows += [{"role": "user", "content": ""}, {"role": "assistant", "content": "   "}]
        self.assertEqual(self.normalize(rows), [])
        self.assertEqual(touched, [])

    def IQ25_SOURCE_quote_shape_still_6000(self):
        entry = {"claim": "Project Aster uses violet channel.", "type": "fact", "topic": "Aster",
                 "evidence_quote": "q" * 6000, "speaker": "user", "message_index": 0,
                 "event_at": "", "confidence": 0.8}
        self.assertTrue(self.ns["_entry_shape_valid"](entry))
        self.assertTrue(self.old["_entry_shape_valid"](entry))
        entry["evidence_quote"] += "q"
        self.assertFalse(self.ns["_entry_shape_valid"](entry))
        self.assertFalse(self.old["_entry_shape_valid"](entry))
        self.assertEqual(self.ns["_MAX_EVIDENCE_QUOTE_CHARS"], 6000)
        # A valid shape is not an asserted/grounded fact or persistence authority.

    def IQ25_SOURCE_response_schema_still_6000(self):
        current = self.ns["_response_schema"]()
        self.assertEqual(current, self.old["_response_schema"]())
        claims = current["schema"]["properties"]["claims"]
        self.assertEqual(claims["maxItems"], 20)
        self.assertEqual(claims["items"]["properties"]["evidence_quote"]["maxLength"], 6000)

    def IQ25_STATIC_complete_product_delta(self):
        current = {node.name: node for node in self.tree.body
                   if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        baseline = {node.name: node for node in self.old_tree.body
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual(set(current), set(baseline))
        aliased = {"_entry_shape_valid", "_normalize_llm_entry", "_response_schema"}

        class QuoteAlias(ast.NodeTransformer):
            def visit_Name(self, node):
                if node.id == "_MAX_MESSAGE_CHARS":
                    node.id = "_MAX_EVIDENCE_QUOTE_CHARS"
                return node

        for name in current:
            with self.subTest(owner=name):
                expected = copy.deepcopy(baseline[name])
                if name in aliased:
                    expected = QuoteAlias().visit(expected)
                elif name == "_heuristic_extract":
                    candidates = [node for node in ast.walk(expected)
                                  if isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp)
                                  and "_claim_supported(raw_claim, evidence_quote)" in ast.unparse(node.test)]
                    self.assertEqual(len(candidates), 1)
                    candidates[0].test.values.insert(1, ast.parse(
                        "len(evidence_quote) > _MAX_EVIDENCE_QUOTE_CHARS", mode="eval").body)
                self.assertEqual(_structural(current[name]), _structural(expected))
        # Framing, owner, negation, transport/settings and refusal bodies are not
        # weakened; this does not rerun the stopped AU03/AU02 contracts.

    def IQ25_STATIC_public_normalizer_order(self):
        owner = _definition(self.tree, "extract_session_claims")
        normalize = [node for node in ast.walk(owner) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == "_normalize_exchanges"]
        effects = [node for node in ast.walk(owner) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id in {
                       "read_extraction_settings", "_heuristic_extract", "_llm_extract", "add_claim_callback"}]
        self.assertEqual(len(normalize), 1)
        self.assertTrue(effects)
        self.assertTrue(all(normalize[0].lineno < node.lineno for node in effects))
        self.assertEqual(_structural(_definition(self.tree, "_normalize_exchanges")),
                         _structural(_definition(self.old_tree, "_normalize_exchanges")))

    def IQ25_STATIC_collection_and_factory(self):
        path = DEVTOOLS_INPUTS["test_extractor_input_budget_source.py"]
        tree = ast.parse(devtools_read_bound(path), filename=path)
        flags = [node for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "__test__" for target in node.targets)]
        self.assertEqual(len(flags), 1)
        self.assertIs(flags[0].value.value, False)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                self.assertFalse(any(isinstance(child, ast.Call) for child in ast.walk(node.value))
                                 and not (isinstance(node.value, ast.Call)
                                          and isinstance(node.value.func, ast.Name)
                                          and node.value.func.id == "frozenset"))
            elif isinstance(node, (ast.Expr, ast.If, ast.With, ast.Try, ast.For)):
                self.assertTrue(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                                and isinstance(node.value.value, str))
        declared = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)
                                        and any(isinstance(target, ast.Name) and target.id == "CASE_IDS"
                                                for target in node.targets)))
        self.assertEqual(declared, CASE_IDS)
        self.assertEqual(len(declared), len(set(declared)))
        methods = tuple(node.name for node in _definition(tree, "ExtractorInputBudgetSourceTests").body
                        if isinstance(node, ast.FunctionDef) and node.name.startswith("IQ25_"))
        self.assertEqual(methods, CASE_IDS)
        factory = _definition(tree, "build_suite")
        self.assertEqual(ast.unparse(factory.body[0]), "_require_bootstrap()")


def build_suite():
    _require_bootstrap()
    return unittest.TestSuite(ExtractorInputBudgetSourceTests(name) for name in CASE_IDS)
