class ArtsyDownloaderError(Exception):
    """Base exception for downloader failures."""


class MetadataError(ArtsyDownloaderError):
    """Raised when artwork metadata cannot be fetched or parsed."""


class DownloadError(ArtsyDownloaderError):
    """Raised when an image or one of its tiles cannot be downloaded."""


class ImageAssemblyError(ArtsyDownloaderError):
    """Raised when downloaded image tiles cannot be stitched safely."""
