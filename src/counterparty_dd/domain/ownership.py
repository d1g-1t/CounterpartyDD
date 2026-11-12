from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction

from counterparty_dd.domain.enums import EdgeBasis, NodeKind, UboBasis, UboExemption
from counterparty_dd.domain.errors import OwnershipError

UBO_THRESHOLD = Fraction(1, 4)
CONTROL_THRESHOLD = Fraction(1, 2)
OPACITY_THRESHOLD = Fraction(1, 4)
MAX_EXPLAINED_PATHS = 10


class UboStatus(StrEnum):
    RESOLVED = "RESOLVED"
    EXEMPT = "EXEMPT"
    EXECUTIVE_FALLBACK = "EXECUTIVE_FALLBACK"
    UNRESOLVED = "UNRESOLVED"


class Flag(StrEnum):
    CROSS_HOLDING = "CROSS_HOLDING"
    OPAQUE_SHARE = "OPAQUE_SHARE"
    MANAGING_COMPANY = "MANAGING_COMPANY"
    FALLBACK_REQUIRES_DECISION = "FALLBACK_REQUIRES_DECISION"
    NO_EXECUTIVE = "NO_EXECUTIVE"


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: NodeKind
    name: str
    exemption: UboExemption | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    basis: EdgeBasis
    share: Fraction | None = None


@dataclass(frozen=True, slots=True)
class OwnershipPath:
    nodes: tuple[str, ...]
    share: Fraction


@dataclass(frozen=True, slots=True)
class BeneficialOwner:
    node_id: str
    name: str
    bases: frozenset[UboBasis]
    effective_share: Fraction
    paths: tuple[OwnershipPath, ...]
    requires_decision: bool = False


@dataclass(frozen=True, slots=True)
class UboAnalysis:
    target_id: str
    status: UboStatus
    exemption: UboExemption | None
    owners: dict[str, Fraction]
    controllers: frozenset[str]
    beneficial_owners: tuple[BeneficialOwner, ...]
    traced_to_persons: Fraction
    opaque_share: Fraction
    flags: frozenset[Flag] = field(default_factory=frozenset)


