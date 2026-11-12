import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
import pyseto
from pyseto import Key

from counterparty_dd.domain.enums import UserRole
from counterparty_dd.domain.errors import AuthError

ACCESS = "access"
REFRESH = "refresh"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _key(secret: str) -> Key:
    return Key.new(version=4, purpose="local", key=hashlib.sha256(secret.encode()).digest())


def issue_token(secret: str, user_id: UUID, tenant_id: UUID, role: UserRole, kind: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tenant": str(tenant_id),
        "role": role.value,
        "typ": kind,
        "iat": now.isoformat(timespec="seconds"),
        "exp": (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
    }
    return pyseto.encode(_key(secret), payload, serializer=json, implicit_assertion=kind.encode()).decode()


def read_token(secret: str, token: str, kind: str) -> dict[str, Any]:
    try:
        decoded = pyseto.decode(_key(secret), token, deserializer=json, implicit_assertion=kind.encode())
    except Exception as exc:
        raise AuthError("Недействительный или просроченный токен") from exc
    payload: dict[str, Any] = decoded.payload  # type: ignore[assignment]
    if payload.get("typ") != kind:
        raise AuthError("Неверный тип токена")
    try:
        expires = datetime.fromisoformat(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("Недействительный токен") from exc
    if expires <= datetime.now(UTC):
        raise AuthError("Недействительный или просроченный токен")
    return payload


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def chain_hash(secret: str, prev_hash: str, payload: dict[str, Any]) -> str:
    return hmac.new(secret.encode(), f"{prev_hash}|{canonical(payload)}".encode(), hashlib.sha256).hexdigest()


def sha256_hex(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()
