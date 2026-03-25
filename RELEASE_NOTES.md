# PGLOK v0.1.7 Release

## 🎉 Features

### Timer System Overhaul
- **New Timer Window**: Replaced Data toolbar button with dedicated Timers feature
- **Compact UI Layout**: Reduced padding and spacing for space-efficient timer display
- **Window State Persistence**: Timers window now restores geometry and position

### Chat Monitor Integration
- **Timer Chat Integration**: Timer window now uses the main chat monitor for log processing
- **Fixed Missing Methods**: Resolved NameError issues with chat log scanning

### UI Improvements
- **Standardized Window Creation**: Consistent Toplevel creation across all windows
- **Better Window Management**: Improved geometry restoration for all popup windows

## 📦 Installation

### Option 1: Download Package (Recommended)
```bash
# Download Linux executable package
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-Linux-v0.1.7.tar.gz -o PGLOK.tar.gz

# Extract and install
tar -xzf PGLOK.tar.gz
cd PGLOK-*
./install.sh
```

### Option 2: Download Source
```bash
# Download source code
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-v0.1.7-source.tar.gz -o PGLOK-source.tar.gz

# Extract and install
tar -xzf PGLOK-source.tar.gz
cd PGLOK-*
./install_linux.sh --desktop
```

### Option 3: Clone Repository
```bash
git clone https://github.com/jgcampbell300/PGLOK.git
cd PGLOK
./install_linux.sh --desktop
```

## 🔄 Auto-Update

PGLOK includes automatic update functionality:
- ✅ Checks for updates on startup
- ✅ Downloads and installs automatically
- ✅ Restarts application when needed
- ✅ Falls back to manual update if needed

## 🐛 Bug Fixes

- Fixed NameError in timer window geometry restoration
- Fixed missing chat log processing methods in timer window
- Standardized Toplevel window creation across the application

## 🚀 Platform Support

- ✅ Linux (tar.gz packages)
- ✅ Windows (zip packages) 
- ✅ macOS (dmg packages)
- ✅ Source code (tar.gz)

## 📋 Requirements

- Python 3.8+ (for source installation)
- 100MB disk space minimum
- 500MB+ for game data

---

**Note**: This is a third-party tool and is not affiliated with Elder Game or Project Gorgon.
