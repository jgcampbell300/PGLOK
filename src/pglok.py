import json
import re
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from datetime import datetime

import src.config.config as config
from src.chat.monitor import ChatLogMonitor
from src.config.ui_theme import UI_ATTRS, UI_TEXT, UI_COLORS, apply_theme
from src.data_acquisition import main as run_data_acquisition
from src.data_index import fetch_rows, get_db_path, index_data_dir, list_indexed_files
from src.locate_PG import initialize_pg_base


WINDOW_STATE_FILE = config.CONFIG_DIR / "ui_window_state.json"
GEOMETRY_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)$")
CHARACTER_FILE_RE = re.compile(r"^Character_(?P<name>.+)_(?P<server>[^_]+)\.json$")
CHAT_CHANNEL_RE = re.compile(r"\[(?P<channel>[^\]]+)\]")


class PGLOKApp:
    def __init__(self, root):
        self.root = root
        self._resize_after_id = None
        self._window_state_ready = False
        self.settings_window = None
        self.data_browser_window = None
        self.character_browser_window = None
        self.chat_window = None
        self.locate_button = None
        self.download_button = None
        self.reset_button = None
        self.data_file_listbox = None
        self.data_rows_tree = None
        self.data_json_text = None
        self.data_search_var = tk.StringVar()
        self.data_page_var = tk.StringVar(value="Page 1")
        self.data_selected_filename = None
        self.data_page_size = 200
        self.data_offset = 0
        self.data_total_rows = 0
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

        apply_theme(self.root)
        self.root.title(UI_ATTRS["window_title"])

        self.app_frame = ttk.Frame(root, padding=UI_ATTRS["container_padding"], style="App.Panel.TFrame")
        self.app_frame.pack(fill="both", expand=True)

        self._build_layout()
        self._build_menu_bar()
        self._apply_startup_geometry()
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh_config_view()
        self._restore_always_on_top_state()
        self.show_page("home")
        self._restore_open_windows()
        self.root.after(150, self._raise_main_window_default)
        if config.PG_BASE is None:
            self.locate_pg()

    def _build_layout(self):
        toolbar = ttk.Frame(self.app_frame, padding=8, style="App.Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Main Toolbar", style="App.Header.TLabel").pack(side="left")
        self.pin_button = ttk.Button(toolbar, text="PIN: OFF", command=self._toggle_always_on_top, style="App.Primary.TButton")
        self.pin_button.pack(side="right")
        ttk.Button(toolbar, text="Chat", command=self._open_chat, style="App.Secondary.TButton").pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Planner", command=self._open_planner, style="App.Secondary.TButton").pack(side="right", padx=(6, 0))
        ttk.Button(
            toolbar,
            text="Characters",
            command=self.open_character_browser_window,
            style="App.Secondary.TButton",
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            toolbar,
            text="Data",
            command=self.open_data_browser_window,
            style="App.Secondary.TButton",
        ).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Settings", command=self.open_settings_window, style="App.Secondary.TButton").pack(
            side="right", padx=(6, 0)
        )

        header = ttk.Frame(self.app_frame, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(2, 10))

        title_column = ttk.Frame(header, style="App.Panel.TFrame")
        title_column.pack(side="left", fill="x", expand=True)
        ttk.Label(title_column, text=UI_ATTRS["window_title"], style="App.Header.TLabel").pack(anchor="w")
        ttk.Label(
            title_column,
            text="Project Gorgon companion tools",
            style="App.Status.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        badge = tk.Label(
            header,
            text="ALPHA",
            bg=UI_COLORS["secondary"],
            fg=UI_COLORS["text"],
            padx=10,
            pady=4,
        )
        badge.pack(side="right")

        self.page_container = ttk.Frame(self.app_frame, style="App.Panel.TFrame")
        self.page_container.pack(fill="both", expand=True)

        self.home_page = ttk.Frame(self.page_container, style="App.Panel.TFrame")

        self._build_home_page()

    def _build_menu_bar(self):
        menu_bar = tk.Menu(self.root)
        self.root.config(menu=menu_bar)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Home", command=lambda: self.show_page("home"))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menu_bar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu_bar, tearoff=0)
        edit_menu.add_command(label="Settings", command=self.open_settings_window)
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy", command=self._menu_not_implemented)
        edit_menu.add_command(label="Paste", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu_bar, tearoff=0)
        view_menu.add_command(label="Home", command=lambda: self.show_page("home"))
        view_menu.add_command(label="Data Browser", command=self.open_data_browser_window)
        menu_bar.add_cascade(label="View", menu=view_menu)

        document_menu = tk.Menu(menu_bar, tearoff=0)
        document_menu.add_command(label="Open Config Folder", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Document", menu=document_menu)

        maps_menu = tk.Menu(menu_bar, tearoff=0)
        maps_menu.add_command(label="Open Map Tools", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Maps", menu=maps_menu)

        tools_menu = tk.Menu(menu_bar, tearoff=0)
        tools_menu.add_command(label="Locate Project Gorgon", command=self.locate_pg)
        tools_menu.add_command(label="Download Newer Files", command=self.download_newer_files)
        tools_menu.add_command(label="Character Browser", command=self.open_character_browser_window)
        tools_menu.add_separator()
        tools_menu.add_command(label="Fletcher", command=self._open_fletcher)
        tools_menu.add_command(label="Itemizer", command=self._open_itemizer)
        tools_menu.add_command(label="Planner", command=self._open_planner)
        tools_menu.add_command(label="Timer", command=self._open_timer)
        tools_menu.add_command(label="Chat", command=self._open_chat)
        menu_bar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="About PGLOK", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Help", menu=help_menu)

    def _menu_not_implemented(self):
        self.status_var.set("Menu action not implemented yet.")

    def _open_fletcher(self):
        self.status_var.set("Fletcher is not implemented yet.")

    def _open_itemizer(self):
        self.status_var.set("Itemizer is not implemented yet.")

    def _open_planner(self):
        self.status_var.set("Planner is not implemented yet.")

    def _open_timer(self):
        self.status_var.set("Timer is not implemented yet.")

    def _open_chat(self):
        self.open_chat_window()

    def open_chat_window(self):
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self.chat_window.deiconify()
            self.chat_window.lift()
            self.chat_window.focus_force()
            return

        self.chat_window = tk.Toplevel(self.root)
        self.chat_window.title(f"{UI_ATTRS['window_title']} - Chat Monitor")
        self.chat_window.configure(bg=self.root.cget("bg"))
        self.chat_window.protocol("WM_DELETE_WINDOW", self._on_close_chat_window)

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
                    self._append_chat_line("All", line)
                    self._append_chat_line(channel, line)
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
        scroll = ttk.Scrollbar(tab_frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            tab_frame,
            wrap="word",
            bg=UI_COLORS["bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            borderwidth=1,
            highlightthickness=0,
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
        status_card = ttk.Frame(self.home_page, padding=16, style="App.Card.TFrame")
        status_card.pack(fill="x")
        ttk.Label(status_card, text="Status", style="App.Header.TLabel").pack(anchor="w")
        ttk.Label(status_card, textvariable=self.status_var, style="App.Status.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(status_card, textvariable=self.character_count_var, style="App.Status.TLabel").pack(anchor="w", pady=(2, 0))

    def _build_settings_content(self, parent):
        shell = ttk.Frame(parent, padding=16, style="App.Card.TFrame")
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text=UI_TEXT["header_text"], style="App.Header.TLabel").pack(anchor="w", pady=(0, 8))

        paths_frame = ttk.Frame(shell, style="App.Card.TFrame")
        paths_frame.pack(fill="x")

        for label, value_var in self.path_vars.items():
            row = ttk.Frame(paths_frame, style="App.Panel.TFrame")
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=f"{label}:", width=UI_ATTRS["label_width"], style="App.TLabel").pack(side="left")
            ttk.Entry(row, textvariable=value_var, style="App.TEntry").pack(side="left", fill="x", expand=True)

        button_row = ttk.Frame(shell, style="App.Card.TFrame")
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
        self.reset_button.pack(side="left")

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
        self.locate_button = None
        self.download_button = None
        self.reset_button = None

    def open_data_browser_window(self):
        if self.data_browser_window is not None and self.data_browser_window.winfo_exists():
            self.data_browser_window.deiconify()
            self.data_browser_window.lift()
            self.data_browser_window.focus_force()
            return

        self.data_browser_window = tk.Toplevel(self.root)
        self.data_browser_window.title(f"{UI_ATTRS['window_title']} - Data Browser")
        self.data_browser_window.configure(bg=self.root.cget("bg"))
        self.data_browser_window.protocol("WM_DELETE_WINDOW", self._on_close_data_browser_window)

        shell = ttk.Frame(self.data_browser_window, padding=12, style="App.Panel.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.Panel.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Data Browser", style="App.Header.TLabel").pack(side="left")
        ttk.Button(header, text="Refresh Index", command=self._refresh_data_index_async, style="App.Primary.TButton").pack(
            side="right"
        )

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, padding=10, style="App.Card.TFrame")
        right = ttk.Frame(body, padding=10, style="App.Card.TFrame")
        body.add(left, weight=1)
        body.add(right, weight=3)

        ttk.Label(left, text="Files", style="App.Header.TLabel").pack(anchor="w")
        self.data_file_listbox = tk.Listbox(
            left,
            bg=UI_COLORS["bg"],
            fg=UI_COLORS["text"],
            selectbackground=UI_COLORS["primary"],
            selectforeground="#ffffff",
            borderwidth=1,
            highlightthickness=0,
        )
        self.data_file_listbox.pack(fill="both", expand=True, pady=(8, 0))
        self.data_file_listbox.bind("<<ListboxSelect>>", self._on_data_file_select)

        control_row = ttk.Frame(right, style="App.Card.TFrame")
        control_row.pack(fill="x")
        ttk.Label(control_row, text="Search:", style="App.TLabel").pack(side="left")
        search_entry = ttk.Entry(control_row, textvariable=self.data_search_var, style="App.TEntry")
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        search_entry.bind("<Return>", lambda _event: self._load_data_rows(reset_offset=True))
        ttk.Button(
            control_row,
            text="Apply",
            command=lambda: self._load_data_rows(reset_offset=True),
            style="App.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(control_row, text="Prev", command=self._prev_data_page, style="App.Secondary.TButton").pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(control_row, text="Next", command=self._next_data_page, style="App.Secondary.TButton").pack(side="left")

        ttk.Label(right, textvariable=self.data_page_var, style="App.Status.TLabel").pack(anchor="w", pady=(8, 6))

        self.data_rows_tree = ttk.Treeview(
            right,
            columns=("row_index", "row_key", "preview"),
            show="headings",
            height=14,
            style="App.Treeview",
        )
        self.data_rows_tree.heading("row_index", text="#")
        self.data_rows_tree.heading("row_key", text="Key")
        self.data_rows_tree.heading("preview", text="Preview")
        self.data_rows_tree.column("row_index", width=70, stretch=False)
        self.data_rows_tree.column("row_key", width=220, stretch=False)
        self.data_rows_tree.column("preview", width=620, stretch=True)
        self.data_rows_tree.pack(fill="both", expand=True)
        self.data_rows_tree.bind("<<TreeviewSelect>>", self._on_data_row_select)

        ttk.Label(right, text="Raw JSON", style="App.Header.TLabel").pack(anchor="w", pady=(8, 4))
        self.data_json_text = tk.Text(
            right,
            height=12,
            wrap="none",
            bg=UI_COLORS["bg"],
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            borderwidth=1,
            highlightthickness=0,
        )
        self.data_json_text.pack(fill="both", expand=True)

        self.data_browser_window.update_idletasks()
        req_w = max(980, self.data_browser_window.winfo_reqwidth())
        req_h = max(620, self.data_browser_window.winfo_reqheight())
        self._apply_saved_window_geometry("data_browser", self.data_browser_window, req_w, req_h)
        self.data_browser_window.minsize(req_w, req_h)
        self._set_window_open_state("data_browser", True)
        self._refresh_data_index_async()

    def _on_close_data_browser_window(self):
        if self.data_browser_window is not None and self.data_browser_window.winfo_exists():
            self._save_window_geometry("data_browser", self.data_browser_window)
            self.data_browser_window.destroy()
        self._set_window_open_state("data_browser", False)
        self.data_browser_window = None
        self.data_file_listbox = None
        self.data_rows_tree = None
        self.data_json_text = None
        self.data_selected_filename = None
        self.data_offset = 0
        self.data_total_rows = 0

    def open_character_browser_window(self):
        if self.character_browser_window is not None and self.character_browser_window.winfo_exists():
            self.character_browser_window.deiconify()
            self.character_browser_window.lift()
            self.character_browser_window.focus_force()
            return

        self.character_browser_window = tk.Toplevel(self.root)
        self.character_browser_window.title(f"{UI_ATTRS['window_title']} - Character Browser")
        self.character_browser_window.configure(bg=self.root.cget("bg"))
        self.character_browser_window.protocol("WM_DELETE_WINDOW", self._on_close_character_browser_window)

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

        character_tree_scroll = ttk.Scrollbar(tree_wrap, orient="vertical")
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
            highlightthickness=0,
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

    def _load_character_entries(self):
        if self.character_tree is None:
            return

        reports_dir = self._get_reports_dir()
        self.character_tree.delete(*self.character_tree.get_children())
        if self.character_json_text is not None:
            self.character_json_text.delete("1.0", tk.END)
        self.character_entries = []

        if reports_dir is None or not reports_dir.exists():
            self._set_character_tree_height(4)
            self.character_count_var.set("Characters Loaded: 0")
            self.status_var.set("Reports directory not found.")
            return

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
        self.character_entries = entries

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
            self.character_tree.selection_set("0")
            self.character_tree.focus("0")
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
                        self.data_file_listbox.selection_set(0)
                        self._on_data_file_select()
                    self.status_var.set(
                        f"Index ready: {result['indexed_files']} updated, {result['skipped_files']} unchanged."
                    )

                self.root.after(0, update_ui)
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"{UI_TEXT['status_error_prefix']}{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_data_file_select(self, _event=None):
        if self.data_file_listbox is None:
            return
        selection = self.data_file_listbox.curselection()
        if not selection:
            return
        row_text = self.data_file_listbox.get(selection[0])
        self.data_selected_filename = row_text.split(" (", 1)[0]
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

        page_num = (self.data_offset // self.data_page_size) + 1
        total_pages = max(1, (self.data_total_rows + self.data_page_size - 1) // self.data_page_size)
        self.data_page_var.set(f"Page {page_num} / {total_pages}   Rows: {self.data_total_rows}")

    def _on_data_row_select(self, _event=None):
        if self.data_rows_tree is None or self.data_json_text is None:
            return
        selection = self.data_rows_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        payload = self.data_rows_tree.item(item_id, "tags")[0]
        self.data_json_text.delete("1.0", tk.END)
        try:
            parsed = json.loads(payload)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            self.data_json_text.insert("1.0", pretty)
        except json.JSONDecodeError:
            self.data_json_text.insert("1.0", payload)

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
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        self._apply_saved_window_geometry("main", self.root, req_w, req_h)
        self.root.minsize(req_w, req_h)
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
        if self._is_window_marked_open("character_browser"):
            self.open_character_browser_window()
        if self._is_window_marked_open("chat_monitor"):
            self.open_chat_window()

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
        states = self._load_all_window_states()
        state = states.get(key)
        if state and "width" in state and "height" in state:
            width = max(int(state["width"]), int(min_width))
            height = max(int(state["height"]), int(min_height))
            if "x" in state and "y" in state:
                window.geometry(f"{width}x{height}+{int(state['x'])}+{int(state['y'])}")
            else:
                window.geometry(f"{width}x{height}")
        else:
            window.geometry(f"{int(min_width)}x{int(min_height)}")

    def _on_window_configure(self, event):
        if event.widget is not self.root or not self._window_state_ready:
            return
        if self._resize_after_id is not None:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(350, self._save_main_window_state)

    def _save_main_window_state(self):
        self._resize_after_id = None
        self._save_window_geometry("main", self.root)

    def _on_close(self):
        self._save_main_window_state()
        self._set_window_open_state("settings", self.settings_window is not None and self.settings_window.winfo_exists())
        self._set_window_open_state(
            "data_browser",
            self.data_browser_window is not None and self.data_browser_window.winfo_exists(),
        )
        self._set_window_open_state(
            "character_browser",
            self.character_browser_window is not None and self.character_browser_window.winfo_exists(),
        )
        self._set_window_open_state("chat_monitor", self.chat_window is not None and self.chat_window.winfo_exists())
        self._save_window_geometry("settings", self.settings_window)
        self._save_window_geometry("data_browser", self.data_browser_window)
        self._save_window_geometry("character_browser", self.character_browser_window)
        self._save_window_geometry("chat_monitor", self.chat_window)
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

    def run_in_background(self, task, busy_message, done_message):
        def runner():
            try:
                self.root.after(0, lambda: self.set_busy(True, busy_message))
                task()
                self.root.after(0, lambda: self.set_busy(False, done_message))
                self.root.after(0, self.refresh_config_view)
            except Exception as exc:
                self.root.after(0, lambda: self.set_busy(False, f"{UI_TEXT['status_error_prefix']}{exc}"))

        threading.Thread(target=runner, daemon=True).start()

    def locate_pg(self):
        self.run_in_background(
            task=lambda: initialize_pg_base(force=True),
            busy_message=UI_TEXT["status_locating"],
            done_message=UI_TEXT["status_ready"],
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
