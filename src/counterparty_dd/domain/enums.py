from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    ANALYST = "ANALYST"
    AUDITOR = "AUDITOR"

    @property
    def can_write(self) -> bool:
        return self in {UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER, UserRole.ANALYST}

    @property
    def can_approve(self) -> bool:
        return self in {UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER}


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    SCREENING = "SCREENING"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMEDIATION = "REMEDIATION"
    APPROVED = "APPROVED"
    MONITORED = "MONITORED"
    CLOSED = "CLOSED"


CASE_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.SCREENING, CaseStatus.CLOSED}),
    CaseStatus.SCREENING: frozenset({CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED}),
    CaseStatus.UNDER_REVIEW: frozenset({CaseStatus.REMEDIATION, CaseStatus.APPROVED, CaseStatus.CLOSED}),
    CaseStatus.REMEDIATION: frozenset({CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED}),
    CaseStatus.APPROVED: frozenset({CaseStatus.MONITORED, CaseStatus.CLOSED}),
    CaseStatus.MONITORED: frozenset({CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED}),
    CaseStatus.CLOSED: frozenset(),
}


class CounterpartyType(StrEnum):
    SUPPLIER = "SUPPLIER"
    CUSTOMER = "CUSTOMER"
    CONTRACTOR = "CONTRACTOR"
    PARTNER = "PARTNER"
    MA_TARGET = "MA_TARGET"
    INVESTOR = "INVESTOR"
    OTHER = "OTHER"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NodeKind(StrEnum):
    PERSON = "PERSON"
    LEGAL_ENTITY = "LEGAL_ENTITY"
    FOREIGN_STRUCTURE = "FOREIGN_STRUCTURE"


class EdgeBasis(StrEnum):
    EQUITY = "EQUITY"
    CONTROL = "CONTROL"
    NOMINEE = "NOMINEE"
    EXECUTIVE_BODY = "EXECUTIVE_BODY"


class UboExemption(StrEnum):
    PUBLIC_BODY = "PUBLIC_BODY"
    INTERNATIONAL_ORGANIZATION = "INTERNATIONAL_ORGANIZATION"
    RELIGIOUS_ORGANIZATION = "RELIGIOUS_ORGANIZATION"
    LISTED_ISSUER = "LISTED_ISSUER"
    FOREIGN_LISTED_COMPANY = "FOREIGN_LISTED_COMPANY"
    FOREIGN_STRUCTURE_WITHOUT_UBO = "FOREIGN_STRUCTURE_WITHOUT_UBO"


class UboBasis(StrEnum):
    OWNERSHIP = "OWNERSHIP"
    CONTROL = "CONTROL"
    EXECUTIVE_FALLBACK = "EXECUTIVE_FALLBACK"


class ListKind(StrEnum):
    TERRORISM_EXTREMISM = "TERRORISM_EXTREMISM"
    SANCTIONS = "SANCTIONS"
    DISQUALIFIED = "DISQUALIFIED"
    PEP = "PEP"
    INTERNAL = "INTERNAL"


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    DISMISSED = "DISMISSED"
    CONFIRMED = "CONFIRMED"


class ApprovalStatus(StrEnum):
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    REJECTED = "REJECTED"


class MonitoringStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
