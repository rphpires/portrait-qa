"""Quality assessment of a face photo.

The result is a list of issues with stable codes plus a 0-100 score. Issues with severity ``error`` make the
photo fail regardless of the score; ``warning`` issues only lower it. All limits live in ``QualityThresholds``
and can be changed in ``config.json``.

The checks follow the spirit of ISO/IEC 19794-5 / ICAO portrait guidance (one frontal face, sharp, evenly lit,
enough resolution) but this is not a certified ICAO conformance test.

Head pose comes from YuNet's five landmarks, which stay close to a frontal layout even when the head is not:
the yaw check catches clearly turned heads only, and in-plane tilt (roll) is not checked at all because the
landmarks underestimate it about fivefold (measured: a 35 degree tilt reads as about 7).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .detector import Face

ERROR = "error"
WARNING = "warning"

# Stable issue codes (documented in docs/api.md). Never rename; add new ones instead.
NO_FACE = "NO_FACE"
MULTIPLE_FACES = "MULTIPLE_FACES"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
FACE_TOO_SMALL = "FACE_TOO_SMALL"
LOW_RESOLUTION = "LOW_RESOLUTION"
FACE_CUT_OFF = "FACE_CUT_OFF"
HEAD_TURNED = "HEAD_TURNED"
BLURRY = "BLURRY"
TOO_DARK = "TOO_DARK"
TOO_BRIGHT = "TOO_BRIGHT"
LOW_CONTRAST = "LOW_CONTRAST"
OVEREXPOSED = "OVEREXPOSED"
UNEVEN_LIGHTING = "UNEVEN_LIGHTING"

# Weights of the score components (sum = 100).
_WEIGHTS = {"sharpness": 30, "exposure": 25, "pose": 25, "resolution": 10, "confidence": 10}

# The face is resampled to this width before measuring sharpness, so the number does not depend on resolution.
_SHARPNESS_WIDTH = 160
_SHARPNESS_STD = 40.0


@dataclass
class QualityThresholds:
    min_score: int = 60
    min_confidence: float = 0.75
    min_eye_distance_px: float = 40  # below: error FACE_TOO_SMALL
    good_eye_distance_px: float = 90  # below: warning LOW_RESOLUTION (a commonly cited minimum for ID portraits)
    secondary_face_ratio: float = 0.35  # another face at least this wide (vs. the main one) = MULTIPLE_FACES
    max_yaw_ratio: float = 0.35
    min_sharpness: float = 15.0  # variance of the Laplacian on the face, normalized in size and contrast
    good_sharpness: float = 60.0
    min_brightness: float = 70.0  # mean L (0-255) on the face
    max_brightness: float = 200.0
    min_contrast: float = 22.0  # std of L on the face
    max_overexposed_fraction: float = 0.08  # share of face pixels with L >= 250
    max_lighting_imbalance: float = 45.0  # |mean L left half - right half|


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    value: float | None = None
    limit: float | None = None


@dataclass
class FaceMetrics:
    box: list[int]
    confidence: float
    eye_distance_px: float
    yaw_ratio: float
    sharpness: float
    brightness: float
    contrast: float
    overexposed_fraction: float
    lighting_imbalance: float


@dataclass
class QualityReport:
    passed: bool
    score: int
    faces: int
    image_size: list[int]
    issues: list[Issue] = field(default_factory=list)
    face: FaceMetrics | None = None
    # Not serialized: kept for the crop step.
    main_face: Face | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("main_face", None)
        for key in ("value", "limit"):
            for issue in data["issues"]:
                if isinstance(issue[key], float):
                    issue[key] = round(issue[key], 3)
        if data["face"]:
            data["face"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in data["face"].items()}
        return data


def _ramp(value: float, bad: float, good: float) -> float:
    """0 at ``bad``, 1 at ``good`` (works in both directions), clamped."""
    if good == bad:
        return 1.0 if value >= good else 0.0
    return min(1.0, max(0.0, (value - bad) / (good - bad)))


def _face_region(image: np.ndarray, face: Face) -> np.ndarray:
    """Inner part of the face box (drops hair/background at the borders)."""
    height, width = image.shape[:2]
    inset_x, inset_y = face.width * 0.12, face.height * 0.08
    x0 = int(max(0, face.x + inset_x))
    y0 = int(max(0, face.y + inset_y))
    x1 = int(min(width, face.x + face.width - inset_x))
    y1 = int(min(height, face.y + face.height - inset_y))
    if x1 - x0 < 4 or y1 - y0 < 4:
        x0, y0 = int(max(0, face.x)), int(max(0, face.y))
        x1, y1 = int(min(width, face.x + face.width)), int(min(height, face.y + face.height))
    return image[y0:y1, x0:x1]


def measure(image: np.ndarray, face: Face) -> FaceMetrics:
    region = _face_region(image, face)
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    scale = _SHARPNESS_WIDTH / gray.shape[1]
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    norm = cv2.resize(gray, (_SHARPNESS_WIDTH, max(4, round(gray.shape[0] * scale))), interpolation=interp)
    norm = norm.astype(np.float64)
    std = norm.std()
    # Contrast normalization: without it a dark (but sharp) face would read as blurry.
    norm = (norm - norm.mean()) * (_SHARPNESS_STD / std) if std > 1e-6 else norm * 0
    sharpness = float(cv2.Laplacian(norm, cv2.CV_64F).var())

    lum = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float64)
    split = int(min(max(face.nose[0] - (face.x + face.width * 0.12), 1), lum.shape[1] - 1))
    left, right = lum[:, :split], lum[:, split:]
    imbalance = abs(float(left.mean()) - float(right.mean())) if left.size and right.size else 0.0

    return FaceMetrics(
        box=face.box(),
        confidence=face.confidence,
        eye_distance_px=face.eye_distance,
        yaw_ratio=face.yaw_ratio,
        sharpness=sharpness,
        brightness=float(lum.mean()),
        contrast=float(lum.std()),
        overexposed_fraction=float((lum >= 250).mean()),
        lighting_imbalance=imbalance,
    )


def assess(image: np.ndarray, faces: list[Face], t: QualityThresholds) -> QualityReport:
    height, width = image.shape[:2]
    size = [width, height]
    if not faces:
        issue = Issue(NO_FACE, ERROR, "No face was found in the image.")
        return QualityReport(passed=False, score=0, faces=0, image_size=size, issues=[issue])

    main = faces[0]
    issues: list[Issue] = []
    m = measure(image, main)

    others = [f for f in faces[1:] if f.width >= main.width * t.secondary_face_ratio]
    if others:
        issues.append(
            Issue(MULTIPLE_FACES, ERROR, f"{len(others) + 1} faces in the image; only one is allowed.", len(others) + 1)
        )
    if m.confidence < t.min_confidence:
        issues.append(
            Issue(LOW_CONFIDENCE, WARNING, "The face was detected with low confidence.", m.confidence, t.min_confidence)
        )
    if m.eye_distance_px < t.min_eye_distance_px:
        issues.append(
            Issue(FACE_TOO_SMALL, ERROR, "The face is too small (too few pixels between the eyes).",
                  m.eye_distance_px, t.min_eye_distance_px)
        )  # fmt: skip
    elif m.eye_distance_px < t.good_eye_distance_px:
        issues.append(
            Issue(LOW_RESOLUTION, WARNING, "Face resolution is below the recommended value.",
                  m.eye_distance_px, t.good_eye_distance_px)
        )  # fmt: skip
    margin = 2
    if (
        main.x <= margin
        or main.y <= margin
        or main.x + main.width >= width - margin
        or main.y + main.height >= height - margin
    ):
        issues.append(Issue(FACE_CUT_OFF, WARNING, "The face touches the edge of the image."))
    if abs(m.yaw_ratio) > t.max_yaw_ratio:
        issues.append(Issue(HEAD_TURNED, ERROR, "The head is turned to the side.", abs(m.yaw_ratio), t.max_yaw_ratio))
    if m.sharpness < t.min_sharpness:
        issues.append(Issue(BLURRY, ERROR, "The face is blurry or out of focus.", m.sharpness, t.min_sharpness))
    if m.brightness < t.min_brightness:
        issues.append(Issue(TOO_DARK, ERROR, "The face is too dark.", m.brightness, t.min_brightness))
    elif m.brightness > t.max_brightness:
        issues.append(Issue(TOO_BRIGHT, ERROR, "The face is too bright.", m.brightness, t.max_brightness))
    if m.contrast < t.min_contrast:
        issues.append(Issue(LOW_CONTRAST, WARNING, "The face has low contrast.", m.contrast, t.min_contrast))
    if m.overexposed_fraction > t.max_overexposed_fraction:
        issues.append(
            Issue(OVEREXPOSED, WARNING, "Part of the face is overexposed (burnt highlights).",
                  m.overexposed_fraction, t.max_overexposed_fraction)
        )  # fmt: skip
    if m.lighting_imbalance > t.max_lighting_imbalance:
        # Twice the limit (e.g. half the face in shadow) is not usable for recognition.
        severity = ERROR if m.lighting_imbalance > 2 * t.max_lighting_imbalance else WARNING
        issues.append(
            Issue(UNEVEN_LIGHTING, severity, "One side of the face is much darker than the other.",
                  m.lighting_imbalance, t.max_lighting_imbalance)
        )  # fmt: skip

    score = _score(m, t)
    if others:
        score = min(score, 40)
    passed = score >= t.min_score and not any(i.severity == ERROR for i in issues)
    return QualityReport(passed=passed, score=score, faces=1 + len(others), image_size=size, issues=issues,
                         face=m, main_face=main)  # fmt: skip


def _score(m: FaceMetrics, t: QualityThresholds) -> int:
    sharp = _ramp(math.log1p(m.sharpness), math.log1p(t.min_sharpness * 0.5), math.log1p(t.good_sharpness))
    mid = (t.min_brightness + t.max_brightness) / 2
    half = (t.max_brightness - t.min_brightness) / 2
    bright = 1.0 - min(1.0, max(0.0, (abs(m.brightness - mid) - half * 0.5) / (half * 0.8)))
    contrast = _ramp(m.contrast, t.min_contrast * 0.5, t.min_contrast * 2)
    balance = _ramp(m.lighting_imbalance, t.max_lighting_imbalance * 1.5, t.max_lighting_imbalance * 0.3)
    exposure = 0.5 * bright + 0.25 * contrast + 0.25 * balance - min(0.5, m.overexposed_fraction * 2)
    pose = _ramp(abs(m.yaw_ratio), t.max_yaw_ratio * 1.5, t.max_yaw_ratio * 0.3)
    resolution = _ramp(m.eye_distance_px, t.min_eye_distance_px * 0.75, t.good_eye_distance_px)
    confidence = _ramp(m.confidence, t.min_confidence * 0.8, 0.9)
    parts = {
        "sharpness": sharp,
        "exposure": max(0.0, exposure),
        "pose": pose,
        "resolution": resolution,
        "confidence": confidence,
    }
    return round(sum(_WEIGHTS[k] * v for k, v in parts.items()))
