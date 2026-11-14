"""Drive the real setup window (Tk) with a fake service manager: check a port, switch to network mode, apply.

    python scripts/ui_smoke.py [--lang pt|en] [--screenshot docs/images/setup.png] [--keep-open]

Exits non-zero on failure. Needs a display; --screenshot needs Pillow and a visible desktop session.
"""

from __future__ import annotations

import argparse
import socket
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portrait_qa import netcheck, winsvc  # noqa: E402
from portrait_qa.setup_core import SetupController  # noqa: E402
from portrait_qa.setup_gui import SetupWindow, set_icon  # noqa: E402


class FakeService:
    def __init__(self):
        self.state = winsvc.NOT_INSTALLED

    def status(self):
        return self.state

    def install_or_update(self, _path):
        self.state = winsvc.STOPPED
        return "installed"

    def start(self):
        self.state = winsvc.RUNNING

    def stop(self):
        self.state = winsvc.STOPPED

    def remove(self):
        self.state = winsvc.NOT_INSTALLED

    def set_firewall(self, _port):
        pass


class Net:
    """Real port checks; health always answers (no real service behind the fake)."""

    def __getattr__(self, name):
        return getattr(netcheck, name)

    def probe_health(self, port, host="127.0.0.1"):
        return {"name": "Portrait QA", "version": "smoke"}


def pump(root: tk.Tk, until, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=("pt", "en"), default="en")
    parser.add_argument("--screenshot")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp())
    service = FakeService()
    ctl = SetupController(tmp / "config.json", service=service, net=Net(), health_timeout=2)
    root = tk.Tk()
    set_icon(root)
    win = SetupWindow(root, ctl, args.lang)
    win.service_ok = True  # the fake service works on any OS
    win._refresh_status()
    pump(root, lambda: False, 0.3)

    # 1) a busy port is reported, with a suggestion
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        win.port.set(str(port))
        win._check_port()
        assert pump(root, lambda: str(port) in win.port_text.get() and win.suggestion), win.port_text.get()
        print("busy port:", win.port_text.get())
    win._use_suggestion()
    assert pump(root, lambda: not win.busy and win.port_text.get() and win.suggestion and
                str(win.suggestion) == win.port.get()), win.port_text.get()  # fmt: skip
    print("suggested port:", win.port.get(), "->", win.port_text.get())

    # 2) network mode generates a key and lists the endpoints
    win.network.set(True)
    win._on_access()
    assert len(win.api_key.get()) >= 16
    urls = [
        w.get() for w in win.endpoint_box.winfo_children() if isinstance(w, tk.Entry) or w.winfo_class() == "TEntry"
    ]
    assert any(u.endswith("/v1/process") for u in urls), urls
    print("endpoints:", urls)

    # 3) apply: config saved, fake service installed and running
    win._apply()
    assert pump(root, lambda: not win.busy and service.state == winsvc.RUNNING, 15), win.message.get()
    assert (tmp / "config.json").exists()
    print("applied:", win.message.get(), "| status:", win.status_text.get())

    if args.screenshot:
        from PIL import ImageGrab

        root.lift()
        root.attributes("-topmost", True)
        pump(root, lambda: False, 0.8)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        Path(args.screenshot).parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab((x, y, x + w, y + h)).save(args.screenshot)
        print("screenshot:", args.screenshot)
    if args.keep_open:
        root.mainloop()
    root.destroy()
    print("UI smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
