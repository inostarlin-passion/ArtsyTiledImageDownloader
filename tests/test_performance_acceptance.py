from __future__ import annotations

import asyncio
import statistics
import time
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from artsy_tiled_image_downloader.config import (
    DEFAULT_CONCURRENCY,
    DEFAULT_IMAGE_CONCURRENCY,
    MAX_ALLOWED_CONCURRENCY,
    MAX_ALLOWED_IMAGE_CONCURRENCY,
    DownloaderSettings,
)
from artsy_tiled_image_downloader.download import (
    DownloadResult,
    download_and_stitch_tiles,
    download_images,
    download_tiles,
)
from artsy_tiled_image_downloader.exceptions import ResponseTooLargeError
from artsy_tiled_image_downloader.http import (
    create_async_client,
    request_bytes_with_retries,
)
from artsy_tiled_image_downloader.models import ImageMetadata

pytestmark = [pytest.mark.integration, pytest.mark.performance]

LEGACY_CONCURRENCY = 24
# Keep the synthetic network phase dominant over cross-platform image I/O
# jitter; this preserves the 50% acceptance target without weakening it.
BENCHMARK_DELAY_SECONDS = 0.10
BENCHMARK_REPEATS = 3


class DelayedTransport(httpx.AsyncBaseTransport):
    def __init__(self, body: bytes, delay: float) -> None:
        self.body = body
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return httpx.Response(
                200,
                headers={"Content-Length": str(len(self.body))},
                content=self.body,
                request=request,
            )
        finally:
            self.active -= 1


def _jpeg_tile() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (256, 256), (12, 34, 56)).save(
        buffer,
        format="JPEG",
        quality=85,
    )
    return buffer.getvalue()


def _single_image_metadata() -> ImageMetadata:
    return ImageMetadata(
        index=0,
        title="performance-benchmark",
        format="jpg",
        url="https://tiles.example/0/",
        tile_size=256,
        overlap=0,
        width=4096,
        height=4096,
        max_zoom_level=12,
    )


def _small_metadata(
    index: int,
    *,
    direct_url: str | None = None,
) -> ImageMetadata:
    if direct_url:
        return ImageMetadata(
            index=index,
            title="acceptance",
            format="png",
            url="https://tiles.example/0/",
            tile_size=1,
            overlap=0,
            width=1,
            height=1,
            max_zoom_level=0,
            direct_urls=(direct_url,),
        )
    return ImageMetadata(
        index=index,
        title="acceptance",
        format="png",
        url="https://tiles.example/2/",
        tile_size=2,
        overlap=0,
        width=4,
        height=4,
        max_zoom_level=2,
        direct_urls=(direct_url,) if direct_url else (),
    )


async def _measure_tile_download(
    tmp_path: Path,
    concurrency: int,
    *,
    end_to_end: bool,
) -> float:
    settings = DownloaderSettings(
        output_dir=tmp_path,
        concurrency=concurrency,
        prefer_direct=False,
    )
    transport = DelayedTransport(_jpeg_tile(), BENCHMARK_DELAY_SECONDS)
    metadata = _single_image_metadata()

    async with create_async_client(settings, transport=transport) as client:
        started = time.perf_counter()
        if end_to_end:
            await download_and_stitch_tiles(
                client,
                metadata,
                settings,
                tmp_path / f"output-{concurrency}.jpg",
            )
        else:
            await download_tiles(client, metadata, settings)
        return time.perf_counter() - started


def test_ac_01_fast_defaults_are_explicit_and_bounded(tmp_path: Path) -> None:
    settings = DownloaderSettings(output_dir=tmp_path)

    assert DEFAULT_CONCURRENCY == MAX_ALLOWED_CONCURRENCY == 64
    assert DEFAULT_IMAGE_CONCURRENCY == 4
    assert settings.concurrency == DEFAULT_CONCURRENCY
    assert settings.image_concurrency == DEFAULT_IMAGE_CONCURRENCY
    assert MAX_ALLOWED_IMAGE_CONCURRENCY == 8