class OwnershipGraph:
    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        self.nodes: dict[str, Node] = {}
        for node in nodes:
            if node.id in self.nodes:
                raise OwnershipError(f"Узел {node.id} указан дважды")
            self.nodes[node.id] = node
        self.edges: list[Edge] = list(edges)
        self._validate()
        self._principal = self._resolve_principals()
        self._equity, self._control = self._resolved_relations()

    def _validate(self) -> None:
        incoming: dict[str, Fraction] = defaultdict(Fraction)
        principals: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges:
            for endpoint in (edge.source, edge.target):
                if endpoint not in self.nodes:
                    raise OwnershipError(f"Узел {endpoint} не найден в графе")
            if edge.source == edge.target:
                raise OwnershipError("Связь узла с самим собой недопустима")
            target_kind = self.nodes[edge.target].kind
            match edge.basis:
                case EdgeBasis.EQUITY:
                    if edge.share is None or not 0 < edge.share <= 1:
                        raise OwnershipError("Доля участия должна быть больше 0 и не больше 100 %")
                    if target_kind is NodeKind.PERSON:
                        raise OwnershipError("Физическое лицо не может иметь участников")
                    incoming[edge.target] += edge.share
                case EdgeBasis.CONTROL:
                    if target_kind is NodeKind.PERSON:
                        raise OwnershipError("Контроль устанавливается только над организацией")
                case EdgeBasis.NOMINEE:
                    principals[edge.target].add(edge.source)
                case EdgeBasis.EXECUTIVE_BODY:
                    if target_kind is NodeKind.PERSON:
                        raise OwnershipError("Единоличный исполнительный орган бывает только у организации")
        for node_id, total in incoming.items():
            if total > 1:
                raise OwnershipError(f"Сумма долей в капитале {self.nodes[node_id].name} превышает 100 %")
        for nominee, sources in principals.items():
            if len(sources) > 1:
                raise OwnershipError(
                    f"У номинального держателя {self.nodes[nominee].name} указано несколько принципалов"
                )

    def _resolve_principals(self) -> dict[str, str]:
        direct = {e.target: e.source for e in self.edges if e.basis is EdgeBasis.NOMINEE}
        resolved: dict[str, str] = {}
        for nominee in direct:
            seen = {nominee}
            current = direct[nominee]
            while current in direct:
                if current in seen:
                    raise OwnershipError("Цепочка номинальных держателей замкнута")
                seen.add(current)
                current = direct[current]
            resolved[nominee] = current
        return resolved

    def principal_of(self, node_id: str) -> str:
        return self._principal.get(node_id, node_id)

    def _resolved_relations(self) -> tuple[dict[str, dict[str, Fraction]], dict[str, set[str]]]:
        equity: dict[str, dict[str, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
        control: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges:
            source = self.principal_of(edge.source)
            if edge.basis is EdgeBasis.EQUITY and edge.share is not None:
                if source == edge.target:
                    raise OwnershipError("Номинальное владение организацией самой себе недопустимо")
                equity[edge.target][source] += edge.share
            elif edge.basis is EdgeBasis.CONTROL and source != edge.target:
                control[source].add(edge.target)
        return {k: dict(v) for k, v in equity.items()}, control

    def _upstream(self, target: str) -> list[str]:
        seen = {target}
        queue = deque([target])
        while queue:
            current = queue.popleft()
            for holder in self._equity.get(current, {}):
                if holder not in seen:
                    seen.add(holder)
                    queue.append(holder)
        return sorted(seen)

    def integrated_ownership(self, target: str) -> dict[str, Fraction]:
        if target not in self.nodes:
            raise OwnershipError(f"Узел {target} не найден в графе")
        variables = self._upstream(target)
        index = {node_id: i for i, node_id in enumerate(variables)}
        size = len(variables)
        matrix = [[Fraction(int(i == j)) for j in range(size)] for i in range(size)]
        rhs = [Fraction(0)] * size
        for owned, holders in self._equity.items():
            if owned not in index:
                continue
            for holder, share in holders.items():
                matrix[index[holder]][index[owned]] -= share
                if owned == target:
                    rhs[index[holder]] += share
        solution = _solve(matrix, rhs)
        return {node_id: solution[index[node_id]] for node_id in variables if solution[index[node_id]] > 0}

    def has_cross_holding(self, target: str) -> bool:
        upstream = set(self._upstream(target))
        state: dict[str, int] = {}

        def visit(node_id: str) -> bool:
            state[node_id] = 1
            for holder in self._equity.get(node_id, {}):
                if holder not in upstream:
                    continue
                if state.get(holder) == 1 or (holder not in state and visit(holder)):
                    return True
            state[node_id] = 2
            return False

        return any(node_id not in state and visit(node_id) for node_id in upstream)

    def controlled_by(self, person: str) -> set[str]:
        controlled: set[str] = set()
        changed = True
        while changed:
            changed = False
            for controller in (person, *controlled):
                for entity in self._control.get(controller, set()):
                    if entity not in controlled:
                        controlled.add(entity)
                        changed = True
            for entity, holders in self._equity.items():
                if entity in controlled or entity == person:
                    continue
                aggregate = sum(
                    (share for holder, share in holders.items() if holder == person or holder in controlled),
                    Fraction(0),
                )
                if aggregate > CONTROL_THRESHOLD:
                    controlled.add(entity)
                    changed = True
        return controlled

    def paths(self, source: str, target: str) -> tuple[OwnershipPath, ...]:
        found: list[OwnershipPath] = []

        def walk(current: str, trail: list[str], share: Fraction) -> None:
            if len(found) >= MAX_EXPLAINED_PATHS:
                return
            for owned, holders in self._equity.items():
                if current not in holders or owned in trail:
                    continue
                next_share = share * holders[current]
                if owned == target:
                    found.append(OwnershipPath((*trail, owned), next_share))
                else:
                    walk(owned, [*trail, owned], next_share)

        walk(source, [source], Fraction(1))
        return tuple(sorted(found, key=lambda p: (-p.share, p.nodes)))

    def analyse(self, target: str) -> UboAnalysis:
        if target not in self.nodes:
            raise OwnershipError(f"Узел {target} не найден в графе")
        node = self.nodes[target]
        integrated = self.integrated_ownership(target)
        integrated.pop(target, None)
        flags: set[Flag] = set()
        if self.has_cross_holding(target):
            flags.add(Flag.CROSS_HOLDING)
        leaves = {n: s for n, s in integrated.items() if not self._equity.get(n)}
        persons = {n: s for n, s in leaves.items() if self.nodes[n].kind is NodeKind.PERSON}
        exempt_leaves = sum((s for n, s in leaves.items() if self.nodes[n].exemption is not None), Fraction(0))
        traced = sum(persons.values(), Fraction(0))
        opaque = 1 - traced - exempt_leaves
        if opaque > OPACITY_THRESHOLD:
            flags.add(Flag.OPAQUE_SHARE)
        persons_all = [n for n, v in self.nodes.items() if v.kind is NodeKind.PERSON and n not in self._principal]
        controllers = frozenset(p for p in persons_all if target in self.controlled_by(p))
        if node.exemption is not None:
            return UboAnalysis(
                target, UboStatus.EXEMPT, node.exemption, leaves, controllers, (), traced, opaque, frozenset(flags)
            )
        found: list[BeneficialOwner] = []
        for person in sorted(set(persons) | controllers):
            bases: set[UboBasis] = set()
            share = persons.get(person, Fraction(0))
            if share > UBO_THRESHOLD:
                bases.add(UboBasis.OWNERSHIP)
            if person in controllers:
                bases.add(UboBasis.CONTROL)
            if bases:
                found.append(
                    BeneficialOwner(
                        person, self.nodes[person].name, frozenset(bases), share, self.paths(person, target)
                    )
                )
        if found:
            status = UboStatus.RESOLVED
        else:
            executives = [e.source for e in self.edges if e.basis is EdgeBasis.EXECUTIVE_BODY and e.target == target]
            person_executives = [e for e in executives if self.nodes[e].kind is NodeKind.PERSON]
            if person_executives:
                status = UboStatus.EXECUTIVE_FALLBACK
                flags.add(Flag.FALLBACK_REQUIRES_DECISION)
                found = [
                    BeneficialOwner(
                        e, self.nodes[e].name, frozenset({UboBasis.EXECUTIVE_FALLBACK}), Fraction(0), (), True
                    )
                    for e in sorted(person_executives)
                ]
            else:
                status = UboStatus.UNRESOLVED
                flags.add(Flag.MANAGING_COMPANY if executives else Flag.NO_EXECUTIVE)
        return UboAnalysis(target, status, None, leaves, controllers, tuple(found), traced, opaque, frozenset(flags))


def _solve(matrix: list[list[Fraction]], rhs: list[Fraction]) -> list[Fraction]:
    size = len(rhs)
    a = [[*row, value] for row, value in zip(matrix, rhs, strict=True)]
    for col in range(size):
        pivot = next((r for r in range(col, size) if a[r][col] != 0), None)
        if pivot is None:
            raise OwnershipError("Замкнутое кольцо взаимного владения без внешних участников: доли не определяются")
        a[col], a[pivot] = a[pivot], a[col]
        lead = a[col][col]
        a[col] = [v / lead for v in a[col]]
        for r in range(size):
            if r != col and a[r][col] != 0:
                factor = a[r][col]
                a[r] = [rv - factor * cv for rv, cv in zip(a[r], a[col], strict=True)]
    return [a[r][size] for r in range(size)]
