from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from counterparty_dd.domain.terms import add_months


class FactClass(StrEnum):
    CONDITION_BREACH = "CONDITION_BREACH"
    REALITY_INDICATOR = "REALITY_INDICATOR"
    REGISTRY_SIGNAL = "REGISTRY_SIGNAL"
    NOT_STANDALONE = "NOT_STANDALONE"
    CONTEXTUAL = "CONTEXTUAL"


class Verdict(StrEnum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CONDITIONS_NOT_MET = "CONDITIONS_NOT_MET"


VERDICT_ORDER = (Verdict.LOW, Verdict.ELEVATED, Verdict.HIGH, Verdict.CONDITIONS_NOT_MET)
CONTEXTUAL_ESCALATION_COUNT = 3


@dataclass(frozen=True, slots=True)
class FactDefinition:
    code: str
    fact_class: FactClass
    title: str
    legal_ref: str


_P1 = "п. 1 ст. 54.1 НК РФ"
_P2 = "п. 2 ст. 54.1 НК РФ"
_P3 = "п. 3 ст. 54.1 НК РФ"
_V5 = "п. 5 Постановления Пленума ВАС РФ от 12.10.2006 № 53"
_V6 = "п. 6 Постановления Пленума ВАС РФ от 12.10.2006 № 53"

CATALOG: dict[str, FactDefinition] = {
    d.code: d
    for d in (
        FactDefinition(
            "DISTORTED_FACTS", FactClass.CONDITION_BREACH, "Искажение сведений о фактах хозяйственной жизни", _P1
        ),
        FactDefinition(
            "TAX_MAIN_PURPOSE",
            FactClass.CONDITION_BREACH,
            "Основная цель сделки — неуплата или возврат налога",
            f"пп. 1 {_P2}",
        ),
        FactDefinition(
            "PERFORMED_BY_THIRD_PARTY",
            FactClass.CONDITION_BREACH,
            "Обязательство исполнено не стороной договора и не лицом, которому оно передано по договору или закону",
            f"пп. 2 {_P2}",
        ),
        FactDefinition(
            "NO_RESOURCES", FactClass.REALITY_INDICATOR, "Нет персонала, основных средств, складов, транспорта", _V5
        ),
        FactDefinition(
            "IMPOSSIBLE_PERFORMANCE",
            FactClass.REALITY_INDICATOR,
            "Реальное исполнение невозможно по времени, месту или объёму ресурсов",
            _V5,
        ),
        FactDefinition(
            "GOODS_NOT_PRODUCED",
            FactClass.REALITY_INDICATOR,
            "Товар не производился или не мог быть произведён в заявленном объёме",
            _V5,
        ),
        FactDefinition(
            "EGRUL_UNRELIABLE",
            FactClass.REGISTRY_SIGNAL,
            "В ЕГРЮЛ внесена запись о недостоверности сведений",
            "п. 6 ст. 11 Федерального закона № 129-ФЗ",
        ),
        FactDefinition(
            "PENDING_EXCLUSION",
            FactClass.REGISTRY_SIGNAL,
            "Принято решение о предстоящем исключении из ЕГРЮЛ",
            "п. 2 ст. 21.1 Федерального закона № 129-ФЗ",
        ),
        FactDefinition(
            "EXCLUSION_RISK",
            FactClass.REGISTRY_SIGNAL,
            "Запись о недостоверности держится более шести месяцев — основание для исключения из ЕГРЮЛ",
            "пп. «б» п. 5 ст. 21.1 Федерального закона № 129-ФЗ",
        ),
        FactDefinition(
            "DISQUALIFIED_EXECUTIVE",
            FactClass.REGISTRY_SIGNAL,
            "Руководитель включён в реестр дисквалифицированных лиц",
            "ст. 3.11, п. 3 ст. 32.11 КоАП РФ",
        ),
        FactDefinition(
            "UNAUTHORIZED_SIGNATORY",
            FactClass.NOT_STANDALONE,
            "Первичные документы подписаны неустановленным или неуполномоченным лицом",
            _P3,
        ),
        FactDefinition(
            "COUNTERPARTY_TAX_VIOLATIONS",
            FactClass.NOT_STANDALONE,
            "Контрагент нарушает законодательство о налогах и сборах",
            _P3,
        ),
        FactDefinition(
            "SAME_RESULT_OTHER_DEAL",
            FactClass.NOT_STANDALONE,
            "Тот же экономический результат достижим иной сделкой",
            _P3,
        ),
        FactDefinition("RECENTLY_REGISTERED", FactClass.CONTEXTUAL, "Организация создана незадолго до сделки", _V6),
        FactDefinition("INTERDEPENDENCE", FactClass.CONTEXTUAL, "Участники сделки взаимозависимы", _V6),
        FactDefinition(
            "IRREGULAR_OPERATIONS", FactClass.CONTEXTUAL, "Неритмичный характер хозяйственных операций", _V6
        ),
        FactDefinition(
            "PAST_TAX_VIOLATIONS", FactClass.CONTEXTUAL, "Нарушения налогового законодательства в прошлом", _V6
        ),
        FactDefinition("ONE_OFF_DEAL", FactClass.CONTEXTUAL, "Разовый характер операции", _V6),
        FactDefinition(
            "OUTSIDE_LOCATION", FactClass.CONTEXTUAL, "Операция не по месту нахождения налогоплательщика", _V6
        ),
        FactDefinition("SINGLE_BANK", FactClass.CONTEXTUAL, "Расчёты через один банк", _V6),
        FactDefinition(
            "TRANSIT_PAYMENTS",
            FactClass.CONTEXTUAL,
            "Транзитные платежи между участниками взаимосвязанных операций",
            _V6,
        ),
        FactDefinition("INTERMEDIARIES", FactClass.CONTEXTUAL, "Использование посредников", _V6),
    )
}


@dataclass(frozen=True, slots=True)
class RegistryState:
    unreliable_since: date | None = None
    pending_exclusion: bool = False
    disqualified_executive: bool = False


@dataclass(frozen=True, slots=True)
class TaxAssessment:
    verdict: Verdict
    facts: tuple[FactDefinition, ...]
    reasons: tuple[str, ...]


def derive_registry_facts(state: RegistryState, on: date) -> set[str]:
    facts: set[str] = set()
    if state.unreliable_since is not None and state.unreliable_since <= on:
        facts.add("EGRUL_UNRELIABLE")
        if on > add_months(state.unreliable_since, 6):
            facts.add("EXCLUSION_RISK")
    if state.pending_exclusion:
        facts.add("PENDING_EXCLUSION")
    if state.disqualified_executive:
        facts.add("DISQUALIFIED_EXECUTIVE")
    return facts


def assess(codes: set[str]) -> TaxAssessment:
    unknown = codes - CATALOG.keys()
    if unknown:
        raise ValueError(f"Неизвестные обстоятельства: {', '.join(sorted(unknown))}")
    facts = tuple(sorted((CATALOG[c] for c in codes), key=lambda d: (list(FactClass).index(d.fact_class), d.code)))
    by_class = {cls: [f for f in facts if f.fact_class is cls] for cls in FactClass}
    significant = by_class[FactClass.REALITY_INDICATOR] + by_class[FactClass.REGISTRY_SIGNAL]
    weak = by_class[FactClass.NOT_STANDALONE] + by_class[FactClass.CONTEXTUAL]
    reasons: list[str] = []
    if by_class[FactClass.CONDITION_BREACH]:
        verdict = Verdict.CONDITIONS_NOT_MET
        reasons.append("Не соблюдены условия ст. 54.1 НК РФ: уменьшение налоговой базы по сделке недопустимо")
    elif (significant and weak) or len(significant) > 1:
        verdict = Verdict.HIGH
        reasons.append("Несколько признаков нереальности исполнения или реестровых сигналов в совокупности")
    elif significant:
        verdict = Verdict.ELEVATED
        reasons.append("Есть признаки необоснованной налоговой выгоды; нужны доказательства реальности операций")
    elif len(weak) >= CONTEXTUAL_ESCALATION_COUNT:
        verdict = Verdict.ELEVATED
        reasons.append(
            "Несколько обстоятельств, каждое из которых само по себе не является основанием, оцениваются в совокупности"
        )
    else:
        verdict = Verdict.LOW
    if weak and verdict in (Verdict.LOW, Verdict.ELEVATED) and not significant:
        reasons.append(
            "Обстоятельства из п. 3 ст. 54.1 НК РФ и п. 6 Пленума ВАС № 53 сами по себе основанием не являются"
        )
    return TaxAssessment(verdict, facts, tuple(reasons))
