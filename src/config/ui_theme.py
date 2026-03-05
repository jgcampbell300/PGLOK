from tkinter import ttk


UI_COLORS = {
    "bg": "#0f111a",
    "panel_bg": "#151a26",
    "card_bg": "#1b2130",
    "text": "#e6edf7",
    "muted_text": "#98a6bd",
    "primary": "#1f8fff",
    "primary_active": "#46a4ff",
    "secondary": "#2a344a",
    "secondary_active": "#3a4661",
    "entry_bg": "#0f141f",
    "entry_border": "#385072",
    "accent": "#5dd6ff",
}

UI_ATTRS = {
    "window_title": "PGLOK",
    "window_min_width": 760,
    "window_min_height": 420,
    "container_padding": 18,
    "label_width": 14,
    "header_text": "Project Gorgon Locator and Data Tools",
    "font_family": "Segoe UI",
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
    )
    style.configure(
        "App.Primary.TButton",
        background=UI_COLORS["primary"],
        foreground="#ffffff",
        borderwidth=1,
        relief="flat",
        focusthickness=2,
        focuscolor=UI_COLORS["primary_active"],
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"]),
        padding=(12, 9),
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
        relief="flat",
        font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"]),
        padding=(12, 9),
    )
    style.map(
        "App.Secondary.TButton",
        background=[("active", UI_COLORS["secondary_active"]), ("disabled", UI_COLORS["secondary"])],
        foreground=[("disabled", UI_COLORS["muted_text"])],
    )
