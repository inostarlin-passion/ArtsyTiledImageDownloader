from __future__ import annotations

from pathlib import Path

import pytest

from artsy_tiled_image_downloader.config import DownloaderSettings


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("output_dir", 42, "filesystem path"),
        ("endpoint", "https://", "absolute HTTP"),
        ("endpoint", "https://user:pass@example.test/v2", "credentials"),
        ("user_agent", 42, "user_agent must be a string"),
        ("user_agent", " ", "must not be empty"),
        ("concurrency", True, "concurrency"),
        ("concurrency", 65, "between 1 and 64"),
        ("timeout", False, "timeout"),
        ("retries", True, "retries"),
        ("retries", 11, "between 1 and 10"),
        ("max_output_pixels", True, "max_output_pixels"),
        ("max_tiles", 0, "max_tiles"),
        ("max_tile_bytes", 0, "max_tile_bytes"),
        ("max_direct_bytes", 0, "max_direct_bytes"),
        ("png_compression", 10, "png_compression"),
        ("png_compression", True, "png_compression must be an integer"),
        ("prefer_direct", "yes", "prefer_direct must be a boolean"),
    ],
)
def test_settings_reject_invalid_boundaries(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    kwargs = {"output_dir": tmp_path, field: value}

    with pytest.raises(ValueError, match=message):
        DownloaderSettings(**kwargs)
