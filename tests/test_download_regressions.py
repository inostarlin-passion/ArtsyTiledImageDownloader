from __future__ import annotations

import ast
import asyncio
import gzip
import threading
from dataclasses import replace
from io import BytesIO

import httpx
import pytest
from PIL import Image

import artsy_tiled_image_downloader.download as downloader
from artsy_tiled_image_downloader import paths
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.exceptions import (
    DownloadError,
    MetadataError,
    ResponseTooLargeError,
)
from artsy_tiled_image_downloader.http import request_bytes_with_retries
from artsy_tiled_image_downloader.metadata import fetch_artwork, parse_metadatas
from artsy_tiled_image_downloader.models import ImageMetadata

DIRECT_URL = "https://example.test/direct"
TILE_URL = "https://example.test/tiles/"


def metadata(*, index=0, fmt="png", width=2, height=2, direct=False):
    return ImageMetadata(
        index,
        "regression",
        fmt,
        TILE_URL,
        2,
        0,
        width,
        height,
        (max(width, height) - 1).bit_length(),
        (DIRECT_URL,) if direct else (),
    )


def encode(image, fmt="PNG", **kwargs):
    with BytesIO() as buffer:
        image.save(buffer, fmt, **kwargs)
        return buffer.getvalue()


@pytest.mark.parametrize("ids", [["other"], [None], ["image-1", "image-1"]])
def test_a01_rejects_ambiguous_or_unrelated_direct_urls(sample_artwork_payload, ids):
    artwork = sample_artwork_payload()
    source = artwork["images"][0]
    artwork["images"] = [dict(source, internalID=value) for value in ids]
    result = parse_metadatas(artwork, "regression")[0]
    assert not result.direct_urls
    assert result.tile_count == 4


def test_a02_matches_id_across_order(sample_artwork_payload):
    artwork = sample_artwork_payload()
    artwork["images"].insert(0, {"internalID": "other", "main": DIRECT_URL})
    assert parse_metadatas(artwork, "regression")[0].direct_urls == (
        "https://images.example/normalized.jpg",
        "https://images.example/main.jpg",
    )


async def download_candidate(candidate, tile, tmp_path, **dimensions):
    spec = metadata(fmt="jpg", direct=True, **dimensions)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        body = candidate if request.url == DIRECT_URL else tile
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await downloader.download_image(
            client, spec, DownloaderSettings(output_dir=tmp_path)
        )
    return result, seen


def assert_decodable_jpeg(result, size=(2, 2)):
    with Image.open(result.output_path) as output:
        output.load()
        assert output.format == "JPEG"
        assert output.size == size


def test_a03_truncated_jpeg_falls_back(image_bytes, tmp_path):
    tile = image_bytes((2, 2), (255, 0, 0), "JPEG")
    start_of_scan = tile.index(b"\xff\xda")
    scan_header_length = int.from_bytes(
        tile[start_of_scan + 2 : start_of_scan + 4], "big"
    )
    truncated = tile[: start_of_scan + 2 + scan_header_length]
    result, seen = asyncio.run(download_candidate(truncated, tile, tmp_path))
    assert result.method == "tiles"
    assert len(seen) == 2
    assert_decodable_jpeg(result)


def test_a04_mismatched_format_falls_back(image_bytes, tmp_path):
    png = image_bytes((2, 2), (0, 255, 0))
    tile = image_bytes((2, 2), (255, 0, 0), "JPEG")
    result, seen = asyncio.run(download_candidate(png, tile, tmp_path))
    assert result.method == "tiles"
    assert result.output_path.suffix == ".jpg"
    assert len(seen) == 2
    assert_decodable_jpeg(result)


def test_a05_pillow_pixel_guard_falls_back(image_bytes, tmp_path, monkeypatch):
    candidate = image_bytes((4, 4), (0, 255, 0), "JPEG")
    tile = image_bytes((2, 2), (255, 0, 0), "JPEG")
    with monkeypatch.context() as patch:
        patch.setattr(Image, "MAX_IMAGE_PIXELS", 5)
        result, seen = asyncio.run(
            download_candidate(candidate, tile, tmp_path, width=4, height=4)
        )
        assert Image.MAX_IMAGE_PIXELS == 5
    assert result.method == "tiles"
    assert len(seen) == 5
    assert_decodable_jpeg(result, size=(4, 4))


