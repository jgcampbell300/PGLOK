from __future__ import annotations

from collections import deque
from email.utils import formatdate, parsedate_to_datetime
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


WIKI_ROOT = "https://wiki.projectgorgon.com"
WIKI_API = f"{WIKI_ROOT}/w/api.php"
IMAGES_ROOT = f"{WIKI_ROOT}/w/images/"
MARKED_RE = re.compile(r".*\.(?:jpe?g)$", re.IGNORECASE)
IMG_LINK_RE = re.compile(r"""href=["'](?P<href>/w/images/(?!thumb/)[^"'<> ]+\.(?:jpe?g))["']""", re.IGNORECASE)
HREF_RE = re.compile(r"""href=["'](?P<href>[^"']+)["']""", re.IGNORECASE)
NEXT_LINK_RE = re.compile(r"""<a[^>]+class=["'][^"']*mw-nextlink[^"']*["'][^>]+href=["'](?P<href>[^"']+)["']""", re.IGNORECASE)
REQUEST_HEADERS = {
    "User-Agent": "PGLOK/1.0 (+https://github.com/jgcampbell300/PGLOK)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _is_marked_map_filename(name: str):
    lowered = str(name).lower()
    if not MARKED_RE.search(lowered):
        return False
    if "old" in lowered:
        return False
    if "unmarked" in lowered:
        return False
    return ("marked" in lowered and "map" in lowered)


def _normalize_wiki_url(url: str):
    text = str(url).strip()
    if text.startswith("http://wiki.projectgorgon.com/"):
        return "https://wiki.projectgorgon.com/" + text[len("http://wiki.projectgorgon.com/") :]
    return text


def _fetch_marked_map_links_from_api():
    found = {}
    continuation = {}
    while True:
        params = {
            "action": "query",
            "format": "json",
            "list": "allimages",
            "ailimit": "500",
            "aiprop": "url",
        }
        params.update(continuation)
        url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=40) as resp:
            import json
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))

        items = payload.get("query", {}).get("allimages", [])
        for item in items:
            name = str(item.get("name") or "").strip()
            file_url = _normalize_wiki_url(str(item.get("url") or "").strip())
            if not name or not file_url:
                continue
            if _is_marked_map_filename(name):
                found[name] = file_url

        cont = payload.get("continue")
        if not isinstance(cont, dict):
            break
        continuation = {k: v for k, v in cont.items() if k != "continue"}
        if not continuation:
            break

    return sorted(found.items(), key=lambda item: item[0].lower())


def _fetch_marked_map_links_from_images_root(max_pages=3000):
    found = {}
    visited = set()
    queue = deque([IMAGES_ROOT])
    pages = 0

    while queue and pages < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            req = urllib.request.Request(url, headers=REQUEST_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_type = str(resp.headers.get("Content-Type", "")).lower()
                body = resp.read()
        except Exception:
            continue

        pages += 1
        if "text/html" not in content_type:
            continue

        html = body.decode("utf-8", errors="replace")
        for match in HREF_RE.finditer(html):
            href = match.group("href").strip()
            if not href:
                continue
            target = urllib.parse.urljoin(url, href)
            if not target.startswith(IMAGES_ROOT):
                continue

            parsed = urllib.parse.urlparse(target)
            path = parsed.path
            if "/thumb/" in path:
                continue

            if path.endswith("/"):
                if target not in visited:
                    queue.append(target)
                continue

            file_name = Path(path).name
            if file_name.lower().endswith((".jpg", ".jpeg")) and _is_marked_map_filename(file_name):
                found[file_name] = _normalize_wiki_url(target)

    return sorted(found.items(), key=lambda item: item[0].lower())


def _fetch_marked_map_links_from_special_list():
    found = {}
    visited = set()
    next_url = f"{WIKI_ROOT}/w/index.php?title=Special:ListFiles&limit=200"

    while next_url and next_url not in visited:
        visited.add(next_url)
        req = urllib.request.Request(next_url, headers=REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        for match in IMG_LINK_RE.finditer(html):
            href = match.group("href")
            file_url = _normalize_wiki_url(urllib.parse.urljoin(WIKI_ROOT, href))
            name = Path(urllib.parse.urlparse(file_url).path).name
            if _is_marked_map_filename(name):
                found[name] = file_url

        next_match = NEXT_LINK_RE.search(html)
        if next_match:
            href = next_match.group("href")
            next_url = urllib.parse.urljoin(WIKI_ROOT, href)
        else:
            next_url = None

    return sorted(found.items(), key=lambda item: item[0].lower())


def _safe_filename(name: str):
    # Keep it readable but filesystem-safe.
    text = name.replace("/", "_").replace("\\", "_").strip()
    return text or "UnnamedMarkedMap.jpg"


def _download_if_changed(file_url: str, out_path: Path):
    headers = dict(REQUEST_HEADERS)
    if out_path.exists():
        try:
            mtime = out_path.stat().st_mtime
            headers["If-Modified-Since"] = formatdate(mtime, usegmt=True)
        except OSError:
            pass

    req = urllib.request.Request(file_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            last_modified = resp.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return "skipped"
        raise

    if out_path.exists():
        try:
            if out_path.read_bytes() == data:
                return "skipped"
        except OSError:
            pass

    out_path.write_bytes(data)
    if last_modified:
        try:
            dt = parsedate_to_datetime(last_modified)
            if dt is not None:
                ts = dt.timestamp()
                os.utime(out_path, (ts, ts))
        except Exception:
            pass
    return "downloaded"


def update_marked_maps(dest_dir: Path):
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    merged = {}
    sources_used = []

    try:
        api_items = _fetch_marked_map_links_from_api()
        if api_items:
            merged.update({name: url for name, url in api_items})
            sources_used.append("api")
    except Exception:
        pass

    try:
        root_items = _fetch_marked_map_links_from_images_root()
        if root_items:
            merged.update({name: url for name, url in root_items})
            sources_used.append("images_root")
    except Exception:
        pass

    try:
        list_items = _fetch_marked_map_links_from_special_list()
        if list_items:
            merged.update({name: url for name, url in list_items})
            sources_used.append("special_list")
    except Exception:
        pass

    images = sorted(merged.items(), key=lambda item: item[0].lower())
    source = "+".join(sources_used) if sources_used else "none"
    downloaded = 0
    skipped = 0
    failed = 0

    for name, file_url in images:
        fname = _safe_filename(name)
        out_path = dest / fname
        try:
            result = _download_if_changed(file_url, out_path)
            if result == "downloaded":
                downloaded += 1
            else:
                skipped += 1
        except Exception:
            failed += 1

    return {
        "found": len(images),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "source": source,
        "destination": str(dest),
    }
