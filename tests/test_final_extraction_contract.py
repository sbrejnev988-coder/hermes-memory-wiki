"""ASTUNIT: real lexical/entry closure, not SDK/native/transport/persistence proof.

Q cases retain the approved uses -> uses_provider oracle correction. The new
owner_contract_bare_name_refusal is separate from historical F04 (expected True);
it does not replace that gold or reinterpret the historical failing gate.
Run with ordinary pytest collection and --noconftest for this pure AST seam.
The existing native provider-ownership conftest is preserved, not patched.
"""
from __future__ import annotations

import ast
import builtins
import copy
import datetime as _dt
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = [{'id': 'Q01',
  'component': 'graph',
  'source': 'Nadia uses New SQL for production and Nadia does not use New SQL for development.',
  'quote': 'Nadia uses New SQL for production',
  'actor': 'Nadia',
  'predicate': 'uses_provider',
  'object': 'New SQL for production',
  'expected': True},
 {'id': 'Q02',
  'component': 'session',
  'source': 'I use SQLite in production, but not SQLite in development.',
  'quote': 'I use SQLite in production',
  'claim': 'I use SQLite in production',
  'expected': True},
 {'id': 'Q03',
  'component': 'graph',
  'source': 'Nadia uses New SQL in PRODUCTION, but not New SQL in PRODUCTION.',
  'quote': 'Nadia uses New SQL in PRODUCTION',
  'actor': 'Nadia',
  'predicate': 'uses_provider',
  'object': 'New SQL in PRODUCTION',
  'expected': False},
 {'id': 'Q04',
  'component': 'graph',
  'source': 'Nadia uses New SQL for Production and Boris does not.',
  'quote': 'Nadia uses New SQL for Production',
  'actor': 'Nadia',
  'predicate': 'uses_provider',
  'object': 'New SQL for Production',
  'expected': True},
 {'id': 'Q05',
  'component': 'session',
  'source': 'I use SQLite for production, but I do not use SQLite in ANY WAY.',
  'quote': 'I use SQLite for production',
  'claim': 'I use SQLite for production',
  'expected': False},
 {'id': 'Q06',
  'component': 'graph',
  'source': 'Nadia uses New SQL in production, but maybe not New SQL in production.',
  'quote': 'Nadia uses New SQL in production',
  'actor': 'Nadia',
  'predicate': 'uses_provider',
  'object': 'New SQL in production',
  'expected': False},
 {'id': 'Q07',
  'component': 'session',
  'source': 'I use SQLite for production, but всё-таки нет.',
  'quote': 'I use SQLite for production',
  'claim': 'I use SQLite for production',
  'expected': False},
 {'id': 'Q08',
  'component': 'graph',
  'source': 'Nadia uses Atlas Engine for production, but Nadia does not use Atlas Index for '
            'production.',
  'quote': 'Nadia uses Atlas Engine for production',
  'actor': 'Nadia',
  'predicate': 'uses_provider',
  'object': 'Atlas Engine for production',
  'expected': True},
 {'id': 'Q09',
  'component': 'session',
  'source': 'I use Made in Heaven for production, but I do not use Made in Heaven.',
  'quote': 'I use Made in Heaven for production',
  'claim': 'I use Made in Heaven for production',
  'expected': False},
 {'id': 'Q10',
  'component': 'session',
  'source': 'I use SQLite for production, but ВОЗМОЖНО нет.',
  'quote': 'I use SQLite for production',
  'claim': 'I use SQLite for production',
  'expected': False},
 {'id': 'Q11',
  'component': 'graph',
  'source': 'Nadia uses SQLite for production and Boris does not use SQLite for production.',
  'quote': 'Nadia uses SQLite for production',
  'actor': 'Nadia',
  'predicate': 'uses_provider',
  'object': 'SQLite for production',
  'expected': True},
 {'id': 'Q12',
  'component': 'session',
  'source': 'I use In House DB for production, but I do not use For Work DB for production.',
  'quote': 'I use In House DB for production',
  'claim': 'I use In House DB for production',
  'expected': True},
 {'id': 'GP02',
  'component': 'graph',
  'source': 'Aster runs on Helix but Lyra does not run on Helix at all.',
  'quote': 'Aster runs on Helix',
  'actor': 'Aster',
  'predicate': 'runs_on',
  'object': 'Helix',
  'expected': True},
 {'id': 'GP11',
  'component': 'graph',
  'source': 'Aster runs on Helix but Lyra does not.',
  'quote': 'Aster runs on Helix',
  'actor': 'Aster',
  'predicate': 'runs_on',
  'object': 'Helix',
  'expected': True},
 {'id': 'GN08',
  'component': 'graph',
  'source': 'Aster purportedly runs on Helix.',
  'quote': 'Aster purportedly runs on Helix.',
  'actor': 'Aster',
  'predicate': 'runs_on',
  'object': 'Helix',
  'expected': False},
 {'id': 'SP09',
  'component': 'session',
  'source': 'We use Quartz for production but we do not use Quartz for development.',
  'claim': 'We use Quartz for production.',
  'quote': 'We use Quartz for production',
  'expected': True},
 {'id': 'SP13',
  'component': 'session',
  'source': 'We do not use Birch and we use Quartz for production and we do not use Quartz for '
            'testing.',
  'claim': 'We do not use Birch and we use Quartz for production.',
  'quote': 'We do not use Birch and we use Quartz for production and we do not use Quartz for '
           'testing.',
  'expected': True},
 {'id': 'SN05',
  'component': 'session',
  'source': 'We use Quartz for production but not Quartz for production.',
  'claim': 'We use Quartz for production.',
  'quote': 'We use Quartz for production',
  'expected': False},
 {'id': 'SN12',
  'component': 'session',
  'source': 'We use Quartz for production but not Quartz anymore.',
  'claim': 'We use Quartz for production.',
  'quote': 'We use Quartz for production',
  'expected': False},
 {'id': 'F03',
  'component': 'graph',
  'source': 'Aster runs on HELIX CLUSTER but Aster does not run on HELIX.',
  'quote': 'Aster runs on HELIX CLUSTER',
  'actor': 'Aster',
  'predicate': 'runs_on',
  'object': 'HELIX CLUSTER',
  'expected': True},
 {'id': 'owner_contract_bare_name_refusal',
  'component': 'graph',
  'source': 'Aster работает на Helix, но Lyra нет.',
  'quote': 'Aster работает на Helix',
  'actor': 'Aster',
  'predicate': 'runs_on',
  'object': 'Helix',
  'expected': False}]


