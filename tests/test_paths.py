from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import artsy_tiled_image_downloader.paths as paths_module
from artsy_tiled_image_downloader.models import ImageMetadata
from artsy_tiled_image_downloader.paths import (
    atomic_save_image,
    atomic_write_bytes,
    output_path_for,
    safe_filename,
)


def test_safe_filename_removes_unsafe_characters() -> None:
    assert safe_filename(" Some / unsafe: title? ") == "Some_unsafe_title"
    assert safe_filename("...") == "artwork"
    assert len(safe_filename("a" * 200)) == 120


@pytest.mark.parametrize(
    ("value", "fallback", "message"),
    [
        (42, "artwork", "must be a string"),
        ("...", "", "non-empty"),
        ("...", "///", "safe character"),
    ],
)
def test_safe_filename_rejects_invalid_api_values(
    value: object,
    fallback: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        safe_filename(value, fallback=fallback)


def test_output_path_for_uses_safe_title_and_extension(tmp_path: Path) -> None:
    metadata = ImageMetadata(
        index=3,
        title="Title / One",
        format="jpeg",
        url="https://tiles.example/2/",
        tile_size=256,
        overlap=1,
        width=512,
        height=512,
        max_zoom_level=9,
    )

    assert output_path_for(metadata, tmp_path) == tmp_path / "output_Title_One_3.jpg"


@pytest.mark.parametrize("writer", ["bytes", "image"])
def test_atomic_writers_remove_temporary_file_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    target = tmp_path / "output.png"

    def fail_replace(*args: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(paths_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        if writer == "bytes":
            atomic_write_bytes(target, b"data")
        else:
            with Image.new("RGB", (1, 1)) as image:
                atomic_save_image(target, image, format="PNG")

    assert list(tmp_path.iterdir()) == []
