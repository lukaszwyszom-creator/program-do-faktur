"""Serwis modułu płatności.

Odpowiedzialności:
  - Import przelewów z CSV
  - Uruchomienie silnika scoringowego
  - Automatyczne i ręczne alokacje
  - Cofanie alokacji
  - Historia płatności faktury
  - Aktualizacja payment_status na fakturze
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.core.utils import to_uuid
from app.domain.enums import InvoicePaymentStatus, PaymentMatchMethod, PaymentMatchStatus
from app.persistence.models.bank_transaction import BankTransactionORM
from app.persistence.models.invoice import InvoiceORM
from app.persistence.models.payment_allocation import PaymentAllocationORM
from app.persistence.repositories.bank_transaction_repository import BankTransactionRepository
from app.persistence.repositories.invoice_repository import InvoiceRepository
from app.persistence.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.services.audit_service import AuditService
from app.services.payment_matcher import (
    AUTO_MATCH_THRESHOLD,
    MANUAL_REVIEW_THRESHOLD,
    InvoiceCandidate,
    PaymentMatcher,
    TransactionCandidate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Nazwy kolumn CSV akceptowane przez importer (case-insensitive)
# ---------------------------------------------------------------------------
_CSV_COLUMN_ALIASES: dict[str, list[str]] = {
    "transaction_date": ["data", "data operacji", "transactiondate", "transaction_date", "data transakcji"],
    "value_date": ["data waluty", "valuedate", "value_date"],
    "amount": ["kwota", "amount", "wartość", "wartosc"],
    "currency": ["waluta", "currency"],
    "counterparty_name": ["nazwa kontrahenta", "counterparty", "counterparty_name", "odbiorca/nadawca"],
    "counterparty_account": ["nr konta kontrahenta", "counterparty_account", "konto kontrahenta"],
    "title": ["tytuł", "tytul", "title", "opis", "szczegoly", "szczegóły przelewu"],
    "external_id": ["id transakcji", "external_id", "reference", "numer transakcji"],
}


class PaymentService:
    def __init__(
        self,
        session: Session,
        bank_transaction_repository: BankTransactionRepository,
        allocation_repository: PaymentAllocationRepository,
        invoice_repository: InvoiceRepository,
        audit_service: AuditService,
        matcher: PaymentMatcher | None = None,
    ) -> None:
        self._session = session
        self._tx_repo = bank_transaction_repository
        self._alloc_repo = allocation_repository
        self._inv_repo = invoice_repository
        self._audit = audit_service
        self._matcher = matcher or PaymentMatcher()

    # -------------------------------------------------------------------------
    # Import CSV
    # -------------------------------------------------------------------------

    def import_csv(
        self,
        csv_content: str,
        source_file: str | None,
        actor: AuthenticatedUser,
    ) -> dict[str, Any]:
        """Parsuje CSV, importuje nowe rekordy (deduplikacja via external_id), uruchamia matching."""
        rows = _parse_csv(csv_content)
        imported: list[BankTransactionORM] = []
        skipped = 0

        for row in rows:
            ext_id = row.get("external_id")
            if ext_id:
                existing = self._tx_repo.get_by_external_id(ext_id)
                if existing:
                    skipped += 1
                    continue

            try:
                tx_date = _parse_date(row["transaction_date"])
                amount = Decimal(str(row["amount"]).replace(",", ".").replace(" ", ""))
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.warning("Pominięto wiersz CSV (błąd parsowania): %s – %s", row, exc)
                skipped += 1
                continue

            orm = BankTransactionORM(
                id=uuid.uuid4(),
                external_id=ext_id or None,
                transaction_date=tx_date,
                value_date=_parse_date(row.get("value_date")) if row.get("value_date") else None,
                amount=amount,
                currency=row.get("currency", "PLN").strip().upper(),
                counterparty_name=row.get("counterparty_name"),
                counterparty_account=row.get("counterparty_account"),
                title=row.get("title"),
                match_status=PaymentMatchStatus.UNMATCHED.value,
                remaining_amount=amount,
                source_file=source_file,
                raw_row_json=row,
                imported_by=to_uuid(actor.user_id),
            )
            self._tx_repo.add(orm)
            imported.append(orm)
        self._session.flush()

        # Matching poza transakcją importu (każda transakcja w osobnej)
        auto_matched = 0
        manual_review = 0
        for tx_orm in imported:
            result = self._run_matching_for_orm(tx_orm, actor)
            if result == "auto":
                auto_matched += 1
            elif result == "manual_review":
                manual_review += 1

        return {
            "imported": len(imported),
            "skipped": skipped,
            "auto_matched": auto_matched,
            "manual_review": manual_review,
        }

    # -------------------------------------------------------------------------
    # Matching
    # -------------------------------------------------------------------------

    def run_matching_for_transaction(
        self, transaction_id: UUID, actor: AuthenticatedUser
    ) -> str:
        tx_orm = self._tx_repo.get_by_id(transaction_id)
        if tx_orm is None:
            raise NotFoundError("Transakcja nie została znaleziona.")
        return self._run_matching_for_orm(tx_orm, actor) or "no_match"

    def _run_matching_for_orm(
        self, tx_orm: BankTransactionORM, actor: AuthenticatedUser
    ) -> str | None:
        """Zwraca 'auto' | 'manual_review' | None."""
        tx_candidate = TransactionCandidate(
            transaction_id=tx_orm.id,
            amount=tx_orm.amount,
            title=tx_orm.title,
            counterparty_name=tx_orm.counterparty_name,
            counterparty_account=tx_orm.counterparty_account,
        )

        # Pobierz faktury gotowe do zaakceptowania / zaakceptowane z łączną kwotą
        invoices_orm = self._inv_repo.list_all()
        invoice_candidates = [
            InvoiceCandidate(
                invoice_id=inv.id,
                invoice_number=inv.number_local or "",
                gross_amount=Decimal(str(inv.totals_json.get("total_gross", 0))),
                buyer_name=inv.buyer_snapshot_json.get("name"),
                buyer_nip=inv.buyer_snapshot_json.get("nip"),
                seller_nip=inv.seller_snapshot_json.get("nip"),
            )
            for inv in invoices_orm
        ]

        best = self._matcher.best_auto(tx_candidate, invoice_candidates)
        if best and best.score >= AUTO_MATCH_THRESHOLD:
            self._do_allocate(
                tx_orm=tx_orm,
                invoice_id=best.invoice_id,
                amount=tx_orm.remaining_amount,
                method=PaymentMatchMethod.AUTO,
                score=best.score,
                reasons=best.reasons,
                actor=actor,
            )
            self._session.flush()
            return "auto"

        # Sprawdź czy są kandydaci na manual_review
        candidates = self._matcher.find_candidates(tx_candidate, invoice_candidates)
        has_manual = any(
            MANUAL_REVIEW_THRESHOLD <= c.score < AUTO_MATCH_THRESHOLD for c in candidates
        )
        if has_manual:
            self._tx_repo.update_match_status(
                tx_orm.id,
                PaymentMatchStatus.MANUAL_REVIEW,
                tx_orm.remaining_amount,
            )
            self._session.flush()
            return "manual_review"

        return None

    # -------------------------------------------------------------------------
    # Ręczna alokacja
    # -------------------------------------------------------------------------

    def allocate_manual(
        self,
        transaction_id: UUID,
        invoice_id: UUID,
        amount: Decimal,
        actor: AuthenticatedUser,
    ) -> PaymentAllocationORM:
        tx_orm = self._tx_repo.get_by_id(transaction_id)
        if tx_orm is None:
            raise NotFoundError("Transakcja nie została znaleziona.")
        inv_orm = self._inv_repo.get_orm_by_id(invoice_id)
        if inv_orm is None:
            raise NotFoundError("Faktura nie została znaleziona.")

        if amount > tx_orm.remaining_amount:
            raise ValueError(
                f"Kwota alokacji ({amount}) przekracza pozostałe saldo transakcji "
                f"({tx_orm.remaining_amount})."
            )
        if amount <= 0:
            raise ValueError("Kwota alokacji musi być dodatnia.")

        alloc = self._do_allocate(
            tx_orm=tx_orm,
            invoice_id=invoice_id,
            amount=amount,
            method=PaymentMatchMethod.MANUAL,
            score=None,
            reasons=[],
            actor=actor,
        )
        self._session.flush()
        return alloc

    # -------------------------------------------------------------------------
    # Cofnięcie alokacji
    # -------------------------------------------------------------------------

    def reverse_allocation(
        self, allocation_id: UUID, actor: AuthenticatedUser
    ) -> None:
        alloc = self._alloc_repo.get_by_id(allocation_id)
        if alloc is None:
            raise NotFoundError("Alokacja nie została znaleziona.")

        before_alloc = {"is_reversed": alloc.is_reversed}
        self._alloc_repo.reverse(allocation_id, actor.user_id)

        # Zaktualizuj remaining_amount + match_status transakcji
        tx_orm = self._tx_repo.get_by_id(alloc.transaction_id)
        if tx_orm:
            allocated = self._alloc_repo.sum_allocated_for_transaction(tx_orm.id)
            remaining = tx_orm.amount - allocated
            match_status = self._compute_tx_match_status(tx_orm.amount, remaining)
            self._tx_repo.update_match_status(tx_orm.id, match_status, remaining)

        # Zaktualizuj payment_status faktury
        inv_orm = self._inv_repo.get_orm_by_id(alloc.invoice_id)
        if inv_orm:
            self._refresh_invoice_payment_status(inv_orm)

        self._audit.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="payment_allocation_reversed",
            entity_type="payment_allocation",
            entity_id=str(allocation_id),
            before=before_alloc,
            after={"is_reversed": True},
        )
        self._session.flush()

    # -------------------------------------------------------------------------
    # Historia płatności faktury
    # -------------------------------------------------------------------------

    def get_invoice_payment_history(
        self, invoice_id: UUID
    ) -> list[PaymentAllocationORM]:
        orm = self._inv_repo.get_orm_by_id(invoice_id)
        if orm is None:
            raise NotFoundError("Faktura nie została znaleziona.")
        return self._alloc_repo.list_for_invoice_all(invoice_id)

    # -------------------------------------------------------------------------
    # Listowanie
    # -------------------------------------------------------------------------

    def list_transactions(
        self,
        page: int = 1,
        size: int = 50,
        match_status: str | None = None,
    ) -> tuple[list[BankTransactionORM], int]:
        if match_status:
            return self._tx_repo.list_unmatched_paginated(page, size, match_status)
        return self._tx_repo.list_all_paginated(page, size)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _do_allocate(
        self,
        tx_orm: BankTransactionORM,
        invoice_id: UUID,
        amount: Decimal,
        method: PaymentMatchMethod,
        score: int | None,
        reasons: list[str],
        actor: AuthenticatedUser,
    ) -> PaymentAllocationORM:
        alloc = PaymentAllocationORM(
            id=uuid.uuid4(),
            transaction_id=tx_orm.id,
            invoice_id=invoice_id,
            allocated_amount=amount,
            match_method=method.value,
            match_score=score,
            match_reasons_json=reasons,
            is_reversed=False,
            created_by=to_uuid(actor.user_id),
        )
        self._alloc_repo.add(alloc)

        # Zaktualizuj remaining + match_status na transakcji
        allocated_total = self._alloc_repo.sum_allocated_for_transaction(tx_orm.id)
        remaining = tx_orm.amount - allocated_total
        match_status = self._compute_tx_match_status(tx_orm.amount, remaining)
        self._tx_repo.update_match_status(tx_orm.id, match_status, remaining)

        # Zaktualizuj payment_status faktury
        inv_orm = self._inv_repo.get_orm_by_id(invoice_id)
        if inv_orm:
            self._refresh_invoice_payment_status(inv_orm)

        self._audit.record(
            actor_user_id=actor.user_id,
            actor_role=actor.role,
            event_type="payment_allocated",
            entity_type="bank_transaction",
            entity_id=str(tx_orm.id),
            before={},
            after={
                "invoice_id": str(invoice_id),
                "amount": str(amount),
                "method": method.value,
                "score": score,
            },
        )
        return alloc

    def _refresh_invoice_payment_status(self, inv_orm: InvoiceORM) -> None:
        gross = Decimal(str(inv_orm.totals_json.get("total_gross", 0)))
        allocated = self._alloc_repo.sum_allocated_for_invoice(inv_orm.id)
        if gross <= 0:
            new_status = InvoicePaymentStatus.UNPAID
        elif allocated >= gross:
            new_status = InvoicePaymentStatus.PAID
        elif allocated > 0:
            new_status = InvoicePaymentStatus.PARTIALLY_PAID
        else:
            new_status = InvoicePaymentStatus.UNPAID
        inv_orm.payment_status = new_status.value
        self._session.flush()

    @staticmethod
    def _compute_tx_match_status(
        amount: Decimal, remaining: Decimal
    ) -> PaymentMatchStatus:
        if remaining <= 0:
            return PaymentMatchStatus.MATCHED
        if remaining < amount:
            return PaymentMatchStatus.PARTIAL
        return PaymentMatchStatus.UNMATCHED


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _parse_csv(content: str) -> list[dict[str, str]]:
    """Parsuje CSV z automatycznym wykryciem separatora i mapowaniem kolumn."""
    # Wykryj separator
    sample = content[:2048]
    sep = ";" if sample.count(";") >= sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(content), delimiter=sep)
    if reader.fieldnames is None:
        return []

    col_map = _build_column_map(list(reader.fieldnames))
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        mapped: dict[str, str] = {}
        for canonical, aliases in _CSV_COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in col_map:
                    mapped[canonical] = (raw_row.get(col_map[alias]) or "").strip()
                    break
        if mapped:
            rows.append(mapped)
    return rows


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Zwraca {lowercase_alias: original_fieldname}."""
    result: dict[str, str] = {}
    for name in fieldnames:
        if name:
            result[name.strip().lower()] = name
    return result


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Nierozpoznany format daty: {val!r}")
