import io

import cv2
import numpy as np
import pytest
from PIL import Image

from portrait_qa import imaging
from portrait_qa.errors import ImageTooLargeError, InvalidImageError

from .conftest import jpeg

LIMITS = {"max_bytes": 10_000_000, "max_pixels": 50_000_000}


def test_sniff_formats(portrait):
    assert imaging.sniff_format(jpeg(portrait)) == "jpeg"
    assert imaging.sniff_format(cv2.imencode(".png", portrait)[1].tobytes()) == "png"
    assert imaging.sniff_format(cv2.imencode(".bmp", portrait)[1].tobytes()) == "bmp"
    assert imaging.sniff_format(cv2.imencode(".webp", portrait)[1].tobytes()) == "webp"
    assert imaging.sniff_format(b"GIF89a....") is None


def test_decode_round_trip(portrait):
    image = imaging.decode(jpeg(portrait), **LIMITS)
    assert image.shape == portrait.shape


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "Empty"),
        (b"hello world, not an image", "Unsupported format"),
        (b"\xff\xd8\xff" + b"\x00" * 100, "could not be decoded"),
    ],
)
def test_decode_invalid(data, message):
    with pytest.raises(InvalidImageError, match=message):
        imaging.decode(data, **LIMITS)


def test_decode_size_limits(portrait):
    data = jpeg(portrait)
    with pytest.raises(ImageTooLargeError, match="MB"):
        imaging.decode(data, max_bytes=len(data) - 1, max_pixels=LIMITS["max_pixels"])
    with pytest.raises(ImageTooLargeError, match="megapixels"):
        imaging.decode(data, max_bytes=LIMITS["max_bytes"], max_pixels=512 * 512 - 1)


def test_exif_orientation_is_applied(portrait):
    """Phone photos are stored sideways with an EXIF orientation tag; the decoder must rotate them."""
    pil = Image.fromarray(cv2.cvtColor(portrait[:300], cv2.COLOR_BGR2RGB))  # 512 wide, 300 tall
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise for display
    buf = io.BytesIO()
    pil.save(buf, "JPEG", exif=exif)
    image = imaging.decode(buf.getvalue(), **LIMITS)
    assert image.shape[:2] == (512, 300)


def test_encode_jpeg_respects_max_kb(portrait):
    big = cv2.resize(portrait, (600, 800))  # the size of the "default" profile
    noisy = cv2.add(big, np.random.default_rng(1).integers(0, 25, big.shape, dtype=np.uint8))
    unlimited = imaging.encode_jpeg(noisy, quality=95)
    limited = imaging.encode_jpeg(noisy, quality=95, max_kb=100)
    assert len(unlimited) > 100 * 1024
    assert len(limited) <= 100 * 1024


def test_encode_jpeg_returns_smallest_when_limit_unreachable(portrait):
    data = imaging.encode_jpeg(portrait, max_kb=1, min_quality=40)
    assert data.startswith(b"\xff\xd8")  # still a JPEG; the caller reports fits_max_kb=False


def test_resize_to_max_side(portrait):
    small, scale = imaging.resize_to_max_side(portrait, 256)
    assert small.shape[:2] == (256, 256) and scale == 0.5
    same, scale = imaging.resize_to_max_side(portrait, 1024)
    assert same is portrait and scale == 1.0
