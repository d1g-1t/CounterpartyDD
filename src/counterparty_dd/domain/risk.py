from dataclasses import dataclass, field

from counterparty_dd.domain.enums import CounterpartyType, ListKind, RiskLevel, Severity
from counterparty_dd.domain.ownership import UboStatus
from counterparty_dd.domain.tax_diligence import Verdict

WEIGHTS = {
    "tax": 0.30,
    "ownership": 0.20,
    "screening": 0.20,
    "adverse_media": 0.15,
    "country": 0.10,
    "type": 0.05,
}
TAX_SCORES = {Verdict.LOW: 0.0, Verdict.ELEVATED: 50.0, Verdict.HIGH: 80.0, Verdict.CONDITIONS_NOT_MET: 100.0}
OWNERSHIP_SCORES = {
    UboStatus.EXEMPT: 0.0,
    UboStatus.RESOLVED: 10.0,
    UboStatus.EXECUTIVE_FALLBACK: 60.0,
    UboStatus.UNRESOLVED: 90.0,
}
SEVERITY_SCORES = {Severity.LOW: 20.0, Severity.MEDIUM: 50.0, Severity.HIGH: 80.0, Severity.CRITICAL: 100.0}
TYPE_SCORES = {
    CounterpartyType.MA_TARGET: 70.0,
    CounterpartyType.INVESTOR: 60.0,
    CounterpartyType.PARTNER: 50.0,
    CounterpartyType.CONTRACTOR: 45.0,
    CounterpartyType.SUPPLIER: 40.0,
    CounterpartyType.CUSTOMER: 30.0,
    CounterpartyType.OTHER: 50.0,
}
BLOCKING_LISTS = frozenset({ListKind.TERRORISM_EXTREMISM, ListKind.SANCTIONS})
MITIGATION_PER_TASK = 0.10
MITIGATION_CAP = 0.30


@dataclass(frozen=True, slots=True)
class RiskInputs:
    counterparty_type: CounterpartyType
    tax_verdict: Verdict | None
    ubo_status: UboStatus | None
    opaque_share_over_threshold: bool
    open_alerts: int
    confirmed_lists: frozenset[ListKind]
    list_exposure_upstream: bool
    adverse_media: tuple[Severity, ...]
    country_code: str | None
    high_risk_countries: frozenset[str] = field(default_factory=frozenset)
    completed_remediations: int = 0


@dataclass(frozen=True, slots=True)
class RiskResult:
    inherent: float
    residual: float
    level: RiskLevel
    factors: dict[str, float]
    overrides: tuple[str, ...]


def level_for(score: float) -> RiskLevel:
    if score >= 70:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 30:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def score(inputs: RiskInputs) -> RiskResult:
    tax = 50.0 if inputs.tax_verdict is None else TAX_SCORES[inputs.tax_verdict]
    ownership = 70.0 if inputs.ubo_status is None else OWNERSHIP_SCORES[inputs.ubo_status]
    if inputs.opaque_share_over_threshold:
        ownership = max(ownership, 60.0)
    screening = min(inputs.open_alerts * 25.0, 75.0)
    if inputs.confirmed_lists - BLOCKING_LISTS:
        screening = max(screening, 70.0)
    if inputs.confirmed_lists & BLOCKING_LISTS or inputs.list_exposure_upstream:
        screening = 100.0
    media = max((SEVERITY_SCORES[s] for s in inputs.adverse_media), default=0.0)
    if inputs.country_code is None:
        country = 30.0
    else:
        country = 90.0 if inputs.country_code.upper() in inputs.high_risk_countries else 10.0
    factors = {
        "tax": tax,
        "ownership": ownership,
        "screening": screening,
        "adverse_media": media,
        "country": country,
        "type": TYPE_SCORES[inputs.counterparty_type],
    }
    inherent = round(sum(factors[k] * w for k, w in WEIGHTS.items()), 2)
    overrides: list[str] = []
    if inputs.confirmed_lists & BLOCKING_LISTS:
        overrides.append("Подтверждено совпадение с перечнем или санкционным списком")
    if inputs.list_exposure_upstream:
        overrides.append("Владелец или контролирующее лицо подтверждено в перечне (п. 2 ст. 6 115-ФЗ)")
    if inputs.tax_verdict is Verdict.CONDITIONS_NOT_MET:
        overrides.append("Не соблюдены условия ст. 54.1 НК РФ")
    if overrides:
        inherent = max(inherent, 70.0)
    mitigation = min(inputs.completed_remediations * MITIGATION_PER_TASK, MITIGATION_CAP)
    residual = inherent if overrides else round(inherent * (1 - mitigation), 2)
    return RiskResult(inherent, residual, level_for(residual), factors, tuple(overrides))
