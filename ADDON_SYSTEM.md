# PGLOK Addon System

PGLOK now supports a comprehensive addon system that allows external applications to integrate seamlessly with the main application.

## 🎯 Features

- **Automatic Addon Discovery** - Scans the addons directory for available addons
- **Dynamic Menu Integration** - Addons appear in the Addons menu automatically
- **Theme Integration** - Addons inherit PGLOK's dark theme
- **Window Management** - Addon windows are managed by PGLOK
- **Status Integration** - Addons can update PGLOK's status bar
- **Clean Architecture** - Addons are isolated but can communicate with PGLOK

## 📁 Addon Directory Structure

```
PGLOK/
├── addons/                    # Addons directory
│   └── BamBam/               # Example addon
│       ├── addon.json        # Addon manifest
│       ├── main.py           # Addon entry point
│       ├── src/              # Addon source code
│       ├── README.md         # Addon documentation
│       └── requirements.txt  # Addon dependencies
└── src/
    └── addons/               # Addon system
        └── __init__.py
```

## 🔧 Creating an Addon

### 1. Addon Manifest (addon.json)

Every addon needs a manifest file:

```json
{
  "name": "MyAddon",
  "version": "1.0.0",
  "description": "Description of your addon",
  "author": "Your Name",
  "entry_point": "main.py",
  "enabled": true,
  "icon": "",
  "category": "Tools"
}
```

**Manifest Fields:**
- `name`: Addon name (required)
- `version`: Addon version (required)
- `description`: Addon description (optional)
- `author`: Addon author (optional)
- `entry_point`: Entry point file (default: "main.py")
- `enabled`: Whether addon is enabled (default: true)
- `icon`: Icon file path (optional)
- `category`: Menu category (default: "General")

### 2. Addon Entry Point (main.py)

Your addon must provide an `AddonApp` class:

```python
import tkinter as tk
from tkinter import ttk

class AddonApp:
    """PGLOK Addon implementation."""
    
    def __init__(self, parent, pglok_app):
        self.parent = parent
        self.pglok_app = pglok_app
        
        # Build your addon UI here
        self._build_ui()
        
    def _build_ui(self):
        """Build the addon user interface."""
        # Your addon code here
        pass
        
    def cleanup(self):
        """Clean up resources when addon is closed."""
        pass
```

**Required Methods:**
- `__init__(self, parent, pglok_app)`: Initialize addon
- `cleanup(self)`: Clean up resources

**PGLOK Integration:**
- `self.parent`: The addon's window (tk.Toplevel)
- `self.pglok_app`: Reference to the main PGLOK application
- `self.pglok_app.status_var`: Update PGLOK status bar

### 3. Optional Standalone Support

For standalone compatibility, you can also provide a `BamBamApp` class:

```python
class BamBamApp:
    """Standalone version of your addon."""
    
    def __init__(self, root):
        self.root = root
        # Build standalone UI
```

## 🚀 Addon Categories

Addons are organized by category in the Addons menu:

- **Tools**: Utility addons
- **General**: General purpose addons
- **Development**: Development tools
- **Games**: Game-related addons
- **Utilities**: System utilities

## 🎨 Theme Integration

Addons automatically inherit PGLOK's theme:

```python
# Use PGLOK colors in your addon
try:
    from src.config.ui_theme import UI_COLORS
    self.colors = UI_COLORS
except:
    # Fallback colors
    self.colors = {
        "bg": "#2b2b2b",
        "fg": "#ffffff",
        "accent": "#0078d4",
        # ... more colors
    }
```

## 📋 Communication with PGLOK

### Status Updates
```python
# Update PGLOK status bar
self.pglok_app.status_var.set("MyAddon: Operation completed")
```

### Window Management
```python
# Center addon window on PGLOK
parent_x = self.pglok_app.root.winfo_x()
parent_y = self.pglok_app.root.winfo_y()
# Calculate position...
```

## 🔍 Available Addons

### BamBam (Example Addon)

**Description**: A modular GUI application framework
**Version**: 1.0.0
**Category**: Tools
**Features**:
- Complete menu system with keyboard shortcuts
- Toolbar with common actions
- Status bar with progress indicator
- Resizable paned interface
- Dark theme styling
- PGLOK integration

**Access**: Addons → Tools → BamBam v1.0.0

## 🛠️ Development Tips

### 1. Testing Your Addon

```python
# Test standalone
python3 your_addon/main.py

# Test as PGLOK addon
# Place in addons/YourAddon/ and restart PGLOK
```

### 2. Debugging

```python
# Add debug prints
print(f"Addon loaded: {self.pglok_app}")

# Check PGLOK integration
print(f"PGLOK status: {self.pglok_app.status_var.get()}")
```

### 3. Error Handling

```python
def cleanup(self):
    """Clean up resources when addon is closed."""
    try:
        # Clean up your resources
        pass
    except Exception as e:
        print(f"Addon cleanup error: {e}")
```

## 📦 Distribution

### Package Your Addon

1. Create addon directory in `PGLOK/addons/YourAddon/`
2. Include all necessary files
3. Test with PGLOK
4. Document features in README.md

### Share Your Addon

1. Export your addon directory
2. Include installation instructions
3. Share with the PGLOK community

## 🔧 Advanced Features

### Custom Menu Items

Addons can add custom menu items to PGLOK:

```python
# In your addon
def _add_custom_menu(self):
    menu = tk.Menu(self.pglok_app.addons_menu, tearoff=0)
    self.pglok_app.addons_menu.add_cascade(label="MyAddon", menu=menu)
```

### Configuration

Addons can store configuration:

```python
import json
from pathlib import Path

config_file = Path(__file__).parent / "config.json"
config = json.load(config_file.open())
```

### Data Persistence

Addons can store data in PGLOK's data directory:

```python
from src.config import DATA_DIR
addon_data_dir = DATA_DIR / "your_addon"
addon_data_dir.mkdir(exist_ok=True)
```

## 🎉 Getting Started

1. **Create addon directory**: `mkdir addons/MyAddon`
2. **Create manifest**: `echo '{}' > addons/MyAddon/addon.json`
3. **Create entry point**: `cp addons/BamBam/main.py addons/MyAddon/`
4. **Customize**: Edit the files for your addon
5. **Test**: Restart PGLOK and check Addons menu

## 📚 Examples

See the `addons/BamBam/` directory for a complete example addon implementation.

---

**Ready to create your own addon?** Start with the BamBam example and customize it for your needs!
