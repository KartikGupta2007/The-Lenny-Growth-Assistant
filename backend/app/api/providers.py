"""Model provider discovery.

``GET /api/providers`` is what the model selector renders. It returns *every*
provider the application knows about, each carrying its own selectability, so
the UI can show a disabled option with an explanation instead of an option
that quietly vanishes when the app is deployed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.constants import ROUTE_PROVIDERS, TAG_PROVIDERS, LLMProviderId
from app.models.base import ProviderStatus
from app.models.registry import ProviderRegistry, get_provider_registry

router = APIRouter(tags=[TAG_PROVIDERS])


class ProvidersResponse(BaseModel):
    """Providers plus the one a new conversation should start on."""

    providers: list[ProviderStatus]
    # ``None`` when no provider is usable; the UI then blocks sending rather
    # than pre-selecting a model that cannot answer.
    default: LLMProviderId | None


@router.get(ROUTE_PROVIDERS, response_model=ProvidersResponse)
async def list_providers(
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> ProvidersResponse:
    """List model providers and their current selectability."""
    statuses = await registry.statuses()
    return ProvidersResponse(
        providers=statuses,
        default=await registry.default_provider_id(),
    )
