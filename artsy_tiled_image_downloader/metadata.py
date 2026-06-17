from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import GRAPHQL_HEADERS, DownloaderSettings
from .exceptions import MetadataError
from .http import create_async_client, request_with_retries
from .models import ImageMetadata

ARTWORK_DEEP_ZOOM_QUERY = """
query ArtworkDeepZoomQuery($artworkID: String!) {
  artworkResult(id: $artworkID) {
    __typename
    ... on Artwork {
      slug
      images(includeAll: true) {
        internalID
        normalized: url(version: ["normalized"])
        larger: url(version: ["larger"])
        large: url(version: ["large"])
        main: url(version: ["main"])
      }
      figures(includeAll: true) {
        __typename
        ... on Image {
          internalID
          isZoomable
          deepZoom {
            Image {
              Url
              Format
              TileSize
              Overlap
              Size {
                Width
                Height
              }
            }
          }
        }
      }
    }
    ... on ArtworkError {
      requestError {
        statusCode
      }
    }
  }
}
"""


def get_artwork_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("artwork URL or slug must not be empty")

    parsed_url = urlparse(cleaned)
    path = parsed_url.path if parsed_url.scheme or parsed_url.netloc else cleaned
    parts = [part for part in path.split("/") if part]

    if "artwork" in parts:
        artwork_index = parts.index("artwork")
        if artwork_index + 1 < len(parts):
            return parts[artwork_index + 1]

    if len(parts) == 1:
        return parts[0]

    raise ValueError(f"cannot parse artwork id from url: {value}")


