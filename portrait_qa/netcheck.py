"""Port and endpoint checks used by the setup window."""

from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import APP_NAME

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass
class PortStatus:
    port: int
    free: bool
    ours: bool = False  # in use, but by a running Portrait QA (fine when reconfiguring)
    version: str | None = None
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.free or self.ours


def can_bind(host: str, port: int) -> tuple[bool, str | None]:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            # Without this Windows lets a second socket bind a port another process already listens on.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((host, port))
        return True, None
    except OSError as exc:
        return False, exc.strerror or str(exc)
    finally:
        sock.close()


def probe_health(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> dict | None:
    """GET /v1/health; returns the JSON if a Portrait QA answers there."""
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    url = f"http://{_url_host(host)}:{port}/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local, fixed scheme
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("name") == APP_NAME else None


def check_port(host: str, port: int) -> PortStatus:
    if not 1 <= port <= 65535:
        return PortStatus(port, free=False, error="port must be between 1 and 65535")
    free, error = can_bind(host, port)
    if free:
        return PortStatus(port, free=True)
    health = probe_health(port, host)
    if health:
        return PortStatus(port, free=False, ours=True, version=health.get("version"))
    return PortStatus(port, free=False, error=error)


def suggest_port(host: str, start: int, attempts: int = 200) -> int | None:
    """First free port from ``start`` upwards (skipping well-known ports below 1024)."""
    port = max(start, 1024)
    for candidate in range(port, min(port + attempts, 65536)):
        if can_bind(host, candidate)[0]:
            return candidate
    return None


def local_addresses() -> list[str]:
    """IPv4 addresses of this machine (for showing network endpoints)."""
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    # The address of the default route, which getaddrinfo sometimes misses.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET address: nothing is sent for UDP connect
            ip = s.getsockname()[0]
            if not ip.startswith("127.") and ip not in found:
                found.insert(0, ip)
    except OSError:
        pass
    return found


def endpoint_hosts(bind_host: str) -> list[str]:
    """Host names a client would use to reach a service bound to ``bind_host``."""
    if bind_host in ("0.0.0.0", "::", ""):
        hosts = [socket.gethostname(), *local_addresses()]
        return list(dict.fromkeys(hosts))
    if bind_host in LOCAL_HOSTS:
        return ["localhost"]
    return [bind_host]


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host
