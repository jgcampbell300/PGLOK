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


def _get_favor_db_path() -> Path:
    return DATA_DIR / FAVOR_DB_FILENAME


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
            for item, score, top_pref in compute_best_gifts(npc, items, limit=300):
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
        # Initialize without a location; we fill that in lazily when needed.
        items[key] = FavorItem(
            key=key,
            name=name,
            value=value_f,
            keywords=[str(k) for k in keywords],
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
        area = str(payload.get("AreaFriendlyName") or "").strip()
        prefs_raw = payload.get("Preferences") or []
        preferences: List[FavorPreference] = []
        if isinstance(prefs_raw, list):
            for p in prefs_raw:
                if not isinstance(p, dict):
                    continue
                desire = str(p.get("Desire") or "").strip() or "Unknown"
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
                        keywords=[str(k) for k in kw_list],
                        pref=pref_val,
                    )
                )
        if preferences:
            npcs.append(FavorNpc(key=key, name=name, area=area, preferences=preferences))

    # Sort NPCs by area then name for nicer dropdown
    npcs.sort(key=lambda n: (n.area.lower(), n.name.lower()))
    return npcs

# Some preference keywords are extremely broad (e.g. "Loot") and should not
# by themselves make an item look like a great gift when more specific
# keywords are available on the same preference.
_GENERIC_PREF_KEYWORDS = {"Loot"}


def _match_score(item: FavorItem, pref: FavorPreference) -> Optional[float]:
    """Return a raw favor score for item against one preference, or None.

    This is intentionally simple: we check if any preference keyword is
    present in the item's Keywords list (string equality). If so, we
    estimate favor as:

        score = item.value * pref.pref * desire_multiplier

    where desire_multiplier is higher for "Love" than for "Like".
    This is an approximation, but it preserves the relative ordering of
    good gifts for a given NPC.
    """
    if not item.keywords:
        return None

    item_kw = set(item.keywords)

    # Prefer specific keywords over very broad ones like "Loot".
    specific_pref_kw = [k for k in pref.keywords if k not in _GENERIC_PREF_KEYWORDS]
    if specific_pref_kw:
        if not any(k in item_kw for k in specific_pref_kw):
            return None
    else:
        if not any(k in item_kw for k in pref.keywords):
            return None

    desire = pref.desire.lower()
    # Use prefix match so we don't mis-classify descriptive text that happens to contain "love"/"like".
    if desire.startswith("love"):
        desire_mult = 1.0
    elif desire.startswith("like"):
        desire_mult = 0.5
    else:
        desire_mult = 0.25

    return max(0.0, item.value) * max(0.0, pref.pref) * desire_mult


