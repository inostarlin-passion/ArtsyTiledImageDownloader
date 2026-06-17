from __future__ import annotations

from pathlib import Path

from artsy_tiled_image_downloader.models import ImageMetadata
from artsy_tiled_image_downloader.paths import output_path_for, safe_filename


def test_safe_filename_removes_unsafe_characters() -> None:
    assert safe_filename(" Some / unsafe: title? ") == "Some_unsafe_title"
    assert safe_filename("...") == "artwork"


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
