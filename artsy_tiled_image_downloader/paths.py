from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from PIL import Image

from .models import ImageMetadata


def safe_filename(value: str, *, fallback: str = "artwork") -> str:
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return filename or fallback


def output_path_for(metadata: ImageMetadata, output_dir: Path) -> Path:
    title = safe_filename(metadata.title)
    filename = f"output_{title}_{metadata.index}.{metadata.output_extension}"
    return output_dir / filename


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_save_image(target: Path, image: Image.Image, **save_kwargs: object) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        image.save(tmp_path, **save_kwargs)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
