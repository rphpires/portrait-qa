"""Decode and encode images. Decoding happens once per request; EXIF orientation is applied by OpenCV.

The pixel limit is checked from the file header (Pillow reads only the header) *before* decoding: a tiny PNG
can declare 20000x20000 pixels and would otherwise allocate gigabytes.
"""

from __future__ import annotations

import io
import warnings

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from .errors import ImageTooLargeError, InvalidImageError

Image.MAX_IMAGE_PIXELS = None  # our own limit (max_pixels) applies; Pillow's would warn or raise first

# JPEG, PNG, BMP and WebP magic numbers. Anything else is refused before decoding.
_SIGNATURES = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"BM", "bmp"),
)


def sniff_format(data: bytes) -> str | None:
    for magic, name in _SIGNATURES:
        if data.startswith(magic):
            return name
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def probe(data: bytes) -> tuple[int, int, bool]:
    """(width, height, has_alpha) from the header, without decoding the pixels."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(data)) as im:
                width, height = im.size
                alpha = im.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in im.info
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise InvalidImageError("The image could not be read (corrupt or truncated file).") from exc
    return width, height, alpha


def _to_bgr(image: np.ndarray, background: tuple[int, int, int]) -> np.ndarray:
    """8-bit BGR from whatever IMREAD_UNCHANGED returned (gray, gray+alpha, BGRA, 16-bit)."""
    if image.dtype == np.uint16:
        image = (image // 257).astype(np.uint8)
    elif image.dtype != np.uint8:
        image = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    channels = image.shape[2]
    if channels == 1:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if channels == 2:
        color, alpha = cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR), image[:, :, 1]
    elif channels == 4:
        color, alpha = image[:, :, :3], image[:, :, 3]
    else:
        return image[:, :, :3]
    a = alpha.astype(np.float32)[:, :, None] / 255.0
    bg = np.array(background, np.float32)[None, None, :]
    return (color.astype(np.float32) * a + bg * (1.0 - a)).round().astype(np.uint8)


def decode(
    data: bytes, *, max_bytes: int, max_pixels: int, background: tuple[int, int, int] = (255, 255, 255)
) -> np.ndarray:
    """Return a BGR image. Transparent areas are composited onto ``background`` (BGR).

    Raises InvalidImageError / ImageTooLargeError.
    """
    if not data:
        raise InvalidImageError("Empty image.")
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"Image is {len(data) / 1e6:.1f} MB; the limit is {max_bytes / 1e6:.1f} MB.")
    if sniff_format(data) is None:
        raise InvalidImageError("Unsupported format; send JPEG, PNG, BMP or WebP.")
    width, height, alpha = probe(data)
    if width * height > max_pixels:
        raise ImageTooLargeError(f"Image is {width}x{height}; the limit is {max_pixels / 1e6:.0f} megapixels.")
    buf = np.frombuffer(data, np.uint8)
    if alpha:
        # IMREAD_UNCHANGED keeps the alpha channel (and ignores EXIF orientation; images with transparency are
        # PNG/WebP, which in practice carry no orientation tag).
        raw = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        image = None if raw is None else _to_bgr(raw, background)
    else:
        image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImageError("The image could not be decoded (corrupt or truncated file).")
    return image


def encode_jpeg(image: np.ndarray, *, quality: int = 92, max_kb: int | None = None, min_quality: int = 40) -> bytes:
    """Encode as JPEG. With ``max_kb``, lower the quality step by step until the file fits.

    If even ``min_quality`` does not fit, the smallest result is returned; the caller reports it.
    """
    q = quality
    while True:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, q, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
        if not ok:  # pragma: no cover - OpenCV only fails here on invalid arrays
            raise InvalidImageError("JPEG encoding failed.")
        data = buf.tobytes()
        if max_kb is None or len(data) <= max_kb * 1024 or q <= min_quality:
            return data
        q = max(min_quality, q - 6)


def resize_to_max_side(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    """Downscale so the longest side is at most ``max_side``. Returns (image, scale) with scale <= 1."""
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image, 1.0
    scale = max_side / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA), scale
