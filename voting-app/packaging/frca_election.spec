# PyInstaller spec for FRCA-Election.exe (one-folder, console).
# Build with packaging/build.ps1, not by hand.
import os

from PyInstaller.utils.hooks import collect_data_files

APP_DIR = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(APP_DIR, "templates"), "templates"),
    (os.path.join(APP_DIR, "static"), "static"),
    (os.path.join(APP_DIR, "docs", "COUNCIL_PROPOSAL.md"), "docs"),
]
datas += collect_data_files("reportlab")

a = Analysis(
    [os.path.join(APP_DIR, "launcher.py")],
    pathex=[APP_DIR],
    datas=datas,
    hiddenimports=["app"],
    excludes=["pytest", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FRCA-Election",
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FRCA-Election")
