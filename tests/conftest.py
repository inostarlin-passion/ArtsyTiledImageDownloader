from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def image_bytes():
    def _make(
        size: tuple[int, int],
        color: tuple[int, int, int],
        image_format: str = "PNG",
    ) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", size, color).save(buffer, format=image_format)
        return buffer.getvalue()

    return _make


@pytest.fixture
def sample_artwork_payload():
    def _make(tile_base_url: str = "https://tiles.example/artwork_files/") -> dict:
        return {
            "__typename": "Artwork",
            "slug": "local-test",
            "images": [
                {
                    "internalID": "image-1",
                    "normalized": "https://images.example/normalized.jpg",
                    "larger": None,
                    "large": None,
                    "main": "https://images.example/main.jpg",
                }
            ],
            "figures": [
                {
                    "__typename": "Image",
                    "internalID": "image-1",
                    "isZoomable": True,
                    "deepZoom": {
                        "Image": {
                            "Url": tile_base_url,
                            "Format": "png",
                            "TileSize": 2,
                            "Overlap": 1,
                            "Size": {"Width": 4, "Height": 4},
                        }
                    },
                }
            ],
        }

    return _make


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]
