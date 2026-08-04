from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
        }
    )


class SourceModel(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id",
            name="fk_sources_active_version_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_sources_slug"),
        Index("ix_sources_enabled", "enabled"),
    )


class SourceVersionModel(Base):
    __tablename__ = "source_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", name="fk_source_versions_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(80), nullable=False)
    entry_url: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_hosts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    allowed_path_prefixes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    cadence: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    robots_status: Mapped[str] = mapped_column(String(40), nullable=False)
    terms_reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rate_limit_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    connector_version: Mapped[str] = mapped_column(String(40), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    relevance_rule_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("trust_tier IN ('A', 'B')", name="ck_source_versions_trust_tier"),
        CheckConstraint("rate_limit_seconds >= 0", name="ck_source_versions_rate_limit"),
        UniqueConstraint("source_id", "version", name="uq_source_versions_source_version"),
        UniqueConstraint(
            "source_id", "config_fingerprint", name="uq_source_versions_source_fingerprint"
        ),
        Index("ix_source_versions_connector_key", "connector_key"),
    )


class SourceCursorModel(Base):
    __tablename__ = "source_cursors"

    source_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id", name="fk_source_cursors_source_version_id", ondelete="CASCADE"
        ),
        primary_key=True,
    )
    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_item_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cursor_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AcquisitionRunModel(Base):
    __tablename__ = "acquisition_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    acquisition_version: Mapped[str] = mapped_column(String(40), nullable=False)
    manual_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    total_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    succeeded_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("trigger IN ('scheduled', 'manual')", name="ck_acquisition_runs_trigger"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', "
            "'partially_succeeded', 'failed', 'cancelled')",
            name="ck_acquisition_runs_status",
        ),
        Index(
            "uq_acquisition_runs_scheduled_business_key",
            "business_date",
            "timezone",
            "acquisition_version",
            unique=True,
            postgresql_where=text("trigger = 'scheduled'"),
        ),
        Index(
            "uq_acquisition_runs_manual_idempotency",
            "manual_idempotency_key",
            unique=True,
            postgresql_where=text("manual_idempotency_key IS NOT NULL"),
        ),
        Index("ix_acquisition_runs_created_at", "created_at"),
    )


class AcquisitionJobModel(Base):
    __tablename__ = "acquisition_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("acquisition_runs.id", name="fk_acquisition_jobs_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", name="fk_acquisition_jobs_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id", name="fk_acquisition_jobs_source_version_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry_scheduled', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_acquisition_jobs_status",
        ),
        UniqueConstraint("run_id", "source_id", name="uq_acquisition_jobs_run_source"),
        Index("ix_acquisition_jobs_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_acquisition_jobs_run_id", "run_id"),
        Index("ix_acquisition_jobs_source_id", "source_id"),
    )


class AcquisitionAttemptModel(Base):
    __tablename__ = "acquisition_attempts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "acquisition_jobs.id", name="fk_acquisition_attempts_job_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_acquisition_attempts_job_number"),
        Index("ix_acquisition_attempts_job_id", "job_id"),
    )


class SourceFetchLeaseModel(Base):
    __tablename__ = "source_fetch_leases"

    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", name="fk_source_fetch_leases_source_id", ondelete="CASCADE"),
        primary_key=True,
    )
    lease_owner: Mapped[str] = mapped_column(String(200), nullable=False)
    lease_token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_source_fetch_leases_expires_at", "expires_at"),)


class SourceSnapshotModel(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    provenance_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id", name="fk_source_snapshots_source_version_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    bucket: Mapped[str] = mapped_column(String(120), nullable=False)
    object_key: Mapped[str] = mapped_column(String(300), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    connector_version: Mapped[str] = mapped_column(String(40), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("kind IN ('list', 'detail')", name="ck_source_snapshots_kind"),
        CheckConstraint("byte_size >= 0", name="ck_source_snapshots_byte_size"),
        UniqueConstraint("provenance_key", name="uq_source_snapshots_provenance_key"),
        Index("ix_source_snapshots_object", "bucket", "object_key"),
        Index("ix_source_snapshots_source_version_id", "source_version_id"),
    )


class EvidenceCandidateModel(Base):
    __tablename__ = "evidence_candidates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", name="fk_evidence_candidates_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id",
            name="fk_evidence_candidates_source_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_item_id: Mapped[str] = mapped_column(String(500), nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    clean_text: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    relevance_rule_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    primary_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_snapshots.id",
            name="fk_evidence_candidates_primary_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("trust_tier IN ('A', 'B')", name="ck_evidence_candidates_trust_tier"),
        UniqueConstraint(
            "source_version_id",
            "source_item_id",
            "content_hash",
            name="uq_evidence_candidates_item_content",
        ),
        Index("ix_evidence_candidates_published_at", "published_at", "id"),
        Index("ix_evidence_candidates_source_id", "source_id", "created_at"),
    )


class SourceObservationModel(Base):
    __tablename__ = "source_observations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("acquisition_runs.id", name="fk_source_observations_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("acquisition_jobs.id", name="fk_source_observations_job_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id",
            name="fk_source_observations_source_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_item_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_snapshots.id", name="fk_source_observations_snapshot_id", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id",
            name="fk_source_observations_candidate_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_source_observations_idempotency_key"),
        Index("ix_source_observations_run_id", "run_id"),
        Index("ix_source_observations_candidate_id", "candidate_id"),
    )


