from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import artsy_tiled_image_downloader.cli as cli_module
from artsy_tiled_image_downloader.download import DownloadResult
from artsy_tiled_image_downloader.exceptions import DownloadError
from artsy_tiled_image_downloader.models import ImageMetadata


class _ClientContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


def _metadata() -> ImageMetadata:
    return ImageMetadata(
        index=0,
        title="cli-test",
        format="png",
        url="https://tiles.example/1/",
        tile_size=1,
        overlap=0,
        width=2,
        height=1,
        max_zoom_level=1,
    )


def test_parser_exposes_version_and_rejects_bad_compression(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["--version"])
    assert "2.1.0" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="2"):
        parser.parse_args(["--png-compression", "10", "slug"])


@pytest.mark.parametrize("metadata_only", [True, False])
def test_run_async_reports_metadata_and_download_progress(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    metadata_only: bool,
) -> None:
    metadata = _metadata()
    output = tmp_path / "output.png"
    download_calls = 0

    async def fake_fetch(*args: object, **kwargs: object) -> list[ImageMetadata]:
        return [metadata]

    async def fake_download(
        client: object,
        image_metadata: ImageMetadata,
        settings: object,
        *,
        progress_callback,
    ) -> DownloadResult:
        nonlocal download_calls
        del client, settings
        download_calls += 1
        progress_callback(1, 2)
        progress_callback(2, 2)
        return DownloadResult(output, "tiles", image_metadata)

    monkeypatch.setattr(cli_module, "create_async_client", lambda _: _ClientContext())
    monkeypatch.setattr(cli_module, "fetch_metadatas", fake_fetch)
    monkeypatch.setattr(cli_module, "download_image", fake_download)

    argv = ["--output-dir", str(tmp_path)]
    if metadata_only:
        argv.append("--metadata-only")
    argv.append("cli-test")
    args = cli_module.build_parser().parse_args(argv)

    assert asyncio.run(cli_module.run_async(args)) == 0

    stdout = capsys.readouterr().out
    assert "Images: 1" in stdout
    assert "Image 1/1: 2x1, 1x2 (2 tiles)" in stdout
    if metadata_only:
        assert download_calls == 0
        assert "Saved:" not in stdout
    else:
        assert download_calls == 1
        assert "Tiles: 2/2" in stdout
        assert f"Saved: {output} (tiles)" in stdout


def test_run_converts_domain_error_to_exit_code(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(_: object) -> int:
        raise DownloadError("expected failure")

    monkeypatch.setattr(cli_module, "run_async", fail)

    assert cli_module.run(["cli-test"]) == 1
    assert "error: expected failure" in capsys.readouterr().err
