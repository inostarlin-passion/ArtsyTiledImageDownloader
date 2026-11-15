from __future__ import annotations

import asyncio
import os

import pytest
from PIL import Image

from artsy_tiled_image_downloader import DownloaderSettings, download_artwork

pytestmark = [
    pytest.mark.system,
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="set RUN_LIVE_TESTS=1 to download an Artsy sample through both paths",
    ),
]

SAMPLE_URL = "https://www.artsy.net/artwork/yayoi-kusama-stars-11"


def test_r18_artsy_live_download_decodes_direct_and_tiles(tmp_path):
    async def run():
        sizes = []
        for method in ("direct", "tiles"):
            config = DownloaderSettings(
                output_dir=tmp_path / method,
                prefer_direct=(method == "direct"),
                concurrency=8,
                timeout=15,
                retries=2,
            )
            [result] = await download_artwork(SAMPLE_URL, config)
            assert result.method == method
            with Image.open(result.output_path) as image:
                image.load()
                assert image.size == (result.metadata.width, result.metadata.height)
                assert min(image.size) > 1
                sizes.append(image.size)
        assert sizes[0] == sizes[1]

    asyncio.run(asyncio.wait_for(run(), timeout=100))
