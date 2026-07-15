from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from PIL import Image

import artsy_tiled_image_downloader.download as download_module
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.download import (
    DownloadedTile,
    download_image,
    download_tiles,
    stitch_tiles,
)
from artsy_tiled_image_downloader.exceptions import DownloadError, ImageAssemblyError
from artsy_tiled_image_downloader.http import create_async_client
from artsy_tiled_image_downloader.models import ImageMetadata

pytestmark = pytest.mark.integration


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

    with pytest.raises(ImageAssemblyError, match="dimensions do not match"):
        stitch_tiles(metadata, tiles, tmp_path / "stitched.png")


def test_stitch_tiles_rejects_oversized_tile_before_decode(
    tmp_path: Path,
    image_bytes,
) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/0/",
        tile_size=2,
        overlap=0,
        width=2,
        height=2,
        max_zoom_level=1,
    )

    with pytest.raises(ImageAssemblyError, match=r"expected=\(2, 2\)"):
        stitch_tiles(
            metadata,
            {(0, 0): image_bytes((100, 100), (1, 2, 3))},
            tmp_path / "oversized.png",
        )


@pytest.mark.parametrize("png_compression", [True, -1, 10])
def test_stitch_tiles_validates_png_compression(
    tmp_path: Path,
    png_compression: object,
) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/0/",
        tile_size=1,
        overlap=0,
        width=1,
        height=1,
        max_zoom_level=0,
    )

    with pytest.raises(ValueError, match="between 0 and 9"):
        stitch_tiles(
            metadata,
            {},
            tmp_path / "output.png",
            png_compression=png_compression,
        )


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


def test_download_image_rejects_tile_count_above_limit(tmp_path: Path) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/4/",
        tile_size=1,
        overlap=0,
        width=10,
        height=10,
        max_zoom_level=4,
    )
    settings = DownloaderSettings(output_dir=tmp_path, max_tiles=99)

    async def run() -> None:
        transport = httpx.MockTransport(lambda _: None)
        async with create_async_client(settings, transport=transport) as client:
            with pytest.raises(DownloadError, match="100 tiles above limit 99"):
                await download_image(client, metadata, settings)

    asyncio.run(run())


def test_download_tiles_only_schedules_up_to_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/2/",
        tile_size=1,
        overlap=0,
        width=4,
        height=1,
        max_zoom_level=2,
    )
    settings = DownloaderSettings(output_dir=tmp_path, concurrency=2)
    started: list[tuple[int, int]] = []

    async def run() -> None:
        release = asyncio.Event()

        async def fake_download_single_tile(
            client: httpx.AsyncClient,
            metadata: ImageMetadata,
            settings: DownloaderSettings,
            col: int,
            row: int,
        ) -> DownloadedTile:
            del client, metadata, settings
            started.append((col, row))
            await release.wait()
            return DownloadedTile(col=col, row=row, content=b"tile")

        monkeypatch.setattr(
            download_module,
            "_download_single_tile",
            fake_download_single_tile,
        )
        transport = httpx.MockTransport(lambda _: httpx.Response(500))
        async with create_async_client(settings, transport=transport) as client:
            task = asyncio.create_task(download_tiles(client, metadata, settings))
            for _ in range(10):
                await asyncio.sleep(0)
                if len(started) == settings.concurrency:
                    break
            assert started == [(0, 0), (1, 0)]
            release.set()
            tiles = await task

        assert set(tiles) == {(0, 0), (1, 0), (2, 0), (3, 0)}

    asyncio.run(run())
