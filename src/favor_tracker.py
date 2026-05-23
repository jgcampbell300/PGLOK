"""Favor Tracker UI + logic for Project Gorgon.

First pass: given an NPC and the CDN data files (items.json, npcs.json),
show which items are good gifts based on the NPC's Preferences and the
item's Keywords/Value.

This does NOT yet read per-character current favor; it focuses on
"what should I give this NPC". Character integration can be layered on
later using the Character_* reports that PGLOK already knows how to find.
"""
from __future__ import annotations

import json
import re
import sqlite3
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox

from src.config import config
from src.config.ui_theme import UI_COLORS, UI_ATTRS, apply_theme


DATA_DIR = config.DATA_DIR

FAVOR_DB_FILENAME = "favor_cache.db"
USER_GIFT_DATA_FILENAME = "user_gift_data.json"
FAVOR_GAIN_DATA_FILENAME = "favor_gain_data.json"


def _get_favor_db_path() -> Path:
    return DATA_DIR / FAVOR_DB_FILENAME


# Cache version - bump this when gift computation logic changes to force cache rebuild
_FAVOR_CACHE_VERSION = "3"


def _compute_cdn_hash() -> str:
    """Compute a stable hash of the CDN JSON we care about.

    We hash items.json and npcs.json contents; if either is missing, we
    fall back to an empty hash and skip DB updates.
    """
    to_hash = [DATA_DIR / "items.json", DATA_DIR / "npcs.json"]
    h = hashlib.sha256()
    have_any = False
    for path in to_hash:
        if not path.exists():
            continue
        have_any = True
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                if not chunk:
                    break
                h.update(chunk)
    # Include cache version in hash so code changes invalidate cache
    h.update(_FAVOR_CACHE_VERSION.encode("utf-8"))
    return h.hexdigest() if have_any else ""


def _maybe_update_favor_cache_db(items: Dict[str, "FavorItem"], npcs: List["FavorNpc"]) -> None:
    """Ensure favor_cache.db mirrors the current CDN data and scores.

    This is cheap on normal runs (hash matches, no work) and only does
    real work when the underlying JSON changes, e.g. after a game patch.
    Failures are swallowed so the UI never breaks because of the cache.
    """
    if not items or not npcs:
        return

    cdn_hash = _compute_cdn_hash()
    if not cdn_hash:
        return

    db_path = _get_favor_db_path()
    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return

    try:
        cur = conn.cursor()
        # Basic schema: metadata + raw CDN projection + precomputed scores.
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                key           TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                value         REAL NOT NULL,
                keywords_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS npcs (
                key   TEXT PRIMARY KEY,
                name  TEXT NOT NULL,
                area  TEXT
            );

            CREATE TABLE IF NOT EXISTS npc_prefs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                npc_key       TEXT NOT NULL,
                desire        TEXT NOT NULL,
                pref          REAL NOT NULL,
                keywords_json TEXT NOT NULL,
                FOREIGN KEY(npc_key) REFERENCES npcs(key)
            );

            CREATE TABLE IF NOT EXISTS gift_scores (
                npc_key  TEXT NOT NULL,
                item_key TEXT NOT NULL,
                score    REAL NOT NULL,
                desire   TEXT,
                PRIMARY KEY (npc_key, item_key),
                FOREIGN KEY(npc_key) REFERENCES npcs(key),
                FOREIGN KEY(item_key) REFERENCES items(key)
            );
            """
        )

        # Check existing hash; if unchanged, nothing to do.
        cur.execute("SELECT value FROM metadata WHERE key = 'cdn_hash'")
        row = cur.fetchone()
        if row and row[0] == cdn_hash:
            return

        # Rebuild projected CDN + scores.
        cur.execute("DELETE FROM gift_scores")
        cur.execute("DELETE FROM npc_prefs")
        cur.execute("DELETE FROM npcs")
        cur.execute("DELETE FROM items")

        item_rows = [
            (itm.key, itm.name, float(itm.value), json.dumps(list(itm.keywords), ensure_ascii=False))
            for itm in items.values()
        ]
        cur.executemany(
            "INSERT INTO items (key, name, value, keywords_json) VALUES (?, ?, ?, ?)",
            item_rows,
        )

        npc_rows = [(npc.key, npc.name, npc.area) for npc in npcs]
        cur.executemany(
            "INSERT INTO npcs (key, name, area) VALUES (?, ?, ?)",
            npc_rows,
        )

        pref_rows = []
        score_rows = []
        for npc in npcs:
            for pref in npc.preferences:
                pref_rows.append(
                    (
                        npc.key,
                        pref.desire,
                        float(pref.pref),
                        json.dumps(list(pref.keywords), ensure_ascii=False),
                    )
                )

            # Precompute best gifts for this NPC and persist non-zero scores.
            for item, score, top_pref, actual_favor in compute_best_gifts(npc, items, limit=300):
                score_rows.append(
                    (
                        npc.key,
                        item.key,
                        float(score),
                        top_pref.desire,
                    )
                )

        if pref_rows:
            cur.executemany(
                "INSERT INTO npc_prefs (npc_key, desire, pref, keywords_json) VALUES (?, ?, ?, ?)",
                pref_rows,
            )
        if score_rows:
            cur.executemany(
                "INSERT INTO gift_scores (npc_key, item_key, score, desire) VALUES (?, ?, ?, ?)",
                score_rows,
            )

        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('cdn_hash', ?)",
            (cdn_hash,),
        )
        conn.commit()
    except Exception:
        # Cache is best-effort only.
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


@dataclass
class FavorPreference:
    desire: str  # e.g. "Love", "Like"
    name: str  # e.g. "Green Crystals", "Brass Items"
    keywords: List[str]
    pref: float  # numeric weight from npcs.json


@dataclass
class FavorNpc:
    key: str              # internal NPC key from npcs.json (e.g. "NPC_Arlan")
    name: str             # display name (e.g. "Arlan")
    area: str             # AreaFriendlyName
    preferences: List[FavorPreference]


@dataclass
class FavorItem:
    key: str              # internal item key (e.g. "item_1001")
    name: str
    value: float
    keywords: List[str]
    keyword_weights: Dict[str, float]  # parsed keyword weights (e.g., {"Dirt": 50, "MoldDirt": 50})
    location: str = ""    # last known storage/location hint from Itemizer


def _load_items() -> Dict[str, FavorItem]:
    """Load items.json and return favor-relevant fields.

    We only care about Name, Value, and Keywords.
    """
    items_path = DATA_DIR / "items.json"
    if not items_path.exists():
        return {}

    with items_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    items: Dict[str, FavorItem] = {}
    for key, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        name = str(payload.get("Name") or "").strip()
        if not name:
            continue
        value = payload.get("Value") or 0
        try:
            value_f = float(value)
        except Exception:
            value_f = 0.0
        keywords = payload.get("Keywords") or []
        if not isinstance(keywords, list):
            keywords = []

        # Parse keyword weights from format "keyword=value" (e.g., "bone=500")
        keyword_weights: Dict[str, float] = {}
        keyword_list: List[str] = []
        for kw in keywords:
            kw_str = str(kw)
            keyword_list.append(kw_str)
            # Check if keyword has a weight value (format: "keyword=value")
            if "=" in kw_str:
                try:
                    kw_name, kw_value = kw_str.split("=", 1)
                    keyword_weights[kw_name] = float(kw_value)
                except Exception:
                    # If parsing fails, just store the keyword without weight
                    pass

        # Initialize without a location; we fill that in lazily when needed.
        items[key] = FavorItem(
            key=key,
            name=name,
            value=value_f,
            keywords=keyword_list,
            keyword_weights=keyword_weights,
            location="",
        )
    return items


def _load_npcs() -> List[FavorNpc]:
    """Load npcs.json and extract display name + gift preferences."""
    npcs_path = DATA_DIR / "npcs.json"
    if not npcs_path.exists():
        return []

    with npcs_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    npcs: List[FavorNpc] = []
    for key, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        name = str(payload.get("Name") or "").strip()
        if not name:
            continue

        # Filter out non-NPC entries (objects, signs, etc.)
        # Exclude entries that are clearly not NPCs
        excluded_patterns = [
            "work orders",
            "beehive",
            "lootchest",
            "myconian_gate",
            "bluecrystal",
            "shopgolem",
            "teleportationattendant",
        ]
        name_lower = name.lower()
        if any(pattern in name_lower for pattern in excluded_patterns):
            continue
        area = str(payload.get("AreaFriendlyName") or "").strip()
        prefs_raw = payload.get("Preferences") or []
        preferences: List[FavorPreference] = []
        if isinstance(prefs_raw, list):
            for p in prefs_raw:
                if not isinstance(p, dict):
                    continue
                desire = str(p.get("Desire") or "").strip() or "Unknown"
                pref_name = str(p.get("Name") or "").strip() or ""
                kw_list = p.get("Keywords") or []
                if not isinstance(kw_list, list) or not kw_list:
                    continue
                try:
                    pref_val = float(p.get("Pref") or 0)
                except Exception:
                    pref_val = 0.0
                preferences.append(
                    FavorPreference(
                        desire=desire,
                        name=pref_name,
                        keywords=[str(k) for k in kw_list],
                        pref=pref_val,
                    )
                )
        # Include all NPCs, even those without gift preferences
        npcs.append(FavorNpc(key=key, name=name, area=area, preferences=preferences))

    # Sort NPCs by area then name for nicer dropdown
    npcs.sort(key=lambda n: (n.area.lower(), n.name.lower()))
    return npcs


def _get_user_gift_data_path() -> Path:
    """Get path to user gift data file."""
    return DATA_DIR / USER_GIFT_DATA_FILENAME


def _get_favor_gain_data_path() -> Path:
    """Get path to favor gain data file."""
    return DATA_DIR / FAVOR_GAIN_DATA_FILENAME


def _load_user_gift_data() -> dict:
    """Load user-defined gift preferences from JSON file.

    Returns dict mapping NPC keys to list of preference dicts.
    """
    path = _get_user_gift_data_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_user_gift_data(data: dict) -> bool:
    """Save user-defined gift preferences to JSON file."""
    path = _get_user_gift_data_path()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _load_favor_gain_data() -> dict:
    """Load actual favor gain data from JSON file.

    Returns dict with structure: {npc_key: {item_key: [favor_gains]}}
    where favor_gains is a list of actual favor values gained from gifting.
    """
    path = _get_favor_gain_data_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_favor_gain_data(data: dict) -> bool:
    """Save actual favor gain data to JSON file."""
    path = _get_favor_gain_data_path()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _record_favor_gain(npc_key: str, item_key: str, actual_favor: float, quantity: int = 1, item_value: float = 0.0, keyword_weight: float = 0.0, npc_pref: float = 0.0) -> bool:
    """Record an actual favor gain from gifting an item to an NPC with detailed information."""
    data = _load_favor_gain_data()
    if npc_key not in data:
        data[npc_key] = {}
    if item_key not in data[npc_key]:
        data[npc_key][item_key] = []

    # Store detailed record
    record = {
        "favor_amount": actual_favor,
        "quantity": quantity,
        "favor_per_item": actual_favor / quantity,
        "item_value": item_value,
        "keyword_weight": keyword_weight,
        "npc_pref": npc_pref,
        "timestamp": datetime.now().isoformat()
    }
    data[npc_key][item_key].append(record)
    return _save_favor_gain_data(data)


def _get_average_favor_gain(npc_key: str, item_key: str) -> Optional[float]:
    """Get the average actual favor gain for a specific NPC/item combination."""
    data = _load_favor_gain_data()
    if npc_key not in data or item_key not in data[npc_key]:
        return None
    records = data[npc_key][item_key]
    if not records:
        return None

    # Handle both old format (list of floats) and new format (list of dicts)
    if isinstance(records[0], dict):
        # New format: extract favor_per_item
        favor_values = [r.get("favor_per_item", r.get("favor_amount", 0)) for r in records]
    else:
        # Old format: list of floats
        favor_values = records

    return sum(favor_values) / len(favor_values)


def _get_favor_gift_multiplier(character_name: str) -> float:
    """Get the character's 'Favor Earned From Gifts' multiplier from their report file."""
    pg_base = getattr(config, "PG_BASE", None)
    
    # If PG_BASE not set, try common Project Gorgon locations
    if not pg_base:
        possible_locations = [
            Path.home() / ".config" / "unity3d" / "Elder Game" / "Project Gorgon",
            Path.home() / "Library" / "Application Support" / "unity.Elder Game.Project Gorgon",
        ]
        for loc in possible_locations:
            if loc.exists():
                pg_base = str(loc)
                break
    
    if not pg_base:
        return 1.0

    reports_dir = Path(pg_base) / "Reports"
    if not reports_dir.exists():
        return 1.0

    # Handle character names that might include server info like "Name (Server)"
    clean_name = character_name.split(" (")[0] if " (" in character_name else character_name
    
    # Find the character's report file
    char_files = list(reports_dir.glob(f"Character_{clean_name}_*.json"))
    if not char_files:
        return 1.0

    try:
        with char_files[0].open("r", encoding="utf-8") as f:
            char_data = json.load(f)
    except Exception as e:
        return 1.0

    # Get the NPC_MOD_FAVORFROMGIFTS stat from CurrentStats
    current_stats = char_data.get("CurrentStats", {})
    multiplier = current_stats.get("NPC_MOD_FAVORFROMGIFTS", 1.0)
    
    try:
        return float(multiplier)
    except (ValueError, TypeError):
        return 1.0


