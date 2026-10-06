"""ASTUNIT: actual repo-relative intent/expansion rules, not native recall proof.

Retain the same nine root-context questions and two earlier measurement controls.
No package initialization, SDK replacement, model response or database fixture.
Use ordinary pytest collection with --noconftest for this pure AST seam only.
"""
from __future__ import annotations

import ast
import builtins
import copy
from datetime import date
from pathlib import Path
import re
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = [{'id': 'C01', 'question': 'Архив после 2024-03-01, 2/3 часа обработки', 'expected_temporal': True},
 {'id': 'C02', 'question': 'Архив с 09.10 и 2 сообщения', 'expected_temporal': True},
 {'id': 'C03', 'question': 'Архив с 2023 г, 2 г образца', 'expected_temporal': True},
 {'id': 'C04', 'question': 'Длина со 3/8, 2 аршина', 'expected_temporal': False},
 {'id': 'C05', 'question': 'Масса с 4/9 и 3 унции', 'expected_temporal': False},
 {'id': 'C06', 'question': 'Смесь с 3 г; 2 г муки', 'expected_temporal': False},
 {'id': 'C07', 'question': 'Архив до следующей весны, 2 часа сверки', 'expected_temporal': True},
 {'id': 'C08', 'question': 'Архив после 30.02.2024, 2 файла', 'expected_temporal': False},
 {'id': 'C09', 'question': 'Архив с 7/8 и 3 сообщения', 'expected_temporal': True},
 {'id': 'grams_year_alias',
  'question': 'Помнишь смесь с 1.5 г,2 г соли?',
  'expected_temporal': False},
 {'id': 'unlisted_measurement',
  'question': 'Помнишь размер с 1.5, 2 дюйма?',
  'expected_temporal': False}]


@pytest.fixture(scope="module")
def actual_planner():
    tree = ast.parse((ROOT / "recall_planner.py").read_bytes().decode("utf-8-sig"))
    # This complete pure module uses only stdlib imports. Supply those exact
    # dependencies explicitly; do not execute plugin/package initialization.
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert {alias.name for alias in node.names} == {"re"}
        elif isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "datetime", "typing"}
    nodes = [node for node in tree.body
             if not isinstance(node, (ast.Import, ast.ImportFrom))]
    forbidden = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    for root in nodes:
        for node in ast.walk(root):
            assert not isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef,
                                         ast.Global, ast.Nonlocal))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden
            if isinstance(node, ast.Attribute):
                assert not node.attr.startswith("__")
                assert node.attr not in {"connect", "system", "environ", "read_text", "write_text"}
    namespace = dict(re=re, date=date, Any=Any)
    namespace["__builtins__"] = {name: value for name, value in vars(builtins).items()
                                  if name not in forbidden}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<repo-actual-intent-rules>",
                 "exec"), namespace)
    return namespace


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_final_calendar_intent(case, actual_planner):
    before = copy.deepcopy(case)
    intent = actual_planner["classify_memory_intent"](case["question"])
    assert intent["temporal"] is case["expected_temporal"]
    assert set(intent) == {"primary", "temporal", "current_state", "multi_hop",
                           "preference", "procedural", "negative_premise", "deep_recommended"}
    cleaned = re.sub(r"\s+", " ", case["question"]).strip(" \t\r\n,.;:!?-")[:500]
    assert actual_planner["expand_memory_queries"](case["question"], "fast") == [cleaned]
    assert case == before
