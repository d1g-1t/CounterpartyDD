from typing import Any

from sqlalchemy import func, select

from counterparty_dd.application.cases import CaseService
from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.application.monitoring import MonitoringService
from counterparty_dd.domain.enums import AlertStatus, RiskLevel
from counterparty_dd.domain.screening import false_positive_ratio
from counterparty_dd.infrastructure.db.models import AlertModel, CaseModel

HIGH_LEVELS = (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value)


class AnalyticsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def _alert_statuses(self, actor: Actor) -> list[AlertStatus]:
        stmt = (
            select(AlertModel.status)
            .join(CaseModel, CaseModel.id == AlertModel.case_id)
            .where(CaseModel.tenant_id == actor.tenant_id)
        )
        return [AlertStatus(s) for s in (await self.uow.session.scalars(stmt)).all()]

    async def high_risk(self, actor: Actor) -> list[CaseModel]:
        stmt = (
            select(CaseModel)
            .where(CaseModel.tenant_id == actor.tenant_id, CaseModel.risk_level.in_(HIGH_LEVELS))
            .order_by(CaseModel.updated_at.desc())
        )
        return list((await self.uow.session.scalars(stmt)).all())

    async def false_positive_ratio(self, actor: Actor) -> float:
        return false_positive_ratio(await self._alert_statuses(actor))

    async def dashboard(self, actor: Actor) -> dict[str, Any]:
        statuses = await self._alert_statuses(actor)
        by_level = dict(
            (
                await self.uow.session.execute(
                    select(CaseModel.risk_level, func.count())
                    .where(CaseModel.tenant_id == actor.tenant_id, CaseModel.risk_level.is_not(None))
                    .group_by(CaseModel.risk_level)
                )
            ).all()
        )
        return {
            "cases_by_status": await CaseService(self.uow).count_by_status(actor),
            "cases_by_risk": {k: int(v) for k, v in by_level.items()},
            "high_risk_cases": sum(int(by_level.get(level, 0)) for level in HIGH_LEVELS),
            "open_alerts": sum(s in (AlertStatus.OPEN, AlertStatus.ESCALATED) for s in statuses),
            "false_positive_ratio": false_positive_ratio(statuses),
            "overdue_recertifications": await MonitoringService(self.uow).overdue(actor),
        }
