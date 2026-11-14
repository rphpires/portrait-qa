"""Logic behind the setup window, without Tk, so it can be tested.

``apply`` = validate -> check the port -> save config.json -> install/update the service -> (re)start it ->
wait for /v1/health -> firewall rule. Each step reports progress through a callback.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import config as config_mod
from . import netcheck, winsvc

LOCALHOST = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"
MIN_KEY_LENGTH = 16

ENDPOINTS = [
    ("POST", "/v1/assess"),
    ("POST", "/v1/crop"),
    ("POST", "/v1/process"),
    ("GET", "/v1/profiles"),
    ("GET", "/v1/health"),
]


@dataclass
class SetupState:
    network: bool = False  # False = only this computer (127.0.0.1)
    port: int = 8080
    api_key: str = ""
    firewall: bool = True  # add an inbound rule when network is on

    @property
    def host(self) -> str:
        return ALL_INTERFACES if self.network else LOCALHOST


class SetupError(Exception):
    """A problem the user can fix (shown as-is). ``key`` selects the translated message."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def generate_key() -> str:
    return secrets.token_urlsafe(24)


class SetupController:
    def __init__(self, config_path: Path | None = None, service=winsvc, net=netcheck, health_timeout: float = 20):
        self.config_path = Path(config_path) if config_path else config_mod.default_config_path()
        self.service = service
        self.net = net
        self.health_timeout = health_timeout

    # -- state ------------------------------------------------------------------------------------------------

    def load_settings(self) -> config_mod.Settings:
        return config_mod.load(self.config_path)

    def load(self) -> SetupState:
        s = self.load_settings().server
        return SetupState(network=s.host not in netcheck.LOCAL_HOSTS, port=s.port, api_key=s.api_key)

    def validate(self, state: SetupState) -> None:
        if not 1 <= state.port <= 65535:
            raise SetupError("port_range")
        if state.network and len(state.api_key) < MIN_KEY_LENGTH:
            raise SetupError("key_required", min=MIN_KEY_LENGTH)
        if state.api_key and (len(state.api_key) < MIN_KEY_LENGTH or not state.api_key.isascii()):
            raise SetupError("key_short", min=MIN_KEY_LENGTH)

    def service_status(self) -> str:
        return self.service.status()

    def check_port(self, state: SetupState) -> netcheck.PortStatus:
        return self.net.check_port(state.host, state.port)

    def suggest_port(self, state: SetupState) -> int | None:
        return self.net.suggest_port(state.host, state.port + 1)

    # -- actions ----------------------------------------------------------------------------------------------

    def save(self, state: SetupState) -> Path:
        settings = self.load_settings()
        settings.server.host = state.host
        settings.server.port = state.port
        settings.server.api_key = state.api_key
        return config_mod.save(settings, self.config_path)

    def apply(self, state: SetupState, progress: Callable[[str, dict], None] = lambda key, params: None) -> None:
        self.validate(state)
        port = self.check_port(state)
        if not port.usable:
            raise SetupError("port_busy", port=state.port, suggestion=self.suggest_port(state), detail=port.error or "")
        progress("saving", {"path": str(self.config_path)})
        self.save(state)
        progress("installing", {})
        action = self.service.install_or_update(self.config_path)
        progress(action, {})
        if self.service.status() in (winsvc.RUNNING, winsvc.STARTING):
            progress("stopping", {})
            self.service.stop()
        progress("starting", {})
        self.service.start()
        progress("waiting_health", {})
        if not self.wait_health(state.port):
            raise SetupError("no_health", port=state.port)
        if state.network and state.firewall:
            progress("firewall", {"port": state.port})
            self.service.set_firewall(state.port)
        else:
            self.service.set_firewall(None)
        progress("done", {})

    def wait_health(self, port: int) -> bool:
        deadline = time.monotonic() + self.health_timeout
        while time.monotonic() < deadline:
            if self.net.probe_health(port):
                return True
            time.sleep(0.5)
        return False

    def stop(self) -> None:
        self.service.stop()

    def uninstall(self) -> None:
        self.service.remove()
        self.service.set_firewall(None)

    # -- display ----------------------------------------------------------------------------------------------

    def base_urls(self, state: SetupState) -> list[str]:
        hosts = self.net.endpoint_hosts(state.host)
        return [f"http://{h}:{state.port}" for h in hosts]

    def endpoints(self, state: SetupState) -> list[tuple[str, str]]:
        base = self.base_urls(state)[0]
        return [(method, base + path) for method, path in ENDPOINTS]
