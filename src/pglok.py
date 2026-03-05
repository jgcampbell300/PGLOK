import json
import re
import threading
import tkinter as tk
from tkinter import ttk

import src.config.config as config
from src.config.ui_theme import UI_ATTRS, UI_TEXT, UI_COLORS, apply_theme
from src.data_acquisition import main as run_data_acquisition
from src.locate_PG import initialize_pg_base


WINDOW_STATE_FILE = config.CONFIG_DIR / "ui_window_state.json"
GEOMETRY_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)$")


class PGLOKApp:
    def __init__(self, root):
        self.root = root
        self._resize_after_id = None
        self._window_state_ready = False
        self.settings_window = None
        self.locate_button = None
        self.download_button = None
        self.reset_button = None
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
        self.show_page("home")
        if config.PG_BASE is None:
            self.locate_pg()

    def _build_layout(self):
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
        menu_bar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="About PGLOK", command=self._menu_not_implemented)
        menu_bar.add_cascade(label="Help", menu=help_menu)

    def _menu_not_implemented(self):
        self.status_var.set("Menu action not implemented yet.")

    def _build_home_page(self):
        hero = ttk.Frame(self.home_page, padding=16, style="App.Card.TFrame")
        hero.pack(fill="x", pady=(0, 12))
        ttk.Label(hero, text="Control Center", style="App.Header.TLabel").pack(anchor="w")
        ttk.Label(
            hero,
            text="Use Edit > Settings for path management and synchronization options.",
            style="App.TLabel",
        ).pack(anchor="w", pady=(6, 12))
        quick_actions = ttk.Frame(hero, style="App.Card.TFrame")
        quick_actions.pack(fill="x")
        ttk.Button(
            quick_actions,
            text="Locate Now",
            command=self.locate_pg,
            style="App.Primary.TButton",
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            quick_actions,
            text="Sync Data",
            command=self.download_newer_files,
            style="App.Secondary.TButton",
        ).pack(side="left")

        status_card = ttk.Frame(self.home_page, padding=16, style="App.Card.TFrame")
        status_card.pack(fill="x")
        ttk.Label(status_card, text="Status", style="App.Header.TLabel").pack(anchor="w")
        ttk.Label(status_card, textvariable=self.status_var, style="App.Status.TLabel").pack(anchor="w", pady=(6, 0))

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
        self.settings_window.transient(self.root)
        self.settings_window.minsize(620, 260)
        self.settings_window.protocol("WM_DELETE_WINDOW", self._on_close_settings_window)

        container = ttk.Frame(
            self.settings_window,
            padding=12,
            style="App.Panel.TFrame",
        )
        container.pack(fill="both", expand=True)
        self._build_settings_content(container)
        self.refresh_config_view()

    def _on_close_settings_window(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None
        self.locate_button = None
        self.download_button = None
        self.reset_button = None

    def show_page(self, page_name):
        for page in (self.home_page,):
            page.pack_forget()
        self.home_page.pack(fill="both", expand=True)

    def _apply_startup_geometry(self):
        state = self._load_window_state()
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()

        if state and "width" in state and "height" in state:
            width = max(int(state["width"]), req_w)
            height = max(int(state["height"]), req_h)
            if "x" in state and "y" in state:
                self.root.geometry(f"{width}x{height}+{int(state['x'])}+{int(state['y'])}")
            else:
                self.root.geometry(f"{width}x{height}")
        else:
            self.root.geometry(f"{req_w}x{req_h}")

        self.root.minsize(req_w, req_h)
        self._window_state_ready = True

    def _load_window_state(self):
        try:
            if not WINDOW_STATE_FILE.exists():
                return None
            return json.loads(WINDOW_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _on_window_configure(self, event):
        if event.widget is not self.root or not self._window_state_ready:
            return
        if self._resize_after_id is not None:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(350, self._save_window_state)

    def _save_window_state(self):
        self._resize_after_id = None
        match = GEOMETRY_RE.match(self.root.geometry())
        if not match:
            return
        state = {
            "width": int(match.group("w")),
            "height": int(match.group("h")),
            "x": int(match.group("x")),
            "y": int(match.group("y")),
        }
        try:
            WINDOW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            WINDOW_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _on_close(self):
        self._save_window_state()
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
