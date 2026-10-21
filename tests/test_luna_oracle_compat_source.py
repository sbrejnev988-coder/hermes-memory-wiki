"""M4 test-only SOURCE compatibility; no pytest collection, SDK or native calls.

Run this shipped file with -I -B -S in an owned credential-free scratch, or use
unchanged devtools/harness.py run_source with the explicit runtime mapping.
Full actual extractor/http modules execute; only the legacy settings reader and
outbound transport are authored seams. The Codex helper itself NEVER executes:
only its exact authored return expression is evaluated, not a genuine SDK reply.
All 17 helper consumers remain native NOT_RUN. AST/raw equality is static proof.
The optional original-*.py.txt inputs are byte-exact e92 tests. Without those
inputs the static before projection is an inverse of the two literal edits,
checked against frozen whole-file hashes; no external unshipped peer is needed.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-6-luna"
SANITIZER = "test_remote_extractor_sanitizer_failure_is_fail_closed"
OLD_CODE = "transcript sanitization failed: RuntimeError"
SAFE_CODE = "transcript_sanitization_failed"
BEFORE_SHA = {
    "grounding": "83433d37265a2a17008767f9afb11973653536e61574ad3b85d5ad24aef6c6b5",
    "codex": "1a953ff8f56f331a6fa701e9d89b5190b4c3ce5475e093f35f473721fc65455b",
}
OLD_RETURN = """SimpleNamespace(model=model, choices=[SimpleNamespace(message=SimpleNamespace(
            content=content if content is not None else json.dumps({'claims': [_candidate()]}),
            tool_calls=None))])"""
NEW_RETURN = """SimpleNamespace(model=model, choices=[SimpleNamespace(index=0, finish_reason='stop', message=SimpleNamespace(
            role='assistant', refusal=None,
            content=content if content is not None else json.dumps({'claims': [_candidate()]}),
            tool_calls=None))])"""
AUTHORED_COMMENT = "        # Authored synthetic validator input, NOT genuine SDK non-refusal provenance.\n"
OBSERVATIONS = {}
SQL_ATTEMPTS = []


def source_path(name):
    return Path(globals().get("DEVTOOLS_INPUTS", {}).get(name, ROOT / name))


def read_source(path):
    reader = globals().get("devtools_read_bound")
    return reader(str(path)) if reader else Path(path).read_bytes()


def current_test(kind):
    return read_source(ROOT / ("tests/test_session_extractor_" + kind + ".py"))


def before_test(kind):
    name = "original-" + kind + ".py.txt"
    inputs = globals().get("DEVTOOLS_INPUTS", {})
    if name in inputs:
        raw = read_source(Path(inputs[name]))
    else:
        text = current_test(kind).decode("utf-8")
        if kind == "grounding":
            assert text.count('"' + SAFE_CODE + '"') == 1
            text = text.replace('"' + SAFE_CODE + '"', '"' + OLD_CODE + '"')
        else:
            assert text.count(NEW_RETURN) == text.count(AUTHORED_COMMENT) == 1
            text = text.replace(NEW_RETURN, OLD_RETURN).replace(AUTHORED_COMMENT, "")
        raw = text.encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == BEFORE_SHA[kind]
    return raw


def named(nodes, kind, name):
    found = [node for node in nodes if isinstance(node, kind) and node.name == name]
    assert len(found) == 1, name
    return found[0]


def fixture_return(raw):
    helper = named(ast.parse(raw).body, ast.FunctionDef, "_native")
    complete = named(helper.body, ast.FunctionDef, "complete")
    returns = [node for node in complete.body if isinstance(node, ast.Return)]
    assert len(returns) == 1
    return returns[0].value


def authored_reply(*, old=False, content=None):
    raw = before_test("codex") if old else current_test("codex")
    candidate = named(ast.parse(raw).body, ast.FunctionDef, "_candidate")
    namespace = {"SimpleNamespace": types.SimpleNamespace, "json": json,
                 "model": MODEL, "content": content}
    exec(compile(ast.Module(body=[candidate], type_ignores=[]), "m4-authored-candidate", "exec"), namespace)
    expression = ast.Expression(body=fixture_return(raw))
    return eval(compile(expression, "m4-authored-return-only", "eval"), namespace)


def load_sources():
    # Same direct full-source loading as the existing shipped Luna SOURCE tests.
    # These are real local modules, not agent/hermes_constants/SDK stand-ins.
    result = []
    for name in ("http_safety", "extractor"):
        path = source_path(name + ".py")
        module = types.ModuleType(name)
        module.__file__, module.__package__ = str(path), ""
        sys.modules[name] = module
        exec(compile(read_source(path), str(path), "exec", dont_inherit=True), module.__dict__)
        result.append(module)
    return result[1]


class LunaOracleCompatSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x = load_sources()
        cls.home = Path(globals().get("DEVTOOLS_SCRATCH", os.environ["TMPDIR"])) / "m4-owner"
        cls.home.mkdir(parents=True, exist_ok=True)

    def invoke(self, reply):
        sent = []

        def authored_transport(settings, messages, **options):
            sent.append((settings.model, messages, options))
            return self.x._codex_response_content(reply, settings.model)

        with patch.object(self.x, "_codex_content", authored_transport):
            answer = self.x.extract_session_claims(
                [{"role": "user", "content": "Project Aster uses a violet release channel."}],
                extraction_settings=self.x.ExtractionSettings(home=self.home, enabled=True))
        assert len(sent) == 1  # Authored boundary only, NEVER network/SDK.
        assert answer["errors"] == []
        assert answer["persisted_ids"] == answer["review_ids"] == []
        assert (answer["persisted"], answer["accepted"], answer["queued_for_review"],
                answer["persistence_unknown"]) == (0, 0, 0, 0)
        assert answer["llm_diagnostics"]["actual_model"] == "UNKNOWN"
        return answer

    def refused(self, reply, code):
        with self.assertRaises(self.x.ExtractionBoundaryError) as caught:
            self.x._codex_response_content(reply, MODEL)
        assert caught.exception.code == code
        answer = self.invoke(reply)
        assert answer["error"] == code
        assert answer["entries"] == [] and answer["extracted"] == 0
        assert answer["llm_diagnostics"]["code"] == code

    def test_01_sanitizer_exact_body_safe_code_and_old_oracle_rejected(self):
        outcomes = []
        for old in (False, True):
            raw = before_test("grounding") if old else current_test("grounding")
            node = named(ast.parse(raw).body, ast.FunctionDef, SANITIZER)
            assert not node.decorator_list
            namespace = {"_module": lambda: self.x}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "m4-affected-sanitizer-body", "exec"), namespace)
            observed = []
            actual_extract = self.x.extract_session_claims

            def observe(*args, **options):
                result = actual_extract(*args, **options)
                observed.append(result)
                return result

            def authored_legacy_reader():
                # Actual env parser, explicit synthetic routing; no SDK reader.
                return self.x.ExtractionSettings(home=self.home, provider="legacy", **self.x._settings())

            with ExitStack() as stack:
                monkeypatch = types.SimpleNamespace(
                    setenv=lambda key, value: stack.enter_context(patch.dict(os.environ, {key: value})),
                    setattr=lambda obj, key, value: stack.enter_context(patch.object(obj, key, value)))
                stack.enter_context(patch.object(self.x, "read_extraction_settings", authored_legacy_reader))
                stack.enter_context(patch.object(self.x, "extract_session_claims", observe))
                if old:
                    with self.assertRaises(AssertionError):
                        namespace[SANITIZER](monkeypatch)
                else:
                    namespace[SANITIZER](monkeypatch)
            assert len(observed) == 1
            answer = observed[0]
            assert answer["error"] == SAFE_CODE
            assert answer["entries"] == [] and answer["extracted"] == 0
            assert answer["persisted_ids"] == answer["review_ids"] == []
            assert "broken sanitizer" not in json.dumps(answer)
            assert "RuntimeError" not in json.dumps(answer)
            outcomes.append("expected_old_oracle_assertion" if old else "corrected_body_passed")
        OBSERVATIONS["sanitizer"] = outcomes

    def test_02_strict_authored_return_positive_and_empty_positive(self):
        reply = authored_reply()
        assert reply.model == MODEL
        choice = reply.choices[0]
        assert choice.index == 0 and choice.finish_reason == "stop"
        assert choice.message.role == "assistant" and choice.message.refusal is None
        content = self.x._codex_response_content(reply, MODEL)
        assert len(self.x._strict_json_object(content)["claims"]) == 1
        answer = self.invoke(reply)
        assert answer["error"] == "" and len(answer["entries"]) == answer["extracted"] == 1
        assert answer["entries"][0]["source"] == "extractor:llm"
        assert answer["entries"][0]["evidence_quote"] == "Project Aster uses a violet release channel."
        empty = self.invoke(authored_reply(content='{"claims":[]}'))
        assert empty["error"] == "" and empty["entries"] == [] and empty["extracted"] == 0
        OBSERVATIONS["authored_positive"] = {"grounded": 1, "empty": 0, "genuine_nonrefusal": "UNKNOWN"}

    def test_03_original_incomplete_authored_fixture_expected_refusal(self):
        expression = fixture_return(before_test("codex"))
        assert ast.dump(expression, include_attributes=False) == ast.dump(ast.parse(OLD_RETURN, mode="eval").body, include_attributes=False)
        reply = authored_reply(old=True)
        assert not hasattr(reply.choices[0], "index")
        assert not hasattr(reply.choices[0], "finish_reason")
        assert not hasattr(reply.choices[0].message, "role")
        assert not hasattr(reply.choices[0].message, "refusal")
        self.refused(reply, "response_choice_invalid")
        OBSERVATIONS["old_fixture"] = "expected response_choice_invalid, not healthy baseline PASS"

    def test_04_independent_missing_fields_and_non_text_controls(self):
        variants = [
            ("index", "response_choice_invalid"),
            ("finish_reason", "response_completion_unconfirmed"),
            ("role", "response_non_text"),
            ("tool_calls", "response_non_text"),
            ("refusal", "response_refusal_unconfirmed"),
        ]
        for field, code in variants:
            reply = authored_reply()
            target = reply.choices[0] if field in {"index", "finish_reason"} else reply.choices[0].message
            delattr(target, field)
            self.refused(reply, code)
        for field, value, code in [
            ("role", "user", "response_non_text"),
            ("tool_calls", [types.SimpleNamespace(id="authored-tool")], "response_non_text"),
            ("content", "", "response_text_invalid"),
            ("content", ["authored block"], "response_text_invalid"),
            ("content", "x" * (self.x._MAX_RESPONSE_BYTES + 1), "response_size_or_type_invalid"),
        ]:
            reply = authored_reply()
            setattr(reply.choices[0].message, field, value)
            self.refused(reply, code)
        OBSERVATIONS["missing_field_and_non_text_controls"] = len(variants) + 5

    def test_05_truncated_and_refused_replies_never_become_candidates(self):
        variants = [("length", "response_truncated"), ("incomplete", "response_truncated"),
                    ("content_filter", "response_refused")]
        for reason, code in variants:
            reply = authored_reply()
            reply.choices[0].finish_reason = reason
            self.refused(reply, code)
        reply = authored_reply()
        reply.choices[0].message.refusal = "authored refusal"
        self.refused(reply, "response_refused")
        OBSERVATIONS["truncated_refused_controls"] = len(variants) + 1

    def test_06_only_two_ast_corrections_all_other_contracts_unchanged(self):
        old_g, old_c = before_test("grounding"), before_test("codex")
        new_g, new_c = current_test("grounding"), current_test("codex")
        assert old_g.count(OLD_CODE.encode()) == 1
        assert new_g == old_g.replace(OLD_CODE.encode(), SAFE_CODE.encode())
        assert old_c.count(OLD_RETURN.encode()) == 1
        assert new_c == old_c.replace(b"        return " + OLD_RETURN.encode(),
                                     AUTHORED_COMMENT.encode() + b"        return " + NEW_RETURN.encode())
        expected_g, actual_g = ast.parse(old_g), ast.parse(new_g)
        oracle = named(expected_g.body, ast.FunctionDef, SANITIZER)
        assertions = [node for node in oracle.body if isinstance(node, ast.Assert)]
        assert len(assertions) == 3
        constant = assertions[-1].test.comparators[0]
        assert constant.value == OLD_CODE
        constant.value = SAFE_CODE
        assert ast.dump(expected_g, include_attributes=False) == ast.dump(actual_g, include_attributes=False)
        expected_c, actual_c = ast.parse(old_c), ast.parse(new_c)
        helper = named(expected_c.body, ast.FunctionDef, "_native")
        complete = named(helper.body, ast.FunctionDef, "complete")
        ret = next(node for node in complete.body if isinstance(node, ast.Return))
        ret.value = copy.deepcopy(fixture_return(new_c))
        assert ast.dump(expected_c, include_attributes=False) == ast.dump(actual_c, include_attributes=False)
        consumers = lambda tree: [node.name for node in tree.body if isinstance(node, ast.FunctionDef)
            and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "_native" for call in ast.walk(node))]
        cohort = consumers(actual_c)
        assert cohort == consumers(ast.parse(old_c)) and len(cohort) == 17
        OBSERVATIONS["static_contract"] = {"literal_assertion_changes": 1, "authored_return_changes": 1,
            "all_other_bytes_and_AST": "unchanged", "native_consumers": cohort, "native_executed": 0}


def main():
    if not (sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.no_site):
        raise RuntimeError("requires_I_B_S")

    def forbid_sql(event, args):
        if event == "sqlite3.connect":
            SQL_ATTEMPTS.append(event)
            raise PermissionError("M4_SQL_NOT_ADMITTED")

    sys.addaudithook(forbid_sql)  # Narrows, never weakens, unchanged SOURCE fence.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LunaOracleCompatSource)
    cases = []

    class Result(unittest.TestResult):
        def startTest(self, test):
            super().startTest(test)
            if globals().get("devtools_case_started"):
                devtools_case_started("m4." + test._testMethodName)

        def addSuccess(self, test):
            super().addSuccess(test)
            cases.append({"id": "m4." + test._testMethodName, "outcome": "passed"})

        def addFailure(self, test, err):
            super().addFailure(test, err)
            cases.append({"id": "m4." + test._testMethodName, "outcome": "failed"})

        def addError(self, test, err):
            super().addError(test, err)
            cases.append({"id": "m4." + getattr(test, "_testMethodName", "setup"), "outcome": "error"})

    result = Result()
    suite.run(result)
    failures = [{"id": str(test), "traceback": trace} for test, trace in result.failures + result.errors]
    if failures:
        # Preserve full diagnostics in owned scratch, not an over-cap traceback dump.
        diagnostic = Path(globals().get("DEVTOOLS_SCRATCH", os.environ["TMPDIR"])) / "m4-failures.json"
        diagnostic.write_text(json.dumps(failures, ensure_ascii=False), encoding="utf-8")
        sys.stderr.write("M4 failure diagnostics: " + str(diagnostic) + "\n")
    forbidden_modules = sorted(name for name in sys.modules if name.split(".", 1)[0]
                               in {"agent", "hermes_constants", "openai", "httpx", "pytest"})
    clean = not forbidden_modules and not SQL_ATTEMPTS
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": cases,
        "observations": OBSERVATIONS, "SQL_attempts": SQL_ATTEMPTS,
        "forbidden_modules": forbidden_modules, "clean_source_scope": clean,
        "roles": {"product": "full actual extractor/http source", "validator": "actual source function",
                  "reply": "authored fixture expression only", "settings_reader": "authored legacy seam",
                  "SDK_native_provider_SQL": "NOT_RUN", "static_AST_main": 1, "behavioral_SOURCE_mains": 5}},
        ensure_ascii=False))
    return 0 if result.wasSuccessful() and clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
