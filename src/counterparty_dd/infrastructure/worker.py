import asyncio

from celery import Celery

from counterparty_dd.application.audit import AuditLog
from counterparty_dd.application.context import UnitOfWork
from counterparty_dd.application.monitoring import MonitoringService
from counterparty_dd.core.config import get_settings
from counterparty_dd.infrastructure.container import Container, build_container

settings = get_settings()
celery_app = Celery("counterparty_dd", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    timezone="UTC",
    beat_schedule={"monitoring-scan": {"task": "cdd.monitoring_scan", "schedule": 3600.0}},
)


async def run_monitoring_scan(container: Container, limit: int = 100) -> int:
    async with container.session_factory() as session:
        audit = AuditLog(session, container.settings.audit_secret.get_secret_value(), container.clock)
        uow = UnitOfWork(session, audit, container.clock, container.settings)
        processed = await MonitoringService(uow).scan(limit)
        await session.commit()
        return processed


async def _scan_once(limit: int) -> int:
    container = build_container(get_settings())
    try:
        return await run_monitoring_scan(container, limit)
    finally:
        await container.close()


@celery_app.task(name="cdd.monitoring_scan", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
def monitoring_scan(limit: int = 100) -> int:
    return asyncio.run(_scan_once(limit))