def get_max_zoom_level(width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid deep zoom image size: {width}x{height}")
    return (max(width, height) - 1).bit_length()


async def fetch_artwork(
    client: httpx.AsyncClient,
    artwork_id: str,
    settings: DownloaderSettings,
) -> dict[str, Any]:
    try:
        response = await request_with_retries(
            client,
            "POST",
            settings.endpoint,
            settings,
            headers=GRAPHQL_HEADERS,
            json={
                "query": ARTWORK_DEEP_ZOOM_QUERY,
                "variables": {"artworkID": artwork_id},
            },
        )
    except httpx.HTTPError as exc:
        raise MetadataError(f"failed to fetch artwork metadata: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise MetadataError("metadata response is not valid JSON") from exc

    errors = payload.get("errors")
    if errors:
        messages = "; ".join(error.get("message", str(error)) for error in errors)
        raise MetadataError(f"graphql error: {messages}")

    artwork_result = payload.get("data", {}).get("artworkResult")
    if not isinstance(artwork_result, dict):
        raise MetadataError("graphql response missing artworkResult")

    if artwork_result.get("__typename") != "Artwork":
        status_code = (artwork_result.get("requestError") or {}).get("statusCode")
        if status_code:
            raise MetadataError(f"artwork not available, status code: {status_code}")
        typename = artwork_result.get("__typename") or "unknown"
        raise MetadataError(f"artwork not available: {typename}")

    return artwork_result


def _dedupe_urls(urls: Iterable[str | None]) -> tuple[str, ...]:
    seen: set[str] = set()
    direct_urls: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        direct_urls.append(url)
        seen.add(url)
    return tuple(direct_urls)


def get_direct_urls_by_image(
    artwork: dict[str, Any],
) -> tuple[dict[str, tuple[str, ...]], list[tuple[str, ...]]]:
    direct_urls_by_internal_id: dict[str, tuple[str, ...]] = {}
    direct_urls_by_index: list[tuple[str, ...]] = []

    for image in artwork.get("images") or []:
        if not isinstance(image, dict):
            continue
        direct_urls = _dedupe_urls(
            (
                image.get("normalized"),
                image.get("larger"),
                image.get("large"),
                image.get("main"),
            )
        )
        direct_urls_by_index.append(direct_urls)

        internal_id = image.get("internalID")
        if internal_id:
            direct_urls_by_internal_id[str(internal_id)] = direct_urls

    return direct_urls_by_internal_id, direct_urls_by_index


def _require_positive_int(source: dict[str, Any], key: str, context: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or value <= 0:
        raise MetadataError(f"{context} missing positive integer field: {key}")
    return value


def _require_non_negative_int(source: dict[str, Any], key: str, context: str) -> int:
    value = source.get(key, 0)
    if not isinstance(value, int) or value < 0:
        raise MetadataError(f"{context} missing non-negative integer field: {key}")
    return value


def _join_level_url(tile_base_url: str, max_zoom_level: int) -> str:
    base = tile_base_url.strip()
    if not base.startswith(("http://", "https://")):
        raise MetadataError(f"invalid Deep Zoom tile URL: {tile_base_url}")
    return f"{base.rstrip('/')}/{max_zoom_level}/"


def parse_metadatas(artwork: dict[str, Any], artwork_id: str) -> list[ImageMetadata]:
    title = str(artwork.get("slug") or artwork_id)
    figures = artwork.get("figures") or []
    direct_urls_by_internal_id, direct_urls_by_index = get_direct_urls_by_image(artwork)
    image_metadatas: list[ImageMetadata] = []

    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        if figure.get("__typename") != "Image":
            continue

        deep_zoom_image = (figure.get("deepZoom") or {}).get("Image")
        if not deep_zoom_image:
            continue
        if not isinstance(deep_zoom_image, dict):
            raise MetadataError(f"figure {index} has malformed deepZoom.Image")

        size = deep_zoom_image.get("Size")
        if not isinstance(size, dict):
            raise MetadataError(f"figure {index} has malformed Deep Zoom size")

        width = _require_positive_int(size, "Width", f"figure {index}")
        height = _require_positive_int(size, "Height", f"figure {index}")
        tile_size = _require_positive_int(
            deep_zoom_image, "TileSize", f"figure {index}"
        )
        overlap = _require_non_negative_int(
            deep_zoom_image, "Overlap", f"figure {index}"
        )
        image_format = deep_zoom_image.get("Format")
        tile_base_url = deep_zoom_image.get("Url")
        if not isinstance(image_format, str) or not image_format.strip():
            raise MetadataError(f"figure {index} missing Deep Zoom format")
        if not isinstance(tile_base_url, str) or not tile_base_url.strip():
            raise MetadataError(f"figure {index} missing Deep Zoom tile URL")

        max_zoom_level = get_max_zoom_level(width, height)
        direct_urls = direct_urls_by_internal_id.get(str(figure.get("internalID")))
        if direct_urls is None and index < len(direct_urls_by_index):
            direct_urls = direct_urls_by_index[index]

        try:
            image_metadatas.append(
                ImageMetadata(
                    index=index,
                    title=title,
                    format=image_format,
                    url=_join_level_url(tile_base_url, max_zoom_level),
                    tile_size=tile_size,
                    overlap=overlap,
                    width=width,
                    height=height,
                    max_zoom_level=max_zoom_level,
                    direct_urls=direct_urls or (),
                )
            )
        except ValueError as exc:
            raise MetadataError(f"figure {index} metadata is invalid: {exc}") from exc

    if not image_metadatas:
        raise MetadataError("no deep zoom images found")

    return image_metadatas


async def fetch_metadatas(
    url: str,
    settings: DownloaderSettings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ImageMetadata]:
    settings = settings or DownloaderSettings()
    artwork_id = get_artwork_id(url)

    if client is not None:
        artwork = await fetch_artwork(client, artwork_id, settings)
        return parse_metadatas(artwork, artwork_id)

    async with create_async_client(settings) as managed_client:
        artwork = await fetch_artwork(managed_client, artwork_id, settings)
        return parse_metadatas(artwork, artwork_id)


def get_metadatas(
    url: str,
    settings: DownloaderSettings | None = None,
) -> list[ImageMetadata]:
    return asyncio.run(fetch_metadatas(url, settings))
