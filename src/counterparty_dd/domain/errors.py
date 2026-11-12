class DomainError(Exception):
    code = "DOMAIN_ERROR"
    status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    code = "NOT_FOUND"
    status = 404


class Forbidden(DomainError):
    code = "FORBIDDEN"
    status = 403


class AuthError(DomainError):
    code = "UNAUTHORIZED"
    status = 401


class Conflict(DomainError):
    code = "CONFLICT"
    status = 409


class InvalidTransition(DomainError):
    code = "INVALID_TRANSITION"
    status = 409


class OwnershipError(DomainError):
    code = "OWNERSHIP_INVALID"


class TooManyAttempts(DomainError):
    code = "TOO_MANY_ATTEMPTS"
    status = 429
