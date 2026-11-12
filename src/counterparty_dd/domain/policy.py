from dataclasses import dataclass
from datetime import datetime, timedelta

from counterparty_dd.domain.enums import CASE_TRANSITIONS, ApprovalStatus, CaseStatus, RiskLevel, UserRole
from counterparty_dd.domain.errors import Conflict, Forbidden, InvalidTransition

RESCREEN_DAYS = {RiskLevel.CRITICAL: 30, RiskLevel.HIGH: 90, RiskLevel.MEDIUM: 180, RiskLevel.LOW: 365}

REQUIRED_CHECKS = {
    "counterparty": "Не заполнен профиль контрагента",
    "screening": "Не проведён скрининг по спискам",
    "alerts_resolved": "Есть нерассмотренные алерты",
    "ownership": "Не определены бенефициарные владельцы",
    "tax_check": "Не проведена проверка по ст. 54.1 НК РФ",
    "risk": "Нет оценки риска",
}
RECOMMENDED_CHECKS = {
    "adverse_media": "Не проверены негативные публикации",
    "evidence": "Не приложены подтверждающие документы",
    "remediation_closed": "Есть открытые задачи по устранению замечаний",
}


@dataclass(frozen=True, slots=True)
class Completeness:
    score: float
    missing: tuple[str, ...]
    committee_ready: bool


def completeness(flags: dict[str, bool]) -> Completeness:
    missing: list[str] = []
    score = 0.0
    for checks, weight in ((REQUIRED_CHECKS, 80.0), (RECOMMENDED_CHECKS, 20.0)):
        for key, message in checks.items():
            if flags.get(key, False):
                score += weight / len(checks)
            else:
                missing.append(message)
    ready = all(flags.get(k, False) for k in REQUIRED_CHECKS)
    return Completeness(round(score, 1), tuple(missing), ready)


def check_transition(current: CaseStatus, target: CaseStatus, role: UserRole) -> None:
    if target not in CASE_TRANSITIONS[current]:
        raise InvalidTransition(f"Переход {current} → {target} не предусмотрен")
    if target in (CaseStatus.APPROVED, CaseStatus.CLOSED) and not role.can_approve:
        raise Forbidden("Одобрять и закрывать проверку может только комплаенс-офицер")


def check_decision(
    status: ApprovalStatus,
    *,
    case_status: CaseStatus,
    ready: Completeness,
    risk_level: RiskLevel | None,
    reason: str | None,
    decided_by: str,
    case_owner: str | None,
) -> CaseStatus:
    if case_status is not CaseStatus.UNDER_REVIEW:
        raise InvalidTransition("Решение принимается только по проверке в статусе UNDER_REVIEW")
    if case_owner is not None and decided_by == case_owner:
        raise Forbidden("Решение принимает не исполнитель проверки (принцип четырёх глаз)")
    if status is ApprovalStatus.REJECTED:
        if not reason:
            raise Conflict("Отказ требует обоснования")
        return CaseStatus.CLOSED
    if not ready.committee_ready:
        raise Conflict("Досье неполное: " + "; ".join(m for m in ready.missing if m in REQUIRED_CHECKS.values()))
    if status is ApprovalStatus.CONDITIONALLY_APPROVED and not reason:
        raise Conflict("Условное одобрение требует обоснования")
    if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL) and not reason:
        raise Conflict("Одобрение при высоком риске требует обоснования (ручное решение)")
    return CaseStatus.APPROVED


def next_rescreen(level: RiskLevel, now: datetime) -> datetime:
    return now + timedelta(days=RESCREEN_DAYS[level])
