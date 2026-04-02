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
    # True when this item has been precisely aligned from a detected ring
    # (or explicit map calibration), and safe to draw as a map pin.
    calibrated: bool = False

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
            'calibrated': self.calibrated,
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
            calibrated=data.get('calibrated', False),
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
        # Player position as fraction of the logical zone map (0.0–1.0)
        self.player_frac_x: Optional[float] = None
        self.player_frac_y: Optional[float] = None
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
                self.player_frac_x = data.get('player_frac_x')
                self.player_frac_y = data.get('player_frac_y')
                
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
            'player_frac_x': self.player_frac_x,
            'player_frac_y': self.player_frac_y,
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


# Canonical in-game map sizes (in "survey meters"), from pg_survey_helper.
MAP_SIZES: Dict[str, Tuple[int, int]] = {
    "Serbule": (2382, 2488),
    "Serbule Hills": (2748, 2668),
    "Eltibule": (2684, 2778),
    "Ilmari": (2920, 2920),
    "Kur Mountains": (3000, 3000),
}


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

        # Route nav bar is no longer shown; navigation is controlled from the
        # main window only. Keep minimal placeholders so existing calls are no-ops.
        self._nav_bar = None
        self._nav_prev_btn = None
        self._nav_next_btn = None
        self._nav_skip_btn = None
        self._nav_label = None
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
        # Bind double-click to set spawn position
        self.canvas.bind('<Double-Button-1>', self._on_double_click)

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
            if self.on_click_callback:
                self.on_click_callback(event.x, event.y, 'set_origin')
        else:
            # Check if clicked on an item
            item_index = self._find_item_index_at(event.x, event.y)
            if item_index is not None and self.on_click_callback:
                self.on_click_callback(event.x, event.y, 'item_clicked', item_index)
    
    def _on_double_click(self, event):
        """Double-click on map to set spawn position."""
        # Check if not clicking on a survey item
        item_index = self._find_item_index_at(event.x, event.y)
        if item_index is not None:
            return  # Don't set spawn if clicking on a survey pin
        
        # Set spawn position at double-click location
        self.settings.origin_x = event.x
        self.settings.origin_y = event.y
        self.settings.current_player_x = event.x
        self.settings.current_player_y = event.y
        
        # Update fractional position
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        self.settings.player_frac_x = max(0.0, min(1.0, event.x / cw))
        self.settings.player_frac_y = max(0.0, min(1.0, event.y / ch))
        self.settings.save()
        
        # Redraw player marker
        self._draw_player_dot()
        
        # Notify parent
        if self.on_click_callback:
            self.on_click_callback(event.x, event.y, 'set_origin')
    
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
        """Draw a draggable player marker at the current origin position."""
        self.canvas.delete('player_marker')
        if self.settings.origin_x is None or self.settings.origin_y is None:
            return
        
        x, y = self.settings.origin_x, self.settings.origin_y
        # Shrink marker ~50% to reduce visual clutter
        radius = 5
        
        # Draw a distinctive player marker (green with white outline)
        self.canvas.create_oval(
            x - radius, y - radius, x + radius, y + radius,
            fill='#00ff88', outline='white', width=2,
            tags=('player_marker', 'player')
        )
        # Inner dot for visibility
        self.canvas.create_oval(
            x - 2, y - 2, x + 2, y + 2,
            fill='white', outline='',
            tags=('player_marker', 'player')
        )
        # Make the player marker draggable
        self.canvas.tag_bind('player_marker', '<Button-1>', self._on_player_marker_click)
        self.canvas.tag_bind('player_marker', '<B1-Motion>', self._on_player_marker_drag)
        self.canvas.tag_bind('player_marker', '<ButtonRelease-1>', self._on_player_marker_release)
    
    def _on_player_marker_click(self, event):
        """Start dragging the player marker."""
        self._player_drag_start = (event.x, event.y)
        self.canvas.config(cursor='fleur')
    
    def _on_player_marker_drag(self, event):
        """Drag the player marker to a new position."""
        if not hasattr(self, '_player_drag_start'):
            return
        
        # Move the player marker visually
        dx = event.x - self._player_drag_start[0]
        dy = event.y - self._player_drag_start[1]
        self.canvas.move('player_marker', dx, dy)
        self._player_drag_start = (event.x, event.y)
    
    def _on_player_marker_release(self, event):
        """Set the new spawn position after dragging."""
        self.canvas.config(cursor='')
        
        # Get the new position from the marker center
        coords = self.canvas.coords('player_marker')
        if len(coords) >= 4:
            x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
            new_x = (x1 + x2) / 2
            new_y = (y1 + y2) / 2
            
            # Update settings
            self.settings.origin_x = new_x
            self.settings.origin_y = new_y
            
            # Update fractional position
            cw = max(self.canvas.winfo_width(), 1)
            ch = max(self.canvas.winfo_height(), 1)
            self.settings.player_frac_x = max(0.0, min(1.0, new_x / cw))
            self.settings.player_frac_y = max(0.0, min(1.0, new_y / ch))
            self.settings.save()
            
            # Notify parent
            if self.on_click_callback:
                self.on_click_callback(new_x, new_y, 'player_dragged')
        
        if hasattr(self, '_player_drag_start'):
            del self._player_drag_start
    
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
        """Draw a survey item on the map.

        Labels are renumbered so that uncollected items show 1..N with no
        gaps. Collected items keep their dot but lose their number.
        """
        color = UI_COLORS["primary"] if not item.collected else UI_COLORS["muted_text"]
        # Slightly smaller pins to reduce clutter
        dot_radius = 5
        
        # Dot
        self.canvas.create_oval(
            item.x-dot_radius, item.y-dot_radius, item.x+dot_radius, item.y+dot_radius,
            fill=color, outline=UI_COLORS["text"], width=2,
            tags=('survey_item', f'item_{index}', f'item_dot_{index}')
        )
        
        # Label (dynamic numbering only - no names)
        label_text = ""
        display_map = getattr(self, "_display_index_map", None)
        if not item.collected and isinstance(display_map, dict):
            num = display_map.get(index)
            if num is not None:
                label_text = str(num)
        # Don't show any label for collected items (they're being removed anyway)
        
        self.canvas.create_text(
            item.x, item.y-12,
            text=label_text,
            fill=UI_COLORS["text"], font=(UI_ATTRS["font_family"], max(10, UI_ATTRS["font_size"]+1), 'bold'),
            tags=('survey_item', f'item_{index}', f'item_label_{index}')
        )
        
        # Distance line from origin to this survey point. Tagged separately
        # as 'distance_line' so that route optimization can hide these radial
        # guides and only show the optimized path.
        if self.settings.origin_x is not None and self.settings.origin_y is not None:
            self.canvas.create_line(
                self.settings.origin_x, self.settings.origin_y,
                item.x, item.y,
                fill=UI_COLORS["accent"], dash=(3, 3), width=1,
                tags=('survey_item', 'distance_line', f'item_{index}', f'item_line_{index}')
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
    
    def clear_item(self, index: int):
        """Clear a specific survey item from the map (completely remove it)."""
        if 0 <= index < len(self.survey_items):
            # Delete the specific item's dot, label, and distance line
            self.canvas.delete(f'item_dot_{index}')
            self.canvas.delete(f'item_label_{index}')
            self.canvas.delete(f'item_line_{index}')
    
    def mark_collected(self, index: int):
        """Mark an item as collected (legacy, now uses clear_item instead)."""
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
        # Hide any radial distance lines once a route is drawn so only the
        # optimized path is visible.
        self.canvas.delete('route_viz')
        self.canvas.delete('distance_line')
        if not route:
            return

        source = items if items is not None else self.survey_items

        # Build ordered (x, y, item_idx, item) list strictly from authoritative
        # survey coordinates. Do not read canvas object positions here.
        stops = []
        for item_idx in route:
            if item_idx < len(source):
                item = source[item_idx]
                if item.x is not None and item.y is not None:
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
                head_radius = 8
            elif is_current:
                pin_fill = '#00ff88'
                pin_outline = 'white'
                text_color = '#000000'
                head_radius = 12
            else:
                pin_fill = '#ffcc00'
                pin_outline = 'white'
                text_color = '#000000'
                head_radius = 10

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

    def show_nav_bar(self, prev_cmd, next_cmd, skip_cmd, label: str = ""):
        """Navigation bar disabled; keep for API compatibility."""
        return

    def hide_nav_bar(self):
        """Navigation bar disabled; keep for API compatibility."""
        self._nav_bar_visible = False

    def update_nav_label(self, label: str):
        """Nav label disabled; keep for API compatibility."""
        return

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
        # Item indices we believe still have survey maps in the inventory.
        self.filled_slots: set[int] = set()
        # Mapping between logical survey items (by index into the helper's
        # items list) and visual inventory slot indices (0..N-1 after
        # inv_offset). This lets us slide numbers left when surveys are used
        # without assuming item index == slot index.
        self.item_to_slot: Dict[int, int] = {}
        self.slot_to_item: Dict[int, int] = {}
        self._route_order: List[int] = []  # route passed to show_route_order
        # Track how many slots to display (total crafted, not remaining)
        self._display_slot_count: int = self.settings.survey_count
        
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
        # Use display_slot_count if available, otherwise fall back to survey_count
        slot_count = getattr(self, '_display_slot_count', self.settings.survey_count)
        count = max(slot_count, 1)
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
                slot_idx = i - offset
                item_idx = self.slot_to_item.get(slot_idx)
                has_item = item_idx is not None and item_idx in self.filled_slots
                # Draw slot
                color = UI_COLORS["primary"] if has_item else UI_COLORS["secondary"]
                outline = UI_COLORS["text"] if has_item else UI_COLORS["muted_text"]
                
                rect = self.canvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=color, outline=outline, width=2,
                    tags=(f'slot_{slot_idx}', 'slot_rect')
                )
                
                self.slots.append(rect)
        # After drawing slots, apply numbering based on active (uncollected)
        # survey maps so that numbers compress when maps are used.
        self.renumber_active_slots()
        # Redraw resize corner on top of everything
        if hasattr(self, '_resize_zone'):
            self._draw_resize_corner()
        # Re-apply route order badges if a route is active
        if hasattr(self, '_route_order') and self._route_order:
            self._apply_route_badges(self._route_order)

    def show_route_order(self, route: List[int]):
        """Overlay route-sequence badges on inventory slots.

        If survey_count is smaller than the largest item index in the route,
        automatically grow the grid so every routed item has a visible slot
        number.
        """
        self._route_order = route
        if route:
            needed = 1 + max(route)
            # Use display_slot_count for comparison
            slot_count = getattr(self, '_display_slot_count', self.settings.survey_count)
            if slot_count < needed:
                self._display_slot_count = needed
                self.settings.survey_count = needed
            # Ensure logical occupancy and mappings cover all routed items.
            slot_count = getattr(self, '_display_slot_count', self.settings.survey_count)
            self.filled_slots = set(range(slot_count))
            self.item_to_slot = {i: i for i in range(slot_count)}
            self.slot_to_item = {i: i for i in range(slot_count)}
            self._draw_grid()
            self.settings.save()
        # Recompute central slot numbers so they reflect route order instead
        # of simple slot index when a route is active.
        self.renumber_active_slots()

    def clear_route_order(self):
        """Remove route-sequence badges."""
        self._route_order = []
        self.canvas.delete('route_badge')
        if hasattr(self, '_resize_zone'):
            self._draw_resize_corner()

    def _apply_route_badges(self, route: List[int]):
        """Route badges disabled on inventory to avoid double numbers.

        The map overlay already shows full route numbering; inventory slots
        only use the main compressed slot numbers plus highlight_next_slot().
        """
        # Clear any old badges that might exist from a previous version.
        self.canvas.delete('route_badge')
        if hasattr(self, '_resize_zone'):
            self._draw_resize_corner()
        return

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
        # Track display slots separately - this is the total crafted
        self._display_slot_count = count
        # Reset logical occupancy and slot mapping.
        self.filled_slots = set(range(count))
        self.item_to_slot = {i: i for i in range(count)}
        self.slot_to_item = {i: i for i in range(count)}
        self._draw_grid()
        self.settings.save()
    
    def mark_slot_filled(self, index: int):
        """Mark an item index as having a survey map.

        `index` is the logical survey item index. We ensure it has a slot
        assigned (creating one if necessary) and mark that slot as filled.
        """
        if index < 0:
            return
        self.filled_slots.add(index)
        slot_idx = self.item_to_slot.get(index)
        if slot_idx is None:
            # Assign the next free slot index for this item.
            slot_idx = max(self.slot_to_item.keys()) + 1 if self.slot_to_item else 0
            self.item_to_slot[index] = slot_idx
            self.slot_to_item[slot_idx] = index
        # Visually mark the slot as filled if it exists on the canvas.
        if self.canvas.find_withtag(f'slot_{slot_idx}'):
            self.canvas.itemconfig(f'slot_{slot_idx}', fill=UI_COLORS["primary"], outline=UI_COLORS["text"], width=2)
    
    def mark_slot_empty(self, index: int):
        """Mark a slot as empty (collected).

        `index` is the logical survey item index that was just used. We drop
        it from the active set, free its slot, and shift all items to the
        right one slot left so numbers stay aligned with the remaining
        surveys in the real inventory.
        """
        if index not in self.filled_slots:
            return
        self.filled_slots.remove(index)
        slot_idx = self.item_to_slot.pop(index, None)
        if slot_idx is None:
            # Nothing to compact; just redraw labels.
            self.renumber_active_slots()
            return
        # Remove the item from its current slot.
        self.slot_to_item.pop(slot_idx, None)
        # Shift any items in higher-numbered slots one step left.
        for s in sorted(list(self.slot_to_item.keys())):
            if s > slot_idx:
                item = self.slot_to_item.pop(s)
                new_s = s - 1
                self.slot_to_item[new_s] = item
                self.item_to_slot[item] = new_s
        # Redraw grid and labels to reflect new layout.
        self._draw_grid()
    
    def renumber_active_slots(self):
        """Renumber visible slot labels so active maps are 1..N with no gaps.

        When a route is active, numbers follow the current route order (1..N
        in visit sequence) and are drawn on top of the corresponding slots.
        Otherwise, they compress left-to-right based on which slots still have
        surveys.
        """
        # Remove any existing slot labels
        self.canvas.delete('slot_label')
        # Use display_slot_count for drawing, not survey_count (which decrements)
        slot_count = getattr(self, '_display_slot_count', self.settings.survey_count)
        if slot_count <= 0:
            return
        # When a route is active, center numbers should show route order
        # (1..N in visit sequence) instead of simple slot index. Otherwise,
        # compress active maps 1..N left-to-right.
        route = getattr(self, '_route_order', []) or []
        display_map: Dict[int, int] = {}
        if route:
            # active_route is the list of item indices in route order that are
            # still present. We then map their *slot* indices to 1..N so the
            # labels slide left but still follow the route sequence.
            active_items = [idx for idx in route if idx in self.filled_slots and idx in self.item_to_slot]
            for pos, item_idx in enumerate(active_items):
                slot_idx = self.item_to_slot.get(item_idx)
                if slot_idx is not None:
                    display_map[slot_idx] = pos + 1
        else:
            # No active route: compress based purely on occupied slot order.
            active_slots = sorted(s for s, item in self.slot_to_item.items() if item in self.filled_slots)
            display_map = {slot_idx: pos + 1 for pos, slot_idx in enumerate(active_slots)}
        num_font_size = max(14, int(UI_ATTRS["font_size"] * 2.0))
        for slot_idx in range(slot_count):
            coords = self.canvas.coords(f'slot_{slot_idx}')
            if not coords:
                continue
            x1, y1, x2, y2 = coords
            label = display_map.get(slot_idx)
            if label is None:
                continue
            # Draw a black outline behind the white number for readability.
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            text = str(label)
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                self.canvas.create_text(
                    cx + dx, cy + dy,
                    text=text,
                    fill="#000000",
                    font=(UI_ATTRS["font_family"], num_font_size, 'bold'),
                    tags=('slot_label', f'slot_label_{slot_idx}')
                )
            self.canvas.create_text(
                cx, cy,
                text=text,
                fill="#ffffff",
                font=(UI_ATTRS["font_family"], num_font_size, 'bold'),
                tags=('slot_label', f'slot_label_{slot_idx}')
            )
    
    def highlight_next_slot(self, item_index: int):
        """Highlight the next-in-route slot with a bright border."""
        # Use display_slot_count for iterating, not survey_count
        slot_count = getattr(self, '_display_slot_count', self.settings.survey_count)
        # Reset all survey slot outlines to their default state
        for slot_idx in range(slot_count):
            item_for_slot = self.slot_to_item.get(slot_idx)
            if item_for_slot is not None and item_for_slot in self.filled_slots:
                self.canvas.itemconfig(f'slot_{slot_idx}', outline=UI_COLORS["text"], width=2)
            else:
                self.canvas.itemconfig(f'slot_{slot_idx}', outline='gray', width=1)
        # Apply highlight to the target slot (item_index is a logical item
        # index; we convert it to the current slot index).
        if item_index >= 0 and item_index in self.item_to_slot:
            slot_idx = self.item_to_slot[item_index]
            if 0 <= slot_idx < slot_count:
                self.canvas.itemconfig(f'slot_{slot_idx}', outline='#00ff88', width=4)

    def _on_next_clicked(self, event=None):
        if self.next_callback:
            self.next_callback()
    
    def clear_all(self):
        """Clear all filled slots and reset mapping."""
        self.filled_slots.clear()
        self.item_to_slot.clear()
        self.slot_to_item.clear()
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

        # Internal-only remaining survey count driven by chat events.
        # The manual "Survey Maps" UI is gone but we still use this IntVar
        # to keep settings.survey_count and the inventory overlay in sync.
        self.count_var = tk.IntVar(value=getattr(self.settings, "survey_count", 0) or 0)

        self.items: List[SurveyItem] = []
        self.current_route: List[int] = []
        self.current_route_index = 0
        self.session_start: Optional[datetime] = None
        self.loot_gained: dict = {}  # item_name → count
        self.reset_time: Optional[datetime] = None  # ignore chat lines before this
        self._ring_detection_active = False
        self._ring_watch_stop = threading.Event()
        self._ring_detection_target: Optional[int] = None
        
        # Track total surveys crafted (for inventory slot count)
        # This is different from survey_count which tracks remaining
        self._total_surveys_crafted: int = 0

        # Remember the user's preferred map + inventory opacity so "Pins Only"
        # can toggle between 20% and whatever the sliders are set to.
        self._preferred_map_opacity: Optional[float] = self.settings.map_opacity
        self._preferred_inv_opacity: Optional[float] = self.settings.inv_opacity
        
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

        # Start every launch as a fresh session so old items/positions
        # and timestamps do not leak into the new run.
        self._reset_session()

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
        ttk.Button(dir_btn_row, text="❔ Help", command=self._show_help, style="App.Secondary.TButton").pack(side='right', padx=2)
        
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
        
        # Left side: overlay buttons
        self.overlays_button = ttk.Button(btn_frame, text="🗺📦 Show Overlays", command=self._show_overlays, style="App.Secondary.TButton")
        self.overlays_button.pack(side='left', padx=2)
        ttk.Button(btn_frame, text="💾 Save Layout", command=self._save_overlay_layout, style="App.Secondary.TButton").pack(side='left', padx=2)

        # Quick toggle: hide/show background but keep pins/lines fully visible
        self.pins_only_var = tk.BooleanVar(value=False)
        self.pins_only_button = ttk.Checkbutton(
            btn_frame,
            text="🎯 Pins Only",
            variable=self.pins_only_var,
            command=self._toggle_pins_only_mode,
            style="App.TCheckbutton",
        )
        self.pins_only_button.pack(side='left', padx=4)
        
        self.map_clickthrough_var = tk.BooleanVar(value=False)  # Map: always OFF
        self.inv_clickthrough_var = tk.BooleanVar(value=True)   # Inventory: always ON

        # Right side: opacity controls on same row
        opacity_frame = tk.Frame(btn_frame, bg=UI_COLORS["panel_bg"])
        opacity_frame.pack(side='right', pady=1)
        
        ttk.Label(opacity_frame, text="Inv %:", style="App.TLabel").pack(side='left', padx=4)
        self.inv_opacity_var = tk.IntVar(value=int(self.settings.inv_opacity * 100))
        self.inv_opacity_spinbox = ttk.Spinbox(opacity_frame, from_=10, to=100, textvariable=self.inv_opacity_var, width=5,
                   style="App.TSpinbox", command=self._update_inv_opacity)
        self.inv_opacity_spinbox.pack(side='left', padx=2)
        self.inv_opacity_spinbox.bind('<Return>', lambda e: self._update_inv_opacity())
        self.inv_opacity_spinbox.bind('<FocusOut>', lambda e: self._update_inv_opacity())
        
        ttk.Label(opacity_frame, text="Map %:", style="App.TLabel").pack(side='left', padx=4)
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
        
        # Positions + Loot side by side using grid so they always share space 50/50
        bottom_row = tk.Frame(frame, bg=UI_COLORS["panel_bg"])
        bottom_row.pack(fill='both', expand=True, pady=3)
        bottom_row.columnconfigure(0, weight=1)
        bottom_row.columnconfigure(1, weight=1)

        # Positions list (scrollable) pinned to the left
        pos_frame = tk.LabelFrame(bottom_row, text="Detected Positions", padx=4, pady=3,
                                  bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                  font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                  borderwidth=1, relief="solid")
        pos_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        self.positions_text = tk.Text(pos_frame, height=6, state='disabled',
                                      bg=UI_COLORS["card_bg"], fg=UI_COLORS["text"],
                                      font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"]-1)),
                                      relief='flat', wrap='none')
        pos_scroll = ttk.Scrollbar(pos_frame, orient='vertical', command=self.positions_text.yview)
        self.positions_text.configure(yscrollcommand=pos_scroll.set)
        pos_scroll.pack(side='right', fill='y')
        self.positions_text.pack(fill='both', expand=True)
        
        # Loot summary pinned to the right
        loot_frame = tk.LabelFrame(bottom_row, text="Loot Gained", padx=4, pady=3,
                                   bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                   font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                   borderwidth=1, relief="solid")
        loot_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
        self.loot_text = tk.Text(loot_frame, height=6, state='disabled',
                                 bg=UI_COLORS["card_bg"], fg=UI_COLORS["text"],
                                 font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"]-1)),
                                 relief='flat', wrap='none')
        loot_scroll = ttk.Scrollbar(loot_frame, orient='vertical', command=self.loot_text.yview)
        self.loot_text.configure(yscrollcommand=loot_scroll.set)
        loot_scroll.pack(side='right', fill='y')
        self.loot_text.pack(fill='both', expand=True)
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

    def _show_help(self):
        """Show basic instructions for using the Survey Helper in a themed window."""
        help_text = (
            "Survey Helper quick guide:\n\n"
            "1. ChatLogs Folder: Point this to your Project Gorgon ChatLogs folder.\n\n"
            "2. Overlays: Use 'Show Overlays' to open the Map + Inventory helpers.\n"
            "   Move/resize them like normal windows; use 'Save Layout' to remember.\n\n"
            "3. Player Position: Double-click the map to set your spawn/player position.\n\n"
            "4. Calibrate: Double-click the first survey pin and drag it so the pin\n"
            "   sits exactly on the in-game red ring. This teaches the helper your\n"
            "   current map scale so later pins line up.\n\n"
            "5. Surveys: As you detect survey positions in chat, pins appear on the map\n"
            "   and numbered slots appear in the inventory overlay.\n\n"
            "6. Route: After positions are found, click 'Optimize Route' to get an\n"
            "   efficient path and step through it with Previous/Next/Skip.\n"
        )

        win = tk.Toplevel(self)
        win.title("Survey Helper Help")
        apply_theme(win)
        win.configure(bg=UI_COLORS["bg"])
        set_window_icon(win)
        win.transient(self)

        frame = tk.Frame(win, bg=UI_COLORS["panel_bg"])
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        text_widget = tk.Text(
            frame,
            height=14,
            wrap="word",
            bg=UI_COLORS["card_bg"],
            fg=UI_COLORS["text"],
            relief="flat",
            font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"] - 1)),
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)

        text_widget.insert("1.0", help_text)
        text_widget.config(state="disabled")

        btn_row = tk.Frame(win, bg=UI_COLORS["panel_bg"])
        btn_row.pack(fill="x", pady=(0, 6))
        ttk.Button(btn_row, text="Close", command=win.destroy, style="App.Secondary.TButton").pack(pady=2)
    
    def _set_survey_count(self):
        """Synchronize overlay with the internally tracked survey count.

        The manual "Survey Maps" controls have been removed; this now just
        keeps the inventory overlay in sync when count_var changes
        automatically from chat events.
        """
        count = max(0, self.count_var.get())
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
        # Enforce map click-through always OFF
        self.map_overlay.set_clickthrough(False)
        # Draw the player marker if origin is set
        if self.settings.origin_x is not None and self.settings.origin_y is not None:
            self.map_overlay._draw_player_dot()

    def _show_inventory(self):
        """Open (or restore) the inventory overlay."""
        if self.inventory_open:
            return
        
        # Calculate total slots: max of (found + remaining) or tracked total crafted
        total_crafted = len(self.items) + self.settings.survey_count
        if total_crafted > self._total_surveys_crafted:
            self._total_surveys_crafted = total_crafted
        total_slots = max(self._total_surveys_crafted, total_crafted, self.settings.survey_count)
        if total_slots == 0:
            total_slots = self.settings.survey_count
        
        if self.inv_overlay is None or not self.inv_overlay.winfo_exists():
            self.inv_overlay = InventoryOverlay(self, self.settings,
                                               on_close=self._on_inv_closed,
                                               next_callback=self._on_inv_next_clicked,
                                               activate_callback=self._start_ring_detection_for_item)
            # Set the display count first so grid draws enough slots
            self.inv_overlay._display_slot_count = total_slots
            self.inv_overlay.set_survey_count(total_slots)
        else:
            self.inv_overlay.deiconify()
            self.inv_overlay.lift()
            self.inv_overlay.after(1, lambda: self.inv_overlay.attributes('-alpha', self.settings.inv_opacity))
        self.inventory_open = True
        self.inv_opacity_var.set(int(self.settings.inv_opacity * 100))
        self._update_overlays_btn()
        # Enforce inventory click-through always ON
        self.inv_overlay.set_clickthrough(True)

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
        """Auto player detection is disabled; fall back to manual spawn set."""
        self._set_player_position()

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

        # Require a fairly strong match so we avoid snapping to the wrong
        # UI element. If this fails, we fall back to manual click-to-set.
        if best_shape_match > 0.35 or best_score < 130:
            return None

        return best_center

    def _apply_detected_player_marker(self, x: float, y: float):
        """Update the visible player marker from detected map coordinates.

        Also re-project all survey pins around the new origin so the
        player dot and pins stay in sync on the map.
        """
        self.settings.current_player_x = x
        self.settings.current_player_y = y
        if self.settings.origin_x is None or self.settings.origin_y is None:
            self.settings.origin_x = x
            self.settings.origin_y = y
        self.settings.save()
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay._draw_player_dot()
        # Recalculate survey item positions to match the new origin/player
        if getattr(self, "items", None):
            try:
                self._recalculate_item_positions()
            except Exception:
                # Failsafe: never let projection errors break the UI
                pass

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
            return
        self._apply_detected_player_marker(*center)

    def _start_ring_detection_for_current(self):
        """Arm ring watching for the current route item or first survey."""
        if self.current_route and self.current_route_index < len(self.current_route):
            self._start_ring_detection_for_item(self.current_route[self.current_route_index])
        elif self.items:
            self._start_ring_detection_for_item(0)
        else:
            self.status_var.set("No survey items available for ring detection")



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
        self.status_var.set("Ring watch running. Double-click a survey slot to arm it.")
        threading.Thread(target=self._ring_watch_worker, args=(bbox,), daemon=True).start()
        if self.current_route or self.items:
            self._start_ring_detection_for_current()

    def _stop_ring_watch(self, status_message: Optional[str] = None):
        """Stop the persistent ring watcher."""
        self._ring_watch_stop.set()
        self._ring_detection_active = False
        self._ring_detection_target = None
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

    def _auto_arm_ring_for_new_item(self, item_index: int):
        """Automatically start ring watch + arm the newest survey item.

        Used when a fresh survey position is parsed from chat so the
        player does not need to toggle ring watching manually.
        """
        if cv2 is None or np is None or ImageGrab is None:
            return
        if item_index < 0 or item_index >= len(self.items):
            return
        if not self._ring_detection_active:
            self._start_ring_watch()
            if not self._ring_detection_active:
                return
        self._ring_detection_target = item_index

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
        # Convert from pixels to logical map meters where south is +Y. A ring
        # north of the player has center_y < origin_y, giving dy_m < 0.
        item.dx_m = (center_x - self.settings.origin_x) / self.settings.scale_factor
        item.dy_m = (center_y - self.settings.origin_y) / self.settings.scale_factor
        item.distance = round(math.sqrt(item.dx_m ** 2 + item.dy_m ** 2), 1)
        item.direction = self._vector_to_direction(item.dx_m, item.dy_m)
        item.calibrated = True  # ring refined, but math pins still work without it

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
            0: 'E', 45: 'NE', 90: 'S', 135: 'SW',
            180: 'W', 225: 'NW', 270: 'N', 315: 'NE'
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
        self.settings.player_frac_x = None
        self.settings.player_frac_y = None
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
            # When the user clicks their spawn, remember that position as a
            # fraction of the current map canvas so we can project pins using
            # the canonical per-zone map sizes.
            if self.map_overlay and self.map_overlay.winfo_exists():
                try:
                    cw = max(self.map_overlay.canvas.winfo_width(), 1)
                    ch = max(self.map_overlay.canvas.winfo_height(), 1)
                    self.settings.player_frac_x = max(0.0, min(1.0, x / cw))
                    self.settings.player_frac_y = max(0.0, min(1.0, y / ch))
                except Exception:
                    self.settings.player_frac_x = None
                    self.settings.player_frac_y = None
            # Clear any legacy pixel-per-meter scale; canonical map math owns it now.
            self.settings.scale_factor = None
            self.settings.save()
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
            # When we have a canonical map size for this zone, pin dragging should
            # not mutate scale: positions come purely from survey math.
            if self.settings.zone_name and self.settings.zone_name in MAP_SIZES:
                self.status_var.set("Pin drag calibration is disabled when zone map size is known")
                self._recalculate_item_positions()
                return
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

        Prefer canonical per-zone map sizes (from MAP_SIZES) so that pins match
        the original pg_survey_helper math. If no canonical size is known for
        the current zone, fall back to the legacy pixel-per-meter scaling.
        """
        if not self.items:
            return

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

        # Common direction table (0 = East, CCW in radians)
        _dir_angles = {
            # Angles in radians, 0 = East, counter-clockwise, but we convert
            # to map meters where south is +Y (north is -Y).
            'E': 0.0,
            'NE': -math.pi / 4.0,
            'N': -math.pi / 2.0,
            'NW': -3.0 * math.pi / 4.0,
            'W': math.pi,
            'SW': 3.0 * math.pi / 4.0,
            'S': math.pi / 2.0,
            'SE': math.pi / 4.0,
        }

        # ── Canonical per-zone map math (preferred) ────────────────────────────
        zone = self.settings.zone_name
        map_size = MAP_SIZES.get(zone) if zone else None
        used_canonical = False
        if map_size is not None and cw > 1 and ch > 1 and has_real_origin:
            map_w, map_h = map_size

            # Player position in logical map meters, stored as fractions so it
            # survives window resizes, matching the web survey helper.
            frac_x = self.settings.player_frac_x
            frac_y = self.settings.player_frac_y
            if frac_x is None or frac_y is None:
                frac_x = max(0.0, min(1.0, ox / cw))
                frac_y = max(0.0, min(1.0, oy / ch))
                self.settings.player_frac_x = frac_x
                self.settings.player_frac_y = frac_y
                self.settings.save()

            player_x_m = frac_x * map_w
            player_y_m = frac_y * map_h

            for item in self.items:
                dx_m = item.dx_m
                dy_m = item.dy_m
                if dx_m is None or dy_m is None:
                    angle = _dir_angles.get(item.direction, 0.0)
                    dx_m = item.distance * math.cos(angle)
                    dy_m = item.distance * math.sin(angle)

                # In map space, +X is east and +Y is south. dx_m/dy_m are
                # already in that space, so just add them to the player.
                survey_x_m = player_x_m + dx_m
                survey_y_m = player_y_m + dy_m

                item.x = (survey_x_m / map_w) * cw
                item.y = (survey_y_m / map_h) * ch

            used_canonical = True

        # ── Legacy pixel-per-meter fallback ────────────────────────────────────
        if not used_canonical:
            sf = self.settings.scale_factor
            if sf is None:
                max_dist = max((item.distance for item in self.items if item.distance > 0), default=1.0)
                sf = (min(cw, ch) * 0.48) / max_dist
                self.settings.scale_factor = sf
                self.settings.save()

            if sf is None or sf <= 0:
                return

            for item in self.items:
                if item.dx_m is not None and item.dy_m is not None:
                    item.x = ox + item.dx_m * sf
                    item.y = oy + item.dy_m * sf
                else:
                    angle = _dir_angles.get(item.direction, 0.0)
                    dx_m = item.distance * math.cos(angle)
                    dy_m = item.distance * math.sin(angle)
                    item.x = ox + dx_m * sf
                    item.y = oy + dy_m * sf

        # Sync to MapOverlay's list and redraw
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.survey_items = self.items
            self.map_overlay.clear_items()
            # Build a display index map so that uncollected items are
            # renumbered 1..N with no gaps, and collected ones lose their
            # numbers. This mirrors pg_survey_helper's renumbering mode.
            display_map: Dict[int, int] = {}
            pos = 1
            for idx, it in enumerate(self.items):
                if not it.collected:
                    display_map[idx] = pos
                    pos += 1
            self.map_overlay._display_index_map = display_map
            for i, item in enumerate(self.items):
                self.map_overlay._draw_item(item, i)
            # Redraw route pins if a route is active
            if self.current_route:
                self.map_overlay.draw_route(self.current_route, self.current_route_index, self.items)


    def _toggle_pins_only_mode(self):
        """Toggle a mode where both overlays are dimmed to 20%.

        On: save the current Map % and Inv % as preferences, then set both to
        20% opacity so you can see the game clearly while still seeing pins and
        slots. Off: restore both sliders to the saved values.
        """
        enabled = self.pins_only_var.get()

        if enabled:
            # Snapshot current preferred opacity whenever the user turns Pins Only on.
            try:
                preferred_map_pct = max(0, min(100, self.map_opacity_var.get()))
            except tk.TclError:
                preferred_map_pct = int(self.settings.map_opacity * 100)
            if preferred_map_pct <= 0:
                preferred_map_pct = 40
            self._preferred_map_opacity = preferred_map_pct / 100.0

            try:
                preferred_inv_pct = max(0, min(100, self.inv_opacity_var.get()))
            except tk.TclError:
                preferred_inv_pct = int(self.settings.inv_opacity * 100)
            if preferred_inv_pct <= 0:
                preferred_inv_pct = 40
            self._preferred_inv_opacity = preferred_inv_pct / 100.0

            # Set both overlays to 20% (0.2) opacity if they are open; also keep
            # the spinboxes in sync.
            low_pct = 20
            low_value = 0.2

            self.map_opacity_var.set(low_pct)
            self.settings.map_opacity = low_value
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay.update_opacity(low_value)

            self.inv_opacity_var.set(low_pct)
            self.settings.inv_opacity = low_value
            if self.inv_overlay and self.inv_overlay.winfo_exists():
                self.inv_overlay.update_opacity(low_value)

            self.settings.save()
        else:
            # Restore last non-zero preferences, defaulting to 0.4 (40%) if unknown.
            restore_map = self._preferred_map_opacity
            if restore_map is None or restore_map <= 0.0:
                restore_map = 0.4
            restore_inv = self._preferred_inv_opacity
            if restore_inv is None or restore_inv <= 0.0:
                restore_inv = 0.4

            map_pct = int(round(restore_map * 100))
            inv_pct = int(round(restore_inv * 100))

            self.map_opacity_var.set(map_pct)
            self.settings.map_opacity = restore_map
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay.update_opacity(restore_map)

            self.inv_opacity_var.set(inv_pct)
            self.settings.inv_opacity = restore_inv
            if self.inv_overlay and self.inv_overlay.winfo_exists():
                self.inv_overlay.update_opacity(restore_inv)

            self.settings.save()

    def _update_map_opacity(self):
        """Update map overlay opacity (from percentage spinbox)."""
        try:
            percentage = self.map_opacity_var.get()
        except tk.TclError:
            return
        percentage = max(0, min(100, percentage))
        self.map_opacity_var.set(percentage)
        decimal_value = percentage / 100.0
        self.settings.map_opacity = decimal_value

        # Remember preferred map opacity when not in Pins Only mode.
        if not self.pins_only_var.get():
            self._preferred_map_opacity = decimal_value

        if self.map_overlay and self.map_overlay.winfo_exists():
            # Delegate to MapOverlay so it can choose between isolated
            # background mode and whole-window alpha based on platform.
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

        # Remember preferred inventory opacity when not in Pins Only mode.
        if not self.pins_only_var.get():
            self._preferred_inv_opacity = decimal_value

        if self.inv_overlay and self.inv_overlay.winfo_exists():
            # update_opacity() will call save() for us
            self.inv_overlay.update_opacity(decimal_value)
        else:
            # Overlay not open, save directly
            self.settings.save()
    

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
        # `survey_count` tracks remaining maps; the total crafted is
        # remaining + positions already found.
        total = self.settings.survey_count + len(self.items)
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
    
    # Map full compass words to (dx_unit, dy_unit) in logical map meters
    # where east = +X and **south = +Y**. This matches pg_survey_helper's
    # convention: north is negative Y, south is positive Y.
    _COMPASS_VECTORS = {
        'n': (0.0, -1.0), 'north': (0.0, -1.0),
        's': (0.0, 1.0), 'south': (0.0, 1.0),
        'e': (1.0, 0.0), 'east': (1.0, 0.0),
        'w': (-1.0, 0.0), 'west': (-1.0, 0.0),
        'ne': (0.7071, -0.7071), 'northeast': (0.7071, -0.7071),
        'nw': (-0.7071, -0.7071), 'northwest': (-0.7071, -0.7071),
        'se': (0.7071, 0.7071), 'southeast': (0.7071, 0.7071),
        'sw': (-0.7071, 0.7071), 'southwest': (-0.7071, 0.7071),
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
        # NOTE: count_var is internal-only; the manual "Survey Maps" UI has
        # been removed so users don't have to manage counts by hand.
        added_match = re.search(r'\[Status\]\s+(.+?)\s+added to inventory', line, re.IGNORECASE)
        if added_match:
            item_name = added_match.group(1).strip()
            if 'survey' in item_name.lower():
                # Survey map crafted — auto-increment counter
                new_count = self.count_var.get() + 1
                self.count_var.set(new_count)
                self._total_surveys_crafted = new_count  # Track total crafted
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

            # Check for duplicate survey positions for the *same* survey map.
            # If you click the same survey multiple times without moving, the
            # game will emit repeated "The X is ..." lines. Those should *not*
            # create new pins.
            for existing in reversed(self.items):  # check most recent first
                if not getattr(existing, 'name', None):
                    continue
                if existing.collected:
                    continue
                if existing.name.strip().lower() != name.lower():
                    continue
                # Treat as duplicate if both the direction and distance match
                # very closely. This is much stricter than the 8m dx/dy check
                # and is tuned specifically for repeated clicks on the same map.
                if (existing.direction == direction and
                        abs(existing.distance - total_dist) < 1.0):
                    self.status_var.set(
                        f"Duplicate position ignored for {name} ({total_dist:.0f}m {direction})"
                    )
                    return

            item = SurveyItem(
                name=name,
                distance=round(total_dist, 1),
                direction=direction,
                dx_m=dx_m,
                dy_m=dy_m,
                timestamp=datetime.now(),
                calibrated=True,  # text-based position is good enough for pins
            )

            self.items.append(item)

            # Each successful survey position means one map was just used.
            # Decrement the remaining survey map count, but never let it go
            # below zero. The inventory overlay's per-slot numbering is driven
            # by loot/collection events, not this counter.
            current = max(self.settings.survey_count, self.count_var.get())
            if current > 0:
                new_count = current - 1
                self.count_var.set(new_count)
                self.settings.survey_count = new_count
                # Update total crafted tracking (used + remaining)
                total_crafted = len(self.items) + new_count
                if total_crafted > self._total_surveys_crafted:
                    self._total_surveys_crafted = total_crafted
                self.settings.save()

            # Always compute/refresh map pins using math from origin, scale,
            # and the text offsets. This does not depend on ring detection.
            self._recalculate_item_positions()
            self.status_var.set(f"Found: {name} at {total_dist:.0f}m {direction}")

            self._update_session_info()
            self._set_phase(max(self.settings.current_phase, 2))
            return

        # ── 4. Loot / item collected ───────────────────────────────────────────
        # "[Status] Fluorite collected!"
        collected_match = re.search(r'\[Status\]\s+(.+?)\s+collected!', line, re.IGNORECASE)
        if collected_match:
            item_name = collected_match.group(1).strip()
            # Record loot, then let _mark_item_collected resolve which survey
            # this belongs to based on the name and current route.
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
        """Mark a survey item as collected by name.

        To avoid corrupting the overlays, we only act on *exact* name matches
        (case-insensitive) and never use loose substring matching.
        """
        target = name.strip().lower()

        # Exact case-insensitive matches for uncollected items
        exact_indices = [
            i for i, item in enumerate(self.items)
            if (not item.collected and item.name and item.name.strip().lower() == target)
        ]

        if not exact_indices:
            return

        # If we have a route, prefer the current route item when it matches
        chosen_index = None
        if self.current_route and 0 <= self.current_route_index < len(self.current_route):
            route_idx = self.current_route[self.current_route_index]
            if route_idx in exact_indices:
                chosen_index = route_idx

        if chosen_index is None:
            # Fall back to the first exact match
            chosen_index = exact_indices[0]

        item = self.items[chosen_index]
        item.collected = True

        if self.map_overlay and self.map_overlay.winfo_exists():
            # Completely remove the pin from the map
            self.map_overlay.clear_item(chosen_index)

        if self.inv_overlay and self.inv_overlay.winfo_exists():
            # Mark the corresponding inventory slot empty and let the
            # inventory overlay compact its labels based on its
            # internal mapping.
            self.inv_overlay.mark_slot_empty(chosen_index)

        # Redraw pins with compressed numbering
        try:
            self._recalculate_item_positions()
        except Exception:
            pass

        self.status_var.set(f"Collected: {item.name}")
        self._update_session_info()
        # Auto-advance route when item matches current next
        if (
            self.current_route
            and 0 <= self.current_route_index < len(self.current_route)
            and self.current_route[self.current_route_index] == chosen_index
        ):
            self.after(300, self._next_item)
    
    def _optimize_route(self):
        """Optimize route using nearest neighbor algorithm."""
        if not self.items:
            self.status_var.set("No items to optimize")
            return

        # Route selection must use the latest calibrated canvas positions.
        self._recalculate_item_positions()
        
        # Get uncollected items that have valid projected positions
        uncollected = [
            (i, item) for i, item in enumerate(self.items)
            if not item.collected and item.x is not None and item.y is not None
        ]
        
        if not uncollected:
            self.status_var.set("No uncollected survey positions available for routing")
            return
        
        # Use spawn/origin position as the route start. If we don't know it
        # yet, force the user to set/detect player position first so routes
        # are always anchored correctly on the map.
        if self.settings.origin_x is None or self.settings.origin_y is None:
            self.status_var.set("Set player position first (click your spawn on the map)")
            return
        start_x, start_y = self.settings.origin_x, self.settings.origin_y
        
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

        # After a reset, we no longer auto-detect the player marker. The user
        # sets spawn by clicking on the map when ready.
    
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
        """Restore map and/or inventory overlays.

        On first launch (no prior state), automatically show both overlays so
        new users immediately see the map + inventory helpers. On later runs,
        respect the last-opened state stored in settings.
        """
        if self.settings.map_was_open or (not self.settings.map_was_open and not self.settings.inventory_was_open):
            self._show_map()
        if self.settings.inventory_was_open or (not self.settings.map_was_open and not self.settings.inventory_was_open):
            self._show_inventory()


def open_survey_helper(parent):
    """Open the Survey Helper window."""
    window = SurveyHelperWindow(parent)
    window.protocol("WM_DELETE_WINDOW", window.on_close)
    return window
