from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counterparty_dd.application.audit import AuditLog
from counterparty_dd.core.clock import Clock
from counterparty_dd.core.config import Settings
from counterparty_dd.domain.enums import UserRole
from counterparty_dd.domain.errors import Forbidden, NotFound
from counterparty_dd.infrastructure.db.models import Base, CaseModel


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: UUID
    tenant_id: UUID
    role: UserRole

    def require_write(self) -> None:
        if not self.role.can_write:
            raise Forbidden("Недостаточно прав для изменения данных")

    def require_approve(self) -> None:
        if not self.role.can_approve:
            raise Forbidden("Действие доступно только комплаенс-офицеру")


@dataclass(slots=True)
class UnitOfWork:
    session: AsyncSession
    audit: AuditLog
    clock: Clock
    settings: Settings

    async def case(self, actor: Actor, case_id: UUID) -> CaseModel:
        case = await self.session.get(CaseModel, case_id)
        if case is None or case.tenant_id != actor.tenant_id:
            raise NotFound("Проверка не найдена")
        return case

    async def child[T: Base](self, model: type[T], actor: Actor, item_id: UUID) -> tuple[T, CaseModel]:
        item = await self.session.get(model, item_id)
        if item is None:
            raise NotFound("Объект не найден")
        case = await self.case(actor, item.case_id)  # type: ignore[attr-defined]
        return item, case

    async def children[T: Base](self, model: type[T], case_id: UUID, *order: Any) -> list[T]:
        stmt = select(model).where(model.case_id == case_id)  # type: ignore[attr-defined]
        if order:
            stmt = stmt.order_by(*order)
        return list((await self.session.scalars(stmt)).all())

    async def record(self, actor: Actor, case: CaseModel, event_type: str, payload: dict[str, Any]) -> None:
        case.updated_at = self.clock()
        await self.audit.append(actor.tenant_id, actor.user_id, "case", case.id, event_type, payload)
