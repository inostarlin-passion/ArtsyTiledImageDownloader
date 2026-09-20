# Changelog

All notable changes to this project are documented here.

## 2.1.1 - 2026-09-20

### Added

- Configurable concurrent downloading of multiple artwork images, with a new
  `--image-concurrency` CLI option and a default of 4 workers.
- Performance acceptance tests and reproducible benchmark coverage for the
  multi-image download path.

### Changed

- Increased the default tile-request concurrency from 24 to 64 while retaining
  the 64-request hard limit.
- Shared the request budget across concurrently downloaded images so the total
  number of active HTTP requests remains bounded.
- Preserved metadata order in multi-image CLI results and aligned library and
  CLI defaults.

### Fixed

- Made the performance acceptance benchmark deterministic across CI platforms
  by separating its synthetic network-delay signal from image I/O jitter.

## 2.1.0 - 2026-07-15

### Added

- A bounded download/decode/stitch pipeline that overlaps network I/O with tile
  decoding and releases decoded images immediately after paste.
- Streaming response-size limits for tiles and direct-image candidates.
- Tile-count, exact Deep Zoom tile-dimension, URL, numeric, and CLI validation.
- Configurable PNG compression and a `--version` CLI option.
- Python 3.10-3.14 CI, branch coverage enforcement, performance-property tests,
  a test report, and a nine-area quality checklist.

### Changed

- Increased default tile-request concurrency from 16 to 24 based on live bounded
  concurrency measurements; the configurable upper bound remains 64.
- PNG output now defaults to lossless compression level 1 for faster saves.
- HTTP image bodies are streamed and bounded instead of being accepted without a
  byte limit.
- Deep Zoom tiles must match their exact edge-aware overlap dimensions before
  pixel decoding.

### Fixed

- Pending requests and decoded Pillow images are now cleaned up when downloads,
  callbacks, decoding, saves, or task cancellation fail.
- Filesystem failures are converted into domain errors suitable for CLI reporting.
- Boolean values can no longer pass integer validation accidentally.
- Removed the Star History section from the README.
