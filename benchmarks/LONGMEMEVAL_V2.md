# LongMemEval-V2: text retrieval probe

Primary sources: [official code and evaluation harness](https://github.com/xiaowu0162/LongMemEval-V2), [official dataset schema](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2/raw/main/SCHEMA.md), [official dataset](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2). Code revision inspected: `2cc8c540bdb87fe6761629b585e727e1c4704520`; dataset revision: `f152293e235517d504809563c833d7190b8c713b` (20 September 2026).

V2 has 451 questions (240 web, 211 enterprise) and two public tiers. Every small-tier question maps to 100 trajectories; questions within a domain share a haystack. The dataset has 29 image questions and screenshot paths in the trajectories. The official harness inserts full trajectories, passes a text or image query to a memory backend, generates answers with a reader, judges the answers, and evaluates accuracy and latency. Public question records do **not** contain gold trajectory or state evidence IDs.

`longmemeval_v2_adapter.py` streams the JSONL trajectory file, indexes accessibility-tree text, goals, URLs, actions and thoughts as bounded SQLite FTS excerpts in a fresh `HERMES_HOME`, then measures Memory Wiki `_search(..., retrieval_mode="fts")`. It verifies official checksums when available. It never uses the live profile, Qdrant, OpenRouter or a Qdrant alias. It leaves its isolated database under the reported temporary path for inspection. It bypasses automatic memory extraction, and does not process screenshot pixels. The normal mode requires every selected haystack trajectory and the official trajectory checksum. `--allow-partial` permits an interrupted JSONL prefix for a diagnostic only and reports both missing trajectories and checksum mismatch.

## Reproduce

Download official data with the [official instructions](https://github.com/xiaowu0162/LongMemEval-V2/#setup-data), then run:

```powershell
python benchmarks/longmemeval_v2_adapter.py --data-root C:\path\to\longmemeval-v2 --tier small --domain enterprise --limit 20 --top-k 5 --output C:\path\to\v2-results.json
python -m pytest -q tests/test_longmemeval_v2_adapter.py
```

The full text-only small-tier run requires both domains separately and the complete 1.2 GB trajectory JSONL. The official QA/LAFS run additionally requires the official reader/judge and image assets; this adapter does not claim to reproduce that score.

## Diagnostic run on official rows

A local partial diagnostic was intentionally not versioned: it used an interrupted prefix of `trajectories.jsonl` that did not match the full-file checksum. It is not a release benchmark or evidence of answer accuracy or evidence recall. Run the command above against complete checksum-verified inputs before publishing a result, together with its runner command, source revision, environment manifest, and dataset checksum.

## Relation to the other adapters

| Adapter | Source | Ground truth available | What the local probe measures |
| --- | --- | --- | --- |
| `longmemeval_adapter.py` | 500 question chat-history LongMemEval | Gold session IDs and annotated answer turns | Session/turn evidence recall, latency, optional answer proxy |
| `locomo_adapter.py` | 10 LoCoMo dialogues | Gold dialogue evidence IDs | Evidence recall, MRR, latency |
| `longmemeval_v2_adapter.py` | 451 question web-agent LongMemEval-V2 | Answer, evaluator specification; **no gold evidence IDs** | Text index coverage and query latency only |

The V2 probe surfaces the product's current gaps: text-only processing, bounded state truncation, slow FTS over raw state excerpts, and retrieval concentration in one trajectory. A full V2 quality claim would require a true multimodal Memory backend run through the official reader/judge on complete small and medium haystacks; the public release is roughly 7 GB and the largest haystacks reach 115 million tokens, so that is a separate resource-intensive evaluation.
