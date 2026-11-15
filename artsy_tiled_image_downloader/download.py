from __future__ import annotations

import asyncio
import traceback
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from .color import CanvasColor, prepare_tile
from .config import DEFAULT_PNG_COMPRESSION, IMAGE_HEADERS, DownloaderSettings
from .exceptions import (
    ArtsyDownloaderError,
    DownloadError,
    ImageAssemblyError,
    OutputExistsError,
)
from .http import (
    create_async_client,
    request_bytes_with_retries,
    request_file_with_retries,
)
from .metadata import fetch_metadatas
from .models import ImageMetadata
from .paths import (
    async_atomic_output,
    atomic_save_image,
    commit_output,
    output_path_for,
    temporary_output,
    wait_for_worker,
)

ProgressCallback = Callable[[int, int], None]
WEBP_MAX_DIMENSION = 16383


@dataclass(frozen=True, slots=True)
class DownloadResult:
    output_path: Path
    method: str
    metadata: ImageMetadata


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    metadata: ImageMetadata
    result: DownloadResult | None = None
    error: ArtsyDownloaderError | None = None

    @property
    def status(self) -> str:
        if self.result is not None:
            return "saved"
        return "failed" if self.error is not None else "cancelled"


class BatchDownloadError(DownloadError):
    def __init__(self, outcomes: tuple[DownloadOutcome, ...]) -> None:
        self.outcomes = outcomes
        failed = [item for item in outcomes if item.error is not None]
        super().__init__(
            f"{len(failed)} of {len(outcomes)} images failed: {failed[0].error}"
        )


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
    profile: bytes | None


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


async def _fetch_bytes_with_limiter(
    client: httpx.AsyncClient,
    url: str,
    settings: DownloaderSettings,
    *,
    max_bytes: int,
    request_limiter: asyncio.Semaphore | None,
) -> bytes:
    """Fetch one object while optionally sharing a process-level request budget."""
    if request_limiter is None:
        return await _fetch_bytes(client, url, settings, max_bytes=max_bytes)

    async with request_limiter:
        return await _fetch_bytes(client, url, settings, max_bytes=max_bytes)


def _validate_direct_candidate(path: Path, metadata: ImageMetadata) -> bool:
    formats = [metadata.pil_format]
    try:
        with Image.open(path, formats=formats) as image:
            if image.size != (metadata.width, metadata.height):
                return False
            image.verify()
        # verify() checks structure where supported. Reopen for actual pixel decoding.
        with Image.open(path, formats=formats) as image:
            image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        EOFError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        return False
    return True


