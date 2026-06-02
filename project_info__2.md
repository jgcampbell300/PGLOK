# PGLOK — Plan Status and Codebase Overview

## Summary
PGLOK is a Python desktop application for locating, indexing, and querying Project Gorgon game data. The current planning thread in this repository is centered on the v0.2.0 release and its auto-update/release pipeline, not a new feature implementation.

From the repository artifacts, the project appears to be in the “release preparation / verification” stage: release notes and a release checklist exist, and a GitHub Actions release workflow is present. The remaining work is less about product features and more about making sure the release packaging and publication path actually works end-to-end.

## Where We Are in the Plan
The plan is currently at the stage where the release is defined, documented, and partially wired up:

- **Release target is established**: `v0.2.0`
- **Release contents are documented**: `RELEASE_NOTES.md`
- **Release verification criteria are documented**: `GITHUB_RELEASE_CHECKLIST.md`
- **A release workflow exists**: `.github/workflows/release.yml`
- **Auto-update behavior is already expected to consume GitHub release assets**: `README.md` and `AUTO_UPDATE_DIAGNOSIS.md`

What is **not yet fully complete** is the publication pipeline itself:

- the workflow is configured to run on tag pushes, but
- the release asset upload step appears to depend on a `create_release` step output that is not actually wired with an `id`
- the docs indicate the app expects a downloadable Linux tarball named like `PGLOK-Linux-v0.2.0.tar.gz`
- the current checklist implies the release must be created and verified, but the repo artifacts suggest the workflow still needs validation against GitHub Releases behavior

In short: **the release plan is documented and partially implemented, but likely not fully verified in practice yet.**

## Architecture
PGLOK is a layered Python application with a traditional desktop-app structure:

- **Core app code** lives under `src/`
- **Configuration and UI settings** live under `src/config/`
- **Domain/data handling** lives in modules like `data_acquisition.py`, `data_index.py`, `food_parser.py`, `food_tracker.py`, and related helpers
- **Subsystems** such as chat monitoring, communication, add-ons, survey tools, and map tools are separated into their own packages
- **Build/release automation** is handled by shell/batch scripts and a GitHub Actions workflow

The top-level launch path is through platform-specific scripts such as:

- `start_linux.sh`
- `start_mac.command`
- `start_windows.bat`

The project also supports packaging via:

- `build_linux.sh`
- `build_mac.command`
- `build_windows.bat`
- `.github/workflows/release.yml`

## Directory Structure

```text
PGLOK/
├── README.md                     — User-facing install, setup, and build instructions
├── RELEASE_NOTES.md              — v0.2.0 feature/release summary
├── GITHUB_RELEASE_CHECKLIST.md   — Release verification checklist
├── AUTO_UPDATE_DIAGNOSIS.md      — Explanation of the release/auto-update failure mode
├── src/                          — Main Python application
│   ├── pglok.py                  — Main application entry point
│   ├── chat/                     — Chat monitoring
│   ├── communications/           — Data publishing/listening and MQTT integration
│   ├── config/                   — Config, theme, window state
│   ├── database/                 — DB manager, migrations, models
│   ├── itemizer/                 — Indexing logic
│   ├── maptools/                 — Browser/wiki sync utilities
│   ├── player/                   — Player log monitoring
│   ├── survey/                   — Survey helper functionality
│   └── utils/                    — Shared helpers
├── addons/                       — External addon system and packaged addons
├── scripts/                      — Environment and packaging helpers
├── .github/workflows/            — Release automation
│   └── release.yml
└── data/, build/, dist/          — Generated/runtime artifacts
```

## Key Abstractions

### `src/pglok.py`
- **Responsibility**: Main desktop application entry point and orchestration layer.
- **Role**: Likely boots the GUI, wires subsystems together, and coordinates startup checks.
- **Used by**: Platform launch scripts and packaged executables.

### `src/config/config.py`
- **Responsibility**: Application configuration management.
- **Role**: Centralizes paths, settings, and runtime configuration.
- **Used by**: Subsystems that need stable application state or paths.

### `src/database/database_manager.py`
- **Responsibility**: Database access and schema management.
- **Role**: Connects the app to persistent storage and migration state.
- **Used by**: Indexing, trackers, and data ingestion modules.

### `src/data_acquisition.py`
- **Responsibility**: Pulling/refreshing Project Gorgon data.
- **Role**: One of the main data pipeline entry points.
- **Used by**: Indexers and UI actions that fetch new files.

### `src/data_index.py`
- **Responsibility**: Indexing and searchable data structures.
- **Role**: Converts downloaded or parsed data into queryable form.
- **Used by**: Search/display features across the app.

