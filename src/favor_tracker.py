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
    except Exception as e:
        print(f"Error saving favor gain data: {e}")
        import traceback
        traceback.print_exc()
        return False


def _get_custom_preferences_path() -> Path:
    """Get path to custom gift preferences file."""
    return DATA_DIR / "custom_gift_preferences.json"


# ------------------------------------------------------------------
# Simple persistent estimates derived from recorded base favor gains.
# These are updated when the app records new base-format entries and
# used to improve scoring for items with little keyword data.
# ------------------------------------------------------------------

def _get_estimates_path() -> Path:
    return DATA_DIR / "favor_item_estimates.json"


# ------------------------------------------------------------------
# Publishing diagnostics and logging
# ------------------------------------------------------------------
def _get_publish_log_path() -> Path:
    return DATA_DIR / "communications_publish.log"


def _log_publish_event(message: str, level: str = "INFO") -> None:
    """Append a timestamped publish diagnostic to the log file.

    This is best-effort and will not raise on failure.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = _get_publish_log_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} [{level}] {message}\n")
    except Exception:
        # Avoid noisy failures — logging must never crash the app
        pass


def _load_estimates() -> dict:
    path = _get_estimates_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_estimates(data: dict) -> bool:
    path = _get_estimates_path()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _update_item_estimate(npc_key: str, item_key: str) -> None:
    """Update persistent base-favor estimate for npc/item using EMA.

    Uses the latest recorded sample with stored_as=='base' and applies an
    exponential moving average (EMA) to the previously-stored estimate.
    The smoothing factor alpha may be configured via config.FAVOR_ESTIMATE_ALPHA
    (default 0.2). If no previous estimate exists, the sample becomes the
    initial estimate.
    """
    try:
        data = _load_favor_gain_data()
        npc_records = data.get(npc_key, {}) if isinstance(data, dict) else {}
        records = npc_records.get(item_key) or []
        if not records:
            return

        # Find the most recent 'base' record (we only use the latest sample
        # for incremental EMA updates).
        sample = None
        for r in reversed(records):
            if isinstance(r, dict) and r.get("stored_as") == "base":
                try:
                    sample = float(r.get("favor_per_item", r.get("favor_amount", 0)))
                    break
                except Exception:
                    continue
        if sample is None:
            return

        # Load existing estimates and existing value for this npc/item
        estimates = _load_estimates()
        old_val = None
        if isinstance(estimates.get(npc_key), dict):
            old_val = estimates[npc_key].get(item_key)

        # Get alpha from config or default; clamp to [0,1]
        try:
            alpha = float(getattr(config, "FAVOR_ESTIMATE_ALPHA", 0.2))
        except Exception:
            alpha = 0.2
        alpha = max(0.0, min(1.0, alpha))

        # Compute new estimate via EMA
        if old_val is None:
            new_est = sample
        else:
            try:
                old_f = float(old_val)
                new_est = alpha * sample + (1.0 - alpha) * old_f
            except Exception:
                new_est = sample

        if npc_key not in estimates or not isinstance(estimates[npc_key], dict):
            estimates[npc_key] = {}
        estimates[npc_key][item_key] = new_est
        _save_estimates(estimates)
    except Exception:
        return


def _recalculate_all_estimates(self) -> None:
    """Recompute estimates from all stored 'base' favor records and persist them."""
    try:
        data = _load_favor_gain_data()
        if not isinstance(data, dict):
            return
        estimates = {}
        for npc_key, items in data.items():
            if not isinstance(items, dict):
                continue
            for item_key, records in items.items():
                if not isinstance(records, list):
                    continue
                base_vals = []
                for r in records:
                    if isinstance(r, dict) and r.get("stored_as") == "base":
                        try:
                            per = float(r.get("favor_per_item", r.get("favor_amount", 0)))
                            base_vals.append(per)
                        except Exception:
                            continue
                if base_vals:
                    estimates.setdefault(npc_key, {})[item_key] = sum(base_vals) / len(base_vals)
        _save_estimates(estimates)
        # Clear gift cache and refresh UI if window exists
        try:
            self._gift_cache.clear()
            self._refresh_table()
        except Exception:
            pass
        try:
            if getattr(self, 'status_var', None):
                self.status_var.set(f"Recalculated estimates for {sum(len(v) for v in estimates.values())} items")
        except Exception:
            pass
        try:
            messagebox.showinfo("Recalculate Estimates", "Recalculation complete.")
        except Exception:
            pass
    except Exception:
        try:
            messagebox.showerror("Recalculate Estimates", "Failed to recalculate estimates")
        except Exception:
            pass


def _load_custom_preferences() -> dict:
    """Load custom gift preferences from JSON file."""
    path = _get_custom_preferences_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_custom_preferences(data: dict) -> bool:
    """Save custom gift preferences to JSON file."""
    path = _get_custom_preferences_path()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _record_favor_gain(npc_key: str, item_key: str, actual_favor: float, quantity: int = 1, item_value: float = 0.0, keyword_weight: float = 0.0, npc_pref: float = 0.0, stored_as: str = "actual") -> bool:
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
        "stored_as": stored_as,
        "timestamp": datetime.now().isoformat()
    }
    data[npc_key][item_key].append(record)
    ok = _save_favor_gain_data(data)
    # If we stored a 'base' record, update persistent estimates for this item
    try:
        if ok and stored_as == "base":
            try:
                _update_item_estimate(npc_key, item_key)
            except Exception:
                pass
    except Exception:
        pass

    # Publish new favor record to communications pglok-data channel if available
    try:
        # Try to locate main app via Tk default root (root.app set in pglok)
        try:
            import tkinter as _tk
            _root = getattr(_tk, '_default_root', None)
        except Exception:
            _root = None
        app = getattr(_root, 'app', None) if _root is not None else None
        if app:
            try:
                favor_data = {
                    "npc_key": npc_key,
                    "item_key": item_key,
                    "favor_amount": float(record.get("favor_per_item", record.get("favor_amount", 0.0))),
                    "quantity": int(record.get("quantity", 1)),
                    "item_value": float(record.get("item_value", 0.0)),
                    "keyword_weight": float(record.get("keyword_weight", 0.0)),
                    "npc_pref": float(record.get("npc_pref", 0.0)),
                    "stored_as": stored_as,
                    "timestamp": record.get("timestamp")
                }
                # Also include npc/item display names if available from CDN cache on the app
                try:
                    ftw = getattr(app, 'favor_tracker_window', None)
                    items = ftw._items if ftw and getattr(ftw, '_items', None) else None
                    if items and isinstance(items, dict) and item_key in items:
                        favor_data["item"] = items[item_key].name
                except Exception:
                    pass
                try:
                    ftw = getattr(app, 'favor_tracker_window', None)
                    npcs = ftw._npcs if ftw and getattr(ftw, '_npcs', None) else None
                    if npcs and isinstance(npcs, list):
                        for n in npcs:
                            if getattr(n, 'key', None) == npc_key:
                                favor_data["npc"] = getattr(n, 'name', npc_key)
                                break
                except Exception:
                    pass

                published = False
                # Primary path: use communications_window.publish_instance_data when available
                try:
                    if getattr(app, 'communications_window', None):
                        try:
                            published = app.communications_window.publish_instance_data("favor", favor_data)
                            _log_publish_event(f"Attempt via communications_window -> {published}")
                        except Exception as e:
                            _log_publish_event(f"Error via communications_window -> {e}", level="ERROR")
                except Exception as e:
                    _log_publish_event(f"Favor publish via communications_window error: {e}", level="ERROR")

                # Fallback: if communications window exists but no publisher, try creating a DataPublisher
                if not published:
                    try:
                        comm = getattr(app, 'communications_window', None)
                        if comm and getattr(comm, 'mqtt_client', None) and getattr(comm.mqtt_client, 'connected', False):
                            from src.communications.data_publisher import DataPublisher
                            dp = DataPublisher(comm.mqtt_client)
                            published = dp.publish_data_to_channel("pglok-data", "favor", favor_data)
                            _log_publish_event(f"Attempt via DataPublisher (existing mqtt_client) -> {published}")
                    except Exception as e:
                        _log_publish_event(f"Favor fallback publish error (existing mqtt_client): {e}", level="ERROR")

                # Final fallback: attempt a transient publish (non-blocking) if MQTT enabled
                if not published:
                    try:
                        import src.config.mqtt_config as mqtt_config
                        if mqtt_config.MQTT_ENABLED and mqtt_config.MQTT_DATA_SHARING_ENABLED:
                            # Create a temporary client, connect, publish, then disconnect
                            from src.communications.mqtt_client import MqttClient
                            from src.communications.data_publisher import DataPublisher
                            temp_client = MqttClient(favor_data.get('npc_key', 'pglok'))
                            ok_conn = temp_client.connect()
                            if ok_conn:
                                dp = DataPublisher(temp_client)
                                published = dp.publish_data_to_channel("pglok-data", "favor", favor_data)
                                _log_publish_event(f"Attempt via transient client -> {published}")
                                try:
                                    temp_client.disconnect()
                                except Exception:
                                    pass
                    except Exception as e:
                        _log_publish_event(f"Favor transient publish error: {e}", level="ERROR")

                if not published:
                    _log_publish_event("Favor publish failed or communications unavailable", level="WARN")
                    # On-screen notification for non-technical users
                    try:
                        # Try to notify via Favor Tracker status bar when available
                        ftw = getattr(app, 'favor_tracker_window', None)
                        prev = None
                        if ftw and getattr(ftw, 'status_var', None):
                            try:
                                prev = ftw.status_var.get()
                                ftw.status_var.set("Failed to publish favor data to communications")
                                try:
                                    if getattr(ftw, 'window', None):
                                        ftw.window.after(5000, lambda: ftw.status_var.set(prev))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        # Also show a modal warning to make it obvious
                        try:
                            from tkinter import messagebox
                            parent = getattr(ftw, 'window', None) if ftw and getattr(ftw, 'window', None) else None
                            messagebox.showwarning("Communications", "Failed to publish favor data to pglok-data. Check Communications window or logs.", parent=parent)
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception as e:
                _log_publish_event(f"Error preparing favor publish: {e}", level="ERROR")
    except Exception as e:
        _log_publish_event(f"Favor publish top-level error: {e}", level="ERROR")

    return ok


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


# Simple cache for loaded character report JSON to avoid repeated file reads.
_character_report_cache: Dict[str, dict] = {}

def _load_character_report(character_name: str) -> Optional[dict]:
    """Load and cache a character's report JSON, returning parsed data or None.

    Caches by the label used in the UI (e.g., "Name (Server)") so repeated
    requests for many NPCs don't re-read the same file.
    """
    if not character_name:
        return None
    # Use the clean name portion for file lookup
    clean_name = character_name.split(" (")[0] if " (" in character_name else character_name
    if clean_name in _character_report_cache:
        return _character_report_cache[clean_name]

    pg_base = getattr(config, "PG_BASE", None)
    if not pg_base:
        # Try common Project Gorgon locations as fallback
        possible_locations = [
            Path.home() / ".config" / "unity3d" / "Elder Game" / "Project Gorgon",
            Path.home() / "Library" / "Application Support" / "unity.Elder Game.Project Gorgon",
        ]
        for loc in possible_locations:
            if loc.exists():
                pg_base = str(loc)
                break
    if not pg_base:
        return None

    reports_dir = Path(pg_base) / "Reports"
    if not reports_dir.exists():
        return None

    char_files = list(reports_dir.glob(f"Character_{clean_name}_*.json"))
    if not char_files:
        return None

    try:
        with char_files[0].open("r", encoding="utf-8") as f:
            char_data = json.load(f)
            _character_report_cache[clean_name] = char_data
            return char_data
    except Exception:
        return None


def _get_character_favor_for_npc(character_name: str, npc_key: str) -> Optional[dict]:
    """Get the current favor level and XP for a character with an NPC from their report file."""
    char_data = _load_character_report(character_name)
    if not char_data:
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

# Keywords that commonly indicate metadata, skill/recipe/book entries, or
# structured descriptors rather than actual item categories. When an item's
# keyword contains these markers we treat it as 'metadata' and avoid matching
# it from broad preference keywords unless the preference explicitly targets
# that metadata.
_METADATA_KEYWORDS = {":", "skill", "recipe", "book", "tome", "text", "manual", "guide", "scroll"}


def _desire_multiplier(desire: str) -> float:
    """Return numeric multiplier for a preference desire string."""
    if not desire:
        return 0.25
    d = desire.lower()
    if d.startswith("love"):
        return 1.0
    if d.startswith("like"):
        return 0.5
    return 0.25


def _match_score(item: FavorItem, pref: FavorPreference) -> Optional[float]:
    """Return a raw favor score for item against one preference, or None.

    Matching rules updated to avoid false-positives from structured metadata
    keywords (e.g. "sword: parry 8" in books/recipes). Metadata-like item
    keywords are ignored for broad preference keywords unless the preference
    explicitly references the same metadata token.
    """
    if not item.keywords:
        return None

    # Check if any preference keyword matches any item keyword
    matched = False
    matched_kw_weight = None
    for pref_kw in pref.keywords:
        pref_kw_lower = pref_kw.lower()
        for item_kw in item.keywords:
            item_kw_lower_str = item_kw.lower()

            # Treat weighted keywords (keyword=value) specially: match on the
            # left-hand side as before and capture weight.
            kw_match = False
            if "=" in item_kw_lower_str:
                kw_name = item_kw_lower_str.split("=", 1)[0]
                # If item keyword appears metadata-like (contains ':' or metadata words)
                # avoid matching by substring; require exact or left-token match.
                if any(mk in kw_name for mk in _METADATA_KEYWORDS) and \
                   ":" not in pref_kw_lower and not any(mk in pref_kw_lower for mk in _METADATA_KEYWORDS):
                    # Skip metadata-like keyword for broad prefs
                    continue
                if pref_kw_lower == kw_name or pref_kw_lower in kw_name:
                    kw_match = True
                    try:
                        matched_kw_weight = float(item_kw_lower_str.split("=", 1)[1])
                    except Exception:
                        pass

            else:
                # If item keyword looks like structured metadata (contains ':' or metadata words)
                # and the preference does not explicitly target metadata, skip loose substring matching.
                if (":" in item_kw_lower_str or any(mk in item_kw_lower_str for mk in _METADATA_KEYWORDS)) and \
                   (":" not in pref_kw_lower and not any(mk in pref_kw_lower for mk in _METADATA_KEYWORDS)):
                    # Only allow a match if the preference exactly equals the token before ':'
                    if ":" in item_kw_lower_str:
                        left = item_kw_lower_str.split(":", 1)[0]
                        if pref_kw_lower == left:
                            kw_match = True
                    # Otherwise skip
                else:
                    # Use whole-word matching where reasonable to avoid substring hits
                    try:
                        if pref_kw_lower == item_kw_lower_str or re.search(r"\\b" + re.escape(pref_kw_lower) + r"\\b", item_kw_lower_str):
                            kw_match = True
                    except re.error:
                        # Fallback to simple substring if regex fails
                        if pref_kw_lower == item_kw_lower_str or pref_kw_lower in item_kw_lower_str:
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


def _build_keyword_index(items: Dict[str, FavorItem]) -> Dict[str, List[FavorItem]]:
    """Build an index mapping lowercase item keyword strings to lists of FavorItem.

    Also indexes the token before '=' for weighted keywords so searches like
    'bone' will match 'bone=500'. This index is much smaller than the items
    list and speeds up preference -> item candidate lookup.
    """
    index: Dict[str, List[FavorItem]] = {}
    for item in items.values():
        for kw in item.keywords:
            k = str(kw).lower()
            index.setdefault(k, []).append(item)
            if "=" in k:
                base = k.split("=", 1)[0]
                index.setdefault(base, []).append(item)
    return index


def compute_best_gifts(npc: FavorNpc, items: Dict[str, FavorItem], limit: int = 200, character_name: str = None, keyword_index: Optional[Dict[str, List[FavorItem]]] = None) -> List[Tuple[FavorItem, float, FavorPreference, Optional[float]]]:
    """Return a sorted list of (item, score, top_pref, actual_favor) for the NPC.

    Optimized: when a keyword_index is provided, only candidate items that
    match preference keywords are evaluated. Favor gain records are loaded
    once per call to avoid repeated JSON disk reads.
    """
    # Get the character's favor gift multiplier
    multiplier = 1.0
    if character_name and character_name != "Any":
        multiplier = _get_favor_gift_multiplier(character_name)

    results: List[Tuple[FavorItem, float, FavorPreference, Optional[float]]] = []

    # Load favor gain data once (avoid per-item JSON loads)
    favor_data = _load_favor_gain_data()
    npc_favor_records = favor_data.get(npc.key, {}) if isinstance(favor_data, dict) else {}

    # If no preferences, still return items with recorded favor
    if not npc.preferences:
        # Only include items that have recorded favor for this NPC
        for item_key, records in npc_favor_records.items():
            if item_key == "Unknown":
                continue
            avg_favor = None
            try:
                if isinstance(records, list) and records:
                    # Compute per-record actual favor taking into account whether the
                    # stored value is 'base' (needs multiplier) or already 'actual'.
                    if isinstance(records[0], dict):
                        vals = []
                        for r in records:
                            per = r.get("favor_per_item", r.get("favor_amount", 0))
                            stored_as = r.get("stored_as")
                            try:
                                per_f = float(per)
                            except Exception:
                                continue
                            if stored_as == "base":
                                vals.append(per_f * multiplier)
                            else:
                                # Treat missing stored_as as 'actual' for backward
                                # compatibility with older records
                                vals.append(per_f)
                        favor_values = vals
                    else:
                        # Old format: list of floats assumed to be actual favor
                        favor_values = records
                    if favor_values:
                        avg_favor = sum(favor_values) / len(favor_values)
            except Exception:
                continue
            if avg_favor is not None:
                item = items.get(item_key)
                if not item:
                    item = FavorItem(key=item_key, name=item_key, value=0.0, keywords=[], keyword_weights={}, location="")
                results.append((item, 0.0, None, avg_favor))
        results.sort(key=lambda t: t[3] if t[3] is not None else 0.0, reverse=True)
        return results[:limit] if limit and limit > 0 else results

    # Build keyword index locally if not provided. This is cheap and much smaller
    # than scanning every item for every preference.
    local_index = keyword_index if keyword_index is not None else _build_keyword_index(items)

    # Collect candidate items by matching preference keywords against the
    # index keys (substring match against keyword strings, which is fast since
    # index keys are distinct keywords, not per-item).
    candidate_items: Dict[str, FavorItem] = {}
    for pref in npc.preferences:
        for pref_kw in pref.keywords:
            pk = str(pref_kw).lower()
            # Iterate index keys and check substring match; number of distinct
            # keywords is typically much smaller than number of items.
            for ik, item_list in local_index.items():
                if pk in ik:
                    for itm in item_list:
                        candidate_items[itm.key] = itm

    # Evaluate candidates
    # Load per-item base estimates for this NPC (if any)
    estimates = _load_estimates()
    npc_estimates = estimates.get(npc.key, {}) if isinstance(estimates, dict) else {}

    for item in candidate_items.values():
        best_score = 0.0
        best_pref: Optional[FavorPreference] = None
        for pref in npc.preferences:
            score = _match_score(item, pref)
            if score is not None and score > best_score:
                best_score = score
                best_pref = pref
        # If we have an empirically observed base favor estimate for this item,
        # use it to produce an alternate score that reflects real-world results
        try:
            est_base = None
            if item.key in npc_estimates:
                try:
                    est_base = float(npc_estimates[item.key])
                except Exception:
                    est_base = None
            if est_base is not None and best_pref is not None:
                # Compute desire multiplier like _match_score does
                desire_mult = _desire_multiplier(best_pref.desire)
                # Estimate-based score uses avg base favor * pref weight * desire multiplier
                est_score = max(0.0, est_base) * max(0.0, best_pref.pref) * desire_mult
                if est_score > best_score:
                    best_score = est_score
        except Exception:
            pass
        # Compute actual favor if available
        actual_favor = None
        records = npc_favor_records.get(item.key)
        if records:
            try:
                if isinstance(records[0], dict):
                    vals = []
                    for r in records:
                        per = r.get("favor_per_item", r.get("favor_amount", 0))
                        stored_as = r.get("stored_as")
                        try:
                            per_f = float(per)
                        except Exception:
                            continue
                        if stored_as == "base":
                            vals.append(per_f * multiplier)
                        else:
                            # Missing stored_as treated as 'actual' for backward compatibility
                            vals.append(per_f)
                    favor_values = vals
                else:
                    # Old format: list of floats assumed to be actual favor
                    favor_values = records
                if favor_values:
                    actual_favor = (sum(favor_values) / len(favor_values))
            except Exception:
                actual_favor = None

        if (best_pref is not None and best_score > 0.0) or actual_favor is not None:
            results.append((item, best_score, best_pref, actual_favor))

    # Include items that have favor data but weren't in candidate set
    for item_key, records in npc_favor_records.items():
        if item_key == "Unknown":
            continue
        if any(item.key == item_key for item, _, _, _ in results):
            continue
        avg_favor = None
        try:
            if isinstance(records[0], dict):
                vals = []
                for r in records:
                    per = r.get("favor_per_item", r.get("favor_amount", 0))
                    stored_as = r.get("stored_as")
                    try:
                        per_f = float(per)
                    except Exception:
                        continue
                    if stored_as == "base":
                        vals.append(per_f * multiplier)
                    else:
                        vals.append(per_f)
                favor_values = vals
            else:
                favor_values = records
            if favor_values:
                avg_favor = (sum(favor_values) / len(favor_values))
        except Exception:
            continue
        if avg_favor is not None:
            item = items.get(item_key)
            if not item:
                item = FavorItem(key=item_key, name=item_key, value=0.0, keywords=[], keyword_weights={}, location="")
            results.append((item, 0.0, None, avg_favor))

    # If too few candidate results, supplement with highest-value items so the
    # user sees a more complete list (e.g., many cooking ingredients). Aim to
    # show at least DESIRED_MIN_ITEMS entries when possible.
    DESIRED_MIN_ITEMS = 25
    try:
        desired_min = DESIRED_MIN_ITEMS if (not limit or limit <= 0) else min(DESIRED_MIN_ITEMS, limit)
    except Exception:
        desired_min = DESIRED_MIN_ITEMS

    if len(results) < desired_min:
        present = {item.key for item, _, _, _ in results}
        # Get remaining items sorted by value descending
        remaining = sorted((itm for itm in items.values() if itm.key not in present), key=lambda it: getattr(it, 'value', 0.0), reverse=True)
        for itm in remaining[: max(0, desired_min - len(results))]:
            results.append((itm, 0.0, None, None))

    # Sort by actual favor if available, otherwise by estimated score; if neither,
    # fall back to item.value so high-value gifts appear.
    def _sort_key(t):
        item, score, pref, actual = t
        if actual is not None:
            return actual
        if score is not None and score > 0.0:
            return score
        return getattr(item, 'value', 0.0)

    results.sort(key=_sort_key, reverse=True)
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
        # In-memory keyword index for fast preference -> item lookups (built on load)
        self._keyword_index: Optional[Dict[str, List[FavorItem]]] = None
        # Track expanded tree nodes for persistence
        self._expanded_nodes: set = set()
        # Tree view bookkeeping: map NPC tree node IDs to NPC objects and track which have been populated
        self._tree_npc_nodes: Dict[str, FavorNpc] = {}
        self._tree_built_for_npc = set()
        # Load custom gift preferences
        self._custom_preferences = _load_custom_preferences()

        self.npc_var = tk.StringVar()
        self.npc_search_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.area_var = tk.StringVar(value="All Areas")
        self.area_search_var = tk.StringVar()
        self.character_var = tk.StringVar(value="Any")
        self.character_search_var = tk.StringVar()
        # Display favor bonus percent for selected character
        self.favor_bonus_var = tk.StringVar(value="Bonus: 0%")
        # Update bonus display when character selection changes
        try:
            self.character_var.trace_add("write", lambda *_: self._update_favor_bonus_display())
        except Exception:
            pass
        # When enabled, restrict items to those carried by the focused character (inventory + saddle)
        self.inventory_only_var = tk.BooleanVar(value=False)
        # When locked, disable auto-area detection from chat logs
        self.area_lock_var = tk.BooleanVar(value=False)

        self._build_ui()
        # Clear cache to ensure it uses new 4-tuple format
        self._gift_cache.clear()
        self._load_data()

        # Listen to parent current_area changes (if available) to keep in sync
        try:
            parent_area = getattr(self.parent, 'current_area', None)
            if parent_area is not None and hasattr(parent_area, 'trace_add'):
                # trace_add returns an identifier in newer Tk; store for potential cleanup
                try:
                    self._parent_area_trace = parent_area.trace_add('write', lambda *_: self._on_parent_area_changed())
                except Exception:
                    # Older Tk versions may not return id; ignore
                    parent_area.trace_add('write', lambda *_: self._on_parent_area_changed())
        except Exception:
            pass

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

        # Recalculate base estimates button (manual trigger)
        try:
            self.recalc_estimates_btn = ttk.Button(
                area_row,
                text="Recalculate Base Estimates",
                command=self._recalculate_all_estimates,
                style="App.Secondary.TButton",
            )
            # Place to the right of the status label
            self.recalc_estimates_btn.pack(side="left", padx=(8, 0))
        except Exception:
            pass

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
        # Show favor bonus for selected character
        try:
            self.character_combo.bind("<<ComboboxSelected>>", lambda _e: (self._on_character_selected(), self._refresh_table()))
        except Exception:
            pass

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
        # Place favor bonus label to the right of the search box
        try:
            ttk.Label(filter_row, textvariable=self.favor_bonus_var, style="App.Muted.TLabel").pack(side="left", padx=(8, 0))
        except Exception:
            pass

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

        # Add custom preference button
        tree_button_frame = ttk.Frame(tree_tab, style="App.Panel.TFrame")
        tree_button_frame.pack(fill="x", padx=5, pady=5)
        ttk.Button(tree_button_frame, text="Add Custom Preference", command=self._add_custom_preference, style="App.Secondary.TButton").pack(side="left", padx=5)

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
        self.tree_hierarchy.column("#0", width=300, anchor="w", stretch=True)

        # Right columns: favor + value + location
        self.tree_hierarchy.heading("favor", text="Est. Favor")
        self.tree_hierarchy.heading("value", text="Value")
        self.tree_hierarchy.heading("location", text="Location")
        self.tree_hierarchy.column("favor", width=120, anchor="e", stretch=True)
        self.tree_hierarchy.column("value", width=100, anchor="e", stretch=True)
        self.tree_hierarchy.column("location", width=200, anchor="w", stretch=True)

        # Scrollbars (vertical + horizontal)
        tree_vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_hierarchy.yview)
        tree_hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_hierarchy.xview)
        self.tree_hierarchy.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)

        # Lazily populate NPC gift details when an NPC node is expanded
        self.tree_hierarchy.bind("<<TreeviewOpen>>", self._on_tree_node_open)
        self.tree_hierarchy.bind("<<TreeviewClose>>", self._on_tree_node_close)

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
        # Configure highlight tag for items with recorded/actual favor
        try:
            self.list_tree.tag_configure("favored", background=UI_COLORS.get("rarity_uncommon", "#163f2c"), foreground=UI_COLORS.get("text", "#e6eef6"))
        except Exception:
            pass
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
            # Build persistent in-memory keyword index for fast lookups
            try:
                self._keyword_index = _build_keyword_index(self._items)
            except Exception:
                self._keyword_index = None
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
        # Support both tk.StringVar and plain strings (or objects with .get()).
        def _extract(val):
            try:
                if hasattr(val, "get"):
                    return (val.get() or "").strip()
                if isinstance(val, str):
                    return val.strip()
            except Exception:
                pass
            return ""

        area_val = _extract(area)
        char_val = _extract(char)
        # If the parent uses StringVar and it's changed since we last loaded,
        # ensure Favor Tracker reflects it immediately.
        if area_val:
            # Call update_area_from_chat to use the same matching logic and debug display
            try:
                self.update_area_from_chat(area_val)
            except Exception:
                pass

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

    def _on_character_selected(self) -> None:
        """Called when user selects a character in the combo. Updates bonus display."""
        try:
            self._update_favor_bonus_display()
        except Exception:
            pass

    def _update_favor_bonus_display(self) -> None:
        """Update the displayed favor bonus percent for the currently selected character."""
        try:
            name = self.character_var.get() if getattr(self, 'character_var', None) else None
            if not name or name == "Any":
                self.favor_bonus_var.set("Bonus: 0% (x1.0)")
                return
            # Extract clean name
            clean_name = name.split(" (")[0] if " (" in name else name
            mult = _get_favor_gift_multiplier(clean_name)
            try:
                pct = (float(mult) - 1.0) * 100.0
            except Exception:
                pct = 0.0
            # Show with no decimals if integer, otherwise one decimal
            if abs(pct - round(pct)) < 0.05:
                pct_str = f"{int(round(pct))}%"
            else:
                pct_str = f"{pct:.1f}%"
            self.favor_bonus_var.set(f"Bonus: +{pct_str} (x{mult:.2f})")
        except Exception:
            try:
                self.favor_bonus_var.set("Bonus: 0% (x1.0)")
            except Exception:
                pass


    def _on_parent_area_changed(self) -> None:
        """Handler for parent.current_area trace to keep Favor Tracker in sync.

        Uses the same update_area_from_chat pipeline and shows a brief debug
        status indicating the parent reported area change.
        """
        try:
            parent_area = getattr(self.parent, 'current_area', None)
            if parent_area is None:
                return
            # Extract value from StringVar or similar
            try:
                val = parent_area.get() if hasattr(parent_area, 'get') else str(parent_area)
            except Exception:
                val = str(parent_area)
            if not val:
                return
            # Show brief debug status
            try:
                prev = self.status_var.get() if hasattr(self, 'status_var') else ''
                self.status_var.set(f"Parent area changed: {val}")
                def _restore():
                    try:
                        self.status_var.set(prev)
                    except Exception:
                        pass
                try:
                    if hasattr(self, 'window') and getattr(self, 'window', None) is not None:
                        self.window.after(3000, _restore)
                    else:
                        if hasattr(self.parent, 'root') and getattr(self.parent, 'root', None) is not None:
                            self.parent.root.after(3000, _restore)
                except Exception:
                    pass
            except Exception:
                pass
            # Delegate to existing matching/updating logic
            try:
                self.update_area_from_chat(val)
            except Exception:
                pass
        except Exception:
            pass

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
                # Publish to pglok-data channel if available
                try:
                    app = getattr(self.parent, 'app', None)
                    if app and getattr(app, 'communications_window', None):
                        try:
                            favor_data = {
                                "npc": npc_name,
                                "npc_key": npc_key,
                                "item": item_name,
                                "item_key": item_key,
                                "favor_amount": float(favor_gain),
                                "timestamp": datetime.now().isoformat()
                            }
                            app.communications_window.publish_instance_data("favor", favor_data)
                        except Exception:
                            pass
                except Exception:
                    pass
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

        # Get character's favor gift multiplier to adjust the recorded value
        character_name = self.character_var.get()
        multiplier = 1.0
        if character_name and character_name != "Any":
            multiplier = _get_favor_gift_multiplier(character_name)
        
        # The favor_value from the game already includes the multiplier,
        # so divide by it to get the base favor for storage
        base_favor = favor_value / multiplier if multiplier > 0 else favor_value

        # If training mode is enabled, open the training item selector when item name is missing.
        # Otherwise, do not pop up the dialog — respect user's training mode setting.
        try:
            training_enabled = bool(getattr(self, 'training_mode_var', None) and self.training_mode_var.get())
        except Exception:
            training_enabled = False

        if training_enabled:
            success = self._open_training_item_selector(npc_obj, base_favor)
            # Only refresh if recording was successful
            if success:
                # Clear cache to ensure new favor data is reflected
                self._gift_cache.clear()
                self._refresh_table()
        else:
            # Training mode is off: do not show the popup. Optionally update status.
            try:
                if getattr(self, 'status_var', None):
                    self.status_var.set("Training mode OFF - favor detected but no item recorded")
            except Exception:
                pass
    
    def record_favor_gain_from_chat_with_item(self, npc_name: str, favor_amount: str, item_name: str) -> None:
        """Record a favor gain parsed from chat log with item name included."""
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

        # Get character's favor gift multiplier to adjust the recorded value
        character_name = self.character_var.get()
        multiplier = 1.0
        if character_name and character_name != "Any":
            multiplier = _get_favor_gift_multiplier(character_name)
        
        # The favor_value from the game already includes the multiplier,
        # so divide by it to get the base favor for storage
        base_favor = favor_value / multiplier if multiplier > 0 else favor_value

        # Find item key by name
        item_key = None
        item_value = 0.0
        keyword_weight = 0.0
        npc_pref_value = 0.0
        
        for k, itm in self._items.items():
            if itm.name.lower() == item_name.lower() or item_name.lower() in itm.name.lower():
                item_key = k
                item_value = getattr(itm, 'value', 0.0)
                # Try to infer keyword weight and pref
                if npc_obj:
                    for pref in (npc_obj.preferences if npc_obj else []):
                        for item_kw in itm.keywords:
                            if any(pref_kw.lower() in item_kw.lower() for pref_kw in pref.keywords):
                                try:
                                    if '=' in item_kw:
                                        keyword_weight = float(item_kw.split('=',1)[1])
                                except Exception:
                                    pass
                                npc_pref_value = pref.pref
                                break
                        if npc_pref_value > 0:
                            break
                break

        record_key = item_key if item_key else item_name
        
        # Record the favor gain with item information
        if _record_favor_gain(npc_key, record_key, base_favor, 1, item_value, keyword_weight, npc_pref_value, stored_as="base"):
            # Publish to pglok-data channel if available
            try:
                app = getattr(self.parent, 'app', None)
                if app and getattr(app, 'communications_window', None):
                    try:
                        favor_data = {
                            "npc": npc_name,
                            "npc_key": npc_key,
                            "item": item_name,
                            "item_key": record_key,
                            "favor_amount": float(base_favor),
                            "item_value": item_value,
                            "keyword_weight": keyword_weight,
                            "npc_pref": npc_pref_value,
                            "multiplier": multiplier,
                            "timestamp": datetime.now().isoformat()
                        }
                        app.communications_window.publish_instance_data("favor", favor_data)
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Clear cache to ensure new favor data is reflected
        self._gift_cache.clear()
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

        # Show ALL items in training mode so user can select any item they gifted
        # Sort items alphabetically for easier searching
        all_items = [(item.name, item, 0, None, None) for item in self._items.values()]
        all_items.sort(key=lambda x: x[0].lower())

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
        # Only use listbox selection - do not use search term for item selection
        selection = item_listbox.curselection()
        if not selection:
            messagebox.showerror("Error", "Please select an item from the list")
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

        # Item should always be found since it's from the list
        if not item_key:
            messagebox.showerror("Error", f"Item '{item_name}' not found in database. This should not happen.")
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
        result = _record_favor_gain(npc.key, record_key, favor_per_item, quantity, item_value, keyword_weight, npc_pref_value, stored_as="base")
        if result:
            # Publish to pglok-data channel if available
            try:
                app = getattr(self.parent, 'app', None)
                if app and getattr(app, 'communications_window', None):
                    try:
                        favor_data = {
                            "npc": npc.name,
                            "npc_key": npc.key,
                            "item": item_name,
                            "item_key": record_key,
                            "favor_amount": float(favor_per_item),
                            "quantity": quantity,
                            "item_value": item_value,
                            "keyword_weight": keyword_weight,
                            "npc_pref": npc_pref_value,
                            "timestamp": datetime.now().isoformat()
                        }
                        app.communications_window.publish_instance_data("favor", favor_data)
                    except Exception:
                        pass
            except Exception:
                pass

            # Clear gift cache to force recalculation with new actual favor data
            self._gift_cache.clear()

            recording_success[0] = True
            self.status_var.set(f"Recorded training data: {item_name} × {quantity} → {npc.name} ({favor_per_item:.1f} each)")
            dialog.destroy()
            self._refresh_table()
        else:
            messagebox.showerror("Error", "Failed to save favor gain data. Check console for details.")

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

        Matching is flexible: exact match, substring, reverse-substring, and
        alphanumeric-normalized comparisons are attempted so area names from
        chat logs that differ in punctuation/casing still match common UI labels.
        """
        if not area_name:
            return
        # Show raw detected area in status bar briefly for debugging
        try:
            prev_status = self.status_var.get() if hasattr(self, 'status_var') else ''
            self.status_var.set(f"Detected area update: {area_name}")
            def _restore():
                try:
                    self.status_var.set(prev_status)
                except Exception:
                    pass
            try:
                # Use after if window exists to restore after 5s
                if hasattr(self, 'window') and getattr(self, 'window', None) is not None:
                    self.window.after(5000, _restore)
                else:
                    # Fallback: schedule on parent/root if available
                    if hasattr(self.parent, 'root') and getattr(self.parent, 'root', None) is not None:
                        self.parent.root.after(5000, _restore)
            except Exception:
                pass
        except Exception:
            pass
        if self.area_lock_var.get():
            self.status_var.set(f"Area '{area_name}' detected but lock is engaged")
            return  # Locked, don't auto-update

        # Update the area filter with flexible matching
        if not hasattr(self, "area_combo"):
            return

        area_name_clean = str(area_name).strip()
        if not area_name_clean:
            return

        # Early debug dump so we can see why selection didn't occur
        try:
            try:
                tmp_path = Path('/tmp') / 'favor_tracker_update_debug.log'
                with tmp_path.open('a', encoding='utf-8') as tf:
                    tf.write(f"{datetime.now().isoformat()}\tarea_in={area_name!r}\tarea_lock={self.area_lock_var.get() if hasattr(self, 'area_lock_var') else '??'}\tarea_combo_exists={hasattr(self, 'area_combo')}\tarea_var={self.area_var.get() if hasattr(self, 'area_var') else '??'}\n")
            except Exception:
                pass
        except Exception:
            pass

        # Run the matching and UI updates on the Tk main thread to avoid race conditions
        def _do_match():
            # Use cget to safely read combobox values
            values = list(self.area_combo.cget('values') or [])

            # Normalize helper for relaxed matching
            def _norm(s: str) -> str:
                return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

            # Helper to update status briefly
            def _log_and_status(chosen: str, method: str):
                try:
                    prev = self.status_var.get() if hasattr(self, 'status_var') else ''
                    try:
                        self.status_var.set(f"Area set: {chosen} ({method})")
                    except Exception:
                        pass
                    def _restore():
                        try:
                            self.status_var.set(prev)
                        except Exception:
                            pass
                    if hasattr(self, 'window') and getattr(self, 'window', None) is not None:
                        try:
                            self.window.after(3000, _restore)
                        except Exception:
                            pass
                    elif hasattr(self.parent, 'root') and getattr(self.parent, 'root', None) is not None:
                        try:
                            self.parent.root.after(3000, _restore)
                        except Exception:
                            pass
                except Exception:
                    pass

            def _select_area_value(val: str):
                try:
                    _state_changed = False
                    try:
                        if hasattr(self, 'area_combo'):
                            try:
                                current_state = None
                                try:
                                    current_state = self.area_combo.cget('state')
                                except Exception:
                                    current_state = None
                                if current_state == 'readonly':
                                    try:
                                        self.area_combo.config(state='normal')
                                        _state_changed = True
                                    except Exception:
                                        _state_changed = False
                                # Refresh values to force redraw
                                try:
                                    vals = list(self.area_combo.cget('values') or [])
                                    self.area_combo.config(values=vals)
                                except Exception:
                                    pass
                                try:
                                    self.area_combo.set(val)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        self.area_var.set(val)
                    except Exception:
                        pass
                    try:
                        self._on_area_filter_changed()
                    except Exception:
                        pass
                    try:
                        if hasattr(self, 'area_combo'):
                            try:
                                self.area_combo.update_idletasks()
                                self.area_combo.event_generate('<<ComboboxSelected>>')
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        if _state_changed and hasattr(self, 'area_combo'):
                            try:
                                self.area_combo.config(state='readonly')
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        self.status_var.set(f"Area updated to: {val}")
                    except Exception:
                        pass
                except Exception:
                    pass

            # 1) Exact (case-insensitive)
            for value in values:
                if not value:
                    continue
                if value.lower() == area_name_clean.lower():
                    _select_area_value(value)
                    _log_and_status(value, 'exact')
                    return

            # 2) area_name is contained within value (e.g., shorter chat name)
            for value in values:
                if not value:
                    continue
                if area_name_clean.lower() in value.lower():
                    _select_area_value(value)
                    _log_and_status(value, 'contains')
                    return

            # 3) value is contained within area_name (e.g., chat includes extra context)
            for value in values:
                if not value:
                    continue
                if value.lower() in area_name_clean.lower():
                    _select_area_value(value)
                    _log_and_status(value, 'reverse_contains')
                    return

            # 4) Alphanumeric-normalized equality (strip punctuation/spacing)
            norm_target = _norm(area_name_clean)
            if norm_target:
                for value in values:
                    if not value:
                        continue
                    if _norm(value) == norm_target:
                        _select_area_value(value)
                        _log_and_status(value, 'norm_equal')
                        return

            # 5) Token overlap matching (handles reorderings, extra words, minor differences)
            stopwords = {"the", "a", "an", "of", "casino", "area", "district", "zone"}
            def _tokens(s: str):
                parts = re.findall(r"[a-z0-9]+", str(s or "").lower())
                return [p for p in parts if p and p not in stopwords]

            target_tokens = set(_tokens(area_name_clean))
            if target_tokens:
                best_match = None
                best_score = 0.0
                for value in values:
                    if not value:
                        continue
                    val_tokens = set(_tokens(value))
                    if not val_tokens:
                        continue
                    inter = target_tokens.intersection(val_tokens)
                    score = len(inter) / min(len(target_tokens), len(val_tokens))
                    if score > best_score:
                        best_score = score
                        best_match = value
                if best_match and best_score >= 0.5:
                    _select_area_value(best_match)
                    _log_and_status(best_match, 'token_overlap')
                    return

            # No match found — add a safe fallback so the UI still reflects the detected area.
            try:
                values_list = list(self.area_combo.cget('values') or [])
                if area_name not in values_list:
                    if values_list and values_list[0].lower().startswith("all"):
                        values_list.insert(1, area_name)
                    else:
                        values_list.append(area_name)
                    try:
                        self.area_combo["values"] = values_list
                    except Exception:
                        pass
                try:
                    if self.area_var.get() != area_name:
                        try:
                            if hasattr(self, 'area_combo') and getattr(self.area_combo, 'set', None):
                                self.area_combo.set(area_name)
                        except Exception:
                            pass
                        try:
                            self.area_var.set(area_name)
                        except Exception:
                            pass
                        try:
                            self._on_area_filter_changed()
                        except Exception:
                            pass
                        _log_and_status(area_name, 'fallback')
                except Exception:
                    pass
            except Exception:
                pass
            try:
                self.status_var.set(f"Area '{area_name}' not found in area list; selected as fallback")
            except Exception:
                pass

        # Schedule the UI update on the main Tk thread
        try:
            if hasattr(self, 'window') and getattr(self, 'window', None) is not None:
                self.window.after(0, _do_match)
            elif hasattr(self.parent, 'root') and getattr(self.parent, 'root', None) is not None:
                self.parent.root.after(0, _do_match)
            else:
                # Last resort: run inline (may be a background thread)
                _do_match()
        except Exception:
            try:
                _do_match()
            except Exception:
                pass

    def update_character_from_chat(self, character_name: str) -> None:
        """Called by parent app when chat log detects a character login.

        Only updates if:
        - area_lock is False (unlocked)
        - character_name is different from current
        """

    def record_external_favor(self, npc_name: str, item_name: str, favor_amount: float, user: str = None) -> None:
        """Record a favor gain that originated from another user (via communications).

        This looks up npc/item keys when possible and stores the same structure as
        locally-recorded favor events. The UI is refreshed to reflect new data.
        """
        try:
            # Find NPC key
            npc_key = None
            npc_obj = None
            for npc in self._npcs:
                if npc.name.lower() == str(npc_name).lower() or str(npc_name).lower() in npc.name.lower():
                    npc_key = npc.key
                    npc_obj = npc
                    break

            # Find item key and value
            item_key = None
            item_value = 0.0
            keyword_weight = 0.0
            npc_pref_value = 0.0
            for k, itm in self._items.items():
                if itm.name.lower() == str(item_name).lower() or str(item_name).lower() in itm.name.lower():
                    item_key = k
                    item_value = getattr(itm, 'value', 0.0)
                    # try to infer keyword weight and pref
                    for pref in (npc_obj.preferences if npc_obj else []):
                        for item_kw in itm.keywords:
                            if any(pref_kw.lower() in item_kw.lower() for pref_kw in pref.keywords):
                                try:
                                    if '=' in item_kw:
                                        keyword_weight = float(item_kw.split('=',1)[1])
                                except Exception:
                                    pass
                                npc_pref_value = pref.pref
                                break
                        if npc_pref_value > 0:
                            break
                    break

            if npc_key is None:
                # Use name as key when unknown
                npc_key = npc_name

            record_key = item_key if item_key else item_name
            # Persist (favor_amount assumed to be per-item)
            if _record_favor_gain(npc_key, record_key, float(favor_amount), 1, float(item_value), float(keyword_weight), float(npc_pref_value)):
                # Publish to pglok-data channel if available
                try:
                    app = getattr(self.parent, 'app', None)
                    if app and getattr(app, 'communications_window', None):
                        try:
                            favor_data = {
                                "npc": npc_name if npc_name else "Unknown",
                                "npc_key": npc_key,
                                "item": item_name if item_name else "Unknown",
                                "item_key": record_key,
                                "favor_amount": float(favor_amount),
                                "item_value": float(item_value),
                                "keyword_weight": float(keyword_weight),
                                "npc_pref": float(npc_pref_value),
                                "timestamp": datetime.now().isoformat()
                            }
                            app.communications_window.publish_instance_data("favor", favor_data)
                        except Exception:
                            pass
                except Exception:
                    pass
            # Refresh UI
            try:
                self._gift_cache.clear()
                self._refresh_table()
            except Exception:
                pass
        except Exception:
            pass
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
                # Use persistent keyword index when available and base_items is the full items set.
                keyword_index = None
                if getattr(self, "_keyword_index", None) is not None and base_items is self._items:
                    keyword_index = self._keyword_index
                else:
                    try:
                        keyword_index = _build_keyword_index(base_items)
                    except Exception:
                        keyword_index = None
                results = compute_best_gifts(npc, base_items, limit=limit, character_name=character_name, keyword_index=keyword_index)

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
                tags = ()
                # Highlight rows that have actual recorded favor
                if actual_favor is not None:
                    tags = ("favored",)
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
                    tags=tags,
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
            npc_id = self.tree_hierarchy.insert(root_id, "end", text=npc_text, values=("", "", ""), open=False)

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
            # Separate items with actual favor data
            actual_favor_items: list[tuple[FavorItem, float, FavorPreference, Optional[float]]] = []
            
            for item, score, pref, actual_favor in results:
                # Guard against None preferences (supplemented high-value items)
                desire = (pref.desire or "").lower() if pref is not None else ""

                # If item has actual favor data, add to actual_favor_items
                if actual_favor is not None:
                    actual_favor_items.append((item, score, pref, actual_favor))

                # Only include Loved/Liked items in preference groups
                if not pref:
                    continue
                if not (desire.startswith("love") or desire.startswith("like")):
                    continue

                # Create preference label (e.g., "Loves Green Crystals", "Likes Brass Items")
                pref_name = pref.name if getattr(pref, "name", None) else ", ".join(getattr(pref, "keywords", []))
                if desire.startswith("love"):
                    pref_label = f"Loves {pref_name}"
                else:
                    pref_label = f"Likes {pref_name}"

                if pref_label not in pref_groups:
                    pref_groups[pref_label] = []
                pref_groups[pref_label].append((item, score, pref, actual_favor))

            # Create tree nodes for each preference group
            for pref_label, items in pref_groups.items():
                pref_id = self.tree_hierarchy.insert(npc_id, "end", text=f"- {pref_label}", values=("", "", ""), open=False)
                # Restore expanded state
                if f"- {pref_label}" in self._expanded_nodes:
                    self.tree_hierarchy.item(pref_id, open=True)

                for item, score, pref, actual_favor in items:
                    # Display item with actual favor if available, otherwise estimated
                    if actual_favor is not None:
                        favor_value = f"{actual_favor:,.1f}"
                    else:
                        favor_value = f"{score:,.1f} (est)"
                    self.tree_hierarchy.insert(
                        pref_id,
                        "end",
                        text=f"-- {item.name}",
                        values=(favor_value, f"{item.value:,.1f}", getattr(item, "location", "")),
                    )

            # Create tree nodes for custom preferences
            if npc.key in self._custom_preferences and self._custom_preferences[npc.key]:
                custom_id = self.tree_hierarchy.insert(npc_id, "end", text="- Custom Preferences", values=("", "", ""), open=False)
                # Restore expanded state
                if "- Custom Preferences" in self._expanded_nodes:
                    self.tree_hierarchy.item(custom_id, open=True)
                
                for custom_pref in self._custom_preferences[npc.key]:
                    item_name = custom_pref["item_name"]
                    desire = custom_pref["desire"]
                    pref_value = custom_pref.get("pref", 0)
                    pref_label = f"{desire} {item_name}"
                    self.tree_hierarchy.insert(
                        custom_id,
                        "end",
                        text=f"-- {pref_label}",
                        values=(f"{pref_value:.1f}", "N/A", ""),
                    )

            # Create tree node for items with actual favor data
            if actual_favor_items:
                actual_id = self.tree_hierarchy.insert(npc_id, "end", text="- Recorded Gifts (Actual Favor)", values=("", "", ""), open=True)
                # Restore expanded state
                if "- Recorded Gifts (Actual Favor)" in self._expanded_nodes:
                    self.tree_hierarchy.item(actual_id, open=True)
                else:
                    self.tree_hierarchy.item(actual_id, open=True)  # Always expand by default
                
                # Sort by actual favor value descending
                actual_favor_items.sort(key=lambda x: x[3] if x[3] is not None else x[1], reverse=True)
                
                for item, score, pref, actual_favor in actual_favor_items:
                    favor_value = f"{actual_favor:,.1f}"
                    self.tree_hierarchy.insert(
                        actual_id,
                        "end",
                        text=f"-- {item.name}",
                        values=(favor_value, f"{item.value:,.1f}", getattr(item, "location", "")),
                    )

    def _on_tree_node_open(self, event) -> None:
        """Treeview open handler - save expanded state."""
        if not hasattr(self, "tree_hierarchy"):
            return
        item_id = self.tree_hierarchy.identify_row(event.y)
        if item_id:
            item_text = self.tree_hierarchy.item(item_id, "text")
            self._expanded_nodes.add(item_text)
    
    def _on_tree_node_close(self, event) -> None:
        """Treeview close handler - remove from expanded state."""
        if not hasattr(self, "tree_hierarchy"):
            return
        item_id = self.tree_hierarchy.identify_row(event.y)
        if item_id:
            item_text = self.tree_hierarchy.item(item_id, "text")
            self._expanded_nodes.discard(item_text)

    def _add_custom_preference(self) -> None:
        """Open dialog to add a custom gift preference for an NPC."""
        npc = self._get_selected_npc()
        if not npc:
            messagebox.showerror("Error", "Please select an NPC first")
            return

        dialog = tk.Toplevel(self.window)
        dialog.title("Add Custom Preference")
        dialog.geometry("400x300")
        dialog.transient(self.window)
        dialog.grab_set()

        container = ttk.Frame(dialog, style="App.Panel.TFrame")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # NPC info
        ttk.Label(container, text=f"NPC: {npc.name}", style="App.Header.TLabel").pack(pady=(0, 10))

        # Item name
        ttk.Label(container, text="Item name:", style="App.TLabel").pack(anchor="w")
        item_var = tk.StringVar()
        ttk.Entry(container, textvariable=item_var, style="App.TEntry").pack(fill="x", pady=(0, 10))

        # Desire level
        ttk.Label(container, text="Desire level:", style="App.TLabel").pack(anchor="w")
        desire_var = tk.StringVar(value="Loves")
        desire_combo = ttk.Combobox(container, textvariable=desire_var, values=["Loves", "Likes"], state="readonly", style="App.TCombobox")
        desire_combo.pack(fill="x", pady=(0, 10))

        # Preference value
        ttk.Label(container, text="Preference value (1.0-3.0):", style="App.TLabel").pack(anchor="w")
        pref_var = tk.StringVar(value="2.0")
        ttk.Entry(container, textvariable=pref_var, style="App.TEntry").pack(fill="x", pady=(0, 10))

        def save_preference():
            item_name = item_var.get().strip()
            desire = desire_var.get().strip()
            try:
                pref_value = float(pref_var.get())
            except ValueError:
                messagebox.showerror("Error", "Preference value must be a number")
                return

            if not item_name:
                messagebox.showerror("Error", "Please enter an item name")
                return

            # Save to custom preferences
            if npc.key not in self._custom_preferences:
                self._custom_preferences[npc.key] = []
            
            self._custom_preferences[npc.key].append({
                "item_name": item_name,
                "desire": desire,
                "pref": pref_value,
                "timestamp": datetime.now().isoformat()
            })
            
            _save_custom_preferences(self._custom_preferences)
            self._refresh_table()
            self._refresh_tree_view()
            dialog.destroy()
            messagebox.showinfo("Success", f"Added custom preference: {desire} {item_name} for {npc.name}")

        ttk.Button(container, text="Save", command=save_preference, style="App.Primary.TButton").pack(side="left", padx=5)
        ttk.Button(container, text="Cancel", command=dialog.destroy, style="App.Secondary.TButton").pack(side="left", padx=5)

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
