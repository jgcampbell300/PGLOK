# data_acquisition.py
import os
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config.config import CDN_BASE_URL, CDN_FILE_EXTENSION, CDN_DOWNLOAD_DIR


def download_file(url, download_dir):
    """Saves the file from the link to the specified directory."""
    # Ensure download directory exists
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    # Extract filename from URL and create a safe path
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        return  # Skip invalid links

    filepath = os.path.join(download_dir, filename)

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
        print(f"Found {len(file_links)} files to download.")
        for link in file_links:
            download_file(link, CDN_DOWNLOAD_DIR)
    else:
        print("No files found or unable to retrieve links.")


if __name__ == "__main__":
    main()

