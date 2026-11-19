from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.domain.enums import CaseStatus, CounterpartyType
from counterparty_dd.domain.errors import NotFound
from counterparty_dd.domain.policy import check_transition
from counterparty_dd.infrastructure.db.models import AuditEventModel, CaseModel, UserModel


@dataclass(frozen=True, slots=True)
class CaseDraft:
    title: str
    counterparty_type: CounterpartyType
    business_unit: str | None = None
    owner_user_id: UUID | None = None


class CaseService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def _check_owner(self, actor: Actor, user_id: UUID | None) -> None:
        if user_id is None:
            return
        user = await self.uow.session.get(UserModel, user_id)
        if user is None or user.tenant_id != actor.tenant_id:
            raise NotFound("Исполнитель не найден")

    async def create(self, actor: Actor, draft: CaseDraft) -> CaseModel:
        actor.require_write()
        owner = draft.owner_user_id or actor.user_id
        await self._check_owner(actor, owner)
        now = self.uow.clock()
        case_id = uuid4()
        case = CaseModel(
            id=case_id,
            tenant_id=actor.tenant_id,
            case_number=f"DD-{now:%Y}-{case_id.hex[:8].upper()}",
            title=draft.title,
            status=CaseStatus.OPEN.value,
            counterparty_type=draft.counterparty_type.value,
            business_unit=draft.business_unit,
            owner_user_id=owner,
            created_at=now,
            updated_at=now,
        )
        self.uow.session.add(case)
        await self.uow.session.flush()
        await self.uow.record(actor, case, "CASE_OPENED", {"title": draft.title, "type": draft.counterparty_type.value})
        return case

    async def search(self, actor: Actor, status: CaseStatus | None, limit: int, offset: int) -> list[CaseModel]:
        stmt = select(CaseModel).where(CaseModel.tenant_id == actor.tenant_id)
        if status is not None:
            stmt = stmt.where(CaseModel.status == status.value)
        stmt = stmt.order_by(CaseModel.created_at.desc(), CaseModel.id).limit(limit).offset(offset)
        return list((await self.uow.session.scalars(stmt)).all())

    async def update(
        self, actor: Actor, case_id: UUID, title: str | None, business_unit: str | None, owner_user_id: UUID | None
    ) -> CaseModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        changes: dict[str, str] = {}
        if title is not None:
            case.title = title
            changes["title"] = title
        if business_unit is not None:
            case.business_unit = business_unit
            changes["business_unit"] = business_unit
        if owner_user_id is not None:
            await self._check_owner(actor, owner_user_id)
            case.owner_user_id = owner_user_id
            changes["owner_user_id"] = str(owner_user_id)
        await self.uow.record(actor, case, "CASE_UPDATED", changes)
        return case

    async def transition(self, actor: Actor, case_id: UUID, target: CaseStatus, reason: str | None) -> CaseModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        current = CaseStatus(case.status)
        check_transition(current, target, actor.role)
        case.status = target.value
        await self.uow.record(
            actor, case, "CASE_STATUS_CHANGED", {"from": current.value, "to": target.value, "reason": reason}
        )
        return case

    async def timeline(self, actor: Actor, case_id: UUID) -> list[AuditEventModel]:
        await self.uow.case(actor, case_id)
        return await self.uow.audit.timeline(actor.tenant_id, case_id)

    async def count_by_status(self, actor: Actor) -> dict[str, int]:
        stmt = (
            select(CaseModel.status, func.count())
            .where(CaseModel.tenant_id == actor.tenant_id)
            .group_by(CaseModel.status)
        )
        return {status: int(n) for status, n in (await self.uow.session.execute(stmt)).all()}
