# BamBam Addon Theme Integration Fixes

## Problem
The BamBam addon was failing to launch with error: `"button_bg" can not be found` because it was trying to use color names that don't exist in PGLOK's theme system.

## Solution
Updated the BamBam addon to properly use PGLOK's color scheme by mapping PGLOK's actual color names to the addon's expected color names.

## Changes Made

### 1. Theme Color Mapping
**File**: `addons/BamBam/main.py` - `_setup_theme()` method

**Before**:
```python
# This failed because PGLOK doesn't have "button_bg" color
from src.config.ui_theme import UI_COLORS
self.colors = UI_COLORS
```

**After**:
```python
# Map PGLOK colors to addon expected names
from src.config.ui_theme import UI_COLORS
self.colors = {
    "bg": UI_COLORS.get("bg", "#060507"),
    "fg": UI_COLORS.get("text", "#ddd6c8"),
    "accent": UI_COLORS.get("primary", "#8d321e"),
    "button_bg": UI_COLORS.get("primary", "#8d321e"),  # Fixed
    "button_fg": UI_COLORS.get("text", "#ddd6c8"),
    "panel_bg": UI_COLORS.get("panel_bg", "#140f0e"),
    "card_bg": UI_COLORS.get("card_bg", "#1e1413"),
    "primary_active": UI_COLORS.get("primary_active", "#a63a22"),
    "secondary": UI_COLORS.get("secondary", "#3a231d"),
    "secondary_active": UI_COLORS.get("secondary_active", "#4c2e26"),
    "accent_color": UI_COLORS.get("accent", "#d8b564")
}
```

### 2. Style Configuration Updates
Updated all style configurations to use the correct PGLOK colors:

- **Frame styles**: Use `panel_bg` and `card_bg` instead of generic colors
- **Button styles**: Use `primary_active` for hover states, `secondary` for secondary buttons
- **Label styles**: Use `accent_color` for status labels
- **Entry styles**: Added `insertcolor` for text cursor
- **Progress bar**: Use `accent_color` for progress indication

### 3. Menu Theme Integration
Updated all menu colors to use PGLOK's `primary_active` instead of generic `accent`:

```python
# All menus now use PGLOK's primary active color
activebackground=self.colors["primary_active"]
```

### 4. Fallback Theme
Added comprehensive fallback colors that match PGLOK's dark theme style:

```python
# Fallback colors (matching PGLOK style)
self.colors = {
    "bg": "#060507",           # PGLOK background
    "fg": "#ddd6c8",           # PGLOK text
    "accent": "#8d321e",       # PGLOK primary
    "button_bg": "#8d321e",    # PGLOK primary
    "panel_bg": "#140f0e",     # PGLOK panel
    "card_bg": "#1e1413",      # PGLOK card
    # ... more colors
}
```

## PGLOK Color Scheme Used

| Addon Color | PGLOK Source | Hex Value |
|-------------|---------------|-----------|
| bg | UI_COLORS["bg"] | #060507 |
| fg | UI_COLORS["text"] | #ddd6c8 |
| accent | UI_COLORS["primary"] | #8d321e |
| button_bg | UI_COLORS["primary"] | #8d321e |
| button_fg | UI_COLORS["text"] | #ddd6c8 |
| panel_bg | UI_COLORS["panel_bg"] | #140f0e |
| card_bg | UI_COLORS["card_bg"] | #1e1413 |
| primary_active | UI_COLORS["primary_active"] | #a63a22 |
| secondary | UI_COLORS["secondary"] | #3a231d |
| secondary_active | UI_COLORS["secondary_active"] | #4c2e26 |
| accent_color | UI_COLORS["accent"] | #d8b564 |

## Result

The BamBam addon now:
- ✅ **Uses PGLOK's exact color scheme**
- ✅ **Matches PGLOK's dark theme appearance**
- ✅ **Integrates seamlessly with the main application**
- ✅ **Maintains consistent visual style**
- ✅ **Has proper fallback colors if PGLOK theme fails**

## Testing

To test the fixed addon:

1. **Start PGLOK**: `~/.local/bin/PGLOK`
2. **Launch Addon**: Click "Addons → Tools → BamBam v1.0.0"
3. **Verify Theme**: The addon should open with the same dark theme as PGLOK
4. **Check Integration**: All UI elements should match PGLOK's styling

## Files Modified

- `addons/BamBam/main.py`: Updated theme integration and color mapping
- `addons/BamBam/test_theme.py`: Created test script (optional)

The addon should now launch successfully and look like a native part of PGLOK!
