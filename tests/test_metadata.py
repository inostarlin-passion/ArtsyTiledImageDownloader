from __future__ import annotations

import asyncio

import httpx
import pytest

import artsy_tiled_image_downloader.metadata as metadata_module
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.exceptions import MetadataError
from artsy_tiled_image_downloader.metadata import (
    fetch_artwork,
    fetch_metadatas,
    get_artwork_id,
    get_max_zoom_level,
    get_metadatas,
    parse_metadatas,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://www.artsy.net/artwork/yayoi-kusama-stars-11",
            "yayoi-kusama-stars-11",
        ),
        ("https://www.artsy.net/artwork/foo?sort=bar", "foo"),
        ("/artwork/foo/", "foo"),
        ("foo", "foo"),
    ],
)
def test_get_artwork_id_accepts_url_path_or_slug(value: str, expected: str) -> None:
    assert get_artwork_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://www.artsy.net/artist/foo/bar",
        "https://www.artsy.net/foo",
        "https://example.com/artwork/foo",
        "foo?bar",
        "a" * 257,
    ],
)
def test_get_artwork_id_rejects_unparseable_input(value: str) -> None:
    with pytest.raises(ValueError):
        get_artwork_id(value)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1, 1, 0),
        (2, 1, 1),
        (3, 2, 2),
        (256, 255, 8),
        (257, 1, 9),
    ],
)
def test_get_max_zoom_level_uses_integer_boundary_math(
    width: int,
    height: int,
    expected: int,
) -> None:
    assert get_max_zoom_level(width, height) == expected


def test_parse_metadatas_builds_deep_zoom_metadata(sample_artwork_payload) -> None:
    metadata = parse_metadatas(sample_artwork_payload(), "local-test")[0]

    assert metadata.title == "local-test"
    assert metadata.url == "https://tiles.example/artwork_files/2/"
    assert metadata.rows == 2
    assert metadata.cols == 2
    assert metadata.tile_count == 4
    assert metadata.direct_urls == (
        "https://images.example/normalized.jpg",
        "https://images.example/main.jpg",
    )


def test_parse_metadatas_rejects_malformed_deep_zoom(sample_artwork_payload) -> None:
    artwork = sample_artwork_payload()
    artwork["figures"][0]["deepZoom"]["Image"]["Size"]["Width"] = 0

    with pytest.raises(MetadataError, match="Width"):
        parse_metadatas(artwork, "local-test")


def test_parse_metadatas_ignores_non_http_direct_urls(sample_artwork_payload) -> None:
    artwork = sample_artwork_payload()
    artwork["images"][0]["normalized"] = "file:///tmp/image.jpg"

    metadata = parse_metadatas(artwork, "local-test")[0]

    assert metadata.direct_urls == ("https://images.example/main.jpg",)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "JSON object"),
        ({"errors": "bad"}, "errors field is malformed"),
        ({"errors": [{"message": "bad query"}]}, "graphql error: bad query"),
        ({}, "missing data object"),
        ({"data": []}, "missing data object"),
        ({"data": {}}, "missing artworkResult"),
        (
            {
                "data": {
                    "artworkResult": {
                        "__typename": "ArtworkError",
                        "requestError": {"statusCode": 404},
                    }
                }
            },
            "status code: 404",
        ),
        (
            {"data": {"artworkResult": {"__typename": "OtherError"}}},
            "OtherError",
        ),
    ],
)
def test_fetch_artwork_rejects_malformed_or_error_payloads(
    tmp_path,
    payload: object,
    message: str,
) -> None:
    settings = DownloaderSettings(
        output_dir=tmp_path,
        endpoint="https://metadata.example/graphql",
        retries=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with metadata_module.create_async_client(
            settings,
            transport=transport,
        ) as client:
            with pytest.raises(MetadataError, match=message):
                await fetch_artwork(client, "local-test", settings)

    asyncio.run(run())


def test_fetch_artwork_wraps_http_and_invalid_json_errors(tmp_path) -> None:
    settings = DownloaderSettings(
        output_dir=tmp_path,
        endpoint="https://metadata.example/graphql",
        retries=1,
    )

    async def assert_failure(response: httpx.Response, message: str) -> None:
        transport = httpx.MockTransport(lambda _: response)
        async with metadata_module.create_async_client(
            settings,
            transport=transport,
        ) as client:
            with pytest.raises(MetadataError, match=message):
                await fetch_artwork(client, "local-test", settings)

    asyncio.run(
        assert_failure(
            httpx.Response(400, request=httpx.Request("POST", settings.endpoint)),
            "failed to fetch",
        )
    )
    asyncio.run(
        assert_failure(
            httpx.Response(
                200,
                content=b"not-json",
                request=httpx.Request("POST", settings.endpoint),
            ),
            "not valid JSON",
        )
    )


def test_fetch_metadatas_with_client_and_sync_wrapper(
    tmp_path,
    sample_artwork_payload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artwork = sample_artwork_payload()
    response_payload = {"data": {"artworkResult": artwork}}
    settings = DownloaderSettings(
        output_dir=tmp_path,
        endpoint="https://metadata.example/graphql",
    )

    async def run() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=response_payload,
                request=request,
            )
        )
        async with metadata_module.create_async_client(
            settings,
            transport=transport,
        ) as client:
            result = await fetch_metadatas("local-test", settings, client=client)
        assert result[0].title == "local-test"

    asyncio.run(run())

    async def fake_fetch(*args: object, **kwargs: object):
        del args, kwargs
        return [metadata_module.parse_metadatas(artwork, "local-test")[0]]

    monkeypatch.setattr(metadata_module, "fetch_metadatas", fake_fetch)
    assert get_metadatas("local-test", settings)[0].title == "local-test"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda artwork: artwork.update(figures=[None]), "no deep zoom"),
        (
            lambda artwork: artwork["figures"][0].update(deepZoom="bad"),
            "malformed deepZoom",
        ),
        (
            lambda artwork: artwork["figures"][0].update(
                deepZoom={"Image": "bad"}
            ),
            "malformed deepZoom.Image",
        ),
        (
            lambda artwork: artwork["figures"][0]["deepZoom"]["Image"].pop(
                "Size"
            ),
            "malformed Deep Zoom size",
        ),
        (
            lambda artwork: artwork["figures"][0]["deepZoom"]["Image"].update(
                Format=""
            ),
            "missing Deep Zoom format",
        ),
        (
            lambda artwork: artwork["figures"][0]["deepZoom"]["Image"].update(
                Url="file:///tmp/tiles"
            ),
            "invalid Deep Zoom tile URL",
        ),
        (
            lambda artwork: artwork["figures"][0]["deepZoom"]["Image"].update(
                Overlap=3
            ),
            "overlap must not exceed",
        ),
    ],
)
def test_parse_metadatas_rejects_malformed_nested_fields(
    sample_artwork_payload,
    mutator,
    message: str,
) -> None:
    artwork = sample_artwork_payload()
    mutator(artwork)

    with pytest.raises(MetadataError, match=message):
        parse_metadatas(artwork, "local-test")
