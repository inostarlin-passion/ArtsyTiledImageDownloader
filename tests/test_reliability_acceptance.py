from __future__ import annotations

import asyncio
import struct
import threading
import tracemalloc
from dataclasses import replace
from io import BytesIO

import httpx
import pytest
from PIL import Image, ImageCms

from artsy_tiled_image_downloader import cli, download
from artsy_tiled_image_downloader.config import DownloaderSettings
from artsy_tiled_image_downloader.exceptions import (
    ArtsyDownloaderError,
    DownloadError,
    ImageAssemblyError,
)
from artsy_tiled_image_downloader.models import ImageMetadata
from artsy_tiled_image_downloader.paths import output_path_for


def metadata(name="artwork", *, index=0, size=(1, 1), fmt="png", direct=False):
    width, height = size
    return ImageMetadata(
        index,
        name,
        fmt,
        f"https://fixture.test/tiles/{index}/",
        min(8192, max(width, height)),
        0,
        width,
        height,
        (max(width, height) - 1).bit_length(),
        ("https://fixture.test/direct",) if direct else (),
    )


def settings(tmp_path, **kwargs):
    return DownloaderSettings(output_dir=tmp_path, **kwargs)


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def encoded(color, *, size=(1, 1), fmt="PNG", **options):
    with Image.new("RGBA" if len(color) == 4 else "RGB", size, color) as image:
        with BytesIO() as buffer:
            image.save(buffer, fmt, **options)
            return buffer.getvalue()


def pixel(path):
    with Image.open(path) as image:
        return image.getpixel((0, 0))


@pytest.mark.parametrize("upstream_identity", [False, True])
def test_r01_distinct_sources_survive_filename_truncation(tmp_path, upstream_identity):
    first = replace(
        metadata("a" * 120 + "-red"),
        artwork_id="artwork-a" if upstream_identity else None,
    )
    second = replace(
        first,
        title="a" * 120 + "-blue",
        artwork_id="artwork-b" if upstream_identity else None,
        url="https://fixture.test/blue/",
    )

    def respond(request):
        color = (0, 0, 255) if "/blue/" in request.url.path else (255, 0, 0)
        return httpx.Response(200, content=encoded(color))

    async def run():
        async with client(respond) as http:
            return await download.download_images(
                http, [first, second], settings(tmp_path)
            )

    results = asyncio.run(run())
    paths = [result.output_path for result in results]
    assert paths == [output_path_for(spec, tmp_path) for spec in (first, second)]
    assert len(set(paths)) == 2
    assert [pixel(path) for path in paths] == [(255, 0, 0), (0, 0, 255)]
    assert set(tmp_path.iterdir()) == set(paths)


def test_r02_default_publish_has_one_winner_in_a_race(tmp_path):
    colors = [(255, 0, 0), (0, 0, 255)]

    async def run():
        both_started = asyncio.Event()
        count = 0

        async def respond(color):
            nonlocal count
            count += 1
            if count == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            return httpx.Response(200, content=encoded(color))

        async def publish(color):
            async def handler(_):
                return await respond(color)

            async with client(handler) as http:
                return await download.download_image(
                    http, metadata(), settings(tmp_path)
                )

        return await asyncio.gather(
            *(publish(color) for color in colors), return_exceptions=True
        )

    results = asyncio.run(run())
    failures = [result for result in results if isinstance(result, DownloadError)]
    assert len(failures) == 1
    assert "already exists" in str(failures[0])
    [(saved, color)] = [
        (result, color)
        for result, color in zip(results, colors, strict=True)
        if isinstance(result, download.DownloadResult)
    ]
    assert list(tmp_path.iterdir()) == [saved.output_path]
    assert pixel(saved.output_path) == color


@pytest.mark.parametrize("direct", [False, True])
def test_r03_only_explicit_overwrite_replaces_output(tmp_path, direct):
    spec = metadata(direct=direct)
    target = output_path_for(spec, tmp_path)
    target.write_bytes(b"original")
    new = encoded((0, 255, 0))

    async def run():
        async with client(lambda _: httpx.Response(200, content=new)) as http:
            with pytest.raises(DownloadError, match="already exists"):
                await download.download_image(http, spec, settings(tmp_path))
            assert target.read_bytes() == b"original"
            await download.download_image(
                http, spec, settings(tmp_path, overwrite=True)
            )

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == [target]
    assert pixel(target) == (0, 255, 0)


