# Paired live hybrid vs FTS-only LongMemEval oracle probe

`paired_hybrid_fts.py` selected five questions from each of the six official
LongMemEval oracle question types using seed `20260920` (30 total). The dataset
SHA-256 was `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c`.
Each case was ingested into two separate temporary Hermes homes with the same
claim quality policy. FTS-only used no embedding service. Hybrid used the
configured OpenRouter `qwen/qwen3-embedding-8b` model and Qdrant. Search was
top-5 in both modes. The production database and active Qdrant alias were not
modified. Every hybrid case created a random physical collection, checked that
the name did not pre-exist, and verified its removal. A final Qdrant listing
found **zero** collections bearing this run's random prefix.

| Metric | FTS-only | OpenRouter + Qdrant hybrid |
| --- | ---: | ---: |
| Cases completed / errors | 30 / 0 | 30 / 0 |
| Evidence-scored cases | 27 | 27 |
| All gold sessions in top 5 | 0.7037 | 0.7407 |
| Any gold session in top 5 | 1.0000 | 1.0000 |
| Session MRR@5 | 1.0000 | 1.0000 |
| All gold turns in top 5 | 0.3704 | 0.3704 |
| Search p50 / p95 | 20.66 / 47.21 ms | 1953.60 / 8548.41 ms |
| Accepted / queued / skipped turns | 429 / 250 / 0 | 429 / 250 / 0 |

Ingestion counts matched in all 30 pairs. Hybrid improved all-session recall
in one `multi-session` case and worsened none, a small difference on this sample.
For all five `single-session-assistant`, `single-session-preference`, and
`single-session-user` cases, both modes found the gold session. The weak area
is multi-session retrieval: FTS found all gold sessions in 0/4 scored cases,
hybrid in 1/4. Three abstention cases do not enter evidence metrics.

Hybrid performed 424 measured embedding calls on 208,468 input characters.
The plugin's embedding client does not expose response token usage or billed
cost, so neither can be reported reliably. Synchronous semantic reindex took
936,385 ms in total across the 30 temporary cases; search latency above
excludes indexing. The measured embedding characters include both indexing
and query requests. This benchmark measures evidence retrieval only; it does
not measure official answer quality. Raw turns were passed through production
claim quality checks, which queued 250 turns. Queued turns were not searchable.

Reproduce with an official local oracle JSON and a local environment file
containing OpenRouter embedding and Qdrant settings:

```powershell
python benchmarks/paired_hybrid_fts.py --dataset <longmemeval_oracle.json> --env-file <hermes.env> --output benchmarks/paired_hybrid_fts_results.json
```

The detailed results contain question IDs and metrics without conversation
text, keys, or answers: `paired_hybrid_fts_results.json`. Adapter tests:
`python -m pytest tests/test_longmemeval_adapter.py -q` → 8 passed.
