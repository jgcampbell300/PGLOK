# PGLOK - Project Gorgon Locator and Data Tools

A comprehensive desktop application for managing and searching Project Gorgon game data.

## Features

- **Data Browser**: Search and browse Project Gorgon game data (abilities, items, quests, recipes, etc.)
- **Itemizer**: Index and search your character inventory reports
- **Chat Monitor**: Real-time monitoring of Project Gorgon chat logs
- **Map Tools**: View and manage game maps with zoom/pan functionality
- **Character Browser**: Browse and analyze character data files
- **Global Search**: Search across all data sources simultaneously

## Quick Start (Installation & Running)

### Option 1: Easy Installation Scripts
```bash
# Clone and install
git clone https://github.com/jgcampbell300/PGLOK.git
cd PGLOK

# Run the installer for your OS
./install_linux.sh    # Linux
./install_mac.command # macOS  
./install_windows.bat # Windows
```

### Option 2: Manual Setup
```bash
# Clone the repository
git clone https://github.com/jgcampbell300/PGLOK.git
cd PGLOK

# Install dependencies
pip install -r requirements.txt

# Run the application
./start_linux.sh    # Linux
./start_mac.command # macOS
start_windows.bat   # Windows
```

Each launcher runs an environment preflight check before starting the app.

## First Time Setup

1. Launch PGLOK using one of the methods above
2. Click "Locate Project Gorgon" and point to your Project Gorgon installation
3. Click "Download Newer Files" to fetch the latest game data
4. The application will index the data and be ready to use

## Manual Environment Check

```bash
python3 scripts/check_env.py
```

If needed, install dependencies:

```bash
pip install -r requirements.txt
```

## System Requirements

- Python 3.8 or higher
- 100MB disk space for application
- 500MB+ disk space for game data
- 2GB+ RAM recommended

## Build One-File Executable (Per OS)

You must build on each target OS (Linux/macOS/Windows) separately.

### Linux
```bash
# Build executable
./build_linux.sh

# Package for distribution
./package_linux.sh
```

### macOS
```bash
./build_mac.command
```

### Windows
```bash
build_windows.bat
```

Build output:
- Linux/macOS: `dist/PGLOK`
- Windows: `dist/PGLOK.exe`

### Executable Features
- ✅ **Standalone** - No Python installation required
- ✅ **Icon Integration** - Custom application icon
- ✅ **Desktop Integration** - Can be added to application menu
- ✅ **Portable** - Single file, no installation needed

### Installing the Executable (Linux)
```bash
# Extract and install
tar -xzf PGLOK-Linux-YYYYMMDD.tar.gz
cd PGLOK-Linux-YYYYMMDD
./install.sh

# Or manually copy
sudo cp dist/PGLOK /usr/local/bin/
```

## Configuration

PGLOK stores configuration in:
- `src/config/` - Application settings and UI preferences
- `src/data/` - Downloaded game data and indexes (auto-created)

## Troubleshooting

**"Project Gorgon not found"**
- Typical locations:
  - Windows: `%USERPROFILE%\AppData\LocalLow\Elder Game\Project Gorgon`
  - macOS: `~/Library/Application Support/unity.Elder Game.Project Gorgon`
  - Linux: `~/.config/unity3d/Elder Game/Project Gorgon`

**"No data files found"**
- Click "Download Newer Files" to fetch game data from CDN
- Check internet connection

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

**Note**: This is a third-party tool and is not affiliated with Elder Game or Project Gorgon.
