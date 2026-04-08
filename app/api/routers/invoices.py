from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import HTMLResponse, Response

from app.api.deps import get_current_user, get_idempotency_service, get_invoice_service
from app.core.exceptions import ConflictError
from app.core.security import AuthenticatedUser
from app.domain.exceptions import InvalidInvoiceError, InvalidStatusTransitionError
from app.schemas.invoice import InvoiceCreateRequest, InvoiceListResponse, InvoiceResponse
from app.services.idempotency_service import DuplicateRequestError, IdempotencyService
from app.services.invoice_service import InvoiceService
from app.services.pdf_service import render_invoice_html, render_invoice_pdf

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("/", response_model=InvoiceListResponse)
def list_invoices(
    status: str | None = Query(default=None),
    issue_date_from: date | None = Query(default=None),
    issue_date_to: date | None = Query(default=None),
    number_filter: str | None = Query(default=None),
    direction: str | None = Query(default=None, pattern="^(sale|purchase)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> InvoiceListResponse:
    items, total = invoice_service.list_invoices(
        status=status,
        page=page,
        size=size,
        issue_date_from=issue_date_from,
        issue_date_to=issue_date_to,
        number_filter=number_filter,
        direction=direction,
    )
    return InvoiceListResponse(
        items=[InvoiceResponse.from_domain(i) for i in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: UUID,
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> InvoiceResponse:
    invoice = invoice_service.get_invoice(invoice_id)
    return InvoiceResponse.from_domain(invoice)


@router.post("/", response_model=InvoiceResponse, status_code=201)
def create_invoice(
    body: InvoiceCreateRequest,
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)] = ...,
    idempotency_service: Annotated[IdempotencyService, Depends(get_idempotency_service)] = ...,
    actor: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> InvoiceResponse:
    scope = "create_invoice"

    if idempotency_key:
        cached = idempotency_service.acquire(scope, idempotency_key, body.model_dump())
        if cached is not None:
            return cached

    try:
        invoice = invoice_service.create_invoice(body.model_dump(), actor)
        response = InvoiceResponse.from_domain(invoice)

        if idempotency_key:
            idempotency_service.complete(
                scope,
                idempotency_key,
                entity_type="invoice",
                entity_id=str(invoice.id),
                response_snapshot=response.model_dump(mode="json"),
            )

        return response

    except (InvalidInvoiceError, DuplicateRequestError):
        if idempotency_key:
            idempotency_service.fail(scope, idempotency_key)
        raise


@router.post("/{invoice_id}/mark-ready", response_model=InvoiceResponse)
def mark_invoice_as_ready(
    invoice_id: UUID,
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)] = ...,
    actor: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> InvoiceResponse:
    invoice = invoice_service.mark_as_ready(invoice_id, actor)
    return InvoiceResponse.from_domain(invoice)


@router.get("/{invoice_id}/preview", response_class=HTMLResponse)
def get_invoice_preview(
    invoice_id: UUID,
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> HTMLResponse:
    """Podgląd HTML faktury — otwierany w nowej karcie, gotowy do druku (Ctrl+P)."""
    invoice = invoice_service.get_invoice(invoice_id)
    schema = InvoiceResponse.from_domain(invoice)
    html = render_invoice_html(schema)
    return HTMLResponse(content=html)


@router.get("/{invoice_id}/pdf")
def get_invoice_pdf(
    invoice_id: UUID,
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> Response:
    """Pobierz fakturę jako plik PDF (application/pdf)."""
    invoice = invoice_service.get_invoice(invoice_id)
    schema = InvoiceResponse.from_domain(invoice)
    pdf_bytes = render_invoice_pdf(schema)
    filename = f"faktura-{schema.number_local or schema.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

