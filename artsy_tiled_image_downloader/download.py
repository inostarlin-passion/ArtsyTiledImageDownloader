from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from .config import DEFAULT_PNG_COMPRESSION, IMAGE_HEADERS, DownloaderSettings
from .exceptions import DownloadError, ImageAssemblyError
from .http import create_async_client, request_bytes_with_retries
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


@dataclass(frozen=True, slots=True)
class DecodedTile:
    col: int
    row: int
    image: Image.Image


def _tile_positions(metadata: ImageMetadata) -> Iterator[tuple[int, int]]:
    for row in range(metadata.rows):
        for col in range(metadata.cols):
            yield col, row


async def _fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    settings: DownloaderSettings,
    *,
    max_bytes: int,
) -> bytes:
    try:
        return await request_bytes_with_retries(
            client,
            "GET",
            url,
            settings,
            max_bytes=max_bytes,
            headers=IMAGE_HEADERS,
        )
    except DownloadError:
        raise
    except httpx.HTTPError as exc:
        raise DownloadError(f"failed to fetch {url}: {exc}") from exc


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
            content = await _fetch_bytes(
                client,
                direct_url,
                settings,
                max_bytes=settings.max_direct_bytes,
            )
            if _image_size_from_bytes(content) != expected_size:
                continue
        except DownloadError:
            continue

        try:
            await asyncio.to_thread(atomic_write_bytes, output_path, content)
        except OSError as exc:
            raise DownloadError(f"failed to write output image: {output_path}") from exc
        return output_path

    return None


async def _download_single_tile(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    col: int,
    row: int,
) -> DownloadedTile:
    content = await _fetch_bytes(
        client,
        metadata.tile_url(col, row),
        settings,
        max_bytes=settings.max_tile_bytes,
    )
    return DownloadedTile(col=col, row=row, content=content)


