"""Face detection with YuNet (OpenCV ``FaceDetectorYN``, MIT-licensed model bundled in ``models/``).

Detection always runs on a copy downscaled to ``max_side`` pixels: YuNet is trained on small inputs, and on
full-resolution phone photos it is slow and produces wrong boxes. Coordinates are mapped back to the original.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .imaging import resize_to_max_side

MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"

try:  # OpenCV 5 logs a harmless "Targets are not supported by the new graph engine" warning per detector
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:  # pragma: no cover - older builds without cv2.utils.logging
    pass

Point = tuple[float, float]


@dataclass(frozen=True)
class Face:
    """One detected face, in original-image pixel coordinates.

    ``right_eye`` / ``left_eye`` are the subject's eyes: on a frontal photo the subject's right eye is on the
    left side of the image.
    """

    x: float
    y: float
    width: float
    height: float
    confidence: float
    right_eye: Point
    left_eye: Point
    nose: Point
    mouth_right: Point
    mouth_left: Point

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def eye_center(self) -> Point:
        return ((self.right_eye[0] + self.left_eye[0]) / 2, (self.right_eye[1] + self.left_eye[1]) / 2)

    @property
    def eye_distance(self) -> float:
        return math.dist(self.right_eye, self.left_eye)

    @property
    def yaw_ratio(self) -> float:
        """Rough left/right head turn: 0 = frontal, ±1 = nose level with one eye.

        Measured as the nose offset from the eye midpoint along the eye line, over half the eye distance.
        """
        half = self.eye_distance / 2
        if half <= 0:
            return 0.0
        ex, ey = self.eye_center
        ux = (self.left_eye[0] - self.right_eye[0]) / (2 * half)
        uy = (self.left_eye[1] - self.right_eye[1]) / (2 * half)
        return ((self.nose[0] - ex) * ux + (self.nose[1] - ey) * uy) / half

    def box(self) -> list[int]:
        return [round(self.x), round(self.y), round(self.width), round(self.height)]


class FaceDetector:
    """Thread-safe wrapper: each thread gets its own ``FaceDetectorYN`` (the OpenCV object is not thread-safe)."""

    def __init__(
        self,
        model_path: Path = MODEL_PATH,
        *,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        max_side: int = 640,
    ):
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Face detection model not found: {model_path}")
        self.model_path = str(model_path)
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.max_side = max_side
        self._local = threading.local()

    def _net(self):
        net = getattr(self._local, "net", None)
        if net is None:
            net = cv2.FaceDetectorYN.create(
                self.model_path, "", (320, 320), self.score_threshold, self.nms_threshold, 50
            )
            self._local.net = net
        return net

    def detect(self, image: np.ndarray) -> list[Face]:
        """Faces sorted by area, largest first."""
        small, scale = resize_to_max_side(image, self.max_side)
        height, width = small.shape[:2]
        net = self._net()
        net.setInputSize((width, height))
        _, raw = net.detect(small)
        if raw is None:
            return []
        inv = 1.0 / scale
        faces = []
        for row in raw:
            v = [float(c) * inv for c in row[:14]]
            faces.append(
                Face(
                    x=v[0],
                    y=v[1],
                    width=v[2],
                    height=v[3],
                    confidence=float(row[14]),
                    right_eye=(v[4], v[5]),
                    left_eye=(v[6], v[7]),
                    nose=(v[8], v[9]),
                    mouth_right=(v[10], v[11]),
                    mouth_left=(v[12], v[13]),
                )
            )
        faces.sort(key=lambda f: f.area, reverse=True)
        return faces
