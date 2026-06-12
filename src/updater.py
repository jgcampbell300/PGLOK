import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

GITHUB_RELEASE_API = "https://api.github.com/repos/jgcampbell300/PGLOK/releases/latest"
GITHUB_TAGS_API = "https://api.github.com/repos/jgcampbell300/PGLOK/tags"
RELEASES_URL = "https://github.com/jgcampbell300/PGLOK/releases/latest"

SKIP_UPDATE_PREFIXES = {
    ".git",
    ".idea",
    "__pycache__",
    "backups",
    "build",
    "build_env",
    "dist",
}
SKIP_UPDATE_SUFFIXES = {".pyc", ".pyo"}
SKIP_UPDATE_FILES = {
    "config/lokfarmer/lokfarmer_config.json",
    "data/farming_data.db",
    "data/pglok.db",
    "timers.db",
}


def get_install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def parse_version_key(version: str) -> Optional[Tuple[int, ...]]:
    if not version:
        return None
    version = version.lstrip("v")
    parts = version.split(".")
    if not parts:
        return None
    return tuple(int(p) for p in parts)


def fetch_latest_repo_version():
    headers = {
        "User-Agent": "PGLOK/1.0 (+https://github.com/jgcampbell300/PGLOK)",
        "Accept": "application/vnd.github+json",
    }

    for url, key in ((GITHUB_RELEASE_API, "tag_name"), (GITHUB_TAGS_API, "name")):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    print(f"API returned status {resp.status} for {url}")
                    continue

                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                if key == "tag_name":
                    value = str(payload.get("tag_name", "")).strip()
                    assets = payload.get("assets", [])
                    if not assets:
                        tarball_url = payload.get("tarball_url")
                        zipball_url = payload.get("zipball_url")
                        if sys.platform.startswith("linux") and tarball_url:
                            assets = [{"name": f"{value}.tar.gz", "browser_download_url": tarball_url}]
                        elif sys.platform == "win32" and zipball_url:
                            assets = [{"name": f"{value}.zip", "browser_download_url": zipball_url}]
                        elif tarball_url:
                            assets = [{"name": f"{value}.tar.gz", "browser_download_url": tarball_url}]
                else:
                    first = payload[0] if isinstance(payload, list) and payload else {}
                    value = str(first.get("name", "")).strip()
                    assets = []

                if value:
                    return value, assets
        except Exception as e:
            print(f"Failed to fetch from {url}: {e}")
            continue

    return "", []


def get_download_url(assets: list, preferred_name: str = None) -> Optional[str]:
    if not assets:
        return None

    if preferred_name:
        for asset in assets:
            if preferred_name in asset.get("name", "").lower():
                return asset.get("browser_download_url")

    return assets[0].get("browser_download_url") if assets else None


def choose_download_filename(download_url: str, assets: list) -> str:
    asset_name = ""
    for asset in assets:
        if asset.get("browser_download_url") == download_url:
            asset_name = str(asset.get("name", "")).lower()
            break

    url_lower = download_url.lower()
    if url_lower.endswith(".zip") or asset_name.endswith(".zip"):
        return "update.zip"
    if url_lower.endswith(".tar.gz") or asset_name.endswith(".tar.gz"):
        return "update.tar.gz"
    if url_lower.endswith(".tgz") or asset_name.endswith(".tgz"):
        return "update.tgz"
    if url_lower.endswith(".dmg") or asset_name.endswith(".dmg"):
        return "update.dmg"
    return "update"


def download_update(url: str, dest_path: Path) -> bool:
    try:
        print(f"Downloading update from {url}")
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False


def resolve_extracted_source_dir(temp_dir: Path) -> Optional[Path]:
    extracted_items = list(temp_dir.iterdir())
    if not extracted_items:
        return None

    # If the archive expands into mixed top-level files and folders, copy from the
    # archive root so all files are preserved. Only collapse into a single child
    # directory when the archive truly wraps everything in one folder.
    top_level_files = [item for item in extracted_items if item.is_file()]
    top_level_dirs = [item for item in extracted_items if item.is_dir()]
    if top_level_files or len(top_level_dirs) != 1:
        return temp_dir

    return top_level_dirs[0]


def should_skip_update_path(relative_path: Path) -> bool:
    rel = relative_path.as_posix()
    if rel in SKIP_UPDATE_FILES:
        return True
    if any(part in SKIP_UPDATE_PREFIXES for part in relative_path.parts):
        return True
    if relative_path.suffix.lower() in SKIP_UPDATE_SUFFIXES:
        return True
    return False


