"""Shared outbound HTTP client.

One pooled client so repeated calls to Ollama do not pay a new connection
each time. Closed on application shutdown by the lifespan handler.
"""

from __future__ import annotations

from functools import lru_cache

import httpx

from app.config import get_settings
from app.constants import APP_NAME


@lru_cache(maxsize=1)
def get_http_client() -> httpx.AsyncClient:
    settings = get_settings()
    limits = httpx.Limits(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_connections // 2 or 1,
    )
    return httpx.AsyncClient(
        limits=limits,
        timeout=httpx.Timeout(settings.provider_probe_timeout_seconds),
        follow_redirects=True,
        headers={"user-agent": f"{APP_NAME}/{settings.app_version}"},
    )


async def close_http_client() -> None:
    if get_http_client.cache_info().currsize:
        await get_http_client().aclose()
        get_http_client.cache_clear()