class GovernanceRunModel(Base):
    __tablename__ = "governance_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    acquisition_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "acquisition_runs.id", name="fk_governance_runs_acquisition_run_id", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    manual_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version_bundle: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    total_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    succeeded_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    review_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("trigger IN ('acquisition', 'manual')", name="ck_governance_runs_trigger"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partially_succeeded', "
            "'failed', 'cancelled')",
            name="ck_governance_runs_status",
        ),
        Index(
            "uq_governance_runs_acquisition_profile",
            "acquisition_run_id",
            "profile_fingerprint",
            unique=True,
            postgresql_where=text("acquisition_run_id IS NOT NULL"),
        ),
        Index(
            "uq_governance_runs_manual_idempotency",
            "manual_idempotency_key",
            unique=True,
            postgresql_where=text("manual_idempotency_key IS NOT NULL"),
        ),
        Index("ix_governance_runs_status_created", "status", "created_at"),
    )


class GovernanceJobModel(Base):
    __tablename__ = "governance_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("governance_runs.id", name="fk_governance_jobs_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id",
            name="fk_governance_jobs_candidate_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    input_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry_scheduled', 'succeeded', "
            "'review_required', 'failed', 'cancelled')",
            name="ck_governance_jobs_status",
        ),
        UniqueConstraint("run_id", "candidate_id", name="uq_governance_jobs_run_candidate"),
        Index("ix_governance_jobs_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_governance_jobs_run_id", "run_id"),
        Index("ix_governance_jobs_candidate_id", "candidate_id"),
        Index("ix_governance_jobs_idempotency_key", "idempotency_key"),
    )


class GovernanceAttemptModel(Base):
    __tablename__ = "governance_attempts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("governance_jobs.id", name="fk_governance_attempts_job_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_governance_attempts_job_number"),
        Index("ix_governance_attempts_job_id", "job_id"),
    )


class ArticleOccurrenceModel(Base):
    __tablename__ = "article_occurrences"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    occurrence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id",
            name="fk_article_occurrences_candidate_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_observations.id",
            name="fk_article_occurrences_observation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_snapshots.id", name="fk_article_occurrences_snapshot_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", name="fk_article_occurrences_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_versions.id",
            name="fk_article_occurrences_source_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_item_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    source_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    relevance_rule_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("trust_tier IN ('A', 'B')", name="ck_article_occurrences_trust_tier"),
        UniqueConstraint("occurrence_key", name="uq_article_occurrences_occurrence_key"),
        UniqueConstraint("observation_id", name="uq_article_occurrences_observation_id"),
        Index("ix_article_occurrences_candidate_id", "candidate_id"),
        Index("ix_article_occurrences_source_id", "source_id"),
    )


class NormalizedArticleModel(Base):
    __tablename__ = "normalized_articles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id",
            name="fk_normalized_articles_candidate_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    input_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    simhash_hex: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "input_content_hash",
            "normalization_version",
            name="uq_normalized_articles_derivation",
        ),
        Index("ix_normalized_articles_normalized_hash", "normalized_hash"),
        Index("ix_normalized_articles_candidate_id", "candidate_id"),
    )


class NormalizedPassageModel(Base):
    __tablename__ = "normalized_passages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    normalized_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_normalized_passages_normalized_article_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id",
            name="fk_normalized_passages_candidate_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    passage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_normalized_passages_ordinal"),
        CheckConstraint(
            "source_start >= 0 AND source_end >= source_start",
            name="ck_normalized_passages_offsets",
        ),
        UniqueConstraint(
            "normalized_article_id", "ordinal", name="uq_normalized_passages_article_ordinal"
        ),
        Index("ix_normalized_passages_candidate_id", "candidate_id"),
    )


class ModelInvocationModel(Base):
    __tablename__ = "model_invocations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    governance_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "governance_jobs.id", name="fk_model_invocations_governance_job_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    safe_usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("capability", "request_fingerprint", name="uq_model_invocations_request"),
        Index("ix_model_invocations_governance_job_id", "governance_job_id"),
    )


class CandidateAnalysisModel(Base):
    __tablename__ = "candidate_analyses"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    normalized_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_candidate_analyses_normalized_article_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id", name="fk_candidate_analyses_candidate_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    invocation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_invocations.id", name="fk_candidate_analyses_invocation_id", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_time_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_time_precision: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'unknown'")
    )
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    validation_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'invalid', 'review_required')",
            name="ck_candidate_analyses_status",
        ),
        CheckConstraint(
            "event_time_precision IN ('exact', 'day', 'month', 'unknown')",
            name="ck_candidate_analyses_time_precision",
        ),
        CheckConstraint(
            "jsonb_typeof(keywords) = 'array'",
            name="ck_candidate_analyses_keywords_array",
        ),
        UniqueConstraint("request_fingerprint", name="uq_candidate_analyses_request"),
        Index("ix_candidate_analyses_candidate_id", "candidate_id"),
    )


class AnalysisFactModel(Base):
    __tablename__ = "analysis_facts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "candidate_analyses.id", name="fk_analysis_facts_analysis_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_text: Mapped[str] = mapped_column("text", Text, nullable=False)
    event_time_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_time_precision: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'unknown'")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "event_time_precision IN ('exact', 'day', 'month', 'unknown')",
            name="ck_analysis_facts_time_precision",
        ),
        CheckConstraint("status = 'accepted'", name="ck_analysis_facts_status"),
        UniqueConstraint("analysis_id", "ordinal", name="uq_analysis_facts_analysis_ordinal"),
        Index("ix_analysis_facts_analysis_id", "analysis_id"),
    )


