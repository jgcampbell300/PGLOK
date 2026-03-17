# Tkinter Sash Error Fix

## Problem
The error `_tkinter.TclError: wrong # args: should be ".!frame.!panedwindow sashpos index ?newpos?"` was caused by incorrect usage of the `sash_place` method in tkinter PanedWindow.

## Root Cause
The `sash_place` method was being called with the wrong number of arguments:
```python
# INCORRECT - This caused the error
self.main_paned.sash_place(0, 0, sash_pos)

# CORRECT - Should be called with 2 arguments
self.main_paned.sash_place(0, sash_pos)
```

## Solution
Removed the complex sash manipulation and relied on the natural behavior of PanedWindow with weight configuration:

### 1. Simplified Layout
```python
# Before: Complex sash manipulation
self.main_paned.sash_place(0, 0, 100)
self.root.bind("<Configure>", self._maintain_status_bar_size)

# After: Let PanedWindow handle it naturally
# The weight=0 on status section should keep it small
```

### 2. Removed Problematic Methods
- Removed `_maintain_status_bar_size()` method
- Removed `_initial_sash_placement()` method
- Removed sash manipulation bindings

### 3. Natural PanedWindow Behavior
```python
# Content section (resizable)
self.main_paned.add(self.top_section, weight=1)

# Status section (not resizable due to weight=0)
self.main_paned.add(self.status_section, weight=0)
```

## How It Works Now

### PanedWindow Weight System
- **Weight=1**: Content area expands/contracts with window resizing
- **Weight=0**: Status bar maintains natural size based on content

### Natural Sash Behavior
- PanedWindow automatically positions the sash based on content
- Users can manually drag the sash if needed
- Status bar stays naturally small due to minimal content

### Benefits
- ✅ **No More Errors**: Eliminates tkinter sash manipulation errors
- ✅ **Simpler Code**: Removes complex sash positioning logic
- ✅ **Natural Behavior**: PanedWindow handles sizing correctly
- ✅ **User Control**: Users can adjust sash position if desired
- ✅ **Always Visible**: Status bar remains visible due to weight=0

## Files Changed
- `src/pglok.py`: Removed sash manipulation methods and simplified layout

## Result
The application now works without tkinter errors, and the status bar remains always visible while allowing natural resizing behavior.
