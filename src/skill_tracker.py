"""Skill Tracker — view all Project Gorgon skills, abilities, trainers, and costs.

- Tree view: Skill → Ability Group → Ability Level
- Shows trainer info per ability (who, where, what favor)
- Groups ability levels (Fireball, Fireball 2, Fireball 3) under one parent
"""

from __future__ import annotations

import json
import re
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.config import config
from src.config.ui_theme import UI_COLORS, UI_ATTRS, apply_theme

DATA_DIR = config.DATA_DIR

# ---------------------------------------------------------------------------
# Favor ordering
# ---------------------------------------------------------------------------
FAVOR_ORDER = [
    "Despised", "Hated", "Tolerated", "Neutral",
    "Comfortable", "Friends", "CloseFriends",
    "BestFriends", "LikeFamily", "SoulMates",
]

def _favor_sort_key(favor: str) -> int:
    try:
        return FAVOR_ORDER.index(favor)
    except ValueError:
        return len(FAVOR_ORDER)

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_json(filename: str) -> dict:
    path = Path(str(DATA_DIR)) / filename
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_skill_tree_data() -> dict:
    """Build a dict of skill -> grouped ability data with trainers.

    Returns::
    {
      "SkillKey": {
        "name": "Fire Magic",
        "combat": True,
        "ability_groups": {
          "Fireball": [
            {
              "ability_id": "ability_xxx",
              "name": "Fireball",
              "level": 1,
              "description": "...",
              "trainers": [{"npc_name": "...", "area": "...", "favor": "..."}],
              "sources": [{"type": "Skill/Training/Item/Quest", "detail": "..."}],
            },
            { ... }  # Fireball 2, Fireball 3, etc.
          ],
          "Warmthball": [ ... ],
        }
      },
      ...
    }
    """
    raw_skills = _load_json("skills.json")
    raw_abilities = _load_json("abilities.json")
    raw_sources = _load_json("sources_abilities.json")
    raw_npcs = _load_json("npcs.json")

    # --- Build NPC lookup ---
    npc_lookup: Dict[str, dict] = {}
    for key, npc in raw_npcs.items():
        if not isinstance(npc, dict):
            continue
        name = str(npc.get("Name") or key).strip()
        area = str(npc.get("AreaFriendlyName") or "").strip()
        services = npc.get("Services") or []
        # Collect the skills this NPC trains and the favor required
        npc_training: Dict[str, Tuple[str, List[str]]] = {}  # skill_name -> (favor, unlocks)
        for svc in services:
            if not isinstance(svc, dict):
                continue
            if svc.get("Type") != "Training":
                continue
            favor = str(svc.get("Favor") or "Despised")
            unlocks = svc.get("Unlocks") or []
            for sk in (svc.get("Skills") or []):
                sk_str = str(sk).strip()
                if sk_str:
                    # Only store the best (lowest) favor for this skill
                    # since the same NPC might have multiple Training services
                    if sk_str not in npc_training or _favor_sort_key(favor) < _favor_sort_key(npc_training[sk_str][0]):
                        npc_training[sk_str] = (favor, unlocks)
        npc_lookup[key] = {
            "name": name,
            "area": area,
            "training": npc_training,
        }

    # Also build a reverse lookup: skill_name -> list of NPCs that train it
    skill_npcs: Dict[str, List[dict]] = {}
    for npc_key, ni in npc_lookup.items():
        for sk_name, (favor, unlocks) in ni["training"].items():
            if sk_name not in skill_npcs:
                skill_npcs[sk_name] = []
            skill_npcs[sk_name].append({
                "npc_key": npc_key,
                "npc_name": ni["name"],
                "area": ni["area"],
                "favor": favor,
                "unlocks": unlocks,
            })

    # --- Step 1: Build ability -> skill mapping ---
    # First from Skill-type entries in sources_abilities
    ability_skill_source: Dict[str, str] = {}  # ability_id -> skill_name (game's key like 'Unarmed', 'Sword')
    for aid, src_info in raw_sources.items():
        if not isinstance(src_info, dict):
            continue
        entries = src_info.get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "Skill":
                sk = str(entry.get("skill", "")).strip()
                if sk:
                    ability_skill_source[aid] = sk

    # Also get skill from the ability's own Skill field
    for aid, ab in raw_abilities.items():
        if not isinstance(ab, dict):
            continue
        skill = ab.get("Skill", "")
        if skill and skill != "Unknown" and aid not in ability_skill_source:
            ability_skill_source[aid] = skill

    # --- Step 2: Build ability-to-trainers mapping with proper favor lookup ---
    ability_trainers: Dict[str, List[dict]] = {}
    ability_item_sources: Dict[str, List[int]] = {}
    ability_quest_sources: Dict[str, List[int]] = {}
    ability_gift_sources: Dict[str, List[str]] = {}

    for aid, src_info in raw_sources.items():
        if not isinstance(src_info, dict):
            continue
        entries = src_info.get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            etype = entry.get("type", "")
            if etype == "Training":
                npc_key = str(entry.get("npc", "")).strip()
                if npc_key and npc_key in npc_lookup:
                    ni = npc_lookup[npc_key]
                    # Determine what skill this NPC trains for this ability
                    # Look up the ability's skill from our mapping
                    ab_skill = ability_skill_source.get(aid, "")
                    favor = "Despised"
                    if ab_skill and ab_skill in ni["training"]:
                        favor = ni["training"][ab_skill][0]
                    elif ni["training"]:
                        # Fallback: use the NPC's first training favor
                        first_skill = next(iter(ni["training"].values()))
                        favor = first_skill[0] if isinstance(first_skill, tuple) else first_skill
                    if aid not in ability_trainers:
                        ability_trainers[aid] = []
                    ability_trainers[aid].append({
                        "npc_key": npc_key,
                        "npc_name": ni["name"],
                        "area": ni["area"],
                        "favor": favor,
                    })
            elif etype == "Item":
                item_id = entry.get("itemTypeId", 0)
                if item_id:
                    if aid not in ability_item_sources:
                        ability_item_sources[aid] = []
                    ability_item_sources[aid].append(item_id)
            elif etype == "Quest":
                qid = entry.get("questId", 0)
                if qid:
                    if aid not in ability_quest_sources:
                        ability_quest_sources[aid] = []
                    ability_quest_sources[aid].append(qid)
            elif etype == "NpcGift":
                npc_key = str(entry.get("npc", "")).strip()
                if npc_key:
                    if aid not in ability_gift_sources:
                        ability_gift_sources[aid] = []
                    ability_gift_sources[aid].append(npc_key)

    # --- Build skill -> ability mapping ---
    # We need to handle: some sources reference skills like 'Unarmed', 'Sword', 'FireMagic' etc.
    # Map those to internal skill keys from skills.json

    # Build lookup: skill display key -> internal key
    skill_key_map: Dict[str, str] = {}
    for skey, sv in raw_skills.items():
        if isinstance(sv, dict) and sv.get("Name"):
            # Also store by common variations
            name = sv["Name"]
            skill_key_map[name.lower()] = skey
            skill_key_map[skey] = skey
            # e.g. "Fire Magic" -> FireMagic
            no_space = name.replace(" ", "").lower()
            skill_key_map[no_space] = skey

    # Build skill -> ability IDs from Skill source entries
    skill_ability_ids: Dict[str, List[str]] = {}
    for aid, skill_name in ability_skill_source.items():
        # The skill_name might be like 'Unarmed', 'Sword', 'FireMagic'
        # Map to internal key
        internal_key = skill_key_map.get(skill_name.lower(), skill_name)
        if internal_key not in skill_ability_ids:
            skill_ability_ids[internal_key] = []
        skill_ability_ids[internal_key].append(aid)

    # Also try matching by the Skill field directly in abilities.json
    for aid, ab in raw_abilities.items():
        if not isinstance(ab, dict):
            continue
        skill = ab.get("Skill", "")
        if skill and skill != "Unknown":
            sk_lower = skill.lower()
            internal_key = skill_key_map.get(sk_lower, skill)
            if internal_key not in skill_ability_ids:
                skill_ability_ids[internal_key] = []
            if aid not in skill_ability_ids[internal_key]:
                skill_ability_ids[internal_key].append(aid)

    # --- Group abilities by skill and ability group ---
    result: Dict[str, dict] = {}

    # Process only non-umbrella skills
    for skey, sv in raw_skills.items():
        if not isinstance(sv, dict):
            continue
        if sv.get("IsUmbrellaSkill"):
            continue
        name = str(sv.get("Name") or skey).strip()
        if not name:
            continue

        result[skey] = {
            "name": name,
            "combat": bool(sv.get("Combat", False)),
            "description": str(sv.get("Description", "")).strip(),
            "xp_table": str(sv.get("XpTable", "")),
            "max_bonus_levels": int(sv.get("MaxBonusLevels", 0)),
            "ability_groups": {},
        }

        # Get all ability IDs for this skill
        ability_ids = skill_ability_ids.get(skey, [])

        # Build ability detail objects
        ability_details: List[dict] = []
        for aid in ability_ids:
            ab = raw_abilities.get(aid)
            if not isinstance(ab, dict):
                continue
            ab_name = str(ab.get("Name", "")).strip()
            if not ab_name:
                continue
            ab_level = int(ab.get("Level", 0))
            desc = str(ab.get("Description", "")).strip()
            internal_name = str(ab.get("InternalName", "")).strip()
            upgrade_of = str(ab.get("UpgradeOf", "")).strip()
            ability_group = str(ab.get("AbilityGroup", "")).strip()
            prereq = str(ab.get("Prerequisite", "")).strip()
            rank = str(ab.get("Rank", "")).strip()

            # Build source info strings for display
            source_strs: List[str] = []
            if aid in ability_item_sources:
                source_strs.append("Item")
            if aid in ability_quest_sources:
                source_strs.append("Quest")
            if aid in ability_gift_sources:
                source_strs.append("NpcGift")
            if not source_strs:
                source_strs.append("Skill Level")

            # Build trainer info
            trainers = ability_trainers.get(aid, [])

            ability_details.append({
                "ability_id": aid,
                "name": ab_name,
                "level": ab_level,
                "description": desc,
                "internal_name": internal_name,
                "upgrade_of": upgrade_of,
                "ability_group": ability_group,
                "prerequisite": prereq,
                "rank": rank,
                "trainers": trainers,
                "sources": source_strs,
            })

        # Group by ability group
        # Strategy: Use AbilityGroup field if present, else use base name
        # (strip trailing number), else use full name
        groups: Dict[str, List[dict]] = {}
        for detail in ability_details:
            group_name = detail["ability_group"]
            if not group_name:
                # Try to derive from base name
                m = re.match(r'^(.*?)\s*(\d+)$', detail["name"])
                if m:
                    group_name = m.group(1).strip()
                else:
                    group_name = detail["name"]

            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(detail)

        # Sort within each group by level
        for gname in groups:
            groups[gname].sort(key=lambda d: d["level"])

        result[skey]["ability_groups"] = groups

    return result


