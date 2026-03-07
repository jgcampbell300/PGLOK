# Safe Extraction Guide

## ⚠️ Dangerous Link Path Warning

When extracting PGLOK archives, you may see:
```
ERROR: Dangerous link path was ignored : PGLOK-main/build_env/bin/python3 : /usr/bin/python3
```

## ✅ What This Means

This is **normal and expected**. The warning occurs because:
- Repository contains virtual environment symlinks
- 7-Zip detects these as "dangerous" (safety feature)
- **No files are actually corrupted or missing**

## 🛡️ Safe Extraction Methods

### Option 1: Use Our Clean Packages (Recommended)
```bash
# Download symlink-free package
curl -L https://github.com/jgcampbell300/PGLOK/releases/latest/download/PGLOK-Linux-Clean.tar.gz -o PGLOK-Clean.tar.gz

# Extract safely
tar -xzf PGLOK-Clean.tar.gz
cd PGLOK-*
./install.sh
```

### Option 2: Extract with Warning (Normal)
```bash
# The warning is safe - just ignore it
7z x PGLOK-main.zip -oPGLOK-main

# Files will extract correctly despite the warning
```

### Option 3: Use tar (Linux/macOS)
```bash
# tar doesn't show these warnings
tar -xzf PGLOK-main.zip
```

## 🔧 For Developers

When creating your own packages:

```bash
# Use our clean packaging script
./package_clean.sh

# Or exclude symlinks manually
tar -czhf package.tar.gz --exclude='build_env/*' --exclude='dist/*' .
```

## ✅ Verification

After extraction, verify:
```bash
# Check main files exist
ls -la PGLOK-main/
# Should show: src/, scripts/, README.md, etc.

# Test installation
cd PGLOK-main
./install_linux.sh --desktop
```

## 📞 Still Having Issues?

1. **Download clean package** from releases
2. **Use tar instead of 7-Zip**
3. **Ignore the warning** - extraction is successful
4. **Check file permissions** after extraction

---

**Note**: This warning only affects extraction. The application works perfectly once extracted.
