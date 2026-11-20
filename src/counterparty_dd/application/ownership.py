from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any
from uuid import UUID

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.application.counterparties import CounterpartyService, validate_identifiers
from counterparty_dd.domain.enums import EdgeBasis, NodeKind, UboExemption
from counterparty_dd.domain.errors import DomainError
from counterparty_dd.domain.ownership import Edge, Node, OwnershipGraph, UboAnalysis
from counterparty_dd.infrastructure.db.models import (
    BeneficialOwnerModel,
    EdgeModel,
    NodeModel,
    OwnershipAnalysisModel,
)

PERCENT = Decimal("0.0001")


def to_percent(value: Fraction) -> Decimal:
    return (Decimal(value.numerator) * 100 / Decimal(value.denominator)).quantize(PERCENT)


@dataclass(frozen=True, slots=True)
class NodeDraft:
    kind: NodeKind
    display_name: str
    inn: str | None = None
    ogrn: str | None = None
    birth_date: date | None = None
    exemption: UboExemption | None = None


@dataclass(frozen=True, slots=True)
class EdgeDraft:
    source_id: UUID
    target_id: UUID
    basis: EdgeBasis
    share_percent: Decimal | None = None
    evidence: tuple[str, ...] = ()


def _node(model: NodeModel) -> Node:
    return Node(
        str(model.id),
        NodeKind(model.kind),
        model.display_name,
        UboExemption(model.exemption) if model.exemption else None,
    )


def _edge(model: EdgeModel) -> Edge:
    share = Fraction(model.share_percent) / 100 if model.share_percent is not None else None
    return Edge(str(model.source_id), str(model.target_id), EdgeBasis(model.basis), share)


