from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from .validation import parse_http_url, validate_http_url

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
        if not isinstance(self.format, str):
            raise ValueError("format must be a string")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("metadata title must not be empty")
        if isinstance(self.direct_urls, str):
            raise ValueError("direct image URLs must be a collection of URLs")
        try:
            direct_urls = tuple(self.direct_urls)
        except TypeError as exc:
            raise ValueError("direct image URLs must be a collection of URLs") from exc

        normalized_format = self.format.lower().lstrip(".")
        object.__setattr__(self, "format", normalized_format)
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "direct_urls", direct_urls)

        if not isinstance(self.index, int) or isinstance(self.index, bool):
            raise ValueError("metadata index must be an integer")
        if self.index < 0:
            raise ValueError("metadata index must not be negative")
        if normalized_format not in SUPPORTED_TILE_FORMATS:
            raise ValueError(f"unsupported tile format: {self.format}")
        tile_url = validate_http_url(self.url, field="tile URL")
        if parse_http_url(tile_url, field="tile URL").query:
            raise ValueError("tile URL must not contain a query string")
        object.__setattr__(self, "url", f"{tile_url.rstrip('/')}/")
        integer_fields = {
            "tile_size": self.tile_size,
            "overlap": self.overlap,
            "width": self.width,
            "height": self.height,
            "max_zoom_level": self.max_zoom_level,
        }
        for field_name, value in integer_fields.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{field_name} must be an integer")

        if self.tile_size <= 0:
            raise ValueError("tile_size must be greater than 0")
        if self.overlap < 0:
            raise ValueError("overlap must not be negative")
        if self.overlap > self.tile_size:
            raise ValueError("overlap must not exceed tile_size")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image width and height must be greater than 0")
        if self.max_zoom_level < 0:
            raise ValueError("max_zoom_level must not be negative")
        expected_zoom_level = (max(self.width, self.height) - 1).bit_length()
        if self.max_zoom_level != expected_zoom_level:
            raise ValueError(
                f"max_zoom_level must be {expected_zoom_level} for "
                f"{self.width}x{self.height}"
            )
        normalized_direct_urls: list[str] = []
        for direct_url in self.direct_urls:
            try:
                normalized_direct_urls.append(
                    validate_http_url(direct_url, field="direct image URL")
                )
            except ValueError as exc:
                message = "direct image URLs must be valid HTTP(S) URLs"
                raise ValueError(message) from exc
        object.__setattr__(self, "direct_urls", tuple(normalized_direct_urls))

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

    def expected_tile_size(self, col: int, row: int) -> tuple[int, int]:
        """Return encoded DZI tile dimensions, including edge-aware overlap."""
        content_width, content_height = self.expected_tile_content_size(col, row)
        horizontal_overlap = self.overlap * int(col > 0)
        horizontal_overlap += self.overlap * int(col < self.cols - 1)
        vertical_overlap = self.overlap * int(row > 0)
        vertical_overlap += self.overlap * int(row < self.rows - 1)
        return (
            content_width + horizontal_overlap,
            content_height + vertical_overlap,
        )

    def output_pixel_count(self) -> int:
        return self.width * self.height
