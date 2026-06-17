from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .config import (
    DEFAULT_CONCURRENCY,
    DEFAULT_MAX_OUTPUT_PIXELS,
    DEFAULT_METAPHYSICS_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    DownloaderSettings,
)
from .download import download_image
from .exceptions import ArtsyDownloaderError
from .http import create_async_client
from .metadata import fetch_metadatas


def log(message: str = "") -> None:
    print(message, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download high-resolution tiled artwork images from Artsy."
    )
    parser.add_argument("url", help="Artsy artwork URL or artwork slug")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory where output images are saved",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="maximum concurrent tile requests",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="retry attempts for transient HTTP failures",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_METAPHYSICS_ENDPOINT,
        help="Artsy Metaphysics GraphQL endpoint",
    )
    parser.add_argument(
        "--max-pixels",
        type=int,
        default=DEFAULT_MAX_OUTPUT_PIXELS,
        help="maximum stitched output pixels to allocate",
    )
    parser.add_argument(
        "--skip-direct",
        action="store_true",
        help="skip same-resolution direct image candidates and always use tiles",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="fetch and print image metadata without downloading images",
    )
    return parser


async def run_async(args: argparse.Namespace) -> int:
    settings = DownloaderSettings(
        output_dir=args.output_dir,
        endpoint=args.endpoint,
        concurrency=args.concurrency,
        timeout=args.timeout,
        retries=args.retries,
        max_output_pixels=args.max_pixels,
        prefer_direct=not args.skip_direct,
    )

    started = time.perf_counter()
    log(f"URL: {args.url}")
    log("Fetching metadata...")

    async with create_async_client(settings) as client:
        image_metadatas = await fetch_metadatas(args.url, settings, client=client)

        log(f"Images: {len(image_metadatas)}")
        for i, image_metadata in enumerate(image_metadatas, start=1):
            resolution = f"{image_metadata.width}x{image_metadata.height}"
            tile_info = (
                f"{image_metadata.rows}x{image_metadata.cols} "
                f"({image_metadata.tile_count} tiles)"
            )
            log(f"Image {i}/{len(image_metadatas)}: {resolution}, {tile_info}")

            if args.metadata_only:
                continue

            log("Downloading...")

            def on_progress(done: int, total: int) -> None:
                if done == total or done % max(1, total // 10) == 0:
                    log(f"Tiles: {done}/{total}")

            result = await download_image(
                client,
                image_metadata,
                settings,
                progress_callback=on_progress,
            )
            log(f"Saved: {result.output_path} ({result.method})")

    log(f"Elapsed: {time.perf_counter() - started:.1f}s")
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run_async(args))
    except (ArtsyDownloaderError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
