#!/usr/bin/env python3
"""
Test script for farming addon
"""

import sys
import tkinter as tk
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Import required modules
from src.database.database_manager import get_database_manager
from addons.farming_automation.addon import FarmingAutomationAddon

# Create mock root window
root = tk.Tk()
root.withdraw()  # Hide the main window

# Create mock app
class MockApp:
    def __init__(self):
        self.db_manager = get_database_manager()
        self.current_user_id = 1
        self.root = root
        
    def apply_theme_to_window(self, window):
        """Apply PGLOK theme to a window."""
        from src.config.ui_theme import UI_COLORS, UI_ATTRS
        window.configure(bg=UI_COLORS["bg"])
        window.option_add("*Font", (UI_ATTRS["font_family"], UI_ATTRS["font_size"]))
        return UI_COLORS, UI_ATTRS

try:
    print("Creating mock app...")
    app = MockApp()
    
    print("Creating farming addon...")
    farming_addon = FarmingAutomationAddon(app)
    
    print("Executing farming addon...")
    farming_addon.execute()
    
    print("Farming addon created successfully!")
    print("Window should be visible now...")
    
    # Keep window open for testing
    root.mainloop()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
