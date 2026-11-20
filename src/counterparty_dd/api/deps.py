from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from counterparty_dd.application.audit import AuditLog
from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.core.security import ACCESS, read_token
from counterparty_dd.domain.enums import UserRole
from counterparty_dd.domain.errors import AuthError
from counterparty_dd.infrastructure.container import Container

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_uow(session: SessionDep, container: ContainerDep) -> UnitOfWork:
    audit = AuditLog(session, container.settings.audit_secret.get_secret_value(), container.clock)
    return UnitOfWork(session, audit, container.clock, container.settings)


UowDep = Annotated[UnitOfWork, Depends(get_uow)]


async def get_actor(
    container: ContainerDep, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Actor:
    if credentials is None:
        raise AuthError("Требуется токен доступа")
    payload = read_token(container.settings.token_secret.get_secret_value(), credentials.credentials, ACCESS)
    try:
        return Actor(UUID(payload["sub"]), UUID(payload["tenant"]), UserRole(payload["role"]))
    except (KeyError, ValueError) as exc:
        raise AuthError("Токен содержит некорректные данные") from exc


ActorDep = Annotated[Actor, Depends(get_actor)]
