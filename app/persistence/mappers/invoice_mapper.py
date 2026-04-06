from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.domain.enums import InvoiceStatus
from app.domain.models.invoice import Invoice, InvoiceItem
from app.persistence.models.contractor import ContractorORM
from app.persistence.models.contractor_override import ContractorOverrideORM
from app.persistence.models.invoice import InvoiceORM
from app.persistence.models.invoice_item import InvoiceItemORM

_SNAPSHOT_FIELDS = (
    "nip", "regon", "krs", "name", "legal_form",
    "street", "building_no", "apartment_no",
    "postal_code", "city", "voivodeship", "county", "commune", "country",
)

_OVERRIDABLE_FIELDS = (
    "name", "legal_form", "street", "building_no", "apartment_no",
    "postal_code", "city", "voivodeship", "county", "commune",
)


class InvoiceMapper:

    @staticmethod
    def to_domain(orm: InvoiceORM) -> Invoice:
        totals = orm.totals_json or {}
        items = sorted(orm.items, key=lambda i: i.sort_order)
        return Invoice(
            id=orm.id,
            number_local=orm.number_local,
            status=InvoiceStatus(orm.status),
            issue_date=orm.issue_date,
            sale_date=orm.sale_date,
            currency=orm.currency,
            seller_snapshot=orm.seller_snapshot_json,
            buyer_snapshot=orm.buyer_snapshot_json,
            items=[InvoiceMapper._item_to_domain(item) for item in items],
            total_net=Decimal(str(totals.get("total_net", 0))),
            total_vat=Decimal(str(totals.get("total_vat", 0))),
            total_gross=Decimal(str(totals.get("total_gross", 0))),
            created_by=orm.created_by,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def to_orm(invoice: Invoice) -> InvoiceORM:
        orm = InvoiceORM(
            id=invoice.id,
            number_local=invoice.number_local,
            status=invoice.status.value,
            seller_snapshot_json=invoice.seller_snapshot,
            buyer_snapshot_json=invoice.buyer_snapshot,
            totals_json=InvoiceMapper._totals_to_json(invoice),
            issue_date=invoice.issue_date,
            sale_date=invoice.sale_date,
            currency=invoice.currency,
            created_by=invoice.created_by,
        )
        orm.items = [
            InvoiceMapper._item_to_orm(item, invoice.id)
            for item in invoice.items
        ]
        return orm

    @staticmethod
    def update_orm(orm: InvoiceORM, invoice: Invoice) -> None:
        orm.number_local = invoice.number_local
        orm.status = invoice.status.value
        orm.seller_snapshot_json = invoice.seller_snapshot
        orm.buyer_snapshot_json = invoice.buyer_snapshot
        orm.totals_json = InvoiceMapper._totals_to_json(invoice)
        orm.issue_date = invoice.issue_date
        orm.sale_date = invoice.sale_date
        orm.currency = invoice.currency

        # Synchronizacja pozycji — zastąpienie kolekcji.
        # Relacja ma cascade="all, delete-orphan", więc SQLAlchemy
        # automatycznie usunie stare i doda nowe pozycje.
        orm.items = [
            InvoiceMapper._item_to_orm(item, invoice.id)
            for item in invoice.items
        ]

    @staticmethod
    def build_contractor_snapshot(
        contractor: ContractorORM,
        override: ContractorOverrideORM | None = None,
    ) -> dict:
        snapshot: dict[str, str | None] = {}
        for field_name in _SNAPSHOT_FIELDS:
            snapshot[field_name] = getattr(contractor, field_name, None)

        if override is not None and override.is_active:
            for field_name in _OVERRIDABLE_FIELDS:
                override_value = getattr(override, field_name, None)
                if override_value is not None:
                    snapshot[field_name] = override_value

        return snapshot

    # -- prywatne helpery --

    @staticmethod
    def _item_to_domain(orm: InvoiceItemORM) -> InvoiceItem:
        return InvoiceItem(
            id=orm.id,
            name=orm.name,
            quantity=orm.quantity,
            unit=orm.unit,
            unit_price_net=orm.unit_price_net,
            vat_rate=orm.vat_rate,
            net_total=orm.net_amount,
            vat_total=orm.vat_amount,
            gross_total=orm.gross_amount,
            sort_order=orm.sort_order,
        )

    @staticmethod
    def _item_to_orm(item: InvoiceItem, invoice_id: UUID) -> InvoiceItemORM:
        return InvoiceItemORM(
            id=item.id,
            invoice_id=invoice_id,
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price_net=item.unit_price_net,
            vat_rate=item.vat_rate,
            net_amount=item.net_total,
            vat_amount=item.vat_total,
            gross_amount=item.gross_total,
            sort_order=item.sort_order,
        )

    @staticmethod
    def _totals_to_json(invoice: Invoice) -> dict:
        return {
            "total_net": str(invoice.total_net),
            "total_vat": str(invoice.total_vat),
            "total_gross": str(invoice.total_gross),
        }
