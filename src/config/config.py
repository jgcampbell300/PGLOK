from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = SRC_DIR / "config"
DATA_DIR = SRC_DIR / "data"

PG_BASE = None
CHAT_DIR = None


def set_pg_base(pg_base):
    global PG_BASE, CHAT_DIR, CDN_DOWNLOAD_DIR

    if pg_base is None:
        PG_BASE = None
        CHAT_DIR = None
    else:
        PG_BASE = Path(pg_base)
        CHAT_DIR = PG_BASE / "ChatLogs"

    CDN_DOWNLOAD_DIR = DATA_DIR

# Get the files needed
CDN_BASE_URL = "https://cdn.projectgorgon.com/v461/data/" #projectgorgon files available
CDN_DOWNLOAD_DIR = DATA_DIR #Download Directory
CDN_FILE_EXTENSION = ".json" #Extentions to download from cdn
