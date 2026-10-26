"""OR01: finite SOURCE validator controls plus separately named STATIC checks.

Ordinary module import/collection is inert: no product read/import/exec, factory
call, SDK, secret resolver, HTTP, SQL, filesystem fixture or model operation.
An admitted parent entry supplies genuine DEVTOOLS_INPUTS/DEVTOOLS_SCRATCH and
devtools_read_bound, then calls build_suite() with normal unittest lifecycle.
Only exact reviewed definitions execute during suite setup. SimpleNamespace
responses below are synthetic DATA, not SDK modules or authorization stand-ins.
The parent result/start reporter is the sole owner of case-start reporting.
Optional refusal omission is compatibility, never proven-null/checkpoint proof.
"""
from __future__ import annotations

import ast
import hashlib
import json
from types import SimpleNamespace
import unittest

__test__ = False

CASE_IDS = (
    "OR01_SOURCE_healthy_claims_nonempty",
    "OR01_SOURCE_healthy_claims_empty",
    "OR01_SOURCE_optional_refusal_omitted",
    "OR01_SOURCE_optional_refusal_null",
    "OR01_SOURCE_terminal_negative_matrix",
    "OR01_SOURCE_error_envelopes",
    "OR01_SOURCE_explicit_refusal_nonnull",
    "OR01_SOURCE_choices_shape",
    "OR01_SOURCE_message_shape",
    "OR01_SOURCE_content_shape",
    "OR01_SOURCE_tools_and_function_call",
    "OR01_SOURCE_safe_exceptions",
    "OR01_STATIC_actual_caller_wiring",
    "OR01_STATIC_route_deadline_cleanup_unchanged",
    "OR01_STATIC_collection_factory_inert",
)


def _require_bootstrap():
    required = ("DEVTOOLS_INPUTS", "DEVTOOLS_SCRATCH", "devtools_read_bound")
    if any(name not in globals() for name in required):
        raise RuntimeError("OR01_genuine_source_bootstrap_required")
    if (type(DEVTOOLS_INPUTS) is not dict or not callable(devtools_read_bound)
            or type(DEVTOOLS_SCRATCH) is not str or not DEVTOOLS_SCRATCH):
        raise RuntimeError("OR01_source_bootstrap_shape_invalid")
    for name in ("extractor.py", "test_openrouter_terminal_response_source.py"):
        if type(DEVTOOLS_INPUTS.get(name)) is not str or not DEVTOOLS_INPUTS[name]:
            raise RuntimeError("OR01_bound_source_input_required")


def _definition(tree, name):
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name]
    if len(selected) != 1:
        raise RuntimeError("OR01_unique_source_definition_required")
    return selected[0]


