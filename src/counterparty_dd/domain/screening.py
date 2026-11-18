from dataclasses import dataclass
from datetime import date
from typing import Any

from counterparty_dd.domain.enums import AlertStatus, ListKind
from counterparty_dd.domain.errors import InvalidTransition
from counterparty_dd.domain.names import normalize, similarity, tokens

BIRTH_DATE_MISMATCH_PENALTY = 0.5
EXPLAINABILITY_VERSION = "2"


@dataclass(frozen=True, slots=True)
class Subject:
    id: str
    subject_type: str
    name: str
    inn: str | None = None
    ogrn: str | None = None
    birth_date: date | None = None


@dataclass(frozen=True, slots=True)
class ListEntry:
    id: str
    source_name: str
    list_kind: ListKind
    name: str
    inn: str | None = None
    ogrn: str | None = None
    birth_date: date | None = None


@dataclass(frozen=True, slots=True)
class Match:
    subject: Subject
    entry: ListEntry
    score: float
    explanation: dict[str, Any]


def confidence(score: float) -> str:
    if score >= 0.85:
        return "HIGH"
    if score >= 0.65:
        return "MEDIUM"
    return "LOW"


def score_pair(subject: Subject, entry: ListEntry) -> tuple[float, dict[str, Any]]:
    signals: dict[str, Any] = {}
    identifier_match = (subject.inn and subject.inn == entry.inn) or (subject.ogrn and subject.ogrn == entry.ogrn)
    name_score = similarity(subject.name, entry.name)
    signals["name_similarity"] = name_score
    if identifier_match:
        signals["identifier_match"] = True
        score = 1.0
    else:
        score = name_score
        if subject.birth_date and entry.birth_date:
            same = subject.birth_date == entry.birth_date
            signals["birth_date_match"] = same
            if not same:
                score = round(score * BIRTH_DATE_MISMATCH_PENALTY, 4)
    shared = sorted(tokens(subject.name) & tokens(entry.name))
    missing = sorted(tokens(subject.name) ^ tokens(entry.name))
    explanation = {
        "version": EXPLAINABILITY_VERSION,
        "query": {"name": subject.name, "normalized": normalize(subject.name), "type": subject.subject_type},
        "match": {"name": entry.name, "source": entry.source_name, "list_kind": entry.list_kind.value},
        "score": score,
        "confidence": confidence(score),
        "matching_tokens": shared,
        "mismatched_tokens": missing,
        "signals": signals,
        "summary": (
            f"«{subject.name}» совпадает с записью «{entry.name}» ({entry.source_name}) "
            f"с уверенностью {confidence(score)} ({score:.0%}). Решение принимает проверяющий."
        ),
    }
    return score, explanation


def screen(subjects: list[Subject], entries: list[ListEntry], threshold: float) -> list[Match]:
    matches: list[Match] = []
    for subject in subjects:
        for entry in entries:
            score, explanation = score_pair(subject, entry)
            if score >= threshold:
                matches.append(Match(subject, entry, score, explanation))
    return sorted(matches, key=lambda m: (-m.score, m.subject.id, m.entry.id))


DISPOSITIONS: dict[AlertStatus, frozenset[AlertStatus]] = {
    AlertStatus.OPEN: frozenset({AlertStatus.DISMISSED, AlertStatus.CONFIRMED, AlertStatus.ESCALATED}),
    AlertStatus.ESCALATED: frozenset({AlertStatus.DISMISSED, AlertStatus.CONFIRMED}),
    AlertStatus.DISMISSED: frozenset(),
    AlertStatus.CONFIRMED: frozenset(),
}


def check_disposition(current: AlertStatus, target: AlertStatus, can_approve: bool) -> None:
    if target not in DISPOSITIONS[current]:
        raise InvalidTransition(f"Алерт в статусе {current} нельзя перевести в {target}")
    if current is AlertStatus.ESCALATED and not can_approve:
        raise InvalidTransition("Эскалированный алерт закрывает только комплаенс-офицер")


def false_positive_ratio(statuses: list[AlertStatus]) -> float:
    dismissed = statuses.count(AlertStatus.DISMISSED)
    resolved = dismissed + statuses.count(AlertStatus.CONFIRMED)
    return round(dismissed / resolved, 4) if resolved else 0.0
