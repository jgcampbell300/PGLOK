# PGLOK v0.2.0 Release

## Highlights

- Added Survey Helper tool for Project Gorgon surveying tasks.
- Added player position tracking from Player.log for better gameplay analysis.
- Added food comparison tool with caching and gourmand report import support.
- Fixed Linux auto-updater tar.gz detection to properly identify release tarballs.
- Improved threading error handling in the auto-update checker.

## New Features

- **Survey Helper**: Streamlined interface for managing and tracking survey tasks across Project Gorgon.
- **Player Position Tracking**: Automatically reads and displays current player position from Player.log.
- **Food Comparison Tool**: Compare foods with integrated caching and gourmand report import functionality.

## Bug Fixes

- Fixed tar.gz detection in Linux auto-updater to correctly identify and download release packages.
- Resolved threading errors that could occur during update checks.
- Improved compatibility with existing addon system.

## Installation

```bash
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-Linux-v0.2.0.tar.gz -o PGLOK.tar.gz
tar -xzf PGLOK.tar.gz
cd PGLOK-Linux-v0.2.0
./install.sh
```

## Assets

- `PGLOK-Linux-v0.2.0.tar.gz`
- `PGLOK-v0.2.0-source.tar.gz`
