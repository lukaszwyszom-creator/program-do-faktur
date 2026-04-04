from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_contractor_service, get_current_user
from app.core.security import AuthenticatedUser
from app.schemas.contractor import ContractorOverrideRequest, ContractorResponse
from app.services.contractor_service import ContractorService

router = APIRouter(prefix="/contractors", tags=["contractors"])


@router.get("/by-nip/{nip}", response_model=ContractorResponse)
def get_contractor_by_nip(
	nip: str,
	contractor_service: Annotated[ContractorService, Depends(get_contractor_service)],
	current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ContractorResponse:
	return ContractorResponse.model_validate(contractor_service.get_by_nip(nip=nip, actor=current_user))


@router.post("/refresh/{nip}", response_model=ContractorResponse)
def refresh_contractor_by_nip(
	nip: str,
	contractor_service: Annotated[ContractorService, Depends(get_contractor_service)],
	current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ContractorResponse:
	return ContractorResponse.model_validate(contractor_service.get_by_nip(nip=nip, actor=current_user, force_refresh=True))


@router.patch("/{contractor_id}/override", response_model=ContractorResponse)
def update_contractor_override(
	contractor_id: UUID,
	payload: ContractorOverrideRequest,
	contractor_service: Annotated[ContractorService, Depends(get_contractor_service)],
	current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ContractorResponse:
	return ContractorResponse.model_validate(
		contractor_service.update_override(
			contractor_id=contractor_id,
			override_data=payload.model_dump(exclude_unset=True),
			actor=current_user,
		)
	)
