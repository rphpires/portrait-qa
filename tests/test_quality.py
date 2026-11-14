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
