from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import GRAPHQL_HEADERS, DownloaderSettings
from .exceptions import MetadataError
from .http import create_async_client, request_with_retries
from .models import ImageMetadata
from .validation import is_http_url, validate_http_url

ARTSY_HOSTS = {"artsy.net"}
MAX_ARTWORK_ID_LENGTH = 256
ARTWORK_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?$")

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
    if not isinstance(value, str):
        raise ValueError("artwork URL or slug must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("artwork URL or slug must not be empty")

    parsed_url = urlsplit(cleaned)
    is_absolute_url = bool(parsed_url.scheme or parsed_url.netloc)
    if is_absolute_url:
        validate_http_url(
            cleaned,
            field="artwork URL",
            allowed_hosts=ARTSY_HOSTS,
            allow_subdomains=True,
        )
        path = parsed_url.path
    elif cleaned.startswith("/"):
        path = parsed_url.path
    else:
        path = cleaned

    parts = [part for part in path.split("/") if part]

    if "artwork" in parts:
        artwork_index = parts.index("artwork")
        if artwork_index + 1 < len(parts):
            artwork_id = parts[artwork_index + 1]
        else:
            artwork_id = ""
    elif not is_absolute_url and len(parts) == 1:
        artwork_id = parts[0]
    else:
        artwork_id = ""

    if (
        not artwork_id
        or len(artwork_id) > MAX_ARTWORK_ID_LENGTH
        or ARTWORK_ID_PATTERN.fullmatch(artwork_id) is None
    ):
        raise ValueError(f"cannot parse artwork id from url: {value}")

    return artwork_id


def get_max_zoom_level(width: int, height: int) -> int:
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
    ):
        raise ValueError("deep zoom image width and height must be integers")
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

    if not isinstance(payload, dict):
        raise MetadataError("metadata response must be a JSON object")

    errors = payload.get("errors")
    if errors:
        if not isinstance(errors, list):
            raise MetadataError("graphql errors field is malformed")
        messages = "; ".join(
            str(error.get("message", error))
            if isinstance(error, dict)
            else str(error)
            for error in errors
        )
        raise MetadataError(f"graphql error: {messages}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise MetadataError("graphql response missing data object")

    artwork_result = data.get("artworkResult")
    if not isinstance(artwork_result, dict):
        raise MetadataError("graphql response missing artworkResult")

    if artwork_result.get("__typename") != "Artwork":
        request_error = artwork_result.get("requestError")
        status_code = (
            request_error.get("statusCode")
            if isinstance(request_error, dict)
            else None
        )
        if status_code:
            raise MetadataError(f"artwork not available, status code: {status_code}")
        typename = artwork_result.get("__typename") or "unknown"
        raise MetadataError(f"artwork not available: {typename}")

    return artwork_result


def _dedupe_urls(urls: Iterable[str | None]) -> tuple[str, ...]:
    seen: set[str] = set()
    direct_urls: list[str] = []
    for url in urls:
        if not url:
            continue
        if not is_http_url(url):
            continue
        cleaned = url.strip()
        if cleaned in seen:
            continue
        direct_urls.append(cleaned)
        seen.add(cleaned)
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
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MetadataError(f"{context} missing positive integer field: {key}")
    return value


def _require_non_negative_int(source: dict[str, Any], key: str, context: str) -> int:
    value = source.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetadataError(f"{context} missing non-negative integer field: {key}")
    return value


def _join_level_url(tile_base_url: str, max_zoom_level: int) -> str:
    try:
        base = validate_http_url(tile_base_url, field="Deep Zoom tile URL")
    except ValueError as exc:
        raise MetadataError(f"invalid Deep Zoom tile URL: {tile_base_url}") from exc
    return f"{base.rstrip('/')}/{max_zoom_level}/"


def parse_metadatas(artwork: dict[str, Any], artwork_id: str) -> list[ImageMetadata]:
    if not isinstance(artwork, dict):
        raise MetadataError("artwork metadata must be an object")
    if not isinstance(artwork_id, str) or not artwork_id:
        raise MetadataError("artwork id must be a non-empty string")

    title = str(artwork.get("slug") or artwork_id)
    figures = artwork.get("figures") or []
    direct_urls_by_internal_id, direct_urls_by_index = get_direct_urls_by_image(artwork)
    image_metadatas: list[ImageMetadata] = []

    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        if figure.get("__typename") != "Image":
            continue

        deep_zoom = figure.get("deepZoom")
        if deep_zoom is None:
            continue
        if not isinstance(deep_zoom, dict):
            raise MetadataError(f"figure {index} has malformed deepZoom")

        deep_zoom_image = deep_zoom.get("Image")
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