# ---------------------------------------------------------------------------
# Character report loading (reused from original)
# ---------------------------------------------------------------------------

_character_report_cache: Dict[str, dict] = {}


def _load_character_report(character_name: str) -> Optional[dict]:
    if not character_name:
        return None
    clean_name = character_name.split(" (")[0] if " (" in character_name else character_name
    if clean_name in _character_report_cache:
        return _character_report_cache[clean_name]

    pg_base = getattr(config, "PG_BASE", None)
    if not pg_base:
        possible = [
            Path.home() / ".config" / "unity3d" / "Elder Game" / "Project Gorgon",
            Path.home() / "Library" / "Application Support" / "unity.Elder Game.Project Gorgon",
        ]
        for loc in possible:
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
            data = json.load(f)
            _character_report_cache[clean_name] = data
            return data
    except Exception:
        return None


def _get_skill_levels(character_name: str) -> Dict[str, int]:
    report = _load_character_report(character_name)
    if not report:
        return {}
    stats = report.get("CurrentStats") or {}
    levels: Dict[str, int] = {}
    for stat_key, value in stats.items():
        if not isinstance(value, (int, float)):
            continue
        if float(value) > 200 or float(value) < 0:
            continue
        if re.match(r"^[A-Z][A-Z0-9_]+$", stat_key):
            try:
                levels[stat_key] = int(value)
            except (ValueError, TypeError):
                pass
    return levels


