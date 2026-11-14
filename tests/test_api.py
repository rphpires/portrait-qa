import base64
import threading

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from portrait_qa import __version__
from portrait_qa.api import create_app
from portrait_qa.config import Settings
from portrait_qa.crop import OutputProfile
from portrait_qa.engine import Engine

from .conftest import jpeg


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def good(variants):
    return jpeg(variants["large"], 90)


@pytest.fixture(scope="module")
def blurry(variants):
    return jpeg(variants["blurry"])


@pytest.fixture(scope="module")
def no_face(cat):
    return jpeg(cat)


def test_health_and_profiles(client):
    health = client.get("/v1/health").json()
    assert health["status"] == "ok" and health["version"] == __version__ and health["auth_required"] is False
    profiles = client.get("/v1/profiles").json()
    assert profiles["default"] == "default"
    assert {"default", "compact", "badge", "square"} <= {p["name"] for p in profiles["profiles"]}


def test_test_page_and_docs(client):
    assert "Portrait QA" in client.get("/").text
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "multipart/form-data" in spec["paths"]["/v1/assess"]["post"]["requestBody"]["content"]


def test_assess_multipart(client, good):
    r = client.post("/v1/assess", files={"image": ("photo.jpg", good, "image/jpeg")})
    assert r.status_code == 200
    data = r.json()
    assert data["passed"] is True and data["faces"] == 1 and data["crop"] is None
    assert data["elapsed_ms"] >= 0


def test_assess_json_base64_and_data_url(client, good):
    b64 = base64.b64encode(good).decode()
    assert client.post("/v1/assess", json={"image_base64": b64}).json()["passed"] is True
    url = "data:image/jpeg;base64," + b64
    assert client.post("/v1/assess", json={"image_base64": url}).json()["passed"] is True


