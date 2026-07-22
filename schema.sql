CREATE TABLE claims(
                    id TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL NOT NULL DEFAULT 0.70,
                    source TEXT NOT NULL DEFAULT '',
                    evidence TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    freshness_at INTEGER NOT NULL,
                    hash TEXT NOT NULL UNIQUE
                , salience REAL NOT NULL DEFAULT 0.70, access_count INTEGER NOT NULL DEFAULT 0, last_accessed INTEGER NOT NULL DEFAULT 0, quality REAL NOT NULL DEFAULT 0.50, pinned INTEGER NOT NULL DEFAULT 0, normalized_claim TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'fact', source_type TEXT NOT NULL DEFAULT 'unknown', last_verified_at INTEGER NOT NULL DEFAULT 0, verification_status TEXT NOT NULL DEFAULT 'unverified', scope TEXT NOT NULL DEFAULT 'global', project_id TEXT NOT NULL DEFAULT '', usefulness REAL NOT NULL DEFAULT 0.50,
                temporal_status TEXT NOT NULL DEFAULT 'current',
                valid_from INTEGER NOT NULL DEFAULT 0,
                valid_to INTEGER NOT NULL DEFAULT 0,
                superseded_by_id TEXT NOT NULL DEFAULT '',
                memory_class TEXT NOT NULL DEFAULT 'durable',
                decay_policy TEXT NOT NULL DEFAULT 'default',
                expires_at INTEGER NOT NULL DEFAULT 0,
                successful_recall_count INTEGER NOT NULL DEFAULT 0,
                irrelevant_recall_count INTEGER NOT NULL DEFAULT 0,
                harmful_recall_count INTEGER NOT NULL DEFAULT 0,
                contradicted_count INTEGER NOT NULL DEFAULT 0,
                last_successful_recall_at INTEGER NOT NULL DEFAULT 0, recall_count INTEGER NOT NULL DEFAULT 0, last_recalled INTEGER NOT NULL DEFAULT 0, trust_class TEXT NOT NULL DEFAULT 'fact', trust_score REAL NOT NULL DEFAULT 0.55, risk TEXT NOT NULL DEFAULT 'low', custody TEXT NOT NULL DEFAULT '{}', quarantined_at INTEGER NOT NULL DEFAULT 0, secrecy_level TEXT NOT NULL DEFAULT 'public', semantic_tokens TEXT DEFAULT '');
CREATE TABLE evidence(
                    id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'support',
                    text TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
                );
