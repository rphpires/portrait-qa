"""Windows service: the service host (``PortraitQA.exe service``) and install/start/stop/remove helpers.

Uses pywin32 (Windows only). Every function here raises ``ServiceError`` with a readable message.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from . import APP_NAME, SERVICE_NAME
from . import config as config_mod

DESCRIPTION = "Face photo quality check and portrait crop (HTTP API)."
FIREWALL_RULE = "Portrait QA"

NOT_INSTALLED = "not_installed"
STOPPED = "stopped"
STARTING = "starting"
RUNNING = "running"
STOPPING = "stopping"
UNKNOWN = "unknown"

_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_ERROR_SERVICE_NOT_ACTIVE = 1062


class ServiceError(Exception):
    pass


def supported() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    if not supported():
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def service_command(config_path: Path) -> str:
    """Command line the service manager runs. The config path is absolute: services start in System32."""
    cfg = str(Path(config_path).resolve())
    if getattr(sys, "frozen", False):
        # Prefer the console build: the windowed one carries a "run as administrator" manifest.
        exe = Path(sys.executable).with_name("portrait-qa.exe")
        if not exe.exists():
            exe = Path(sys.executable)
        return f'"{exe}" --config "{cfg}" service'
    return f'"{sys.executable}" -m portrait_qa --config "{cfg}" service'


def _win():
    try:
        import pywintypes
        import win32service
        import win32serviceutil
    except ImportError as exc:  # pragma: no cover - only without pywin32
        raise ServiceError("pywin32 is not installed; the Windows service is not available.") from exc
    return win32service, win32serviceutil, pywintypes


def status() -> str:
    if not supported():
        return UNKNOWN
    win32service, win32serviceutil, pywintypes = _win()
    try:
        state = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
    except pywintypes.error as exc:
        if exc.winerror == _ERROR_SERVICE_DOES_NOT_EXIST:
            return NOT_INSTALLED
        raise ServiceError(f"Could not query the service: {exc.strerror}") from exc
    return {
        win32service.SERVICE_STOPPED: STOPPED,
        win32service.SERVICE_START_PENDING: STARTING,
        win32service.SERVICE_RUNNING: RUNNING,
        win32service.SERVICE_STOP_PENDING: STOPPING,
    }.get(state, UNKNOWN)


def install_or_update(config_path: Path) -> str:
    """Create the service, or point the existing one at this executable/config. Returns 'installed'/'updated'."""
    win32service, _, pywintypes = _win()
    command = service_command(config_path)
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    except pywintypes.error as exc:
        raise ServiceError(f"Could not open the service manager (run as administrator): {exc.strerror}") from exc
    try:
        try:
            handle = win32service.OpenService(scm, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)
            action = "updated"
            win32service.ChangeServiceConfig(
                handle, win32service.SERVICE_NO_CHANGE, win32service.SERVICE_AUTO_START,
                win32service.SERVICE_NO_CHANGE, command, None, 0, None, None, None, APP_NAME,
            )  # fmt: skip
        except pywintypes.error as exc:
            if exc.winerror != _ERROR_SERVICE_DOES_NOT_EXIST:
                raise
            handle = win32service.CreateService(
                scm, SERVICE_NAME, APP_NAME, win32service.SERVICE_ALL_ACCESS,
                win32service.SERVICE_WIN32_OWN_PROCESS, win32service.SERVICE_AUTO_START,
                win32service.SERVICE_ERROR_NORMAL, command, None, 0, None, None, None,
            )  # fmt: skip
            action = "installed"
        try:
            win32service.ChangeServiceConfig2(handle, win32service.SERVICE_CONFIG_DESCRIPTION, DESCRIPTION)
            # Restart after a crash: 5 s, 5 s, then 30 s; the failure count resets after a day.
            win32service.ChangeServiceConfig2(
                handle,
                win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                {
                    "ResetPeriod": 86400,
                    "RebootMsg": None,
                    "Command": None,
                    "Actions": [
                        (win32service.SC_ACTION_RESTART, 5000),
                        (win32service.SC_ACTION_RESTART, 5000),
                        (win32service.SC_ACTION_RESTART, 30000),
                    ],
                },
            )
        finally:
            win32service.CloseServiceHandle(handle)
        return action
    except pywintypes.error as exc:
        raise ServiceError(f"Could not install the service: {exc.strerror}") from exc
    finally:
        win32service.CloseServiceHandle(scm)


def _wait_for(target: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    current = status()
    while current != target and time.monotonic() < deadline:
        time.sleep(0.3)
        current = status()
    return current


def start(timeout: float = 30) -> None:
    _, win32serviceutil, pywintypes = _win()
    try:
        win32serviceutil.StartService(SERVICE_NAME)
    except pywintypes.error as exc:
        raise ServiceError(f"Could not start the service: {exc.strerror}") from exc
    final = _wait_for(RUNNING, timeout)
    if final != RUNNING:
        raise ServiceError(f"The service did not start (state: {final}); see the log folder.")


def stop(timeout: float = 30) -> None:
    _, win32serviceutil, pywintypes = _win()
    try:
        win32serviceutil.StopService(SERVICE_NAME)
    except pywintypes.error as exc:
        if exc.winerror in (_ERROR_SERVICE_NOT_ACTIVE, _ERROR_SERVICE_DOES_NOT_EXIST):
            return
        raise ServiceError(f"Could not stop the service: {exc.strerror}") from exc
    final = _wait_for(STOPPED, timeout)
    if final != STOPPED:
        raise ServiceError(f"The service did not stop (state: {final}).")


def remove() -> None:
    _, win32serviceutil, pywintypes = _win()
    stop()
    try:
        win32serviceutil.RemoveService(SERVICE_NAME)
    except pywintypes.error as exc:
        if exc.winerror == _ERROR_SERVICE_DOES_NOT_EXIST:
            return
        raise ServiceError(f"Could not remove the service: {exc.strerror}") from exc


def _netsh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["netsh", "advfirewall", "firewall", *args],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def set_firewall(port: int | None) -> None:
    """Replace the inbound rule. ``None`` only removes it."""
    _netsh("delete", "rule", f"name={FIREWALL_RULE}")
    if port is None:
        return
    proc = _netsh("add", "rule", f"name={FIREWALL_RULE}", "dir=in", "action=allow", "protocol=TCP", f"localport={port}")
    if proc.returncode != 0:
        raise ServiceError(f"Could not add the firewall rule: {(proc.stdout or proc.stderr).strip()}")


# --- service host --------------------------------------------------------------------------------------------


def run_dispatcher(config_path: Path | None) -> int:
    """Entry point when the service manager starts ``... service``."""
    import servicemanager
    import win32service
    import win32serviceutil

    cfg_path = Path(config_path) if config_path else config_mod.default_config_path()

    class PortraitQAService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = APP_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.server = None

        def SvcStop(self):  # noqa: N802 - pywin32 API
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.server is not None:
                self.server.should_exit = True

        def SvcDoRun(self):  # noqa: N802 - pywin32 API
            import logging

            from .server import build_server, setup_logging

            log = logging.getLogger("portrait_qa")
            try:
                settings = config_mod.load(cfg_path)
                setup_logging(settings.log_level, folder=cfg_path.resolve().parent / "logs", to_console=False)
                log.info("Service starting with %s", cfg_path)
                self.server = build_server(settings)
                try:
                    self.server.run()
                except SystemExit:  # uvicorn exits the process when it cannot bind
                    self.server.started = False
                if not self.server.started and not self.server.should_exit:
                    raise RuntimeError(
                        f"could not listen on {settings.server.host}:{settings.server.port} (port in use?)"
                    )
                log.info("Service stopped")
            except Exception as exc:
                setup_logging("info", folder=cfg_path.resolve().parent / "logs", to_console=False)
                log.exception("Service failed")
                servicemanager.LogErrorMsg(f"{APP_NAME} failed: {exc}")
                # Leaving SvcDoRun ends the service; raising makes the SCM report a failure and restart it.
                raise

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(PortraitQAService)
    servicemanager.StartServiceCtrlDispatcher()
    return 0
