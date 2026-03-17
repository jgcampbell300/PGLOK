import json
from pathlib import Path
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


def setup_window(win, name, min_w=None, min_h=None, default_geometry=None, on_close=None, debounce_ms=200):
    """Apply theme to a Toplevel and attach geometry persistence.

    win: the Toplevel to prepare
    name: key under which geometry will be saved
    min_w/min_h: optional minimum size
    default_geometry: optional default geometry string (e.g. '900x600+10+10')
    on_close: optional callable to run when window is closed
    debounce_ms: ms to debounce configure events
    """
    try:
        apply_theme(win)
    except Exception:
        # best-effort theme application
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

    if default_geometry:
        try:
            win.geometry(default_geometry)
        except Exception:
            pass

    # Restore saved geometry if present
    try:
        states = _load_states()
        if name in states:
            geom = states[name].get("geometry")
            if geom:
                win.geometry(geom)
    except Exception:
        pass

    # Debounced save on configure
    def _schedule_save(event=None):
        try:
            if hasattr(win, "_window_state_after_id") and win._window_state_after_id:
                win.after_cancel(win._window_state_after_id)
        except Exception:
            pass

        try:
            win._window_state_after_id = win.after(debounce_ms, _save_now)
        except Exception:
            # fallback immediate
            _save_now()

    def _save_now():
        try:
            geom = win.geometry()
            states = _load_states()
            states[name] = {"geometry": geom, "timestamp": datetime.now().isoformat()}
            _save_states(states)
        except Exception:
            pass

    # Bind resize/move events
    try:
        win.bind("<Configure>", _schedule_save)
    except Exception:
        pass

    # Ensure geometry saved on close and call optional on_close
    def _on_close_wrapper():
        try:
            _save_now()
        except Exception:
            pass
        if on_close:
            try:
                on_close()
            except Exception:
                try:
                    win.destroy()
                except Exception:
                    pass
        else:
            try:
                win.destroy()
            except Exception:
                pass

    try:
        win.protocol("WM_DELETE_WINDOW", _on_close_wrapper)
    except Exception:
        pass

    return win