def batch_response(request):
    if "/1/" in request.url.path:
        return httpx.Response(404)
    return httpx.Response(200, content=encoded((0, 255, 0)))


def test_r04_batch_error_contains_all_ordered_outcomes(tmp_path):
    specs = [metadata(index=i) for i in range(3)]
    seen = []

    async def run():
        async with client(batch_response) as http:
            with pytest.raises(DownloadError) as error:
                await download.download_images(
                    http,
                    specs,
                    settings(tmp_path, image_concurrency=1),
                    outcome_callback=seen.append,
                )
        return error.value

    error = asyncio.run(run())
    assert error.outcomes == tuple(seen)
    assert [item.metadata for item in seen] == specs
    assert [item.status for item in seen] == ["saved", "failed", "saved"]
    assert "404" in str(seen[1].error)
    assert {item.result.output_path for item in seen if item.result} == set(
        tmp_path.iterdir()
    )


def test_r05_cli_reports_each_result_and_partial_exit(tmp_path, monkeypatch, capsys):
    captured = []

    def respond(request):
        if "/2/" in request.url.path:
            captured.append(capsys.readouterr())
            assert "Saved:" in captured[-1].out
        return batch_response(request)

    async def fetch(*args, **kwargs):
        return [metadata(index=i) for i in range(3)]

    monkeypatch.setattr(cli, "create_async_client", lambda _: client(respond))
    monkeypatch.setattr(cli, "fetch_metadatas", fetch)
    assert cli.run(["--image-concurrency", "1", "-o", str(tmp_path), "artwork"]) == 1
    output = capsys.readouterr()
    assert "Saved:" in output.out
    assert "Saved: 2, failed: 1, cancelled: 0" in output.out
    assert "404" in captured[0].err + output.err
    assert len(list(tmp_path.iterdir())) == 2


def test_r06_cancellation_reports_started_and_queued_once(tmp_path):
    async def run():
        started = asyncio.Event()
        active = 0
        outcomes = []

        async def respond(_):
            nonlocal active
            active += 1
            started.set()
            try:
                await asyncio.Future()
            finally:
                active -= 1

        async with client(respond) as http:
            task = asyncio.create_task(
                download.download_images(
                    http,
                    [metadata(index=0), metadata(index=1)],
                    settings(tmp_path, image_concurrency=1),
                    outcome_callback=outcomes.append,
                )
            )
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        assert active == 0
        assert [(item.metadata.index, item.status) for item in outcomes] == [
            (0, "cancelled"),
            (1, "cancelled"),
        ]

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, fail=False):
        self.chunks = chunks
        self.fail = fail

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise httpx.ReadError("fixture disconnected")


def test_r07_large_direct_body_is_streamed_to_disk(tmp_path):
    body = encoded((12, 34, 56))
    extra_size = 8 * 1024 * 1024

    def chunks():
        yield body
        for _ in range(128):
            yield bytes(65536)

    async def run():
        async with client(
            lambda _: httpx.Response(200, stream=Stream(chunks()))
        ) as http:
            return await download.download_image(
                http,
                metadata(direct=True),
                settings(
                    tmp_path,
                    max_canvas_bytes=1024,
                ),
            )

    tracemalloc.start()
    try:
        result = asyncio.run(run())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.method == "direct"
    assert result.output_path.stat().st_size == len(body) + extra_size
    assert pixel(result.output_path) == (12, 34, 56)
    assert peak < extra_size // 2
    assert list(tmp_path.iterdir()) == [result.output_path]


def test_r08_direct_retry_rewinds_the_temporary_file(tmp_path, monkeypatch):
    body = encoded((12, 34, 56))
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        stream = Stream([b"old prefix"], fail=True) if calls == 1 else Stream([body])
        return httpx.Response(200, stream=stream)

    monkeypatch.setattr("artsy_tiled_image_downloader.http.retry_delay", lambda *_: 0)

    async def run():
        async with client(respond) as http:
            return await download.download_image(
                http,
                metadata(direct=True),
                settings(tmp_path, retries=2),
            )

    result = asyncio.run(run())
    assert calls == 2
    assert result.method == "direct"
    assert result.output_path.read_bytes() == body
    assert list(tmp_path.iterdir()) == [result.output_path]


