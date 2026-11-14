"""HTTP API (FastAPI).

The image can be sent three ways, on every POST endpoint:
- ``multipart/form-data`` with a file field named ``image``;
- ``application/json`` with ``{"image_base64": "..."}`` (a ``data:image/...;base64,`` prefix is accepted);
- the raw bytes, with ``Content-Type: image/jpeg`` / ``image/png`` / ``application/octet-stream``.

Reading the body is async; the CPU work runs in a worker thread, bounded by ``server.max_concurrency``.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import APP_NAME, __version__
from .config import Settings
from .engine import Engine, Result
from .errors import ImageTooLargeError, InvalidImageError, PortraitQAError

log = logging.getLogger("portrait_qa.api")

WEB_DIR = Path(__file__).resolve().parent / "web"
PUBLIC_PATHS = {"/", "/v1/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}

_IMAGE_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {"type": "object", "required": ["image"],
                       "properties": {"image": {"type": "string", "format": "binary"}}}
        },
        "application/json": {
            "schema": {"type": "object", "required": ["image_base64"],
                       "properties": {"image_base64": {"type": "string", "description": "JPEG/PNG/BMP/WebP, base64"}}}
        },
        "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
        "image/png": {"schema": {"type": "string", "format": "binary"}},
    },
}  # fmt: skip

_PROFILE_PARAM = {
    "name": "profile",
    "in": "query",
    "required": False,
    "schema": {"type": "string"},
    "description": "Output profile (GET /v1/profiles). Default: default_profile in config.json.",
}
_FORMAT_PARAM = {
    "name": "format",
    "in": "query",
    "required": False,
    "schema": {"type": "string", "enum": ["json", "jpeg"], "default": "json"},
    "description": "json: report + image in base64. jpeg: only the image; the report goes in X-Portrait-* headers.",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


async def read_body(request: Request, max_bytes: int) -> bytes:
    """Read the body, refusing it as soon as it exceeds ``max_bytes`` (works without Content-Length, e.g.
    chunked uploads). The body is cached on the request so ``request.form()`` can parse it afterwards."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_bytes:
        raise ImageTooLargeError(f"Request body is too large; the limit is {max_bytes / 1e6:.1f} MB.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise ImageTooLargeError(f"Request body is too large; the limit is {max_bytes / 1e6:.1f} MB.")
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body  # Starlette reads a cached body from here (stream(), body(), form())
    return body


async def read_image(request: Request, max_bytes: int) -> bytes:
    """Extract the image bytes from any of the accepted body formats."""
    # Base64 and multipart add overhead on top of the image limit.
    body = await read_body(request, int(max_bytes * 1.4) + 64 * 1024)
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype == "multipart/form-data":
        try:
            form = await request.form()
        except Exception:  # malformed multipart: python-multipart raises various errors
            raise InvalidImageError("Malformed multipart body.") from None
        upload = form.get("image")
        if upload is None or isinstance(upload, str):
            raise InvalidImageError("Multipart body must have a file field named 'image'.")
        return await upload.read()
    if ctype == "application/json":
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise InvalidImageError("Body is not valid JSON.") from None
        value = payload.get("image_base64") if isinstance(payload, dict) else None
        if not isinstance(value, str) or not value:
            raise InvalidImageError("JSON body must have a non-empty 'image_base64' string.")
        if value.startswith("data:"):
            value = value.partition(",")[2]
        value = "".join(value.split())  # base64 wrapped at 64/76 columns (openssl, MIME) is common
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise InvalidImageError("'image_base64' is not valid base64.") from None
    if ctype.startswith("image/") or ctype in ("application/octet-stream", ""):
        return body
    raise InvalidImageError(f"Unsupported Content-Type {ctype!r}; use multipart/form-data, JSON or image/*.")


def _result_json(result: Result, include_image: bool = True) -> dict:
    data = result.report.to_dict()
    if result.crop is not None:
        info = result.crop.info()
        if include_image:
            info["image_base64"] = base64.b64encode(result.crop.jpeg).decode("ascii")
        data["crop"] = info
    else:
        data["crop"] = None
    data["elapsed_ms"] = round(result.elapsed_ms, 1)
    return data


def create_app(settings: Settings, engine: Engine | None = None) -> FastAPI:
    engine = engine or Engine(settings)
    started = time.time()
    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        description="Face photo quality check and portrait crop. See docs/api.md for the issue codes.",
    )
    app.state.engine = engine
    app.state.settings = settings

    @app.middleware("http")
    async def auth_and_log(request: Request, call_next):
        start = time.perf_counter()
        key = settings.server.api_key
        if key and request.url.path not in PUBLIC_PATHS and request.method != "OPTIONS":
            sent = request.headers.get("x-api-key") or ""
            auth = request.headers.get("authorization", "")
            if not sent and auth.lower().startswith("bearer "):
                sent = auth[7:].strip()
            if not hmac.compare_digest(sent.encode(), key.encode()):
                log.warning("%s %s 401 from %s", request.method, request.url.path, _client(request))
                return _error(401, "UNAUTHORIZED", "Missing or invalid API key (header X-API-Key).")
        response = await call_next(request)
        log.info("%s %s %s %.0fms from %s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000, _client(request))  # fmt: skip
        return response

    # Added after the auth middleware, so it wraps it: 401 answers carry CORS headers too.
    if settings.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            expose_headers=["X-Portrait-Passed", "X-Portrait-Score", "X-Portrait-Issues"],
        )

    @app.exception_handler(PortraitQAError)
    async def domain_error(_request: Request, exc: PortraitQAError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):  # pragma: no cover - safety net
        log.exception("Unexpected error")
        return _error(500, "INTERNAL_ERROR", "Unexpected error; see the service log.")

    @app.get("/", include_in_schema=False)
    def test_page():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/v1/health", summary="Service status (no API key needed)")
    def health():
        return {
            "status": "ok",
            "name": APP_NAME,
            "version": __version__,
            "uptime_seconds": round(time.time() - started),
            "auth_required": bool(settings.server.api_key),
        }

    @app.get("/v1/profiles", summary="Output profiles available for crop/process")
    def profiles():
        return {
            "default": settings.default_profile,
            "profiles": [p.to_dict() for p in settings.all_profiles.values()],
        }

    async def handle(request: Request, mode: str) -> Response:
        data = await read_image(request, settings.max_upload_bytes)
        profile = request.query_params.get("profile")
        fmt = request.query_params.get("format", "json").lower()
        if fmt not in ("json", "jpeg"):
            return _error(400, "INVALID_FORMAT", "format must be 'json' or 'jpeg'.")
        result = await run_in_threadpool(engine.run, data, mode=mode, profile=profile)
        if fmt == "jpeg" and mode != "assess":
            report = result.report
            headers = {
                "X-Portrait-Passed": str(report.passed).lower(),
                "X-Portrait-Score": str(report.score),
                "X-Portrait-Issues": ",".join(i.code for i in report.issues),
            }
            if result.crop is None:  # process mode and the photo failed
                return JSONResponse(status_code=200, content=_result_json(result), headers=headers)
            return Response(content=result.crop.jpeg, media_type="image/jpeg", headers=headers)
        return JSONResponse(content=_result_json(result))

    @app.post(
        "/v1/assess",
        summary="Quality check only",
        openapi_extra={"requestBody": _IMAGE_BODY},
    )
    async def assess_endpoint(request: Request):
        return await handle(request, "assess")

    @app.post(
        "/v1/crop",
        summary="Crop the main face (even if the quality check fails) + quality report",
        openapi_extra={"requestBody": _IMAGE_BODY, "parameters": [_PROFILE_PARAM, _FORMAT_PARAM]},
    )
    async def crop_endpoint(request: Request):
        return await handle(request, "crop")

    @app.post(
        "/v1/process",
        summary="Quality check, and crop only if the photo passes",
        openapi_extra={"requestBody": _IMAGE_BODY, "parameters": [_PROFILE_PARAM, _FORMAT_PARAM]},
    )
    async def process_endpoint(request: Request):
        return await handle(request, "process")

    return app


def _client(request: Request) -> str:
    return request.client.host if request.client else "-"
