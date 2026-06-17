from __future__ import annotations

import pytest

from artsy_tiled_image_downloader.exceptions import MetadataError
from artsy_tiled_image_downloader.metadata import (
    get_artwork_id,
    get_max_zoom_level,
    parse_metadatas,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://www.artsy.net/artwork/yayoi-kusama-stars-11",
            "yayoi-kusama-stars-11",
        ),
        ("https://www.artsy.net/artwork/foo?sort=bar", "foo"),
        ("/artwork/foo/", "foo"),
        ("foo", "foo"),
    ],
)
def test_get_artwork_id_accepts_url_path_or_slug(value: str, expected: str) -> None:
    assert get_artwork_id(value) == expected


@pytest.mark.parametrize("value", ["", "https://www.artsy.net/artist/foo/bar"])
def test_get_artwork_id_rejects_unparseable_input(value: str) -> None:
    with pytest.raises(ValueError):
        get_artwork_id(value)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1, 1, 0),
        (2, 1, 1),
        (3, 2, 2),
        (256, 255, 8),
        (257, 1, 9),
    ],
)
def test_get_max_zoom_level_uses_integer_boundary_math(
    width: int,
    height: int,
    expected: int,
) -> None:
    assert get_max_zoom_level(width, height) == expected


def test_parse_metadatas_builds_deep_zoom_metadata(sample_artwork_payload) -> None:
    metadata = parse_metadatas(sample_artwork_payload(), "local-test")[0]

    assert metadata.title == "local-test"
    assert metadata.url == "https://tiles.example/artwork_files/2/"
    assert metadata.rows == 2
    assert metadata.cols == 2
    assert metadata.tile_count == 4
    assert metadata.direct_urls == (
        "https://images.example/normalized.jpg",
        "https://images.example/main.jpg",
    )


def test_parse_metadatas_rejects_malformed_deep_zoom(sample_artwork_payload) -> None:
    artwork = sample_artwork_payload()
    artwork["figures"][0]["deepZoom"]["Image"]["Size"]["Width"] = 0

    with pytest.raises(MetadataError, match="Width"):
        parse_metadatas(artwork, "local-test")
