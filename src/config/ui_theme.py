from tkinter import ttk


UI_COLORS = {
    "bg": "#060507",
    "panel_bg": "#140f0e",
    "card_bg": "#1e1413",
    "text": "#ddd6c8",
    "muted_text": "#baa98d",
    "primary": "#8d321e",
    "primary_active": "#a63a22",
    "secondary": "#3a231d",
    "secondary_active": "#4c2e26",
    "entry_bg": "#140f0f",
    "entry_border": "#8a6a3d",
    "accent": "#d8b564",
    "menu_active": "#4c2e26",
}

UI_ATTRS = {
    "window_title": "PG-LOK",
    "window_min_width": 760,
    "window_min_height": 420,
    "container_padding": 18,
    "label_width": 14,
    "header_text": "Project Gorgon Locator and Data Tools",
    "font_family": "Palatino Linotype",
    "font_size": 10,
    "font_size_header": 14,
}

UI_TEXT = {
    "header_text": "Project Gorgon Locator and Data Tools",
    "path_labels": (
        "PG Base",
        "CDN URL",
    ),
    "none_value": "None",
    "locate_button": "Locate Project Gorgon",
    "download_button": "Download Newer Files",
    "reset_button": "Reset Config Paths",
    "status_ready": "Ready",
    "status_locating": "Locating Project Gorgon...",
    "status_downloading": "Checking and downloading newer data files...",
    "status_download_done": "Data acquisition complete.",
    "status_reset_done": "Config paths reset to defaults.",
    "status_error_prefix": "Error: ",
}


