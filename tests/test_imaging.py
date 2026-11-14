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
        (b"\xff\xd8\xff" + b"\x00" * 100, "could not be"),
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


def test_pixel_bomb_is_refused_from_the_header():
    """A ~400 KB PNG declaring 20000x20000 pixels must be refused without allocating the image."""
    import zlib

    try:
        import resource  # Unix only: the memory check is skipped on Windows, the refusal is not
    except ImportError:
        resource = None

    width = height = 20000
    raw = zlib.compress(b"".join(b"\x00" + bytes(width) for _ in range(height)), 9)

    def chunk(kind, body):
        return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else 0
    with pytest.raises(ImageTooLargeError, match="20000x20000"):
        imaging.decode(png, **LIMITS)
    if resource:
        grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
        assert grown_mb < 100


def png_bytes(array) -> bytes:
    return cv2.imencode(".png", array)[1].tobytes()


def test_transparent_png_is_composited_on_white():
    rgba = np.zeros((60, 40, 4), np.uint8)
    rgba[:, :20] = (0, 0, 255, 255)  # opaque red on the left, fully transparent (black) on the right
    image = imaging.decode(png_bytes(rgba), **LIMITS)
    assert image.shape == (60, 40, 3)
    assert tuple(image[10, 5]) == (0, 0, 255)
    assert tuple(image[10, 35]) == (255, 255, 255)


def test_gray_alpha_and_16_bit_pngs():
    ga = Image.new("LA", (30, 20), (0, 0))
    buf = io.BytesIO()
    ga.save(buf, "PNG")
    image = imaging.decode(buf.getvalue(), **LIMITS)
    assert image.shape == (20, 30, 3) and image.min() == 255
    deep = np.full((20, 30, 3), 65535, np.uint16)
    image = imaging.decode(png_bytes(deep), **LIMITS)
    assert image.dtype == np.uint8 and image.min() == 255


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
