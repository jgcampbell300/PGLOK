#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path


MIN_PYTHON = (3, 10)
REQUIRED_MODULES = (
    ("tkinter", "tk"),
    ("requests", "requests"),
    ("bs4", "beautifulsoup4"),
    ("PIL.Image", "Pillow"),
)
NETWORK_CHECKS = (
    "https://api.github.com/",
    "https://wiki.projectgorgon.com/w/images/",
)


def _ok(text: str):
    print(f"[OK]   {text}")


def _warn(text: str):
    print(f"[WARN] {text}")


def _fail(text: str):
    print(f"[FAIL] {text}")


def _check_python_version() -> bool:
    current = sys.version_info[:3]
    if current < MIN_PYTHON:
        _fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, "
            f"found {current[0]}.{current[1]}.{current[2]}."
        )
        return False
    _ok(f"Python version: {current[0]}.{current[1]}.{current[2]}")
    return True


def _check_module(module_name: str, install_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        _ok(f"Module available: {module_name}")
        return True
    except Exception:
        _fail(f"Missing module: {module_name} (install: pip install {install_name})")
        return False


def _check_writeable_dir(path: Path, label: str) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".envcheck_", delete=True):
            pass
        _ok(f"{label} is writable: {path}")
        return True
    except Exception as exc:
        _fail(f"{label} is not writable: {path} ({exc})")
        return False


def _check_network(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PGLOK-env-check/1.0"})
        with urllib.request.urlopen(req, timeout=5):
            pass
        _ok(f"Network reachable: {url}")
        return True
    except Exception as exc:
        _warn(f"Network check failed for {url} ({exc})")
        return False


def main() -> int:
    print("PGLOK Environment Check")
    print("========================")

    project_root = Path(__file__).resolve().parents[1]
    src_dir = project_root / "src"
    config_dir = src_dir / "config"
    data_dir = src_dir / "data"

    failures = 0

    if not _check_python_version():
        failures += 1

    for module_name, install_name in REQUIRED_MODULES:
        if not _check_module(module_name, install_name):
            failures += 1

    if not _check_writeable_dir(config_dir, "Config directory"):
        failures += 1
    if not _check_writeable_dir(data_dir, "Data directory"):
        failures += 1

    if os.environ.get("PGLOK_SKIP_NETWORK_CHECK", "").strip() not in {"1", "true", "TRUE"}:
        for url in NETWORK_CHECKS:
            _check_network(url)
    else:
        _warn("Skipping network checks (PGLOK_SKIP_NETWORK_CHECK enabled).")

    print("========================")
    if failures:
        _fail(f"Environment check failed with {failures} blocking issue(s).")
        print("Fix missing items, then run: python3 scripts/check_env.py")
        return 1

    _ok("Environment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