def _get_all_characters() -> List[str]:
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
                label = f"{m.group('name')} ({m.group('server')})"
                if label not in seen:
                    seen.add(label)
                    characters.append(label)
            characters.sort(key=lambda s: (s == "Any", s.lower()))
    return characters


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class SkillTrackerWindow:
    """Main Skill Tracker window with tree view."""

    def __init__(self, parent):
        self.parent = parent

        try:
            if hasattr(parent, "create_themed_toplevel"):
                self.window = parent.create_themed_toplevel("skill_tracker", "Skill Tracker")
            else:
                self.window = tk.Toplevel(parent)
                from src.config.window_state import setup_window
                setup_window(self.window, "skill_tracker", min_w=920, min_h=620)
        except Exception:
            self.window = tk.Toplevel(parent)
            self.window.title("PGLOK - Skill Tracker")
            try:
                apply_theme(self.window)
            except Exception:
                pass

        # Always-on-top
        self.always_on_top_var = tk.BooleanVar(value=False)
        if hasattr(self.parent, "_get_ui_pref"):
            try:
                saved = bool(self.parent._get_ui_pref("skill_tracker_always_on_top", False))
                self.always_on_top_var.set(saved)
                if saved:
                    self.window.attributes("-topmost", True)
            except Exception:
                pass

        # State
        self._skill_tree_data: Dict[str, dict] = {}
        self._skill_levels: Dict[str, int] = {}

        # Variables
        self.character_var = tk.StringVar(value="Any")
        self.filter_var = tk.StringVar(value="")
        self.category_var = tk.StringVar(value="All Skills")

        self._build_ui()
        self._load_data()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        shell = ttk.Frame(self.window, padding=8, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Skill Tracker", style="App.Header.TLabel").pack(side="left")

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

        # Filters row
        filters = ttk.Frame(shell, style="App.Panel.TFrame")
        filters.pack(fill="x", pady=(0, 4))

        ttk.Label(filters, text="Character:", style="App.TLabel").pack(side="left")
        self.character_combo = ttk.Combobox(
            filters,
            textvariable=self.character_var,
            state="readonly",
            width=22,
            style="App.TCombobox",
        )
        self.character_combo.pack(side="left", padx=(4, 10))
        self.character_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_character_changed())

        ttk.Label(filters, text="Category:", style="App.TLabel").pack(side="left")
        self.category_combo = ttk.Combobox(
            filters,
            textvariable=self.category_var,
            state="readonly",
            width=16,
            style="App.TCombobox",
        )
        self.category_combo.pack(side="left", padx=(4, 10))
        self.category_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_tree())

        ttk.Label(filters, text="Filter:", style="App.TLabel").pack(side="left")
        filter_entry = ttk.Entry(filters, textvariable=self.filter_var, width=24, style="App.TEntry")
        filter_entry.pack(side="left", padx=(4, 0))
        self.filter_var.trace_add("write", lambda *_: self._refresh_tree())

        # Treeview wrapped in a card
        tree_frame = ttk.Frame(shell, style="App.Card.TFrame", padding=4)
        tree_frame.pack(fill="both", expand=True)

        # Columns
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("info",),
            show="tree",
            selectmode="browse",
            style="App.Treeview",
        )
        self.tree.heading("#0", text="Skill / Ability")
        self.tree.column("#0", width=280, minwidth=200, stretch=True)
        self.tree.column("info", width=600, minwidth=300, stretch=True)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview, style="App.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview, style="App.Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Tag styles
        self.tree.tag_configure("skill_combat", foreground=UI_COLORS.get("rarity_legendary", "#f59e0b"), font=("TkDefaultFont", 10, "bold"))
        self.tree.tag_configure("skill_noncombat", foreground=UI_COLORS["accent"], font=("TkDefaultFont", 10, "bold"))
        self.tree.tag_configure("ability_group", foreground=UI_COLORS["text"], font=("TkDefaultFont", 9, "italic"))
        self.tree.tag_configure("ability_item", foreground=UI_COLORS["muted_text"], font=("TkDefaultFont", 9))
        self.tree.tag_configure("ability_trained", background="#1a3a2a", foreground=UI_COLORS.get("rarity_uncommon", "#22c55e"))
        self.tree.tag_configure("ability_unknown", foreground="#888888")

        # Selection callback
        self.tree.bind("<<TreeviewSelect>>", self._on_item_select)

        # Detail area
        detail_frame = ttk.LabelFrame(shell, text="Details", style="App.TLabelframe", padding=4)
        detail_frame.pack(fill="x", pady=(4, 0))

        self.detail_text = tk.Text(
            detail_frame,
            height=5,
            wrap="word",
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
            state="disabled",
        )
        self.detail_text.pack(fill="x")

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(shell, textvariable=self.status_var, style="App.Muted.TLabel").pack(
            side="bottom", fill="x", pady=(2, 0), anchor="w"
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        """Load skills, abilities, and NPC data."""
        try:
            self._skill_tree_data = build_skill_tree_data()
        except Exception as e:
            messagebox.showerror("Skill Tracker", f"Failed to load data: {e}")
            return

        if not self._skill_tree_data:
            self.status_var.set("skills.json not found; run Download Newer Files.")
        else:
            self.status_var.set(f"Loaded {len(self._skill_tree_data)} skills.")

        # Populate character combo
        chars = _get_all_characters()
        self.character_combo["values"] = chars
        if self.character_var.get() not in chars:
            self.character_var.set("Any")

        # Populate category combo
        cats = ["All Skills", "Combat", "Non-Combat"]
        self.category_combo["values"] = cats
        if self.category_var.get() not in cats:
            self.category_var.set("All Skills")

        self._on_character_changed()

    def _on_character_changed(self) -> None:
        char = self.character_var.get()
        if char and char != "Any":
            clean = char.split(" (")[0] if " (" in char else char
            self._skill_levels = _get_skill_levels(clean)
            self.status_var.set(f"Loaded levels for {clean}.")
        else:
            self._skill_levels = {}
            self.status_var.set("No character selected.")
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Tree population
    # ------------------------------------------------------------------

    def _refresh_tree(self) -> None:
        if not hasattr(self, "tree") or self.tree is None:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

        filter_text = self.filter_var.get().strip().lower()
        category = self.category_var.get()

        # Get sorted skill keys
        combat_keys = []
        noncombat_keys = []
        for skey, sdata in self._skill_tree_data.items():
            name = sdata["name"].lower()
            if filter_text and filter_text not in skey.lower() and filter_text not in name:
                continue
            if category == "Combat" and not sdata["combat"]:
                continue
            if category == "Non-Combat" and sdata["combat"]:
                continue
            if sdata["combat"]:
                combat_keys.append((skey, sdata["name"]))
            else:
                noncombat_keys.append((skey, sdata["name"]))

        combat_keys.sort(key=lambda x: x[1].lower())
        noncombat_keys.sort(key=lambda x: x[1].lower())

        skill_count = 0

        if combat_keys:
            combat_root = self.tree.insert(
                "", "end", text="Combat Skills", open=True,
                tags=("category_combat",),
            )
            self.tree.set(combat_root, "info", "")
            for skey, _sname in combat_keys:
                self._insert_skill_node(combat_root, skey)
                skill_count += 1

        if noncombat_keys:
            noncombat_root = self.tree.insert(
                "", "end", text="Non-Combat Skills", open=True,
                tags=("category_noncombat",),
            )
            self.tree.set(noncombat_root, "info", "")
            for skey, _sname in noncombat_keys:
                self._insert_skill_node(noncombat_root, skey)
                skill_count += 1

        self.status_var.set(f"Showing {skill_count} skills.")

    def _insert_skill_node(self, parent: str, skill_key: str) -> None:
        sdata = self._skill_tree_data.get(skill_key)
        if not sdata:
            return

        name = sdata["name"]
        tag = "skill_combat" if sdata["combat"] else "skill_noncombat"

        # Count total abilities
        total_abilities = sum(len(v) for v in sdata["ability_groups"].values())

        # Get character level for this skill if available
        report_key = skill_key.upper()
        current_level = self._skill_levels.get(report_key, 0)
        level_str = f" (Level {current_level})" if current_level > 0 else ""

        node = self.tree.insert(
            parent, "end",
            text=f"{name}{level_str}",
            open=False,
            tags=(tag,),
        )
        self.tree.set(node, "info", f"{len(sdata['ability_groups'])} abilities / {total_abilities} levels")

        # Insert ability groups
        for group_name in sorted(sdata["ability_groups"].keys(), key=str.lower):
            abilities = sdata["ability_groups"][group_name]
            self._insert_ability_group_node(node, group_name, abilities)

    def _insert_ability_group_node(self, parent: str, group_name: str, abilities: List[dict]) -> None:
        # Determine the range of levels
        levels = [a["level"] for a in abilities]
        level_range = f"lv{min(levels)}-{max(levels)}" if len(levels) > 1 else f"lv{levels[0]}"
        has_trainer = any(a["trainers"] for a in abilities)

        group_node = self.tree.insert(
            parent, "end",
            text=f"  {group_name}  ({level_range})",
            open=False,
            tags=("ability_group",),
        )

        # Insert individual ability levels
        for ab in abilities:
            self._insert_ability_level_node(group_node, ab)

    def _insert_ability_level_node(self, parent: str, ab: dict) -> None:
        name = ab["name"]
        level = ab["level"]
        desc = ab.get("description", "")

        # Build info line
        info_parts = []

        # Trainers
        if ab["trainers"]:
            # Show the best (lowest favor) trainer
            sorted_trainers = sorted(ab["trainers"], key=lambda t: _favor_sort_key(t["favor"]))
            primary = sorted_trainers[0]
            info_parts.append(f"👤 {primary['npc_name']} ({primary['area']}) [{primary['favor']}]")
            if len(sorted_trainers) > 1:
                info_parts.append(f"+{len(sorted_trainers)-1} more")
        else:
            # Show source type
            sources = ab.get("sources", [])
            if sources:
                info_parts.append(f"📦 {', '.join(sources)}")
            else:
                info_parts.append("❓ Unknown source")

        # Prerequisite
        prereq = ab.get("prerequisite", "")
        if prereq:
            info_parts.append(f"Requires: {prereq}")

        info_str = " | ".join(info_parts)

        # Determine tag
        tags = ("ability_item",)
        if ab["trainers"]:
            tags = ("ability_item",)

        ab_node = self.tree.insert(
            parent, "end",
            text=f"    {name}",
            tags=tags,
        )
        self.tree.set(ab_node, "info", info_str)

        # Store ability data for detail view
        self.tree.item(ab_node, values=(ab["ability_id"],))

    # ------------------------------------------------------------------
    # Selection / detail
    # ------------------------------------------------------------------

    def _on_item_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        values = self.tree.item(item, "values")
        if not values or not values[0]:
            # It's a group or skill node — show summary
            self.detail_text.configure(state="normal")
            self.detail_text.delete("1.0", tk.END)
            text = self.tree.item(item, "text")
            info = self.tree.set(item, "info")
            self.detail_text.insert("1.0", f"{text}\n{info}")
            self.detail_text.configure(state="disabled")
            return

        ability_id = values[0]
        # Find the ability data
        for sdata in self._skill_tree_data.values():
            for group_abilities in sdata["ability_groups"].values():
                for ab in group_abilities:
                    if ab["ability_id"] == ability_id:
                        self._show_ability_detail(ab)
                        return

    def _show_ability_detail(self, ab: dict) -> None:
        lines = []
        lines.append(f"📖 {ab['name']} (Level {ab['level']})")
        if ab.get("description"):
            lines.append(f"   {ab['description']}")
        lines.append("")

        # Sources
        if ab["trainers"]:
            lines.append("🏫 Trainers:")
            for tr in sorted(ab["trainers"], key=lambda t: _favor_sort_key(t["favor"])):
                lines.append(f"   • {tr['npc_name']} in {tr['area']} — {tr['favor']}")
        else:
            sources = ab.get("sources", [])
            if sources:
                lines.append(f"📦 Source: {', '.join(sources)}")
            else:
                lines.append("❓ Source unknown")

        # Prerequisites
        prereq = ab.get("prerequisite", "")
        if prereq:
            lines.append(f"   Requires: {prereq}")
        upgrade_of = ab.get("upgrade_of", "")
        if upgrade_of:
            lines.append(f"   Upgrades from: {upgrade_of}")

        # Internal name
        internal = ab.get("internal_name", "")
        if internal:
            lines.append(f"   Internal: {internal}")

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")

    def _toggle_always_on_top(self) -> None:
        enabled = bool(self.always_on_top_var.get())
        try:
            self.window.attributes("-topmost", enabled)
        except Exception:
            pass
        if hasattr(self.parent, "_set_ui_pref"):
            try:
                self.parent._set_ui_pref("skill_tracker_always_on_top", enabled)
            except Exception:
                pass

    def focus(self) -> None:
        self.window.lift()
        self.window.focus_force()
