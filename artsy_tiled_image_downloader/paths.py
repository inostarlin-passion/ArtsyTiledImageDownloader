from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
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
    identity = (
        ("artwork", metadata.artwork_id)
        if metadata.artwork_id is not None
        else ("tiles", metadata.title, metadata.url)
    )
    source = sha256(json.dumps(identity).encode("ascii")).hexdigest()[:16]
    filename = f"output_{title}_{source}_{metadata.index}.{metadata.output_extension}"
    return output_dir / filename


@contextmanager
def temporary_output(target: Path) -> Iterator[tuple[Path, BinaryIO]]:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            yield tmp_path, file
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _stage_output(target: Path, write: Callable[[BinaryIO], object]) -> Path:
    with temporary_output(target) as (temporary, file):
        write(file)
    return temporary


def commit_output(temporary: Path, target: Path, *, overwrite: bool) -> None:
    try:
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


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
    target: Path, write: Callable[[BinaryIO], object], *, overwrite: bool = True
) -> None:
    task = asyncio.create_task(asyncio.to_thread(_stage_output, target, write))
    temporary = await wait_for_worker(
        task,
        discard=lambda path: path.unlink(missing_ok=True),
    )
    commit_output(temporary, target, overwrite=overwrite)


def atomic_write_bytes(target: Path, data: bytes) -> None:
    temporary = _stage_output(target, lambda file: file.write(data))
    commit_output(temporary, target, overwrite=True)


def atomic_save_image(
    target: Path, image: Image.Image, *, overwrite: bool = True, **save_kwargs: object
) -> None:
    temporary = _stage_output(target, lambda file: image.save(file, **save_kwargs))
    commit_output(temporary, target, overwrite=overwrite)
