from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = JSON().with_variant(JSONB(), "postgresql")
Tz = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class CaseChild(IdMixin):
    case_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("cases.id", ondelete="CASCADE"), index=True)


class UserModel(IdMixin, Base):
    __tablename__ = "users"
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(Tz)


class CaseModel(IdMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (Index("ix_cases_tenant_status", "tenant_id", "status"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    case_number: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    counterparty_type: Mapped[str] = mapped_column(String(32))
    business_unit: Mapped[str | None] = mapped_column(String(128))
    owner_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    risk_level: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(Tz)
    updated_at: Mapped[datetime] = mapped_column(Tz)


class CounterpartyModel(CaseChild, Base):
    __tablename__ = "counterparties"
    __table_args__ = (UniqueConstraint("case_id", name="uq_counterparties_case"),)
    legal_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    inn: Mapped[str | None] = mapped_column(String(12), index=True)
    ogrn: Mapped[str | None] = mapped_column(String(15))
    country_code: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    registered_on: Mapped[date | None] = mapped_column(Date)
    egrul_unreliable_since: Mapped[date | None] = mapped_column(Date)
    pending_exclusion: Mapped[bool] = mapped_column(Boolean, default=False)
    ubo_exemption: Mapped[str | None] = mapped_column(String(48))
    node_id: Mapped[UUID] = mapped_column(Uuid)


class RelatedPersonModel(CaseChild, Base):
    __tablename__ = "related_persons"
    full_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    relation_type: Mapped[str] = mapped_column(String(32))
    inn: Mapped[str | None] = mapped_column(String(12))
    birth_date: Mapped[date | None] = mapped_column(Date)
    citizenship: Mapped[str | None] = mapped_column(String(2))


class WatchlistSourceModel(IdMixin, Base):
    __tablename__ = "watchlist_sources"
    tenant_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(255))
    list_kind: Mapped[str] = mapped_column(String(32))
    version_label: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Tz)


class WatchlistEntryModel(IdMixin, Base):
    __tablename__ = "watchlist_entries"
    source_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("watchlist_sources.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    inn: Mapped[str | None] = mapped_column(String(12), index=True)
    ogrn: Mapped[str | None] = mapped_column(String(15))
    birth_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class ScreeningRunModel(CaseChild, Base):
    __tablename__ = "screening_runs"
    threshold: Mapped[float] = mapped_column(Float)
    subjects_count: Mapped[int] = mapped_column(Integer)
    entries_count: Mapped[int] = mapped_column(Integer)
    alerts_count: Mapped[int] = mapped_column(Integer)
    started_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(Tz)


class AlertModel(CaseChild, Base):
    __tablename__ = "screening_alerts"
    __table_args__ = (Index("ix_alerts_case_status", "case_id", "status"),)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("screening_runs.id", ondelete="CASCADE"))
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    subject_name: Mapped[str] = mapped_column(String(512))
    entry_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("watchlist_entries.id", ondelete="CASCADE"))
    list_kind: Mapped[str] = mapped_column(String(32))
    matched_name: Mapped[str] = mapped_column(String(512))
    score: Mapped[float] = mapped_column(Float)
    explanation: Mapped[dict[str, Any]] = mapped_column(Json)
    status: Mapped[str] = mapped_column(String(16))
    disposition_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(Tz)
    created_at: Mapped[datetime] = mapped_column(Tz)


class NodeModel(CaseChild, Base):
    __tablename__ = "ownership_nodes"
    kind: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(512))
    inn: Mapped[str | None] = mapped_column(String(12))
    ogrn: Mapped[str | None] = mapped_column(String(15))
    birth_date: Mapped[date | None] = mapped_column(Date)
    exemption: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(Tz)


class EdgeModel(CaseChild, Base):
    __tablename__ = "ownership_edges"
    source_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("ownership_nodes.id", ondelete="CASCADE"))
    target_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("ownership_nodes.id", ondelete="CASCADE"))
    basis: Mapped[str] = mapped_column(String(32))
    share_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    evidence: Mapped[list[str]] = mapped_column(Json, default=list)
    created_at: Mapped[datetime] = mapped_column(Tz)


class OwnershipAnalysisModel(CaseChild, Base):
    __tablename__ = "ownership_analyses"
    __table_args__ = (UniqueConstraint("case_id", name="uq_ownership_analyses_case"),)
    target_node_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(32))
    exemption: Mapped[str | None] = mapped_column(String(48))
    traced_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    opaque_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    flags: Mapped[list[str]] = mapped_column(Json, default=list)
    computed_at: Mapped[datetime] = mapped_column(Tz)


class BeneficialOwnerModel(CaseChild, Base):
    __tablename__ = "beneficial_owners"
    node_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("ownership_nodes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(512))
    bases: Mapped[list[str]] = mapped_column(Json)
    effective_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    requires_decision: Mapped[bool] = mapped_column(Boolean, default=False)
    paths: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)


class TaxCheckModel(CaseChild, Base):
    __tablename__ = "tax_checks"
    facts: Mapped[list[str]] = mapped_column(Json)
    verdict: Mapped[str] = mapped_column(String(32))
    reasons: Mapped[list[str]] = mapped_column(Json)
    comment: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(Tz)


class AdverseMediaModel(CaseChild, Base):
    __tablename__ = "adverse_media"
    title: Mapped[str] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    severity: Mapped[str] = mapped_column(String(16))
    published_on: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Tz)


class EvidenceModel(CaseChild, Base):
    __tablename__ = "evidence_items"
    title: Mapped[str] = mapped_column(String(512))
    evidence_type: Mapped[str] = mapped_column(String(32))
    file_name: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(Tz)


class RiskAssessmentModel(CaseChild, Base):
    __tablename__ = "risk_assessments"
    inherent: Mapped[float] = mapped_column(Float)
    residual: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(16))
    factors: Mapped[dict[str, float]] = mapped_column(Json)
    overrides: Mapped[list[str]] = mapped_column(Json)
    rationale: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(Tz)


class RemediationTaskModel(CaseChild, Base):
    __tablename__ = "remediation_tasks"
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    due_at: Mapped[datetime | None] = mapped_column(Tz)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(Tz)
    closed_at: Mapped[datetime | None] = mapped_column(Tz)


class ApprovalDecisionModel(CaseChild, Base):
    __tablename__ = "approval_decisions"
    status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(16))
    decided_by: Mapped[UUID] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(Tz)


class MonitoringModel(CaseChild, Base):
    __tablename__ = "monitoring_subscriptions"
    __table_args__ = (UniqueConstraint("case_id", name="uq_monitoring_case"),)
    status: Mapped[str] = mapped_column(String(16))
    interval_days: Mapped[int] = mapped_column(Integer)
    next_run_at: Mapped[datetime] = mapped_column(Tz, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(Tz)


class AuditEventModel(IdMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "seq", name="uq_audit_tenant_seq"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    seq: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(Json)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Tz)
