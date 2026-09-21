"""Validate and summarize output from LongMemEval's official evaluate_qa.py.

This parser makes no model calls. It binds every judged hypothesis to the
Memory Wiki run and rejects missing, duplicate, edited, or unexpected rows.
The official judge's API cost is outside the reader budget and is not known.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def summarize(report_path: Path, judge_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("questions"), list):
        raise ValueError("invalid Memory Wiki answer report")
    if not isinstance(report.get("dataset_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", report["dataset_sha256"]):
        raise ValueError("invalid dataset SHA-256 in Memory Wiki report")
    expected: dict[str, dict[str, Any]] = {}
    all_ids: set[str] = set()
    for row in report["questions"]:
        if not isinstance(row, dict):
            raise ValueError("invalid Memory Wiki question")
        question_id, hypothesis = row.get("question_id"), row.get("hypothesis")
        if not isinstance(question_id, str) or question_id in all_ids:
            raise ValueError("duplicate or invalid Memory Wiki question ID")
        all_ids.add(question_id)
        if isinstance(hypothesis, str):
            expected[question_id] = row
    if not expected:
        raise ValueError("report has no generated hypotheses")
    seen: set[str] = set()
    model: str | None = None
    by_type: dict[str, list[bool]] = {}
    abstention: list[bool] = []
    with judge_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"invalid official judge row {line_number}")
            question_id = item.get("question_id")
            if not isinstance(question_id, str) or question_id not in expected or question_id in seen:
                raise ValueError(f"unknown or duplicate official judge row {line_number}")
            if item.get("hypothesis") != expected[question_id]["hypothesis"]:
                raise ValueError(f"edited hypothesis in official judge row {line_number}")
            verdict = item.get("autoeval_label")
            if not isinstance(verdict, dict) or not isinstance(verdict.get("label"), bool) or not isinstance(verdict.get("model"), str):
                raise ValueError(f"invalid official judge label in row {line_number}")
            if model is None:
                model = verdict["model"]
            elif model != verdict["model"]:
                raise ValueError("official judge models differ across rows")
            label = verdict["label"]
            by_type.setdefault(str(expected[question_id]["question_type"]), []).append(label)
            if question_id.endswith("_abs"):
                abstention.append(label)
            seen.add(question_id)
    if seen != set(expected):
        raise ValueError("official judge rows do not cover all generated hypotheses")
    labels = [label for values in by_type.values() for label in values]
    evaluated = report.get("evaluated_questions")
    if isinstance(evaluated, bool) or not isinstance(evaluated, int) or evaluated < len(expected):
        raise ValueError("invalid evaluated question count")
    return {
        "benchmark": "LongMemEval official QA judge result for Memory Wiki hypotheses",
        "dataset_sha256": report.get("dataset_sha256"),
        "reader_model": report.get("answer_model"),
        "official_judge_model": model,
        "evaluated_questions": evaluated,
        "generated_hypotheses": len(expected),
        "judged_hypotheses": len(labels),
        "qa_accuracy_on_judged": round(sum(labels) / len(labels), 4),
        "qa_accuracy_full_run": round(sum(labels) / evaluated, 4) if evaluated == len(labels) else None,
        "abstention_questions_judged": len(abstention),
        "abstention_accuracy_on_judged": round(sum(abstention) / len(abstention), 4) if abstention else None,
        "by_question_type": {
            kind: {"n": len(values), "accuracy": round(sum(values) / len(values), 4)}
            for kind, values in sorted(by_type.items())
        },
        "judge_cost_usd": None,
        "judge_cost_note": "The official script does not report token usage or cost.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--official-results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.report, args.official_results)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        if args.output.resolve() in {args.report.resolve(), args.official_results.resolve()}:
            parser.error("--output must differ from the input files")
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
