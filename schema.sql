-- Hermes Memory Wiki v1.18.4 runtime schema snapshot
-- REFERENCE ONLY. The authoritative upgrade path is MemoryWikiProvider._migrate().
-- Generated from an empty database after all runtime migrations.
PRAGMA foreign_keys=ON;

-- table: audit_log
CREATE TABLE audit_log(id TEXT PRIMARY KEY, op TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);

-- table: backups
CREATE TABLE backups(id TEXT PRIMARY KEY, path TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);

-- table: claims
CREATE TABLE claims(
                id TEXT PRIMARY KEY, claim TEXT NOT NULL, topic TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                confidence REAL NOT NULL DEFAULT .70, salience REAL NOT NULL DEFAULT .70, source TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, freshness_at INTEGER NOT NULL, access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed INTEGER NOT NULL DEFAULT 0, hash TEXT NOT NULL UNIQUE, quality REAL NOT NULL DEFAULT 0.50, pinned INTEGER NOT NULL DEFAULT 0, normalized_claim TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'fact', source_type TEXT NOT NULL DEFAULT 'unknown', last_verified_at INTEGER NOT NULL DEFAULT 0, verification_status TEXT NOT NULL DEFAULT 'unverified', scope TEXT NOT NULL DEFAULT 'global', project_id TEXT NOT NULL DEFAULT '', usefulness REAL NOT NULL DEFAULT 0.50, recall_count INTEGER NOT NULL DEFAULT 0, last_recalled INTEGER NOT NULL DEFAULT 0, trust_class TEXT NOT NULL DEFAULT 'fact', trust_score REAL NOT NULL DEFAULT 0.55, risk TEXT NOT NULL DEFAULT 'low', custody TEXT NOT NULL DEFAULT '{}', quarantined_at INTEGER NOT NULL DEFAULT 0, quality_flags TEXT NOT NULL DEFAULT '[]', source_ref TEXT NOT NULL DEFAULT '', derived_from TEXT NOT NULL DEFAULT '', review_state TEXT NOT NULL DEFAULT 'accepted', secrecy_level TEXT NOT NULL DEFAULT 'public', temporal_status TEXT NOT NULL DEFAULT 'current', valid_from INTEGER NOT NULL DEFAULT 0, valid_to INTEGER NOT NULL DEFAULT 0, superseded_by_id TEXT NOT NULL DEFAULT '', memory_class TEXT NOT NULL DEFAULT 'durable', decay_policy TEXT NOT NULL DEFAULT 'default', expires_at INTEGER NOT NULL DEFAULT 0, successful_recall_count INTEGER NOT NULL DEFAULT 0, irrelevant_recall_count INTEGER NOT NULL DEFAULT 0, harmful_recall_count INTEGER NOT NULL DEFAULT 0, contradicted_count INTEGER NOT NULL DEFAULT 0, last_successful_recall_at INTEGER NOT NULL DEFAULT 0, origin_bot_id TEXT NOT NULL DEFAULT '', origin_session_id TEXT NOT NULL DEFAULT '', origin_chat_hash TEXT NOT NULL DEFAULT '', source_kind TEXT NOT NULL DEFAULT 'other', visibility_scope TEXT NOT NULL DEFAULT 'global', memory_revision INTEGER NOT NULL DEFAULT 0, event_at INTEGER NOT NULL DEFAULT 0, event_timezone TEXT NOT NULL DEFAULT 'UTC');

-- table: claims_fts
CREATE VIRTUAL TABLE claims_fts USING fts5(id UNINDEXED, claim, normalized, topic, evidence, search_text, tokenize='unicode61');

-- table: claims_history
CREATE TABLE claims_history(
                id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, claim TEXT NOT NULL, topic TEXT NOT NULL,
                confidence REAL, salience REAL, status TEXT, scope TEXT, project_id TEXT,
                trust_class TEXT, trust_score REAL, quality REAL, secrecy_level TEXT DEFAULT 'public',
                changed_at INTEGER NOT NULL, change_type TEXT NOT NULL DEFAULT 'update',
                FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE);

-- table: claims_simhash
CREATE TABLE claims_simhash(
                id TEXT PRIMARY KEY, simhash INTEGER NOT NULL,
                FOREIGN KEY(id) REFERENCES claims(id) ON DELETE CASCADE);

