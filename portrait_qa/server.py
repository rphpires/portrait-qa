"""Run the API with uvicorn. Shared by ``portrait-qa serve`` and the Windows service."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import uvicorn

from . import __version__
from .api import create_app
from .config import Settings

log = logging.getLogger("portrait_qa")


def setup_logging(
    level: str = "info", *, folder: Path | None = None, to_file: bool = True, to_console: bool = True
) -> Path | None:
    """Rotating file ``<folder>/portrait-qa.log`` (5 x 5 MB) and/or the console."""
    root = logging.getLogger("portrait_qa")
    root.setLevel(level.upper())
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    path = None
    if to_file and folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "portrait-qa.log"
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    if to_console and sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    return path


def build_server(settings: Settings) -> uvicorn.Server:
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,  # our own logging; uvicorn's default config breaks without a console (service)
        access_log=False,  # the API middleware logs each request
        server_header=False,
    )
    return uvicorn.Server(config)


def serve(settings: Settings) -> None:
    log.info("Portrait QA %s listening on http://%s:%s", __version__, settings.server.host, settings.server.port)
    if settings.server.api_key == "" and settings.server.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Listening on the network without an API key: anyone who reaches the port can use the API.")
    build_server(settings).run()
