"""The engine: decode once, detect once, then assess and/or crop. Used by the API and the CLI."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from . import imaging
from .config import Settings
from .crop import CropResult, OutputProfile, crop
from .detector import FaceDetector
from .errors import BusyError, NoFaceError, UnknownProfileError
from .quality import QualityReport, assess


@dataclass
class Result:
    report: QualityReport
    crop: CropResult | None = None
    elapsed_ms: float = 0.0


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector = FaceDetector(
            score_threshold=settings.detector.score_threshold, max_side=settings.detector.max_side
        )
        self._slots = threading.BoundedSemaphore(settings.concurrency())

    @contextmanager
    def _slot(self):
        if not self._slots.acquire(timeout=self.settings.server.queue_timeout_seconds):
            raise BusyError("The service is busy; try again in a moment.")
        try:
            yield
        finally:
            self._slots.release()

    def profile(self, name: str | None) -> OutputProfile:
        name = name or self.settings.default_profile
        try:
            return self.settings.all_profiles[name]
        except KeyError:
            known = ", ".join(sorted(self.settings.all_profiles))
            raise UnknownProfileError(f"Unknown profile {name!r}; available: {known}.") from None

    def decode(self, data: bytes) -> np.ndarray:
        return imaging.decode(data, max_bytes=self.settings.max_upload_bytes, max_pixels=self.settings.max_pixels)

    def assess_image(self, image: np.ndarray) -> QualityReport:
        return assess(image, self.detector.detect(image), self.settings.quality)

    def run(self, data: bytes, *, mode: str, profile: str | None = None) -> Result:
        """``mode``: ``assess`` (report only), ``crop`` (always crop when a face exists) or ``process``
        (crop only when the photo passes)."""
        if mode not in ("assess", "crop", "process"):
            raise ValueError(f"unknown mode {mode!r}")
        out_profile = self.profile(profile) if mode != "assess" else None
        start = time.perf_counter()
        with self._slot():
            image = self.decode(data)
            report = self.assess_image(image)
            cropped = None
            if mode == "crop":
                if report.main_face is None:
                    raise NoFaceError("No face was found in the image, so it cannot be cropped.")
                cropped = crop(image, report.main_face, out_profile)
            elif mode == "process" and report.passed:
                cropped = crop(image, report.main_face, out_profile)
        return Result(report=report, crop=cropped, elapsed_ms=(time.perf_counter() - start) * 1000)
