# data_acquisition.py
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config.config import CDN_BASE_URL, CDN_FILE_EXTENSION, CDN_DOWNLOAD_DIR


def get_local_filepath(url, download_dir):
    """Builds a local file path from a remote URL."""
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        return None
    return os.path.join(download_dir, filename)


def get_remote_metadata(url):
    """Fetches lightweight remote metadata used to compare freshness."""
    try:
        response = requests.head(url, allow_redirects=True, timeout=15)
        if response.status_code == 405:
            response = requests.get(url, stream=True, timeout=15)
        response.raise_for_status()

        last_modified = response.headers.get("Last-Modified")
        content_length = response.headers.get("Content-Length")

        remote_last_modified = None
        if last_modified:
            remote_last_modified = parsedate_to_datetime(last_modified)
            if remote_last_modified.tzinfo is None:
                remote_last_modified = remote_last_modified.replace(tzinfo=timezone.utc)

        remote_size = int(content_length) if content_length and content_length.isdigit() else None
        return remote_last_modified, remote_size
    except requests.exceptions.RequestException:
        return None, None
    finally:
        if 'response' in locals():
            response.close()


def should_download_file(url, download_dir):
    """Returns True when remote file is missing locally or appears newer."""
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
        return False, "unable to determine remote freshness"

    return False, "already up to date"


def download_file(url, download_dir):
    """Saves the file from the link to the specified directory."""
    # Ensure download directory exists
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    # Extract filename from URL and create a safe path
    filepath = get_local_filepath(url, download_dir)
    if filepath is None:
        return  # Skip invalid links
    filename = os.path.basename(filepath)

    print(f"Downloading: {url} to {filepath}")
    try:
        # Use 'stream=True' for large files to be memory efficient
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Check for bad responses

        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # Filter out keep-alive chunks
                    f.write(chunk)
        print(f"Successfully downloaded: {filename}")

    except requests.exceptions.RequestException as e:
        print(f"Failed to download {url}: {e}")


def get_download_links(base_url, extensions):
    """Retrieves links to specific file types from the page."""
    response = requests.get(base_url)
    if response.status_code != 200:
        print(f"Failed to retrieve the page. Status code: {response.status_code}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        # Join relative URLs with the base URL
        full_url = urljoin(base_url, href)

        # Check if the URL ends with a desired file extension
        if full_url.lower().endswith(extensions):
            links.append(full_url)

    return links

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