def apply_theme(root):
    root.configure(bg=UI_COLORS["bg"])
    root.option_add("*Font", (UI_ATTRS["font_family"], UI_ATTRS["font_size"]))

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        "App.TFrame",
        background=UI_COLORS["bg"],
    )
    style.configure(
        "App.Panel.TFrame",
        background=UI_COLORS["panel_bg"],
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "App.Card.TFrame",
        background=UI_COLORS["card_bg"],
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "App.TLabel",
        background=UI_COLORS["panel_bg"],
        foreground=UI_COLORS["text"],
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"]),
    )
    style.configure(
        "App.Header.TLabel",
        background=UI_COLORS["panel_bg"],
        foreground=UI_COLORS["accent"],
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size_header"], "bold"),
    )
    style.configure(
        "App.Status.TLabel",
        background=UI_COLORS["panel_bg"],
        foreground=UI_COLORS["muted_text"],
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"]),
    )
    style.configure(
        "App.TEntry",
        fieldbackground=UI_COLORS["entry_bg"],
        foreground=UI_COLORS["text"],
        bordercolor=UI_COLORS["entry_border"],
        insertcolor=UI_COLORS["text"],
        lightcolor=UI_COLORS["entry_border"],
        darkcolor=UI_COLORS["entry_border"],
        padding=(6, 4),
    )
    style.map("App.TEntry", bordercolor=[("focus", UI_COLORS["accent"])], lightcolor=[("focus", UI_COLORS["accent"])])
    style.configure(
        "App.SpellError.TEntry",
        fieldbackground=UI_COLORS["entry_bg"],
        foreground=UI_COLORS["text"],
        bordercolor="#b63a3a",
        insertcolor=UI_COLORS["text"],
        lightcolor="#b63a3a",
        darkcolor="#b63a3a",
        padding=(6, 4),
    )
    style.map(
        "App.SpellError.TEntry",
        bordercolor=[("focus", "#d84a4a")],
        lightcolor=[("focus", "#d84a4a")],
    )
    style.configure(
        "App.Primary.TButton",
        background=UI_COLORS["primary"],
        foreground=UI_COLORS["text"],
        borderwidth=1,
        relief="raised",
        focusthickness=2,
        focuscolor=UI_COLORS["primary_active"],
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"]),
        padding=(10, 6),
    )
    style.map(
        "App.Primary.TButton",
        background=[("active", UI_COLORS["primary_active"]), ("disabled", UI_COLORS["secondary"])],
        foreground=[("disabled", UI_COLORS["muted_text"])],
    )
    style.configure(
        "App.Secondary.TButton",
        background=UI_COLORS["secondary"],
        foreground=UI_COLORS["text"],
        borderwidth=1,
        relief="raised",
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"]),
        padding=(10, 6),
    )
    style.map(
        "App.Secondary.TButton",
        background=[("active", UI_COLORS["secondary_active"]), ("disabled", UI_COLORS["secondary"])],
        foreground=[("disabled", UI_COLORS["muted_text"])],
    )
    style.configure(
        "App.Treeview",
        background=UI_COLORS["entry_bg"],
        fieldbackground=UI_COLORS["entry_bg"],
        foreground=UI_COLORS["text"],
        bordercolor=UI_COLORS["entry_border"],
        rowheight=24,
    )
    style.map(
        "App.Treeview",
        background=[("selected", UI_COLORS["secondary_active"])],
        foreground=[("selected", UI_COLORS["accent"])],
    )
    style.configure(
        "App.Treeview.Heading",
        background=UI_COLORS["secondary"],
        foreground=UI_COLORS["text"],
        relief="raised",
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
    )
    style.map("App.Treeview.Heading", background=[("active", UI_COLORS["secondary_active"])])
    style.configure(
        "App.TCombobox",
        fieldbackground=UI_COLORS["entry_bg"],
        background=UI_COLORS["secondary"],
        foreground=UI_COLORS["text"],
        bordercolor=UI_COLORS["entry_border"],
        lightcolor=UI_COLORS["entry_border"],
        darkcolor=UI_COLORS["entry_border"],
        arrowcolor=UI_COLORS["accent"],
        insertcolor=UI_COLORS["text"],
    )
    style.map(
        "App.TCombobox",
        fieldbackground=[("readonly", UI_COLORS["entry_bg"])],
        foreground=[("readonly", UI_COLORS["text"])],
        background=[("readonly", UI_COLORS["secondary"])],
    )
    style.configure(
        "TScrollbar",
        troughcolor=UI_COLORS["card_bg"],
        background=UI_COLORS["secondary"],
        arrowcolor=UI_COLORS["accent"],
        bordercolor=UI_COLORS["entry_border"],
        lightcolor=UI_COLORS["entry_border"],
        darkcolor=UI_COLORS["entry_border"],
        gripcount=0,
    )
    style.map(
        "TScrollbar",
        background=[("active", UI_COLORS["secondary_active"])],
    )
    style.configure(
        "App.Vertical.TScrollbar",
        troughcolor=UI_COLORS["card_bg"],
        background=UI_COLORS["secondary"],
        arrowcolor=UI_COLORS["accent"],
        bordercolor=UI_COLORS["entry_border"],
        lightcolor=UI_COLORS["entry_border"],
        darkcolor=UI_COLORS["entry_border"],
        gripcount=0,
    )
    style.map(
        "App.Vertical.TScrollbar",
        background=[("active", UI_COLORS["secondary_active"])],
    )
    style.configure(
        "App.Horizontal.TScrollbar",
        troughcolor=UI_COLORS["card_bg"],
        background=UI_COLORS["secondary"],
        arrowcolor=UI_COLORS["accent"],
        bordercolor=UI_COLORS["entry_border"],
        lightcolor=UI_COLORS["entry_border"],
        darkcolor=UI_COLORS["entry_border"],
        gripcount=0,
    )
    style.map(
        "App.Horizontal.TScrollbar",
        background=[("active", UI_COLORS["secondary_active"])],
    )
    style.configure(
        "App.TPanedwindow",
        background=UI_COLORS["card_bg"],
        sashthickness=6,
        sashrelief="flat",
    )
    style.configure(
        "TNotebook",
        background=UI_COLORS["card_bg"],
        borderwidth=1,
    )
    style.configure(
        "TNotebook.Tab",
        background=UI_COLORS["secondary"],
        foreground=UI_COLORS["text"],
        padding=(10, 4),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", UI_COLORS["primary"]), ("active", UI_COLORS["secondary_active"])],
        foreground=[("selected", UI_COLORS["text"])],
    )


def configure_menu_theme(menu):
    menu.configure(
        bg=UI_COLORS["panel_bg"],
        fg=UI_COLORS["text"],
        activebackground=UI_COLORS["menu_active"],
        activeforeground=UI_COLORS["accent"],
        selectcolor=UI_COLORS["accent"],
        relief="flat",
        borderwidth=1,
    )
