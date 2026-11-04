from __future__ import annotations

import asyncio
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, TypeVar

from PIL import Image

from .models import ImageMetadata

MAX_FILENAME_COMPONENT_LENGTH = 120


def safe_filename(value: str, *, fallback: str = "artwork") -> str:
    if not isinstance(value, str):
        raise ValueError("filename value must be a string")
    if not isinstance(fallback, str) or not fallback:
        raise ValueError("filename fallback must be a non-empty string")
    safe_fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._")
    if not safe_fallback:
        raise ValueError("filename fallback must contain a safe character")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    filename = filename[:MAX_FILENAME_COMPONENT_LENGTH].rstrip("._")
    return filename or safe_fallback[:MAX_FILENAME_COMPONENT_LENGTH]


def output_path_for(metadata: ImageMetadata, output_dir: Path) -> Path:
    title = safe_filename(metadata.title)
    filename = f"output_{title}_{metadata.index}.{metadata.output_extension}"
    return output_dir / filename


def _stage_output(target: Path, write: Callable[[BinaryIO], object]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            write(file)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


def _commit_output(temporary: Path, target: Path) -> None:
    try:
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


T = TypeVar("T")


async def wait_for_worker(
    task: asyncio.Future[T], *, discard: Callable[[T], object] | None = None
) -> T:
    """Keep resources owned by the caller alive until its worker has stopped."""
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled() and task.exception() is None and discard is not None:
            discard(task.result())
        raise


async def async_atomic_output(
    target: Path, write: Callable[[BinaryIO], object]
) -> None:
    task = asyncio.create_task(asyncio.to_thread(_stage_output, target, write))
    temporary = await wait_for_worker(
        task,
        discard=lambda path: path.unlink(missing_ok=True),
    )
    _commit_output(temporary, target)


def atomic_write_bytes(target: Path, data: bytes) -> None:
    temporary = _stage_output(target, lambda file: file.write(data))
    _commit_output(temporary, target)


def atomic_save_image(target: Path, image: Image.Image, **save_kwargs: object) -> None:
    temporary = _stage_output(target, lambda file: image.save(file, **save_kwargs))
    _commit_output(temporary, target)
