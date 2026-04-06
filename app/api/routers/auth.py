from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_auth_service
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
	payload: LoginRequest,
	auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
	return auth_service.login(payload.username, payload.password)
