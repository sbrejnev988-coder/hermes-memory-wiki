"""Final SOURCE disclosure read fence; not a permission service or future lease.

Retain original authority and raw SQLite images, even if display guards redact
those images. No connect/init/replay/repair at final admission. Unobserved writes
are conservatively withheld (data_version + total_changes + existing revisions),
including ABA in columns not covered by the historical revision trigger.
"""
from __future__ import annotations
from contextlib import nullcontext
import contextvars
import threading
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
try:
    from .shared_blocks import _attached_claims, _block_refs
except ImportError:
    from shared_blocks import _attached_claims, _block_refs

MAX_ROWS = 4096
BATCH = 400
# Only actual existing tables/identity columns; no caller-controlled SQL names.
KEYS = {
    'claims': 'id', 'evidence': 'id', 'entities': 'id', 'relations': 'id',
    'document_sources': 'source_id', 'document_revisions': 'revision_id',
    'document_units': 'unit_id', 'document_chunks': 'chunk_id',
    'document_edges': 'edge_id', 'external_sources': 'source_key',
    'code_graph_repositories': 'repository_id', 'code_graph_files': ('repository_id','file_path'),
    'code_graph_symbols': ('repository_id','symbol_id'),
    'code_graph_chunks': ('repository_id','chunk_id'),
    'code_graph_lines': ('repository_id','file_path','line_no'),
    'code_graph_edges': ('repository_id','edge_id'), 'code_graph_events': 'event_id',
    'code_claim_metadata': 'claim_id', 'patch_outcomes': ('repository_id','patch_id'),
    'memory_events': 'event_id', 'episodic_turns': 'id',
    'memory_observations': 'observation_id',
    'project_profiles': 'project_id', 'contradictions': 'id',
    'preference_rules': 'id', 'preference_attestations': 'rule_id',
    'claims_history': 'id', 'memory_mutations': 'id', 'memory_changes': 'id',
    'recall_events': 'id',
    'shared_blocks': 'id',
    'shared_block_grants': ('block_id', 'principal_type', 'principal_id'),
    'shared_block_attachments': ('block_id', 'principal_type', 'principal_id'),
}

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), default=str).encode('utf-8')).hexdigest()

