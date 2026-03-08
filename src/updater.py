import os
import sys
import json
import urllib.request
import urllib.parse
import subprocess
import tempfile
import shutil
import webbrowser
from pathlib import Path
from typing import Optional, Tuple

# GitHub URLs
GITHUB_RELEASE_API = "https://api.github.com/repos/jgcampbell300/PGLOK/releases/latest"
GITHUB_TAGS_API = "https://api.github.com/repos/jgcampbell300/PGLOK/tags"
RELEASES_URL = "https://github.com/jgcampbell300/PGLOK/releases/latest"


def parse_version_key(version: str) -> Optional[Tuple[int, ...]]:
    """Parse version string into tuple of integers for comparison."""
    if not version:
        return None
    # Remove 'v' prefix if present
    version = version.lstrip('v')
    parts = version.split('.')
    if not parts:
        return None
    return tuple(int(p) for p in parts)


def fetch_latest_repo_version():
    """Fetch the latest version from GitHub."""
    headers = {
        "User-Agent": "PGLOK/1.0 (+https://github.com/jgcampbell300/PGLOK)",
        "Accept": "application/vnd.github+json",
    }
    
    for url, key in ((GITHUB_RELEASE_API, "tag_name"), (GITHUB_TAGS_API, "name")):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                    
                    if key == "tag_name":
                        value = str(payload.get("tag_name", "")).strip()
                        assets = payload.get("assets", [])
                    else:
                        first = payload[0] if isinstance(payload, list) and payload else {}
                        value = str(first.get("name", "")).strip()
                        assets = []
                    
                    if value:
                        return value, assets
                else:
                    print(f"API returned status {resp.status} for {url}")
        except Exception as e:
            print(f"Failed to fetch from {url}: {e}")
            continue
    
    return "", []


def get_download_url(assets: list, preferred_name: str = None) -> Optional[str]:
    """Get the download URL for the preferred asset."""
    if not assets:
        return None
    
    # Try to find preferred asset first
    if preferred_name:
        for asset in assets:
            if preferred_name in asset.get("name", "").lower():
                return asset.get("browser_download_url")
    
    # Fallback to first asset
    return assets[0].get("browser_download_url") if assets else None


def download_update(url: str, dest_path: Path) -> bool:
    """Download the update file."""
    try:
        print(f"Downloading update from {url}")
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False


def install_update_windows(zip_path: Path) -> bool:
    """Install update on Windows by extracting over current installation."""
    try:
        import zipfile
        
        # Get current script directory
        current_dir = Path(__file__).resolve().parent.parent.parent
        
        # Extract zip to temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Find the extracted directory (usually PGLOK-main)
            extracted_dirs = [d for d in Path(temp_dir).iterdir() if d.is_dir()]
            if not extracted_dirs:
                return False
            
            source_dir = extracted_dirs[0]
            
            # Copy files over current installation
            for item in source_dir.rglob('*'):
                if item.is_file():
                    dest_file = current_dir / item.relative_to(source_dir)
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
        
        return True
    except Exception as e:
        print(f"Windows update failed: {e}")
        return False


def install_update_linux(tar_path: Path) -> bool:
    """Install update on Linux by extracting over current installation."""
    try:
        import tarfile
        
        # Get current script directory
        current_dir = Path(__file__).resolve().parent.parent.parent
        
        # Extract tar to temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            with tarfile.open(tar_path, 'r:*') as tar_ref:
                tar_ref.extractall(temp_dir)
            
            # Find the extracted directory
            extracted_dirs = [d for d in Path(temp_dir).iterdir() if d.is_dir()]
            if not extracted_dirs:
                return False
            
            source_dir = extracted_dirs[0]
            
            # Copy files over current installation
            for item in source_dir.rglob('*'):
                if item.is_file():
                    dest_file = current_dir / item.relative_to(source_dir)
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
        
        return True
    except Exception as e:
        print(f"Linux update failed: {e}")
        return False


def install_update_mac(dmg_path: Path) -> bool:
    """Install update on macOS (basic implementation)."""
    try:
        # For now, just open the DMG for manual installation
        subprocess.run(['open', str(dmg_path)], check=True)
        return True
    except Exception as e:
        print(f"macOS update failed: {e}")
        return False


def restart_application():
    """Restart the application."""
    try:
        # Get current executable path
        executable = sys.executable
        if sys.executable.endswith('python') or sys.executable.endswith('python3'):
            # We're running from source, restart with main script
            script_path = Path(__file__).resolve().parent.parent.parent / 'src' / 'pglok.py'
            subprocess.Popen([sys.executable, str(script_path)])
        else:
            # We're running from executable
            subprocess.Popen([executable])
        
        # Exit current instance
        sys.exit(0)
    except Exception as e:
        print(f"Failed to restart application: {e}")


def perform_auto_update(current_version: str) -> bool:
    """Perform automatic update if a newer version is available."""
    try:
        # Check for updates
        latest_version, assets = fetch_latest_repo_version()
        if not latest_version:
            return False
        
        current_key = parse_version_key(current_version)
        latest_key = parse_version_key(latest_version)
        
        if current_key is None or latest_key is None or latest_key <= current_key:
            return False  # No update needed
        
        print(f"Update available: {current_version} -> {latest_version}")
        
        # Determine preferred asset based on platform
        platform = sys.platform
        preferred_name = None
        
        if platform == 'win32':
            preferred_name = 'windows' or 'exe'
        elif platform == 'darwin':
            preferred_name = 'mac' or 'dmg'
        elif platform.startswith('linux'):
            preferred_name = 'linux' or 'tar.gz'
        
        # Get download URL
        download_url = get_download_url(assets, preferred_name)
        if not download_url:
            print("No suitable download found")
            return False
        
        # Download update
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            
            # Determine file extension
            if download_url.endswith('.zip'):
                update_file = temp_dir_path / "update.zip"
            elif download_url.endswith('.tar.gz'):
                update_file = temp_dir_path / "update.tar.gz"
            elif download_url.endswith('.dmg'):
                update_file = temp_dir_path / "update.dmg"
            else:
                update_file = temp_dir_path / "update"
            
            if not download_update(download_url, update_file):
                return False
            
            # Install update
            success = False
            if platform == 'win32' and update_file.suffix == '.zip':
                success = install_update_windows(update_file)
            elif platform.startswith('linux') and update_file.suffix in ['.tar.gz', '.tgz']:
                success = install_update_linux(update_file)
            elif platform == 'darwin' and update_file.suffix == '.dmg':
                success = install_update_mac(update_file)
            
            if success:
                print("Update installed successfully")
                return True
            else:
                print("Update installation failed")
                return False
                
    except Exception as e:
        print(f"Auto update failed: {e}")
        return False
