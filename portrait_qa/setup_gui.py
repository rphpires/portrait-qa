"""Setup window: choose access (this computer / network), port, API key; install and start the Windows service;
show the endpoints to use. Long operations run on a worker thread; the Tk thread polls a queue for results."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from . import APP_NAME, __version__, winsvc
from .errors import PortraitQAError
from .i18n import TEXTS, detect_language
from .setup_core import ENDPOINTS, SetupController, SetupError, SetupState, generate_key


class SetupWindow:
    def __init__(self, root: tk.Tk, controller: SetupController, lang: str):
        self.root = root
        self.ctl = controller
        self.t = TEXTS[lang]
        self.results: queue.Queue = queue.Queue()
        self.busy = False
        self.service_ok = winsvc.supported()
        self._status = winsvc.UNKNOWN

        state = controller.load()
        self.network = tk.BooleanVar(value=state.network)
        self.port = tk.StringVar(value=str(state.port))
        self.api_key = tk.StringVar(value=state.api_key)
        self.firewall = tk.BooleanVar(value=True)
        self.show_key = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar()
        self.port_text = tk.StringVar()
        self.message = tk.StringVar()

        root.title(self.t["title"])
        root.minsize(620, 0)
        self._build()
        self._refresh_status()
        self._refresh_endpoints()
        root.after(100, self._poll)
        if self.service_ok and not winsvc.is_admin():
            self._say(self.t["not_admin"], error=True)
        elif not self.service_ok:
            self._say(self.t["not_windows"], error=True)

    # -- layout -----------------------------------------------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self.root, padding=12)
        frm.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text=f"{APP_NAME} {__version__}", font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(frm, text=self.t["service"]).grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(frm, textvariable=self.status_text).grid(row=1, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(frm, text=self.t["access"]).grid(row=2, column=0, sticky="nw", **pad)
        access = ttk.Frame(frm)
        access.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Radiobutton(access, text=self.t["local"], variable=self.network, value=False,
                        command=self._on_access).grid(sticky="w")  # fmt: skip
        ttk.Radiobutton(access, text=self.t["network"], variable=self.network, value=True,
                        command=self._on_access).grid(sticky="w")  # fmt: skip

        ttk.Label(frm, text=self.t["port"]).grid(row=3, column=0, sticky="w", **pad)
        port_row = ttk.Frame(frm)
        port_row.grid(row=3, column=1, columnspan=2, sticky="we", **pad)
        entry = ttk.Entry(port_row, textvariable=self.port, width=8)
        entry.grid(row=0, column=0)
        entry.bind("<FocusOut>", lambda _e: self._refresh_endpoints())
        self.check_btn = ttk.Button(port_row, text=self.t["check"], command=self._check_port)
        self.check_btn.grid(row=0, column=1, padx=6)
        ttk.Label(port_row, textvariable=self.port_text, wraplength=380).grid(row=0, column=2, sticky="w")
        self.suggest_btn = ttk.Button(port_row, command=self._use_suggestion)
        self.suggestion: int | None = None

        ttk.Label(frm, text=self.t["api_key"]).grid(row=4, column=0, sticky="w", **pad)
        key_row = ttk.Frame(frm)
        key_row.grid(row=4, column=1, columnspan=2, sticky="we", **pad)
        key_row.columnconfigure(0, weight=1)
        self.key_entry = ttk.Entry(key_row, textvariable=self.api_key, show="•")
        self.key_entry.grid(row=0, column=0, sticky="we")
        ttk.Button(key_row, text=self.t["generate"], command=self._generate_key).grid(row=0, column=1, padx=6)
        ttk.Checkbutton(key_row, text=self.t["show"], variable=self.show_key, command=self._toggle_key).grid(
            row=0, column=2
        )
        ttk.Label(key_row, text=self.t["key_hint"], foreground="gray").grid(row=1, column=0, columnspan=3, sticky="w")

        self.fw_check = ttk.Checkbutton(frm, text=self.t["firewall"], variable=self.firewall)
        self.fw_check.grid(row=5, column=1, columnspan=2, sticky="w", **pad)

        buttons = ttk.Frame(frm)
        buttons.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 4))
        self.apply_btn = ttk.Button(buttons, command=self._apply)
        self.apply_btn.grid(row=0, column=0, padx=(0, 6))
        self.stop_btn = ttk.Button(buttons, text=self.t["stop"], command=self._stop)
        self.stop_btn.grid(row=0, column=1, padx=6)
        self.remove_btn = ttk.Button(buttons, text=self.t["uninstall"], command=self._uninstall)
        self.remove_btn.grid(row=0, column=2, padx=6)

        self.message_label = ttk.Label(frm, textvariable=self.message, wraplength=580)
        self.message_label.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 8))

        box = ttk.LabelFrame(frm, text=self.t["endpoints"], padding=8)
        box.grid(row=8, column=0, columnspan=3, sticky="we")
        box.columnconfigure(1, weight=1)
        self.endpoint_box = box

        links = ttk.Frame(frm)
        links.grid(row=9, column=0, columnspan=3, sticky="w", pady=(10, 0))
        for col, (key, cmd) in enumerate(
            [("open_test", lambda: self._open_url("/")), ("open_docs", lambda: self._open_url("/docs")),
             ("open_logs", self._open_logs), ("open_config", self._open_config)]
        ):  # fmt: skip
            ttk.Button(links, text=self.t[key], command=cmd).grid(row=0, column=col, padx=(0, 6))
        self._on_access()

    # -- helpers ----------------------------------------------------------------------------------------------

    def _say(self, text: str, error: bool = False) -> None:
        self.message.set(text)
        self.message_label.configure(foreground="#c53030" if error else "")

    def _state(self) -> SetupState | None:
        try:
            port = int(self.port.get().strip())
        except ValueError:
            self._say(self.t["port_number"], error=True)
            return None
        return SetupState(network=self.network.get(), port=port, api_key=self.api_key.get().strip(),
                          firewall=self.firewall.get())  # fmt: skip

    def _format_error(self, exc: Exception) -> str:
        if isinstance(exc, SetupError):
            params = dict(exc.params)
            if exc.key == "port_busy":
                detail = f" ({params['detail']})" if params.get("detail") else ""
                text = self.t["port_busy"].format(port=params["port"], detail=detail)
                if params.get("suggestion"):
                    text += self.t["port_suggest"].format(suggestion=params["suggestion"])
                return text
            return self.t[exc.key].format(**params)
        if isinstance(exc, PortraitQAError):
            return exc.message
        return str(exc)

    def _run(self, work, on_done) -> None:
        """Run ``work(progress)`` on a worker thread; ``on_done(result, error)`` runs on the Tk thread."""
        if self.busy:
            return
        self.busy = True
        self._set_buttons()

        def progress(key: str, params: dict) -> None:
            self.results.put(("progress", key, params))

        def target():
            try:
                self.results.put(("done", on_done, work(progress), None))
            except Exception as exc:  # reported in the window
                self.results.put(("done", on_done, None, exc))

        threading.Thread(target=target, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                item = self.results.get_nowait()
                if item[0] == "progress":
                    key, params = item[1], item[2]
                    text_key = "firewall_step" if key == "firewall" else key
                    self._say(self.t.get(text_key, key).format(**params))
                else:
                    _, on_done, result, error = item
                    self.busy = False
                    try:
                        on_done(result, error)
                    finally:
                        self._refresh_status()
        except queue.Empty:
            pass
        except Exception as exc:  # never stop polling
            self._say(str(exc), error=True)
        self.root.after(150, self._poll)

    def _set_buttons(self) -> None:
        status = self._status
        installed = status not in (winsvc.NOT_INSTALLED, winsvc.UNKNOWN)
        can = self.service_ok and not self.busy
        self.apply_btn.configure(text=self.t["apply_update" if installed else "apply_install"])
        self.apply_btn.state(["!disabled"] if can else ["disabled"])
        self.stop_btn.state(["!disabled"] if can and status == winsvc.RUNNING else ["disabled"])
        self.remove_btn.state(["!disabled"] if can and installed else ["disabled"])
        self.check_btn.state(["disabled"] if self.busy else ["!disabled"])

    def _refresh_status(self) -> None:
        try:
            self._status = self.ctl.service_status()
        except Exception as exc:
            self._status = winsvc.UNKNOWN
            self._say(str(exc), error=True)
        self.status_text.set(self.t["status"].get(self._status, self._status))
        self._set_buttons()

    def _refresh_endpoints(self) -> None:
        for child in self.endpoint_box.winfo_children():
            child.destroy()
        state = self._state()
        if state is None:
            return
        for row, (method, url) in enumerate(self.ctl.endpoints(state)):
            ttk.Label(self.endpoint_box, text=method, width=5).grid(row=row, column=0, sticky="w")
            field = ttk.Entry(self.endpoint_box)
            field.insert(0, url)
            field.configure(state="readonly")
            field.grid(row=row, column=1, sticky="we", pady=1)
            ttk.Button(self.endpoint_box, text=self.t["copy"], command=lambda u=url: self._copy(u)).grid(
                row=row, column=2, padx=(6, 0)
            )
        others = self.ctl.base_urls(state)[1:]
        if others:
            ttk.Label(self.endpoint_box, text=" · ".join(others), foreground="gray").grid(
                row=len(ENDPOINTS), column=1, sticky="w"
            )

    # -- events -----------------------------------------------------------------------------------------------

    def _on_access(self) -> None:
        if self.network.get() and not self.api_key.get().strip():
            self.api_key.set(generate_key())
        self.fw_check.state(["!disabled"] if self.network.get() else ["disabled"])
        self.port_text.set("")
        self._refresh_endpoints()

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    def _generate_key(self) -> None:
        self.api_key.set(generate_key())
        self.show_key.set(True)
        self._toggle_key()

    def _copy(self, url: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._say(self.t["copied"].format(url=url))

    def _check_port(self) -> None:
        state = self._state()
        if state is None:
            return
        self._refresh_endpoints()

        def work(_progress):
            status = self.ctl.check_port(state)
            suggestion = None if status.usable else self.ctl.suggest_port(state)
            return status, suggestion

        def done(result, error):
            self.suggest_btn.grid_forget()
            if error:
                self._say(self._format_error(error), error=True)
                return
            status, suggestion = result
            if status.free:
                self.port_text.set(self.t["port_free"].format(port=status.port))
            elif status.ours:
                self.port_text.set(self.t["port_ours"].format(port=status.port, version=status.version))
            else:
                detail = f" ({status.error})" if status.error else ""
                text = self.t["port_busy"].format(port=status.port, detail=detail)
                if suggestion:
                    text += self.t["port_suggest"].format(suggestion=suggestion)
                    self.suggestion = suggestion
                    self.suggest_btn.configure(text=self.t["use_suggestion"].format(suggestion=suggestion))
                    self.suggest_btn.grid(row=0, column=3, padx=6)
                self.port_text.set(text)

        self._run(work, done)

    def _use_suggestion(self) -> None:
        if self.suggestion:
            self.port.set(str(self.suggestion))
            self.suggest_btn.grid_forget()
            self._check_port()

    def _apply(self) -> None:
        state = self._state()
        if state is None:
            return
        self._refresh_endpoints()

        def done(_result, error):
            if error:
                self._say(self._format_error(error), error=True)
                messagebox.showerror(self.t["error"], self._format_error(error), parent=self.root)
            else:
                self.port_text.set("")

        self._run(lambda progress: self.ctl.apply(state, progress), done)

    def _stop(self) -> None:
        def done(_result, error):
            self._say(self._format_error(error) if error else self.t["stopped_msg"], error=bool(error))

        self._run(lambda _p: self.ctl.stop(), done)

    def _uninstall(self) -> None:
        if not messagebox.askyesno(APP_NAME, self.t["uninstall_confirm"], parent=self.root):
            return

        def done(_result, error):
            self._say(self._format_error(error) if error else self.t["uninstalled"], error=bool(error))

        self._run(lambda _p: self.ctl.uninstall(), done)

    def _open_url(self, path: str) -> None:
        state = self._state()
        if state:
            webbrowser.open(f"http://localhost:{state.port}{path}")

    def _open_folder(self, path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opens Explorer / the default editor
        else:
            webbrowser.open(path.as_uri())

    def _open_logs(self) -> None:
        folder = self.ctl.config_path.resolve().parent / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        self._open_folder(folder)

    def _open_config(self) -> None:
        path = self.ctl.config_path.resolve()
        if not path.exists():
            state = self._state()
            if state is None:
                return
            self.ctl.save(state)
        self._open_folder(path)


ASSETS = Path(__file__).resolve().parent / "assets"


def set_icon(root: tk.Tk) -> None:
    try:
        if sys.platform == "win32":
            root.iconbitmap(default=str(ASSETS / "icon.ico"))
        else:
            root.iconphoto(True, tk.PhotoImage(file=str(ASSETS / "icon.png")))
    except tk.TclError:
        pass


def main(config_path: Path | None = None) -> int:
    root = tk.Tk()
    set_icon(root)
    try:
        controller = SetupController(config_path)
        SetupWindow(root, controller, detect_language())
    except Exception as exc:
        root.withdraw()
        messagebox.showerror(APP_NAME, str(exc))
        return 2
    root.mainloop()
    return 0
