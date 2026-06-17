# Artsy Tiled Image Downloader

Download high-resolution tiled artwork images from Artsy artwork pages for personal study and technical research.

## Features

- Uses a reusable HTTPX async client with connection pooling and HTTP/2 support.
- Validates input URL/slug, metadata fields, tile dimensions, output size limits, retry counts, timeouts, and concurrency.
- Downloads tiles concurrently and stitches directly from in-memory tile bytes.
- Writes final files with an atomic temporary file in the output directory, so a failed save does not leave a partial image at the final path.
- Splits CLI, metadata parsing, downloading, image assembly, paths, config, and exceptions into testable modules.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
./main.py [artsy-artwork-url]
```

Example:

```bash
./main.py https://www.artsy.net/artwork/yayoi-kusama-stars-11
```

Useful options:

```bash
./main.py --metadata-only https://www.artsy.net/artwork/yayoi-kusama-stars-11
./main.py --output-dir ~/Downloads --concurrency 24 --timeout 30 [url]
./main.py --skip-direct [url]
```

Sample output:

```text
URL: https://www.artsy.net/artwork/yayoi-kusama-stars-11
Fetching metadata...
Images: 1
Image 1/1: 2547x3543, 14x10 (140 tiles)
Downloading...
Saved: /Users/you/Downloads/output_yayoi-kusama-stars-11_0.jpg (direct)
Elapsed: 1.0s
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

The test suite covers URL parsing, metadata parsing, filename safety, tile crop math, direct-image fallback, in-memory tile stitching, and a local HTTP end-to-end CLI run.

## Temporary Data

The downloader no longer stores tiles in a process-wide temporary directory.
Tiles are downloaded into memory as compressed bytes and decoded one at a time while stitching.
The only temporary files are short-lived files created beside the final output for atomic replacement.

If a future very-large-image mode needs disk-backed tile caching, prefer `tempfile.TemporaryDirectory()` as a scoped context manager rather than a fixed folder under `~/Downloads`.

## Star History

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=inostarlin-passion/artsytiledimagedownloader&type=date&theme=dark&legend=top-left" />
  <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=inostarlin-passion/artsytiledimagedownloader&type=date&legend=top-left" />
  <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=inostarlin-passion/artsytiledimagedownloader&type=date&legend=top-left" />
</picture>

## Disclaimer

This project is independent and is not affiliated with Artsy.

Use it only for personal learning, interoperability research, and lawful technical analysis.
You are responsible for respecting Artsy's terms of use, robots policies, copyright restrictions, and any applicable laws.
Do not use this project for commercial redistribution, copyright infringement, abusive automation, or any unauthorized access.

The software is provided as-is, without warranty.
The maintainers are not responsible for misuse or for any direct or indirect loss caused by using this tool.
