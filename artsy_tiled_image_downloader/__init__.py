"""Download and stitch high-resolution Artsy Deep Zoom images."""

from ._version import __version__
from .config import DownloaderSettings
from .download import DownloadResult, download_artwork, download_full_image
from .metadata import fetch_metadatas, get_artwork_id, get_max_zoom_level, get_metadatas
from .models import ImageMetadata

__all__ = [
    "DownloadResult",
    "DownloaderSettings",
    "ImageMetadata",
    "__version__",
    "download_artwork",
    "download_full_image",
    "fetch_metadatas",
    "get_artwork_id",
    "get_max_zoom_level",
    "get_metadatas",
]
