import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading
import time
import json
import re

import src.config.config as config
from src.timer_db import TimerDatabase, get_db_path, DEFAULT_TIMER_DURATIONS, DEFAULT_BOSS_DURATIONS
from src.chat.monitor import ChatLogMonitor
from src.player.monitor import PlayerLogMonitor
from src.config.ui_theme import UI_ATTRS, UI_COLORS, apply_theme, configure_menu_theme

# Timer window state file
TIMER_STATE_FILE = Path.home() / ".pglok" / "timer_state.json"


def _load_timer_state():
    """Load timer window state from file."""
    try:
        if TIMER_STATE_FILE.exists():
            return json.loads(TIMER_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _save_timer_state(state):
    """Save timer window state to file."""
    try:
        TIMER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TIMER_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


class TimerWindow:
    """Main timer window with multiple concurrent timer support."""
    
    def __init__(self, parent, config_dir: Path, chat_dir: Optional[Path] = None):
        self.parent = parent
        self.config_dir = config_dir
        self.chat_dir = chat_dir
        
        # Initialize database and monitor
        self.timer_db = TimerDatabase(get_db_path(config_dir))
        self.chat_monitor = ChatLogMonitor(chat_dir) if chat_dir else None
        self.player_monitor = PlayerLogMonitor(log_dir=config.PG_BASE) if getattr(config, "PG_BASE", None) else None
        
        # Initialize default durations only if needed (check first)
        try:
            existing_durations = self.timer_db.get_timer_durations()
            if not existing_durations:
                self.timer_db.initialize_default_durations()
        except:
            self.timer_db.initialize_default_durations()
        
        try:
            existing_boss_durations = self.timer_db.get_boss_durations()
            if not existing_boss_durations:
                self.timer_db.initialize_boss_durations()
        except:
            self.timer_db.initialize_boss_durations()
        
        # UI state
        self.active_timers = {}
        self.timer_update_thread = None
        self.monitoring_active = False
        self.always_on_top = False
        
        # Persistent UI state variables - load from parent's preferences
        self.selected_tab_var = tk.IntVar(value=self._get_ui_pref("timer_selected_tab", 0))
        self.management_auto_start_var = tk.BooleanVar(value=self._get_ui_pref("timer_management_auto_start", True))
        self.management_scan_interval_var = tk.IntVar(value=self._get_ui_pref("timer_management_scan_interval", 5))
        self.management_notifications_var = tk.BooleanVar(value=self._get_ui_pref("timer_management_notifications", True))
        self.history_limit_var = tk.IntVar(value=self._get_ui_pref("timer_history_limit", 50))
        self.boss_notes_var = tk.StringVar(value=self._get_ui_pref("timer_boss_notes", ""))
        self.notes_var = tk.StringVar(value=self._get_ui_pref("timer_notes", ""))
        
        # Load timer selections from parent's preferences
        self.activity_var = tk.StringVar(value=self._get_ui_pref("timer_last_activity", ""))
        self.duration_var = tk.StringVar(value=self._get_ui_pref("timer_last_duration", ""))
        self.boss_var = tk.StringVar(value=self._get_ui_pref("timer_last_boss", ""))
        self.boss_duration_var = tk.StringVar(value=self._get_ui_pref("timer_last_boss_duration", ""))
        
        # Always on top and window geometry
        self.always_on_top_var = tk.BooleanVar(value=self._get_ui_pref("timer_always_on_top", False))
        
        # Create window using themed helper so geometry and theme are consistent
        try:
            # prefer parent's helper (PGLOKApp.create_themed_toplevel)
            if hasattr(parent, 'create_themed_toplevel'):
                self.window = parent.create_themed_toplevel("timer", "Timers", on_close=self._on_close)
            else:
                # fallback to centralized setup
                from src.config.window_state import setup_window
                self.window = tk.Toplevel(parent.root)
                setup_window(self.window, "timer", min_w=300, min_h=200, on_close=self._on_close)
        except Exception:
            # ultimate fallback
            self.window = tk.Toplevel(parent.root)
            self.window.title("⏱️ PGLOK Timer System")
            self.window.minsize(300, 200)
            try:
                apply_theme(self.window)
            except Exception:
                pass

        # Apply any legacy saved geometry from parent prefs if present
        try:
            legacy_geom = self._get_ui_pref("timer_window_geometry", None)
            if legacy_geom:
                try:
                    self.window.geometry(legacy_geom)
                except Exception:
                    pass
        except Exception:
            pass

        # Initialize status variables
        self.status_var = tk.StringVar(value="Ready")
        self.monitor_status_var = tk.StringVar(value="🟢 Log Monitoring Active") if (self.chat_monitor or self.player_monitor) else None
        
        # Start monitoring if a log source is available
        if self.chat_monitor or self.player_monitor:
            self.start_chat_monitoring()
        
        self._build_ui()
        
        # Restore saved geometry after UI is built to prevent size override
        self._restore_window_geometry()
        
        # Force window to update its size
        self.window.update_idletasks()
        
        # Apply geometry again after a delay to ensure it takes effect
        self.window.after(100, self._restore_window_geometry)
        
        # Refresh timers only after window is fully shown
        self.window.after(50, self._refresh_timers)
        
        # Apply always on top state after UI is built
        if self.always_on_top_var.get():
            self.window.attributes('-topmost', True)
            # Update button text after it's created
            self.window.after(100, self._update_always_on_top_button)
        
        # Track window resize events for saving geometry
        self.window.bind("<Configure>", self._on_window_resize)
        
        # Handle window close
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _build_ui(self):
        """Build the timer UI."""
        # Main container (more compact padding)
        main_frame = ttk.Frame(self.window, padding=8, style="App.TFrame")
        main_frame.pack(fill="both", expand=True)

        # Header with title and always on top button
        header_frame = ttk.Frame(main_frame, style="App.Panel.TFrame", padding=(12, 10))
        header_frame.pack(fill="x", pady=(0, 8))

        header_text = ttk.Frame(header_frame, style="App.Panel.TFrame")
        header_text.pack(side="left", fill="x", expand=True)

        title_label = ttk.Label(header_text, text="⏱️ Game Timer System", style="Timer.Title.TLabel")
        title_label.pack(anchor="w")
        ttk.Label(
            header_text,
            text="Track active timers, boss respawns, and chat-driven events.",
            style="Timer.Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # Always on top button
        self.always_on_top_var = tk.BooleanVar(value=self._get_ui_pref("timer_always_on_top", False))
        # ensure internal flag matches saved pref
        self.always_on_top = self.always_on_top_var.get()
        self.always_on_top_button = ttk.Button(
            header_frame,
            text="📌 Always on Top",
            command=self._toggle_always_on_top,
            style="Timer.Secondary.TButton",
        )
        self.always_on_top_button.pack(side="right", padx=(6, 0), anchor="n")

        # Apply initial always on top state
        if self.always_on_top_var.get():
            self.window.attributes('-topmost', True)
            self.always_on_top_button.configure(text="📌 Always on Top ✓")

        # Status bar - between header and tabs for better visibility
        status_frame = ttk.Frame(main_frame, style="App.Panel.TFrame", padding=(10, 8))
        status_frame.pack(fill="x", pady=(0, 8))

        # Status bar content - single line
        ttk.Label(status_frame, textvariable=self.status_var, style="Timer.Status.TLabel").pack(side="left", padx=2)

        # Chat/log monitoring status
        if self.monitor_status_var is not None:
            ttk.Label(status_frame, textvariable=self.monitor_status_var, style="Timer.Status.TLabel").pack(
                side="right",
                padx=2,
            )

        # Create notebook for the three main sections
        self.notebook = ttk.Notebook(main_frame, style="TNotebook")
        self.notebook.pack(fill="both", expand=True)

        # Bind tab change event to save preference
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Current timers tab
        self.active_frame = ttk.Frame(self.notebook, style="App.TFrame")
        self.notebook.add(self.active_frame, text="Current Timers")
        self._build_active_timers_ui()

        # History tab
        self.history_frame = ttk.Frame(self.notebook, style="App.TFrame")
        self.notebook.add(self.history_frame, text="History")
        self._build_history_ui()

        # Settings tab
        self.settings_frame = ttk.Frame(self.notebook, style="App.TFrame")
        self.notebook.add(self.settings_frame, text="Settings")

        settings_container = ttk.Frame(self.settings_frame, style="App.Panel.TFrame", padding=4)
        settings_container.pack(fill="both", expand=True)

        settings_canvas = tk.Canvas(settings_container, highlightthickness=0, bg=UI_COLORS["panel_bg"])
        settings_scrollbar = ttk.Scrollbar(settings_container, orient="vertical", command=settings_canvas.yview, style="App.Vertical.TScrollbar")
        settings_shell = ttk.Frame(settings_canvas, style="App.Panel.TFrame", padding=6)
        settings_window = settings_canvas.create_window((0, 0), window=settings_shell, anchor="nw")
        settings_canvas.configure(yscrollcommand=settings_scrollbar.set)

        def _sync_settings_width(_event):
            settings_canvas.itemconfigure(settings_window, width=settings_canvas.winfo_width())
        settings_canvas.bind("<Configure>", _sync_settings_width)
        settings_shell.bind("<Configure>", lambda e: settings_canvas.configure(scrollregion=settings_canvas.bbox("all")))

        settings_canvas.pack(side="left", fill="both", expand=True)
        settings_scrollbar.pack(side="right", fill="y")

        settings_shell.columnconfigure(0, weight=1, uniform="settings")
        settings_shell.columnconfigure(1, weight=1, uniform="settings")
        settings_shell.rowconfigure(0, weight=1)

        self.management_frame = ttk.Frame(settings_shell, style="App.TFrame")
        self.management_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_management_ui()

        self.boss_frame = ttk.Frame(settings_shell, style="App.TFrame")
        self.boss_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._build_boss_timers_ui()

        # Restore selected tab
        self.notebook.select(self.selected_tab_var.get())
    
    def _show_current_timers_tab(self):
        """Switch the notebook to the Current Timers tab."""
        if hasattr(self, "notebook") and self.notebook is not None:
            try:
                self.notebook.select(0)
            except Exception:
                pass

    def _build_active_timers_ui(self):
        """Build the active timers display."""
        shell = ttk.Frame(self.active_frame, style="App.Panel.TFrame", padding=8)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Timer.HeaderCard.TFrame", padding=(12, 10))
        header.pack(fill="x", pady=(0, 8))

        ttk.Label(header, text="Current Timers", style="Timer.Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Timers you start or detect from chat will appear here.",
            style="Timer.Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        canvas = tk.Canvas(shell, highlightthickness=0, bg=UI_COLORS["card_bg"])
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview, style="App.Vertical.TScrollbar")
        scrollable_frame = ttk.Frame(canvas, style="App.Card.TFrame")
        scrollable_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _sync_active_timer_width(_event):
            canvas.itemconfigure(scrollable_window, width=canvas.winfo_width())
        canvas.bind("<Configure>", _sync_active_timer_width)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self.active_timers_frame = scrollable_frame
    
    def _build_management_ui(self):
        """Build the timer management interface."""
        shell = ttk.Frame(self.management_frame, style="App.Panel.TFrame", padding=4)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Timer.HeaderCard.TFrame", padding=(8, 6))
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Timer Management", style="Timer.Title.TLabel").pack(anchor="w")

        manual_frame = ttk.LabelFrame(shell, text="Manual Timer", padding=6, style="Timer.Section.TLabelframe")
        manual_frame.pack(fill="x", pady=(0, 6))

        select_frame = ttk.Frame(manual_frame, style="Timer.Card.TFrame")
        select_frame.pack(fill="x")
        select_frame.columnconfigure(1, weight=1)

        ttk.Label(select_frame, text="Activity", style="Timer.Card.Muted.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.activity_var = tk.StringVar()
        self.activity_combo = ttk.Combobox(select_frame, textvariable=self.activity_var, style="App.TCombobox", width=24)
        self.activity_combo.grid(row=0, column=1, padx=4, pady=2, sticky="ew")

        activities = [f"{event_data['description']} ({event_key})" for event_key, event_data in DEFAULT_TIMER_DURATIONS.items()]
        self.activity_combo["values"] = sorted(activities)
        if activities:
            self.activity_combo.set(self.activity_var.get() if self.activity_var.get() in activities else activities[0])

        ttk.Label(select_frame, text="Duration", style="Timer.Card.Muted.TLabel").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(select_frame, textvariable=self.duration_var, style="App.TEntry", width=12).grid(row=1, column=1, padx=4, pady=2, sticky="ew")

        ttk.Label(select_frame, text="Notes", style="Timer.Card.Muted.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(select_frame, textvariable=self.notes_var, style="App.TEntry").grid(row=2, column=1, padx=4, pady=2, sticky="ew")

        self.activity_var.trace_add("write", lambda *args: self._save_timer_selection())
        self.duration_var.trace_add("write", lambda *args: self._save_timer_selection())
        self.notes_var.trace_add("write", lambda *args: self._save_timer_selection())

        button_frame = ttk.Frame(manual_frame, style="Timer.Card.TFrame")
        button_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(button_frame, text="Start", command=self._start_manual_timer, style="Timer.Primary.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(button_frame, text="Stop All", command=self._stop_all_timers, style="Timer.Secondary.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(button_frame, text="Clear All", command=self._clear_all_timers, style="Timer.Secondary.TButton").pack(side="left")

        if self.chat_monitor:
            chat_frame = ttk.LabelFrame(shell, text="Chat Monitoring", padding=6, style="Timer.Section.TLabelframe")
            chat_frame.pack(fill="x", pady=(0, 0))

            self.auto_start_var = tk.BooleanVar(value=self._get_ui_pref("timer_auto_start", True))
            chat_row = ttk.Frame(chat_frame, style="Timer.Card.TFrame")
            chat_row.pack(fill="x")
            ttk.Checkbutton(
                chat_row,
                text="Auto-start from chat",
                variable=self.auto_start_var,
                style="App.Card.TCheckbutton",
                command=self._toggle_auto_monitoring,
            ).pack(side="left", anchor="w")
            ttk.Button(chat_row, text="Scan Now", command=self._scan_chat_now, style="Timer.Secondary.TButton").pack(side="right")
    
    def _build_history_ui(self):
        """Build the timer history display."""
        shell = ttk.Frame(self.history_frame, style="App.Panel.TFrame", padding=8)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Timer.HeaderCard.TFrame", padding=(12, 10))
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Timer History", style="Timer.Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Recently completed timers and their outcomes.",
            style="Timer.Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        tree_frame = ttk.Frame(shell, style="App.Card.TFrame", padding=10)
        tree_frame.pack(fill="both", expand=True)

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", style="App.Vertical.TScrollbar")
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=("time", "activity", "duration", "status"),
            show="headings",
            style="Timer.Treeview",
            yscrollcommand=tree_scroll.set,
        )
        self.history_tree.heading("time", text="Time")
        self.history_tree.heading("activity", text="Activity")
        self.history_tree.heading("duration", text="Duration")
        self.history_tree.heading("status", text="Status")
        self.history_tree.column("time", width=150, stretch=False)
        self.history_tree.column("activity", width=220, stretch=True)
        self.history_tree.column("duration", width=110, stretch=False)
        self.history_tree.column("status", width=120, stretch=False)

        self.history_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        tree_scroll.configure(command=self.history_tree.yview)

        ttk.Button(shell, text="Refresh History", command=self._refresh_history, style="Timer.Secondary.TButton").pack(anchor="e", pady=(8, 0))
    
    def _build_boss_timers_ui(self):
        """Build the boss timers display."""
        shell = ttk.Frame(self.boss_frame, style="App.Panel.TFrame", padding=4)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Timer.HeaderCard.TFrame", padding=(8, 6))
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Boss Timers", style="Timer.Title.TLabel").pack(anchor="w")

        manual_frame = ttk.LabelFrame(shell, text="Manual Boss", padding=6, style="Timer.Section.TLabelframe")
        manual_frame.pack(fill="x", pady=(0, 6))

        select_frame = ttk.Frame(manual_frame, style="Timer.Card.TFrame")
        select_frame.pack(fill="x")
        select_frame.columnconfigure(1, weight=1)

        ttk.Label(select_frame, text="Boss", style="Timer.Card.Muted.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.boss_var = tk.StringVar()
        self.boss_combo = ttk.Combobox(select_frame, textvariable=self.boss_var, style="App.TCombobox", width=24)
        self.boss_combo.grid(row=0, column=1, padx=4, pady=2, sticky="ew")

        bosses = [f"{event_data['description']} ({event_key})" for event_key, event_data in DEFAULT_BOSS_DURATIONS.items()]
        self.boss_combo["values"] = sorted(bosses)
        last_boss = self._get_ui_pref("timer_last_boss", "")
        if bosses:
            self.boss_var.set(last_boss if last_boss in bosses else bosses[0])

        ttk.Label(select_frame, text="Duration", style="Timer.Card.Muted.TLabel").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.boss_duration_var = tk.StringVar()
        ttk.Entry(select_frame, textvariable=self.boss_duration_var, style="App.TEntry", width=12).grid(row=1, column=1, padx=4, pady=2, sticky="ew")

        ttk.Label(select_frame, text="Notes", style="Timer.Card.Muted.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(select_frame, textvariable=self.boss_notes_var, style="App.TEntry").grid(row=2, column=1, padx=4, pady=2, sticky="ew")

        last_boss_duration = self._get_ui_pref("timer_last_boss_duration", "")
        if last_boss_duration:
            self.boss_duration_var.set(last_boss_duration)

        self.boss_var.trace_add("write", lambda *args: self._save_boss_selection())
        self.boss_duration_var.trace_add("write", lambda *args: self._save_boss_selection())
        self.boss_notes_var.trace_add("write", lambda *args: self._save_boss_selection())

        button_frame = ttk.Frame(manual_frame, style="Timer.Card.TFrame")
        button_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(button_frame, text="Start", command=self._start_boss_timer, style="Timer.Primary.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(button_frame, text="Stop All", command=self._stop_boss_timers, style="Timer.Secondary.TButton").pack(side="left")

        active_frame = ttk.LabelFrame(shell, text="Active Boss", padding=6, style="Timer.Section.TLabelframe")
        active_frame.pack(fill="both", expand=True, pady=(0, 0))

        canvas = tk.Canvas(active_frame, highlightthickness=0, bg=UI_COLORS["card_bg"])
        scrollbar = ttk.Scrollbar(active_frame, orient="vertical", command=canvas.yview, style="App.Vertical.TScrollbar")
        scrollable_frame = ttk.Frame(canvas, style="App.Card.TFrame")
        scrollable_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _sync_active_boss_timer_width(_event):
            canvas.itemconfigure(scrollable_window, width=canvas.winfo_width())
        canvas.bind("<Configure>", _sync_active_boss_timer_width)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self.active_boss_timers_frame = ttk.Frame(scrollable_frame, style="Timer.Card.TFrame")
        self.active_boss_timers_frame.pack(fill="both", expand=True)
    
    def _on_tab_changed(self, event):
        """Handle tab change event and save preference."""
        try:
            notebook = event.widget
            current_tab = notebook.index(notebook.select())
            self.selected_tab_var.set(current_tab)
            self._set_ui_pref("timer_selected_tab", current_tab)
        except Exception as e:
            print(f"Error saving tab selection: {e}")
    
    def _save_management_settings(self):
        """Save management settings preferences."""
        try:
            self._set_ui_pref("timer_management_auto_start", self.management_auto_start_var.get())
            self._set_ui_pref("timer_management_scan_interval", self.management_scan_interval_var.get())
            self._set_ui_pref("timer_management_notifications", self.management_notifications_var.get())
        except Exception as e:
            print(f"Error saving management settings: {e}")
    
    def _save_timer_selection(self):
        """Save timer selection preferences."""
        try:
            self._set_ui_pref("timer_last_activity", self.activity_var.get())
            self._set_ui_pref("timer_last_duration", self.duration_var.get())
            self._set_ui_pref("timer_notes", self.notes_var.get())
        except Exception as e:
            print(f"Error saving timer selection: {e}")
    
    def _save_boss_selection(self):
        """Save boss timer selection preferences."""
        try:
            self._set_ui_pref("timer_last_boss", self.boss_var.get())
            self._set_ui_pref("timer_last_boss_duration", self.boss_duration_var.get())
            self._set_ui_pref("timer_boss_notes", self.boss_notes_var.get())
        except Exception as e:
            print(f"Error saving boss selection: {e}")
    
    def _start_boss_timer(self):
        """Start a boss timer."""
        try:
            # Get selected boss and extract event type
            boss_text = self.boss_var.get()
            if not boss_text:
                messagebox.showerror("Error", "Please select a boss.")
                return
            
            # Extract event type from the description
            event_type = None
            for key, data in DEFAULT_BOSS_DURATIONS.items():
                if data['description'] in boss_text:
                    event_type = key
                    break
            
            if not event_type:
                messagebox.showerror("Error", "Invalid boss selected.")
                return
            
            # Get duration
            try:
                duration = int(self.boss_duration_var.get()) if self.boss_duration_var.get() else None
                if not duration or duration <= 0:
                    messagebox.showerror("Error", "Please enter a valid duration in seconds.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Duration must be a number.")
                return
            
            # Get boss name from event_type
            _boss_name = event_type.split(':', 1)
            boss_name = _boss_name[1] if len(_boss_name) > 1 else _boss_name[0]
            
            # Start boss timer
            timer_id = self.timer_db.start_timer("boss", boss_name, self.boss_notes_var.get(), duration)
            
            self.status_var.set(f"Started boss timer: {self.boss_var.get()}")
            self._refresh_timers()
            self._show_current_timers_tab()
            self._refresh_boss_timers()
            self._refresh_history()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start boss timer: {e}")
    
    def _stop_boss_timers(self):
        """Stop all active boss timers."""
        try:
            boss_timers = self.timer_db.get_active_boss_timers()
            stopped_count = 0
            
            for timer in boss_timers:
                self.timer_db.stop_timer(timer['id'], 'manual_stop')
                stopped_count += 1
            
            self.status_var.set(f"Stopped {stopped_count} boss timer(s)")
            self._refresh_timers()
            self._refresh_boss_timers()
            self._refresh_history()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop boss timers: {e}")
    
    def _refresh_boss_timers(self):
        """Refresh the active boss timers display."""
        # Clear existing boss timer displays
        for widget in self.active_boss_timers_frame.winfo_children():
            widget.destroy()
        
        # Get active boss timers
        boss_timers = self.timer_db.get_active_boss_timers()
        
        if not boss_timers:
            no_timers_label = ttk.Label(self.active_boss_timers_frame 
                                     , text="No active boss timers" 
                                     , style="App.Muted.TLabel")
            no_timers_label.pack(pady=8)
            return
        
        # Display each active boss timer
        for i, timer in enumerate(boss_timers, 1):
            self._create_boss_timer_display(timer, i)
    
    def _create_boss_timer_display(self, timer, row):
        """Create UI display for a single boss timer."""
        frame = ttk.Frame(self.active_boss_timers_frame, style="Timer.Card.TFrame", padding=0)
        frame.pack(fill="x", pady=3, padx=1)

        display_name = timer["event_name"].replace("_", " ").title()
        max_duration = int(timer.get("duration_seconds") or DEFAULT_BOSS_DURATIONS.get(f"boss:{timer['event_name']}", {}).get("duration", 900))
        current_duration = timer["current_duration_seconds"]

        row_frame = ttk.Frame(frame, style="Timer.Card.TFrame", padding=(8, 5, 8, 6))
        row_frame.pack(fill="x")
        row_frame.columnconfigure(0, weight=1)
        row_frame.columnconfigure(1, weight=0)

        indicator_canvas = tk.Canvas(row_frame, height=30, highlightthickness=0, bg=UI_COLORS["card_bg"])
        indicator_canvas.grid(row=0, column=0, sticky="ew")

        self.active_boss_timers[timer['id']] = {
            'frame': frame,
            'indicator_canvas': indicator_canvas,
            'display_name': display_name,
            'current_duration': current_duration,
            'start_time': timer['start_time'],
            'max_duration': max_duration,
        }

        indicator_canvas.bind("<Configure>", lambda _event, timer_id=timer['id']: self._refresh_timer_indicator(timer_id, boss=True))
        self._refresh_timer_indicator(timer['id'], boss=True)
        self._update_boss_timer_progress(timer['id'])
    
    def _stop_boss_timer(self, timer_id: int):
        """Stop a specific boss timer."""
        try:
            result = self.timer_db.stop_timer(timer_id, 'manual_stop')
            if result:
                self.status_var.set(f"Stopped boss timer: {result['event_name']}")
                self._refresh_timers()
                self._refresh_boss_timers()
                self._refresh_history()
            else:
                messagebox.showerror("Error", "Boss timer not found or already stopped.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop boss timer: {e}")
    
    def _cancel_boss_timer(self, timer_id: int):
        """Cancel a specific boss timer."""
        try:
            if self.timer_db.cancel_timer(timer_id):
                self.status_var.set(f"Cancelled boss timer: #{timer_id}")
                self._refresh_timers()
                self._refresh_boss_timers()
            else:
                messagebox.showerror("Error", "Boss timer not found.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to cancel boss timer: {e}")
    
    def _update_boss_timer_progress(self, timer_id: int):
        """Update the boss timer countdown indicator."""
        if not hasattr(self, 'active_boss_timers') or timer_id not in self.active_boss_timers:
            return

        timer_data = self.active_boss_timers[timer_id]

        try:
            frame = timer_data.get("frame")
            canvas = timer_data.get("indicator_canvas")
            remaining_label = timer_data.get("remaining_label")
            if self.window is None or not self.window.winfo_exists():
                return
            if frame is None or not frame.winfo_exists():
                return
            if canvas is None or not canvas.winfo_exists():
                return
            if remaining_label is not None and not remaining_label.winfo_exists():
                return
        except tk.TclError:
            return

        start_time = datetime.fromisoformat(timer_data['start_time'])
        current_duration = int((datetime.now() - start_time).total_seconds())
        timer_data['current_duration'] = current_duration

        self._refresh_timer_indicator(timer_id, boss=True)

        # Schedule next update only if the window is still alive
        try:
            if self.window is not None and self.window.winfo_exists():
                self.window.after(1000, lambda: self._update_boss_timer_progress(timer_id))
        except Exception:
            pass

    def _start_manual_timer(self):
        """Start a manual timer."""
        try:
            # Get selected activity and extract event type
            activity_text = self.activity_var.get()
            if not activity_text:
                messagebox.showerror("Error", "Please select an activity.")
                return
            
            # Extract event type from the description
            event_type = None
            for key, data in DEFAULT_TIMER_DURATIONS.items():
                if data['description'] in activity_text:
                    event_type = key
                    break
            
            if not event_type:
                messagebox.showerror("Error", "Invalid activity selected.")
                return
            
            # Get duration
            duration = self._parse_duration_input(self.duration_var.get())
            if not duration or duration <= 0:
                messagebox.showerror("Error", "Please enter a valid duration in seconds.")
                return
            
            # Get event name from event_type
            _event_name = event_type.split(':', 1)
            event_name = _event_name[1] if len(_event_name) > 1 else _event_name[0]
            
            # Start timer
            timer_id = self.timer_db.start_timer(event_type, event_name, self.notes_var.get(), duration)
            
            self.status_var.set(f"Started timer: {self.activity_var.get()}")
            self._refresh_timers()
            self._show_current_timers_tab()
            self._refresh_history()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start timer: {e}")
    
    def _stop_all_timers(self):
        """Stop all active timers."""
        try:
            active_timers = self.timer_db.get_active_timers()
            stopped_count = 0
            
            for timer in active_timers:
                self.timer_db.stop_timer(timer['id'], 'manual_stop')
                stopped_count += 1
            
            self.status_var.set(f"Stopped {stopped_count} timer(s)")
            self._refresh_timers()
            self._refresh_history()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop timers: {e}")
    
    def _clear_all_timers(self):
        """Cancel all active timers."""
        try:
            active_timers = self.timer_db.get_active_timers()
            cleared_count = 0
            
            for timer in active_timers:
                if self.timer_db.cancel_timer(timer['id']):
                    cleared_count += 1
            
            self.status_var.set(f"Cleared {cleared_count} timer(s)")
            self._refresh_timers()
            self._refresh_history()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear timers: {e}")
    
    def _toggle_auto_monitoring(self):
        """Toggle chat monitoring on/off and save preference."""
        if self.auto_start_var.get():
            self.start_chat_monitoring()
        else:
            self.stop_chat_monitoring()
        
        # Save preference
        self._set_ui_pref("timer_auto_start", self.auto_start_var.get())
    
    def _scan_chat_now(self):
        """Manually scan chat and player logs for events."""
        if not self.chat_monitor and self.player_monitor is None:
            messagebox.showwarning("Warning", "Log monitoring not available.")
            return
        
        try:
            lines = self._read_chat_monitor_lines()
            player_lines = self._read_player_monitor_lines()
            actions = self._process_chat_lines(lines) + self._process_player_lines(player_lines)
            
            for action in actions:
                self.status_var.set(action)
                self._refresh_timers()
                self._refresh_history()
            
            if actions:
                messagebox.showinfo("Scan Complete", f"Processed {len(actions)} events.")
            else:
                messagebox.showinfo("Scan Complete", "No new timer events found.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to scan chat: {e}")
    
    def start_chat_monitoring(self):
        """Start background chat monitoring."""
        if self.monitoring_active:
            return
        if not self.chat_monitor and self.player_monitor is None:
            return
        
        self.monitoring_active = True
        if self.monitor_status_var is not None:
            self.monitor_status_var.set("🟢 Log Monitoring Active")
        
        def monitor_loop():
            while self.monitoring_active:
                try:
                    chat_lines = self._read_chat_monitor_lines()
                    player_lines = self._read_player_monitor_lines()
                    actions = self._process_chat_lines(chat_lines) + self._process_player_lines(player_lines)
                    if actions:
                        self.window.after(0, lambda acts=actions: self._apply_chat_actions(acts))
                    time.sleep(5)  # Check every 5 seconds
                    
                except Exception as e:
                    print(f"Chat monitoring error: {e}")
                    time.sleep(10)
        
        self.timer_update_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.timer_update_thread.start()
    
    def _apply_chat_actions(self, actions):
        """Apply chat-derived timer actions on the Tk main thread."""
        if not actions:
            return
        for action in actions:
            self.status_var.set(action)
        self._refresh_timers()
        self._refresh_history()
    
    def stop_chat_monitoring(self):
        """Stop chat monitoring."""
        self.monitoring_active = False
        self.monitor_status_var.set("🔴 Chat Monitoring Stopped")
        
        if self.timer_update_thread:
            self.timer_update_thread.join(timeout=2)
    
    def _read_chat_monitor_lines(self):
        """Read newly appended chat log lines from the underlying monitor."""
        if not self.chat_monitor:
            return []
        try:
            return self.chat_monitor.read_new_lines()
        except Exception:
            return []

    def _read_player_monitor_lines(self):
        """Read newly appended player.log lines from the underlying monitor."""
        if self.player_monitor is None:
            self._ensure_player_monitor()
        if self.player_monitor is None:
            return []
        try:
            return self.player_monitor.read_new_lines()
        except Exception:
            return []

    def _ensure_player_monitor(self):
        """Create the player monitor lazily when PG_BASE becomes available."""
        if self.player_monitor is not None:
            return
        if getattr(config, "PG_BASE", None) is None:
            return
        try:
            self.player_monitor = PlayerLogMonitor(log_dir=config.PG_BASE)
        except Exception:
            self.player_monitor = None

    def _get_timer_key_variants(self, event_type: str, event_name: str) -> List[str]:
        key = f"{event_type}:{event_name}".lower()
        variants = {key}
        if event_name:
            compact = event_name.replace("_", "")
            variants.add(f"{event_type}:{compact}".lower())
        return list(variants)

    def _get_timer_duration_seconds(self, event_type: str, event_name: str, default: int = 300) -> int:
        for key in self._get_timer_key_variants(event_type, event_name):
            data = DEFAULT_TIMER_DURATIONS.get(key)
            if data:
                return int(data.get("duration", default))
        return default

    def _get_timer_display_name(self, event_type: str, event_name: str) -> str:
        for key in self._get_timer_key_variants(event_type, event_name):
            data = DEFAULT_TIMER_DURATIONS.get(key)
            if data and data.get("description"):
                return str(data["description"])
        return event_name.replace("_", " ").title()

    def _parse_duration_input(self, raw_value: str) -> Optional[int]:
        """Parse a timer duration from user input.

        Accepts plain seconds like "10" and simple human-friendly values like
        "10 sec", "5m", or "1h 30m".
        """
        text = str(raw_value or "").strip().lower()
        if not text:
            return None

        try:
            return max(1, int(text))
        except ValueError:
            pass

        total_seconds = 0
        matched = False
        for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", text):
            matched = True
            value = float(amount)
            if unit == "h":
                total_seconds += int(value * 3600)
            elif unit == "m":
                total_seconds += int(value * 60)
            elif unit == "s":
                total_seconds += int(value)

        if matched and total_seconds > 0:
            return total_seconds

        return None

    def _draw_timer_indicator(self, canvas, percent_remaining: float, label_text: str):
        """Draw a smooth gradient countdown bar with centered text."""
        if canvas is None or not canvas.winfo_exists():
            return

        canvas.delete("all")
        width = max(240, int(canvas.winfo_width() or canvas.winfo_reqwidth() or 240))
        height = max(30, int(canvas.winfo_height() or canvas.winfo_reqheight() or 30))

        pad_x = 3
        pad_y = 4
        track_x0 = pad_x
        track_x1 = max(track_x0 + 10, width - pad_x)
        track_y0 = pad_y
        track_y1 = max(track_y0 + 10, height - pad_y)
        track_width = track_x1 - track_x0
        segment_colors = ["#22c55e", "#eab308", "#ef4444"]

        for i in range(24):
            start = i / 24.0
            end = (i + 1) / 24.0
            seg_x0 = track_x0 + (track_width * start)
            seg_x1 = track_x0 + (track_width * end)
            color_index = 0 if start < 0.5 else 1 if start < 0.85 else 2
            canvas.create_rectangle(
                seg_x0,
                track_y0,
                seg_x1,
                track_y1,
                fill=segment_colors[color_index],
                outline=segment_colors[color_index],
                width=0,
            )

        canvas.create_rectangle(track_x0, track_y0, track_x1, track_y1, outline="#0f1720", width=1)
        marker_x = track_x0 + (track_width * max(0.0, min(1.0, percent_remaining)))
        marker_x = max(track_x0, min(track_x1, marker_x))
        canvas.create_line(marker_x, track_y0 - 1, marker_x, track_y1 + 1, fill="#ffffff", width=3)
        canvas.create_oval(marker_x - 6, track_y0 + 2, marker_x + 6, track_y0 + 14, fill="#ffffff", outline="#111827", width=2)
        canvas.create_text(
            (track_x0 + track_x1) / 2,
            (track_y0 + track_y1) / 2,
            text=label_text,
            fill="#000000",
            font=(UI_ATTRS["font_family"], max(10, UI_ATTRS["font_size"] + 1), "bold"),
            justify="center",
        )

    def _draw_timer_switch(self, canvas, percent_remaining: float):
        """Draw a sliding switch-style countdown indicator."""
        if canvas is None or not canvas.winfo_exists():
            return

        canvas.delete("all")
        width = max(56, int(canvas.winfo_width() or canvas.winfo_reqwidth() or 56))
        height = max(28, int(canvas.winfo_height() or canvas.winfo_reqheight() or 28))
        progress = max(0.0, min(1.0, percent_remaining))

        track_outline = "#111827"
        track_fill = "#22c55e" if progress > 0.66 else "#f59e0b" if progress > 0.33 else "#ef4444"
        knob_left = 6 + int((width - 22) * (1.0 - progress))
        knob_right = knob_left + 16

        canvas.create_rectangle(10, 8, width - 10, height - 8, fill="#1f2937", outline=track_outline, width=2)
        canvas.create_rectangle(12, 10, width - 12, height - 10, fill=track_fill, outline="", width=0)
        canvas.create_oval(knob_left, 5, knob_right, height - 5, fill="#ffffff", outline=track_outline, width=2)

    def _refresh_timer_indicator(self, timer_id: int, boss: bool = False):
        """Redraw the countdown switch, bar, and label for one timer."""
        store = self.active_boss_timers if boss else self.active_timers
        timer_data = store.get(timer_id)
        if not timer_data:
            return

        canvas = timer_data.get("indicator_canvas")
        frame = timer_data.get("frame")
        display_name = timer_data.get("display_name", "Timer")

        try:
            if canvas is None or not canvas.winfo_exists():
                return
            if frame is not None and not frame.winfo_exists():
                return
        except tk.TclError:
            return

        current_duration = int(timer_data.get("current_duration", 0))
        max_duration = max(1, int(timer_data.get("max_duration", 300)))
        remaining = max(0, max_duration - current_duration)
        percent_remaining = max(0.0, min(1.0, remaining / max_duration))
        label_text = f"{display_name}  •  {int(round(percent_remaining * 100))}%  •  {self._format_duration(remaining)} left"

        try:
            self._draw_timer_indicator(canvas, percent_remaining, label_text)
        except tk.TclError:
            return

    def _has_active_timer(self, event_type: str, event_name: str) -> bool:
        for timer in self.timer_db.get_active_timers():
            if timer.get("event_type") == event_type and timer.get("event_name") == event_name:
                return True
        return False

    def _start_auto_timer_from_line(self, event_key: str, line: str, source: str) -> Optional[str]:
        event_data = DEFAULT_TIMER_DURATIONS.get(event_key)
        if not event_data:
            return None
        event_type, event_name = event_key.split(":", 1)
        if self._has_active_timer(event_type, event_name):
            return f"{event_data['description']} already running"

        timer_id = self.timer_db.start_timer(
            event_type,
            event_name,
            f"Auto-started from {source}: {line.strip()}",
        )
        self.window.after(0, self._show_current_timers_tab)
        self.window.after(0, self._refresh_timers)
        return f"Started {event_data['description']} timer (ID: {timer_id})"

    def _detect_auto_timer_key(self, line: str) -> Optional[str]:
        lowered = line.lower()
        compact = lowered.replace(" ", "").replace("-", "").replace("_", "")

        if "egg run" in lowered or "eggrun" in compact or "one hour clock" in lowered or "hour clock" in lowered:
            return "misc:egg_run"

        if ("retting" in lowered and "flax" in lowered) or "rettingbundle" in compact or "linen retting" in lowered:
            return "retting:flax"

        return None
    
    def _process_chat_lines(self, lines):
        """Convert chat log lines into timer actions.

        This preserves the timer window workflow without relying on older
        ChatLogMonitor helper methods that no longer exist.
        """
        actions = []
        for line in lines or []:
            if not line:
                continue

            auto_key = self._detect_auto_timer_key(line)
            if auto_key:
                action = self._start_auto_timer_from_line(auto_key, line, "chat log")
                if action:
                    actions.append(action)
                continue

            lowered = line.lower()
            if "timer" in lowered and ("start" in lowered or "begin" in lowered):
                actions.append(f"Timer event detected: {line}")
            elif "boss" in lowered and ("respawn" in lowered or "spawn" in lowered):
                actions.append(f"Boss event detected: {line}")
        return actions

    def _process_player_lines(self, lines):
        """Convert player.log lines into timer actions."""
        actions = []
        for line in lines or []:
            if not line:
                continue

            auto_key = self._detect_auto_timer_key(line)
            if auto_key:
                action = self._start_auto_timer_from_line(auto_key, line, "player.log")
                if action:
                    actions.append(action)
        return actions
    
    def _refresh_timers(self):
        """Refresh the active timers display."""
        # Clear existing timer displays
        for widget in self.active_timers_frame.winfo_children():
            widget.destroy()
        
        # Get active timers
        active_timers = self.timer_db.get_active_timers()
        
        if not active_timers:
            no_timers_label = ttk.Label(
                self.active_timers_frame,
                text="No active timers yet.",
                style="App.Muted.TLabel",
            )
            no_timers_label.pack(pady=20)
            return
        
        # Display each active timer
        for i, timer in enumerate(active_timers, 1):
            self._create_timer_display(timer, i)
    
    def _create_timer_display(self, timer, row):
        """Create UI display for a single timer."""
        frame = ttk.Frame(self.active_timers_frame, style="Timer.Card.TFrame", padding=0)
        frame.pack(fill="x", pady=3, padx=1)

        display_name = self._get_timer_display_name(timer["event_type"], timer["event_name"])
        max_duration = int(timer.get("duration_seconds") or self._get_timer_duration_seconds(timer["event_type"], timer["event_name"], default=300))
        current_duration = timer["current_duration_seconds"]

        row_frame = ttk.Frame(frame, style="Timer.Card.TFrame", padding=(8, 5, 8, 6))
        row_frame.pack(fill="x")
        row_frame.columnconfigure(0, weight=1)
        row_frame.columnconfigure(1, weight=0)

        indicator_canvas = tk.Canvas(row_frame, height=30, highlightthickness=0, bg=UI_COLORS["card_bg"])
        indicator_canvas.grid(row=0, column=0, sticky="ew")

        self.active_timers[timer['id']] = {
            'frame': frame,
            'indicator_canvas': indicator_canvas,
            'display_name': display_name,
            'current_duration': current_duration,
            'start_time': timer['start_time'],
            'max_duration': max_duration,
        }

        indicator_canvas.bind("<Configure>", lambda _event, timer_id=timer['id']: self._refresh_timer_indicator(timer_id))
        self._refresh_timer_indicator(timer['id'])
        self._update_timer_progress(timer['id'])
    
    def _stop_timer(self, timer_id: int):
        """Stop a specific timer."""
        try:
            result = self.timer_db.stop_timer(timer_id, 'manual_stop')
            if result:
                self.status_var.set(f"Stopped timer: {result['event_name']}")
                self._refresh_timers()
                self._refresh_history()
            else:
                messagebox.showerror("Error", "Timer not found or already stopped.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop timer: {e}")
    
    def _cancel_timer(self, timer_id: int):
        """Cancel a specific timer."""
        try:
            if self.timer_db.cancel_timer(timer_id):
                self.status_var.set(f"Cancelled timer: #{timer_id}")
                self._refresh_timers()
            else:
                messagebox.showerror("Error", "Timer not found.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to cancel timer: {e}")
    
    def _update_timer_progress(self, timer_id: int):
        """Update the timer countdown indicator."""
        if timer_id not in self.active_timers:
            return

        timer_data = self.active_timers[timer_id]

        try:
            frame = timer_data.get("frame")
            canvas = timer_data.get("indicator_canvas")
            remaining_label = timer_data.get("remaining_label")
            if self.window is None or not self.window.winfo_exists():
                return
            if frame is None or not frame.winfo_exists():
                return
            if canvas is None or not canvas.winfo_exists():
                return
            if remaining_label is not None and not remaining_label.winfo_exists():
                return
        except tk.TclError:
            return

        start_time = datetime.fromisoformat(timer_data['start_time'])
        current_duration = int((datetime.now() - start_time).total_seconds())
        timer_data['current_duration'] = current_duration

        self._refresh_timer_indicator(timer_id)

        # Schedule next update only if the window is still alive
        try:
            if self.window is not None and self.window.winfo_exists():
                self.window.after(1000, lambda: self._update_timer_progress(timer_id))
        except Exception:
            pass
    
    def _refresh_history(self):
        """Refresh the history display."""
        # Clear existing history
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        
        # Add recent history
        history = self.timer_db.get_timer_history(50)
        for entry in history:
            time_str = datetime.fromisoformat(entry['start_time']).strftime("%H:%M:%S")
            duration_str = self._format_duration(entry['duration_seconds'])
            
            self.history_tree.insert("", "end", values=(
                time_str,
                entry['event_name'],
                duration_str,
                entry['completion_status']
            ))
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    def _on_window_resize(self, event):
        """Handle window resize events with optimized debouncing."""
        # Only save on actual resize events (not move events)
        if event.widget == self.window:
            # Check if this is a resize (both width and height > 1)
            if hasattr(self, '_last_geometry'):
                current_geom = f"{event.width}x{event.height}"
                if current_geom == self._last_geometry:
                    return  # No actual change skip
                self._last_geometry = current_geom
            else:
                self._last_geometry = f"{event.width}x{event.height}"
            
            # Cancel any existing save timer
            if hasattr(self, '_resize_timer'):
                self.window.after_cancel(self._resize_timer)
            
            # Schedule save with longer debouncing for better performance
            self._resize_timer = self.window.after(1000, self._save_window_geometry)
    
    def _update_always_on_top_button(self):
        """Update the always on top button text after UI is built."""
        try:
            if hasattr(self, 'always_on_top_button'):
                self.always_on_top_button.configure(text="📌 Always on Top ✓")
        except Exception as e:
            print(f"Error updating always on top button: {e}")
    
    def _toggle_always_on_top(self):
        """Toggle always on top state."""
        self.always_on_top = not self.always_on_top
        self.always_on_top_var.set(self.always_on_top)
        
        if self.always_on_top:
            self.window.attributes('-topmost', True)
            self.always_on_top_button.configure(text="📌 Always on Top ✓")
        else:
            self.window.attributes('-topmost', False)
            self.always_on_top_button.configure(text="📌 Always on Top")
        
        # Save preference
        self._set_ui_pref("timer_always_on_top", self.always_on_top)
    
    def _get_ui_pref(self, key: str, default=None):
        """Get a UI preference from the parent app."""
        try:
            if hasattr(self.parent, '_get_ui_pref'):
                value = self.parent._get_ui_pref(key, default)
                return value
            else:
                return default
        except Exception as e:
            return default
    
    def _set_ui_pref(self, key: str, value):
        """Set a UI preference in the parent app."""
        try:
            if hasattr(self.parent, '_set_ui_pref'):
                self.parent._set_ui_pref(key, value)
            else:
                pass
        except Exception as e:
            pass
    
    def _save_window_geometry(self):
        """Save window geometry and all settings."""
        try:
            geometry = self.window.geometry()
            self._set_ui_pref("timer_window_geometry", geometry)
            self._set_ui_pref("timer_always_on_top", self.always_on_top)
            
            # Save all UI state
            self._set_ui_pref("timer_selected_tab", self.selected_tab_var.get())
            self._set_ui_pref("timer_management_auto_start", self.management_auto_start_var.get())
            self._set_ui_pref("timer_management_scan_interval", self.management_scan_interval_var.get())
            self._set_ui_pref("timer_management_notifications", self.management_notifications_var.get())
            self._set_ui_pref("timer_history_limit", self.history_limit_var.get())
            
            # Save timer selections
            self._set_ui_pref("timer_last_activity", self.activity_var.get())
            self._set_ui_pref("timer_last_duration", self.duration_var.get())
            self._set_ui_pref("timer_notes", self.notes_var.get())
            self._set_ui_pref("timer_last_boss", self.boss_var.get())
            self._set_ui_pref("timer_last_boss_duration", self.boss_duration_var.get())
            self._set_ui_pref("timer_boss_notes", self.boss_notes_var.get())
            
        except Exception as e:
            print(f"Error saving timer window settings: {e}")
    
    def _restore_window_geometry(self):
        """Restore window geometry and settings."""
        try:
            # Get saved geometry from parent's preferences
            saved_geometry = self._get_ui_pref("timer_window_geometry", "400x300+100+100")
            
            # Apply the saved geometry directly; if it has no explicit screen
            # position, center relative to the parent window instead of the
            # whole desktop.
            if saved_geometry and "+" not in saved_geometry and hasattr(self.parent, "root"):
                try:
                    self.parent.root.update_idletasks()
                    root_x = self.parent.root.winfo_rootx()
                    root_y = self.parent.root.winfo_rooty()
                    root_w = self.parent.root.winfo_width() or self.parent.root.winfo_reqwidth()
                    root_h = self.parent.root.winfo_height() or self.parent.root.winfo_reqheight()
                    width = self.window.winfo_width() or self.window.winfo_reqwidth() or 400
                    height = self.window.winfo_height() or self.window.winfo_reqheight() or 300
                    x = root_x + max(0, (root_w - width) // 2)
                    y = root_y + max(0, (root_h - height) // 2)
                    self.window.geometry(f"{width}x{height}+{x}+{y}")
                except Exception:
                    self.window.geometry(saved_geometry)
            else:
                self.window.geometry(saved_geometry)
            
            # Apply always on top state
            if self.always_on_top_var.get():
                self.window.attributes('-topmost', True)
                self.always_on_top_button.configure(text="📌 Always on Top ✓")
            
            print(f"✅ Applied saved geometry: {saved_geometry}")
            
        except Exception as e:
            print(f"Error restoring timer window geometry: {e}")
            # Fallback to default geometry
            self.window.geometry("400x300+100+100")
    
    def _center_window(self):
        """Center the window on the screen."""
        try:
            self.window.update_idletasks()
            width = self.window.winfo_width()
            height = self.window.winfo_height()
            x = (self.window.winfo_screenwidth() // 2) - (width // 2)
            y = (self.window.winfo_screenheight() // 2) - (height // 2)
            self.window.geometry(f"+{x}+{y}")
        except Exception as e:
            print(f"Error centering window: {e}")
    
    def _on_close(self):
        """Handle window close event and save settings efficiently."""
        # Stop monitoring immediately
        self.monitoring_active = False
        
        # Cancel any pending timers
        if hasattr(self, '_resize_timer'):
            self.window.after_cancel(self._resize_timer)
        
        # Stop update thread quickly (non-blocking)
        if hasattr(self, 'timer_update_thread') and self.timer_update_thread:
            self.timer_update_thread.join(timeout=0.5)  # Shorter timeout
        
        # Save geometry immediately without delays
        try:
            geometry = self.window.geometry()
            self._set_ui_pref("timer_window_geometry", geometry)
            self._set_ui_pref("timer_always_on_top", self.always_on_top)
        except Exception as e:
            print(f"Error saving final geometry: {e}")
        
        # Destroy window immediately
        self.window.destroy()