async def download_direct_image(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    *,
    request_limiter: asyncio.Semaphore | None = None,
    buffer_budget: _ByteBudget | None = None,
) -> Path | None:
    if not settings.prefer_direct or not metadata.direct_urls:
        return None

    output_path = output_path_for(metadata, settings.output_dir)
    budget = buffer_budget or _ByteBudget(
        settings.max_tile_buffer_bytes, "image buffer"
    )

    for direct_url in metadata.direct_urls:
        temporary = None
        try:
            with temporary_output(output_path) as (temporary, file):
                async with request_limiter or asyncio.Semaphore(1):
                    await request_file_with_retries(
                        client,
                        direct_url,
                        settings,
                        file,
                        max_bytes=settings.max_direct_bytes,
                        headers=IMAGE_HEADERS,
                    )
            # Pillow may read an entire encoded chunk or WebP stream at once.
            reserve = 3 * temporary.stat().st_size
            if metadata.pil_format == "WEBP":
                reserve += 8 * metadata.output_pixel_count()
            async with budget.reserve(reserve):
                validation = asyncio.create_task(
                    asyncio.to_thread(_validate_direct_candidate, temporary, metadata)
                )
                if not await wait_for_worker(validation):
                    continue
            commit_output(temporary, output_path, overwrite=settings.overwrite)
        except (DownloadError, httpx.HTTPError):
            continue
        except FileExistsError as exc:
            raise OutputExistsError(f"output already exists: {output_path}") from exc
        except OSError as exc:
            raise DownloadError(f"failed to write output image: {output_path}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return output_path

    return None


async def _download_single_tile(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    col: int,
    row: int,
    *,
    request_limiter: asyncio.Semaphore | None = None,
) -> DownloadedTile:
    content = await _fetch_bytes_with_limiter(
        client,
        metadata.tile_url(col, row),
        settings,
        max_bytes=settings.max_tile_bytes,
        request_limiter=request_limiter,
    )
    return DownloadedTile(col=col, row=row, content=content)


async def _cancel_tasks(tasks: Sequence[asyncio.Task] | set[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        cleanup = asyncio.gather(*tasks, return_exceptions=True)
        await wait_for_worker(cleanup)


async def download_tiles(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    *,
    progress_callback: ProgressCallback | None = None,
    request_limiter: asyncio.Semaphore | None = None,
) -> dict[tuple[int, int], bytes]:
    """Collect compressed tiles in memory, bounded by the tile buffer budget."""
    _validate_output_size(metadata, settings)
    positions = _tile_positions(metadata)
    pending: set[asyncio.Task[DownloadedTile]] = set()
    scheduled = 0
    retained = 0
    tiles: dict[tuple[int, int], bytes] = {}
    reserve = 3 * settings.max_tile_bytes

    try:
        while len(tiles) < metadata.tile_count:
            while (
                scheduled < metadata.tile_count
                and len(pending) < settings.concurrency
                and retained + (len(pending) + 1) * reserve
                <= settings.max_tile_buffer_bytes
            ):
                col, row = next(positions)
                kwargs = {"request_limiter": request_limiter} if request_limiter else {}
                pending.add(
                    asyncio.create_task(
                        _download_single_tile(
                            client, metadata, settings, col, row, **kwargs
                        )
                    )
                )
                scheduled += 1
            if not pending:
                raise DownloadError(
                    "all compressed tiles cannot fit in the tile buffer budget"
                )

            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                tile = task.result()
                pending.remove(task)
                tiles[(tile.col, tile.row)] = tile.content
                retained += len(tile.content)
                if progress_callback:
                    progress_callback(len(tiles), metadata.tile_count)
    except BaseException:
        await _cancel_tasks(pending)
        raise
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
            has_alpha = "A" in raw_tile.getbands() or "transparency" in raw_tile.info
            target_mode = "RGBA" if has_alpha else "RGB"
            try:
                tile_image, profile = prepare_tile(cropped_tile, target_mode)
            except BaseException:
                cropped_tile.close()
                raise
            if tile_image is not cropped_tile:
                cropped_tile.close()
    except ImageAssemblyError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        EOFError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ImageAssemblyError(f"invalid tile image: {col}_{row}") from exc

    return DecodedTile(col=col, row=row, image=tile_image, profile=profile)


def _image_save_kwargs(
    metadata: ImageMetadata,
    *,
    png_compression: int,
    profile: bytes | None,
) -> dict[str, object]:
    save_kwargs: dict[str, object] = {"format": metadata.pil_format}
    if metadata.pil_format == "JPEG":
        save_kwargs["quality"] = 95
    elif metadata.pil_format == "PNG":
        save_kwargs["compress_level"] = png_compression
    if profile is not None:
        save_kwargs["icc_profile"] = profile
    return save_kwargs


def _validate_codec_size(metadata: ImageMetadata) -> None:
    if (
        metadata.pil_format == "WEBP"
        and max(metadata.width, metadata.height) > WEBP_MAX_DIMENSION
    ):
        raise ImageAssemblyError(
            f"WebP image {metadata.width}x{metadata.height} exceeds "
            f"the encoder limit of {WEBP_MAX_DIMENSION} pixels per side"
        )


def _new_canvas(metadata: ImageMetadata) -> Image.Image:
    try:
        return Image.new("RGB", (metadata.width, metadata.height), "white")
    except (MemoryError, ValueError) as exc:
        raise ImageAssemblyError(
            f"failed to allocate {metadata.width}x{metadata.height} RGB canvas"
        ) from exc


def _canvas_for_tile(canvas: Image.Image, tile: Image.Image) -> Image.Image:
    if tile.mode == "RGBA" and canvas.mode == "RGB":
        upgraded_canvas = canvas.convert("RGBA")
        canvas.close()
        return upgraded_canvas
    return canvas


def _canvas_bytes(metadata: ImageMetadata, settings: DownloaderSettings) -> int:
    # Pillow uses four bytes per RGB/RGBA pixel. During an alpha upgrade both
    # canvases coexist, so reserve space for both in formats that support alpha.
    bytes_per_pixel = 4 if metadata.pil_format == "JPEG" else 8
    required = metadata.output_pixel_count() * bytes_per_pixel
    if required > settings.max_canvas_bytes:
        raise DownloadError(
            f"image canvas requires {required} bytes above budget "
            f"{settings.max_canvas_bytes}"
        )
    return required


def stitch_tiles(
    metadata: ImageMetadata,
    tiles: dict[tuple[int, int], bytes],
    output_path: Path,
    *,
    png_compression: int = DEFAULT_PNG_COMPRESSION,
    overwrite: bool = False,
) -> Path:
    if (
        not isinstance(png_compression, int)
        or isinstance(png_compression, bool)
        or not 0 <= png_compression <= 9
    ):
        raise ValueError("png_compression must be between 0 and 9")
    _validate_codec_size(metadata)
    canvas = _new_canvas(metadata)
    color = CanvasColor()

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
                    canvas = _canvas_for_tile(canvas, tile_image)
                    color.prepare(canvas, tile_image, decoded_tile.profile)
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
                overwrite=overwrite,
                **_image_save_kwargs(
                    metadata, png_compression=png_compression, profile=color.profile
                ),
            )
        except FileExistsError as exc:
            raise OutputExistsError(f"output already exists: {output_path}") from exc
        except (OSError, ValueError) as exc:
            raise ImageAssemblyError(
                f"failed to save assembled image: {output_path}"
            ) from exc
        return output_path
    finally:
        canvas.close()


class _ByteBudget:
    def __init__(self, capacity: int, description: str) -> None:
        self.capacity = capacity
        self.available = capacity
        self.description = description
        self.released = asyncio.Event()

    @asynccontextmanager
    async def reserve(self, amount: int) -> AsyncIterator[None]:
        if amount > self.capacity:
            raise DownloadError(
                f"{self.description} requires {amount} bytes "
                f"above budget {self.capacity}"
            )
        while amount > self.available:
            await self.released.wait()
        self.available -= amount
        try:
            yield
        finally:
            self.available += amount
            self.released.set()
            self.released.clear()


def _tile_buffer_reservation(
    metadata: ImageMetadata, settings: DownloaderSettings
) -> int:
    width = min(metadata.tile_size, metadata.width) + 2 * metadata.overlap
    height = min(metadata.tile_size, metadata.height) + 2 * metadata.overlap
    # Compressed body, conversion to bytes and Pillow's input stream, plus
    # the decoded source, crop, and temporary color/alpha buffers.
    return 3 * settings.max_tile_bytes + 24 * width * height


async def download_and_stitch_tiles(
    client: httpx.AsyncClient,
    metadata: ImageMetadata,
    settings: DownloaderSettings,
    output_path: Path,
    *,
    progress_callback: ProgressCallback | None = None,
    request_limiter: asyncio.Semaphore | None = None,
    tile_budget: _ByteBudget | None = None,
) -> Path:
    """Overlap the bounded transfer and decoding of individual tiles."""
    _validate_codec_size(metadata)
    _validate_output_size(metadata, settings)
    _canvas_bytes(metadata, settings)
    reserve = _tile_buffer_reservation(metadata, settings)
    budget = tile_budget or _ByteBudget(settings.max_tile_buffer_bytes, "tile buffer")
    if reserve > budget.capacity:
        raise DownloadError(
            f"tile buffer requires {reserve} bytes above budget {budget.capacity}"
        )

    canvas = _new_canvas(metadata)
    color = CanvasColor()
    positions = _tile_positions(metadata)
    limiter = request_limiter or asyncio.Semaphore(settings.concurrency)
    completed = 0

    async def worker() -> None:
        nonlocal canvas, completed
        for col, row in positions:
            async with budget.reserve(reserve):
                compressed = await _download_single_tile(
                    client, metadata, settings, col, row, request_limiter=limiter
                )
                decoding = asyncio.create_task(
                    asyncio.to_thread(_decode_tile_content, metadata, compressed)
                )
                del compressed
                try:
                    tile = await wait_for_worker(
                        decoding, discard=lambda decoded: decoded.image.close()
                    )
                finally:
                    del decoding
                try:
                    canvas = _canvas_for_tile(canvas, tile.image)
                    color.prepare(canvas, tile.image, tile.profile)
                    canvas.paste(
                        tile.image,
                        (tile.col * metadata.tile_size, tile.row * metadata.tile_size),
                    )
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, metadata.tile_count)
                finally:
                    tile.image.close()
                    del tile

    tasks = [
        asyncio.create_task(worker())
        for _ in range(min(2 * settings.concurrency, metadata.tile_count))
    ]
    try:
        await asyncio.gather(*tasks)
        try:
            save_kwargs = _image_save_kwargs(
                metadata,
                png_compression=settings.png_compression,
                profile=color.profile,
            )
            await async_atomic_output(
                output_path,
                lambda file: canvas.save(file, **save_kwargs),
                overwrite=settings.overwrite,
            )
        except FileExistsError as exc:
            raise OutputExistsError(f"output already exists: {output_path}") from exc
        except (OSError, ValueError) as exc:
            raise ImageAssemblyError(
                f"failed to save assembled image: {output_path}"
            ) from exc
        return output_path
    except BaseException:
        await _cancel_tasks(tasks)
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
    request_limiter: asyncio.Semaphore | None = None,
    tile_budget: _ByteBudget | None = None,
) -> DownloadResult:
    _validate_codec_size(metadata)
    _validate_output_size(metadata, settings)
    _canvas_bytes(metadata, settings)

    direct_output_path = await download_direct_image(
        client,
        metadata,
        settings,
        request_limiter=request_limiter,
        buffer_budget=tile_budget,
    )
    if direct_output_path:
        return DownloadResult(direct_output_path, "direct", metadata)

    output_path = output_path_for(metadata, settings.output_dir)
    stitched_path = await download_and_stitch_tiles(
        client,
        metadata,
        settings,
        output_path,
        progress_callback=progress_callback,
        request_limiter=request_limiter,
        tile_budget=tile_budget,
    )
    return DownloadResult(stitched_path, "tiles", metadata)


