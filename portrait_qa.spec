# PyInstaller spec: one folder (dist/PortraitQA) with two executables sharing the same runtime.
#   PortraitQA.exe   windowed, asks for administrator rights: the setup window (no arguments)
#   portrait-qa.exe  console: CLI (serve, assess, batch, install...) and the Windows service host
# Build on Windows: .\build.ps1
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("portrait_qa/models", "portrait_qa/models"),
    ("portrait_qa/web", "portrait_qa/web"),
    ("portrait_qa/assets", "portrait_qa/assets"),
]
hidden = collect_submodules("uvicorn") + [
    "win32timezone",
    "servicemanager",
    "win32service",
    "win32serviceutil",
    "win32event",
]

a = Analysis(
    ["packaging/entry.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hidden,
    excludes=["PIL", "matplotlib", "pytest", "IPython", "pandas", "scipy"],
)
# OpenCV's FFmpeg plugin (~30 MB) is only used for video I/O, which this service never does.
a.binaries = [b for b in a.binaries if "opencv_videoio_ffmpeg" not in b[0]]
pyz = PYZ(a.pure)

gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PortraitQA",
    console=False,
    icon="portrait_qa/assets/icon.ico",
    uac_admin=True,
    version=None,
)
cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="portrait-qa",
    console=True,
    icon="portrait_qa/assets/icon.ico",
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="PortraitQA")
