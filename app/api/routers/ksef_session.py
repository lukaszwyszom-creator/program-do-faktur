"""Endpointy zarządzania sesją KSeF."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_ksef_session_service
from app.core.security import AuthenticatedUser
from app.schemas.ksef_session import (
    CloseSessionResponse,
    KSeFSessionResponse,
    OpenSessionRequest,
)
from app.services.ksef_session_service import KSeFSessionService

router = APIRouter(prefix="/ksef/session", tags=["ksef-session"])


@router.post("/open", response_model=KSeFSessionResponse, status_code=201)
def open_session(
    body: OpenSessionRequest,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> KSeFSessionResponse:
    """Otwiera nową sesję KSeF (challenge → init token)."""
    orm = ksef_session_service.open_session(
        nip=body.nip,
        actor_user_id=current_user.user_id,
    )
    return KSeFSessionResponse.model_validate(orm)


@router.delete("/close", response_model=CloseSessionResponse)
def close_session(
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CloseSessionResponse:
    """Zamyka aktywną sesję KSeF."""
    orm = ksef_session_service.close_session(actor_user_id=current_user.user_id)
    return CloseSessionResponse.model_validate(orm)


@router.get("/active", response_model=KSeFSessionResponse)
def get_active_session(
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> KSeFSessionResponse:
    """Zwraca aktywną sesję KSeF."""
    orm = ksef_session_service.get_active_session()
    return KSeFSessionResponse.model_validate(orm)


@router.get("/{session_id}", response_model=KSeFSessionResponse)
def get_session_by_id(
    session_id: UUID,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> KSeFSessionResponse:
    """Pobiera sesję KSeF po ID."""
    orm = ksef_session_service.get_session_by_id(session_id)
    return KSeFSessionResponse.model_validate(orm)
