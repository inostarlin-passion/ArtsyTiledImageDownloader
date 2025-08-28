import math
from urllib.parse import urlparse

import requests

import image_metadata
from config import *


ARTWORK_DEEP_ZOOM_QUERY = """
query ArtworkDeepZoomQuery($artworkID: String!) {
  artworkResult(id: $artworkID) {
    __typename
    ... on Artwork {
      slug
      images(includeAll: true) {
        internalID
        main: url(version: "main")
        normalized: url(version: "normalized")
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


def get_artwork_id(url):
    parsed_url = urlparse(url)
    path = parsed_url.path if parsed_url.scheme or parsed_url.netloc else url
    parts = [part for part in path.split("/") if part]

    if "artwork" in parts:
        artwork_index = parts.index("artwork")
        if artwork_index + 1 < len(parts):
            return parts[artwork_index + 1]

    if len(parts) == 1:
        return parts[0]

    raise ValueError(f"cannot parse artwork id from url: {url}")


def get_max_zoom_level(width, height):
    max_dimension = max(width, height)
    if max_dimension <= 0:
        raise ValueError(f"invalid deep zoom image size: {width}x{height}")
    return math.ceil(math.log2(max_dimension))


def fetch_artwork(artwork_id):
    response = requests.post(
        METAPHYSICS_ENDPOINT,
        headers=GRAPHQL_HEADERS,
        json={
            "query": ARTWORK_DEEP_ZOOM_QUERY,
            "variables": {"artworkID": artwork_id},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    if payload.get("errors"):
        messages = "; ".join(
            error.get("message", str(error)) for error in payload["errors"]
        )
        raise ValueError(f"graphql error: {messages}")

    artwork_result = payload.get("data", {}).get("artworkResult")
    if not artwork_result:
        raise ValueError("graphql response missing artworkResult")

    if artwork_result.get("__typename") != "Artwork":
        status_code = artwork_result.get("requestError", {}).get("statusCode")
        if status_code:
            raise ValueError(f"artwork not available, status code: {status_code}")
        raise ValueError(f"artwork not available: {artwork_result.get('__typename')}")

    return artwork_result


def get_direct_urls_by_image(artwork):
    direct_urls_by_internal_id = {}
    direct_urls_by_index = []

    for image in artwork.get("images", []):
        direct_urls = [
            url for url in (image.get("normalized"), image.get("main")) if url
        ]
        direct_urls_by_index.append(direct_urls)

        internal_id = image.get("internalID")
        if internal_id:
            direct_urls_by_internal_id[internal_id] = direct_urls

    return direct_urls_by_internal_id, direct_urls_by_index


def get_metadatas(url):
    artwork_id = get_artwork_id(url)
    artwork = fetch_artwork(artwork_id)
    title = artwork.get("slug") or artwork_id
    figures = artwork.get("figures", [])
    direct_urls_by_internal_id, direct_urls_by_index = get_direct_urls_by_image(artwork)
    image_metadatas = []

    for i, figure in enumerate(figures):
        if figure["__typename"] != "Image":
            continue

        deep_zoom_image = (figure.get("deepZoom") or {}).get("Image")
        if not deep_zoom_image:
            continue

        format = deep_zoom_image["Format"]
        tile_url = deep_zoom_image["Url"]
        tile_size = deep_zoom_image["TileSize"]
        overlap = deep_zoom_image.get("Overlap", 0)
        width = deep_zoom_image["Size"]["Width"]
        height = deep_zoom_image["Size"]["Height"]
        max_zoom_level = get_max_zoom_level(width, height)
        tile_url += f"{max_zoom_level}/"
        rows = math.ceil(height / tile_size)
        cols = math.ceil(width / tile_size)
        direct_urls = direct_urls_by_internal_id.get(figure.get("internalID"))
        if direct_urls is None and i < len(direct_urls_by_index):
            direct_urls = direct_urls_by_index[i]

        image_metadatas.append(
            image_metadata.ImageMetadata(
                index=i,
                title=title,
                format=format,
                url=tile_url,
                tile_size=tile_size,
                overlap=overlap,
                width=width,
                height=height,
                rows=rows,
                cols=cols,
                max_zoom_level=max_zoom_level,
                direct_urls=direct_urls,
            )
        )

    if not image_metadatas:
        raise ValueError("no deep zoom images found")

    return image_metadatas
