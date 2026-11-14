# Build the Windows package into dist\PortraitQA\ (run on Windows, with a Python that includes Tcl/Tk).
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -e ".[dev,build]"
& $py -c "import tkinter" ; if ($LASTEXITCODE -ne 0) { throw "This Python has no Tcl/Tk: the setup window would not open." }
& $py -m pytest ; if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
& $py -m PyInstaller --noconfirm --clean portrait_qa.spec ; if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Copy-Item README.md, LICENSE dist\PortraitQA\
Write-Host "Built dist\PortraitQA\ (PortraitQA.exe = setup window, portrait-qa.exe = command line)"
