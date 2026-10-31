"""SOURCE regression: direct end-extraction selects dialogue, not tool frames.

Collection is inert. The admitted existing SOURCE bootstrap supplies bound
caller_current.py, caller_baseline.py and extractor.py. Exact original caller
and normalizer definitions execute; receiver, settings and extraction callback
are explicit synthetic observation seams. No SDK, SQL, model, user store,
grounding, public save, retained-event worker or ordinary Telegram is exercised.
"""
from __future__ import annotations

import ast
from collections import deque
import datetime as _dt
import json
import math
import re
import unittest

__test__ = False
CASE_IDS = (
    "SFW_SOURCE_tool_heavy_baseline_and_fix",
    "SFW_SOURCE_short_dialogue_and_time_unchanged",
    "SFW_SOURCE_last32_dialogue_with_interleaved_tools",
    "SFW_SOURCE_nonstring_and_protocol_frames_excluded",
    "SFW_SOURCE_empty_dialogue_has_no_handoff",
    "SFW_SOURCE_message_boundary_preserves_whole_source",
    "SFW_SOURCE_transcript_boundary_preserves_whole_window",
    "SFW_SOURCE_older_oversize_outside_dialogue_window",
    "SFW_SOURCE_callback_and_settings_handoff_unchanged",
    "SFW_STATIC_inert_collection_and_bounded_caller",
)
NORMALIZER_DEFINITIONS = (
    "ExtractionBoundaryError", "_coerce_event_at", "_message_event_at", "_normalize_exchanges",
)
NORMALIZER_CONSTANTS = frozenset({"_MAX_MESSAGES", "_MAX_MESSAGE_CHARS", "_MAX_TRANSCRIPT_CHARS"})


def _require_bootstrap():
    if (type(globals().get("DEVTOOLS_INPUTS")) is not dict
            or type(globals().get("DEVTOOLS_SCRATCH")) is not str
            or not DEVTOOLS_SCRATCH or not callable(globals().get("devtools_read_bound"))):
        raise RuntimeError("SFW_genuine_SOURCE_bootstrap_required")
    for name in ("caller_current.py", "caller_baseline.py", "extractor.py",
                 "test_session_extractor_frame_window_source.py"):
        if type(DEVTOOLS_INPUTS.get(name)) is not str or not DEVTOOLS_INPUTS[name]:
            raise RuntimeError("SFW_bound_input_required")


def _definition(tree, name):
    found = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name]
    if len(found) != 1:
        raise RuntimeError("SFW_unique_definition_required")
    return found[0]


def _assigned_names(node):
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return {n.id for n in targets if isinstance(n, ast.Name)}


def _load_normalizer():
    path = DEVTOOLS_INPUTS["extractor.py"]
    tree = ast.parse(devtools_read_bound(path), filename=path)
    selected = [_definition(tree, name) for name in NORMALIZER_DEFINITIONS]
    constants = [n for n in tree.body if _assigned_names(n) & NORMALIZER_CONSTANTS]
    if set().union(*(_assigned_names(n) for n in constants)) != NORMALIZER_CONSTANTS:
        raise RuntimeError("SFW_normalizer_constant_closure")
    future = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    ns = {"__name__": "SFW_normalizer", "__file__": path, "math": math, "_dt": _dt, "re": re}
    exec(compile(ast.Module(body=[*future, *constants, *selected], type_ignores=[]),
                 path, "exec", dont_inherit=True), ns)
    return ns


def _load_caller(name, extraction, settings):
    path = DEVTOOLS_INPUTS[name]
    raw = devtools_read_bound(path)
    tree = ast.parse(raw, filename=path)
    if (len(tree.body) != 2 or not isinstance(tree.body[0], ast.ImportFrom)
            or tree.body[0].module != "__future__" or not isinstance(tree.body[1], ast.If)
            or not isinstance(tree.body[1].test, ast.Constant) or tree.body[1].test.value is not True
            or tree.body[1].orelse or len(tree.body[1].body) != 1):
        raise RuntimeError("SFW_exact_caller_carrier_required")
    owner = tree.body[1].body[0]
    if not isinstance(owner, ast.FunctionDef) or owner.name != "_extract_session_claims" or owner.decorator_list:
        raise RuntimeError("SFW_caller_owner_required")
    ns = {"__name__": "SFW_caller", "__file__": path, "deque": deque, "json": json,
          "extract_session_claims": extraction, "read_extraction_settings": settings,
          "redact_secrets": object(), "secret_scan": object(), "short": lambda value, limit: value[:limit]}
    exec(compile(raw, path, "exec", dont_inherit=True), ns)
    if ns["_extract_session_claims"].__globals__ is not ns:
        raise RuntimeError("SFW_original_namespace_required")
    return ns, tree


