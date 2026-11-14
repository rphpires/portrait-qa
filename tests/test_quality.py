import pytest

from portrait_qa import quality as q
from portrait_qa.quality import QualityThresholds, assess


def run(detector, image, thresholds=None):
    return assess(image, detector.detect(image), thresholds or QualityThresholds())


def codes(report):
    return {i.code for i in report.issues}


def errors(report):
    return {i.code for i in report.issues if i.severity == q.ERROR}


def test_good_photo_passes(detector, variants):
    report = run(detector, variants["large"])
    assert report.passed
    assert report.score >= 80
    assert errors(report) == set()
    assert report.faces == 1


def test_small_but_usable_photo_passes_with_resolution_warning(detector, variants):
    report = run(detector, variants["original"])
    assert report.passed
    assert codes(report) == {q.LOW_RESOLUTION}


def test_no_face(detector, cat):
    report = run(detector, cat)
    assert not report.passed and report.score == 0 and report.faces == 0
    assert codes(report) == {q.NO_FACE}
    assert report.face is None


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("blurry", q.BLURRY),
        ("dark", q.TOO_DARK),
        ("bright", q.TOO_BRIGHT),
        ("two_faces", q.MULTIPLE_FACES),
        ("tiny", q.FACE_TOO_SMALL),
        ("half_shadow", q.UNEVEN_LIGHTING),
    ],
)
def test_bad_photos_fail_with_the_right_code(detector, variants, variant, expected):
    report = run(detector, variants[variant])
    assert not report.passed
    assert expected in errors(report)


def test_dark_photo_is_not_reported_as_blurry(detector, variants):
    """Sharpness is contrast-normalized: a sharp but dark face must not read as out of focus."""
    report = run(detector, variants["dark"])
    assert q.BLURRY not in codes(report)


def test_small_background_face_is_ignored(detector, portrait):
    import cv2
    import numpy as np

    small = cv2.resize(portrait, (150, 150))
    canvas = np.hstack([portrait, np.full((512, 200, 3), 200, np.uint8)])
    canvas[350:500, 540:690] = small  # a face much smaller than the main one
    report = run(detector, canvas)
    assert q.MULTIPLE_FACES not in codes(report)


def test_thresholds_are_configurable(detector, variants):
    strict = QualityThresholds(min_score=95)
    report = run(detector, variants["large"], strict)
    assert not report.passed  # score below min_score, even without error issues
    assert errors(report) == set()


def test_report_serialization(detector, variants):
    data = run(detector, variants["original"]).to_dict()
    assert set(data) == {"passed", "score", "faces", "image_size", "issues", "face"}
    assert data["image_size"] == [512, 512]
    assert set(data["face"]) >= {"box", "confidence", "eye_distance_px", "yaw_ratio", "sharpness", "brightness"}
    assert data["issues"][0] == {
        "code": "LOW_RESOLUTION",
        "severity": "warning",
        "message": data["issues"][0]["message"],
        "value": data["issues"][0]["value"],
        "limit": 90,
    }


def make_face(x, y, w, h, nose_x=None):
    from portrait_qa.detector import Face

    cy = y + h * 0.4
    nose_x = x + w / 2 if nose_x is None else nose_x
    return Face(x=x, y=y, width=w, height=h, confidence=0.9, right_eye=(x + w * 0.3, cy), left_eye=(x + w * 0.7, cy),
                nose=(nose_x, y + h * 0.6), mouth_right=(x + w * 0.35, y + h * 0.8),
                mouth_left=(x + w * 0.65, y + h * 0.8))  # fmt: skip


def test_lighting_split_uses_the_nose_for_faces_at_the_left_edge():
    """The face box starts at x=0 (clipped by the detector); the split must still be at the nose."""
    import numpy as np

    image = np.zeros((200, 200, 3), np.uint8)
    image[:, :60] = 60
    image[:, 60:] = 200
    face = make_face(0, 20, 120, 160, nose_x=60)
    m = q.measure(image, face)
    assert m.lighting_imbalance > 130


def test_detector_clips_boxes_to_the_image(detector, portrait):
    """A face cut by the left edge: the box is clipped, measurements and crop still work."""
    from portrait_qa.crop import BUILTIN_PROFILES, crop

    cut = portrait[:, 200:]  # cuts through the face (it starts around x=178)
    faces = detector.detect(cut)
    for face in faces:
        assert face.x >= 0 and face.y >= 0
        assert face.x + face.width <= cut.shape[1] and face.y + face.height <= cut.shape[0]
    report = assess(cut, faces, QualityThresholds())
    if report.main_face is not None:
        result = crop(cut, report.main_face, BUILTIN_PROFILES["badge"])
        assert result.width == 300


def test_crop_rectangle_partly_outside_the_image_is_padded():
    import cv2
    import numpy as np

    from portrait_qa.crop import BUILTIN_PROFILES, crop

    image = np.full((100, 100, 3), 120, np.uint8)
    face = make_face(0, 0, 60, 80)  # face in the top-left corner: the crop extends far outside
    result = crop(image, face, BUILTIN_PROFILES["badge"])
    out = cv2.imdecode(np.frombuffer(result.jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert result.padded and out.shape[:2] == (400, 300)
    assert out[2, 2].min() > 240  # background in the corner that lies outside the image
