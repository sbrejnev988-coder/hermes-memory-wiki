"""LUNA-S1/L1: SOURCE caller -> full extractor -> authored outbound boundary.

Один packet вместе с неизменёнными 20 Luna controls. Method/secret helpers
извлекаются из exact owning scope, без provider initialize/SDK/SQL. Под harness
caller carrier содержит те же source spans: полный __init__.py > binder 1 MB.
Никакой SQL/redactor authority не подделывается: SQL вход явно отказывает,
redactor/scan — настоящие source-extracted функции, sink — пассивный observer.
Прямой запуск требует собственного credential-free TMPDIR и -I -B -S.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import sys
import types
import unittest
from dataclasses import replace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_HELPERS = frozenset({
    "QUOTED_SECRET_ASSIGN_RE", "QUOTED_SECRET_CONTAINER_RE", "REDaction_MARKER_RE",
    "SECRET_ASSIGN_RE", "SECRET_FIELD_RE", "SECRET_PATTERNS",
    "_balanced_secret_container_end", "_quoted_secret_assignment_is_raw",
    "_redact_quoted_secret_assignment", "_redact_quoted_secret_containers",
    "_sensitive_secret_field", "clamp", "redact_secrets", "secret_scan", "short",
})


def read_source(path):
    reader = globals().get("devtools_read_bound")
    return reader(str(path)) if reader else Path(path).read_bytes()


def load_peer():
    path = ROOT / "tests/test_luna_extractor_boundaries.py"
    ns = {"__name__": "luna_unchanged_controls", "__file__": str(path)}
    for key in ("DEVTOOLS_SCRATCH", "devtools_read_bound"):
        if key in globals():
            ns[key] = globals()[key]
    exec(compile(read_source(path), str(path), "exec", dont_inherit=True), ns)
    return ns


def provider_nodes(raw):
    """Exact method + closed, unchanged local privacy helpers; no imports/init."""
    tree = ast.parse(raw)
    selected = []
    found = set()
    for node in tree.body:
        names = {node.name} if isinstance(node, ast.FunctionDef) else {
            target.id for target in (node.targets if isinstance(node, ast.Assign) else
                                    [node.target] if isinstance(node, ast.AnnAssign) else [])
            if isinstance(target, ast.Name)
        }
        if names & PROVIDER_HELPERS:
            selected.append(node)
            found.update(names & PROVIDER_HELPERS)
    assert found == PROVIDER_HELPERS
    owners = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MemoryWikiProvider"]
    assert len(owners) == 1
    methods = [node for node in owners[0].body if isinstance(node, ast.FunctionDef)
               and node.name == "_extract_session_claims"]
    assert len(methods) == 1 and not methods[0].decorator_list
    selected.append(methods[0])
    return selected


def load_caller(path):
    nodes = provider_nodes(read_source(path))
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    ns = {"__name__": "luna_provider_source", "__file__": str(path), "re": re, "json": json}
    exec(compile(tree, str(path), "exec", dont_inherit=True), ns)
    return ns


def bounded_text(length, prefix="Ordinary context. "):
    assert length >= len(prefix)
    filler = " ordinary context."
    return (prefix + filler * (length // len(filler) + 1))[:length]


def denial_text(length):
    prefix, tail = "Remember: Aster uses Qdrant", ", or not really."
    assert length >= len(prefix) + len(tail)
    return prefix + " " * (length - len(prefix) - len(tail)) + tail


class SourceReceiver:
    """Synthetic receiver, NOT provider/SQL/identity admission or stored proof."""
    def __init__(self, home):
        self.home, self.session_id, self.bot_id = home, "authored-session", "authored-bot"
        self.callbacks, self.audits, self.sql_refusals = [], [], 0

    def _connect(self):
        self.sql_refusals += 1
        raise PermissionError("SQL NOT_RUN in SOURCE")

    def _chat_hash(self, _session):
        return "authored-scope-label"  # Identity mapper is synthetic, not authority.

    def _add_claim(self, claim, **options):
        self.callbacks.append((claim, options))
        return None  # No fabricated c_/rq_ IDs and no assertion of durable effects.

    def _audit(self, *args):
        self.audits.append(args)

    def _auto_graph_enrich_extracted_claims(self, _ids):
        raise AssertionError("SQL-denied source fixture must not enrich")


class LunaSourceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.peer = load_peer()
        cls.x, cls.g = cls.peer["load_sources"]()
        cls.home = Path(globals().get("DEVTOOLS_SCRATCH", os.environ.get("TMPDIR", str(ROOT.parent / "scratch")))) / "scope-owner"
        cls.home.mkdir(parents=True, exist_ok=True)
        cls.caller_path = Path(globals().get("DEVTOOLS_INPUTS", {}).get("luna_caller.py", ROOT / "__init__.py"))
        cls.caller = load_caller(cls.caller_path)

    def settings(self, enabled=True):
        return self.x.ExtractionSettings(home=self.home, enabled=enabled)

    def invoke(self, exchanges, rows=None, *, caller=False, enabled=True, module=None, namespace=None):
        x = module if module is not None else self.x
        settings = x.ExtractionSettings(home=self.home, enabled=enabled)
        sent, callbacks = [], []
        response = self.peer["completion"](json.dumps({"claims": rows or []}))

        def authored_transport(snapshot, messages, **options):
            sent.append((snapshot, messages, options))
            return x._codex_response_content(response, snapshot.model)

        def observe(claim, **options):
            callbacks.append((claim, options))
            return None

        with patch.object(x, "_codex_content", authored_transport):
            if caller:
                ns = dict(namespace if namespace is not None else self.caller)
                ns.update(extract_session_claims=x.extract_session_claims,
                          read_extraction_settings=lambda _home: settings)
                # Functions retain their own actual globals, not this dict copy.
                original = (namespace if namespace is not None else self.caller)["_extract_session_claims"]
                body = types.FunctionType(original.__code__, ns, original.__name__)
                receiver = SourceReceiver(self.home)
                body(receiver, exchanges)
                return receiver, sent
            result = x.extract_session_claims(exchanges, session_id="authored-session",
                                              extraction_settings=settings, add_claim_callback=observe)
        return result, sent, callbacks

    def assert_refused(self, result, sent, callbacks, code):
        assert result["error"] == code and result["errors"] == []
        assert result["entries"] == result["persisted_ids"] == result["review_ids"] == []
        assert (result["extracted"], result["persisted"], result["accepted"],
                result["queued_for_review"], result["persistence_unknown"]) == (0, 0, 0, 0, 0)
        assert sent == callbacks == []
        diagnostic = result["llm_diagnostics"]
        assert diagnostic["outcome"] == "source_refused" and diagnostic["code"] == code
        assert (diagnostic["offered"], diagnostic["grounded"], diagnostic["rejected"]) == (0, 0, 0)
        assert diagnostic["actual_model"] == diagnostic["model_capability"] == "UNKNOWN"

    def test_original_caps_and_closed_refusal_diagnostics(self):
        assert (self.x._MAX_MESSAGES, self.x._MAX_MESSAGE_CHARS, self.x._MAX_TRANSCRIPT_CHARS) == (32, 6000, 48000)
        for code in ("source_message_budget_exceeded", "source_transcript_budget_exceeded"):
            assert code in self.x.ExtractionBoundaryError.CODES
            assert self.x._extraction_error_code(self.x.ExtractionBoundaryError(code)) == code
            diagnostic = self.x._extraction_diagnostics(code)
            assert set(diagnostic) == {"outcome", "code", "offered", "grounded", "rejected", "actual_model",
                                       "model_capability", "server_schema_enforced"}
            assert diagnostic["outcome"] == "source_refused"

    def test_actual_caller_raw_dict_list_objects_never_coerced_or_dispatched(self):
        touched = []
        class Foreign:
            def __str__(self):
                touched.append("str")
                raise AssertionError("foreign str")
            def __bool__(self):
                touched.append("bool")
                raise AssertionError("foreign bool")
        class ForeignString(str):
            def strip(self, *args):
                touched.append("strip")
                raise AssertionError("not a plain string")
        for raw in ({"attachment": {"text": "ordinary attachment body"}},
                    [{"text": "ordinary attachment body"}], Foreign(), ForeignString("Remember: Aster uses Qdrant.")):
            receiver, sent = self.invoke([{"role": "user", "content": raw}], caller=True)
            assert sent == receiver.callbacks == receiver.audits == [] and receiver.sql_refusals == 0
            assert self.x._normalize_exchanges([{"role": "user", "content": raw}]) == []
        assert touched == []

    def test_actual_caller_plain_strings_roles_indexes_and_source_time(self):
        rows = [self.peer["entry"](), self.peer["entry"](claim="I completed Aster tests.",
                evidence_quote="I completed Aster tests.", speaker="assistant", message_index=1)]
        receiver, sent = self.invoke([
            {"role": "tool", "content": "not owner speech"},
            {"role": "user", "content": "  Project Aster uses violet channel.  ",
             "timestamp": 1779292800, "timezone": "Europe/Moscow"},
            {"role": "assistant", "content": "I completed Aster tests.", "event_at": 1779292801},
        ], rows, caller=True)
        assert len(sent) == 1 and len(receiver.callbacks) == 2 and receiver.sql_refusals == 1
        transcript = json.loads(sent[0][1][1]["content"].split("TRANSCRIPT_JSON:\n", 1)[1])
        assert [(m["message_index"], m["speaker"], m["event_at"]) for m in transcript] == [
            (0, "user", 1779292800), (1, "assistant", 1779292801)]
        assert transcript[0]["content"] == rows[0]["claim"] and transcript[0]["event_timezone"] == "Europe/Moscow"
        for _claim, options in receiver.callbacks:
            evidence = json.loads(options["evidence"])
            assert evidence["session_id"] == "authored-session" and options["visibility_scope"] == "chat"
            assert "verified" not in options and "status" not in options
        assert receiver.audits and receiver.audits[0][1] == "ok"

    def test_actual_caller_preserves_raw_budget_before_whitespace_trim(self):
        text = "Project Aster uses violet channel."
        for raw in (text + " " * (6001 - len(text)), denial_text(6001)):
            receiver, sent = self.invoke([{"role": "user", "content": raw},
                                         {"role": "user", "content": "Remember: Aster uses Qdrant."}], caller=True)
            assert sent == receiver.callbacks == [] and receiver.sql_refusals == 1
            assert receiver.audits[0][1] == "partial"
            audit = json.loads(receiver.audits[0][2])
            assert audit["llm_error"] == "source_message_budget_exceeded" and audit["persisted"] == 0
            assert "Qdrant" not in receiver.audits[0][2]

    def test_message_exact_and_plus_one_refuse_whole_not_remaining_positive(self):
        text = bounded_text(6000, "Remember: Project Aster uses violet channel. ")
        result, sent, callbacks = self.invoke([{"role": "user", "content": text}], [self.peer["entry"]()])
        assert len(sent) == 1 and len(callbacks) == 1 and result["extracted"] == 1
        transcript = json.loads(sent[0][1][1]["content"].split("TRANSCRIPT_JSON:\n", 1)[1])
        assert transcript[0]["content"] == text.strip() and len(transcript[0]["content"]) <= 6000
        for enabled in (False, True):
            result, sent, callbacks = self.invoke([
                {"role": "user", "content": text + "."},
                {"role": "user", "content": "Remember: Project Aster uses violet channel."},
            ], [self.peer["entry"]()], enabled=enabled)
            self.assert_refused(result, sent, callbacks, "source_message_budget_exceeded")

    def test_trailing_denial_exact_whitespace_and_plus_one_no_positive(self):
        row = self.peer["entry"](claim="Aster uses Qdrant.", evidence_quote="Aster uses Qdrant")
        for length in (6000, 6001, 6040):
            result, sent, callbacks = self.invoke([{"role": "user", "content": denial_text(length)}], [row])
            assert callbacks == [] and result["entries"] == []
            if length == 6000:
                assert len(sent) == 1 and ", or not really." in sent[0][1][1]["content"]
                assert result["llm_diagnostics"]["rejected"] == 1
            else:
                self.assert_refused(result, sent, callbacks, "source_message_budget_exceeded")

    def test_transcript_exact_and_plus_one_without_partial_boundary(self):
        texts = [bounded_text(6000, "Remember: Project Aster uses violet channel. ")]
        texts += [bounded_text(6000) for _ in range(7)]
        exchanges = [{"role": "user" if i == 0 else "assistant", "content": text} for i, text in enumerate(texts)]
        assert sum(map(len, texts)) == 48000
        result, sent, callbacks = self.invoke(exchanges, [self.peer["entry"]()])
        assert len(sent) == len(callbacks) == result["extracted"] == 1
        normalized = self.x._normalize_exchanges(exchanges)
        assert len(normalized) == 8 and [m["content"] for m in normalized] == [t.strip() for t in texts]
        result, sent, callbacks = self.invoke(exchanges + [{"role": "assistant", "content": "."}], [self.peer["entry"]()])
        self.assert_refused(result, sent, callbacks, "source_transcript_budget_exceeded")

    def test_transcript_partial_clause_or_whole_denial_omission_refuses_all(self):
        partial = [{"role": "user", "content": denial_text(1000)}]
        partial += [{"role": "assistant", "content": bounded_text(6000)} for _ in range(7)]
        partial += [{"role": "assistant", "content": bounded_text(5970)}]
        omitted = [{"role": "user", "content": "Aster does not use Qdrant."},
                   {"role": "user", "content": bounded_text(6000, "Remember: Aster uses Qdrant. ")}]
        omitted += [{"role": "assistant", "content": bounded_text(6000)} for _ in range(7)]
        for exchanges in (partial, omitted):
            assert max(len(m["content"]) for m in exchanges) <= 6000
            assert sum(len(m["content"]) for m in exchanges) > 48000
            for enabled in (False, True):
                result, sent, callbacks = self.invoke(exchanges, enabled=enabled)
                self.assert_refused(result, sent, callbacks, "source_transcript_budget_exceeded")

    def test_transcript_raw_whitespace_counts_even_when_stripped_source_fits(self):
        texts = [bounded_text(5999) + " " for _ in range(8)]
        exchanges = [{"role": "assistant", "content": text} for text in texts]
        exchanges.insert(0, {"role": "user", "content": "Remember: Aster uses Qdrant."})
        assert sum(len(m["content"].strip()) for m in exchanges[1:]) <= 48000
        result, sent, callbacks = self.invoke(exchanges)
        self.assert_refused(result, sent, callbacks, "source_transcript_budget_exceeded")

    def test_intentional_last_whole_message_window_and_indexes_preserved(self):
        tail = [{"role": "user", "content": "Remember: Aster uses Qdrant."}]
        tail += [{"role": "assistant", "content": "Ordinary complete context."} for _ in range(31)]
        # An older message is deliberately outside the last-32-message contract.
        exchanges = [{"role": "user", "content": denial_text(6001)}, *tail]
        normalized = self.x._normalize_exchanges(exchanges)
        assert len(normalized) == 32 and [m["message_index"] for m in normalized] == list(range(1, 33))
        assert normalized[0]["content"] == tail[0]["content"]
        result, sent, callbacks = self.invoke(exchanges, enabled=False)
        assert result["extracted"] == len(callbacks) == 1 and sent == []
        evidence = json.loads(callbacks[0][1]["evidence"])
        assert evidence["message_index"] == 1
        receiver, sent = self.invoke(exchanges, caller=True, enabled=False)
        assert len(receiver.callbacks) == 1 and sent == []
        # Actual caller already chooses last 32 raw messages, as before correction.
        assert json.loads(receiver.callbacks[0][1]["evidence"])["message_index"] == 0

    def test_legacy_pairs_event_metadata_and_complete_positive(self):
        exchanges = [{"user": "Remember: Aster uses Qdrant.", "assistant": "Completed Aster tests.",
                      "user_event_at": 1779292800, "assistant_timestamp": 1779292801,
                      "user_event_timezone": "Europe/Moscow"}]
        normalized = self.x._normalize_exchanges(exchanges)
        assert [(m["role"], m["message_index"], m["event_at"]) for m in normalized] == [
            ("user", 0, 1779292800), ("assistant", 1, 1779292801)]
        assert normalized[0]["event_timezone"] == "Europe/Moscow"
        result, sent, callbacks = self.invoke(exchanges, enabled=False)
        assert result["extracted"] == len(callbacks) == 1 and sent == []

    def test_score_known_refusal_is_zero_without_lifecycle_exception(self):
        complete = [{"role": "user", "content": "Remember: Aster uses Qdrant."}]
        assert self.x.extractor_score_session(complete)["total"] > 0
        oversized = [{"role": "user", "content": denial_text(6001)}, *complete]
        transcript = complete + [{"role": "assistant", "content": bounded_text(6000)} for _ in range(8)]
        for exchanges in (oversized, transcript):
            assert self.x.extractor_score_session(exchanges) == {"total": 0.0}
            with patch.object(self.x, "read_extraction_settings", side_effect=AssertionError("routing must not run")):
                result = self.x.extract_session_claims(exchanges)
            assert result["llm_diagnostics"]["outcome"] == "source_refused"
        primary = KeyboardInterrupt("authored cancellation")
        with patch.object(self.x, "_normalize_exchanges", side_effect=primary):
            for target in (self.x.extract_session_claims, self.x.extractor_score_session):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    target(complete)
                assert caught.exception is primary

    def test_actual_source_redactor_and_scan_not_permissive_standins(self):
        assert self.caller["secret_scan"]("password=tiny-secret")["raw_secret"] is True
        assert "tiny-secret" not in self.caller["redact_secrets"]("password=tiny-secret")
        receiver, sent = self.invoke([{"role": "user", "content":
            "Project Aster uses violet channel. password=tiny-secret"}], [self.peer["entry"]()], caller=True)
        assert len(sent) == len(receiver.callbacks) == 1
        assert "tiny-secret" not in sent[0][1][1]["content"]


class LunaF7WitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = globals().get("DEVTOOLS_INPUTS", {})
        if not {"luna_f7_extractor.py", "luna_f7_caller.py"} <= set(inputs):
            raise unittest.SkipTest("immutable f7 SOURCE carriers not supplied")
        LunaSourceScopeTests.setUpClass()
        cls.fixture = LunaSourceScopeTests(methodName="test_original_caps_and_closed_refusal_diagnostics")
        cls.fixture.x, cls.fixture.peer, cls.fixture.home = LunaSourceScopeTests.x, LunaSourceScopeTests.peer, LunaSourceScopeTests.home
        path = Path(inputs["luna_f7_extractor.py"])
        cls.x = types.ModuleType("luna_f7_extractor")
        cls.x.__file__, cls.x.__package__ = str(path), ""
        sys.modules[cls.x.__name__] = cls.x
        exec(compile(read_source(path), str(path), "exec", dont_inherit=True), cls.x.__dict__)
        cls.caller = load_caller(Path(inputs["luna_f7_caller.py"]))

    def test_f7_actual_caller_coercion_is_expected_baseline_violation(self):
        receiver, sent = self.fixture.invoke([{"role": "user", "content": {"attachment": "ordinary attachment body"}}],
                                               caller=True, module=self.x, namespace=self.caller)
        assert len(sent) == 1 and receiver.callbacks == []
        transcript = json.loads(sent[0][1][1]["content"].split("TRANSCRIPT_JSON:\n", 1)[1])
        assert transcript[0]["content"] == "{'attachment': 'ordinary attachment body'}"

    def test_f7_prefix_loss_is_expected_baseline_violation_not_stored_proof(self):
        result, sent, callbacks = self.fixture.invoke([{"role": "user", "content": denial_text(6040)}],
                                                      enabled=False, module=self.x)
        assert result["extracted"] == len(callbacks) == 1 and sent == []
        assert "not really" not in callbacks[0][0] and "Aster uses Qdrant" in callbacks[0][0]
        assert result["persisted"] == 0  # Passive sink never asserts a SQLite write.


def main():
    peer = load_peer()
    # Old controls execute unchanged, not inherited into a silently duplicated suite.
    suites = [("luna.", unittest.defaultTestLoader.loadTestsFromTestCase(peer["LunaBoundaryTests"])),
              ("luna_scope.", unittest.defaultTestLoader.loadTestsFromTestCase(LunaSourceScopeTests))]
    if "luna_f7_extractor.py" in globals().get("DEVTOOLS_INPUTS", {}):
        suites.append(("luna_f7.", unittest.defaultTestLoader.loadTestsFromTestCase(LunaF7WitnessTests)))
    cases = []
    class Result(unittest.TestResult):
        prefix = ""
        def startTest(self, test):
            super().startTest(test)
            if globals().get("devtools_case_started"):
                devtools_case_started(self.prefix + test._testMethodName)
        def addSuccess(self, test):
            super().addSuccess(test)
            cases.append({"id": self.prefix + test._testMethodName, "outcome": "passed"})
        def addFailure(self, test, err):
            super().addFailure(test, err)
            cases.append({"id": self.prefix + test._testMethodName, "outcome": "failed"})
        def addError(self, test, err):
            super().addError(test, err)
            if hasattr(test, "_testMethodName"):
                cases.append({"id": self.prefix + test._testMethodName, "outcome": "error"})
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            cases.append({"id": self.prefix + test._testMethodName, "outcome": "skipped"})
    result = Result()
    for prefix, suite in suites:
        result.prefix = prefix
        suite.run(result)
    for _test, trace in result.failures + result.errors:
        sys.stderr.write(trace + "\n")
    print(json.dumps({"schema": "memory-stack.cases/v1", "cases": cases}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
