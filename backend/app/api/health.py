"""Health endpoint.

Model providers are deliberately not probed here: health is polled constantly
and must stay fast, and a missing Ollama daemon makes one model unselectable,
not the application unhealthy. That question is answered by GET /api/providers.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.config import get_settings
from app.constants import ROUTE_HEALTH
from app.db.session import check_database

router = APIRouter(tags=["health"])


class DependencyStatus(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    version: str
    dependencies: list[DependencyStatus]


@router.get(ROUTE_HEALTH, response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """200 when every required dependency is reachable, 503 when not."""
    settings = get_settings()

    db_healthy, db_detail = await check_database()
    status: Literal["ok", "degraded"] = "ok" if db_healthy else "degraded"
    if not db_healthy:
        response.status_code = 503

    return HealthResponse(
        status=status,
        environment=settings.app_env,
        version=settings.app_version,
        dependencies=[
            DependencyStatus(name="database", healthy=db_healthy, detail=db_detail)
        ],
    )
