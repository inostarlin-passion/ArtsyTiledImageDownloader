from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

SUPPORTED_TILE_FORMATS = {"jpg", "jpeg", "png", "webp"}


@dataclass(frozen=True, slots=True)
class ImageMetadata:
    index: int
    title: str
    format: str
    url: str
    tile_size: int
    overlap: int
    width: int
    height: int
    max_zoom_level: int
    direct_urls: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized_format = self.format.lower().lstrip(".")
        object.__setattr__(self, "format", normalized_format)
        object.__setattr__(self, "direct_urls", tuple(self.direct_urls))

        if self.index < 0:
            raise ValueError("metadata index must not be negative")
        if not self.title:
            raise ValueError("metadata title must not be empty")
        if normalized_format not in SUPPORTED_TILE_FORMATS:
            raise ValueError(f"unsupported tile format: {self.format}")
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("tile URL must be an HTTP(S) URL")
        if self.tile_size <= 0:
            raise ValueError("tile_size must be greater than 0")
        if self.overlap < 0:
            raise ValueError("overlap must not be negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image width and height must be greater than 0")
        if self.max_zoom_level < 0:
            raise ValueError("max_zoom_level must not be negative")
        if any(
            not direct_url.startswith(("http://", "https://"))
            for direct_url in self.direct_urls
        ):
            raise ValueError("direct image URLs must be HTTP(S) URLs")

    @property
    def rows(self) -> int:
        return math.ceil(self.height / self.tile_size)

    @property
    def cols(self) -> int:
        return math.ceil(self.width / self.tile_size)

    @property
    def tile_count(self) -> int:
        return self.rows * self.cols

    @property
    def output_extension(self) -> str:
        return "jpg" if self.format == "jpeg" else self.format

    @property
    def pil_format(self) -> Literal["JPEG", "PNG", "WEBP"]:
        if self.format in {"jpg", "jpeg"}:
            return "JPEG"
        if self.format == "png":
            return "PNG"
        return "WEBP"

    def tile_url(self, col: int, row: int) -> str:
        if not 0 <= col < self.cols:
            raise ValueError(f"tile column out of range: {col}")
        if not 0 <= row < self.rows:
            raise ValueError(f"tile row out of range: {row}")
        return f"{self.url}{col}_{row}.{self.format}"

    def expected_tile_content_size(self, col: int, row: int) -> tuple[int, int]:
        if not 0 <= col < self.cols:
            raise ValueError(f"tile column out of range: {col}")
        if not 0 <= row < self.rows:
            raise ValueError(f"tile row out of range: {row}")
        width = min(self.tile_size, self.width - col * self.tile_size)
        height = min(self.tile_size, self.height - row * self.tile_size)
        return width, height

    def output_pixel_count(self) -> int:
        return self.width * self.height
