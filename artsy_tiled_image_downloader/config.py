from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from ._version import __version__
from .validation import validate_http_url

DEFAULT_USER_AGENT = f"ArtsyTiledImageDownloader/{__version__}"
DEFAULT_METAPHYSICS_ENDPOINT = "https://metaphysics-production.artsy.net/v2"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_CONCURRENCY = 24
DEFAULT_RETRIES = 3
DEFAULT_MAX_OUTPUT_PIXELS = 300_000_000
DEFAULT_MAX_TILES = 100_000
DEFAULT_MAX_TILE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_DIRECT_BYTES = 512 * 1024 * 1024
DEFAULT_PNG_COMPRESSION = 1
MAX_ALLOWED_CONCURRENCY = 64


@dataclass(frozen=True, slots=True)
class DownloaderSettings:
    output_dir: Path = DEFAULT_OUTPUT_DIR
    endpoint: str = DEFAULT_METAPHYSICS_ENDPOINT
    concurrency: int = DEFAULT_CONCURRENCY
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    retries: int = DEFAULT_RETRIES
    max_output_pixels: int = DEFAULT_MAX_OUTPUT_PIXELS
    max_tiles: int = DEFAULT_MAX_TILES
    max_tile_bytes: int = DEFAULT_MAX_TILE_BYTES
    max_direct_bytes: int = DEFAULT_MAX_DIRECT_BYTES
    png_compression: int = DEFAULT_PNG_COMPRESSION
    user_agent: str = DEFAULT_USER_AGENT
    prefer_direct: bool = True

    def __post_init__(self) -> None:
        try:
            output_dir = Path(self.output_dir).expanduser()
        except TypeError as exc:
            raise ValueError("output_dir must be a filesystem path") from exc
        if not isinstance(self.user_agent, str):
            raise ValueError("user_agent must be a string")
        object.__setattr__(self, "output_dir", output_dir)
        endpoint = validate_http_url(self.endpoint, field="endpoint")
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "user_agent", self.user_agent.strip())

        if not self.user_agent:
            raise ValueError("user_agent must not be empty")
        if not isinstance(self.concurrency, int) or isinstance(
            self.concurrency, bool
        ):
            raise ValueError("concurrency must be an integer")
        if not 1 <= self.concurrency <= MAX_ALLOWED_CONCURRENCY:
            raise ValueError(
                f"concurrency must be between 1 and {MAX_ALLOWED_CONCURRENCY}"
            )
        if (
            not isinstance(self.timeout, (int, float))
            or isinstance(self.timeout, bool)
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
        ):
            raise ValueError("timeout must be a finite number greater than 0")
        if not isinstance(self.retries, int) or isinstance(self.retries, bool):
            raise ValueError("retries must be an integer")
        if not 1 <= self.retries <= 10:
            raise ValueError("retries must be between 1 and 10")

        positive_integer_fields = {
            "max_output_pixels": self.max_output_pixels,
            "max_tiles": self.max_tiles,
            "max_tile_bytes": self.max_tile_bytes,
            "max_direct_bytes": self.max_direct_bytes,
        }
        for field_name, value in positive_integer_fields.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")

        if not isinstance(self.png_compression, int) or isinstance(
            self.png_compression, bool
        ):
            raise ValueError("png_compression must be an integer")
        if not 0 <= self.png_compression <= 9:
            raise ValueError("png_compression must be between 0 and 9")
        if not isinstance(self.prefer_direct, bool):
            raise ValueError("prefer_direct must be a boolean")


REQUEST_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
}

GRAPHQL_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/jpeg,image/png,image/*,*/*;q=0.8",
}
