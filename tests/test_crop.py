import cv2
import numpy as np
import pytest

from portrait_qa.crop import BUILTIN_PROFILES, OutputProfile, crop, crop_box


@pytest.mark.parametrize("name", sorted(BUILTIN_PROFILES))
def test_builtin_profiles_output(detector, variants, name):
    profile = BUILTIN_PROFILES[name]
    profile.validate()
    image = variants["large"]
    face = detector.detect(image)[0]
    result = crop(image, face, profile)
    out = cv2.imdecode(np.frombuffer(result.jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert out.shape[:2] == (profile.height, profile.width)
    assert result.fits_max_kb and len(result.jpeg) <= profile.max_kb * 1024
    assert not result.upscaled


def test_framing_puts_eyes_on_the_eye_line(detector, variants):
    image = variants["large"]
    face = detector.detect(image)[0]
    profile = BUILTIN_PROFILES["default"]
    x, y, w, h = crop_box(face, (image.shape[1], image.shape[0]), profile)
    eye_x, eye_y = face.eye_center
    assert abs((eye_y - y) / h - profile.eye_line) < 0.01
    assert abs(face.width / w - profile.face_width_ratio) < 0.01
    assert x < eye_x < x + w


def test_tight_photo_crops_closer_instead_of_padding(detector, portrait):
    """Little room around the face: the crop gets tighter (up to max_face_width_ratio) before padding."""
    face = detector.detect(portrait)[0]
    tight = portrait[30:330, 120:330]
    shifted = type(face)(**{**face.__dict__, "x": face.x - 120, "y": face.y - 30,
                            "right_eye": (face.right_eye[0] - 120, face.right_eye[1] - 30),
                            "left_eye": (face.left_eye[0] - 120, face.left_eye[1] - 30)})  # fmt: skip
    profile = BUILTIN_PROFILES["default"]
    x, y, w, h = crop_box(shifted, (tight.shape[1], tight.shape[0]), profile)
    ratio = shifted.width / w
    assert profile.face_width_ratio < ratio <= profile.max_face_width_ratio + 1e-6


def test_face_at_the_border_is_padded_with_background(detector, portrait):
    face_only = portrait[60:180, 170:275]  # the face fills the frame: no room at all
    face = detector.detect(cv2.resize(face_only, None, fx=3, fy=3))
    if not face:
        pytest.skip("detector does not find the tightly cropped face")
    image = cv2.resize(face_only, None, fx=3, fy=3)
    result = crop(image, face[0], BUILTIN_PROFILES["default"])
    assert result.padded
    out = cv2.imdecode(np.frombuffer(result.jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert out[2, 2].min() > 240  # white corner


def test_small_source_is_flagged_as_upscaled(detector, portrait):
    face = detector.detect(portrait)[0]
    result = crop(portrait, face, BUILTIN_PROFILES["default"])
    assert result.upscaled  # the 512 px photo has fewer pixels than 600x800 around the face


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 8},
        {"face_width_ratio": 0.8, "max_face_width_ratio": 0.7},
        {"eye_line": 0.9},
        {"max_kb": 1},
        {"jpeg_quality": 10},
        {"background": (0, 0, 300)},
    ],
)
def test_profile_validation(kwargs):
    profile = OutputProfile(**{"name": "x", "width": 300, "height": 400, **kwargs})
    with pytest.raises(ValueError):
        profile.validate()
