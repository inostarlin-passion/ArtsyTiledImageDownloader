from __future__ import annotations

import pytest

from artsy_tiled_image_downloader.models import ImageMetadata


def test_image_metadata_rejects_non_http_direct_urls() -> None:
    with pytest.raises(ValueError, match="direct image URLs"):
        ImageMetadata(
            index=0,
            title="local-test",
            format="png",
            url="https://tiles.example/2/",
            tile_size=256,
            overlap=1,
            width=512,
            height=512,
            max_zoom_level=9,
            direct_urls=("file:///tmp/image.png",),
        )


def test_expected_tile_size_includes_only_available_overlap() -> None:
    metadata = ImageMetadata(
        index=0,
        title="local-test",
        format="png",
        url="https://tiles.example/3/",
        tile_size=2,
        overlap=1,
        width=5,
        height=3,
        max_zoom_level=3,
    )

    assert metadata.expected_tile_size(0, 0) == (3, 3)
    assert metadata.expected_tile_size(1, 0) == (4, 3)
    assert metadata.expected_tile_size(2, 0) == (2, 3)
    assert metadata.expected_tile_size(1, 1) == (4, 2)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tile_size", True, "tile_size"),
        ("overlap", 3, "overlap"),
        ("width", True, "width must be an integer"),
    ],
)
def test_image_metadata_rejects_boolean_and_overlap_boundaries(
    field: str,
    value: object,
    message: str,
) -> None:
    values = {
        "index": 0,
        "title": "local-test",
        "format": "png",
        "url": "https://tiles.example/3/",
        "tile_size": 2,
        "overlap": 1,
        "width": 5,
        "height": 3,
        "max_zoom_level": 3,
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        ImageMetadata(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("format", None, "format must be a string"),
        ("format", "gif", "unsupported"),
        ("title", " ", "title must not be empty"),
        ("direct_urls", "https://example.test/a.png", "collection"),
        ("direct_urls", None, "collection"),
        ("index", True, "index must be an integer"),
        ("index", -1, "must not be negative"),
        ("tile_size", 0, "tile_size must be greater"),
        ("overlap", -1, "overlap must not be negative"),
        ("width", 0, "width and height"),
        ("max_zoom_level", -1, "must not be negative"),
        ("max_zoom_level", 2, "must be 3"),
    ],
)
def test_image_metadata_rejects_invalid_api_values(
    field: str,
    value: object,
    message: str,
) -> None:
    values = {
        "index": 0,
        "title": "local-test",
        "format": "png",
        "url": "https://tiles.example/3/",
        "tile_size": 2,
        "overlap": 1,
        "width": 5,
        "height": 3,
        "max_zoom_level": 3,
        "direct_urls": (),
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        ImageMetadata(**values)


def test_image_metadata_format_and_coordinate_boundaries() -> None:
    jpeg = ImageMetadata(
        index=0,
        title="jpeg",
        format="jpeg",
        url="https://tiles.example/0/",
        tile_size=1,
        overlap=0,
        width=1,
        height=1,
        max_zoom_level=0,
    )
    webp = ImageMetadata(
        index=0,
        title="webp",
        format="webp",
        url="https://tiles.example/0/",
        tile_size=1,
        overlap=0,
        width=1,
        height=1,
        max_zoom_level=0,
    )

    assert jpeg.output_extension == "jpg"
    assert jpeg.pil_format == "JPEG"
    assert webp.pil_format == "WEBP"

    with pytest.raises(ValueError, match="column out of range"):
        jpeg.tile_url(1, 0)
    with pytest.raises(ValueError, match="row out of range"):
        jpeg.tile_url(0, 1)
    with pytest.raises(ValueError, match="column out of range"):
        jpeg.expected_tile_content_size(-1, 0)
    with pytest.raises(ValueError, match="row out of range"):
        jpeg.expected_tile_content_size(0, -1)


def test_image_metadata_normalizes_urls_and_rejects_tile_query() -> None:
    metadata = ImageMetadata(
        index=0,
        title="normalized",
        format="png",
        url="https://tiles.example/0",
        tile_size=1,
        overlap=0,
        width=1,
        height=1,
        max_zoom_level=0,
        direct_urls=(" https://images.example/direct.png ",),
    )

    assert metadata.url == "https://tiles.example/0/"
    assert metadata.direct_urls == ("https://images.example/direct.png",)

    with pytest.raises(ValueError, match="query string"):
        ImageMetadata(
            index=0,
            title="bad-query",
            format="png",
            url="https://tiles.example/0/?token=secret",
            tile_size=1,
            overlap=0,
            width=1,
            height=1,
            max_zoom_level=0,
        )