class OwnershipService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def _graph(self, case_id: UUID, extra: EdgeModel | None = None) -> OwnershipGraph:
        nodes = await self.uow.children(NodeModel, case_id)
        edges = await self.uow.children(EdgeModel, case_id)
        if extra is not None:
            edges = [*edges, extra]
        return OwnershipGraph([_node(n) for n in nodes], [_edge(e) for e in edges])

    async def add_node(self, actor: Actor, case_id: UUID, draft: NodeDraft) -> NodeModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        validate_identifiers(draft.inn, draft.ogrn)
        if draft.kind is NodeKind.PERSON and draft.exemption is not None:
            raise DomainError("Основания освобождения применяются только к организациям")
        node = NodeModel(
            case_id=case_id,
            kind=draft.kind.value,
            display_name=draft.display_name,
            inn=draft.inn,
            ogrn=draft.ogrn,
            birth_date=draft.birth_date,
            exemption=draft.exemption.value if draft.exemption else None,
            created_at=self.uow.clock(),
        )
        self.uow.session.add(node)
        await self.uow.session.flush()
        await self.uow.record(actor, case, "OWNERSHIP_NODE_ADDED", {"node_id": str(node.id), "kind": draft.kind.value})
        return node

    async def add_edge(self, actor: Actor, case_id: UUID, draft: EdgeDraft) -> EdgeModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        if (draft.basis is EdgeBasis.EQUITY) != (draft.share_percent is not None):
            raise DomainError("Доля указывается только для участия в капитале и для него обязательна")
        edge = EdgeModel(
            case_id=case_id,
            source_id=draft.source_id,
            target_id=draft.target_id,
            basis=draft.basis.value,
            share_percent=draft.share_percent,
            evidence=list(draft.evidence),
            created_at=self.uow.clock(),
        )
        graph = await self._graph(case_id, edge)
        profile = await CounterpartyService(self.uow).get(actor, case_id)
        if profile is not None:
            graph.integrated_ownership(str(profile.node_id))
        self.uow.session.add(edge)
        await self.uow.session.flush()
        await self.uow.record(
            actor,
            case,
            "OWNERSHIP_EDGE_ADDED",
            {
                "edge_id": str(edge.id),
                "basis": draft.basis.value,
                "share": str(draft.share_percent) if draft.share_percent else None,
            },
        )
        return edge

    async def delete_edge(self, actor: Actor, edge_id: UUID) -> None:
        actor.require_write()
        edge, case = await self.uow.child(EdgeModel, actor, edge_id)
        await self.uow.session.delete(edge)
        await self.uow.record(actor, case, "OWNERSHIP_EDGE_REMOVED", {"edge_id": str(edge_id)})

    async def view(self, actor: Actor, case_id: UUID) -> tuple[list[NodeModel], list[EdgeModel]]:
        await self.uow.case(actor, case_id)
        return await self.uow.children(NodeModel, case_id, NodeModel.created_at), await self.uow.children(
            EdgeModel, case_id, EdgeModel.created_at
        )

    async def analyse(self, actor: Actor, case_id: UUID) -> UboAnalysis:
        profile = await CounterpartyService(self.uow).require(actor, case_id)
        return (await self._graph(case_id)).analyse(str(profile.node_id))

    async def recompute(self, actor: Actor, case_id: UUID) -> tuple[OwnershipAnalysisModel, list[BeneficialOwnerModel]]:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        analysis = await self.analyse(actor, case_id)
        for old in await self.uow.children(BeneficialOwnerModel, case_id):
            await self.uow.session.delete(old)
        for old in await self.uow.children(OwnershipAnalysisModel, case_id):
            await self.uow.session.delete(old)
        await self.uow.session.flush()
        stored = OwnershipAnalysisModel(
            case_id=case_id,
            target_node_id=UUID(analysis.target_id),
            status=analysis.status.value,
            exemption=analysis.exemption.value if analysis.exemption else None,
            traced_percent=to_percent(analysis.traced_to_persons),
            opaque_percent=to_percent(max(analysis.opaque_share, Fraction(0))),
            flags=sorted(f.value for f in analysis.flags),
            computed_at=self.uow.clock(),
        )
        self.uow.session.add(stored)
        owners = [
            BeneficialOwnerModel(
                case_id=case_id,
                node_id=UUID(bo.node_id),
                name=bo.name,
                bases=sorted(b.value for b in bo.bases),
                effective_percent=to_percent(bo.effective_share),
                requires_decision=bo.requires_decision,
                paths=[{"nodes": list(p.nodes), "percent": str(to_percent(p.share))} for p in bo.paths],
            )
            for bo in analysis.beneficial_owners
        ]
        self.uow.session.add_all(owners)
        await self.uow.session.flush()
        await self.uow.record(
            actor,
            case,
            "UBO_RECOMPUTED",
            {"status": analysis.status.value, "owners": [o.name for o in owners], "flags": stored.flags},
        )
        return stored, owners

    async def stored(
        self, actor: Actor, case_id: UUID
    ) -> tuple[OwnershipAnalysisModel | None, list[BeneficialOwnerModel]]:
        await self.uow.case(actor, case_id)
        analyses = await self.uow.children(OwnershipAnalysisModel, case_id)
        return (analyses[0] if analyses else None), await self.uow.children(
            BeneficialOwnerModel, case_id, BeneficialOwnerModel.name
        )

    async def upstream_exposure(self, actor: Actor, case_id: UUID, hits: set[UUID]) -> list[dict[str, Any]]:
        if not hits:
            return []
        profile = await CounterpartyService(self.uow).get(actor, case_id)
        if profile is None:
            return []
        graph = await self._graph(case_id)
        target = str(profile.node_id)
        owners = graph.integrated_ownership(target)
        exposure: list[dict[str, Any]] = []
        for hit in sorted(hits, key=str):
            node_id = graph.principal_of(str(hit))
            if node_id not in graph.nodes or node_id == target:
                continue
            share = min(owners.get(node_id, Fraction(0)), Fraction(1))
            controls = target in graph.controlled_by(node_id)
            if share > 0 or controls:
                exposure.append(
                    {
                        "node_id": node_id,
                        "name": graph.nodes[node_id].name,
                        "percent": str(to_percent(share)),
                        "controls": controls,
                    }
                )
        return exposure
