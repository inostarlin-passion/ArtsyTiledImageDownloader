# Artsy Tiled Image Downloader

Download high-resolution tiled artwork images from Artsy artwork pages for personal study and technical research.

## Features

- Fetches artwork image metadata through Artsy's GraphQL data source.
- Downloads same-resolution direct image assets when available.
- Falls back to Deep Zoom tile download and stitching when a direct image is unavailable.
- Saves output images to `~/Downloads/` by default.

## Installation

```bash
pip3 install -r requirements.txt
```

If your Python installation is externally managed, use a virtual environment:

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

Sample output:

```text
URL: https://www.artsy.net/artwork/yayoi-kusama-stars-11
Fetching metadata...
Images: 1
Image 1/1: 2547x3543
Downloading...
Saved: /Users/you/Downloads/output_yayoi-kusama-stars-11_0.jpg (direct)
Elapsed: 1.0s
```

## Star History

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=inostarlin-passion/artsytiledimagedownloader&type=date&theme=dark&legend=top-left" />
  <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=inostarlin-passion/artsytiledimagedownloader&type=date&legend=top-left" />
  <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=inostarlin-passion/artsytiledimagedownloader&type=date&legend=top-left" />
</picture>

## Disclaimer

This project is independent and is not affiliated with Artsy.

Use it only for personal learning, interoperability research, and lawful technical analysis. You are responsible for respecting Artsy's terms of use, robots policies, copyright restrictions, and any applicable laws. Do not use this project for commercial redistribution, copyright infringement, abusive automation, or any unauthorized access.

The software is provided as-is, without warranty. The maintainers are not responsible for misuse or for any direct or indirect loss caused by using this tool.
