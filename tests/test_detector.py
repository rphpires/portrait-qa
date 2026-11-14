import pytest

from portrait_qa.detector import FaceDetector


def test_detects_one_face_with_landmarks(detector, portrait):
    faces = detector.detect(portrait)
    assert len(faces) == 1
    face = faces[0]
    assert face.confidence > 0.85
    x, y, w, h = face.box()
    assert 150 < x < 210 and 40 < y < 90 and 70 < w < 110
    # The subject's right eye is on the left of the image.
    assert face.right_eye[0] < face.left_eye[0]
    assert x < face.nose[0] < x + w
    assert 35 < face.eye_distance < 60
    assert abs(face.yaw_ratio) < 0.3


def test_no_face(detector, cat):
    assert detector.detect(cat) == []


def test_large_image_is_detected_on_a_downscaled_copy(detector, variants):
    """At full resolution YuNet misses / misplaces the face; coordinates must come back in original pixels."""
    faces = detector.detect(variants["large"])
    assert len(faces) == 1
    scale = 3000 / 512
    x, y, w, _ = faces[0].box()
    assert abs(x - 178 * scale) < 25 * scale and abs(y - 63 * scale) < 25 * scale
    assert abs(w - 90 * scale) < 20 * scale


def test_faces_sorted_largest_first(detector, variants):
    faces = detector.detect(variants["two_faces"])
    assert len(faces) == 2
    assert faces[0].area >= faces[1].area


def test_missing_model(tmp_path):
    with pytest.raises(FileNotFoundError):
        FaceDetector(tmp_path / "nope.onnx")
