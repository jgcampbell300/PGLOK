# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sysconfig

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import PyInstaller.config as conf


# Get the project root directory
project_root = Path(os.getcwd())

datas = []
for rel_path in ("src/config", "src/assets", "src/data", "addons"):
    src_path = project_root / rel_path
    if src_path.exists():
        datas.append((str(src_path), rel_path))

# Include Tkinter data files (collected from python package)
datas += collect_data_files("tkinter")

hiddenimports = collect_submodules("src")
# Ensure tkinter and its C extension are explicitly included
hiddenimports += ["tkinter", "_tkinter", "tkinter.constants", "tkinter.font",
                   "tkinter.filedialog", "tkinter.messagebox", "tkinter.simpledialog",
                   "tkinter.commondialog", "tkinter.colorchooser", "tkinter.scrolledtext",
                   "tkinter.dialog", "tkinter.dnd", "tkinter.tix", "tkinter.ttk"]

# Bundle Tcl/Tk runtime scripts (required by _tkinter at runtime)
tcl_dir = Path("/usr/share/tcltk/tcl8.6")
tk_dir = Path("/usr/share/tcltk/tk8.6")
if tcl_dir.exists():
    datas.append((str(tcl_dir), "tcl8.6"))
if tk_dir.exists():
    datas.append((str(tk_dir), "tk8.6"))

# Find and bundle Tcl/Tk shared libraries
binaries = []
for lib_name in ("libtcl8.6.so", "libtcl8.6.so.0", "libtk8.6.so", "libtk8.6.so.0"):
    # Search common library paths
    for lib_dir in ("/usr/lib/x86_64-linux-gnu", "/usr/lib/i386-linux-gnu",
                    "/usr/lib64", "/usr/lib", "/lib/x86_64-linux-gnu",
                    "/lib64", "/lib"):
        lib_path = Path(lib_dir) / lib_name
        if lib_path.exists():
            binaries.append((str(lib_path), "."))
            break

# Register runtime hook to set TCL_LIBRARY/TK_LIBRARY paths
runtime_hooks = [str(project_root / "scripts" / "pyinstaller" / "runtime_tk_hook.py")]

a = Analysis(
    [str(project_root / "src" / "pglok.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=["test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PGLOK",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "icon.ico"),
)
