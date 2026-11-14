"""Portrait crop: frame the main face according to an output profile, resize and encode as JPEG."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .detector import Face
from .imaging import encode_jpeg


@dataclass(frozen=True)
class OutputProfile:
    """Geometry and file limits of the cropped portrait.

    ``face_width_ratio``: width of the detected face box over the output width (the box covers the face from
    brow to chin, without hair and ears). ``eye_line``: height of the eyes from the top, as a fraction of the
    output height. ``max_face_width_ratio``: how much tighter the crop may get when the photo has no room
    around the face, before the missing area is filled with ``background`` (BGR).
    """

    name: str
    width: int
    height: int
    face_width_ratio: float = 0.5
    eye_line: float = 0.42
    max_face_width_ratio: float = 0.7
    max_kb: int | None = 200
    jpeg_quality: int = 92
    background: tuple[int, int, int] = (255, 255, 255)
    description: str = ""

    def validate(self) -> None:
        if not (16 <= self.width <= 4096 and 16 <= self.height <= 4096):
            raise ValueError(f"profile {self.name}: width/height must be between 16 and 4096")
        if not 0.1 <= self.face_width_ratio <= self.max_face_width_ratio <= 0.95:
            raise ValueError(f"profile {self.name}: need 0.1 <= face_width_ratio <= max_face_width_ratio <= 0.95")
        if not 0.2 <= self.eye_line <= 0.7:
            raise ValueError(f"profile {self.name}: eye_line must be between 0.2 and 0.7")
        if self.max_kb is not None and self.max_kb < 5:
            raise ValueError(f"profile {self.name}: max_kb must be at least 5")
        if not 40 <= self.jpeg_quality <= 100:
            raise ValueError(f"profile {self.name}: jpeg_quality must be between 40 and 100")
        if len(self.background) != 3 or not all(0 <= c <= 255 for c in self.background):
            raise ValueError(f"profile {self.name}: background must be three values 0-255 (B, G, R)")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["background"] = list(self.background)
        return data


# Generic profiles. Device-specific limits (size, resolution, file size) vary by model and firmware: check the
# device manual and add a profile in config.json instead of trusting these numbers for a given terminal.
BUILTIN_PROFILES: dict[str, OutputProfile] = {
    p.name: p
    for p in (
        OutputProfile("default", 600, 800, max_kb=200, description="3:4 portrait, 600x800, up to 200 KB"),
        OutputProfile("compact", 480, 640, max_kb=100, description="3:4 portrait, 480x640, up to 100 KB"),
        OutputProfile("badge", 300, 400, max_kb=60, description="3:4 portrait for ID badges, 300x400, up to 60 KB"),
        OutputProfile(
            "square",
            640,
            640,
            face_width_ratio=0.45,
            eye_line=0.45,
            max_kb=150,
            description="Square 640x640, up to 150 KB",
        ),  # fmt: skip
    )
}


@dataclass
class CropResult:
    jpeg: bytes
    width: int
    height: int
    profile: str
    source_box: list[int]  # crop rectangle in the source image (may extend past it when padded)
    padded: bool  # part of the output was filled with the background color
    upscaled: bool  # the crop had fewer pixels than the output (the result is softer)
    fits_max_kb: bool

    def info(self) -> dict:
        return {
            "profile": self.profile,
            "width": self.width,
            "height": self.height,
            "bytes": len(self.jpeg),
            "format": "jpeg",
            "source_box": self.source_box,
            "padded": self.padded,
            "upscaled": self.upscaled,
            "fits_max_kb": self.fits_max_kb,
        }


def crop_box(face: Face, image_size: tuple[int, int], profile: OutputProfile) -> tuple[float, float, float, float]:
    """Crop rectangle (x, y, w, h) in source pixels, before any padding."""
    img_w, img_h = image_size
    aspect = profile.height / profile.width
    eye_x, eye_y = face.eye_center
    # Horizontal anchor: between the eye midpoint and the box centre (the box alone drifts with hair/ears).
    anchor_x = (eye_x + face.x + face.width / 2) / 2
    anchor_y = eye_y
    fx = 0.5  # anchor at the horizontal centre of the output
    fy = profile.eye_line

    def fits(cw: float) -> bool:
        ch = cw * aspect
        return (
            anchor_x - fx * cw >= 0
            and anchor_x + (1 - fx) * cw <= img_w
            and anchor_y - fy * ch >= 0
            and anchor_y + (1 - fy) * ch <= img_h
        )

    desired = face.width / profile.face_width_ratio
    cw = desired
    if not fits(cw):
        # Largest width that still fits around the anchor; accept it if the face does not get too big.
        limit = min(
            anchor_x / fx,
            (img_w - anchor_x) / (1 - fx),
            anchor_y / (fy * aspect),
            (img_h - anchor_y) / ((1 - fy) * aspect),
        )
        tightest = face.width / profile.max_face_width_ratio
        cw = max(limit, tightest) if limit < desired else desired
    ch = cw * aspect
    return anchor_x - fx * cw, anchor_y - fy * ch, cw, ch


def crop(image: np.ndarray, face: Face, profile: OutputProfile) -> CropResult:
    img_h, img_w = image.shape[:2]
    x, y, cw, ch = crop_box(face, (img_w, img_h), profile)
    x0, y0 = int(round(x)), int(round(y))
    x1, y1 = int(round(x + cw)), int(round(y + ch))
    pad_left, pad_top = max(0, -x0), max(0, -y0)
    pad_right, pad_bottom = max(0, x1 - img_w), max(0, y1 - img_h)
    padded = any((pad_left, pad_top, pad_right, pad_bottom))
    region = image[max(0, y0) : min(img_h, y1), max(0, x0) : min(img_w, x1)]
    if padded:
        region = cv2.copyMakeBorder(
            region, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_CONSTANT, value=profile.background
        )
    upscaled = region.shape[1] < profile.width
    interp = cv2.INTER_CUBIC if upscaled else cv2.INTER_AREA
    out = cv2.resize(region, (profile.width, profile.height), interpolation=interp)
    jpeg = encode_jpeg(out, quality=profile.jpeg_quality, max_kb=profile.max_kb)
    fits = profile.max_kb is None or len(jpeg) <= profile.max_kb * 1024
    return CropResult(
        jpeg=jpeg,
        width=profile.width,
        height=profile.height,
        profile=profile.name,
        source_box=[x0, y0, x1 - x0, y1 - y0],
        padded=padded,
        upscaled=upscaled,
        fits_max_kb=fits,
    )
