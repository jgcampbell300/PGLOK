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


def should_skip_update_path(relative_path: Path) -> bool:
    rel = relative_path.as_posix()
    if rel in SKIP_UPDATE_FILES:
        return True
    if any(part in SKIP_UPDATE_PREFIXES for part in relative_path.parts):
        return True
    if relative_path.suffix.lower() in SKIP_UPDATE_SUFFIXES:
        return True
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
            shutil.copy2(item, dest_file)
            files_copied += 1
            print(f"Copied: {item} -> {dest_file}")
        except shutil.SameFileError:
            files_skipped += 1
            print(f"Skipped identical file: {item} -> {dest_file}")
            continue
        except Exception as e:
            print(f"Failed to copy {item}: {e}")
            return False

    print(f"Successfully copied {files_copied} files")
    if files_skipped:
        print(f"Skipped {files_skipped} local or identical files")
    return True


def install_update_windows(zip_path: Path) -> bool:
    try:
        import zipfile

        current_dir = get_install_root()
        print(f"Extracting Windows update from {zip_path} to {current_dir}")

        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Using temporary directory: {temp_dir}")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            extracted_dirs = [d for d in Path(temp_dir).iterdir() if d.is_dir()]
            if not extracted_dirs:
                print("No directories found in extracted zip")
                return False

            source_dir = extracted_dirs[0]
            print(f"Source directory for update: {source_dir}")
            return copy_update_tree(source_dir, current_dir)
    except Exception as e:
        print(f"Windows update failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def install_update_linux(tar_path: Path) -> bool:
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

            extracted_items = list(Path(temp_dir).iterdir())
            if not extracted_items:
                print("No items found in extracted archive")
                return False

            source_dir = None
            for item in extracted_items:
                if item.is_dir():
                    source_dir = item
                    break
                if item.is_file() and item.name in ["test.txt", "README.md"]:
                    source_dir = Path(temp_dir)
                    break

            if source_dir is None:
                print("No suitable source directory found in extracted archive")
                return False

            print(f"Source directory for update: {source_dir}")
            return copy_update_tree(Path(source_dir), current_dir)
    except Exception as e:
        print(f"Linux update failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def install_update_mac(dmg_path: Path) -> bool:
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
            if platform == "win32" and update_file.suffix == ".zip":
                success = install_update_windows(update_file)
            elif platform.startswith("linux") and (
                update_file.suffix == ".tgz" or suffixes[-2:] == [".tar", ".gz"]
            ):
                success = install_update_linux(update_file)
            elif platform == "darwin" and update_file.suffix == ".dmg":
                success = install_update_mac(update_file)

            if success:
                print("Update installed successfully")
                return True

            print("Update installation failed")
            return False
    except Exception as e:
        print(f"Auto update failed: {e}")
        return False
