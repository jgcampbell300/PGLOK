# 🎯 EXACT GitHub Release Setup for Auto-Update

## 📝 Release Information
- **Tag**: `v0.1.7`
- **Title**: `PGLOK v0.1.7`
- **Target Branch**: `main`
- **Description**: Copy content from `RELEASE_NOTES.md`

## 📎 REQUIRED Assets (Upload EXACTLY These Files)

### 1️⃣ PRIMARY: Linux Executable Package
```
File: PGLOK-Linux-v0.1.7.tar.gz
Size: 58MB
Purpose: Complete Linux installation package
Contents:
  ├── PGLOK (executable)
  ├── install.sh (installation script)
  ├── icon.png (application icon)
  ├── README.md (documentation)
  └── LICENSE (license file)
```

### 2️⃣ OPTIONAL: Source Package
```
File: PGLOK-v0.1.7-source.tar.gz
Size: 280KB
Purpose: Source code for developers
Contents: Complete source code repository
```

## ⚠️ CRITICAL: Naming Requirements

The auto-update system requires EXACT naming:
- ✅ **Must contain "linux"** for Linux detection
- ✅ **Must end with ".tar.gz"** for Linux packages
- ✅ **Version number helps** with identification (v0.1.7)

## 🚀 Step-by-Step Instructions

### 1. Go to Release Page
```
https://github.com/jgcampbell300/PGLOK/releases/new
```

### 2. Fill Release Form
- **Tag version**: `v0.1.7`
- **Release title**: `PGLOK v0.1.7`
- **Target**: `main`
- **Description**: Copy from `RELEASE_NOTES.md`

### 3. Upload Assets
Click "Attach files" and upload:
1. `PGLOK-Linux-v0.1.7.tar.gz` (58MB)
2. `PGLOK-v0.1.7-source.tar.gz` (280KB)

### 4. Publish
Click "Publish release"

## 🧪 Verification After Release

### Test Current Version
```bash
~/.local/bin/PGLOK
# Should show: "PGLOK is up to date"
```

### Test Auto-Update (with older version)
```bash
# Install v0.1.6 somewhere else
./start_linux.sh
# Should auto-update to v0.1.7
```

## 🔍 What Auto-Update System Does

1. **Checks**: `https://api.github.com/repos/jgcampbell300/PGLOK/releases/latest`
2. **Finds**: Assets with "linux" in name + ".tar.gz" extension
3. **Downloads**: The matching asset (PGLOK-Linux-v0.1.7.tar.gz)
4. **Extracts**: To temporary directory
5. **Installs**: Overwrites current installation
6. **Restarts**: New version automatically

## 📋 Quick Checklist

- [ ] Tag: v0.1.7
- [ ] Title: PGLOK v0.1.7
- [ ] Target: main
- [ ] Description: RELEASE_NOTES.md content
- [ ] Asset 1: PGLOK-Linux-v0.1.7.tar.gz (58MB)
- [ ] Asset 2: PGLOK-v0.1.7-source.tar.gz (280KB)
- [ ] Click: "Publish release"

## 🎯 Ready to Go!

Both files are in your PGLOK directory and ready for upload.
The auto-update system will work immediately after release creation.