def _actual_namespace():
    """Select the dependency-closed pure AST from repo-relative actual files."""
    ordered, definitions = [], {}
    for filename in ("extractor.py", "entity_relation_extractor.py"):
        tree = ast.parse((ROOT / filename).read_bytes().decode("utf-8-sig"))
        for node in tree.body:
            names = ([node.name] if isinstance(node, ast.FunctionDef) else
                     [target.id for target in node.targets if isinstance(target, ast.Name)]
                     if isinstance(node, ast.Assign) else [])
            ordered.append((node, names))
            for name in names:
                assert name not in definitions, name
                definitions[name] = node
    required = {"_grounded_relation_clause", "_normalize_llm_entry", "_claim_supported"}
    queue = list(required)
    while queue:
        for node in ast.walk(definitions[queue.pop()]):
            if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                    and node.id in definitions and node.id not in required):
                required.add(node.id)
                queue.append(node.id)
    nodes = [node for node, names in ordered if required.intersection(names)]
    forbidden = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    for root in nodes:
        for node in ast.walk(root):
            assert not isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef,
                                         ast.Global, ast.Nonlocal))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden
            if isinstance(node, ast.Attribute):
                assert not node.attr.startswith("__")
                assert node.attr not in {"read_bytes", "write_bytes", "read_text",
                                         "write_text", "unlink", "rmdir", "mkdir",
                                         "connect", "system", "environ"}
    namespace = dict(re=re, _dt=_dt, Any=Any, Callable=Callable, Dict=Dict,
                     Iterable=Iterable, List=List, Optional=Optional, Tuple=Tuple)
    namespace["__builtins__"] = {name: value for name, value in vars(builtins).items()
                                  if name not in forbidden}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<repo-actual-pure-closure>",
                 "exec"), namespace)
    return namespace


