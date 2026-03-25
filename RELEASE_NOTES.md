# PGLOK v0.1.8 Release

## Highlights

- Fixed the Linux auto-update loop in source installs.
- Added fallback to GitHub release tarballs when a release has no uploaded assets.
- Prevented repo-based updates from overwriting local config, databases, virtualenv files, and build output.
- Fixed standalone Linux packaging so bundled builds can load top-level addons correctly.
- Fixed the update completion dialog path by importing `messagebox` in the main app.

## Linux Packaging

- Rebuilt the standalone Linux executable from the fixed checkout.
- Updated the PyInstaller spec to include the top-level `addons/` directory.
- Verified the packaged executable starts cleanly from `~/.local/bin/PGLOK`.

## Auto-Update Behavior

- Release checks now fall back to GitHub `tarball_url`/`zipball_url` when release assets are missing.
- Linux `.tar.gz` and `.tgz` downloads are detected correctly.
- Install and restart paths now resolve to the actual app root for both source and frozen runs.

## Installation

```bash
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-Linux-v0.1.8.tar.gz -o PGLOK.tar.gz
tar -xzf PGLOK.tar.gz
cd PGLOK-Linux-v0.1.8
./install.sh
```

## Assets

- `PGLOK-Linux-v0.1.8.tar.gz`
- `PGLOK-v0.1.8-source.tar.gz`
