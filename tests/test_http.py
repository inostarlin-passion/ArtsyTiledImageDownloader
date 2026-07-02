from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

import artsy_tiled_image_downloader.http as http_module
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.http import create_async_client, request_with_retries


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
