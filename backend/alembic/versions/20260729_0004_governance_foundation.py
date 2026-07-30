"""Add factual-governance persistence and LangGraph checkpoint tables.

Revision ID: 20260729_0004
Revises: 20260729_0003
Create Date: 2026-07-29
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0004"
down_revision: str | None = "20260729_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    statements = """
            CREATE TABLE governance_runs (
                id UUID CONSTRAINT pk_governance_runs PRIMARY KEY,
                trigger VARCHAR(20) NOT NULL,
                acquisition_run_id UUID,
                manual_idempotency_key VARCHAR(128),
                timezone VARCHAR(80) NOT NULL,
                profile_fingerprint VARCHAR(64) NOT NULL,
                version_bundle JSONB NOT NULL,
                status VARCHAR(30) NOT NULL,
                total_jobs INTEGER NOT NULL DEFAULT 0,
                succeeded_jobs INTEGER NOT NULL DEFAULT 0,
                review_jobs INTEGER NOT NULL DEFAULT 0,
                failed_jobs INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                CONSTRAINT fk_governance_runs_acquisition_run_id
                    FOREIGN KEY (acquisition_run_id) REFERENCES acquisition_runs(id) ON DELETE RESTRICT,
                CONSTRAINT ck_governance_runs_trigger
                    CHECK (trigger IN ('acquisition', 'manual')),
                CONSTRAINT ck_governance_runs_status
                    CHECK (status IN ('queued', 'running', 'succeeded', 'partially_succeeded',
                                      'failed', 'cancelled'))
            );
            CREATE UNIQUE INDEX uq_governance_runs_acquisition_profile
                ON governance_runs(acquisition_run_id, profile_fingerprint)
                WHERE acquisition_run_id IS NOT NULL;
            CREATE UNIQUE INDEX uq_governance_runs_manual_idempotency
                ON governance_runs(manual_idempotency_key)
                WHERE manual_idempotency_key IS NOT NULL;
            CREATE INDEX ix_governance_runs_status_created
                ON governance_runs(status, created_at);

            CREATE TABLE governance_jobs (
                id UUID CONSTRAINT pk_governance_jobs PRIMARY KEY,
                run_id UUID NOT NULL,
                candidate_id UUID NOT NULL,
                input_content_hash VARCHAR(64) NOT NULL,
                idempotency_key VARCHAR(64) NOT NULL,
                status VARCHAR(30) NOT NULL,
                current_stage VARCHAR(80),
                available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                lease_owner VARCHAR(200),
                lease_token UUID,
                lease_expires_at TIMESTAMPTZ,
                heartbeat_at TIMESTAMPTZ,
                outcome VARCHAR(80),
                error_code VARCHAR(80),
                safe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                CONSTRAINT fk_governance_jobs_run_id
                    FOREIGN KEY (run_id) REFERENCES governance_runs(id) ON DELETE CASCADE,
                CONSTRAINT fk_governance_jobs_candidate_id
                    FOREIGN KEY (candidate_id) REFERENCES evidence_candidates(id) ON DELETE RESTRICT,
                CONSTRAINT ck_governance_jobs_status
                    CHECK (status IN ('queued', 'running', 'retry_scheduled', 'succeeded',
                                      'review_required', 'failed', 'cancelled')),
                CONSTRAINT uq_governance_jobs_run_candidate UNIQUE (run_id, candidate_id)
            );
            CREATE INDEX ix_governance_jobs_claim
                ON governance_jobs(status, available_at, lease_expires_at);
            CREATE INDEX ix_governance_jobs_run_id ON governance_jobs(run_id);
            CREATE INDEX ix_governance_jobs_candidate_id ON governance_jobs(candidate_id);
            CREATE INDEX ix_governance_jobs_idempotency_key ON governance_jobs(idempotency_key);

            CREATE TABLE governance_attempts (
                id UUID CONSTRAINT pk_governance_attempts PRIMARY KEY,
                job_id UUID NOT NULL,
                attempt_number INTEGER NOT NULL,
                stage VARCHAR(80) NOT NULL,
                result VARCHAR(40),
                error_code VARCHAR(80),
                safe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMPTZ NOT NULL,
                completed_at TIMESTAMPTZ,
                CONSTRAINT fk_governance_attempts_job_id
                    FOREIGN KEY (job_id) REFERENCES governance_jobs(id) ON DELETE CASCADE,
                CONSTRAINT uq_governance_attempts_job_number UNIQUE (job_id, attempt_number)
            );
            CREATE INDEX ix_governance_attempts_job_id ON governance_attempts(job_id);

            CREATE TABLE article_occurrences (
                id UUID CONSTRAINT pk_article_occurrences PRIMARY KEY,
                occurrence_key VARCHAR(64) NOT NULL,
                candidate_id UUID NOT NULL,
                observation_id UUID NOT NULL,
                snapshot_id UUID NOT NULL,
                source_id UUID NOT NULL,
                source_version_id UUID NOT NULL,
                source_item_id VARCHAR(500) NOT NULL,
                source_slug VARCHAR(80) NOT NULL,
                source_display_name VARCHAR(200) NOT NULL,
                trust_tier VARCHAR(1) NOT NULL,
                original_url TEXT NOT NULL,
                final_url TEXT NOT NULL,
                published_at TIMESTAMPTZ,
                fetched_at TIMESTAMPTZ NOT NULL,
                parser_version VARCHAR(40) NOT NULL,
                relevance_rule_version VARCHAR(40),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_article_occurrences_candidate_id
                    FOREIGN KEY (candidate_id) REFERENCES evidence_candidates(id) ON DELETE RESTRICT,
                CONSTRAINT fk_article_occurrences_observation_id
                    FOREIGN KEY (observation_id) REFERENCES source_observations(id) ON DELETE RESTRICT,
                CONSTRAINT fk_article_occurrences_snapshot_id
                    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(id) ON DELETE RESTRICT,
                CONSTRAINT fk_article_occurrences_source_id
                    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT,
                CONSTRAINT fk_article_occurrences_source_version_id
                    FOREIGN KEY (source_version_id) REFERENCES source_versions(id) ON DELETE RESTRICT,
                CONSTRAINT ck_article_occurrences_trust_tier CHECK (trust_tier IN ('A', 'B')),
                CONSTRAINT uq_article_occurrences_occurrence_key UNIQUE (occurrence_key),
                CONSTRAINT uq_article_occurrences_observation_id UNIQUE (observation_id)
            );
            CREATE INDEX ix_article_occurrences_candidate_id ON article_occurrences(candidate_id);
            CREATE INDEX ix_article_occurrences_source_id ON article_occurrences(source_id);

            CREATE TABLE normalized_articles (
                id UUID CONSTRAINT pk_normalized_articles PRIMARY KEY,
                candidate_id UUID NOT NULL,
                input_content_hash VARCHAR(64) NOT NULL,
                normalization_version VARCHAR(80) NOT NULL,
                normalized_hash VARCHAR(64) NOT NULL,
                simhash_hex VARCHAR(16) NOT NULL,
                normalized_text TEXT NOT NULL,
                language VARCHAR(20) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_normalized_articles_candidate_id
                    FOREIGN KEY (candidate_id) REFERENCES evidence_candidates(id) ON DELETE RESTRICT,
                CONSTRAINT uq_normalized_articles_derivation
                    UNIQUE (candidate_id, input_content_hash, normalization_version)
            );
            CREATE INDEX ix_normalized_articles_normalized_hash
                ON normalized_articles(normalized_hash);
            CREATE INDEX ix_normalized_articles_candidate_id ON normalized_articles(candidate_id);

            CREATE TABLE normalized_passages (
                id UUID CONSTRAINT pk_normalized_passages PRIMARY KEY,
                normalized_article_id UUID NOT NULL,
                candidate_id UUID NOT NULL,
                ordinal INTEGER NOT NULL,
                passage_hash VARCHAR(64) NOT NULL,
                text TEXT NOT NULL,
                source_start INTEGER NOT NULL,
                source_end INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_normalized_passages_normalized_article_id
                    FOREIGN KEY (normalized_article_id) REFERENCES normalized_articles(id) ON DELETE CASCADE,
                CONSTRAINT fk_normalized_passages_candidate_id
                    FOREIGN KEY (candidate_id) REFERENCES evidence_candidates(id) ON DELETE RESTRICT,
                CONSTRAINT ck_normalized_passages_ordinal CHECK (ordinal >= 0),
                CONSTRAINT ck_normalized_passages_offsets
                    CHECK (source_start >= 0 AND source_end >= source_start),
                CONSTRAINT uq_normalized_passages_article_ordinal
                    UNIQUE (normalized_article_id, ordinal)
            );
            CREATE INDEX ix_normalized_passages_candidate_id ON normalized_passages(candidate_id);

            CREATE TABLE model_invocations (
                id UUID CONSTRAINT pk_model_invocations PRIMARY KEY,
                governance_job_id UUID NOT NULL,
                capability VARCHAR(40) NOT NULL,
                provider VARCHAR(40) NOT NULL,
                model VARCHAR(120) NOT NULL,
                request_fingerprint VARCHAR(64) NOT NULL,
                provider_request_id VARCHAR(200),
                status VARCHAR(30) NOT NULL,
                prompt_version VARCHAR(80),
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                safe_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_code VARCHAR(80),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ,
                CONSTRAINT fk_model_invocations_governance_job_id
                    FOREIGN KEY (governance_job_id) REFERENCES governance_jobs(id) ON DELETE CASCADE,
                CONSTRAINT uq_model_invocations_request
                    UNIQUE (capability, request_fingerprint)
            );
            CREATE INDEX ix_model_invocations_governance_job_id
                ON model_invocations(governance_job_id);

            CREATE TABLE candidate_analyses (
                id UUID CONSTRAINT pk_candidate_analyses PRIMARY KEY,
                normalized_article_id UUID NOT NULL,
                candidate_id UUID NOT NULL,
                invocation_id UUID,
                request_fingerprint VARCHAR(64) NOT NULL,
                prompt_version VARCHAR(80) NOT NULL,
                schema_version VARCHAR(80) NOT NULL,
                taxonomy_version VARCHAR(80) NOT NULL,
                provider VARCHAR(40) NOT NULL,
                model VARCHAR(120) NOT NULL,
                status VARCHAR(30) NOT NULL,
                summary TEXT,
                event_time_start TIMESTAMPTZ,
                event_time_end TIMESTAMPTZ,
                event_time_precision VARCHAR(20) NOT NULL DEFAULT 'unknown',
                keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
                validation_code VARCHAR(80),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_candidate_analyses_normalized_article_id
                    FOREIGN KEY (normalized_article_id) REFERENCES normalized_articles(id) ON DELETE RESTRICT,
                CONSTRAINT fk_candidate_analyses_candidate_id
                    FOREIGN KEY (candidate_id) REFERENCES evidence_candidates(id) ON DELETE RESTRICT,
                CONSTRAINT fk_candidate_analyses_invocation_id
                    FOREIGN KEY (invocation_id) REFERENCES model_invocations(id) ON DELETE RESTRICT,
                CONSTRAINT ck_candidate_analyses_status
                    CHECK (status IN ('pending', 'accepted', 'invalid', 'review_required')),
                CONSTRAINT ck_candidate_analyses_time_precision
                    CHECK (event_time_precision IN ('exact', 'day', 'month', 'unknown')),
                CONSTRAINT ck_candidate_analyses_keywords_array
                    CHECK (jsonb_typeof(keywords) = 'array'),
                CONSTRAINT uq_candidate_analyses_request UNIQUE (request_fingerprint)
            );
            CREATE INDEX ix_candidate_analyses_candidate_id ON candidate_analyses(candidate_id);

            CREATE TABLE analysis_facts (
                id UUID CONSTRAINT pk_analysis_facts PRIMARY KEY,
                analysis_id UUID NOT NULL,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL,
                event_time_start TIMESTAMPTZ,
                event_time_end TIMESTAMPTZ,
                event_time_precision VARCHAR(20) NOT NULL DEFAULT 'unknown',
                status VARCHAR(20) NOT NULL,
                CONSTRAINT fk_analysis_facts_analysis_id
                    FOREIGN KEY (analysis_id) REFERENCES candidate_analyses(id) ON DELETE CASCADE,
                CONSTRAINT ck_analysis_facts_time_precision
                    CHECK (event_time_precision IN ('exact', 'day', 'month', 'unknown')),
                CONSTRAINT ck_analysis_facts_status CHECK (status = 'accepted'),
                CONSTRAINT uq_analysis_facts_analysis_ordinal UNIQUE (analysis_id, ordinal)
            );
            CREATE INDEX ix_analysis_facts_analysis_id ON analysis_facts(analysis_id);

            CREATE TABLE analysis_entities (
                id UUID CONSTRAINT pk_analysis_entities PRIMARY KEY,
                analysis_id UUID NOT NULL,
                ordinal INTEGER NOT NULL,
                entity_type VARCHAR(40) NOT NULL,
                source_mention TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                support_passage_id UUID NOT NULL,
                CONSTRAINT fk_analysis_entities_analysis_id
                    FOREIGN KEY (analysis_id) REFERENCES candidate_analyses(id) ON DELETE CASCADE,
                CONSTRAINT fk_analysis_entities_support_passage_id
                    FOREIGN KEY (support_passage_id) REFERENCES normalized_passages(id) ON DELETE RESTRICT,
                CONSTRAINT ck_analysis_entities_type
                    CHECK (entity_type IN ('organization', 'person', 'product', 'model',
                                           'policy', 'place', 'technology', 'other')),
                CONSTRAINT uq_analysis_entities_analysis_ordinal UNIQUE (analysis_id, ordinal)
            );
            CREATE INDEX ix_analysis_entities_analysis_id ON analysis_entities(analysis_id);

            CREATE TABLE analysis_categories (
                id UUID CONSTRAINT pk_analysis_categories PRIMARY KEY,
                analysis_id UUID NOT NULL,
                taxonomy_version VARCHAR(80) NOT NULL,
                category VARCHAR(80) NOT NULL,
                is_primary BOOLEAN NOT NULL DEFAULT false,
                confidence DOUBLE PRECISION NOT NULL,
                CONSTRAINT fk_analysis_categories_analysis_id
                    FOREIGN KEY (analysis_id) REFERENCES candidate_analyses(id) ON DELETE CASCADE,
                CONSTRAINT ck_analysis_categories_confidence
                    CHECK (confidence >= 0 AND confidence <= 1),
                CONSTRAINT ck_analysis_categories_taxonomy
                    CHECK (category IN ('ai_education_policy', 'large_generative_models',
                                        'robotics_embodied_intelligence', 'ai_compute_chips',
                                        'youth_science_education', 'ai_industry_application',
                                        'ai_governance_safety')),
                CONSTRAINT uq_analysis_categories_label
                    UNIQUE (analysis_id, taxonomy_version, category)
            );
            CREATE UNIQUE INDEX uq_analysis_categories_one_primary
                ON analysis_categories(analysis_id) WHERE is_primary = true;

            CREATE TABLE evidence_bindings (
                id UUID CONSTRAINT pk_evidence_bindings PRIMARY KEY,
                binding_key VARCHAR(64) NOT NULL,
                analysis_id UUID NOT NULL,
                fact_id UUID,
                statement_kind VARCHAR(20) NOT NULL,
                passage_id UUID NOT NULL,
                candidate_id UUID NOT NULL,
                occurrence_id UUID NOT NULL,
                snapshot_id UUID NOT NULL,
                exact_quote TEXT NOT NULL,
                quote_start INTEGER NOT NULL,
                quote_end INTEGER NOT NULL,
                validated BOOLEAN NOT NULL,
                CONSTRAINT fk_evidence_bindings_analysis_id
                    FOREIGN KEY (analysis_id) REFERENCES candidate_analyses(id) ON DELETE CASCADE,
                CONSTRAINT fk_evidence_bindings_fact_id
                    FOREIGN KEY (fact_id) REFERENCES analysis_facts(id) ON DELETE CASCADE,
                CONSTRAINT fk_evidence_bindings_passage_id
                    FOREIGN KEY (passage_id) REFERENCES normalized_passages(id) ON DELETE RESTRICT,
                CONSTRAINT fk_evidence_bindings_candidate_id
                    FOREIGN KEY (candidate_id) REFERENCES evidence_candidates(id) ON DELETE RESTRICT,
                CONSTRAINT fk_evidence_bindings_occurrence_id
                    FOREIGN KEY (occurrence_id) REFERENCES article_occurrences(id) ON DELETE RESTRICT,
                CONSTRAINT fk_evidence_bindings_snapshot_id
                    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(id) ON DELETE RESTRICT,
                CONSTRAINT ck_evidence_bindings_statement_kind
                    CHECK (statement_kind IN ('summary', 'fact')),
                CONSTRAINT ck_evidence_bindings_offsets
                    CHECK (quote_start >= 0 AND quote_end >= quote_start),
                CONSTRAINT uq_evidence_bindings_binding_key UNIQUE (binding_key)
            );
            CREATE INDEX ix_evidence_bindings_analysis_id ON evidence_bindings(analysis_id);
            CREATE INDEX ix_evidence_bindings_passage_id ON evidence_bindings(passage_id);

            CREATE TABLE article_embeddings (
                id UUID CONSTRAINT pk_article_embeddings PRIMARY KEY,
                normalized_article_id UUID NOT NULL,
                purpose VARCHAR(40) NOT NULL,
                provider VARCHAR(40) NOT NULL,
                model VARCHAR(120) NOT NULL,
                dimensions INTEGER NOT NULL,
                input_hash VARCHAR(64) NOT NULL,
                input_version VARCHAR(80) NOT NULL,
                vector vector(2048) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_article_embeddings_normalized_article_id
                    FOREIGN KEY (normalized_article_id) REFERENCES normalized_articles(id) ON DELETE CASCADE,
                CONSTRAINT ck_article_embeddings_dimensions CHECK (dimensions = 2048),
                CONSTRAINT ck_article_embeddings_purpose
                    CHECK (purpose IN ('near_duplicate', 'event_assignment')),
                CONSTRAINT uq_article_embeddings_derivation
                    UNIQUE (normalized_article_id, purpose, provider, model, input_hash, input_version)
            );
            CREATE INDEX ix_article_embeddings_article_purpose
                ON article_embeddings(normalized_article_id, purpose);

            CREATE TABLE duplicate_relations (
                id UUID CONSTRAINT pk_duplicate_relations PRIMARY KEY,
                left_article_id UUID NOT NULL,
                right_article_id UUID NOT NULL,
                relation_kind VARCHAR(40) NOT NULL,
                policy_version VARCHAR(80) NOT NULL,
                outcome VARCHAR(40) NOT NULL,
                threshold DOUBLE PRECISION,
                features JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_duplicate_relations_left_article_id
                    FOREIGN KEY (left_article_id) REFERENCES normalized_articles(id) ON DELETE CASCADE,
                CONSTRAINT fk_duplicate_relations_right_article_id
                    FOREIGN KEY (right_article_id) REFERENCES normalized_articles(id) ON DELETE CASCADE,
                CONSTRAINT ck_duplicate_relations_pair CHECK (left_article_id < right_article_id),
                CONSTRAINT ck_duplicate_relations_kind
                    CHECK (relation_kind IN ('same_content', 'same_url', 'same_source_item',
                                             'revision_of', 'near_duplicate')),
                CONSTRAINT ck_duplicate_relations_outcome
                    CHECK (outcome IN ('matched', 'distinct')),
                CONSTRAINT ck_duplicate_relations_threshold
                    CHECK (threshold IS NULL OR (threshold >= 0 AND threshold <= 1)),
                CONSTRAINT uq_duplicate_relations_pair_policy
                    UNIQUE (left_article_id, right_article_id, relation_kind, policy_version)
            );
            CREATE INDEX ix_duplicate_relations_left_article_id
                ON duplicate_relations(left_article_id);
            CREATE INDEX ix_duplicate_relations_right_article_id
                ON duplicate_relations(right_article_id);

            CREATE TABLE event_clusters (
                id UUID CONSTRAINT pk_event_clusters PRIMARY KEY,
                status VARCHAR(30) NOT NULL,
                current_version_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_event_clusters_status
                    CHECK (status IN ('active', 'merged', 'archived'))
            );
            CREATE INDEX ix_event_clusters_status ON event_clusters(status);

            CREATE TABLE event_assignment_decisions (
                id UUID CONSTRAINT pk_event_assignment_decisions PRIMARY KEY,
                normalized_article_id UUID NOT NULL,
                governance_run_id UUID NOT NULL,
                selected_event_id UUID,
                policy_version VARCHAR(80) NOT NULL,
                outcome VARCHAR(40) NOT NULL,
                recent_window_start TIMESTAMPTZ NOT NULL,
                recent_window_end TIMESTAMPTZ NOT NULL,
                features JSONB NOT NULL,
                thresholds JSONB NOT NULL,
                alternatives JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_event_assignment_decisions_normalized_article_id
                    FOREIGN KEY (normalized_article_id) REFERENCES normalized_articles(id) ON DELETE CASCADE,
                CONSTRAINT fk_event_assignment_decisions_governance_run_id
                    FOREIGN KEY (governance_run_id) REFERENCES governance_runs(id) ON DELETE RESTRICT,
                CONSTRAINT fk_event_assignment_decisions_selected_event_id
                    FOREIGN KEY (selected_event_id) REFERENCES event_clusters(id) ON DELETE RESTRICT,
                CONSTRAINT ck_event_assignment_decisions_outcome
                    CHECK (outcome IN ('assigned_existing', 'created_new', 'review_required')),
                CONSTRAINT uq_event_assignment_decisions_article_run_policy
                    UNIQUE (normalized_article_id, governance_run_id, policy_version)
            );

            CREATE TABLE event_cluster_versions (
                id UUID CONSTRAINT pk_event_cluster_versions PRIMARY KEY,
                event_id UUID NOT NULL,
                version INTEGER NOT NULL,
                representative_article_id UUID NOT NULL,
                representative_title TEXT NOT NULL,
                summary_projection JSONB NOT NULL,
                event_time_start TIMESTAMPTZ,
                event_time_end TIMESTAMPTZ,
                event_time_precision VARCHAR(20) NOT NULL,
                member_set_hash VARCHAR(64) NOT NULL,
                source_diversity INTEGER NOT NULL,
                category_projection JSONB NOT NULL,
                entity_projection JSONB NOT NULL,
                clustering_policy_version VARCHAR(80) NOT NULL,
                version_bundle_fingerprint VARCHAR(64) NOT NULL,
                created_by_run_id UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_event_cluster_versions_event_id
                    FOREIGN KEY (event_id) REFERENCES event_clusters(id) ON DELETE CASCADE,
                CONSTRAINT fk_event_cluster_versions_representative_article_id
                    FOREIGN KEY (representative_article_id) REFERENCES normalized_articles(id) ON DELETE RESTRICT,
                CONSTRAINT fk_event_cluster_versions_created_by_run_id
                    FOREIGN KEY (created_by_run_id) REFERENCES governance_runs(id) ON DELETE RESTRICT,
                CONSTRAINT ck_event_cluster_versions_version CHECK (version >= 1),
                CONSTRAINT ck_event_cluster_versions_source_diversity CHECK (source_diversity >= 1),
                CONSTRAINT ck_event_cluster_versions_time_precision
                    CHECK (event_time_precision IN ('exact', 'day', 'month', 'unknown')),
                CONSTRAINT uq_event_cluster_versions_event_version UNIQUE (event_id, version),
                CONSTRAINT uq_event_cluster_versions_projection
                    UNIQUE (event_id, member_set_hash, clustering_policy_version,
                            version_bundle_fingerprint)
            );
            ALTER TABLE event_clusters ADD CONSTRAINT fk_event_clusters_current_version_id
                FOREIGN KEY (current_version_id) REFERENCES event_cluster_versions(id) ON DELETE RESTRICT;

            CREATE TABLE event_memberships (
                id UUID CONSTRAINT pk_event_memberships PRIMARY KEY,
                event_id UUID NOT NULL,
                normalized_article_id UUID NOT NULL,
                assignment_decision_id UUID NOT NULL,
                policy_version VARCHAR(80) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT true,
                superseded_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT fk_event_memberships_event_id
                    FOREIGN KEY (event_id) REFERENCES event_clusters(id) ON DELETE CASCADE,
                CONSTRAINT fk_event_memberships_normalized_article_id
                    FOREIGN KEY (normalized_article_id) REFERENCES normalized_articles(id) ON DELETE CASCADE,
                CONSTRAINT fk_event_memberships_assignment_decision_id
                    FOREIGN KEY (assignment_decision_id) REFERENCES event_assignment_decisions(id) ON DELETE RESTRICT,
                CONSTRAINT ck_event_memberships_lifecycle
                    CHECK ((active AND superseded_at IS NULL) OR
                           (NOT active AND superseded_at IS NOT NULL)),
                CONSTRAINT uq_event_memberships_event_article_policy
                    UNIQUE (event_id, normalized_article_id, policy_version)
            );
            CREATE UNIQUE INDEX uq_event_memberships_active_article_policy
                ON event_memberships(normalized_article_id, policy_version) WHERE active = true;
            CREATE INDEX ix_event_memberships_event_id ON event_memberships(event_id);

            CREATE TABLE checkpoint_migrations (v INTEGER CONSTRAINT pk_checkpoint_migrations PRIMARY KEY);
            CREATE TABLE checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint JSONB NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}',
                CONSTRAINT pk_checkpoints PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            CREATE TABLE checkpoint_blobs (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL,
                version TEXT NOT NULL,
                type TEXT NOT NULL,
                blob BYTEA,
                CONSTRAINT pk_checkpoint_blobs PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
            );
            CREATE TABLE checkpoint_writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                task_path TEXT NOT NULL DEFAULT '',
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                blob BYTEA NOT NULL,
                CONSTRAINT pk_checkpoint_writes
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            );
            CREATE INDEX checkpoints_thread_id_idx ON checkpoints(thread_id);
            CREATE INDEX checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id);
            CREATE INDEX checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id);
            INSERT INTO checkpoint_migrations(v) SELECT generate_series(0, 9);
            """
    for statement in statements.split(";\n"):
        if statement.strip():
            op.execute(sa.text(statement))


def downgrade() -> None:
    connection = op.get_bind()
    has_governance_data = connection.scalar(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1 FROM governance_runs
                UNION ALL SELECT 1 FROM article_occurrences
                UNION ALL SELECT 1 FROM normalized_articles
                UNION ALL SELECT 1 FROM model_invocations
                UNION ALL SELECT 1 FROM event_clusters
                UNION ALL SELECT 1 FROM checkpoints
                UNION ALL SELECT 1 FROM checkpoint_blobs
                UNION ALL SELECT 1 FROM checkpoint_writes
            )
            """
        )
    )
    if has_governance_data:
        raise RuntimeError(
            "cannot downgrade governance foundation while governance or checkpoint data exists"
        )
    statements = """
            DROP TABLE checkpoint_writes;
            DROP TABLE checkpoint_blobs;
            DROP TABLE checkpoints;
            DROP TABLE checkpoint_migrations;
            DROP TABLE event_memberships;
            ALTER TABLE event_clusters DROP CONSTRAINT fk_event_clusters_current_version_id;
            DROP TABLE event_cluster_versions;
            DROP TABLE event_assignment_decisions;
            DROP TABLE event_clusters;
            DROP TABLE duplicate_relations;
            DROP TABLE article_embeddings;
            DROP TABLE evidence_bindings;
            DROP TABLE analysis_categories;
            DROP TABLE analysis_entities;
            DROP TABLE analysis_facts;
            DROP TABLE candidate_analyses;
            DROP TABLE model_invocations;
            DROP TABLE normalized_passages;
            DROP TABLE normalized_articles;
            DROP TABLE article_occurrences;
            DROP TABLE governance_attempts;
            DROP TABLE governance_jobs;
            DROP TABLE governance_runs;
            """
    for statement in statements.split(";\n"):
        if statement.strip():
            op.execute(sa.text(statement))
