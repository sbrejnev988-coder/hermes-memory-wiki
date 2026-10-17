"""Own standalone cold schema preparation, never a caller's pending SQL.

SOURCE only: reuse the existing genuine standalone fixture and secure text
extractor. Test-owned disposal after UNKNOWN witnesses is not recovery proof.
"""
from __future__ import annotations

from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'connector_schema_existing_stage', Path(__file__).with_name('test_connector_stage_admission.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
stage = peer.stage
SCOPE = peer.SCOPE


class LegacyProvider:
    """The existing home-less, owner-less standalone protocol."""
    def __init__(self, conn, bot_id):
        self.conn = conn
        self.bot_id = bot_id
        self.project_scope = SCOPE

    def _connect(self):
        return self.conn


def ordinary_path(store):
    path = store.p.home / 'cache/documents/attachments/schema-owner.txt'
    path.parent.mkdir(parents=True)
    path.write_text(peer.A, encoding='utf-8')
    return path


def ingest(store, provider, path):
    return store.g.ingest_document(provider, dict(
        path=str(path), scope_id=SCOPE, repository_id=SCOPE, embed=False))


def test_pending_caller_is_not_schema_owner_and_clean_retry_enables_FK(stage):
    s = stage
    path = ordinary_path(s)
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.row_factory = sqlite3.Row
        provider = LegacyProvider(conn, s.p.bot_id)
        assert not hasattr(provider, 'home') and not hasattr(provider, '_claim_transaction')
        conn.execute('CREATE TABLE caller_payload(value TEXT)')
        conn.execute('INSERT INTO caller_payload VALUES(?)', ('uncommitted caller row',))
        assert conn.in_transaction and conn.execute('PRAGMA foreign_keys').fetchone()[0] == 0
        before, decoded = conn.total_changes, len(s.decodes)
        with pytest.raises(RuntimeError, match='^document_transaction_requires_idle_owner$'):
            ingest(s, provider, path)
        assert conn.in_transaction and conn.total_changes == before
        assert conn.execute('SELECT value FROM caller_payload').fetchall()[0][0] == 'uncommitted caller row'
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'document_%'").fetchall() == []
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 0
        assert len(s.decodes) == decoded
        # Only this caller ends its own transaction. Production never adopts it.
        conn.rollback()
        result = ingest(s, provider, path)
        assert result['status'] == 'indexed' and not conn.in_transaction
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('SELECT source_id FROM document_sources').fetchone()[0] == result['source_id']
        assert ingest(s, provider, path)['status'] == 'unchanged' and not conn.in_transaction
        s.witness('standalone_schema_pending_refused_then_healthy', foreign_keys=1,
                  pending_caller_preserved=True, no_home_or_owner_added=True)


@pytest.mark.parametrize('rollback_unknown', [False, True])
def test_schema_failure_keeps_primary_and_its_actual_owned_transaction(stage, monkeypatch, rollback_unknown):
    s = stage
    path = ordinary_path(s)
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.row_factory = sqlite3.Row
        provider = LegacyProvider(conn, s.p.bot_id)
        primary = RuntimeError('SOURCE owned schema preparation failure')
        original = s.g.install_document_graph_schema
        reached = []

        def fail_after_real_schema(handle):
            assert handle is conn and handle.in_transaction
            original(handle)
            assert handle.execute('PRAGMA foreign_keys').fetchone()[0] == 1
            reached.append('real_schema')
            raise primary

        if rollback_unknown:
            def authorizer(action, first, second, database, trigger):
                if action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorizer)
        try:
            with monkeypatch.context() as local:
                local.setattr(s.g, 'install_document_graph_schema', fail_after_real_schema)
                with pytest.raises(RuntimeError) as captured:
                    ingest(s, provider, path)
            assert captured.value is primary and reached == ['real_schema']
            assert provider._connect() is conn and not s.decodes
            if rollback_unknown:
                assert conn.in_transaction
                assert any('UNKNOWN' in note for note in getattr(primary, '__notes__', ()))
                assert conn.execute("SELECT value FROM document_graph_meta WHERE key='schema_version'").fetchone()
                before = conn.total_changes
                with pytest.raises(RuntimeError, match='^document_transaction_requires_idle_owner$'):
                    ingest(s, provider, path)
                assert conn.in_transaction and conn.total_changes == before
                assert provider._connect() is conn
            else:
                assert not conn.in_transaction
                assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'document_%'").fetchall() == []
                assert ingest(s, provider, path)['status'] == 'indexed'
                assert not conn.in_transaction
            s.witness('standalone_schema_failure', rollback_unknown=rollback_unknown,
                      primary_identity_preserved=captured.value is primary,
                      exact_handle_retained=provider._connect() is conn,
                      transaction_pending=conn.in_transaction)
        finally:
            # Test-owned disposal AFTER the retained witnesses, not a retry,
            # production recovery or release of a managed provider's quarantine.
            conn.set_authorizer(None)