def test_ac_02_mean_tile_download_time_is_reduced_by_50_percent(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[float, float]:
        legacy = [
            await _measure_tile_download(
                tmp_path / "legacy",
                LEGACY_CONCURRENCY,
                end_to_end=True,
            )
            for _ in range(BENCHMARK_REPEATS)
        ]
        optimized = [
            await _measure_tile_download(
                tmp_path / "optimized",
                DEFAULT_CONCURRENCY,
                end_to_end=True,
            )
            for _ in range(BENCHMARK_REPEATS)
        ]
        return statistics.mean(legacy), statistics.mean(optimized)

    legacy_mean, optimized_mean = asyncio.run(run())
    reduction = 1 - optimized_mean / legacy_mean
    assert reduction >= 0.50, (
        f"expected at least 50% reduction, got {reduction:.1%}; "
        f"legacy={legacy_mean:.6f}s optimized={optimized_mean:.6f}s"
    )


def test_ac_03_optimized_pipeline_preserves_dimensions_and_pixels(
    tmp_path: Path,
    image_bytes,
) -> None:
    metadata = _small_metadata(0)
    colors = {
        "0_0": (255, 0, 0),
        "1_0": (0, 255, 0),
        "0_1": (0, 0, 255),
        "1_1": (255, 255, 0),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        tile_name = str(request.url).rsplit("/", 1)[-1].removesuffix(".png")
        return httpx.Response(
            200,
            content=image_bytes((2, 2), colors[tile_name]),
            request=request,
        )

    async def run() -> Path:
        settings = DownloaderSettings(
            output_dir=tmp_path,
            concurrency=DEFAULT_CONCURRENCY,
            prefer_direct=False,
        )
        output = tmp_path / "optimized.png"
        async with create_async_client(
            settings,
            transport=httpx.MockTransport(handler),
        ) as client:
            await download_and_stitch_tiles(client, metadata, settings, output)
        return output

    output = asyncio.run(run())
    with Image.open(output) as image:
        assert image.size == (4, 4)
        assert image.getpixel((0, 0)) == (255, 0, 0)
        assert image.getpixel((3, 0)) == (0, 255, 0)
        assert image.getpixel((0, 3)) == (0, 0, 255)
        assert image.getpixel((3, 3)) == (255, 255, 0)


def test_ac_04_tile_and_shared_artwork_request_windows_are_bounded(
    tmp_path: Path,
) -> None:
    tile_body_buffer = BytesIO()
    Image.new("RGB", (2, 2), (12, 34, 56)).save(tile_body_buffer, format="PNG")
    tile_body = tile_body_buffer.getvalue()
    metadata = ImageMetadata(
        index=0,
        title="bound",
        format="png",
        url="https://tiles.example/0/",
        tile_size=1,
        overlap=0,
        width=10,
        height=1,
        max_zoom_level=4,
    )

    async def run_tile_window() -> int:
        settings = DownloaderSettings(
            output_dir=tmp_path / "tiles",
            concurrency=3,
            prefer_direct=False,
        )
        transport = DelayedTransport(tile_body, 0.01)
        async with create_async_client(settings, transport=transport) as client:
            tiles = await download_tiles(client, metadata, settings)
        assert len(tiles) == metadata.tile_count
        return transport.max_active

    assert asyncio.run(run_tile_window()) <= 3

    async def run_shared_artwork_window() -> int:
        settings = DownloaderSettings(
            output_dir=tmp_path / "artwork",
            concurrency=3,
            image_concurrency=3,
            prefer_direct=False,
        )
        transport = DelayedTransport(tile_body, 0.01)
        metadatas = [_small_metadata(index) for index in range(3)]
        async with create_async_client(settings, transport=transport) as client:
            results = await download_images(client, metadatas, settings)
        assert [result.metadata.index for result in results] == [0, 1, 2]
        return transport.max_active

    assert asyncio.run(run_shared_artwork_window()) <= 3


def test_ac_05_artwork_parallelism_is_fast_and_keeps_result_order(
    tmp_path: Path,
) -> None:
    pixel = BytesIO()
    Image.new("RGB", (1, 1), (12, 34, 56)).save(pixel, format="PNG")
    metadatas = [
        _small_metadata(index, direct_url=f"https://images.example/{index}.png")
        for index in range(6)
    ]

    async def measure(image_concurrency: int, directory: Path) -> float:
        settings = DownloaderSettings(
            output_dir=directory,
            concurrency=DEFAULT_CONCURRENCY,
            image_concurrency=image_concurrency,
        )
        transport = DelayedTransport(pixel.getvalue(), BENCHMARK_DELAY_SECONDS)
        async with create_async_client(settings, transport=transport) as client:
            started = time.perf_counter()
            results = await download_images(client, metadatas, settings)
        assert all(isinstance(result, DownloadResult) for result in results)
        assert [result.metadata.index for result in results] == list(range(6))
        assert transport.max_active <= image_concurrency
        return time.perf_counter() - started

    async def run() -> tuple[float, float]:
        legacy = [
            await measure(1, tmp_path / f"legacy-{index}")
            for index in range(BENCHMARK_REPEATS)
        ]
        optimized = [
            await measure(
                DEFAULT_IMAGE_CONCURRENCY,
                tmp_path / f"optimized-{index}",
            )
            for index in range(BENCHMARK_REPEATS)
        ]
        return statistics.mean(legacy), statistics.mean(optimized)

    legacy_mean, optimized_mean = asyncio.run(run())
    assert optimized_mean <= legacy_mean * 0.50


def test_ac_06_cancelled_downloads_release_all_inflight_requests(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.active = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            del request
            self.active += 1
            started.set()
            try:
                await release.wait()
                return httpx.Response(200, content=b"tile")
            finally:
                self.active -= 1

    async def run() -> int:
        transport = BlockingTransport()
        settings = DownloaderSettings(
            output_dir=tmp_path,
            concurrency=4,
            prefer_direct=False,
        )
        metadata = ImageMetadata(
            index=0,
            title="cancel",
            format="png",
            url="https://tiles.example/0/",
            tile_size=1,
            overlap=0,
            width=8,
            height=1,
            max_zoom_level=3,
        )
        async with create_async_client(settings, transport=transport) as client:
            task = asyncio.create_task(download_tiles(client, metadata, settings))
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        release.set()
        return transport.active

    assert asyncio.run(run()) == 0
    assert list(tmp_path.iterdir()) == []


def test_ac_07_fast_response_path_still_enforces_byte_limit(tmp_path: Path) -> None:
    settings = DownloaderSettings(output_dir=tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "4"},
            content=b"data",
            request=request,
        )

    async def run() -> None:
        async with create_async_client(
            settings,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(ResponseTooLargeError, match="limit 3"):
                await request_bytes_with_retries(
                    client,
                    "GET",
                    "https://images.example/too-large.png",
                    settings,
                    max_bytes=3,
                )

    asyncio.run(run())


def test_ac_08_cli_uses_the_optimized_defaults(tmp_path: Path) -> None:
    import artsy_tiled_image_downloader.cli as cli_module

    parser = cli_module.build_parser()
    args = parser.parse_args(
        ["--output-dir", str(tmp_path), "example-artwork"]
    )
    custom_args = parser.parse_args(
        ["--image-concurrency", "2", "example-artwork"]
    )

    assert args.concurrency == DEFAULT_CONCURRENCY
    assert args.image_concurrency == DEFAULT_IMAGE_CONCURRENCY
    assert custom_args.image_concurrency == 2