class AnalysisEntityModel(Base):
    __tablename__ = "analysis_entities"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "candidate_analyses.id", name="fk_analysis_entities_analysis_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_mention: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    support_passage_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_passages.id",
            name="fk_analysis_entities_support_passage_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('organization', 'person', 'product', 'model', "
            "'policy', 'place', 'technology', 'other')",
            name="ck_analysis_entities_type",
        ),
        UniqueConstraint("analysis_id", "ordinal", name="uq_analysis_entities_analysis_ordinal"),
        Index("ix_analysis_entities_analysis_id", "analysis_id"),
    )


class AnalysisCategoryModel(Base):
    __tablename__ = "analysis_categories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "candidate_analyses.id", name="fk_analysis_categories_analysis_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    taxonomy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_analysis_categories_confidence"
        ),
        CheckConstraint(
            "category IN ('ai_education_policy', 'large_generative_models', "
            "'robotics_embodied_intelligence', 'ai_compute_chips', "
            "'youth_science_education', 'ai_industry_application', "
            "'ai_governance_safety')",
            name="ck_analysis_categories_taxonomy",
        ),
        UniqueConstraint(
            "analysis_id", "taxonomy_version", "category", name="uq_analysis_categories_label"
        ),
        Index(
            "uq_analysis_categories_one_primary",
            "analysis_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
    )


class EvidenceBindingModel(Base):
    __tablename__ = "evidence_bindings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    binding_key: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "candidate_analyses.id", name="fk_evidence_bindings_analysis_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    fact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_facts.id", name="fk_evidence_bindings_fact_id", ondelete="CASCADE"),
        nullable=True,
    )
    statement_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    passage_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_passages.id", name="fk_evidence_bindings_passage_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evidence_candidates.id", name="fk_evidence_bindings_candidate_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    occurrence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "article_occurrences.id", name="fk_evidence_bindings_occurrence_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "source_snapshots.id", name="fk_evidence_bindings_snapshot_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    exact_quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_end: Mapped[int] = mapped_column(Integer, nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "statement_kind IN ('summary', 'fact')", name="ck_evidence_bindings_statement_kind"
        ),
        CheckConstraint(
            "quote_start >= 0 AND quote_end >= quote_start", name="ck_evidence_bindings_offsets"
        ),
        UniqueConstraint("binding_key", name="uq_evidence_bindings_binding_key"),
        UniqueConstraint(
            "id",
            "candidate_id",
            "passage_id",
            "occurrence_id",
            "snapshot_id",
            name="uq_evidence_bindings_copy_provenance",
        ),
        Index("ix_evidence_bindings_analysis_id", "analysis_id"),
        Index("ix_evidence_bindings_passage_id", "passage_id"),
    )


class ArticleEmbeddingModel(Base):
    __tablename__ = "article_embeddings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    normalized_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_article_embeddings_normalized_article_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_version: Mapped[str] = mapped_column(String(80), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("dimensions = 2048", name="ck_article_embeddings_dimensions"),
        CheckConstraint(
            "purpose IN ('near_duplicate', 'event_assignment')",
            name="ck_article_embeddings_purpose",
        ),
        UniqueConstraint(
            "normalized_article_id",
            "purpose",
            "provider",
            "model",
            "input_hash",
            "input_version",
            name="uq_article_embeddings_derivation",
        ),
        Index("ix_article_embeddings_article_purpose", "normalized_article_id", "purpose"),
    )


class DuplicateRelationModel(Base):
    __tablename__ = "duplicate_relations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    left_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_duplicate_relations_left_article_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    right_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_duplicate_relations_right_article_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    relation_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("left_article_id < right_article_id", name="ck_duplicate_relations_pair"),
        CheckConstraint(
            "relation_kind IN ('same_content', 'same_url', 'same_source_item', "
            "'revision_of', 'near_duplicate')",
            name="ck_duplicate_relations_kind",
        ),
        CheckConstraint(
            "outcome IN ('matched', 'distinct')",
            name="ck_duplicate_relations_outcome",
        ),
        CheckConstraint(
            "threshold IS NULL OR (threshold >= 0 AND threshold <= 1)",
            name="ck_duplicate_relations_threshold",
        ),
        UniqueConstraint(
            "left_article_id",
            "right_article_id",
            "relation_kind",
            "policy_version",
            name="uq_duplicate_relations_pair_policy",
        ),
        Index("ix_duplicate_relations_left_article_id", "left_article_id"),
        Index("ix_duplicate_relations_right_article_id", "right_article_id"),
    )


class EventClusterModel(Base):
    __tablename__ = "event_clusters"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_cluster_versions.id",
            name="fk_event_clusters_current_version_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'merged', 'archived')",
            name="ck_event_clusters_status",
        ),
        Index("ix_event_clusters_status", "status"),
    )


class EventAssignmentDecisionModel(Base):
    __tablename__ = "event_assignment_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    normalized_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_event_assignment_decisions_normalized_article_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    governance_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "governance_runs.id",
            name="fk_event_assignment_decisions_governance_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    selected_event_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_clusters.id",
            name="fk_event_assignment_decisions_selected_event_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    recent_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recent_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('assigned_existing', 'created_new', 'review_required')",
            name="ck_event_assignment_decisions_outcome",
        ),
        UniqueConstraint(
            "normalized_article_id",
            "governance_run_id",
            "policy_version",
            name="uq_event_assignment_decisions_article_run_policy",
        ),
    )