def test_assess_raw_body(client, good):
    r = client.post("/v1/assess", content=good, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["passed"] is True


def test_crop_json(client, good):
    r = client.post("/v1/crop?profile=badge", files={"image": ("p.jpg", good)})
    data = r.json()
    crop = data["crop"]
    assert crop["width"] == 300 and crop["height"] == 400 and crop["profile"] == "badge"
    image = cv2.imdecode(np.frombuffer(base64.b64decode(crop["image_base64"]), np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (400, 300)
    assert crop["bytes"] == len(base64.b64decode(crop["image_base64"]))


def test_crop_jpeg_format(client, good):
    r = client.post("/v1/crop?format=jpeg", files={"image": ("p.jpg", good)})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-portrait-passed"] == "true"
    assert int(r.headers["x-portrait-score"]) > 0
    assert r.content.startswith(b"\xff\xd8")


def test_crop_happens_even_when_quality_fails(client, blurry):
    data = client.post("/v1/crop", files={"image": ("p.jpg", blurry)}).json()
    assert data["passed"] is False and data["crop"] is not None


def test_process_crops_only_when_passed(client, good, blurry):
    ok = client.post("/v1/process", files={"image": ("p.jpg", good)}).json()
    assert ok["passed"] and ok["crop"]
    bad = client.post("/v1/process", files={"image": ("p.jpg", blurry)}).json()
    assert not bad["passed"] and bad["crop"] is None
    assert "BLURRY" in {i["code"] for i in bad["issues"]}
    # format=jpeg on a failed photo: JSON report instead of an image
    r = client.post("/v1/process?format=jpeg", files={"image": ("p.jpg", blurry)})
    assert r.headers["content-type"].startswith("application/json") and r.headers["x-portrait-passed"] == "false"


def test_crop_without_face_is_422(client, no_face):
    r = client.post("/v1/crop", files={"image": ("cat.jpg", no_face)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_FACE"
    # assess and process answer 200 with NO_FACE in the report
    r = client.post("/v1/process", files={"image": ("cat.jpg", no_face)})
    assert r.status_code == 200 and r.json()["issues"][0]["code"] == "NO_FACE"


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"files": {"other": ("x.jpg", b"123")}}, 400, "INVALID_IMAGE"),
        ({"json": {"image_base64": "%%%"}}, 400, "INVALID_IMAGE"),
        ({"json": {"nope": 1}}, 400, "INVALID_IMAGE"),
        ({"content": b"{not json", "headers": {"Content-Type": "application/json"}}, 400, "INVALID_IMAGE"),
        ({"content": b"abc", "headers": {"Content-Type": "text/plain"}}, 400, "INVALID_IMAGE"),
        ({"content": b"GIF89a", "headers": {"Content-Type": "image/gif"}}, 400, "INVALID_IMAGE"),
    ],
)
def test_bad_requests(client, kwargs, status, code):
    r = client.post("/v1/assess", **kwargs)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


def test_unknown_profile_and_format(client, good):
    r = client.post("/v1/crop?profile=nope", files={"image": ("p.jpg", good)})
    assert r.status_code == 400 and r.json()["error"]["code"] == "UNKNOWN_PROFILE"
    r = client.post("/v1/crop?format=png", files={"image": ("p.jpg", good)})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_FORMAT"


def test_upload_limit(good):
    s = Settings()
    s.limits.max_upload_mb = 0.01
    client = TestClient(create_app(s))
    r = client.post("/v1/assess", content=good, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "IMAGE_TOO_LARGE"


def test_custom_profile_from_settings(good):
    s = Settings(profiles={"tiny": OutputProfile("tiny", 120, 160, max_kb=20)})
    client = TestClient(create_app(s))
    crop = client.post("/v1/crop?profile=tiny", files={"image": ("p.jpg", good)}).json()["crop"]
    assert (crop["width"], crop["height"]) == (120, 160)


def test_api_key(good):
    s = Settings()
    s.server.api_key = "k" * 20
    client = TestClient(create_app(s))
    assert client.get("/v1/health").json()["auth_required"] is True  # public
    assert client.get("/").status_code == 200  # test page is public; it asks for the key
    r = client.post("/v1/assess", files={"image": ("p.jpg", good)})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
    assert client.get("/v1/profiles").status_code == 401
    r = client.post("/v1/assess", files={"image": ("p.jpg", good)}, headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    r = client.post("/v1/assess", files={"image": ("p.jpg", good)}, headers={"X-API-Key": "k" * 20})
    assert r.status_code == 200
    r = client.post("/v1/assess", files={"image": ("p.jpg", good)}, headers={"Authorization": "Bearer " + "k" * 20})
    assert r.status_code == 200


def test_busy_returns_503(good):
    s = Settings()
    s.server.max_concurrency = 1
    s.server.queue_timeout_seconds = 0.05
    engine = Engine(s)
    client = TestClient(create_app(s, engine))
    engine._slots.acquire()  # simulate a long request holding the only slot
    try:
        r = client.post("/v1/assess", files={"image": ("p.jpg", good)})
        assert r.status_code == 503 and r.json()["error"]["code"] == "BUSY"
    finally:
        engine._slots.release()
    assert client.post("/v1/assess", files={"image": ("p.jpg", good)}).status_code == 200


def test_concurrent_requests(client, good):
    """Detector instances are per thread; parallel requests must all succeed with the same result."""
    scores = []

    def call():
        scores.append(client.post("/v1/assess", files={"image": ("p.jpg", good)}).json()["score"])

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(scores) == 8 and len(set(scores)) == 1


def test_cors(good):
    s = Settings()
    s.server.cors_origins = ["https://app.example"]
    client = TestClient(create_app(s))
    r = client.options("/v1/assess", headers={"Origin": "https://app.example", "Access-Control-Request-Method": "POST"})
    assert r.headers["access-control-allow-origin"] == "https://app.example"


def test_chunked_upload_over_the_limit_is_refused(good):
    """No Content-Length (chunked): the limit is enforced while reading."""
    s = Settings()
    s.limits.max_upload_mb = 0.05
    client = TestClient(create_app(s))

    def body():
        for _ in range(100):
            yield b"\xff" * 10_000

    r = client.post("/v1/assess", content=body(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "IMAGE_TOO_LARGE"


def test_chunked_upload_within_the_limit_works(client, good):
    def body():
        for i in range(0, len(good), 4096):
            yield good[i : i + 4096]

    r = client.post("/v1/assess", content=body(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["passed"] is True


def test_wrapped_base64_is_accepted(client, good):
    wrapped = base64.encodebytes(good).decode()  # newline every 76 characters
    assert "\n" in wrapped
    assert client.post("/v1/assess", json={"image_base64": wrapped}).json()["passed"] is True


def test_unauthorized_answer_has_cors_headers(good):
    s = Settings()
    s.server.api_key = "k" * 20
    s.server.cors_origins = ["https://app.example"]
    client = TestClient(create_app(s))
    r = client.post("/v1/assess", files={"image": ("p.jpg", good)}, headers={"Origin": "https://app.example"})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == "https://app.example"


def test_transparent_png_upload(client, portrait):
    rgba = cv2.cvtColor(portrait, cv2.COLOR_BGR2BGRA)
    rgba[:, :40, 3] = 0  # transparent strip on the left
    data = cv2.imencode(".png", rgba)[1].tobytes()
    r = client.post("/v1/crop", files={"image": ("p.png", data, "image/png")})
    assert r.status_code == 200 and r.json()["faces"] == 1
