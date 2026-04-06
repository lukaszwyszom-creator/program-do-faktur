"""Router modułu płatności.

Endpoints:
  POST   /payments/import                    – import CSV z przelewami
  GET    /payments/transactions              – lista transakcji (z filtrowaniem)
  POST   /payments/transactions/{id}/match   – ponów matching dla transakcji
  POST   /payments/transactions/{id}/allocate – ręczna alokacja do faktury
  DELETE /payments/allocations/{id}          – cofnięcie alokacji
  GET    /payments/invoice/{id}/history      – historia płatności faktury
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status

from app.api.deps import get_current_user, get_payment_service
from app.core.exceptions import NotFoundError
from app.core.security import AuthenticatedUser
from app.schemas.payment import (
    BankTransactionResponse,
    ImportResultResponse,
    ManualAllocateRequest,
    PaymentAllocationResponse,
    TransactionListResponse,
)
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post(
    "/import",
    response_model=ImportResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Importuj przelewy z pliku CSV",
)
async def import_transactions(
    file: UploadFile,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> ImportResultResponse:
    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("windows-1250", errors="replace")

    result = payment_service.import_csv(
        csv_content=content,
        source_file=file.filename,
        actor=current_user,
    )
    return ImportResultResponse(**result)


# ---------------------------------------------------------------------------
# Lista transakcji
# ---------------------------------------------------------------------------

@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    summary="Lista transakcji bankowych",
)
def list_transactions(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    match_status: str | None = Query(None, description="Filtr statusu dopasowania"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> TransactionListResponse:
    rows, total = payment_service.list_transactions(
        page=page, size=size, match_status=match_status
    )
    return TransactionListResponse(
        items=[BankTransactionResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


# ---------------------------------------------------------------------------
# Ponów matching
# ---------------------------------------------------------------------------

@router.post(
    "/transactions/{transaction_id}/match",
    response_model=dict,
    summary="Uruchom ponownie matching dla transakcji",
)
def rematch_transaction(
    transaction_id: UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> dict:
    try:
        outcome = payment_service.run_matching_for_transaction(transaction_id, current_user)
        return {"transaction_id": str(transaction_id), "outcome": outcome}
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Ręczna alokacja
# ---------------------------------------------------------------------------

@router.post(
    "/transactions/{transaction_id}/allocate",
    response_model=PaymentAllocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ręcznie przypisz przelew do faktury",
)
def allocate_manual(
    transaction_id: UUID,
    body: ManualAllocateRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentAllocationResponse:
    try:
        alloc = payment_service.allocate_manual(
            transaction_id=transaction_id,
            invoice_id=body.invoice_id,
            amount=body.amount,
            actor=current_user,
        )
        return PaymentAllocationResponse.from_orm_with_tx(alloc)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


# ---------------------------------------------------------------------------
# Cofnięcie alokacji
# ---------------------------------------------------------------------------

@router.delete(
    "/allocations/{allocation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cofnij alokację przelewu",
)
def reverse_allocation(
    allocation_id: UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> None:
    try:
        payment_service.reverse_allocation(allocation_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


# ---------------------------------------------------------------------------
# Historia płatności faktury
# ---------------------------------------------------------------------------

@router.get(
    "/invoice/{invoice_id}/history",
    response_model=list[PaymentAllocationResponse],
    summary="Historia płatności faktury",
)
def invoice_payment_history(
    invoice_id: UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> list[PaymentAllocationResponse]:
    try:
        allocs = payment_service.get_invoice_payment_history(invoice_id)
        return [PaymentAllocationResponse.from_orm_with_tx(a) for a in allocs]
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
