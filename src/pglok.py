import json
import re
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from datetime import datetime

import sys
from pathlib import Path as _Path

if __package__ in (None, ""):
    _project_root = str(_Path(__file__).resolve().parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

import src.config.config as config
from src import __version__
from src.chat.monitor import ChatLogMonitor
from src.config.ui_theme import UI_ATTRS, UI_TEXT, UI_COLORS, apply_theme, configure_menu_theme
from src.data_index import fetch_rows, get_db_path, index_data_dir, list_indexed_files
from src.itemizer import get_filter_values as itemizer_get_filter_values
from src.itemizer import index_item_reports, search_item_totals, search_items
from src.locate_PG import initialize_pg_base
from src.utils.spellcheck import EntrySpellcheckBinder
from src.updater import perform_auto_update
import sys
import queue
import os
import time

# Import database manager
from src.database.database_manager import get_database_manager

# Import base addon
# Addon base class (optional at runtime)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    addon_root = Path(sys._MEIPASS) / "addons"
else:
    addon_root = Path(__file__).resolve().parent.parent / "addons"

try:
    # Allow import both from the source tree (addons/base_addon.py) and from
    # the frozen bundle where "addons" is next to the executable.
    if addon_root.exists():
        sys.path.insert(0, str(addon_root))
    from base_addon import BaseAddon  # type: ignore
except Exception:
    # If the addons package or BaseAddon is missing, continue without crashing;
    # the Addons menu will simply show as unavailable.
    BaseAddon = object  # fallback placeholder


WINDOW_STATE_FILE = config.CONFIG_DIR / "ui_window_state.json"
GEOMETRY_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)$")
CHARACTER_FILE_RE = re.compile(r"^Character_(?P<name>.+)_(?P<server>[^_]+)\.json$")
CHAT_CHANNEL_RE = re.compile(r"\[(?P<channel>[^\]]+)\]")
MAIN_MIN_WIDTH = 900
MAIN_MIN_HEIGHT = 620
REPO_URL = "https://github.com/jgcampbell300/PGLOK"
RELEASES_URL = f"{REPO_URL}/releases/latest"
GITHUB_RELEASE_API = "https://api.github.com/repos/jgcampbell300/PGLOK/releases/latest"
GITHUB_TAGS_API = "https://api.github.com/repos/jgcampbell300/PGLOK/tags?per_page=1"


def _resolve_icon_path() -> str:
    """Return the path to the app icon (.ico on Windows, .png/.xbm on Linux/macOS)."""
    icon_name = "icon.ico"
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        icon_dir = Path(sys._MEIPASS)
    else:
        icon_dir = Path(__file__).resolve().parent.parent
    icon_path = icon_dir / icon_name
    if icon_path.exists():
        return str(icon_path)
    return ""


class _DebugStreamTee:
    """Mirror stdout/stderr into PGLOK's debug tab without breaking the console."""

    def __init__(self, app, stream, label):
        self.app = app
        self.stream = stream
        self.label = label
        self._buffer = ""

    def write(self, text):
        try:
            self.stream.write(text)
            self.stream.flush()
        except Exception:
            pass
        if not text:
            return
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.app._debug_log(line.rstrip(), source=self.label)

    def flush(self):
        if self._buffer.strip():
            self.app._debug_log(self._buffer.rstrip(), source=self.label)
            self._buffer = ""
        try:
            self.stream.flush()
        except Exception:
            pass