def test_a06_valid_direct_is_preserved(image_bytes, tmp_path):
    jpeg = image_bytes((2, 2), (255, 0, 0), "JPEG")
    result, seen = asyncio.run(download_candidate(jpeg, jpeg, tmp_path))
    assert result.method == "direct"
    assert seen == [DIRECT_URL]
    assert result.output_path.read_bytes() == jpeg


class CountingStream(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk

    async def aclose(self):
        self.closed = True


async def read_limited(handler, *, follow_redirects=False):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
    ) as client:
        return await request_bytes_with_retries(
            client, "GET", DIRECT_URL, DownloaderSettings(), max_bytes=5
        )


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "3"}])
def test_a07_over_limit_stops_reading(headers):
    stream = CountingStream(b"123", b"456", b"789")
    with pytest.raises(ResponseTooLargeError):
        asyncio.run(
            read_limited(lambda _: httpx.Response(200, headers=headers, stream=stream))
        )
    assert stream.read == 2
    assert stream.closed


def test_a08_encoded_response_rejected_without_reading():
    stream = CountingStream(gzip.compress(b"0" * 1024))

    def handler(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=stream)

    with pytest.raises(DownloadError, match="Content-Encoding"):
        asyncio.run(read_limited(handler))
    assert stream.read == 0
    assert stream.closed


def test_a09_graphql_body_has_streaming_limit():
    stream = CountingStream(b'{"abc"', b": 123}", b" ")

    async def run():
        settings = DownloaderSettings(max_metadata_bytes=8)
        transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(MetadataError, match="byte limit"):
                await fetch_artwork(client, "regression", settings)

    asyncio.run(run())
    assert stream.read == 2
    assert stream.closed


def test_a10_redirect_body_is_not_read():
    intermediate = CountingStream(b"oversized")
    final = CountingStream(b"okay")

    def handler(request):
        if request.url == DIRECT_URL:
            return httpx.Response(
                302, headers={"Location": "/next"}, stream=intermediate
            )
        assert request.url.path == "/next"
        return httpx.Response(200, stream=final)

    assert asyncio.run(read_limited(handler, follow_redirects=True)) == b"okay"
    assert intermediate.read == 0
    assert intermediate.closed and final.closed


def test_a11_limit_settings_are_wired_through_cli(project_root):
    package = project_root / "artsy_tiled_image_downloader"
    cli = ast.parse((package / "cli.py").read_text())
    config = ast.parse((package / "config.py").read_text())
    for field in ("max_canvas_bytes", "max_metadata_bytes"):
        assert any(
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == field
            for node in ast.walk(config)
        )
        assert any(
            isinstance(node, ast.Constant)
            and node.value == "--" + field.replace("_", "-")
            for node in ast.walk(cli)
        )
        assert any(
            isinstance(node, ast.keyword)
            and node.arg == field
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == field
            for node in ast.walk(cli)
        )


def test_a12_shared_canvas_budget_blocks_third_image(
    tmp_path, image_bytes, monkeypatch
):
    tile = image_bytes((2, 2), (0, 255, 0))
    allocations = []
    active = set()
    create_canvas = downloader._new_canvas

    def monitor(spec):
        allocations.append(spec.index)
        active.add(spec.index)
        assert len(active) <= 2
        canvas = create_canvas(spec)
        close = canvas.close

        def release_canvas():
            active.remove(spec.index)
            close()

        canvas.close = release_canvas
        return canvas

    monkeypatch.setattr(downloader, "_new_canvas", monitor)

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        requests = 0

        async def handler(_):
            nonlocal requests
            requests += 1
            if requests == 2:
                entered.set()
            await release.wait()
            return httpx.Response(200, content=tile)

        settings = DownloaderSettings(output_dir=tmp_path, max_canvas_bytes=64)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(
                downloader.download_images(
                    client, [metadata(index=i) for i in range(3)], settings
                )
            )
            try:
                await asyncio.wait_for(entered.wait(), 2)
                assert allocations == [0, 1]
            finally:
                release.set()
                results = await asyncio.wait_for(task, 2)
            assert all(result.output_path.exists() for result in results)
            assert allocations == [0, 1, 2]
            assert not active

    asyncio.run(run())


