# Artsy Tiled Image Downloader

Download high-resolution tiled artwork images from Artsy artwork pages for personal study and technical research.

## Features

- Uses a reusable HTTPX async client with connection pooling and HTTP/2 support.
- Validates input URL/slug, metadata fields, tile dimensions, output size limits, retry counts, timeouts, and concurrency.
- Uses a bounded 64-request download window by default and overlaps network I/O with
  parallel tile decoding, while serializing canvas writes for deterministic,
  thread-safe assembly.
- Downloads up to four images from one artwork concurrently while sharing the same
  request budget; use `--image-concurrency` to tune that limit.
- Streams image and metadata response bodies through configurable byte limits.
  Requests identity content encoding and rejects HTTP content encodings such as gzip.
- Streams direct-image candidates to temporary files. `--max-canvas-bytes`
  (2.5 GiB by default) budgets full image pixels. `--max-tile-buffer-bytes`
  (4 GiB by default) budgets tile work and direct-image codec input across the
  artwork. These estimates do not cap total process memory. The metadata response
  limit defaults to 8 MiB and can be set with `--max-metadata-bytes`.
- Writes complete files atomically. Existing files are preserved by default.
- Preserves a common embedded ICC profile in tiled images and converts mixed
  profiles to sRGB. WebP outputs exceeding 16,383 pixels on either side fail
  before tile requests.
- Splits CLI, metadata parsing, downloading, image assembly, paths, config, and exceptions into testable modules.

## Installation

Install from PyPI:

```bash
pip install artsy-tiled-image-downloader
```

The installed console command is:

```bash
artsy-downloader [artsy-artwork-url]
```

For local development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
python -m artsy_tiled_image_downloader [artsy-artwork-url]
```

After installation, the same CLI is also available as:

```bash
artsy-downloader [artsy-artwork-url]
```

Example:

```bash
python -m artsy_tiled_image_downloader https://www.artsy.net/artwork/yayoi-kusama-stars-11
```

Useful options:

```bash
python -m artsy_tiled_image_downloader --metadata-only https://www.artsy.net/artwork/yayoi-kusama-stars-11
python -m artsy_tiled_image_downloader --output-dir ~/Downloads --concurrency 64 --image-concurrency 4 --timeout 30 [url]
python -m artsy_tiled_image_downloader --skip-direct [url]
python -m artsy_tiled_image_downloader --overwrite [url]
python -m artsy_tiled_image_downloader --png-compression 1 [url]
```

Sample output:

```text
URL: https://www.artsy.net/artwork/yayoi-kusama-stars-11
Fetching metadata...
Images: 1
Image 1/1: 2547x3543, 7x5 (35 tiles)
Downloading...
Saved: /Users/you/Downloads/output_yayoi-kusama-stars-11_<source-id>_0.jpg (direct)
Saved: 1, failed: 0, cancelled: 0
Elapsed: 1.0s
```

Output filenames include a digest of the artwork identity. Use `--overwrite`
to replace an existing file at the generated path. Publishing without overwrite
requires hard-link support in the destination filesystem.

If one image fails, the CLI continues downloading the other images and exits
with status 1 after reporting the successes and failures. Python callers can use
`outcome_callback` for per-image results. A partial failure raises
`BatchDownloadError` with outcomes in input order.

## Testing

```bash
pip install -e ".[dev]"
pytest
pytest --cov --cov-report=term-missing
ruff check .
RUN_LIVE_TESTS=1 pytest tests/test_live_download.py
```

The test suite covers URL and limit validation, metadata parsing, filename safety,
Deep Zoom boundary math, retry and response-size behavior, bounded concurrency,
pipelined assembly, direct-image fallback, packaging, and a local HTTP end-to-end CLI run.
See [`TEST_REPORT.md`](TEST_REPORT.md) and
[`QUALITY_CHECKLIST.md`](QUALITY_CHECKLIST.md) for the release evidence.
The current download-time optimization evidence is in
[`reports/technical_design_document.md`](reports/technical_design_document.md),
[`reports/test_case_specification.md`](reports/test_case_specification.md), and
[`reports/test_completion_report.md`](reports/test_completion_report.md).

## PyPI Release

Package name: `artsy-tiled-image-downloader`

Build and validate the release artifacts:

```bash
rm -rf build dist *.egg-info
python -m pip install -e ".[dev]"
python -m build
python -m twine check --strict dist/*
```

Upload with a PyPI project or account token:

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-... python -m twine upload dist/*
```

This repository also includes `.github/workflows/publish.yml` for PyPI Trusted
Publishing. Configure the `pypi` environment as a trusted publisher for this
repository. Publishing a `vX.Y.Z` GitHub release then checks that the tag exactly
matches the package version before building and uploading both the wheel and sdist.

## Temporary Data

The downloader holds a bounded set of compressed and decoded tiles in memory.
Decoded images are closed after they are pasted. The downloader creates temporary
files beside the final output to stream direct candidates and encode assembled
images before committing them.

If a future very-large-image mode needs disk-backed tile caching, prefer `tempfile.TemporaryDirectory()` as a scoped context manager rather than a fixed folder under `~/Downloads`.

## Disclaimer

This project is independent and is not affiliated with Artsy.

Use it only for personal learning, interoperability research, and lawful technical analysis.
You are responsible for respecting Artsy's terms of use, robots policies, copyright restrictions, and any applicable laws.
Do not use this project for commercial redistribution, copyright infringement, abusive automation, or any unauthorized access.

The software is provided as-is, without warranty.
The maintainers are not responsible for misuse or for any direct or indirect loss caused by using this tool.