def _extract_version_from_dirname(source_dir: Path) -> Optional[str]:
    """Try to extract a version number from the extracted directory name.

    The tarball creates a directory like PGLOK-Linux-v0.2.7/ or PGLOK-Linux-v0.2.6/.
    """
    # The source_dir itself might be the versioned directory
    for candidate in [source_dir] + list(source_dir.parents)[:2]:
        name = candidate.name
        # Look for patterns like v0.2.7 or 0.2.7 in the directory name
        import re
        match = re.search(r'v?(\d+\.\d+\.\d+)', name)
        if match:
            return match.group(1)
    return None


def _sha256_of_exe_in(source_dir: Path) -> Optional[str]:
    """Return SHA256 of the PGLOK executable found under source_dir."""
    import hashlib
    exe_name = "PGLOK.exe" if sys.platform == "win32" else "PGLOK"
    for candidate in source_dir.rglob(exe_name):
        try:
            h = hashlib.sha256()
            h.update(candidate.read_bytes())
            return h.hexdigest()
        except Exception:
            return None
    return None


def _is_same_binary_as_running(source_dir: Path) -> bool:
    """Check if the extracted binary is identical to the currently running one.

    If true, the update archive contains the same binary we already have,
    meaning it was incorrectly packaged.
    """
    extracted_sha = _sha256_of_exe_in(source_dir)
    if extracted_sha is None:
        return False

    # Path to the running executable
    if getattr(sys, "frozen", False):
        running_path = Path(sys.executable)
    else:
        return False  # Running from source, can't compare

    try:
        h = hashlib.sha256()
        h.update(running_path.read_bytes())
        return h.hexdigest() == extracted_sha
    except Exception:
        return False


def copy_update_tree(source_dir: Path, current_dir: Path) -> bool:
    files_copied = 0
    files_skipped = 0

    for item in source_dir.rglob("*"):
        if not item.is_file():
            continue

        relative_path = item.relative_to(source_dir)
        if should_skip_update_path(relative_path):
            files_skipped += 1
            continue

        dest_file = current_dir / relative_path
        try:
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            # If the destination is the running executable, rename it aside first.
            # On Linux, renaming a running binary is safe — the old process keeps
            # the original inode. On Windows, the rename will fail and we fall
            # through to the existing exception handler.
            if dest_file.exists():
                old_name = dest_file.with_name(dest_file.name + ".old")
                try:
                    dest_file.rename(old_name)
                except OSError:
                    pass  # Can't rename — proceed to try direct copy
            shutil.copy2(item, dest_file)
            # Clean up the renamed-aside file on success
            old_name = dest_file.with_name(dest_file.name + ".old")
            if old_name.exists():
                try:
                    old_name.unlink()
                except OSError:
                    pass  # Best-effort cleanup
            files_copied += 1
            print(f"Copied: {item} -> {dest_file}")
        except shutil.SameFileError:
            files_skipped += 1
            print(f"Skipped identical file: {item} -> {dest_file}")
            continue
        except Exception as e:
            print(f"Failed to copy {item}: {e}")
            return False

    # Clean up any leftover .old files
    for leftover in current_dir.rglob("*.old"):
        if leftover.name.endswith(".old"):
            try:
                leftover.unlink()
            except OSError:
                pass

    print(f"Successfully copied {files_copied} files")
    if files_skipped:
        print(f"Skipped {files_skipped} local or identical files")
    return True


def _verify_extracted_version(source_dir: Path, expected_version: str) -> bool:
    """Check the extracted update matches the expected release version.

    Two checks:
      1) Directory name contains the expected version (e.g. ...-v0.2.7/).
      2) SHA256 of the extracted binary differs from the currently running binary
         (catches identical-binary-in-wrong-tarball packaging errors).

    Both must pass for the update to proceed.
    """
    expected_clean = expected_version.lstrip("v")

    # Check 1: directory name version
    dir_version = _extract_version_from_dirname(source_dir)
    if dir_version and dir_version != expected_clean:
        print(f"❌ Version mismatch: extracted directory indicates v{dir_version}, "
              f"expected v{expected_clean}")
        print(f"   The release archive was incorrectly packaged. Update aborted.")
        return False

    if dir_version == expected_clean:
        print(f"✅ Extracted directory version matches: v{dir_version}")

    # Check 2: SHA comparison vs running binary (catches identical binary with wrong name)
    if _is_same_binary_as_running(source_dir):
        print(f"❌ Extracted binary is identical to the currently running executable.")
        print(f"   The release archive contains the same binary — not an upgrade. Update aborted.")
        return False

    print(f"✅ Extracted binary differs from running executable — proceeding with update.")
    return True


