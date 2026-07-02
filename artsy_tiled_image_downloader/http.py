from __future__ import annotations

import asyncio
import email.utils
import random
from datetime import UTC, datetime
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
        connect=min(settings.timeout, 30.0),
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


def retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                try:
                    parsed = email.utils.parsedate_to_datetime(retry_after)
                except (TypeError, ValueError, IndexError, OverflowError):
                    pass
                else:
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    seconds = (parsed - datetime.now(UTC)).total_seconds()
                    return min(max(seconds, 0.0), 30.0)
            else:
                return min(max(seconds, 0.0), 30.0)

    base_delay = min(0.5 * (2**attempt), 5.0)
    return base_delay + random.uniform(0.0, 0.1)


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    settings: DownloaderSettings,
    **kwargs: Any,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(settings.retries):
        retry_response: httpx.Response | None = None
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            retry_response = exc.response
            if not is_retryable_status(exc.response.status_code):
                raise
        except httpx.TransportError as exc:
            last_error = exc

        if attempt == settings.retries - 1:
            break
        await asyncio.sleep(retry_delay(attempt, retry_response))

    assert last_error is not None
    raise last_error
