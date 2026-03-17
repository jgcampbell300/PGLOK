import json
import re
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from datetime import datetime

import src.config.config as config
from src import __version__
from src.chat.monitor import ChatLogMonitor
from src.config.ui_theme import UI_ATTRS, UI_TEXT, UI_COLORS, apply_theme, configure_menu_theme
from src.data_acquisition import main as run_data_acquisition
from src.data_index import fetch_rows, get_db_path, index_data_dir, list_indexed_files
from src.itemizer import get_filter_values as itemizer_get_filter_values
from src.itemizer import index_item_reports, search_item_totals, search_items
from src.locate_PG import initialize_pg_base
from src.maptools import MapToolsBrowser
from src.utils.spellcheck import EntrySpellcheckBinder
from src.updater import perform_auto_update
import sys

# Import database manager
from src.database.database_manager import get_database_manager

# Import base addon
sys.path.insert(0, str(Path(__file__).parent.parent / "addons"))
from base_addon import BaseAddon


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


class PGLOKApp:
    def __init__(self, root):
        self.root = root
        self._resize_after_id = None
        self._data_browser_resize_after_id = None
        self._itemizer_resize_after_id = None
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
        self.chat_polling = False
        self.chat_after_id = None
        self.chat_text = None
        self.chat_notebook = None
        self.chat_tab_text = {}
        self.chat_info_var = tk.StringVar(value="Lines: 0    Date: --    Time: --    File: None")
        self.chat_lines_seen = 0
        self.character_count_var = tk.StringVar(value="Characters Loaded: 0")
        self.path_vars = {label: tk.StringVar() for label in UI_TEXT["path_labels"]}
        self.status_var = tk.StringVar(value=UI_TEXT["status_ready"])
        self.global_search_var = tk.StringVar(value=str(self._get_ui_pref("global_search_query", "")))
        self.global_search_results_tree = None
        self.global_search_detail_text = None
        self.global_search_paned = None
        self.global_search_results = []
        self._global_search_after_id = None
        self.alpha_button = None
        self.entry_spellcheck = EntrySpellcheckBinder()
        
        # Timer configuration variables
        self.timer_auto_start_var = tk.BooleanVar(value=self._get_ui_pref("timer_auto_start", True))
        self.timer_scan_interval_var = tk.IntVar(value=self._get_ui_pref("timer_scan_interval", 5))
        self.timer_notification_var = tk.BooleanVar(value=self._get_ui_pref("timer_notifications", True))
        
        # Addon manager will be initialized lazily
        self.addon_manager = None
        self.addons_menu = None

        apply_theme(self.root)
        self.root.title(UI_ATTRS["window_title"])
        self.data_search_var.trace_add("write", lambda *_: self._schedule_data_live_search())
        self.itemizer_search_var.trace_add("write", lambda *_: self._schedule_itemizer_live_search())

        self.app_frame = ttk.Frame(root, padding=(4, 2, 4, 4), style="App.Panel.TFrame")
        self.app_frame.pack(fill="both", expand=True)

        self._build_layout()
        self._build_menu_bar()
        self._apply_startup_geometry()
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh_config_view()
        self._restore_always_on_top_state()
        self.show_page("home")
        self._refresh_character_cache()
        self._restore_open_windows()
        self.root.after(150, self._raise_main_window_default)
        self._check_for_upgrade_async()
        if config.PG_BASE is None:
            self.locate_pg()

    def _build_layout(self):
        # Create main paned window for resizable layout
        self.main_paned = ttk.PanedWindow(self.app_frame, orient="vertical", style="App.TFrame")
        self.main_paned.pack(fill="both", expand=True)
        
        # Top section for toolbar and content
        self.top_section = ttk.Frame(self.main_paned, style="App.TFrame")
        self.main_paned.add(self.top_section, weight=1)
        
        # Toolbar
        toolbar = ttk.Frame(self.top_section, style="App.Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 3))
        ttk.Button(toolbar, text="Chat", command=self._open_chat, style="App.Secondary.TButton").pack(side="left")
        ttk.Button(
            toolbar,
            text="Characters",
            command=self.open_character_browser_window,
            style="App.Secondary.TButton",
        ).pack(side="left", padx=(3, 0))
        ttk.Button(toolbar, text="Data", command=self.open_data_browser_window, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )
        ttk.Button(toolbar, text="Itemizer", command=self.open_itemizer_window, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )
        ttk.Button(toolbar, text="Maps", command=self.open_map_tools_window, style="App.Secondary.TButton").pack(
            side="left", padx=(3, 0)
        )
        ttk.Button(toolbar, text="Planner", command=self._open_planner, style="App.Secondary.TButton").pack(side="left", padx=(3, 0))
        self.pin_button = ttk.Button(toolbar, text="PIN: OFF", command=self._toggle_always_on_top, style="App.Primary.TButton")
        self.pin_button.pack(side="left", padx=(3, 0))

        self.alpha_button = ttk.Button(
            toolbar,
            text=f"ALPHA v{__version__}",
            command=lambda: webbrowser.open(REPO_URL),
            style="App.Secondary.TButton",
        )
        self.alpha_button.pack(side="right")

        # Content area
        self.page_container = ttk.Frame(self.top_section, style="App.Panel.TFrame")
        self.page_container.pack(fill="both", expand=True)

        self.home_page = ttk.Frame(self.page_container, style="App.Panel.TFrame")
        self._build_home_page()

        # Status bar section (always visible, not resizable)
        self.status_section = ttk.Frame(self.main_paned, style="App.Panel.TFrame")
        self.main_paned.add(self.status_section, weight=0)  # Weight 0 means it won't resize
        
        # Create persistent status bar
        self._create_status_bar()
        
        # Configure paned window - let it handle sizing naturally
        # The weight=0 on status section should keep it small

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
        
        # Center status - additional info (expands)
        self.center_status = ttk.Frame(status_row, style="App.Panel.TFrame")
        self.center_status.grid(row=0, column=1, sticky="we")
        self.center_info_var = tk.StringVar(value="")
        ttk.Label(self.center_status, textvariable=self.center_info_var, style="App.Muted.TLabel").pack(side="left")
        
        # Right status - character count
        right_status = ttk.Frame(status_row, style="App.Panel.TFrame")
        right_status.grid(row=0, column=2, sticky="e")
        ttk.Label(right_status, textvariable=self.character_count_var, style="App.Status.TLabel").pack(side="left")
        
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
        tools_menu.add_command(label="Locate Project Gorgon", command=self.locate_pg)
        tools_menu.add_command(label="Download Newer Files", command=self.download_newer_files)
        tools_menu.add_command(label="Character Browser", command=self.open_character_browser_window)
        tools_menu.add_command(label="Data Browser", command=self.open_data_browser_window)
        tools_menu.add_separator()
        tools_menu.add_command(label="Map Tools", command=self.open_map_tools_window)
        tools_menu.add_separator()
        tools_menu.add_command(label="Fletcher", command=self._open_fletcher)
        tools_menu.add_command(label="Itemizer", command=self._open_itemizer)
        tools_menu.add_command(label="Planner", command=self._open_planner)
        tools_menu.add_command(label="Timer", command=self._open_timer)
        tools_menu.add_command(label="Chat", command=self._open_chat)
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
        from tkinter import messagebox
        import threading
        
        # Create progress dialog
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Checking for Updates")
        progress_window.geometry("500x300")
        progress_window.resizable(False, False)
        progress_window.transient(self.root)
        progress_window.grab_set()
        
        # Center the dialog
        progress_window.update_idletasks()
        x = (progress_window.winfo_screenwidth() // 2) - (500 // 2)
        y = (progress_window.winfo_screenheight() // 2) - (300 // 2)
        progress_window.geometry(f"500x300+{x}+{y}")
        
        # Apply theme
        main_frame = ttk.Frame(progress_window, style="App.Card.TFrame", padding=20)
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="PGLOK Update", style="App.Title.TLabel")
        title_label.pack(pady=(0, 15))
        
        # Status text
        status_var = tk.StringVar(value="Checking for updates...")
        status_label = ttk.Label(main_frame, textvariable=status_var, style="App.Status.TLabel")
        status_label.pack(pady=10, anchor="w")
        
        # Progress bar
        progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(main_frame, variable=progress_var, mode="indeterminate", style="App.Horizontal.TProgressbar")
        progress_bar.pack(fill="x", pady=10)
        progress_bar.start(10)
        
        # Details text
        details_text = tk.Text(main_frame, height=8, wrap="word", bg=UI_COLORS["entry_bg"], fg=UI_COLORS["text"], 
                              borderwidth=1, relief="solid", highlightthickness=1,
                              highlightbackground=UI_COLORS["entry_border"], highlightcolor=UI_COLORS["accent"])
        details_scroll = ttk.Scrollbar(main_frame, orient="vertical", command=details_text.yview, style="App.Vertical.TScrollbar")
        details_text.configure(yscrollcommand=details_scroll.set)
        
        details_frame = ttk.Frame(main_frame)
        details_frame.pack(fill="both", expand=True, pady=10)
        details_text.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")
        
        # Close button (initially disabled)
        close_var = tk.BooleanVar(value=False)
        close_button = ttk.Button(main_frame, text="Close", command=progress_window.destroy, state="disabled", style="App.Primary.TButton")
        close_button.pack(pady=(10, 0))
        
        def update_status(message):
            """Update status message and details."""
            status_var.set(message)
            details_text.insert(tk.END, f"[{self._get_timestamp()}] {message}\n")
            details_text.see(tk.END)
            progress_window.update_idletasks()
        
        def update_progress(value):
            """Update progress bar."""
            progress_var.set(value)
            progress_window.update_idletasks()
        
        def enable_close():
            """Enable close button and stop progress."""
            progress_bar.stop()
            close_button.configure(state="normal")
            close_var.set(True)
        
        def worker():
            """Update worker thread."""
            try:
                update_status("Checking for updates...")
                update_progress(10)
                
                from src.updater import fetch_latest_repo_version, parse_version_key
                
                latest_version, assets = fetch_latest_repo_version()
                update_progress(30)
                
                if not latest_version:
                    update_status("Unable to check for updates")
                    details_text.insert(tk.END, "\nCould not connect to GitHub to check for updates.\n")
                    details_text.insert(tk.END, "Please check your internet connection and try again.\n")
                    enable_close()
                    return
                
                current_key = parse_version_key(__version__)
                latest_key = parse_version_key(latest_version)
                
                update_progress(50)
                update_status(f"Current version: {__version__}")
                update_status(f"Latest version: {latest_version}")
                
                if current_key is None or latest_key is None or latest_key <= current_key:
                    update_status("PGLOK is up to date!")
                    details_text.insert(tk.END, f"\nYou are running the latest version ({__version__}).\n")
                    update_progress(100)
                    enable_close()
                    return
                
                update_status(f"Update available: {__version__} → {latest_version}")
                update_progress(70)
                
                # Count assets
                if assets:
                    details_text.insert(tk.END, f"\nAvailable release assets:\n")
                    for i, asset in enumerate(assets, 1):
                        size_mb = asset.get('size', 0) / (1024*1024)
                        details_text.insert(tk.END, f"  {i}. {asset['name']} ({size_mb:.1f}MB)\n")
                
                update_status("Downloading update...")
                update_progress(80)
                
                from src.updater import perform_auto_update
                update_success = perform_auto_update(__version__)
                
                update_progress(90)
                
                if update_success:
                    update_status("Update completed successfully!")
                    details_text.insert(tk.END, "\n✅ Update has been installed successfully.\n")
                    details_text.insert(tk.END, "The application will restart to apply the update.\n")
                    update_progress(100)
                    enable_close()
                    
                    def restart_after_delay():
                        progress_window.destroy()
                        self._restart_application()
                    
                    progress_window.after(3000, restart_after_delay)
                else:
                    update_status("Update failed")
                    details_text.insert(tk.END, "\n❌ Automatic update failed.\n")
                    details_text.insert(tk.END, "You can download the update manually from:\n")
                    details_text.insert(tk.END, "https://github.com/jgcampbell300/PGLOK/releases/latest\n")
                    enable_close()
                
            except Exception as exc:
                update_status(f"Update check failed: {exc}")
                details_text.insert(tk.END, f"\n❌ Error: {exc}\n")
                details_text.insert(tk.END, "Please try again or check your internet connection.\n")
                enable_close()
        
        # Start update check in background thread
        threading.Thread(target=worker, daemon=True).start()
        
        # Handle window close
        def on_close():
            if close_var.get():
                progress_window.destroy()
        
        progress_window.protocol("WM_DELETE_WINDOW", on_close)
    
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
        def worker():
            try:
                # Perform automatic update
                update_success = perform_auto_update(__version__)
                
                def apply_result():
                    if update_success:
                        # Show success message and restart
                        messagebox.showinfo(
                            "Update Complete", 
                            f"PGLOK has been updated successfully!\n\nThe application will restart to apply the update."
                        )
                        self.root.after(1000, self._restart_application)
                    else:
                        # Check if update is available but auto-install failed
                        from src.updater import fetch_latest_repo_version, parse_version_key
                        
                        latest_version, _ = fetch_latest_repo_version()
                        if latest_version:
                            current_key = parse_version_key(__version__)
                            latest_key = parse_version_key(latest_version)
                            
                            if current_key and latest_key and latest_key > current_key:
                                def apply_upgrade_state():
                                    if self.alpha_button is None:
                                        return
                                    self.alpha_button.configure(
                                        text="Update Available!", 
                                        command=lambda: webbrowser.open(RELEASES_URL)
                                    )
                                    self.status_var.set(f"Update available: {__version__} → {latest_version}")
                                
                                self.root.after(0, apply_upgrade_state)
                            else:
                                self.status_var.set("PGLOK is up to date")
                        else:
                            self.status_var.set("Unable to check for updates")

                self.root.after(0, apply_result)
                
            except Exception as exc:
                def show_error():
                    self.status_var.set(f"Update check failed: {exc}")
                self.root.after(0, show_error)

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

    def _open_config_folder(self):
        """Open the PGLOK config folder."""
        try:
            import subprocess
            import platform
            system = platform.system()
            folder_path = str(config.CONFIG_DIR)
            
            if system == "Windows":
                subprocess.run(["explorer", folder_path])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
            
            self.status_var.set(f"Opened config folder: {folder_path}")
        except Exception as e:
            self.status_var.set(f"Error opening config folder: {e}")

    def _open_data_folder(self):
        """Open the PGLOK data folder."""
        try:
            import subprocess
            import platform
            system = platform.system()
            folder_path = str(config.DATA_DIR)
            
            if system == "Windows":
                subprocess.run(["explorer", folder_path])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
            
            self.status_var.set(f"Opened data folder: {folder_path}")
        except Exception as e:
            self.status_var.set(f"Error opening data folder: {e}")

    def _open_maps_folder(self):
        """Open the PGLOK maps folder."""
        try:
            import subprocess
            import platform
            system = platform.system()
            folder_path = config.DATA_DIR / "maps"  # Keep as Path object
            
            # Create maps folder if it doesn't exist
            if not folder_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)
            
            folder_path_str = str(folder_path)  # Convert to string only for subprocess
            
            if system == "Windows":
                subprocess.run(["explorer", folder_path_str])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path_str])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path_str])
            
            self.status_var.set(f"Opened maps folder: {folder_path_str}")
        except Exception as e:
            self.status_var.set(f"Error opening maps folder: {e}")

    def _open_chat_logs_folder(self):
        """Open the PGLOK chat logs folder."""
        try:
            import subprocess
            import platform
            system = platform.system()
            
            if config.PG_BASE is None:
                initialize_pg_base(force=True)
            
            if config.PG_BASE is None:
                self.status_var.set("Project Gorgon not located - cannot open chat logs")
                return
            
            folder_path = str(config.CHAT_DIR)
            
            if system == "Windows":
                subprocess.run(["explorer", folder_path])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
            
            self.status_var.set(f"Opened chat logs folder: {folder_path}")
        except Exception as e:
            self.status_var.set(f"Error opening chat logs folder: {e}")

    def _open_reports_folder(self):
        """Open the PGLOK reports folder."""
        try:
            import subprocess
            import platform
            system = platform.system()
            
            reports_dir = self._get_reports_dir()
            if reports_dir is None:
                self.status_var.set("Project Gorgon not located - cannot open reports")
                return
            
            folder_path = str(reports_dir)
            
            if system == "Windows":
                subprocess.run(["explorer", folder_path])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
            
            self.status_var.set(f"Opened reports folder: {folder_path}")
        except Exception as e:
            self.status_var.set(f"Error opening reports folder: {e}")

    def _open_fletcher(self):
        self.status_var.set("Fletcher is not implemented yet.")

    def _open_itemizer(self):
        self.open_itemizer_window()

    def _open_planner(self):
        self.status_var.set("Planner is not implemented yet.")

    def _open_timer(self):
        """Open the timer window."""
        try:
            from src.timer_window import TimerWindow
            from pathlib import Path
            
            # Get chat directory if available
            chat_dir = None
            if config.PG_BASE is not None:
                chat_dir = Path(config.PG_BASE) / "ChatLogs"
                if chat_dir.exists():
                    chat_dir = chat_dir
            
            # Create and show timer window
            timer_window = TimerWindow(self, config.DATA_DIR, chat_dir)
            self.status_var.set("Timer window opened")
            
        except Exception as e:
            self.status_var.set(f"Error opening timer: {e}")
            import traceback
            traceback.print_exc()

    def _open_chat(self):
        self.open_chat_window()
    
    def _open_duration_manager(self):
        """Open the duration manager window."""
        self.status_var.set("Duration manager not implemented yet.")
    
    def _save_timer_settings(self):
        """Save timer settings to preferences."""
        try:
            self._set_ui_pref("timer_auto_start", self.timer_auto_start_var.get())
            self._set_ui_pref("timer_scan_interval", self.timer_scan_interval_var.get())
            self._set_ui_pref("timer_notifications", self.timer_notification_var.get())
            self.status_var.set("Timer settings saved")
        except Exception as e:
            self.status_var.set(f"Error saving timer settings: {e}")
    
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
        """Create a Toplevel with the PGLOK theme and standard title.

        name: identifier used by caller for saved geometry keys (for callers' use).
        title_suffix: displayed after the app title.
        on_close: optional callable to set as WM_DELETE_WINDOW handler.
        """
        win = tk.Toplevel(self.root)
        win.title(f"{UI_ATTRS['window_title']} - {title_suffix}")
        # Apply central theme (sets icon and styles)
        apply_theme(win)
        if on_close:
            try:
                win.protocol("WM_DELETE_WINDOW", on_close)
            except Exception:
                # Fall back to a simple destroy
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

        self.map_tools_window = self.create_themed_toplevel("map_tools", "Map Tools", on_close=self._on_close_map_tools_window)

        shell = ttk.Frame(self.map_tools_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        browser = MapToolsBrowser(
            shell,
            maps_dir=config.DATA_DIR / "maps",
            status_callback=self.status_var.set,
            selected_map=self._get_ui_pref("map_tools_last_map", ""),
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

        info = ttk.Frame(shell, style="App.Card.TFrame", padding=10)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, textvariable=self.chat_info_var, style="App.Status.TLabel").pack(anchor="w")

        output_wrap = ttk.Frame(shell, style="App.Card.TFrame", padding=8)
        output_wrap.pack(fill="both", expand=True)
        self.chat_notebook = ttk.Notebook(output_wrap)
        self.chat_notebook.pack(fill="both", expand=True)
        self.chat_tab_text = {}
        self._ensure_chat_tab("All")

        self.chat_window.update_idletasks()
        req_w = max(920, self.chat_window.winfo_reqwidth())
        req_h = max(520, self.chat_window.winfo_reqheight())
        self._apply_saved_window_geometry("chat_monitor", self.chat_window, req_w, req_h)
        self.chat_window.minsize(req_w, req_h)
        self._set_window_open_state("chat_monitor", True)

        self._start_chat_monitor()

    def _on_close_chat_window(self):
        self._stop_chat_monitor()
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self._save_window_geometry("chat_monitor", self.chat_window)
            self.chat_window.destroy()
        self._set_window_open_state("chat_monitor", False)
        self.chat_window = None
        self.chat_text = None
        self.chat_notebook = None
        self.chat_tab_text = {}

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

    def _stop_chat_monitor(self):
        self.chat_polling = False
        if self.chat_after_id is not None:
            try:
                self.root.after_cancel(self.chat_after_id)
            except tk.TclError:
                pass
            self.chat_after_id = None
        self.status_var.set("Chat monitor stopped.")

    def _clear_chat_output(self):
        self.chat_lines_seen = 0
        for widget in self.chat_tab_text.values():
            widget.delete("1.0", tk.END)
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
            if lines and self.chat_notebook is not None:
                for line in lines:
                    channel = self._extract_chat_channel(line)
                    
                    # Combine Status and Error channels into System tab
                    if channel in ["Status", "Error"]:
                        combined_channel = "System"
                    else:
                        combined_channel = channel
                    
                    self._append_chat_line("All", line)
                    self._append_chat_line(combined_channel, line)
                self.chat_lines_seen += len(lines)
            self._update_chat_info(current_file)
        except Exception as exc:
            self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}")

        self.chat_after_id = self.root.after(500, self._chat_poll_tick)

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

    def _ensure_chat_tab(self, name):
        if self.chat_notebook is None:
            return None
        if name in self.chat_tab_text:
            return self.chat_tab_text[name]

        tab_frame = ttk.Frame(self.chat_notebook, style="App.Card.TFrame")
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
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=text.yview)
        self.chat_notebook.add(tab_frame, text=name)
        self.chat_tab_text[name] = text
        return text

    def _append_chat_line(self, tab_name, line):
        text = self._ensure_chat_tab(tab_name)
        if text is None:
            return
        text.insert(tk.END, line + "\n")
        text.see(tk.END)
        self._trim_chat_widget(text)

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
        new_state = not bool(self.always_on_top_var.get())
        self.always_on_top_var.set(new_state)
        self.root.attributes("-topmost", new_state)
        if self.pin_button is not None:
            self.pin_button.configure(text="PIN: ON" if new_state else "PIN: OFF")
        self._set_ui_pref("always_on_top", new_state)

    def _restore_always_on_top_state(self):
        value = bool(self._get_ui_pref("always_on_top", False))
        self.always_on_top_var.set(value)
        self.root.attributes("-topmost", value)
        if self.pin_button is not None:
            self.pin_button.configure(text="PIN: ON" if value else "PIN: OFF")

    def _build_home_page(self):
        self.home_paned = None
        search_card = ttk.Frame(self.home_page, padding=8, style="App.Card.TFrame")
        search_card.pack(fill="both", expand=True)

        ttk.Label(search_card, text="Global Search", style="App.Header.TLabel").pack(anchor="w")

        search_row = ttk.Frame(search_card, style="App.Card.TFrame")
        search_row.pack(fill="x", pady=(4, 4))
        search_entry = ttk.Entry(search_row, textvariable=self.global_search_var, style="App.TEntry")
        search_entry.pack(side="left", fill="x", expand=True)
        self.entry_spellcheck.register(search_entry)
        search_entry.bind("<Return>", lambda _e: self._start_global_search())
        search_entry.bind("<Button-1>", lambda _e: self._select_all_text(search_entry))
        ttk.Button(
            search_row,
            text="Search",
            command=self._start_global_search,
            style="App.Primary.TButton",
        ).pack(side="left", padx=(6, 4))
        ttk.Button(
            search_row,
            text="Reset",
            command=self._reset_global_search,
            style="App.Secondary.TButton",
        ).pack(side="left")

        results_wrap = ttk.Frame(search_card, style="App.Card.TFrame")
        results_wrap.pack(fill="both", expand=True)

        self.global_search_paned = ttk.Panedwindow(results_wrap, orient="vertical", style="App.TPanedwindow")
        self.global_search_paned.pack(fill="both", expand=True)
        self.global_search_paned.bind("<ButtonRelease-1>", self._on_global_search_pane_resize)
        results_top = ttk.Frame(self.global_search_paned, style="App.Card.TFrame")
        results_bottom = ttk.Frame(self.global_search_paned, style="App.Card.TFrame")
        self.global_search_paned.add(results_top, weight=3)
        self.global_search_paned.add(results_bottom, weight=2)
        try:
            self.global_search_paned.pane(results_top, minsize=90)
            self.global_search_paned.pane(results_bottom, minsize=90)
        except tk.TclError:
            pass

        results_tree_wrap = ttk.Frame(results_top, style="App.Card.TFrame")
        results_tree_wrap.pack(fill="both", expand=True)
        results_tree_scroll = ttk.Scrollbar(results_tree_wrap, orient="vertical", style="App.Vertical.TScrollbar")
        results_tree_scroll.pack(side="right", fill="y")
        self.global_search_results_tree = ttk.Treeview(
            results_tree_wrap,
            columns=("source", "title", "location"),
            show="headings",
            height=7,
            style="App.Treeview",
            yscrollcommand=results_tree_scroll.set,
        )
        self.global_search_results_tree.heading("source", text="Source")
        self.global_search_results_tree.heading("title", text="Found")
        self.global_search_results_tree.heading("location", text="Where")
        self.global_search_results_tree.column("source", width=120, stretch=False)
        self.global_search_results_tree.column("title", width=260, stretch=False)
        self.global_search_results_tree.column("location", width=520, stretch=True)
        self.global_search_results_tree.pack(side="left", fill="both", expand=True)
        results_tree_scroll.configure(command=self.global_search_results_tree.yview)
        self.global_search_results_tree.bind("<<TreeviewSelect>>", self._on_global_search_select)

        detail_wrap = ttk.Frame(results_bottom, style="App.Card.TFrame")
        detail_wrap.pack(fill="both", expand=True, pady=(4, 0))
        detail_scroll = ttk.Scrollbar(detail_wrap, orient="vertical", style="App.Vertical.TScrollbar")
        detail_scroll.pack(side="right", fill="y")
        self.global_search_detail_text = tk.Text(
            detail_wrap,
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
            yscrollcommand=detail_scroll.set,
        )
        self.global_search_detail_text.pack(side="left", fill="both", expand=True)
        detail_scroll.configure(command=self.global_search_detail_text.yview)
        self._set_global_search_detail("")
        self.root.after(120, self._restore_global_search_split)
        self.root.after(140, self._restore_global_search_state)
        self._ensure_home_layout_visible()

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
                self.root.after(0, lambda: self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}"))

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

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title(f"{UI_ATTRS['window_title']} - Settings")
        self.settings_window.configure(bg=self.root.cget("bg"))
        self.settings_window.protocol("WM_DELETE_WINDOW", self._on_close_settings_window)

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
        ttk.Button(header, text="Refresh Index", command=self._refresh_data_index_async, style="Data.Primary.TButton").pack(
            side="right"
        )

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
        header.columnconfigure(2, weight=1)
        ttk.Label(header, text="Itemizer", style="App.Header.TLabel").grid(row=0, column=1)
        ttk.Button(header, text="Refresh Index", command=self._refresh_itemizer_index_async, style="App.Primary.TButton").grid(
            row=0, column=2, sticky="e"
        )

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
                    if result.get('cleaned_reports', 0) > 0:
                        status_msg += f" {result['cleaned_reports']} orphaned reports removed."
                    if result.get('cleaned_items', 0) > 0:
                        status_msg += f" {result['cleaned_items']} orphaned items removed."
                    
                    self.status_var.set(status_msg)

                self.root.after(0, update_ui)
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}"))

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
                tags=(row["raw_json"],),
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
        payload = self.itemizer_tree.item(selection[0], "tags")[0]
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
                self.root.after(0, lambda: self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}"))

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
        for page in (self.home_page,):
            page.pack_forget()
        self.home_page.pack(fill="both", expand=True)

    def _apply_startup_geometry(self):
        self.root.update_idletasks()
        req_w = max(int(self.root.winfo_reqwidth()), MAIN_MIN_WIDTH)
        req_h = max(int(self.root.winfo_reqheight()), MAIN_MIN_HEIGHT)
        states = self._load_all_window_states()
        if "main" in states:
            # Use fixed minimums so the window remains user-resizable.
            self._apply_saved_window_geometry("main", self.root, MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT)
        else:
            screen_w = max(640, int(self.root.winfo_screenwidth()))
            screen_h = max(480, int(self.root.winfo_screenheight()))
            max_w = max(480, screen_w - 80)
            max_h = max(320, screen_h - 100)
            width = min(req_w, max_w)
            height = min(req_h, max_h)
            self.root.geometry(f"{width}x{height}")
        self.root.minsize(MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT)
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
        if self._is_window_marked_open("chat_monitor"):
            self.open_chat_window()
        if self._is_window_marked_open("map_tools"):
            self.open_map_tools_window()

    def _raise_main_window_default(self):
        try:
            self.root.lift()
            self.root.focus_set()
        except tk.TclError:
            pass

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
        screen_w = max(640, int(window.winfo_screenwidth()))
        screen_h = max(480, int(window.winfo_screenheight()))
        max_w = max(480, screen_w - 80)
        max_h = max(320, screen_h - 100)
        base_w = max(320, min(int(min_width), max_w))
        base_h = max(240, min(int(min_height), max_h))

        states = self._load_all_window_states()
        state = states.get(key)
        if state and "width" in state and "height" in state:
            width = max(base_w, int(state["width"]))
            height = max(base_h, int(state["height"]))
            width = min(width, max_w)
            height = min(height, max_h)
            if "x" in state and "y" in state:
                max_x = max(0, screen_w - width)
                max_y = max(0, screen_h - height)
                x = min(max(int(state["x"]), 0), max_x)
                y = min(max(int(state["y"]), 0), max_y)
                window.geometry(f"{width}x{height}+{x}+{y}")
            else:
                window.geometry(f"{width}x{height}")
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
        self._set_window_open_state("chat_monitor", self.chat_window is not None and self.chat_window.winfo_exists())
        self._set_window_open_state("map_tools", self.map_tools_window is not None and self.map_tools_window.winfo_exists())
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
        self._save_window_geometry("chat_monitor", self.chat_window)
        self._save_window_geometry("map_tools", self.map_tools_window)
        self._stop_chat_monitor()
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
        def runner():
            try:
                self.root.after(0, lambda: self.set_busy(True, busy_message))
                task()
                self.root.after(0, lambda: self.set_busy(False, done_message))
                self.root.after(0, self.refresh_config_view)
                if ui_after is not None:
                    self.root.after(0, ui_after)
            except Exception as exc:
                self.root.after(0, lambda: self.set_busy(False, f"{UI_TEXT['status_error_prefix']}{exc}"))

        threading.Thread(target=runner, daemon=True).start()

    def locate_pg(self):
        self.run_in_background(
            task=lambda: initialize_pg_base(force=True),
            busy_message=UI_TEXT["status_locating"],
            done_message=UI_TEXT["status_ready"],
            ui_after=self._refresh_character_cache,
        )

    def download_newer_files(self):
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
    root = tk.Tk()
    app = PGLOKApp(root)
    root.app = app
    root.mainloop()


if __name__ == "__main__":
    main()
