from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.application.counterparties import CounterpartyService
from counterparty_dd.application.ownership import OwnershipService
from counterparty_dd.application.screening import ScreeningService
from counterparty_dd.domain import risk as risk_rules
from counterparty_dd.domain import tax_diligence as tax
from counterparty_dd.domain.enums import AlertStatus, CounterpartyType, ListKind, Severity, TaskStatus
from counterparty_dd.domain.errors import DomainError, InvalidTransition
from counterparty_dd.domain.ownership import OPACITY_THRESHOLD, UboStatus
from counterparty_dd.infrastructure.db.models import (
    AdverseMediaModel,
    AlertModel,
    CaseModel,
    EvidenceModel,
    OwnershipAnalysisModel,
    RemediationTaskModel,
    RiskAssessmentModel,
    TaxCheckModel,
)

ALL_LISTS = frozenset(ListKind)


@dataclass(frozen=True, slots=True)
class MediaDraft:
    title: str
    severity: Severity
    source_url: str | None = None
    published_on: date | None = None
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    title: str
    evidence_type: str
    sha256: str
    file_name: str | None = None


class DiligenceService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def tax_check(self, actor: Actor, case_id: UUID, facts: set[str], comment: str | None) -> TaxCheckModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        profile = await CounterpartyService(self.uow).require(actor, case_id)
        state = tax.RegistryState(
            unreliable_since=profile.egrul_unreliable_since,
            pending_exclusion=profile.pending_exclusion,
            disqualified_executive=await ScreeningService(self.uow).disqualified_executive(case_id),
        )
        derived = tax.derive_registry_facts(state, self.uow.clock().date())
        try:
            result = tax.assess(facts | derived)
        except ValueError as exc:
            raise DomainError(str(exc)) from exc
        check = TaxCheckModel(
            case_id=case_id,
            facts=[f.code for f in result.facts],
            verdict=result.verdict.value,
            reasons=list(result.reasons),
            comment=comment,
            created_by=actor.user_id,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(check)
        await self.uow.session.flush()
        await self.uow.record(
            actor, case, "TAX_CHECK_RECORDED", {"verdict": result.verdict.value, "facts": check.facts}
        )
        return check

    async def latest_tax_check(self, case_id: UUID) -> TaxCheckModel | None:
        checks = await self.uow.children(TaxCheckModel, case_id, TaxCheckModel.created_at.desc())
        return checks[0] if checks else None

    async def tax_checks(self, actor: Actor, case_id: UUID) -> list[TaxCheckModel]:
        await self.uow.case(actor, case_id)
        return await self.uow.children(TaxCheckModel, case_id, TaxCheckModel.created_at.desc())

    async def add_media(self, actor: Actor, case_id: UUID, draft: MediaDraft) -> AdverseMediaModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        item = AdverseMediaModel(
            case_id=case_id,
            title=draft.title,
            source_url=draft.source_url,
            severity=draft.severity.value,
            published_on=draft.published_on,
            summary=draft.summary,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(item)
        await self.uow.session.flush()
        await self.uow.record(
            actor, case, "ADVERSE_MEDIA_ADDED", {"item_id": str(item.id), "severity": draft.severity.value}
        )
        return item

    async def add_evidence(self, actor: Actor, case_id: UUID, draft: EvidenceDraft) -> EvidenceModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        item = EvidenceModel(
            case_id=case_id,
            title=draft.title,
            evidence_type=draft.evidence_type,
            file_name=draft.file_name,
            sha256=draft.sha256.lower(),
            created_by=actor.user_id,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(item)
        await self.uow.session.flush()
        await self.uow.record(actor, case, "EVIDENCE_ADDED", {"item_id": str(item.id), "sha256": item.sha256})
        return item

    async def evidence(self, actor: Actor, case_id: UUID) -> list[EvidenceModel]:
        await self.uow.case(actor, case_id)
        return await self.uow.children(EvidenceModel, case_id, EvidenceModel.created_at)

    async def risk_inputs(self, actor: Actor, case: CaseModel) -> risk_rules.RiskInputs:
        profile = await CounterpartyService(self.uow).get(actor, case.id)
        latest = await self.latest_tax_check(case.id)
        analyses = await self.uow.children(OwnershipAnalysisModel, case.id)
        analysis = analyses[0] if analyses else None
        alerts = await self.uow.children(AlertModel, case.id)
        screening = ScreeningService(self.uow)
        hits = await screening.confirmed_node_hits(case.id, risk_rules.BLOCKING_LISTS)
        exposure = await OwnershipService(self.uow).upstream_exposure(actor, case.id, hits)
        media = await self.uow.children(AdverseMediaModel, case.id)
        tasks = await self.uow.children(RemediationTaskModel, case.id)
        return risk_rules.RiskInputs(
            counterparty_type=CounterpartyType(case.counterparty_type),
            tax_verdict=tax.Verdict(latest.verdict) if latest else None,
            ubo_status=UboStatus(analysis.status) if analysis else None,
            opaque_share_over_threshold=bool(analysis and analysis.opaque_percent > OPACITY_THRESHOLD * 100),
            open_alerts=sum(a.status in (AlertStatus.OPEN.value, AlertStatus.ESCALATED.value) for a in alerts),
            confirmed_lists=frozenset(ListKind(a.list_kind) for a in alerts if a.status == AlertStatus.CONFIRMED.value),
            list_exposure_upstream=bool(exposure),
            adverse_media=tuple(Severity(m.severity) for m in media),
            country_code=profile.country_code if profile else None,
            high_risk_countries=frozenset(c.upper() for c in self.uow.settings.high_risk_countries),
            completed_remediations=sum(t.status == TaskStatus.DONE.value for t in tasks),
        )

    async def assess_risk(self, actor: Actor, case_id: UUID, rationale: str) -> RiskAssessmentModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        result = risk_rules.score(await self.risk_inputs(actor, case))
        assessment = RiskAssessmentModel(
            case_id=case_id,
            inherent=result.inherent,
            residual=result.residual,
            level=result.level.value,
            factors=result.factors,
            overrides=list(result.overrides),
            rationale=rationale,
            created_by=actor.user_id,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(assessment)
        case.risk_level = result.level.value
        await self.uow.session.flush()
        await self.uow.record(
            actor,
            case,
            "RISK_ASSESSED",
            {"inherent": result.inherent, "residual": result.residual, "level": result.level.value},
        )
        return assessment

    async def latest_risk(self, case_id: UUID) -> RiskAssessmentModel | None:
        rows = await self.uow.children(RiskAssessmentModel, case_id, RiskAssessmentModel.created_at.desc())
        return rows[0] if rows else None

    async def create_task(
        self, actor: Actor, case_id: UUID, title: str, description: str, owner: UUID | None, due_at: datetime | None
    ) -> RemediationTaskModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        task = RemediationTaskModel(
            case_id=case_id,
            title=title,
            description=description,
            owner_user_id=owner,
            due_at=due_at,
            status=TaskStatus.OPEN.value,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(task)
        await self.uow.session.flush()
        await self.uow.record(actor, case, "REMEDIATION_TASK_CREATED", {"task_id": str(task.id), "title": title})
        return task

    async def close_task(self, actor: Actor, task_id: UUID, status: TaskStatus) -> RemediationTaskModel:
        actor.require_write()
        task, case = await self.uow.child(RemediationTaskModel, actor, task_id)
        if task.status != TaskStatus.OPEN.value or status is TaskStatus.OPEN:
            raise InvalidTransition("Закрыть можно только открытую задачу")
        task.status = status.value
        task.closed_at = self.uow.clock()
        await self.uow.record(actor, case, "REMEDIATION_TASK_CLOSED", {"task_id": str(task.id), "status": status.value})
        return task

    async def tasks(self, actor: Actor, case_id: UUID) -> list[RemediationTaskModel]:
        await self.uow.case(actor, case_id)
        return await self.uow.children(RemediationTaskModel, case_id, RemediationTaskModel.created_at)
