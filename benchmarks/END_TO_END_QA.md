# Public benchmark QA protocol

These runners use an isolated temporary Hermes home. Their retrieval calls are
Memory Wiki's production `_search` path. LongMemEval writes conversation turns
through the normal claim quality policy; LoCoMo inserts bounded raw dialogue
turns into the claim table, then calls the same production search. Neither run
reads a live profile. The reader sees only retrieved public benchmark text.

## LongMemEval

Use a local copy of an [official LongMemEval dataset](https://github.com/xiaowu0162/LongMemEval#data).
Pin and record its SHA-256. The adapter includes the dataset SHA-256, model,
retrieval mode, request budget, per-answer usage, cost, and latency in its JSON
report. Example for a *small* diagnostic run:

```powershell
python benchmarks/longmemeval_adapter.py --dataset C:\benchmarks\longmemeval_s_cleaned.json --limit 5 --top-k 8 --answer-model openai/gpt-4.1-mini --env-file C:\private\hermes-benchmark.env --answer-request-budget 5 --answer-max-tokens 160 --answer-context-chars 6000 --output C:\benchmarks\memory-wiki-lme-report.json --hypotheses-out C:\benchmarks\memory-wiki-lme-hypotheses.jsonl
```

For a publishable answer score, run all 500 questions with the chosen
retrieval mode and identical reader prompt/model/budget across comparator
systems. The default above is offline FTS; `--semantic` makes live embedding
requests and uses an isolated Qdrant physical collection per question. Confirm
`isolated_collections_removed=true` after semantic runs. Record embedding
usage and costs separately: the plugin embedding client does not currently
return them, so **the report's answer cost is not total system cost**.

To test the production episode fallback and claim search together, run the
paired probe's optional reader. It uses the same retrieved evidence that its
offline recall measurement scores, with a fixed total of `top-k` claim and
episode slots. Its source-tree digest fails the run if code changes while the
reader is running:

```powershell
python benchmarks/full_oracle_episode_probe.py --dataset C:\benchmarks\longmemeval_oracle.json --limit 5 --top-k 8 --episode-slots 5 --answer-model openai/gpt-4.1-mini --env-file C:\private\hermes-benchmark.env --answer-request-budget 5 --answer-max-tokens 160 --answer-context-chars 6000 --output C:\benchmarks\memory-wiki-episode-qa.json --hypotheses-out C:\benchmarks\memory-wiki-episode-qa.jsonl
```

Only the public benchmark question and the production tool's guarded claim
and episode excerpts go to the reader; its answer has no access to reference
answers. The `answer_evaluation` section labels the result as unjudged and
reports coverage, errors, usage, latency, and a normalized exact-match proxy.
Use the official judge separately for a comparable answer-quality score. The
offline evidence probe's original output is unchanged when `--answer-model`
is omitted; its provenance manifest applies only to that offline result.

The report's `answer_proxy_exact_match` is a stringent local text check, not
the official LongMemEval score. The official repository's
[`evaluate_qa.py`](https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py)
accepts the emitted `question_id`/`hypothesis` JSONL. It uses a separate
OpenAI judge credential and charges separately. Run the judge in a separately
prepared official environment, then bind its results to this run:

```powershell
python C:\benchmarks\LongMemEval\src\evaluation\evaluate_qa.py gpt-4o C:\benchmarks\memory-wiki-lme-hypotheses.jsonl C:\benchmarks\longmemeval_s_cleaned.json
python benchmarks/official_longmemeval_judge.py --report C:\benchmarks\memory-wiki-lme-report.json --official-results C:\benchmarks\memory-wiki-lme-hypotheses.jsonl.eval-results-gpt-4o --output C:\benchmarks\memory-wiki-lme-official-score.json
```

The verifier rejects duplicate, edited, missing, and unexpected hypotheses.
It reports full-run accuracy only if every evaluated question has a judged
answer. The official judge script does not return its usage/cost, so that
expense remains `null` in the merged report.

## LoCoMo

The LoCoMo adapter accepts a local official JSON file or downloads one pinned
official revision with checksum verification. It scores evidence retrieval and
can now generate reader answers with the same request and context bounds:

```powershell
python benchmarks/locomo_adapter.py --download-official --max-conversations 1 --questions-per-conversation 5 --top-k 8 --answer-model openai/gpt-4.1-mini --env-file C:\private\hermes-benchmark.env --answer-request-budget 5 --answer-max-tokens 160 --answer-context-chars 6000 --output C:\benchmarks\memory-wiki-locomo-report.json
```

This report contains generated hypotheses, evidence recall, latency, usage,
and cost. It does **not** call those hypotheses official LoCoMo QA accuracy.
The LoCoMo reader uses `No information available` for unsupported questions,
because the official category-5 evaluator recognizes that phrase. It applies
the same instruction to every question and does not expose answer categories
or references to the reader.
For comparable QA scoring, apply the pinned [official LoCoMo evaluation
function](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py)
to each original `qa` entry with its generated `hypothesis` assigned to the
evaluator's `prediction` key. The official evaluator uses category-specific
metrics; a generic exact match or token F1 cannot replace it. Preserve its
source commit, dependency versions, and result alongside the Memory Wiki
report.

## Budget and interpretation

- `--answer-request-budget` is a hard maximum on attempted reader calls, even
  when a request fails. Each request also has a completion-token cap and an
  exact character cap on supplied evidence. The question itself is capped at
  2,000 characters.
- `--answer-cost-soft-cap-usd` stops **later** calls once OpenRouter reports
  the cap was reached. The current request can overshoot it, so this is not a
  hard dollar ceiling. If cost is omitted or a request fails, cost becomes
  unknown and later calls stop when this cap was requested.
- A total token or dollar figure is `null` unless every successful reader
  response supplies that field. Failed requests and embedding calls make
  total system cost unknown. A measured zero is never substituted for missing
  usage.
- `answer_abstention_heuristic` is a phrase detector, not an official judge.
  Report answer coverage and errors next to any score. A five-question sample
  is a smoke test; it cannot support a market ranking.
- The LongMemEval and LoCoMo adapters use different ingest paths and gold
  evidence conventions. Compare systems only within the same dataset,
  release, history size, retrieval budget, reader, judge, and coverage rules.

Never put credentials into CLI flags, benchmark output, or a committed file.
Use an existing private dotenv file only for the explicit reader run.
