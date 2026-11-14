# Building and testing

## Tests and lint

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

No network, camera or Windows needed. The suite covers:

- decoding (formats, corrupt files, size and pixel limits, EXIF rotation) and JPEG size fitting,
- detection on the test portrait, on an upscaled copy (downscale path), with two faces and with none,
- each quality issue on a derived image (blur, dark, bright, two faces, thumbnail, half shadow) and the
  contrast normalization of sharpness,
- crop geometry for every built-in profile, tighter crop vs padding, upscale flag, profile validation,
- the API end to end with FastAPI's test client: three body formats, `format=jpeg`, every error code, API key,
  `503 BUSY`, CORS, parallel requests,
- `config.json` parsing and validation, the CLI (`assess`, `crop`, `batch`),
- the setup controller with a fake service manager, real port checks, and a real uvicorn server recognized by
  the port check,
- pt-BR/en text completeness.

`scripts/ui_smoke.py` opens the real Tk window with a fake service manager: busy port and suggestion, network
mode with a generated key, endpoints, apply. It needs a display and a Python with Tcl/Tk.

## Windows package

Build **on Windows** with a Python that includes Tcl/Tk (the python.org installer does; `build.ps1` checks):

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

It installs the dev and build extras, runs the tests, and runs PyInstaller with `portrait_qa.spec`. Output:
`dist\PortraitQA\` with `PortraitQA.exe` (setup window), `portrait-qa.exe` (CLI and service host),
`_internal\`, README and LICENSE. About 165 MB (72 MB zipped), most of it OpenCV; the spec drops OpenCV's FFmpeg plugin
(video only, ~30 MB). Zip the folder to distribute it.

Checked on Windows Server (win-server-2) before each release:

```powershell
.\portrait-qa.exe assess photo.jpg
.\portrait-qa.exe install --network --port 18080      # admin prompt
.\portrait-qa.exe status
Stop-Process -Name portrait-qa -Force; Start-Sleep 9; .\portrait-qa.exe status   # restarted by the SCM
.\portrait-qa.exe uninstall
```

## Icon

`scripts/make_icon.py` (Pillow) draws `portrait_qa/assets/icon.png` and `icon.ico`.