def test_a13_single_canvas_over_budget_is_rejected(tmp_path, monkeypatch):
    def unexpected(*_):
        pytest.fail("unexpected allocation or HTTP request")

    monkeypatch.setattr(downloader, "_new_canvas", unexpected)

    async def run():
        settings = DownloaderSettings(output_dir=tmp_path, max_canvas_bytes=31)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(unexpected)
        ) as client:
            with pytest.raises(DownloadError, match="canvas.*budget"):
                await downloader.download_and_stitch_tiles(
                    client, metadata(), settings, tmp_path / "target.png"
                )

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


async def cancel_save(tmp_path, monkeypatch, tile, direct):
    spec = metadata(direct=direct)
    target = paths.output_path_for(spec, tmp_path)
    target.write_bytes(b"original")
    started = asyncio.Event()
    release = threading.Event()
    real_stage = paths._stage_output
    loop = asyncio.get_running_loop()
    staged = []

    def blocked_stage(*args):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        temporary = real_stage(*args)
        staged.append(temporary)
        return temporary

    monkeypatch.setattr(paths, "_stage_output", blocked_stage)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=tile))
    ) as client:
        task = asyncio.create_task(
            downloader.download_image(
                client, spec, DownloaderSettings(output_dir=tmp_path)
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 2)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            assert target.read_bytes() == b"original"
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
    assert len(staged) == 1
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_a14_direct_save_cancel_is_safe(tmp_path, monkeypatch, image_bytes):
    tile = image_bytes((2, 2), (255, 0, 0))
    asyncio.run(cancel_save(tmp_path, monkeypatch, tile, direct=True))


def test_a15_tile_save_cancel_is_safe(tmp_path, monkeypatch, image_bytes):
    tile = image_bytes((2, 2), (255, 0, 0))
    asyncio.run(cancel_save(tmp_path, monkeypatch, tile, direct=False))


@pytest.mark.parametrize("direct", [True, False])
def test_a16_successful_save_commits(tmp_path, image_bytes, direct):
    tile = image_bytes((2, 2), (255, 0, 0))
    spec = metadata(direct=direct)
    target = paths.output_path_for(spec, tmp_path)
    target.write_bytes(b"original")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=tile))
        ) as client:
            return await downloader.download_image(
                client, spec, DownloaderSettings(output_dir=tmp_path)
            )

    result = asyncio.run(run())
    assert result.method == ("direct" if direct else "tiles")
    with Image.open(target) as saved:
        assert saved.getpixel((0, 0)) == (255, 0, 0)
    assert list(tmp_path.iterdir()) == [target]


def stitch_alpha(tmp_path, transparent_tile, opaque_tile, pipeline, fmt="png"):
    spec = metadata(width=4, fmt=fmt)
    target = tmp_path / f"alpha.{fmt}"
    if pipeline:

        def handler(request):
            tile = (
                opaque_tile
                if request.url.path.split("/")[-1].startswith("0_")
                else transparent_tile
            )
            return httpx.Response(200, content=tile)

        async def run():
            settings = replace(DownloaderSettings(), concurrency=1)
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                await downloader.download_and_stitch_tiles(
                    client, spec, settings, target
                )

        asyncio.run(run())
    else:
        downloader.stitch_tiles(
            spec, {(0, 0): opaque_tile, (1, 0): transparent_tile}, target
        )
    with Image.open(target) as result:
        assert result.size == (4, 2)
        assert result.mode == "RGBA"
        return result.getpixel((0, 0)), result.getpixel((3, 0))


@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("fmt", ["png", "webp"])
def test_a17_rgba_tiles_preserve_alpha(tmp_path, pipeline, fmt):
    with Image.new("RGBA", (2, 2), (10, 20, 30, 60)) as rgba:
        transparent = encode(rgba, fmt.upper(), lossless=True)
    with Image.new("RGB", (2, 2), (100, 110, 120)) as rgb:
        opaque = encode(rgb, fmt.upper(), lossless=True)
    left, right = stitch_alpha(tmp_path, transparent, opaque, pipeline, fmt)
    assert left[3] == 255 and right[3] == 60
    if fmt == "png":
        assert left == (100, 110, 120, 255)
        assert right == (10, 20, 30, 60)


@pytest.mark.parametrize("pipeline", [False, True])
def test_a18_palette_transparency_is_preserved(tmp_path, image_bytes, pipeline):
    with Image.new("P", (2, 2)) as palette:
        transparent = encode(palette, transparency=0)
    opaque = image_bytes((2, 2), (100, 110, 120))
    left, right = stitch_alpha(tmp_path, transparent, opaque, pipeline)
    assert left == (100, 110, 120, 255)
    assert right[3] == 0
