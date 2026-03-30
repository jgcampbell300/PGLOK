"""Crash reporter: catches unhandled exceptions, writes a log, and offers
to open a pre-filled GitHub issue in the browser."""

import platform
import sys
import traceback
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

from src import __version__

REPO_ISSUES_URL = "https://github.com/jgcampbell300/PGLOK/issues/new"
CRASH_LOG_PATH = Path.home() / ".config" / "PGLOK" / "crash.log"


def _format_report(exc_type, exc_value, exc_tb) -> str:
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_str = "".join(tb_lines)
    return (
        f"PGLOK Crash Report\n"
        f"==================\n"
        f"Time:       {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Version:    {__version__}\n"
        f"OS:         {platform.system()} {platform.release()} ({platform.version()})\n"
        f"Python:     {sys.version}\n"
        f"Architecture: {platform.machine()}\n"
        f"\n"
        f"Traceback:\n"
        f"{tb_str}"
    )


def _write_crash_log(report: str) -> Path:
    try:
        CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(report)
            f.write("\n" + "=" * 60 + "\n\n")
    except Exception:
        pass
    return CRASH_LOG_PATH


def _open_github_issue(report: str):
    title = f"Crash: PGLOK v{__version__} on {platform.system()}"
    body = (
        "<!-- PGLOK auto-generated crash report. Please add any steps to reproduce above the report. -->\n\n"
        "**Steps to reproduce (if known):**\n"
        "1. \n\n"
        "---\n\n"
        "```\n"
        f"{report}"
        "```"
    )
    params = urllib.parse.urlencode({"title": title, "body": body})
    url = f"{REPO_ISSUES_URL}?{params}"
    webbrowser.open(url)


def _show_crash_dialog(report: str, log_path: Path):
    """Show a Tkinter crash dialog (best-effort; Tk may itself be broken)."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        msg = (
            f"PGLOK crashed unexpectedly.\n\n"
            f"Crash log saved to:\n{log_path}\n\n"
            f"Would you like to open a GitHub issue so this can be fixed?\n"
            f"(Your browser will open with the details pre-filled.)"
        )
        if messagebox.askyesno("PGLOK Crashed", msg, icon="error"):
            _open_github_issue(report)
        root.destroy()
    except Exception:
        # Tk is broken — just open the browser directly
        _open_github_issue(report)


def handle_exception(exc_type, exc_value, exc_tb):
    """Global exception handler — replaces sys.excepthook."""
    # Let KeyboardInterrupt through normally
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    report = _format_report(exc_type, exc_value, exc_tb)
    log_path = _write_crash_log(report)

    # Print to stderr so developers see it in the terminal too
    print(report, file=sys.stderr)

    _show_crash_dialog(report, log_path)


def install():
    """Install the global crash handler."""
    sys.excepthook = handle_exception
