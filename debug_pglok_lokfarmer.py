#!/usr/bin/env python3
"""
Debug script for PGLOK LokFarmer black screen issue
"""

import sys
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

# Add paths like PGLOK does
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'addons'))
sys.path.insert(0, str(Path(__file__).parent / 'addons' / 'lok_farmer'))

def test_pglok_lokfarmer():
    """Test LokFarmer exactly as PGLOK would load it"""
    
    print("=== PGLOK LokFarmer Debug Test ===")
    
    try:
        # Import exactly like PGLOK does
        from lok_farmer_addon_integrated import LokFarmerAddon
        print("✅ LokFarmerAddon imported successfully")
        
        # Create mock PGLOK app
        class MockPGLOKApp:
            def __init__(self):
                self.db_manager = None
                self.status_var = None
                self.root = tk.Tk()
                self.root.withdraw()  # Hide main window like PGLOK does
        
        app = MockPGLOKApp()
        print("✅ Mock PGLOK app created")
        
        # Create LokFarmer addon instance
        addon = LokFarmerAddon(app)
        print("✅ LokFarmerAddon instantiated successfully")
        
        # Execute the addon (this is what PGLOK calls)
        print("\n=== Executing LokFarmer (PGLOK method) ===")
        addon.execute()
        print("✅ LokFarmer executed successfully")
        
        # Check if window was created
        if addon.window:
            print(f"✅ Window created: {addon.window}")
            print(f"Window title: {addon.window.title()}")
            print(f"Window geometry: {addon.window.geometry()}")
            print(f"Window background: {addon.window.cget('bg')}")
            
            # Check if notebook exists
            if hasattr(addon, 'notebook') and addon.notebook:
                print(f"✅ Notebook created: {addon.notebook}")
                print(f"Number of tabs: {len(addon.notebook.tabs())}")
                
                # Check first tab
                if len(addon.notebook.tabs()) > 0:
                    first_tab = addon.notebook.nametowidget(addon.notebook.tabs()[0])
                    print(f"✅ First tab: {first_tab}")
                    
                    # Check tab background
                    try:
                        tab_bg = first_tab.cget('bg')
                        print(f"First tab background: {tab_bg}")
                    except:
                        print("Could not get tab background")
                
                # Update window to ensure rendering
                addon.window.deiconify()
                addon.window.lift()
                addon.window.focus_force()
                addon.window.update_idletasks()
                addon.window.update()
                
                print("\n=== Window Should Be Visible Now ===")
                print("Check if the window shows:")
                print("- Dark gray background (#2b2b2b)")
                print("- White text")
                print("- Multiple tabs")
                print("- Control buttons")
                
                # Keep window open for inspection
                print("\nWindow will stay open for 5 seconds...")
                addon.window.after(5000, addon.window.destroy)
                addon.window.mainloop()
                
            else:
                print("❌ Notebook not created")
        else:
            print("❌ Window not created")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pglok_lokfarmer()
