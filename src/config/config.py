# config.py
from pathlib import Path

# __file__ refers to the current script's path
# .resolve() ensures it is an absolute path
BASE_DIR = Path(__file__).resolve().parent
# BASE_PG_DIR = "Set by locate_PG.py

# Creating safe subdirectories
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'

# Get the files needed
CDN_BASE_URL = "https://cdn.projectgorgon.com/v461/data/" #projectgorgon files available
CDN_DOWNLOAD_DIR = DATA_DIR #Download Directory
CDN_FILE_EXTENSION = ".json" #Extentions to download from cdn

