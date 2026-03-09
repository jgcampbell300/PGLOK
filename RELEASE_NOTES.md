# PGLOK v0.1.4 Release

## 🎉 Features

### Chat Monitor Improvements
- **Combined Status/Error Tabs**: Status and error messages now appear together in a single "System" tab
- **Improved Organization**: Reduced tab clutter while maintaining message filtering
- **Better User Experience**: System messages are logically grouped together

### Previous Enhancements
- **Automatic Update System**: Checks for updates on startup and installs automatically
- **Linux Tar Extraction**: Fixed issues with .tar.gz and .tar file extraction
- **Safe Extraction**: Prevents dangerous symlink warnings during installation
- **Professional Icons**: Custom application branding for all platforms

## 📦 Installation

### Option 1: Download Package (Recommended)
```bash
# Download Linux executable package
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-Linux-v0.1.4.tar.gz -o PGLOK.tar.gz

# Extract and install
tar -xzf PGLOK.tar.gz
cd PGLOK-*
./install.sh
```

### Option 2: Download Source
```bash
# Download source code
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-v0.1.4-source.tar.gz -o PGLOK-source.tar.gz

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

PGLOK now includes automatic update functionality:
- ✅ Checks for updates on startup
- ✅ Downloads and installs automatically
- ✅ Restarts application when needed
- ✅ Falls back to manual update if needed

## 🐛 Bug Fixes

- Fixed Linux tar.gz extraction issues
- Combined Status/Error tabs for better organization
- Improved error handling in update system

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