def install_update_windows(zip_path: Path, expected_version: str) -> bool:
    try:
        import zipfile

        current_dir = get_install_root()
        print(f"Extracting Windows update from {zip_path} to {current_dir}")

        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Using temporary directory: {temp_dir}")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            source_dir = resolve_extracted_source_dir(Path(temp_dir))
            if source_dir is None:
                print("No items found in extracted zip")
                return False

            print(f"Source directory for update: {source_dir}")

            if not _verify_extracted_version(source_dir, expected_version):
                return False

            return copy_update_tree(source_dir, current_dir)
    except Exception as e:
        print(f"Windows update failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def install_update_linux(tar_path: Path, expected_version: str) -> bool:
    try:
        import tarfile

        current_dir = get_install_root()
        print(f"Extracting update from {tar_path} to {current_dir}")

        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Using temporary directory: {temp_dir}")
            try:
                with tarfile.open(tar_path, "r:gz") as tar_ref:
                    tar_ref.extractall(temp_dir)
            except tarfile.ReadError:
                try:
                    with tarfile.open(tar_path, "r:bz2") as tar_ref:
                        tar_ref.extractall(temp_dir)
                except tarfile.ReadError:
                    with tarfile.open(tar_path, "r") as tar_ref:
                        tar_ref.extractall(temp_dir)

            source_dir = resolve_extracted_source_dir(Path(temp_dir))
            if source_dir is None:
                print("No items found in extracted archive")
                return False

            print(f"Source directory for update: {source_dir}")

            if not _verify_extracted_version(source_dir, expected_version):
                return False

            return copy_update_tree(source_dir, current_dir)
    except Exception as e:
        print(f"Linux update failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def install_update_mac(dmg_path: Path, expected_version: str) -> bool:
    try:
        subprocess.run(["open", str(dmg_path)], check=True)
        return True
    except Exception as e:
        print(f"macOS update failed: {e}")
        return False


def restart_application():
    try:
        executable = sys.executable
        if getattr(sys, "frozen", False):
            subprocess.Popen([executable])
        elif sys.executable.endswith("python") or sys.executable.endswith("python3"):
            script_path = get_install_root() / "src" / "pglok.py"
            subprocess.Popen([sys.executable, str(script_path)])

        sys.exit(0)
    except Exception as e:
        print(f"Failed to restart application: {e}")
        import traceback
        traceback.print_exc()


def _refresh_required_data_files() -> bool:
    """Download any missing or changed CDN data files.

    This is best-effort: if the network or downloader fails, we keep the
    application update result intact and let the user retry data refresh later.
    """
    try:
        from src.data_acquisition import main as run_data_acquisition

        print("Refreshing required CDN data files...")
        run_data_acquisition()
        return True
    except Exception as e:
        print(f"Data refresh failed: {e}")
        return False


def perform_auto_update(current_version: str) -> bool:
    try:
        latest_version, assets = fetch_latest_repo_version()
        if not latest_version:
            return False

        current_key = parse_version_key(current_version)
        latest_key = parse_version_key(latest_version)
        if current_key is None or latest_key is None or latest_key <= current_key:
            return False

        print(f"Update available: {current_version} -> {latest_version}")

        platform = sys.platform
        preferred_name = None
        if platform == "win32":
            preferred_name = "windows"
        elif platform == "darwin":
            preferred_name = "mac"
        elif platform.startswith("linux"):
            preferred_name = "linux"

        download_url = get_download_url(assets, preferred_name)
        if not download_url:
            print("No suitable download found")
            return False

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            update_file = temp_dir_path / choose_download_filename(download_url, assets)
            if not download_update(download_url, update_file):
                return False

            success = False
            suffixes = update_file.suffixes
            url_lower = download_url.lower()
            if platform == "win32" and (update_file.suffix == ".zip" or ".zip" in url_lower):
                success = install_update_windows(update_file, latest_version)
            elif platform.startswith("linux") and (
                ".tgz" in url_lower or ".tar.gz" in url_lower or 
                (len(suffixes) >= 2 and suffixes[-2].lower() == ".tar" and suffixes[-1].lower() == ".gz")
            ):
                success = install_update_linux(update_file, latest_version)
            elif platform == "darwin" and update_file.suffix == ".dmg":
                success = install_update_mac(update_file, latest_version)

            if success:
                print("Update installed successfully")
                _refresh_required_data_files()
                return True

            print("Update installation failed")
            return False
    except Exception as e:
        print(f"Auto update failed: {e}")
        return False
