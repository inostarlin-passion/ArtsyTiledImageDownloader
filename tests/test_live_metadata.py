from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.metadata import fetch_metadatas

pytestmark = [pytest.mark.system, pytest.mark.live]

SAMPLE_URL = (
    "https://www.artsy.net/artwork/"
    "meguru-yamaguchi-splitting-horizon-no-dot-10-11"
)


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="set RUN_LIVE_TESTS=1 to query Artsy live metadata",
)
def test_live_metadata_smoke(project_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "artsy_tiled_image_downloader",
            "--metadata-only",
            "https://www.artsy.net/artwork/yayoi-kusama-stars-11",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Images:" in result.stdout


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="set RUN_LIVE_TESTS=1 to query Artsy live metadata",
)
def test_live_sample_metadata_matches_page_and_deep_zoom_contract() -> None:
    async def run():
        return await fetch_metadatas(SAMPLE_URL, DownloaderSettings())

    metadatas = asyncio.run(run())

    assert len(metadatas) == 6
    assert (metadatas[0].width, metadatas[0].height) == (3865, 4951)
    assert sum(metadata.tile_count for metadata in metadatas) == 207
    assert metadatas[0].direct_urls
