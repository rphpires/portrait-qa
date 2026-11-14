"""Decode and encode images. Decoding happens once per request; EXIF orientation is applied by OpenCV."""

from __future__ import annotations

import cv2
import numpy as np

from .errors import ImageTooLargeError, InvalidImageError

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


def decode(data: bytes, *, max_bytes: int, max_pixels: int) -> np.ndarray:
    """Return a BGR image. Raises InvalidImageError / ImageTooLargeError."""
    if not data:
        raise InvalidImageError("Empty image.")
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"Image is {len(data) / 1e6:.1f} MB; the limit is {max_bytes / 1e6:.1f} MB.")
    if sniff_format(data) is None:
        raise InvalidImageError("Unsupported format; send JPEG, PNG, BMP or WebP.")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImageError("The image could not be decoded (corrupt or truncated file).")
    height, width = image.shape[:2]
    if width * height > max_pixels:
        raise ImageTooLargeError(f"Image is {width}x{height}; the limit is {max_pixels / 1e6:.0f} megapixels.")
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