### `src/chat/monitor.py`
- **Responsibility**: Chat log monitoring.
- **Role**: Watches game logs and extracts chat-related events or text.
- **Used by**: Chat UI features and event-driven data updates.

### `src/player/monitor.py`
- **Responsibility**: Player log monitoring.
- **Role**: Reads player position/state from logs.
- **Used by**: The player-position feature mentioned in the release notes.

### `src/survey/`
- **Responsibility**: Survey helper feature set.
- **Role**: New feature area called out in the v0.2.0 notes.
- **Used by**: The main app UI for surveying tasks.

### `src/addons/`
- **Responsibility**: Addon discovery and integration.
- **Role**: Hosts the addon system described in `ADDON_SYSTEM.md`.
- **Used by**: Menu integration, window management, and external addon loading.

### `.github/workflows/release.yml`
- **Responsibility**: Automates release packaging and GitHub release creation.
- **Role**: Triggered by tag pushes and packages source artifacts.
- **Used by**: Release publishing and auto-update distribution.

## Data Flow
1. A tag push such as `v0.2.0` triggers `.github/workflows/release.yml`.
2. The workflow checks out code, installs Python dependencies, and packages a release tarball.
3. GitHub Release creation is intended to publish that tarball as a downloadable asset.
4. The app’s auto-update logic expects those release assets to exist and match naming conventions.
5. End users install the build or download the release tarball and run the app through platform launchers.
6. On startup, the app checks local environment, locates Project Gorgon data, downloads missing files, and indexes the data for browsing/search.

## Non-Obvious Behaviors & Design Decisions

- **Release publication is as important as the app itself**  
  The app’s auto-update behavior depends on GitHub release assets, so a missing or misconfigured release workflow effectively breaks update delivery even if the app code is fine.

- **The release pipeline is tag-driven**  
  The workflow only runs when a tag matching `v*` is pushed. That means versioning discipline is part of the deployment mechanism.

- **The documentation reflects a fallback strategy**  
  `AUTO_UPDATE_DIAGNOSIS.md` notes that if a release has no uploaded assets, the app can fall back to GitHub-generated tarballs. That is a resilience measure, not just a convenience.

- **The Linux tarball naming convention matters**  
  Docs explicitly require the Linux package name to include `linux` and end in `.tar.gz`. This is a hidden contract between build tooling and the updater.

- **The repo includes both feature code and deployment tooling**  
  The application is not just a GUI; it also includes packaging scripts, installer scripts, and release automation, so a change in one layer can break another.

## Current Gaps / Risks

- The release workflow should be reviewed for GitHub Actions wiring correctness.
- The release artifact naming should be validated against the auto-update code expectations.
- The checklist claims verification of version `0.2.0` and update offer from `0.1.9`, but the repo artifacts alone do not prove that path has been exercised successfully.
- The workflow’s asset upload step appears suspicious because the release creation step is not shown with an explicit `id`, yet later steps reference `steps.create_release.outputs.upload_url`.

## Module Reference

| File | Purpose |
|------|---------|
| `README.md` | User install/build docs and release download instructions |
| `RELEASE_NOTES.md` | v0.2.0 release summary and package names |
| `GITHUB_RELEASE_CHECKLIST.md` | Manual release verification checklist |
| `AUTO_UPDATE_DIAGNOSIS.md` | Explains why auto-update failed before releases existed |
| `.github/workflows/release.yml` | GitHub Actions release packaging and publishing workflow |
| `src/pglok.py` | Main app entry point |
| `src/data_acquisition.py` | Fetches game data |
| `src/data_index.py` | Indexes data for search/use |
| `src/chat/monitor.py` | Watches chat logs |
| `src/player/monitor.py` | Watches player logs/position |
| `src/database/database_manager.py` | Database management |
| `src/addons/` | Addon subsystem |
| `src/survey/` | Survey helper feature area |
| `src/maptools/` | Browser/wiki synchronization tools |

## Suggested Reading Order
1. `GITHUB_RELEASE_CHECKLIST.md` — Best place to see the intended release state and verification criteria.
2. `RELEASE_NOTES.md` — Confirms what v0.2.0 is supposed to contain.
3. `AUTO_UPDATE_DIAGNOSIS.md` — Explains the update failure mode and the missing release dependency.
4. `.github/workflows/release.yml` — Shows the actual automation path.
5. `README.md` — Connects release artifacts to user install and startup behavior.
6. `src/pglok.py` — Main runtime entry point once you want to trace app startup.

## Bottom Line
The plan is currently in the **release verification / publication** stage. The codebase already documents the v0.2.0 release and has a release workflow, but the repo artifacts suggest the team still needs to confirm that the GitHub release step, asset upload, and auto-update path work together correctly.