def test_r09_shared_budget_is_held_until_tiles_are_processed(tmp_path, monkeypatch):
    requests = []
    decode_started = threading.Event()
    release = threading.Event()
    original = download._decode_tile_content

    def decode(spec, tile):
        decode_started.set()
        assert release.wait(5)
        return original(spec, tile)

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(200, content=encoded((0, 255, 0)))

    monkeypatch.setattr(download, "_decode_tile_content", decode)

    async def run():
        async with client(respond) as http:
            task = asyncio.create_task(
                download.download_images(
                    http,
                    [metadata(index=0), metadata(index=1)],
                    settings(tmp_path, max_tile_bytes=128, max_tile_buffer_bytes=500),
                )
            )
            try:
                assert await asyncio.to_thread(decode_started.wait, 2)
                assert len(requests) == 1
            finally:
                release.set()
            return await asyncio.wait_for(task, 3)

    assert len(asyncio.run(run())) == 2
    assert len(requests) == 2


@pytest.mark.parametrize("assemble", [False, True])
def test_r10_impossible_tile_budget_fails_before_io(tmp_path, assemble):
    spec = metadata()

    async def run():
        async with client(lambda _: pytest.fail("unexpected HTTP")) as http:
            config = settings(tmp_path, max_tile_bytes=128, max_tile_buffer_bytes=100)
            with pytest.raises(DownloadError, match="tile.*budget"):
                if assemble:
                    await download.download_and_stitch_tiles(
                        http,
                        spec,
                        config,
                        tmp_path / "output.png",
                    )
                else:
                    await download.download_tiles(http, spec, config)

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("size", [(16384, 1), (1, 16384)])
def test_r11_webp_oversize_rejected_before_requests_or_allocation(
    tmp_path,
    monkeypatch,
    size,
):
    spec = metadata(size=size, fmt="webp")
    target = tmp_path / "large.webp"
    monkeypatch.setattr(download, "_new_canvas", lambda _: pytest.fail("allocated"))

    async def run():
        async with client(lambda _: pytest.fail("unexpected HTTP")) as http:
            with pytest.raises(ArtsyDownloaderError, match="16383"):
                await download.download_image(http, spec, settings(tmp_path))
            with pytest.raises(ArtsyDownloaderError, match="16383"):
                await download.download_and_stitch_tiles(
                    http,
                    spec,
                    settings(tmp_path),
                    target,
                )

    asyncio.run(run())
    with pytest.raises(ImageAssemblyError, match="16383"):
        download.stitch_tiles(spec, {}, target)
    assert list(tmp_path.iterdir()) == []


def test_r12_webp_accepts_the_encoder_boundary(tmp_path):
    spec = metadata(size=(16383, 1), fmt="webp")
    tiles = {
        (col, 0): encoded(
            (10, 20, 30), size=spec.expected_tile_size(col, 0), fmt="WEBP"
        )
        for col in range(2)
    }
    target = download.stitch_tiles(spec, tiles, tmp_path / "limit.webp")
    with Image.open(target) as image:
        image.load()
        assert (image.size, image.format) == ((16383, 1), "WEBP")


def srgb():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


def alternate_rgb_profile():
    data = bytearray(srgb().tobytes())
    count = struct.unpack_from(">I", data, 128)[0]
    for i in range(count):
        name, offset, _ = struct.unpack_from(">4sII", data, 132 + 12 * i)
        if name == b"rTRC":
            assert data[offset : offset + 4] == b"para"
            struct.pack_into(">i", data, offset + 12, int(1.5 * 65536))
            return bytes(data)
    pytest.fail("the sample profile has no tone curve")


@pytest.mark.parametrize("async_path", [False, True])
def test_r13_uniform_rgb_icc_is_embedded_verbatim(tmp_path, async_path):
    profile = alternate_rgb_profile()
    body = encoded((60, 120, 180), icc_profile=profile)
    spec = metadata()
    target = tmp_path / "icc.png"

    async def run():
        async with client(lambda _: httpx.Response(200, content=body)) as http:
            await download.download_and_stitch_tiles(
                http,
                spec,
                settings(tmp_path),
                target,
            )

    if async_path:
        asyncio.run(run())
    else:
        download.stitch_tiles(spec, {(0, 0): body}, target)
    with Image.open(target) as image:
        assert image.info["icc_profile"] == profile
        assert image.getpixel((0, 0)) == (60, 120, 180)


