from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

import artsy_tiled_image_downloader.download as download_module
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.download import DownloadResult
from artsy_tiled_image_downloader.models import ImageMetadata

pytestmark = pytest.mark.integration


def _metadata() -> ImageMetadata:
    return ImageMetadata(
        index=0,
        title="api-test",
        format="png",
        url="https://tiles.example/0/",
        tile_size=1,
        overlap=0,
        width=1,
        height=1,
        max_zoom_level=0,
    )


class _ClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *args: object) -> None:
        return None


def test_download_artwork_supports_supplied_and_managed_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _metadata()
    settings = DownloaderSettings(output_dir=tmp_path)
    transport = httpx.MockTransport(lambda _: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport)
    seen_clients: list[httpx.AsyncClient] = []

    async def fake_fetch(*args: object, **kwargs: object) -> list[ImageMetadata]:
        return [metadata]

    async def fake_download(
        used_client: httpx.AsyncClient,
        image_metadata: ImageMetadata,
        used_settings: DownloaderSettings,
        **kwargs: object,
    ) -> DownloadResult:
        del used_settings, kwargs
        seen_clients.append(used_client)
        return DownloadResult(tmp_path / "output.png", "tiles", image_metadata)

    monkeypatch.setattr(download_module, "fetch_metadatas", fake_fetch)
    monkeypatch.setattr(download_module, "download_image", fake_download)
    monkeypatch.setattr(
        download_module,
        "create_async_client",
        lambda _: _ClientContext(client),
    )

    async def run() -> None:
        supplied = await download_module.download_artwork(
            "api-test",
            settings,
            client=client,
        )
        managed = await download_module.download_artwork("api-test", settings)
        assert supplied[0].method == "tiles"
        assert managed[0].method == "tiles"

    try:
        asyncio.run(run())
    finally:
        asyncio.run(client.aclose())

    assert seen_clients == [client, client]


def test_download_full_image_sync_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _metadata()
    settings = DownloaderSettings(output_dir=tmp_path)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    )

    async def fake_download(*args: object, **kwargs: object) -> DownloadResult:
        return DownloadResult(tmp_path / "output.png", "tiles", metadata)

    monkeypatch.setattr(download_module, "download_image", fake_download)
    monkeypatch.setattr(
        download_module,
        "create_async_client",
        lambda _: _ClientContext(client),
    )

    try:
        output, method = download_module.download_full_image(metadata, settings)
    finally:
        asyncio.run(client.aclose())

    assert output == str(tmp_path / "output.png")
    assert method == "tiles"
