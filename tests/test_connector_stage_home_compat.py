"""R3-SOURCE-L1: legacy home-less callers, not a managed-cache capability.

Reuse the shipped standalone SOURCE fixture and real secure .txt extraction.
No SDK/trust stand-ins, native parser worker, transport or live profile files.
The three unchanged legacy callers run separately; their parsers are synthetic.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'connector_home_existing_stage', Path(__file__).with_name('test_connector_stage_admission.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
stage = peer.stage
SCOPE = peer.SCOPE


class HomeLessProvider:
    """The legacy _connect/project_scope/bot_id protocol, with NO home."""
    def __init__(self, store):
        self.conn = store.db
        self.project_scope = store.p.project_scope
        self.bot_id = store.p.bot_id

    def _connect(self):
        return self.conn


@pytest.mark.parametrize('committed', [False, True])
def test_missing_home_classifies_but_never_admits_managed_generation(stage, committed):
    s = stage
    if committed:
        s.upsert()
        s.coherent(s.path(), s.record())  # Genuine committed producer, no SQL forgery.
    path = s.path()
    if not committed:
        path.write_text(peer.B, encoding='utf-8')
    provider = HomeLessProvider(s)
    assert not hasattr(provider, 'home')
    assert s.g._managed_connector_cache_root(provider) == path.parent
    before, decoded, changes = s.durable(), len(s.decodes), s.db.total_changes
    raw = path.read_bytes()
    args = dict(path=str(path), scope_id=SCOPE, repository_id=SCOPE, embed=False)
    with pytest.raises(PermissionError, match='^document_managed_connector_home_required$'):
        s.g.ingest_document(provider, args)
    # A supplied hook cannot turn the classification fallback into a grant,
    # either. The public path still validates hook identity before dispatch.
    with pytest.raises(PermissionError, match='^document_managed_connector_home_required$'):
        s.g._managed_connector_admission(provider, s.db, path, s.g._source_id(path),
                                        SCOPE, SCOPE, hashlib.sha256(raw).hexdigest(), object())
    assert s.durable() == before and s.db.total_changes == changes
    assert len(s.decodes) == decoded and path.read_bytes() == raw
    assert s.p._claim_tx_document_stage is None and s.p._transaction_quarantine is None
    s.witness('missing_home_denied', committed=committed, canonical_unchanged=True,
              decode_delta=0, SQL_write_delta=0, cache_unchanged=True)

    # Fallback still excludes the reserved subtree BEFORE max_files, without
    # broadening the ordinary attachment root or changing a legacy receiver.
    attachment = path.parent.parent / 'attachments/connectors/ordinary.txt'
    attachment.parent.mkdir(parents=True)
    attachment.write_text(peer.A, encoding='utf-8')
    # A genuine ordinary standalone handle, not a provider-owned connection
    # whose native owner lifetime would be missing from this legacy receiver.
    with closing(sqlite3.connect(str(s.p.db_path), timeout=0)) as legacy_db:
        legacy_db.row_factory = sqlite3.Row
        provider.conn = legacy_db
        scan = s.g.scan_documents(provider, dict(root=str(path.parent.parent), max_files=1,
                                                scope_id=SCOPE, repository_id=SCOPE, embed=False))
    assert scan['discovered'] == scan['indexed'] == 1 and scan['failed'] == 0
    assert scan['results'][0]['source_id'] == s.g._source_id(attachment)
    assert len(s.decodes) == decoded + 1 and path.read_bytes() == raw
    if committed:
        s.coherent(path, s.record())
    else:
        assert s.tuple(path)['source'] is None


def test_explicit_home_wins_and_original_admission_rejects_late_home_loss(stage, monkeypatch):
    s = stage
    home = s.p.home
    root = home / 'cache/documents/connectors'
    # Explicit home is authoritative even under a different profile fallback.
    foreign = s.root / 'different-fallback'
    foreign.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(foreign))
    with s.g._document_profile_scope(foreign):
        assert s.g._hermes_home() == foreign
        assert s.g._managed_connector_cache_root(s.p) == root
    monkeypatch.setenv('HERMES_HOME', str(home))
    assert s.g._hermes_home() == home
    result = s.upsert()
    path = s.path()
    s.coherent(path, s.record())
    reference = s.g._document_source_recovery_reference(s.p, result['source_id'], action='ingest')
    assert s.g._replay_document_source_reference(s.p, reference)['status'] == 'restored'
    s.coherent(path, s.record())
    before = s.durable()
    seen = []
    journal = s.p._claim_journal_pending_commit

    def lose_home(conn):
        value = journal(conn)
        owning = s.p._claim_tx_document_stage
        if owning[2]:
            assert owning[0] is s.db and len(owning[2][0][1]) == 7
            seen.append(owning)
            del s.p.home
            # The fallback is IDENTICAL to the original root. Root equality
            # alone must not silently rebase this original managed admission.
            assert s.g._managed_connector_cache_root(s.p) == root
        return value

    monkeypatch.setattr(s.p, '_claim_journal_pending_commit', lose_home)
    try:
        with pytest.raises(PermissionError, match='^document_managed_connector_home_changed$'):
            with s.p._claim_transaction(s.db):
                assert s.ingest(path)['status'] == 'unchanged'
        assert seen and not hasattr(s.p, 'home')
        assert not s.db.in_transaction and s.p._claim_tx_document_stage is None
        assert s.p._transaction_quarantine is None and s.durable() == before
        s.witness('late_home_loss_owning_journal_denied', original_stage_observed=True,
                  fallback_root_equal=True, rollback_confirmed=True, canonical_unchanged=True)
    finally:
        # Restore only this test-owned attribute AFTER observing the refusal;
        # this is fixture disposal, not an admission retry or quarantine reset.
        s.p.home = home
