from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.domain import screening as rules
from counterparty_dd.domain.enums import AlertStatus, CaseStatus, EdgeBasis, ListKind
from counterparty_dd.domain.errors import Conflict, NotFound
from counterparty_dd.domain.names import normalize
from counterparty_dd.domain.screening import ListEntry, Subject
from counterparty_dd.infrastructure.db.models import (
    AlertModel,
    CaseModel,
    CounterpartyModel,
    EdgeModel,
    NodeModel,
    RelatedPersonModel,
    ScreeningRunModel,
    WatchlistEntryModel,
    WatchlistSourceModel,
)


@dataclass(frozen=True, slots=True)
class EntryDraft:
    name: str
    inn: str | None = None
    ogrn: str | None = None
    birth_date: date | None = None
    note: str | None = None


class WatchlistService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_source(self, actor: Actor, name: str, kind: ListKind, version: str | None) -> WatchlistSourceModel:
        actor.require_approve()
        source = WatchlistSourceModel(
            tenant_id=actor.tenant_id,
            name=name,
            list_kind=kind.value,
            version_label=version,
            active=True,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(source)
        await self.uow.session.flush()
        await self.uow.audit.append(
            actor.tenant_id, actor.user_id, "watchlist", source.id, "WATCHLIST_CREATED", {"name": name}
        )
        return source

    async def source(self, actor: Actor, source_id: UUID) -> WatchlistSourceModel:
        source = await self.uow.session.get(WatchlistSourceModel, source_id)
        if source is None or source.tenant_id != actor.tenant_id:
            raise NotFound("Список не найден")
        return source

    async def sources(self, actor: Actor) -> list[WatchlistSourceModel]:
        stmt = (
            select(WatchlistSourceModel)
            .where(WatchlistSourceModel.tenant_id == actor.tenant_id)
            .order_by(WatchlistSourceModel.name)
        )
        return list((await self.uow.session.scalars(stmt)).all())

    async def add_entries(self, actor: Actor, source_id: UUID, drafts: list[EntryDraft]) -> int:
        actor.require_approve()
        source = await self.source(actor, source_id)
        for draft in drafts:
            self.uow.session.add(
                WatchlistEntryModel(
                    source_id=source.id,
                    name=draft.name,
                    normalized_name=normalize(draft.name),
                    inn=draft.inn,
                    ogrn=draft.ogrn,
                    birth_date=draft.birth_date,
                    note=draft.note,
                )
            )
        await self.uow.session.flush()
        await self.uow.audit.append(
            actor.tenant_id, actor.user_id, "watchlist", source.id, "WATCHLIST_ENTRIES_ADDED", {"count": len(drafts)}
        )
        return len(drafts)

    async def set_active(self, actor: Actor, source_id: UUID, active: bool) -> WatchlistSourceModel:
        actor.require_approve()
        source = await self.source(actor, source_id)
        source.active = active
        await self.uow.audit.append(
            actor.tenant_id, actor.user_id, "watchlist", source.id, "WATCHLIST_TOGGLED", {"active": active}
        )
        return source


class ScreeningService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def _subjects(self, case_id: UUID) -> list[Subject]:
        subjects: list[Subject] = []
        profile = (await self.uow.children(CounterpartyModel, case_id) or [None])[0]
        if profile is not None:
            subjects.append(Subject(str(profile.id), "COUNTERPARTY", profile.legal_name, profile.inn, profile.ogrn))
        for person in await self.uow.children(RelatedPersonModel, case_id):
            subjects.append(
                Subject(
                    str(person.id),
                    f"PERSON:{person.relation_type}",
                    person.full_name,
                    person.inn,
                    None,
                    person.birth_date,
                )
            )
        for node in await self.uow.children(NodeModel, case_id):
            if profile is not None and node.id == profile.node_id:
                continue
            subjects.append(
                Subject(str(node.id), f"OWNERSHIP:{node.kind}", node.display_name, node.inn, node.ogrn, node.birth_date)
            )
        return subjects

    async def _entries(self, tenant_id: UUID) -> list[ListEntry]:
        stmt = (
            select(WatchlistEntryModel, WatchlistSourceModel)
            .join(WatchlistSourceModel, WatchlistEntryModel.source_id == WatchlistSourceModel.id)
            .where(WatchlistSourceModel.tenant_id == tenant_id, WatchlistSourceModel.active.is_(True))
        )
        return [
            ListEntry(str(e.id), s.name, ListKind(s.list_kind), e.name, e.inn, e.ogrn, e.birth_date)
            for e, s in (await self.uow.session.execute(stmt)).all()
        ]

    async def run(self, actor: Actor, case_id: UUID, threshold: float | None) -> ScreeningRunModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        return await self.run_for_case(case, actor.user_id, threshold)

    async def run_for_case(
        self, case: CaseModel, started_by: UUID | None, threshold: float | None
    ) -> ScreeningRunModel:
        if case.status == CaseStatus.CLOSED.value:
            raise Conflict("Проверка закрыта")
        limit = self.uow.settings.screening_threshold if threshold is None else threshold
        subjects = await self._subjects(case.id)
        entries = await self._entries(case.tenant_id)
        matches = rules.screen(subjects, entries, limit)
        existing = {
            (a.subject_id, a.entry_id)
            for a in await self.uow.children(AlertModel, case.id)
            if a.status in (AlertStatus.OPEN.value, AlertStatus.ESCALATED.value, AlertStatus.DISMISSED.value)
        }
        now = self.uow.clock()
        run = ScreeningRunModel(
            case_id=case.id,
            threshold=limit,
            subjects_count=len(subjects),
            entries_count=len(entries),
            alerts_count=0,
            started_by=started_by,
            created_at=now,
        )
        self.uow.session.add(run)
        await self.uow.session.flush()
        created = 0
        for match in matches:
            key = (UUID(match.subject.id), UUID(match.entry.id))
            if key in existing:
                continue
            self.uow.session.add(
                AlertModel(
                    case_id=case.id,
                    run_id=run.id,
                    subject_type=match.subject.subject_type,
                    subject_id=key[0],
                    subject_name=match.subject.name,
                    entry_id=key[1],
                    list_kind=match.entry.list_kind.value,
                    matched_name=match.entry.name,
                    score=match.score,
                    explanation=match.explanation,
                    status=AlertStatus.OPEN.value,
                    created_at=now,
                )
            )
            created += 1
        run.alerts_count = created
        if case.status == CaseStatus.OPEN.value:
            case.status = CaseStatus.SCREENING.value
        case.updated_at = now
        await self.uow.audit.append(
            case.tenant_id,
            started_by,
            "case",
            case.id,
            "SCREENING_COMPLETED",
            {"run_id": str(run.id), "subjects": len(subjects), "entries": len(entries), "alerts": created},
        )
        return run

    async def alerts(self, actor: Actor, case_id: UUID, status: AlertStatus | None) -> list[AlertModel]:
        await self.uow.case(actor, case_id)
        rows = await self.uow.children(AlertModel, case_id, AlertModel.score.desc(), AlertModel.id)
        return [a for a in rows if status is None or a.status == status.value]

    async def dispose(self, actor: Actor, alert_id: UUID, target: AlertStatus, reason: str) -> AlertModel:
        actor.require_write()
        alert, case = await self.uow.child(AlertModel, actor, alert_id)
        rules.check_disposition(AlertStatus(alert.status), target, actor.role.can_approve)
        previous = alert.status
        alert.status = target.value
        alert.disposition_reason = reason
        alert.reviewed_by = actor.user_id
        alert.reviewed_at = self.uow.clock()
        await self.uow.record(
            actor,
            case,
            "ALERT_DISPOSED",
            {"alert_id": str(alert.id), "from": previous, "to": target.value, "reason": reason},
        )
        return alert

    async def confirmed_node_hits(self, case_id: UUID, kinds: frozenset[ListKind]) -> set[UUID]:
        return {
            a.subject_id
            for a in await self.uow.children(AlertModel, case_id)
            if a.status == AlertStatus.CONFIRMED.value and ListKind(a.list_kind) in kinds
        }

    async def disqualified_executive(self, case_id: UUID) -> bool:
        persons = {p.id for p in await self.uow.children(RelatedPersonModel, case_id) if p.relation_type == "DIRECTOR"}
        profile = (await self.uow.children(CounterpartyModel, case_id) or [None])[0]
        executive_nodes = {
            e.source_id
            for e in await self.uow.children(EdgeModel, case_id)
            if profile is not None and e.basis == EdgeBasis.EXECUTIVE_BODY.value and e.target_id == profile.node_id
        }
        hits = await self.confirmed_node_hits(case_id, frozenset({ListKind.DISQUALIFIED}))
        return bool(hits & persons) or bool(hits & executive_nodes)