class PGLOKApp:
    def __init__(self, root):
        self.root = root
        self._resize_after_id = None
        self._data_browser_resize_after_id = None
        self._itemizer_resize_after_id = None
        self._clock_after_id = None
        self._window_state_ready = False
        self.settings_window = None
        self.data_browser_window = None
        self.data_browser_paned = None
        self.data_browser_display_paned = None
        self.character_browser_window = None
        self.chat_window = None
        self.itemizer_window = None
        self.map_tools_window = None
        self.map_tools_browser = None
        self.survey_helper_window = None
        self.communications_window = None
        self.timer_window = None
        self.skill_tracker_window = None
        self.home_paned = None
        self.itemizer_paned = None
        self.itemizer_bottom_paned = None
        self.locate_button = None
        self.download_button = None
        self.reset_button = None
        self.data_file_listbox = None
        self.data_rows_tree = None
        self.data_json_text = None
        self.data_browser_font_size = int(self._get_ui_pref("data_browser_font_size", max(9, UI_ATTRS["font_size"])))
        self.data_search_var = tk.StringVar(value=str(self._get_ui_pref("data_browser_search", "")))
        self._data_search_after_id = None
        self.data_page_var = tk.StringVar(value="Page 1")
        self.data_selected_filename = None
        
        # Initialize database manager
        self.db_manager = get_database_manager()
        self.current_user_id = 1  # Default user
        
        self.data_page_size = 200
        self.data_offset = int(self._get_ui_pref("data_browser_offset", 0) or 0)
        self.data_total_rows = 0
        self.itemizer_tree = None
        self.itemizer_json_text = None
        self.itemizer_search_var = tk.StringVar(value=str(self._get_ui_pref("itemizer_search", "")))
        self.itemizer_server_var = tk.StringVar(value=str(self._get_ui_pref("itemizer_server", "")))
        self.itemizer_character_var = tk.StringVar(value=str(self._get_ui_pref("itemizer_character", "")))
        self.itemizer_page_var = tk.StringVar(value="Page 1")
        self.itemizer_totals_var = tk.StringVar(value="Total Qty: 0   Total Value: 0")
        self.itemizer_server_combo = None
        self.itemizer_character_combo = None
        self.itemizer_notes_canvas = None
        self.itemizer_notes_inner = None
        self.itemizer_notes_window_id = None
        self.itemizer_note_vars = {}
        self.itemizer_note_entry_widgets = {}
        self.itemizer_note_row_widgets = {}
        self.itemizer_drag_name = None
        self.itemizer_page_size = 250
        self.itemizer_offset = int(self._get_ui_pref("itemizer_offset", 0) or 0)
        self.itemizer_total_rows = 0
        self._itemizer_search_after_id = None
        self.always_on_top_var = tk.BooleanVar(value=False)
        self.pin_button = None
        self.character_tree = None
        self.character_json_text = None
        self.character_entries = []
        self.chat_monitor = None
        # Player log monitor for player.log file
        self.player_log_monitor = None
        self.player_log_polling = False
        self.player_log_after_id = None
        self.player_log_lines_seen = 0
        # Active Favor Tracker window (if open), used for chat-based item watching
        self.favor_tracker_window = None
        self.chat_polling = False
        self.chat_after_id = None
        self.chat_text = None
        # Chat notebook for integrated chat page
        self.chat_notebook = None
        # Chat tab text widgets for integrated chat page
        self.chat_tab_text = {}
        # Chat notebook for standalone chat window (separate from integrated page)
        self.chat_window_notebook = None
        # Chat tab text widgets for standalone chat window
        self.chat_window_tab_text = {}
        self.chat_info_var = tk.StringVar(value="Lines: 0    Date: --    Time: --    File: None")
        self.chat_lines_seen = 0
        # Comma-separated list of watch terms for the PGLok chat channel
        self.chat_watch_terms_var = tk.StringVar(value=str(self._get_ui_pref("chat_watch_terms", "")))
        # Player log filter (regex or substring) and highlighting settings
        self.player_log_filter_var = tk.StringVar(value=str(self._get_ui_pref("player_log_filter", "")))
        self.player_log_highlight_terms_var = tk.StringVar(value=str(self._get_ui_pref("player_log_highlight_terms", "")))
        self.player_log_highlight_var = tk.BooleanVar(value=self._get_ui_pref("player_log_highlight", True))
        # Persist UI prefs when changed
        try:
            self.player_log_filter_var.trace_add("write", lambda *_: self._set_ui_pref("player_log_filter", self.player_log_filter_var.get()))
            self.player_log_highlight_terms_var.trace_add("write", lambda *_: self._set_ui_pref("player_log_highlight_terms", self.player_log_highlight_terms_var.get()))
            self.player_log_highlight_var.trace_add("write", lambda *_: self._set_ui_pref("player_log_highlight", bool(self.player_log_highlight_var.get())))
        except Exception:
            pass

        # Character and game info tracking
        self.current_character = tk.StringVar(value="Unknown")
        self.current_area = tk.StringVar(value="Unknown")
        self.current_guild = tk.StringVar(value="None")
        # Track last gifted item for favor tracking
        self.last_gifted_item = None
        self.last_gifted_npc = None
        self.last_gifted_time = None

        # Damage tracker – parsed damage events from player.log
        self.damage_events = []  # list of dicts: {source, target, amount, type, timestamp, is_player_damage}
        
        # Add trace to update map when area changes
        self.current_area.trace_add("write", self._on_area_change)
        self.character_count_var = tk.StringVar(value="Characters Loaded: 0")
        self.clock_var = tk.StringVar(value="")
        self.game_clock_var = tk.StringVar(value="")
        self.path_vars = {label: tk.StringVar() for label in UI_TEXT["path_labels"]}
        self.status_var = tk.StringVar(value=UI_TEXT["status_ready"])
        self.global_search_var = tk.StringVar(value=str(self._get_ui_pref("global_search_query", "")))
        self.global_search_results_tree = None
        self.global_search_detail_text = None
        self.global_search_paned = None
        self.global_search_results = []
        self._global_search_after_id = None
        self.alpha_button = None
        self.pin_var = tk.BooleanVar(value=False)
        self.entry_spellcheck = EntrySpellcheckBinder()
        
        # Timer configuration variables
        self.timer_auto_start_var = tk.BooleanVar(value=self._get_ui_pref("timer_auto_start", True))
        self.timer_scan_interval_var = tk.IntVar(value=self._get_ui_pref("timer_scan_interval", 5))
        self.timer_notification_var = tk.BooleanVar(value=self._get_ui_pref("timer_notifications", True))
        # Chat monitor auto-start preference
        self.chat_auto_start_var = tk.BooleanVar(value=self._get_ui_pref("chat_auto_start", True))
        
        # Addon manager will be initialized lazily
        self.addon_manager = None
        self.addons_menu = None
        
        # Player position monitor
        self.player_monitor = None
        self.player_position_var = tk.StringVar(value="")
        self._player_pos_after_id = None
        self._debug_lock = threading.Lock()
        self._debug_buffer = []
        self._debug_flush_after_id = None
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._stdout_tee = _DebugStreamTee(self, self._orig_stdout, "stdout")
        self._stderr_tee = _DebugStreamTee(self, self._orig_stderr, "stderr")
        sys.stdout = self._stdout_tee
        sys.stderr = self._stderr_tee
        try:
            self.status_var.trace_add("write", lambda *_: self._debug_log(self.status_var.get(), source="status"))
        except Exception:
            pass
        self._debug_log("PGLOK startup initialized")

        apply_theme(self.root)
        self.root.title(UI_ATTRS["window_title"])
        self.data_search_var.trace_add("write", lambda *_: self._schedule_data_live_search())
        self.itemizer_search_var.trace_add("write", lambda *_: self._schedule_itemizer_live_search())

        self.app_frame = ttk.Frame(root, padding=(4, 2, 4, 4), style="App.Panel.TFrame")
        self.app_frame.pack(fill="both", expand=True)

        self._build_layout()
        self._build_menu_bar()
        self.root.after(250, self._poll_debug_buffer)
        self._apply_startup_geometry()
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh_config_view()
        self._restore_always_on_top_state()
        self.show_page("chat")
        self._update_clock()

        # Enable main-window persistence only after startup layout settles.
        self.root.after(1000, self._enable_main_window_state_persistence)

        # Defer heavier startup tasks so the window appears faster.
        self.root.after(250, self._refresh_character_cache)
        self.root.after(750, self._start_deferred_startup_tasks)

        # Restore any windows that were open when the app last closed.
        self.root.after(1000, self._restore_open_windows)

        # Auto-start chat monitor if enabled
        if self.chat_auto_start_var.get():
            self.root.after(500, self._try_start_chat_monitor)

    def _build_layout(self):
        # Toolbar
        toolbar = ttk.Frame(self.app_frame, style="App.Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 3))
        ttk.Button(
            toolbar,
            text="Characters",
            command=self.open_character_browser_window,
            style="App.Secondary.TButton",
        ).pack(side="left")
        ttk.Button(toolbar, text="Timers", command=self._open_timer, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )
        ttk.Button(toolbar, text="Itemizer", command=self.open_itemizer_window, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )
        ttk.Button(toolbar, text="Maps", command=self.open_map_tools_window, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )
        ttk.Button(toolbar, text="Planner", command=self._open_planner, style="App.Secondary.TButton").pack(side="left", padx=(3, 0))
        ttk.Button(toolbar, text="Skills", command=self._open_skill_tracker, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )

        # Right side: Always on Top toggle + Alpha version button
        self.pin_button = ttk.Checkbutton(
            toolbar,
            text="Always on Top",
            variable=self.pin_var,
            command=self._toggle_always_on_top,
            style="App.TCheckbutton",
        )
        self.pin_button.pack(side="right", padx=(0, 4))

        self.alpha_button = ttk.Button(
            toolbar,
            text=f"ALPHA v{__version__}",
            command=lambda: webbrowser.open(REPO_URL),
            style="App.Secondary.TButton",
        )
        self.alpha_button.pack(side="right")

        # Status bar (pinned to bottom) - pack FIRST to reserve space
        self.status_section = ttk.Frame(self.app_frame, style="App.Panel.TFrame")
        self.status_section.pack(fill="x", side="bottom")
        
        # Create persistent status bar
        self._create_status_bar()

        # Content area (expands to fill remaining space)
        self.page_container = ttk.Frame(self.app_frame, style="App.Panel.TFrame")
        self.page_container.pack(fill="both", expand=True)

        self.home_page = ttk.Frame(self.page_container, style="App.Panel.TFrame")
        self._build_home_page()

        # Chat page (initially hidden)
        self.chat_page = ttk.Frame(self.page_container, style="App.Panel.TFrame")
        self._build_chat_page()

    def _create_status_bar(self):
        """Create the persistent status bar."""
        # Main status bar frame with minimal padding
        status_frame = ttk.Frame(self.status_section, style="App.Card.TFrame", padding=2)
        status_frame.pack(fill="x", expand=True)
        
        # Single status row
        status_row = ttk.Frame(status_frame, style="App.Panel.TFrame")
        status_row.pack(fill="x")
        status_row.columnconfigure(1, weight=1)  # Center section expands
        
        # Left status - icon and status text
        left_status = ttk.Frame(status_row, style="App.Panel.TFrame")
        left_status.grid(row=0, column=0, sticky="w")
        
        self.status_icon = ttk.Label(left_status, text="●", style="App.Status.TLabel", foreground="#8d321e")
        self.status_icon.pack(side="left")
        ttk.Label(left_status, textvariable=self.status_var, style="App.Status.TLabel").pack(side="left", padx=(4, 8))
        
        # Center status - character info (expands)
        self.center_status = ttk.Frame(status_row, style="App.Panel.TFrame")
        self.center_status.grid(row=0, column=1, sticky="we")
        self.center_info_var = tk.StringVar(value="")
        ttk.Label(self.center_status, textvariable=self.center_info_var, style="App.Muted.TLabel").pack(side="left")
        
        # Update center status with character info
        self._update_center_status()
        
        # Right status - character count and clocks
        right_status = ttk.Frame(status_row, style="App.Panel.TFrame")
        right_status.grid(row=0, column=2, sticky="e")
        ttk.Label(right_status, textvariable=self.character_count_var, style="App.Status.TLabel").pack(side="left")
        ttk.Label(right_status, text="   ", style="App.Status.TLabel").pack(side="left")
        ttk.Label(right_status, textvariable=self.clock_var, style="App.Status.TLabel").pack(side="left")
        ttk.Label(right_status, text="   ", style="App.Status.TLabel").pack(side="left")
        ttk.Label(right_status, textvariable=self.game_clock_var, style="App.Status.TLabel").pack(side="left")
        
        # Progress bar (hidden by default, shown below status when needed)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            status_frame, 
            variable=self.progress_var, 
            mode="determinate", 
            style="App.Horizontal.TProgressbar",
            length=200
        )
        # Progress bar will be shown/hidden as needed
        
        # Store reduced status height
        self.status_height = 35  # Reduced height for cleaner status bar
        
    def show_progress(self, message, value=0):
        """Show progress in status bar."""
        self.status_var.set(message)
        self.progress_var.set(value)
        
        # Show progress bar if value > 0
        if value > 0:
            self.progress_bar.pack(side="right", padx=(10, 0))
        else:
            # Hide progress bar after a delay
            self.root.after(2000, lambda: self.progress_bar.pack_forget())
    
    def set_center_status(self, message):
        """Set center status information."""
        self.center_info_var.set(message)
        
    def _update_center_status(self):
        """Update center status with current character info."""
        char = self.current_character.get()
        area = self.current_area.get()
        pos_str = self.player_position_var.get()
        if char and char != "Unknown":
            if pos_str:
                self.set_center_status(f"👤 {char}  📍 {area}  📍 {pos_str}")
            else:
                self.set_center_status(f"👤 {char}  📍 {area}")
        else:
            self.set_center_status("")

    def _get_estimated_game_time(self, now=None):
        """Estimate in-game time from real time using a 12x speed ratio.

        PGLOK currently does not have a trusted in-game clock source in logs,
        so this provides a readable approximation based on the 1 hour game =
        5 minutes real rule.
        """
        current = now or datetime.now()
        real_seconds = (current.hour * 3600) + (current.minute * 60) + current.second
        game_seconds = (real_seconds * 12) % 86400
        hours_24 = game_seconds // 3600
        minutes = (game_seconds % 3600) // 60
        am_pm = "AM" if hours_24 < 12 else "PM"
        hours_12 = hours_24 % 12
        if hours_12 == 0:
            hours_12 = 12
        return f"🎮 Est. Game {hours_12}:{minutes:02d} {am_pm}"

    def _update_clock(self):
        """Update the visible real-world clock and estimated game clock."""
        now = datetime.now()
        try:
            self.clock_var.set(now.strftime("🕒 %I:%M:%S %p").lstrip("0"))
            self.game_clock_var.set(self._get_estimated_game_time(now))
        except Exception:
            pass
        try:
            self._clock_after_id = self.root.after(1000, self._update_clock)
        except Exception:
            self._clock_after_id = None

    def _flush_debug_buffer(self):
        if not getattr(self, "_debug_buffer", None):
            return
        with self._debug_lock:
            pending = self._debug_buffer[:]
            self._debug_buffer.clear()
            self._debug_flush_after_id = None
        for message, source in pending:
            self._append_chat_line("Debug", f"[{source}] {message}", notebook=self.chat_notebook, tab_text_dict=self.chat_tab_text)

    def _schedule_debug_flush(self):
        if threading.current_thread() is not threading.main_thread():
            return
        if self._debug_flush_after_id is not None:
            return
        try:
            self._debug_flush_after_id = self.root.after(250, self._poll_debug_buffer)
        except Exception:
            self._debug_flush_after_id = None

    def _poll_debug_buffer(self):
        self._debug_flush_after_id = None
        self._flush_debug_buffer()
        try:
            self._debug_flush_after_id = self.root.after(250, self._poll_debug_buffer)
        except tk.TclError:
            self._debug_flush_after_id = None

    def _debug_log(self, message, source="debug"):
        text = str(message).strip()
        if not text:
            return
        if threading.current_thread() is not threading.main_thread() or self.chat_notebook is None:
            with self._debug_lock:
                self._debug_buffer.append((text, source))
            self._schedule_debug_flush()
            return
        self._append_chat_line("Debug", f"[{source}] {text}", notebook=self.chat_notebook, tab_text_dict=self.chat_tab_text)
    
    def _start_deferred_startup_tasks(self):
        """Run heavier startup tasks after the UI is visible."""
        try:
            if config.PG_BASE is None:
                self.locate_pg()
        except Exception as exc:
            print(f"Deferred locate failed: {exc}")

        try:
            self._check_for_upgrade_async()
        except Exception as exc:
            print(f"Deferred update check failed: {exc}")

        try:
            self._start_player_monitor()
        except Exception as exc:
            print(f"Deferred player monitor failed: {exc}")

    def _start_player_monitor(self):
        """Initialize and start the player position monitor."""
        try:
            from src.player.monitor import PlayerLogMonitor
            self.player_monitor = PlayerLogMonitor()
            self._poll_player_position()
        except Exception as e:
            print(f"Failed to start player monitor: {e}")
    
    def _poll_player_position(self):
        """Poll for player position updates."""
        if self.player_monitor:
            try:
                pos = self.player_monitor.get_latest_position()
                if pos:
                    pos_str = f"X:{pos.x:.1f} Y:{pos.y:.1f} Z:{pos.z:.1f}"
                    self.player_position_var.set(pos_str)
                    self._update_center_status()
            except Exception:
                pass  # Silently fail - position tracking is optional
        
        # Schedule next poll in 2 seconds
        self._player_pos_after_id = self.root.after(2000, self._poll_player_position)
        
    def set_status_color(self, color):
        """Set status icon color."""
        try:
            self.status_icon.configure(foreground=color)
        except:
            pass
    
    def _select_all_text(self, entry_widget):
        """Select all text in an entry widget when clicked."""
        # Schedule selection to ensure it happens after the default click behavior
        entry_widget.after(10, lambda: entry_widget.select_range(0, 'end'))
        # Ensure focus is on the entry
        entry_widget.focus_set()

    def _build_menu_bar(self):
        menu_bar = tk.Menu(self.root)
        configure_menu_theme(menu_bar)
        self.root.config(menu=menu_bar)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        configure_menu_theme(file_menu)
        file_menu.add_command(label="Home", command=lambda: self.show_page("home"))
        file_menu.add_command(label="Download Newer Files", command=self.download_newer_files)
        file_menu.add_command(label="Locate Project Gorgon", command=self.locate_pg)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menu_bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=0)
        configure_menu_theme(edit_menu)
        edit_menu.add_command(label="Settings", command=self.open_settings_window)
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy", command=self._menu_not_implemented)
        edit_menu.add_command(label="Paste", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu_bar, tearoff=0)
        configure_menu_theme(view_menu)
        view_menu.add_command(label="Home", command=lambda: self.show_page("home"))
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Always on Top", variable=self.pin_var, command=self._toggle_always_on_top)
        menu_bar.add_cascade(label="View", menu=view_menu)

        document_menu = tk.Menu(menu_bar, tearoff=0)
        configure_menu_theme(document_menu)
        document_menu.add_command(label="📁 Config Folder", command=self._open_config_folder)
        document_menu.add_command(label="📁 Data Folder", command=self._open_data_folder)
        document_menu.add_command(label="📁 Maps Folder", command=self._open_maps_folder)
        document_menu.add_command(label="📁 Chat Logs Folder", command=self._open_chat_logs_folder)
        document_menu.add_command(label="📁 Reports Folder", command=self._open_reports_folder)
        document_menu.add_separator()
        document_menu.add_command(label="Open Config Folder", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Document", menu=document_menu)

        tools_menu = tk.Menu(menu_bar, tearoff=0)
        configure_menu_theme(tools_menu)
        # Tools menu entries sorted alphabetically by label (excluding items now in File menu)
        tools_menu.add_command(label="Character Browser", command=self.open_character_browser_window)
        tools_menu.add_command(label="Communications", command=self._open_communications_window)
        tools_menu.add_command(label="Data Browser", command=self.open_data_browser_window)
        tools_menu.add_command(label="Favor Tracker", command=self._open_favor_tracker)
        tools_menu.add_command(label="Fletcher", command=self._open_fletcher)
        tools_menu.add_command(label="Food Comparison", command=self._open_food_comparison)
        tools_menu.add_command(label="Itemizer", command=self.open_itemizer_window)
        tools_menu.add_command(label="Maps", command=self.open_map_tools_window)
        tools_menu.add_command(label="Planner", command=self._open_planner)
        tools_menu.add_command(label="Skill Tracker", command=self._open_skill_tracker)
        tools_menu.add_command(label="Survey Helper", command=self._open_survey_helper)
        tools_menu.add_command(label="Timer", command=self._open_timer)
        menu_bar.add_cascade(label="Tools", menu=tools_menu)

        # Addons menu
        try:
            # Check if addons should be enabled (can be disabled if causing issues)
            enable_addons = True  # Set to False to disable addon system
            
            if enable_addons:
                addons_menu = tk.Menu(menu_bar, tearoff=0)
                configure_menu_theme(addons_menu)
                self.addons_menu = addons_menu
                self._create_addons_menu()
                menu_bar.add_cascade(label="Addons", menu=addons_menu)
            else:
                # Addons disabled
                addons_menu = tk.Menu(menu_bar, tearoff=0)
                configure_menu_theme(addons_menu)
                addons_menu.add_command(label="Addons Disabled", state="disabled")
                menu_bar.add_cascade(label="Addons", menu=addons_menu)
                
        except Exception as e:
            print(f"Warning: Failed to create addons menu: {e}")
            # Create a disabled addons menu as fallback
            addons_menu = tk.Menu(menu_bar, tearoff=0)
            configure_menu_theme(addons_menu)
            addons_menu.add_command(label="Addons Unavailable", state="disabled")
            menu_bar.add_cascade(label="Addons", menu=addons_menu)

        help_menu = tk.Menu(menu_bar, tearoff=0)
        configure_menu_theme(help_menu)
        help_menu.add_command(label="Check for Updates", command=self._check_for_updates_manual)
        help_menu.add_separator()
        help_menu.add_command(label="About PGLOK", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Help", menu=help_menu)

    def _check_for_updates_manual(self):
        """Manual update check with progress dialog."""
        event_queue = queue.Queue()

        progress_window = tk.Toplevel(self.root)
        progress_window.title("Checking for Updates")
        progress_window.geometry("500x300")
        progress_window.resizable(False, False)

        progress_window.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width() or self.root.winfo_reqwidth()
        root_h = self.root.winfo_height() or self.root.winfo_reqheight()
        x = root_x + max(0, (root_w - 500) // 2)
        y = root_y + max(0, (root_h - 300) // 2)
        progress_window.geometry(f"500x300+{x}+{y}")

        main_frame = ttk.Frame(progress_window, style="App.Card.TFrame", padding=20)
        main_frame.pack(fill="both", expand=True)

        ttk.Label(main_frame, text="PGLOK Update", style="App.Title.TLabel").pack(pady=(0, 15))

        status_var = tk.StringVar(value="Checking for updates...")
        ttk.Label(main_frame, textvariable=status_var, style="App.Status.TLabel").pack(pady=10, anchor="w")

        progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(
            main_frame,
            variable=progress_var,
            mode="indeterminate",
            style="App.Horizontal.TProgressbar",
        )
        progress_bar.pack(fill="x", pady=10)
        progress_bar.start(10)

        details_frame = ttk.Frame(main_frame)
        details_frame.pack(fill="both", expand=True, pady=10)

        details_text = tk.Text(
            details_frame,
            height=8,
            wrap="word",
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
        )
        details_scroll = ttk.Scrollbar(details_frame, orient="vertical", command=details_text.yview, style="App.Vertical.TScrollbar")
        details_text.configure(yscrollcommand=details_scroll.set)
        details_text.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")

        close_button = ttk.Button(main_frame, text="Close", command=progress_window.destroy, state="normal", style="App.Primary.TButton")
        close_button.pack(pady=(10, 0))

        def enqueue(kind, payload=None):
            event_queue.put((kind, payload))

        def poll_events():
            if not progress_window.winfo_exists():
                return

            try:
                while True:
                    kind, payload = event_queue.get_nowait()
                    if kind == "status":
                        text = str(payload)
                        status_var.set(text)
                        details_text.insert(tk.END, f"[{self._get_timestamp()}] {text}\n")
                        details_text.see(tk.END)
                    elif kind == "details":
                        details_text.insert(tk.END, str(payload))
                        details_text.see(tk.END)
                    elif kind == "progress":
                        progress_var.set(float(payload))
                    elif kind == "enable_close":
                        progress_bar.stop()
                        close_button.configure(state="normal")
                    elif kind == "restart":
                        delay = int(payload or 0)

                        def restart_after_delay():
                            try:
                                progress_window.destroy()
                            except tk.TclError:
                                pass
                            self._restart_application()

                        progress_window.after(delay, restart_after_delay)
                    elif kind == "set_status":
                        status_var.set(str(payload))
                    elif kind == "error":
                        progress_bar.stop()
                        close_button.configure(state="normal")
                        text = str(payload)
                        status_var.set(f"Update check failed: {text}")
                        details_text.insert(tk.END, f"\n❌ Error: {text}\n")
                        details_text.insert(tk.END, "Please try again or check your internet connection.\n")
                        details_text.see(tk.END)
            except queue.Empty:
                pass
            except tk.TclError:
                return

            if progress_window.winfo_exists():
                try:
                    progress_window.after(100, poll_events)
                except tk.TclError:
                    return

        def worker():
            try:
                enqueue("status", "Checking for updates...")
                enqueue("progress", 10)

                from src.updater import fetch_latest_repo_version, parse_version_key

                latest_version, assets = fetch_latest_repo_version()
                enqueue("progress", 30)

                if not latest_version:
                    enqueue("status", "Unable to check for updates")
                    enqueue("details", "\nCould not connect to GitHub to check for updates.\n")
                    enqueue("details", "Please check your internet connection and try again.\n")
                    enqueue("enable_close")
                    return

                current_key = parse_version_key(__version__)
                latest_key = parse_version_key(latest_version)

                enqueue("progress", 50)
                enqueue("status", f"Current version: {__version__}")
                enqueue("status", f"Latest version: {latest_version}")

                if current_key is None or latest_key is None or latest_key <= current_key:
                    enqueue("status", "PGLOK is up to date!")
                    enqueue("details", f"\nYou are running the latest version ({__version__}).\n")
                    enqueue("status", "Refreshing CDN data files...")
                    try:
                        from src.data_acquisition import main as run_data_acquisition
                        run_data_acquisition()
                        enqueue("details", "\n✅ CDN data refresh completed.\n")
                    except Exception as data_exc:
                        enqueue("details", f"\n⚠ CDN data refresh failed: {data_exc}\n")
                    enqueue("details", "\nYou can continue using PGLOK while this window stays open, or close it now.\n")
                    enqueue("progress", 100)
                    enqueue("enable_close")
                    return

                enqueue("status", f"Update available: {__version__} → {latest_version}")
                enqueue("progress", 70)

                if assets:
                    enqueue("details", "\nAvailable release assets:\n")
                    for i, asset in enumerate(assets, 1):
                        size_mb = asset.get("size", 0) / (1024 * 1024)
                        enqueue("details", f"  {i}. {asset['name']} ({size_mb:.1f}MB)\n")

                enqueue("status", "Downloading update...")
                enqueue("progress", 80)

                from src.updater import perform_auto_update
                update_success = perform_auto_update(__version__)

                enqueue("progress", 90)

                if update_success:
                    enqueue("status", "Update completed successfully!")
                    enqueue("details", "\n✅ Update has been installed successfully.\n")
                    enqueue("details", "The application will restart to apply the update.\n")
                    enqueue("progress", 100)
                    enqueue("enable_close")
                    enqueue("restart", 3000)
                else:
                    enqueue("status", "Update failed")
                    enqueue("details", "\n❌ Automatic update failed.\n")
                    enqueue("details", "You can download the update manually from:\n")
                    enqueue("details", "https://github.com/jgcampbell300/PGLOK/releases/latest\n")
                    enqueue("enable_close")
            except Exception as exc:
                enqueue("error", exc)

        def on_close():
            try:
                progress_window.destroy()
            except tk.TclError:
                pass

        progress_window.protocol("WM_DELETE_WINDOW", on_close)
        poll_events()
        threading.Thread(target=worker, daemon=True).start()
    
    def _get_timestamp(self):
        """Get current timestamp for log entries."""
        import datetime
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _create_addons_menu(self):
        """Create the Addons menu with discovered addons."""
        try:
            # Initialize addon manager if needed
            if self.addon_manager is None:
                from src.addons import AddonManager
                self.addon_manager = AddonManager(self)
            
            if self.addon_manager and hasattr(self.addon_manager, 'create_addons_menu'):
                self.addon_manager.create_addons_menu(self.addons_menu)
            else:
                if self.addons_menu:
                    self.addons_menu.add_command(label="No Addon Manager", state="disabled")
                    
        except Exception as e:
            print(f"Warning: Failed to create addons menu: {e}")
            if self.addons_menu:
                self.addons_menu.add_command(label="Addons Error", state="disabled")

    def _check_for_upgrade_async(self):
        """Check for updates and automatically install if available."""
        event_queue = queue.Queue()

        def poll_events():
            if not self.root.winfo_exists():
                return

            try:
                while True:
                    kind, payload = event_queue.get_nowait()
                    if kind == "success":
                        messagebox.showinfo(
                            "Update Complete",
                            "PGLOK has been updated successfully!\n\nThe application will restart to apply the update.",
                        )
                        self.root.after(1000, self._restart_application)
                    elif kind == "available":
                        latest_version = str(payload)
                        if self.alpha_button is not None:
                            self.alpha_button.configure(
                                text="Update Available!",
                                command=lambda: webbrowser.open(RELEASES_URL),
                            )
                        self.status_var.set(f"Update available: {__version__} → {latest_version}")
                    elif kind == "up_to_date":
                        self.status_var.set("PGLOK is up to date")
                    elif kind == "unable_to_check":
                        self.status_var.set("Unable to check for updates")
                    elif kind == "error":
                        self.status_var.set(f"Update check failed: {payload}")
                    elif kind == "done":
                        return
            except queue.Empty:
                pass
            except tk.TclError:
                return

            try:
                self.root.after(100, poll_events)
            except tk.TclError:
                pass

        def worker():
            try:
                from src.updater import fetch_latest_repo_version, parse_version_key

                latest_version, _ = fetch_latest_repo_version()
                if not latest_version:
                    event_queue.put(("unable_to_check", None))
                    event_queue.put(("done", None))
                    return

                current_key = parse_version_key(__version__)
                latest_key = parse_version_key(latest_version)

                if current_key is None or latest_key is None or latest_key <= current_key:
                    event_queue.put(("up_to_date", None))
                    event_queue.put(("done", None))
                    return

                update_success = perform_auto_update(__version__)
                if update_success:
                    event_queue.put(("success", None))
                else:
                    event_queue.put(("available", latest_version))
                event_queue.put(("done", None))
            except Exception as exc:
                event_queue.put(("error", str(exc)))
                event_queue.put(("done", None))

        poll_events()
        threading.Thread(target=worker, daemon=True).start()
    
    def _restart_application(self):
        """Restart the application."""
        try:
            # Get current executable path
            executable = sys.executable
            if sys.executable.endswith('python') or sys.executable.endswith('python3'):
                # We're running from source, restart with main script
                script_path = Path(__file__).resolve().parent / 'pglok.py'
                subprocess.Popen([executable, str(script_path)])
            else:
                # We're running from executable
                subprocess.Popen([executable])
            
            # Exit current instance
            self.root.quit()
        except Exception as e:
            messagebox.showerror("Restart Failed", f"Failed to restart application: {e}")

    def _menu_not_implemented(self):
        self.status_var.set("Menu action not implemented yet.")

    def _open_folder_in_system(self, folder_path, success_label: str, error_label: str, create: bool = False):
        """Open a folder in the operating system file browser."""
        try:
            import platform
            import subprocess

            system = platform.system()
            if create and not folder_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)

            folder_path_str = str(folder_path)

            if system == "Windows":
                subprocess.run(["explorer", folder_path_str])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path_str])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path_str])

            self.status_var.set(f"Opened {success_label}: {folder_path_str}")
        except Exception as e:
            self.status_var.set(f"Error opening {error_label}: {e}")

    def _open_config_folder(self):
        """Open the PGLOK config folder."""
        self._open_folder_in_system(config.CONFIG_DIR, "config folder", "config folder")

    def _open_data_folder(self):
        """Open the PGLOK data folder."""
        self._open_folder_in_system(config.DATA_DIR, "data folder", "data folder")

    def _open_maps_folder(self):
        """Open the PGLOK maps folder."""
        self._open_folder_in_system(config.DATA_DIR / "maps", "maps folder", "maps folder", create=True)

    def _open_chat_logs_folder(self):
        """Open the PGLOK chat logs folder."""
        try:
            if config.PG_BASE is None:
                initialize_pg_base(force=True)

            if config.PG_BASE is None:
                self.status_var.set("Project Gorgon not located - cannot open chat logs")
                return

            self._open_folder_in_system(config.CHAT_DIR, "chat logs folder", "chat logs folder")
        except Exception as e:
            self.status_var.set(f"Error opening chat logs folder: {e}")

    def _open_reports_folder(self):
        """Open the PGLOK reports folder."""
        try:
            reports_dir = self._get_reports_dir()
            if reports_dir is None:
                self.status_var.set("Project Gorgon not located - cannot open reports")
                return

            self._open_folder_in_system(reports_dir, "reports folder", "reports folder")
        except Exception as e:
            self.status_var.set(f"Error opening reports folder: {e}")

    def _open_survey_helper(self):
        """Open the Survey Helper window."""
        try:
            from src.survey import open_survey_helper
            if self.survey_helper_window is None or not self.survey_helper_window.winfo_exists():
                self.survey_helper_window = open_survey_helper(self.root)
            else:
                self.survey_helper_window.lift()
            self.status_var.set("Survey Helper opened")
        except Exception as e:
            self.status_var.set(f"Error opening survey helper: {e}")
            import traceback
            traceback.print_exc()

    def _open_fletcher(self):
        self.status_var.set("Fletcher is not implemented yet.")

    def _open_itemizer(self):
        self.open_itemizer_window()

    def _open_planner(self):
        self.status_var.set("Planner is not implemented yet.")

    def _open_timer(self):
        """Open the timer window."""
        try:
            if self.timer_window is not None:
                try:
                    if self.timer_window.window.winfo_exists():
                        self.timer_window.window.deiconify()
                        self.timer_window.window.lift()
                        self.timer_window.window.focus_force()
                        self.status_var.set("Timer window opened")
                        return
                except Exception:
                    self.timer_window = None

            from src.timer_window import TimerWindow
            from pathlib import Path

            chat_dir = None
            if config.PG_BASE is not None:
                chat_dir = Path(config.PG_BASE) / "ChatLogs"
                if not chat_dir.exists():
                    chat_dir = None

            self.timer_window = TimerWindow(self, config.DATA_DIR, chat_dir)
            self.status_var.set("Timer window opened")

        except Exception as e:
            self.status_var.set(f"Error opening timer: {e}")
            import traceback
            traceback.print_exc()

    def _open_skill_tracker(self):
        """Open the Skill Tracker window."""
        try:
            if self.skill_tracker_window is not None:
                try:
                    if self.skill_tracker_window.window.winfo_exists():
                        self.skill_tracker_window.window.deiconify()
                        self.skill_tracker_window.window.lift()
                        self.skill_tracker_window.window.focus_force()
                        self.status_var.set("Skill Tracker opened")
                        return
                except Exception:
                    self.skill_tracker_window = None

            from src.skill_tracker import SkillTrackerWindow

            self.skill_tracker_window = SkillTrackerWindow(self)
            self.status_var.set("Skill Tracker opened")

        except Exception as e:
            self.status_var.set(f"Error opening Skill Tracker: {e}")
            import traceback
            traceback.print_exc()

    def _open_chat(self):
        """Show the integrated chat page in the main window."""
        self.show_page("chat")
    
    def _open_duration_manager(self):
        """Open the duration manager window."""
        self.status_var.set("Duration manager not implemented yet.")

    def _open_food_comparison(self):
        """Open the food comparison and tracking window."""
        try:
            from src.food_comparison import FoodComparisonWindow

            character = self.current_character.get() if hasattr(self, 'current_character') else "Unknown"
            # Pass self so the window can use create_themed_toplevel and shared settings
            food_window = FoodComparisonWindow(self, character)
            self.status_var.set("Food comparison window opened")
        except Exception as e:
            self.status_var.set(f"Error opening food comparison: {e}")
            import traceback
            traceback.print_exc()

    def _open_favor_tracker(self):
        """Open the Favor Tracker window."""
        try:
            from src.favor_tracker import FavorTrackerWindow

            # Reuse existing Favor Tracker window when possible
            if self.favor_tracker_window is not None:
                try:
                    if self.favor_tracker_window.window.winfo_exists():
                        self.favor_tracker_window.focus()
                        self.status_var.set("Favor Tracker opened")
                        return
                except Exception:
                    self.favor_tracker_window = None

            window = FavorTrackerWindow(self)
            self.favor_tracker_window = window
            self._set_window_open_state("favor_tracker", True)
            self.status_var.set("Favor Tracker opened")
        except Exception as e:
            self.status_var.set(f"Error opening Favor Tracker: {e}")
            import traceback
            traceback.print_exc()

    def _open_communications_window(self):
        """Open the Communications window for MQTT chat and data sharing."""
        try:
            # Reuse existing Communications window when possible
            if self.communications_window is not None:
                try:
                    if self.communications_window.window.winfo_exists():
                        self.communications_window.window.lift()
                        self.status_var.set("Communications opened")
                        return
                except Exception:
                    self.communications_window = None

            # Get character name from detected game info
            character_name = self.current_character.get().strip()
            if not character_name or character_name == "Unknown" or character_name == "":
                character_name = "Unknown"

            # Create window with app reference
            from src.communications.communications_window import CommunicationsWindow
            window = CommunicationsWindow(self.root, character_name)
            self.communications_window = window
            
            # Bind close event
            window.window.protocol("WM_DELETE_WINDOW", self._on_close_communications_window)
            # Persist open state so restore logic can reopen this window
            try:
                self._set_window_open_state("communications", True)
            except Exception:
                pass
            self.status_var.set("Communications opened")
        except Exception as e:
            self.status_var.set(f"Error opening Communications: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_close_communications_window(self):
        """Handle communications window close."""
        if self.communications_window is not None and self.communications_window.window.winfo_exists():
            self.communications_window._cleanup_mqtt()
            self.communications_window.window.destroy()
        self.communications_window = None
        try:
            self._set_window_open_state("communications", False)
        except Exception:
            pass
    
    
    def _save_timer_settings(self):
        """Save timer settings to preferences."""
        try:
            self._set_ui_pref("timer_auto_start", self.timer_auto_start_var.get())
            self._set_ui_pref("timer_scan_interval", self.timer_scan_interval_var.get())
            self._set_ui_pref("timer_notifications", self.timer_notification_var.get())
            self.status_var.set("Timer settings saved")
        except Exception as e:
            self.status_var.set(f"Error saving timer settings: {e}")

    def _save_chat_settings(self):
        """Save chat monitor settings to preferences."""
        try:
            self._set_ui_pref("chat_auto_start", self.chat_auto_start_var.get())
            self.status_var.set("Chat settings saved")
        except Exception as e:
            self.status_var.set(f"Error saving chat settings: {e}")
    
    def apply_theme_to_window(self, window):
        """Apply PGLOK theme to a window."""
        try:
            import src.config.ui_theme as ui_theme
            
            # Apply base theme like PGLOK does
            window.configure(bg=ui_theme.UI_COLORS["bg"])
            window.option_add("*Font", (ui_theme.UI_ATTRS["font_family"], ui_theme.UI_ATTRS["font_size"]))
            
            # Apply ttk styling like PGLOK
            style = ttk.Style(window)
            style.theme_use("clam")
            
            # Configure PGLOK frame style
            style.configure(
                "App.TFrame",
                background=ui_theme.UI_COLORS["bg"],
                relief="flat",
            )
            
            return ui_theme.UI_COLORS, ui_theme.UI_ATTRS
        except ImportError:
            # Fallback theme application
            from src.config.ui_theme import UI_COLORS, UI_ATTRS
            window.configure(bg=UI_COLORS["bg"])
            window.option_add("*Font", (UI_ATTRS["font_family"], UI_ATTRS["font_size"]))
            return UI_COLORS, UI_ATTRS

    def create_themed_toplevel(self, name, title_suffix, on_close=None):
        """Create a Toplevel with the PGLOK theme, standard title and persistent geometry.

        name: identifier used by caller for saved geometry keys (for callers' use).
        title_suffix: displayed after the app title.
        on_close: optional callable to set as WM_DELETE_WINDOW handler.
        """
        win = tk.Toplevel(self.root)
        win.title(f"{UI_ATTRS['window_title']} - {title_suffix}")
        # Use centralized setup to apply theme and attach geometry persistence
        try:
            from src.config.window_state import setup_window
            # Provide reasonable minimums — callers may override
            setup_window(win, name, min_w=760, min_h=480, on_close=on_close, parent_window=self.root)
        except Exception:
            # Fallback: apply theme directly and set protocol
            try:
                apply_theme(win)
            except Exception:
                pass
            if on_close:
                try:
                    win.protocol("WM_DELETE_WINDOW", on_close)
                except Exception:
                    win.protocol("WM_DELETE_WINDOW", lambda: win.destroy())
        return win
    
    def save_window_state(self, name, window):
        """Save window state."""
        try:
            geometry = window.geometry()
            state_file = WINDOW_STATE_FILE
            
            if state_file.exists():
                with open(state_file, 'r') as f:
                    states = json.load(f)
            else:
                states = {}
            
            states[name] = {
                'geometry': geometry,
                'timestamp': datetime.now().isoformat()
            }
            
            with open(state_file, 'w') as f:
                json.dump(states, f, indent=2)
        except Exception as e:
            print(f"Error saving window state: {e}")
    
    def restore_window_state(self, name, window):
        """Restore window state."""
        try:
            state_file = WINDOW_STATE_FILE
            
            if state_file.exists():
                with open(state_file, 'r') as f:
                    states = json.load(f)
                
                if name in states:
                    window.geometry(states[name]['geometry'])
        except Exception as e:
            print(f"Error restoring window state: {e}")

    def open_map_tools_window(self):
        if self.map_tools_window is not None and self.map_tools_window.winfo_exists():
            self.map_tools_window.deiconify()
            self.map_tools_window.lift()
            self.map_tools_window.focus_force()
            return

        from src.maptools.browser import MapToolsBrowser

        self.map_tools_window = self.create_themed_toplevel("map_tools", "Maps", on_close=self._on_close_map_tools_window)

        shell = ttk.Frame(self.map_tools_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        browser = MapToolsBrowser(
            shell,
            maps_dir=config.DATA_DIR / "maps",
            status_callback=self.status_var.set,
            selected_map=self.current_area.get() or self._get_ui_pref("map_tools_last_map", ""),
            on_map_change=lambda name: self._set_ui_pref("map_tools_last_map", name),
        )
        self.map_tools_browser = browser
        browser.pack(fill="both", expand=True)

        self.map_tools_window.update_idletasks()
        req_w = max(900, self.map_tools_window.winfo_reqwidth())
        req_h = max(600, self.map_tools_window.winfo_reqheight())
        self._apply_saved_window_geometry("map_tools", self.map_tools_window, req_w, req_h)
        self.map_tools_window.minsize(760, 480)
        self._set_window_open_state("map_tools", True)

    def _on_close_map_tools_window(self):
        if self.map_tools_window is not None and self.map_tools_window.winfo_exists():
            if self.map_tools_browser is not None:
                self._set_ui_pref("map_tools_last_map", self.map_tools_browser.selected_map_var.get().strip())
            self._save_window_geometry("map_tools", self.map_tools_window)
            self.map_tools_window.destroy()
        self._set_window_open_state("map_tools", False)
        self.map_tools_window = None
        self.map_tools_browser = None

    def _toggle_character_browser_always_on_top(self) -> None:
        """Toggle always-on-top state for the Character Browser window only."""
        if self.character_browser_window is None or not self.character_browser_window.winfo_exists():
            return
        enabled = bool(self.character_browser_pin_var.get())
        try:
            self.character_browser_window.attributes("-topmost", enabled)
        except Exception:
            return
        try:
            self._set_ui_pref("character_browser_always_on_top", enabled)
        except Exception:
            pass

    def open_chat_window(self):
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self.chat_window.deiconify()
            self.chat_window.lift()
            self.chat_window.focus_force()
            return

        self.chat_window = self.create_themed_toplevel("chat_monitor", "Chat Monitor", on_close=self._on_close_chat_window)

        shell = ttk.Frame(self.chat_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Chat Monitor", style="App.Header.TLabel").pack(side="left")
        ttk.Button(header, text="Start", command=self._start_chat_monitor, style="App.Primary.TButton").pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(header, text="Stop", command=self._stop_chat_monitor, style="App.Secondary.TButton").pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(header, text="Clear", command=self._clear_chat_output, style="App.Secondary.TButton").pack(side="right")

        # Watch terms row (used with the in-game PGLok chat channel)
        watch_row = ttk.Frame(shell, style="App.Panel.TFrame")
        watch_row.pack(fill="x", pady=(0, 6))
        ttk.Label(
            watch_row,
            text="Watch terms (PGLok channel, comma-separated):",
            style="App.TLabel",
        ).pack(side="left")
        ttk.Entry(
            watch_row,
            textvariable=self.chat_watch_terms_var,
            width=40,
            style="App.TEntry",
        ).pack(side="left", padx=(6, 0))

        info = ttk.Frame(shell, style="App.Card.TFrame", padding=10)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, textvariable=self.chat_info_var, style="App.Status.TLabel").pack(anchor="w")

        output_wrap = ttk.Frame(shell, style="App.Card.TFrame", padding=8)
        output_wrap.pack(fill="both", expand=True)
        self.chat_window_notebook = ttk.Notebook(output_wrap)
        self.chat_window_notebook.pack(fill="both", expand=True)
        self.chat_window_tab_text = {}

        # Create tabs using standalone window's notebook and tab_text
        self._ensure_chat_tab("All", notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text)
        self._ensure_chat_tab("Other", notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text)
        self._ensure_chat_tab("Info", notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text)
        self._ensure_chat_tab("Player Log", notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text)

        self.chat_window.update_idletasks()
        req_w = max(920, self.chat_window.winfo_reqwidth())
        req_h = max(520, self.chat_window.winfo_reqheight())
        self._apply_saved_window_geometry("chat_monitor", self.chat_window, req_w, req_h)
        self.chat_window.minsize(req_w, req_h)
        self._set_window_open_state("chat_monitor", True)

        self._start_chat_monitor()

    def _on_close_chat_window(self):
        self._stop_chat_monitor()
        # Persist watch-term settings for next run
        try:
            self._set_ui_pref("chat_watch_terms", self.chat_watch_terms_var.get())
        except Exception:
            pass
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self._save_window_geometry("chat_monitor", self.chat_window)
            self.chat_window.destroy()
        self._set_window_open_state("chat_monitor", False)
        self.chat_window = None
        self.chat_text = None
        self.chat_window_notebook = None
        self.chat_window_tab_text = {}

    def _start_chat_monitor(self):
        if self.chat_polling:
            return
        try:
            if config.PG_BASE is None:
                initialize_pg_base(force=True)
            self.chat_monitor = ChatLogMonitor()
        except Exception as exc:
            self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}")
            return

        self.chat_polling = True
        self.status_var.set("Chat monitor running.")
        self._chat_poll_tick()

        # Start player log monitor (background, non-blocking)
        try:
            self._start_player_log_monitor()
        except Exception:
            # Do not let player log monitor failures stop chat monitoring
            pass

    def _stop_chat_monitor(self):
        self.chat_polling = False
        if self.chat_after_id is not None:
            try:
                self.root.after_cancel(self.chat_after_id)
            except tk.TclError:
                pass
            self.chat_after_id = None
        self.status_var.set("Chat monitor stopped.")

        # Stop player log monitoring
        self._stop_player_log_monitor()

    def _start_player_log_monitor(self):
        """Start monitoring the player.log file using a background thread and queue.

        This avoids blocking the Tk mainloop when reading the file or processing many lines.
        """
        # Already running?
        if getattr(self, "_player_log_thread", None) and self._player_log_thread.is_alive():
            return

        try:
            from src.player.monitor import PlayerLogMonitor
            # Pass PG_BASE directory if available
            log_dir = config.PG_BASE if hasattr(config, 'PG_BASE') and config.PG_BASE else None
            monitor = PlayerLogMonitor(log_dir=log_dir)
            self.player_log_monitor = monitor

            # Queue + thread + stop event
            self._player_log_queue = queue.Queue()
            self._player_log_stop = threading.Event()
            self._player_log_thread = threading.Thread(
                target=self._player_log_tail_thread,
                args=(monitor,),
                daemon=True,
            )
            self._player_log_thread.start()

            self.player_log_polling = True
            self.player_log_lines_seen = 0
            # Schedule UI-side poll loop
            self.player_log_after_id = self.root.after(500, self._player_log_poll_tick)
        except Exception as exc:
            # Display error message in the Player Log tab
            print(f"Error starting player log monitor: {exc}")

    def _player_log_tail_thread(self, monitor):
        """Background tail: poll monitor.read_new_lines() and enqueue lines.

        Uses the provided PlayerLogMonitor which handles file discovery and offset tracking.
        """
        stop_evt = getattr(self, "_player_log_stop", None)
        if stop_evt is None:
            return
        try:
            while not stop_evt.is_set():
                try:
                    lines = monitor.read_new_lines()
                    if lines:
                        for ln in lines:
                            try:
                                self._player_log_queue.put(ln)
                            except Exception:
                                # If queue put fails, drop the line
                                pass
                        # small sleep to yield
                        time.sleep(0)
                    else:
                        time.sleep(0.2)
                except Exception:
                    # On transient errors, wait a moment and continue
                    time.sleep(1.0)
        finally:
            return

    def _stop_player_log_monitor(self):
        """Stop monitoring the player.log file and clean up background thread."""
        self.player_log_polling = False
        # Signal background thread to stop
        if getattr(self, "_player_log_stop", None) is not None:
            try:
                self._player_log_stop.set()
            except Exception:
                pass
        # Join thread (short wait)
        if getattr(self, "_player_log_thread", None) is not None:
            try:
                self._player_log_thread.join(timeout=1.0)
            except Exception:
                pass
            self._player_log_thread = None

        # Cancel UI after() if scheduled
        if self.player_log_after_id is not None:
            try:
                self.root.after_cancel(self.player_log_after_id)
            except tk.TclError:
                pass
            self.player_log_after_id = None

    def _player_log_poll_tick(self):
        """Drains queued lines on the Tk main thread and appends to UI widgets.

        Runs frequently via root.after; keeps all Tk calls on the main thread.
        """
        if not getattr(self, "player_log_polling", False):
            return
        q = getattr(self, "_player_log_queue", None)
        if q:
            # Drain up to a modest batch to avoid hogging the UI
            drained = 0
            try:
                # Prepare filter and highlight regexes
                filter_pat = self.player_log_filter_var.get().strip()
                filter_re = None
                if filter_pat:
                    try:
                        filter_re = re.compile(filter_pat, re.IGNORECASE)
                    except Exception:
                        filter_re = None
                highlight_enabled = bool(self.player_log_highlight_var.get())
                highlight_terms = self.player_log_highlight_terms_var.get().strip()
                highlight_re = None
                if highlight_terms:
                    # treat comma-separated terms as alternation
                    try:
                        parts = [re.escape(p.strip()) for p in highlight_terms.split(",") if p.strip()]
                        if parts:
                            highlight_re = re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)
                    except Exception:
                        highlight_re = None

                while drained < 200:
                    line = q.get_nowait()
                    # Parse gift-related events from player log
                    self._parse_player_log_for_gifts(line)
                    # Parse damage events from player log
                    self._parse_player_log_for_damage(line)
                    # Apply filter if present
                    if filter_re:
                        if not filter_re.search(line):
                            continue
                    # Determine highlight
                    should_highlight = False
                    if highlight_enabled and highlight_re and highlight_re.search(line):
                        should_highlight = True
                    if self.chat_notebook is not None:
                        self._append_chat_line("Player Log", line, notebook=self.chat_notebook, tab_text_dict=self.chat_tab_text, highlight=should_highlight)
                    if self.chat_window_notebook is not None:
                        self._append_chat_line("Player Log", line, notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text, highlight=should_highlight)
                    drained += 1
                    self.player_log_lines_seen += 1
            except Exception as exc:
                # queue.Empty expected when drained; import locally to avoid global dependency issues
                try:
                    import queue as _q
                    if not isinstance(exc, _q.Empty):
                        print(f"Player log poll error: {exc}")
                except Exception:
                    pass

        # Reschedule
        try:
            self.player_log_after_id = self.root.after(500, self._player_log_poll_tick)
        except Exception:
            # If scheduling fails, stop polling
            self.player_log_polling = False

    def _try_start_chat_monitor(self):
        """Try to auto-start chat monitor if PG_BASE is available."""
        if self.chat_polling:
            return
        if config.PG_BASE is None:
            # PG not located yet - show status and try again later
            self.status_var.set("Chat monitor waiting for PG location...")
            # Retry every 5 seconds until PG is located
            self.root.after(5000, self._try_start_chat_monitor)
            return
        try:
            self._start_chat_monitor()
        except Exception as exc:
            # Show error on auto-start failure
            self.status_var.set(f"Chat monitor auto-start failed: {exc}")

    def _clear_chat_output(self):
        self.chat_lines_seen = 0
        self.player_log_lines_seen = 0

        # Clear integrated chat page tabs
        for widget in self.chat_tab_text.values():
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.configure(state="disabled")

        # Clear standalone chat window tabs if they exist
        for widget in self.chat_window_tab_text.values():
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.configure(state="disabled")

        current_file = self.chat_monitor.current_file.name if self.chat_monitor and self.chat_monitor.current_file else "None"
        self._update_chat_info(current_file)

    def _chat_poll_tick(self):
        if not self.chat_polling:
            return
        if self.chat_monitor is None:
            self.chat_polling = False
            return

        try:
            lines = self.chat_monitor.read_new_lines()
            current_file = self.chat_monitor.current_file.name if self.chat_monitor.current_file else "None"
            if lines:
                # Append to integrated chat page if it exists
                if self.chat_notebook is not None:
                    for line in lines:
                        channel = self._extract_chat_channel(line)

                        # Parse game info from chat lines
                        self._parse_game_info(line)

                        # Parse favor gain messages
                        self._parse_favor_gain(line)

                        # Parse damage events from chat lines
                        self._parse_player_log_for_damage(line)

                        # Handle PGLok channel commands / watch terms
                        self._handle_pglok_watch_terms(line, channel)

                        # Combine Status and Error channels into System tab
                        if channel in ["Status", "Error"]:
                            combined_channel = "System"
                        else:
                            combined_channel = channel

                        self._append_chat_line("All", line, notebook=self.chat_notebook, tab_text_dict=self.chat_tab_text)
                        self._append_chat_line(combined_channel, line, notebook=self.chat_notebook, tab_text_dict=self.chat_tab_text)

                # Append to standalone chat window if it exists
                if self.chat_window_notebook is not None:
                    for line in lines:
                        channel = self._extract_chat_channel(line)

                        # Combine Status and Error channels into System tab
                        if channel in ["Status", "Error"]:
                            combined_channel = "System"
                        else:
                            combined_channel = channel

                        self._append_chat_line("All", line, notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text)
                        self._append_chat_line(combined_channel, line, notebook=self.chat_window_notebook, tab_text_dict=self.chat_window_tab_text)

                self.chat_lines_seen += len(lines)
                self._update_info_tab()
            self._update_chat_info(current_file)
        except Exception as exc:
            self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}")

        self.chat_after_id = self.root.after(500, self._chat_poll_tick)

    def _handle_pglok_watch_terms(self, line, channel):
        """Watch for user-defined terms on the in-game PGLok chat channel.

        Lines that match will be echoed into the Info tab with a [WATCH] prefix
        so they are easy to spot. Terms are a comma-separated list.
        """
        if not line:
            return

        # Only pay attention to the dedicated PGLok channel
        if str(channel).lower() != "pglok":
            return

        raw = (self.chat_watch_terms_var.get() or "").strip()
        if not raw:
            return

        lower_line = line.lower()
        terms = [t.strip().lower() for t in raw.split(",") if t.strip()]
        for term in terms:
            if term and term in lower_line:
                self._append_chat_line("Info", f"[WATCH:{channel}] {line}")
                # Also surface on status bar for quick feedback
                self.status_var.set(f"PGLok match: '{term}' in chat")
                break

    def _parse_game_info(self, line):
        """Parse login, logout, area, and guild info from chat lines."""
        import re
        lower = line.lower()

        # Login detection - various patterns
        login_patterns = [
            "you have entered",
            "welcome to",
            "logged in as",
            "login:"
        ]
        for pattern in login_patterns:
            if pattern in lower:
                # Try to extract character name from various formats
                # Format: "You have entered [Area] as [Character]"
                # Format: "Welcome to [Area], [Character]!"
                # Format: "Logged in as: [Character]"

                # Look for character name after "as" or comma
                match = re.search(r"as\s+(\w+)", line, re.IGNORECASE)
                if match:
                    self.current_character.set(match.group(1))
                    self._append_chat_line("Info", f"[LOGIN] Character: {match.group(1)}")
                    # Update favor tracker with character if open
                    if self.favor_tracker_window is not None:
                        try:
                            if self.favor_tracker_window.window.winfo_exists():
                                if hasattr(self.favor_tracker_window, 'update_character_from_chat'):
                                    self.favor_tracker_window.update_character_from_chat(match.group(1))
                        except Exception:
                            pass

    def _parse_player_log_for_gifts(self, line):
        """Parse player log for gift-related events to track which items are being gifted."""
        import re
        from datetime import datetime
        
        # Pattern for ProcessPromptForItem event which indicates gift dialog
        # Example: LocalPlayer: ProcessPromptForItem(14974, "Give Gift", "A gift? For me?", "Choose gift", null, [...], System.String[], -1301, "", Error, 0, ForNpc, "NPC_EvelineRastin")
        match = re.search(r'ProcessPromptForItem\([^,]+,\s*"Give Gift"[^)]*"ForNpc",\s*"([^"]+)"', line)
        if match:
            npc_key = match.group(1)
            # Clear the last gifted item when a new gift dialog opens
            self.last_gifted_item = None
            self.last_gifted_npc = npc_key
            self.last_gifted_time = datetime.now()
            return

        # Try to detect explicit "You gave X to Y" style lines so we can remember the item
        # Example: "You gave Blood Mushroom to Mandibles" or similar variants.
        try:
            m = re.search(r"you gave (.+?) to (.+)", line, re.IGNORECASE)
            if not m:
                m = re.search(r"gave (.+?) to (.+)", line, re.IGNORECASE)
            if m:
                item_name = m.group(1).strip()
                npc_part = m.group(2).strip()
                # Store the last gifted item and the recipient (display name or key fragment)
                self.last_gifted_item = item_name
                self.last_gifted_npc = npc_part
                self.last_gifted_time = datetime.now()
                return
        except Exception:
            # Don't let parsing errors interrupt the player log processing
            pass

        # Pattern for inventory item removal (might indicate gifting)
        # This is a fallback - the game doesn't always send removal messages for gifts
        # We'll rely on the favor gain message to trigger the actual recording

    def _parse_player_log_for_damage(self, line):
        """Parse player.log and chat lines for damage events.

        Supports many Project Gorgon formats:
          Chat box (English):
            - 'You hit [enemy] for X damage with [ability]'
            - '[Enemy] hits you for X [type] damage'
            - 'Your [ability] hits [enemy] for X [type] damage'
            - 'You are hit for X [type] damage'
            - Armor absorption messages

          Unity player.log (debug traces):
            - 'LocalPlayer: ProcessDoDamage(NPC_Orc, 42)'
            - 'TakeDamage(player, 12, "crushing", "NPC_Orc")'
            - 'ProcessDamage(...)' 
            - Generic: any line with 'damage' and a number near a creature name

          Fallback – catches lines with 'damage' keyword + a numeric value.
        """
        if not line:
            return

        # ======================
        # CHAT-STYLE damage (English patterns – from chat log or echoed to player.log)
        # ======================

        # "You hit [enemy] for X damage" or "You hit [enemy] for X [type] damage" with optional ability
        match = re.search(
            r"you hit (.+?) for ([\d,]+(?:\.\d+)?) damage(?: with (.+?))?(?:\s*$|\s*\.|\s*\()",
            line, re.IGNORECASE
        )
        if match:
            target = match.group(1).strip()
            amount = match.group(2).replace(",", "")
            ability = (match.group(3) or "").strip()
            self._record_damage_event(
                source="You",
                target=target,
                amount=float(amount),
                damage_type=ability if ability else "",
                is_player_damage=True,
                raw_line=line,
            )
            return

        # "Your [ability] hits [enemy] for X [type] damage"
        match = re.search(
            r"your (.+?) hits? (.+?) for ([\d,]+(?:\.\d+)?) (?:(\w+)\s*)?damage",
            line, re.IGNORECASE
        )
        if match:
            ability = match.group(1).strip()
            target = match.group(2).strip()
            amount = match.group(3).replace(",", "")
            dmgt = (match.group(4) or "").strip()
            self._record_damage_event(
                source="You",
                target=target,
                amount=float(amount),
                damage_type=f"{ability} {dmgt}".strip(),
                is_player_damage=True,
                raw_line=line,
            )
            return

        # "You deal X damage to [target]" or "You deal X [type] damage to [target]"
        match = re.search(
            r"you deal ([\d,]+(?:\.\d+)?) (?:(\w+)\s*)?damage to (.+)",
            line, re.IGNORECASE
        )
        if match:
            amount = match.group(1).replace(",", "")
            dmgt = (match.group(2) or "").strip()
            target = match.group(3).strip()
            self._record_damage_event(
                source="You",
                target=target,
                amount=float(amount),
                damage_type=dmgt,
                is_player_damage=True,
                raw_line=line,
            )
            return

        # "[Enemy] hits you for X [type] damage"
        match = re.search(
            r"(.+?) hits? you for ([\d,]+(?:\.\d+)?) (?:(\w+)\s*)?damage",
            line, re.IGNORECASE
        )
        if match:
            enemy = match.group(1).strip()
            amount = match.group(2).replace(",", "")
            dmgt = (match.group(3) or "").strip()
            self._record_damage_event(
                source=enemy,
                target="You",
                amount=float(amount),
                damage_type=dmgt,
                is_player_damage=False,
                raw_line=line,
            )
            return

        # "You are hit for X [type] damage"
        match = re.search(
            r"you (?:are|were) hit for ([\d,]+(?:\.\d+)?) (?:(\w+)\s*)?damage",
            line, re.IGNORECASE
        )
        if match:
            amount = match.group(1).replace(",", "")
            dmgt = (match.group(2) or "").strip()
            self._record_damage_event(
                source="Unknown",
                target="You",
                amount=float(amount),
                damage_type=dmgt,
                is_player_damage=False,
                raw_line=line,
            )
            return

        # --- Armor absorption ---
        # "Your armor absorbed / absorbs X damage"
        match = re.search(
            r"(?:your armor|armor) absorb(?:s|ed)? ([\d,]+(?:\.\d+)?)\s*(?:points? of)?\s*damage",
            line, re.IGNORECASE
        )
        if match:
            amount = match.group(1).replace(",", "")
            self._record_damage_event(
                source="Armor",
                target="You",
                amount=float(amount),
                damage_type="absorbed",
                is_player_damage=False,
                raw_line=line,
            )
            return

        # "You evaded [enemy]'s attack" or "You avoided damage"
        match = re.search(
            r"you (?:evaded?|avoid(?:ed)?|dodged?|parried?|block(?:ed)?) (.+?)'?s?\s*(?:attack|blow|hit|strike|damage)",
            line, re.IGNORECASE
        )
        if match:
            # Record as 0 damage with the source name
            enemy_or_attack = match.group(1).strip()
            if enemy_or_attack.lower() not in ("the", "a", "an", "its", "their"):
                self._record_damage_event(
                    source=enemy_or_attack,
                    target="You",
                    amount=0.0,
                    damage_type="avoided",
                    is_player_damage=False,
                    raw_line=line,
                )
            return

        # "[Enemy] evaded / dodged your attack"
        match = re.search(
            r"(.+?) (?:evaded?|dodged?|parried?|block(?:ed)?|avoid(?:ed)?) your (?:attack|blow|hit|strike|damage)",
            line, re.IGNORECASE
        )
        if match:
            enemy = match.group(1).strip()
            if enemy.lower() not in ("the", "a", "an", "its", "their"):
                self._record_damage_event(
                    source="You",
                    target=enemy,
                    amount=0.0,
                    damage_type="avoided",
                    is_player_damage=True,
                    raw_line=line,
                )
            return

        # ======================
        # UNITY PLAYER.LOG damage (debug traces from the C# engine)
        # ======================

        # "LocalPlayer: ProcessDoDamage(target, amount)"
        match = re.search(r"LocalPlayer:\s*ProcessDoDamage\(([^,)]+)[,)]\s*([\d,]+(?:\.\d+)?)", line, re.IGNORECASE)
        if match:
            target = match.group(1).strip().strip('"').strip("'")
            amount = match.group(2).replace(",", "")
            self._record_damage_event(
                source="You",
                target=target,
                amount=float(amount),
                damage_type="",
                is_player_damage=True,
                raw_line=line,
            )
            return

        # "ProcessDamage(attacker, defender, amount, ...)" – detect who is the player
        match = re.search(r"ProcessDamage\(([^,]+),\s*([^,]+),\s*([\d,]+(?:\.\d+)?)", line, re.IGNORECASE)
        if match:
            attacker = match.group(1).strip().strip('"').strip("'")
            defender = match.group(2).strip().strip('"').strip("'")
            amount = float(match.group(3).replace(",", ""))
            if amount <= 0:
                return
            # Determine if player is attacker or defender
            player_aliases = ("player", "localplayer", "you", "")
            if any(p in attacker.lower() for p in player_aliases):
                self._record_damage_event(
                    source="You", target=defender, amount=amount,
                    damage_type="", is_player_damage=True, raw_line=line,
                )
            elif any(p in defender.lower() for p in player_aliases):
                self._record_damage_event(
                    source=attacker, target="You", amount=amount,
                    damage_type="", is_player_damage=False, raw_line=line,
                )
            return

        # "TakeDamage(entity, amount, type, source)" — player taking damage
        match = re.search(r"TakeDamage\(([^,)]+)[,)]\s*([\d,]+(?:\.\d+)?)\s*[,)]?\s*([^,)]*?)[,)]?\s*([^,)]*?)\)", line, re.IGNORECASE)
        if match:
            entity = match.group(1).strip().strip('"').strip("'")
            amount = match.group(2).replace(",", "")
            dmgt = match.group(3).strip().strip('"').strip("'")
            source = match.group(4).strip().strip('"').strip("'") if match.group(4) else ""
            player_aliases = ("player", "localplayer", "you", "")
            if any(p in entity.lower() for p in player_aliases):
                self._record_damage_event(
                    source=source if source else "Unknown",
                    target="You",
                    amount=float(amount),
                    damage_type=dmgt,
                    is_player_damage=False,
                    raw_line=line,
                )
                return

        # "Damage: X [type] to Y" or "Dealt X damage to Y" (generic Debug.Log)
        match = re.search(r"(?:Damage|Dealt):?\s*([\d,]+(?:\.\d+)?)\s*(?:(\w+)\s*)?(?:damage|DMG)?\s*(?:to|on|->)\s*(.+)", line, re.IGNORECASE)
        if match:
            amount = match.group(1).replace(",", "")
            dmgt = (match.group(2) or "").strip()
            target = match.group(3).strip()
            self._record_damage_event(
                source="You",
                target=target,
                amount=float(amount),
                damage_type=dmgt,
                is_player_damage=True,
                raw_line=line,
            )
            return

        # ======================
        # BROAD FALLBACK – any line with "damage" + a number after a creature-like name
        # Catches many custom formats without false positives.
        # ======================

        # Only apply fallback if line contains the word "damage" (case-insensitive)
        if not re.search(r"damage", line, re.IGNORECASE):
            return

        # Try to extract: [word] [hits|hit|deals] you for [number]
        match = re.search(
            r"(?:^|\s)([A-Z][\w\s]{1,40}?)\s+(?:hits?|deals?|does)\s+(?:you\s+for\s+|)([\d,]+(?:\.\d+)?)",
            line, re.IGNORECASE
        )
        if match:
            source_name = match.group(1).strip()
            amount_text = match.group(2).replace(",", "")
            # Filter out non-creature phrases
            if source_name.lower() not in ("you", "your", "the", "a", "an", "and", "or", "but", "that", "this", "with", "from", "to"):
                self._record_damage_event(
                    source=source_name,
                    target="You",
                    amount=float(amount_text),
                    damage_type="",
                    is_player_damage=False,
                    raw_line=line,
                )
                return

    def _record_damage_event(self, source, target, amount, damage_type, is_player_damage, raw_line):
        """Record a single damage event and append it to the Damage Log tab."""
        event = {
            "source": source,
            "target": target,
            "amount": amount,
            "damage_type": damage_type,
            "is_player_damage": is_player_damage,
            "timestamp": datetime.now(),
            "raw": raw_line,
        }
        # Clamp the list to avoid unbounded memory growth
        if len(self.damage_events) > 5000:
            self.damage_events = self.damage_events[-4000:]
        self.damage_events.append(event)

        # Build the display line with color tags
        if not self.chat_notebook:
            return

        damage_text = self.chat_tab_text.get("Damage Log")
        if damage_text is None:
            return

        damage_text.configure(state="normal")

        time_str = event["timestamp"].strftime("%H:%M:%S")
        damage_text.insert(tk.END, f"[{time_str}] ")

        if is_player_damage:
            # Green: You → enemy
            damage_text.insert(tk.END, "You ", ("player_damage",))
            damage_text.insert(tk.END, f"→ {target}: ")
            damage_text.insert(tk.END, f"{amount:,.0f}", ("damage_amount",))
            if damage_type:
                damage_text.insert(tk.END, f" ({damage_type})", ("damage_type",))
            damage_text.insert(tk.END, " damage")
        else:
            # Red: enemy → You
            damage_text.insert(tk.END, f"{source} ", ("damage_source",))
            damage_text.insert(tk.END, "→ You: ")
            damage_text.insert(tk.END, f"{amount:,.0f}", ("damage_amount",))
            if damage_type:
                damage_text.insert(tk.END, f" ({damage_type})", ("damage_type",))
            damage_text.insert(tk.END, " damage", ("enemy_damage",))

        damage_text.insert(tk.END, "\n")
        damage_text.see(tk.END)
        self._trim_chat_widget(damage_text)
        damage_text.configure(state="disabled")

    def _parse_favor_gain(self, line):
        """Parse favor gain messages from chat logs and automatically record them."""
        import re
        lower = line.lower()

        # Pattern 1: "You gained X favor with NPC Name for giving them Item Name"
        # Example: "You gained 5.5 favor with Willem Fangblade for giving them Bone"
        match = re.search(r"you gained ([\d.]+) favor with (.+?) for giving them (.+)", line, re.IGNORECASE)
        if match:
            favor_amount = match.group(1)
            npc_name = match.group(2).strip()
            item_name = match.group(3).strip()

            # Try to record the favor gain in the favor tracker with item name
            if self.favor_tracker_window is not None:
                try:
                    if self.favor_tracker_window.window.winfo_exists():
                        if hasattr(self.favor_tracker_window, 'record_favor_gain_from_chat_with_item'):
                            self.favor_tracker_window.record_favor_gain_from_chat_with_item(npc_name, favor_amount, item_name)
                        elif hasattr(self.favor_tracker_window, 'record_favor_gain_from_chat'):
                            # Fallback to method without item name
                            self.favor_tracker_window.record_favor_gain_from_chat(npc_name, favor_amount)
                except Exception:
                    pass
            return

        # Pattern 2: "You gained X favor with NPC Name" (fallback without item)
        # Example: "You gained 5.5 favor with Willem Fangblade"
        match = re.search(r"you gained ([\d.]+) favor with (.+)", line, re.IGNORECASE)
        if match:
            favor_amount = match.group(1)
            npc_name = match.group(2).strip()

            # If we recently detected an explicit "You gave X to Y" line, use the remembered item
            try:
                from datetime import datetime
                if self.last_gifted_item and self.last_gifted_time:
                    delta = datetime.now() - self.last_gifted_time
                    # Only trust recent detections (e.g., within 10 seconds)
                    if delta.total_seconds() <= 10:
                        if self.last_gifted_npc and (self.last_gifted_npc.lower() in npc_name.lower() or npc_name.lower() in self.last_gifted_npc.lower()):
                            item_name = self.last_gifted_item
                            # Record with the inferred item name
                            if self.favor_tracker_window is not None:
                                try:
                                    if self.favor_tracker_window.window.winfo_exists():
                                        if hasattr(self.favor_tracker_window, 'record_favor_gain_from_chat_with_item'):
                                            self.favor_tracker_window.record_favor_gain_from_chat_with_item(npc_name, favor_amount, item_name)
                                        elif hasattr(self.favor_tracker_window, 'record_favor_gain_from_chat'):
                                            # Fallback: record without explicit item
                                            self.favor_tracker_window.record_favor_gain_from_chat(npc_name, favor_amount)
                                except Exception:
                                    pass
                            # Clear remembered gift to avoid double-using it
                            self.last_gifted_item = None
                            self.last_gifted_npc = None
                            self.last_gifted_time = None
                            return
            except Exception:
                pass

            # Try to record the favor gain in the favor tracker (no item detected or inference failed)
            if self.favor_tracker_window is not None:
                try:
                    if self.favor_tracker_window.window.winfo_exists():
                        if hasattr(self.favor_tracker_window, 'record_favor_gain_from_chat'):
                            # Record without item name since it's not in the message
                            # The favor tracker will handle training mode if enabled
                            self.favor_tracker_window.record_favor_gain_from_chat(npc_name, favor_amount)
                except Exception:
                    pass
        
        # Logout detection
        logout_patterns = ["you have left", "logged out", "disconnected", "logout"]
        for pattern in logout_patterns:
            if pattern in lower:
                self._append_chat_line("Info", f"[LOGOUT] {self.current_character.get()}")
                break
        
        # Area/Zone change detection
        area_patterns = [
            "you have entered",
            "you are now in",
            "area:",
            "zone:",
            "location:",
            "entered",
            "warped to",
            "teleported to",
        ]
        for pattern in area_patterns:
            if pattern in lower:
                # More flexible regex for area detection
                # Try multiple patterns to extract area name
                area_match = None
                
                # Pattern 1: "entered [AreaName] as" or "entered [AreaName],"
                area_match = re.search(r"entered\s+([\w\s'\-]+?)(?:\s+as|,|\s*!|$)", line, re.IGNORECASE)
                
                # Pattern 2: "now in [AreaName]" or "in [AreaName]"
                if not area_match:
                    area_match = re.search(r"(?:now\s+)?in\s+([\w\s'\-]+?)(?:\.|!|$)", line, re.IGNORECASE)
                
                # Pattern 3: "to [AreaName]" (for warped/teleported)
                if not area_match:
                    area_match = re.search(r"(?:to|into)\s+([\w\s'\-]+?)(?:\.|!|$)", line, re.IGNORECASE)
                
                # Pattern 4: "area: [AreaName]" or "zone: [AreaName]"
                if not area_match:
                    area_match = re.search(r"(?:area|zone|location):\s*([\w\s'\-]+?)(?:\.|!|$)", line, re.IGNORECASE)
                
                if area_match:
                    area = area_match.group(1).strip()
                    if area and area != self.current_area.get():
                        self.current_area.set(area)
                        self._append_chat_line("Info", f"[AREA] {area}")
                        # Update favor tracker with area if open
                        if self.favor_tracker_window is not None:
                            try:
                                if self.favor_tracker_window.window.winfo_exists():
                                    if hasattr(self.favor_tracker_window, 'update_area_from_chat'):
                                        self.favor_tracker_window.update_area_from_chat(area)
                            except Exception:
                                pass
                break
        
        # Guild info detection
        if "guild" in lower:
            # Look for guild mentions
            guild_match = re.search(r'guild["\s:]+([\w\s]+)', line, re.IGNORECASE)
            if guild_match:
                guild = guild_match.group(1).strip()
                self.current_guild.set(guild)
                self._append_chat_line("Info", f"[GUILD] {guild}")
            
            # Guild login/logout of other members
            if "has come online" in lower or "has gone offline" in lower:
                self._append_chat_line("Info", f"[GUILD] {line.strip()}")

    def _on_area_change(self, *args):
        """Handle area change - update map browser and favor tracker if open."""
        new_area = self.current_area.get()

        # Update map browser if it's open
        if self.map_tools_browser is not None and self.map_tools_window is not None:
            if self.map_tools_window.winfo_exists():
                # Check if the new area matches a map file
                browser = self.map_tools_browser
                available_maps = browser.map_combo["values"] if browser.map_combo else []

                # Try to find matching map (case-insensitive, partial match)
                if available_maps:
                    # Direct match first
                    if new_area in available_maps:
                        browser.selected_map_var.set(new_area)
                        browser._on_map_selected()
                        return

                    # Partial match (e.g., "Serbule" matches "Serbule.png")
                    for map_name in available_maps:
                        if new_area.lower() in map_name.lower() or map_name.lower() in new_area.lower():
                            browser.selected_map_var.set(map_name)
                            browser._on_map_selected()
                            return

        # Update favor tracker if it's open and has the update method
        if self.favor_tracker_window is not None:
            try:
                if self.favor_tracker_window.window.winfo_exists():
                    if hasattr(self.favor_tracker_window, 'update_area_from_chat'):
                        self.favor_tracker_window.update_area_from_chat(new_area)
            except Exception:
                pass

    def _update_info_tab(self):
        """Update the Info tab with current game information."""
        text = self._ensure_chat_tab("Info")
        if text is None:
            return
        
        # Update center status bar with character info
        self._update_center_status()
        
        # Clear and rebuild info display
        text.configure(state="normal")
        text.delete("1.0", tk.END)
        
        info_lines = [
            "=== Character Info ===",
            f"Character: {self.current_character.get()}",
            f"Area: {self.current_area.get()}",
            f"Guild: {self.current_guild.get()}",
            "",
            "=== Recent Events ===",
        ]
        
        for line in info_lines:
            text.insert(tk.END, line + "\n")
        
        text.configure(state="disabled")

    def _extract_chat_channel(self, line):
        lower = line.lower()
        if "item:" in lower:
            return "Item"
        if "recipe:" in lower:
            return "Recipe"
        if "status:" in lower:
            return "Status"
        if "error:" in lower:
            return "Error"
        match = CHAT_CHANNEL_RE.search(line)
        if not match:
            return "Other"
        channel = match.group("channel").strip() or "Other"
        normalized = channel.lower()
        if normalized == "npc chatter":
            return "NPC"
        if normalized in {"action emotes", "emotes"}:
            return "Emotes"
        return channel

    def _ensure_chat_tab(self, name, notebook=None, tab_text_dict=None):
        """Ensure a chat tab exists. Optionally use a specific notebook and tab text dict."""
        target_notebook = notebook if notebook is not None else self.chat_notebook
        target_tab_text = tab_text_dict if tab_text_dict is not None else self.chat_tab_text

        if target_notebook is None:
            return None
        if name in target_tab_text:
            return target_tab_text[name]

        tab_frame = ttk.Frame(target_notebook, style="App.Card.TFrame")
        scroll = ttk.Scrollbar(tab_frame, orient="vertical", style="App.Vertical.TScrollbar")
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            tab_frame,
            wrap="word",
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
            yscrollcommand=scroll.set,
            state="disabled",
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=text.yview)
        # Allow text selection and copy but block keyboard editing
        text.bind("<Key>", lambda e: "break" if e.state == 0 and len(e.char) == 1 else None)
        text.bind("<Control-c>", lambda e: None)  # let default copy through
        text.bind("<Control-a>", lambda e: (text.tag_add("sel", "1.0", "end"), "break"))
        target_notebook.add(tab_frame, text=name)
        target_tab_text[name] = text
        return text

    def _append_chat_line(self, tab_name, line, notebook=None, tab_text_dict=None, highlight=False):
        """Append a line to a chat tab. Optionally highlight the inserted line."""
        target_notebook = notebook if notebook is not None else self.chat_notebook
        target_tab_text = tab_text_dict if tab_text_dict is not None else self.chat_tab_text

        text = self._ensure_chat_tab(tab_name, notebook=target_notebook, tab_text_dict=target_tab_text)
        if text is None:
            return
        text.configure(state="normal")
        # Insert with optional tag for highlighting whole line
        if highlight:
            tag_name = f"player_log_highlight"
            try:
                # Configure tag appearance once per widget
                if tag_name not in text.tag_names():
                    text.tag_configure(tag_name, background=UI_COLORS.get("accent", "yellow"))
            except Exception:
                pass
            text.insert(tk.END, line + "\n", (tag_name,))
        else:
            text.insert(tk.END, line + "\n")
        text.see(tk.END)
        self._trim_chat_widget(text)
        text.configure(state="disabled")

    def _trim_chat_widget(self, widget, max_lines=6000, keep_lines=4000):
        total_lines = int(widget.index("end-1c").split(".")[0])
        if total_lines > max_lines:
            widget.delete("1.0", f"{total_lines - keep_lines}.0")

    def _update_chat_info(self, current_file):
        now = datetime.now()
        self.chat_info_var.set(
            f"Lines: {self.chat_lines_seen}    Date: {now:%Y-%m-%d}    Time: {now:%H:%M:%S}    File: {current_file}"
        )

    def _toggle_always_on_top(self):
        """Toggle always on top state from checkbox."""
        new_state = self.pin_var.get()
        self.root.attributes("-topmost", new_state)
        self._set_ui_pref("always_on_top", new_state)

    def _restore_always_on_top_state(self):
        """Restore always on top state from preferences."""
        value = bool(self._get_ui_pref("always_on_top", False))
        self.pin_var.set(value)
        self.root.attributes("-topmost", value)

    def _build_home_page(self):
        self.home_paned = None
        self._ensure_home_layout_visible()

    def _build_chat_page(self):
        """Build the integrated chat monitor page."""
        # Header with controls
        header = ttk.Frame(self.chat_page, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Chat Monitor", style="App.Header.TLabel").pack(side="left")

        control_frame = ttk.Frame(header, style="App.Panel.TFrame")
        control_frame.pack(side="right")

        ttk.Button(control_frame, text="Start", command=self._start_chat_monitor, style="App.Primary.TButton").pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(control_frame, text="Stop", command=self._stop_chat_monitor, style="App.Secondary.TButton").pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(control_frame, text="Clear", command=self._clear_chat_output, style="App.Secondary.TButton").pack(side="left")

        # Player log filter and highlight controls
        try:
            ttk.Label(control_frame, text="Filter", style="App.TLabel").pack(side="left", padx=(18, 4))
            ttk.Entry(control_frame, textvariable=self.player_log_filter_var, width=20, style="App.TEntry").pack(side="left")
            ttk.Label(control_frame, text="Highlight Terms", style="App.TLabel").pack(side="left", padx=(8, 4))
            ttk.Entry(control_frame, textvariable=self.player_log_highlight_terms_var, width=20, style="App.TEntry").pack(side="left")
            ttk.Checkbutton(control_frame, text="Highlight", variable=self.player_log_highlight_var, style="App.TCheckbutton").pack(side="left", padx=(6, 0))
        except Exception:
            # UI can fail in unusual environments; ignore
            pass

        # Info bar
        info = ttk.Frame(self.chat_page, style="App.Card.TFrame", padding=8)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, textvariable=self.chat_info_var, style="App.Status.TLabel").pack(anchor="w")

        # Chat notebook with tabs
        output_wrap = ttk.Frame(self.chat_page, style="App.Card.TFrame", padding=8)
        output_wrap.pack(fill="both", expand=True)
        self.chat_notebook = ttk.Notebook(output_wrap)
        self.chat_notebook.pack(fill="both", expand=True)

        # Create tabs
        self._ensure_chat_tab("All")
        self._ensure_chat_tab("Other")
        self._ensure_chat_tab("Info")
        self._ensure_chat_tab("Player Log")
        self._ensure_chat_tab("Damage Log")
        self._ensure_chat_tab("Debug")
        self._flush_debug_buffer()

        # Configure damage log text widget with color tags
        damage_text = self.chat_tab_text.get("Damage Log")
        if damage_text is not None:
            damage_text.tag_configure("player_damage", foreground="#4CAF50")  # green
            damage_text.tag_configure("enemy_damage", foreground="#F44336")   # red
            damage_text.tag_configure("damage_source", foreground="#FF9800")  # orange for source names
            damage_text.tag_configure("damage_type", foreground="#9E9E9E")    # grey for damage type
            damage_text.tag_configure("damage_amount", foreground="#FFFFFF")   # white for amounts

    def _on_home_pane_resize(self, _event=None):
        self._save_home_split()
        self._ensure_home_layout_visible()

    def _save_home_split(self):
        if self.home_paned is None:
            return
        try:
            split = int(self.home_paned.sashpos(0))
        except (tk.TclError, ValueError):
            return
        self._set_ui_pref("home_split", split)

    def _restore_home_split(self):
        if self.home_paned is None:
            return
        self.home_paned.update_idletasks()
        split = self._get_ui_pref("home_split", None)
        if split is None:
            return
        try:
            max_height = max(240, self.home_paned.winfo_height() - 120)
            clamped = min(max(int(split), 200), max_height)
            self.home_paned.sashpos(0, clamped)
        except (tk.TclError, ValueError):
            return
        self._ensure_home_layout_visible()

    def _set_global_search_detail(self, text):
        if self.global_search_detail_text is None:
            return
        self.global_search_detail_text.configure(state="normal")
        self.global_search_detail_text.delete("1.0", tk.END)
        self.global_search_detail_text.insert("1.0", text)
        self.global_search_detail_text.configure(state="disabled")

    def _on_global_search_pane_resize(self, _event=None):
        self._save_global_search_split()
        self._ensure_home_layout_visible()

    def _save_global_search_split(self):
        if self.global_search_paned is None:
            return
        try:
            split = int(self.global_search_paned.sashpos(0))
        except (tk.TclError, ValueError):
            return
        self._set_ui_pref("global_search_split", split)

    def _restore_global_search_split(self):
        if self.global_search_paned is None:
            return
        self.global_search_paned.update_idletasks()
        split = self._get_ui_pref("global_search_split", None)
        if split is None:
            return
        try:
            max_height = max(140, self.global_search_paned.winfo_height() - 100)
            clamped = min(max(int(split), 80), max_height)
            self.global_search_paned.sashpos(0, clamped)
        except (tk.TclError, ValueError):
            return
        self._ensure_home_layout_visible()

    def _ensure_home_layout_visible(self):
        # Keep home split panes within safe bounds so all sections remain visible.
        if self.home_paned is not None:
            try:
                total_h = int(self.home_paned.winfo_height())
                if total_h > 0:
                    min_top = 170
                    min_bottom = 95
                    max_top = max(min_top, total_h - min_bottom)
                    current = int(self.home_paned.sashpos(0))
                    clamped = min(max(current, min_top), max_top)
                    if clamped != current:
                        self.home_paned.sashpos(0, clamped)
            except (tk.TclError, ValueError):
                pass

        if self.global_search_paned is not None:
            try:
                total_h = int(self.global_search_paned.winfo_height())
                if total_h > 0:
                    min_top = 80
                    min_bottom = 70
                    max_top = max(min_top, total_h - min_bottom)
                    current = int(self.global_search_paned.sashpos(0))
                    clamped = min(max(current, min_top), max_top)
                    if clamped != current:
                        self.global_search_paned.sashpos(0, clamped)
            except (tk.TclError, ValueError):
                pass

    def _populate_global_search_results(self, results):
        self.global_search_results = list(results)
        self._set_ui_pref("global_search_results", self.global_search_results)
        if self.global_search_results_tree is not None:
            self.global_search_results_tree.delete(*self.global_search_results_tree.get_children())
            for idx, item in enumerate(self.global_search_results):
                # Add category to the display if available
                category_prefix = f"[{item.get('category', 'General')}] " if item.get('category') else ""
                display_title = f"{category_prefix}{item['title']}"
                self.global_search_results_tree.insert(
                    "",
                    tk.END,
                    iid=str(idx),
                    values=(item["source"], display_title, item["location"]),
                )
            if self.global_search_results:
                self.global_search_results_tree.selection_set("0")
                self.global_search_results_tree.focus("0")
                self._on_global_search_select()
            else:
                self._set_global_search_detail("No matches found.")

    def _on_global_search_select(self, _event=None):
        if self.global_search_results_tree is None:
            return
        sel = self.global_search_results_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.global_search_results):
            return
        self._set_ui_pref("global_search_selected_index", idx)
        item = self.global_search_results[idx]
        
        # Build a cleaner, more organized detail view
        detail_lines = []
        
        # Header section with category and source
        if item.get('category'):
            detail_lines.append(f"📁 {item['category']}")
        
        source_icons = {
            "Database": "🗄️",
            "Items": "🎒", 
            "File": "📄"
        }
        icon = source_icons.get(item['source'], "📋")
        detail_lines.append(f"{icon} {item['source']}")
        detail_lines.append("")  # Spacer
        
        # Main content section
        detail_lines.append(f"🔍 {item['title']}")
        detail_lines.append("")
        
        # Location with better formatting
        detail_lines.append(f"📍 {item['location']}")
        detail_lines.append("")
        
        # Preview section with cleaner formatting
        detail_lines.append("📄 Content Preview")
        detail_lines.append("─" * 30)
        
        # Clean up the snippet for better display
        snippet = item['snippet'].strip()
        if snippet:
            # If snippet contains bullet points, it's already well-formatted
            if snippet.startswith('•'):
                detail_lines.append(snippet)
            # If snippet contains highlighting markers, preserve them
            elif '🔸' in snippet:
                detail_lines.append(snippet)
            else:
                # For plain text, add some structure
                lines = snippet.split('\n')
                for line in lines:
                    if line.strip():
                        detail_lines.append(f"  {line.strip()}")
        else:
            detail_lines.append("  No preview available")
        
        self._set_global_search_detail("\n".join(detail_lines))

    def _reset_global_search(self):
        self.global_search_var.set("")
        self._populate_global_search_results([])
        self._set_global_search_detail("")
        self._set_ui_pref("global_search_query", "")
        self._set_ui_pref("global_search_results", [])
        self._set_ui_pref("global_search_selected_index", 0)
        self.status_var.set(UI_TEXT["status_ready"])

    def _start_global_search(self):
        if self._global_search_after_id is not None:
            try:
                self.root.after_cancel(self._global_search_after_id)
            except tk.TclError:
                pass
            self._global_search_after_id = None
        query = self.global_search_var.get().strip()
        self._set_ui_pref("global_search_query", query)
        if not query:
            self._reset_global_search()
            return

        self.status_var.set("Searching databases and files...")

        def worker():
            try:
                results = self._run_global_search(query)
                lines = [f"Results for: {query}", "=" * 64]
                if not results:
                    pass

                def done():
                    self._populate_global_search_results(results)
                    self.status_var.set(f"Global search complete: {len(results)} matches.")

                self.root.after(0, done)
            except Exception as exc:
                self.root.after(0, lambda e=exc: self.status_var.set(f"{UI_TEXT['status_error_prefix']}{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _restore_global_search_state(self):
        saved_results = self._get_ui_pref("global_search_results", [])
        if not isinstance(saved_results, list):
            saved_results = []

        normalized = []
        for item in saved_results[:200]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "source": str(item.get("source", "")),
                    "title": str(item.get("title", "")),
                    "location": str(item.get("location", "")),
                    "snippet": str(item.get("snippet", "")),
                    "category": str(item.get("category", "General")),
                }
            )

        if normalized:
            self._populate_global_search_results(normalized)
            selected_idx = int(self._get_ui_pref("global_search_selected_index", 0) or 0)
            selected_idx = max(0, min(selected_idx, len(normalized) - 1))
            if self.global_search_results_tree is not None:
                self.global_search_results_tree.selection_set(str(selected_idx))
                self.global_search_results_tree.focus(str(selected_idx))
                self._on_global_search_select()

    def _run_global_search(self, query):
        needle = query.lower()
        like = f"%{query}%"
        results = []
        max_results = 200

        def add_result(source, title, location, snippet, category="General"):
            if len(results) >= max_results:
                return
            
            # Clean up snippet based on its type
            if isinstance(snippet, str):
                # Remove excessive whitespace while preserving structure
                clean_lines = []
                for line in snippet.split('\n'):
                    line = line.strip()
                    if line:
                        clean_lines.append(line)
                
                if clean_lines:
                    # Join lines with appropriate spacing
                    if len(clean_lines) == 1:
                        clean = clean_lines[0]
                    else:
                        # For multi-line content, preserve the structure
                        clean = '\n'.join(clean_lines)
                else:
                    clean = ""
            else:
                # Convert non-string to string and clean
                clean = " ".join(str(snippet).split())
            
            # Apply length limit more intelligently
            if len(clean) > 300:
                if '\n' in clean:
                    # For structured content, try to preserve complete lines
                    lines = clean.split('\n')
                    truncated = []
                    current_length = 0
                    for line in lines:
                        if current_length + len(line) + 1 <= 297:  # Leave room for "..."
                            truncated.append(line)
                            current_length += len(line) + 1
                        else:
                            break
                    clean = '\n'.join(truncated) + "..."
                else:
                    # For single line, simple truncation
                    clean = clean[:297] + "..."
            
            results.append(
                {
                    "source": source,
                    "title": title,
                    "location": location,
                    "snippet": clean,
                    "category": category,
                }
            )

        def format_json_snippet(json_str, query):
            """Format JSON snippet to be more readable and highlight context"""
            try:
                import json
                data = json.loads(json_str)
                
                def format_value(value):
                    """Format individual values for display"""
                    if isinstance(value, str):
                        # Clean up strings, remove extra whitespace
                        value = " ".join(value.split())
                        if len(value) > 60:
                            value = value[:57] + "..."
                        return f'"{value}"'
                    elif isinstance(value, (int, float)):
                        return str(value)
                    elif isinstance(value, bool):
                        return str(value)
                    elif isinstance(value, list):
                        return f"[{len(value)} items]"
                    elif isinstance(value, dict):
                        return f"{{{len(value)} keys}}"
                    else:
                        return str(value)[:30]
                
                # Extract meaningful fields based on data type
                if isinstance(data, dict):
                    # Look for the query in values and provide context
                    matching_fields = []
                    important_fields = []
                    
                    # Priority order for important keys
                    priority_keys = ['name', 'title', 'type', 'description', 'id', 'skill', 'level', 'damage', 'armor']
                    
                    for key in priority_keys:
                        if key in data:
                            value = data[key]
                            formatted_value = format_value(value)
                            
                            # Check if this field matches the query
                            if isinstance(value, str) and needle in value.lower():
                                matching_fields.append(f"• {key.title()}: {formatted_value}")
                            elif str(value) in query:
                                matching_fields.append(f"• {key.title()}: {formatted_value}")
                            else:
                                important_fields.append(f"• {key.title()}: {formatted_value}")
                    
                    # Look for other matching fields
                    for key, value in data.items():
                        if key in priority_keys:
                            continue  # Already processed
                        
                        if isinstance(value, str) and needle in value.lower():
                            formatted_value = format_value(value)
                            matching_fields.append(f"• {key.title()}: {formatted_value}")
                        elif isinstance(value, (int, float)) and str(value) in query:
                            formatted_value = format_value(value)
                            matching_fields.append(f"• {key.title()}: {formatted_value}")
                    
                    # Combine matching fields first, then important fields
                    all_fields = matching_fields[:3]  # Limit to 3 matching fields
                    if not all_fields and important_fields:
                        all_fields = important_fields[:2]  # Show 2 important fields if no matches
                    
                    if all_fields:
                        return "\n".join(all_fields)
                    else:
                        # Fallback: show first few fields
                        fallback_fields = []
                        for key, value in list(data.items())[:3]:
                            formatted_value = format_value(value)
                            fallback_fields.append(f"• {key.title()}: {formatted_value}")
                        return "\n".join(fallback_fields)
                
                # Handle arrays
                elif isinstance(data, list) and data:
                    if len(data) <= 3:
                        return f"Array: [{', '.join(format_value(item) for item in data)}]"
                    else:
                        return f"Array: [{format_value(data[0])}, {format_value(data[1])}, ... ({len(data)} items)]"
                
                # Handle other types
                else:
                    return format_value(data)
                    
            except:
                # Fallback for invalid JSON - clean up the text
                clean_text = " ".join(str(json_str).split())
                if len(clean_text) > 100:
                    clean_text = clean_text[:97] + "..."
                return clean_text

        # Search Data DB with better formatting
        data_db = get_db_path(config.DATA_DIR)
        if data_db.exists():
            with sqlite3.connect(data_db) as conn:
                rows = conn.execute(
                    """
                    SELECT filename, row_index, row_key, payload
                    FROM data_rows
                    WHERE search_text LIKE ?
                    LIMIT 80
                    """,
                    (like,),
                ).fetchall()
            for row in rows:
                filename = row[0]
                row_key = row[2] or '(no key)'
                
                # Create more descriptive title
                if filename.endswith('.json'):
                    title = f"📄 {filename.replace('.json', '')} - {row_key}"
                else:
                    title = f"📄 {filename} - {row_key}"
                
                # Format location more clearly
                location = f"Data: {filename} (Row {row[1]})"
                
                # Better snippet formatting
                snippet = format_json_snippet(row[3], query)
                
                add_result(
                    "Database",
                    title,
                    location,
                    snippet,
                    "Game Data"
                )
                if len(results) >= max_results:
                    return results

        # Search Itemizer DB with better formatting
        item_db = config.DATA_DIR / "itemizer.db"
        if item_db.exists():
            with sqlite3.connect(item_db) as conn:
                rows = conn.execute(
                    """
                    SELECT r.file_name, r.server, r.character, i.item_name, i.raw_json
                    FROM items i
                    JOIN reports r ON r.id = i.report_id
                    WHERE i.search_text LIKE ? OR i.item_name LIKE ?
                    LIMIT 80
                    """,
                    (like, like),
                ).fetchall()
            for row in rows:
                item_name = row[3] or 'Unknown Item'
                character = row[2] or 'Unknown Character'
                server = row[1] or 'Unknown Server'
                
                # More descriptive title
                title = f"🎒 {item_name}"
                
                # Better location format
                location = f"Inventory: {character} @ {server}"
                
                # Format snippet from item JSON
                snippet = format_json_snippet(row[4], query)
                
                add_result(
                    "Items",
                    title,
                    location,
                    snippet,
                    "Inventory"
                )
                if len(results) >= max_results:
                    return results

        def format_text_snippet(text, query, idx):
                """Format text snippet with better structure and highlighting"""
                # Extract context around the match
                context_size = 60
                start = max(0, idx - context_size)
                end = min(len(text), idx + max(context_size, len(query) + context_size))
                
                # Get the snippet
                snippet = text[start:end]
                
                # Clean up whitespace
                snippet = " ".join(snippet.split())
                
                # Find the actual match position in the cleaned snippet
                cleaned_idx = snippet.lower().find(needle)
                if cleaned_idx >= 0:
                    # Add highlighting markers around the match
                    match_start = cleaned_idx
                    match_end = cleaned_idx + len(query)
                    highlighted = (
                        snippet[:match_start] + 
                        "🔸" + snippet[match_start:match_end] + "🔸" + 
                        snippet[match_end:]
                    )
                    snippet = highlighted
                
                # Add ellipsis to show truncation
                if start > 0:
                    snippet = "..." + snippet
                if end < len(text):
                    snippet = snippet + "..."
                
                return snippet

        # Search files with better categorization
        search_roots = [config.DATA_DIR]
        reports_dir = self._get_reports_dir()
        if reports_dir is not None and reports_dir.exists():
            search_roots.append(reports_dir)

        allowed_suffixes = {".json", ".txt", ".log", ".ini"}
        for root in search_roots:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                idx = text.lower().find(needle)
                if idx < 0:
                    continue
                
                # Use the new formatting function
                snippet = format_text_snippet(text, query, idx)
                
                # Determine file category and create appropriate title
                suffix = path.suffix.lower()
                if suffix == ".json":
                    if "character" in path.name.lower():
                        category = "Character"
                        title = f"👤 {path.name}"
                    elif "item" in path.name.lower():
                        category = "Items"
                        title = f"🎒 {path.name}"
                    else:
                        category = "Data"
                        title = f"📄 {path.name}"
                elif suffix == ".log":
                    category = "Logs"
                    title = f"📋 {path.name}"
                elif suffix == ".txt":
                    category = "Text"
                    title = f"📝 {path.name}"
                else:
                    category = "Config"
                    title = f"⚙️ {path.name}"
                
                # Better location format
                relative_path = path.relative_to(root.parent) if root.parent else path
                location = f"File: {relative_path}"
                
                add_result(
                    "File",
                    title,
                    location,
                    snippet,
                    category
                )
                if len(results) >= max_results:
                    return results

        return results

    def _build_settings_content(self, parent):
        shell = ttk.Frame(parent, padding=16, style="App.Card.TFrame")
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text=UI_TEXT["header_text"], style="App.Header.TLabel").pack(anchor="w", pady=(0, 8))

        paths_frame = ttk.Frame(shell, style="App.Card.TFrame")
        paths_frame.pack(fill="x")
        
        # Timer configuration frame
        timer_frame = ttk.LabelFrame(shell, text="⏱️ Timer Settings", 
                                     style="App.Card.TFrame", padding=10)
        timer_frame.pack(fill="x", pady=(10, 0))
        
        # Auto-start settings
        auto_frame = ttk.Frame(timer_frame, style="App.Panel.TFrame")
        auto_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Checkbutton(auto_frame, text="Auto-start timers from chat events", 
                       variable=self.timer_auto_start_var, style="App.TCheckbutton",
                       command=self._save_timer_settings).pack(anchor="w")
        
        # Scan interval
        interval_frame = ttk.Frame(timer_frame, style="App.Panel.TFrame")
        interval_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Label(interval_frame, text="Chat Scan Interval (seconds):", 
                 style="App.TLabel").pack(side="left", padx=5)
        
        interval_spinbox = ttk.Spinbox(interval_frame, from_=1, to=30, 
                                      textvariable=self.timer_scan_interval_var, 
                                      style="App.TSpinbox", width=10)
        interval_spinbox.pack(side="left", padx=5)
        
        # Notifications
        notification_frame = ttk.Frame(timer_frame, style="App.Panel.TFrame")
        notification_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Checkbutton(notification_frame, text="Enable timer notifications", 
                           variable=self.timer_notification_var, style="App.TCheckbutton",
                           command=self._save_timer_settings).pack(anchor="w")
        
        # Timer durations management
        durations_frame = ttk.LabelFrame(timer_frame, text="⏱️ Default Durations", 
                                        style="App.Card.TFrame", padding=10)
        durations_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Label(durations_frame, text="Manage default timer durations for activities:", 
                 style="App.TLabel").pack(anchor="w", pady=(0, 5))
        
        ttk.Button(durations_frame, text="Open Duration Manager", 
                 command=self._open_duration_manager, style="App.Secondary.TButton").pack(pady=10)
        
        # Chat Monitor configuration frame
        chat_frame = ttk.LabelFrame(shell, text="💬 Chat Monitor Settings", 
                                     style="App.Card.TFrame", padding=10)
        chat_frame.pack(fill="x", pady=(10, 0))
        
        # Auto-start settings
        chat_auto_frame = ttk.Frame(chat_frame, style="App.Panel.TFrame")
        chat_auto_frame.pack(fill="x")
        
        ttk.Checkbutton(chat_auto_frame, text="Auto-start chat monitor on program startup", 
                       variable=self.chat_auto_start_var, style="App.TCheckbutton",
                       command=self._save_chat_settings).pack(anchor="w")
        
        # Button row for actions
        button_row = ttk.Frame(shell, style="App.Panel.TFrame")
        button_row.pack(fill="x", pady=14)

        self.locate_button = ttk.Button(
            button_row,
            text=UI_TEXT["locate_button"],
            command=self.locate_pg,
            style="App.Primary.TButton",
        )
        self.locate_button.pack(side="left", padx=(0, 8))

        self.download_button = ttk.Button(
            button_row,
            text=UI_TEXT["download_button"],
            command=self.download_newer_files,
            style="App.Primary.TButton",
        )
        self.download_button.pack(side="left", padx=(0, 8))

        self.reset_button = ttk.Button(
            button_row,
            text=UI_TEXT["reset_button"],
            command=self.reset_paths,
            style="App.Secondary.TButton",
        )
        self.reset_button.pack(side="left", padx=(0, 8))

        self.dependencies_button = ttk.Button(
            button_row,
            text="Check Dependencies",
            command=self._check_dependencies,
            style="App.Secondary.TButton",
        )
        self.dependencies_button.pack(side="left")

        ttk.Label(shell, textvariable=self.status_var, style="App.Status.TLabel").pack(anchor="w")

    def open_settings_window(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        self.settings_window = self.create_themed_toplevel("settings", "Settings", on_close=self._on_close_settings_window)
        self.settings_window.configure(bg=self.root.cget("bg"))

        container = ttk.Frame(
            self.settings_window,
            padding=12,
            style="App.Panel.TFrame",
        )
        container.pack(fill="both", expand=True)
        self._build_settings_content(container)
        self.settings_window.update_idletasks()
        req_w = max(620, self.settings_window.winfo_reqwidth())
        req_h = max(260, self.settings_window.winfo_reqheight())
        self._apply_saved_window_geometry("settings", self.settings_window, req_w, req_h)
        self.settings_window.minsize(req_w, req_h)
        self._set_window_open_state("settings", True)
        self.refresh_config_view()

    def _on_close_settings_window(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self._save_window_geometry("settings", self.settings_window)
            self.settings_window.destroy()
        self._set_window_open_state("settings", False)
        self.settings_window = None

    def _check_dependencies(self):
        """Check and manage PGLOK dependencies."""
        try:
            # Use simple dependency checker to prevent crashes
            from simple_dependency_checker import safe_show_dependency_checker
            success = safe_show_dependency_checker(self)
            
            if not success:
                print("Warning: Dependency checker failed to open")
                
        except Exception as e:
            print(f"Error in dependency checker: {e}")
            # Show user-friendly error message
            try:
                messagebox.showerror("Error", f"Failed to open dependency checker: {e}")
            except:
                print("Could not show error message")

    def open_data_browser_window(self):
        if self.data_browser_window is not None and self.data_browser_window.winfo_exists():
            self.data_browser_window.deiconify()
            self.data_browser_window.lift()
            self.data_browser_window.focus_force()
            return

        self.data_browser_window = self.create_themed_toplevel("data_browser", "Data Browser", on_close=self._on_close_data_browser_window)
        self.data_browser_window.bind("<Configure>", self._on_data_browser_window_configure)

        shell = ttk.Frame(self.data_browser_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Data Browser", style="Data.Header.TLabel").pack(side="left")

        # Always-on-top toggle for the Data Browser window
        self.data_browser_pin_var = tk.BooleanVar(value=bool(self._get_ui_pref("data_browser_always_on_top", False)))
        ttk.Checkbutton(
            header,
            text="Always on Top",
            variable=self.data_browser_pin_var,
            command=self._toggle_data_browser_always_on_top,
            style="App.TCheckbutton",
        ).pack(side="right", padx=(6, 0))

        ttk.Button(header, text="Refresh Index", command=self._refresh_data_index_async, style="Data.Primary.TButton").pack(
            side="right"
        )

        # Apply saved always-on-top state for this window
        try:
            self.data_browser_window.attributes("-topmost", bool(self.data_browser_pin_var.get()))
        except Exception:
            pass

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.data_browser_paned = body
        body.bind("<ButtonRelease-1>", self._on_data_browser_pane_resize)

        left = ttk.Frame(body, padding=10, style="App.Card.TFrame")
        right = ttk.Frame(body, padding=10, style="App.Card.TFrame")
        body.add(left, weight=1)
        body.add(right, weight=3)

        ttk.Label(left, text="Files", style="Data.Header.TLabel").pack(anchor="w")
        self.data_file_listbox = tk.Listbox(
            left,
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            selectbackground=UI_COLORS["secondary_active"],
            selectforeground=UI_COLORS["accent"],
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
            font=(UI_ATTRS["font_family"], self.data_browser_font_size),
        )
        self.data_file_listbox.pack(fill="both", expand=True, pady=(8, 0))
        self.data_file_listbox.bind("<<ListboxSelect>>", self._on_data_file_select)
        self.data_file_listbox.bind("<Button-3>", self._show_data_file_context_menu)
        self.data_file_listbox.bind("<Button-2>", self._show_data_file_context_menu)

        control_row = ttk.Frame(right, style="App.Card.TFrame")
        control_row.pack(fill="x")
        ttk.Label(control_row, text="Search:", style="Data.TLabel").pack(side="left")
        search_entry = ttk.Entry(control_row, textvariable=self.data_search_var, style="Data.TEntry")
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.entry_spellcheck.register(search_entry)
        search_entry.bind("<Return>", lambda _event: self._load_data_rows(reset_offset=True))
        search_entry.bind("<Button-1>", lambda _e: self._select_all_text(search_entry))
        ttk.Button(
            control_row,
            text="Apply",
            command=lambda: self._load_data_rows(reset_offset=True),
            style="Data.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            control_row,
            text="Reset",
            command=self._reset_data_filters,
            style="Data.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(control_row, text="Prev", command=self._prev_data_page, style="Data.Secondary.TButton").pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(control_row, text="Next", command=self._next_data_page, style="Data.Secondary.TButton").pack(side="left")

        ttk.Label(right, textvariable=self.data_page_var, style="Data.Status.TLabel").pack(anchor="w", pady=(8, 6))

        display_paned = ttk.Panedwindow(right, orient="vertical")
        display_paned.pack(fill="both", expand=True)
        self.data_browser_display_paned = display_paned
        display_paned.bind("<ButtonRelease-1>", self._on_data_browser_display_pane_resize)

        top_display = ttk.Frame(display_paned, style="App.Card.TFrame")
        bottom_display = ttk.Frame(display_paned, style="App.Card.TFrame")
        display_paned.add(top_display, weight=3)
        display_paned.add(bottom_display, weight=2)

        self.data_rows_tree = ttk.Treeview(
            top_display,
            columns=("row_index", "row_key", "preview"),
            show="headings",
            height=14,
            style="Data.Treeview",
        )
        self.data_rows_tree.heading("row_index", text="#")
        self.data_rows_tree.heading("row_key", text="Key")
        self.data_rows_tree.heading("preview", text="Preview")
        self.data_rows_tree.column("row_index", width=70, stretch=False)
        self.data_rows_tree.column("row_key", width=220, stretch=False)
        self.data_rows_tree.column("preview", width=1100, stretch=False)
        data_tree_xscroll = ttk.Scrollbar(top_display, orient="horizontal", style="App.Horizontal.TScrollbar")
        self.data_rows_tree.configure(xscrollcommand=data_tree_xscroll.set)
        data_tree_xscroll.configure(command=self.data_rows_tree.xview)
        self.data_rows_tree.pack(fill="both", expand=True)
        data_tree_xscroll.pack(fill="x", pady=(2, 0))
        self.data_rows_tree.bind("<<TreeviewSelect>>", self._on_data_row_select)
        self.data_rows_tree.bind("<Button-3>", self._show_data_tree_context_menu)
        self.data_rows_tree.bind("<Button-2>", self._show_data_tree_context_menu)

        ttk.Label(bottom_display, text="Details", style="Data.Header.TLabel").pack(anchor="w", pady=(2, 4))
        self.data_json_text = tk.Text(
            bottom_display,
            height=12,
            wrap="none",
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            font=(UI_ATTRS["font_family"], self.data_browser_font_size),
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
        )
        self.data_json_text.pack(fill="both", expand=True)
        self.data_json_text.bind("<Button-3>", self._show_data_text_context_menu)
        self.data_json_text.bind("<Button-2>", self._show_data_text_context_menu)
        data_text_xscroll = ttk.Scrollbar(bottom_display, orient="horizontal", style="App.Horizontal.TScrollbar")
        self.data_json_text.configure(xscrollcommand=data_text_xscroll.set)
        data_text_xscroll.configure(command=self.data_json_text.xview)
        data_text_xscroll.pack(fill="x", pady=(2, 0))
        self._apply_data_browser_font_size()
        self._bind_data_browser_zoom_events(self.data_browser_window)

        self.data_browser_window.update_idletasks()
        screen_w = max(640, int(self.data_browser_window.winfo_screenwidth()))
        screen_h = max(480, int(self.data_browser_window.winfo_screenheight()))
        req_w = min(max(900, self.data_browser_window.winfo_reqwidth()), max(480, screen_w - 80))
        req_h = min(max(560, self.data_browser_window.winfo_reqheight()), max(320, screen_h - 100))
        self._apply_saved_window_geometry("data_browser", self.data_browser_window, req_w, req_h)
        self.data_browser_window.minsize(min(760, req_w), min(500, req_h))
        self._set_window_open_state("data_browser", True)
        self.data_browser_window.after(10, self._restore_data_browser_pane_split)
        self.data_browser_window.after(20, self._restore_data_browser_display_pane_split)
        self._refresh_data_index_async()

    def _on_close_data_browser_window(self):
        if self._data_search_after_id is not None:
            try:
                self.root.after_cancel(self._data_search_after_id)
            except tk.TclError:
                pass
            self._data_search_after_id = None
        if self._data_browser_resize_after_id is not None:
            try:
                self.root.after_cancel(self._data_browser_resize_after_id)
            except tk.TclError:
                pass
            self._data_browser_resize_after_id = None
        if self.data_browser_window is not None and self.data_browser_window.winfo_exists():
            self._set_ui_pref("data_browser_search", self.data_search_var.get().strip())
            self._set_ui_pref("data_browser_offset", int(self.data_offset))
            if self.data_selected_filename:
                self._set_ui_pref("data_browser_selected_file", self.data_selected_filename)
            self._save_data_browser_pane_split()
            self._save_data_browser_display_pane_split()
            self._save_window_geometry("data_browser", self.data_browser_window)
            self.data_browser_window.destroy()
        self._set_window_open_state("data_browser", False)
        self.data_browser_window = None
        self.data_browser_paned = None
        self.data_browser_display_paned = None
        self.data_file_listbox = None
        self.data_rows_tree = None
        self.data_json_text = None
        self.data_selected_filename = None
        self.data_offset = 0
        self.data_total_rows = 0

    def _toggle_data_browser_always_on_top(self) -> None:
        """Toggle always-on-top state for the Data Browser window only."""
        if self.data_browser_window is None or not self.data_browser_window.winfo_exists():
            return
        enabled = bool(self.data_browser_pin_var.get())
        try:
            self.data_browser_window.attributes("-topmost", enabled)
        except Exception:
            return
        try:
            self._set_ui_pref("data_browser_always_on_top", enabled)
        except Exception:
            pass

    def _on_data_browser_window_configure(self, event):
        if self.data_browser_window is None or event.widget is not self.data_browser_window:
            return
        if self._data_browser_resize_after_id is not None:
            self.root.after_cancel(self._data_browser_resize_after_id)
        self._data_browser_resize_after_id = self.root.after(300, self._save_data_browser_window_state)

    def _save_data_browser_window_state(self):
        self._data_browser_resize_after_id = None
        self._save_window_geometry("data_browser", self.data_browser_window)

    def _on_data_browser_pane_resize(self, _event=None):
        self._save_data_browser_pane_split()

    def _on_data_browser_display_pane_resize(self, _event=None):
        self._save_data_browser_display_pane_split()

    def _save_data_browser_pane_split(self):
        if self.data_browser_paned is None or not self.data_browser_paned.winfo_exists():
            return
        try:
            split = int(self.data_browser_paned.sashpos(0))
        except (tk.TclError, ValueError):
            return
        self._set_ui_pref("data_browser_split", split)

    def _restore_data_browser_pane_split(self):
        if self.data_browser_paned is None or not self.data_browser_paned.winfo_exists():
            return
        split = self._get_ui_pref("data_browser_split", None)
        if split is None:
            return
        try:
            max_width = max(300, self.data_browser_paned.winfo_width() - 360)
            clamped = min(max(int(split), 180), max_width)
            self.data_browser_paned.sashpos(0, clamped)
        except (tk.TclError, ValueError):
            return

    def _save_data_browser_display_pane_split(self):
        if self.data_browser_display_paned is None or not self.data_browser_display_paned.winfo_exists():
            return
        try:
            split = int(self.data_browser_display_paned.sashpos(0))
        except (tk.TclError, ValueError):
            return
        self._set_ui_pref("data_browser_display_split", split)

    def _restore_data_browser_display_pane_split(self):
        if self.data_browser_display_paned is None or not self.data_browser_display_paned.winfo_exists():
            return
        split = self._get_ui_pref("data_browser_display_split", None)
        if split is None:
            return
        try:
            max_height = max(260, self.data_browser_display_paned.winfo_height() - 220)
            clamped = min(max(int(split), 160), max_height)
            self.data_browser_display_paned.sashpos(0, clamped)
        except (tk.TclError, ValueError):
            return

    def open_itemizer_window(self):
        if self.itemizer_window is not None and self.itemizer_window.winfo_exists():
            self.itemizer_window.deiconify()
            self.itemizer_window.lift()
            self.itemizer_window.focus_force()
            return

        self.itemizer_window = self.create_themed_toplevel("itemizer", "Itemizer", on_close=self._on_close_itemizer_window)
        self.itemizer_window.bind("<Configure>", self._on_itemizer_window_configure)

        shell = ttk.Frame(self.itemizer_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        header.columnconfigure(2, weight=0)
        header.columnconfigure(3, weight=1)
        ttk.Label(header, text="Itemizer", style="App.Header.TLabel").grid(row=0, column=1)
        ttk.Button(header, text="Refresh Index", command=self._refresh_itemizer_index_async, style="App.Primary.TButton").grid(
            row=0, column=2, sticky="e"
        )
        # Independent always-on-top toggle for the Itemizer window
        self.itemizer_pin_var = tk.BooleanVar(value=bool(self._get_ui_pref("itemizer_always_on_top", False)))
        ttk.Checkbutton(
            header,
            text="Always on Top",
            variable=self.itemizer_pin_var,
            command=self._toggle_itemizer_always_on_top,
            style="App.TCheckbutton",
        ).grid(row=0, column=3, sticky="e", padx=(8, 0))

        # Apply saved always-on-top state for the Itemizer window
        try:
            self.itemizer_window.attributes("-topmost", bool(self.itemizer_pin_var.get()))
        except Exception:
            pass

        filters = ttk.Frame(shell, padding=10, style="App.Card.TFrame")
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="Server:", style="App.TLabel").pack(side="left")
        self.itemizer_server_combo = ttk.Combobox(
            filters,
            textvariable=self.itemizer_server_var,
            state="readonly",
            width=18,
            style="App.TCombobox",
        )
        self.itemizer_server_combo.pack(side="left", padx=(6, 10))
        self.itemizer_server_combo.bind("<<ComboboxSelected>>", lambda _e: self._load_itemizer_rows(reset_offset=True))

        ttk.Label(filters, text="Character:", style="App.TLabel").pack(side="left")
        self.itemizer_character_combo = ttk.Combobox(
            filters,
            textvariable=self.itemizer_character_var,
            state="readonly",
            width=18,
            style="App.TCombobox",
        )
        self.itemizer_character_combo.pack(side="left", padx=(6, 10))
        self.itemizer_character_combo.bind("<<ComboboxSelected>>", lambda _e: self._load_itemizer_rows(reset_offset=True))

        ttk.Label(filters, text="Search:", style="App.TLabel").pack(side="left")
        search_entry = ttk.Entry(filters, textvariable=self.itemizer_search_var, style="App.TEntry")
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.entry_spellcheck.register(search_entry)
        search_entry.bind("<Return>", lambda _e: self._load_itemizer_rows(reset_offset=True))
        search_entry.bind("<Button-1>", lambda _e: self._select_all_text(search_entry))
        ttk.Button(
            filters,
            text="Apply",
            command=lambda: self._load_itemizer_rows(reset_offset=True),
            style="App.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            filters,
            text="Reset",
            command=self._reset_itemizer_filters,
            style="App.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(filters, text="Prev", command=self._prev_itemizer_page, style="App.Secondary.TButton").pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(filters, text="Next", command=self._next_itemizer_page, style="App.Secondary.TButton").pack(side="left")

        status_row = ttk.Frame(shell, style="App.Panel.TFrame")
        status_row.pack(fill="x", pady=(0, 6))
        ttk.Label(status_row, textvariable=self.itemizer_page_var, style="App.Status.TLabel").pack(side="left")
        ttk.Label(status_row, textvariable=self.itemizer_totals_var, style="App.Status.TLabel").pack(side="right")

        body = ttk.Panedwindow(shell, orient="vertical")
        body.pack(fill="both", expand=True)
        self.itemizer_paned = body
        top = ttk.Frame(body, padding=10, style="App.Card.TFrame")
        bottom = ttk.Frame(body, padding=10, style="App.Card.TFrame")
        body.add(top, weight=4)
        body.add(bottom, weight=1)
        body.bind("<ButtonRelease-1>", self._on_itemizer_pane_resize)

        self.itemizer_tree = ttk.Treeview(
            top,
            columns=("server", "character", "item", "qty", "value", "rarity", "slot", "location", "timestamp"),
            show="headings",
            style="App.Treeview",
            height=14,
        )
        self.itemizer_tree.heading("server", text="Server")
        self.itemizer_tree.heading("character", text="Character")
        self.itemizer_tree.heading("item", text="Item")
        self.itemizer_tree.heading("qty", text="Qty")
        self.itemizer_tree.heading("value", text="Value")
        self.itemizer_tree.heading("rarity", text="Rarity")
        self.itemizer_tree.heading("slot", text="Slot")
        self.itemizer_tree.heading("location", text="Location")
        self.itemizer_tree.heading("timestamp", text="Timestamp")
        self.itemizer_tree.column("server", width=120, stretch=False)
        self.itemizer_tree.column("character", width=140, stretch=False)
        self.itemizer_tree.column("item", width=260, stretch=True)
        self.itemizer_tree.column("qty", width=60, stretch=False, anchor="e")
        self.itemizer_tree.column("value", width=70, stretch=False, anchor="e")
        self.itemizer_tree.column("rarity", width=100, stretch=False)
        self.itemizer_tree.column("slot", width=110, stretch=False)
        self.itemizer_tree.column("location", width=120, stretch=False)
        self.itemizer_tree.column("timestamp", width=190, stretch=False)
        self._restore_itemizer_column_widths()
        self.itemizer_tree.pack(fill="both", expand=True)
        self.itemizer_tree.bind("<<TreeviewSelect>>", self._on_itemizer_row_select)
        self.itemizer_tree.bind("<ButtonRelease-1>", self._on_itemizer_tree_mouse_release, add="+")

        # Configure rarity color tags for the Itemizer tree
        self.itemizer_tree.tag_configure("rarity_rare", foreground=UI_COLORS["rarity_rare"])
        self.itemizer_tree.tag_configure("rarity_uncommon", foreground=UI_COLORS["rarity_uncommon"])
        self.itemizer_tree.tag_configure("rarity_exceptional", foreground=UI_COLORS["rarity_exceptional"])
        self.itemizer_tree.tag_configure("rarity_epic", foreground=UI_COLORS["rarity_epic"])
        self.itemizer_tree.tag_configure("rarity_legendary", foreground=UI_COLORS["rarity_legendary"])

        bottom_split = ttk.Panedwindow(bottom, orient="horizontal")
        bottom_split.pack(fill="both", expand=True)
        self.itemizer_bottom_paned = bottom_split
        bottom_split.bind("<ButtonRelease-1>", self._on_itemizer_bottom_pane_resize)
        json_wrap = ttk.Frame(bottom_split, style="App.Card.TFrame")
        notes_wrap = ttk.Frame(bottom_split, style="App.Card.TFrame")
        bottom_split.add(json_wrap, weight=1)
        bottom_split.add(notes_wrap, weight=1)

        json_inner = ttk.Frame(json_wrap, padding=(0, 0, 6, 0), style="App.Card.TFrame")
        json_inner.pack(fill="both", expand=True)
        notes_inner = ttk.Frame(notes_wrap, padding=(6, 0, 0, 0), style="App.Card.TFrame")
        notes_inner.pack(fill="both", expand=True)

        self.itemizer_json_text = tk.Text(
            json_inner,
            wrap="none",
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
        )
        self.itemizer_json_text.pack(fill="both", expand=True)

        notes_header = ttk.Frame(notes_inner, style="App.Card.TFrame")
        notes_header.pack(fill="x", pady=(0, 2))
        notes_header.columnconfigure(0, weight=1)
        notes_header.columnconfigure(1, weight=0)
        notes_header.columnconfigure(2, weight=1)
        ttk.Label(notes_header, text="Character Notes", style="App.TLabel").grid(row=0, column=1)
        save_notes_btn = ttk.Button(
            notes_header,
            text="Save Notes",
            command=self._save_itemizer_character_notes,
            style="App.Secondary.TButton",
            width=10,
        )
        save_notes_btn.grid(row=0, column=2, sticky="e")

        notes_body = ttk.Frame(notes_inner, style="App.Card.TFrame")
        notes_body.pack(fill="both", expand=True)
        notes_scroll = ttk.Scrollbar(notes_body, orient="vertical", style="App.Vertical.TScrollbar")
        notes_scroll.pack(side="right", fill="y")

        self.itemizer_notes_canvas = tk.Canvas(
            notes_body,
            bg=UI_COLORS["entry_bg"],
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            relief="solid",
            bd=0,
            yscrollcommand=notes_scroll.set,
        )
        self.itemizer_notes_canvas.pack(side="left", fill="both", expand=True)
        notes_scroll.configure(command=self.itemizer_notes_canvas.yview)

        self.itemizer_notes_inner = ttk.Frame(self.itemizer_notes_canvas, style="App.Card.TFrame")
        self.itemizer_notes_window_id = self.itemizer_notes_canvas.create_window(
            (0, 0), window=self.itemizer_notes_inner, anchor="nw"
        )
        self.itemizer_notes_inner.bind("<Configure>", self._on_itemizer_notes_inner_configure)
        self.itemizer_notes_canvas.bind("<Configure>", self._on_itemizer_notes_canvas_configure)
        self._render_itemizer_character_notes([])

        self.itemizer_window.update_idletasks()
        screen_w = max(640, int(self.itemizer_window.winfo_screenwidth()))
        screen_h = max(480, int(self.itemizer_window.winfo_screenheight()))
        req_w = min(max(980, self.itemizer_window.winfo_reqwidth()), max(480, screen_w - 80))
        req_h = min(max(580, self.itemizer_window.winfo_reqheight()), max(320, screen_h - 100))
        self._apply_saved_window_geometry("itemizer", self.itemizer_window, req_w, req_h)
        self.itemizer_window.minsize(min(860, req_w), min(520, req_h))
        self._set_window_open_state("itemizer", True)
        self.itemizer_window.after(10, self._restore_itemizer_pane_split)
        self.itemizer_window.after(20, self._restore_itemizer_bottom_pane_split)
        self._refresh_itemizer_index_async()

    def _toggle_itemizer_always_on_top(self) -> None:
        """Toggle always-on-top state for the Itemizer window only."""
        if self.itemizer_window is None or not self.itemizer_window.winfo_exists():
            return
        enabled = bool(self.itemizer_pin_var.get())
        try:
            self.itemizer_window.attributes("-topmost", enabled)
        except Exception:
            return
        # Persist preference
        try:
            self._set_ui_pref("itemizer_always_on_top", enabled)
        except Exception:
            pass

    def _on_close_itemizer_window(self):
        if self._itemizer_resize_after_id is not None:
            try:
                self.root.after_cancel(self._itemizer_resize_after_id)
            except tk.TclError:
                pass
            self._itemizer_resize_after_id = None
        if self.itemizer_window is not None and self.itemizer_window.winfo_exists():
            self._save_itemizer_pane_split()
            self._save_itemizer_bottom_pane_split()
            self._save_itemizer_column_widths()
            self._save_itemizer_character_notes()
            self._save_window_geometry("itemizer", self.itemizer_window)
            self.itemizer_window.destroy()
        self._set_window_open_state("itemizer", False)
        self.itemizer_window = None
        self.itemizer_tree = None
        self.itemizer_json_text = None
        self.itemizer_paned = None
        self.itemizer_bottom_paned = None
        self.itemizer_server_combo = None
        self.itemizer_character_combo = None
        self.itemizer_notes_canvas = None
        self.itemizer_notes_inner = None
        self.itemizer_notes_window_id = None
        self.itemizer_note_vars = {}
        self.itemizer_note_entry_widgets = {}
        self.itemizer_note_row_widgets = {}
        self.itemizer_drag_name = None
        self.itemizer_offset = 0
        self.itemizer_total_rows = 0
        self.itemizer_totals_var.set("Total Qty: 0   Total Value: 0")

    def _on_itemizer_window_configure(self, event):
        if self.itemizer_window is None or event.widget is not self.itemizer_window:
            return
        if self._itemizer_resize_after_id is not None:
            self.root.after_cancel(self._itemizer_resize_after_id)
        self._itemizer_resize_after_id = self.root.after(300, self._save_itemizer_window_state)

    def _save_itemizer_window_state(self):
        self._itemizer_resize_after_id = None
        self._save_window_geometry("itemizer", self.itemizer_window)

    def _refresh_itemizer_index_async(self):
        self.status_var.set("Indexing item reports...")

        def worker():
            try:
                result = index_item_reports(force_refresh=True)
                filters = itemizer_get_filter_values()

                def update_ui():
                    if self.itemizer_window is None:
                        return
                    servers = [""] + filters["servers"]
                    characters = [""] + filters["characters"]
                    if self.itemizer_server_combo is not None:
                        self.itemizer_server_combo["values"] = servers
                        if self.itemizer_server_var.get() not in servers:
                            self.itemizer_server_var.set("")
                    if self.itemizer_character_combo is not None:
                        self.itemizer_character_combo["values"] = characters
                        if self.itemizer_character_var.get() not in characters:
                            self.itemizer_character_var.set("")
                    self._render_itemizer_character_notes(filters["characters"])
                    self._load_itemizer_rows(reset_offset=True)
                    
                    # Show cleanup info if applicable
                    status_msg = f"Itemizer index ready: {result['indexed_reports']} updated, {result['skipped_reports']} skipped."
                    if result.get('files_removed', 0) > 0:
                        status_msg += f" {result['files_removed']} old file(s) removed, {result['files_kept']} kept."
                    if result.get('cleaned_reports', 0) > 0:
                        status_msg += f" {result['cleaned_reports']} orphaned reports removed."
                    if result.get('cleaned_items', 0) > 0:
                        status_msg += f" {result['cleaned_items']} orphaned items removed."
                    
                    self.status_var.set(status_msg)

                self.root.after(0, update_ui)
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _load_itemizer_rows(self, reset_offset=False):
        if self.itemizer_tree is None:
            return
        if reset_offset:
            self.itemizer_offset = 0

        selected_server = self.itemizer_server_var.get().strip()
        selected_character = self.itemizer_character_var.get().strip()
        search_text = self.itemizer_search_var.get().strip()

        rows, total = search_items(
            server=selected_server,
            character=selected_character,
            text=search_text,
            limit=self.itemizer_page_size,
            offset=self.itemizer_offset,
        )
        totals = search_item_totals(
            server=selected_server,
            character=selected_character,
            text=search_text,
        )
        self.itemizer_total_rows = total

        self.itemizer_tree.delete(*self.itemizer_tree.get_children())
        for row in rows:
            rarity = row.get("rarity", "")
            rarity_tag = f"rarity_{rarity.lower()}" if rarity else ""
            self.itemizer_tree.insert(
                "",
                tk.END,
                values=(
                    row["server"],
                    row["character"],
                    row["item_name"],
                    row["stack_size"],
                    row["value"],
                    row["rarity"],
                    row["slot"],
                    row["storage_vault"],
                    row["timestamp"],
                ),
                tags=(rarity_tag, row["raw_json"]),
            )

        if self.itemizer_json_text is not None:
            self.itemizer_json_text.delete("1.0", tk.END)

        page_num = (self.itemizer_offset // self.itemizer_page_size) + 1
        total_pages = max(1, (self.itemizer_total_rows + self.itemizer_page_size - 1) // self.itemizer_page_size)
        self.itemizer_page_var.set(f"Page {page_num} / {total_pages}   Rows: {self.itemizer_total_rows}")
        self.itemizer_totals_var.set(
            f"Total Qty: {totals['qty_total']:,}   Total Value: {totals['value_total']:,}"
        )
        self._set_ui_pref("itemizer_server", selected_server)
        self._set_ui_pref("itemizer_character", selected_character)
        self._set_ui_pref("itemizer_search", search_text)
        self._set_ui_pref("itemizer_offset", int(self.itemizer_offset))

    def _on_itemizer_row_select(self, _event=None):
        if self.itemizer_tree is None or self.itemizer_json_text is None:
            return
        selection = self.itemizer_tree.selection()
        if not selection:
            return
        tags = self.itemizer_tree.item(selection[0], "tags")
        # Tags tuple is (rarity_tag, raw_json); raw_json is at index 1
        payload = tags[1] if len(tags) > 1 else tags[0] if tags else ""
        self.itemizer_json_text.delete("1.0", tk.END)
        try:
            parsed = json.loads(payload)
            self.itemizer_json_text.insert("1.0", json.dumps(parsed, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            self.itemizer_json_text.insert("1.0", payload)

    def _reset_itemizer_filters(self):
        self.itemizer_server_var.set("")
        self.itemizer_character_var.set("")
        self.itemizer_search_var.set("")
        self._load_itemizer_rows(reset_offset=True)

    def _schedule_itemizer_live_search(self):
        if self._itemizer_search_after_id is not None:
            try:
                self.root.after_cancel(self._itemizer_search_after_id)
            except tk.TclError:
                pass
        self._itemizer_search_after_id = self.root.after(220, self._run_itemizer_live_search)

    def _run_itemizer_live_search(self):
        self._itemizer_search_after_id = None
        if self.itemizer_window is None or not self.itemizer_window.winfo_exists():
            return
        if self.itemizer_tree is None:
            return
        self._load_itemizer_rows(reset_offset=True)

    def _on_itemizer_pane_resize(self, _event=None):
        self._save_itemizer_pane_split()

    def _on_itemizer_bottom_pane_resize(self, _event=None):
        self._save_itemizer_bottom_pane_split()

    def _on_itemizer_tree_mouse_release(self, _event=None):
        self._save_itemizer_column_widths()

    def _save_itemizer_pane_split(self):
        if self.itemizer_paned is None or not self.itemizer_paned.winfo_exists():
            return
        try:
            split = int(self.itemizer_paned.sashpos(0))
        except (tk.TclError, ValueError):
            return
        self._set_ui_pref("itemizer_split", split)

    def _restore_itemizer_pane_split(self):
        if self.itemizer_paned is None or not self.itemizer_paned.winfo_exists():
            return
        split = self._get_ui_pref("itemizer_split", None)
        if split is None:
            return
        try:
            max_height = max(220, self.itemizer_paned.winfo_height() - 140)
            clamped = min(max(int(split), 160), max_height)
            self.itemizer_paned.sashpos(0, clamped)
        except (tk.TclError, ValueError):
            return

    def _save_itemizer_bottom_pane_split(self):
        if self.itemizer_bottom_paned is None or not self.itemizer_bottom_paned.winfo_exists():
            return
        try:
            split = int(self.itemizer_bottom_paned.sashpos(0))
        except (tk.TclError, ValueError):
            return
        self._set_ui_pref("itemizer_bottom_split", split)

    def _restore_itemizer_bottom_pane_split(self):
        if self.itemizer_bottom_paned is None or not self.itemizer_bottom_paned.winfo_exists():
            return
        split = self._get_ui_pref("itemizer_bottom_split", None)
        if split is None:
            return
        try:
            max_width = max(240, self.itemizer_bottom_paned.winfo_width() - 240)
            clamped = min(max(int(split), 240), max_width)
            self.itemizer_bottom_paned.sashpos(0, clamped)
        except (tk.TclError, ValueError):
            return

    def _save_itemizer_column_widths(self):
        if self.itemizer_tree is None or not self.itemizer_tree.winfo_exists():
            return
        widths = {}
        for col in ("server", "character", "item", "qty", "value", "rarity", "slot", "location", "timestamp"):
            try:
                widths[col] = int(self.itemizer_tree.column(col, "width"))
            except (tk.TclError, ValueError):
                continue
        if widths:
            self._set_ui_pref("itemizer_column_widths", widths)

    def _restore_itemizer_column_widths(self):
        if self.itemizer_tree is None or not self.itemizer_tree.winfo_exists():
            return
        widths = self._get_ui_pref("itemizer_column_widths", {})
        if not isinstance(widths, dict):
            return
        for col in ("server", "character", "item", "qty", "value", "rarity", "slot", "location", "timestamp"):
            width = widths.get(col)
            if width is None:
                continue
            try:
                parsed = int(width)
            except (TypeError, ValueError):
                continue
            if parsed >= 40:
                try:
                    self.itemizer_tree.column(col, width=parsed)
                except tk.TclError:
                    continue

    def _on_itemizer_notes_inner_configure(self, _event=None):
        if self.itemizer_notes_canvas is None or self.itemizer_notes_inner is None:
            return
        try:
            self.itemizer_notes_canvas.configure(scrollregion=self.itemizer_notes_canvas.bbox("all"))
        except tk.TclError:
            return

    def _on_itemizer_notes_canvas_configure(self, event=None):
        if self.itemizer_notes_canvas is None or self.itemizer_notes_inner is None or self.itemizer_notes_window_id is None:
            return
        if event is None:
            return
        try:
            self.itemizer_notes_canvas.itemconfigure(self.itemizer_notes_window_id, width=event.width)
        except tk.TclError:
            return

    def _render_itemizer_character_notes(self, character_names):
        if self.itemizer_notes_inner is None:
            return
        existing_notes = self._get_ui_pref("itemizer_character_notes", {})
        if not isinstance(existing_notes, dict):
            existing_notes = {}

        normalized = self._get_ordered_itemizer_character_names(character_names)
        current_values = {name: var.get() for name, var in self.itemizer_note_vars.items()}
        current_values.update({k: str(v) for k, v in existing_notes.items()})

        for child in self.itemizer_notes_inner.winfo_children():
            child.destroy()
        self.itemizer_note_vars = {}
        self.itemizer_note_entry_widgets = {}
        self.itemizer_note_row_widgets = {}

        if not normalized:
            ttk.Label(
                self.itemizer_notes_inner,
                text="No character names found.",
                style="App.Status.TLabel",
            ).pack(anchor="w", padx=6, pady=6)
            return

        for name in normalized:
            row = ttk.Frame(self.itemizer_notes_inner, style="App.Card.TFrame")
            row.pack(fill="x", padx=3, pady=1)
            name_label = ttk.Label(row, text=name, width=18, style="App.TLabel", cursor="fleur")
            name_label.pack(side="left")
            name_label.bind("<ButtonPress-1>", lambda e, n=name: self._start_itemizer_note_drag(n, e))
            name_label.bind("<ButtonRelease-1>", lambda e, n=name: self._drop_itemizer_note_drag(n, e))
            var = tk.StringVar(value=current_values.get(name, ""))
            entry = ttk.Entry(row, textvariable=var, style="App.TEntry", width=28)
            entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
            self.entry_spellcheck.register(entry)
            entry.bind("<FocusOut>", lambda _e: self._save_itemizer_character_notes())
            entry.bind("<Return>", lambda _e: self._save_itemizer_character_notes())
            self.itemizer_note_vars[name] = var
            self.itemizer_note_entry_widgets[name] = entry
            self.itemizer_note_row_widgets[name] = row

    def _save_itemizer_character_notes(self):
        if not self.itemizer_note_vars:
            return
        existing_notes = self._get_ui_pref("itemizer_character_notes", {})
        if not isinstance(existing_notes, dict):
            existing_notes = {}

        notes = dict(existing_notes)
        for name, var in self.itemizer_note_vars.items():
            value = var.get().strip()
            if value:
                notes[name] = value
            elif name in notes:
                # Clearing a visible field should clear that specific saved note.
                notes.pop(name, None)
        self._set_ui_pref("itemizer_character_notes", notes)
        self._save_itemizer_character_order(list(self.itemizer_note_vars.keys()))

    def _get_ordered_itemizer_character_names(self, character_names):
        normalized = {str(name).strip() for name in character_names if str(name).strip()}
        saved_order = self._get_ui_pref("itemizer_character_order", [])
        if not isinstance(saved_order, list):
            saved_order = []

        ordered = []
        seen = set()
        for name in saved_order:
            text = str(name).strip()
            if text and text in normalized and text not in seen:
                ordered.append(text)
                seen.add(text)

        for name in sorted(normalized, key=str.lower):
            if name not in seen:
                ordered.append(name)
                seen.add(name)
        return ordered

    def _save_itemizer_character_order(self, names):
        if not names:
            return
        existing = self._get_ui_pref("itemizer_character_order", [])
        if not isinstance(existing, list):
            existing = []
        clean = []
        seen = set()
        for name in names:
            text = str(name).strip()
            if text and text not in seen:
                clean.append(text)
                seen.add(text)
        for name in existing:
            text = str(name).strip()
            if text and text not in seen:
                clean.append(text)
                seen.add(text)
        self._set_ui_pref("itemizer_character_order", clean)

    def _start_itemizer_note_drag(self, name, _event=None):
        self.itemizer_drag_name = name
        self.status_var.set(f"Dragging note row: {name}")

    def _drop_itemizer_note_drag(self, name, event=None):
        dragged = self.itemizer_drag_name or name
        self.itemizer_drag_name = None
        if dragged not in self.itemizer_note_row_widgets or event is None or self.itemizer_notes_inner is None:
            return

        order = list(self.itemizer_note_vars.keys())
        if dragged not in order or len(order) <= 1:
            return

        y_local = event.y_root - self.itemizer_notes_inner.winfo_rooty()
        target_idx = len(order) - 1
        for idx, row_name in enumerate(order):
            row_widget = self.itemizer_note_row_widgets.get(row_name)
            if row_widget is None:
                continue
            mid = row_widget.winfo_y() + (row_widget.winfo_height() // 2)
            if y_local < mid:
                target_idx = idx
                break

        current_idx = order.index(dragged)
        if target_idx == current_idx:
            self.status_var.set("Character notes order unchanged.")
            return

        values = {n: v.get() for n, v in self.itemizer_note_vars.items()}
        item = order.pop(current_idx)
        if target_idx > current_idx:
            target_idx -= 1
        order.insert(max(0, min(target_idx, len(order))), item)

        self._save_itemizer_character_order(order)
        self._render_itemizer_character_notes(order)
        for key, value in values.items():
            if key in self.itemizer_note_vars:
                self.itemizer_note_vars[key].set(value)
        self._save_itemizer_character_notes()
        self.status_var.set(f"Moved {dragged}.")

    def _next_itemizer_page(self):
        if self.itemizer_offset + self.itemizer_page_size >= self.itemizer_total_rows:
            return
        self.itemizer_offset += self.itemizer_page_size
        self._load_itemizer_rows(reset_offset=False)

    def _prev_itemizer_page(self):
        self.itemizer_offset = max(0, self.itemizer_offset - self.itemizer_page_size)
        self._load_itemizer_rows(reset_offset=False)

    def open_character_browser_window(self):
        if self.character_browser_window is not None and self.character_browser_window.winfo_exists():
            self.character_browser_window.deiconify()
            self.character_browser_window.lift()
            self.character_browser_window.focus_force()
            return

        self.character_browser_window = self.create_themed_toplevel("character_browser", "Character Browser", on_close=self._on_close_character_browser_window)

        shell = ttk.Frame(self.character_browser_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Character Browser", style="App.Header.TLabel").pack(side="left")

        # Per-window always-on-top toggle for Character Browser
        self.character_browser_pin_var = tk.BooleanVar(value=bool(self._get_ui_pref("character_browser_always_on_top", False)))
        ttk.Checkbutton(
            header,
            text="Always on Top",
            variable=self.character_browser_pin_var,
            command=self._toggle_character_browser_always_on_top,
            style="App.TCheckbutton",
        ).pack(side="right", padx=(6, 0))

        ttk.Button(header, text="Refresh", command=self._load_character_entries, style="App.Primary.TButton").pack(
            side="right"
        )

        top = ttk.Frame(shell, padding=10, style="App.Card.TFrame")
        top.pack(fill="x", expand=False)
        bottom = ttk.Frame(shell, padding=10, style="App.Card.TFrame")
        bottom.pack(fill="both", expand=True, pady=(8, 0))

        tree_wrap = ttk.Frame(top, style="App.Card.TFrame")
        tree_wrap.pack(fill="x", expand=False)

        character_tree_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", style="App.Vertical.TScrollbar")
        character_tree_scroll.pack(side="right", fill="y")

        self.character_tree = ttk.Treeview(
            tree_wrap,
            columns=("server", "name", "filename"),
            show="headings",
            height=8,
            style="App.Treeview",
            yscrollcommand=character_tree_scroll.set,
        )
        self.character_tree.heading("server", text="Server")
        self.character_tree.heading("name", text="Character")
        self.character_tree.heading("filename", text="File")
        self.character_tree.column("server", width=220, stretch=False)
        self.character_tree.column("name", width=240, stretch=False)
        self.character_tree.column("filename", width=420, stretch=True)
        self.character_tree.pack(side="left", fill="x", expand=True)
        character_tree_scroll.configure(command=self.character_tree.yview)
        self.character_tree.bind("<<TreeviewSelect>>", self._on_character_select)

        ttk.Label(bottom, text="Character JSON", style="App.Header.TLabel").pack(anchor="w", pady=(0, 4))
        self.character_json_text = tk.Text(
            bottom,
            height=12,
            wrap="none",
            bg=UI_COLORS["entry_bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            borderwidth=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=UI_COLORS["entry_border"],
            highlightcolor=UI_COLORS["accent"],
        )
        self.character_json_text.pack(fill="both", expand=True)

        # Apply saved always-on-top state for this window
        try:
            self.character_browser_window.attributes("-topmost", bool(self.character_browser_pin_var.get()))
        except Exception:
            pass

        # Apply saved always-on-top state for this window
        try:
            self.character_browser_window.attributes("-topmost", bool(self.character_browser_pin_var.get()))
        except Exception:
            pass

        self.character_browser_window.update_idletasks()
        req_w = max(920, self.character_browser_window.winfo_reqwidth())
        req_h = max(620, self.character_browser_window.winfo_reqheight())
        self._apply_saved_window_geometry("character_browser", self.character_browser_window, req_w, req_h)
        self.character_browser_window.minsize(req_w, req_h)
        self._set_window_open_state("character_browser", True)
        self._load_character_entries()

    def _on_close_character_browser_window(self):
        if self.character_browser_window is not None and self.character_browser_window.winfo_exists():
            self._save_window_geometry("character_browser", self.character_browser_window)
            self.character_browser_window.destroy()
        self._set_window_open_state("character_browser", False)
        self.character_browser_window = None
        self.character_tree = None
        self.character_json_text = None
        self.character_entries = []

    def _get_reports_dir(self):
        if config.PG_BASE is None:
            initialize_pg_base(force=True)
        if config.PG_BASE is None:
            return None
        return Path(config.PG_BASE) / "Reports"

    def _collect_character_entries(self):
        reports_dir = self._get_reports_dir()
        if reports_dir is None or not reports_dir.exists():
            return []

        entries = []
        for path in reports_dir.glob("Character_*.json"):
            match = CHARACTER_FILE_RE.match(path.name)
            if not match:
                continue
            entries.append(
                {
                    "server": match.group("server"),
                    "name": match.group("name"),
                    "path": path,
                    "filename": path.name,
                }
            )
        entries.sort(key=lambda x: (x["server"].lower(), x["name"].lower()))
        return entries

    def _refresh_character_cache(self):
        entries = self._collect_character_entries()
        self.character_entries = entries
        self.character_count_var.set(f"Characters Loaded: {len(entries)}")

    def _load_character_entries(self):
        if self.character_tree is None:
            return

        self.character_tree.delete(*self.character_tree.get_children())
        if self.character_json_text is not None:
            self.character_json_text.delete("1.0", tk.END)
        entries = self._collect_character_entries()
        self.character_entries = entries

        if not entries:
            self._set_character_tree_height(4)
            self.character_count_var.set("Characters Loaded: 0")
            self.status_var.set("Reports directory not found.")
            return

        for idx, entry in enumerate(entries):
            self.character_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(entry["server"], entry["name"], entry["filename"]),
            )

        self.character_count_var.set(f"Characters Loaded: {len(entries)}")
        self.status_var.set(f"Loaded {len(entries)} character reports.")
        self._set_character_tree_height(len(entries))
        if entries:
            selected_idx = 0
            preferred = str(self._get_ui_pref("character_browser_selected_file", ""))
            if preferred:
                for idx, entry in enumerate(entries):
                    if entry["filename"] == preferred:
                        selected_idx = idx
                        break
            self.character_tree.selection_set(str(selected_idx))
            self.character_tree.focus(str(selected_idx))
            self._on_character_select()

    def _on_character_select(self, _event=None):
        if self.character_tree is None or self.character_json_text is None:
            return
        selection = self.character_tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        if idx < 0 or idx >= len(self.character_entries):
            return

        path = self.character_entries[idx]["path"]
        entry = self.character_entries[idx]
        self._set_ui_pref("character_browser_selected_file", entry["filename"])
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            pretty = self._format_character_payload(entry, payload)
        except Exception as exc:
            pretty = f"{UI_TEXT['status_error_prefix']}{exc}"

        self.character_json_text.delete("1.0", tk.END)
        self.character_json_text.insert("1.0", pretty)

    def _set_character_tree_height(self, row_count):
        if self.character_tree is None:
            return
        visible_rows = max(4, min(14, int(row_count) + 1))
        self.character_tree.configure(height=visible_rows)

    def _format_character_payload(self, entry, payload):
        lines = []
        lines.append("Character Report")
        lines.append("=" * 64)
        lines.append(f"Server: {entry['server']}")
        lines.append(f"Character: {entry['name']}")
        lines.append(f"File: {entry['filename']}")
        lines.append("")

        if isinstance(payload, dict):
            scalar_items = []
            complex_items = []
            for key, value in payload.items():
                if isinstance(value, (dict, list)):
                    complex_items.append((key, value))
                else:
                    scalar_items.append((key, value))

            if scalar_items:
                lines.append("Overview")
                lines.append("-" * 64)
                for key, value in scalar_items:
                    lines.append(f"{self._humanize_key(key)}: {value}")
                lines.append("")

            if complex_items:
                lines.append("Details")
                lines.append("-" * 64)
                for key, value in complex_items:
                    lines.append(f"{self._humanize_key(key)}:")
                    lines.extend(self._summarize_structure(value, indent="  ", max_depth=2, max_items=12))
                    lines.append("")
        else:
            lines.append("Overview")
            lines.append("-" * 64)
            lines.append(str(payload))
            lines.append("")

        lines.append("Raw JSON")
        lines.append("-" * 64)
        lines.append(json.dumps(payload, indent=2, ensure_ascii=False))
        return "\n".join(lines)

    def _humanize_key(self, key):
        text = str(key).replace("_", " ").strip()
        if text.isupper() and len(text) <= 6:
            return text
        # Split camelCase/PascalCase without breaking acronym blocks.
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        cleaned = " ".join(text.split())
        return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned

    def _summarize_structure(self, value, indent="  ", max_depth=2, max_items=12):
        if max_depth < 0:
            return [f"{indent}..."]

        if isinstance(value, dict):
            items = list(value.items())
            lines = []
            for idx, (key, child) in enumerate(items):
                if idx >= max_items:
                    lines.append(f"{indent}... ({len(items) - max_items} more)")
                    break
                if isinstance(child, (dict, list)):
                    lines.append(f"{indent}{self._humanize_key(key)}:")
                    lines.extend(
                        self._summarize_structure(
                            child,
                            indent=indent + "  ",
                            max_depth=max_depth - 1,
                            max_items=max_items,
                        )
                    )
                else:
                    lines.append(f"{indent}{self._humanize_key(key)}: {child}")
            return lines or [f"{indent}(empty)"]

        if isinstance(value, list):
            lines = [f"{indent}Count: {len(value)}"]
            for idx, item in enumerate(value[:max_items]):
                prefix = f"{indent}- "
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}[{idx}]")
                    lines.extend(
                        self._summarize_structure(
                            item,
                            indent=indent + "  ",
                            max_depth=max_depth - 1,
                            max_items=max_items,
                        )
                    )
                else:
                    lines.append(f"{prefix}{item}")
            if len(value) > max_items:
                lines.append(f"{indent}... ({len(value) - max_items} more)")
            return lines

        return [f"{indent}{value}"]

    def _refresh_data_index_async(self):
        self.status_var.set("Indexing JSON files...")

        def worker():
            try:
                result = index_data_dir(config.DATA_DIR)
                files = list_indexed_files(get_db_path(config.DATA_DIR))

                def update_ui():
                    if self.data_file_listbox is None:
                        return
                    self.data_file_listbox.delete(0, tk.END)
                    for item in files:
                        label = f"{item['filename']} ({item['row_count']})"
                        self.data_file_listbox.insert(tk.END, label)
                    if files:
                        preferred = str(self._get_ui_pref("data_browser_selected_file", "")) or self.data_selected_filename
                        selected_idx = 0
                        for idx, item in enumerate(files):
                            if item["filename"] == preferred:
                                selected_idx = idx
                                break
                        self.data_offset = int(self._get_ui_pref("data_browser_offset", 0) or 0)
                        self.data_file_listbox.selection_set(selected_idx)
                        self._on_data_file_select(reset_offset=False)
                    self.status_var.set(
                        f"Index ready: {result['indexed_files']} updated, {result['skipped_files']} unchanged."
                    )

                self.root.after(0, update_ui)
            except Exception as exc:
                def show_error(e=exc):
                    try:
                        self.status_var.set(f"{UI_TEXT['status_error_prefix']}{e}")
                    except RuntimeError:
                        # Main loop not running, can't update UI
                        pass
                try:
                    self.root.after(0, show_error)
                except RuntimeError:
                    # Main loop not running, can't schedule update
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_data_file_select(self, _event=None, reset_offset=True):
        if self.data_file_listbox is None:
            return
        selection = self.data_file_listbox.curselection()
        if not selection:
            return
        row_text = self.data_file_listbox.get(selection[0])
        self.data_selected_filename = row_text.split(" (", 1)[0]
        self._set_ui_pref("data_browser_selected_file", self.data_selected_filename)
        self._load_data_rows(reset_offset=reset_offset)

    def _reset_data_filters(self):
        self.data_search_var.set("")
        self._load_data_rows(reset_offset=True)

    def _schedule_data_live_search(self):
        if self._data_search_after_id is not None:
            try:
                self.root.after_cancel(self._data_search_after_id)
            except tk.TclError:
                pass
        self._data_search_after_id = self.root.after(220, self._run_data_live_search)

    def _run_data_live_search(self):
        self._data_search_after_id = None
        if self.data_browser_window is None or not self.data_browser_window.winfo_exists():
            return
        if self.data_rows_tree is None or self.data_selected_filename is None:
            return
        self._load_data_rows(reset_offset=True)

    def _load_data_rows(self, reset_offset=False):
        if self.data_selected_filename is None or self.data_rows_tree is None:
            return
        if reset_offset:
            self.data_offset = 0

        search = self.data_search_var.get().strip()
        rows, total = fetch_rows(
            get_db_path(config.DATA_DIR),
            filename=self.data_selected_filename,
            search_text=search,
            limit=self.data_page_size,
            offset=self.data_offset,
        )
        self.data_total_rows = total

        self.data_rows_tree.delete(*self.data_rows_tree.get_children())
        for row in rows:
            preview = row["payload"].replace("\\n", " ")
            if len(preview) > 180:
                preview = preview[:177] + "..."
            self.data_rows_tree.insert(
                "",
                tk.END,
                values=(row["row_index"], row["row_key"] or "", preview),
                tags=(row["payload"],),
            )

        if self.data_json_text is not None:
            self.data_json_text.delete("1.0", tk.END)

        selected_row_pref = self._get_ui_pref("data_browser_selected_row", {})
        if isinstance(selected_row_pref, dict) and selected_row_pref.get("filename") == self.data_selected_filename:
            target_key = str(selected_row_pref.get("row_key", ""))
            target_index = str(selected_row_pref.get("row_index", ""))
            for item_id in self.data_rows_tree.get_children():
                vals = self.data_rows_tree.item(item_id, "values")
                row_key = str(vals[1]) if len(vals) > 1 else ""
                row_index = str(vals[0]) if vals else ""
                if row_key == target_key and row_index == target_index:
                    self.data_rows_tree.selection_set(item_id)
                    self.data_rows_tree.focus(item_id)
                    self._on_data_row_select()
                    break

        page_num = (self.data_offset // self.data_page_size) + 1
        total_pages = max(1, (self.data_total_rows + self.data_page_size - 1) // self.data_page_size)
        self.data_page_var.set(f"Page {page_num} / {total_pages}   Rows: {self.data_total_rows}")
        self._set_ui_pref("data_browser_search", self.data_search_var.get().strip())
        self._set_ui_pref("data_browser_selected_file", self.data_selected_filename)
        self._set_ui_pref("data_browser_offset", int(self.data_offset))

    def _on_data_row_select(self, _event=None):
        if self.data_rows_tree is None or self.data_json_text is None:
            return
        selection = self.data_rows_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        payload = self.data_rows_tree.item(item_id, "tags")[0]
        values = self.data_rows_tree.item(item_id, "values")
        row_index = values[0] if values else ""
        row_key = values[1] if len(values) > 1 else ""
        self._set_ui_pref(
            "data_browser_selected_row",
            {"filename": self.data_selected_filename or "", "row_index": row_index, "row_key": row_key},
        )
        self.data_json_text.delete("1.0", tk.END)
        try:
            parsed = json.loads(payload)
            pretty = self._format_data_payload(self.data_selected_filename or "", row_index, row_key, parsed)
            self.data_json_text.insert("1.0", pretty)
        except json.JSONDecodeError:
            self.data_json_text.insert("1.0", payload)

    def _show_data_file_context_menu(self, event):
        if self.data_file_listbox is None:
            return "break"
        idx = self.data_file_listbox.nearest(event.y)
        if idx >= 0:
            self.data_file_listbox.selection_clear(0, tk.END)
            self.data_file_listbox.selection_set(idx)
            self.data_file_listbox.activate(idx)

        menu = tk.Menu(self.data_browser_window, tearoff=0)
        menu.add_command(label="Copy Filename", command=self._copy_selected_data_filename)
        menu.add_command(label="Refresh Index", command=self._refresh_data_index_async)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _show_data_tree_context_menu(self, event):
        if self.data_rows_tree is None:
            return "break"
        row_id = self.data_rows_tree.identify_row(event.y)
        if row_id:
            self.data_rows_tree.selection_set(row_id)
            self.data_rows_tree.focus(row_id)
            self._on_data_row_select()

        menu = tk.Menu(self.data_browser_window, tearoff=0)
        menu.add_command(label="Copy Row Key", command=self._copy_selected_data_row_key)
        menu.add_command(label="Copy Raw JSON", command=self._copy_selected_data_row_payload)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _show_data_text_context_menu(self, event):
        if self.data_json_text is None:
            return "break"
        menu = tk.Menu(self.data_browser_window, tearoff=0)
        menu.add_command(label="Cut", command=lambda: self.data_json_text.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: self.data_json_text.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: self.data_json_text.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: self.data_json_text.tag_add("sel", "1.0", tk.END))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _copy_selected_data_filename(self):
        if self.data_file_listbox is None:
            return
        sel = self.data_file_listbox.curselection()
        if not sel:
            return
        text = self.data_file_listbox.get(sel[0]).split(" (", 1)[0]
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _copy_selected_data_row_key(self):
        if self.data_rows_tree is None:
            return
        sel = self.data_rows_tree.selection()
        if not sel:
            return
        values = self.data_rows_tree.item(sel[0], "values")
        key = values[1] if len(values) > 1 else ""
        self.root.clipboard_clear()
        self.root.clipboard_append(str(key))

    def _copy_selected_data_row_payload(self):
        if self.data_rows_tree is None:
            return
        sel = self.data_rows_tree.selection()
        if not sel:
            return
        payload = self.data_rows_tree.item(sel[0], "tags")[0]
        self.root.clipboard_clear()
        self.root.clipboard_append(payload)

    def _bind_data_browser_zoom_events(self, widget):
        if widget is None:
            return
        try:
            widget.bind("<Control-MouseWheel>", self._on_data_browser_ctrl_mousewheel, add="+")
            widget.bind("<Control-Button-4>", self._on_data_browser_ctrl_wheel_up, add="+")
            widget.bind("<Control-Button-5>", self._on_data_browser_ctrl_wheel_down, add="+")
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_data_browser_zoom_events(child)

    def _on_data_browser_ctrl_wheel_up(self, _event=None):
        self._change_data_browser_font_size(1)
        return "break"

    def _on_data_browser_ctrl_wheel_down(self, _event=None):
        self._change_data_browser_font_size(-1)
        return "break"

    def _on_data_browser_ctrl_mousewheel(self, event):
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return "break"
        steps = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self._change_data_browser_font_size(steps)
        return "break"

    def _change_data_browser_font_size(self, step):
        self.data_browser_font_size = max(8, min(32, int(self.data_browser_font_size) + int(step)))
        self._apply_data_browser_font_size()
        self._set_ui_pref("data_browser_font_size", self.data_browser_font_size)

    def _apply_data_browser_font_size(self):
        size = int(self.data_browser_font_size)
        style = ttk.Style(self.root)
        style.configure(
            "Data.TLabel",
            background=UI_COLORS["panel_bg"],
            foreground=UI_COLORS["text"],
            font=(UI_ATTRS["font_family"], size),
        )
        style.configure(
            "Data.Header.TLabel",
            background=UI_COLORS["panel_bg"],
            foreground=UI_COLORS["accent"],
            font=(UI_ATTRS["font_family"], max(size + 3, 10), "bold"),
        )
        style.configure(
            "Data.Status.TLabel",
            background=UI_COLORS["panel_bg"],
            foreground=UI_COLORS["muted_text"],
            font=(UI_ATTRS["font_family"], size),
        )
        style.configure(
            "Data.Primary.TButton",
            background=UI_COLORS["primary"],
            foreground=UI_COLORS["text"],
            borderwidth=1,
            relief="raised",
            focusthickness=2,
            focuscolor=UI_COLORS["primary_active"],
            font=(UI_ATTRS["font_family"], size),
            padding=(10, 6),
        )
        style.map(
            "Data.Primary.TButton",
            background=[("active", UI_COLORS["primary_active"]), ("disabled", UI_COLORS["secondary"])],
            foreground=[("disabled", UI_COLORS["muted_text"])],
        )
        style.configure(
            "Data.Secondary.TButton",
            background=UI_COLORS["secondary"],
            foreground=UI_COLORS["text"],
            borderwidth=1,
            relief="raised",
            font=(UI_ATTRS["font_family"], size),
            padding=(10, 6),
        )
        style.map(
            "Data.Secondary.TButton",
            background=[("active", UI_COLORS["secondary_active"]), ("disabled", UI_COLORS["secondary"])],
            foreground=[("disabled", UI_COLORS["muted_text"])],
        )
        style.configure(
            "Data.TEntry",
            fieldbackground=UI_COLORS["entry_bg"],
            foreground=UI_COLORS["text"],
            bordercolor=UI_COLORS["entry_border"],
            insertcolor=UI_COLORS["text"],
            lightcolor=UI_COLORS["entry_border"],
            darkcolor=UI_COLORS["entry_border"],
            font=(UI_ATTRS["font_family"], size),
            padding=(6, 4),
        )
        style.map("Data.TEntry", bordercolor=[("focus", UI_COLORS["accent"])], lightcolor=[("focus", UI_COLORS["accent"])])
        style.configure(
            "Data.Treeview",
            background=UI_COLORS["entry_bg"],
            fieldbackground=UI_COLORS["entry_bg"],
            foreground=UI_COLORS["text"],
            bordercolor=UI_COLORS["entry_border"],
            font=(UI_ATTRS["font_family"], size),
            rowheight=max(20, size * 2 + 4),
        )
        style.map(
            "Data.Treeview",
            background=[("selected", UI_COLORS["secondary_active"])],
            foreground=[("selected", UI_COLORS["accent"])],
        )
        style.configure(
            "Data.Treeview.Heading",
            background=UI_COLORS["secondary"],
            foreground=UI_COLORS["text"],
            relief="raised",
            font=(UI_ATTRS["font_family"], size, "bold"),
        )
        style.map("Data.Treeview.Heading", background=[("active", UI_COLORS["secondary_active"])])

        if self.data_file_listbox is not None:
            self.data_file_listbox.configure(font=(UI_ATTRS["font_family"], size))
        if self.data_json_text is not None:
            self.data_json_text.configure(font=(UI_ATTRS["font_family"], size))

    def _format_data_payload(self, filename, row_index, row_key, payload):
        lines = []
        lines.append("Data Row")
        lines.append("=" * 64)
        lines.append(f"File: {filename}")
        lines.append(f"Row: {row_index}")
        if row_key:
            lines.append(f"Key: {row_key}")
        lines.append("")

        if isinstance(payload, dict):
            scalar_items = []
            complex_items = []
            for key, value in payload.items():
                if isinstance(value, (dict, list)):
                    complex_items.append((key, value))
                else:
                    scalar_items.append((key, value))

            if scalar_items:
                lines.append("Overview")
                lines.append("-" * 64)
                for key, value in scalar_items:
                    lines.append(f"{self._humanize_key(key)}: {value}")
                lines.append("")

            if complex_items:
                lines.append("Details")
                lines.append("-" * 64)
                for key, value in complex_items:
                    lines.append(f"{self._humanize_key(key)}:")
                    lines.extend(self._summarize_structure(value, indent="  ", max_depth=2, max_items=14))
                    lines.append("")
        elif isinstance(payload, list):
            lines.append("Overview")
            lines.append("-" * 64)
            lines.extend(self._summarize_structure(payload, indent="  ", max_depth=2, max_items=20))
            lines.append("")
        else:
            lines.append("Overview")
            lines.append("-" * 64)
            lines.append(str(payload))
            lines.append("")

        lines.append("Raw JSON")
        lines.append("-" * 64)
        lines.append(json.dumps(payload, indent=2, ensure_ascii=False))
        return "\n".join(lines)

    def _next_data_page(self):
        if self.data_selected_filename is None:
            return
        if self.data_offset + self.data_page_size >= self.data_total_rows:
            return
        self.data_offset += self.data_page_size
        self._load_data_rows(reset_offset=False)

    def _prev_data_page(self):
        if self.data_selected_filename is None:
            return
        self.data_offset = max(0, self.data_offset - self.data_page_size)
        self._load_data_rows(reset_offset=False)

    def show_page(self, page_name):
        """Show a specific page in the content area."""
        # Hide all pages
        self.home_page.pack_forget()
        self.chat_page.pack_forget()

        # Show requested page
        if page_name == "home":
            self.home_page.pack(fill="both", expand=True)
        elif page_name == "chat":
            self.chat_page.pack(fill="both", expand=True)
            # Auto-start chat monitor if not running
            if not self.chat_polling:
                self._start_chat_monitor()

    def _get_primary_monitor_geometry(self):
        try:
            result = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, check=False)
            lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            for line in lines:
                if "*" not in line:
                    continue
                match = re.search(r"(?P<w>\d+)/\d+x(?P<h>\d+)/\d+\+(?P<x>-?\d+)\+(?P<y>-?\d+)", line)
                if match:
                    return {
                        "width": int(match.group("w")),
                        "height": int(match.group("h")),
                        "x": int(match.group("x")),
                        "y": int(match.group("y")),
                    }
        except Exception:
            pass
        return None

    def _apply_startup_geometry(self):
        self.root.update_idletasks()
        req_w = max(int(self.root.winfo_reqwidth()), MAIN_MIN_WIDTH)
        req_h = max(int(self.root.winfo_reqheight()), MAIN_MIN_HEIGHT)

        saved_geometry = None
        try:
            states = self._load_all_window_states()
            state = states.get("main")
            if isinstance(state, dict):
                if state.get("geometry"):
                    saved_geometry = str(state["geometry"])
                elif "width" in state and "height" in state:
                    width = int(state["width"])
                    height = int(state["height"])
                    if "x" in state and "y" in state:
                        saved_geometry = f"{width}x{height}+{int(state['x'])}+{int(state['y'])}"
                    else:
                        saved_geometry = f"{width}x{height}"
        except Exception:
            saved_geometry = None

        if saved_geometry:
            try:
                self.root.geometry(saved_geometry)
                self.root.minsize(MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT)
                self._window_state_ready = False
                return
            except tk.TclError:
                saved_geometry = None

        monitor = self._get_primary_monitor_geometry()
        if monitor is not None:
            width = min(req_w, monitor["width"])
            height = min(req_h, monitor["height"])
            x = monitor["x"] + max(0, (monitor["width"] - width) // 2)
            y = monitor["y"] + max(0, (monitor["height"] - height) // 2)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.root.minsize(MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT)
        self._window_state_ready = False

    def _show_main_window(self):
        return

    def _enforce_main_window_geometry(self):
        return

    def _on_window_map(self, _event=None):
        return

    def _on_window_visibility(self, _event=None):
        return

    def _enable_main_window_state_persistence(self):
        self._window_state_ready = True

    def _load_all_window_states(self):
        try:
            if not WINDOW_STATE_FILE.exists():
                return {}
            payload = json.loads(WINDOW_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "width" in payload and "height" in payload:
                # Backward compatibility with legacy single-window format.
                return {"main": payload}
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_all_window_states(self, states):
        try:
            WINDOW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            WINDOW_STATE_FILE.write_text(json.dumps(states, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _set_window_open_state(self, key, is_open):
        states = self._load_all_window_states()
        open_windows = states.get("open_windows")
        if not isinstance(open_windows, dict):
            open_windows = {}
        open_windows[key] = bool(is_open)
        states["open_windows"] = open_windows
        self._save_all_window_states(states)

    def _is_window_marked_open(self, key):
        states = self._load_all_window_states()
        open_windows = states.get("open_windows")
        if not isinstance(open_windows, dict):
            return False
        return bool(open_windows.get(key, False))

    def _set_ui_pref(self, key, value):
        states = self._load_all_window_states()
        prefs = states.get("prefs")
        if not isinstance(prefs, dict):
            prefs = {}
        prefs[key] = value
        states["prefs"] = prefs
        self._save_all_window_states(states)

    def _get_ui_pref(self, key, default=None):
        states = self._load_all_window_states()
        prefs = states.get("prefs")
        if not isinstance(prefs, dict):
            return default
        return prefs.get(key, default)

    def _restore_open_windows(self):
        if self._is_window_marked_open("settings"):
            self.open_settings_window()
        if self._is_window_marked_open("data_browser"):
            self.open_data_browser_window()
        if self._is_window_marked_open("itemizer"):
            self.open_itemizer_window()
        if self._is_window_marked_open("character_browser"):
            self.open_character_browser_window()
        if self._is_window_marked_open("map_tools"):
            self.open_map_tools_window()
        if self._is_window_marked_open("survey_helper"):
            self._open_survey_helper()
        if self._is_window_marked_open("favor_tracker"):
            self._open_favor_tracker()
        if self._is_window_marked_open("communications"):
            # Open communications window if it was open previously
            try:
                self._open_communications_window()
            except Exception:
                pass
        if self._is_window_marked_open("timer"):
            try:
                self._open_timer()
            except Exception:
                pass

    def _raise_main_window_default(self):
        return

    def _capture_window_geometry(self, window):
        match = GEOMETRY_RE.match(window.geometry())
        if not match:
            return None
        return {
            "width": int(match.group("w")),
            "height": int(match.group("h")),
            "x": int(match.group("x")),
            "y": int(match.group("y")),
        }

    def _save_window_geometry(self, key, window):
        if window is None or not window.winfo_exists():
            return
        geometry = self._capture_window_geometry(window)
        if geometry is None:
            return
        states = self._load_all_window_states()
        states[key] = geometry
        self._save_all_window_states(states)

    def _apply_saved_window_geometry(self, key, window, min_width, min_height):
        def _parse_geometry(geometry):
            try:
                size_part, x_part, y_part = geometry.split("+", 2)
                width_str, height_str = size_part.split("x", 1)
                return int(width_str), int(height_str), int(x_part), int(y_part)
            except Exception:
                return None

        def _get_owner_geometry():
            owner = getattr(window, "master", None)
            if owner is None:
                return None
            try:
                if not owner.winfo_exists():
                    return None
                owner.update_idletasks()
                parsed = _parse_geometry(owner.winfo_geometry())
                if parsed is not None:
                    return parsed
                return (
                    int(owner.winfo_rootx()),
                    int(owner.winfo_rooty()),
                    int(owner.winfo_width() or owner.winfo_reqwidth()),
                    int(owner.winfo_height() or owner.winfo_reqheight()),
                )
            except Exception:
                return None

        def _get_screen_bounds():
            try:
                screen_x = int(window.winfo_vrootx()) if hasattr(window, "winfo_vrootx") else 0
            except Exception:
                screen_x = 0
            try:
                screen_y = int(window.winfo_vrooty()) if hasattr(window, "winfo_vrooty") else 0
            except Exception:
                screen_y = 0
            screen_w = max(640, int(window.winfo_screenwidth()))
            screen_h = max(480, int(window.winfo_screenheight()))
            return screen_x, screen_y, screen_w, screen_h

        def _clamp_geometry(width, height, x, y, bounds):
            screen_x, screen_y, screen_w, screen_h = bounds
            width = min(width, screen_w)
            height = min(height, screen_h)
            x = max(screen_x, min(int(x), screen_x + max(0, screen_w - width)))
            y = max(screen_y, min(int(y), screen_y + max(0, screen_h - height)))
            return width, height, x, y

        screen_x, screen_y, screen_w, screen_h = _get_screen_bounds()
        max_w = max(480, screen_w - 80)
        max_h = max(320, screen_h - 100)
        base_w = max(320, min(int(min_width), max_w))
        base_h = max(240, min(int(min_height), max_h))

        owner_geom = _get_owner_geometry()
        if owner_geom is not None:
            owner_x, owner_y, owner_w, owner_h = owner_geom

        states = self._load_all_window_states()
        state = states.get(key)
        saved_geometry = None
        if isinstance(state, dict):
            if state.get("geometry"):
                saved_geometry = str(state["geometry"])
            elif "width" in state and "height" in state:
                try:
                    width = int(state["width"])
                    height = int(state["height"])
                    if "x" in state and "y" in state:
                        saved_geometry = f"{width}x{height}+{int(state['x'])}+{int(state['y'])}"
                    else:
                        saved_geometry = f"{width}x{height}"
                except (TypeError, ValueError):
                    saved_geometry = None

        if saved_geometry:
            parsed = _parse_geometry(saved_geometry)
            if parsed is not None:
                width, height, x, y = parsed
                width = max(base_w, width)
                height = max(base_h, height)
                width, height, x, y = _clamp_geometry(width, height, x, y, (screen_x, screen_y, screen_w, screen_h))
                window.geometry(f"{width}x{height}+{x}+{y}")
            else:
                try:
                    window.geometry(saved_geometry)
                except tk.TclError:
                    if owner_geom is not None:
                        x = owner_x + ((owner_w - base_w) // 2)
                        y = owner_y + ((owner_h - base_h) // 2)
                        window.geometry(f"{base_w}x{base_h}+{x}+{y}")
                    else:
                        window.geometry(f"{base_w}x{base_h}")
            return

        if owner_geom is not None:
            x = owner_x + ((owner_w - base_w) // 2)
            y = owner_y + ((owner_h - base_h) // 2)
            x = max(screen_x, min(x, screen_x + max(0, screen_w - base_w)))
            y = max(screen_y, min(y, screen_y + max(0, screen_h - base_h)))
            window.geometry(f"{base_w}x{base_h}+{x}+{y}")
        else:
            window.geometry(f"{base_w}x{base_h}")

    def _on_window_configure(self, event):
        if event.widget is not self.root or not self._window_state_ready:
            return
        self._ensure_home_layout_visible()
        if self._resize_after_id is not None:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(350, self._save_main_window_state)

    def _save_main_window_state(self):
        self._resize_after_id = None
        self._save_window_geometry("main", self.root)

    def _on_close(self):
        # Stop chat monitoring
        self._stop_chat_monitor()
        
        # Stop player log monitoring
        self._stop_player_log_monitor()
        
        # Stop player position monitoring
        if self._player_pos_after_id is not None:
            try:
                self.root.after_cancel(self._player_pos_after_id)
            except tk.TclError:
                pass
            self._player_pos_after_id = None
        
        if self._data_search_after_id is not None:
            try:
                self.root.after_cancel(self._data_search_after_id)
            except tk.TclError:
                pass
            self._data_search_after_id = None
        if self._data_browser_resize_after_id is not None:
            try:
                self.root.after_cancel(self._data_browser_resize_after_id)
            except tk.TclError:
                pass
            self._data_browser_resize_after_id = None
        if self._itemizer_resize_after_id is not None:
            try:
                self.root.after_cancel(self._itemizer_resize_after_id)
            except tk.TclError:
                pass
            self._itemizer_resize_after_id = None
        if self._itemizer_search_after_id is not None:
            try:
                self.root.after_cancel(self._itemizer_search_after_id)
            except tk.TclError:
                pass
            self._itemizer_search_after_id = None
        if self._clock_after_id is not None:
            try:
                self.root.after_cancel(self._clock_after_id)
            except tk.TclError:
                pass
            self._clock_after_id = None
        self._save_main_window_state()
        self._set_window_open_state("settings", self.settings_window is not None and self.settings_window.winfo_exists())
        self._set_window_open_state(
            "data_browser",
            self.data_browser_window is not None and self.data_browser_window.winfo_exists(),
        )
        self._set_window_open_state("itemizer", self.itemizer_window is not None and self.itemizer_window.winfo_exists())
        self._set_window_open_state(
            "character_browser",
            self.character_browser_window is not None and self.character_browser_window.winfo_exists(),
        )
        self._set_window_open_state("map_tools", self.map_tools_window is not None and self.map_tools_window.winfo_exists())
        self._set_window_open_state("survey_helper", self.survey_helper_window is not None and self.survey_helper_window.winfo_exists())
        # Capture timer open state before closing it so startup restore can reopen it.
        try:
            was_timer_open = self.timer_window is not None and self.timer_window.window.winfo_exists()
        except Exception:
            was_timer_open = False
        self._set_window_open_state("timer", was_timer_open)
        # Track favor tracker window open state if present
        try:
            is_favor_open = self.favor_tracker_window is not None and self.favor_tracker_window.window.winfo_exists()
        except Exception:
            is_favor_open = False
        self._set_window_open_state("favor_tracker", is_favor_open)
        self._save_window_geometry("settings", self.settings_window)
        self._save_data_browser_pane_split()
        self._save_data_browser_display_pane_split()
        self._save_global_search_split()
        self._save_window_geometry("data_browser", self.data_browser_window)
        self._save_window_geometry("itemizer", self.itemizer_window)
        self._save_itemizer_pane_split()
        self._save_itemizer_bottom_pane_split()
        self._save_itemizer_column_widths()
        self._save_itemizer_character_notes()
        self._set_ui_pref("data_browser_search", self.data_search_var.get().strip())
        self._set_ui_pref("data_browser_offset", int(self.data_offset))
        self._set_ui_pref("itemizer_server", self.itemizer_server_var.get().strip())
        self._set_ui_pref("itemizer_character", self.itemizer_character_var.get().strip())
        self._set_ui_pref("itemizer_search", self.itemizer_search_var.get().strip())
        self._set_ui_pref("itemizer_offset", int(self.itemizer_offset))
        self._save_window_geometry("character_browser", self.character_browser_window)
        self._save_window_geometry("map_tools", self.map_tools_window)
        if self.timer_window is not None:
            try:
                self.timer_window._on_close()
            except Exception:
                try:
                    if self.timer_window.window.winfo_exists():
                        self.timer_window.window.destroy()
                except Exception:
                    pass
            self.timer_window = None
        self._stop_chat_monitor()
        try:
            sys.stdout = self._orig_stdout
            sys.stderr = self._orig_stderr
        except Exception:
            pass
        self.root.destroy()

    def refresh_config_view(self):
        self.path_vars["PG Base"].set(UI_TEXT["none_value"] if config.PG_BASE is None else str(config.PG_BASE))
        self.path_vars["CDN URL"].set(str(config.CDN_BASE_URL))

    def set_busy(self, busy, message):
        state = "disabled" if busy else "normal"
        if self.locate_button is not None:
            self.locate_button.configure(state=state)
        if self.download_button is not None:
            self.download_button.configure(state=state)
        if self.reset_button is not None:
            self.reset_button.configure(state=state)
        self.status_var.set(message)

    def run_in_background(self, task, busy_message, done_message, ui_after=None):
        """Run a background task without calling Tk from the worker thread."""
        event_queue = queue.Queue()
        done_state = {"done": False}

        def poll_events():
            if done_state["done"]:
                return

            try:
                while True:
                    kind, payload = event_queue.get_nowait()
                    if kind == "busy":
                        self.set_busy(True, busy_message)
                    elif kind == "done":
                        self.set_busy(False, done_message)
                        self.refresh_config_view()
                        if ui_after is not None:
                            ui_after()
                        done_state["done"] = True
                    elif kind == "error":
                        self.set_busy(False, f"{UI_TEXT['status_error_prefix']}{payload}")
                        done_state["done"] = True
            except queue.Empty:
                pass
            except tk.TclError:
                done_state["done"] = True
                return

            if not done_state["done"]:
                try:
                    self.root.after(100, poll_events)
                except tk.TclError:
                    done_state["done"] = True

        def runner():
            try:
                event_queue.put(("busy", None))
                task()
                event_queue.put(("done", None))
            except Exception as exc:
                event_queue.put(("error", exc))

        poll_events()
        threading.Thread(target=runner, daemon=True).start()

    def locate_pg(self):
        self.run_in_background(
            task=lambda: initialize_pg_base(force=True),
            busy_message=UI_TEXT["status_locating"],
            done_message=UI_TEXT["status_ready"],
            ui_after=self._refresh_character_cache,
        )

    def download_newer_files(self):
        from src.data_acquisition import main as run_data_acquisition

        self.run_in_background(
            task=run_data_acquisition,
            busy_message=UI_TEXT["status_downloading"],
            done_message=UI_TEXT["status_download_done"],
        )

    def reset_paths(self):
        config.set_pg_base(None)
        self.refresh_config_view()
        self.status_var.set(UI_TEXT["status_reset_done"])


def main():
    from src import crash_reporter
    crash_reporter.install()

    root = tk.Tk()
    root.withdraw()
    # Set taskbar/window icon (critical on Windows for taskbar icon to show)
    try:
        icon_path = _resolve_icon_path()
        if icon_path and icon_path.endswith(".ico"):
            root.iconbitmap(default=icon_path)
        elif icon_path:
            from PIL import Image, ImageTk
            img = Image.open(icon_path)
            root.tk.call("wm", "iconphoto", root._w, ImageTk.PhotoImage(img))
    except Exception:
        pass
    root.deiconify()
    app = PGLOKApp(root)
    root.app = app
    root.mainloop()


if __name__ == "__main__":
    main()
