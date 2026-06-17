from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from PIL import Image

from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.download import download_image, stitch_tiles
from artsy_tiled_image_downloader.exceptions import DownloadError, ImageAssemblyError
from artsy_tiled_image_downloader.http import create_async_client
from artsy_tiled_image_downloader.models import ImageMetadata


def test_stitch_tiles_crops_deep_zoom_overlap(tmp_path: Path, image_bytes) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/2/",
        tile_size=2,
        overlap=1,
        width=4,
        height=4,
        max_zoom_level=2,
    )
    tiles = {
        (0, 0): image_bytes((3, 3), (255, 0, 0)),
        (1, 0): image_bytes((3, 3), (0, 255, 0)),
        (0, 1): image_bytes((3, 3), (0, 0, 255)),
        (1, 1): image_bytes((3, 3), (255, 255, 0)),
    }

    output = stitch_tiles(metadata, tiles, tmp_path / "stitched.png")

    with Image.open(output) as stitched:
        assert stitched.size == (4, 4)
        assert stitched.getpixel((0, 0)) == (255, 0, 0)
        assert stitched.getpixel((3, 0)) == (0, 255, 0)
        assert stitched.getpixel((0, 3)) == (0, 0, 255)
        assert stitched.getpixel((3, 3)) == (255, 255, 0)


def test_stitch_tiles_rejects_too_small_overlap_tile(
    tmp_path: Path,
    image_bytes,
) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/2/",
        tile_size=2,
        overlap=1,
        width=4,
        height=4,
        max_zoom_level=2,
    )
    tiles = {
        (0, 0): image_bytes((3, 3), (255, 0, 0)),
        (1, 0): image_bytes((2, 2), (0, 255, 0)),
        (0, 1): image_bytes((3, 3), (0, 0, 255)),
        (1, 1): image_bytes((3, 3), (255, 255, 0)),
    }

    with pytest.raises(ImageAssemblyError, match="smaller than expected"):
        stitch_tiles(metadata, tiles, tmp_path / "stitched.png")


def test_download_image_uses_same_size_direct_candidate(
    tmp_path: Path,
    image_bytes,
) -> None:
    direct_url = "https://images.example/direct.png"
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/2/",
        tile_size=2,
        overlap=0,
        width=4,
        height=4,
        max_zoom_level=2,
        direct_urls=(direct_url,),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == direct_url
        return httpx.Response(200, content=image_bytes((4, 4), (10, 20, 30)))

    settings = DownloaderSettings(output_dir=tmp_path)
    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with create_async_client(settings, transport=transport) as client:
            result = await download_image(client, metadata, settings)
        assert result.method == "direct"
        with Image.open(result.output_path) as output:
            assert output.size == (4, 4)
            assert output.getpixel((0, 0)) == (10, 20, 30)

    asyncio.run(run())


def test_download_image_falls_back_to_tiles_when_direct_size_mismatches(
    tmp_path: Path,
    image_bytes,
) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/2/",
        tile_size=2,
        overlap=1,
        width=4,
        height=4,
        max_zoom_level=2,
        direct_urls=("https://images.example/direct.png",),
    )

    tile_colors = {
        "0_0": (255, 0, 0),
        "1_0": (0, 255, 0),
        "0_1": (0, 0, 255),
        "1_1": (255, 255, 0),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://images.example/direct.png":
            return httpx.Response(200, content=image_bytes((2, 2), (1, 1, 1)))
        tile_name = url.rsplit("/", 1)[-1].removesuffix(".png")
        return httpx.Response(200, content=image_bytes((3, 3), tile_colors[tile_name]))

    settings = DownloaderSettings(output_dir=tmp_path, concurrency=2)
    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with create_async_client(settings, transport=transport) as client:
            result = await download_image(client, metadata, settings)
        assert result.method == "tiles"
        with Image.open(result.output_path) as output:
            assert output.size == (4, 4)
            assert output.getpixel((3, 3)) == (255, 255, 0)

    asyncio.run(run())


def test_download_image_rejects_output_above_pixel_limit(tmp_path: Path) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/2/",
        tile_size=2,
        overlap=0,
        width=100,
        height=100,
        max_zoom_level=7,
    )
    settings = DownloaderSettings(output_dir=tmp_path, max_output_pixels=999)

    async def run() -> None:
        transport = httpx.MockTransport(lambda _: None)
        async with create_async_client(settings, transport=transport) as client:
            with pytest.raises(DownloadError, match="above limit"):
                await download_image(client, metadata, settings)

    asyncio.run(run())
