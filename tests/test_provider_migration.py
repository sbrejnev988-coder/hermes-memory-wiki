"""Provider migration regressions on real owned SPI/SQL/Qdrant resources."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

_SPEC = importlib.util.spec_from_file_location(
    '_provider_migration_fixture', Path(__file__).with_name('ci_owned') / 'provider_migration_fixture.py')
_fixture = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _fixture
_SPEC.loader.exec_module(_fixture)
provider_migration_case = _fixture.provider_migration_case


def test_nous_openrouter_mixed_scope_baseline_explains_legacy_refusals(provider_migration_case):
    f = provider_migration_case
    assert f.old_hash != f.new_hash
    assert f.m._embedding_manifest()['provider'] == 'openrouter'
    assert f.m._qdrant_count(f.old_target) == 4
    assert f.alias() == f.old_target
    before = f.a._compare_search('migration receiver calibration', limit=5)
    assert before['fts_only'] and before['vector_only'] == []
    preview = f.public(current_scope_only=True, dry_run=True, limit=2)
    assert preview['status'] == 'refused'
    assert preview['error'] == 'scope_active_target_not_owned_or_compatible'
    assert f.foreign_text not in json.dumps(preview)
    sql = []
    conn = f.a._connect()
    conn.set_trace_callback(sql.append)
    try:
        legacy = f.public(force=True, limit=4)
    finally:
        conn.set_trace_callback(None)
    assert legacy['status'] == 'partial' and legacy['alias_switched'] is False
    assert legacy['failed'] == 2
    assert f.alias() == f.old_target and f.old_unchanged()
    assert set(legacy['failed_ids']) == {f.ids['b_private'], f.ids['b_chat']}
    assert f.embedding_posts and all(item['provider'] == 'openrouter' for item in f.embedding_posts)
    assert all(f.foreign_text not in item['input'] for item in f.embedding_posts)
    # The foreign branch could not find new-manifest registered vectors. No
    # widening of claim visibility or reading foreign SQL text is an acceptable fix.
    reads = [s for s in sql if 'SELECT normalized_claim FROM claims' in s]
    assert reads and all(f.ids['b_private'] not in s and f.ids['b_chat'] not in s for s in reads)