class EventClusterVersionModel(Base):
    __tablename__ = "event_cluster_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_clusters.id", name="fk_event_cluster_versions_event_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    representative_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_event_cluster_versions_representative_article_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    representative_title: Mapped[str] = mapped_column(Text, nullable=False)
    summary_projection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    event_time_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_time_precision: Mapped[str] = mapped_column(String(20), nullable=False)
    member_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_diversity: Mapped[int] = mapped_column(Integer, nullable=False)
    category_projection: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    entity_projection: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    clustering_policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    version_bundle_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "governance_runs.id",
            name="fk_event_cluster_versions_created_by_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_event_cluster_versions_version"),
        CheckConstraint("source_diversity >= 1", name="ck_event_cluster_versions_source_diversity"),
        CheckConstraint(
            "event_time_precision IN ('exact', 'day', 'month', 'unknown')",
            name="ck_event_cluster_versions_time_precision",
        ),
        UniqueConstraint("event_id", "version", name="uq_event_cluster_versions_event_version"),
        UniqueConstraint("id", "event_id", name="uq_event_cluster_versions_id_event"),
        UniqueConstraint(
            "event_id",
            "member_set_hash",
            "clustering_policy_version",
            "version_bundle_fingerprint",
            name="uq_event_cluster_versions_projection",
        ),
    )


class EventMembershipModel(Base):
    __tablename__ = "event_memberships"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("event_clusters.id", name="fk_event_memberships_event_id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "normalized_articles.id",
            name="fk_event_memberships_normalized_article_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    assignment_decision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_assignment_decisions.id",
            name="fk_event_memberships_assignment_decision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(active AND superseded_at IS NULL) OR (NOT active AND superseded_at IS NOT NULL)",
            name="ck_event_memberships_lifecycle",
        ),
        UniqueConstraint(
            "event_id",
            "normalized_article_id",
            "policy_version",
            name="uq_event_memberships_event_article_policy",
        ),
        Index(
            "uq_event_memberships_active_article_policy",
            "normalized_article_id",
            "policy_version",
            unique=True,
            postgresql_where=text("active = true"),
        ),
        Index("ix_event_memberships_event_id", "event_id"),
    )


class TopicScoringConfigModel(Base):
    __tablename__ = "topic_scoring_configs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    profile: Mapped[str] = mapped_column(String(40), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("profile", "version", name="uq_topic_scoring_configs_profile_version"),
        UniqueConstraint("fingerprint", name="uq_topic_scoring_configs_fingerprint"),
    )


class TopicSelectionRunModel(Base):
    __tablename__ = "topic_selection_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    scoring_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    config_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_scoring_configs.id",
            name="fk_topic_selection_runs_config_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    governed_event_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    selected_event_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_clusters.id",
            name="fk_topic_selection_runs_selected_event_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    selected_event_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_cluster_versions.id",
            name="fk_topic_selection_runs_selected_event_version_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    no_topic_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_selection_runs.id",
            name="fk_topic_selection_runs_superseded_by_run_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    total_scores: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    eligible_scores: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('manual', 'scheduled')",
            name="ck_topic_selection_runs_trigger",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_topic_selection_runs_status",
        ),
        CheckConstraint(
            "no_topic_code IS NULL OR no_topic_code IN "
            "('no_candidates', 'all_vetoed', 'below_threshold')",
            name="ck_topic_selection_runs_no_topic_code",
        ),
        CheckConstraint("total_scores >= 0", name="ck_topic_selection_runs_total_scores"),
        CheckConstraint("eligible_scores >= 0", name="ck_topic_selection_runs_eligible_scores"),
        CheckConstraint("revision >= 1", name="ck_topic_selection_runs_revision"),
        CheckConstraint(
            "(selected_event_id IS NULL) = (selected_event_version_id IS NULL)",
            name="ck_topic_selection_runs_selected_pair",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR "
            "((selected_event_id IS NOT NULL AND no_topic_code IS NULL) OR "
            "(selected_event_id IS NULL AND no_topic_code IS NOT NULL))",
            name="ck_topic_selection_runs_terminal_decision",
        ),
        UniqueConstraint(
            "business_date",
            "timezone",
            "scoring_profile",
            "revision",
            name="uq_topic_selection_runs_business_revision",
        ),
        ForeignKeyConstraint(
            ["selected_event_version_id", "selected_event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_topic_selection_runs_selected_event_version_event",
            ondelete="RESTRICT",
        ),
        Index("ix_topic_selection_runs_status_created", "status", "created_at"),
    )


class TopicSelectionJobModel(Base):
    __tablename__ = "topic_selection_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_selection_runs.id",
            name="fk_topic_selection_jobs_run_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_topic_selection_jobs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_topic_selection_jobs_attempt_count"),
        UniqueConstraint("run_id", name="uq_topic_selection_jobs_run_id"),
        Index("ix_topic_selection_jobs_claim", "status", "available_at", "lease_expires_at"),
    )


