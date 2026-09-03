"""Measure the legacy and optimized download profiles on a deterministic workload."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from artsy_tiled_image_downloader.config import (
    DEFAULT_CONCURRENCY,
    DEFAULT_IMAGE_CONCURRENCY,
    DownloaderSettings,
)
from artsy_tiled_image_downloader.download import (
    download_and_stitch_tiles,
    download_images,
)
from artsy_tiled_image_downloader.http import create_async_client
from artsy_tiled_image_downloader.models import ImageMetadata

LEGACY_CONCURRENCY = 24
LEGACY_IMAGE_CONCURRENCY = 1
TILE_COUNT = 256
ARTWORK_IMAGE_COUNT = 6


class DelayedTransport(httpx.AsyncBaseTransport):
    def __init__(self, body: bytes, delay: float) -> None:
        self.body = body
        self.delay = delay

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self.delay)
        return httpx.Response(
            200,
            headers={"Content-Length": str(len(self.body))},
            content=self.body,
            request=request,
        )


def _jpeg_tile() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (256, 256), (12, 34, 56)).save(
        buffer,
        format="JPEG",
        quality=85,
    )
    return buffer.getvalue()


def _pixel() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def _tile_metadata() -> ImageMetadata:
    return ImageMetadata(
        index=0,
        title="benchmark-4096",
        format="jpg",
        url="https://tiles.example/0/",
        tile_size=256,
        overlap=0,
        width=4096,
        height=4096,
        max_zoom_level=12,
    )


def _artwork_metadatas() -> list[ImageMetadata]:
    return [
        ImageMetadata(
            index=index,
            title="benchmark-artwork",
            format="png",
            url="https://tiles.example/0/",
            tile_size=1,
            overlap=0,
            width=1,
            height=1,
            max_zoom_level=0,
            direct_urls=(f"https://images.example/{index}.png",),
        )
        for index in range(ARTWORK_IMAGE_COUNT)
    ]


async def _measure_tiles(
    concurrency: int,
    delay: float,
    repeats: int,
) -> list[float]:
    samples: list[float] = []
    for _ in range(repeats):
        with tempfile.TemporaryDirectory(prefix="atidd-tile-benchmark-") as raw_dir:
            output_dir = Path(raw_dir)
            settings = DownloaderSettings(
                output_dir=output_dir,
                concurrency=concurrency,
                prefer_direct=False,
            )
            async with create_async_client(
                settings,
                transport=DelayedTransport(_jpeg_tile(), delay),
            ) as client:
                started = time.perf_counter()
                await download_and_stitch_tiles(
                    client,
                    _tile_metadata(),
                    settings,
                    output_dir / "output.jpg",
                )
                samples.append(time.perf_counter() - started)
    return samples


async def _measure_artwork(
    image_concurrency: int,
    delay: float,
    repeats: int,
) -> list[float]:
    samples: list[float] = []
    for _ in range(repeats):
        with tempfile.TemporaryDirectory(prefix="atidd-artwork-benchmark-") as raw_dir:
            output_dir = Path(raw_dir)
            settings = DownloaderSettings(
                output_dir=output_dir,
                concurrency=DEFAULT_CONCURRENCY,
                image_concurrency=image_concurrency,
            )
            async with create_async_client(
                settings,
                transport=DelayedTransport(_pixel(), delay),
            ) as client:
                started = time.perf_counter()
                await download_images(
                    client,
                    _artwork_metadatas(),
                    settings,
                )
                samples.append(time.perf_counter() - started)
    return samples


def _summary(before: list[float], after: list[float]) -> dict[str, object]:
    before_mean = statistics.mean(before)
    after_mean = statistics.mean(after)
    return {
        "before_samples_seconds": [round(value, 6) for value in before],
        "after_samples_seconds": [round(value, 6) for value in after],
        "before_mean_seconds": round(before_mean, 6),
        "after_mean_seconds": round(after_mean, 6),
        "reduction": round(1 - after_mean / before_mean, 6),
    }


async def _run(repeats: int, delay: float) -> dict[str, object]:
    tile_before = await _measure_tiles(LEGACY_CONCURRENCY, delay, repeats)
    tile_after = await _measure_tiles(DEFAULT_CONCURRENCY, delay, repeats)
    artwork_before = await _measure_artwork(
        LEGACY_IMAGE_CONCURRENCY,
        delay,
        repeats,
    )
    artwork_after = await _measure_artwork(
        DEFAULT_IMAGE_CONCURRENCY,
        delay,
        repeats,
    )
    return {
        "workload": {
            "tile_count": TILE_COUNT,
            "tile_image": "4096x4096 JPEG",
            "request_delay_seconds": delay,
            "repeats": repeats,
        },
        "profiles": {
            "legacy": {
                "tile_concurrency": LEGACY_CONCURRENCY,
                "image_concurrency": LEGACY_IMAGE_CONCURRENCY,
            },
            "optimized": {
                "tile_concurrency": DEFAULT_CONCURRENCY,
                "image_concurrency": DEFAULT_IMAGE_CONCURRENCY,
            },
        },
        "tile_end_to_end": _summary(tile_before, tile_after),
        "six_image_direct": _summary(artwork_before, artwork_after),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--delay-ms", type=float, default=50.0)
    args = parser.parse_args()
    if args.repeats <= 0 or args.delay_ms <= 0:
        parser.error("--repeats and --delay-ms must be greater than 0")
    print(
        json.dumps(
            asyncio.run(_run(args.repeats, args.delay_ms / 1000.0)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
