from dataclasses import dataclass
from datetime import date
from uuid import UUID

from counterparty_dd.application.context import Actor, UnitOfWork
from counterparty_dd.domain.enums import NodeKind, UboExemption
from counterparty_dd.domain.errors import Conflict, DomainError, NotFound
from counterparty_dd.domain.identifiers import is_valid_inn, is_valid_ogrn, is_valid_ogrnip
from counterparty_dd.domain.names import normalize
from counterparty_dd.infrastructure.db.models import CounterpartyModel, NodeModel, RelatedPersonModel


@dataclass(frozen=True, slots=True)
class CounterpartyDraft:
    legal_name: str
    inn: str | None = None
    ogrn: str | None = None
    country_code: str | None = "RU"
    address: str | None = None
    registered_on: date | None = None
    ubo_exemption: UboExemption | None = None


@dataclass(frozen=True, slots=True)
class RegistryUpdate:
    egrul_unreliable_since: date | None
    pending_exclusion: bool
    registered_on: date | None


@dataclass(frozen=True, slots=True)
class PersonDraft:
    full_name: str
    relation_type: str
    inn: str | None = None
    birth_date: date | None = None
    citizenship: str | None = None


def validate_identifiers(inn: str | None, ogrn: str | None) -> None:
    if inn is not None and not is_valid_inn(inn):
        raise DomainError("ИНН не прошёл проверку контрольного числа")
    if ogrn is not None and not (is_valid_ogrn(ogrn) or is_valid_ogrnip(ogrn)):
        raise DomainError("ОГРН/ОГРНИП не прошёл проверку контрольного числа")


class CounterpartyService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def get(self, actor: Actor, case_id: UUID) -> CounterpartyModel | None:
        await self.uow.case(actor, case_id)
        found = await self.uow.children(CounterpartyModel, case_id)
        return found[0] if found else None

    async def require(self, actor: Actor, case_id: UUID) -> CounterpartyModel:
        profile = await self.get(actor, case_id)
        if profile is None:
            raise NotFound("Контрагент по проверке не зарегистрирован")
        return profile

    async def register(self, actor: Actor, case_id: UUID, draft: CounterpartyDraft) -> CounterpartyModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        if await self.get(actor, case_id) is not None:
            raise Conflict("Контрагент по проверке уже зарегистрирован")
        validate_identifiers(draft.inn, draft.ogrn)
        now = self.uow.clock()
        node = NodeModel(
            case_id=case_id,
            kind=NodeKind.LEGAL_ENTITY.value,
            display_name=draft.legal_name,
            inn=draft.inn,
            ogrn=draft.ogrn,
            exemption=draft.ubo_exemption.value if draft.ubo_exemption else None,
            created_at=now,
        )
        self.uow.session.add(node)
        await self.uow.session.flush()
        profile = CounterpartyModel(
            case_id=case_id,
            legal_name=draft.legal_name,
            normalized_name=normalize(draft.legal_name),
            inn=draft.inn,
            ogrn=draft.ogrn,
            country_code=draft.country_code.upper() if draft.country_code else None,
            address=draft.address,
            registered_on=draft.registered_on,
            pending_exclusion=False,
            ubo_exemption=node.exemption,
            node_id=node.id,
        )
        self.uow.session.add(profile)
        await self.uow.session.flush()
        await self.uow.record(actor, case, "COUNTERPARTY_REGISTERED", {"inn": draft.inn, "ogrn": draft.ogrn})
        return profile

    async def update_registry(self, actor: Actor, case_id: UUID, update: RegistryUpdate) -> CounterpartyModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        profile = await self.require(actor, case_id)
        profile.egrul_unreliable_since = update.egrul_unreliable_since
        profile.pending_exclusion = update.pending_exclusion
        if update.registered_on is not None:
            profile.registered_on = update.registered_on
        await self.uow.record(
            actor,
            case,
            "REGISTRY_STATE_UPDATED",
            {
                "egrul_unreliable_since": str(update.egrul_unreliable_since) if update.egrul_unreliable_since else None,
                "pending_exclusion": update.pending_exclusion,
            },
        )
        return profile

    async def add_person(self, actor: Actor, case_id: UUID, draft: PersonDraft) -> RelatedPersonModel:
        actor.require_write()
        case = await self.uow.case(actor, case_id)
        validate_identifiers(draft.inn, None)
        person = RelatedPersonModel(
            case_id=case_id,
            full_name=draft.full_name,
            normalized_name=normalize(draft.full_name),
            relation_type=draft.relation_type,
            inn=draft.inn,
            birth_date=draft.birth_date,
            citizenship=draft.citizenship.upper() if draft.citizenship else None,
        )
        self.uow.session.add(person)
        await self.uow.session.flush()
        await self.uow.record(
            actor, case, "RELATED_PERSON_ADDED", {"person_id": str(person.id), "relation": draft.relation_type}
        )
        return person

    async def persons(self, actor: Actor, case_id: UUID) -> list[RelatedPersonModel]:
        await self.uow.case(actor, case_id)
        return await self.uow.children(RelatedPersonModel, case_id, RelatedPersonModel.full_name)