class TopicScoreModel(Base):
    __tablename__ = "topic_scores"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topic_selection_runs.id", name="fk_topic_scores_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("event_clusters.id", name="fk_topic_scores_event_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_cluster_versions.id",
            name="fk_topic_scores_event_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    raw_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    penalty_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    positive_components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    penalty_components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    passes_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    veto_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("rank >= 1", name="ck_topic_scores_rank"),
        CheckConstraint(
            "jsonb_typeof(veto_codes) = 'array'", name="ck_topic_scores_veto_codes_array"
        ),
        UniqueConstraint("run_id", "event_id", name="uq_topic_scores_run_event"),
        UniqueConstraint("run_id", "rank", name="uq_topic_scores_run_rank"),
        ForeignKeyConstraint(
            ["event_version_id", "event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_topic_scores_event_version_event",
            ondelete="RESTRICT",
        ),
        Index("ix_topic_scores_run_total", "run_id", "total"),
    )


class DailyTopicSelectionModel(Base):
    __tablename__ = "daily_topic_selections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    scoring_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_selection_runs.id",
            name="fk_daily_topic_selections_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    config_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_scoring_configs.id",
            name="fk_daily_topic_selections_config_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    selected_event_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_clusters.id",
            name="fk_daily_topic_selections_selected_event_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    selected_event_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "event_cluster_versions.id",
            name="fk_daily_topic_selections_selected_event_version_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    no_topic_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_selection_runs.id",
            name="fk_daily_topic_selections_superseded_by_run_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "decision_kind IN ('selected', 'no_topic')",
            name="ck_daily_topic_selections_decision_kind",
        ),
        CheckConstraint(
            "no_topic_code IS NULL OR no_topic_code IN "
            "('no_candidates', 'all_vetoed', 'below_threshold')",
            name="ck_daily_topic_selections_no_topic_code",
        ),
        CheckConstraint(
            "(decision_kind = 'selected' AND selected_event_id IS NOT NULL "
            "AND selected_event_version_id IS NOT NULL AND no_topic_code IS NULL) OR "
            "(decision_kind = 'no_topic' AND selected_event_id IS NULL "
            "AND selected_event_version_id IS NULL AND no_topic_code IS NOT NULL)",
            name="ck_daily_topic_selections_decision",
        ),
        UniqueConstraint("run_id", name="uq_daily_topic_selections_run_id"),
        ForeignKeyConstraint(
            ["selected_event_version_id", "selected_event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_daily_topic_selections_selected_event_version_event",
            ondelete="RESTRICT",
        ),
        Index("ix_daily_topic_selections_selected_event", "selected_event_id", "business_date"),
        Index(
            "uq_daily_topic_selections_current_business_key",
            "business_date",
            "timezone",
            "scoring_profile",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )


class BrandDocumentModel(Base):
    __tablename__ = "brand_documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    brand_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    document_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    audience: Mapped[str] = mapped_column(String(40), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("brand_slug = 'sai-xiansheng'", name="ck_brand_documents_single_brand"),
        CheckConstraint(
            "document_kind IN ('positioning', 'tone', 'approved_example', "
            "'prohibited_language', 'safety_rule', 'visual_guidance', 'other')",
            name="ck_brand_documents_kind",
        ),
        CheckConstraint("audience IN ('parents', 'internal')", name="ck_brand_documents_audience"),
        CheckConstraint("language = 'zh-CN'", name="ck_brand_documents_language"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_brand_documents_status"),
        UniqueConstraint("document_key", name="uq_brand_documents_document_key"),
        ForeignKeyConstraint(
            ["active_version_id", "id"],
            ["brand_document_versions.id", "brand_document_versions.document_id"],
            name="fk_brand_documents_active_version_document",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_brand_documents_scope", "brand_slug", "audience", "document_kind", "status"),
    )


class BrandDocumentVersionModel(Base):
    __tablename__ = "brand_document_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "brand_documents.id",
            name="fk_brand_document_versions_document_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(120), nullable=False)
    object_key: Mapped[str] = mapped_column(String(300), nullable=False)
    metadata_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    chunk_version: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_input_version: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    tone_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    safety_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    visual_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    extraction_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ocr_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ocr_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ocr_request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocr_provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ocr_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_brand_document_versions_version"),
        CheckConstraint("byte_size > 0", name="ck_brand_document_versions_byte_size"),
        CheckConstraint(
            "extraction_method IS NULL OR extraction_method IN ('local', 'ocr')",
            name="ck_brand_document_versions_extraction_method",
        ),
        CheckConstraint(
            "ocr_page_count IS NULL OR ocr_page_count BETWEEN 1 AND 100",
            name="ck_brand_document_versions_ocr_page_count",
        ),
        CheckConstraint(
            "ocr_prompt_tokens IS NULL OR ocr_prompt_tokens BETWEEN 0 AND 10000000",
            name="ck_brand_document_versions_ocr_prompt_tokens",
        ),
        CheckConstraint(
            "ocr_completion_tokens IS NULL OR ocr_completion_tokens BETWEEN 0 AND 10000000",
            name="ck_brand_document_versions_ocr_completion_tokens",
        ),
        CheckConstraint(
            "ocr_latency_ms IS NULL OR ocr_latency_ms BETWEEN 0 AND 3600000",
            name="ck_brand_document_versions_ocr_latency_ms",
        ),
        CheckConstraint(
            "extraction_method IS NULL OR extraction_method = 'local' OR "
            "(ocr_provider IS NOT NULL AND ocr_model IS NOT NULL AND "
            "ocr_request_fingerprint IS NOT NULL AND ocr_page_count IS NOT NULL)",
            name="ck_brand_document_versions_ocr_metadata",
        ),
        CheckConstraint(
            "embedding_dimensions = 2048", name="ck_brand_document_versions_dimensions"
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'ready', 'failed')",
            name="ck_brand_document_versions_status",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_brand_document_versions_validity",
        ),
        CheckConstraint("jsonb_typeof(tone_tags) = 'array'", name="ck_brand_versions_tone_tags"),
        CheckConstraint(
            "jsonb_typeof(safety_tags) = 'array'", name="ck_brand_versions_safety_tags"
        ),
        CheckConstraint(
            "jsonb_typeof(visual_tags) = 'array'", name="ck_brand_versions_visual_tags"
        ),
        UniqueConstraint(
            "document_id", "version", name="uq_brand_document_versions_document_version"
        ),
        UniqueConstraint("id", "document_id", name="uq_brand_document_versions_id_document"),
        Index(
            "uq_brand_document_versions_derivation",
            "document_id",
            "sha256",
            "metadata_fingerprint",
            "parser_version",
            "chunk_version",
            "embedding_input_version",
            "embedding_provider",
            "embedding_model",
            unique=True,
            postgresql_where=text("status <> 'failed'"),
        ),
        Index(
            "uq_brand_document_versions_one_active",
            "document_id",
            unique=True,
            postgresql_where=text("active = true"),
        ),
        Index("ix_brand_document_versions_status", "status", "created_at"),
        Index(
            "ix_brand_document_versions_extraction",
            "extraction_method",
            "ocr_provider",
            "ocr_model",
        ),
    )


