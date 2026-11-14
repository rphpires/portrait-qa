"""Command line: ``portrait-qa serve | assess | crop | batch | gui | install | uninstall | status``.

The frozen Windows executable with no arguments opens the setup window (``gui``).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import __version__, config
from .errors import PortraitQAError

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _settings(args):
    settings = config.load(args.config)
    if getattr(args, "host", None):
        settings.server.host = args.host
    if getattr(args, "port", None):
        settings.server.port = args.port
    settings.validate()
    return settings


def cmd_serve(args) -> int:
    from .server import serve, setup_logging

    settings = _settings(args)
    folder = (args.config or config.default_config_path()).resolve().parent / "logs"
    setup_logging(settings.log_level, folder=folder, to_file=not args.no_log_file)
    serve(settings)
    return 0


def _engine(args):
    from .engine import Engine

    return Engine(_settings(args))


def cmd_assess(args) -> int:
    engine = _engine(args)
    status = 0
    for path in args.files:
        try:
            result = engine.run(Path(path).read_bytes(), mode="assess")
            data = {"file": str(path), **result.report.to_dict()}
            if not result.report.passed:
                status = max(status, 1)
        except (PortraitQAError, OSError) as exc:
            data = {"file": str(path), "error": getattr(exc, "code", "IO_ERROR"), "message": str(exc)}
            status = 2
        print(json.dumps(data))
    return status


def cmd_crop(args) -> int:
    engine = _engine(args)
    try:
        result = engine.run(Path(args.file).read_bytes(), mode="crop", profile=args.profile)
    except (PortraitQAError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.crop.jpeg)
    print(json.dumps({"file": str(args.file), "out": str(out), **result.report.to_dict(), "crop": result.crop.info()}))
    return 0 if result.report.passed else 1


def _crop_targets(src: Path, files: list[Path]) -> dict[Path, Path]:
    """Output name of each crop, relative to the output folder: ``photo.png`` -> ``photo.jpg``. When two
    sources would collide (``a.png`` and ``a.jpg``), both keep their extension: ``a.png.jpg``, ``a.jpg.jpg``."""
    plain = {p: p.relative_to(src).with_suffix(".jpg") for p in files}
    counts: dict[str, int] = {}
    for target in plain.values():
        key = target.as_posix().lower()  # Windows file names are case-insensitive
        counts[key] = counts.get(key, 0) + 1
    return {
        p: (t if counts[t.as_posix().lower()] == 1 else p.relative_to(src).with_name(p.name + ".jpg"))
        for p, t in plain.items()
    }


def cmd_batch(args) -> int:
    """Assess (and optionally crop) every image in a folder; write a CSV report."""
    engine = _engine(args)
    src = Path(args.folder)
    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file())
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report) if args.report else (out_dir or src) / "portrait-qa-report.csv"
    targets = _crop_targets(src, files)
    mode = "process" if out_dir else "assess"
    counts = {"passed": 0, "failed": 0, "error": 0}
    with report_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "passed", "score", "faces", "issues", "cropped", "error"])
        for i, path in enumerate(files, 1):
            rel = path.relative_to(src).as_posix()  # same report on Windows and Linux
            try:
                result = engine.run(path.read_bytes(), mode=mode, profile=args.profile)
                r = result.report
                cropped = ""
                if result.crop is not None and out_dir:
                    target = out_dir / targets[path]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(result.crop.jpeg)
                    cropped = target.relative_to(out_dir).as_posix()
                writer.writerow([rel, r.passed, r.score, r.faces, " ".join(x.code for x in r.issues), cropped, ""])
                counts["passed" if r.passed else "failed"] += 1
            except (PortraitQAError, OSError) as exc:
                writer.writerow([rel, "", "", "", "", "", f"{getattr(exc, 'code', 'IO_ERROR')}: {exc}"])
                counts["error"] += 1
            if not args.quiet:
                print(f"\r{i}/{len(files)}", end="", file=sys.stderr, flush=True)
    if not args.quiet:
        print(file=sys.stderr)
    print(json.dumps({"files": len(files), **counts, "report": str(report_path)}))
    return 0


def _controller(args):
    from .setup_core import SetupController

    return SetupController(args.config)


def cmd_install(args) -> int:
    """Silent install: same steps as the setup window (check port, save config, install, start, health)."""
    from . import winsvc
    from .setup_core import SetupError, SetupState, generate_key

    if not winsvc.supported():
        print("error: the Windows service is only available on Windows; use 'portrait-qa serve'", file=sys.stderr)
        return 2
    ctl = _controller(args)
    current = ctl.load()
    network = args.network if args.network is not None else current.network
    api_key = args.api_key if args.api_key is not None else current.api_key
    if network and not api_key:
        api_key = generate_key()
    state = SetupState(network=network, port=args.port or current.port, api_key=api_key, firewall=not args.no_firewall)
    try:
        ctl.apply(state, lambda key, params: print(" ".join([key, *map(str, params.values())]), file=sys.stderr))
    except SetupError as exc:
        details = ", ".join(f"{k}={v}" for k, v in exc.params.items() if v not in (None, ""))
        print(f"error: {exc.key}" + (f" ({details})" if details else ""), file=sys.stderr)
        return 2
    except winsvc.ServiceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": ctl.service_status(), "base_urls": ctl.base_urls(state), "api_key": state.api_key}))
    return 0


def cmd_uninstall(args) -> int:
    from . import winsvc

    try:
        _controller(args).uninstall()
    except winsvc.ServiceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": winsvc.status()}))
    return 0


def cmd_status(args) -> int:
    from . import netcheck, winsvc

    ctl = _controller(args)
    state = ctl.load()
    health = netcheck.probe_health(state.port)
    print(json.dumps({"service": winsvc.status(), "port": state.port, "host": state.host, "health": health}))
    return 0 if health else 1


def cmd_service(args) -> int:
    from .winsvc import run_dispatcher

    return run_dispatcher(args.config)


def cmd_gui(args) -> int:
    from .setup_gui import main as gui_main

    return gui_main(config_path=args.config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portrait-qa", description="Face photo quality check and portrait crop.")
    parser.add_argument("--version", action="version", version=f"portrait-qa {__version__}")
    parser.add_argument("--config", type=Path, help="config.json path (default: next to the executable)")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="run the HTTP API in the foreground")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--no-log-file", action="store_true", help="log to the console only")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("assess", help="check photos; one JSON line per file (exit 1 if any fails)")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_assess)

    p = sub.add_parser("crop", help="crop one photo to a profile")
    p.add_argument("file")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("-p", "--profile")
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("batch", help="check a folder (recursive); with --out, also crop the photos that pass")
    p.add_argument("folder")
    p.add_argument("-o", "--out", help="folder for the cropped photos")
    p.add_argument("-p", "--profile")
    p.add_argument("--report", help="CSV path (default: portrait-qa-report.csv in --out or the folder)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("gui", help="setup window: port, API key, Windows service")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("install", help="install/update and start the Windows service without the window (admin)")
    p.add_argument("--port", type=int)
    access = p.add_mutually_exclusive_group()
    access.add_argument("--network", dest="network", action="store_true", default=None, help="listen on all interfaces")
    access.add_argument("--local", dest="network", action="store_false", help="listen on 127.0.0.1 only")
    p.add_argument("--api-key", help="default: keep the current one; generated in network mode when empty")
    p.add_argument("--no-firewall", action="store_true", help="do not add the Windows Firewall rule")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="stop and remove the Windows service (config and logs are kept)")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("status", help="service state and /v1/health on the configured port")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("service", help=argparse.SUPPRESS)  # entry point of the Windows service
    p.set_defaults(func=cmd_service)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        if getattr(sys, "frozen", False):
            args = parser.parse_args([*argv, "gui"])
        else:
            parser.print_help()
            return 0
    try:
        return args.func(args)
    except PortraitQAError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2
