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
    
    def to_dict(self):
        return {
            'name': self.name,
            'distance': self.distance,
            'direction': self.direction,
            'x': self.x,
            'y': self.y,
            'collected': self.collected,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
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
            timestamp=ts
        )


class SurveySettings:
    """Manages survey helper settings."""
    
    SETTINGS_FILE = Path(__file__).parent / 'survey_settings.json'
    
    def __init__(self):
        self.chatlog_dir: Optional[Path] = None
        self.survey_count: int = 0
        self.map_opacity: float = 0.7
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
        self.main_window_position: Optional[Tuple[int, int]] = None  # (x, y)
        self.main_window_size: Optional[Tuple[int, int]] = None  # (width, height)
        self.map_was_open: bool = False  # whether map was open on last close
        self.inventory_was_open: bool = False  # whether inventory was open on last close
        
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
                
                if data.get('main_window_position'):
                    self.main_window_position = tuple(data['main_window_position'])
                if data.get('main_window_size'):
                    self.main_window_size = tuple(data['main_window_size'])
                
                self.map_was_open = data.get('map_was_open', False)
                self.inventory_was_open = data.get('inventory_was_open', False)
                
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
            'main_window_position': list(self.main_window_position) if self.main_window_position else None,
            'main_window_size': list(self.main_window_size) if self.main_window_size else None,
            'map_was_open': self.map_was_open,
            'inventory_was_open': self.inventory_was_open,
        }
        
        try:
            with open(self.SETTINGS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving survey settings: {e}")


def _set_clickthrough_x11(tk_win, enabled: bool):
    """Enable or disable X11 input pass-through using the SHAPE extension.

    Clicks land on the WM frame (which reparents our window), so we must
    walk UP the X11 tree to find the direct child of root and apply SHAPE
    to it and ALL descendants — including Tk's internal wrapper windows,
    the Toplevel, and every child widget.
    """
    try:
        from Xlib import display, X
        from Xlib.ext.shape import SO, SK
        d = display.Display()
        root_id = d.screen().root.id

        # Walk up from the Tk window to find the outermost X11 window
        # (direct child of root = WM frame or, with overrideredirect, Tk's frame)
        xid = tk_win.winfo_id()
        current = d.create_resource_object('window', xid)
        while True:
            parent = current.query_tree().parent
            if parent.id == root_id:
                break
            current = parent
        outermost = current

        def apply_recursive(win):
            if enabled:
                win.shape_rectangles(SO.Set, SK.Input, X.Unsorted, 0, 0, [])
            else:
                win.shape_combine(SO.Set, SK.Input, 0, 0, win, SK.Bounding)
            for child in win.query_tree().children:
                apply_recursive(child)

        apply_recursive(outermost)
        d.flush()
        d.close()
    except Exception as e:
        print(f"Click-through not available: {e}")


class MapOverlay(tk.Toplevel):
    """Transparent overlay window for the map with survey dots."""
    
    def __init__(self, parent, settings: SurveySettings, on_click_callback=None, on_close=None):
        super().__init__(parent)
        self.settings = settings
        self.on_click_callback = on_click_callback
        self.on_close_callback = on_close
        
        self.title("Survey Map")
        self.attributes('-topmost', True)
        # Don't set opacity yet - will be set after window settles
        
        # Set window icon for taskbar
        set_window_icon(self)
        
        # Remove window decorations
        self.overrideredirect(False)
        
        # Canvas for drawing
        self.canvas = tk.Canvas(self, bg=UI_COLORS["card_bg"], highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Items to display
        self.survey_items: List[SurveyItem] = []
        self.player_dot = None
        self.scale_indicator = None
        
        # Dragging
        self._drag_data = {'x': 0, 'y': 0}
        self._is_setting_position = False
        
        # Skip Configure events during initialization
        self._skip_configure = True
        
        # Bind events
        self.canvas.bind('<Button-1>', self._on_click)
        self.canvas.bind('<Button-3>', self._start_drag)
        self.canvas.bind('<B3-Motion>', self._on_drag)
        self.bind('<Configure>', self._on_resize)
        
        # Resize handle
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
        
        # Restore clickthrough if previously enabled - deferred to after window maps
        # Enable Configure tracking and apply opacity after window settles
        self.after(500, self._enable_configure_tracking_and_opacity)
    
    def _create_resize_handle(self):
        """Create a resize handle in the bottom-right corner."""
        self.resize_handle = tk.Frame(self, bg=UI_COLORS["secondary"], width=15, height=15)
        self.resize_handle.place(relx=1.0, rely=1.0, anchor='se')
        self.resize_handle.bind('<Button-1>', self._start_resize)
        self.resize_handle.bind('<B1-Motion>', self._on_resize_drag)
    
    def _start_resize(self, event):
        self._resize_start = {'x': event.x_root, 'y': event.y_root, 'w': self.winfo_width(), 'h': self.winfo_height()}
    
    def _on_resize_drag(self, event):
        if hasattr(self, '_resize_start'):
            dx = event.x_root - self._resize_start['x']
            dy = event.y_root - self._resize_start['y']
            new_w = max(100, self._resize_start['w'] + dx)
            new_h = max(100, self._resize_start['h'] + dy)
            self.geometry(f"{new_w}x{new_h}")
    
    def _enable_configure_tracking(self):
        """Enable Configure event tracking after window initialization."""
        self._skip_configure = False
    
    def _enable_configure_tracking_and_opacity(self):
        """Enable Configure tracking and apply opacity after window settles."""
        self._skip_configure = False
        self.attributes('-alpha', self.settings.map_opacity)
        if self.settings.map_clickthrough:
            self.set_clickthrough(True)
    
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
    
    def _on_click(self, event):
        if self._is_setting_position:
            # Setting player position
            self.settings.origin_x = event.x
            self.settings.origin_y = event.y
            self._is_setting_position = False
            self._draw_player_dot()
            if self.on_click_callback:
                self.on_click_callback(event.x, event.y, 'set_origin')
        else:
            # Check if clicked on an item
            items = self.canvas.find_overlapping(event.x-10, event.y-10, event.x+10, event.y+10)
            for item in items:
                tags = self.canvas.gettags(item)
                if tags and tags[0].startswith('item_'):
                    idx = int(tags[0].split('_')[1])
                    if self.on_click_callback:
                        self.on_click_callback(event.x, event.y, 'item_clicked', idx)
    
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
        
        if self.settings.origin_x and self.settings.origin_y:
            x, y = self.settings.origin_x, self.settings.origin_y
            self.player_dot = self.canvas.create_oval(
                x-5, y-5, x+5, y+5,
                fill=UI_COLORS["accent"], outline=UI_COLORS["text"], width=2,
                tags='player'
            )
    
    def add_survey_item(self, item: SurveyItem) -> bool:
        """Add a survey item to the map. Returns True if placed automatically."""
        if self.settings.scale_factor is None or self.settings.origin_x is None:
            # Need calibration first
            return False
        
        # Calculate position based on distance and direction
        angle = self._direction_to_angle(item.direction)
        dx = item.distance * math.cos(angle) * self.settings.scale_factor
        dy = item.distance * math.sin(angle) * self.settings.scale_factor
        
        item.x = self.settings.origin_x + dx
        item.y = self.settings.origin_y - dy  # Y is inverted in canvas
        
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
        
        # Dot
        self.canvas.create_oval(
            item.x-8, item.y-8, item.x+8, item.y+8,
            fill=color, outline=UI_COLORS["text"], width=2,
            tags=(f'item_{index}', f'item_dot_{index}')
        )
        
        # Label
        self.canvas.create_text(
            item.x, item.y-15,
            text=f"{index+1}. {item.name[:15]}",
            fill=UI_COLORS["text"], font=(UI_ATTRS["font_family"], max(8, UI_ATTRS["font_size"]-2), 'bold'),
            tags=(f'item_{index}', f'item_label_{index}')
        )
        
        # Distance line
        if self.settings.origin_x:
            self.canvas.create_line(
                self.settings.origin_x, self.settings.origin_y,
                item.x, item.y,
                fill=UI_COLORS["accent"], dash=(3, 3), width=1,
                tags=(f'item_{index}', f'item_line_{index}')
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
        self.canvas.delete('item_')
    
    def mark_collected(self, index: int):
        """Mark an item as collected."""
        if 0 <= index < len(self.survey_items):
            self.survey_items[index].collected = True
            # Redraw as gray
            self.canvas.itemconfig(f'item_dot_{index}', fill='gray')
    
    def highlight_next(self, index: int):
        """Highlight the next item to collect."""
        # Reset all highlights
        for i in range(len(self.survey_items)):
            if not self.survey_items[i].collected:
                self.canvas.itemconfig(f'item_dot_{i}', outline='white', width=2)
        
        # Highlight next
        if 0 <= index < len(self.survey_items):
            self.canvas.itemconfig(f'item_dot_{index}', outline='red', width=4)
    
    def update_opacity(self, value: float):
        """Update window opacity."""
        self.attributes('-alpha', value)
        self.settings.map_opacity = value
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
        """Close window, ensuring all settings are saved first."""
        self.settings.save()
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()
    
    def _on_close(self):
        """Handle window close event - save position/size before closing."""
        self.settings.save()
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()


class InventoryOverlay(tk.Toplevel):
    """Transparent overlay window for inventory grid."""
    
    def __init__(self, parent, settings: SurveySettings, on_close=None):
        super().__init__(parent)
        self.settings = settings
        self.on_close_callback = on_close
        
        self.title("Survey Inventory")
        self.attributes('-topmost', True)
        # Don't set opacity yet - will be set after window settles
        
        # Set window icon for taskbar
        set_window_icon(self)
        
        self.canvas = tk.Canvas(self, bg=UI_COLORS["card_bg"], highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Dragging
        self._drag_data = {'x': 0, 'y': 0}
        
        # Skip Configure events during initialization
        self._skip_configure = True
        
        # Bind events
        self.canvas.bind('<Button-3>', self._start_drag)
        self.canvas.bind('<B3-Motion>', self._on_drag)
        self.bind('<Configure>', self._on_resize)
        
        # Resize handle
        self._create_resize_handle()
        
        # Close handler to save position/size
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Slots
        self.slots: List[int] = []  # Canvas item IDs
        self.filled_slots: set = set()
        
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
        
        # Enable Configure tracking and apply opacity after window settles
        self.after(500, self._enable_configure_tracking_and_opacity)
    
    def _create_resize_handle(self):
        self.resize_handle = tk.Frame(self, bg=UI_COLORS["secondary"], width=15, height=15)
        self.resize_handle.place(relx=1.0, rely=1.0, anchor='se')
        self.resize_handle.bind('<Button-1>', self._start_resize)
        self.resize_handle.bind('<B1-Motion>', self._on_resize_drag)
    
    def _start_resize(self, event):
        self._resize_start = {'x': event.x_root, 'y': event.y_root, 
                              'w': self.winfo_width(), 'h': self.winfo_height()}
    
    def _on_resize_drag(self, event):
        if hasattr(self, '_resize_start'):
            dx = event.x_root - self._resize_start['x']
            dy = event.y_root - self._resize_start['y']
            new_w = max(100, self._resize_start['w'] + dx)
            new_h = max(100, self._resize_start['h'] + dy)
            self.geometry(f"{new_w}x{new_h}")
            self._recalculate_grid()
    
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
                    fill=UI_COLORS["text"], font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], 'bold')
                )
                
                self.slots.append(rect)
    
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
        self._calculate_size()
        self._draw_grid()
        self.settings.save()
    
    def mark_slot_filled(self, index: int):
        """Mark a slot as having a survey map."""
        if 0 <= index < len(self.slots):
            self.filled_slots.add(index)
            self.canvas.itemconfig(f'slot_{index}', fill='green', outline='white')
    
    def mark_slot_empty(self, index: int):
        """Mark a slot as empty (collected)."""
        if index in self.filled_slots:
            self.filled_slots.remove(index)
            self.canvas.itemconfig(f'slot_{index}', fill='darkgray', outline='gray')
    
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
        """Close window, ensuring all settings are saved first."""
        self.settings.save()
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()
    
    def _on_close(self):
        """Handle window close event - save position/size before closing."""
        self.settings.save()
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()


class SurveyHelperWindow(tk.Toplevel):
    """Main control panel for the Survey Helper."""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.title("Survey Helper")
        
        self.settings = SurveySettings()
        self.items: List[SurveyItem] = []
        self.current_route: List[int] = []
        self.current_route_index = 0
        self.session_start: Optional[datetime] = None
        
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
        
        # Title
        ttk.Label(frame, text="🔍 Survey Helper", style="App.Header.TLabel").pack(pady=3)
        
        # ChatLog directory - use tk.LabelFrame with dark theme colors
        dir_frame = tk.LabelFrame(frame, text="ChatLogs Folder", padx=4, pady=3,
                                  bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"], 
                                  font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                  borderwidth=1, relief="solid")
        dir_frame.pack(fill='x', pady=3)
        
        self.dir_var = tk.StringVar(value=str(self.settings.chatlog_dir) if self.settings.chatlog_dir else "Not set")
        ttk.Label(dir_frame, textvariable=self.dir_var, wraplength=300, style="App.TLabel").pack(fill='x')
        ttk.Button(dir_frame, text="💬 Set Folder", command=self._set_chatlog_dir, style="App.Secondary.TButton").pack(pady=1)
        
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
        
        ttk.Label(arrange_frame, text="Blank Spaces Before 1st Item:", style="App.TLabel").pack(anchor='w')
        self.offset_var = tk.IntVar(value=self.settings.inv_offset)
        offset_spinbox = ttk.Spinbox(arrange_frame, from_=0, to=100, textvariable=self.offset_var, width=5, style="App.TSpinbox")
        offset_spinbox.pack(side='left', padx=4)
        ttk.Button(arrange_frame, text="Apply", command=self._set_inv_offset, style="App.Secondary.TButton").pack(side='left', padx=4)
        
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
        
        ttk.Button(grid_frame, text="Apply", command=self._apply_grid_settings, style="App.Secondary.TButton").pack(side='left', padx=2)
        
        # Overlay controls - use tk.LabelFrame with dark theme colors
        overlay_frame = tk.LabelFrame(frame, text="Overlays", padx=4, pady=3,
                                      bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                      font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                      borderwidth=1, relief="solid")
        overlay_frame.pack(fill='x', pady=3)
        
        btn_frame = tk.Frame(overlay_frame, bg=UI_COLORS["panel_bg"])
        btn_frame.pack(fill='x', pady=1)
        
        self.map_button = ttk.Button(btn_frame, text="🗺 Show Map", command=self._show_map, style="App.Secondary.TButton")
        self.map_button.pack(side='left', padx=2)
        self.inv_button = ttk.Button(btn_frame, text="📦 Show Inventory", command=self._show_inventory, style="App.Secondary.TButton")
        self.inv_button.pack(side='left', padx=2)
        
        # Position setting
        ttk.Button(overlay_frame, text="📍 Set My Position", command=self._set_player_position, style="App.Secondary.TButton").pack(fill='x', pady=1)
        
        # Opacity controls - use Spinbox for precise values (in percentage)
        opacity_frame = tk.Frame(overlay_frame, bg=UI_COLORS["panel_bg"])
        opacity_frame.pack(fill='x', pady=1)
        
        ttk.Label(opacity_frame, text="Map Opacity %:", style="App.TLabel").pack(side='left', padx=4)
        self.map_opacity_var = tk.IntVar(value=int(self.settings.map_opacity * 100))
        self.map_opacity_spinbox = ttk.Spinbox(opacity_frame, from_=10, to=100, textvariable=self.map_opacity_var, width=5,
                   style="App.TSpinbox", command=self._update_map_opacity)
        self.map_opacity_spinbox.pack(side='left', padx=2)
        self.map_opacity_spinbox.bind('<Return>', lambda e: self._update_map_opacity())
        self.map_opacity_spinbox.bind('<FocusOut>', lambda e: self._update_map_opacity())
        
        ttk.Label(opacity_frame, text="Inv Opacity %:", style="App.TLabel").pack(side='left', padx=4)
        self.inv_opacity_var = tk.IntVar(value=int(self.settings.inv_opacity * 100))
        self.inv_opacity_spinbox = ttk.Spinbox(opacity_frame, from_=10, to=100, textvariable=self.inv_opacity_var, width=5,
                   style="App.TSpinbox", command=self._update_inv_opacity)
        self.inv_opacity_spinbox.pack(side='left', padx=2)
        self.inv_opacity_spinbox.bind('<Return>', lambda e: self._update_inv_opacity())
        self.inv_opacity_spinbox.bind('<FocusOut>', lambda e: self._update_inv_opacity())
        
        # Click-through toggle buttons
        clickthrough_frame = tk.Frame(overlay_frame, bg=UI_COLORS["panel_bg"])
        clickthrough_frame.pack(fill='x', pady=1)
        
        self.map_clickthrough_var = tk.BooleanVar(value=self.settings.map_clickthrough)
        self.map_clickthrough_btn = ttk.Button(clickthrough_frame, text="🗺 Click-Through: OFF", command=self._toggle_map_clickthrough, style="App.Secondary.TButton")
        self.map_clickthrough_btn.pack(side='left', padx=2)
        self._update_map_clickthrough_btn()
        
        self.inv_clickthrough_var = tk.BooleanVar(value=self.settings.inv_clickthrough)
        self.inv_clickthrough_btn = ttk.Button(clickthrough_frame, text="📦 Click-Through: OFF", command=self._toggle_inv_clickthrough, style="App.Secondary.TButton")
        self.inv_clickthrough_btn.pack(side='left', padx=2)
        self._update_inv_clickthrough_btn()
        
        # Route optimization - use tk.LabelFrame with dark theme colors
        route_frame = tk.LabelFrame(frame, text="Route Optimization", padx=4, pady=3,
                                    bg=UI_COLORS["panel_bg"], fg=UI_COLORS["text"],
                                    font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"], "bold"),
                                    borderwidth=1, relief="solid")
        route_frame.pack(fill='x', pady=3)
        
        ttk.Button(route_frame, text="🗺 Optimize Route", command=self._optimize_route, style="App.Secondary.TButton").pack(fill='x', pady=1)
        
        self.route_info_var = tk.StringVar(value="No route active")
        ttk.Label(route_frame, textvariable=self.route_info_var, style="App.TLabel").pack(pady=1)
        
        nav_frame = tk.Frame(route_frame, bg=UI_COLORS["panel_bg"])
        nav_frame.pack(fill='x', pady=1)
        ttk.Button(nav_frame, text="← Previous", command=self._prev_item, style="App.Secondary.TButton").pack(side='left', padx=2)
        ttk.Button(nav_frame, text="Next →", command=self._next_item, style="App.Secondary.TButton").pack(side='left', padx=2)
        ttk.Button(nav_frame, text="Skip", command=self._skip_item, style="App.Secondary.TButton").pack(side='left', padx=2)
        
        # Session info
        self.session_var = tk.StringVar(value="Items found: 0")
        ttk.Label(frame, textvariable=self.session_var, style="App.Title.TLabel").pack(pady=3)
        
        # Reset
        ttk.Button(frame, text="🔄 Reset Session", command=self._reset_session, style="App.Secondary.TButton").pack(fill='x', pady=3)
        
        # Status
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var, style="App.Status.TLabel").pack(pady=1)
    
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
        count = self.count_var.get()
        self.settings.survey_count = count
        self.settings.save()
        
        if self.inv_overlay:
            self.inv_overlay.set_survey_count(count)
        
        # Mark all slots as filled initially
        for i in range(count):
            if self.inv_overlay:
                self.inv_overlay.mark_slot_filled(i)
    
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
        """Apply new grid column, slot size, and gap settings."""
        cols = self.cols_var.get()
        slot_size = self.slot_size_var.get()
        gap = self.gap_var.get()
        
        self.settings.grid_cols = cols
        self.settings.slot_size = slot_size
        self.settings.slot_gap = gap
        self.settings.save()
        
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay._draw_grid()  # Redraw with new settings
    
    def _show_map(self):
        """Toggle the map overlay open/closed."""
        if self.map_open:
            # Close the map
            if self.map_overlay and self.map_overlay.winfo_exists():
                self.map_overlay._close_window()
            self.map_open = False
            self.map_button.config(text="🗺 Show Map")
        else:
            # Open the map
            if self.map_overlay is None or not self.map_overlay.winfo_exists():
                self.map_overlay = MapOverlay(self, self.settings, self._on_map_click, 
                                             on_close=self._on_map_closed)
            else:
                self.map_overlay.lift()
            self.map_open = True
            self.map_button.config(text="🗺 Hide Map")
            # Ensure spinbox is in sync with overlay opacity (convert decimal to percentage)
            self.map_opacity_var.set(int(self.settings.map_opacity * 100))
    
    def _on_map_closed(self):
        """Called when map overlay is closed by user."""
        self.map_open = False
        if self.map_button:
            self.map_button.config(text="🗺 Show Map")
    
    def _show_inventory(self):
        """Toggle the inventory overlay open/closed."""
        if self.inventory_open:
            # Close the inventory
            if self.inv_overlay and self.inv_overlay.winfo_exists():
                self.inv_overlay._close_window()
            self.inventory_open = False
            self.inv_button.config(text="📦 Show Inventory")
        else:
            # Open the inventory
            if self.inv_overlay is None or not self.inv_overlay.winfo_exists():
                self.inv_overlay = InventoryOverlay(self, self.settings,
                                                   on_close=self._on_inv_closed)
                # Fill slots based on survey count
                for i in range(self.settings.survey_count):
                    self.inv_overlay.mark_slot_filled(i)
            else:
                self.inv_overlay.lift()
            self.inventory_open = True
            self.inv_button.config(text="📦 Hide Inventory")
            # Ensure spinbox is in sync with overlay opacity (convert decimal to percentage)
            self.inv_opacity_var.set(int(self.settings.inv_opacity * 100))
    
    def _on_inv_closed(self):
        """Called when inventory overlay is closed by user."""
        self.inventory_open = False
        if self.inv_button:
            self.inv_button.config(text="📦 Show Inventory")
    
    def _set_player_position(self):
        """Enable player position setting mode."""
        self._show_map()
        self.map_overlay.set_setting_position_mode(True)
        self.status_var.set("Click on map to set your position")
    
    def _on_map_click(self, x: float, y: float, action: str, item_index: Optional[int] = None):
        """Handle map click events."""
        if action == 'set_origin':
            self.status_var.set(f"Player position set: ({x:.0f}, {y:.0f})")
        elif action == 'item_clicked' and item_index is not None:
            # Calibrate from this item
            if self.settings.scale_factor is None:
                self.map_overlay.calibrate_from_click(item_index, x, y)
                self.status_var.set(f"Scale calibrated: {self.settings.scale_factor:.2f} px/m")
    
    def _update_map_opacity(self):
        """Update map overlay opacity (from percentage spinbox)."""
        try:
            percentage = self.map_opacity_var.get()
        except tk.TclError:
            return
        percentage = max(10, min(100, percentage))
        self.map_opacity_var.set(percentage)
        decimal_value = percentage / 100.0
        self.settings.map_opacity = decimal_value
        if self.map_overlay and self.map_overlay.winfo_exists():
            # update_opacity() will call save() for us
            self.map_overlay.update_opacity(decimal_value)
        else:
            # Overlay not open, save directly
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
    
    def _toggle_map_clickthrough(self):
        """Toggle map click-through mode."""
        enabled = not self.map_clickthrough_var.get()
        self.map_clickthrough_var.set(enabled)
        self.settings.map_clickthrough = enabled
        self.settings.save()
        if self.map_overlay and self.map_overlay.winfo_exists():
            self.map_overlay.set_clickthrough(enabled)
        self._update_map_clickthrough_btn()
    
    def _toggle_inv_clickthrough(self):
        """Toggle inventory click-through mode."""
        enabled = not self.inv_clickthrough_var.get()
        self.inv_clickthrough_var.set(enabled)
        self.settings.inv_clickthrough = enabled
        self.settings.save()
        if self.inv_overlay and self.inv_overlay.winfo_exists():
            self.inv_overlay.set_clickthrough(enabled)
        self._update_inv_clickthrough_btn()
    
    def _update_map_clickthrough_btn(self):
        """Update map click-through button text."""
        state = "ON" if self.map_clickthrough_var.get() else "OFF"
        self.map_clickthrough_btn.config(text=f"🗺 Click-Through: {state}")
    
    def _update_inv_clickthrough_btn(self):
        """Update inventory click-through button text."""
        state = "ON" if self.inv_clickthrough_var.get() else "OFF"
        self.inv_clickthrough_btn.config(text=f"📦 Click-Through: {state}")
    
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
    
    def _parse_chat_line(self, line: str):
        """Parse chat line for survey and collection messages."""
        # Survey message pattern: [Status] The X is Ym DIR
        # Example: [Status] The Ancient Tombstone is 45m NE
        survey_match = re.search(
            r'\[Status\]\s*The\s+(\S+(?:\s+\S+)*)\s+is\s+(\d+)m?\s*(N|NE|E|SE|S|SW|W|NW)?',
            line,
            re.IGNORECASE
        )
        
        if survey_match:
            name = survey_match.group(1).strip()
            distance = float(survey_match.group(2))
            direction = survey_match.group(3) or 'N'
            
            item = SurveyItem(
                name=name,
                distance=distance,
                direction=direction.upper(),
                timestamp=datetime.now()
            )
            
            self.items.append(item)
            
            # Try to add to map
            if self.map_overlay:
                auto_placed = self.map_overlay.add_survey_item(item)
                if not auto_placed:
                    self.status_var.set(f"Found: {name} - Click map to calibrate")
                else:
                    self.status_var.set(f"Found: {name} at {distance}m {direction}")
            
            self._update_session_info()
            return
        
        # Collection message pattern: "X collected!" or "You receive X"
        collection_patterns = [
            r'([^"]+)\s+collected!',
            r'You\s+receive\s+(\S+(?:\s+\S+)*)',
            r'You\s+loot\s+(\S+(?:\s+\S+)*)',
        ]
        
        for pattern in collection_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                item_name = match.group(1).strip()
                self._mark_item_collected(item_name)
                break
    
    def _mark_item_collected(self, name: str):
        """Mark a survey item as collected."""
        # Find matching item
        for i, item in enumerate(self.items):
            if not item.collected and name.lower() in item.name.lower():
                item.collected = True
                
                if self.map_overlay:
                    self.map_overlay.mark_collected(i)
                
                # Remove from inventory grid
                if self.inv_overlay:
                    self.inv_overlay.mark_slot_empty(i)
                
                self.status_var.set(f"Collected: {item.name}")
                self._update_session_info()
                break
    
    def _optimize_route(self):
        """Optimize route using nearest neighbor algorithm."""
        if not self.items:
            self.status_var.set("No items to optimize")
            return
        
        if self.settings.origin_x is None:
            self.status_var.set("Set player position first")
            return
        
        # Get uncollected items
        uncollected = [(i, item) for i, item in enumerate(self.items) if not item.collected]
        
        if not uncollected:
            self.status_var.set("All items collected!")
            return
        
        # Nearest neighbor algorithm
        route = []
        current_x, current_y = self.settings.origin_x, self.settings.origin_y
        remaining = uncollected.copy()
        
        while remaining:
            # Find nearest item
            nearest_idx = None
            nearest_dist = float('inf')
            
            for idx, (item_idx, item) in enumerate(remaining):
                dist = math.sqrt((item.x - current_x)**2 + (item.y - current_y)**2)
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
        
        self._highlight_next_item()
        self._update_route_info()
        self.status_var.set(f"Route optimized: {len(route)} items")
    
    def _highlight_next_item(self):
        """Highlight the next item in the route."""
        if self.map_overlay and self.current_route_index < len(self.current_route):
            idx = self.current_route[self.current_route_index]
            self.map_overlay.highlight_next(idx)
    
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
            if self.map_overlay:
                self.map_overlay.mark_collected(idx)
            self._next_item()
    
    def _update_route_info(self):
        """Update route information display."""
        if self.current_route and self.current_route_index < len(self.current_route):
            idx = self.current_route[self.current_route_index]
            item = self.items[idx]
            self.route_info_var.set(f"Next: {item.name} ({item.distance}m {item.direction})")
        else:
            self.route_info_var.set("Route complete!")
    
    def _update_session_info(self):
        """Update session statistics."""
        total = len(self.items)
        collected = sum(1 for item in self.items if item.collected)
        self.session_var.set(f"Items: {collected}/{total} collected")
    
    def _reset_session(self):
        """Reset the current session."""
        self.items = []
        self.current_route = []
        self.current_route_index = 0
        self.session_start = None
        
        if self.map_overlay:
            self.map_overlay.survey_items = []
            self.map_overlay.clear_items()
        
        if self.inv_overlay:
            self.inv_overlay.clear_all()
            for i in range(self.settings.survey_count):
                self.inv_overlay.mark_slot_filled(i)
        
        self.session_var.set("Items found: 0")
        self.route_info_var.set("No route active")
        self.status_var.set("Session reset")
    
    def on_close(self):
        """Clean up on window close."""
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
