from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.application.screening import ScreeningService
from counterparty_dd.domain.enums import CaseStatus, MonitoringStatus, RiskLevel
from counterparty_dd.domain.errors import InvalidTransition
from counterparty_dd.domain.policy import RESCREEN_DAYS, next_rescreen
from counterparty_dd.infrastructure.db.models import CaseModel, MonitoringModel


class MonitoringService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def enable(self, actor: Actor, case_id: UUID, interval_days: int | None) -> MonitoringModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        if case.status not in (CaseStatus.APPROVED.value, CaseStatus.MONITORED.value):
            raise InvalidTransition("Мониторинг включается после одобрения контрагента")
        level = RiskLevel(case.risk_level) if case.risk_level else RiskLevel.MEDIUM
        days = interval_days or RESCREEN_DAYS[level]
        now = self.uow.clock()
        existing = await self.uow.children(MonitoringModel, case_id)
        subscription = existing[0] if existing else MonitoringModel(case_id=case_id)
        subscription.status = MonitoringStatus.ACTIVE.value
        subscription.interval_days = days
        subscription.next_run_at = now + timedelta(days=days)
        if not existing:
            self.uow.session.add(subscription)
        case.status = CaseStatus.MONITORED.value
        await self.uow.session.flush()
        await self.uow.record(actor, case, "MONITORING_ENABLED", {"interval_days": days})
        return subscription

    async def pause(self, actor: Actor, case_id: UUID) -> MonitoringModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        existing = await self.uow.children(MonitoringModel, case_id)
        if not existing:
            raise InvalidTransition("Мониторинг не включён")
        existing[0].status = MonitoringStatus.PAUSED.value
        await self.uow.record(actor, case, "MONITORING_PAUSED", {})
        return existing[0]

    async def due(self, limit: int = 100) -> list[tuple[MonitoringModel, CaseModel]]:
        stmt = (
            select(MonitoringModel, CaseModel)
            .join(CaseModel, CaseModel.id == MonitoringModel.case_id)
            .where(
                MonitoringModel.status == MonitoringStatus.ACTIVE.value, MonitoringModel.next_run_at <= self.uow.clock()
            )
            .order_by(MonitoringModel.next_run_at)
            .limit(limit)
        )
        return [(m, c) for m, c in (await self.uow.session.execute(stmt)).all()]

    async def scan(self, limit: int = 100) -> int:
        processed = 0
        screening = ScreeningService(self.uow)
        for subscription, case in await self.due(limit):
            if case.status == CaseStatus.CLOSED.value:
                subscription.status = MonitoringStatus.PAUSED.value
                continue
            run = await screening.run_for_case(case, None, None)
            now = self.uow.clock()
            subscription.last_run_at = now
            subscription.next_run_at = next_rescreen(RiskLevel(case.risk_level or RiskLevel.MEDIUM), now)
            if run.alerts_count and case.status == CaseStatus.MONITORED.value:
                case.status = CaseStatus.UNDER_REVIEW.value
                await self.uow.audit.append(
                    case.tenant_id, None, "case", case.id, "CASE_REOPENED_BY_MONITORING", {"alerts": run.alerts_count}
                )
            processed += 1
        return processed

    async def overdue(self, actor: Actor) -> int:
        stmt = (
            select(MonitoringModel.id)
            .join(CaseModel, CaseModel.id == MonitoringModel.case_id)
            .where(
                CaseModel.tenant_id == actor.tenant_id,
                MonitoringModel.status == MonitoringStatus.ACTIVE.value,
                MonitoringModel.next_run_at < self.uow.clock(),
            )
        )
        return len((await self.uow.session.scalars(stmt)).all())
