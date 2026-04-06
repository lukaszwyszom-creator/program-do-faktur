from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_transmission_service
from app.core.security import AuthenticatedUser
from app.domain.enums import TransmissionStatus
from app.schemas.transmission import (
    KSeFStatusResponse,
    RetryTransmissionResponse,
    SubmitInvoiceResponse,
    TransmissionListResponse,
    TransmissionResponse,
)
from app.services.transmission_service import TransmissionService

router = APIRouter(prefix="/transmissions", tags=["transmissions"])

_TERMINAL_STATUSES = {TransmissionStatus.SUCCESS, TransmissionStatus.FAILED_PERMANENT}


@router.post("/submit/{invoice_id}", response_model=SubmitInvoiceResponse, status_code=202)
def submit_invoice(
    invoice_id: UUID,
    transmission_service: Annotated[TransmissionService, Depends(get_transmission_service)] = ...,
    actor: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> SubmitInvoiceResponse:
    transmission = transmission_service.submit_invoice(invoice_id, actor)
    return SubmitInvoiceResponse(
        transmission_id=transmission.id,
        invoice_id=invoice_id,
        status=transmission.status,
    )


@router.post("/{transmission_id}/retry", response_model=RetryTransmissionResponse)
def retry_transmission(
    transmission_id: UUID,
    transmission_service: Annotated[TransmissionService, Depends(get_transmission_service)] = ...,
    actor: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> RetryTransmissionResponse:
    transmission = transmission_service.retry_transmission(transmission_id, actor)
    return RetryTransmissionResponse(
        transmission_id=transmission.id,
        attempt_no=transmission.attempt_no,
        status=transmission.status,
    )


@router.get("/{transmission_id}/ksef-status", response_model=KSeFStatusResponse)
def get_ksef_status(
    transmission_id: UUID,
    transmission_service: Annotated[TransmissionService, Depends(get_transmission_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> KSeFStatusResponse:
    """Zwięzły widok wyniku integracji KSeF.

    Numer KSeF jest finalny wyłącznie gdy ``is_final=True`` i ``status='success'``.
    Gdy ``upo_status`` jest ``null``, UPO nie zostało jeszcze pobrane lub transmisja
    nie osiągnęła statusu success.
    """
    transmission = transmission_service.get_transmission(transmission_id)
    status_value = transmission.status.value if hasattr(transmission.status, "value") else transmission.status
    return KSeFStatusResponse(
        transmission_id=transmission.id,
        invoice_id=transmission.invoice_id,
        status=status_value,
        ksef_reference_number=transmission.ksef_reference_number,
        upo_status=transmission.upo_status,
        is_final=status_value in {s.value for s in _TERMINAL_STATUSES},
    )


@router.get("/{transmission_id}", response_model=TransmissionResponse)
def get_transmission(
    transmission_id: UUID,
    transmission_service: Annotated[TransmissionService, Depends(get_transmission_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> TransmissionResponse:
    transmission = transmission_service.get_transmission(transmission_id)
    return TransmissionResponse.model_validate(transmission)


@router.get("/invoice/{invoice_id}", response_model=TransmissionListResponse)
def list_transmissions_for_invoice(
    invoice_id: UUID,
    transmission_service: Annotated[TransmissionService, Depends(get_transmission_service)] = ...,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)] = ...,
) -> TransmissionListResponse:
    transmissions = transmission_service.list_for_invoice(invoice_id)
    return TransmissionListResponse(
        items=[TransmissionResponse.model_validate(t) for t in transmissions],
        invoice_id=invoice_id,
    )

