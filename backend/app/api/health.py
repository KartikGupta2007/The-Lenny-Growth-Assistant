"""Health endpoint.

Reports application liveness plus the status of each dependency the request
path *requires*, per architecture.md section 19.

Model providers are deliberately not probed here. Health is polled by
orchestrators and by the frontend on load, and it must stay fast and
deterministic; provider reachability is a capability question, answered by
``GET /api/providers``. A missing Ollama daemon makes one model unselectable,
not the application unhealthy.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.config import get_settings
from app.constants import HTTP_SERVICE_UNAVAILABLE, ROUTE_HEALTH, TAG_HEALTH
from app.db.session import check_database

router = APIRouter(tags=[TAG_HEALTH])


class DependencyStatus(BaseModel):
    """Status of a single downstream dependency."""

    name: str
    healthy: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    """Overall application health."""

    status: Literal["ok", "degraded"]
    environment: str
    version: str
    dependencies: list[DependencyStatus]


@router.get(ROUTE_HEALTH, response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """Return application and dependency health.

    Returns 200 when every required dependency is reachable and 503 when the
    database is not, so that a container orchestrator or the frontend can
    distinguish "up" from "up but unusable".
    """
    settings = get_settings()

    db_healthy, db_detail = await check_database()
    dependencies = [
        DependencyStatus(name="database", healthy=db_healthy, detail=db_detail)
    ]

    status: Literal["ok", "degraded"] = "ok" if db_healthy else "degraded"
    if status == "degraded":
        response.status_code = HTTP_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=status,
        environment=settings.app_env,
        version=settings.app_version,
        dependencies=dependencies,
    )