def _get_character_favor_for_npc(character_name: str, npc_key: str) -> Optional[dict]:
    """Get the current favor level and XP for a character with an NPC from their report file."""
    pg_base = getattr(config, "PG_BASE", None)
    if not pg_base:
        return None

    reports_dir = Path(pg_base) / "Reports"
    if not reports_dir.exists():
        return None

    # Find the character's report file
    char_files = list(reports_dir.glob(f"Character_{character_name}_*.json"))
    if not char_files:
        return None

    try:
        with char_files[0].open("r", encoding="utf-8") as f:
            char_data = json.load(f)
    except Exception as e:
        return None

    # The actual structure: NPCs -> NPC_Name -> {FavorLevel: "LikeFamily"}
    npcs_data = char_data.get("NPCs", {})
    if not npcs_data:
        return None

    # Try to find the NPC by key or by matching the name
    # NPC keys in the report are like "NPC_WillemFangblade"
    for report_key, npc_info in npcs_data.items():
        if isinstance(npc_info, dict):
            favor_level = npc_info.get("FavorLevel")
            if favor_level:
                # Check if this matches our NPC
                # Remove "NPC_" prefix and compare
                report_name = report_key.replace("NPC_", "").lower()
                if report_name == npc_key.lower() or npc_key.lower() in report_name or report_name in npc_key.lower():
                    return {
                        "level": favor_level,
                        "xp": 0,
                        "xp_to_next": 0,
                    }

    return None


def _get_npc_label_with_favor(npc: FavorNpc, character_name: str) -> str:
    """Generate NPC label with favor level for the character."""
    favor_data = _get_character_favor_for_npc(character_name, npc.key)
    if favor_data:
        level = favor_data["level"]
        return f"{npc.name} ({level})"
    else:
        # Show Favor Unknown if no favor data
        return f"{npc.name} (Favor Unknown)"


def _merge_user_gift_preferences(npcs: List[FavorNpc]) -> List[FavorNpc]:
    """Merge user-defined gift preferences with CDN data.

    User data takes precedence and can add preferences to NPCs that have none.
    """
    user_data = _load_user_gift_data()
    if not user_data:
        return npcs

    npc_map = {npc.key: npc for npc in npcs}

    for npc_key, prefs_list in user_data.items():
        if npc_key not in npc_map:
            continue  # Skip if NPC not in current CDN data

        npc = npc_map[npc_key]
        # Parse user preferences
        user_prefs: List[FavorPreference] = []
        for p in prefs_list:
            if not isinstance(p, dict):
                continue
            desire = str(p.get("Desire") or p.get("desire") or "").strip() or "Like"
            keywords = p.get("Keywords") or p.get("keywords") or []
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
            try:
                pref_val = float(p.get("Pref") or p.get("pref") or 1.0)
            except Exception:
                pref_val = 1.0
            if keywords:
                user_prefs.append(FavorPreference(
                    desire=desire,
                    keywords=[str(k) for k in keywords],
                    pref=pref_val
                ))

        # Replace or add to existing preferences
        if user_prefs:
            npc.preferences = user_prefs

    return list(npc_map.values())


# Some preference keywords are extremely broad (e.g. "Loot") and should not
# by themselves make an item look like a great gift when more specific
# keywords are available on the same preference.
_GENERIC_PREF_KEYWORDS = {"Loot"}


def _match_score(item: FavorItem, pref: FavorPreference) -> Optional[float]:
    """Return a raw favor score for item against one preference, or None.

    This is intentionally simple: we check if any preference keyword is
    present in the item's Keywords list (case-insensitive substring match). If so, we
    estimate favor as:

        score = keyword_weight * pref.pref * desire_multiplier

    where keyword_weight is the weight from the keyword (e.g., "bone=500") or item.value if no weight.
    desire_multiplier is higher for "Love" than for "Like".
    This is an approximation, but it preserves the relative ordering of
    good gifts for a given NPC.
    """
    if not item.keywords:
        return None

    item_kw_lower = {k.lower() for k in item.keywords}

    # Check if any preference keyword matches any item keyword
    matched = False
    matched_kw_weight = None
    for pref_kw in pref.keywords:
        pref_kw_lower = pref_kw.lower()
        for item_kw in item.keywords:
            item_kw_lower_str = item_kw.lower()

            # Check if preference keyword matches item keyword (exact or substring)
            # Also check if it matches the part before "=" in weighted keywords
            kw_match = False
            if "=" in item_kw_lower_str:
                kw_name = item_kw_lower_str.split("=", 1)[0]
                if pref_kw_lower == kw_name or pref_kw_lower in kw_name:
                    kw_match = True
                    try:
                        matched_kw_weight = float(item_kw_lower_str.split("=", 1)[1])
                    except Exception:
                        pass
            elif pref_kw_lower == item_kw_lower_str or pref_kw_lower in item_kw_lower_str:
                kw_match = True

            if kw_match:
                matched = True
                break
        if matched:
            break

    if not matched:
        return None

    desire = pref.desire.lower()
    # Use prefix match so we don't mis-classify descriptive text that happens to contain "love"/"like".
    if desire.startswith("love"):
        desire_mult = 1.0
    elif desire.startswith("like"):
        desire_mult = 0.5
    else:
        desire_mult = 0.25

    # Use keyword weight if available, otherwise fall back to item value
    base_value = matched_kw_weight if matched_kw_weight is not None else item.value
    return max(0.0, base_value) * max(0.0, pref.pref) * desire_mult


