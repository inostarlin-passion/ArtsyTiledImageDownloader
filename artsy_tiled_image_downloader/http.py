from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import DownloaderSettings


def create_async_client(
    settings: DownloaderSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=settings.concurrency + 4,
        max_keepalive_connections=settings.concurrency + 4,
    )
    timeout = httpx.Timeout(
        settings.timeout,
        connect=min(max(settings.timeout, 5.0), 30.0),
        pool=settings.timeout,
    )
    return httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
        http2=True,
        transport=transport,
    )


def is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    settings: DownloaderSettings,
    **kwargs: Any,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(settings.retries):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if not is_retryable_status(exc.response.status_code):
                raise
        except httpx.TransportError as exc:
            last_error = exc

        if attempt == settings.retries - 1:
            break
        await asyncio.sleep(min(0.5 * (2**attempt), 5.0))

    assert last_error is not None
    raise last_error
