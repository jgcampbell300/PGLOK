# PGLOK
Tool for Project Gorgon

## Quick Start

Run one of these from the project root:

- Linux: `./start_linux.sh`
- macOS: `./start_mac.command`
- Windows: `start_windows.bat`

Each launcher runs an environment preflight check before starting the app.

## Manual Environment Check

```bash
python3 scripts/check_env.py
```

If needed, install dependencies:

```bash
pip install -r requirements.txt
```

## Build One-File Executable (Per OS)

You must build on each target OS (Linux/macOS/Windows) separately.

- Linux: `./build_linux.sh`
- macOS: `./build_mac.command`
- Windows: `build_windows.bat`

Build output:

- Linux/macOS: `dist/PGLOK`
- Windows: `dist/PGLOK.exe`
