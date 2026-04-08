from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, get_stock_service
from app.core.security import AuthenticatedUser
from app.domain.models.stock import MovementType
from app.schemas.stock import (
    ProductCreateRequest,
    ProductResponse,
    StockListResponse,
    StockMovementCreateRequest,
    StockMovementListResponse,
    StockMovementResponse,
    StockResponse,
)
from app.services.stock_service import StockService

router = APIRouter(prefix="/stock", tags=["stock"])


# ── Products ──────────────────────────────────────────────────────────────────

@router.post("/products", response_model=ProductResponse, status_code=201)
def create_product(
    body: ProductCreateRequest,
    stock_service: Annotated[StockService, Depends(get_stock_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> ProductResponse:
    product = stock_service.create_product(name=body.name, isbn=body.isbn, unit=body.unit)
    return ProductResponse.from_domain(product)


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    stock_service: Annotated[StockService, Depends(get_stock_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> list[ProductResponse]:
    return [ProductResponse.from_domain(p) for p in stock_service.list_products()]


# ── Stock ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=StockListResponse)
def list_stock(
    warehouse_id: UUID | None = Query(default=None),
    stock_service: Annotated[StockService, Depends(get_stock_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> StockListResponse:
    items = stock_service.list_stock(warehouse_id=warehouse_id)
    return StockListResponse(
        items=[StockResponse.from_domain(s) for s in items],
        total=len(items),
    )


# ── Movements ─────────────────────────────────────────────────────────────────

@router.post("/movement", response_model=StockMovementResponse, status_code=201)
def create_movement(
    body: StockMovementCreateRequest,
    stock_service: Annotated[StockService, Depends(get_stock_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> StockMovementResponse:
    movement = stock_service.create_movement(
        movement_type=body.movement_type,
        product_id=body.product_id,
        quantity=body.quantity,
        warehouse_id=body.warehouse_id,
        note=body.note,
    )
    return StockMovementResponse.from_domain(movement)


@router.get("/history", response_model=StockMovementListResponse)
def list_movements(
    product_id: UUID | None = Query(default=None),
    warehouse_id: UUID | None = Query(default=None),
    invoice_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    stock_service: Annotated[StockService, Depends(get_stock_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> StockMovementListResponse:
    items = stock_service.list_movements(
        product_id=product_id,
        warehouse_id=warehouse_id,
        invoice_id=invoice_id,
        limit=limit,
        offset=offset,
    )
    return StockMovementListResponse(
        items=[StockMovementResponse.from_domain(m) for m in items],
        total=len(items),
    )
