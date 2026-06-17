from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_USER_AGENT = "ArtsyTiledImageDownloader/2.0"
DEFAULT_METAPHYSICS_ENDPOINT = "https://metaphysics-production.artsy.net/v2"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_CONCURRENCY = 16
DEFAULT_RETRIES = 3
DEFAULT_MAX_OUTPUT_PIXELS = 300_000_000
MAX_ALLOWED_CONCURRENCY = 64


@dataclass(frozen=True, slots=True)
class DownloaderSettings:
    output_dir: Path = DEFAULT_OUTPUT_DIR
    endpoint: str = DEFAULT_METAPHYSICS_ENDPOINT
    concurrency: int = DEFAULT_CONCURRENCY
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    retries: int = DEFAULT_RETRIES
    max_output_pixels: int = DEFAULT_MAX_OUTPUT_PIXELS
    user_agent: str = DEFAULT_USER_AGENT
    prefer_direct: bool = True

    def __post_init__(self) -> None:
        output_dir = Path(self.output_dir).expanduser()
        object.__setattr__(self, "output_dir", output_dir)
        object.__setattr__(self, "endpoint", self.endpoint.strip())
        object.__setattr__(self, "user_agent", self.user_agent.strip())

        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        if not self.user_agent:
            raise ValueError("user_agent must not be empty")
        if not 1 <= self.concurrency <= MAX_ALLOWED_CONCURRENCY:
            raise ValueError(
                f"concurrency must be between 1 and {MAX_ALLOWED_CONCURRENCY}"
            )
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if not 1 <= self.retries <= 10:
            raise ValueError("retries must be between 1 and 10")
        if self.max_output_pixels <= 0:
            raise ValueError("max_output_pixels must be greater than 0")


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