class BrandIngestionJobModel(Base):
    __tablename__ = "brand_ingestion_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "brand_document_versions.id",
            name="fk_brand_ingestion_jobs_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry_scheduled', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_brand_ingestion_jobs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_brand_ingestion_jobs_attempt_count"),
        UniqueConstraint("version_id", name="uq_brand_ingestion_jobs_version_id"),
        Index("ix_brand_ingestion_jobs_claim", "status", "available_at", "lease_expires_at"),
    )


class BrandIngestionAttemptModel(Base):
    __tablename__ = "brand_ingestion_attempts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "brand_ingestion_jobs.id",
            name="fk_brand_ingestion_attempts_job_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'retry_scheduled', 'succeeded', 'failed')",
            name="ck_brand_ingestion_attempts_status",
        ),
        UniqueConstraint("job_id", "attempt_number", name="uq_brand_ingestion_attempts_job_number"),
        Index("ix_brand_ingestion_attempts_job_id", "job_id"),
    )


class BrandChunkModel(Base):
    __tablename__ = "brand_chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "brand_document_versions.id",
            name="fk_brand_chunks_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_key: Mapped[str] = mapped_column(String(64), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', text)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_brand_chunks_ordinal"),
        CheckConstraint(
            "char_start >= 0 AND char_end > char_start", name="ck_brand_chunks_offsets"
        ),
        UniqueConstraint("chunk_key", name="uq_brand_chunks_chunk_key"),
        UniqueConstraint("version_id", "ordinal", name="uq_brand_chunks_version_ordinal"),
        Index("ix_brand_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_brand_chunks_version_id", "version_id"),
    )


class BrandChunkEmbeddingModel(Base):
    __tablename__ = "brand_chunk_embeddings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    chunk_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "brand_chunks.id",
            name="fk_brand_chunk_embeddings_chunk_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_version: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    vector: Mapped[list[float]] = mapped_column(Vector(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("purpose = 'brand_retrieval'", name="ck_brand_chunk_embeddings_purpose"),
        CheckConstraint("dimensions = 2048", name="ck_brand_chunk_embeddings_dimensions"),
        UniqueConstraint(
            "chunk_id",
            "purpose",
            "provider",
            "model",
            "input_hash",
            "input_version",
            name="uq_brand_chunk_embeddings_derivation",
        ),
        UniqueConstraint("request_fingerprint", name="uq_brand_chunk_embeddings_request"),
        Index("ix_brand_chunk_embeddings_chunk_id", "chunk_id"),
    )


class CopyGenerationRunModel(Base):
    __tablename__ = "copy_generation_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    daily_topic_selection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "daily_topic_selections.id",
            name="fk_copy_generation_runs_daily_topic_selection_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    topic_selection_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "topic_selection_runs.id",
            name="fk_copy_generation_runs_topic_selection_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    scoring_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    selected_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    selected_event_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    no_topic_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(80), nullable=False)
    version_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version_bundle: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    active_draft_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    repair_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "decision_kind IN ('selected', 'no_topic')", name="ck_copy_generation_runs_decision"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'no_topic', 'accepted', 'review_required', 'failed')",
            name="ck_copy_generation_runs_status",
        ),
        CheckConstraint("repair_count BETWEEN 0 AND 1", name="ck_copy_generation_runs_repair"),
        CheckConstraint(
            "(decision_kind = 'selected' AND selected_event_id IS NOT NULL "
            "AND selected_event_version_id IS NOT NULL AND no_topic_code IS NULL) OR "
            "(decision_kind = 'no_topic' AND selected_event_id IS NULL "
            "AND selected_event_version_id IS NULL AND no_topic_code IS NOT NULL)",
            name="ck_copy_generation_runs_topic_shape",
        ),
        UniqueConstraint(
            "daily_topic_selection_id",
            "version_fingerprint",
            name="uq_copy_generation_runs_topic_version",
        ),
        ForeignKeyConstraint(
            ["selected_event_version_id", "selected_event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_copy_generation_runs_event_version_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["active_draft_version_id", "id"],
            ["copy_draft_versions.id", "copy_draft_versions.run_id"],
            name="fk_copy_generation_runs_active_draft_run",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_copy_generation_runs_status_created", "status", "created_at"),
    )


class CopyGenerationJobModel(Base):
    __tablename__ = "copy_generation_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_runs.id",
            name="fk_copy_generation_jobs_run_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'retry_scheduled', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_copy_generation_jobs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_copy_generation_jobs_attempt_count"),
        UniqueConstraint("run_id", name="uq_copy_generation_jobs_run_id"),
        Index("ix_copy_generation_jobs_claim", "status", "available_at", "lease_expires_at"),
    )