CREATE TABLE contradictions(
                    id TEXT PRIMARY KEY,
                    claim_a TEXT NOT NULL,
                    claim_b TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at INTEGER NOT NULL,
                    resolved_at INTEGER, resolution TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(claim_a) REFERENCES claims(id) ON DELETE CASCADE,
                    FOREIGN KEY(claim_b) REFERENCES claims(id) ON DELETE CASCADE
                );
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE review_queue(
                id TEXT PRIMARY KEY, candidate TEXT NOT NULL, topic TEXT NOT NULL DEFAULT 'general', source TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '', suggested_claim TEXT NOT NULL DEFAULT '', suggested_topic TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT .5,
                salience REAL NOT NULL DEFAULT .5, status TEXT NOT NULL DEFAULT 'pending', claim_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE memory_changes(
                id TEXT PRIMARY KEY, action TEXT NOT NULL, claim_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
CREATE TABLE recall_events(
                id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, query TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0, used REAL NOT NULL DEFAULT -1, created_at INTEGER NOT NULL);
CREATE TABLE topic_aliases(alias TEXT PRIMARY KEY, topic TEXT NOT NULL);
CREATE TABLE secret_index(
                id TEXT PRIMARY KEY, subject TEXT NOT NULL, scope TEXT NOT NULL, secret_type TEXT NOT NULL DEFAULT 'credential',
                locator TEXT NOT NULL DEFAULT '', value TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT .85, salience REAL NOT NULL DEFAULT .85, status TEXT NOT NULL DEFAULT 'active',
                last_verified_at INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TABLE post_task_log(
                id TEXT PRIMARY KEY, summary TEXT NOT NULL, topic TEXT NOT NULL DEFAULT 'operations', changed_files TEXT NOT NULL DEFAULT '[]',
                backups TEXT NOT NULL DEFAULT '[]', verification TEXT NOT NULL DEFAULT '', services TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'post_task', created_at INTEGER NOT NULL, memory_role TEXT NOT NULL DEFAULT 'environment', type TEXT NOT NULL DEFAULT 'task');
CREATE TABLE backups(id TEXT PRIMARY KEY, path TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE decisions(id TEXT PRIMARY KEY, decision TEXT NOT NULL, rationale TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT 'decisions', alternatives TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'tool', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TABLE mistakes(id TEXT PRIMARY KEY, trigger TEXT NOT NULL, mistake TEXT NOT NULL, fix TEXT NOT NULL DEFAULT '', prevention TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT 'lessons', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TABLE project_profiles(project_id TEXT PRIMARY KEY, root TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT '', commands TEXT NOT NULL DEFAULT '[]', services TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL);
CREATE TABLE task_capsules(id TEXT PRIMARY KEY, intent TEXT NOT NULL, topic TEXT NOT NULL DEFAULT 'tasks', plan TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]', commands TEXT NOT NULL DEFAULT '[]', errors TEXT NOT NULL DEFAULT '[]', fixes TEXT NOT NULL DEFAULT '[]', verification TEXT NOT NULL DEFAULT '', followups TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TABLE entities(id TEXT PRIMARY KEY, name TEXT NOT NULL, entity_type TEXT NOT NULL DEFAULT 'thing', aliases TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TABLE relations(id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL, confidence REAL NOT NULL DEFAULT .8, evidence TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TABLE audit_log(id TEXT PRIMARY KEY, op TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
CREATE TABLE secret_quarantine(
                id TEXT PRIMARY KEY, table_name TEXT NOT NULL, row_id TEXT NOT NULL, field TEXT NOT NULL,
                redacted_value TEXT NOT NULL DEFAULT '', original_hash TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL, resolved_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(table_name,row_id,field,original_hash));
CREATE TABLE sqlite_stat1(tbl,idx,stat);
CREATE INDEX idx_claims_topic ON claims(topic);
CREATE INDEX idx_claims_updated ON claims(updated_at);
CREATE INDEX idx_claims_freshness ON claims(freshness_at);
CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_fresh ON claims(freshness_at);
CREATE INDEX idx_claims_scope_project ON claims(scope, project_id);
CREATE INDEX idx_review_queue_status ON review_queue(status, updated_at);
CREATE INDEX idx_memory_changes_created ON memory_changes(created_at);
CREATE INDEX idx_recall_events_claim ON recall_events(claim_id, created_at);
CREATE INDEX idx_secret_index_subject ON secret_index(subject, scope, status);
CREATE INDEX idx_relations_subject ON relations(subject,predicate);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);
CREATE INDEX idx_secret_quarantine_status ON secret_quarantine(status, created_at);
CREATE INDEX idx_claims_recall_scope ON claims(status, scope, project_id, topic, risk, trust_score, updated_at);
CREATE INDEX idx_claims_priority ON claims(status, pinned, salience, usefulness, trust_score, freshness_at);
CREATE INDEX idx_claims_type_topic ON claims(status, type, topic, updated_at);
CREATE INDEX idx_claims_hash_norm ON claims(hash, normalized_claim);
CREATE VIRTUAL TABLE claims_fts USING fts5(id UNINDEXED, claim, normalized, topic, evidence, search_text, tokenize='unicode61')
/* claims_fts(id,claim,normalized,topic,evidence,search_text) */;
CREATE TABLE IF NOT EXISTS 'claims_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE IF NOT EXISTS 'claims_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS 'claims_fts_content'(id INTEGER PRIMARY KEY, c0, c1, c2, c3, c4, c5);
CREATE TABLE IF NOT EXISTS 'claims_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE IF NOT EXISTS 'claims_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE claims_history(
        id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, claim TEXT NOT NULL, topic TEXT NOT NULL,
        confidence REAL, salience REAL, status TEXT, scope TEXT, project_id TEXT,
        trust_class TEXT, trust_score REAL, quality REAL, secrecy_level TEXT DEFAULT 'public',
        changed_at INTEGER NOT NULL, change_type TEXT NOT NULL DEFAULT 'update',
        FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE);
CREATE INDEX idx_claims_history_claim ON claims_history(claim_id, changed_at);
CREATE INDEX idx_claims_history_topic ON claims_history(topic, changed_at);
CREATE TRIGGER trg_claims_history BEFORE UPDATE ON claims
        WHEN OLD.status != 'deleted' AND (OLD.claim != NEW.claim OR OLD.topic != NEW.topic OR OLD.confidence != NEW.confidence OR OLD.salience != NEW.salience OR OLD.status != NEW.status OR OLD.scope != NEW.scope)
        BEGIN
            INSERT INTO claims_history(id, claim_id, claim, topic, confidence, salience, status, scope, project_id, trust_class, trust_score, quality, secrecy_level, changed_at, change_type)
            VALUES (hex(randomblob(16)), OLD.id, OLD.claim, OLD.topic, OLD.confidence, OLD.salience, OLD.status, OLD.scope, OLD.project_id, OLD.trust_class, OLD.trust_score, OLD.quality, COALESCE(OLD.secrecy_level,'public'), CAST((julianday('now') - 2440587.5) * 86400 AS INTEGER), 'update');
        END;
CREATE TABLE claim_embeddings (
        claim_id TEXT PRIMARY KEY,
        embedding BLOB NOT NULL,
        dims INTEGER DEFAULT 0,
        model TEXT DEFAULT 'deepseek-v4-pro',
        created_at INTEGER,
        FOREIGN KEY (claim_id) REFERENCES claims(id)
    );
CREATE TABLE entity_embeddings (
        entity_id TEXT PRIMARY KEY,
        embedding BLOB NOT NULL,
        dims INTEGER DEFAULT 0,
        model TEXT DEFAULT 'deepseek-v4-pro',
        created_at INTEGER,
        FOREIGN KEY (entity_id) REFERENCES entities(id)
    );

-- v1.15.0: Transactional outbox
CREATE TABLE IF NOT EXISTS index_outbox(
    id TEXT PRIMARY KEY,
    operation TEXT DEFAULT 'upsert',
    object_type TEXT DEFAULT 'claim',
    object_id TEXT NOT NULL,
    payload_json TEXT,
    payload_hash TEXT,
    attempts INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    last_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- v1.15.0: Resumable reindex
CREATE TABLE IF NOT EXISTS reindex_jobs(
    id TEXT PRIMARY KEY,
    source_collection TEXT NOT NULL,
    target_collection TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    total_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    started_at INTEGER NOT NULL,
    completed_at INTEGER
);

-- v1.15.0: Recall feedback loop
CREATE TABLE IF NOT EXISTS recall_feedback(
    id TEXT PRIMARY KEY,
    recall_event_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    retrieved INTEGER DEFAULT 1,
    injected INTEGER DEFAULT 0,
    used INTEGER DEFAULT 0,
    helpful REAL DEFAULT 0,
    irrelevant INTEGER DEFAULT 0,
    contradicted INTEGER DEFAULT 0,
    harmful INTEGER DEFAULT 0,
    answer_id TEXT DEFAULT '',
    feedback_source TEXT DEFAULT 'auto',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);
