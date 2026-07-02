from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import IMAGE_HEADERS, DownloaderSettings
from .exceptions import DownloadError, ImageAssemblyError
from .http import create_async_client, request_with_retries
from .metadata import fetch_metadatas
from .models import ImageMetadata
from .paths import atomic_save_image, atomic_write_bytes, output_path_for

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class DownloadResult:
    output_path: Path
    method: str
    metadata: ImageMetadata


@dataclass(frozen=True, slots=True)
class DownloadedTile:
    col: int
    row: int
    content: bytes


def _tile_positions(metadata: ImageMetadata) -> Iterator[tuple[int, int]]:
    for row in range(metadata.rows):
        for col in range(metadata.cols):
            yield col, row


async def _fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    settings: DownloaderSettings,
) -> bytes:
    try:
        response = await request_with_retries(
            client,
            "GET",
            url,
            settings,
            headers=IMAGE_HEADERS,
        )
    except httpx.HTTPError as exc:
        raise DownloadError(f"failed to fetch {url}: {exc}") from exc
    return response.content


def _image_size_from_bytes(content: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(content)) as image:
            size = image.size
            image.verify()
            return size
    except (OSError, UnidentifiedImageError) as exc:
        raise DownloadError("downloaded direct image is not a valid image") from exc


async def download_direct_image(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
) -> Path | None:
    if not settings.prefer_direct or not metadata.direct_urls:
        return None

    output_path = output_path_for(metadata, settings.output_dir)
    expected_size = (metadata.width, metadata.height)

    for direct_url in metadata.direct_urls:
        try:
            content = await _fetch_bytes(client, direct_url, settings)
            if _image_size_from_bytes(content) != expected_size:
                continue
            await asyncio.to_thread(atomic_write_bytes, output_path, content)
            return output_path
        except DownloadError:
            continue

    return None


async def _download_single_tile(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    semaphore: asyncio.Semaphore,
    col: int,
    row: int,
) -> DownloadedTile:
    async with semaphore:
        content = await _fetch_bytes(client, metadata.tile_url(col, row), settings)
        return DownloadedTile(col=col, row=row, content=content)


async def download_tiles(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[tuple[int, int], bytes]:
    semaphore = asyncio.Semaphore(settings.concurrency)
    positions = _tile_positions(metadata)
    pending: set[asyncio.Task[DownloadedTile]] = set()

    def schedule_next() -> None:
        try:
            col, row = next(positions)
        except StopIteration:
            return
        pending.add(
            asyncio.create_task(
                _download_single_tile(client, metadata, settings, semaphore, col, row)
            )
        )

    for _ in range(min(settings.concurrency, metadata.tile_count)):
        schedule_next()

    completed = 0
    tiles: dict[tuple[int, int], bytes] = {}

    try:
        while pending:
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                tile = task.result()
                tiles[(tile.col, tile.row)] = tile.content
                completed += 1
                if progress_callback:
                    progress_callback(completed, metadata.tile_count)
                schedule_next()
    except Exception:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise

    if len(tiles) != metadata.tile_count:
        raise DownloadError(
            f"downloaded {len(tiles)} of {metadata.tile_count} required tiles"
        )
    return tiles


def _tile_crop_box(
    metadata: ImageMetadata,
    col: int,
    row: int,
    tile_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    left = metadata.overlap if col > 0 else 0
    top = metadata.overlap if row > 0 else 0
    content_width, content_height = metadata.expected_tile_content_size(col, row)
    right = left + content_width
    bottom = top + content_height

    if tile_size[0] < right or tile_size[1] < bottom:
        raise ImageAssemblyError(
            "tile is smaller than expected after accounting for overlap: "
            f"tile=({col},{row}) size={tile_size} crop={(left, top, right, bottom)}"
        )
    return left, top, right, bottom


def stitch_tiles(
    metadata: ImageMetadata,
    tiles: dict[tuple[int, int], bytes],
    output_path: Path,
) -> Path:
    canvas = Image.new("RGB", (metadata.width, metadata.height), "white")

    try:
        for row in range(metadata.rows):
            for col in range(metadata.cols):
                content = tiles.get((col, row))
                if content is None:
                    raise ImageAssemblyError(f"missing downloaded tile: {col}_{row}")

                try:
                    with Image.open(BytesIO(content)) as raw_tile:
                        tile_image = ImageOps.exif_transpose(raw_tile).convert("RGB")
                        try:
                            crop_box = _tile_crop_box(
                                metadata,
                                col,
                                row,
                                tile_image.size,
                            )
                            cropped_tile = tile_image.crop(crop_box)
                            try:
                                canvas.paste(
                                    cropped_tile,
                                    (
                                        col * metadata.tile_size,
                                        row * metadata.tile_size,
                                    ),
                                )
                            finally:
                                cropped_tile.close()
                        finally:
                            tile_image.close()
                except (OSError, UnidentifiedImageError) as exc:
                    raise ImageAssemblyError(
                        f"invalid tile image: {col}_{row}"
                    ) from exc

        save_kwargs: dict[str, object] = {"format": metadata.pil_format}
        if metadata.pil_format == "JPEG":
            save_kwargs["quality"] = 95

        atomic_save_image(output_path, canvas, **save_kwargs)
        return output_path
    finally:
        canvas.close()


def _validate_output_size(
    metadata: ImageMetadata,
    settings: DownloaderSettings,
) -> None:
    pixel_count = metadata.output_pixel_count()
    if pixel_count > settings.max_output_pixels:
        raise DownloadError(
            f"refusing to allocate {metadata.width}x{metadata.height} image "
            f"({pixel_count} pixels) above limit {settings.max_output_pixels}"
        )


async def download_image(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    *,
    progress_callback: ProgressCallback | None = None,
) -> DownloadResult:
    _validate_output_size(metadata, settings)

    direct_output_path = await download_direct_image(client, metadata, settings)
    if direct_output_path:
        return DownloadResult(direct_output_path, "direct", metadata)

    output_path = output_path_for(metadata, settings.output_dir)
    tiles = await download_tiles(
        client,
        metadata,
        settings,
        progress_callback=progress_callback,
    )
    stitched_path = await asyncio.to_thread(stitch_tiles, metadata, tiles, output_path)
    return DownloadResult(stitched_path, "tiles", metadata)


async def download_artwork(
    url: str,
    settings: DownloaderSettings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[DownloadResult]:
    settings = settings or DownloaderSettings()

    if client is not None:
        metadatas = await fetch_metadatas(url, settings, client=client)
        return [
            await download_image(
                client,
                metadata,
                settings,
                progress_callback=progress_callback,
            )
            for metadata in metadatas
        ]

    async with create_async_client(settings) as managed_client:
        metadatas = await fetch_metadatas(url, settings, client=managed_client)
        return [
            await download_image(
                managed_client,
                metadata,
                settings,
                progress_callback=progress_callback,
            )
            for metadata in metadatas
        ]


def download_full_image(
    image_metadata: ImageMetadata,
    settings: DownloaderSettings | None = None,
) -> tuple[str, str]:
    settings = settings or DownloaderSettings()

    async def _run() -> DownloadResult:
        async with create_async_client(settings) as client:
            return await download_image(client, image_metadata, settings)

    result = asyncio.run(_run())
    return str(result.output_path), result.method
