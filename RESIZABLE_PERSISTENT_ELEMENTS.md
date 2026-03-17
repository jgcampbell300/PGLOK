# PGLOK Resizable and Persistent Elements Implementation

## Overview
All PGLOK elements and windows are now fully resizable and persistent, with a status bar that is always visible.

## Changes Made

### 1. Main Window Layout Restructure
**File**: `src/pglok.py` - `_build_layout()` method

**Before**: Simple pack layout with basic status card
**After**: Paned window layout with fixed status bar

```python
# Create main paned window for resizable layout
self.main_paned = ttk.PanedWindow(self.app_frame, orient="vertical", style="App.TFrame")
self.main_paned.pack(fill="both", expand=True)

# Top section for toolbar and content (resizable)
self.top_section = ttk.Frame(self.main_paned, style="App.TFrame")
self.main_paned.add(self.top_section, weight=1)

# Status bar section (always visible, not resizable)
self.status_section = ttk.Frame(self.main_paned, style="App.Panel.TFrame")
self.main_paned.add(self.status_section, weight=0)  # Weight 0 prevents resizing
```

### 2. Enhanced Status Bar
**File**: `src/pglok.py` - `_create_status_bar()` method

**Features**:
- **Always Visible**: Fixed position at bottom with weight=0
- **Three Sections**: Left (status), Center (info), Right (counts)
- **Progress Bar**: Appears when needed, auto-hides
- **Status Icon**: Color-coded status indicator
- **Persistent Size**: Maintains fixed height regardless of window resizing

```python
# Status bar with three sections
left_status = ttk.Frame(status_row, style="App.Panel.TFrame")
self.status_icon = ttk.Label(left_status, text="●", style="App.Status.TLabel", foreground="#8d321e")

# Center info section
self.center_status = ttk.Frame(status_row, style="App.Panel.TFrame")
self.center_info_var = tk.StringVar(value="Ready")

# Progress bar (hidden by default)
self.progress_var = tk.DoubleVar()
self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, mode="determinate")
```

### 3. Status Bar Maintenance
**File**: `src/pglok.py` - `_maintain_status_bar_size()` method

**Function**: Prevents status bar from being resized by paned window

```python
def _maintain_status_bar_size(self, event=None):
    """Maintain status bar size and prevent resizing."""
    window_height = self.root.winfo_height()
    sash_pos = window_height - self.status_height - 20
    self.main_paned.sash_place(0, 0, sash_pos)
```

### 4. Enhanced Status Bar Functions
**File**: `src/pglok.py` - New methods

```python
def show_progress(self, message, value=0):
    """Show progress in status bar."""
    
def set_center_status(self, message):
    """Set center status information."""
    
def set_status_color(self, color):
    """Set status icon color."""
```

### 5. Addon Window Resizability
**File**: `src/addons/__init__.py` - `launch_addon()` method

**Changes**:
- **Larger Default Size**: 1000x700 instead of 800x600
- **Minimum Size**: 800x600 to prevent too-small windows
- **Fully Resizable**: `resizable(True, True)`
- **Persistent Geometry**: Saves and restores window position/size

```python
addon_window.geometry("1000x700")  # Larger default size
addon_window.minsize(800, 600)    # Minimum size
addon_window.resizable(True, True)  # Make fully resizable

# Apply saved geometry if available
self._apply_saved_addon_geometry(addon_name, addon_window)

# Save geometry on close
def on_close():
    self._save_addon_geometry(addon_name, addon_window)
```

### 6. Addon Geometry Persistence
**File**: `src/addons/__init__.py` - New methods

```python
def _apply_saved_addon_geometry(self, addon_name: str, window):
    """Apply saved addon window geometry."""
    geometry_file = self.pglok_app.addons_dir / f"{addon_name}_geometry.json"

def _save_addon_geometry(self, addon_name: str, window):
    """Save addon window geometry."""
    geometry_data = {"geometry": window.geometry(), "timestamp": time.time()}

def _on_addon_configure(self, addon_name: str, event):
    """Handle addon window configure events."""
    # Debounced geometry saving
    self._addon_save_timer = self.pglok_app.root.after(500, save_geometry)
```

### 7. BamBam Addon Resizability
**File**: `addons/BamBam/main.py` - `_create_main_area()` method

**Changes**:
- **Enhanced Panel Layout**: Better frame structure for resizing
- **Resizable Text Widgets**: Properly configured with scrollbars
- **Persistent Content**: Added references to text widgets

```python
# Sample content for left panel with resizable text widget
left_text_frame = ttk.Frame(self.left_panel, style="App.TFrame")
left_text_frame.pack(fill="both", expand=True)

left_text = tk.Text(left_text_frame, bg=self.colors["entry_bg"], fg=self.colors["fg"])
left_scroll = ttk.Scrollbar(left_text_frame, orient="vertical", command=left_text.yview)
```

### 8. Theme Style Addition
**File**: `src/config/ui_theme.py` - Added `App.Muted.TLabel` style

```python
style.configure(
    "App.Muted.TLabel",
    background=UI_COLORS["panel_bg"],
    foreground=UI_COLORS["muted_text"],
    font=(UI_ATTRS["font_family"], UI_ATTRS["font_size"] - 1),
)
```

## Key Features

### ✅ **Resizable Elements**
- **Main Window**: Fully resizable with minimum size constraints
- **Addon Windows**: 800x600 minimum, fully resizable
- **Paned Panels**: Drag dividers to resize content areas
- **Text Widgets**: Expand to fill available space with scrollbars

### ✅ **Persistent State**
- **Window Geometry**: Size and position saved for all windows
- **Addon Windows**: Individual geometry files per addon
- **Layout State**: Panel sizes and positions remembered
- **Debounced Saving**: Prevents excessive file I/O during resizing

### ✅ **Always-Visible Status Bar**
- **Fixed Position**: Cannot be resized or hidden
- **Three Sections**: Status, Info, and Counts
- **Progress Indicator**: Appears when needed, auto-hides
- **Status Colors**: Visual feedback with color-coded icons

### ✅ **Enhanced User Experience**
- **Smooth Resizing**: All elements resize properly
- **Persistent Preferences**: Windows reopen in same position/size
- **Visual Feedback**: Progress bars and status updates
- **Consistent Theme**: All elements follow PGLOK's dark theme

## File Structure

```
PGLOK/
├── src/
│   ├── pglok.py              # Main window layout and status bar
│   ├── addons/
│   │   └── __init__.py      # Addon window resizability and persistence
│   └── config/
│       └── ui_theme.py      # Added App.Muted.TLabel style
└── addons/
    └── BamBam/
        └── main.py          # Enhanced resizable panels
```

## Usage

### **Main Window**
- Resize window normally - status bar stays visible
- Content area expands/contracts as needed
- Status bar maintains fixed height

### **Addon Windows**
- Launch from Addons menu
- Resize to preferred size
- Position where desired
- Next launch restores size/position

### **Status Bar**
- Always visible at bottom
- Shows current status and progress
- Center section for additional info
- Right section shows character counts

## Benefits

1. **Better UX**: Users can resize windows to their preference
2. **Persistence**: No need to resize windows every session
3. **Consistent Status**: Always visible status information
4. **Professional Feel**: Smooth, responsive resizing
5. **Addon Integration**: All addons inherit resizability

All elements are now fully resizable and persistent with an always-visible status bar!