def compute_best_gifts(npc: FavorNpc, items: Dict[str, FavorItem], limit: int = 200) -> List[Tuple[FavorItem, float, FavorPreference]]:
    """Return a sorted list of (item, score, top_pref) for the NPC.

    Items are sorted descending by score. Only items that match at least
    one preference are returned.
    """
    results: List[Tuple[FavorItem, float, FavorPreference]] = []

    for item in items.values():
        best_score = 0.0
        best_pref: Optional[FavorPreference] = None
        for pref in npc.preferences:
            score = _match_score(item, pref)
            if score is not None and score > best_score:
                best_score = score
                best_pref = pref
        if best_pref is not None and best_score > 0.0:
            results.append((item, best_score, best_pref))

    results.sort(key=lambda t: t[1], reverse=True)
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
        self._gift_cache: Dict[str, List[Tuple[FavorItem, float, FavorPreference]]] = {}
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
        # When enabled, use current area + character from PGLOK to filter NPC list
        self.use_current_area_var = tk.BooleanVar(value=False)
        # When enabled, restrict items to those carried by the focused character (inventory + saddle)
        self.inventory_only_var = tk.BooleanVar(value=False)

        self._build_ui()
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

        # Context checkboxes row: follow PGLOK context + restrict to carried items
        context_row = ttk.Frame(shell, style="App.Panel.TFrame")
        context_row.pack(fill="x", pady=(0, 8))

        ttk.Checkbutton(
            context_row,
            text="Use current area / character",
            variable=self.use_current_area_var,
            command=self._on_use_current_context_toggled,
            style="App.TCheckbutton",
        ).pack(side="left", padx=(0, 8))

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

        columns = ("item", "favor", "value", "location", "pref", "desire", "keywords")
        self.list_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="App.Treeview",
        )

        self.list_tree.heading("item", text="Item")
        self.list_tree.heading("favor", text="Est. Favor Score")
        self.list_tree.heading("value", text="Value")
        self.list_tree.heading("location", text="Location")
        self.list_tree.heading("pref", text="Match")
        self.list_tree.heading("desire", text="Desire")
        self.list_tree.heading("keywords", text="Matched Keywords")

        self.list_tree.column("item", width=230, anchor="w", stretch=True)
        self.list_tree.column("favor", width=110, anchor="center", stretch=True)
        self.list_tree.column("value", width=80, anchor="center", stretch=True)
        self.list_tree.column("location", width=180, anchor="center", stretch=True)
        self.list_tree.column("pref", width=150, anchor="w")
        self.list_tree.column("desire", width=80, anchor="w")
        self.list_tree.column("keywords", width=260, anchor="w", stretch=True)

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
        all_labels = [f"{n.name} ({n.area})" if n.area else n.name for n in self._npcs]
        self._all_npc_labels = all_labels
        values = ["All"] + all_labels
        self.npc_combo["values"] = values
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

        # If we're supposed to follow the current PGLOK context, apply it now
        if self.use_current_area_var.get():
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
                    if value.lower() == area_val.lower():
                        self.area_var.set(value)
                        break

        # Try to select matching character in combo, if any
        if char_val and self.character_combo is not None:
            for value in self.character_combo["values"]:
                # values look like "Name (Server)"
                if value.lower().startswith(char_val.lower()):
                    self.character_var.set(value)
                    break

    def _on_use_current_context_toggled(self) -> None:
        """Handler when "Use current area / character" is toggled."""
        if self.use_current_area_var.get():
            # Enable context-following and immediately apply
            self._apply_current_context_filters()
        else:
            # Turn off: restore full NPC + area list (with All)
            if hasattr(self, "_all_npc_labels"):
                values = ["All"] + self._all_npc_labels
                self.npc_combo["values"] = values
                if self.npc_var.get() not in values:
                    self.npc_var.set("All")
            if hasattr(self, "area_combo"):
                self.area_var.set("All Areas")
        self._refresh_table()

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
        # Character change may affect inventory-only results
        self._gift_cache.clear()
        self._refresh_table()

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
        key = npc.key
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
                            tmp: List[Tuple[FavorItem, float, FavorPreference]] = []
                            for item_key, score, desire in rows:
                                item = self._items.get(item_key)
                                if not item:
                                    continue
                                # Recreate a minimal FavorPreference to display desire text.
                                pref = FavorPreference(desire=desire or "", keywords=[], pref=0.0)
                                tmp.append((item, float(score), pref))
                            if tmp:
                                results = tmp
                        finally:
                            conn.close()
                except Exception:
                    results = None

            # Fallback: compute on the fly using current items view.
            if results is None:
                results = compute_best_gifts(npc, base_items, limit=limit)

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

        results = self._get_gifts_for_npc(npc, limit=300)
        term = self.search_var.get().strip().lower()

        # Preload locations for any items that don't have one yet, in a single DB hit.
        try:
            missing_items = [item for item, _score, _pref in results if not getattr(item, "location", "")]
        except Exception:
            missing_items = []
        if missing_items:
            self._ensure_locations_for_items(missing_items)

        shown = 0
        for item, score, pref in results:
            if term and term not in item.name.lower():
                continue

            # Figure out which keywords actually matched, for display.
            matched_kw = [k for k in pref.keywords if k in item.keywords]
            matched_text = ", ".join(matched_kw) if matched_kw else ", ".join(pref.keywords)

            # Use cached location if populated.
            location = getattr(item, "location", "")

            if hasattr(self, "list_tree"):
                self.list_tree.insert(
                    "",
                    "end",
                    values=(
                        item.name,
                        f"{score:,.1f}",
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
        # If "All" or nothing is selected, show all visible NPCs.
        selected_label = self.npc_var.get().strip()
        if selected_label and selected_label.lower() != "all":
            visible_labels = [selected_label]
        else:
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

            npc_text = f"{npc.name} ({npc.area})" if npc.area else npc.name
            npc_id = self.tree_hierarchy.insert(root_id, "end", text=npc_text, open=False)

            # Use the same cached gift computation the table uses (limit for performance)
            results = self._get_gifts_for_npc(npc, limit=120)

            # Preload locations for any items we may show, in a single DB hit.
            try:
                missing_items = [item for item, _score, _pref in results if not getattr(item, "location", "")]
            except Exception:
                missing_items = []
            if missing_items:
                self._ensure_locations_for_items(missing_items)

            loved_id = None
            liked_id = None

            for item, score, pref in results:
                desire = (pref.desire or "").lower()
                # Bucket strictly by prefix so "Like" preferences don't get caught by a stray "love" word.
                if desire.startswith("love"):
                    if loved_id is None:
                        loved_id = self.tree_hierarchy.insert(npc_id, "end", text="Loved", open=False)
                    parent_id = loved_id
                elif desire.startswith("like"):
                    if liked_id is None:
                        liked_id = self.tree_hierarchy.insert(npc_id, "end", text="Liked", open=False)
                    parent_id = liked_id
                else:
                    # Skip items that aren't clearly Loved/Liked to keep tree focused
                    continue

                # Use cached location if populated.
                location = getattr(item, "location", "")

                self.tree_hierarchy.insert(
                    parent_id,
                    "end",
                    text=item.name,
                    values=(f"{score:,.1f}", f"{item.value:,.1f}", location),
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
