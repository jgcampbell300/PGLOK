from pathlib import Path
import os

import src.config.config as config


GAME_DIR_NAME = "Project Gorgon"
COMPANY_NAME = "Elder Game"


def _looks_like_pg_user_config(path):
    if not path or not path.is_dir():
        return False
    lower_parts = [part.lower() for part in path.parts]
    if path.name != GAME_DIR_NAME:
        return False
    if "elder game".lower() in lower_parts:
        return True
    # macOS Unity convention: ~/Library/Application Support/unity.Elder Game.Project Gorgon
    return "unity.elder game.project gorgon" in str(path).lower()


def _unity_roots():
    home = Path.home()
    return (
        # Linux
        home / ".config" / "unity3d",
        # Windows
        home / "AppData" / "LocalLow",
        Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" if os.environ.get("USERPROFILE") else None,
        # macOS
        home / "Library" / "Application Support",
    )


def _candidate_game_paths_from_os_defaults():
    candidates = []
    home = Path.home()

    # Linux
    candidates.append(home / ".config" / "unity3d" / COMPANY_NAME / GAME_DIR_NAME)
    # Windows
    candidates.append(home / "AppData" / "LocalLow" / COMPANY_NAME / GAME_DIR_NAME)
    if os.environ.get("USERPROFILE"):
        candidates.append(Path(os.environ["USERPROFILE"]) / "AppData" / "LocalLow" / COMPANY_NAME / GAME_DIR_NAME)
    # macOS common variants
    candidates.append(home / "Library" / "Application Support" / "unity.Elder Game.Project Gorgon")
    candidates.append(home / "Library" / "Application Support" / COMPANY_NAME / GAME_DIR_NAME)

    return [path for path in candidates if path is not None]


def _dedupe_paths(paths):
    seen = set()
    unique_paths = []
    for path in paths:
        normalized = str(path.resolve(strict=False))
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(path)
    return unique_paths


def _find_directory_from_unity_roots():
    search_roots = [path for path in _unity_roots() if path and path.is_dir()]
    if not search_roots:
        search_roots = [Path.home()]

    matches = []
    for root in search_roots:
        print(f"Searching for Project Gorgon config under: {root}")
        for path in root.rglob(GAME_DIR_NAME):
            if _looks_like_pg_user_config(path):
                matches.append(path)

        # macOS Unity single-folder naming
        for path in root.rglob("unity.Elder Game.Project Gorgon"):
            if path.is_dir():
                matches.append(path)

    if not matches:
        return None
    # Prefer explicit Elder Game parent naming when present
    elder_game_matches = [path for path in matches if path.parent.name == COMPANY_NAME]
    if elder_game_matches:
        return elder_game_matches[0]
    return matches[0]


def find_pg():
    default_candidates = _dedupe_paths(_candidate_game_paths_from_os_defaults())
    for candidate in default_candidates:
        if _looks_like_pg_user_config(candidate) or candidate.is_dir():
            print(f"Found path from OS default location: [{candidate}]")
            return candidate

    found_path = _find_directory_from_unity_roots()
    if found_path:
        print(f"Found path via recursive search: [{found_path}]")
    else:
        print(f"Could not find path: [{COMPANY_NAME}/{GAME_DIR_NAME}]")
    return found_path


def initialize_pg_base(force=False):
    if config.PG_BASE is not None and not force:
        return config.PG_BASE

    found_path = find_pg()
    config.set_pg_base(found_path)
    return found_path
