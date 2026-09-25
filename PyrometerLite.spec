from pathlib import Path

root = Path(SPECPATH).parent.parent
# Ship every managed DLL from the LHM folder: the CLR resolves dependencies
# lazily, so a missing one only surfaces as a runtime "assembly not found".
skip = {"Aga.Controls.dll", "OxyPlot.dll", "OxyPlot.WindowsForms.dll"}
binaries = [(str(path), ".") for path in sorted(root.glob("*.dll"))
            if path.name not in skip]

icon_file = Path(SPECPATH) / "icon.ico"

a = Analysis(
    ["main.py"],
    pathex=[str(Path(SPECPATH))],
    binaries=binaries,
    datas=[(str(icon_file), ".")] if icon_file.exists() else [],
    hiddenimports=["clr", "pythonnet"],
    excludes=["curses", "windows_curses", "numpy", "PIL", "matplotlib",
              "scipy", "unittest", "email", "http", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PyrometerLite",
    console=False,
    debug=False,
    strip=False,
    upx=False,
    uac_admin=True,
    icon=str(icon_file) if icon_file.exists() else None,
)
