"""Survey Helper - Tool to assist with Project Gorgon surveying.

Monitors chat logs for survey results, displays item positions on map overlay,
and tracks survey maps in inventory grid.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import re
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, asdict
from datetime import datetime
import threading
import time
def _import_vision_stack():
    """Import OpenCV/numpy/ImageGrab, falling back to build_env site-packages."""
    try:
        import cv2 as _cv2
        import numpy as _np
        from PIL import ImageGrab as _ImageGrab
        return _cv2, _np, _ImageGrab
    except ImportError:
        project_root = Path(__file__).resolve().parents[2]
        build_env_lib = project_root / "build_env" / "lib"
        if build_env_lib.is_dir():
            for python_dir in sorted(build_env_lib.glob("python*/site-packages")):
                site_packages = str(python_dir)
                if site_packages not in sys.path:
                    sys.path.insert(0, site_packages)
            try:
                import cv2 as _cv2
                import numpy as _np
                from PIL import ImageGrab as _ImageGrab
                return _cv2, _np, _ImageGrab
            except ImportError:
                pass
    return None, None, None


cv2, np, ImageGrab = _import_vision_stack()

from src.chat.monitor import ChatLogMonitor
from src.locate_PG import initialize_pg_base
import src.config.config as config
from src.config.ui_theme import UI_ATTRS, UI_COLORS, apply_theme


def set_window_icon(window, icon_path: str = "icon.png"):
    """Set window icon for taskbar/window title bar.
    
    Args:
        window: tk.Tk or tk.Toplevel window
        icon_path: Path to icon file (png, ico, etc)
    """
    try:
        # Try to find icon in project root
        icon_file = Path(icon_path)
        if not icon_file.exists():
            # Try relative to this module
            icon_file = Path(__file__).parent.parent.parent / icon_path
        
        if icon_file.exists():
            if str(icon_file).lower().endswith('.ico'):
                window.iconbitmap(str(icon_file))
            else:
                # Use PhotoImage for PNG and other formats
                photo = tk.PhotoImage(file=str(icon_file))
                window.iconphoto(False, photo)
    except Exception as e:
        # Silently fail - icon is optional
        pass


def parse_geometry(geom_string: str) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """Parse a geometry string (WIDTHxHEIGHT+X+Y) into components.
    
    Args:
        geom_string: Geometry string like "400x300+100+50"
    
    Returns:
        Tuple of (width, height, x, y) where each may be None if parsing fails
    """
    match = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', geom_string)
    if match:
        w, h, x, y = map(int, match.groups())
        return (w, h, x, y)
    return (None, None, None, None)


def save_window_geometry(window) -> Dict[str, Tuple[int, int]]:
    """Save window position and size using the actual geometry string.
    
    This uses wm_geometry() which returns the true geometry that was set,
    avoiding the coordinate offset issues that occur when reconstructing
    geometry from winfo_x/y/width/height.
    
    Returns:
        Dict with 'position': (x, y) and 'size': (width, height)
    """
    geom = window.wm_geometry()
    w, h, x, y = parse_geometry(geom)
    return {'position': (x, y), 'size': (w, h)}


def find_gorgon_config() -> Optional[Path]:
    """Search for GorgonConfig.txt or GorgonSettings.txt across different OS locations."""
    import sys
    
    possible_paths = []
    filenames = ['GorgonSettings.txt', 'GorgonConfig.txt']  # Try GorgonSettings first (more common on Linux)
    
    if sys.platform == 'win32':
        # Windows paths
        appdata = Path.home() / 'AppData' / 'Roaming' / 'ProjectGorgon'
        localappdata = Path.home() / 'AppData' / 'Local' / 'ProjectGorgon'
        for filename in filenames:
            possible_paths.extend([
                appdata / filename,
                localappdata / filename,
                Path(f'C:/Program Files/ProjectGorgon/{filename}'),
                Path(f'C:/Program Files (x86)/ProjectGorgon/{filename}'),
            ])
    elif sys.platform == 'darwin':
        # macOS paths
        home = Path.home()
        for filename in filenames:
            possible_paths.extend([
                home / 'Library' / 'Application Support' / 'ProjectGorgon' / filename,
                home / 'Library' / 'Preferences' / 'ProjectGorgon' / filename,
                home / '.projectgorgon' / filename,
            ])
    else:
        # Linux paths
        home = Path.home()
        for filename in filenames:
            possible_paths.extend([
                # Unity3D config path (most common on Linux)
                home / '.config' / 'unity3d' / 'Elder Game' / 'Project Gorgon' / filename,
                # Fallback paths
                home / '.local' / 'share' / 'ProjectGorgon' / filename,
                home / '.config' / 'ProjectGorgon' / filename,
                home / '.projectgorgon' / filename,
            ])
    
    # Search for the file
    for path in possible_paths:
        try:
            if path.exists():
                return path
        except Exception:
            pass
    
    return None


def parse_gorgon_config(config_path: Path) -> Dict:
    """Parse GorgonConfig.txt or GorgonSettings.txt to extract window positions and sizes.
    
    Handles both formats:
    - Key=Value format (standard config)
    - Tab-delimited format (Unity3D GorgonSettings.txt): type\tkey\tindex\tvalue
    """
    config_data = {}
    try:
        with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Check for tab-delimited format (Unity3D)
                if '\t' in line:
                    parts = line.split('\t')
                    if len(parts) >= 4:
                        # Format: type\tkey\tindex\tvalue
                        key = parts[1]
                        value = parts[3]
                        config_data[key] = value
                # Check for key=value format
                elif '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip()
    except Exception as e:
        print(f"Error parsing config file: {e}")
    
    return config_data


def get_ui_scale(config_data: Dict) -> float:
    """Extract UI scale factor from config.
    
    Returns: UI scale (default 1.0 if not found)
    Example: 1.524914 = 152.49% UI scaling
    """
    try:
        for scale_key in ['UI_GUIScale', 'GUIScale', 'ui_scale']:
            if scale_key in config_data:
                return float(config_data[scale_key])
    except (ValueError, KeyError):
        pass
    
    return 1.0


def get_inventory_window_dims(config_data: Dict) -> Optional[Tuple[int, int, int, int]]:
    """Extract inventory GRID window position and size from config.
    
    Returns: (x, y, grid_width, height) or None if not found
    
    Note: WinPosition_InventoryWindow includes both the bags sidebar AND main grid.
    We subtract the sidebar width to get the actual grid dimensions.
    
    Applies UI scaling factor if found in config
    Handles both legacy key-value format and Unity3D WinPosition format
    """
    try:
        # Get UI scale factor
        scale = get_ui_scale(config_data)
        
        # Get sidebar width (bags bar on left side)
        sidebar_width = 0
        if 'WinPosition_InventorySidebarWidth' in config_data:
            try:
                sidebar_width = int(float(config_data['WinPosition_InventorySidebarWidth']) * scale)
            except (ValueError, TypeError):
                sidebar_width = int(58 * scale)  # Default if parse fails
        else:
            sidebar_width = int(58 * scale)  # Fallback default
        
        # Try Unity3D format first: WinPosition_InventoryWindow = "M20.86581;L63.52591;617.4161;463.7999|T|T||-1|-1"
        if 'WinPosition_InventoryWindow' in config_data:
            value = config_data['WinPosition_InventoryWindow']
            # Extract the position part (before the first |)
            pos_part = value.split('|')[0]
            parts = pos_part.split(';')
            
            if len(parts) >= 4:
                try:
                    # Format: M<x>;L<y>;<width>;<height>
                    x = int(float(parts[0][1:]) * scale)  # Remove 'M' prefix, apply scale
                    y = int(float(parts[1][1:]) * scale)  # Remove 'L' prefix, apply scale
                    total_width = int(float(parts[2]) * scale)  # Total window width (with sidebar)
                    height = int(float(parts[3]) * scale)  # Apply scale
                    
                    # Calculate main grid width by subtracting sidebar width
                    grid_width = total_width - sidebar_width
                    
                    # Add sidebar offset to X position to move grid to the right of sidebar
                    grid_x = x + sidebar_width
                    
                    return (grid_x, y, grid_width, height)
                except (ValueError, IndexError):
                    pass
        
        # Fallback to legacy format: inventoryWindowX, inventoryWindowY, etc.
        for x_key in ['inventoryWindowX', 'Inventory_WindowX', 'InventoryWindowX']:
            if x_key in config_data:
                x = int(float(config_data[x_key]) * scale)
                y = int(float(config_data.get(x_key.replace('X', 'Y'), 0)) * scale)
                width = int(float(config_data.get(x_key.replace('X', 'Width'), 400)) * scale)
                height = int(float(config_data.get(x_key.replace('X', 'Height'), 300)) * scale)
                return (x, y, width, height)
    except (ValueError, KeyError, IndexError) as e:
        print(f"Error extracting inventory dimensions: {e}")
    
    return None


def get_inventory_grid_settings(config_data: Dict) -> Optional[Tuple[int, int]]:
    """Extract inventory grid columns and slot size from config.
    
    Returns: (columns, slot_size) or None if not found
    """
    try:
        # Look for grid configuration entries
        # Common patterns: inventoryColumns, InventoryColumns, inventory_columns, itemSize, slot_size, etc.
        for col_key in ['inventoryColumns', 'InventoryColumns', 'inventory_columns', 
                        'invColumns', 'inv_columns', 'gridColumns', 'grid_columns']:
            if col_key in config_data:
                columns = int(config_data[col_key])
                
                # Look for slot/item size
                slot_size = 40  # default
                for size_key in ['itemSlotSize', 'ItemSlotSize', 'slotSize', 'slot_size', 
                                'inventorySlotSize', 'inventory_slot_size']:
                    if size_key in config_data:
                        slot_size = int(config_data[size_key])
                        break
                
                return (columns, slot_size)
    except (ValueError, KeyError) as e:
        print(f"Error extracting inventory grid settings: {e}")
    
    return None


def calculate_grid_columns_from_width(window_width: int, slot_size: int = 32, gap: int = 4) -> int:
    """Calculate number of columns that fit in the given window width.
    
    Formula: window_width / (slot_size + gap)
    
    This accounts for the gap/padding between item slots but not left/right margins
    (those are handled by the UI framework and vary per user setup).
    
    Args:
        window_width: Grid width in pixels (from GorgonSettings)
        slot_size: Item slot size in pixels (typically 32px, user can customize)
        gap: Gap between slots in pixels (typically 4px)
    
    Returns: Estimated number of columns (user can fine-tune with spinbox)
    """
    if slot_size <= 0:
        return 1
    columns = max(1, window_width // (slot_size + gap))
    return columns


def find_game_window() -> Optional[Tuple[int, int, int, int]]:
    """Find Project Gorgon game window position and size.
    
    Returns: (x, y, width, height) or None if not found
    Works on Linux with wmctrl. Returns None on other platforms.
    """
    if sys.platform != 'linux':
        return None
    
    try:
        # Use wmctrl to find window info
        result = subprocess.run(
            ['wmctrl', '-l', '-p', '-G'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Parse output to find "Project Gorgon" window
        for line in result.stdout.splitlines():
            if 'Project Gorgon' in line and 'jgcampbell300@' not in line:  # Exclude file browser
                parts = line.split()
                if len(parts) >= 7:
                    try:
                        # Format: window_id desktop pid x y width height host name...
                        x = int(parts[3])
                        y = int(parts[4])
                        width = int(parts[5])
                        height = int(parts[6])
                        return (x, y, width, height)
                    except (ValueError, IndexError):
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return None


def calculate_overlay_position(game_pos: Tuple[int, int, int, int], 
                               rel_x: float, rel_y: float) -> Tuple[int, int]:
    """Calculate absolute overlay position from game window and relative coordinates.
    
    Args:
        game_pos: (game_x, game_y, game_width, game_height)
        rel_x: Relative X position within game window (e.g., M value from GorgonSettings)
        rel_y: Relative Y position within game window (e.g., L value from GorgonSettings)
    
    Returns: (abs_x, abs_y) - absolute screen coordinates
    """
    game_x, game_y, _, _ = game_pos
    abs_x = game_x + int(rel_x)
    abs_y = game_y + int(rel_y)
    return (abs_x, abs_y)



@dataclass
class SurveyItem:
    """Represents a survey item found in the world."""
    name: str
    distance: float
    direction: str  # N, NE, E, SE, S, SW, W, NW
    x: float = 0.0
    y: float = 0.0
    collected: bool = False
    timestamp: Optional[datetime] = None
    # Direct meter offsets (east=+, north=+) used when compound direction is parsed
    dx_m: Optional[float] = None
    dy_m: Optional[float] = None

    def to_dict(self):
        return {
            'name': self.name,
            'distance': self.distance,
            'direction': self.direction,
            'x': self.x,
            'y': self.y,
            'collected': self.collected,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'dx_m': self.dx_m,
            'dy_m': self.dy_m,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SurveyItem':
        ts = None
        if data.get('timestamp'):
            try:
                ts = datetime.fromisoformat(data['timestamp'])
            except:
                pass
        return cls(
            name=data['name'],
            distance=data['distance'],
            direction=data['direction'],
            x=data.get('x', 0.0),
            y=data.get('y', 0.0),
            collected=data.get('collected', False),
            timestamp=ts,
            dx_m=data.get('dx_m'),
            dy_m=data.get('dy_m'),
        )


class SurveySettings:
    """Manages survey helper settings."""
    
    SETTINGS_FILE = Path(__file__).parent / 'survey_settings.json'
    
    def __init__(self):
        self.chatlog_dir: Optional[Path] = None
        self.survey_count: int = 0
        self.map_opacity: float = 0.25
        self.inv_opacity: float = 0.7
        self.map_clickthrough: bool = False
        self.inv_clickthrough: bool = False
        self.grid_cols: int = 10
        self.slot_size: int = 40
        self.slot_gap: int = 4
        self.inv_offset: int = 0  # blank slots before first item
        self.hotkey: str = "<num0>"
        self.map_position: Optional[Tuple[int, int]] = None
        self.inv_position: Optional[Tuple[int, int]] = None
        self.map_size: Optional[Tuple[int, int]] = None
        self.inv_size: Optional[Tuple[int, int]] = None
        self.scale_factor: Optional[float] = None  # pixels per meter
        self.origin_x: Optional[float] = None  # player position on map
        self.origin_y: Optional[float] = None
        self.current_player_x: Optional[float] = None
        self.current_player_y: Optional[float] = None
        self.main_window_position: Optional[Tuple[int, int]] = None  # (x, y)
        self.main_window_size: Optional[Tuple[int, int]] = None  # (width, height)
        self.map_was_open: bool = False  # whether map was open on last close
        self.inventory_was_open: bool = False  # whether inventory was open on last close
        self.always_on_top: bool = False
        self.zone_name: Optional[str] = None
        self.current_phase: int = 0
        
        self.load()
    
    def load(self):
        """Load settings from file."""
        if self.SETTINGS_FILE.exists():
            try:
                with open(self.SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                
                self.chatlog_dir = Path(data['chatlog_dir']) if data.get('chatlog_dir') else None
                self.survey_count = data.get('survey_count', 0)
                self.map_opacity = data.get('map_opacity', 0.7)
                self.inv_opacity = data.get('inv_opacity', 0.7)
                self.map_clickthrough = data.get('map_clickthrough', False)
                self.inv_clickthrough = data.get('inv_clickthrough', False)
                self.grid_cols = data.get('grid_cols', 10)
                self.slot_size = data.get('slot_size', 40)
                self.slot_gap = data.get('slot_gap', 4)
                self.inv_offset = data.get('inv_offset', 0)
                self.hotkey = data.get('hotkey', '<num0>')
                
                if data.get('map_position'):
                    self.map_position = tuple(data['map_position'])
                if data.get('inv_position'):
                    self.inv_position = tuple(data['inv_position'])
                if data.get('map_size'):
                    self.map_size = tuple(data['map_size'])
                if data.get('inv_size'):
                    self.inv_size = tuple(data['inv_size'])
                
                self.scale_factor = data.get('scale_factor')
                self.origin_x = data.get('origin_x')
                self.origin_y = data.get('origin_y')
                self.current_player_x = data.get('current_player_x')
                self.current_player_y = data.get('current_player_y')
                
                if data.get('main_window_position'):
                    self.main_window_position = tuple(data['main_window_position'])
                if data.get('main_window_size'):
                    self.main_window_size = tuple(data['main_window_size'])
                
                self.map_was_open = data.get('map_was_open', False)
                self.inventory_was_open = data.get('inventory_was_open', False)
                self.always_on_top = data.get('always_on_top', False)
                self.zone_name = data.get('zone_name')
                self.current_phase = data.get('current_phase', 0)
                
            except Exception as e:
                print(f"Error loading survey settings: {e}")
    
    def save(self):
        """Save settings to file."""
        data = {
            'chatlog_dir': str(self.chatlog_dir) if self.chatlog_dir else None,
            'survey_count': self.survey_count,
            'map_opacity': self.map_opacity,
            'inv_opacity': self.inv_opacity,
            'map_clickthrough': self.map_clickthrough,
            'inv_clickthrough': self.inv_clickthrough,
            'grid_cols': self.grid_cols,
            'slot_size': self.slot_size,
            'slot_gap': self.slot_gap,
            'inv_offset': self.inv_offset,
            'hotkey': self.hotkey,
            'map_position': list(self.map_position) if self.map_position else None,
            'inv_position': list(self.inv_position) if self.inv_position else None,
            'map_size': list(self.map_size) if self.map_size else None,
            'inv_size': list(self.inv_size) if self.inv_size else None,
            'scale_factor': self.scale_factor,
            'origin_x': self.origin_x,
            'origin_y': self.origin_y,
            'current_player_x': self.current_player_x,
            'current_player_y': self.current_player_y,
            'main_window_position': list(self.main_window_position) if self.main_window_position else None,
            'main_window_size': list(self.main_window_size) if self.main_window_size else None,
            'map_was_open': self.map_was_open,
            'inventory_was_open': self.inventory_was_open,
            'always_on_top': self.always_on_top,
            'zone_name': self.zone_name,
            'current_phase': self.current_phase,
        }
        
        try:
            with open(self.SETTINGS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving survey settings: {e}")


def _get_all_xids(tk_win):
    """Return all X11 window IDs for this Tk widget tree including the Tk wrapper."""
    import ctypes

    xids = []

    def collect(widget):
        try:
            xids.append(widget.winfo_id())
        except Exception:
            pass
        for child in widget.winfo_children():
            collect(child)

    tk_win.update_idletasks()
    collect(tk_win)

    # Also include the Tk wrapper window (parent of the Toplevel XID)
    try:
        libX11 = ctypes.cdll.LoadLibrary('libX11.so.6')
        libX11.XOpenDisplay.restype = ctypes.c_void_p
        disp = libX11.XOpenDisplay(None)
        if disp:
            libX11.XQueryTree.restype = ctypes.c_int
            libX11.XQueryTree.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong),  # root_return
                ctypes.POINTER(ctypes.c_ulong),  # parent_return
                ctypes.POINTER(ctypes.c_void_p), # children_return
                ctypes.POINTER(ctypes.c_uint),   # nchildren_return
            ]
            root_ret = ctypes.c_ulong(0)
            parent_ret = ctypes.c_ulong(0)
            children_ret = ctypes.c_void_p(0)
            nchildren_ret = ctypes.c_uint(0)
            top_xid = tk_win.winfo_id()
            libX11.XQueryTree(disp, top_xid,
                              ctypes.byref(root_ret), ctypes.byref(parent_ret),
                              ctypes.byref(children_ret), ctypes.byref(nchildren_ret))
            root_xid = root_ret.value
            wrapper_xid = parent_ret.value
            if children_ret.value:
                libX11.XFree(children_ret)
            if wrapper_xid and wrapper_xid != root_xid and wrapper_xid not in xids:
                xids.append(wrapper_xid)
            libX11.XCloseDisplay(disp)
    except Exception:
        pass

    return xids


def _set_clickthrough_x11(tk_win, enabled: bool):
    """Enable or disable X11 input pass-through via SHAPE/ctypes."""
    try:
        xids = _get_all_xids(tk_win)
        if enabled:
            tk_win.after(100, lambda: _apply_shape_ctypes(xids))
        else:
            tk_win.after(100, lambda: _reset_shape_ctypes(xids))
    except Exception as e:
        print(f"Click-through not available: {e}")


def _apply_shape_ctypes(xids):
    """Apply empty ShapeInput region to windows (enables click-through) via ctypes."""
    try:
        import ctypes
        libX11 = ctypes.cdll.LoadLibrary('libX11.so.6')
        libXext = ctypes.cdll.LoadLibrary('libXext.so.6')

        libX11.XOpenDisplay.restype = ctypes.c_void_p
        disp = libX11.XOpenDisplay(None)
        if not disp:
            print("Click-through: could not open display")
            return

        # XShapeCombineRectangles(display, dest, dest_kind=ShapeInput(2),
        #                         x_off, y_off, rects, n_rects, op=ShapeSet(0), ordering=0)
        libXext.XShapeCombineRectangles.restype = None
        libXext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        for xid in xids:
            libXext.XShapeCombineRectangles(disp, xid, 2, 0, 0, None, 0, 0, 0)

        libX11.XSync(disp, 0)
        libX11.XCloseDisplay(disp)
    except Exception as e:
        print(f"Click-through apply failed: {e}")


def _reset_shape_ctypes(xids):
    """Remove ShapeInput restriction from windows (disables click-through) via ctypes."""
    try:
        import ctypes
        libX11 = ctypes.cdll.LoadLibrary('libX11.so.6')
        libXext = ctypes.cdll.LoadLibrary('libXext.so.6')

        libX11.XOpenDisplay.restype = ctypes.c_void_p
        disp = libX11.XOpenDisplay(None)
        if not disp:
            return

        # XShapeCombineMask(display, dest, dest_kind=ShapeInput(2),
        #                   x_off, y_off, src=None(resets to full), op=ShapeSet(0))
        libXext.XShapeCombineMask.restype = None
        libXext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_int,
        ]
        for xid in xids:
            libXext.XShapeCombineMask(disp, xid, 2, 0, 0, 0, 0)  # src=None resets region

        libX11.XSync(disp, 0)
        libX11.XCloseDisplay(disp)
    except Exception as e:
        print(f"Click-through reset failed: {e}")


class MapOverlay(tk.Toplevel):
    """Transparent overlay window for the map with survey dots."""
    _BG_STIPPLES = [
        (0.20, 'gray12'),
        (0.40, 'gray25'),
        (0.60, 'gray50'),
        (0.80, 'gray75'),
    ]
    _TRANSPARENT_COLOR = '#ff00ff'
    
    def __init__(self, parent, settings: SurveySettings, on_click_callback=None, on_close=None):
        super().__init__(parent)
        self.settings = settings
        self.on_click_callback = on_click_callback
        self.on_close_callback = on_close
        
        self.title("Survey Map")
        self.attributes('-topmost', True)
        # Overlays bypass WM entirely — custom drag/resize handles all positioning.
        # This prevents the WM from shifting the window on withdraw/deiconify.
        self.overrideredirect(True)

        # Title bar for dragging
        self._title_bar = tk.Frame(self, bg=UI_COLORS["secondary"], height=18, cursor='fleur')
        self._title_bar.pack(fill='x', side='top')
        tk.Label(self._title_bar, text="⊹ Map", bg=UI_COLORS["secondary"],
                 fg=UI_COLORS["muted_text"], font=(UI_ATTRS["font_family"], 7)).pack(side='left', padx=4)
        tk.Button(self._title_bar, text="✕", bg=UI_COLORS["secondary"], fg=UI_COLORS["muted_text"],
                  relief='flat', bd=0, font=(UI_ATTRS["font_family"], 7),
                  command=self._close_window).pack(side='right', padx=2)

        # Route nav bar (hidden until route is active)
        self._nav_bar = tk.Frame(self, bg=UI_COLORS["card_bg"], height=24)
        # Not packed initially — shown by show_nav_bar()
        _nbtn = dict(bg=UI_COLORS["secondary"], fg=UI_COLORS["text"],
                     relief='flat', bd=1, font=(UI_ATTRS["font_family"], 7),
                     activebackground=UI_COLORS["accent"])
        self._nav_prev_btn = tk.Button(self._nav_bar, text="◀ Prev", **_nbtn)
        self._nav_prev_btn.pack(side='left', padx=2, pady=1)
        self._nav_next_btn = tk.Button(self._nav_bar, text="Next ▶", **_nbtn)
        self._nav_next_btn.pack(side='left', padx=2, pady=1)
        self._nav_skip_btn = tk.Button(self._nav_bar, text="Skip", **_nbtn)
        self._nav_skip_btn.pack(side='left', padx=2, pady=1)
        self._nav_label = tk.Label(self._nav_bar, text="", bg=UI_COLORS["card_bg"],
                                   fg=UI_COLORS["text"], font=(UI_ATTRS["font_family"], 7))
        self._nav_label.pack(side='left', padx=4)
        self._nav_bar_visible = False

        self._supports_isolated_background = False
        self.configure(bg=self._TRANSPARENT_COLOR)

        # Canvas for drawing — background opacity is handled separately when the
        # platform supports transparent-color windows.
        self.canvas = tk.Canvas(self, bg=self._TRANSPARENT_COLOR, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Items to display
        self.survey_items: List[SurveyItem] = []
        self.player_dot = None
        self.scale_indicator = None
        
        # Dragging
        self._drag_data = {'x': 0, 'y': 0}
        self._is_setting_position = False
        self._item_drag = None
        self._player_drag = None
        
        # Skip Configure events during initialization
        self._skip_configure = True
        
        # Bind drag to title bar (left-click) and canvas (right-click fallback)
        self._bind_drag(self._title_bar)
        self.canvas.bind('<Button-3>', self._start_drag)
        self.canvas.bind('<B3-Motion>', self._on_drag)
        self.bind('<Configure>', self._on_resize)
        
        # Resize handle (also binds canvas Button-1 via _create_resize_handle)
        self._create_resize_handle()
        
        # Close handler to save position/size
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Restore position/size
        if self.settings.map_position and self.settings.map_size:
            # Combine geometry call: WIDTHxHEIGHT+X+Y
            self.geometry(f"{self.settings.map_size[0]}x{self.settings.map_size[1]}"
                         f"+{self.settings.map_position[0]}+{self.settings.map_position[1]}")
        elif self.settings.map_position:
            self.geometry(f"+{self.settings.map_position[0]}+{self.settings.map_position[1]}")
        elif self.settings.map_size:
            self.geometry(f"{self.settings.map_size[0]}x{self.settings.map_size[1]}")
        else:
            self.geometry("400x400")
        
        # Apply opacity once window is actually mapped on X11 (after(1) fires too early)
        self.bind('<Map>', self._on_first_map)
        self.after(500, self._enable_configure_tracking_and_opacity)

    def _try_enable_isolated_background(self) -> bool:
        """Enable transparent-color mode if the platform supports it."""
        try:
            self.wm_attributes('-transparentcolor', self._TRANSPARENT_COLOR)
            self._supports_isolated_background = True
        except tk.TclError:
            self._supports_isolated_background = False
            self.configure(bg='black')
            self.canvas.config(bg='black')
        return self._supports_isolated_background
    
    def _on_first_map(self, event=None):
        """Apply opacity as soon as the window is mapped by the compositor."""
        self.unbind('<Map>')
        if self._try_enable_isolated_background():
            self.attributes('-alpha', 1.0)
            self._apply_background_opacity()
        else:
            self.attributes('-alpha', self.settings.map_opacity)

    def _bind_drag(self, widget):
        """Recursively bind left-click drag to widget and its children."""
        widget.bind('<Button-1>', self._start_drag)
        widget.bind('<B1-Motion>', self._on_drag)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _create_resize_handle(self):
        """Draw a visible resize corner on the canvas and handle resize via canvas events."""
        self._resize_zone = 30  # px from bottom-right corner of canvas
        self._resize_start = None
        self._draw_resize_corner()
        # Bind canvas left-click: resize zone takes priority over item clicks
        self.canvas.bind('<Button-1>', self._on_canvas_press)
        self.canvas.bind('<B1-Motion>', self._on_canvas_motion)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)

    def _draw_resize_corner(self):
        """Draw a small grip indicator in the bottom-right of the canvas."""
        self.canvas.delete('resize_corner')
        w = self.canvas.winfo_width() or 400
        h = self.canvas.winfo_height() or 400
        sz = self._resize_zone
        color = UI_COLORS.get("muted_text", "#888888")
        # Draw 3 diagonal lines as a grip
        for i in range(3):
            offset = 4 + i * 5
            self.canvas.create_line(w - offset, h, w, h - offset,
                                    fill=color, width=1, tags='resize_corner')
        self.canvas.tag_raise('resize_corner')

    def _on_canvas_press(self, event):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        sz = self._resize_zone
        if event.x >= cw - sz and event.y >= ch - sz:
            self._resize_start = {'x': event.x_root, 'y': event.y_root,
                                  'w': self.winfo_width(), 'h': self.winfo_height()}
        else:
            self._resize_start = None
            if self._is_over_player_dot(event.x, event.y) and not self._is_setting_position:
                self._player_drag = {'x': event.x, 'y': event.y}
                self._item_drag = None
            else:
                self._player_drag = None
                item_index = self._find_item_index_at(event.x, event.y)
                if item_index is not None and not self._is_setting_position:
                    self._item_drag = {'index': item_index, 'x': event.x, 'y': event.y}
                else:
                    self._item_drag = None
                    self._on_click(event)

    def _on_canvas_motion(self, event):
        if self._resize_start:
            dx = event.x_root - self._resize_start['x']
            dy = event.y_root - self._resize_start['y']
            new_w = max(100, self._resize_start['w'] + dx)
            new_h = max(100, self._resize_start['h'] + dy)
            self.geometry(f"{new_w}x{new_h}")
            self._draw_resize_corner()
        elif self._player_drag:
            dx = event.x - self._player_drag['x']
            dy = event.y - self._player_drag['y']
            if dx or dy:
                self.canvas.move('player', dx, dy)
                self._player_drag['x'] = event.x
                self._player_drag['y'] = event.y
                x, y = self._player_center_from_canvas()
                if x is not None and y is not None and self.on_click_callback:
                    self.on_click_callback(x, y, 'player_preview_moved')
        elif self._item_drag:
            dx = event.x - self._item_drag['x']
            dy = event.y - self._item_drag['y']
            if dx or dy:
                item_index = self._item_drag['index']
                self.canvas.move(f'item_{item_index}', dx, dy)
                item = self.survey_items[item_index]
                item.x += dx
                item.y += dy
                self._item_drag['x'] = event.x
                self._item_drag['y'] = event.y
                if self.on_click_callback:
                    self.on_click_callback(item.x, item.y, 'item_preview_moved', item_index)

    def _on_canvas_release(self, event):
        self._resize_start = None
        if self._player_drag:
            self._player_drag = None
            x, y = self._player_center_from_canvas()
            if x is not None and y is not None and self.on_click_callback:
                self.on_click_callback(x, y, 'player_dragged')
        if self._item_drag:
            item_index = self._item_drag['index']
            item = self.survey_items[item_index]
            self._item_drag = None
            if self.on_click_callback:
                self.on_click_callback(item.x, item.y, 'item_dragged', item_index)

    def _is_over_player_dot(self, x: float, y: float) -> bool:
        """Return True when the pointer is over the drawn player marker."""
        for canvas_item in self.canvas.find_overlapping(x - 8, y - 8, x + 8, y + 8):
            if 'player' in self.canvas.gettags(canvas_item):
                return True
        return False

    def _player_center_from_canvas(self) -> Tuple[Optional[float], Optional[float]]:
        """Return the current player marker center from the canvas."""
        coords = self.canvas.coords('player')
        if len(coords) == 4:
            return ((coords[0] + coords[2]) / 2.0, (coords[1] + coords[3]) / 2.0)
        return (None, None)

    def _find_item_index_at(self, x: float, y: float) -> Optional[int]:
        """Find a survey item index near the given canvas position."""
        items = self.canvas.find_overlapping(x - 12, y - 12, x + 12, y + 12)
        for canvas_item in items:
            item_index = self._extract_item_index(self.canvas.gettags(canvas_item))
            if item_index is not None:
                return item_index
        return None

    @staticmethod
    def _extract_item_index(tags) -> Optional[int]:
        """Extract an item index from a canvas tag tuple."""
        for tag in tags:
            if tag.startswith('item_') and tag.count('_') == 1:
                try:
                    return int(tag.split('_')[1])
                except ValueError:
                    return None
        return None

    def _enable_configure_tracking(self):
        """Enable Configure event tracking after window initialization."""
        self._skip_configure = False
    
    def _enable_configure_tracking_and_opacity(self):
        """Enable Configure tracking and apply opacity after window settles."""
        self._skip_configure = False
        if self._supports_isolated_background:
            self.attributes('-alpha', 1.0)
            self._apply_background_opacity()
        else:
            self.attributes('-alpha', self.settings.map_opacity)
        if self.settings.map_clickthrough:
            self.set_clickthrough(True)

    def _background_stipple_for_opacity(self, value: float) -> str:
        """Choose a stipple density for the dimming layer."""
        for threshold, stipple in self._BG_STIPPLES:
            if value <= threshold:
                return stipple
        return ''

    def _apply_background_opacity(self):
        """Apply the user opacity setting to the map background layer only."""
        if not self._supports_isolated_background:
            return
        self.canvas.delete('map_bg')
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        stipple = self._background_stipple_for_opacity(self.settings.map_opacity)
        if self.settings.map_opacity > 0:
            self.canvas.create_rectangle(
                0, 0, width, height,
                fill='black',
                outline='',
                stipple=stipple,
                tags='map_bg'
            )
            self.canvas.tag_lower('map_bg')
        # Keep all markers fully opaque above the dimming layer.
        for tag in ('survey_item', 'route_viz', 'player', 'resize_corner'):
            self.canvas.tag_raise(tag)
    
    def _on_resize(self, event):
        """Handle Configure events - save position/size when window changes."""
        # Skip Configure events during initialization
        if self._skip_configure:
            return
        
        # Only save position/size if window has reasonable dimensions
        # (avoid saving during destruction or minimization)
        width = self.winfo_width()
        height = self.winfo_height()
        if width > 50 and height > 50:
            # Use the actual geometry string to avoid coordinate offset issues
            geom = self.wm_geometry()
            w, h, x, y = parse_geometry(geom)
            if w and h:
                self.settings.map_position = (x, y)
                self.settings.map_size = (w, h)
                self.settings.save()
            self._apply_background_opacity()
            self._draw_resize_corner()
    
    def _on_click(self, event):
        if self._is_setting_position:
            # Setting player position
            self.settings.origin_x = event.x
            self.settings.origin_y = event.y
            self.settings.current_player_x = event.x
            self.settings.current_player_y = event.y
            self._is_setting_position = False
            self._draw_player_dot()
            if self.on_click_callback:
                self.on_click_callback(event.x, event.y, 'set_origin')
        else:
            # Check if clicked on an item
            item_index = self._find_item_index_at(event.x, event.y)
            if item_index is not None and self.on_click_callback:
                self.on_click_callback(event.x, event.y, 'item_clicked', item_index)
    
    def _start_drag(self, event):
        self._drag_data['x'] = event.x_root - self.winfo_x()
        self._drag_data['y'] = event.y_root - self.winfo_y()
    
    def _on_drag(self, event):
        x = event.x_root - self._drag_data['x']
        y = event.y_root - self._drag_data['y']
        self.geometry(f"+{x}+{y}")
        # Read back the actual geometry to account for window manager adjustments
        geom = self.wm_geometry()
        w, h, actual_x, actual_y = parse_geometry(geom)
        if actual_x is not None and actual_y is not None:
            self.settings.map_position = (actual_x, actual_y)
        self.settings.save()
    
    def set_setting_position_mode(self, enabled: bool):
        """Enable/disable position setting mode."""
        self._is_setting_position = enabled
        if enabled:
            self.canvas.config(cursor='crosshair')
        else:
            self.canvas.config(cursor='')
    
    def _draw_player_dot(self):
        """Draw the player position dot."""
        if self.player_dot:
            self.canvas.delete(self.player_dot)
        
        x = self.settings.current_player_x if self.settings.current_player_x is not None else self.settings.origin_x
        y = self.settings.current_player_y if self.settings.current_player_y is not None else self.settings.origin_y
        if x is not None and y is not None:
            self.player_dot = self.canvas.create_oval(
                x-5, y-5, x+5, y+5,
                fill=UI_COLORS["accent"], outline=UI_COLORS["text"], width=2,
                tags='player'
            )
    
    def add_survey_item(self, item: SurveyItem) -> bool:
        """Add a survey item to the map. Returns True if placed automatically."""
        if self.settings.scale_factor is None or self.settings.origin_x is None:
            return False
        
        if item.dx_m is not None and item.dy_m is not None:
            # Use direct meter offsets (east=+x, north=-y in canvas coords)
            item.x = self.settings.origin_x + item.dx_m * self.settings.scale_factor
            item.y = self.settings.origin_y - item.dy_m * self.settings.scale_factor
        else:
            angle = self._direction_to_angle(item.direction)
            dx = item.distance * math.cos(angle) * self.settings.scale_factor
            dy = item.distance * math.sin(angle) * self.settings.scale_factor
            item.x = self.settings.origin_x + dx
            item.y = self.settings.origin_y - dy
        
        self.survey_items.append(item)
        self._draw_item(item, len(self.survey_items) - 1)
        return True
    
    def _direction_to_angle(self, direction: str) -> float:
        """Convert direction to angle in radians (0 = East, CCW)."""
        angles = {
            'E': 0, 'NE': math.pi/4, 'N': math.pi/2, 'NW': 3*math.pi/4,
            'W': math.pi, 'SW': 5*math.pi/4, 'S': 3*math.pi/2, 'SE': 7*math.pi/4
        }
        return angles.get(direction, 0)
    
    def _draw_item(self, item: SurveyItem, index: int):
        """Draw a survey item on the map."""
        color = UI_COLORS["primary"] if not item.collected else UI_COLORS["muted_text"]
        dot_radius = 12
        
        # Dot
        self.canvas.create_oval(
            item.x-dot_radius, item.y-dot_radius, item.x+dot_radius, item.y+dot_radius,
            fill=color, outline=UI_COLORS["text"], width=2,
            tags=('survey_item', f'item_{index}', f'item_dot_{index}')
        )
        
        # Label
        self.canvas.create_text(
            item.x, item.y-15,
            text=f"{index+1}. {item.name[:15]}",
            fill=UI_COLORS["text"], font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"]-2), 'bold'),
            tags=('survey_item', f'item_{index}', f'item_label_{index}')
        )
        
        # Distance line
        if self.settings.origin_x:
            self.canvas.create_line(
                self.settings.origin_x, self.settings.origin_y,
                item.x, item.y,
                fill=UI_COLORS["accent"], dash=(3, 3), width=1,
                tags=('survey_item', f'item_{index}', f'item_line_{index}')
            )
    
    def calibrate_from_click(self, item_index: int, click_x: float, click_y: float):
        """Calibrate scale factor from a known item click."""
        if item_index >= len(self.survey_items):
            return
        
        item = self.survey_items[item_index]
        
        # Calculate distance in pixels
        pixel_dist = math.sqrt((click_x - self.settings.origin_x)**2 + 
                               (click_y - self.settings.origin_y)**2)
        
        # Calculate scale factor (pixels per meter)
        if item.distance > 0:
            self.settings.scale_factor = pixel_dist / item.distance
            self.settings.save()
            
            # Recalculate all item positions
            self.clear_items()
            for i, si in enumerate(self.survey_items):
                angle = self._direction_to_angle(si.direction)
                dx = si.distance * math.cos(angle) * self.settings.scale_factor
                dy = si.distance * math.sin(angle) * self.settings.scale_factor
                si.x = self.settings.origin_x + dx
                si.y = self.settings.origin_y - dy
                self._draw_item(si, i)
    
    def clear_items(self):
        """Clear all survey items from the map."""
        self.canvas.delete('survey_item')
    
    def mark_collected(self, index: int):
        """Mark an item as collected."""
        if 0 <= index < len(self.survey_items):
            self.survey_items[index].collected = True
            # Redraw as gray
            self.canvas.itemconfig(f'item_dot_{index}', fill='gray')
    
    def highlight_next(self, index: int):
        """Highlight the next item to collect (legacy — route pins handle this now)."""
        pass  # Route visualization via draw_route() handles highlighting

    def draw_route(self, route: List[int], current_index: int = 0,
                   items: Optional[List['SurveyItem']] = None):
        """Draw numbered pins and connecting arrows for the optimized route.

        Args:
            route: ordered list of item indices (indices into `items`)
            current_index: position in route that is the current stop
            items: the authoritative SurveyItem list from SurveyHelperWindow;
                   falls back to self.survey_items if not provided (legacy)
        """
        self.canvas.delete('route_viz')
        if not route:
            return

        source = items if items is not None else self.survey_items

        # Build ordered (x, y, item_idx, item) list strictly from authoritative
        # survey coordinates. Do not read canvas object positions here.
        stops = []
        for item_idx in route:
            if item_idx < len(source):
                item = source[item_idx]
                if item.x != 0.0 or item.y != 0.0:
                    stops.append((item.x, item.y, item_idx, item))

        if not stops:
            return

        # Draw connecting arrows between stops in route order
        for i in range(len(stops) - 1):
            x1, y1 = stops[i][0], stops[i][1]
            x2, y2 = stops[i + 1][0], stops[i + 1][1]
            # Shadow line (black, wider)
            self.canvas.create_line(
                x1, y1, x2, y2,
                fill='black', width=5, dash=(8, 4),
                tags='route_viz'
            )
            # Visible colored line on top
            self.canvas.create_line(
                x1, y1, x2, y2,
                fill='#ffcc00', width=2, dash=(8, 4),
                arrow=tk.LAST, arrowshape=(12, 14, 5),
                tags='route_viz'
            )

        # Draw numbered pins (on top of arrows)
        for route_pos, (x, y, item_idx, item) in enumerate(stops):
            is_current = (route_pos == current_index)

            if item.collected:
                pin_fill = '#555555'
                pin_outline = '#888888'
                text_color = '#cccccc'
                head_radius = 10
            elif is_current:
                pin_fill = '#00ff88'
                pin_outline = 'white'
                text_color = '#000000'
                head_radius = 14
            else:
                pin_fill = '#ffcc00'
                pin_outline = 'white'
                text_color = '#000000'
                head_radius = 12

            tip_y = y
            head_center_y = tip_y - head_radius - 6
            shadow_offset = 2

            # Black shadow for contrast and a visible anchored tip.
            self.canvas.create_polygon(
                x, tip_y + shadow_offset,
                x - 7, head_center_y + 6 + shadow_offset,
                x + 7, head_center_y + 6 + shadow_offset,
                fill='black', outline='',
                tags='route_viz'
            )
            self.canvas.create_oval(
                x - head_radius - shadow_offset, head_center_y - head_radius - shadow_offset,
                x + head_radius + shadow_offset, head_center_y + head_radius + shadow_offset,
                fill='black', outline='', width=0,
                tags='route_viz'
            )

            # Pin body anchored so the tip sits exactly on the survey point.
            self.canvas.create_polygon(
                x, tip_y,
                x - 6, head_center_y + 5,
                x + 6, head_center_y + 5,
                fill=pin_fill, outline=pin_outline, width=2,
                tags='route_viz'
            )
            self.canvas.create_oval(
                x - head_radius, head_center_y - head_radius,
                x + head_radius, head_center_y + head_radius,
                fill=pin_fill, outline=pin_outline, width=2,
                tags='route_viz'
            )
            # Number label
            self.canvas.create_text(
                x, head_center_y,
                text=str(route_pos + 1),
                fill=text_color,
                font=(UI_ATTRS["font_family"], max(8, head_radius - 2), 'bold'),
                tags='route_viz'
            )

        self.canvas.tag_raise('route_viz')

    def clear_route(self):
        """Remove route visualization."""
        self.canvas.delete('route_viz')
        self.hide_nav_bar()

    def show_nav_bar(self, prev_cmd, next_cmd, skip_cmd, label: str = ""):
        """Show route navigation bar below title bar."""
        self._nav_prev_btn.config(command=prev_cmd)
        self._nav_next_btn.config(command=next_cmd)
        self._nav_skip_btn.config(command=skip_cmd)
        self._nav_label.config(text=label)
        if not self._nav_bar_visible:
            self._nav_bar.pack(fill='x', side='top', before=self.canvas)
            self._nav_bar_visible = True

    def hide_nav_bar(self):
        """Hide route navigation bar."""
        if self._nav_bar_visible:
            self._nav_bar.pack_forget()
            self._nav_bar_visible = False

    def update_nav_label(self, label: str):
        """Update the nav bar info label."""
        self._nav_label.config(text=label)

    def update_opacity(self, value: float):
        """Update window opacity."""
        self.settings.map_opacity = value
        if self._supports_isolated_background:
            self.attributes('-alpha', 1.0)
            self._apply_background_opacity()
        else:
            self.attributes('-alpha', value)
        self.settings.save()
    
    def set_clickthrough(self, enabled: bool):
        """Set click-through mode."""
        self.settings.map_clickthrough = enabled
        if sys.platform == 'win32':
            self.attributes('-transparentcolor', 'black' if enabled else '')
        else:
            _set_clickthrough_x11(self, enabled)
        self.settings.save()
    
    def _close_window(self):
        """Save map position then close."""
        try:
            geom = self.wm_geometry()
            w, h, x, y = parse_geometry(geom)
            if x is not None:
                self.settings.map_position = (x, y)
            if w:
                self.settings.map_size = (w, h)
        except Exception:
            pass
        self.settings.save()
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()
    
    def _on_close(self):
        """Handle window close event - save position/size before closing."""
        self._close_window()


class InventoryOverlay(tk.Toplevel):
    """Transparent overlay window for inventory grid."""
    
    def __init__(self, parent, settings: SurveySettings, on_close=None, next_callback=None, activate_callback=None):
        super().__init__(parent)
        self.settings = settings
        self.on_close_callback = on_close
        self.next_callback = next_callback  # Called when Next button on overlay is clicked
        self.activate_callback = activate_callback
        
        self.title("Survey Inventory")
        self.attributes('-topmost', True)
        # Overlays bypass WM entirely — custom drag/resize handles all positioning.
        self.overrideredirect(True)

        # Title bar for dragging
        self._title_bar = tk.Frame(self, bg=UI_COLORS["secondary"], height=18, cursor='fleur')
        self._title_bar.pack(fill='x', side='top')
        tk.Label(self._title_bar, text="⊹ Inventory", bg=UI_COLORS["secondary"],
                 fg=UI_COLORS["muted_text"], font=(UI_ATTRS["font_family"], 7)).pack(side='left', padx=4)
        tk.Button(self._title_bar, text="✕", bg=UI_COLORS["secondary"], fg=UI_COLORS["muted_text"],
                  relief='flat', bd=0, font=(UI_ATTRS["font_family"], 7),
                  command=self._close_window).pack(side='right', padx=2)

        self.canvas = tk.Canvas(self, bg=UI_COLORS["card_bg"], highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Dragging
        self._drag_data = {'x': 0, 'y': 0}
        
        # Skip Configure events during initialization
        self._skip_configure = True
        
        # Bind drag to title bar (left-click) and canvas (right-click fallback)
        self._bind_drag(self._title_bar)
        self.canvas.bind('<Button-3>', self._start_drag)
        self.canvas.bind('<B3-Motion>', self._on_drag)
        self.bind('<Configure>', self._on_resize)
        
        # Resize handle
        self._create_resize_handle()
        self.canvas.bind('<Double-Button-1>', self._on_canvas_double_click)
        
        # Close handler to save position/size
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Slots
        self.slots: List[int] = []  # Canvas item IDs
        self.filled_slots: set = set()
        self._route_order: List[int] = []  # route passed to show_route_order
        
        # Restore position/size
        if self.settings.inv_position and self.settings.inv_size:
            # Combine geometry call: WIDTHxHEIGHT+X+Y
            self.geometry(f"{self.settings.inv_size[0]}x{self.settings.inv_size[1]}"
                         f"+{self.settings.inv_position[0]}+{self.settings.inv_position[1]}")
        elif self.settings.inv_position:
            self.geometry(f"+{self.settings.inv_position[0]}+{self.settings.inv_position[1]}")
        elif self.settings.inv_size:
            self.geometry(f"{self.settings.inv_size[0]}x{self.settings.inv_size[1]}")
        else:
            self._calculate_size()
        
        self._draw_grid()
        
        # Apply opacity once window is actually mapped on X11
        self.bind('<Map>', self._on_first_map)
        self.after(500, self._enable_configure_tracking_and_opacity)
    
    def _on_first_map(self, event=None):
        """Apply opacity as soon as the window is mapped by the compositor."""
        self.unbind('<Map>')
        self.attributes('-alpha', self.settings.inv_opacity)

    def _bind_drag(self, widget):
        """Recursively bind left-click drag to widget and its children."""
        widget.bind('<Button-1>', self._start_drag)
        widget.bind('<B1-Motion>', self._on_drag)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _create_resize_handle(self):
        """Draw a visible resize corner on the canvas and handle resize via canvas events."""
        self._resize_zone = 30
        self._resize_start = None
        self._draw_resize_corner()
        self.canvas.bind('<Button-1>', self._on_canvas_press)
        self.canvas.bind('<B1-Motion>', self._on_canvas_motion)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)

    def _draw_resize_corner(self):
        """Draw a small grip indicator in the bottom-right of the canvas."""
        self.canvas.delete('resize_corner')
        w = self.canvas.winfo_width() or 200
        h = self.canvas.winfo_height() or 100
        color = UI_COLORS.get("muted_text", "#888888")
        for i in range(3):
            offset = 4 + i * 5
            self.canvas.create_line(w - offset, h, w, h - offset,
                                    fill=color, width=1, tags='resize_corner')
        self.canvas.tag_raise('resize_corner')

    def _on_canvas_press(self, event):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if event.x >= cw - self._resize_zone and event.y >= ch - self._resize_zone:
            self._resize_start = {'x': event.x_root, 'y': event.y_root,
                                  'w': self.winfo_width(), 'h': self.winfo_height()}
        else:
            self._resize_start = None

    def _on_canvas_motion(self, event):
        if self._resize_start:
            dx = event.x_root - self._resize_start['x']
            dy = event.y_root - self._resize_start['y']
            new_w = max(100, self._resize_start['w'] + dx)
            new_h = max(100, self._resize_start['h'] + dy)
            self.geometry(f"{new_w}x{new_h}")
            self._recalculate_grid()
            self._draw_resize_corner()

    def _on_canvas_release(self, event):
        self._resize_start = None

    def _on_canvas_double_click(self, event):
        if event.x >= self.canvas.winfo_width() - self._resize_zone and event.y >= self.canvas.winfo_height() - self._resize_zone:
            return
        slot_index = self._find_slot_index_at(event.x, event.y)
        if slot_index is not None and self.activate_callback:
            self.activate_callback(slot_index)

    def _find_slot_index_at(self, x: float, y: float) -> Optional[int]:
        """Return the slot index near the given canvas position."""
        for canvas_item in self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4):
            for tag in self.canvas.gettags(canvas_item):
                if tag.startswith('slot_'):
                    try:
                        return int(tag.split('_')[1])
                    except ValueError:
                        return None
        return None

    def _calculate_size(self):
        """Calculate window size based on grid settings."""
        cols = self.settings.grid_cols
        total_slots = self.settings.survey_count + self.settings.inv_offset
        rows = (total_slots + cols - 1) // cols if total_slots > 0 else 1
        
        width = cols * self.settings.slot_size + (cols - 1) * self.settings.slot_gap + 20
        height = rows * self.settings.slot_size + (rows - 1) * self.settings.slot_gap + 20
        
        self.geometry(f"{width}x{height}")
    
    def _recalculate_grid(self):
        """Recalculate slot size based on window size."""
        if self.settings.survey_count == 0:
            return
        
        cols = self.settings.grid_cols
        total_slots = self.settings.survey_count + self.settings.inv_offset
        rows = (total_slots + cols - 1) // cols
        
        # Calculate slot size to fit
        available_w = self.winfo_width() - 20
        available_h = self.winfo_height() - 20
        
        slot_w = (available_w - (cols - 1) * self.settings.slot_gap) // cols
        slot_h = (available_h - (rows - 1) * self.settings.slot_gap) // rows
        
        self.settings.slot_size = min(slot_w, slot_h, 50)
        self._draw_grid()
    
    def _draw_grid(self):
        """Draw the inventory grid."""
        self.canvas.delete('all')
        self.slots = []
        
        cols = self.settings.grid_cols
        count = max(self.settings.survey_count, 1)
        offset = self.settings.inv_offset
        total_slots = count + offset  # Include blank slots in calculation
        rows = (total_slots + cols - 1) // cols
        
        slot = self.settings.slot_size
        gap = self.settings.slot_gap
        
        for i in range(total_slots):
            row = i // cols
            col = i % cols
            
            x1 = 10 + col * (slot + gap)
            y1 = 10 + row * (slot + gap)
            x2 = x1 + slot
            y2 = y1 + slot
            
            # Skip blank slots at the beginning
            if i < offset:
                # Draw empty slot (grayed out)
                self.canvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=UI_COLORS["card_bg"], outline=UI_COLORS["entry_border"], width=1,
                    tags=f'blank_{i}'
                )
            else:
                item_idx = i - offset
                # Draw slot
                color = UI_COLORS["primary"] if item_idx in self.filled_slots else UI_COLORS["secondary"]
                outline = UI_COLORS["text"] if item_idx in self.filled_slots else UI_COLORS["muted_text"]
                
                rect = self.canvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=color, outline=outline, width=2,
                    tags=f'slot_{item_idx}'
                )
                
                # Add number
                self.canvas.create_text(
                    (x1 + x2) // 2, (y1 + y2) // 2,
                    text=str(item_idx + 1),
                    fill=UI_COLORS["text"],
                    font=(UI_ATTRS["font_family"], max(8, int(UI_ATTRS["font_size"] * 1.5)), 'bold')
                )
                
                self.slots.append(rect)
        # Redraw resize corner on top of everything
        if hasattr(self, '_resize_zone'):
            self._draw_resize_corner()
        # Re-apply route order badges if a route is active
        if hasattr(self, '_route_order') and self._route_order:
            self._apply_route_badges(self._route_order)

    def show_route_order(self, route: List[int]):
        """Overlay route-sequence badges on inventory slots."""
        self._route_order = route
        self._apply_route_badges(route)

    def clear_route_order(self):
        """Remove route-sequence badges."""
        self._route_order = []
        self.canvas.delete('route_badge')
        if hasattr(self, '_resize_zone'):
            self._draw_resize_corner()

    def _apply_route_badges(self, route: List[int]):
        """Draw small numbered badges showing route visit order on each slot."""
        self.canvas.delete('route_badge')
        if not route:
            return
        # Map item_idx -> 1-based route position
        order_map = {item_idx: pos + 1 for pos, item_idx in enumerate(route)}

        cols = self.settings.grid_cols
        offset = self.settings.inv_offset
        slot = self.settings.slot_size
        gap = self.settings.slot_gap
        margin = 10

        for item_idx, route_pos in order_map.items():
            if item_idx < 0 or item_idx >= self.settings.survey_count:
                continue
            i = item_idx + offset
            col = i % cols
            row = i // cols
            x1 = margin + col * (slot + gap)
            y1 = margin + row * (slot + gap)
            # Small circle badge in top-right corner of slot
            r = max(10, int((max(7, slot // 5)) * 1.5))
            bx = x1 + slot - r - 1
            by = y1 + r + 1
            self.canvas.create_oval(
                bx - r, by - r, bx + r, by + r,
                fill='#ffcc00', outline='#333333', width=1,
                tags='route_badge'
            )
            self.canvas.create_text(
                bx, by,
                text=str(route_pos),
                fill='#000000',
                font=(UI_ATTRS["font_family"], max(9, int(max(6, r - 1) * 1.5)), 'bold'),
                tags='route_badge'
            )

        self.canvas.tag_raise('route_badge')
        if hasattr(self, '_resize_zone'):
            self._draw_resize_corner()

    def _start_drag(self, event):
        self._drag_data['x'] = event.x_root - self.winfo_x()
        self._drag_data['y'] = event.y_root - self.winfo_y()
    
    def _on_drag(self, event):
        x = event.x_root - self._drag_data['x']
        y = event.y_root - self._drag_data['y']
        self.geometry(f"+{x}+{y}")
        # Read back the actual geometry to account for window manager adjustments
        geom = self.wm_geometry()
        w, h, actual_x, actual_y = parse_geometry(geom)
        if actual_x is not None and actual_y is not None:
            self.settings.inv_position = (actual_x, actual_y)
        self.settings.save()
    
    def _on_resize(self, event):
        """Handle Configure events - save position/size when window changes."""
        # Skip Configure events during initialization
        if self._skip_configure:
            return
        
        # Only save position/size if window has reasonable dimensions
        # (avoid saving during destruction or minimization)
        width = self.winfo_width()
        height = self.winfo_height()
        if width > 50 and height > 50:
            # Use the actual geometry string to avoid coordinate offset issues
            geom = self.wm_geometry()
            w, h, x, y = parse_geometry(geom)
            if w and h:
                self.settings.inv_position = (x, y)
                self.settings.inv_size = (w, h)
                self.settings.save()
            if hasattr(self, '_resize_zone'):
                self._draw_resize_corner()
    
    def _enable_configure_tracking(self):
        """Enable Configure event tracking after window initialization."""
        self._skip_configure = False
    
    def _enable_configure_tracking_and_opacity(self):
        """Enable Configure tracking and apply opacity after window settles."""
        self._skip_configure = False
        self.attributes('-alpha', self.settings.inv_opacity)
        if self.settings.inv_clickthrough:
            self.set_clickthrough(True)
    
    def set_survey_count(self, count: int):
        """Update the number of survey maps."""
        self.settings.survey_count = count
        self.filled_slots = set(range(count))
        self._draw_grid()
        self.settings.save()
    
    def mark_slot_filled(self, index: int):
        """Mark a slot as having a survey map."""
        if index >= 0:
            self.filled_slots.add(index)
            self.canvas.itemconfig(f'slot_{index}', fill='green', outline='white')
    
    def mark_slot_empty(self, index: int):
        """Mark a slot as empty (collected)."""
        if index in self.filled_slots:
            self.filled_slots.remove(index)
            self.canvas.itemconfig(f'slot_{index}', fill='darkgray', outline='gray')
    
    def highlight_next_slot(self, item_index: int):
        """Highlight the next-in-route slot with a bright border."""
        # Reset all survey slot outlines to their default state
        for idx in range(self.settings.survey_count):
            if idx in self.filled_slots:
                self.canvas.itemconfig(f'slot_{idx}', outline=UI_COLORS["text"], width=2)
            else:
                self.canvas.itemconfig(f'slot_{idx}', outline='gray', width=1)
        # Apply highlight to the target slot
        if 0 <= item_index < self.settings.survey_count:
            self.canvas.itemconfig(f'slot_{item_index}', outline='#00ff88', width=4)
        # Show/hide the Next button on the overlay
        self._draw_next_button(item_index)
    
    def _draw_next_button(self, item_index: int):
        """Draw (or refresh) the Next button at the top of the overlay canvas."""
        self.canvas.delete('next_btn')
        if item_index < 0 or item_index >= self.settings.survey_count:
            return
        w = self.winfo_width() or 200
        btn_x1, btn_y1, btn_x2, btn_y2 = 4, 2, w - 4, 22
        self.canvas.create_rectangle(
            btn_x1, btn_y1, btn_x2, btn_y2,
            fill=UI_COLORS["accent"], outline=UI_COLORS["text"], width=1,
            tags='next_btn'
        )
        self.canvas.create_text(
            (btn_x1 + btn_x2) // 2, (btn_y1 + btn_y2) // 2,
            text=f"✓ Done  —  Next Survey →",
            fill=UI_COLORS["bg"], font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], 'bold'),
            tags='next_btn'
        )
        self.canvas.tag_bind('next_btn', '<Button-1>', self._on_next_clicked)
    
    def _on_next_clicked(self, event=None):
        if self.next_callback:
            self.next_callback()
    
    def clear_all(self):
        """Clear all filled slots."""
        self.filled_slots.clear()
        self._draw_grid()
    
    def update_opacity(self, value: float):
        """Update window opacity."""
        self.attributes('-alpha', value)
        self.settings.inv_opacity = value
        self.settings.save()
    
    def set_clickthrough(self, enabled: bool):
        """Set click-through mode."""
        self.settings.inv_clickthrough = enabled
        if sys.platform == 'win32':
            self.attributes('-transparentcolor', 'black' if enabled else '')
        else:
            _set_clickthrough_x11(self, enabled)
        self.settings.save()
    
    def _close_window(self):
        """Save inventory position then close."""
        try:
            geom = self.wm_geometry()
            w, h, x, y = parse_geometry(geom)
            if x is not None:
                self.settings.inv_position = (x, y)
            if w:
                self.settings.inv_size = (w, h)
        except Exception:
            pass
        self.settings.save()
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()
    
    def _on_close(self):
        """Handle window close event - save position/size before closing."""
        self._close_window()


class SurveyHelperWindow(tk.Toplevel):
    """Main control panel for the Survey Helper."""

    # Items that can be gained from surveying (gems, metal slabs, glass, parchment)
    # Built dynamically from items.json at class load time.
    _SURVEY_LOOT_ITEMS: set = set()

    @classmethod
    def _build_survey_loot_set(cls):
        """Populate _SURVEY_LOOT_ITEMS from items.json."""
        if cls._SURVEY_LOOT_ITEMS:
            return  # already built
        try:
            import os
            items_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'items.json')
            with open(items_path, 'r', encoding='utf-8') as f:
                import json as _json
                items_data = _json.load(f)
            _EXCLUDE = {'Survey', 'Arrangement', 'Display', 'Bouquet', 'Orb', 'Pearl',
                        'Ring', 'Staff', 'Robe', 'Hood', 'Coat', 'Sword', 'Bow', 'Shield',
                        'Crossbow', 'Dagger', 'Medallion', 'Talisman', 'Work Order',
                        'Beaker', 'Jar', 'Collar', 'Necklace', 'Bracelet', 'Glove', 'Wand'}
            for v in items_data.values():
                name = v.get('Name', '')
                if not name or any(x in name for x in _EXCLUDE):
                    continue
                kws = v.get('Keywords', [])
                if (any(kw.startswith('Gem=') for kw in kws) or
                        any(kw.startswith('MetalSlab') for kw in kws) or
                        'GlassChunk' in kws or
                        'Parchment' in kws):
                    cls._SURVEY_LOOT_ITEMS.add(name)
        except Exception as e:
            print(f"Could not build survey loot set: {e}")

    def __init__(self, parent):
        super().__init__(parent)
        
        self.title("Survey Helper")
        self._build_survey_loot_set()
        
        self.settings = SurveySettings()
        self.items: List[SurveyItem] = []
        self.current_route: List[int] = []
        self.current_route_index = 0
        self.session_start: Optional[datetime] = None
        self.loot_gained: dict = {}  # item_name → count
        self.reset_time: Optional[datetime] = None  # ignore chat lines before this
        self._ring_detection_active = False
        self._ring_watch_stop = threading.Event()
        self._ring_detection_target: Optional[int] = None
        self.ring_watch_btn: Optional[ttk.Button] = None
        self.player_track_btn: Optional[ttk.Button] = None
        
        # Restore main window geometry or use default
        if self.settings.main_window_position and self.settings.main_window_size:
            self.geometry(f"{self.settings.main_window_size[0]}x{self.settings.main_window_size[1]}"
                         f"+{self.settings.main_window_position[0]}+{self.settings.main_window_position[1]}")
        elif self.settings.main_window_size:
            self.geometry(f"{self.settings.main_window_size[0]}x{self.settings.main_window_size[1]}")
        else:
            self.geometry("400x500")
        
        # Chat monitor
        self.chat_monitor: Optional[ChatLogMonitor] = None
        self._monitoring = False
        
        # Overlays
        self.map_overlay: Optional[MapOverlay] = None
        self.inv_overlay: Optional[InventoryOverlay] = None
        self.map_open = False
        self.inventory_open = False
        
        # Button references for toggle functionality
        self.map_button: Optional[ttk.Button] = None
        self.inv_button: Optional[ttk.Button] = None
        
        # Bind Configure event to save window size/position on changes
        self.bind('<Configure>', self._on_main_window_configure)
        
        # Apply PGLOK theme - this sets window background and TTK styles
        apply_theme(self)
        
        # Explicitly set window background to ensure it shows (not just frame)
        self.configure(bg=UI_COLORS["bg"])
        
        self._build_ui()
        self._restore_overlays()
        self._start_chat_monitor()
    
    def _build_ui(self):
        """Build the control panel UI."""
        frame = tk.Frame(self, bg=UI_COLORS["panel_bg"])
        frame.pack(fill='both', expand=True, padx=8, pady=8)
        
        # Title + always-on-top checkbox on same row
        title_row = tk.Frame(frame, bg=UI_COLORS["panel_bg"])
        title_row.pack(fill='x', pady=3)
        ttk.Label(title_row, text="🔍 Survey Helper", style="App.Header.TLabel").pack(side='left', padx=4)
        self.always_on_top_var = tk.BooleanVar(value=self.settings.always_on_top)
        ttk.Checkbutton(title_row, text="Always on Top", variable=self.always_on_top_var,
                        command=self._toggle_always_on_top, style="App.TCheckbutton").pack(side='right', padx=8)
        self.attributes('-topmost', self.settings.always_on_top)
        
        # ChatLog directory - use tk.LabelFrame with dark theme colors
        dir_frame = tk.LabelFrame(frame, text="ChatLogs Folder", padx=4, pady=3,
                                  bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"], 
                                  font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                  borderwidth=1, relief="solid")
        dir_frame.pack(fill='x', pady=3)
        
        self.dir_var = tk.StringVar(value=str(self.settings.chatlog_dir) if self.settings.chatlog_dir else "Not set")
        ttk.Label(dir_frame, textvariable=self.dir_var, wraplength=300, style="App.TLabel").pack(fill='x')
        dir_btn_row = tk.Frame(dir_frame, bg=UI_COLORS["panel_bg"])
        dir_btn_row.pack(fill='x', pady=1)
        ttk.Button(dir_btn_row, text="💬 Set Folder", command=self._set_chatlog_dir, style="App.Secondary.TButton").pack(side='left', padx=2)
        ttk.Button(dir_btn_row, text="🔄 Reset Session", command=self._reset_session, style="App.Secondary.TButton").pack(side='left', padx=2)
        
        # Survey count - use tk.LabelFrame with dark theme colors
        count_frame = tk.LabelFrame(frame, text="Survey Maps", padx=4, pady=3,
                                    bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                    font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                    borderwidth=1, relief="solid")
        count_frame.pack(fill='x', pady=3)
        
        self.count_var = tk.IntVar(value=self.settings.survey_count)
        ttk.Spinbox(count_frame, from_=0, to=100, textvariable=self.count_var, width=5, style="App.TSpinbox").pack(side='left', padx=4)
        ttk.Button(count_frame, text="Set Count", command=self._set_survey_count, style="App.Secondary.TButton").pack(side='left', padx=4)
        
        # Inventory arrangement - use tk.LabelFrame with dark theme colors
        arrange_frame = tk.LabelFrame(frame, text="Inventory Arrangement", padx=4, pady=3,
                                      bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                      font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                      borderwidth=1, relief="solid")
        arrange_frame.pack(fill='x', pady=3)
        
        ttk.Label(arrange_frame, text="Blank Spaces Before 1st Survey:", style="App.TLabel").pack(anchor='w')
        self.offset_var = tk.IntVar(value=self.settings.inv_offset)
        offset_spinbox = ttk.Spinbox(arrange_frame, from_=0, to=100, textvariable=self.offset_var, width=5, style="App.TSpinbox")
        offset_spinbox.pack(side='left', padx=4)
        
        # Grid sizing controls
        grid_frame = tk.Frame(arrange_frame, bg=UI_COLORS["panel_bg"])
        grid_frame.pack(fill='x', pady=2)
        
        ttk.Label(grid_frame, text="Columns:", style="App.TLabel").pack(side='left', padx=4)
        self.cols_var = tk.IntVar(value=self.settings.grid_cols)
        ttk.Spinbox(grid_frame, from_=1, to=20, textvariable=self.cols_var, width=3, 
                   style="App.TSpinbox", command=self._update_grid_calc).pack(side='left', padx=2)
        
        ttk.Label(grid_frame, text="Slot Size:", style="App.TLabel").pack(side='left', padx=4)
        self.slot_size_var = tk.IntVar(value=self.settings.slot_size)
        ttk.Spinbox(grid_frame, from_=20, to=80, textvariable=self.slot_size_var, width=3,
                   style="App.TSpinbox", command=self._update_grid_calc).pack(side='left', padx=2)
        
        ttk.Label(grid_frame, text="Gap:", style="App.TLabel").pack(side='left', padx=4)
        self.gap_var = tk.IntVar(value=self.settings.slot_gap)
        ttk.Spinbox(grid_frame, from_=0, to=20, textvariable=self.gap_var, width=3,
                   style="App.TSpinbox", command=self._update_grid_calc).pack(side='left', padx=2)
        
        ttk.Button(grid_frame, text="Apply All", command=self._apply_grid_settings, style="App.Secondary.TButton").pack(side='left', padx=2)
        
        # Overlay controls - use tk.LabelFrame with dark theme colors
        overlay_frame = tk.LabelFrame(frame, text="Overlays", padx=4, pady=3,
                                      bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                      font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                      borderwidth=1, relief="solid")
        overlay_frame.pack(fill='x', pady=3)
        
        btn_frame = tk.Frame(overlay_frame, bg=UI_COLORS["panel_bg"])
        btn_frame.pack(fill='x', pady=1)
        
        self.overlays_button = ttk.Button(btn_frame, text="🗺📦 Show Overlays", command=self._show_overlays, style="App.Secondary.TButton")
        self.overlays_button.pack(side='left', padx=2)
        
        self.map_clickthrough_var = tk.BooleanVar(value=self.settings.map_clickthrough)
        self.inv_clickthrough_var = tk.BooleanVar(value=self.settings.inv_clickthrough)
        self.lock_btn = ttk.Button(btn_frame, text="🔒 Lock Overlays: OFF", command=self._toggle_lock_overlays, style="App.Secondary.TButton")
        self.lock_btn.pack(side='left', padx=2)
        self._update_lock_btn()

        ttk.Button(btn_frame, text="💾 Save Layout", command=self._save_overlay_layout, style="App.Secondary.TButton").pack(side='left', padx=2)
        self.player_track_btn = ttk.Button(btn_frame, text="📍 Detect Player", command=self._detect_player_from_map, style="App.Secondary.TButton")
        self.player_track_btn.pack(side='left', padx=2)
        
        # Opacity controls
        opacity_frame = tk.Frame(overlay_frame, bg=UI_COLORS["panel_bg"])
        opacity_frame.pack(fill='x', pady=1)
        
        ttk.Label(opacity_frame, text="Inv Opacity %:", style="App.TLabel").pack(side='left', padx=4)
        self.inv_opacity_var = tk.IntVar(value=int(self.settings.inv_opacity * 100))
        self.inv_opacity_spinbox = ttk.Spinbox(opacity_frame, from_=10, to=100, textvariable=self.inv_opacity_var, width=5,
                   style="App.TSpinbox", command=self._update_inv_opacity)
        self.inv_opacity_spinbox.pack(side='left', padx=2)
        self.inv_opacity_spinbox.bind('<Return>', lambda e: self._update_inv_opacity())
        self.inv_opacity_spinbox.bind('<FocusOut>', lambda e: self._update_inv_opacity())
        
        ttk.Label(opacity_frame, text="Map Opacity %:", style="App.TLabel").pack(side='left', padx=4)
        self.map_opacity_var = tk.IntVar(value=int(self.settings.map_opacity * 100))
        self.map_opacity_spinbox = ttk.Spinbox(opacity_frame, from_=5, to=100, textvariable=self.map_opacity_var, width=5,
                   style="App.TSpinbox", command=self._update_map_opacity)
        self.map_opacity_spinbox.pack(side='left', padx=2)
        self.map_opacity_spinbox.bind('<Return>', lambda e: self._update_map_opacity())
        self.map_opacity_spinbox.bind('<FocusOut>', lambda e: self._update_map_opacity())
        
        # Route optimization - use tk.LabelFrame with dark theme colors
        route_frame = tk.LabelFrame(frame, text="Route Optimization", padx=4, pady=3,
                                    bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                    font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                    borderwidth=1, relief="solid")
        route_frame.pack(fill='x', pady=3)
        
        route_btn_frame = tk.Frame(route_frame, bg=UI_COLORS["panel_bg"])
        route_btn_frame.pack(fill='x', pady=1)
        ttk.Button(route_btn_frame, text="🗺 Optimize Route", command=self._optimize_route, style="App.Secondary.TButton").pack(side='left', padx=2)
        self.ring_watch_btn = ttk.Button(route_btn_frame, text="🔴 Watch Ring: OFF", command=self._toggle_ring_watch, style="App.Secondary.TButton")
        self.ring_watch_btn.pack(side='left', padx=2)
        ttk.Button(route_btn_frame, text="← Previous", command=self._prev_item, style="App.Secondary.TButton").pack(side='left', padx=2)
        ttk.Button(route_btn_frame, text="Next →", command=self._next_item, style="App.Secondary.TButton").pack(side='left', padx=2)
        ttk.Button(route_btn_frame, text="Skip", command=self._skip_item, style="App.Secondary.TButton").pack(side='left', padx=2)
        
        self.route_info_var = tk.StringVar(value="No route active")
        ttk.Label(route_frame, textvariable=self.route_info_var, style="App.TLabel").pack(pady=1)
        
        # Session info
        self.session_var = tk.StringVar(value="Items found: 0")
        ttk.Label(frame, textvariable=self.session_var, style="App.Title.TLabel").pack(pady=3)
        
        # Status
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var, style="App.Status.TLabel").pack(pady=1)
        
        # Phase indicator
        phase_outer = tk.LabelFrame(frame, text="Workflow", padx=4, pady=3,
                                    bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                    font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                    borderwidth=1, relief="solid")
        phase_outer.pack(fill='x', pady=3)
        self._phase_labels = []
        phase_row = tk.Frame(phase_outer, bg=UI_COLORS["panel_bg"])
        phase_row.pack(fill='x')
        phases = ["1.Zone", "2.Surveys", "3.Positions", "4.Optimize", "5.Route", "6.Done"]
        for i, text in enumerate(phases):
            lbl = tk.Label(phase_row, text=text, bg=UI_COLORS["panel_bg"],
                           fg=UI_COLORS["muted_text"],
                           font=(UI_ATTRS["font_family"], max(7, UI_ATTRS["font_size"]-1)))
            lbl.pack(side='left', padx=2, pady=1)
            self._phase_labels.append(lbl)
            if i < len(phases) - 1:
                tk.Label(phase_row, text="→", bg=UI_COLORS["panel_bg"],
                         fg=UI_COLORS["muted_text"],
                         font=(UI_ATTRS["font_family"], max(7, UI_ATTRS["font_size"]-1))).pack(side='left')
        self._set_phase(self.settings.current_phase)
        
        # Zone + Positions found
        self.zone_var = tk.StringVar(value=f"Zone: {self.settings.zone_name or 'Unknown'}")
        self.positions_var = tk.StringVar(value="Positions: 0 found")
        info_row = tk.Frame(frame, bg=UI_COLORS["panel_bg"])
        info_row.pack(fill='x', pady=1)
        ttk.Label(info_row, textvariable=self.zone_var, style="App.TLabel").pack(side='left', padx=6)
        ttk.Label(info_row, textvariable=self.positions_var, style="App.TLabel").pack(side='left', padx=6)
        
        # Positions list (scrollable)
        pos_frame = tk.LabelFrame(frame, text="Detected Positions", padx=4, pady=3,
                                  bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                  font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                  borderwidth=1, relief="solid")
        pos_frame.pack(fill='x', pady=3)
        self.positions_text = tk.Text(pos_frame, height=4, state='disabled',
                                      bg=UI_COLORS["card_bg"], fg=UI_COLORS["text"],
                                      font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"]-1)),
                                      relief='flat', wrap='none')
        pos_scroll = ttk.Scrollbar(pos_frame, orient='vertical', command=self.positions_text.yview)
        self.positions_text.configure(yscrollcommand=pos_scroll.set)
        pos_scroll.pack(side='right', fill='y')
        self.positions_text.pack(fill='x')
        
        # Loot summary
        loot_frame = tk.LabelFrame(frame, text="Loot Gained", padx=4, pady=3,
                                   bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                   font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                   borderwidth=1, relief="solid")
        loot_frame.pack(fill='x', pady=3)
        self.loot_text = tk.Text(loot_frame, height=4, state='disabled',
                                 bg=UI_COLORS["card_bg"], fg=UI_COLORS["text"],
                                 font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"]-1)),
                                 relief='flat', wrap='none')
        loot_scroll = ttk.Scrollbar(loot_frame, orient='vertical', command=self.loot_text.yview)
        self.loot_text.configure(yscrollcommand=loot_scroll.set)
        loot_scroll.pack(side='right', fill='y')
        self.loot_text.pack(fill='x')
        ttk.Button(loot_frame, text="📋 Copy Loot", command=self._copy_loot,
                   style="App.Secondary.TButton").pack(pady=2)
    
    def _set_chatlog_dir(self):
        """Set the chatlog directory."""
        from tkinter import filedialog
        
        dir_path = filedialog.askdirectory(title="Select ChatLogs Folder")
        if dir_path:
            self.settings.chatlog_dir = Path(dir_path)
            self.dir_var.set(dir_path)
            self.settings.save()
            self._start_chat_monitor()
    
    def _set_survey_count(self):
        """Set the number of survey maps."""
        count = max(0, self.count_var.get())
        self.count_var.set(count)
        self.settings.survey_count = count
        self.settings.save()
        
        if self.inv_overlay:
            self.inv_overlay.set_survey_count(count)
    
    def _set_inv_offset(self):
        """Set the inventory blank space offset."""
        offset = self.offset_var.get()
        self.settings.inv_offset = offset
        self.settings.save()
        
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay._draw_grid()  # Redraw with new offset
    
    def _update_grid_calc(self):
        """Update grid calculation (called on spinbox change)."""
        # Just update the variables, don't apply yet
        pass
    
    def _apply_grid_settings(self):
        """Apply all inventory arrangement settings (offset, columns, slot size, gap)."""
        self.settings.inv_offset = self.offset_var.get()
        self.settings.grid_cols = self.cols_var.get()
        self.settings.slot_size = self.slot_size_var.get()
        self.settings.slot_gap = self.gap_var.get()
        self.settings.save()
        
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay._draw_grid()
    
    def _show_overlays(self):
        """Toggle both map and inventory overlays open/closed."""
        both_open = self.map_open and self.inventory_open
        if both_open:
            if self.map_overlay and self.map_overlay.winfo_exists():
                self._save_overlay_position(self.map_overlay, 'map')
                self.map_overlay.withdraw()
            if self.inv_overlay and self.inv_overlay.winfo_exists():
                self._save_overlay_position(self.inv_overlay, 'inv')
                self.inv_overlay.withdraw()
            self.map_open = False
            self.inventory_open = False
        else:
            self._show_map()
            self._show_inventory()
        self._update_overlays_btn()

    def _save_overlay_position(self, overlay, kind: str):
        """Save the current WM position/size of an overlay before hiding it."""
        try:
            geom = overlay.wm_geometry()
            w, h, x, y = parse_geometry(geom)
            if kind == 'map':
                if x is not None:
                    self.settings.map_position = (x, y)
                if w:
                    self.settings.map_size = (w, h)
            else:
                if x is not None:
                    self.settings.inv_position = (x, y)
                if w:
                    self.settings.inv_size = (w, h)
            self.settings.save()
        except Exception:
            pass

    def _restore_overlay_geometry(self, overlay, kind: str):
        """Restore saved geometry after deiconify (WM may have shifted position)."""
        try:
            if kind == 'map':
                pos = self.settings.map_position
                size = self.settings.map_size
            else:
                pos = self.settings.inv_position
                size = self.settings.inv_size
            if pos and size:
                overlay.geometry(f"{size[0]}x{size[1]}+{pos[0]}+{pos[1]}")
            elif pos:
                overlay.geometry(f"+{pos[0]}+{pos[1]}")
        except Exception:
            pass

    def _show_map(self):
        """Open (or restore) the map overlay."""
        if self.map_open:
            return
        if self.map_overlay is None or not self.map_overlay.winfo_exists():
            self.map_overlay = MapOverlay(self, self.settings, self._on_map_click,
                                         on_close=self._on_map_closed)
        else:
            self.map_overlay.deiconify()
            self.map_overlay.lift()
            self.map_overlay.after(1, lambda: self.map_overlay.update_opacity(self.settings.map_opacity))
        self.map_open = True
        self.map_opacity_var.set(int(self.settings.map_opacity * 100))
        self._update_overlays_btn()

    def _show_inventory(self):
        """Open (or restore) the inventory overlay."""
        if self.inventory_open:
            return
        if self.inv_overlay is None or not self.inv_overlay.winfo_exists():
            self.inv_overlay = InventoryOverlay(self, self.settings,
                                               on_close=self._on_inv_closed,
                                               next_callback=self._on_inv_next_clicked,
                                               activate_callback=self._start_ring_detection_for_item)
            for i in range(self.settings.survey_count):
                self.inv_overlay.mark_slot_filled(i)
        else:
            self.inv_overlay.deiconify()
            self.inv_overlay.lift()
            self.inv_overlay.after(1, lambda: self.inv_overlay.attributes('-alpha', self.settings.inv_opacity))
        self.inventory_open = True
        self.inv_opacity_var.set(int(self.settings.inv_opacity * 100))
        self._update_overlays_btn()

    def _on_map_closed(self):
        """Called when map overlay is closed by user."""
        self.map_open = False
        self._update_overlays_btn()

    def _on_inv_closed(self):
        """Called when inventory overlay is closed by user."""
        self.inventory_open = False
        self._update_overlays_btn()

    def _update_overlays_btn(self):
        """Update show overlays button text."""
        if self.map_open and self.inventory_open:
            text = "🗺📦 Hide Overlays"
        elif self.map_open or self.inventory_open:
            text = "🗺📦 Hide Overlays"
        else:
            text = "🗺📦 Show Overlays"
        self.overlays_button.config(text=text)
    
    def _set_player_position(self):
        """Enable player position setting mode."""
        self._show_map()
        self.map_overlay.set_setting_position_mode(True)
        self.status_var.set("Click on map to set your position")

    @staticmethod
    def _median(values: List[float]) -> float:
        """Return the median of a non-empty numeric list."""
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    def _detect_player_from_map(self):
        """Capture the visible map once and detect the player marker."""
        if cv2 is None or np is None or ImageGrab is None:
            self.status_var.set("OpenCV/Pillow capture is not available")
            return
        self._show_map()
        if not (self.map_overlay and self.map_overlay.winfo_exists()):
            self.status_var.set("Open the map overlay first")
            return

        self.status_var.set("Detecting player marker from the visible map...")
        self._detect_player_once()

    def _capture_map_bbox(self) -> Optional[Tuple[int, int, int, int]]:
        """Return the screen bbox of the map overlay canvas."""
        if not (self.map_overlay and self.map_overlay.winfo_exists()):
            return None
        self.map_overlay.update_idletasks()
        canvas = self.map_overlay.canvas
        left = canvas.winfo_rootx()
        top = canvas.winfo_rooty()
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1 or height <= 1:
            return None
        return (left, top, left + width, top + height)

    @staticmethod
    def _detect_player_marker(frame_rgb, previous_center: Optional[Tuple[float, float]] = None,
                              previous_frame_gray=None) -> Optional[Tuple[float, float]]:
        """Detect the beige triangular player marker in a map screenshot."""
        if cv2 is None or np is None:
            return None

        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        frame_h, frame_w = frame_rgb.shape[:2]
        frame_center = (frame_w / 2.0, frame_h / 2.0)
        target = previous_center if previous_center is not None else frame_center
        ref_contour = np.array([[[13, 11]], [[12, 5]], [[3, 8]]], dtype=np.int32)
        best_center = None
        best_score = float('-inf')
        best_shape_match = float('inf')

        # The in-game player icon is a small beige triangle. Detect that contour
        # directly instead of looking for a generic moving colored blob.
        mask_ranges = [
            (np.array([0, 0, 78]), np.array([40, 110, 175])),
            (np.array([0, 0, 70]), np.array([48, 130, 190])),
        ]

        for lower, upper in mask_ranges:
            candidate_mask = cv2.inRange(hsv, lower, upper)
            candidate_mask = cv2.morphologyEx(
                candidate_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)
            )
            contours, _ = cv2.findContours(candidate_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < 18 or area > 110:
                    continue
                perimeter = cv2.arcLength(contour, True)
                if perimeter <= 0:
                    continue
                approx = cv2.approxPolyDP(contour, 0.06 * perimeter, True)
                if not 3 <= len(approx) <= 6:
                    continue

                moments = cv2.moments(contour)
                if moments["m00"] == 0:
                    continue
                center = (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])
                x, y, w, h = cv2.boundingRect(contour)
                hull = cv2.convexHull(contour)
                hull_area = cv2.contourArea(hull) or 1.0
                solidity = area / hull_area
                aspect_ratio = max(w, h, 1) / max(1, min(w, h))
                shape_match = cv2.matchShapes(ref_contour, approx, cv2.CONTOURS_MATCH_I1, 0.0)
                sat_mean = float(hsv[y:y + h, x:x + w, 1].mean())
                val_mean = float(hsv[y:y + h, x:x + w, 2].mean())
                distance = math.hypot(center[0] - target[0], center[1] - target[1])
                edge_margin = min(center[0], center[1], frame_w - center[0], frame_h - center[1])

                score = 240.0
                score -= shape_match * 320.0
                score -= abs(area - 39.0) * 1.1
                score -= abs(aspect_ratio - 1.55) * 18.0
                score -= abs(solidity - 0.88) * 28.0
                score -= abs(sat_mean - 54.0) * 0.35
                score -= abs(val_mean - 100.0) * 0.22
                score -= distance * (0.15 if previous_center is None else 0.35)
                score += min(edge_margin, 90.0) * 0.08
                if len(approx) == 3:
                    score += 28.0

                if score > best_score:
                    best_score = score
                    best_shape_match = shape_match
                    best_center = center

        if best_center is None:
            return None
        if best_shape_match > 0.4 or best_score < 120:
            return None

        return best_center

    def _apply_detected_player_marker(self, x: float, y: float):
        """Update the visible player marker from detected map coordinates."""
        self.settings.current_player_x = x
        self.settings.current_player_y = y
        if self.settings.origin_x is None or self.settings.origin_y is None:
            self.settings.origin_x = x
            self.settings.origin_y = y
        self.settings.save()
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay._draw_player_dot()

    def _detect_player_once(self):
        """Capture the map once and seed the player marker immediately."""
        bbox = self._capture_map_bbox()
        if bbox is None:
            self.status_var.set("Map overlay is not ready for player detection")
            return
        try:
            frame = ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:
            frame = ImageGrab.grab(bbox=bbox)
        except Exception as exc:
            self.status_var.set(f"Player detection failed: {exc}")
            return
        center = self._detect_player_marker(np.array(frame))
        if center is None:
            self.status_var.set("Could not find the player marker on the map")
            return
        self._apply_detected_player_marker(*center)
        self.status_var.set("Player marker detected from the visible map")

    def _start_ring_detection_for_current(self):
        """Arm ring watching for the current route item or first survey."""
        if self.current_route and self.current_route_index < len(self.current_route):
            self._start_ring_detection_for_item(self.current_route[self.current_route_index])
        elif self.items:
            self._start_ring_detection_for_item(0)
        else:
            self.status_var.set("No survey items available for ring detection")

    def _update_ring_watch_btn(self):
        """Refresh the persistent ring-watch button label."""
        if self.ring_watch_btn is not None:
            state = "ON" if self._ring_detection_active else "OFF"
            self.ring_watch_btn.config(text=f"🔴 Watch Ring: {state}")

    def _toggle_ring_watch(self):
        """Toggle persistent ring watching on or off."""
        if self._ring_detection_active:
            self._stop_ring_watch("Ring watch stopped")
        else:
            self._start_ring_watch()

    def _start_ring_watch(self):
        """Start the persistent ring watcher and arm the current survey if possible."""
        if cv2 is None or np is None or ImageGrab is None:
            self.status_var.set("OpenCV/Pillow capture is not available")
            return
        self._show_map()
        bbox = self._capture_map_bbox()
        if bbox is None:
            self.status_var.set("Map overlay is not ready for capture")
            return

        self._ring_watch_stop.clear()
        self._ring_detection_active = True
        self._update_ring_watch_btn()
        self.status_var.set("Ring watch running. Double-click a survey slot to arm it.")
        threading.Thread(target=self._ring_watch_worker, args=(bbox,), daemon=True).start()
        if self.current_route or self.items:
            self._start_ring_detection_for_current()

    def _stop_ring_watch(self, status_message: Optional[str] = None):
        """Stop the persistent ring watcher."""
        self._ring_watch_stop.set()
        self._ring_detection_active = False
        self._ring_detection_target = None
        self._update_ring_watch_btn()
        if status_message:
            self.status_var.set(status_message)

    def _start_ring_detection_for_item(self, item_index: int):
        """Arm a survey item for the next detected in-game red ring."""
        if cv2 is None or np is None or ImageGrab is None:
            self.status_var.set("OpenCV/Pillow capture is not available")
            return
        if item_index < 0 or item_index >= len(self.items):
            self.status_var.set("Invalid survey item for ring detection")
            return
        if not self._ring_detection_active:
            self._start_ring_watch()
            if not self._ring_detection_active:
                return
        self._ring_detection_target = item_index
        item_name = self.items[item_index].name
        self.status_var.set(f"Ring watch armed for survey #{item_index + 1}: {item_name}")

    @staticmethod
    def _detect_red_ring(frame_rgb) -> Optional[Tuple[float, float, float]]:
        """Detect a red ring center/radius in an RGB frame."""
        if cv2 is None or np is None:
            return None
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 120, 80]), np.array([10, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([170, 120, 80]), np.array([180, 255, 255]))
        mask = cv2.bitwise_or(mask1, mask2)
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.GaussianBlur(mask, (9, 9), 0)
        circles = cv2.HoughCircles(
            mask,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=40,
            param1=60,
            param2=18,
            minRadius=12,
            maxRadius=max(25, min(frame_rgb.shape[0], frame_rgb.shape[1]) // 2),
        )
        if circles is not None and len(circles[0]) > 0:
            x, y, r = max(circles[0], key=lambda c: c[2])
            return (float(x), float(y), float(r))

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_radius = 0.0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 150:
                continue
            (x, y), radius = cv2.minEnclosingCircle(contour)
            if radius < 12 or radius <= best_radius:
                continue
            best = (float(x), float(y), float(radius))
            best_radius = float(radius)
        return best

    def _ring_watch_worker(self, bbox: Tuple[int, int, int, int]):
        """Continuously watch for red rings and apply them to the armed survey."""
        detections: List[Tuple[float, float, float]] = []
        last_seen_time = 0.0
        while not self._ring_watch_stop.is_set():
            try:
                frame = ImageGrab.grab(bbox=bbox, all_screens=True)
            except TypeError:
                frame = ImageGrab.grab(bbox=bbox)
            except Exception as exc:
                self.after(0, lambda err=str(exc): self._stop_ring_watch(f"Ring watch failed: {err}"))
                return

            detection = self._detect_red_ring(np.array(frame))
            if detection is not None and self._ring_detection_target is not None:
                detections.append(detection)
                last_seen_time = time.time()
            elif detections and self._ring_detection_target is not None and time.time() - last_seen_time > 0.35:
                target_index = self._ring_detection_target
                center_x = self._median([d[0] for d in detections])
                center_y = self._median([d[1] for d in detections])
                radius = self._median([d[2] for d in detections])
                detections = []
                self.after(
                    0,
                    lambda item_idx=target_index, det=(center_x, center_y, radius): self._finish_ring_detection(item_idx, det, None)
                )
            time.sleep(0.08)

    def _finish_ring_detection(self, item_index: int,
                               detection: Optional[Tuple[float, float, float]],
                               error: Optional[str]):
        """Apply the detected ring center to the selected survey item."""
        if error:
            self._ring_detection_target = None
            self.status_var.set(f"Ring watch error: {error}")
            return
        if detection is None or item_index < 0 or item_index >= len(self.items):
            self._ring_detection_target = None
            self.status_var.set("Ring watch did not produce a usable target")
            return
        if self.settings.origin_x is None or self.settings.origin_y is None or not self.settings.scale_factor:
            self._ring_detection_target = None
            self.status_var.set("Set player position and scale before applying ring detection")
            return

        center_x, center_y, _radius = detection
        item = self.items[item_index]
        item.x = center_x
        item.y = center_y
        item.dx_m = (center_x - self.settings.origin_x) / self.settings.scale_factor
        item.dy_m = (self.settings.origin_y - center_y) / self.settings.scale_factor
        item.distance = round(math.sqrt(item.dx_m ** 2 + item.dy_m ** 2), 1)
        item.direction = self._vector_to_direction(item.dx_m, item.dy_m)

        self._recalculate_item_positions()
        self._ring_detection_target = None
        if self._ring_detection_active:
            self.status_var.set(f"Survey #{item_index + 1} aligned. Ring watch is waiting for the next survey.")
        else:
            self.status_var.set(f"Survey #{item_index + 1} aligned to detected red ring")

    @staticmethod
    def _vector_to_direction(dx_m: float, dy_m: float) -> str:
        """Convert a meter vector into a nearest-8-way direction."""
        angle_deg = math.degrees(math.atan2(dy_m, dx_m))
        snap = round(angle_deg / 45) * 45 % 360
        snap_to_dir = {
            0: 'E', 45: 'NE', 90: 'N', 135: 'NW',
            180: 'W', 225: 'SW', 270: 'S', 315: 'SE'
        }
        return snap_to_dir.get(snap, 'N')

    def _on_player_position_reset(self, event_msg: str = ""):
        """Called whenever a zone entry or recall resets the player's known position.

        Clears the stored origin so that the user must re-click their spawn point
        on the map, and shows a prompt in the status bar.
        """
        self.settings.origin_x = None
        self.settings.origin_y = None
        self.settings.scale_factor = None
        self.settings.current_player_x = None
        self.settings.current_player_y = None
        self.settings.save()

        prompt = f"{event_msg}  —  Click map to set spawn position"
        self.status_var.set(prompt.strip(" —"))

        # Flash map overlay into position-setting mode if it is open
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.set_setting_position_mode(True)
            self.map_overlay._draw_player_dot()  # clears old dot

    def _on_map_click(self, x: float, y: float, action: str, item_index: Optional[int] = None):
        """Handle map click events."""
        if action == 'set_origin':
            self.status_var.set(f"Player position set: ({x:.0f}, {y:.0f})")
            # Recalculate canvas coordinates for all items that have metric offsets
            self._recalculate_item_positions()
        elif action == 'player_preview_moved':
            self.status_var.set(f"Adjusting player marker: ({x:.0f}, {y:.0f})")
        elif action == 'player_dragged':
            self.settings.current_player_x = x
            self.settings.current_player_y = y
            if self.settings.origin_x is None or self.settings.origin_y is None:
                self.settings.origin_x = x
                self.settings.origin_y = y
            self.settings.save()
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay._draw_player_dot()
            self.status_var.set(f"Player marker moved to ({x:.0f}, {y:.0f})")
        elif action == 'item_clicked' and item_index is not None:
            # Always recalibrate from this item; players may change maps or DPI
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay.calibrate_from_click(item_index, x, y)
                if self.settings.scale_factor:
                    self.status_var.set(f"Scale calibrated: {self.settings.scale_factor:.2f} px/m")
                else:
                    self.status_var.set("Scale calibrated from clicked item")
                self._recalculate_item_positions()
        elif action == 'item_preview_moved' and item_index is not None:
            self.status_var.set(f"Adjusting pin #{item_index + 1}...")
        elif action == 'item_dragged' and item_index is not None:
            if self.settings.origin_x is None or self.settings.origin_y is None:
                self.status_var.set("Set your position first, then drag a pin to calibrate")
                self._recalculate_item_positions()
                return
            item = self.items[item_index]
            pixel_dist = math.sqrt((x - self.settings.origin_x) ** 2 +
                                   (y - self.settings.origin_y) ** 2)
            metric_dist = math.sqrt(item.dx_m ** 2 + item.dy_m ** 2) if (
                item.dx_m is not None and item.dy_m is not None
            ) else item.distance
            if metric_dist and metric_dist > 0:
                self.settings.scale_factor = pixel_dist / metric_dist
                self.settings.save()
                self.status_var.set(f"Pin #{item_index + 1} calibrated: {self.settings.scale_factor:.2f} px/m")
                self._recalculate_item_positions()

    def _recalculate_item_positions(self):
        """Recalculate canvas x/y for all items and refresh map + route.

        - If a real player origin is set, items are positioned around it.
        - If not, a temporary center origin is used **only for drawing pins**;
          the saved player marker is NOT changed.
        """
        # Determine canvas size (from live overlay or saved size)
        if self.map_overlay and self.map_overlay.winfo_exists():
            cw = self.map_overlay.canvas.winfo_width()
            ch = self.map_overlay.canvas.winfo_height()
        else:
            cw, ch = 0, 0
        if cw <= 1:
            cw = self.settings.map_size[0] if self.settings.map_size else 400
            ch = max((self.settings.map_size[1] or 400) - 18, 100) if self.settings.map_size else 382

        has_real_origin = self.settings.origin_x is not None and self.settings.origin_y is not None
        if has_real_origin:
            ox, oy = self.settings.origin_x, self.settings.origin_y
        else:
            # Temporary render origin at canvas center (do NOT write back to settings)
            ox, oy = cw // 2, ch // 2

        # Auto-compute a scale that fits all items if none is saved
        sf = self.settings.scale_factor
        if sf is None and self.items:
            max_dist = max((item.distance for item in self.items if item.distance > 0), default=1)
            # Fit furthest item within 40% of the shorter canvas dimension from origin
            sf = (min(cw, ch) * 0.4) / max_dist
            # Remember this auto scale so subsequent calls are stable
            self.settings.scale_factor = sf
            self.settings.save()

        if sf is None or sf <= 0:
            return

        _dir_angles = {
            'E': 0, 'NE': math.pi/4, 'N': math.pi/2, 'NW': 3*math.pi/4,
            'W': math.pi, 'SW': 5*math.pi/4, 'S': 3*math.pi/2, 'SE': 7*math.pi/4
        }

        for item in self.items:
            if item.dx_m is not None and item.dy_m is not None:
                item.x = ox + item.dx_m * sf
                item.y = oy - item.dy_m * sf
            else:
                angle = _dir_angles.get(item.direction, 0)
                item.x = ox + item.distance * math.cos(angle) * sf
                item.y = oy - item.distance * math.sin(angle) * sf

        # Sync to MapOverlay's list and redraw
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.survey_items = self.items
            self.map_overlay.clear_items()
            # Only draw player marker if we have a real origin
            if has_real_origin:
                self.map_overlay.settings.origin_x = self.settings.origin_x
                self.map_overlay.settings.origin_y = self.settings.origin_y
                self.map_overlay._draw_player_dot()
            for i, item in enumerate(self.items):
                self.map_overlay._draw_item(item, i)
            # Redraw route pins if a route is active
            if self.current_route:
                self.map_overlay.draw_route(self.current_route, self.current_route_index, self.items)


    def _update_map_opacity(self):
        """Update map overlay opacity (from percentage spinbox)."""
        try:
            percentage = self.map_opacity_var.get()
        except tk.TclError:
            return
        percentage = max(5, min(100, percentage))
        self.map_opacity_var.set(percentage)
        decimal_value = percentage / 100.0
        self.settings.map_opacity = decimal_value
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.update_opacity(decimal_value)
        else:
            self.settings.save()
    
    def _update_inv_opacity(self):
        """Update inventory overlay opacity (from percentage spinbox)."""
        try:
            percentage = self.inv_opacity_var.get()
        except tk.TclError:
            return
        percentage = max(10, min(100, percentage))
        self.inv_opacity_var.set(percentage)
        decimal_value = percentage / 100.0
        self.settings.inv_opacity = decimal_value
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            # update_opacity() will call save() for us
            self.inv_overlay.update_opacity(decimal_value)
        else:
            # Overlay not open, save directly
            self.settings.save()
    
    def _toggle_lock_overlays(self):
        """Toggle click-through lock on both overlays."""
        enabled = not (self.map_clickthrough_var.get() and self.inv_clickthrough_var.get())
        self.map_clickthrough_var.set(enabled)
        self.inv_clickthrough_var.set(enabled)
        self.settings.map_clickthrough = enabled
        self.settings.inv_clickthrough = enabled
        self.settings.save()
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.set_clickthrough(enabled)
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay.set_clickthrough(enabled)
        self._update_lock_btn()

    def _update_lock_btn(self):
        """Update lock button text."""
        locked = self.map_clickthrough_var.get() and self.inv_clickthrough_var.get()
        self.lock_btn.config(text=f"🔒 Lock Overlays: {'ON' if locked else 'OFF'}")

    def _save_overlay_layout(self):
        """Read current overlay geometry and save to settings."""
        for overlay, prefix in [
            (self.map_overlay, 'map'),
            (self.inv_overlay, 'inv'),
        ]:
            if overlay and overlay.winfo_exists():
                try:
                    geom = overlay.wm_geometry()
                    w, h, x, y = parse_geometry(geom)
                    if x is not None:
                        setattr(self.settings, f'{prefix}_position', (x, y))
                    if w:
                        setattr(self.settings, f'{prefix}_size', (w, h))
                except Exception:
                    pass
        self.settings.save()
        self.status_var.set("Overlay layout saved")
    
    def _toggle_always_on_top(self):
        """Toggle always-on-top for the Survey Helper window."""
        enabled = self.always_on_top_var.get()
        self.settings.always_on_top = enabled
        self.attributes('-topmost', enabled)
        self.settings.save()
    
    def _set_phase(self, phase: int):
        """Highlight the current workflow phase in the phase indicator bar."""
        self.settings.current_phase = phase
        colors = {
            'done': UI_COLORS.get("success", "#44aa44"),
            'active': UI_COLORS.get("accent", "#5599ff"),
            'future': UI_COLORS.get("muted_text", "#888888"),
        }
        for i, lbl in enumerate(self._phase_labels):
            if i < phase:
                lbl.config(fg=colors['done'])
            elif i == phase:
                lbl.config(fg=colors['active'], font=(UI_ATTRS["font_family"],
                           max(7, UI_ATTRS["font_size"]-1), 'bold'))
            else:
                lbl.config(fg=colors['future'],
                           font=(UI_ATTRS["font_family"], max(7, UI_ATTRS["font_size"]-1)))
    
    def _update_positions_display(self):
        """Refresh the detected positions text widget."""
        total = self.settings.survey_count
        found = len(self.items)
        self.positions_var.set(f"Positions: {found}/{total} found")
        self.positions_text.config(state='normal')
        self.positions_text.delete('1.0', 'end')
        for i, item in enumerate(self.items):
            dist_str = f"{item.distance:.0f}m {item.direction}"
            collected_str = " ✓" if item.collected else ""
            self.positions_text.insert('end', f"{i+1}. {item.name}  ({dist_str}){collected_str}\n")
        self.positions_text.config(state='disabled')
        # Auto-optimize when all positions found
        if total > 0 and found >= total and not self.current_route:
            self.status_var.set(f"All {total} positions found! Click Optimize Route.")
            self._set_phase(3)
    
    def _update_loot_display(self):
        """Refresh the loot gained text widget."""
        self.loot_text.config(state='normal')
        self.loot_text.delete('1.0', 'end')
        for name, count in sorted(self.loot_gained.items()):
            self.loot_text.insert('end', f"{name}  x{count}\n")
        self.loot_text.config(state='disabled')
    
    def _copy_loot(self):
        """Copy loot summary to clipboard."""
        if not self.loot_gained:
            return
        text = "\n".join(f"{name} x{count}" for name, count in sorted(self.loot_gained.items()))
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Loot copied to clipboard!")
    
    def _on_inv_next_clicked(self):
        """Called when the Next button on the inventory overlay is clicked."""
        self._skip_item()
    
    def _start_chat_monitor(self):
        """Start monitoring chat logs for survey messages."""
        # Try to auto-detect chat log directory if not manually set
        if self.settings.chatlog_dir is None:
            try:
                # Ensure PG_BASE is initialized
                if config.PG_BASE is None:
                    initialize_pg_base(force=False)
                
                # Use auto-detected CHAT_DIR if available
                if config.CHAT_DIR is not None:
                    self.settings.chatlog_dir = config.CHAT_DIR
                    self.settings.save()
            except Exception as e:
                print(f"Auto-detection failed: {e}")
        
        # Only proceed if we have a chat log directory
        if self.settings.chatlog_dir is None:
            return
        
        try:
            self.chat_monitor = ChatLogMonitor(chat_dir=self.settings.chatlog_dir)
            self._monitoring = True
            self._poll_chat()
            self.status_var.set("Monitoring chat logs...")
        except Exception as e:
            self.status_var.set(f"Chat monitor error: {e}")
    
    def _poll_chat(self):
        """Poll for new chat messages."""
        if not self._monitoring or self.chat_monitor is None:
            return
        
        try:
            lines = self.chat_monitor.read_new_lines()
            for line in lines:
                self._parse_chat_line(line)
        except Exception as e:
            print(f"Chat poll error: {e}")
        
        # Schedule next poll
        self.after(1000, self._poll_chat)
    
    # Map full compass words to (dx_unit, dy_unit) where east=+x, north=+y
    _COMPASS_VECTORS = {
        'n': (0.0, 1.0), 'north': (0.0, 1.0),
        's': (0.0, -1.0), 'south': (0.0, -1.0),
        'e': (1.0, 0.0), 'east': (1.0, 0.0),
        'w': (-1.0, 0.0), 'west': (-1.0, 0.0),
        'ne': (0.7071, 0.7071), 'northeast': (0.7071, 0.7071),
        'nw': (-0.7071, 0.7071), 'northwest': (-0.7071, 0.7071),
        'se': (0.7071, -0.7071), 'southeast': (0.7071, -0.7071),
        'sw': (-0.7071, -0.7071), 'southwest': (-0.7071, -0.7071),
    }
    _ABBREV_DIR = {
        'n': 'N', 's': 'S', 'e': 'E', 'w': 'W',
        'ne': 'NE', 'nw': 'NW', 'se': 'SE', 'sw': 'SW',
        'north': 'N', 'south': 'S', 'east': 'E', 'west': 'W',
        'northeast': 'NE', 'northwest': 'NW', 'southeast': 'SE', 'southwest': 'SW',
    }

    def _parse_chat_line(self, line: str):
        """Parse chat line for zone entry, survey creation, positions, and loot."""

        # Parse line timestamp (used for reset filter and age checks)
        line_time = None
        ts_match = re.match(r'(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if ts_match:
            try:
                line_time = datetime.strptime(ts_match.group(1), '%y-%m-%d %H:%M:%S')
            except ValueError:
                pass

        # Skip lines older than the last session reset
        if self.reset_time is not None and line_time is not None:
            if line_time < self.reset_time:
                return

        # ── 1. Zone entry ──────────────────────────────────────────────────────
        zone_match = re.search(r'Entering\s+Area:\s*(.+)', line, re.IGNORECASE)
        if zone_match:
            zone = zone_match.group(1).strip().rstrip('*').strip()
            self.settings.zone_name = zone
            self.settings.save()
            self.zone_var.set(f"Zone: {zone}")
            self._on_player_position_reset(f"📍 Entered: {zone}")
            self._set_phase(1)
            return

        # ── 1b. Recall / teleport — position is now known ──────────────────────
        # Project Gorgon logs one of these when a recall fires:
        #   [Status] You recall to X   |   You are recalled   |   Recall successful
        #   [General] You recall ...
        recall_match = re.search(
            r'(?:you\s+(?:are\s+)?recall(?:ed)?|recall\s+successful)',
            line, re.IGNORECASE
        )
        if recall_match:
            self._on_player_position_reset("🔁 Recalled — position reset")

        # ── 2. Item added to inventory (survey creation OR loot) ──────────────────
        added_match = re.search(r'\[Status\]\s+(.+?)\s+added to inventory', line, re.IGNORECASE)
        if added_match:
            item_name = added_match.group(1).strip()
            if 'survey' in item_name.lower():
                # Survey map crafted — auto-increment counter
                new_count = self.count_var.get() + 1
                self.count_var.set(new_count)
                self._set_survey_count()
                self.status_var.set(f"Survey #{new_count} made — {item_name}")
                self._set_phase(max(self.settings.current_phase, 1))
            else:
                # Regular loot item
                self._record_loot(item_name)
                self._mark_item_collected(item_name)
            return

        # ── 3. Survey position ─────────────────────────────────────────────────
        # Skip position lines older than 15 minutes
        if line_time is not None:
            age = (datetime.now() - line_time).total_seconds()
            if age > 900:  # 15 minutes
                return
        # Handles both:
        #   [Status] The Fluorite is 2001m east and 25m north.
        #   [Status] The Ancient Tombstone is 45m NE
        # Pattern: capture everything after "The" up to "is", then one or two
        # distance+direction components joined by optional " and ".
        _dir_pat = r'(?:north(?:east|west)?|south(?:east|west)?|east|west|n|s|e|w|ne|nw|se|sw)'
        pos_match = re.search(
            rf'\[Status\]\s+The\s+(.+?)\s+is\s+'
            rf'(\d+(?:\.\d+)?)m?\s+({_dir_pat})'
            rf'(?:\s+and\s+(\d+(?:\.\d+)?)m?\s+({_dir_pat}))?'
            rf'[\.\s]*$',
            line, re.IGNORECASE
        )
        if pos_match:
            name = pos_match.group(1).strip()
            dist1 = float(pos_match.group(2))
            dir1_raw = pos_match.group(3).lower()
            dist2 = float(pos_match.group(4)) if pos_match.group(4) else None
            dir2_raw = pos_match.group(5).lower() if pos_match.group(5) else None

            vec1 = self._COMPASS_VECTORS.get(dir1_raw, (1.0, 0.0))
            dx_m = dist1 * vec1[0]
            dy_m = dist1 * vec1[1]

            if dist2 is not None and dir2_raw:
                vec2 = self._COMPASS_VECTORS.get(dir2_raw, (0.0, 0.0))
                dx_m += dist2 * vec2[0]
                dy_m += dist2 * vec2[1]

            # Total distance and nearest-8-way direction for display
            total_dist = math.sqrt(dx_m**2 + dy_m**2)
            angle_deg = math.degrees(math.atan2(dy_m, dx_m))
            # Snap to nearest 45° and convert to compass abbreviation
            snap = round(angle_deg / 45) * 45 % 360
            _snap_to_dir = {0: 'E', 45: 'NE', 90: 'N', 135: 'NW',
                            180: 'W', 225: 'SW', 270: 'S', 315: 'SE'}
            direction = _snap_to_dir.get(snap, 'N')

            item = SurveyItem(
                name=name,
                distance=round(total_dist, 1),
                direction=direction,
                dx_m=dx_m,
                dy_m=dy_m,
                timestamp=datetime.now()
            )

            self.items.append(item)

            if self.map_overlay and self.map_overlay.winfo_exists():
                auto_placed = self.map_overlay.add_survey_item(item)
                if not auto_placed:
                    self.status_var.set(f"Found: {name} — click map to calibrate")
                else:
                    self.status_var.set(f"Found: {name} at {total_dist:.0f}m {direction}")
            else:
                self.status_var.set(f"Found: {name} at {total_dist:.0f}m {direction}")

            self._update_session_info()
            self._set_phase(max(self.settings.current_phase, 2))
            return

        # ── 4. Loot / item collected ───────────────────────────────────────────
        # "[Status] Fluorite collected!"
        collected_match = re.search(r'\[Status\]\s+(.+?)\s+collected!', line, re.IGNORECASE)
        if collected_match:
            item_name = collected_match.group(1).strip()
            self._record_loot(item_name)
            self._mark_item_collected(item_name)
            return

        # "You receive X" / "You loot X"
        for pattern in [r'You\s+receive\s+(.+)', r'You\s+loot\s+(.+)']:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                item_name = m.group(1).strip().rstrip('.')
                self._record_loot(item_name)
                break

    def _record_loot(self, name: str):
        """Track a survey loot item gained during the session."""
        # Only record items known to drop from surveying
        if self._SURVEY_LOOT_ITEMS and name not in self._SURVEY_LOOT_ITEMS:
            return
        self.loot_gained[name] = self.loot_gained.get(name, 0) + 1
        self._update_loot_display()

    def _mark_item_collected(self, name: str):
        """Mark a survey item as collected by name."""
        for i, item in enumerate(self.items):
            if not item.collected and (
                name.lower() in item.name.lower() or item.name.lower() in name.lower()
            ):
                item.collected = True

                if self.map_overlay and self.map_overlay.winfo_exists():
                    self.map_overlay.mark_collected(i)

                self.status_var.set(f"Collected: {item.name}")
                self._update_session_info()
                # Auto-advance route when item matches current next
                if (self.current_route and
                        self.current_route_index < len(self.current_route) and
                        self.current_route[self.current_route_index] == i):
                    self.after(300, self._next_item)
                break
    
    def _optimize_route(self):
        """Optimize route using nearest neighbor algorithm."""
        if not self.items:
            self.status_var.set("No items to optimize")
            return

        # Route selection must use the latest calibrated canvas positions.
        self._recalculate_item_positions()
        
        # Get uncollected items
        uncollected = [
            (i, item) for i, item in enumerate(self.items)
            if not item.collected and item.x is not None and item.y is not None
        ]
        
        if not uncollected:
            self.status_var.set("No uncollected survey positions available for routing")
            return
        
        # Use player position as start if known; otherwise start from centroid of items
        if self.settings.current_player_x is not None and self.settings.current_player_y is not None:
            start_x, start_y = self.settings.current_player_x, self.settings.current_player_y
        elif self.settings.origin_x is not None:
            start_x, start_y = self.settings.origin_x, self.settings.origin_y
        else:
            start_x = sum(item.x for _, item in uncollected) / len(uncollected)
            start_y = sum(item.y for _, item in uncollected) / len(uncollected)
        
        # Nearest neighbor algorithm
        route = []
        current_x, current_y = start_x, start_y
        remaining = uncollected.copy()
        
        while remaining:
            # Find nearest item
            nearest_idx = None
            nearest_dist = float('inf')
            
            for idx, (item_idx, item) in enumerate(remaining):
                dist = math.hypot(item.x - current_x, item.y - current_y)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_idx = idx
            
            if nearest_idx is not None:
                item_idx, item = remaining.pop(nearest_idx)
                route.append(item_idx)
                current_x, current_y = item.x, item.y
        
        self.current_route = route
        self.current_route_index = 0
        
        if self.session_start is None:
            self.session_start = datetime.now()

        # Ensure map is open so pins are visible
        if not self.map_open:
            self._show_map()

        # Draw route on overlays
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.draw_route(self.current_route, 0, self.items)
            self.map_overlay.show_nav_bar(
                self._prev_item, self._next_item, self._skip_item
            )
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay.show_route_order(self.current_route)

        self._highlight_next_item()
        self._update_route_info()
        self._set_phase(4)
        self.status_var.set(f"Route optimized: {len(route)} items")
    
    def _highlight_next_item(self):
        """Update route visualization to highlight the current stop."""
        if self.current_route_index < len(self.current_route):
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay.draw_route(self.current_route, self.current_route_index, self.items)
                # Update nav label with current stop info
                idx = self.current_route[self.current_route_index]
                item = self.items[idx]
                label = f"Stop {self.current_route_index + 1}/{len(self.current_route)}: {item.name[:20]}"
                self.map_overlay.update_nav_label(label)
            if self.inv_overlay and self.inv_overlay.winfo_exists():
                idx = self.current_route[self.current_route_index]
                self.inv_overlay.highlight_next_slot(idx)
        else:
            # Route complete — clear current-stop highlighting
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay.draw_route(self.current_route, -1, self.items)
                self.map_overlay.update_nav_label("Route complete!")
            if self.inv_overlay and self.inv_overlay.winfo_exists():
                self.inv_overlay.highlight_next_slot(-1)
    
    def _next_item(self):
        """Go to next item in route."""
        if self.current_route_index < len(self.current_route) - 1:
            self.current_route_index += 1
            self._highlight_next_item()
            self._update_route_info()
    
    def _prev_item(self):
        """Go to previous item in route."""
        if self.current_route_index > 0:
            self.current_route_index -= 1
            self._highlight_next_item()
            self._update_route_info()
    
    def _skip_item(self):
        """Skip current item in route."""
        if self.current_route_index < len(self.current_route):
            idx = self.current_route[self.current_route_index]
            self.items[idx].collected = True
            self._next_item()
    
    def _update_route_info(self):
        """Update route information display."""
        if self.current_route and self.current_route_index < len(self.current_route):
            idx = self.current_route[self.current_route_index]
            item = self.items[idx]
            self.route_info_var.set(f"Next: {item.name} ({item.distance}m {item.direction})")
            self._set_phase(5)
        else:
            self.route_info_var.set("Route complete!")
            if self.current_route:
                self._set_phase(6)
    
    def _update_session_info(self):
        """Update session statistics."""
        total = len(self.items)
        collected = sum(1 for item in self.items if item.collected)
        self.session_var.set(f"Items: {collected}/{total} collected")
        self._update_positions_display()
    
    def _reset_session(self):
        """Reset the current session."""
        self._stop_ring_watch()
        self.reset_time = datetime.now()  # ignore all chat lines before now
        self.items = []
        self.current_route = []
        self.current_route_index = 0
        self.session_start = None
        self.loot_gained = {}

        # Reset survey count to 0
        self.settings.survey_count = 0
        self.settings.origin_x = None
        self.settings.origin_y = None
        self.settings.scale_factor = None
        self.settings.current_player_x = None
        self.settings.current_player_y = None
        self.count_var.set(0)
        self.settings.save()
        
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.survey_items = []
            self.map_overlay.clear_items()
            self.map_overlay.clear_route()
        
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay.clear_route_order()
            self.inv_overlay.set_survey_count(0)
        
        self.settings.zone_name = None
        self.settings.current_phase = 0
        self.settings.save()
        
        self.zone_var.set("Zone: Unknown")
        self.positions_var.set("Positions: 0 found")
        self.session_var.set("Items found: 0")
        self.route_info_var.set("No route active")
        self.status_var.set("Session reset")
        self._set_phase(0)
        self._update_positions_display()
        self._update_loot_display()
    
    def on_close(self):
        """Clean up on window close."""
        self._stop_ring_watch()
        self._monitoring = False
        # Save main window geometry before closing
        self.settings.main_window_position = (self.winfo_x(), self.winfo_y())
        self.settings.main_window_size = (self.winfo_width(), self.winfo_height())
        # Save overlay state
        self.settings.map_was_open = self.map_open
        self.settings.inventory_was_open = self.inventory_open
        self.settings.save()  # Save all settings before destroying overlays
        if self.map_overlay:
            self.map_overlay.destroy()
        if self.inv_overlay:
            self.inv_overlay.destroy()
        self.destroy()
    
    def _on_main_window_configure(self, event=None):
        """Save main window position/size on resize/move."""
        # Avoid saving during window creation/destruction or when size is too small
        if self.winfo_exists():
            width = self.winfo_width()
            height = self.winfo_height()
            # Only save if window has reasonable size (not collapsed)
            if width > 100 and height > 100:
                self.settings.main_window_position = (self.winfo_x(), self.winfo_y())
                self.settings.main_window_size = (width, height)
    
    def _restore_overlays(self):
        """Restore map and/or inventory overlays if they were open before."""
        if self.settings.map_was_open:
            self._show_map()
        if self.settings.inventory_was_open:
            self._show_inventory()


def open_survey_helper(parent):
    """Open the Survey Helper window."""
    window = SurveyHelperWindow(parent)
    window.protocol("WM_DELETE_WINDOW", window.on_close)
    return window
