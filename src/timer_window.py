import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading
import time
import json

from src.timer_db import TimerDatabase, get_db_path, DEFAULT_TIMER_DURATIONS, DEFAULT_BOSS_DURATIONS
from src.chat_monitor import ChatLogMonitor
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
        self.chat_monitor = ChatLogMonitor(chat_dir, self.timer_db) if chat_dir else None
        
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
        self.monitor_status_var = tk.StringVar(value="🟢 Chat Monitoring Active") if self.chat_monitor else None
        
        # Start monitoring if chat directory is available
        if self.chat_monitor:
            self.start_chat_monitoring()
        
        self._build_ui()
        
        # Apply saved geometry after UI is built to prevent size override
        self.window.geometry(saved_geometry)
        
        # Force window to update its size
        self.window.update_idletasks()
        
        # Apply geometry again after a delay to ensure it takes effect
        self.window.after(100, lambda: self.window.geometry(saved_geometry))
        
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
        main_frame = ttk.Frame(self.window, padding=6, style="App.TFrame")
        main_frame.pack(fill="both", expand=True)
        
        # Header with title and always on top button
        header_frame = ttk.Frame(main_frame, style="App.Panel.TFrame")
        header_frame.pack(fill="x", pady=(0, 6))
        
        title_label = ttk.Label(header_frame, text="⏱️ Game Timer System", style="App.Title.TLabel")
        title_label.pack(side="left")
        
        # Always on top button
        self.always_on_top_var = tk.BooleanVar(value=self._get_ui_pref("timer_always_on_top", False))
        # ensure internal flag matches saved pref
        self.always_on_top = self.always_on_top_var.get()
        self.always_on_top_button = ttk.Button(header_frame, text="📌 Always on Top", 
                                             command=self._toggle_always_on_top,
                                             style="App.Secondary.TButton")
        self.always_on_top_button.pack(side="right", padx=(6, 0))
        
        # Apply initial always on top state
        if self.always_on_top_var.get():
            self.window.attributes('-topmost', True)
            self.always_on_top_button.configure(text="📌 Always on Top ✓")
        
        # Status bar - between header and tabs for better visibility
        status_frame = ttk.Frame(main_frame, style="App.TFrame")
        status_frame.pack(fill="x", pady=(3, 6))
        
        # Status bar content - single line
        ttk.Label(status_frame, textvariable=self.status_var, 
                 style="App.Status.TLabel").pack(side="left", padx=5)
        
        # Chat monitoring status
        if self.chat_monitor:
            ttk.Label(status_frame, textvariable=self.monitor_status_var, 
                     style="App.Status.TLabel").pack(side="right", padx=5)
        
        # Create notebook for different sections
        notebook = ttk.Notebook(main_frame, style="TNotebook")
        notebook.pack(fill="both", expand=True)
        
        # Bind tab change event to save preference
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        
        # Active timers tab
        self.active_frame = ttk.Frame(notebook, style="App.TFrame")
        notebook.add(self.active_frame, text="🔴 Active Timers")
        self._build_active_timers_ui()
        
        # Timer management tab
        self.management_frame = ttk.Frame(notebook, style="App.TFrame")
        notebook.add(self.management_frame, text="⚙️ Timer Management")
        self._build_management_ui()
        
        # History tab
        self.history_frame = ttk.Frame(notebook, style="App.TFrame")
        notebook.add(self.history_frame, text="📊 History")
        self._build_history_ui()
        
        # Boss timer tab
        self.boss_frame = ttk.Frame(notebook, style="App.TFrame")
        notebook.add(self.boss_frame, text="👹 Boss Timers")
        self._build_boss_timers_ui()
        
        # Restore selected tab
        notebook.select(self.selected_tab_var.get())
    
    def _build_active_timers_ui(self):
        """Build the active timers display."""
        # Scrollable frame for active timers (horizontal layout)
        canvas = tk.Canvas(self.active_frame, highlightthickness=0)
        canvas.configure(bg=UI_COLORS["card_bg"])
        h_scroll = ttk.Scrollbar(self.active_frame, orient="horizontal", command=canvas.xview, style="App.Horizontal.TScrollbar")
        
        scrollable_frame = ttk.Frame(canvas, style="App.Card.TFrame")
        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(xscrollcommand=h_scroll.set)
        
        # Pack canvas and horizontal scrollbar
        canvas.pack(side="top", fill="both", expand=True)
        h_scroll.pack(side="bottom", fill="x")
        
        # Header (kept above the horizontal strip)
        header_frame = ttk.Frame(scrollable_frame, style="App.Card.TFrame")
        header_frame.pack(fill="x", pady=(0, 4))
        
        headers = ["ID", "Activity", "Duration", "Status", "Actions"]
        for i, header in enumerate(headers):
            label = ttk.Label(header_frame, text=header, style="App.Card.Header.TLabel")
            label.grid(row=0, column=i, padx=10, pady=5, sticky="w")
        
        # Active timers container (place timers horizontally inside scrollable_frame)
        self.active_timers_frame = scrollable_frame
        
        # Configure scrollregion on resize
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    
    def _build_management_ui(self):
        """Build the timer management interface."""
        # Manual timer controls
        manual_frame = ttk.LabelFrame(self.management_frame, text="⏱️ Manual Timer", padding=6, style="App.Card.TLabelframe")
        manual_frame.pack(fill="x", pady=(0, 6))
        
        # Timer selection
        select_frame = ttk.Frame(manual_frame, style="App.Card.TFrame")
        select_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(select_frame, text="Activity:", style="App.Card.TLabel").grid(row=0, column=0, sticky="w", padx=5)
        
        self.activity_var = tk.StringVar()
        self.activity_combo = ttk.Combobox(select_frame, textvariable=self.activity_var, style="App.TCombobox", width=25)
        self.activity_combo.grid(row=0, column=1, padx=5, sticky="ew")
        
        # Populate with available activities
        activities = []
        for event_key, event_data in DEFAULT_TIMER_DURATIONS.items():
            activities.append(f"{event_data['description']} ({event_key})")
        
        self.activity_combo['values'] = sorted(activities)
        
        # Restore last selected activity
        last_activity = self.activity_var.get()
        if last_activity and last_activity in activities:
            self.activity_combo.set(last_activity)
        elif activities:
            self.activity_combo.set(activities[0])
        
        # Custom duration
        ttk.Label(select_frame, text="Duration (seconds):", style="App.Card.TLabel").grid(row=1, column=0, sticky="w", padx=5, pady=(10, 0))
        
        duration_entry = ttk.Entry(select_frame, textvariable=self.duration_var, style="App.TEntry", width=15)
        duration_entry.grid(row=1, column=1, padx=5, pady=(10, 0), sticky="ew")
        
        # Notes
        ttk.Label(select_frame, text="Notes:", style="App.Card.TLabel").grid(row=2, column=0, sticky="w", padx=5, pady=(10, 0))
        
        notes_entry = ttk.Entry(select_frame, textvariable=self.notes_var, style="App.TEntry", width=30)
        notes_entry.grid(row=2, column=1, padx=5, pady=(10, 0), sticky="ew")
        
        # Save selection on change
        self.activity_var.trace_add('write', lambda *args: self._save_timer_selection())
        self.duration_var.trace_add('write', lambda *args: self._save_timer_selection())
        self.notes_var.trace_add('write', lambda *args: self._save_timer_selection())
        
        # Buttons
        button_frame = ttk.Frame(manual_frame, style="App.Card.TFrame")
        button_frame.pack(fill="x", pady=8)
        
        ttk.Button(button_frame, text="▶️ Start Timer", command=self._start_manual_timer, style="App.Primary.TButton").pack(side="left", padx=4)
        ttk.Button(button_frame, text="⏹️ Stop All", command=self._stop_all_timers, style="App.Secondary.TButton").pack(side="left", padx=4)
        ttk.Button(button_frame, text="🗑️ Clear All", command=self._clear_all_timers, style="App.Secondary.TButton").pack(side="left", padx=4)
        
        # Configure grid weights
        select_frame.columnconfigure(1, weight=1)
        
        # Chat monitoring controls
        if self.chat_monitor:
            chat_frame = ttk.LabelFrame(self.management_frame, text="💬 Chat Monitoring", padding=10, style="App.Card.TLabelframe")
            chat_frame.pack(fill="x", pady=(10, 0))
            
            self.auto_start_var = tk.BooleanVar(value=self._get_ui_pref("timer_auto_start", True))
            ttk.Checkbutton(chat_frame, text="Auto-start timers from chat events", variable=self.auto_start_var, style="App.Card.TCheckbutton", command=self._toggle_auto_monitoring).pack(anchor="w")
            
            ttk.Button(chat_frame, text="🔄 Scan Now", command=self._scan_chat_now, style="App.Secondary.TButton").pack(pady=(10, 0), anchor="w")
    
    def _build_history_ui(self):
        """Build the timer history display."""
        # History treeview
        tree_frame = ttk.Frame(self.history_frame, style="App.TFrame")
        tree_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Treeview with scrollbar
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", style="App.Vertical.TScrollbar")
        self.history_tree = ttk.Treeview(tree_frame, 
                                     columns=("time", "activity", "duration", "status"),                                     show="headings", style="App.Treeview",                                     yscrollcommand=tree_scroll.set)
        
        # Configure columns
        self.history_tree.heading("time", text="Time")
        self.history_tree.heading("activity", text="Activity")
        self.history_tree.heading("duration", text="Duration")
        self.history_tree.heading("status", text="Status")
        
        self.history_tree.column("time", width=150, stretch=False)
        self.history_tree.column("activity", width=200, stretch=True)
        self.history_tree.column("duration", width=100, stretch=False)
        self.history_tree.column("status", width=100, stretch=False)
        
        # Pack treeview and scrollbar
        self.history_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        tree_scroll.configure(command=self.history_tree.yview)
        
        # Refresh button
        ttk.Button(self.history_frame, text="🔄 Refresh History", command=self._refresh_history, style="App.Secondary.TButton").pack(pady=10)
    
    def _build_boss_timers_ui(self):
        """Build the boss timers display."""
        # Manual boss timer controls
        manual_frame = ttk.LabelFrame(self.boss_frame, text="👹 Manual Boss Timer", padding=6, style="App.Card.TLabelframe")
        manual_frame.pack(fill="x", pady=(0, 6))
        
        # Boss selection
        select_frame = ttk.Frame(manual_frame, style="App.Card.TFrame")
        select_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(select_frame, text="Boss:", style="App.Card.TLabel").grid(row=0, column=0, sticky="w", padx=5)
        
        self.boss_var = tk.StringVar()
        self.boss_combo = ttk.Combobox(select_frame, textvariable=self.boss_var, style="App.TCombobox", width=30)
        self.boss_combo.grid(row=0, column=1, padx=5, sticky="ew")
        
        # Populate with available bosses
        bosses = []
        for event_key, event_data in DEFAULT_BOSS_DURATIONS.items():
            bosses.append(f"{event_data['description']} ({event_key})")
        
        self.boss_combo['values'] = sorted(bosses)
        
        # Restore last selected boss
        last_boss = self._get_ui_pref("timer_last_boss", "")
        if last_boss and last_boss in bosses:
            self.boss_var.set(last_boss)
        elif bosses:
            self.boss_var.set(bosses[0])
        
        # Custom duration
        ttk.Label(select_frame, text="Duration (seconds):", style="App.Card.TLabel").grid(row=1, column=0, sticky="w", padx=5, pady=(10, 0))
        
        self.boss_duration_var = tk.StringVar()
        duration_entry = ttk.Entry(select_frame, textvariable=self.boss_duration_var, style="App.TEntry", width=15)
        duration_entry.grid(row=1, column=1, padx=5, pady=(10, 0), sticky="ew")
        
        # Restore last boss duration
        last_boss_duration = self._get_ui_pref("timer_last_boss_duration", "")
        if last_boss_duration:
            self.boss_duration_var.set(last_boss_duration)
        
        # Notes
        ttk.Label(select_frame, text="Notes:", style="App.Card.TLabel").grid(row=2, column=0, sticky="w", padx=5, pady=(10, 0))
        
        notes_entry = ttk.Entry(select_frame, textvariable=self.boss_notes_var, style="App.TEntry", width=30)
        notes_entry.grid(row=2, column=1, padx=5, pady=(10, 0), sticky="ew")
        
        # Save selection on change
        self.boss_var.trace_add('write', lambda *args: self._save_boss_selection())
        self.boss_duration_var.trace_add('write', lambda *args: self._save_boss_selection())
        self.boss_notes_var.trace_add('write', lambda *args: self._save_boss_selection())
        
        # Buttons
        button_frame = ttk.Frame(manual_frame, style="App.Card.TFrame")
        button_frame.pack(fill="x", pady=8)
        
        ttk.Button(button_frame, text="👹 Start Boss Timer", command=self._start_boss_timer, style="App.Primary.TButton").pack(side="left", padx=4)
        ttk.Button(button_frame, text="⏹️ Stop Boss Timers", command=self._stop_boss_timers, style="App.Secondary.TButton").pack(side="left", padx=4)
        
        # Active boss timers
        active_frame = ttk.LabelFrame(self.boss_frame, text="🔴 Active Boss Timers", padding=6, style="App.Card.TLabelframe")
        active_frame.pack(fill="both", expand=True, pady=(6, 0))
        
        # Scrollable frame for active boss timers
        canvas = tk.Canvas(active_frame, highlightthickness=0)
        canvas.configure(bg=UI_COLORS["card_bg"])
        scrollbar = ttk.Scrollbar(active_frame, orient="vertical", command=canvas.yview, style="App.Vertical.TScrollbar")
        
        scrollable_frame = ttk.Frame(canvas, style="App.Card.TFrame")
        
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Active boss timers container
        self.active_boss_timers_frame = ttk.Frame(scrollable_frame, style="App.Card.TFrame")
        self.active_boss_timers_frame.pack(fill="both", expand=True)
        
        # Configure scrollregion
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        # Configure grid weights
        select_frame.columnconfigure(1, weight=1)
        
        # Refresh button
        ttk.Button(self.boss_frame, text="🔄 Refresh Boss Timers", command=self._refresh_boss_timers, style="App.Secondary.TButton").pack(pady=10)
    
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
            from timer_db import DEFAULT_BOSS_DURATIONS
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
            timer_id = self.timer_db.start_timer("boss", boss_name, self.boss_notes_var.get())
            
            self.status_var.set(f"Started boss timer: {self.boss_var.get()}")
            self._refresh_timers()
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
            messagebox.showerror("Error" f"Failed to stop boss timers: {e}")
    
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
        frame = ttk.Frame(self.active_boss_timers_frame, style="App.Card.TFrame")
        frame.pack(fill="x", pady=5, padx=10)
        
        # Boss timer info
        info_frame = ttk.Frame(frame, style="App.TFrame")
        info_frame.pack(fill="x", padx=10, pady=10)
        
        # Boss name with special styling
        ttk.Label(info_frame, text=f"👹 {timer['event_name'].title()}", style="App.Card.TLabel").grid(row=0, column=0, sticky="w")
        
        # Duration
        duration_str = self._format_duration(timer['current_duration_seconds'])
        ttk.Label(info_frame, text=f"⏱️ {duration_str}", style="App.Card.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 0))
        
        # Progress bar
        boss_key = f"boss:{timer['event_name']}"
        max_duration = DEFAULT_BOSS_DURATIONS.get(boss_key, {}).get('duration', 900)
        progress_var = tk.DoubleVar(value=min(timer['current_duration_seconds'] / max_duration, 1.0))
        progress_bar = ttk.Progressbar(info_frame, variable=progress_var, maximum=1.0, style="App.Horizontal.TProgressbar", length=200)
        progress_bar.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        
        # Action buttons
        button_frame = ttk.Frame(frame, style="App.TFrame")
        button_frame.pack(fill="x", padx=10, pady=(10, 10))
        
        ttk.Button(button_frame, text="⏹️ Stop Boss", command=lambda: self._stop_boss_timer(timer['id']), style="App.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(button_frame, text="🗑️ Cancel", command=lambda: self._cancel_boss_timer(timer['id']), style="App.Secondary.TButton").pack(side="left", padx=5)
        
        # Store reference and update progress
        if not hasattr(self, 'active_boss_timers'):
            self.active_boss_timers = {}
        
        self.active_boss_timers[timer['id']] = {
            'frame': frame,
            'progress_var': progress_var,
            'start_time': timer['start_time'],
            'max_duration': max_duration
        }
        
        # Start progress update
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
                messagebox.showerror("Error" "Boss timer not found or already stopped.")
        except Exception as e:
            messagebox.showerror("Error" f"Failed to stop boss timer: {e}")
    
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
        """Update progress bar for a boss timer."""
        if not hasattr(self, 'active_boss_timers') or timer_id not in self.active_boss_timers:
            return
        
        timer_data = self.active_boss_timers[timer_id]
        start_time = datetime.fromisoformat(timer_data['start_time'])
        current_duration = int((datetime.now() - start_time).total_seconds())
        
        # Update progress
        progress = min(current_duration / timer_data['max_duration'], 1.0)
        timer_data['progress_var'].set(progress)
        
        # Update duration display
        for widget in timer_data['frame'].winfo_children():
            if isinstance(widget, ttk.Label) and "⏱️" in widget.cget("text"):
                duration_str = self._format_duration(current_duration)
                widget.config(text=f"⏱️ {duration_str}")
        
        # Schedule next update
        try:
            self.window.after(1000, lambda: self._update_boss_timer_progress(timer_id))
        except Exception:
            pass
    def _start_manual_timer(self):
        """Start a manual timer."""
        try:
            # Get selected activity and extract event type
            activity_text = self.activity_var.get()
            if not activity_text:
                messagebox.showerror("Error" "Please select an activity.")
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
            try:
                duration = int(self.duration_var.get()) if self.duration_var.get() else None
                if not duration or duration <= 0:
                    messagebox.showerror("Error", "Please enter a valid duration in seconds.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Duration must be a number.")
                return
            
            # Get event name from event_type
            _event_name = event_type.split(':', 1)
            event_name = _event_name[1] if len(_event_name) > 1 else _event_name[0]
            
            # Start timer
            timer_id = self.timer_db.start_timer(event_type, event_name, self.notes_var.get())
            
            self.status_var.set(f"Started timer: {self.activity_var.get()}")
            self._refresh_timers()
            self._refresh_history()
            
        except Exception as e:
            messagebox.showerror("Error" f"Failed to start timer: {e}")
    
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
            messagebox.showerror("Error" f"Failed to clear timers: {e}")
    
    def _toggle_auto_monitoring(self):
        """Toggle chat monitoring on/off and save preference."""
        if self.auto_start_var.get():
            self.start_chat_monitoring()
        else:
            self.stop_chat_monitoring()
        
        # Save preference
        self._set_ui_pref("timer_auto_start", self.auto_start_var.get())
    
    def _scan_chat_now(self):
        """Manually scan chat logs for events."""
        if not self.chat_monitor:
            messagebox.showwarning("Warning", "Chat monitoring not available.")
            return
        
        try:
            events = self.chat_monitor.scan_chat_logs()
            actions = self.chat_monitor.process_events(events)
            
            for action in actions:
                self.status_var.set(action)
                self._refresh_timers()
                self._refresh_history()
            
            if actions:
                messagebox.showinfo("Scan Complete" f"Processed {len(actions)} events.")
            else:
                messagebox.showinfo("Scan Complete" "No new timer events found.")
                
        except Exception as e:
            messagebox.showerror("Error" f"Failed to scan chat: {e}")
    
    def start_chat_monitoring(self):
        """Start background chat monitoring."""
        if not self.chat_monitor or self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitor_status_var.set("🟢 Chat Monitoring Active")
        
        def monitor_loop():
            while self.monitoring_active:
                try:
                    events = self.chat_monitor.scan_chat_logs()
                    actions = self.chat_monitor.process_events(events)
                    
                    if actions:
                        for action in actions:
                            self.status_var.set(action)
                            self._refresh_timers()
                            self._refresh_history()
                    
                    time.sleep(5)  # Check every 5 seconds
                    
                except Exception as e:
                    print(f"Chat monitoring error: {e}")
                    time.sleep(10)
        
        self.timer_update_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.timer_update_thread.start()
    
    def stop_chat_monitoring(self):
        """Stop chat monitoring."""
        self.monitoring_active = False
        self.monitor_status_var.set("🔴 Chat Monitoring Stopped")
        
        if self.timer_update_thread:
            self.timer_update_thread.join(timeout=2)
    
    def _refresh_timers(self):
        """Refresh the active timers display."""
        # Clear existing timer displays
        for widget in self.active_timers_frame.winfo_children():
            widget.destroy()
        
        # Get active timers
        active_timers = self.timer_db.get_active_timers()
        
        if not active_timers:
            no_timers_label = ttk.Label(self.active_timers_frame 
                                     , text="No active timers" 
                                     , style="App.Muted.TLabel")
            no_timers_label.pack(pady=20)
            return
        
        # Display each active timer
        for i, timer in enumerate(active_timers, 1):
            self._create_timer_display(timer, i)
    
    def _create_timer_display(self, timer, row):
        """Create UI display for a single timer."""
        frame = ttk.Frame(self.active_timers_frame, style="App.Card.TFrame")
        # Place timers horizontally so many can fit in one line
        frame.pack(side="left", padx=8, pady=8)
        frame.pack_propagate(False)
        frame.configure(width=260)
        
        # Timer info
        info_frame = ttk.Frame(frame, style="App.TFrame")
        info_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # ID and Activity
        ttk.Label(info_frame, text=f"#{timer['id']}", style="App.Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, text=timer['event_name'], style="App.Card.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        
        # Duration
        duration_str = self._format_duration(timer['current_duration_seconds'])
        ttk.Label(info_frame, text=f"⏱️ {duration_str}", style="App.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))
        
        # Progress bar
        progress_var = tk.DoubleVar(value=min(timer['current_duration_seconds'] / 300, 1.0))  # Assume 5 min max
        progress_bar = ttk.Progressbar(info_frame, variable=progress_var, maximum=1.0, style="App.Horizontal.TProgressbar", length=200)
        progress_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        
        # Action buttons
        button_frame = ttk.Frame(frame, style="App.TFrame")
        button_frame.pack(fill="x", padx=10, pady=(10, 10))
        
        ttk.Button(button_frame, text="⏹️ Stop", command=lambda: self._stop_timer(timer['id']), style="App.Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(button_frame, text="🗑️ Cancel", command=lambda: self._cancel_timer(timer['id']), style="App.Secondary.TButton").pack(side="left", padx=5)
        
        # Store reference and update progress
        self.active_timers[timer['id']] = {
            'frame': frame,
            'progress_var': progress_var,
            'start_time': timer['start_time'],
            'max_duration': 300
        }
        
        # Start progress update
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
        """Update progress bar for a timer."""
        if timer_id not in self.active_timers or not self.monitoring_active:
            return
        
        timer_data = self.active_timers[timer_id]
        start_time = datetime.fromisoformat(timer_data['start_time'])
        current_duration = int((datetime.now() - start_time).total_seconds())
        
        # Update progress (assuming 5 minutes = 100% for most activities)
        progress = min(current_duration / 300, 1.0)
        timer_data['progress_var'].set(progress)
        
        # Update duration display
        for widget in timer_data['frame'].winfo_children():
            if isinstance(widget, ttk.Label) and "⏱️" in widget.cget("text"):
                duration_str = self._format_duration(current_duration)
                widget.config(text=f"⏱️ {duration_str}")
                break
        
        # Schedule next update
        if self.monitoring_active:
            self.window.after(1000, lambda: self._update_timer_progress(timer_id))
    
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
            
            # Apply the saved geometry directly
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
