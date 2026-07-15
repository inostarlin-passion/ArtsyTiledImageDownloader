from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx
import pytest
from PIL import Image

import artsy_tiled_image_downloader.download as download_module
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.download import download_and_stitch_tiles
from artsy_tiled_image_downloader.http import create_async_client
from artsy_tiled_image_downloader.models import ImageMetadata

pytestmark = [pytest.mark.integration, pytest.mark.performance]


def test_pipeline_overlaps_network_with_bounded_decode_batch(
    tmp_path: Path,
    image_bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = ImageMetadata(
        index=0,
        title="pipeline-test",
        format="png",
        url="https://tiles.example/4/",
        tile_size=1,
        overlap=0,
        width=10,
        height=1,
        max_zoom_level=4,
    )
    settings = DownloaderSettings(
        output_dir=tmp_path,
        concurrency=2,
        prefer_direct=False,
    )
    tile_content = image_bytes((1, 1), (12, 34, 56))
    requested: list[str] = []
    decode_started = threading.Event()
    release_decode = threading.Event()
    original_decode = download_module._decode_tile_content

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=tile_content, request=request)

    def blocked_decode(metadata, tile):
        decode_started.set()
        if not release_decode.wait(timeout=5):
            raise TimeoutError("test did not release decoder")
        return original_decode(metadata, tile)

    async def run() -> None:
        monkeypatch.setattr(download_module, "_decode_tile_content", blocked_decode)
        transport = httpx.MockTransport(handler)
        output = tmp_path / "pipeline.png"
        async with create_async_client(settings, transport=transport) as client:
            task = asyncio.create_task(
                download_and_stitch_tiles(client, metadata, settings, output)
            )
            try:
                assert await asyncio.to_thread(decode_started.wait, 2)
                for _ in range(100):
                    if len(requested) >= settings.concurrency * 2:
                        break
                    await asyncio.sleep(0.01)

                # One decode batch plus one refilled network window is the bound;
                # the remaining six tiles are not eagerly buffered.
                assert len(requested) == settings.concurrency * 2
            finally:
                release_decode.set()
            await task

        with Image.open(output) as image:
            assert image.size == (10, 1)
            assert image.getpixel((9, 0)) == (12, 34, 56)

    asyncio.run(run())
