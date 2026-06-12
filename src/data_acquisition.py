# data_acquisition.py
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from src.config.config import CDN_BASE_URL, CDN_FILE_EXTENSION, CDN_DOWNLOAD_DIR


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def get_local_filepath(url, download_dir):
    """Build a local file path from a remote URL."""
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        return None
    return os.path.join(download_dir, filename)


def _open_url(url, method="GET", timeout=15):
    request = Request(
        url,
        method=method,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    return urlopen(request, timeout=timeout)


def get_remote_metadata(url):
    """Fetch lightweight remote metadata used to compare freshness."""
    response = None
    try:
        try:
            response = _open_url(url, method="HEAD", timeout=15)
        except HTTPError as exc:
            if exc.code != 405:
                raise
            response = _open_url(url, method="GET", timeout=15)

        headers = response.headers
        last_modified = headers.get("Last-Modified")
        content_length = headers.get("Content-Length")

        remote_last_modified = None
        if last_modified:
            remote_last_modified = parsedate_to_datetime(last_modified)
            if remote_last_modified.tzinfo is None:
                remote_last_modified = remote_last_modified.replace(tzinfo=timezone.utc)

        remote_size = int(content_length) if content_length and content_length.isdigit() else None
        return remote_last_modified, remote_size
    except (HTTPError, URLError, OSError):
        return None, None
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def should_download_file(url, download_dir):
    """Return True when remote file is missing locally or appears newer."""
    filepath = get_local_filepath(url, download_dir)
    if filepath is None:
        return False, "invalid file link"

    if not os.path.exists(filepath):
        return True, "new file"

    remote_last_modified, remote_size = get_remote_metadata(url)

    if remote_last_modified:
        local_mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=timezone.utc)
        if remote_last_modified > local_mtime:
            return True, "remote file is newer"

    if remote_size is not None:
        local_size = os.path.getsize(filepath)
        if remote_size != local_size:
            return True, "file size changed"

    if remote_last_modified is None and remote_size is None:
        return True, "unable to determine remote freshness; downloading anyway"

    return False, "already up to date"


def download_file(url, download_dir):
    """Save the file from the link to the specified directory."""
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    filepath = get_local_filepath(url, download_dir)
    if filepath is None:
        return

    filename = os.path.basename(filepath)

    print(f"Downloading: {url} to {filepath}")
    response = None
    try:
        response = _open_url(url, method="GET", timeout=30)
        with open(filepath, "wb") as file_handle:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                file_handle.write(chunk)
        print(f"Successfully downloaded: {filename}")
    except (HTTPError, URLError, OSError) as exc:
        print(f"Failed to download {url}: {exc}")
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def get_download_links(base_url, extensions):
    """Retrieve links to specific file types from the page."""
    response = None
    try:
        response = _open_url(base_url, method="GET", timeout=15)
        if getattr(response, "status", 200) != 200:
            print(f"Failed to retrieve the page. Status code: {getattr(response, 'status', 'unknown')}")
            return []

        html = response.read().decode("utf-8", errors="replace")
        parser = _LinkCollector()
        parser.feed(html)

        links = []
        for href in parser.links:
            full_url = urljoin(base_url, href)
            if full_url.lower().endswith(extensions):
                links.append(full_url)

        return links
    except (HTTPError, URLError, OSError) as exc:
        print(f"Failed to retrieve the page: {exc}")
        return []
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def main():
    print(f"Starting download process from {CDN_BASE_URL}")
    file_links = get_download_links(CDN_BASE_URL, CDN_FILE_EXTENSION)

    if file_links:
        print(f"Found {len(file_links)} files on remote site.")
        downloaded_count = 0
        skipped_count = 0
        for link in file_links:
            should_download, reason = should_download_file(link, CDN_DOWNLOAD_DIR)
            if should_download:
                print(f"Will download {link} ({reason}).")
                download_file(link, CDN_DOWNLOAD_DIR)
                downloaded_count += 1
            else:
                print(f"Skipping {link} ({reason}).")
                skipped_count += 1
        print(f"Download complete. Downloaded: {downloaded_count}, skipped: {skipped_count}")
    else:
        print("No files found or unable to retrieve links.")


if __name__ == "__main__":
    main()
