"""Shared outbound HTTP client.

Every outbound call (Ollama, embedding providers, transcript sync) reuses one
``httpx.AsyncClient`` so that connections are pooled rather than a new TLS
handshake being paid per request. The client is closed on application shutdown
by the lifespan handler in ``app.main``.

No default timeout is set globally beyond a conservative ceiling: each caller
passes the timeout appropriate to its operation, because a 3-second provider
probe and a 180-second local generation have very different expectations.
"""

from __future__ import annotations

from functools import lru_cache

import httpx

from app.config import get_settings
from app.constants import USER_AGENT_TEMPLATE


@lru_cache(maxsize=1)
def get_http_client() -> httpx.AsyncClient:
    """Return the process-wide async HTTP client."""
    settings = get_settings()
    limits = httpx.Limits(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_connections // 2 or 1,
    )
    return httpx.AsyncClient(
        limits=limits,
        timeout=httpx.Timeout(settings.provider_probe_timeout_seconds),
        follow_redirects=True,
        headers={
            "user-agent": USER_AGENT_TEMPLATE.format(version=settings.app_version)
        },
    )


async def close_http_client() -> None:
    """Close the shared client and drop the cached instance."""
    if get_http_client.cache_info().currsize:
        await get_http_client().aclose()
        get_http_client.cache_clear()