class CopyDraftVersionModel(Base):
    __tablename__ = "copy_draft_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_runs.id",
            name="fk_copy_draft_versions_run_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    repair_of_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    copywriting: Mapped[str] = mapped_column(Text, nullable=False)
    parent_takeaway: Mapped[str] = mapped_column(Text, nullable=False)
    interaction: Mapped[str] = mapped_column(Text, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    image_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    validation_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audit_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("version IN (1, 2)", name="ck_copy_draft_versions_version"),
        CheckConstraint(
            "(version = 1 AND repair_of_version_id IS NULL) OR "
            "(version = 2 AND repair_of_version_id IS NOT NULL)",
            name="ck_copy_draft_versions_repair_lineage",
        ),
        UniqueConstraint("id", "run_id", name="uq_copy_draft_versions_id_run"),
        ForeignKeyConstraint(
            ["repair_of_version_id", "run_id"],
            ["copy_draft_versions.id", "copy_draft_versions.run_id"],
            name="fk_copy_draft_versions_repair_same_run",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "version", name="uq_copy_draft_versions_run_version"),
        UniqueConstraint("provider", "request_fingerprint", name="uq_copy_draft_versions_request"),
        Index("ix_copy_draft_versions_run_id", "run_id"),
    )


class CopyGenerationAttemptModel(Base):
    __tablename__ = "copy_generation_attempts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_jobs.id",
            name="fk_copy_generation_attempts_job_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    draft_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_copy_generation_attempts_draft_version_id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "capability IN ('generation', 'audit', 'workflow')",
            name="ck_copy_generation_attempts_capability",
        ),
        CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_copy_generation_attempts_status"
        ),
        UniqueConstraint(
            "capability", "request_fingerprint", name="uq_copy_generation_attempts_request"
        ),
        Index("ix_copy_generation_attempts_job_id", "job_id"),
    )


class CopyDraftClaimModel(Base):
    __tablename__ = "copy_draft_claims"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    draft_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_copy_draft_claims_draft_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    claim_key: Mapped[str] = mapped_column(String(80), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('external_fact', 'brand_statement', 'opinion')",
            name="ck_copy_draft_claims_kind",
        ),
        CheckConstraint("ordinal >= 0", name="ck_copy_draft_claims_ordinal"),
        UniqueConstraint("draft_version_id", "claim_key", name="uq_copy_draft_claims_draft_key"),
        UniqueConstraint("draft_version_id", "ordinal", name="uq_copy_draft_claims_draft_ordinal"),
    )


class CopyClaimEvidenceBindingModel(Base):
    __tablename__ = "copy_claim_evidence_bindings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_claims.id",
            name="fk_copy_claim_evidence_bindings_claim_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    evidence_binding_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    passage_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    occurrence_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exact_quote: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("source_tier IN ('A', 'B')", name="ck_copy_evidence_source_tier"),
        ForeignKeyConstraint(
            [
                "evidence_binding_id",
                "candidate_id",
                "passage_id",
                "occurrence_id",
                "snapshot_id",
            ],
            [
                "evidence_bindings.id",
                "evidence_bindings.candidate_id",
                "evidence_bindings.passage_id",
                "evidence_bindings.occurrence_id",
                "evidence_bindings.snapshot_id",
            ],
            name="fk_copy_claim_evidence_bindings_provenance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("claim_id", "evidence_binding_id", name="uq_copy_claim_evidence_binding"),
    )


class CopyClaimBrandBindingModel(Base):
    __tablename__ = "copy_claim_brand_bindings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_claims.id",
            name="fk_copy_claim_brand_bindings_claim_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    brand_chunk_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "brand_chunks.id",
            name="fk_copy_claim_brand_bindings_brand_chunk_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("claim_id", "brand_chunk_id", name="uq_copy_claim_brand_binding"),
    )


class CopyValidationResultModel(Base):
    __tablename__ = "copy_validation_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    draft_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_copy_validation_results_draft_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("draft_version_id", name="uq_copy_validation_results_draft"),
        UniqueConstraint("result_fingerprint", name="uq_copy_validation_results_fingerprint"),
    )


class CopyAuditModel(Base):
    __tablename__ = "copy_audits"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    draft_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_copy_audits_draft_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_attempts.id",
            name="fk_copy_audits_attempt_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("draft_version_id", name="uq_copy_audits_draft"),
        UniqueConstraint("result_fingerprint", name="uq_copy_audits_fingerprint"),
    )


