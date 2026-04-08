from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_settings_service
from app.core.security import AuthenticatedUser
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/", response_model=SettingsResponse)
def get_settings(
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SettingsResponse:
    """Zwraca aktualne ustawienia aplikacji.

    Priorytet: wartości z bazy danych (nadpisane przez PUT) → zmienne
    środowiskowe (SELLER_NIP itp.) jako fallback.
    """
    data = settings_service.get_settings()
    return SettingsResponse(**data)


@router.put("/", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SettingsResponse:
    """Aktualizuje ustawienia sprzedawcy.

    Przesyłaj tylko pola do zmiany — reszta pozostaje bez zmian (partial update).
    Pola read-only (ksef_environment, app_env, app_version) są ignorowane.
    """
    payload = body.model_dump(exclude_none=True)
    data = settings_service.update_settings(payload)
    return SettingsResponse(**data)