-- table: code_claim_metadata
CREATE TABLE code_claim_metadata(
                claim_id TEXT PRIMARY KEY, repository_id TEXT NOT NULL DEFAULT '',
                commit_sha TEXT DEFAULT '', file_path TEXT DEFAULT '',
                symbol_id TEXT DEFAULT '', symbol_revision TEXT DEFAULT '',
                content_hash TEXT DEFAULT '', claim_type TEXT DEFAULT 'code_claim',
                FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE CASCADE);

-- table: contradictions
CREATE TABLE contradictions(id TEXT PRIMARY KEY, claim_a TEXT NOT NULL, claim_b TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', resolution TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, resolved_at INTEGER, severity TEXT NOT NULL DEFAULT 'possible', FOREIGN KEY(claim_a) REFERENCES claims(id) ON DELETE CASCADE, FOREIGN KEY(claim_b) REFERENCES claims(id) ON DELETE CASCADE);

-- table: decisions
CREATE TABLE decisions(id TEXT PRIMARY KEY, decision TEXT NOT NULL, rationale TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT 'decisions', alternatives TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'tool', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: entities
CREATE TABLE entities(id TEXT PRIMARY KEY, name TEXT NOT NULL, entity_type TEXT NOT NULL DEFAULT 'thing', aliases TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: evidence
CREATE TABLE evidence(id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'support', text TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE);

-- table: index_outbox
CREATE TABLE index_outbox(
    id TEXT PRIMARY KEY,operation TEXT DEFAULT 'upsert',object_type TEXT DEFAULT 'claim',
    object_id TEXT NOT NULL,payload_json TEXT,payload_hash TEXT,attempts INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',last_error TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
    worker_id TEXT NOT NULL DEFAULT '',lease_until INTEGER NOT NULL DEFAULT 0,
    next_retry_at INTEGER NOT NULL DEFAULT 0);

-- table: integration_events
CREATE TABLE integration_events(
                producer TEXT NOT NULL, event_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
                result_claim_id TEXT NOT NULL DEFAULT '', processed_at INTEGER NOT NULL,
                PRIMARY KEY(producer,event_id));

-- table: memory_changes
CREATE TABLE memory_changes(
                id TEXT PRIMARY KEY, action TEXT NOT NULL, claim_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);

-- table: memory_consumers
CREATE TABLE memory_consumers(
                consumer_id TEXT PRIMARY KEY,
                bot_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                chat_hash TEXT NOT NULL DEFAULT '',
                project_id TEXT NOT NULL DEFAULT '',
                last_seen_revision INTEGER NOT NULL DEFAULT 0,
                database_instance_id TEXT NOT NULL DEFAULT '',
                absolute_db_path TEXT NOT NULL DEFAULT '',
                journal_mode TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL DEFAULT 0);

-- table: memory_mutations
CREATE TABLE memory_mutations(
                id TEXT PRIMARY KEY, batch_id TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT 'memory-wiki', operation TEXT NOT NULL,
                target_table TEXT NOT NULL DEFAULT '', target_id TEXT NOT NULL DEFAULT '', before_json TEXT NOT NULL DEFAULT '', after_json TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '', reversible INTEGER NOT NULL DEFAULT 1, undone_at INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);

-- table: meta
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);

-- table: mistakes
CREATE TABLE mistakes(id TEXT PRIMARY KEY, trigger TEXT NOT NULL, mistake TEXT NOT NULL, fix TEXT NOT NULL DEFAULT '', prevention TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT 'lessons', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: patch_outcomes
CREATE TABLE patch_outcomes(
                repository_id TEXT NOT NULL, patch_id TEXT NOT NULL,
                claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
                outcome TEXT NOT NULL, commit_sha TEXT NOT NULL DEFAULT '',
                old_content_hash TEXT NOT NULL DEFAULT '', new_content_hash TEXT NOT NULL DEFAULT '',
                changed_files_json TEXT NOT NULL DEFAULT '[]',
                changed_symbols_json TEXT NOT NULL DEFAULT '[]',
                validation_report_json TEXT NOT NULL DEFAULT '{}',
                rollback_steps TEXT NOT NULL DEFAULT '', source_event_id TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                PRIMARY KEY(repository_id,patch_id));

-- table: post_commit_failures
CREATE TABLE post_commit_failures(
                id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, operation TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
                resolved_at INTEGER NOT NULL DEFAULT 0);

-- table: post_task_log
CREATE TABLE post_task_log(
                id TEXT PRIMARY KEY, summary TEXT NOT NULL, topic TEXT NOT NULL DEFAULT 'operations', changed_files TEXT NOT NULL DEFAULT '[]',
                backups TEXT NOT NULL DEFAULT '[]', verification TEXT NOT NULL DEFAULT '', services TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'post_task', created_at INTEGER NOT NULL, memory_role TEXT NOT NULL DEFAULT 'environment', type TEXT NOT NULL DEFAULT 'task');

-- table: preference_rules
CREATE TABLE preference_rules(
                id TEXT PRIMARY KEY, rule TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 100,
                scope TEXT NOT NULL DEFAULT 'global', source TEXT NOT NULL DEFAULT 'system', status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: project_profiles
CREATE TABLE project_profiles(project_id TEXT PRIMARY KEY, root TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT '', commands TEXT NOT NULL DEFAULT '[]', services TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL, stack_json TEXT NOT NULL DEFAULT '{}', current_status TEXT NOT NULL DEFAULT '', last_verified_at INTEGER NOT NULL DEFAULT 0, scope TEXT NOT NULL DEFAULT 'project', source TEXT NOT NULL DEFAULT 'project_profile');

-- table: recall_events
CREATE TABLE recall_events(
                id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, query TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0, used REAL NOT NULL DEFAULT -1, created_at INTEGER NOT NULL);

-- table: recall_feedback
CREATE TABLE recall_feedback(
                id TEXT PRIMARY KEY,
                recall_event_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                query TEXT NOT NULL DEFAULT '',
                retrieved INTEGER NOT NULL DEFAULT 1,
                injected INTEGER NOT NULL DEFAULT 0,
                used INTEGER NOT NULL DEFAULT 0,
                helpful REAL NOT NULL DEFAULT 0,
                irrelevant INTEGER NOT NULL DEFAULT 0,
                contradicted INTEGER NOT NULL DEFAULT 0,
                harmful INTEGER NOT NULL DEFAULT 0,
                answer_id TEXT NOT NULL DEFAULT '',
                feedback_source TEXT NOT NULL DEFAULT 'auto',
                notes TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
            );

-- table: reindex_jobs
CREATE TABLE reindex_jobs(
                id TEXT PRIMARY KEY,
                source_collection TEXT NOT NULL,
                target_collection TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                processed_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running',
                started_at INTEGER NOT NULL,
                completed_at INTEGER, updated_at INTEGER NOT NULL DEFAULT 0, failed_ids_json TEXT NOT NULL DEFAULT '[]', last_error TEXT NOT NULL DEFAULT '',
                CHECK(status IN ('running','completed','failed','rolled_back'))
            );

-- table: relations
CREATE TABLE relations(id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL, confidence REAL NOT NULL DEFAULT .8, evidence TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: retrieval_eval_cases
CREATE TABLE retrieval_eval_cases(
                id TEXT PRIMARY KEY, query TEXT NOT NULL, must_topics TEXT NOT NULL DEFAULT '[]', must_not_topics TEXT NOT NULL DEFAULT '[]',
                must_include TEXT NOT NULL DEFAULT '[]', must_not_include TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);

-- table: review_queue
CREATE TABLE review_queue(
                id TEXT PRIMARY KEY, candidate TEXT NOT NULL, topic TEXT NOT NULL DEFAULT 'general', source TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '', suggested_claim TEXT NOT NULL DEFAULT '', suggested_topic TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT .5,
                salience REAL NOT NULL DEFAULT .5, status TEXT NOT NULL DEFAULT 'pending', claim_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);

-- table: secret_index
CREATE TABLE secret_index(
                id TEXT PRIMARY KEY, subject TEXT NOT NULL, scope TEXT NOT NULL, secret_type TEXT NOT NULL DEFAULT 'credential',
                locator TEXT NOT NULL DEFAULT '', value TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT .85, salience REAL NOT NULL DEFAULT .85, status TEXT NOT NULL DEFAULT 'active',
                last_verified_at INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE, vault_ref TEXT NOT NULL DEFAULT '', aliases_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}');

-- table: secret_quarantine
CREATE TABLE secret_quarantine(
                id TEXT PRIMARY KEY, table_name TEXT NOT NULL, row_id TEXT NOT NULL, field TEXT NOT NULL,
                redacted_value TEXT NOT NULL DEFAULT '', original_hash TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL, resolved_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(table_name,row_id,field,original_hash));

-- table: semantic_vectors
CREATE TABLE semantic_vectors(id TEXT PRIMARY KEY, vec BLOB NOT NULL, dims INTEGER NOT NULL DEFAULT 0, provider TEXT NOT NULL DEFAULT 'openrouter', model TEXT NOT NULL DEFAULT 'perplexity/pplx-embed-v1-4b', instruction_hash TEXT NOT NULL DEFAULT '', manifest_hash TEXT NOT NULL DEFAULT '', FOREIGN KEY(id) REFERENCES claims(id) ON DELETE CASCADE);

-- table: source_artifacts
CREATE TABLE source_artifacts(
                id TEXT PRIMARY KEY, source_table TEXT NOT NULL DEFAULT 'claims', source_id TEXT NOT NULL, artifact_type TEXT NOT NULL,
                redacted_excerpt TEXT NOT NULL DEFAULT '', source_ref TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'archived',
                created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: source_policies
CREATE TABLE source_policies(
                source_type TEXT PRIMARY KEY, policy_json TEXT NOT NULL, updated_at INTEGER NOT NULL);

-- table: sync_bundles
CREATE TABLE sync_bundles(
                id TEXT PRIMARY KEY, path TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', payload_hash TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL DEFAULT 'export', created_at INTEGER NOT NULL);

-- table: task_capsules
CREATE TABLE task_capsules(id TEXT PRIMARY KEY, intent TEXT NOT NULL, topic TEXT NOT NULL DEFAULT 'tasks', plan TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]', commands TEXT NOT NULL DEFAULT '[]', errors TEXT NOT NULL DEFAULT '[]', fixes TEXT NOT NULL DEFAULT '[]', verification TEXT NOT NULL DEFAULT '', followups TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE);

-- table: topic_aliases
CREATE TABLE topic_aliases(alias TEXT PRIMARY KEY, topic TEXT NOT NULL);

-- index: idx_audit_log_created
CREATE INDEX idx_audit_log_created ON audit_log(created_at);

-- index: idx_ccm_hash
CREATE INDEX idx_ccm_hash ON code_claim_metadata(repository_id, content_hash);

-- index: idx_ccm_repo
CREATE INDEX idx_ccm_repo ON code_claim_metadata(repository_id);

-- index: idx_ccm_symbol
CREATE INDEX idx_ccm_symbol ON code_claim_metadata(repository_id, symbol_id);

-- index: idx_claims_fresh
CREATE INDEX idx_claims_fresh ON claims(freshness_at);

-- index: idx_claims_hash_norm
CREATE INDEX idx_claims_hash_norm ON claims(hash, normalized_claim);

-- index: idx_claims_history_claim
CREATE INDEX idx_claims_history_claim ON claims_history(claim_id, changed_at);

-- index: idx_claims_history_topic
CREATE INDEX idx_claims_history_topic ON claims_history(topic, changed_at);

-- index: idx_claims_origin_chat
CREATE INDEX idx_claims_origin_chat ON claims(origin_chat_hash,status,memory_revision);

-- index: idx_claims_priority
CREATE INDEX idx_claims_priority ON claims(status, pinned, salience, usefulness, trust_score, freshness_at);

-- index: idx_claims_quality_flags
CREATE INDEX idx_claims_quality_flags ON claims(status, quality, trust_class, review_state);

-- index: idx_claims_recall_scope
CREATE INDEX idx_claims_recall_scope ON claims(status, scope, project_id, topic, risk, trust_score, updated_at);

-- index: idx_claims_scope_project
CREATE INDEX idx_claims_scope_project ON claims(scope, project_id);

-- index: idx_claims_simhash_val
CREATE INDEX idx_claims_simhash_val ON claims_simhash(simhash);

-- index: idx_claims_status
CREATE INDEX idx_claims_status ON claims(status);

-- index: idx_claims_topic
CREATE INDEX idx_claims_topic ON claims(topic);

-- index: idx_claims_type_topic
CREATE INDEX idx_claims_type_topic ON claims(status, type, topic, updated_at);

-- index: idx_claims_visibility_revision
CREATE INDEX idx_claims_visibility_revision ON claims(visibility_scope,memory_revision,status);

-- index: idx_entities_name
CREATE INDEX idx_entities_name ON entities(name, entity_type);

-- index: idx_integration_events_claim
CREATE INDEX idx_integration_events_claim ON integration_events(result_claim_id);

-- index: idx_memory_changes_created
CREATE INDEX idx_memory_changes_created ON memory_changes(created_at);

-- index: idx_memory_consumers_bot
CREATE INDEX idx_memory_consumers_bot ON memory_consumers(bot_id,updated_at);

-- index: idx_memory_mutations_batch
CREATE INDEX idx_memory_mutations_batch ON memory_mutations(batch_id,created_at);

-- index: idx_memory_mutations_target
CREATE INDEX idx_memory_mutations_target ON memory_mutations(target_table,target_id,created_at);

-- index: idx_outbox_lease
CREATE INDEX idx_outbox_lease ON index_outbox(status,lease_until);

-- index: idx_outbox_status
CREATE INDEX idx_outbox_status
    ON index_outbox(status,next_retry_at,created_at);

-- index: idx_patch_outcomes_claim
CREATE INDEX idx_patch_outcomes_claim ON patch_outcomes(claim_id);

-- index: idx_patch_outcomes_event
CREATE INDEX idx_patch_outcomes_event ON patch_outcomes(source_event_id);

-- index: idx_post_commit_failures_claim
CREATE INDEX idx_post_commit_failures_claim ON post_commit_failures(claim_id,created_at);

-- index: idx_preference_rules_priority
CREATE INDEX idx_preference_rules_priority ON preference_rules(status, priority, updated_at);

-- index: idx_recall_events_claim
CREATE INDEX idx_recall_events_claim ON recall_events(claim_id, created_at);

-- index: idx_recall_feedback_answer
CREATE INDEX idx_recall_feedback_answer ON recall_feedback(answer_id);

-- index: idx_recall_feedback_claim
CREATE INDEX idx_recall_feedback_claim ON recall_feedback(claim_id, created_at);

-- index: idx_reindex_status
CREATE INDEX idx_reindex_status ON reindex_jobs(status);

-- index: idx_relations_object
CREATE INDEX idx_relations_object ON relations(object,predicate);

-- index: idx_relations_subject
CREATE INDEX idx_relations_subject ON relations(subject,predicate);

-- index: idx_retrieval_eval_cases_updated
CREATE INDEX idx_retrieval_eval_cases_updated ON retrieval_eval_cases(updated_at);

-- index: idx_review_queue_status
CREATE INDEX idx_review_queue_status ON review_queue(status, updated_at);

-- index: idx_secret_index_subject
CREATE INDEX idx_secret_index_subject ON secret_index(subject, scope, status);

-- index: idx_secret_index_vault_ref
CREATE INDEX idx_secret_index_vault_ref ON secret_index(vault_ref,status);

-- index: idx_secret_quarantine_status
CREATE INDEX idx_secret_quarantine_status ON secret_quarantine(status, created_at);

-- index: idx_semantic_vectors_id
CREATE INDEX idx_semantic_vectors_id ON semantic_vectors(id);

-- index: idx_source_artifacts_source
CREATE INDEX idx_source_artifacts_source ON source_artifacts(source_table, source_id, artifact_type);

-- index: idx_sync_bundles_created
CREATE INDEX idx_sync_bundles_created ON sync_bundles(created_at);

-- trigger: trg_claims_active_content_indexes
CREATE TRIGGER trg_claims_active_content_indexes
                AFTER UPDATE OF claim,normalized_claim,topic,evidence ON claims
                WHEN NEW.status='active' AND OLD.status='active'
                BEGIN
                    DELETE FROM claims_fts WHERE id=NEW.id;
                    INSERT INTO claims_fts(id,claim,normalized,topic,evidence,search_text)
                    VALUES(
                        NEW.id,NEW.claim,COALESCE(NULLIF(NEW.normalized_claim,''),NEW.claim),
                        NEW.topic,NEW.evidence,
                        NEW.claim || ' ' || COALESCE(NEW.normalized_claim,'') || ' ' || NEW.topic || ' ' || NEW.evidence
                    );
                    DELETE FROM index_outbox
                     WHERE object_type='claim' AND object_id=NEW.id
                       AND status='pending'
                       AND operation IN ('upsert','embed_and_upsert','delete');
                    INSERT INTO index_outbox(
                        id,operation,object_type,object_id,payload_json,
                        created_at,updated_at,next_retry_at
                    )
                    SELECT lower(hex(randomblob(8))),'embed_and_upsert','claim',NEW.id,
                           json_object(
                               'text',COALESCE(NULLIF(NEW.normalized_claim,''),NEW.claim),
                               'topic',NEW.topic,
                               'memory_revision',NEW.memory_revision,
                               'visibility_scope',NEW.visibility_scope,
                               'origin_bot_id',NEW.origin_bot_id,
                               'origin_chat_hash',NEW.origin_chat_hash,
                               'project_id',NEW.project_id,
                               'event_at',NEW.event_at
                           ),
                           CAST(strftime('%s','now') AS INTEGER),
                           CAST(strftime('%s','now') AS INTEGER),
                           CAST(strftime('%s','now') AS INTEGER)
                     WHERE EXISTS (
                        SELECT 1 FROM meta WHERE key='semantic_enabled' AND value='1'
                     );
                END;

-- trigger: trg_claims_deactivate_indexes
CREATE TRIGGER trg_claims_deactivate_indexes
                AFTER UPDATE OF status ON claims
                WHEN OLD.status='active' AND NEW.status<>'active'
                BEGIN
                    DELETE FROM claims_fts WHERE id=NEW.id;
                    DELETE FROM index_outbox
                     WHERE object_type='claim' AND object_id=NEW.id
                       AND status='pending'
                       AND operation IN ('upsert','embed_and_upsert');
                    INSERT INTO index_outbox(
                        id,operation,object_type,object_id,payload_json,
                        created_at,updated_at,next_retry_at
                    )
                    SELECT lower(hex(randomblob(8))),'delete','claim',NEW.id,'{}',
                           CAST(strftime('%s','now') AS INTEGER),
                           CAST(strftime('%s','now') AS INTEGER),
                           CAST(strftime('%s','now') AS INTEGER)
                     WHERE EXISTS (
                        SELECT 1 FROM meta WHERE key='semantic_enabled' AND value='1'
                     ) AND NOT EXISTS (
                        SELECT 1 FROM index_outbox
                         WHERE object_type='claim' AND object_id=NEW.id
                           AND status='pending' AND operation='delete'
                     );
                END;

-- trigger: trg_claims_history
CREATE TRIGGER trg_claims_history BEFORE UPDATE ON claims
                    WHEN OLD.status != 'deleted' AND (OLD.claim != NEW.claim OR OLD.topic != NEW.topic OR OLD.confidence != NEW.confidence OR OLD.salience != NEW.salience OR OLD.status != NEW.status OR OLD.scope != NEW.scope)
                    BEGIN
                        INSERT INTO claims_history(id, claim_id, claim, topic, confidence, salience, status, scope, project_id, trust_class, trust_score, quality, secrecy_level, changed_at, change_type)
                        VALUES (hex(randomblob(16)), OLD.id, OLD.claim, OLD.topic, OLD.confidence, OLD.salience, OLD.status, OLD.scope, OLD.project_id, OLD.trust_class, OLD.trust_score, OLD.quality, COALESCE(OLD.secrecy_level,'public'), CAST((julianday('now') - 2440587.5) * 86400 AS INTEGER), 'update');
                    END;

-- trigger: trg_claims_reactivate_indexes
CREATE TRIGGER trg_claims_reactivate_indexes
                AFTER UPDATE OF status ON claims
                WHEN OLD.status<>'active' AND NEW.status='active'
                BEGIN
                    DELETE FROM claims_fts WHERE id=NEW.id;
                    INSERT INTO claims_fts(id,claim,normalized,topic,evidence,search_text)
                    VALUES(
                        NEW.id,NEW.claim,COALESCE(NULLIF(NEW.normalized_claim,''),NEW.claim),
                        NEW.topic,NEW.evidence,
                        NEW.claim || ' ' || COALESCE(NEW.normalized_claim,'') || ' ' || NEW.topic || ' ' || NEW.evidence
                    );
                    DELETE FROM index_outbox
                     WHERE object_type='claim' AND object_id=NEW.id
                       AND status='pending'
                       AND operation IN ('upsert','embed_and_upsert','delete');
                    INSERT INTO index_outbox(
                        id,operation,object_type,object_id,payload_json,
                        created_at,updated_at,next_retry_at
                    )
                    SELECT lower(hex(randomblob(8))),'embed_and_upsert','claim',NEW.id,
                           json_object(
                               'text',COALESCE(NULLIF(NEW.normalized_claim,''),NEW.claim),
                               'topic',NEW.topic,
                               'memory_revision',NEW.memory_revision,
                               'visibility_scope',NEW.visibility_scope,
                               'origin_bot_id',NEW.origin_bot_id,
                               'origin_chat_hash',NEW.origin_chat_hash,
                               'project_id',NEW.project_id,
                               'event_at',NEW.event_at
                           ),
                           CAST(strftime('%s','now') AS INTEGER),
                           CAST(strftime('%s','now') AS INTEGER),
                           CAST(strftime('%s','now') AS INTEGER)
                     WHERE EXISTS (
                        SELECT 1 FROM meta WHERE key='semantic_enabled' AND value='1'
                     );
                END;

-- trigger: trg_claims_revision_delete
CREATE TRIGGER trg_claims_revision_delete AFTER DELETE ON claims
                BEGIN
                    UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='memory_revision';
                END;

-- trigger: trg_claims_revision_insert
CREATE TRIGGER trg_claims_revision_insert AFTER INSERT ON claims
                WHEN NEW.memory_revision=0
                BEGIN
                    UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='memory_revision';
                    UPDATE claims SET memory_revision=CAST((SELECT value FROM meta WHERE key='memory_revision') AS INTEGER),
                                      event_at=CASE WHEN NEW.event_at=0 THEN NEW.created_at ELSE NEW.event_at END
                    WHERE id=NEW.id;
                END;

-- trigger: trg_claims_revision_update
CREATE TRIGGER trg_claims_revision_update
                AFTER UPDATE OF claim,topic,status,confidence,salience,source,evidence,freshness_at,
                                quality,pinned,normalized_claim,type,source_type,verification_status,
                                last_verified_at,scope,project_id,risk,custody,quality_flags,source_ref,
                                derived_from,review_state,secrecy_level,temporal_status,valid_from,valid_to,
                                superseded_by_id,memory_class,decay_policy,expires_at
                ON claims
                WHEN NEW.memory_revision=OLD.memory_revision
                BEGIN
                    UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='memory_revision';
                    UPDATE claims SET memory_revision=CAST((SELECT value FROM meta WHERE key='memory_revision') AS INTEGER)
                    WHERE id=NEW.id;
                END;

-- trigger: trg_max_claim_length
CREATE TRIGGER trg_max_claim_length BEFORE INSERT ON claims WHEN LENGTH(NEW.claim) > 8000 BEGIN SELECT RAISE(FAIL, 'claim too long (>8000 chars)'); END;

-- trigger: trg_min_claim_length
CREATE TRIGGER trg_min_claim_length BEFORE INSERT ON claims WHEN LENGTH(TRIM(NEW.claim)) < 10 BEGIN SELECT RAISE(FAIL, 'claim too short (<10 chars)'); END;

-- trigger: trg_no_context_capsule_ins
CREATE TRIGGER trg_no_context_capsule_ins
                BEFORE INSERT ON task_capsules
                WHEN NEW.intent LIKE '%context capsule%' OR NEW.intent LIKE '%CONTEXT CAPSULE%'
                    OR NEW.topic LIKE '%context capsule%'
                BEGIN
                    SELECT RAISE(FAIL, 'context capsule forbidden by DB trigger (council fix 2026-06-26)');
                END;

-- trigger: trg_no_context_capsule_upd
CREATE TRIGGER trg_no_context_capsule_upd
                BEFORE UPDATE ON task_capsules
                WHEN NEW.intent LIKE '%context capsule%' OR NEW.intent LIKE '%CONTEXT CAPSULE%'
                    OR NEW.topic LIKE '%context capsule%'
                BEGIN
                    SELECT RAISE(FAIL, 'context capsule forbidden by DB trigger (council fix 2026-06-26)');
                END;
