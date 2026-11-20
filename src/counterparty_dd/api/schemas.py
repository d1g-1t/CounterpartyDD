from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from counterparty_dd.domain.enums import (
    AlertStatus,
    ApprovalStatus,
    CaseStatus,
    CounterpartyType,
    EdgeBasis,
    ListKind,
    NodeKind,
    Severity,
    TaskStatus,
    UboExemption,
)

Inn = Annotated[str, StringConstraints(pattern=r"^\d{10}(\d{2})?$")]
Ogrn = Annotated[str, StringConstraints(pattern=r"^\d{13}(\d{2})?$")]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=512)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


class MeOut(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: str


class CaseIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    counterparty_type: CounterpartyType
    business_unit: str | None = Field(default=None, max_length=128)
    owner_user_id: UUID | None = None


class CasePatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)] | None = None
    business_unit: str | None = Field(default=None, max_length=128)
    owner_user_id: UUID | None = None


class AssignIn(BaseModel):
    owner_user_id: UUID


class TransitionIn(BaseModel):
    status: CaseStatus
    reason: str | None = Field(default=None, max_length=2000)


class CaseOut(Orm):
    id: UUID
    tenant_id: UUID
    case_number: str
    title: str
    status: str
    counterparty_type: str
    business_unit: str | None
    owner_user_id: UUID | None
    risk_level: str | None
    created_at: datetime
    updated_at: datetime


class CounterpartyIn(BaseModel):
    legal_name: Text
    inn: Inn | None = None
    ogrn: Ogrn | None = None
    country_code: Country | None = "RU"
    address: str | None = Field(default=None, max_length=1000)
    registered_on: date | None = None
    ubo_exemption: UboExemption | None = None


class RegistryIn(BaseModel):
    egrul_unreliable_since: date | None = None
    pending_exclusion: bool = False
    registered_on: date | None = None


class CounterpartyOut(Orm):
    id: UUID
    case_id: UUID
    legal_name: str
    normalized_name: str
    inn: str | None
    ogrn: str | None
    country_code: str | None
    address: str | None
    registered_on: date | None
    egrul_unreliable_since: date | None
    pending_exclusion: bool
    ubo_exemption: str | None
    node_id: UUID


class PersonIn(BaseModel):
    full_name: Text
    relation_type: Annotated[str, StringConstraints(pattern=r"^(DIRECTOR|SIGNATORY|FOUNDER|ACCOUNTANT|OTHER)$")]
    inn: Inn | None = None
    birth_date: date | None = None
    citizenship: Country | None = None


class PersonOut(Orm):
    id: UUID
    full_name: str
    normalized_name: str
    relation_type: str
    inn: str | None
    birth_date: date | None
    citizenship: str | None


class CounterpartyView(BaseModel):
    profile: CounterpartyOut | None
    related_persons: list[PersonOut]


class SourceIn(BaseModel):
    name: Text
    list_kind: ListKind
    version_label: str | None = Field(default=None, max_length=64)


class SourcePatch(BaseModel):
    active: bool


class SourceOut(Orm):
    id: UUID
    name: str
    list_kind: str
    version_label: str | None
    active: bool


class EntryIn(BaseModel):
    name: Text
    inn: Inn | None = None
    ogrn: Ogrn | None = None
    birth_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class EntriesIn(BaseModel):
    entries: list[EntryIn] = Field(min_length=1, max_length=5000)


class RunIn(BaseModel):
    threshold: float | None = Field(default=None, ge=0.3, le=1.0)


class RunOut(Orm):
    id: UUID
    threshold: float
    subjects_count: int
    entries_count: int
    alerts_count: int
    created_at: datetime


class AlertOut(Orm):
    id: UUID
    run_id: UUID
    subject_type: str
    subject_id: UUID
    subject_name: str
    list_kind: str
    matched_name: str
    score: float
    status: str
    explanation: dict[str, Any]
    disposition_reason: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None


class DisposeIn(BaseModel):
    status: AlertStatus
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class NodeIn(BaseModel):
    kind: NodeKind
    display_name: Text
    inn: Inn | None = None
    ogrn: Ogrn | None = None
    birth_date: date | None = None
    exemption: UboExemption | None = None


