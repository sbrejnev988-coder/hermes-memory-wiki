"""Cooperative, permission-preserving embedding-provider migration.

A chat contributes only claims visible to its CURRENT native provider. A host
may orchestrate actual initialized owner providers; persisted bot/session IDs
are never used to manufacture one. Coordination reads metadata/digests only.
The legacy full reindex and its same-manifest foreign-vector fence stay intact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from typing import Any

# No claim/evidence text in global coordination, durable work or public results.
_FIELDS = ('id', 'topic', 'memory_revision', 'updated_at', 'visibility_scope',
           'origin_bot_id', 'origin_session_id', 'origin_chat_hash', 'project_id',
           'event_at', 'created_at', 'status', 'risk', 'quarantined_at',
           'trust_class', 'type', 'expires_at', 'hash')
_ACTIVE = "status='active' AND normalized_claim IS NOT NULL AND normalized_claim!=''"
_META_KEYS = ('database_instance_id', 'memory_revision', 'cache_state_revision',
              'privacy_erasure_applied_seq')
_ERRORS = frozenset({
    'migration_requires_initialized_native_owner', 'migration_owner_or_route_changed',
    'migration_semantic_contract_unavailable', 'migration_requires_alias_api',
    'migration_alias_binding_unproven', 'migration_alias_target_not_owned',
    'migration_requires_unversioned_collection_base', 'migration_erasure_not_applied',
    'migration_target_contract_unavailable', 'migration_source_changed',
    'migration_point_delivery_unconfirmed', 'migration_alias_outcome_unknown',
    'migration_pending_write_outcome_unknown', 'migration_target_state_unproven',
    'migration_alias_changed', 'migration_invalid_owner_participants',
    'migration_claim_deletes_not_quiescent',
})


class Refused(Exception):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _alias(module):
    """Fresh positive binding, not the legacy negative capability cache."""
    if module._qdrant_alias_mode() not in {'auto', 'require'}:
        raise Refused('migration_requires_alias_api')
    response = module._qdrant_req('GET', '/aliases', timeout=3.0)
    body = response.get('result') if isinstance(response, dict) and response.get('status') == 'ok' else None
    rows = body.get('aliases') if isinstance(body, dict) else None
    if not isinstance(rows, list) or any(
            not isinstance(r, dict) or type(r.get('alias_name')) is not str
            or type(r.get('collection_name')) is not str for r in rows):
        raise Refused('migration_alias_binding_unproven')
    matches = [r['collection_name'] for r in rows if r['alias_name'] == module._qdrant_alias()]
    if len(matches) != 1 or not matches[0]:
        raise Refused('migration_alias_binding_unproven')
    target = matches[0]
    if (target == module._qdrant_alias() or not module._is_managed_claim_collection(target)
            or not module._profile_target_allowed(target)):
        raise Refused('migration_alias_target_not_owned')
    return target


def _install(conn):
    # Only an explicit migration installs its own content-free checkpoint tables.
    # No implicit store opener/migration is used by the scope-only dry-run path.
    conn.execute('''CREATE TABLE IF NOT EXISTS embedding_migrations(
        id TEXT PRIMARY KEY, route_key TEXT NOT NULL UNIQUE,
        database_instance_id TEXT NOT NULL, endpoint TEXT NOT NULL,
        alias_name TEXT NOT NULL, source_collection TEXT NOT NULL,
        target_collection TEXT NOT NULL, manifest_json TEXT NOT NULL,
        status TEXT NOT NULL, completed_revision INTEGER,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS embedding_migration_points(
        migration_id TEXT NOT NULL, claim_id TEXT NOT NULL,
        metadata_digest TEXT NOT NULL, state_json TEXT NOT NULL DEFAULT '',
        contributor_digest TEXT NOT NULL, status TEXT NOT NULL,
        updated_at INTEGER NOT NULL, PRIMARY KEY(migration_id,claim_id))''')


def _actor(provider, module):
    conn = getattr(provider, '_conn', None)
    if (type(provider) is not module.MemoryWikiProvider or not isinstance(conn, sqlite3.Connection)
            or conn is not getattr(provider, '_owned_conn', None)
            or getattr(provider, '_lifecycle_state', '') not in {'ready', 'idle'}
            or getattr(provider, '_transaction_quarantine', None) is not None
            or module._set_native_home is None):
        raise Refused('migration_requires_initialized_native_owner')
    identity = provider._runtime_identity()
    if (identity.get('conn_path_matches') is not True or identity.get('profile_ready') is not True
            or Path(identity['request_home']).resolve() != Path(provider.home).resolve()):
        raise Refused('migration_requires_initialized_native_owner')
    return (provider.bot_id, provider.session_id, provider.project_scope,
            bool(getattr(provider, '_bot_scope_trusted', False)), provider.platform,
            provider.agent_context, str(Path(provider.home).resolve()),
            str(Path(provider.db_path).resolve()), id(conn), id(provider._privacy_erasure),
            module._REQUEST_HOME.get(), module._profile_configuration_generation(),
            module._embedding_cache_configuration_signature(), module._normalized_qdrant_endpoint())


def _snapshot(provider, module, conn):
    meta = dict(conn.execute('SELECT key,value FROM meta WHERE key IN (?,?,?,?)', _META_KEYS))
    if (not meta.get('database_instance_id')
            or meta['database_instance_id'] != provider.database_instance_id):
        raise Refused('migration_source_changed')
    ledger = provider._privacy_erasure
    entries = ledger._load_unlocked()  # Existing authenticated erasure authority only.
    if int(meta.get('privacy_erasure_applied_seq', 0)) != len(entries):
        raise Refused('migration_erasure_not_applied')
    rows = conn.execute('SELECT '+','.join(_FIELDS)+' FROM claims WHERE '+_ACTIVE+' ORDER BY id').fetchall()
    images = {str(r['id']): dict(r) for r in rows}
    return {'meta': meta, 'rows': images, 'erasure_digest': _digest(entries)}


def _own_rows(provider, conn):
    visibility, parameters = provider._claim_visibility_sql()
    rows = conn.execute('SELECT '+','.join(_FIELDS)+' FROM claims WHERE '+_ACTIVE+
                        ' AND '+visibility+' ORDER BY id', parameters).fetchall()
    return [r for r in rows if provider._claim_visible(r)]


def _result(status, *, ok=False, switched=False, **fields):
    return {'ok': ok, 'provider_migration': True, 'status': status,
            'alias_switched': switched, **fields}


def migrate(provider: Any, module: Any, limit: int = 0):
    """Durable staging contribution under this owner, then metadata-only cutover.

    Healthy bounded calls resume the same target and do not re-embed delivered
    receipts. Uncertain PUT/alias outcomes are held, not retried/guessed away.
    No remote source text is loaded by the coordinator or returned to a chat.
    """
    if type(limit) is not int or limit < 0:
        return _result('refused', error='invalid_arguments')
    attempts = delivered = 0
    job = None
    alias_may_have_been_issued = False
    try:
        anchor = _actor(provider, module)
        conn = provider._conn
        if conn.in_transaction:
            raise Refused('migration_requires_initialized_native_owner')
        if not module.SEMANTIC_ENABLED or not module.EMBED_CONTRACT_VALID:
            raise Refused('migration_semantic_contract_unavailable')
        manifest = module._embedding_manifest()
        manifest_json = _json(manifest)
        manifest_hash = module._manifest_hash(manifest)
        endpoint = module._normalized_qdrant_endpoint()
        base = module._qdrant_collection()
        # A user-pinned immutable physical collection is not an unversioned base.
        # Do not silently repair that identifier or reinterpret its old vectors.
        if re.fullmatch(r'.+_[0-9a-f]{12}', base):
            raise Refused('migration_requires_unversioned_collection_base')

        def current():
            if (_actor(provider, module) != anchor or provider._conn is not conn
                    or module._manifest_hash(module._embedding_manifest()) != manifest_hash
                    or module._normalized_qdrant_endpoint() != endpoint):
                raise Refused('migration_owner_or_route_changed')

        # Existing native cross-process lock; no stale PID/TTL takeover and no
        # new privilege. Its order matches ordinary journaled native mutations.
        with provider._journal_operation_scope():
            current()
            source = _alias(module)
            initial = _snapshot(provider, module, conn)
            instance = initial['meta']['database_instance_id']
            route = _digest((instance, endpoint, module._qdrant_alias(), manifest_hash))
            with provider._claim_transaction(conn):
                _install(conn)
            job = conn.execute('SELECT * FROM embedding_migrations WHERE route_key=?', (route,)).fetchone()
            if job is None:
                target = module._physical_collection_name(manifest)+'_force_'+str(time.time_ns())
                if not module._is_managed_claim_collection(target) or not module._profile_target_allowed(target):
                    raise Refused('migration_alias_target_not_owned')
                identifier = 'em_' + uuid.uuid4().hex
                stamp = int(time.time())
                with provider._claim_transaction(conn):
                    conn.execute('''INSERT INTO embedding_migrations
                        (id,route_key,database_instance_id,endpoint,alias_name,source_collection,
                         target_collection,manifest_json,status,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,'running',?,?)''',
                        (identifier, route, instance, endpoint, module._qdrant_alias(), source,
                         target, manifest_json, stamp, stamp))
                job = conn.execute('SELECT * FROM embedding_migrations WHERE id=?', (identifier,)).fetchone()
            else:
                target, identifier = job['target_collection'], job['id']
                if (job['manifest_json'] != manifest_json or job['endpoint'] != endpoint
                        or job['database_instance_id'] != instance):
                    raise Refused('migration_owner_or_route_changed')
                if job['status'] == 'activation_unknown':
                    raise Refused('migration_alias_outcome_unknown')
                if job['status'] == 'write_unknown' or conn.execute(
                        "SELECT 1 FROM embedding_migration_points WHERE migration_id=? AND status='pending' LIMIT 1",
                        (identifier,)).fetchone():
                    raise Refused('migration_pending_write_outcome_unknown')
                if source not in {job['source_collection'], target}:
                    raise Refused('migration_alias_changed')
            if not module._ensure_collection(target):
                raise Refused('migration_target_contract_unavailable')
            current()
            eligible = _own_rows(provider, conn)
            own_ready = 0
            for row in eligible:
                cid = str(row['id'])
                md = _digest(dict(row))
                receipt = conn.execute('''SELECT metadata_digest,state_json,status
                    FROM embedding_migration_points WHERE migration_id=? AND claim_id=?''',
                    (identifier, cid)).fetchone()
                if receipt is not None and receipt['status'] == 'complete' and receipt['metadata_digest'] == md:
                    own_ready += 1
                    continue
                if limit and attempts >= limit:
                    break
                attempts += 1
                # Crash-safe possible-location and content-free work intent
                # precede the ORIGINAL actor/erasure/source fence.
                stamp = int(time.time())
                with provider._claim_transaction(conn):
                    module._record_claim_vector_target(conn, cid, collection=target,
                        endpoint=endpoint, manifest_hash=manifest_hash, status='write_pending')
                    conn.execute('''INSERT INTO embedding_migration_points
                        (migration_id,claim_id,metadata_digest,state_json,contributor_digest,status,updated_at)
                        VALUES(?,?,?,'',?,'pending',?) ON CONFLICT(migration_id,claim_id)
                        DO UPDATE SET metadata_digest=excluded.metadata_digest,state_json='',
                            contributor_digest=excluded.contributor_digest,status='pending',updated_at=excluded.updated_at''',
                        (identifier, cid, md, _digest(anchor), stamp))
                fence = module._DisclosureFence(provider, conn)
                image = fence.index_claim(row, 'full_reindex')

                def admit():
                    current()
                    fence.admit_index()

                document = str(image['normalized_claim'])
                vector = module._embed_document(document, _admit=admit)
                admit()
                if module._validate_embedding_vector(vector, 'provider migration') is None:
                    # No point PUT was entered. A known embedding refusal is
                    # retryable under fresh current owner permissions.
                    with provider._claim_transaction(conn):
                        conn.execute("UPDATE embedding_migration_points SET status='retry' WHERE migration_id=? AND claim_id=?",
                                     (identifier, cid))
                    raise Refused('migration_point_delivery_unconfirmed')
                payload = module._qdrant_claim_payload(cid, document, image, manifest_hash=manifest_hash)
                payload.pop('claim', None)  # No plaintext preview in shared staging.
                if payload['visibility_scope'] == 'invalid':
                    raise Refused('migration_source_changed')
                if not module._qdrant_upsert(cid, vector, payload, collection=target,
                        create_collection=False, _admit=admit):
                    with provider._claim_transaction(conn):
                        conn.execute("UPDATE embedding_migrations SET status='write_unknown',updated_at=? WHERE id=?",
                                     (int(time.time()), identifier))
                    raise Refused('migration_point_delivery_unconfirmed')
                admit()
                point_state = module._qdrant_claim_reconciliation_state(payload)
                # The original fence is consumed before bookkeeping changes its
                # epoch. Recheck metadata inside the genuine owner transaction.
                with provider._claim_transaction(conn):
                    current()
                    now_row = conn.execute('SELECT '+','.join(_FIELDS)+' FROM claims WHERE id=?', (cid,)).fetchone()
                    if now_row is None or _digest(dict(now_row)) != md or not provider._claim_visible(now_row):
                        raise Refused('migration_source_changed')
                    module._record_claim_vector_target(conn, cid, collection=target,
                        endpoint=endpoint, manifest_hash=manifest_hash, status='active', indexed_at=int(time.time()))
                    conn.execute("UPDATE embedding_migration_points SET state_json=?,status='complete',updated_at=? WHERE migration_id=? AND claim_id=?",
                                 (_json(point_state), int(time.time()), identifier, cid))
                delivered += 1
                own_ready += 1

            # Current chat cannot embed another owner's text. Its absence is
            # durable waiting work, not a reason to weaken ACL or copy Nous data.
            current()
            before = _snapshot(provider, module, conn)
            receipts = {str(r['claim_id']): dict(r) for r in conn.execute(
                "SELECT claim_id,metadata_digest,state_json,status FROM embedding_migration_points WHERE migration_id=?",
                (identifier,)).fetchall()}
            expected = {}
            for cid, row in before['rows'].items():
                receipt = receipts.get(cid)
                if (receipt is None or receipt['status'] != 'complete'
                        or receipt['metadata_digest'] != _digest(row)):
                    return _result('awaiting_authorized_owners', ok=True, migration_id=identifier,
                        collection=target, attempts=attempts, ok_count=delivered,
                        own_eligible_count=len(eligible), own_ready_count=own_ready)
                expected[cid] = json.loads(receipt['state_json'])
            observed = module._qdrant_claim_state(target)
            if observed is None or observed != expected:
                raise Refused('migration_target_state_unproven')
            if _snapshot(provider, module, conn) != before:
                raise Refused('migration_source_changed')
            if _alias(module) not in {job['source_collection'], target}:
                raise Refused('migration_alias_changed')
            # SQLite writer exclusion covers the final full ID/revision/ACL
            # snapshot and the actual atomic alias transaction, not just counts.
            with provider._claim_transaction(conn):
                current()
                cut = _snapshot(provider, module, conn)
                if cut != before:
                    raise Refused('migration_source_changed')
                # Already leased legacy deletes can mutate shared staging
                # without a new claim revision. Their ACK needs this SQLite
                # writer slot. Never drain another owner's work from this chat.
                if conn.execute("""SELECT 1 FROM index_outbox
                        WHERE object_type='claim' AND operation='delete'
                          AND status IN ('pending','processing','failed') LIMIT 1""").fetchone():
                    raise Refused('migration_claim_deletes_not_quiescent')
                if module._qdrant_claim_state(target) != expected:
                    raise Refused('migration_target_state_unproven')
                active = _alias(module)
                if active not in {job['source_collection'], target}:
                    raise Refused('migration_alias_changed')

                def cutover_admit():
                    current()
                    if _snapshot(provider, module, conn) != cut:
                        raise Refused('migration_source_changed')

                if active != target:
                    actions = [{'delete_alias': {'alias_name': module._qdrant_alias()}},
                               {'create_alias': {'collection_name': target, 'alias_name': module._qdrant_alias()}}]
                    cutover_admit()
                    alias_may_have_been_issued = True
                    reply = module._qdrant_req('POST', '/collections/aliases', {'actions': actions},
                                               _admit=cutover_admit)
                    if not isinstance(reply, dict) or reply.get('status') != 'ok':
                        raise Refused('migration_alias_outcome_unknown')
                if _alias(module) != target:
                    raise Refused('migration_alias_outcome_unknown')
                cutover_admit()
                conn.execute("UPDATE embedding_migrations SET status='completed',completed_revision=?,updated_at=? WHERE id=?",
                             (int(cut['meta']['memory_revision']), int(time.time()), identifier))
            return _result('completed', ok=True, switched=True, migration_id=identifier,
                collection=target, attempts=attempts, ok_count=delivered,
                own_eligible_count=len(eligible), own_ready_count=own_ready,
                validated_revision=int(before['meta']['memory_revision']))
    except Exception as exc:
        code = exc.args[0] if type(exc) is Refused and len(exc.args) == 1 else 'migration_source_changed'
        if type(code) is not str or code not in _ERRORS:
            code = 'migration_source_changed'
        if job is not None and alias_may_have_been_issued:
            # Never manufacture old-alias success from an ambiguous POST/COMMIT.
            try:
                with provider._claim_transaction(provider._conn):
                    provider._conn.execute("UPDATE embedding_migrations SET status='activation_unknown',updated_at=? WHERE id=?",
                                           (int(time.time()), job['id']))
            except Exception:
                pass
        return _result('refused', switched=None if alias_may_have_been_issued else False,
            error=code, attempts=attempts, ok_count=delivered,
            alias_outcome='unknown' if alias_may_have_been_issued else 'not_switched_by_this_call')


def orchestrate(provider, module, owners, limit=0):
    """Host-only convenience over ACTUAL provider objects, never JSON principals.

    A host must already possess each native owner's current authorized context.
    This function does not discover owners, clone consumers, change sessions,
    expand ACL or revive stale permissions. Missing owners remain waiting.
    """
    if (type(owners) not in (tuple, list) or not 1 <= len(owners) <= 64
            or type(limit) is not int or limit < 0):
        return _result('refused', error='migration_invalid_owner_participants')
    try:
        _actor(provider, module)
        home = Path(provider.home).resolve()
        path = Path(provider.db_path).resolve()
        for owner in owners:
            _actor(owner, module)
            if (Path(owner.home).resolve() != home or Path(owner.db_path).resolve() != path
                    or owner._conn.in_transaction):
                raise Refused('migration_invalid_owner_participants')
    except Exception:
        return _result('refused', error='migration_invalid_owner_participants')
    remaining = limit
    result = _result('awaiting_authorized_owners', ok=True)
    for owner in owners:
        # Each ordinary scoped provider method supplies its own real authority.
        result = owner._reindex(limit=remaining, provider_migration=True)
        if not result.get('ok') or result.get('alias_switched'):
            return result
        if limit:
            remaining -= result.get('attempts', 0)
            if remaining <= 0:
                break
    return result