class CopyIssueModel(Base):
    __tablename__ = "copy_issues"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    draft_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_copy_issues_draft_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    audit_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("copy_audits.id", name="fk_copy_issues_audit_id", ondelete="CASCADE"),
        nullable=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    claim_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_message: Mapped[str] = mapped_column(String(240), nullable=False)

    __table_args__ = (
        CheckConstraint("stage IN ('deterministic', 'audit')", name="ck_copy_issues_stage"),
        CheckConstraint(
            "(stage = 'deterministic' AND audit_id IS NULL) OR "
            "(stage = 'audit' AND audit_id IS NOT NULL)",
            name="ck_copy_issues_stage_audit_shape",
        ),
        CheckConstraint("severity IN ('warning', 'error')", name="ck_copy_issues_severity"),
        CheckConstraint("ordinal >= 0", name="ck_copy_issues_ordinal"),
        UniqueConstraint(
            "draft_version_id", "stage", "ordinal", name="uq_copy_issues_draft_stage_ordinal"
        ),
    )


class CopyGenerationCheckpointModel(Base):
    __tablename__ = "copy_generation_checkpoints"

    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_runs.id",
            name="fk_copy_generation_checkpoints_run_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    draft_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    issue_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(issue_codes) = 'array'", name="ck_copy_checkpoints_issue_codes_array"
        ),
    )


class ImageArtifactModel(Base):
    __tablename__ = "image_artifacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_runs.id", name="fk_image_artifacts_run_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    draft_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_image_artifacts_draft_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reference_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'legacy_single'")
    )
    visual_brief_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provider_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_upload_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(120), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    storage_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(
            '\'{"access": "private", "immutable": true, "content_addressed": true}\'::jsonb'
        ),
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'review_required')",
            name="ck_image_artifacts_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_image_artifacts_attempt_count"),
        CheckConstraint(
            "reference_mode IN ("
            "'legacy_single', 'single_reference', 'single_fallback', "
            "'budgeted_multi_reference', 'multi_reference'"
            ")",
            name="ck_image_artifacts_reference_mode",
        ),
        CheckConstraint(
            "jsonb_typeof(visual_brief_snapshot) = 'object'",
            name="ck_image_artifacts_visual_brief_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(storage_metadata) = 'object'",
            name="ck_image_artifacts_storage_metadata_object",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND media_type IS NOT NULL AND width = 1024 AND height = 1024 "
            "AND byte_size IS NOT NULL AND sha256 IS NOT NULL AND bucket IS NOT NULL "
            "AND object_key IS NOT NULL) "
            "OR status <> 'succeeded'",
            name="ck_image_artifacts_success_shape",
        ),
        UniqueConstraint("request_fingerprint", name="uq_image_artifacts_request_fingerprint"),
        UniqueConstraint("run_id", "draft_version_id", name="uq_image_artifacts_run_draft"),
        Index(
            "ix_image_artifacts_claim",
            "status",
            "available_at",
            "lease_expires_at",
        ),
        Index("ix_image_artifacts_status_created", "status", "created_at"),
    )


class ImageArtifactReferenceModel(Base):
    __tablename__ = "image_artifact_references"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    image_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "image_artifacts.id",
            name="fk_image_artifact_references_artifact_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_role: Mapped[str] = mapped_column(String(40), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(80), nullable=False)
    selector_version: Mapped[str] = mapped_column(String(80), nullable=False)
    selection_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_image_artifact_references_ordinal"),
        CheckConstraint("asset_id <> ''", name="ck_image_artifact_references_asset_id"),
        CheckConstraint("reference_role <> ''", name="ck_image_artifact_references_role"),
        UniqueConstraint(
            "image_artifact_id", "ordinal", name="uq_image_artifact_references_artifact_ordinal"
        ),
        Index("ix_image_artifact_references_asset_id", "asset_id"),
    )


class MaterialPackageModel(Base):
    __tablename__ = "material_packages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_generation_runs.id", name="fk_material_packages_run_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    draft_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "copy_draft_versions.id",
            name="fk_material_packages_draft_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    image_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "image_artifacts.id", name="fk_material_packages_image_artifact_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    package_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    topic_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    copy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    brand_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    validation_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    audit_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    review_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'pending'")
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'ready', 'awaiting_manual_use', 'completed', "
            "'rejected', 'failed')",
            name="ck_material_packages_status",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_material_packages_review_status",
        ),
        CheckConstraint("package_version >= 1", name="ck_material_packages_version"),
        CheckConstraint(
            "jsonb_typeof(brand_snapshot) = 'array'",
            name="ck_material_packages_brand_snapshot_array",
        ),
        CheckConstraint(
            "jsonb_typeof(validation_snapshot) = 'object'",
            name="ck_material_packages_validation_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(version_snapshot) = 'object'",
            name="ck_material_packages_version_snapshot_object",
        ),
        UniqueConstraint("run_id", "package_version", name="uq_material_packages_run_version"),
        UniqueConstraint("request_fingerprint", name="uq_material_packages_request_fingerprint"),
        Index("ix_material_packages_status_created", "status", "created_at"),
    )


class MaterialReviewModel(Base):
    __tablename__ = "material_reviews"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    package_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "material_packages.id", name="fk_material_reviews_package_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_material_reviews_decision"
        ),
        UniqueConstraint("package_id", name="uq_material_reviews_package_id"),
    )
