"""Setup controller (no Tk, no Windows): fake service manager and network; real port checks and a real server."""

import socket
import threading
import time

import pytest

from portrait_qa import config, netcheck, winsvc
from portrait_qa.server import build_server
from portrait_qa.setup_core import SetupController, SetupError, SetupState


class FakeService:
    def __init__(self, state=winsvc.NOT_INSTALLED):
        self.state = state
        self.calls = []

    def status(self):
        return self.state

    def install_or_update(self, path):
        self.calls.append(("install", str(path)))
        was = self.state
        if self.state == winsvc.NOT_INSTALLED:
            self.state = winsvc.STOPPED
        return "installed" if was == winsvc.NOT_INSTALLED else "updated"

    def start(self):
        self.calls.append(("start",))
        self.state = winsvc.RUNNING

    def stop(self):
        self.calls.append(("stop",))
        self.state = winsvc.STOPPED

    def remove(self):
        self.calls.append(("remove",))
        self.state = winsvc.NOT_INSTALLED

    def set_firewall(self, port):
        self.calls.append(("firewall", port))


class FakeNet:
    def __init__(self, port_status=None, healthy=True):
        self.port_status = port_status
        self.healthy = healthy

    def check_port(self, host, port):
        return self.port_status or netcheck.PortStatus(port, free=True)

    def suggest_port(self, host, start):
        return start

    def probe_health(self, port, host="127.0.0.1"):
        return {"name": "Portrait QA"} if self.healthy else None

    def endpoint_hosts(self, host):
        return netcheck.endpoint_hosts(host)


def controller(tmp_path, service=None, net=None, **kw):
    return SetupController(tmp_path / "config.json", service=service or FakeService(), net=net or FakeNet(), **kw)


def test_load_defaults(tmp_path):
    state = controller(tmp_path).load()
    assert state == SetupState(network=False, port=8080, api_key="", firewall=True)


def test_apply_installs_starts_and_saves(tmp_path):
    svc = FakeService()
    ctl = controller(tmp_path, svc)
    steps = []
    ctl.apply(SetupState(port=8181), lambda key, params: steps.append(key))
    assert steps == ["saving", "installing", "installed", "starting", "waiting_health", "done"]
    assert [c[0] for c in svc.calls] == ["install", "start", "firewall"]
    assert svc.calls[-1] == ("firewall", None)  # local mode removes any old rule
    saved = config.load(tmp_path / "config.json")
    assert saved.server.port == 8181 and saved.server.host == "127.0.0.1"


def test_apply_network_restarts_and_opens_firewall(tmp_path):
    svc = FakeService(winsvc.RUNNING)
    ctl = controller(tmp_path, svc)
    ctl.apply(SetupState(network=True, port=9000, api_key="x" * 20))
    assert [c[0] for c in svc.calls] == ["install", "stop", "start", "firewall"]
    assert svc.calls[-1] == ("firewall", 9000)
    saved = config.load(tmp_path / "config.json")
    assert saved.server.host == "0.0.0.0" and saved.server.api_key == "x" * 20


def test_apply_keeps_other_settings(tmp_path):
    (tmp_path / "config.json").write_text('{"quality": {"min_score": 77}, "server": {"cors_origins": ["https://a"]}}')
    controller(tmp_path).apply(SetupState(port=8282))
    saved = config.load(tmp_path / "config.json")
    assert saved.quality.min_score == 77 and saved.server.cors_origins == ["https://a"]


@pytest.mark.parametrize(
    ("state", "key"),
    [
        (SetupState(port=0), "port_range"),
        (SetupState(network=True, api_key=""), "key_required"),
        (SetupState(network=True, api_key="short"), "key_required"),
        (SetupState(api_key="short"), "key_short"),
    ],
)
def test_validation(tmp_path, state, key):
    svc = FakeService()
    with pytest.raises(SetupError) as err:
        controller(tmp_path, svc).apply(state)
    assert err.value.key == key
    assert svc.calls == []


def test_busy_port_is_refused_with_suggestion(tmp_path):
    svc = FakeService()
    net = FakeNet(netcheck.PortStatus(8080, free=False, error="in use"))
    with pytest.raises(SetupError) as err:
        controller(tmp_path, svc, net).apply(SetupState())
    assert err.value.key == "port_busy" and err.value.params["suggestion"] == 8081
    assert svc.calls == [] and not (tmp_path / "config.json").exists()


def test_port_used_by_our_service_is_accepted(tmp_path):
    net = FakeNet(netcheck.PortStatus(8080, free=False, ours=True, version="1.0.0"))
    controller(tmp_path, net=net).apply(SetupState())


def test_no_health_is_an_error(tmp_path):
    ctl = controller(tmp_path, net=FakeNet(healthy=False), health_timeout=0.2)
    with pytest.raises(SetupError) as err:
        ctl.apply(SetupState())
    assert err.value.key == "no_health"


def test_uninstall(tmp_path):
    svc = FakeService(winsvc.RUNNING)
    controller(tmp_path, svc).uninstall()
    assert svc.calls == [("remove",), ("firewall", None)]


def test_endpoints(tmp_path):
    ctl = controller(tmp_path)
    local = ctl.endpoints(SetupState(port=8123))
    assert ("POST", "http://localhost:8123/v1/assess") in local
    assert len(local) == 5
    network = ctl.base_urls(SetupState(network=True, port=8123))
    assert network[0] == f"http://{socket.gethostname()}:8123"


# -- real network checks -------------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_check_port_free_and_busy():
    port = free_port()
    assert netcheck.check_port("127.0.0.1", port).free
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        status = netcheck.check_port("127.0.0.1", port)
        assert not status.free and not status.ours and not status.usable
        suggestion = netcheck.suggest_port("127.0.0.1", port)
        assert suggestion and suggestion != port
    assert not netcheck.check_port("127.0.0.1", 0).usable


def test_check_port_recognizes_a_running_portrait_qa(settings):
    settings.server.port = free_port()
    server = build_server(settings)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        status = netcheck.check_port("127.0.0.1", settings.server.port)
        assert status.ours and status.usable and status.version
        assert netcheck.probe_health(settings.server.port)["status"] == "ok"
    finally:
        server.should_exit = True
        thread.join(10)


def test_service_command_has_absolute_config(tmp_path):
    cmd = winsvc.service_command(tmp_path / "config.json")
    assert str((tmp_path / "config.json").resolve()) in cmd
    assert cmd.endswith(" service")
