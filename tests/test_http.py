from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

import artsy_tiled_image_downloader.http as http_module
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.exceptions import ResponseTooLargeError
from artsy_tiled_image_downloader.http import (
    create_async_client,
    request_bytes_with_retries,
    request_with_retries,
)


def test_request_with_retries_honors_retry_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = DownloaderSettings(output_dir=tmp_path, retries=2)
    sleeps: list[float] = []
    attempts = 0

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.25"},
                request=request,
            )
        return httpx.Response(200, request=request)

    async def run() -> None:
        monkeypatch.setattr(http_module.asyncio, "sleep", fake_sleep)
        transport = httpx.MockTransport(handler)
        async with create_async_client(settings, transport=transport) as client:
            response = await request_with_retries(
                client,
                "GET",
                "https://example.test/image.png",
                settings,
            )
        assert response.status_code == 200

    asyncio.run(run())

    assert sleeps == [0.25]
    assert attempts == 2


def test_create_async_client_connect_timeout_does_not_exceed_setting(
    tmp_path: Path,
) -> None:
    settings = DownloaderSettings(output_dir=tmp_path, timeout=1.5)
    client = create_async_client(settings)
    try:
        assert client.timeout.connect == 1.5
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("declared_length", [True, False])
def test_request_bytes_rejects_response_above_limit(
    tmp_path: Path,
    declared_length: bool,
) -> None:
    settings = DownloaderSettings(output_dir=tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"Content-Length": "4"} if declared_length else {}
        return httpx.Response(200, headers=headers, content=b"data", request=request)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with create_async_client(settings, transport=transport) as client:
            with pytest.raises(ResponseTooLargeError, match="limit 3"):
                await request_bytes_with_retries(
                    client,
                    "GET",
                    "https://example.test/tile.png",
                    settings,
                    max_bytes=3,
                )

    asyncio.run(run())


def test_retry_delay_handles_http_date_invalid_and_nan_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_module.random, "uniform", lambda *_: 0.0)

    future = httpx.Response(
        503,
        headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"},
    )
    invalid = httpx.Response(503, headers={"Retry-After": "invalid"})
    nan = httpx.Response(503, headers={"Retry-After": "nan"})

    assert http_module.retry_delay(0, future) == 30.0
    assert http_module.retry_delay(1, invalid) == 1.0
    assert http_module.retry_delay(1, nan) == 1.0


def test_requests_do_not_retry_non_transient_status(tmp_path: Path) -> None:
    settings = DownloaderSettings(output_dir=tmp_path, retries=3)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with create_async_client(settings, transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await request_with_retries(
                    client,
                    "GET",
                    "https://example.test/missing",
                    settings,
                )

    asyncio.run(run())
    assert attempts == 1


def test_streamed_bytes_retry_then_succeed(tmp_path: Path) -> None:
    settings = DownloaderSettings(output_dir=tmp_path, retries=2)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with create_async_client(settings, transport=transport) as client:
            content = await request_bytes_with_retries(
                client,
                "GET",
                "https://example.test/tile",
                settings,
                max_bytes=2,
            )
        assert content == b"ok"

    asyncio.run(run())
    assert attempts == 2


@pytest.mark.parametrize("max_bytes", [True, 0, "3"])
def test_streamed_bytes_validate_limit_type(tmp_path: Path, max_bytes: object) -> None:
    settings = DownloaderSettings(output_dir=tmp_path)

    async def run() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200))
        async with create_async_client(settings, transport=transport) as client:
            with pytest.raises(ValueError, match="greater than 0"):
                await request_bytes_with_retries(
                    client,
                    "GET",
                    "https://example.test/tile",
                    settings,
                    max_bytes=max_bytes,
                )

    asyncio.run(run())
