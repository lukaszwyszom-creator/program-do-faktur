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

# Alias REST-owy: /ksef-sessions/  (bardziej idiomatyczny URL)
router_sessions = APIRouter(prefix="/ksef-sessions", tags=["ksef-session"])


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


@router_sessions.post(
    "/",
    response_model=KSeFSessionResponse,
    status_code=201,
    summary="Utwórz sesję KSeF",
    description="Inicjalizuje sesję KSeF dla podanego NIP sprzedawcy "
                "(challenge → init token). Wymaga KSEF_AUTH_TOKEN w .env.",
)
def create_session(
    body: OpenSessionRequest,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> KSeFSessionResponse:
    """POST /api/v1/ksef-sessions/ — alias dla /ksef/session/open."""
    orm = ksef_session_service.open_session(
        nip=body.nip,
        actor_user_id=current_user.user_id,
    )
    return KSeFSessionResponse.model_validate(orm)


@router_sessions.get(
    "/active",
    response_model=KSeFSessionResponse,
    summary="Aktywna sesja KSeF",
)
def get_active_session_v2(
    nip: str,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> KSeFSessionResponse:
    """GET /api/v1/ksef-sessions/active?nip=... — aktywna sesja dla NIP."""
    orm = ksef_session_service.get_active_session(nip)
    return KSeFSessionResponse.model_validate(orm)


@router_sessions.delete(
    "/",
    response_model=CloseSessionResponse,
    summary="Zamknij sesję KSeF",
)
def close_session_v2(
    nip: str,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CloseSessionResponse:
    """DELETE /api/v1/ksef-sessions/?nip=... — zamknij aktywną sesję."""
    orm = ksef_session_service.close_session(nip=nip, actor_user_id=current_user.user_id)
    return CloseSessionResponse.model_validate(orm)


@router.delete("/close", response_model=CloseSessionResponse)
def close_session(
    nip: str,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CloseSessionResponse:
    """Zamyka aktywną sesję KSeF dla danego NIP."""
    orm = ksef_session_service.close_session(nip=nip, actor_user_id=current_user.user_id)
    return CloseSessionResponse.model_validate(orm)


@router.get("/active", response_model=KSeFSessionResponse)
def get_active_session(
    nip: str,
    ksef_session_service: Annotated[KSeFSessionService, Depends(get_ksef_session_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> KSeFSessionResponse:
    """Zwraca aktywną sesję KSeF dla danego NIP."""
    orm = ksef_session_service.get_active_session(nip)
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
