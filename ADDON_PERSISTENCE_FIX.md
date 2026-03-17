# Addon Window Persistence Fix

## Problem
The BamBam addon window position and size settings were not persistent between sessions.

## Root Causes
1. **Incorrect Path Usage**: Using `self.pglok_app.addons_dir` instead of `self.addons_dir`
2. **Timing Issues**: Saving geometry before window was properly sized (1x1)
3. **Missing Event Bindings**: Not enough events to trigger geometry saving
4. **Invalid Event Filtering**: Not filtering out invalid configure events

## Solution Applied

### 1. Fixed Path References
**Before:**
```python
geometry_file = self.pglok_app.addons_dir / f"{addon_name}_geometry.json"
```

**After:**
```python
geometry_file = self.addons_dir / f"{addon_name}_geometry.json"
```

### 2. Improved Geometry Saving with Timing
**Before:**
```python
def _save_addon_geometry(self, addon_name: str, window):
    geometry_data = {
        "geometry": window.geometry(),
        "timestamp": time.time()
    }
```

**After:**
```python
def _save_addon_geometry(self, addon_name: str, window):
    # Wait for window to be properly sized
    window.update_idletasks()
    geometry = window.geometry()
    
    # Only save if window has proper size (not 1x1)
    if "1x1" in geometry:
        print(f"Skipping geometry save for {addon_name} - window not properly sized yet")
        return
    
    geometry_data = {
        "geometry": geometry,
        "timestamp": time.time()
    }
```

### 3. Enhanced Event Bindings
**Added multiple event bindings:**
```python
# Configure event (resize/move)
addon_window.bind("<Configure>", lambda e: self._on_addon_configure(addon_name, e))

# Focus out (when window loses focus)
addon_window.bind("<FocusOut>", lambda e: self.pglok_app.root.after(200, lambda: self._save_addon_geometry(addon_name, addon_window)))

# Map/Unmap (window show/hide)
addon_window.bind("<Map>", lambda e: self.pglok_app.root.after(200, lambda: self._save_addon_geometry(addon_name, addon_window)))
addon_window.bind("<Unmap>", lambda e: self.pglok_app.root.after(200, lambda: self._save_addon_geometry(addon_name, addon_window)))
```

### 4. Improved Configure Event Handling
**Before:**
```python
def _on_addon_configure(self, addon_name: str, event):
    # Save geometry on resize (debounced)
    self._addon_save_timer = self.pglok_app.root.after(500, save_geometry)
```

**After:**
```python
def _on_addon_configure(self, addon_name: str, event):
    # Only save on actual resize/move events
    if event.width <= 1 or event.height <= 1:
        return  # Ignore invalid events
    
    # Per-addon timer management
    if hasattr(self, '_addon_save_timers'):
        if addon_name in self._addon_save_timers:
            self.pglok_app.root.after_cancel(self._addon_save_timers[addon_name])
    else:
        self._addon_save_timers = {}
    
    def save_geometry():
        # Add delay to ensure proper sizing
        self.pglok_app.root.after(100, lambda: self._save_addon_geometry(addon_name, window))
    
    self._addon_save_timers[addon_name] = self.pglok_app.root.after(1000, save_geometry)
```

### 5. Delayed Geometry Application
**Before:**
```python
# Apply saved geometry immediately
self._apply_saved_addon_geometry(addon_name, addon_window)
```

**After:**
```python
# Apply saved geometry after window is ready
self.pglok_app.root.after(100, lambda: self._apply_saved_addon_geometry(addon_name, addon_window))
```

## Key Features

### ✅ **Multiple Save Triggers**
- **Configure Events**: Window resize/move (debounced 1 second)
- **Focus Out**: When window loses focus (200ms delay)
- **Map/Unmap**: When window is shown/hidden (200ms delay)
- **Window Close**: Before window destruction

### ✅ **Smart Timing**
- **Update Idle Tasks**: Ensures window is properly sized before saving
- **1x1 Filter**: Ignores saves when window is not properly sized
- **Delays**: 100-200ms delays to ensure proper geometry
- **Debouncing**: Prevents excessive saves during resizing

### ✅ **Per-Addon Management**
- **Individual Timers**: Each addon has its own save timer
- **Separate Files**: Each addon has its own geometry file
- **Clean Cleanup**: Proper timer and reference cleanup

### ✅ **Error Handling & Debugging**
- **Logging**: Print statements for debugging geometry operations
- **Exception Handling**: Graceful error handling with continue
- **Path Validation**: Uses correct addon directory path

## Files Modified

### `src/addons/__init__.py`
- Fixed path references in `_apply_saved_addon_geometry()` and `_save_addon_geometry()`
- Enhanced `_save_addon_geometry()` with timing and validation
- Improved `_on_addon_configure()` with per-addon timer management
- Added multiple event bindings for comprehensive coverage
- Added delayed geometry application

## Testing Results

### ✅ **Test Suite Results**
```
🧪 Testing Addon Window Persistence...
✅ Addons directory: /home/jgcampbell300/PGLOK/addons
✅ Addons directory exists: True
✅ Saved geometry: 800x600+100+100
✅ Geometry applied correctly: 800x600+100+100
🎉 Persistence tests passed!
```

## Usage

### **For Users:**
1. **Launch Addon**: Open any addon from the Addons menu
2. **Resize/Move**: Resize and position the window as desired
3. **Close Window**: Close the addon window
4. **Re-launch**: Launch the same addon again
5. **Verify**: Window opens in the same position and size

### **For Developers:**
- **Geometry Files**: Stored in `addons/{addon_name}_geometry.json`
- **Format**: `{"geometry": "1000x700+100+100", "timestamp": 1234567890.0}`
- **Debugging**: Check console output for geometry save/apply messages

## Result

**Addon window position and size settings are now fully persistent!**

- ✅ **Position Saved**: Window X/Y coordinates remembered
- ✅ **Size Saved**: Window width/height remembered  
- ✅ **Multiple Triggers**: Various events ensure persistence
- ✅ **Smart Timing**: Prevents invalid saves and ensures proper sizing
- ✅ **Per-Addon**: Each addon maintains its own geometry independently
- ✅ **Error Resistant**: Graceful handling of edge cases and errors