def compute_best_gifts(npc: FavorNpc, items: Dict[str, FavorItem], limit: int = 200, character_name: str = None) -> List[Tuple[FavorItem, float, FavorPreference, Optional[float]]]:
    """Return a sorted list of (item, score, top_pref, actual_favor) for the NPC.

    Items are sorted descending by score. Only items that match at least
    one preference are returned. actual_favor is the average actual favor
    gain from gameplay data, or None if no data exists.
    
    If character_name is provided, applies the character's 'Favor Earned From Gifts' multiplier.
    """
    # Get the character's favor gift multiplier
    multiplier = 1.0
    if character_name and character_name != "Any":
        multiplier = _get_favor_gift_multiplier(character_name)
    
    results: List[Tuple[FavorItem, float, FavorPreference, Optional[float]]] = []

    for item in items.values():
        best_score = 0.0
        best_pref: Optional[FavorPreference] = None
        for pref in npc.preferences:
            score = _match_score(item, pref)
            if score is not None and score > best_score:
                best_score = score
                best_pref = pref
        if best_pref is not None and best_score > 0.0:
            # Get actual favor data if available
            actual_favor = _get_average_favor_gain(npc.key, item.key)
            # Apply multiplier to actual favor if available
            if actual_favor is not None:
                actual_favor = actual_favor * multiplier
            results.append((item, best_score, best_pref, actual_favor))

    # Sort by actual favor if available, otherwise by estimated score
    results.sort(key=lambda t: (t[3] if t[3] is not None else t[1]), reverse=True)
    if limit and limit > 0:
        results = results[:limit]
    return results


