from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.core.security import AuthenticatedUser
from app.core.utils import to_uuid
from app.persistence.models.contractor import ContractorORM
from app.persistence.models.contractor_override import ContractorOverrideORM
from app.persistence.repositories.contractor_override_repository import ContractorOverrideRepository
from app.persistence.repositories.contractor_repository import ContractorRepository
from app.services.audit_service import AuditService


class ContractorService:
    def __init__(
        self,
        session: Session,
        contractor_repository: ContractorRepository,
        contractor_override_repository: ContractorOverrideRepository,
        audit_service: AuditService,
        regon_client,
        regon_mapper,
    ) -> None:
        self.session = session
        self.contractor_repository = contractor_repository
        self.contractor_override_repository = contractor_override_repository
        self.audit_service = audit_service
        self.regon_client = regon_client
        self.regon_mapper = regon_mapper

    def create_manual(self, nip: str, name: str, city: str, postal_code: str,
                       street: str | None, building_no: str | None,
                       apartment_no: str | None, actor: AuthenticatedUser) -> dict:
        """Tworzy kontrahenta ręcznie (bez zapytania do REGON).

        Używane wyłącznie w środowiskach testowych / dla kontrahentów zagranicznych.
        """
        normalized_nip = nip.strip()
        existing = self.contractor_repository.get_by_nip(normalized_nip)
        if existing is not None:
            return self._build_response(
                existing,
                self.contractor_override_repository.get_active_by_contractor_id(existing.id),
            )

        from datetime import UTC, datetime
        contractor = ContractorORM(
            nip=normalized_nip,
            name=name,
            city=city,
            postal_code=postal_code,
            street=street,
            building_no=building_no,
            apartment_no=apartment_no,
            source="manual",
            source_fetched_at=datetime.now(UTC),
        )
        self.contractor_repository.add(contractor)
        self.audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="contractor.manual_create",
            entity_type="contractor",
            entity_id=str(contractor.id),
            metadata={"nip": normalized_nip},
        )
        self.session.commit()
        self.session.refresh(contractor)
        return self._build_response(contractor, None)

    def get_by_nip(self, nip: str, actor: AuthenticatedUser, force_refresh: bool = False) -> dict:
        normalized_nip = self._normalize_nip(nip)
        self._validate_nip(normalized_nip)

        contractor = self.contractor_repository.get_by_nip(normalized_nip)
        active_override = None
        if contractor is not None:
            active_override = self.contractor_override_repository.get_active_by_contractor_id(contractor.id)

        if contractor is not None and not force_refresh and self._is_cache_fresh(contractor):
            return self._build_response(contractor, active_override)

        try:
            lookup_result = self.regon_client.lookup_by_nip(normalized_nip)
        except ExternalServiceError as exc:
            if contractor is None:
                raise

            contractor.lookup_last_status = "failed"
            contractor.lookup_last_error = str(exc)
            self.contractor_repository.save(contractor)
            self.session.commit()
            self.session.refresh(contractor)
            return self._build_response(contractor, active_override)

        if lookup_result is None:
            if contractor is not None:
                contractor.lookup_last_status = "not_found"
                contractor.lookup_last_error = None
                self.contractor_repository.save(contractor)
                self.session.commit()
                self.session.refresh(contractor)
                return self._build_response(contractor, active_override)
            raise NotFoundError(f"Nie znaleziono kontrahenta dla NIP {normalized_nip}.")

        contractor = self._upsert_from_regon(contractor=contractor, lookup_result=lookup_result)
        active_override = self.contractor_override_repository.get_active_by_contractor_id(contractor.id)
        self.audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="contractor.regon_sync",
            entity_type="contractor",
            entity_id=str(contractor.id),
            metadata={"nip": normalized_nip, "force_refresh": force_refresh},
        )
        self.session.commit()
        self.session.refresh(contractor)
        return self._build_response(contractor, active_override)

    def update_override(self, contractor_id: UUID, override_data: dict, actor: AuthenticatedUser) -> dict:
        contractor = self.contractor_repository.get_by_id(contractor_id)
        if contractor is None:
            raise NotFoundError("Nie znaleziono kontrahenta.")

        active_override = self.contractor_override_repository.get_active_by_contractor_id(contractor_id)
        before = self._override_snapshot(active_override)

        if active_override is None:
            active_override = ContractorOverrideORM(contractor_id=contractor_id, created_by=to_uuid(actor.user_id))
            for field_name, value in override_data.items():
                setattr(active_override, field_name, value)
            self.contractor_override_repository.add(active_override)
        else:
            for field_name, value in override_data.items():
                setattr(active_override, field_name, value)
            self.contractor_override_repository.save(active_override)

        self.audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="contractor.override_updated",
            entity_type="contractor",
            entity_id=str(contractor.id),
            before=before,
            after=self._override_snapshot(active_override),
        )
        self.session.commit()
        self.session.refresh(active_override)
        return self._build_response(contractor, active_override)

    def _upsert_from_regon(self, contractor: ContractorORM | None, lookup_result: dict) -> ContractorORM:
        mapped_data = self.regon_mapper.to_contractor_fields(
            lookup_result,
            fetched_at=datetime.now(UTC),
            cache_ttl_days=settings.contractor_cache_ttl_days,
        )

        if contractor is None:
            contractor = ContractorORM(**mapped_data)
            self.contractor_repository.add(contractor)
            return contractor

        for field_name, value in mapped_data.items():
            setattr(contractor, field_name, value)
        self.contractor_repository.save(contractor)
        return contractor

    def _build_response(self, contractor: ContractorORM, active_override: ContractorOverrideORM | None) -> dict:
        response = {
            "id": contractor.id,
            "nip": contractor.nip,
            "regon": contractor.regon,
            "krs": contractor.krs,
            "name": contractor.name,
            "legal_form": contractor.legal_form,
            "street": contractor.street,
            "building_no": contractor.building_no,
            "apartment_no": contractor.apartment_no,
            "postal_code": contractor.postal_code,
            "city": contractor.city,
            "voivodeship": contractor.voivodeship,
            "county": contractor.county,
            "commune": contractor.commune,
            "country": contractor.country,
            "status": contractor.status,
            "source": contractor.source,
            "source_fetched_at": contractor.source_fetched_at,
            "cache_valid_until": contractor.cache_valid_until,
            "lookup_last_status": contractor.lookup_last_status,
            "lookup_last_error": contractor.lookup_last_error,
            "has_override": active_override is not None,
        }

        if active_override is None:
            return response

        for field_name in (
            "name",
            "legal_form",
            "street",
            "building_no",
            "apartment_no",
            "postal_code",
            "city",
            "county",
            "commune",
            "voivodeship",
        ):
            override_value = getattr(active_override, field_name)
            if override_value:
                response[field_name] = override_value

        response["source"] = "regon_with_override" if contractor.source == "regon" else contractor.source
        return response

    @staticmethod
    def _normalize_nip(nip: str) -> str:
        return "".join(character for character in nip if character.isdigit())

    @staticmethod
    def _validate_nip(nip: str) -> None:
        if len(nip) != 10 or not nip.isdigit():
            raise NotFoundError("Nieprawidlowy format NIP.")

        weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
        checksum = sum(int(digit) * weight for digit, weight in zip(nip[:9], weights, strict=True)) % 11
        if checksum == 10 or checksum != int(nip[9]):
            raise NotFoundError("Nieprawidlowy numer NIP.")

    @staticmethod
    def _is_cache_fresh(contractor: ContractorORM) -> bool:
        return contractor.cache_valid_until is not None and contractor.cache_valid_until >= datetime.now(UTC)

    @staticmethod
    def _override_snapshot(active_override: ContractorOverrideORM | None) -> dict | None:
        if active_override is None:
            return None

        return {
            "name": active_override.name,
            "legal_form": active_override.legal_form,
            "street": active_override.street,
            "building_no": active_override.building_no,
            "apartment_no": active_override.apartment_no,
            "postal_code": active_override.postal_code,
            "city": active_override.city,
            "county": active_override.county,
            "commune": active_override.commune,
            "voivodeship": active_override.voivodeship,
            "override_reason": active_override.override_reason,
            "is_active": active_override.is_active,
        }