async def download_images(
    client: httpx.AsyncClient,
    metadatas: Sequence[ImageMetadata],
    settings: DownloaderSettings,
    *,
    progress_callback: ProgressCallback | None = None,
    outcome_callback: Callable[[DownloadOutcome], None] | None = None,
) -> list[DownloadResult]:
    """Return ordered successes or raise BatchDownloadError with every outcome."""
    metadata_list = list(metadatas)
    if not metadata_list:
        return []

    worker_count = min(settings.image_concurrency, len(metadata_list))
    request_limiter = asyncio.Semaphore(settings.concurrency)
    canvas_budget = _ByteBudget(settings.max_canvas_bytes, "image canvas")
    tile_budget = _ByteBudget(settings.max_tile_buffer_bytes, "tile buffer")
    work_items = iter(enumerate(metadata_list))
    outcomes: list[DownloadOutcome | None] = [None] * len(metadata_list)

    def record(index: int, outcome: DownloadOutcome) -> None:
        outcomes[index] = outcome
        if outcome_callback is not None:
            outcome_callback(outcome)

    async def worker() -> None:
        for index, metadata in work_items:
            try:
                async with canvas_budget.reserve(_canvas_bytes(metadata, settings)):
                    result = await download_image(
                        client,
                        metadata,
                        settings,
                        progress_callback=progress_callback,
                        request_limiter=request_limiter,
                        tile_budget=tile_budget,
                    )
            except ArtsyDownloaderError as exc:
                # A batch error can outlive the work. Do not keep failed buffers
                # or workers alive through the exception traceback.
                cause: BaseException | None = exc
                while cause is not None:
                    if cause.__traceback__ is not None:
                        traceback.clear_frames(cause.__traceback__)
                    cause = cause.__cause__
                record(index, DownloadOutcome(metadata, error=exc.with_traceback(None)))
            else:
                record(index, DownloadOutcome(metadata, result=result))

    tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        try:
            await _cancel_tasks(tasks)
        finally:
            for index, metadata in enumerate(metadata_list):
                if outcomes[index] is None:
                    record(index, DownloadOutcome(metadata))
        raise

    ordered = tuple(outcome for outcome in outcomes if outcome is not None)
    if any(outcome.error is not None for outcome in ordered):
        raise BatchDownloadError(ordered)
    return [outcome.result for outcome in ordered if outcome.result is not None]


async def download_artwork(
    url: str,
    settings: DownloaderSettings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    progress_callback: ProgressCallback | None = None,
    outcome_callback: Callable[[DownloadOutcome], None] | None = None,
) -> list[DownloadResult]:
    settings = settings or DownloaderSettings()

    if client is not None:
        metadatas = await fetch_metadatas(url, settings, client=client)
        return await download_images(
            client,
            metadatas,
            settings,
            progress_callback=progress_callback,
            outcome_callback=outcome_callback,
        )

    async with create_async_client(settings) as managed_client:
        metadatas = await fetch_metadatas(url, settings, client=managed_client)
        return await download_images(
            managed_client,
            metadatas,
            settings,
            progress_callback=progress_callback,
            outcome_callback=outcome_callback,
        )


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