@pytest.mark.parametrize("tagged_first", [False, True])
@pytest.mark.parametrize("tag_other", [False, True])
def test_r14_mixed_icc_is_normalized_without_changing_alpha(
    tmp_path,
    tagged_first,
    tag_other,
):
    profile = alternate_rgb_profile()
    color = (60, 120, 180, 71)
    output_profile = srgb()
    with Image.new("RGBA", (1, 1), color) as source:
        with ImageCms.profileToProfile(
            source,
            ImageCms.ImageCmsProfile(BytesIO(profile)),
            output_profile,
            outputMode="RGBA",
        ) as converted:
            expected = converted.getpixel((0, 0))
    assert expected != color and expected[3] == color[3]
    tagged = encoded(color, icc_profile=profile)
    options = {"icc_profile": output_profile.tobytes()} if tag_other else {}
    untagged = encoded((20, 30, 40), **options)
    pair = [tagged, untagged] if tagged_first else [untagged, tagged]
    spec = replace(metadata(size=(2, 1)), tile_size=1)
    target = download.stitch_tiles(
        spec,
        {(col, 0): body for col, body in enumerate(pair)},
        tmp_path / "mix.png",
    )
    with Image.open(target) as image:
        final_profile = ImageCms.ImageCmsProfile(BytesIO(image.info["icc_profile"]))
        assert "srgb" in ImageCms.getProfileName(final_profile).lower()
        other = (20, 30, 40, 255)
        assert [image.getpixel((col, 0)) for col in range(2)] == (
            [expected, other]
            if tagged_first
            else [
                other,
                expected,
            ]
        )


def test_r15_invalid_icc_reports_assembly_error(tmp_path):
    body = encoded((12, 34, 56), icc_profile=b"invalid ICC")
    with pytest.raises(ImageAssemblyError, match="ICC"):
        download.stitch_tiles(metadata(), {(0, 0): body}, tmp_path / "invalid.png")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field", ["images", "figures"])
@pytest.mark.parametrize("value", [42, False, {}, "invalid"])
def test_r16_malformed_graphql_field_is_a_cli_error(
    tmp_path,
    monkeypatch,
    capsys,
    field,
    value,
):
    def respond(request):
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "data": {
                    "artworkResult": {
                        "__typename": "Artwork",
                        field: value,
                    }
                }
            },
        )

    monkeypatch.setattr(cli, "create_async_client", lambda _: client(respond))
    assert cli.run(["--metadata-only", "-o", str(tmp_path), "fixture-artwork"]) == 1
    error = capsys.readouterr().err
    assert f"error: {field} must be a list or null" in error
    assert "Traceback" not in error
    assert not list(tmp_path.iterdir())


def test_r17_independent_scheduled_workflow_runs_live_download(project_root):
    workflow_dir = project_root / ".github" / "workflows"
    if not (workflow_dir / "ci.yml").is_file():
        pytest.skip("GitHub Actions files are only present in the repository")
    live = (workflow_dir / "artsy-live.yml").read_text()
    assert "\n  schedule:\n    - cron:" in live
    assert "\n  workflow_dispatch:" in live
    assert 'RUN_LIVE_TESTS: "1"' in live
    assert "python -m pytest tests/test_live_download.py" in live
    for filename in ("ci.yml", "publish.yml"):
        assert "RUN_LIVE_TESTS" not in (workflow_dir / filename).read_text()


def test_r19_direct_codec_buffer_over_budget_falls_back(tmp_path, monkeypatch):
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("fixture", "a" * 4096)
    body = encoded((12, 34, 56), pnginfo=info)
    tile = encoded((0, 255, 0))
    monkeypatch.setattr(
        download, "_validate_direct_candidate", lambda *_: pytest.fail("decoded")
    )

    def respond(request):
        content = body if request.url.path == "/direct" else tile
        return httpx.Response(200, content=content)

    async def run():
        async with client(respond) as http:
            return await download.download_image(
                http,
                metadata(direct=True),
                settings(tmp_path, max_tile_bytes=128, max_tile_buffer_bytes=500),
            )

    result = asyncio.run(run())
    assert result.method == "tiles"
    assert pixel(result.output_path) == (0, 255, 0)
    assert list(tmp_path.iterdir()) == [result.output_path]
