from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.system, pytest.mark.live]


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
