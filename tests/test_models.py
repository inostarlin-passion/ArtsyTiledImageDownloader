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
