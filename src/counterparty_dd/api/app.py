from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from counterparty_dd.api.routers import cases, counterparties, diligence, governance, ownership, screening, system
from counterparty_dd.domain.errors import DomainError
from counterparty_dd.infrastructure.container import Container


def create_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        yield
        await container.close()

    app = FastAPI(
        title="Counterparty DD",
        version="0.2.0",
        description="Бенефициарные владельцы (115-ФЗ), должная осмотрительность (ст. 54.1 НК РФ), скрининг",
        lifespan=lifespan,
    )
    app.state.container = container
    if container.settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=container.settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "detail": exc.message}, status_code=exc.status)

    for module in (system, cases, counterparties, screening, ownership, diligence, governance):
        app.include_router(module.router, prefix="/api/v1")
    return app
