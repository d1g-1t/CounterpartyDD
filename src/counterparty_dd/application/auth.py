from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from counterparty_dd.application.context import UnitOfWork
from counterparty_dd.core.security import ACCESS, REFRESH, issue_token, read_token, verify_password
from counterparty_dd.domain.enums import UserRole
from counterparty_dd.domain.errors import AuthError, TooManyAttempts
from counterparty_dd.infrastructure.db.models import UserModel
from counterparty_dd.infrastructure.throttle import LoginThrottle


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, uow: UnitOfWork, throttle: LoginThrottle) -> None:
        self.uow = uow
        self.throttle = throttle

    def _pair(self, user_id: UUID, tenant_id: UUID, role: UserRole) -> TokenPair:
        secret = self.uow.settings.token_secret.get_secret_value()
        return TokenPair(
            issue_token(secret, user_id, tenant_id, role, ACCESS, self.uow.settings.access_ttl_seconds),
            issue_token(secret, user_id, tenant_id, role, REFRESH, self.uow.settings.refresh_ttl_seconds),
        )

    async def login(self, email: str, password: str) -> TokenPair:
        key = email.strip().lower()
        if await self.throttle.blocked(key):
            raise TooManyAttempts("Слишком много неудачных попыток входа, повторите позже")
        user = (await self.uow.session.scalars(select(UserModel).where(UserModel.email == key))).one_or_none()
        if user is None or not verify_password(password, user.hashed_password):
            await self.throttle.failed(key)
            raise AuthError("Неверный email или пароль")
        await self.throttle.reset(key)
        return self._pair(user.id, user.tenant_id, UserRole(user.role))

    async def refresh(self, token: str) -> TokenPair:
        payload = read_token(self.uow.settings.token_secret.get_secret_value(), token, REFRESH)
        user = await self.uow.session.get(UserModel, UUID(payload["sub"]))
        if user is None:
            raise AuthError("Пользователь не найден")
        return self._pair(user.id, user.tenant_id, UserRole(user.role))