def physical(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise PermissionError('disclosure_path_unproven')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise PermissionError('disclosure_file_unproven')
    return (str(path.resolve()), info.st_dev, info.st_ino)

def config_image(home, name='config.yaml'):
    path = Path(home) / name
    try:
        identity = physical(path)
    except FileNotFoundError:
        return None  # genuine standalone policy, not a missing native authority
    info = path.lstat()
    return (*identity, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

def existing_ledger(module, root):
    """Read existing federation authority without constructor/create/replay.

    Reuse the exact ErasureLedger MAC/parser/matching methods. Nothing here
    authorizes missing files or invents a key; no profile lifecycle is booted.
    """
    cls = module.ErasureLedger
    directory = Path(root) / 'privacy-erasure'
    for name in ('key.bin', 'intents.jsonl', 'intents.lock'):
        physical(directory / name)
    key = (directory / 'key.bin').read_bytes()
    if len(key) != 32:
        raise PermissionError('disclosure_erasure_key_unproven')
    ledger = object.__new__(cls)
    ledger.dir, ledger.key = directory, key
    ledger.key_path, ledger.log_path, ledger.lock_path = [directory / n for n in ('key.bin','intents.jsonl','intents.lock')]
    ledger._base = (int.from_bytes(hmac.digest(key, b'rolling-base', 'sha256')[:8], 'big') | 1) & ((1 << 64) - 1)
    if ledger._base < 257:
        ledger._base += 257
    return ledger

class DisclosureFence:
    """Bounded original read set + short authoritative final SQLite snapshot."""
    def __init__(self, provider, conn=None, *, home=None, ledger=None, foreign=False):
        self.provider = provider
        self.conn = conn if conn is not None else getattr(provider, '_conn', None)
        self.owner_conn = getattr(provider, '_conn', None)
        self.source_conn = None  # exact factory reader, original images only
        self.home = Path(home if home is not None else provider.home)
        self.foreign = foreign
        self.ledger = ledger if foreign else getattr(provider, '_privacy_erasure', None)
        self.images, self.selectors, self.purposes = {}, {}, {}
        self.shared_sets = {}
        self.policy_environment = tuple(os.environ.get(k) for k in
                                        ('MEMORY_WIKI_STRICT_RECALL', 'HERMES_SECURITY_STRICT'))
        # Pin the original read body before guards, never a receipt capability.
        self.context_reader = getattr(type(provider), '_disclosure_context', None)
        while hasattr(self.context_reader, '__wrapped__'):
            self.context_reader = self.context_reader.__wrapped__
        self.ok = False
        try:
            if not isinstance(self.conn, sqlite3.Connection) or not isinstance(self.owner_conn, sqlite3.Connection):
                raise PermissionError('disclosure_connection_unproven')
            if self.conn.in_transaction:
                raise PermissionError('disclosure_requires_current_idle_reader')
            self.tables = {str(r[0]) for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.anchor = self._authority()
            self.epoch = self._epoch()
            self.erasure = self._erasures()
            self.ok = True
        except Exception:
            self.ok = False

    def _authority(self, *, terminal=False):
        p = self.provider
        if p._conn is not self.owner_conn or (not self.foreign and p._privacy_erasure is not self.ledger):
            raise PermissionError('disclosure_owner_replaced')
        identity, generation = (self.context_reader(p, terminal=True) if terminal
                                else p._disclosure_context())
        if identity.get('conn_path_matches') is not True or identity.get('profile_ready') is not True:
            raise PermissionError('disclosure_current_owner_unproven')
        if Path(identity['request_home']).resolve() != Path(p.home).resolve():
            raise PermissionError('disclosure_request_owner_unproven')
        if getattr(p, '_lifecycle_state', '') not in {'ready', 'idle'} or getattr(p, '_transaction_quarantine', None) is not None:
            raise PermissionError('disclosure_owner_not_ready')
        actual = next(str(r[2]) for r in self.conn.execute('PRAGMA database_list') if r[1] == 'main')
        expected = self.home / 'memory-wiki' / 'memory_wiki.sqlite3' if self.foreign else Path(p.db_path)
        if not actual or Path(actual).resolve() != expected.resolve():
            raise PermissionError('disclosure_namespace_unproven')
        if self.ledger is None or (not terminal and not p._disclosure_ledger_type(self.ledger)):
            raise PermissionError('disclosure_existing_erasure_required')
        if self.ledger.dir.resolve() != (self.home / 'memory-wiki/privacy-erasure').resolve():
            raise PermissionError('disclosure_erasure_owner_unproven')
        return (fingerprint(identity), generation, str(Path(p.home).resolve()),
                str(Path(p.root).resolve()), str(Path(p.db_path).resolve()),
                p.bot_id, p.session_id, p.project_scope, getattr(p, '_bot_scope_trusted', False),
                p.platform, p.agent_context, id(self.owner_conn), id(self.ledger),
                physical(expected), config_image(self.home),
                config_image(self.home, '.env'), config_image(self.home, 'proxy/.env'),
                physical(self.ledger.key_path), physical(self.ledger.log_path),
                hashlib.sha256(self.ledger.key).hexdigest())

    def _epoch(self):
        meta = dict(self.conn.execute("SELECT key,value FROM meta WHERE key IN ('database_instance_id','memory_revision','cache_state_revision','privacy_erasure_applied_seq')"))
        if not meta.get('database_instance_id') or 'memory_revision' not in meta or 'cache_state_revision' not in meta:
            raise PermissionError('disclosure_revision_unproven')
        if not self.foreign and meta['database_instance_id'] != self.provider.database_instance_id:
            raise PermissionError('disclosure_database_replaced')
        return (fingerprint(meta), int(self.conn.execute('PRAGMA data_version').fetchone()[0]), self.conn.total_changes)

    def _erasures(self):
        # Existing verified parser, no lock-file creation or replay/SQLite write.
        entries = self.ledger._load_unlocked()
        row = self.conn.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()
        applied = int(row[0]) if row else 0  # genuine old zero-intent store
        if applied != len(entries):
            raise PermissionError('disclosure_erasure_replay_required')
        return entries

    def _same(self, delivery=None):
        expected = delivery.expected_epoch(self) if delivery is not None else self.epoch
        return (self.ok and self.anchor == self._authority(terminal=delivery is not None) and expected == self._epoch()
                and self.policy_environment == tuple(os.environ.get(k) for k in
                    ('MEMORY_WIKI_STRICT_RECALL', 'HERMES_SECURITY_STRICT'))
                and fingerprint(self.erasure) == fingerprint(self._erasures()))

    def bind_reader(self, reader):
        # Only the actual private factory may attach its source to this ORIGINAL
        # provider-owned fence. Path/UUID equality alone never grants a lifetime.
        try:
            from .code_knowledge_graph import _owns_graph_reader
        except ImportError:
            from code_knowledge_graph import _owns_graph_reader
        if (self.source_conn is not None or self.conn is not self.provider._owned_conn
                or not _owns_graph_reader(self.provider, reader)
                or reader._graph_read_fence is not self
                or reader.execute('PRAGMA query_only').fetchone()[0] != 1):
            raise DeliveryWithheld('terminal_original_read_owner_required')
        main = next(r[2] for r in reader.execute('PRAGMA database_list') if r[1] == 'main')
        meta = dict(reader.execute("SELECT key,value FROM meta WHERE key IN ('database_instance_id','memory_revision','cache_state_revision','privacy_erasure_applied_seq')"))
        if (not main or physical(main) != physical(self.provider.db_path)
                or fingerprint(meta) != self.epoch[0] or not self._same()):
            raise DeliveryWithheld('terminal_original_reader_image_mismatch')
        self.source_conn = reader

    def _read(self, table, column, ids, *, conn=None):
        columns = column if isinstance(column, tuple) else (column,)
        if table not in KEYS or not set(columns).issubset(self._columns(table)):
            raise PermissionError('disclosure_read_set_invalid')
        rows = []
        for offset in range(0, len(ids), BATCH):
            chunk = ids[offset:offset+BATCH]
            if isinstance(column, tuple):
                if column != KEYS[table] or any(len(i) != len(column) for i in chunk):
                    raise PermissionError('disclosure_composite_identity_invalid')
                clause = '(' + ' AND '.join(c+'=?' for c in column) + ')'
                where = ' OR '.join(clause for _ in chunk)
                parameters = tuple(v for i in chunk for v in i)
            else:
                where = column + ' IN (' + ','.join('?' for _ in chunk) + ')'
                parameters = tuple(chunk)
            rows.extend(dict(r) for r in (self.conn if conn is None else conn).execute(
                f"SELECT * FROM {table} WHERE {where} LIMIT ?", (*parameters, MAX_ROWS+1)).fetchall())
            if len(rows) > MAX_ROWS:
                raise PermissionError('disclosure_read_set_exceeded')
        return rows

    def _columns(self, table):
        return {str(r[1]) for r in self.conn.execute(f'PRAGMA table_info({table})')}

    def watch(self, table, column, ids, *, optional=False):
        try:
            if not self._same():
                raise PermissionError('disclosure_original_epoch_changed')
            ids = tuple(sorted({tuple(str(v) for v in i) if isinstance(column, tuple) else str(i)
                                for i in ids if i}))
            if len(ids) > MAX_ROWS:
                raise PermissionError('disclosure_id_set_exceeded')
            if not ids:
                return []
            if table not in self.tables:
                if optional:
                    return []
                raise PermissionError('disclosure_source_missing')
            key = (table, column, ids)
            rows = self._read(*key)
            digest = fingerprint(rows)
            if self.source_conn is not None:
                try:
                    from .code_knowledge_graph import _owns_graph_reader
                except ImportError:
                    from code_knowledge_graph import _owns_graph_reader
                if (not _owns_graph_reader(self.provider, self.source_conn)
                        or self.source_conn.in_transaction
                        or fingerprint(self._read(*key, conn=self.source_conn)) != digest
                        or not self._same()):
                    raise PermissionError('disclosure_original_reader_image_changed')
            if key in self.selectors and self.selectors[key] != digest:
                raise PermissionError('disclosure_cannot_adopt_new_image')
            self.selectors[key] = digest
            self.images[key] = rows
            if sum(len(r) for r in self.images.values()) > MAX_ROWS:
                raise PermissionError('disclosure_bulk_set_exceeded')
            return rows
        except Exception:
            self.ok = False
            return []

    def rows(self, table, rows):
        """Bind raw SQLite rows before caller ACL/display callbacks, preserving order.

        This does not grant visibility. Only explicit fixed-schema callers use it;
        existing caller ACL/trust predicates still decide which rows to render.
        """
        column = KEYS[table]
        for row in rows:
            identity = tuple(row[c] for c in column) if isinstance(column, tuple) else row[column]
            original = self.watch(table, column, [identity])
            if len(original) != 1 or dict(row) != original[0]:
                self.ok = False
                return
            yield row

    def shared(self, block_ids):
        """Retain real sharing rows and full source images before any guard.

        Sharing remains a grant+attachment policy, separate from creator ACL.
        The private carrier stays on this fence through the caller's last guard.
        """
        try:
            if self.foreign or not {'shared_blocks', 'shared_block_grants',
                                    'shared_block_attachments'}.issubset(self.tables):
                raise PermissionError('disclosure_sharing_schema_missing')
            ids = tuple(sorted({str(i) for i in block_ids if i}))
            blocks = self.watch('shared_blocks', 'id', ids)
            grants = self.watch('shared_block_grants', 'block_id', ids)
            attachments = self.watch('shared_block_attachments', 'block_id', ids)
            claim_ids = tuple(sorted({str(ref['claim_id']) for b in blocks for ref in _block_refs(b)}))
            claims = self.watch('claims', 'id', claim_ids)
            if not self.ok or len(blocks) != len(ids):
                raise PermissionError('disclosure_sharing_snapshot_unproven')
            eligible = _attached_claims(self.provider, blocks, grants, attachments, claims)
            keys = (('shared_blocks', 'id', ids), ('shared_block_grants', 'block_id', ids),
                    ('shared_block_attachments', 'block_id', ids), ('claims', 'id', claim_ids))
            if ids:
                self.shared_sets[keys] = {bid: [str(r['id']) for r in rows]
                                          for bid, rows in eligible.items()}
            return blocks, eligible
        except Exception:
            self.ok = False
            return [], {}

    def claims(self, rows, purpose='recall', *, session_id='', include_all_projects=False):
        rows = list(rows)
        current = self.watch('claims', 'id', [r['id'] for r in rows])
        by_id = {r['id']:r for r in current}
        # Capture the raw claim and linked source images before display callbacks.
        # These watches keep the original epoch; none can adopt a later version.
        ids = list(by_id)
        self.watch('evidence','claim_id',ids,optional=True)
        links = self.watch('document_chunks','embedding_claim_id',ids,optional=True)
        if links:
            self.documents(links)
        code = self.watch('code_claim_metadata','claim_id',ids,optional=True)
        if code:
            self.code(code)
        for row in rows:
            cid = str(row['id'])
            raw = by_id.get(cid)
            # Rendered fields bind raw source, not a model's declared used_fields.
            if raw is None:
                self.ok = False
                continue
            values = dict(row)
            if values != raw:
                safe = self.provider._sanitize_row(raw)
                if any(k in safe and safe[k] != value and raw[k] != value for k,value in values.items()):
                    self.ok = False
            self.purposes[cid] = (purpose, session_id, include_all_projects)
        return current

    def documents(self, rows):
        ids = [r.get('source_id','') for r in rows]
        sources = self.watch('document_sources','source_id',ids)
        for source in sources:
            if int(source['active'] or 0) != 1:
                self.ok = False
            self.provider._disclosure_document_access(source)
        self.watch('document_revisions','revision_id',[r.get('revision_id','') for r in rows]+[r.get('revision_id','') for r in sources])
        connectors = self.watch('external_sources','document_source_id',ids,optional=True)
        if any(str(r['status']) != 'active' or str(r['owner_bot_id']) != str(self.provider.bot_id) for r in connectors):
            self.ok = False
        linked = self.watch('claims','id',[r.get('embedding_claim_id','') for r in rows],optional=True)
        for row in linked:
            self.purposes[str(row['id'])] = ('recall','',False)
        if any(r.get('embedding_claim_id') and not any(c['id']==r['embedding_claim_id'] for c in linked) for r in rows):
            self.ok = False

    def code(self, rows):
        repos = {r.get('repository_id','') for r in rows}
        repository_rows = self.watch('code_graph_repositories','repository_id',repos)
        if len(repository_rows) != len(repos) or any(str(r['repository_id']) != self.provider._disclosure_code_repository(self.conn, r['repository_id']) for r in repository_rows):
            self.ok = False
        files = self.watch('code_graph_files', ('repository_id','file_path'),
                           [(r.get('repository_id',''),r.get('file_path','')) for r in rows if r.get('file_path')])
        if any(r.get('file_path') and not any(f['repository_id']==r['repository_id'] and f['file_path']==r['file_path'] for f in files) for r in rows):
            self.ok = False
        events = self.watch('code_graph_events','event_id',[r.get('graph_event_id','') for r in rows])
        for row in rows:
            event_id = row.get('graph_event_id')
            if event_id and not any(e['event_id']==event_id and e['status']=='completed' and e['payload_hash']==row.get('graph_payload_hash') for e in events):
                self.ok = False
        linked = self.watch('claims','id',[r.get('embedding_claim_id','') for r in rows],optional=True)
        for row in linked:
            self.purposes[str(row['id'])] = ('recall','',False)
        if any(r.get('embedding_claim_id') and not any(c['id']==r['embedding_claim_id'] for c in linked) for r in rows):
            self.ok = False

    def _eligible(self, row, purpose, session, include_projects):
        cid = str(row['id'])
        if self.foreign:
            if str(row['visibility_scope']) != 'global':
                return False
            # Existing federation policy is stricter than diagnostic STRICT=0.
            if (row['status'] != 'active' or row['risk'] == 'secret' or int(row['quarantined_at'])
                    or row['trust_class'] in {'tool_log','raw_blob','secret'} or row['type']=='source_artifact' or float(row['quality'])<.20):
                return False
        else:
            if not self.provider._claim_visible(row,session) and not (include_projects and row['visibility_scope']=='project'):
                return False
            if cid not in self.policy_ids.get(purpose, set()):
                return False
        return self._unerased(row)

    def _unerased(self, row):
        cid = str(row['id'])
        for entry in self.erasure:
            if not self.ledger._owner_allows(entry['owner'],row,'claim'):
                continue
            text = self.provider._disclosure_normalize(str(row['normalized_claim'] or row['claim'])).casefold()
            if (self.ledger.digest('claim-id',cid) in entry['claims'] or
                    (int(row['created_at'])<=int(entry['created_at']) and self.ledger._contains_digest(text,entry['claim_text'],'claim-text'))):
                return False
        return True

    def finish(self, *, _delivery=None):
        """Final synchronous read, after guards/remote waits; never fresh adoption."""
        if not self.ok:
            return False
        savepoint = 'memory_wiki_disclosure_' + format(id(self),'x')
        begun = False
        try:
            with getattr(self.provider,'_lock',nullcontext()):
                owned = _delivery is not None and _delivery.owns_snapshot(self)
                if (self.conn.in_transaction and not owned) or not self._same(_delivery):
                    return False
                self.conn.execute('SAVEPOINT '+savepoint); begun = True
                current = {}
                for key, digest in self.selectors.items():
                    current[key] = self._read(*key)
                    expected = _delivery.expected_image(self, key) if owned else digest
                    if fingerprint(current[key]) != expected:
                        return False
                for keys, original in (() if owned else self.shared_sets.items()):
                    eligible = _attached_claims(self.provider, *(current.get(k, []) for k in keys))
                    if original != {bid: [str(r['id']) for r in rows] for bid, rows in eligible.items()}:
                        return False
                    if any(not self._unerased(r) for rows in eligible.values() for r in rows):
                        return False
                self.policy_ids = {}
                if not self.foreign:
                    for purpose in {p[0] for p in self.purposes.values()}:
                        ids = sorted(cid for cid, p in self.purposes.items() if p[0] == purpose)
                        accepted = set()
                        policy = (_delivery.policies[(id(self), purpose)] if owned
                                  else self.provider._claim_metadata_eligibility_sql(purpose))
                        for offset in range(0, len(ids), BATCH):
                            chunk = ids[offset:offset+BATCH]
                            accepted.update(str(r[0]) for r in self.conn.execute(
                                'SELECT id FROM claims WHERE id IN (' + ','.join('?' for _ in chunk)
                                + ') AND ' + policy, chunk).fetchall())
                        self.policy_ids[purpose] = accepted
                        if owned and accepted != set(ids):
                            return False
                for rows in (() if owned else self.images.values()):
                    for row in rows:
                        if 'id' in row and row['id'] in self.purposes and 'claim' in row:
                            if not self._eligible(row,*self.purposes[row['id']]):
                                return False
                # Same owner/config/erasure and revision epoch around the read.
                if not self._same(_delivery):
                    return False
                self.conn.execute('RELEASE '+savepoint); begun = False
                return self._same(_delivery)
        except Exception:
            return False
        finally:
            if begun:
                try:
                    self.conn.execute('ROLLBACK TO '+savepoint)
                    self.conn.execute('RELEASE '+savepoint)
                except Exception:
                    self.ok = False


# Private in-process preparation, never serialized in a receipt or accepted from
# tool JSON. Callback phase may fail or mutate authority; it cannot commit ACKs.
DELIVERY = contextvars.ContextVar('memory_wiki_terminal_delivery', default=None)


# Inserted only into the existing disclosure_fence module, not a new service.
AUDIT_PREPARATION = contextvars.ContextVar('memory_wiki_detached_audit', default=None)


def _audit_binding(provider, session_id):
    # No connection/TerminalDelivery/transaction reference leaves the parent.
    generation = provider._disclosure_context()[1]
    if (type(generation) is not tuple or len(generation) != 4
            or type(generation[0]) is not str or len(generation[0]) != 64
            or any(type(v) is not int for v in generation[1:])
            or any(type(v) is not str or len(v) > 512 for v in
                   (provider.bot_id, provider.session_id, session_id, provider.project_scope))):
        raise DeliveryWithheld('detached_audit_owner_unproven')
    return (id(provider), provider.bot_id, provider.session_id, session_id,
            provider.project_scope, generation)


class PreparedAudits:
    """Attempt-local data only: bounded frozen tuples, never a SQL writer."""
    __slots__ = ('binding', 'attempt', 'cancel', 'parent_thread', 'worker_thread',
                 '_lock', '_pending', 'prepared', 'prepared_count', 'dropped_count',
                 'late_count', 'byte_count', 'outcome', 'persisted_count')

    def __init__(self, binding, cancel):
        self.binding, self.cancel = binding, cancel
        self.attempt = object()
        self.parent_thread, self.worker_thread = threading.get_ident(), None
        self._lock = threading.Lock()
        self._pending, self.prepared = [], ()
        self.prepared_count = self.dropped_count = self.late_count = self.byte_count = 0
        self.outcome, self.persisted_count = 'collecting', 0

    def bind_worker(self):
        with self._lock:
            if self.worker_thread is not None or threading.get_ident() == self.parent_thread:
                raise DeliveryWithheld('detached_audit_worker_unproven')
            self.worker_thread = threading.get_ident()

    def _drop(self, reason):
        if self.outcome in {'collecting', 'prepared', 'queued'}:
            self.dropped_count = self.prepared_count
            self._pending.clear()
            self.prepared = ()
            self.outcome, self.persisted_count = reason, 0

    def drop(self, reason):
        with self._lock:
            self._drop(reason)

    def prepare(self, provider, values):
        with self._lock:
            if self.cancel.is_set() or self.outcome != 'collecting':
                self._drop('dropped_cancelled')
                self.late_count += 1
                return False
            limits = (64, 120, 40, 1600, None, 7, 512, 512, 512, 512)
            if (threading.get_ident() != self.worker_thread or
                    _audit_binding(provider, self.binding[3]) != self.binding or
                    type(values) is not tuple or len(values) != 10 or
                    type(values[4]) is not int or values[4] < 0 or
                    any(type(v) is not str or len(v) > bound for v, bound in zip(values, limits) if bound is not None)):
                self._drop('refused_preparation')
                raise DeliveryWithheld('detached_audit_intent_unproven')
            if values in self._pending:
                return True  # The historical audit ID/readback is idempotent.
            size = sum(len(v.encode('utf-8')) for v in values if type(v) is str)
            if len(self._pending) >= 128 or self.byte_count + size > 256000:
                self._drop('refused_bounds')
                raise DeliveryWithheld('detached_audit_bounds_exceeded')
            self._pending.append(values)
            self.prepared_count += 1
            self.byte_count += size
            return True

    def seal(self):
        with self._lock:
            if threading.get_ident() != self.worker_thread:
                self._drop('refused_worker')
                raise DeliveryWithheld('detached_audit_worker_unproven')
            if self.cancel.is_set():
                self._drop('dropped_cancelled')
            elif self.outcome == 'collecting':
                self.prepared = tuple(self._pending)
                self._pending.clear()
                self.outcome = 'prepared'

    def take(self, provider):
        with self._lock:
            if (threading.get_ident() != self.parent_thread or self.cancel.is_set()
                    or self.outcome != 'prepared'
                    or _audit_binding(provider, self.binding[3]) != self.binding):
                self._drop('refused_parent_admission')
                raise DeliveryWithheld('detached_audit_original_attempt_required')
            self.outcome = 'queued'
            return self.prepared


def current_delivery(provider=None):
    delivery = DELIVERY.get()
    return delivery if (type(delivery) is TerminalDelivery and
                        (provider is None or delivery.provider is provider)) else None


class DeliveryWithheld(PermissionError):
    pass


# Exactly the historical accounting effects, no SQL supplied by a renderer.
EFFECTS = {
    'sync_bundle': ('INSERT OR REPLACE INTO sync_bundles(id,path,summary,payload_hash,direction,created_at) VALUES(?,?,?,?,?,?)', 6),
    'recall_count': ('UPDATE claims SET access_count=access_count+1, recall_count=recall_count+1, last_accessed=?, last_recalled=? WHERE id=?', 3),
    'recall_event': ('INSERT INTO recall_events(id,claim_id,query,score,used,answer_id,outcome,created_at) VALUES(?,?,?,?,?,?,?,?)', 8),
    'feedback': ('INSERT INTO recall_feedback(id,recall_event_id,claim_id,query,retrieved,injected,used,helpful,irrelevant,contradicted,harmful,answer_id,feedback_source,notes,created_at,outcome,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING', 17),
    'last_recalled': ('UPDATE claims SET last_recalled=? WHERE id=?', 2),
    'consumer': ('''INSERT INTO memory_consumers(consumer_id,bot_id,session_id,chat_hash,project_id,last_seen_revision,database_instance_id,absolute_db_path,journal_mode,updated_at) VALUES(?,?,?,?,?,0,?,?,?,?) ON CONFLICT(consumer_id) DO UPDATE SET bot_id=excluded.bot_id,session_id=excluded.session_id,chat_hash=excluded.chat_hash,project_id=excluded.project_id,database_instance_id=excluded.database_instance_id,absolute_db_path=excluded.absolute_db_path,journal_mode=excluded.journal_mode,updated_at=excluded.updated_at''', 9),
    'seen': ('UPDATE memory_consumers SET last_seen_revision=max(last_seen_revision,?),updated_at=? WHERE consumer_id=?', 3),
    'audit': ('INSERT OR IGNORE INTO audit_log(id,op,status,detail,created_at,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id) VALUES(?,?,?,?,?,?,?,?,?,?)', 10),
    'metric': ('''INSERT INTO memory_online_metrics(day_utc,operation,outcome,latency_bucket_ms,sample_count,duration_sum_ms,duration_max_ms) VALUES(?,?,?,?,1,?,?) ON CONFLICT(day_utc,operation,outcome,latency_bucket_ms) DO UPDATE SET sample_count=sample_count+1,duration_sum_ms=duration_sum_ms+excluded.duration_sum_ms,duration_max_ms=max(duration_max_ms,excluded.duration_max_ms)''', 6),
    'metric_expire': ('DELETE FROM memory_online_metrics WHERE day_utc<?', 1),
}


class TerminalDelivery:
    """One last admission for the actual upper caller, not a permission engine.

    All callbacks/receipt serialization finish in prepare. Existing transaction
    ownership then fences the ORIGINAL images and applies only these fixed own
    effects. Full rows/meta and measured total_changes are checked in that TX.
    Native commit is the last effect: no recorder/guard/diagnostic callback, new
    authority read/adoption or revocation-after-committed-ACK follows it. This is
    an in-function SQLite admission snapshot, not a lease for host speech or an
    OS-atomic return. Actor/config/erasure carriers are never refreshed.
    """
    def __init__(self, provider):
        self.provider = provider
        self.fences = []
        self.effects = []
        self.events = {}
        self.claim_after = {}
        self.delta = 0
        self.phase = 'prepare'
        self.diagnostics = None
        self.measurement = None
        self.reason = None
        self.policies = {}
        self.consumer = None
        self.audit_preparations = []

    def detach_audits(self, session_id, cancel):
        if self.phase != "prepare" or current_delivery(self.provider) is not self:
            raise DeliveryWithheld("detached_audit_original_parent_required")
        staged = PreparedAudits(_audit_binding(self.provider, session_id), cancel)
        self.audit_preparations.append((staged.attempt, staged))
        return staged

    def adopt_audits(self, staged):
        if (self.phase != "prepare" or type(staged) is not PreparedAudits
                or current_delivery(self.provider) is not self
                or not any(attempt is staged.attempt and item is staged for attempt, item in self.audit_preparations)):
            raise DeliveryWithheld("detached_audit_original_attempt_required")
        for values in staged.take(self.provider):
            self.queue("audit", values)

    def retain(self, fence):
        if (self.phase != 'prepare' or type(fence) is not DisclosureFence or
                fence.provider is not self.provider or fence.foreign or
                fence.conn is not self.provider._conn):
            raise DeliveryWithheld('terminal_original_owner_required')
        if not any(f is fence for f in self.fences):
            self.fences.append(fence)

    def queue(self, kind, values):
        if (self.phase != 'prepare' or kind not in EFFECTS or
                len(values) != EFFECTS[kind][1] or len(self.effects) >= MAX_ROWS * 4 or
                any(type(v) not in (str, int, float, type(None)) for v in values)):
            raise DeliveryWithheld('terminal_effect_unproven')
        if kind in {'recall_count', 'last_recalled'} and not any(
                str(values[-1]) in f.purposes for f in self.fences):
            raise DeliveryWithheld('terminal_tracking_source_not_retained')
        self.effects.append((kind, tuple(values)))
        if kind == 'consumer':
            self.consumer = (values[0], values[3])

    def recall(self, rows, stamp, event_ids):
        for cid, row in rows.items():
            self.queue('recall_count', (stamp, stamp, cid))
            event = (event_ids[cid], cid, '', float(row.get('score') or 0), -1, '', 'pending', stamp)
            self.queue('recall_event', event)
            self.events[event_ids[cid]] = cid

    def checkpoint(self):
        return len(self.effects), dict(self.events)

    def restore_preparation(self, checkpoint):
        # Drop only uncommitted own intents. Never undo a callback's DB/ACL write.
        length, events = checkpoint
        del self.effects[length:]
        self.events = events

    def owns_snapshot(self, fence):
        p = self.provider
        return (type(self) is TerminalDelivery and self.phase in {'owned', 'verify'}
                and any(f is fence for f in self.fences)
                and fence.conn is p._conn is p._owned_conn
                and p._claim_tx_connection is fence.conn
                and p._claim_tx_thread == threading.get_ident()
                and fence.conn.in_transaction)

    def expected_epoch(self, fence):
        if not self.owns_snapshot(fence):
            raise DeliveryWithheld('terminal_transaction_provenance_missing')
        # Original meta/data_version stay EXACT; only measured own changes move.
        return (fence.epoch[0], fence.epoch[1], fence.epoch[2] + self.delta)

    def expected_image(self, fence, key):
        if not self.owns_snapshot(fence):
            raise DeliveryWithheld('terminal_transaction_provenance_missing')
        if key[0] != 'claims' or not self.claim_after:
            return fence.selectors[key]
        return fingerprint([self.claim_after.get(str(row['id']), row) for row in fence.images[key]])

    def _apply(self, conn):
        originals = {}
        for fence in self.fences:
            for key, rows in fence.images.items():
                if key[0] == 'claims':
                    for row in rows:
                        cid = str(row['id'])
                        if cid in originals and originals[cid] != row:
                            raise DeliveryWithheld('terminal_original_images_disagree')
                        originals[cid] = dict(row)
        count = conn.total_changes
        affected = 0
        for kind, values in self.effects:
            metric_before = None
            consumer_before = None
            if kind == 'metric':
                metric_before = conn.execute('SELECT sample_count,duration_sum_ms,duration_max_ms FROM memory_online_metrics WHERE day_utc=? AND operation=? AND outcome=? AND latency_bucket_ms=?', values[:4]).fetchone()
            elif kind == 'consumer':
                consumer_before = conn.execute('SELECT last_seen_revision FROM memory_consumers WHERE consumer_id=?', values[:1]).fetchone()
            cursor = conn.execute(EFFECTS[kind][0], values)
            rowcount = cursor.rowcount
            cursor.close()
            if rowcount < 0:
                raise DeliveryWithheld('terminal_effect_count_unknown')
            affected += rowcount
            if kind in {'recall_count', 'last_recalled'}:
                cid = str(values[-1])
                if rowcount != 1 or cid not in originals:
                    raise DeliveryWithheld('terminal_claim_effect_missing')
                row = self.claim_after.setdefault(cid, dict(originals[cid]))
                if kind == 'recall_count':
                    row['access_count'] += 1
                    row['recall_count'] += 1
                    row['last_accessed'], row['last_recalled'] = values[:2]
                else:
                    row['last_recalled'] = values[0]
            elif kind in {'recall_event', 'feedback', 'consumer', 'seen', 'metric', 'sync_bundle'} and rowcount != 1:
                raise DeliveryWithheld('terminal_accounting_not_written')
            if kind == 'sync_bundle':
                row = conn.execute('SELECT id,path,summary,payload_hash,direction,created_at FROM sync_bundles WHERE id=?', values[:1]).fetchone()
                if row is None or tuple(row) != values:
                    raise DeliveryWithheld('terminal_sync_bundle_readback_unproven')
            elif kind == 'feedback':
                row = conn.execute('SELECT id,recall_event_id,claim_id,query,retrieved,injected,used,helpful,irrelevant,contradicted,harmful,answer_id,feedback_source,notes,created_at,outcome,idempotency_key FROM recall_feedback WHERE id=?', values[:1]).fetchone()
                if row is None or tuple(row) != values:
                    raise DeliveryWithheld('terminal_feedback_readback_unproven')
            elif kind == 'consumer':
                row = conn.execute('SELECT consumer_id,bot_id,session_id,chat_hash,project_id,database_instance_id,absolute_db_path,journal_mode,updated_at,last_seen_revision FROM memory_consumers WHERE consumer_id=?', values[:1]).fetchone()
                expected = (*values, int(consumer_before[0]) if consumer_before else 0)
                if row is None or tuple(row) != expected:
                    raise DeliveryWithheld('terminal_consumer_readback_unproven')
            elif kind == 'metric':
                row = conn.execute('SELECT sample_count,duration_sum_ms,duration_max_ms FROM memory_online_metrics WHERE day_utc=? AND operation=? AND outcome=? AND latency_bucket_ms=?', values[:4]).fetchone()
                old = tuple(metric_before) if metric_before else (0, 0, 0)
                if row is None or tuple(row) != (old[0]+1, old[1]+values[4], max(old[2],values[5])):
                    raise DeliveryWithheld('terminal_metric_readback_unproven')
            elif kind == 'audit':
                row = conn.execute('SELECT id,op,status,detail,created_at,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id FROM audit_log WHERE id=?', values[:1]).fetchone()
                if row is None or tuple(row) != values:
                    raise DeliveryWithheld('terminal_audit_readback_unproven')
        self.delta = conn.total_changes - count
        if self.delta != affected:
            raise DeliveryWithheld('terminal_unaccounted_trigger_effect')
        # Read back every exact event linkage, not a callback's truthy result.
        for event_id, cid in self.events.items():
            row = conn.execute('SELECT id,claim_id,query,score,used,answer_id,outcome,created_at FROM recall_events WHERE id=?', (event_id,)).fetchone()
            expected = next(values for kind, values in self.effects if kind == 'recall_event' and values[0] == event_id)
            if row is None or tuple(row) != expected or str(row[1]) != cid:
                raise DeliveryWithheld('terminal_event_linkage_unproven')
        for kind, values in self.effects:
            if kind == 'seen':
                row = conn.execute('SELECT last_seen_revision FROM memory_consumers WHERE consumer_id=?', (values[2],)).fetchone()
                if row is None or int(row[0]) < values[0]:
                    raise DeliveryWithheld('terminal_ack_readback_missing')

    def commit(self):
        if getattr(self.provider, '_transaction_quarantine', None) is not None:
            for _, staged in self.audit_preparations:
                if staged.outcome == "queued":
                    staged.outcome, staged.persisted_count = "unknown", None
            primary = getattr(self.provider, '_transaction_primary', None)
            if primary is not None:
                raise primary
            raise RuntimeError('terminal_owner_quarantine_UNKNOWN')
        if self.phase != 'prepare' or not self.fences:
            self.reason = 'terminal_original_carrier_missing'
            return False
        conn = self.fences[0].conn
        if any(f.conn is not conn for f in self.fences):
            self.reason = 'terminal_writer_transition_unavailable'
            return False
        try:
            # Policy/visibility/sharing callbacks all precede native BEGIN.
            # Native tail checks original images and prepared eligibility SQL.
            for fence in self.fences:
                source = fence.source_conn
                if source is not None and (source._graph_read_state != 'closed'
                        or source._graph_read_shared is not self.provider._conn
                        or source._graph_read_fence is not fence
                        or source in getattr(self.provider, '_graph_reader_connections', {})):
                    raise DeliveryWithheld('terminal_reader_cleanup_unproven')
                if not fence.finish():
                    raise DeliveryWithheld('terminal_protected_drift')
                for purpose in {p[0] for p in fence.purposes.values()}:
                    self.policies[(id(fence), purpose)] = self.provider._claim_metadata_eligibility_sql(purpose)
            # _claim_transaction runs its callbacks BEFORE BEGIN for this exact
            # terminal owner. Other callers keep their historical journal path.
            with self.provider._claim_transaction(conn, _terminal=self):
                self.phase = 'owned'
                if not all(f.finish(_delivery=self) for f in self.fences):
                    raise DeliveryWithheld('terminal_protected_drift')
                if any(staged.outcome == "queued" and (staged.cancel.is_set() or staged.parent_thread != threading.get_ident() or attempt is not staged.attempt) for attempt, staged in self.audit_preparations):
                    raise DeliveryWithheld("detached_audit_attempt_cancelled")
                before = conn.total_changes
                self._apply(conn)
                self.phase = 'verify'
                if any(staged.outcome == "queued" and (staged.cancel.is_set() or staged.parent_thread != threading.get_ident() or attempt is not staged.attempt) for attempt, staged in self.audit_preparations):
                    raise DeliveryWithheld("detached_audit_attempt_cancelled")
                if not all(f.finish(_delivery=self) for f in self.fences):
                    raise DeliveryWithheld('terminal_protected_effect_drift')
                self.measurement = {'before_changes': before, 'after_changes': conn.total_changes,
                                    'owned_changes': self.delta, 'commit_returned': False}
            # No callbacks here. commit_total_changes and native idle have been
            # attested by the transaction owner at its actual commit return.
            self.phase = 'committed'
            # Plain private outcome metadata, not a post-commit callback.
            for _, staged in self.audit_preparations:
                if staged.outcome == 'queued':
                    staged.outcome, staged.persisted_count = 'persisted', staged.prepared_count
            if self.diagnostics is not None:
                self.provider._last_prefetch_diagnostics = self.diagnostics
            if self.consumer is not None:
                self.provider._consumer_id, self.provider.origin_chat_hash = self.consumer
            return True
        except DeliveryWithheld as exc:
            if getattr(self.provider, '_transaction_quarantine', None) is not None:
                for _, staged in self.audit_preparations:
                    if staged.outcome == "queued":
                        staged.outcome, staged.persisted_count = "unknown", None
                # An unconfirmed rollback is a primary error, not a normal
                # privacy withdrawal. Preserve its identity and retained owner.
                raise
            for _, staged in self.audit_preparations:
                if staged.outcome == "queued":
                    staged.outcome, staged.persisted_count = "withheld", 0
            self.reason = str(exc)
            self.phase = 'withheld'
            return False
        except Exception:
            if getattr(self.provider, '_transaction_quarantine', None) is not None:
                for _, staged in self.audit_preparations:
                    if staged.outcome == "queued":
                        staged.outcome, staged.persisted_count = "unknown", None
                # UNKNOWN commit/ownership is not an admitted ACK followed by
                # ordinary late-empty output. Preserve the primary refusal.
                raise
            for _, staged in self.audit_preparations:
                if staged.outcome == "queued":
                    staged.outcome, staged.persisted_count = "withheld", 0
            self.reason = 'terminal_commit_unavailable'
            self.phase = 'withheld'
            return False


def withheld_payload(kind):
    """Prepared before admission; contains no source-derived metadata/linkage."""
    if kind in {'memory_wiki_get_project_context', '_get_project_context'}:
        return {'project_id': '', 'profile': None, 'claims': [], 'task_capsules': [], 'graph': {'entities': [], 'relations': []}, 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_preference_layer', '_preference_layer'}:
        return {'query': '', 'policy_order': [], 'rules': [], 'items': [], 'count': 0, 'fresh_instruction_note': '', 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_why_believe', '_why_believe'}:
        return {'claim': {}, 'evidence': [], 'contradictions': [], 'mutations': [], 'recalls': [], 'why': {}, 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_dashboard', '_dashboard'}:
        return {'success': True, 'counts': {}, 'topics': [], 'top_claims': [], 'stale': [], 'contradictions': [], 'review_pending': 0, 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_graph_query', '_graph_query'}:
        return {'entities': [], 'relations': [], 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_summarize_topic', '_summarize_topic'}:
        return {'topic': '', 'summary': '', 'claim_count': 0, 'key_facts': [], 'contradictions': 0, 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_export', '_export'}:
        return {'success': True, 'claims': [], 'evidence': [], 'contradictions': [], 'review_queue': [], 'secret_quarantine': [], 'changes': [], 'mutations': [], 'project_profiles': [], 'entities': [], 'relations': [], 'preference_rules': [], 'sync_bundles': [], 'audit': [], 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_export_bundle', '_export_bundle'}:
        return {'id': '', 'path': '', 'payload_hash': '', 'counts': {}, 'payload': {}, 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_claim_history', '_claim_history'}:
        return {'claim_id': '', 'current': {}, 'history': [], 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_get_page', '_get_page'}:
        return {'path': '', 'content': '', 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_document_query', 'memory_wiki_document_source',
                'memory_wiki_document_unit_context', 'memory_wiki_document_neighbors',
                'memory_wiki_document_status', 'memory_wiki_source_list'}:
        return {'sources': [], 'units': [], 'edges': [], 'nodes': [], 'results': [],
                'counts': {}, 'retrieval': {}, 'disclosure_status': 'withheld'}
    if kind in {'memory_wiki_code_graph_query', 'memory_wiki_code_line_context',
                'memory_wiki_code_graph_neighbors', 'memory_wiki_code_graph_status',
                'memory_wiki_code_claim_query', 'memory_wiki_symbol_history',
                'memory_wiki_repository_context'}:
        return {'results': [], 'lines': [], 'symbols': [], 'nodes': [], 'edges': [],
                'repositories': [], 'claims': [], 'history': [], 'totals': {},
                'retrieval': {}, 'disclosure_status': 'withheld'}
    if kind == 'memory_wiki_query':
        return {'success': True, 'claims': [], 'disclosure_status': 'withheld'}
    if kind == 'memory_wiki_recall':
        return {'success': True, 'items': [], 'evidence_count': 0, 'chars_used': 0,
                'intent_plan': {}, 'conflicts': False, 'conflict_check': {'status': 'unknown'},
                'recall_tracking': {'status': 'withheld', 'events': [],
                                    'answer_linkage': {'claim_ids': [], 'recall_event_ids': []}},
                'answer_policy': {'citations': [], 'status': 'insufficient_evidence'},
                'disclosure_status': 'withheld'}
    return {'success': True, 'context': '', 'used_chars': 0, 'chunk_count': 0,
            'sources': {}, 'plan': {}, 'omitted': {}, 'memory_revision_watermark': 0,
            'results': [], 'structured_pack': {}, 'disclosure_status': 'withheld'}

