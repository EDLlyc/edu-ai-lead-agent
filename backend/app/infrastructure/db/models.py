from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