class _Receiver:
    """Synthetic receiver: deliberately unavailable DB, never an SQL grant."""
    def __init__(self):
        self.bot_id, self.session_id, self.home = "synthetic-bot", "synthetic-session", DEVTOOLS_SCRATCH
        self.connect_attempts = 0
        self.save_attempts = 0
        self.graph_attempts = 0
        self.audits = []

    def _connect(self):
        self.connect_attempts += 1
        raise OSError("SFW_synthetic_database_unavailable")

    def _chat_hash(self, session):
        return "synthetic-session-hash"

    def _add_claim(self, *args, **kwargs):
        self.save_attempts += 1
        raise AssertionError("SFW_no_persistence_admission")

    def _auto_graph_enrich_extracted_claims(self, *args):
        self.graph_attempts += 1
        raise AssertionError("SFW_no_remote_enrichment_admission")

    def _audit(self, *args):
        self.audits.append(args)


def _tools(count):
    return [row for index in range(count) for row in (
        {"role": "assistant", "content": None, "tool_calls": [{"id": str(index)}]},
        {"role": "tool", "content": "protocol result", "tool_call_id": str(index)},
    )]


class SessionExtractorFrameWindowSourceTests(unittest.TestCase):
    __test__ = False

    @classmethod
    def setUpClass(cls):
        _require_bootstrap()
        cls.normalizer = _load_normalizer()

    @classmethod
    def tearDownClass(cls):
        cls.normalizer = None

    def capture(self, rows, *, baseline=False):
        receiver = _Receiver()
        seen, settings_calls, normalized, refusals = [], [], [], []
        settings_value = object()

        def settings(home):
            settings_calls.append(home)
            return settings_value

        def extraction(exchanges, **kwargs):
            self.assertIs(type(exchanges), list)
            seen.append((exchanges, kwargs))
            try:
                normalized.extend(self.normalizer["_normalize_exchanges"](exchanges))
            except self.normalizer["ExtractionBoundaryError"] as exc:
                refusals.append(exc)
                raise
            return {"extracted": 0, "persisted": 0, "persisted_ids": [], "errors": []}

        name = "caller_baseline.py" if baseline else "caller_current.py"
        ns, tree = _load_caller(name, extraction, settings)
        result = ns["_extract_session_claims"](receiver, rows)
        self.assertIsNone(result)
        self.assertEqual(receiver.save_attempts, 0)
        self.assertEqual(receiver.graph_attempts, 0)
        return receiver, seen, settings_calls, settings_value, normalized, refusals, ns, tree

    def SFW_SOURCE_tool_heavy_baseline_and_fix(self):
        user = {"role": "user", "content": "Project Aster uses the violet channel.",
                "timestamp": 1779292800, "timezone": "Europe/Moscow"}
        assistant = {"role": "assistant", "content": "The violet channel is noted."}
        rows = [user, *_tools(20), assistant]
        self.assertEqual(len(rows), 42)
        old = self.capture(rows, baseline=True)
        new = self.capture(rows)
        self.assertEqual(old[1][0][0], [assistant])
        self.assertEqual(new[1][0][0], [user, assistant])
        self.assertEqual([row["content"] for row in new[4]], [user["content"], assistant["content"]])
        self.assertEqual(new[4][0]["event_at"], user["timestamp"])
        self.assertEqual(new[4][0]["event_timezone"], user["timezone"])
        self.assertEqual(new[0].connect_attempts, 1)
        self.assertEqual(new[0].audits, [])

    def SFW_SOURCE_short_dialogue_and_time_unchanged(self):
        rows = [{"role": "USER", "content": "  Project Aster uses violet.  ",
                 "event_at": 1779292800, "timestamp": 1779292801, "created_at": 1779292802,
                 "event_timezone": "Europe/Moscow", "timezone": "UTC"},
                {"role": "assistant", "content": "\nNoted.\n"}]
        old, new = self.capture(rows, baseline=True), self.capture(rows)
        self.assertEqual(new[1][0][0], old[1][0][0])
        self.assertEqual(new[1][0][0][0], {**rows[0], "role": "user"})
        self.assertEqual(new[4], old[4])
        self.assertEqual(new[4][0]["content"], rows[0]["content"].strip())
        self.assertEqual(rows[0]["content"], "  Project Aster uses violet.  ")

    def SFW_SOURCE_last32_dialogue_with_interleaved_tools(self):
        eligible = [{"role": "user" if i % 2 == 0 else "assistant", "content": "message-" + str(i),
                     "timestamp": 1779292800 + i} for i in range(40)]
        rows = [frame for row in eligible for frame in (row, *_tools(2))]
        new = self.capture(rows)
        self.assertEqual(new[1][0][0], eligible[-32:])
        self.assertEqual(len(new[4]), 32)
        self.assertEqual([r["content"] for r in new[4]], [r["content"] for r in eligible[-32:]])
        self.assertEqual([r["message_index"] for r in new[4]], list(range(32)))

    def SFW_SOURCE_nonstring_and_protocol_frames_excluded(self):
        touched = []

        class Foreign:
            def __str__(self):
                touched.append("str")
                raise AssertionError("SFW_foreign_content_coercion")

        user = {"role": "user", "content": "Owner source."}
        final = {"role": "assistant", "content": "Final source."}
        excluded = [{"role": "user", "content": value} for value in (None, {}, [], Foreign())]
        excluded += [{"role": role, "content": "x" * 25001} for role in ("tool", "system")]
        excluded += [{"role": role, "content": value} for role in ("user", "assistant") for value in ("", " \n\t")]
        result = self.capture([user, *excluded, *_tools(20), final])
        self.assertEqual(result[1][0][0], [user, final])
        self.assertEqual(touched, [])
        self.assertEqual(result[5], [])

    def SFW_SOURCE_empty_dialogue_has_no_handoff(self):
        for rows in ([], _tools(20), [{"role": "user", "content": " \n"}]):
            with self.subTest(shape=len(rows)):
                result = self.capture(rows)
                self.assertEqual(result[0].connect_attempts, 0)
                self.assertEqual(result[1], [])
                self.assertEqual(result[2], [])
                self.assertEqual(result[0].audits, [])

    def SFW_SOURCE_message_boundary_preserves_whole_source(self):
        for text, expected in (("Я🙂e\u0301" * 6250, None),
                               ("Я🙂e\u0301" * 6250 + "я", "source_message_budget_exceeded"),
                               ("owner text" + " " * 24991, "source_message_budget_exceeded")):
            with self.subTest(chars=len(text), expected=expected):
                row = {"role": "user", "content": text}
                result = self.capture([row, *_tools(20)])
                self.assertEqual(result[1][0][0], [row])
                if expected is None:
                    self.assertEqual(result[4][0]["content"], text)
                    self.assertEqual(result[5], [])
                    self.assertEqual(result[0].audits, [])
                else:
                    self.assertEqual(len(result[5]), 1)
                    self.assertEqual(result[5][0].args, (expected,))
                    self.assertEqual(result[4], [])
                    self.assertEqual(result[0].audits[0][:2], ("extraction", "failed"))

    def SFW_SOURCE_transcript_boundary_preserves_whole_window(self):
        for last_length, expected in ((23000, None), (23001, "source_transcript_budget_exceeded")):
            with self.subTest(last_length=last_length):
                rows = [{"role": "user", "content": "u" * 25000},
                        *_tools(20), {"role": "assistant", "content": "a" * last_length}]
                result = self.capture(rows)
                self.assertEqual(result[1][0][0], [rows[0], rows[-1]])
                if expected is None:
                    self.assertEqual([r["content"] for r in result[4]], [rows[0]["content"], rows[-1]["content"]])
                    self.assertEqual(result[5], [])
                else:
                    self.assertEqual(len(result[5]), 1)
                    self.assertEqual(result[5][0].args, (expected,))
                    self.assertEqual(result[4], [])

    def SFW_SOURCE_older_oversize_outside_dialogue_window(self):
        tail = [{"role": "assistant", "content": "tail-" + str(i)} for i in range(32)]
        rows = [{"role": "user", "content": "x" * 25001}]
        rows += [frame for row in tail for frame in (*_tools(1), row)]
        result = self.capture(rows)
        self.assertEqual(result[1][0][0], tail)
        self.assertEqual(len(result[4]), 32)
        self.assertEqual(result[5], [])

    def SFW_SOURCE_callback_and_settings_handoff_unchanged(self):
        row = {"role": "user", "content": "Whole speech."}
        receiver, seen, settings_calls, settings_value, _, _, ns, _ = self.capture([row])
        self.assertEqual(settings_calls, [receiver.home])
        self.assertEqual(len(seen), 1)
        kwargs = seen[0][1]
        self.assertEqual(set(kwargs), {"session_id", "add_claim_callback", "redact_secret_callback",
                                      "secret_scan_callback", "extraction_settings"})
        self.assertEqual(kwargs["session_id"], receiver.session_id)
        self.assertEqual(kwargs["add_claim_callback"], receiver._add_claim)
        self.assertIs(kwargs["redact_secret_callback"], ns["redact_secrets"])
        self.assertIs(kwargs["secret_scan_callback"], ns["secret_scan"])
        self.assertIs(kwargs["extraction_settings"], settings_value)

    def SFW_STATIC_inert_collection_and_bounded_caller(self):
        _, _, _, _, _, _, _, tree = self.capture([{"role": "user", "content": "source"}])
        owner = tree.body[1].body[0]
        loop = next(n for n in ast.walk(owner) if isinstance(n, ast.For) and ast.unparse(n.target) == "message")
        self.assertEqual(ast.unparse(loop.iter), "messages")
        initial = owner.body[1].body[0]
        self.assertEqual(ast.unparse(initial), "exchanges = deque(maxlen=32)")
        source = ast.parse(devtools_read_bound(DEVTOOLS_INPUTS["test_session_extractor_frame_window_source.py"]))
        actual = tuple(n.name for n in _definition(source, "SessionExtractorFrameWindowSourceTests").body
                       if isinstance(n, ast.FunctionDef) and n.name.startswith("SFW_"))
        self.assertEqual(actual, CASE_IDS)
        self.assertEqual(len(actual), len(set(actual)))
        for node in source.body:
            self.assertNotIsInstance(node, (ast.If, ast.Try, ast.With, ast.For))
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                self.assertEqual(ast.unparse(node.value.func), "frozenset")


def build_suite():
    _require_bootstrap()
    return unittest.TestSuite(SessionExtractorFrameWindowSourceTests(name) for name in CASE_IDS)
