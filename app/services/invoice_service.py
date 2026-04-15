from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.core.utils import to_uuid
from app.domain.enums import InvoiceStatus
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError
from app.domain.models.invoice import Invoice, InvoiceItem
from app.persistence.mappers.invoice_mapper import InvoiceMapper
from app.persistence.repositories.contractor_override_repository import (
    ContractorOverrideRepository,
)
from app.persistence.repositories.contractor_repository import ContractorRepository
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.integrations.nbp.client import NbpRateClient, NbpRateError
from app.services.audit_service import AuditService
from app.services.invoice_number_policy import InvoiceNumberPolicy
from app.services.stock_service import StockService

logger = logging.getLogger(__name__)

_TWO_PLACES = Decimal("0.01")


class InvoiceService:
    MAX_RETRIES = 3

    def __init__(
        self,
        session: Session,
        invoice_repository: InvoiceRepository,
        contractor_repository: ContractorRepository,
        contractor_override_repository: ContractorOverrideRepository,
        audit_service: AuditService,
        stock_service: StockService | None = None,
    ) -> None:
        self.session = session
        self.invoice_repository = invoice_repository
        self.contractor_repository = contractor_repository
        self.contractor_override_repository = contractor_override_repository
        self.audit_service = audit_service
        self.stock_service = stock_service

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def create_invoice(self, data: dict, actor: AuthenticatedUser) -> Invoice:
        buyer_id: UUID | None = data.get("buyer_id")
        if buyer_id is None:
            raise InvalidInvoiceError("Nabywca (buyer_id) jest wymagany.")

        raw_items: list[dict] = data.get("items", [])
        if not raw_items:
            raise InvalidInvoiceError(
                "Faktura musi zawierać co najmniej jedną pozycję."
            )

        issue_date = data["issue_date"]
        sale_date = data["sale_date"]
        delivery_date: date | None = data.get("delivery_date")

        if sale_date > issue_date:
            raise InvalidInvoiceError(
                "Data sprzedaży nie może być późniejsza niż data wystawienia."
            )

        buyer_snapshot = self._resolve_buyer_snapshot(buyer_id)
        seller_snapshot = self._build_seller_snapshot()
        items = self._build_items(raw_items)
        total_net, total_vat, total_gross = self._calculate_totals(items)

        currency = data.get("currency", "PLN")
        exchange_rate: Decimal | None = data.get("exchange_rate")
        exchange_rate_date: date | None = data.get("exchange_rate_date")

        if currency != "PLN" and exchange_rate is None:
            nbp_date = exchange_rate_date or (issue_date - date.resolution)
            try:
                exchange_rate = NbpRateClient().get_mid_rate(currency, nbp_date)
                exchange_rate_date = nbp_date
            except NbpRateError as exc:
                logger.warning("Nie udało się pobrać kursu NBP dla %s: %s", currency, exc)

        now = datetime.now(UTC)

        invoice = Invoice(
            id=uuid4(),
            number_local=None,
            status=InvoiceStatus.DRAFT,
            direction=data.get("direction", "sale"),
            issue_date=issue_date,
            sale_date=sale_date,
            delivery_date=delivery_date,
            currency=currency,
            exchange_rate=exchange_rate,
            exchange_rate_date=exchange_rate_date,
            seller_snapshot=seller_snapshot,
            buyer_snapshot=buyer_snapshot,
            items=items,
            total_net=total_net,
            total_vat=total_vat,
            total_gross=total_gross,
            created_by=to_uuid(actor.user_id),
            created_at=now,
            updated_at=now,
        )

        saved = self.invoice_repository.add(invoice)
        self.session.flush()

        self.audit_service.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="invoice.created",
            entity_type="invoice",
            entity_id=str(saved.id),
            after={
                "status": saved.status.value,
                "total_gross": str(saved.total_gross),
            },
        )

        if self.stock_service is not None:
            self.stock_service.handle_invoice_created(
                invoice_id=saved.id,
                direction=saved.direction,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in saved.items
                    if hasattr(item, "product_id")
                ],
            )

        return saved

    def get_invoice(self, invoice_id: UUID) -> Invoice:
        invoice = self.invoice_repository.get_by_id(invoice_id)
        if invoice is None:
            raise NotFoundError(f"Nie znaleziono faktury {invoice_id}.")
        return invoice

    def list_invoices(
        self,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        issue_date_from: date | None = None,
        issue_date_to: date | None = None,
        number_filter: str | None = None,
        direction: str | None = None,
    ) -> tuple[list[Invoice], int]:
        return self.invoice_repository.list_paginated(
            status=status,
            page=page,
            size=size,
            issue_date_from=issue_date_from,
            issue_date_to=issue_date_to,
            number_filter=number_filter,
            direction=direction,
        )

    def mark_as_ready(
        self, invoice_id: UUID, actor: AuthenticatedUser
    ) -> Invoice:
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                invoice = self.invoice_repository.lock_for_update(invoice_id)
                if invoice is None:
                    raise NotFoundError(f"Faktura {invoice_id} nie istnieje.")

                if not invoice.can_transition_to(InvoiceStatus.READY_FOR_SUBMISSION):
                    raise InvalidStatusTransitionError(
                        f"Nie można zmienić statusu z "
                        f"'{invoice.status.value}' na 'ready_for_submission'."
                    )

                year = invoice.issue_date.year
                month = invoice.issue_date.month

                seq = self.invoice_repository.get_next_sequence_number(year, month)
                number = InvoiceNumberPolicy.generate(year, month, seq)

                if self.invoice_repository.exists_by_number(number):
                    raise IntegrityError(
                        statement=None,
                        params=None,
                        orig=Exception(f"Duplikat numeru faktury: {number}"),
                    )

                invoice.number_local = number
                invoice.status = InvoiceStatus.READY_FOR_SUBMISSION
                invoice.updated_at = datetime.now(UTC)

                updated = self.invoice_repository.update(invoice_id, invoice)
                self.session.flush()

                self.audit_service.record(
                    actor_user_id=actor.user_id,
                    actor_role=actor.role,
                    event_type="invoice.marked_ready",
                    entity_type="invoice",
                    entity_id=str(invoice_id),
                    after={
                        "status": updated.status.value,
                        "number_local": updated.number_local,
                    },
                )

                logger.info(
                    "Faktura oznaczona jako gotowa: invoice_id=%s number=%s",
                    invoice_id,
                    number,
                )

                return updated

            except (InvalidStatusTransitionError, NotFoundError, ValueError):
                raise

            except (IntegrityError, OperationalError):
                self.session.rollback()

                if attempt >= self.MAX_RETRIES:
                    logger.exception(
                        "Nie udało się oznaczyć faktury jako gotowej: invoice_id=%s",
                        invoice_id,
                    )
                    raise

                logger.warning(
                    "Retry mark_as_ready: attempt=%s/%s invoice_id=%s",
                    attempt,
                    self.MAX_RETRIES,
                    invoice_id,
                )

        raise RuntimeError(
            f"Nie udało się oznaczyć faktury jako gotowej: {invoice_id}"
        )

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _resolve_buyer_snapshot(self, buyer_id: UUID) -> dict:
        contractor = self.contractor_repository.get_by_id(buyer_id)
        if contractor is None:
            raise NotFoundError(f"Nie znaleziono kontrahenta {buyer_id}.")

        override = (
            self.contractor_override_repository.get_active_by_contractor_id(buyer_id)
        )
        return InvoiceMapper.build_contractor_snapshot(contractor, override)

    @staticmethod
    def _build_seller_snapshot() -> dict:
        return {
            "nip": settings.seller_nip,
            "name": settings.seller_name,
            "street": settings.seller_street,
            "building_no": settings.seller_building_no,
            "apartment_no": settings.seller_apartment_no,
            "postal_code": settings.seller_postal_code,
            "city": settings.seller_city,
            "country": settings.seller_country,
        }

    @staticmethod
    def _build_items(raw_items: list[dict]) -> list[InvoiceItem]:
        items: list[InvoiceItem] = []

        for idx, raw in enumerate(raw_items):
            name = raw["name"].strip()
            if not name:
                raise InvalidInvoiceError(
                    f"Pozycja {idx + 1}: nazwa nie może być pusta."
                )

            quantity = Decimal(str(raw["quantity"]))
            unit_price_net = Decimal(str(raw["unit_price_net"]))
            vat_rate = Decimal(str(raw["vat_rate"]))

            if quantity <= 0:
                raise InvalidInvoiceError(
                    f"Pozycja {idx + 1}: ilość musi być większa od zera."
                )
            if unit_price_net < 0:
                raise InvalidInvoiceError(
                    f"Pozycja {idx + 1}: cena jednostkowa nie może być ujemna."
                )
            if vat_rate < 0 or vat_rate > 100:
                raise InvalidInvoiceError(
                    f"Pozycja {idx + 1}: stawka VAT musi być w zakresie 0–100."
                )

            net_total = (quantity * unit_price_net).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )
            vat_total = (net_total * vat_rate / 100).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )
            gross_total = net_total + vat_total

            items.append(
                InvoiceItem(
                    name=name,
                    quantity=quantity,
                    unit=raw.get("unit", "szt."),
                    unit_price_net=unit_price_net,
                    vat_rate=vat_rate,
                    net_total=net_total,
                    vat_total=vat_total,
                    gross_total=gross_total,
                    sort_order=idx + 1,
                )
            )

        return items

    @staticmethod
    def _calculate_totals(
        items: list[InvoiceItem],
    ) -> tuple[Decimal, Decimal, Decimal]:
        total_net = sum(i.net_total for i in items)
        total_vat = sum(i.vat_total for i in items)
        total_gross = sum(i.gross_total for i in items)
        return (
            Decimal(str(total_net)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            Decimal(str(total_vat)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            Decimal(str(total_gross)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
        )