async def _cancel_tasks(tasks: set[asyncio.Task[DownloadedTile]]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def download_tiles(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[tuple[int, int], bytes]:
    positions = _tile_positions(metadata)
    pending: set[asyncio.Task[DownloadedTile]] = set()

    def schedule_next() -> None:
        try:
            col, row = next(positions)
        except StopIteration:
            return
        pending.add(
            asyncio.create_task(
                _download_single_tile(client, metadata, settings, col, row)
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
    except BaseException:
        await _cancel_tasks(pending)
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

    expected_size = metadata.expected_tile_size(col, row)
    if tile_size != expected_size:
        raise ImageAssemblyError(
            "tile dimensions do not match Deep Zoom metadata: "
            f"tile=({col},{row}) size={tile_size} expected={expected_size}"
        )
    return left, top, right, bottom


def _decode_tile_content(
    metadata: ImageMetadata,
    downloaded_tile: DownloadedTile,
) -> DecodedTile:
    """Decode and crop a tile to its non-overlapping content rectangle."""
    col, row, content = (
        downloaded_tile.col,
        downloaded_tile.row,
        downloaded_tile.content,
    )
    try:
        with Image.open(BytesIO(content), formats=[metadata.pil_format]) as raw_tile:
            crop_box = _tile_crop_box(metadata, col, row, raw_tile.size)
            raw_tile.load()
            cropped_tile = raw_tile.crop(crop_box)
            if cropped_tile.mode == "RGB":
                tile_image = cropped_tile
            else:
                try:
                    tile_image = cropped_tile.convert("RGB")
                finally:
                    cropped_tile.close()
    except ImageAssemblyError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ImageAssemblyError(f"invalid tile image: {col}_{row}") from exc

    return DecodedTile(col=col, row=row, image=tile_image)


def _close_decoded_tiles(results: list[DecodedTile | BaseException]) -> None:
    for result in results:
        if isinstance(result, DecodedTile):
            result.image.close()


async def _decode_tiles_bounded(
    metadata: ImageMetadata,
    tiles: list[DownloadedTile],
) -> list[DecodedTile | BaseException]:
    """Decode a bounded batch without leaking thread results during cancellation."""

    async def run_batch() -> list[DecodedTile | BaseException]:
        return await asyncio.gather(
            *(
                asyncio.to_thread(_decode_tile_content, metadata, tile)
                for tile in tiles
            ),
            return_exceptions=True,
        )

    decode_task = asyncio.create_task(run_batch())
    try:
        return await asyncio.shield(decode_task)
    except BaseException:
        # Pillow work running in a worker thread cannot be force-cancelled. Wait for
        # this bounded batch and close every produced image before propagating.
        results = await decode_task
        _close_decoded_tiles(results)
        raise


def _image_save_kwargs(
    metadata: ImageMetadata,
    *,
    png_compression: int,
) -> dict[str, object]:
    save_kwargs: dict[str, object] = {"format": metadata.pil_format}
    if metadata.pil_format == "JPEG":
        save_kwargs["quality"] = 95
    elif metadata.pil_format == "PNG":
        save_kwargs["compress_level"] = png_compression
    return save_kwargs


def _new_canvas(metadata: ImageMetadata) -> Image.Image:
    try:
        return Image.new("RGB", (metadata.width, metadata.height), "white")
    except (MemoryError, ValueError) as exc:
        raise ImageAssemblyError(
            f"failed to allocate {metadata.width}x{metadata.height} RGB canvas"
        ) from exc


def stitch_tiles(
    metadata: ImageMetadata,
    tiles: dict[tuple[int, int], bytes],
    output_path: Path,
    *,
    png_compression: int = DEFAULT_PNG_COMPRESSION,
) -> Path:
    if (
        not isinstance(png_compression, int)
        or isinstance(png_compression, bool)
        or not 0 <= png_compression <= 9
    ):
        raise ValueError("png_compression must be between 0 and 9")
    canvas = _new_canvas(metadata)

    try:
        for row in range(metadata.rows):
            for col in range(metadata.cols):
                content = tiles.get((col, row))
                if content is None:
                    raise ImageAssemblyError(f"missing downloaded tile: {col}_{row}")

                decoded_tile = _decode_tile_content(
                    metadata,
                    DownloadedTile(col=col, row=row, content=content),
                )
                tile_image = decoded_tile.image
                try:
                    canvas.paste(
                        tile_image,
                        (
                            col * metadata.tile_size,
                            row * metadata.tile_size,
                        ),
                    )
                finally:
                    tile_image.close()

        try:
            atomic_save_image(
                output_path,
                canvas,
                **_image_save_kwargs(metadata, png_compression=png_compression),
            )
        except OSError as exc:
            raise ImageAssemblyError(
                f"failed to save assembled image: {output_path}"
            ) from exc
        return output_path
    finally:
        canvas.close()


async def download_and_stitch_tiles(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    output_path: Path,
    *,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Pipeline bounded tile downloads, parallel decoding, and serial canvas writes."""
    canvas = _new_canvas(metadata)
    positions = _tile_positions(metadata)
    pending: set[asyncio.Task[DownloadedTile]] = set()
    completed = 0

    def schedule_next() -> None:
        try:
            col, row = next(positions)
        except StopIteration:
            return
        pending.add(
            asyncio.create_task(
                _download_single_tile(client, metadata, settings, col, row)
            )
        )

    for _ in range(min(settings.concurrency, metadata.tile_count)):
        schedule_next()

    try:
        while pending:
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )

            downloaded = [task.result() for task in done]
            # Refill the network window before decoding so both stages overlap.
            for _ in downloaded:
                schedule_next()

            decoded = await _decode_tiles_bounded(metadata, downloaded)
            first_error = next(
                (result for result in decoded if isinstance(result, BaseException)),
                None,
            )
            if first_error is not None:
                _close_decoded_tiles(decoded)
                raise first_error

            try:
                for tile in decoded:
                    assert isinstance(tile, DecodedTile)
                    canvas.paste(
                        tile.image,
                        (
                            tile.col * metadata.tile_size,
                            tile.row * metadata.tile_size,
                        ),
                    )

                    completed += 1
                    if progress_callback:
                        progress_callback(completed, metadata.tile_count)
            finally:
                _close_decoded_tiles(decoded)

        if completed != metadata.tile_count:
            raise DownloadError(
                f"assembled {completed} of {metadata.tile_count} required tiles"
            )

        try:
            await asyncio.to_thread(
                atomic_save_image,
                output_path,
                canvas,
                **_image_save_kwargs(
                    metadata,
                    png_compression=settings.png_compression,
                ),
            )
        except OSError as exc:
            raise ImageAssemblyError(
                f"failed to save assembled image: {output_path}"
            ) from exc
        return output_path
    except BaseException:
        await _cancel_tasks(pending)
        raise
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
    if metadata.tile_count > settings.max_tiles:
        raise DownloadError(
            f"refusing to schedule {metadata.tile_count} tiles above limit "
            f"{settings.max_tiles}"
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
    stitched_path = await download_and_stitch_tiles(
        client,
        metadata,
        settings,
        output_path,
        progress_callback=progress_callback,
    )
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