class NodeOut(Orm):
    id: UUID
    kind: str
    display_name: str
    inn: str | None
    ogrn: str | None
    exemption: str | None


class EdgeIn(BaseModel):
    source_id: UUID
    target_id: UUID
    basis: EdgeBasis
    share_percent: Decimal | None = Field(default=None, gt=0, le=100, max_digits=9, decimal_places=4)
    evidence: list[str] = Field(default_factory=list, max_length=20)


class EdgeOut(Orm):
    id: UUID
    source_id: UUID
    target_id: UUID
    basis: str
    share_percent: Decimal | None
    evidence: list[str]


class GraphOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class OwnerOut(Orm):
    node_id: UUID
    name: str
    bases: list[str]
    effective_percent: Decimal
    requires_decision: bool
    paths: list[dict[str, Any]]


class AnalysisOut(BaseModel):
    status: str | None
    exemption: str | None = None
    traced_percent: Decimal | None = None
    opaque_percent: Decimal | None = None
    flags: list[str] = Field(default_factory=list)
    owners: dict[str, Decimal] = Field(default_factory=dict)
    beneficial_owners: list[OwnerOut] = Field(default_factory=list)
    legal_basis: list[str] = Field(default_factory=list)


class FactOut(BaseModel):
    code: str
    fact_class: str
    title: str
    legal_ref: str


class TaxCheckIn(BaseModel):
    facts: list[Annotated[str, StringConstraints(pattern=r"^[A-Z_]{3,40}$")]] = Field(
        default_factory=list, max_length=40
    )
    comment: str | None = Field(default=None, max_length=4000)


class TaxCheckOut(Orm):
    id: UUID
    verdict: str
    facts: list[str]
    reasons: list[str]
    comment: str | None
    created_by: UUID
    created_at: datetime


class MediaIn(BaseModel):
    title: Text
    severity: Severity
    source_url: str | None = Field(default=None, max_length=1024)
    published_on: date | None = None
    summary: str | None = Field(default=None, max_length=4000)


class MediaOut(Orm):
    id: UUID
    title: str
    severity: str
    source_url: str | None
    published_on: date | None


class EvidenceIn(BaseModel):
    title: Text
    evidence_type: Annotated[
        str, StringConstraints(pattern=r"^(REGISTRY_EXTRACT|CONTRACT|AUTHORITY_PROOF|RESOURCE_PROOF|OTHER)$")
    ]
    sha256: Sha256
    file_name: str | None = Field(default=None, max_length=255)


class EvidenceOut(Orm):
    id: UUID
    title: str
    evidence_type: str
    file_name: str | None
    sha256: str
    created_at: datetime


class RiskIn(BaseModel):
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=4000)]


class RiskOut(Orm):
    id: UUID
    inherent: float
    residual: float
    level: str
    factors: dict[str, float]
    overrides: list[str]
    rationale: str
    created_at: datetime


class TaskIn(BaseModel):
    title: Text
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=4000)]
    owner_user_id: UUID | None = None
    due_at: datetime | None = None


class TaskClose(BaseModel):
    status: TaskStatus


class TaskOut(Orm):
    id: UUID
    title: str
    description: str
    owner_user_id: UUID | None
    due_at: datetime | None
    status: str
    closed_at: datetime | None


class DecisionIn(BaseModel):
    status: ApprovalStatus
    note: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=4000)


class DecisionOut(Orm):
    id: UUID
    status: str
    note: str | None
    reason: str | None
    risk_level: str | None
    decided_by: UUID
    decided_at: datetime


class CompletenessOut(BaseModel):
    score: float
    missing: list[str]
    committee_ready: bool


class MonitoringIn(BaseModel):
    interval_days: int | None = Field(default=None, ge=1, le=365)


class MonitoringOut(Orm):
    status: str
    interval_days: int
    next_run_at: datetime
    last_run_at: datetime | None


class EventOut(Orm):
    seq: int
    event_type: str
    actor_id: UUID | None
    payload: dict[str, Any]
    hash: str
    created_at: datetime


class ChainOut(BaseModel):
    valid: bool
    events: int
    broken_at: int | None
