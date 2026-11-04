from __future__ import annotations

import asyncio
import email.utils
import math
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import DownloaderSettings
from .exceptions import DownloadError, ResponseTooLargeError


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
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
                    return min(max(seconds, 0.0), 30.0)
            else:
                if math.isfinite(seconds):
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


def _declared_content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError:
        return None
    return length if length >= 0 else None


@asynccontextmanager
async def _stream_response(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    auth: Any,
    follow_redirects: bool,
) -> AsyncIterator[httpx.Response]:
    # HTTPX drains intermediate redirect responses when following automatically.
    response = await client.send(
        request, auth=auth, stream=True, follow_redirects=False
    )
    for _ in range(client.max_redirects):
        next_request = response.next_request
        if not follow_redirects or next_request is None:
            break
        await response.aclose()
        response = await client.send(
            next_request, auth=None, stream=True, follow_redirects=False
        )
    try:
        if follow_redirects and response.next_request is not None:
            raise httpx.TooManyRedirects(
                "Exceeded maximum allowed redirects.", request=response.request
            )
        yield response
    finally:
        await response.aclose()


async def request_bytes_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    settings: DownloaderSettings,
    *,
    max_bytes: int,
    **kwargs: Any,
) -> bytes:
    """Stream a bounded response body while retaining the standard retry policy."""
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes <= 0
    ):
        raise ValueError("max_bytes must be greater than 0")

    auth = kwargs.pop("auth", httpx.USE_CLIENT_DEFAULT)
    follow_redirects = kwargs.pop("follow_redirects", httpx.USE_CLIENT_DEFAULT)
    if follow_redirects is httpx.USE_CLIENT_DEFAULT:
        follow_redirects = client.follow_redirects
    last_error: Exception | None = None

    for attempt in range(settings.retries):
        retry_response: httpx.Response | None = None
        try:
            request = client.build_request(method, url, **kwargs)
            request.headers["Accept-Encoding"] = "identity"
            async with _stream_response(
                client, request, auth=auth, follow_redirects=follow_redirects
            ) as response:
                response.raise_for_status()

                declared_length = _declared_content_length(response)
                if declared_length is not None and declared_length > max_bytes:
                    raise ResponseTooLargeError(
                        f"response from {url} declares {declared_length} bytes, "
                        f"above limit {max_bytes}"
                    )

                encoding = response.headers.get("Content-Encoding", "identity")
                if encoding.strip().lower() != "identity":
                    raise DownloadError(f"unsupported Content-Encoding: {encoding}")

                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise ResponseTooLargeError(
                            f"response from {url} exceeds byte limit {max_bytes}"
                        )
                    content.extend(chunk)
                return bytes(content)
        except ResponseTooLargeError:
            raise
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
