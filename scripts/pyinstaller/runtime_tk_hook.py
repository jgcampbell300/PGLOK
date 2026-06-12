"""Runtime hook for PyInstaller: sets TCL_LIBRARY and TK_LIBRARY paths.

This hook ensures that the frozen executable can find the Tcl/Tk runtime
scripts that are bundled as data files.
"""
import os
import sys
from pathlib import Path


def _find_tcl_tk_dirs():
    """Locate the tcl and tk library script directories inside the frozen bundle."""
    # When frozen, data files are in sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        # Look for tcl and tk directories in common locations
        for candidate in (
            base / "tcl8.6",
            base / "tk8.6",
            base / "tcl" / "tcl8.6",
            base / "tk" / "tk8.6",
            base / "share" / "tcltk" / "tcl8.6",
            base / "share" / "tcltk" / "tk8.6",
        ):
            if candidate.is_dir():
                if "tcl" in candidate.name or "tcl" in candidate.parent.name:
                    os.environ.setdefault("TCL_LIBRARY", str(candidate))
                elif "tk" in candidate.name or "tk" in candidate.parent.name:
                    os.environ.setdefault("TK_LIBRARY", str(candidate))

        # Also check known relative paths used in PyInstaller builds
        tcl_paths = list(base.rglob("tclIndex"))
        for tp in tcl_paths:
            parent = tp.parent
            if "tcl8.6" in parent.name:
                os.environ.setdefault("TCL_LIBRARY", str(parent))
            elif "tk8.6" in parent.name:
                os.environ.setdefault("TK_LIBRARY", str(parent))


_find_tcl_tk_dirs()
