from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from counterparty_dd.core.clock import Clock
from counterparty_dd.core.security import chain_hash
from counterparty_dd.infrastructure.db.models import AuditEventModel

GENESIS = "0" * 64


@dataclass(frozen=True, slots=True)
class ChainCheck:
    valid: bool
    events: int
    broken_at: int | None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class AuditLog:
    def __init__(self, session: AsyncSession, secret: str, clock: Clock) -> None:
        self._session = session
        self._secret = secret
        self._clock = clock

    @staticmethod
    def _body(event: AuditEventModel) -> dict[str, Any]:
        return {
            "seq": event.seq,
            "actor": str(event.actor_id) if event.actor_id else None,
            "resource_type": event.resource_type,
            "resource_id": str(event.resource_id),
            "event_type": event.event_type,
            "payload": event.payload,
            "created_at": _utc(event.created_at).isoformat(),
        }

    async def append(
        self,
        tenant_id: UUID,
        actor_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> AuditEventModel:
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            await self._session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"), {"t": str(tenant_id)})
        last = (
            await self._session.execute(
                select(AuditEventModel.seq, AuditEventModel.hash)
                .where(AuditEventModel.tenant_id == tenant_id)
                .order_by(AuditEventModel.seq.desc())
                .limit(1)
            )
        ).first()
        seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
        event = AuditEventModel(
            tenant_id=tenant_id,
            seq=seq,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            event_type=event_type,
            payload=payload,
            prev_hash=prev,
            created_at=self._clock(),
        )
        event.hash = chain_hash(self._secret, prev, self._body(event))
        self._session.add(event)
        await self._session.flush()
        return event

    async def timeline(self, tenant_id: UUID, resource_id: UUID, limit: int = 500) -> list[AuditEventModel]:
        stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.tenant_id == tenant_id, AuditEventModel.resource_id == resource_id)
            .order_by(AuditEventModel.seq)
            .limit(limit)
        )
        return list((await self._session.scalars(stmt)).all())

    async def verify(self, tenant_id: UUID) -> ChainCheck:
        stmt = select(AuditEventModel).where(AuditEventModel.tenant_id == tenant_id).order_by(AuditEventModel.seq)
        prev = GENESIS
        count = 0
        for event in (await self._session.scalars(stmt)).all():
            count += 1
            if event.prev_hash != prev or event.hash != chain_hash(self._secret, prev, self._body(event)):
                return ChainCheck(False, count, event.seq)
            prev = event.hash
        return ChainCheck(True, count, None)
