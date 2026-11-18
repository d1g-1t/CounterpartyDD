from typing import Any
from uuid import UUID

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.application.counterparties import CounterpartyService
from counterparty_dd.application.diligence import DiligenceService
from counterparty_dd.application.ownership import OwnershipService
from counterparty_dd.core.security import sha256_hex
from counterparty_dd.domain.enums import AlertStatus, ApprovalStatus, CaseStatus, RiskLevel, TaskStatus
from counterparty_dd.domain.policy import Completeness, check_decision, completeness
from counterparty_dd.infrastructure.db.models import (
    AdverseMediaModel,
    AlertModel,
    ApprovalDecisionModel,
    EvidenceModel,
    OwnershipAnalysisModel,
    RemediationTaskModel,
    ScreeningRunModel,
)


class ApprovalService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def completeness(self, actor: Actor, case_id: UUID) -> Completeness:
        await self.uow.case(actor, case_id)
        alerts = await self.uow.children(AlertModel, case_id)
        tasks = await self.uow.children(RemediationTaskModel, case_id)
        diligence = DiligenceService(self.uow)
        flags = {
            "counterparty": await CounterpartyService(self.uow).get(actor, case_id) is not None,
            "screening": bool(await self.uow.children(ScreeningRunModel, case_id)),
            "alerts_resolved": all(
                a.status in (AlertStatus.DISMISSED.value, AlertStatus.CONFIRMED.value) for a in alerts
            ),
            "ownership": bool(await self.uow.children(OwnershipAnalysisModel, case_id)),
            "tax_check": await diligence.latest_tax_check(case_id) is not None,
            "risk": await diligence.latest_risk(case_id) is not None,
            "adverse_media": bool(await self.uow.children(AdverseMediaModel, case_id)),
            "evidence": bool(await self.uow.children(EvidenceModel, case_id)),
            "remediation_closed": all(t.status != TaskStatus.OPEN.value for t in tasks),
        }
        return completeness(flags)

    async def decide(
        self, actor: Actor, case_id: UUID, status: ApprovalStatus, note: str | None, reason: str | None
    ) -> ApprovalDecisionModel:
        actor.require_approve()
        case = await self.uow.case(actor, case_id)
        ready = await self.completeness(actor, case_id)
        risk = await DiligenceService(self.uow).latest_risk(case_id)
        level = RiskLevel(risk.level) if risk else None
        new_status = check_decision(
            status,
            case_status=CaseStatus(case.status),
            ready=ready,
            risk_level=level,
            reason=reason,
            decided_by=str(actor.user_id),
            case_owner=str(case.owner_user_id) if case.owner_user_id else None,
        )
        decision = ApprovalDecisionModel(
            case_id=case_id,
            status=status.value,
            note=note,
            reason=reason,
            risk_level=level.value if level else None,
            decided_by=actor.user_id,
            decided_at=self.uow.clock(),
        )
        self.uow.session.add(decision)
        previous = case.status
        case.status = new_status.value
        await self.uow.session.flush()
        await self.uow.record(
            actor,
            case,
            "APPROVAL_RECORDED",
            {"decision": status.value, "reason": reason, "from": previous, "to": new_status.value},
        )
        return decision

    async def decisions(self, actor: Actor, case_id: UUID) -> list[ApprovalDecisionModel]:
        await self.uow.case(actor, case_id)
        return await self.uow.children(ApprovalDecisionModel, case_id, ApprovalDecisionModel.decided_at)

    async def committee_packet(self, actor: Actor, case_id: UUID) -> dict[str, Any]:
        case = await self.uow.case(actor, case_id)
        profile = await CounterpartyService(self.uow).get(actor, case_id)
        analysis, owners = await OwnershipService(self.uow).stored(actor, case_id)
        diligence = DiligenceService(self.uow)
        tax = await diligence.latest_tax_check(case_id)
        risk = await diligence.latest_risk(case_id)
        alerts = await self.uow.children(AlertModel, case_id, AlertModel.score.desc())
        evidence = await self.uow.children(EvidenceModel, case_id, EvidenceModel.created_at)
        ready = await self.completeness(actor, case_id)
        chain = await self.uow.audit.verify(actor.tenant_id)
        evidence_items = [
            {"id": str(e.id), "title": e.title, "type": e.evidence_type, "sha256": e.sha256} for e in evidence
        ]
        return {
            "case": {
                "id": str(case.id),
                "number": case.case_number,
                "title": case.title,
                "status": case.status,
                "risk_level": case.risk_level,
            },
            "counterparty": None
            if profile is None
            else {
                "legal_name": profile.legal_name,
                "inn": profile.inn,
                "ogrn": profile.ogrn,
                "country": profile.country_code,
            },
            "beneficial_owners": {
                "status": analysis.status if analysis else None,
                "flags": analysis.flags if analysis else [],
                "opaque_percent": str(analysis.opaque_percent) if analysis else None,
                "owners": [{"name": o.name, "bases": o.bases, "percent": str(o.effective_percent)} for o in owners],
            },
            "screening": [
                {
                    "subject": a.subject_name,
                    "matched": a.matched_name,
                    "list": a.list_kind,
                    "score": a.score,
                    "status": a.status,
                }
                for a in alerts
            ],
            "tax_check": None if tax is None else {"verdict": tax.verdict, "facts": tax.facts, "reasons": tax.reasons},
            "risk": None
            if risk is None
            else {
                "inherent": risk.inherent,
                "residual": risk.residual,
                "level": risk.level,
                "overrides": risk.overrides,
            },
            "completeness": {
                "score": ready.score,
                "missing": list(ready.missing),
                "committee_ready": ready.committee_ready,
            },
            "evidence": {"items": evidence_items, "pack_sha256": sha256_hex(evidence_items)},
            "audit_chain_valid": chain.valid,
            "notice": "Решение принимает уполномоченное лицо; система не одобряет контрагентов автоматически.",
        }
