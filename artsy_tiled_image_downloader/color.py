from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageCms

from .exceptions import ImageAssemblyError


@lru_cache(maxsize=1)
def _srgb() -> tuple[ImageCms.ImageCmsProfile, bytes]:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile, profile.tobytes()


def _profile(data: bytes) -> ImageCms.ImageCmsProfile:
    try:
        return ImageCms.ImageCmsProfile(BytesIO(data))
    except (ImageCms.PyCMSError, OSError, TypeError, ValueError) as exc:
        raise ImageAssemblyError("invalid tile ICC color profile") from exc


def _to_srgb(
    image: Image.Image,
    profile: ImageCms.ImageCmsProfile,
    *,
    mode: str,
    in_place: bool = False,
) -> Image.Image | None:
    try:
        return ImageCms.profileToProfile(
            image, profile, _srgb()[0], outputMode=mode, inPlace=in_place
        )
    except (ImageCms.PyCMSError, OSError, ValueError) as exc:
        raise ImageAssemblyError("could not convert tile ICC color profile") from exc


def prepare_tile(image: Image.Image, mode: str) -> tuple[Image.Image, bytes | None]:
    """Convert the cropped tile to a canvas mode without losing its color space."""
    data = image.info.get("icc_profile")
    if data is None:
        return (image if image.mode == mode else image.convert(mode)), None

    profile = _profile(data)
    space = profile.profile.xcolor_space.strip()
    if space == "RGB" and image.mode not in {"CMYK", "LAB"}:
        return (image if image.mode == mode else image.convert(mode)), data

    if space == "GRAY" and image.mode in {"1", "L", "LA", "I", "I;16"}:
        with image.convert("L") as grayscale:
            converted = _to_srgb(grayscale, profile, mode="RGB")
    elif (space, image.mode) in {("CMYK", "CMYK"), ("Lab", "LAB")}:
        converted = _to_srgb(image, profile, mode="RGB")
    else:
        raise ImageAssemblyError(f"tile ICC color space {space!r} does not match image")

    assert converted is not None
    if mode == "RGBA":
        try:
            with image.convert("RGBA") as rgba, rgba.getchannel("A") as alpha:
                converted.putalpha(alpha)
        except BaseException:
            converted.close()
            raise
    return converted, _srgb()[1]


class CanvasColor:
    """Keep an RGB profile when uniform, otherwise normalize to sRGB."""

    def __init__(self) -> None:
        self.profile: bytes | None = None
        self._initialized = False
        self._mixed = False

    def prepare(
        self, canvas: Image.Image, tile: Image.Image, profile: bytes | None
    ) -> None:
        if not self._initialized:
            self.profile = profile
            self._initialized = True
            return
        if not self._mixed and profile != self.profile:
            if self.profile is not None and self.profile != _srgb()[1]:
                _to_srgb(
                    canvas, _profile(self.profile), mode=canvas.mode, in_place=True
                )
            self.profile = _srgb()[1]
            self._mixed = True
        if self._mixed and profile is not None and profile != self.profile:
            _to_srgb(tile, _profile(profile), mode=tile.mode, in_place=True)
