# Quality checks

Everything here is measured on the **main face** (the largest one) and every limit lives in the `quality`
section of `config.json`. The checks follow the spirit of ISO/IEC 19794-5 and ICAO portrait guidance (one
frontal, sharp, evenly lit face with enough resolution). This is **not** a certified ICAO conformance test.

## Detection

[YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (OpenCV `FaceDetectorYN`,
2023 model, 230 KB, MIT) gives a face box, a confidence and five landmarks: both eyes, nose tip and mouth
corners.

Detection always runs on a copy whose longest side is at most `detector.max_side` (640 px). YuNet is trained on
small inputs: on the test portrait upscaled to 4000 px it took 685 ms and returned a wrong box plus a false
positive, while on the downscaled copy it takes a few milliseconds and is accurate. Coordinates are mapped back to the original,
and every measurement below uses the full-resolution pixels.

## Checks

| Measurement | How | Limit (config key) | Issue |
|---|---|---|---|
| Faces | other faces at least `secondary_face_ratio` (35%) as wide as the main one | | `MULTIPLE_FACES` (error); smaller faces in the background are ignored |
| Detection confidence | YuNet score | `min_confidence` 0.75 | `LOW_CONFIDENCE` (warning) |
| Resolution | distance between the eye centres, px | `min_eye_distance_px` 40 / `good_eye_distance_px` 90 | `FACE_TOO_SMALL` (error) / `LOW_RESOLUTION` (warning) |
| Framing | face box within 2 px of the image edge | | `FACE_CUT_OFF` (warning) |
| Yaw (head turned) | nose offset from the eye midpoint, along the eye line, over half the eye distance (0 = frontal) | `max_yaw_ratio` 0.35 | `HEAD_TURNED` (error) |
| Sharpness | variance of the Laplacian of the face, resampled to 160 px wide and normalized to a fixed contrast | `min_sharpness` 15 (`good_sharpness` 60 for the score) | `BLURRY` (error) |
| Brightness | mean L (CIELAB, 0-255) of the inner face | `min_brightness` 70 / `max_brightness` 200 | `TOO_DARK` / `TOO_BRIGHT` (error) |
| Contrast | standard deviation of L | `min_contrast` 22 | `LOW_CONTRAST` (warning) |
| Burnt highlights | share of face pixels with L ≥ 250 | `max_overexposed_fraction` 0.08 | `OVEREXPOSED` (warning) |
| Side lighting | difference of mean L between the two halves of the face (split at the nose) | `max_lighting_imbalance` 45 | `UNEVEN_LIGHTING` (warning; error above 2×) |

Two details that matter in practice:

- Sharpness is **resolution-independent** (the face is resampled to a fixed width) and
  **contrast-normalized**. Without the normalization a dark but sharp photo reads as blurry, because the
  Laplacian scales with intensity.
- The "inner face" drops 12% on each side and 8% top and bottom of the box, so hair and background do not
  count as face.

## Score

0-100, weighted: sharpness 30, exposure 25 (brightness, contrast, balance, highlights), pose 25 (yaw),
resolution 10, confidence 10. Each part ramps linearly between a "bad" and a "good" value derived from the
limits above. With more than one face the score is capped at 40.

**Passed** = no issue with severity `error` **and** `score >= min_score` (60).

## Calibration

The defaults were calibrated on derived versions of the test portrait (512 px and upscaled to 3000 px):
Gaussian blur σ 2-8, brightness × 0.2-0.35, +110 brightness, two faces side by side, a 128 px thumbnail, half
the face in shadow, JPEG quality 30, horizontal flip. `tests/test_quality.py` locks those outcomes. Real photos
from a given camera or kiosk may need different limits. Run `portrait-qa batch` on a sample folder, look at
the CSV, and adjust `config.json`.

## Known limits

- **Head tilt (roll) is not checked, and the crop does not straighten the head.** YuNet's landmarks stay close
  to a frontal layout: a portrait rotated by 20° reads as about 2°, one rotated by 35° as about 7°. Checking or
  correcting tilt from those numbers would be wrong, so neither is done. A landmark model with real pose
  output (e.g. MediaPipe Face Landmarker) is the way to add it.
- For the same reason **yaw is underestimated**: `HEAD_TURNED` catches clearly turned heads, not slight turns.
- Not checked: eyes open/closed, glasses glare, hats, mouth open, background uniformity, colour cast. Each of
  these needs its own model or rule.
- The test set is small and synthetic (one public-domain portrait and its variants). The thresholds are a
  sensible start, not a validated benchmark.