def _source_entry(source, quote, claim):
    message = dict(role="user", content=source, message_index=0,
                   event_at=1234, event_timezone="UTC")
    entry = dict(claim=claim, type="fact", topic="database", evidence_quote=quote,
                 speaker="user", message_index=0, event_at="", confidence=0.9)
    return message, entry


@pytest.fixture(scope="module")
def actual_boundary():
    namespace = _actual_namespace()
    normalize = namespace["_normalize_llm_entry"]
    text = "We use Quartz for production."
    message, entry = _source_entry(text, text, text)
    original = copy.deepcopy((message, entry))
    result = normalize(entry, {0: message}, reject_secret_material=True)
    assert result is not None
    assert (result["evidence_quote"], result["speaker"], result["message_index"],
            result["event_at"], result["event_timezone"]) == (text, "user", 0, 1234, "UTC")
    for update in ({"speaker": "assistant"}, {"message_index": 1},
                   {"message_index": True}, {"type": "unsupported"},
                   {"evidence_quote": "We use Ember for production."},
                   {"extra_field": "not admitted"}):
        assert normalize(dict(entry, **update), {0: message},
                         reject_secret_material=True) is None
    # Unquoted semantic timestamps cannot replace trusted source event metadata.
    spoofed = normalize(dict(entry, event_at="1700000000"), {0: message},
                        reject_secret_material=True)
    assert spoofed is not None and spoofed["event_at"] == 1234
    assert not namespace["_claim_supported"]("Bob paid Alice.", "Alice paid Bob.")
    assert not namespace["_claim_supported"]("We use Quartz.", "We do not use Quartz.")
    assert (message, entry) == original
    assert set(namespace["_PREDICATE_CUES"]) == {
        "owns", "owned_by", "runs_on", "hosts", "depends_on", "required_by",
        "uses_provider", "authenticated_by", "replaces", "replaced_by",
        "valid_until", "supports", "contradicts",
    }
    grounded = namespace["_grounded_relation_clause"]
    assert not grounded("Aster", "uses", "Helix", "Aster uses Helix.")
    assert not grounded("Helix", "runs_on", "Aster", "Aster runs on Helix.")
    return namespace


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_final_extraction_contract(case, actual_boundary):
    before = copy.deepcopy(case)
    assert case["quote"] in case["source"]
    if case["component"] == "graph":
        cues = actual_boundary["_PREDICATE_CUES"]
        assert case["predicate"] in cues
        assert any(re.search(cue, case["quote"], re.I)
                   for cue in cues[case["predicate"]])
        assert all(re.search(r"(?<!\w)" + re.escape(case[key]) + r"(?!\w)",
                             case["quote"], re.I) for key in ("actor", "object"))
        accepted = actual_boundary["_grounded_relation_clause"](
            case["actor"], case["predicate"], case["object"], case["quote"],
            source=case["source"])
    else:
        message, entry = _source_entry(case["source"], case["quote"], case["claim"])
        originals = copy.deepcopy((message, entry))
        result = actual_boundary["_normalize_llm_entry"](
            entry, {0: message}, reject_secret_material=True)
        assert (message, entry) == originals
        accepted = result is not None
        if accepted:
            assert (result["evidence_quote"], result["speaker"],
                    result["message_index"], result["event_at"],
                    result["event_timezone"]) == (case["quote"], "user", 0, 1234, "UTC")
            assert result["claim"].endswith(case["claim"])
    assert case == before
    assert accepted is case["expected"]
