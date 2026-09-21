"""Scale harness exercises a real isolated ledger and discards the database."""

from __future__ import annotations

from benchmarks.scale_event_ledger import run


def test_scale_probe_cold_start_retention_fts_and_privacy(tmp_path):
    result = run(rows=1050, batch_size=137, repetitions=1,
                 directory=tmp_path, progress_every=0)
    assert result["rows"] == 1050
    assert result["quick_check"] == "ok"
    assert result["privacy_rows_erased"] == 1000
    assert result["retained_rows"] == 50
    assert result["query"]["rare"]["p50_ms"] >= 0
    assert result["storage_after_checkpoint_bytes"]["wal"] == 0
    assert not list(tmp_path.iterdir())
