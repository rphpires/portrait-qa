"""Shared fixtures. Test photos: ``astronaut.png`` (NASA, public domain) and ``cat.png`` (CC0), both from the
scikit-image data set; every other case is derived from them in code."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from portrait_qa.config import Settings
from portrait_qa.detector import FaceDetector
from portrait_qa.engine import Engine

IMAGES = Path(__file__).parent / "images"


def load(name: str) -> np.ndarray:
    image = cv2.imread(str(IMAGES / name))
    assert image is not None, name
    return image


def jpeg(image: np.ndarray, quality: int = 95) -> bytes:
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()


@pytest.fixture(scope="session")
def portrait() -> np.ndarray:
    return load("astronaut.png")


@pytest.fixture(scope="session")
def cat() -> np.ndarray:
    return load("cat.png")


@pytest.fixture(scope="session")
def detector() -> FaceDetector:
    return FaceDetector()


@pytest.fixture(scope="session")
def variants(portrait) -> dict[str, np.ndarray]:
    img = portrait
    return {
        "original": img,
        "large": cv2.resize(img, (3000, 3000), interpolation=cv2.INTER_CUBIC),
        "blurry": cv2.GaussianBlur(img, (0, 0), 3),
        "dark": (img * 0.3).astype(np.uint8),
        "bright": cv2.convertScaleAbs(img, alpha=1.0, beta=110),
        "two_faces": np.hstack([img, img]),
        "tiny": cv2.resize(img, (128, 128), interpolation=cv2.INTER_AREA),
        "half_shadow": np.hstack([img[:, :224], (img[:, 224:] * 0.3).astype(np.uint8)]),
    }


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    s.server.max_concurrency = 2
    return s


@pytest.fixture
def engine(settings) -> Engine:
    return Engine(settings)
