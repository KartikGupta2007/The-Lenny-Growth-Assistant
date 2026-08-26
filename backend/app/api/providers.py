"""Model provider discovery -- what the frontend's model selector renders.

Returns every provider the application knows about, each with its own
selectability, so the UI can show a disabled option with an explanation
instead of one that quietly vanishes when the app is deployed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.constants import ROUTE_PROVIDERS, LLMProviderId
from app.models.base import ProviderStatus
from app.models.registry import ProviderRegistry, get_provider_registry

router = APIRouter(tags=["providers"])


class ProvidersResponse(BaseModel):
    providers: list[ProviderStatus]
    # None when nothing is usable; the UI then blocks sending.
    default: LLMProviderId | None


@router.get(ROUTE_PROVIDERS, response_model=ProvidersResponse)
async def list_providers(
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> ProvidersResponse:
    return ProvidersResponse(
        providers=await registry.statuses(),
        default=await registry.default_provider_id(),
    )
