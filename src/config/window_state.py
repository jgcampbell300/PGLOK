import json
from datetime import datetime

import src.config.config as config
from src.config.ui_theme import apply_theme

STATE_FILE = config.CONFIG_DIR / "ui_window_state.json"


def _ensure_state_file():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({}), encoding="utf-8")


def _load_states():
    try:
        _ensure_state_file()
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_states(states):
    try:
        _ensure_state_file()
        STATE_FILE.write_text(json.dumps(states, indent=2), encoding="utf-8")
    except Exception:
        pass


def _parse_geometry(geometry):
    if not geometry:
        return None
    try:
        size_part, x_part, y_part = geometry.split("+", 2)
        width_str, height_str = size_part.split("x", 1)
        return int(width_str), int(height_str), int(x_part), int(y_part)
    except Exception:
        return None


def _get_owner_window(win):
    owner = getattr(win, "master", None)
    if owner is None:
        return None
    try:
        return owner if owner.winfo_exists() else None
    except Exception:
        return None


def _get_owner_geometry(win):
    owner = _get_owner_window(win)
    if owner is None:
        return None
    try:
        owner.update_idletasks()
        parsed = _parse_geometry(owner.winfo_geometry())
        if parsed is not None:
            return parsed
        return (
            int(owner.winfo_rootx()),
            int(owner.winfo_rooty()),
            int(owner.winfo_width() or owner.winfo_reqwidth() or 1),
            int(owner.winfo_height() or owner.winfo_reqheight() or 1),
        )
    except Exception:
        return None


def _center_geometry_within(bounds, width, height):
    if bounds is None:
        return None
    try:
        owner_x, owner_y, owner_w, owner_h = bounds
        x = owner_x + max(0, (owner_w - width) // 2)
        y = owner_y + max(0, (owner_h - height) // 2)
        return x, y
    except Exception:
        return None


def _apply_geometry_on_same_monitor(win, width, height, owner_geom=None):
    try:
        centered = _center_geometry_within(owner_geom, width, height)
        if centered is not None:
            x, y = centered
            win.geometry(f"{width}x{height}+{x}+{y}")
            return

        screen_w = max(640, int(win.winfo_screenwidth()))
        screen_h = max(480, int(win.winfo_screenheight()))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        win.geometry(f"{width}x{height}")


def setup_window(
    win,
    name,
    min_w=None,
    min_h=None,
    default_geometry=None,
    on_close=None,
    debounce_ms=200,
    parent_window=None,
):
    """Apply theme to a Toplevel and attach geometry persistence."""

    try:
        apply_theme(win)
    except Exception:
        try:
            from src.config.ui_theme import UI_COLORS, UI_ATTRS

            win.configure(bg=UI_COLORS.get("bg", "#333333"))
            win.option_add("*Font", (UI_ATTRS.get("font_family", "Segoe UI"), UI_ATTRS.get("font_size", 10)))
        except Exception:
            pass

    if min_w or min_h:
        try:
            win.minsize(min_w or 100, min_h or 100)
        except Exception:
            pass

    saved_geometry = None
    try:
        states = _load_states()
        if name in states:
            saved_geometry = states[name].get("geometry")
    except Exception:
        saved_geometry = None

    owner_geom = None
    if parent_window is not None:
        try:
            if parent_window.winfo_exists():
                owner_geom = _get_owner_geometry(parent_window)
                if owner_geom is None:
                    owner_geom = (
                        int(parent_window.winfo_rootx()),
                        int(parent_window.winfo_rooty()),
                        int(parent_window.winfo_width() or parent_window.winfo_reqwidth() or 1),
                        int(parent_window.winfo_height() or parent_window.winfo_reqheight() or 1),
                    )
        except Exception:
            owner_geom = None

    geometry_to_apply = default_geometry or saved_geometry
    applied_size = False
    if geometry_to_apply:
        parsed = _parse_geometry(geometry_to_apply)
        if parsed is not None:
            width, height, x, y = parsed
            width = max(min_w or 1, width)
            height = max(min_h or 1, height)
            if saved_geometry is None and owner_geom is not None:
                _apply_geometry_on_same_monitor(win, width, height, owner_geom=owner_geom)
            else:
                if x is not None and y is not None:
                    win.geometry(f"{width}x{height}+{x}+{y}")
                else:
                    win.geometry(f"{width}x{height}")
            applied_size = True
        else:
            try:
                win.geometry(geometry_to_apply)
                applied_size = True
            except Exception:
                pass

    if not applied_size:
        try:
            base_w = max(min_w or 320, min(900, win.winfo_reqwidth() or 900))
            base_h = max(min_h or 240, min(600, win.winfo_reqheight() or 600))
        except Exception:
            base_w, base_h = max(min_w or 320, 900), max(min_h or 240, 600)
        _apply_geometry_on_same_monitor(win, base_w, base_h, owner_geom=owner_geom)

    def _save_now():
        try:
            if not win.winfo_exists():
                return
            geom = win.geometry()
            states = _load_states()
            states[name] = {"geometry": geom, "timestamp": datetime.now().isoformat()}
            _save_states(states)
        except Exception:
            pass

    def _schedule_save(_event=None):
        try:
            if hasattr(win, "_window_state_after_id") and win._window_state_after_id:
                win.after_cancel(win._window_state_after_id)
        except Exception:
            pass

        try:
            win._window_state_after_id = win.after(debounce_ms, _save_now)
        except Exception:
            _save_now()

    try:
        win.bind("<Configure>", _schedule_save)
    except Exception:
        pass

    def _on_close_wrapper():
        try:
            _save_now()
        except Exception:
            pass
        try:
            if on_close:
                on_close()
            else:
                win.destroy()
        except Exception:
            try:
                if win.winfo_exists():
                    win.destroy()
            except Exception:
                pass

    try:
        win.protocol("WM_DELETE_WINDOW", _on_close_wrapper)
    except Exception:
        pass

    return win