class OpenRouterTerminalResponseSourceTests(unittest.TestCase):
    __test__ = False

    @classmethod
    def setUpClass(cls):
        _require_bootstrap()
        cls.path = DEVTOOLS_INPUTS["extractor.py"]
        cls.raw = devtools_read_bound(cls.path)
        if type(cls.raw) is not bytes or len(cls.raw) > 1_000_000:
            raise RuntimeError("OR01_bound_source_bytes_required")
        cls.tree = ast.parse(cls.raw, filename=cls.path)
        names = ("ExtractionBoundaryError", "_openrouter_response_content",
                 "_extraction_error_code", "_extraction_diagnostics")
        selected = [_definition(cls.tree, name) for name in names]
        if any(isinstance(node, (ast.Import, ast.ImportFrom))
               for definition in selected for node in ast.walk(definition)):
            raise RuntimeError("OR01_unreviewed_source_import_dependency")
        future = [node for node in cls.tree.body if isinstance(node, ast.ImportFrom)
                  and node.module == "__future__"]
        cls.ns = {"__name__": "OR01_exact_source_definitions", "__file__": cls.path, "json": json}
        # Existing source-definition pattern: original AST, locations and bodies,
        # one namespace, no import rewriting, product/module bootstrap or stubs.
        exec(compile(ast.Module(body=[*future, *selected], type_ignores=[]), cls.path,
                     "exec", dont_inherit=True), cls.ns)

    @classmethod
    def tearDownClass(cls):
        cls.ns = cls.tree = cls.raw = cls.path = None

    def setUp(self):
        for name in ("_openrouter_response_content", "_extraction_error_code", "_extraction_diagnostics"):
            self.assertIs(self.ns[name].__globals__, self.ns)
            self.assertEqual(self.ns[name].__code__.co_filename, self.path)

    def reply(self, content='{"claims": []}'):
        return SimpleNamespace(choices=[SimpleNamespace(
            index=0, finish_reason="stop", message=SimpleNamespace(
                role="assistant", content=content, tool_calls=None, function_call=None, refusal=None))])

    def accept(self, reply):
        actual = self.ns["_openrouter_response_content"](reply)
        self.assertIs(actual, reply.choices[0].message.content)
        return actual

    def reject(self, reply, code):
        with self.assertRaises(self.ns["ExtractionBoundaryError"]) as caught:
            self.ns["_openrouter_response_content"](reply)
        error = caught.exception
        self.assertEqual(error.args, (code,))
        self.assertEqual(str(error), code)
        self.assertEqual(self.ns["_extraction_error_code"](error), code)
        diagnostic = self.ns["_extraction_diagnostics"](code)
        self.assertEqual((diagnostic["offered"], diagnostic["grounded"], diagnostic["rejected"]), (0, 0, 0))
        for name in ("actual_model", "model_capability", "server_schema_enforced"):
            self.assertEqual(diagnostic[name], "UNKNOWN")
        return diagnostic

    def OR01_SOURCE_healthy_claims_nonempty(self):
        payload = {"claims": [{
            "claim": "User reports Project Aster uses a violet release channel.",
            "type": "fact", "topic": "Aster", "evidence_quote": "Project Aster uses a violet release channel.",
            "speaker": "user", "message_index": 0, "event_at": "", "confidence": 0.8,
        }]}
        content = " \n" + json.dumps(payload, ensure_ascii=False) + "\n "
        self.assertEqual(json.loads(self.accept(self.reply(content))), payload)

    def OR01_SOURCE_healthy_claims_empty(self):
        content = ' \n{"claims": []}\n '
        self.assertEqual(json.loads(self.accept(self.reply(content))), {"claims": []})

    def OR01_SOURCE_optional_refusal_omitted(self):
        reply = self.reply()
        del reply.choices[0].message.refusal
        self.accept(reply)
        # Documented optional tool fields may also be omitted. This proves no
        # native SDK or producer refusal preservation: these are authored data.
        del reply.choices[0].message.tool_calls
        del reply.choices[0].message.function_call
        self.accept(reply)

    def OR01_SOURCE_optional_refusal_null(self):
        for tools in (None, []):
            with self.subTest(tool_calls=tools):
                reply = self.reply()
                reply.error = reply.choices[0].error = None
                reply.choices[0].message.tool_calls = tools
                self.accept(reply)

    def OR01_SOURCE_terminal_negative_matrix(self):
        self.accept(self.reply())
        cases = (
            ("length", "response_truncated"), ("content_filter", "response_refused"),
            ("error", "response_completion_unconfirmed"), ("tool_calls", "response_completion_unconfirmed"),
            ("function_call", "response_completion_unconfirmed"), ("vendor_terminal", "response_completion_unconfirmed"),
            ("incomplete", "response_completion_unconfirmed"), ("end_turn", "response_completion_unconfirmed"),
            (None, "response_completion_unconfirmed"), ("", "response_completion_unconfirmed"),
            ("STOP", "response_completion_unconfirmed"), ("stop ", "response_completion_unconfirmed"),
            (False, "response_completion_unconfirmed"), (0, "response_completion_unconfirmed"),
            ([], "response_completion_unconfirmed"), ({}, "response_completion_unconfirmed"),
        )
        for reason, code in cases:
            with self.subTest(reason=reason):
                reply = self.reply()
                reply.choices[0].finish_reason = reason
                self.reject(reply, code)
        reply = self.reply()
        del reply.choices[0].finish_reason
        self.reject(reply, "response_completion_unconfirmed")

    def OR01_SOURCE_error_envelopes(self):
        self.accept(self.reply())
        for location in ("response", "choice"):
            for error in ({"message": "OR01_SYNTHETIC_PRIVATE_CANARY"}, "private-error", {}, [], "", False, 0):
                with self.subTest(location=location, error_type=type(error).__name__):
                    reply = self.reply()
                    owner = reply if location == "response" else reply.choices[0]
                    owner.error = error
                    self.reject(reply, "response_completion_unconfirmed")

    def OR01_SOURCE_explicit_refusal_nonnull(self):
        self.accept(self.reply())
        for refusal in ("OR01_SYNTHETIC_PRIVATE_CANARY", "", False, 0, [], {}, SimpleNamespace()):
            with self.subTest(refusal_type=type(refusal).__name__):
                reply = self.reply()
                reply.choices[0].message.refusal = refusal
                diagnostic = self.reject(reply, "response_refused")
                self.assertEqual(diagnostic["outcome"], "refused")

    def OR01_SOURCE_choices_shape(self):
        self.accept(self.reply())
        for choices in (None, [], [self.reply().choices[0], self.reply().choices[0]], (), {}, "choices", 1):
            with self.subTest(choices_type=type(choices).__name__):
                self.reject(SimpleNamespace(choices=choices), "response_choice_invalid")
        for response in (SimpleNamespace(), None, {}, "response"):
            with self.subTest(response_type=type(response).__name__):
                self.reject(response, "response_choice_invalid")
        for choice in (None, {}, [], "choice", SimpleNamespace()):
            with self.subTest(choice_type=type(choice).__name__):
                self.reject(SimpleNamespace(choices=[choice]), "response_completion_unconfirmed")

    def OR01_SOURCE_message_shape(self):
        self.accept(self.reply())
        for message in (None, {}, [], "message", SimpleNamespace()):
            with self.subTest(message_type=type(message).__name__):
                reply = self.reply()
                reply.choices[0].message = message
                self.reject(reply, "response_non_text")
        reply = self.reply()
        del reply.choices[0].message
        self.reject(reply, "response_non_text")
        for role in (None, "user", "tool", "system", "Assistant", "assistant ", "", False, 0, [], {}):
            with self.subTest(role=role):
                reply = self.reply()
                reply.choices[0].message.role = role
                self.reject(reply, "response_non_text")
        reply = self.reply()
        del reply.choices[0].message.role
        self.reject(reply, "response_non_text")

    def OR01_SOURCE_content_shape(self):
        self.accept(self.reply())
        for content in (None, "", " \t\r\n", False, 0, [], {}, b'{"claims": []}',
                        [{"type": "text", "text": '{"claims": []}'}]):
            with self.subTest(content_type=type(content).__name__):
                self.reject(self.reply(content), "response_text_invalid")
        reply = self.reply()
        del reply.choices[0].message.content
        self.reject(reply, "response_text_invalid")

    def OR01_SOURCE_tools_and_function_call(self):
        self.accept(self.reply())
        for tools in ([{"type": "function", "function": {"name": "synthetic"}}], (), {}, "", False, 0):
            with self.subTest(tool_calls_type=type(tools).__name__):
                reply = self.reply()
                reply.choices[0].message.tool_calls = tools
                self.reject(reply, "response_non_text")
        for function in ({"name": "synthetic"}, {}, [], "", False, 0):
            with self.subTest(function_call_type=type(function).__name__):
                reply = self.reply()
                reply.choices[0].message.function_call = function
                self.reject(reply, "response_non_text")

    def OR01_SOURCE_safe_exceptions(self):
        touched = []

        class Opaque:
            def __str__(self):
                touched.append("str")
                raise AssertionError("OR01_SYNTHETIC_PRIVATE_CANARY")

            def __repr__(self):
                touched.append("repr")
                raise AssertionError("OR01_SYNTHETIC_PRIVATE_CANARY")

            def __bool__(self):
                touched.append("bool")
                raise AssertionError("OR01_SYNTHETIC_PRIVATE_CANARY")

            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("OR01_SYNTHETIC_PRIVATE_CANARY")

        for location, field, code in (
            ("response", "error", "response_completion_unconfirmed"),
            ("choice", "error", "response_completion_unconfirmed"),
            ("choice", "finish_reason", "response_completion_unconfirmed"),
            ("message", "refusal", "response_refused"),
            ("message", "role", "response_non_text"),
            ("message", "tool_calls", "response_non_text"),
            ("message", "function_call", "response_non_text"),
            ("message", "content", "response_text_invalid"),
        ):
            with self.subTest(location=location, field=field):
                reply = self.reply()
                owner = {"response": reply, "choice": reply.choices[0], "message": reply.choices[0].message}[location]
                setattr(owner, field, Opaque())
                self.reject(reply, code)
        self.assertEqual(touched, [])
        canary = "OR01_SYNTHETIC_PRIVATE_CANARY"
        for error, code in ((ValueError(canary), "ValueError"), (RuntimeError(canary), "extraction_request_failed")):
            self.assertEqual(self.ns["_extraction_error_code"](error), code)
            self.assertNotIn(canary, json.dumps(self.ns["_extraction_diagnostics"](code)))

    def OR01_STATIC_actual_caller_wiring(self):
        owner = _definition(self.tree, "_openrouter_content")
        scopes = [node for node in owner.body if isinstance(node, ast.Try)]
        self.assertEqual(len(scopes), 1)
        expected_tail = ast.parse("check_deadline()\nreturn _openrouter_response_content(response)").body
        self.assertEqual([ast.dump(n, include_attributes=False) for n in scopes[0].body[-2:]],
                         [ast.dump(n, include_attributes=False) for n in expected_tail])
        calls = [node for node in ast.walk(owner) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "_openrouter_response_content"]
        self.assertEqual(len(calls), 1)
        caller = _definition(self.tree, "_llm_extract")
        branches = [node for node in ast.walk(caller) if isinstance(node, ast.If)
                    and ast.dump(node.test, include_attributes=False) == ast.dump(
                        ast.parse('settings.provider == "openrouter"', mode="eval").body, include_attributes=False)]
        self.assertEqual(len(branches), 1)
        expected = ast.parse("content = _openrouter_content(settings, request_messages)").body[0]
        self.assertEqual([ast.dump(n, include_attributes=False) for n in branches[0].body],
                         [ast.dump(expected, include_attributes=False)])
        parses = [node for node in ast.walk(caller) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "_strict_json_object"]
        self.assertEqual(len(parses), 1)
        self.assertEqual(ast.dump(parses[0], include_attributes=False),
                         ast.dump(ast.parse("_strict_json_object(content)", mode="eval").body, include_attributes=False))
        self.assertGreater(parses[0].lineno, branches[0].lineno)
        span = ast.get_source_segment(self.raw.decode("utf-8"), caller)
        self.assertEqual(hashlib.sha256(span.encode("utf-8")).hexdigest(),
                         "508a2b21de641d701f501ad222f80525ecec4b2e0cf3c70d2a49e28d59471496")

    def OR01_STATIC_route_deadline_cleanup_unchanged(self):
        owner = _definition(self.tree, "_openrouter_content")
        span = ast.get_source_segment(self.raw.decode("utf-8"), owner)
        needle = "        return _openrouter_response_content(response)"
        self.assertEqual(span.count(needle), 1)
        old_tail = ('        if response.choices[0].message.tool_calls:\n'
                    '            raise ValueError("OpenRouter non-text response")\n'
                    '        return response.choices[0].message.content')
        # Reconstruct the sole removed guard/return, then hash the entire original
        # function's UTF-8 span (without trailing newline) at b656c4a. This keeps
        # keys, endpoint, SDK args, hooks, deadline, no-retry and finally exact;
        # it is raw-source STATIC parity, not version-sensitive AST fingerprinting.
        restored = span.replace(needle, old_tail)
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(),
                         "b355677c357a4e91088212772c218c48aa4e7edf59083454093d7951726d880e")

    def OR01_STATIC_collection_factory_inert(self):
        path = DEVTOOLS_INPUTS["test_openrouter_terminal_response_source.py"]
        tree = ast.parse(devtools_read_bound(path), filename=path)
        module_assignments = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                              if isinstance(node, ast.Assign) and len(node.targets) == 1
                              and isinstance(node.targets[0], ast.Name)}
        self.assertIs(module_assignments["__test__"], False)
        ids = module_assignments["CASE_IDS"]
        self.assertEqual(ids, CASE_IDS)
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(all(name.startswith("OR01_SOURCE_") or name.startswith("OR01_STATIC_") for name in ids))
        owner = _definition(tree, "OpenRouterTerminalResponseSourceTests")
        self.assertTrue(any(isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                            and n.targets[0].id == "__test__" and ast.literal_eval(n.value) is False
                            for n in owner.body))
        methods = {node.name for node in owner.body if isinstance(node, ast.FunctionDef) and node.name.startswith("OR01_")}
        self.assertEqual(methods, set(ids))
        allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.ClassDef)
        for node in tree.body:
            self.assertTrue(isinstance(node, allowed) or (isinstance(node, ast.Expr)
                            and isinstance(node.value, ast.Constant) and type(node.value.value) is str))
        imports = {node.module if isinstance(node, ast.ImportFrom) else alias.name
                   for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
                   for alias in node.names}
        self.assertEqual(imports, {"__future__", "ast", "hashlib", "json", "types", "unittest"})
        factory = _definition(tree, "build_suite")
        expected = ast.parse('_require_bootstrap()\nreturn unittest.TestSuite(\n'
                             '    OpenRouterTerminalResponseSourceTests(case) for case in CASE_IDS)').body
        self.assertEqual([ast.dump(n, include_attributes=False) for n in factory.body],
                         [ast.dump(n, include_attributes=False) for n in expected])


def build_suite() -> unittest.TestSuite:
    _require_bootstrap()
    return unittest.TestSuite(OpenRouterTerminalResponseSourceTests(case) for case in CASE_IDS)