class FavorTrackerWindow:
    """Simple Favor Tracker window.

    Lets the player choose an NPC and shows high-value gift items based on
    CDN data. This is a read-only helper; it does not modify game data.
    """

    def _ensure_locations_for_items(self, items: List[FavorItem]) -> None:
        """Populate FavorItem.location for a batch of items using Itemizer, once per name.

        This does a single SQL query over the Itemizer DB instead of one lookup per row.
        """
        if not items:
            return
        try:
            from src.itemizer.indexer import get_db_path, ensure_schema

            db_path = get_db_path()
            if not db_path.exists():
                return

            # Figure out which item names still need a location.
            cache = getattr(self, "_location_cache", None)
            pending_names = {
                item.name
                for item in items
                if not getattr(item, "location", "") and (cache is None or item.name not in cache)
            }
            if not pending_names:
                return

            names = sorted(pending_names)
            placeholders = ",".join(["?"] * len(names))

            with sqlite3.connect(db_path) as conn:
                ensure_schema(conn)
                rows = conn.execute(
                    f"""
                    SELECT i.item_name, COALESCE(i.storage_vault, '')
                    FROM items i
                    JOIN reports r ON r.id = i.report_id
                    WHERE i.item_name IN ({placeholders})
                    """,
                    tuple(names),
                ).fetchall()

            name_to_loc: Dict[str, str] = {}
            for name, storage in rows:
                if storage:
                    # Last write wins; any non-empty storage is a valid hint.
                    name_to_loc[str(name)] = str(storage)

            if cache is not None:
                for n in names:
                    cache[n] = name_to_loc.get(n, "")

            for item in items:
                loc = name_to_loc.get(item.name, "")
                if loc:
                    try:
                        item.location = loc
                    except Exception:
                        pass
        except Exception:
            # If anything goes wrong, just leave locations blank.
            return

    def __init__(self, parent):
        self.parent = parent

        # Create window using the central theming + persistence helper when available
        try:
            if hasattr(parent, "create_themed_toplevel"):
                self.window = parent.create_themed_toplevel("favor_tracker", "Favor Tracker")
            else:
                # Fallback: standalone window with persistent geometry
                self.window = tk.Toplevel(parent)
                from src.config.window_state import setup_window as _setup_window
                _setup_window(self.window, "favor_tracker", min_w=720, min_h=480)
        except Exception:
            # Ultimate fallback: basic Toplevel + theming
            self.window = tk.Toplevel(parent)
            self.window.title("Favor Tracker")
            try:
                apply_theme(self.window)
            except Exception:
                pass

        # Per-window always-on-top state
        self.always_on_top_var = tk.BooleanVar(value=False)
        if hasattr(self.parent, "_get_ui_pref"):
            try:
                saved_pin = bool(self.parent._get_ui_pref("favor_tracker_always_on_top", False))
            except Exception:
                saved_pin = False
            self.always_on_top_var.set(saved_pin)
            if saved_pin:
                try:
                    self.window.attributes("-topmost", True)
                except Exception:
                    pass

        self._items: Dict[str, FavorItem] = {}
        self._npcs: List[FavorNpc] = []
        # Cache for computed best gifts per NPC key to avoid recomputing on every refresh
        self._gift_cache: Dict[str, List[Tuple[FavorItem, float, FavorPreference, Optional[float]]]] = {}
        # Cache for item locations so we only hit Itemizer once per item name
        self._location_cache: Dict[str, str] = {}
        # Tree view bookkeeping: map NPC tree node IDs to NPC objects and track which have been populated
        self._tree_npc_nodes: Dict[str, FavorNpc] = {}
        self._tree_built_for_npc = set()

        self.npc_var = tk.StringVar()
        self.npc_search_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.area_var = tk.StringVar(value="All Areas")
        self.area_search_var = tk.StringVar()
        self.character_var = tk.StringVar(value="Any")
        self.character_search_var = tk.StringVar()
        # When enabled, restrict items to those carried by the focused character (inventory + saddle)
        self.inventory_only_var = tk.BooleanVar(value=False)
        # When locked, disable auto-area detection from chat logs
        self.area_lock_var = tk.BooleanVar(value=False)

        self._build_ui()
        # Clear cache to ensure it uses new 4-tuple format
        self._gift_cache.clear()
        self._load_data()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        shell = ttk.Frame(self.window, padding=10, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            header,
            text="Favor Tracker",
            style="App.Header.TLabel",
        ).pack(side="left")

        # Per-window always-on-top toggle
        ttk.Checkbutton(
            header,
            text="Always on Top",
            variable=self.always_on_top_var,
            command=self._toggle_always_on_top,
            style="App.TCheckbutton",
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            header,
            text="Refresh Data",
            command=self._load_data,
            style="App.Secondary.TButton",
        ).pack(side="right")

        ttk.Button(
            header,
            text="Record Favor",
            command=self._open_favor_recorder,
            style="App.Secondary.TButton",
        ).pack(side="right", padx=(0, 6))

        # Training mode toggle
        self.training_mode_var = tk.BooleanVar(value=False)
        self.training_btn = ttk.Checkbutton(
            header,
            text="Training Mode",
            variable=self.training_mode_var,
            command=self._on_training_mode_toggled,
            style="App.TCheckbutton",
        )
        self.training_btn.pack(side="right", padx=(0, 6))

        ttk.Button(
            header,
            text="Edit Gifts",
            command=self._open_gift_editor,
            style="App.Secondary.TButton",
        ).pack(side="right", padx=(0, 6))

        # Area filters (row 1)
        area_row = ttk.Frame(shell, style="App.Panel.TFrame")
        area_row.pack(fill="x", pady=(0, 4))

        ttk.Label(area_row, text="Area:", width=6, style="App.TLabel").pack(side="left")
        self.area_combo = ttk.Combobox(
            area_row,
            textvariable=self.area_var,
            state="readonly",
            width=30,
            style="App.TCombobox",
        )
        self.area_combo.pack(side="left", padx=(0, 4))
        self.area_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_area_filter_changed())

        area_search = ttk.Entry(
            area_row,
            textvariable=self.area_search_var,
            width=18,
            style="App.TEntry",
        )
        area_search.insert(0, "search")
        area_search.pack(side="left", padx=(4, 0))
        area_search.bind("<FocusIn>", lambda _e: area_search.selection_range(0, "end"))
        self.area_search_var.trace_add("write", self._on_area_search_changed)

        # Lock button to disable auto-area detection (on right side of search box)
        lock_button_frame = tk.Frame(area_row, width=24, height=24)
        lock_button_frame.pack(side="left", padx=(4, 0))
        lock_button_frame.pack_propagate(False)  # Prevent frame from shrinking
        
        self.lock_button = tk.Button(
            lock_button_frame,
            text="🔓",
            command=self._toggle_area_lock,
            font=("TkDefaultFont", 14),
            relief="raised",
            bd=1,
            padx=0,
            pady=0,
        )
        self.lock_button.pack(fill="both", expand=True)
        
        # Status label next to lock button
        self.lock_status_label = ttk.Label(
            area_row,
            text="Auto-detecting area & character",
            style="App.Muted.TLabel",
            font=("TkDefaultFont", 8),
        )
        self.lock_status_label.pack(side="left", padx=(4, 0))

        # NPC filters (row 2)
        npc_row = ttk.Frame(shell, style="App.Panel.TFrame")
        npc_row.pack(fill="x", pady=(0, 4))

        ttk.Label(npc_row, text="NPC:", width=6, style="App.TLabel").pack(side="left")
        self.npc_combo = ttk.Combobox(
            npc_row,
            textvariable=self.npc_var,
            state="readonly",
            width=30,
            style="App.TCombobox",
        )
        self.npc_combo.pack(side="left", padx=(0, 4))
        self.npc_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_table())

        npc_search = ttk.Entry(
            npc_row,
            textvariable=self.npc_search_var,
            width=18,
            style="App.TEntry",
        )
        npc_search.insert(0, "search")
        npc_search.pack(side="left", padx=(4, 0))
        npc_search.bind("<FocusIn>", lambda _e: npc_search.selection_range(0, "end"))
        self.npc_search_var.trace_add("write", self._on_npc_search_changed)

        # Character row (row 3)
        char_row = ttk.Frame(shell, style="App.Panel.TFrame")
        char_row.pack(fill="x", pady=(0, 4))

        ttk.Label(char_row, text="Char:", width=6, style="App.TLabel").pack(side="left")
        self.character_combo = ttk.Combobox(
            char_row,
            textvariable=self.character_var,
            state="readonly",
            width=30,
            style="App.TCombobox",
        )
        self.character_combo.pack(side="left", padx=(0, 4))

        char_search = ttk.Entry(
            char_row,
            textvariable=self.character_search_var,
            width=18,
            style="App.TEntry",
        )
        char_search.insert(0, "search")
        char_search.pack(side="left", padx=(4, 0))
        char_search.bind("<FocusIn>", lambda _e: char_search.selection_range(0, "end"))
        self.character_search_var.trace_add("write", self._on_character_search_changed)

        # Item-name filter row (row 4)
        filter_row = ttk.Frame(shell, style="App.Panel.TFrame")
        filter_row.pack(fill="x", pady=(0, 4))

        ttk.Label(filter_row, text="Filter Items:", style="App.TLabel").pack(side="left")
        search_entry = ttk.Entry(
            filter_row,
            textvariable=self.search_var,
            width=30,
            style="App.TEntry",
        )
        search_entry.insert(0, "search")
        search_entry.pack(side="left", padx=(4, 0))
        search_entry.bind("<FocusIn>", lambda _e: search_entry.selection_range(0, "end"))
        self.search_var.trace_add("write", lambda *_: self._refresh_table())

        # Context checkboxes row: restrict to carried items
        context_row = ttk.Frame(shell, style="App.Panel.TFrame")
        context_row.pack(fill="x", pady=(0, 8))

        ttk.Checkbutton(
            context_row,
            text="Only items I'm carrying",
            variable=self.inventory_only_var,
            command=self._on_inventory_only_toggled,
            style="App.TCheckbutton",
        ).pack(side="left", padx=(0, 8))

        # Global rule: quick link to open Itemizer window from Favor Tracker
        if hasattr(self.parent, "open_itemizer_window"):
            ttk.Checkbutton(
                context_row,
                text="Itemizer",
                command=self.parent.open_itemizer_window,
                style="App.TCheckbutton",
            ).pack(side="left", padx=(0, 8))

        # Tabs: Tree view, List view, and Watched Items
        notebook = ttk.Notebook(shell, style="TNotebook")
        notebook.pack(fill="both", expand=True)

        # Tree tab
        tree_tab = ttk.Frame(notebook, style="App.Panel.TFrame")
        notebook.add(tree_tab, text="Tree")

        tree_frame = ttk.Frame(tree_tab, style="App.Card.TFrame")
        tree_frame.pack(fill="both", expand=True)

        self.tree_hierarchy = ttk.Treeview(
            tree_frame,
            columns=("favor", "value", "location"),
            show="tree headings",
            selectmode="browse",
            style="App.Treeview",
        )
        # Left column: character / NPC / Loved / Liked / Item name
        self.tree_hierarchy.heading("#0", text="Name")
        self.tree_hierarchy.column("#0", width=260, anchor="w", stretch=True)

        # Right columns: favor + value + where, right-aligned but allowed to stretch horizontally
        self.tree_hierarchy.heading("favor", text="Est. Favor")
        self.tree_hierarchy.heading("value", text="Value")
        self.tree_hierarchy.heading("location", text="Location")
        self.tree_hierarchy.column("favor", width=110, anchor="center", stretch=True)
        self.tree_hierarchy.column("value", width=80, anchor="center", stretch=True)
        self.tree_hierarchy.column("location", width=180, anchor="center", stretch=True)

        # Scrollbars (vertical + horizontal)
        tree_vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_hierarchy.yview)
        tree_hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_hierarchy.xview)
        self.tree_hierarchy.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)

        # Lazily populate NPC gift details when an NPC node is expanded
        self.tree_hierarchy.bind("<<TreeviewOpen>>", self._on_tree_node_open)

        self.tree_hierarchy.pack(side="top", fill="both", expand=True)
        tree_vsb.pack(side="right", fill="y")
        tree_hsb.pack(side="bottom", fill="x")

        # List tab
        list_tab = ttk.Frame(notebook, style="App.Panel.TFrame")
        notebook.add(list_tab, text="List")

        table_frame = ttk.Frame(list_tab, style="App.Card.TFrame")
        table_frame.pack(fill="both", expand=True)

        columns = ("item", "favor", "actual_favor", "value", "location", "pref", "desire", "keywords")
        self.list_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="App.Treeview",
        )

        self.list_tree.heading("item", text="Item")
        self.list_tree.heading("favor", text="Est. Favor Score")
        self.list_tree.heading("actual_favor", text="Actual Favor")
        self.list_tree.heading("value", text="Value")
        self.list_tree.heading("location", text="Location")
        self.list_tree.heading("pref", text="Match")
        self.list_tree.heading("desire", text="Desire")
        self.list_tree.heading("keywords", text="Matched Keywords")

        self.list_tree.column("item", width=200, anchor="w", stretch=True)
        self.list_tree.column("favor", width=100, anchor="center", stretch=True)
        self.list_tree.column("actual_favor", width=100, anchor="center", stretch=True)
        self.list_tree.column("value", width=70, anchor="center", stretch=True)
        self.list_tree.column("location", width=160, anchor="center", stretch=True)
        self.list_tree.column("pref", width=130, anchor="w")
        self.list_tree.column("desire", width=70, anchor="w")
        self.list_tree.column("keywords", width=230, anchor="w", stretch=True)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.list_tree.yview)
        self.list_tree.configure(yscrollcommand=vsb.set)

        self.list_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Status label pinned to the bottom of the window
        self.status_var = tk.StringVar(value="")
        ttk.Label(shell, textvariable=self.status_var, style="App.Muted.TLabel").pack(
            side="bottom", fill="x", pady=(6, 0), anchor="w"
        )

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _load_data(self) -> None:
        try:
            self._items = _load_items()
            self._npcs = _load_npcs()
            # Merge user-defined gift preferences (overrides CDN data)
            self._npcs = _merge_user_gift_preferences(self._npcs)
            # Invalidate any cached gift computations when data changes
            self._gift_cache.clear()
            # Best-effort: mirror CDN + precomputed scores into SQLite cache.
            _maybe_update_favor_cache_db(self._items, self._npcs)
        except Exception as e:
            messagebox.showerror("Favor Tracker", f"Failed to load data: {e}")
            return

        if not self._items:
            self.status_var.set("items.json not found or empty; run Download Newer Files.")
        elif not self._npcs:
            self.status_var.set("npcs.json not found or has no preferences.")
        else:
            self.status_var.set(
                f"Loaded {len(self._npcs)} NPCs and {len(self._items)} items from CDN data."
            )

        # Populate NPC combo (All + all NPCs)
        character_name = self.character_var.get()
        if character_name and character_name != "Any":
            # Extract character name from label (format: "Name (Server)")
            char_name = character_name.split(" (")[0] if " (" in character_name else character_name
            all_labels = [_get_npc_label_with_favor(n, char_name) for n in self._npcs]
        else:
            # Show Favor Unknown when no character selected
            all_labels = [f"{n.name} (Favor Unknown)" for n in self._npcs]
        self._all_npc_labels = all_labels
        values = ["All"] + all_labels
        self.npc_combo["values"] = values
        # Default to All
        if not self.npc_var.get() or self.npc_var.get() not in values:
            self.npc_var.set("All")

        # Populate Area combo from all known NPC areas
        areas = sorted({n.area for n in self._npcs if getattr(n, "area", "")}, key=str.lower)
        self._all_areas = ["All Areas"] + areas
        if hasattr(self, "area_combo"):
            self.area_combo["values"] = self._all_areas
            if self.area_var.get() not in self._all_areas:
                self.area_var.set("All Areas")

        # Populate character focus combo (Any + known characters from Reports)
        characters = ["Any"]
        pg_base = getattr(config, "PG_BASE", None)
        if pg_base:
            reports_dir = Path(pg_base) / "Reports"
            if reports_dir.exists():
                char_re = re.compile(r"^Character_(?P<name>.+)_(?P<server>[^_]+)\.json$")
                seen = set()
                for path in reports_dir.glob("Character_*.json"):
                    m = char_re.match(path.name)
                    if not m:
                        continue
                    name = m.group("name")
                    server = m.group("server")
                    label = f"{name} ({server})"
                    if label not in seen:
                        seen.add(label)
                        characters.append(label)
                characters.sort(key=lambda s: (s == "Any", s.lower()))

        self.character_combo["values"] = characters
        if not self.character_var.get() or self.character_var.get() not in characters:
            self.character_var.set("Any")
        # Remember full character list for searching
        self._all_characters = characters[:]

        # Auto-sync with current PGLOK context (character + area) if unlocked
        if not self.area_lock_var.get():
            self._apply_current_context_filters()

        self._refresh_table()

    def _apply_current_context_filters(self) -> None:
        """Sync NPC + character filters from the main PGLOK app (area + toon)."""
        if not isinstance(self.parent, object):
            return
        # Use attributes defined on PGLOKApp when available
        area = getattr(self.parent, "current_area", None)
        char = getattr(self.parent, "current_character", None)
        if isinstance(area, tk.StringVar):
            area_val = area.get().strip()
        else:
            area_val = ""
        if isinstance(char, tk.StringVar):
            char_val = char.get().strip()
        else:
            char_val = ""

        # Filter NPC list by area if we know it
        if area_val and hasattr(self, "_all_npc_labels"):
            lowered_area = area_val.lower()
            filtered = [label for label in self._all_npc_labels if lowered_area in label.lower()]
            if filtered:
                values_with_all = ["All"] + filtered
                self.npc_combo["values"] = values_with_all
                if self.npc_var.get() not in values_with_all:
                    self.npc_var.set("All")
            # Try to select matching area in area combo
            if hasattr(self, "area_combo"):
                for value in self.area_combo["values"]:
                    # Try exact match first, then partial match
                    if value.lower() == area_val.lower() or area_val.lower() in value.lower():
                        self.area_var.set(value)
                        break

        # Try to select matching character in combo, if any
        if char_val and self.character_combo is not None:
            for value in self.character_combo["values"]:
                # values look like "Name (Server)"
                if value.lower().startswith(char_val.lower()):
                    self.character_var.set(value)
                    break

    def _open_favor_recorder(self) -> None:
        """Open dialog to record actual favor gain from gifting an item."""
        if not self._npcs or not self._items:
            messagebox.showinfo("Favor Recorder", "No NPC or item data loaded.")
            return

        # Create dialog window
        dialog = tk.Toplevel(self.window)
        dialog.title("Record Favor Gain")
        dialog.geometry("400x300")
        dialog.transient(self.window)
        dialog.grab_set()

        # NPC selection
        ttk.Label(dialog, text="NPC:", style="App.TLabel").pack(pady=(10, 5))
        npc_var = tk.StringVar()
        npc_combo = ttk.Combobox(dialog, textvariable=npc_var, state="readonly", style="App.TCombobox")
        npc_values = [f"{npc.name} ({npc.area})" if npc.area else npc.name for npc in self._npcs]
        npc_combo["values"] = npc_values
        npc_combo.pack(pady=(0, 10), padx=20, fill="x")
        if npc_values:
            npc_combo.current(0)

        # Item selection
        ttk.Label(dialog, text="Item:", style="App.TLabel").pack(pady=(5, 5))
        item_var = tk.StringVar()
        item_combo = ttk.Combobox(dialog, textvariable=item_var, state="readonly", style="App.TCombobox")
        item_values = [item.name for item in self._items.values()]
        item_combo["values"] = sorted(item_values)
        item_combo.pack(pady=(0, 10), padx=20, fill="x")
        if item_values:
            item_combo.current(0)

        # Favor gain input
        ttk.Label(dialog, text="Favor Gained:", style="App.TLabel").pack(pady=(5, 5))
        favor_var = tk.StringVar()
        favor_entry = ttk.Entry(dialog, textvariable=favor_var, style="App.TEntry")
        favor_entry.pack(pady=(0, 10), padx=20, fill="x")

        def on_record():
            npc_name = npc_var.get()
            item_name = item_var.get()
            favor_text = favor_var.get().strip()

            if not npc_name or not item_name or not favor_text:
                messagebox.showerror("Error", "Please fill in all fields.")
                return

            try:
                favor_gain = float(favor_text)
            except ValueError:
                messagebox.showerror("Error", "Favor gain must be a number.")
                return

            # Find NPC key
            npc_key = None
            for npc in self._npcs:
                npc_label = f"{npc.name} ({npc.area})" if npc.area else npc.name
                if npc_label == npc_name:
                    npc_key = npc.key
                    break

            # Find item key
            item_key = None
            for key, item in self._items.items():
                if item.name == item_name:
                    item_key = key
                    break

            if not npc_key or not item_key:
                messagebox.showerror("Error", "Could not find NPC or item.")
                return

            # Record the favor gain
            if _record_favor_gain(npc_key, item_key, favor_gain):
                self.status_var.set(f"Recorded favor gain: {favor_gain} for {item_name} → {npc_name}")
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to save favor gain data.")

        # Buttons
        button_frame = ttk.Frame(dialog, style="App.Panel.TFrame")
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Record", command=on_record, style="App.Primary.TButton").pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy, style="App.Secondary.TButton").pack(side="left", padx=5)

    def record_favor_gain_from_chat(self, npc_name: str, favor_amount: str) -> None:
        """Record a favor gain parsed from chat log (without item name)."""
        try:
            favor_value = float(favor_amount)
        except ValueError:
            return

        # Find NPC key by name
        npc_key = None
        npc_obj = None
        for npc in self._npcs:
            if npc.name.lower() == npc_name.lower():
                npc_key = npc.key
                npc_obj = npc
                break

        if not npc_key:
            return

        # If training mode is on, open popup to select item
        if self.training_mode_var.get():
            success = self._open_training_item_selector(npc_obj, favor_value)
            # Only refresh if recording was successful
            if success:
                self._refresh_table()
        else:
            # Record without item name (use "Unknown" as placeholder) with minimal data
            _record_favor_gain(npc_key, "Unknown", favor_value, 1, 0.0, 0.0, 0.0)
            # Refresh the table to show updated actual favor data
            self._refresh_table()

    def _on_training_mode_toggled(self) -> None:
        """Handle training mode toggle."""
        if self.training_mode_var.get():
            self.status_var.set("Training mode ON - Select items when favor gains are detected")
        else:
            self.status_var.set("Training mode OFF")

    def _open_training_item_selector(self, npc: FavorNpc, favor_amount: float) -> bool:
        """Open a popup dialog to select the item gifted to the NPC during training.

        Returns True if recording was successful, False if cancelled or failed.
        """
        dialog = tk.Toplevel(self.window)
        dialog.title(f"Training Mode - {npc.name}")
        dialog.geometry("500x600")
        dialog.transient(self.window)
        dialog.grab_set()

        # Track whether recording was successful
        recording_success = [False]

        # Container frame
        container = ttk.Frame(dialog, style="App.Panel.TFrame")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Header with favor info
        header_frame = ttk.Frame(container, style="App.Panel.TFrame")
        header_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(header_frame, text=f"Favor Gained: {favor_amount}", style="App.Header.TLabel").pack()
        ttk.Label(header_frame, text=f"NPC: {npc.name}", style="App.TLabel").pack()

        # Search/Item name entry (serves both search and custom item name)
        search_frame = ttk.Frame(container, style="App.Panel.TFrame")
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="Item name:", style="App.TLabel").pack(side="left")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, style="App.TEntry")
        search_entry.pack(side="left", fill="x", expand=True, padx=5)

        # Item list
        list_frame = ttk.Frame(container, style="App.Panel.TFrame")
        list_frame.pack(fill="both", expand=True, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        item_listbox = tk.Listbox(list_frame, height=15, yscrollcommand=scrollbar.set)
        item_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=item_listbox.yview)

        # Get items that match NPC preferences
        results = self._get_gifts_for_npc(npc, limit=200)
        all_items = [(item.name, item, score, pref, actual_favor) for item, score, pref, actual_favor in results]

        # Populate list with all items
        for name, _, _, _, _ in all_items:
            item_listbox.insert(tk.END, name)

        # Search filter function
        def filter_items(*args):
            search_text = search_var.get().lower()
            item_listbox.delete(0, tk.END)
            if search_text:
                for name, _, _, _, _ in all_items:
                    if search_text in name.lower():
                        item_listbox.insert(tk.END, name)
            else:
                # Show all items when search is empty
                for name, _, _, _, _ in all_items:
                    item_listbox.insert(tk.END, name)

        search_var.trace_add("write", filter_items)

        # Bottom frame for quantity and buttons (pinned to bottom)
        bottom_frame = ttk.Frame(dialog, style="App.Panel.TFrame")
        bottom_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        # Quantity input
        quantity_frame = ttk.Frame(bottom_frame, style="App.Panel.TFrame")
        quantity_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(quantity_frame, text="Quantity:", style="App.TLabel").pack(side="left")
        quantity_var = tk.StringVar(value="1")
        quantity_entry = ttk.Entry(quantity_frame, textvariable=quantity_var, width=10, style="App.TEntry")
        quantity_entry.pack(side="left", padx=5)

        # Buttons
        button_frame = ttk.Frame(bottom_frame, style="App.Panel.TFrame")
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Record", command=lambda: self._record_training_favor(npc, favor_amount, item_listbox, quantity_var, search_var, dialog, recording_success), style="App.Primary.TButton").pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy, style="App.Secondary.TButton").pack(side="left", padx=5)

        # Ensure minimum window size
        dialog.minsize(400, 500)

        dialog.wait_window()  # Wait for dialog to close before continuing
        return recording_success[0]

    def _record_training_favor(self, npc: FavorNpc, favor_amount: float, item_listbox, quantity_var, search_var, dialog, recording_success: list) -> None:
        """Record favor gain with specific item and quantity from training mode."""
        typed_name = search_var.get().strip()

        # Use typed name if provided, otherwise use listbox selection
        if typed_name:
            item_name = typed_name
        else:
            selection = item_listbox.curselection()
            if not selection:
                messagebox.showerror("Error", "Please select an item or type an item name")
                return
            item_name = item_listbox.get(selection[0])

        try:
            quantity = int(quantity_var.get())
            if quantity < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Quantity must be a positive integer")
            return

        # Find item key (if item exists in database)
        item_key = None
        for key, item in self._items.items():
            if item.name.lower() == item_name.lower():
                item_key = key
                item_name = item.name  # Use correct casing from database
                break

        # If typed name was used and not found in database, show error with suggestions
        if typed_name and not item_key:
            # Find similar item names for suggestions
            suggestions = []
            item_name_lower = item_name.lower()
            for key, item in self._items.items():
                if item_name_lower in item.name.lower() or item.name.lower() in item_name_lower:
                    suggestions.append(item.name)
            suggestions = sorted(set(suggestions))[:5]  # Top 5 suggestions

            error_msg = f"Item '{item_name}' not found in item database."
            if suggestions:
                error_msg += f"\n\nDid you mean:\n" + "\n".join(f"• {s}" for s in suggestions)
            error_msg += "\n\nPlease select from the list or use the exact item name from the game."
            messagebox.showerror("Item Not Found", error_msg)
            return

        # Record favor gain per item with detailed information
        favor_per_item = favor_amount / quantity

        # Get item details for analysis (if item exists in database)
        item_value = 0.0
        keyword_weight = 0.0
        npc_pref_value = 0.0

        if item_key:
            item_obj = self._items.get(item_key)
            item_value = item_obj.value if item_obj else 0.0

            # Find matching preference to get pref value
            matched_keyword_weight = None
            for pref in npc.preferences:
                for item_kw in item_obj.keywords if item_obj else []:
                    if any(pref_kw.lower() in item_kw.lower() for pref_kw in pref.keywords):
                        npc_pref_value = pref.pref
                        # Extract keyword weight if available
                        if "=" in item_kw:
                            try:
                                matched_keyword_weight = float(item_kw.split("=", 1)[1])
                            except Exception:
                                pass
                        break
                if npc_pref_value > 0:
                    break

            keyword_weight = matched_keyword_weight if matched_keyword_weight is not None else 0.0

        # Use item_key if found, otherwise use custom name as key
        record_key = item_key if item_key else item_name
        _record_favor_gain(npc.key, record_key, favor_per_item, quantity, item_value, keyword_weight, npc_pref_value)

        # Clear gift cache to force recalculation with new actual favor data
        self._gift_cache.clear()

        recording_success[0] = True
        self.status_var.set(f"Recorded training data: {item_name} × {quantity} → {npc.name} ({favor_per_item:.1f} each)")
        dialog.destroy()
        self._refresh_table()

    def _toggle_area_lock(self) -> None:
        """Toggle the area auto-detection lock."""
        current = self.area_lock_var.get()
        self.area_lock_var.set(not current)
        locked = self.area_lock_var.get()

        if locked:
            self.lock_button.configure(text="🔒", font=("TkDefaultFont", 14))
            self.lock_status_label.configure(text="Locked - manual selection")
        else:
            self.lock_button.configure(text="🔓", font=("TkDefaultFont", 14))
            self.lock_status_label.configure(text="Auto-detecting area & character")
            # If unlocked, immediately apply current context
            self._apply_current_context_filters()

    def update_area_from_chat(self, area_name: str) -> None:
        """Called by parent app when chat log detects an area change.

        Only updates if:
        - area_lock is False (unlocked)
        - area_name is different from current
        """
        if not area_name:
            return
        if self.area_lock_var.get():
            self.status_var.set(f"Area '{area_name}' detected but lock is engaged")
            return  # Locked, don't auto-update

        # Update the area filter
        if hasattr(self, "area_combo"):
            for value in self.area_combo["values"]:
                if value.lower() == area_name.lower():
                    if self.area_var.get() != value:
                        self.area_var.set(value)
                        self._on_area_filter_changed()
                        self.status_var.set(f"Area updated to: {value}")
                    return
            self.status_var.set(f"Area '{area_name}' not found in area list")

    def update_character_from_chat(self, character_name: str) -> None:
        """Called by parent app when chat log detects a character login.

        Only updates if:
        - area_lock is False (unlocked)
        - character_name is different from current
        """
        if not character_name:
            return
        if self.area_lock_var.get():
            self.status_var.set(f"Character '{character_name}' detected but lock is engaged")
            return  # Locked, don't auto-update

        # Update the character filter
        if hasattr(self, "character_combo"):
            for value in self.character_combo["values"]:
                if value.lower() == character_name.lower():
                    if self.character_var.get() != value:
                        self.character_var.set(value)
                        self._on_character_search_changed()
                        self.status_var.set(f"Character updated to: {value}")
                    return
            self.status_var.set(f"Character '{character_name}' not found in character list")

    def _on_area_filter_changed(self) -> None:
        """Filter NPC list when area dropdown changes via selection."""
        self._apply_area_filter_from_text(self.area_var.get())

    def _on_area_text_changed(self) -> None:
        """Filter NPC list as the user types in the Area field."""
        self._apply_area_filter_from_text(self.area_var.get())

    def _on_npc_search_changed(self, *_: object) -> None:
        """Filter the NPC dropdown based on the NPC search box."""
        term = self.npc_search_var.get().strip().lower()
        if not hasattr(self, "_all_npc_labels"):
            return
        base = self._all_npc_labels
        if not term:
            labels = base
        else:
            exact = [label for label in base if label.lower() == term]
            prefix = [label for label in base if label.lower().startswith(term) and label not in exact]
            contains = [
                label
                for label in base
                if term in label.lower() and label not in exact and label not in prefix
            ]
            labels = exact + prefix + contains
        values = ["All"] + labels
        self.npc_combo["values"] = values
        if labels:
            best = labels[0]
            if self.npc_var.get() not in values or self.npc_var.get().strip().lower() == "all":
                self.npc_var.set(best)
        else:
            self.npc_var.set("All")
        self._refresh_table()

    def _on_area_search_changed(self, *_: object) -> None:
        """Filter the Area dropdown and NPC list based on the Area search box."""
        if not hasattr(self, "_all_areas"):
            return
        term = self.area_search_var.get().strip().lower()
        base = list(self._all_areas)
        if not base:
            return
        if not term or term == "all areas":
            areas = base
        else:
            real_areas = [a for a in base if a.lower() != "all areas"]
            exact = [a for a in real_areas if a.lower() == term]
            prefix = [a for a in real_areas if a.lower().startswith(term) and a not in exact]
            contains = [
                a
                for a in real_areas
                if term in a.lower() and a not in exact and a not in prefix
            ]
            ordered = exact + prefix + contains
            areas = ["All Areas"] + ordered if ordered else base
        self.area_combo["values"] = areas
        # Choose a sensible selection and then apply NPC filtering
        if len(areas) > 1 and term and areas[0].lower() == "all areas":
            self.area_var.set(areas[1])
        else:
            self.area_var.set(areas[0])
        self._on_area_filter_changed()

    def _on_character_search_changed(self, *_: object) -> None:
        """Filter the Character dropdown based on the Character search box."""
        # Clear cache when character changes since multiplier affects results
        self._gift_cache.clear()
        if not hasattr(self, "_all_characters"):
            return
        term = self.character_search_var.get().strip().lower()
        base = list(self._all_characters)
        if not base:
            return
        any_values = [v for v in base if v.strip().lower() == "any"]
        char_values = [v for v in base if v.strip().lower() != "any"]
        if not term or term == "any":
            ordered = char_values
        else:
            exact = [v for v in char_values if v.lower() == term]
            prefix = [v for v in char_values if v.lower().startswith(term) and v not in exact]
            contains = [
                v
                for v in char_values
                if term in v.lower() and v not in exact and v not in prefix
            ]
            ordered = exact + prefix + contains
        values = any_values + ordered
        self.character_combo["values"] = values
        if len(values) > 1 and (term and values[0].strip().lower() == "any"):
            self.character_var.set(values[1])
        else:
            self.character_var.set(values[0])
        # Character change may affect inventory-only results and NPC labels
        self._gift_cache.clear()
        self._tree_built_for_npc.clear()  # Clear tree cache to force rebuild
        self._refresh_npc_labels()
        self._refresh_table()

    def _refresh_npc_labels(self) -> None:
        """Refresh NPC labels with current favor levels."""
        if not hasattr(self, "_all_npc_labels") or not self._npcs:
            return

        # Get the currently selected NPC's actual name before refresh
        current_label = self.npc_var.get()
        current_npc_name = None
        if current_label and current_label != "All":
            # Extract name from old label format
            current_npc_name = current_label.split(" (")[0]

        character_name = self.character_var.get()
        if character_name and character_name != "Any":
            # Extract character name from label (format: "Name (Server)")
            char_name = character_name.split(" (")[0] if " (" in character_name else character_name
            all_labels = [_get_npc_label_with_favor(n, char_name) for n in self._npcs]
        else:
            # Show Favor Unknown when no character selected
            all_labels = [f"{n.name} (Favor Unknown)" for n in self._npcs]

        self._all_npc_labels = all_labels

        # Update the NPC combo values
        values = ["All"] + all_labels
        self.npc_combo["values"] = values

        # Try to preserve the selection by matching the NPC name
        if current_npc_name:
            # Find the new label for this NPC
            for label in values:
                if label.startswith(current_npc_name + " ("):
                    self.npc_var.set(label)
                    return
        # If we couldn't preserve, select the first NPC instead of All
        if len(values) > 1:
            self.npc_var.set(values[1])
        else:
            self.npc_var.set("All")

    def _apply_area_filter_from_text(self, text: str) -> None:
        if not hasattr(self, "_all_npc_labels"):
            return
        area_label = (text or "").strip()
        if not area_label or area_label.lower() == "all areas":
            values = self._all_npc_labels
        else:
            lowered = area_label.lower()
            # Rank by prefix match in area section, then contains
            def _area_name(label: str) -> str:
                if "(" in label and ")" in label:
                    return label.split("(", 1)[1].rstrip(")").strip().lower()
                return ""
            prefix = [label for label in self._all_npc_labels if _area_name(label).startswith(lowered)]
            contains = [
                label
                for label in self._all_npc_labels
                if lowered in _area_name(label) and label not in prefix
            ]
            values = prefix + contains
        values_with_all = ["All"] + values
        self.npc_combo["values"] = values_with_all
        if values:
            # Keep current selection if still valid; otherwise reset to All.
            if self.npc_var.get() not in values_with_all:
                self.npc_var.set("All")
        else:
            self.npc_var.set("All")
        self._refresh_table()

    def _on_npc_text_changed(self) -> None:
        """Filter the NPC dropdown as the user types in the NPC field."""
        term = self.npc_var.get().strip().lower()
        if not hasattr(self, "_all_npc_labels"):
            return
        if not term or term == "all":
            filtered = ["All"] + self._all_npc_labels
        else:
            base = self._all_npc_labels
            # Rank results: prefix matches first, then contains matches
            prefix = [label for label in base if label.lower().startswith(term)]
            contains = [
                label
                for label in base
                if term in label.lower() and label not in prefix
            ]
            labels = prefix + contains
            filtered = ["All"] + labels
        self.npc_combo["values"] = filtered
        # Keep current selection if it still matches, otherwise pick first after All.
        if self.npc_var.get() not in filtered:
            if len(filtered) > 1:
                self.npc_var.set(filtered[1])
            else:
                self.npc_var.set("All")

    def _on_character_text_changed(self) -> None:
        """Filter the Character dropdown as the user types in the Character field."""
        term = self.character_var.get().strip().lower()
        values = list(self.character_combo["values"]) if self.character_combo is not None else []
        if not values:
            return
        base = values
        base_any = [v for v in base if v.strip().lower() == "any"]
        base_chars = [v for v in base if v.strip().lower() != "any"]
        if not term or term == "any":
            filtered = base_any + base_chars
        else:
            # Rank characters: prefix matches first, then contains
            prefix = [label for label in base_chars if label.lower().startswith(term)]
            contains = [
                label
                for label in base_chars
                if term in label.lower() and label not in prefix
            ]
            labels = prefix + contains
            filtered = base_any + labels
        self.character_combo["values"] = filtered
        if self.character_var.get() not in filtered:
            # Prefer first real character if available, otherwise Any.
            if len(filtered) > 1:
                self.character_var.set(filtered[1])
            else:
                self.character_var.set(filtered[0])
        # Character change may affect inventory-only results
        self._gift_cache.clear()
        self._refresh_table()

    def _get_selected_npc(self) -> Optional[FavorNpc]:
        label = self.npc_var.get().strip()
        if not label or label.lower() == "all":
            return None
        # Match by name prefix before " (" if present
        name = label.split(" (")[0]
        for npc in self._npcs:
            if npc.name == name:
                return npc
        return None

    def _get_gifts_for_npc(self, npc: FavorNpc, limit: int = 300):
        """Return best gifts for an NPC, optionally restricted to carried items.

        When inventory-only mode is enabled and we can resolve a character
        + server, we intersect the global CDN items with the items that
        character is currently carrying in their personal inventory or
        saddle, using the Itemizer index.
        """
        character_name = self.character_var.get()
        key = (npc.key, character_name)  # Include character in cache key
        cached = self._gift_cache.get(key)
        if cached is None:
            # Default to computing in-memory.
            base_items = self._items

            # Optionally restrict to carried items for the focused character
            if getattr(self, "inventory_only_var", None) is not None and self.inventory_only_var.get():
                try:
                    from src.itemizer import get_carried_item_names

                    # Character combo values look like "Name (Server)" or "Any"
                    label = self.character_var.get().strip()
                    if label and label.lower() != "any":
                        name = label.split(" (")[0]
                        server = ""
                        if "(" in label and ")" in label:
                            try:
                                server = label.split("(", 1)[1].rstrip(")")
                            except Exception:
                                server = ""
                        carried_names = get_carried_item_names(server=server, character=name)
                        if carried_names:
                            lowered = {n.lower() for n in carried_names}
                            base_items = {
                                key: item
                                for key, item in self._items.items()
                                if item.name.lower() in lowered
                            }
                except Exception:
                    # If anything goes wrong, fall back to all items
                    base_items = self._items

            # Try to use the SQLite favor cache when inventory-only is OFF and DB is available.
            results: Optional[List[Tuple[FavorItem, float, FavorPreference]]] = None
            if not (getattr(self, "inventory_only_var", None) is not None and self.inventory_only_var.get()):
                try:
                    db_path = _get_favor_db_path()
                    if db_path.exists():
                        conn = sqlite3.connect(db_path)
                        try:
                            cur = conn.cursor()
                            cur.execute(
                                """
                                SELECT g.item_key, g.score, g.desire
                                FROM gift_scores g
                                WHERE g.npc_key = ?
                                ORDER BY g.score DESC
                                LIMIT ?
                                """,
                                (key, int(limit)),
                            )
                            rows = cur.fetchall()
                            tmp: List[Tuple[FavorItem, float, FavorPreference, Optional[float]]] = []
                            for item_key, score, desire in rows:
                                item = self._items.get(item_key)
                                if not item:
                                    continue
                                # Recreate a minimal FavorPreference to display desire text.
                                pref = FavorPreference(desire=desire or "", keywords=[], pref=0.0)
                                tmp.append((item, float(score), pref, None))
                            if tmp:
                                results = tmp
                        finally:
                            conn.close()
                except Exception:
                    results = None

            # Fallback: compute on the fly using current items view.
            if results is None:
                character_name = self.character_var.get()
                results = compute_best_gifts(npc, base_items, limit=limit, character_name=character_name)

            cached = results
            self._gift_cache[key] = cached
        return cached

    def _on_inventory_only_toggled(self) -> None:
        """Handler when "Only items I'm carrying" is toggled."""
        # Changing this affects which items are eligible; clear caches and refresh.
        self._gift_cache.clear()
        if hasattr(self, "_location_cache"):
            self._location_cache.clear()
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Refresh the flat list view and the tree view."""
        # --- List view (per-NPC gifts) ---
        if hasattr(self, "list_tree"):
            for item_id in self.list_tree.get_children():
                self.list_tree.delete(item_id)

        npc = self._get_selected_npc()
        if npc is None:
            self.status_var.set("Select an NPC to see gift suggestions.")
            # Still refresh tree to reflect filters, even if no NPC selected
            self._refresh_tree_view()
            return

        # Check if NPC has no gift preferences
        if not npc.preferences:
            self.status_var.set(f"⚠ No gift data available for {npc.name}.")
            # Still refresh tree to show the NPC in the hierarchy
            self._refresh_tree_view()
            return

        results = self._get_gifts_for_npc(npc, limit=300)
        term = self.search_var.get().strip().lower()

        # Preload locations for any items that don't have one yet, in a single DB hit.
        try:
            missing_items = [item for item, _score, _pref, _actual_favor in results if not getattr(item, "location", "")]
        except Exception:
            missing_items = []
        if missing_items:
            self._ensure_locations_for_items(missing_items)

        shown = 0
        for item, score, pref, actual_favor in results:
            if term and term not in item.name.lower():
                continue

            # Figure out which keywords actually matched, for display.
            matched_kw = [k for k in pref.keywords if k in item.keywords]
            matched_text = ", ".join(matched_kw) if matched_kw else ", ".join(pref.keywords)

            # Use cached location if populated.
            location = getattr(item, "location", "")

            if hasattr(self, "list_tree"):
                # Use actual favor in score column if available
                display_score = f"{actual_favor:,.1f}" if actual_favor is not None else f"{score:,.1f} (est)"
                self.list_tree.insert(
                    "",
                    "end",
                    values=(
                        item.name,
                        display_score,
                        f"{actual_favor:,.1f}" if actual_favor is not None else "N/A",
                        f"{item.value:,.1f}",
                        location,
                        pref.name if hasattr(pref, "name") else ", ".join(pref.keywords),
                        pref.desire,
                        matched_text,
                    ),
                )
                shown += 1

        self.status_var.set(
            f"Showing {shown} gift suggestions for {npc.name}. Higher scores are generally better gifts."
        )

        # --- Tree view (Character -> NPCs -> Loved/Liked -> Items) ---
        self._refresh_tree_view()

    def _refresh_tree_view(self) -> None:
        """Rebuild the hierarchical view for the current filters.

        Root: selected character (or "Any")
          - NPC (for each NPC currently visible in the NPC dropdown)
            - Loved
              - Items
            - Liked
              - Items
        """
        if not hasattr(self, "tree_hierarchy"):
            return

        # Clear existing tree
        for item_id in self.tree_hierarchy.get_children():
            self.tree_hierarchy.delete(item_id)

        # Root node: current character focus
        char_label = self.character_var.get().strip() or "Any"
        root_id = self.tree_hierarchy.insert("", "end", text=char_label, open=True)

        # By default, only show the currently selected NPC to keep things fast.
        # If "All" or nothing is selected, show all visible NPCs filtered by area.
        selected_label = self.npc_var.get().strip()
        if selected_label and selected_label.lower() != "all":
            visible_labels = [selected_label]
        else:
            # Get area-filtered labels using NPC area property
            area_label = self.area_var.get().strip()
            if area_label and area_label.lower() != "all areas":
                # Filter by area using NPC objects
                filtered_npcs = [npc for npc in self._npcs if npc.area and area_label.lower() in npc.area.lower()]
                character_name = self.character_var.get()
                if character_name and character_name != "Any":
                    char_name = character_name.split(" (")[0] if " (" in character_name else character_name
                    visible_labels = [_get_npc_label_with_favor(npc, char_name) for npc in filtered_npcs]
                else:
                    visible_labels = [f"{npc.name} (Favor Unknown)" for npc in filtered_npcs]
            else:
                # Show all NPCs
                visible_labels = [
                    label
                    for label in (list(self.npc_combo["values"]) if self.npc_combo is not None else [])
                    if label.strip().lower() != "all"
                ]
        if not visible_labels:
            return

        # Map labels back to FavorNpc objects
        npcs_by_name = {n.name: n for n in self._npcs}

        for label in visible_labels:
            name = label.split(" (")[0]
            npc = npcs_by_name.get(name)
            if npc is None:
                continue

            # Use favor label format with current character
            character_name = self.character_var.get()
            if character_name and character_name != "Any":
                char_name = character_name.split(" (")[0] if " (" in character_name else character_name
                npc_text = _get_npc_label_with_favor(npc, char_name)
            else:
                npc_text = f"{npc.name} (Favor Unknown)"
            npc_id = self.tree_hierarchy.insert(root_id, "end", text=npc_text, open=False)

            # Use the same cached gift computation the table uses (limit for performance)
            results = self._get_gifts_for_npc(npc, limit=120)

            # If NPC has no gift preferences, show a message
            if not npc.preferences:
                self.tree_hierarchy.insert(npc_id, "end", text="⚠ No gift data available", open=False)
                continue

            # Preload locations for any items we may show, in a single DB hit.
            try:
                missing_items = [item for item, _score, _pref, _actual_favor in results if not getattr(item, "location", "")]
            except Exception:
                missing_items = []
            if missing_items:
                self._ensure_locations_for_items(missing_items)

            # Group items by preference name
            pref_groups: dict[str, list[tuple[FavorItem, float, FavorPreference, Optional[float]]]] = {}
            for item, score, pref, actual_favor in results:
                desire = (pref.desire or "").lower()
                # Only include Loved/Liked items
                if not (desire.startswith("love") or desire.startswith("like")):
                    continue

                # Create preference label (e.g., "Loves Green Crystals", "Likes Brass Items")
                pref_name = pref.name if hasattr(pref, "name") else ", ".join(pref.keywords)
                if desire.startswith("love"):
                    pref_label = f"Loves {pref_name}"
                else:
                    pref_label = f"Likes {pref_name}"

                if pref_label not in pref_groups:
                    pref_groups[pref_label] = []
                pref_groups[pref_label].append((item, score, pref, actual_favor))

            # Create tree nodes for each preference group
            for pref_label, items in pref_groups.items():
                pref_id = self.tree_hierarchy.insert(npc_id, "end", text=f"- {pref_label}", open=False)

                for item, score, pref, actual_favor in items:
                    # Display item with actual favor if available, otherwise estimated
                    if actual_favor is not None:
                        item_text = f"-- {item.name} ({actual_favor:,.1f} XP)"
                    else:
                        item_text = f"-- {item.name} ({score:,.1f} XP est)"
                    self.tree_hierarchy.insert(
                        pref_id,
                        "end",
                        text=item_text,
                    )

    def _on_tree_node_open(self, _event) -> None:
        """Treeview open handler (currently unused; tree is fully built)."""
        # Placeholder for future lazy-loading logic
        return

    def _toggle_always_on_top(self) -> None:
        """Toggle always-on-top state for this favor tracker window."""
        enabled = bool(self.always_on_top_var.get())
        try:
            self.window.attributes("-topmost", enabled)
        except Exception:
            pass
        # Persist preference via parent app when available
        if hasattr(self.parent, "_set_ui_pref"):
            try:
                self.parent._set_ui_pref("favor_tracker_always_on_top", enabled)
            except Exception:
                pass

    def focus(self) -> None:
        self.window.lift()
        self.window.focus_force()

    def _open_gift_editor(self) -> None:
        """Open a dialog to manually edit gift preferences for the selected NPC."""
        npc = self._get_selected_npc()
        if npc is None:
            messagebox.showinfo("Edit Gifts", "Please select an NPC first.")
            return

        # Create editor window
        editor = tk.Toplevel(self.window)
        editor.title(f"Edit Gift Preferences - {npc.name}")
        editor.geometry("500x400")
        editor.transient(self.window)
        editor.grab_set()
        apply_theme(editor)

        shell = ttk.Frame(editor, padding=10, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        # Instructions
        ttk.Label(
            shell,
            text=f"Enter gift keywords for {npc.name}",
            style="App.Header.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            shell,
            text="Format: keyword1, keyword2, keyword3 (e.g., 'Red', 'Magic', 'Sword')",
            font=("TkDefaultFont", 9),
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        # Current preferences display
        ttk.Label(shell, text="Current Preferences:", style="App.TLabel").pack(anchor="w", pady=(0, 4))

        prefs_text = tk.Text(shell, height=6, wrap="word", state="normal")
        prefs_text.pack(fill="both", expand=True, pady=(0, 8))

        if npc.preferences:
            for pref in npc.preferences:
                line = f"[{pref.desire}] {', '.join(pref.keywords)}\n"
                prefs_text.insert("end", line)
        else:
            prefs_text.insert("end", "(No preferences set)\n")
        prefs_text.configure(state="disabled")

        # New preference entry
        ttk.Label(shell, text="Add New Preference:", style="App.TLabel").pack(anchor="w", pady=(0, 4))

        entry_frame = ttk.Frame(shell, style="App.Panel.TFrame")
        entry_frame.pack(fill="x", pady=(0, 8))

        desire_var = tk.StringVar(value="Like")
        ttk.Combobox(
            entry_frame,
            textvariable=desire_var,
            values=["Love", "Like", "Neutral"],
            width=10,
            state="readonly",
            style="App.TCombobox",
        ).pack(side="left", padx=(0, 4))

        keywords_var = tk.StringVar()
        ttk.Entry(
            entry_frame,
            textvariable=keywords_var,
            width=35,
            style="App.TEntry",
        ).pack(side="left", fill="x", expand=True)

        def add_preference():
            keywords = [k.strip() for k in keywords_var.get().split(",") if k.strip()]
            if not keywords:
                messagebox.showwarning("Edit Gifts", "Please enter at least one keyword.")
                return

            desire = desire_var.get()

            # Load existing user data
            user_data = _load_user_gift_data()

            # Add or update this NPC's preferences
            if npc.key not in user_data:
                user_data[npc.key] = []

            user_data[npc.key].append({
                "Desire": desire,
                "Keywords": keywords,
                "Pref": 1.0,
            })

            # Save
            if _save_user_gift_data(user_data):
                messagebox.showinfo("Edit Gifts", f"Added {desire} preference for {npc.name}.")
                keywords_var.set("")
                # Refresh the display
                self._load_data()
                self._refresh_table()
            else:
                messagebox.showerror("Edit Gifts", "Failed to save preference.")

        def clear_preferences():
            if not messagebox.askyesno("Edit Gifts", f"Clear all custom preferences for {npc.name}?"):
                return

            user_data = _load_user_gift_data()
            if npc.key in user_data:
                del user_data[npc.key]

            if _save_user_gift_data(user_data):
                messagebox.showinfo("Edit Gifts", f"Cleared preferences for {npc.name}.")
                self._load_data()
                self._refresh_table()
                editor.destroy()
            else:
                messagebox.showerror("Edit Gifts", "Failed to clear preferences.")

        # Buttons
        btn_frame = ttk.Frame(shell, style="App.Panel.TFrame")
        btn_frame.pack(fill="x", pady=(8, 0))

        ttk.Button(
            btn_frame,
            text="Add Preference",
            command=add_preference,
            style="App.Primary.TButton",
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            btn_frame,
            text="Clear All",
            command=clear_preferences,
            style="App.Secondary.TButton",
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            btn_frame,
            text="Close",
            command=editor.destroy,
            style="App.Secondary.TButton",
        ).pack(side="right")
