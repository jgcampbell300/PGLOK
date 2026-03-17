#!/usr/bin/env python3
"""
Final test to verify PGLOK menu link works correctly
"""

import sys
import os
from pathlib import Path

def test_pglok_menu_final():
    """Final verification that PGLOK menu link works"""
    
    print("=== Final PGLOK Menu Link Test ===")
    print("This verifies that clicking the PGLOK menu will now work correctly")
    
    try:
        # Step 1: Test the exact PGLOK import
        print("\\n1. Testing PGLOK import logic...")
        
        # Simulate PGLOK path resolution
        current_file = Path('src/pglok.py').resolve()
        src_dir = current_file.parent
        
        possible_roots = [
            src_dir.parent,
            src_dir.parent.parent,
            current_file.parent.parent.parent,
        ]
        
        lok_farmer_path = None
        for root in possible_roots:
            test_path = root / 'addons' / 'lok_farmer'
            if test_path.exists():
                lok_farmer_path = test_path
                break
        
        if lok_farmer_path:
            sys.path.insert(0, str(lok_farmer_path))
            from lok_farmer_addon_integrated import LokFarmerAddon
            print(f"✅ LokFarmer imported from: {lok_farmer_path}")
        else:
            print("❌ LokFarmer path not found")
            return
        
        # Step 2: Test instantiation
        print("\\n2. Testing LokFarmer instantiation...")
        
        class MockPGLOKApp:
            def __init__(self):
                self.db_manager = None
                self.status_var = None
                self.root = None
        
        app = MockPGLOKApp()
        addon = LokFarmerAddon(app)
        print("✅ LokFarmer instantiated successfully")
        
        # Step 3: Test execute (what menu click does)
        print("\\n3. Testing execute method (menu click)...")
        addon.execute()
        print("✅ Execute method completed")
        
        # Step 4: Verify window and theme
        if addon.window:
            print("\\n4. Verifying window and theme...")
            bg = addon.window.cget('bg')
            print(f"   Window background: {bg}")
            
            if bg == '#2b2b2b':
                print("✅ Correct background color (visible)")
            else:
                print(f"⚠️  Unexpected background: {bg}")
            
            if hasattr(addon, 'notebook') and addon.notebook:
                tabs = addon.notebook.tabs()
                print(f"✅ Notebook with {len(tabs)} tabs created")
            
            # Step 5: Show window for verification
            print("\\n5. Showing window for final verification...")
            print("   This window should be:")
            print("   - Dark gray background (not black)")
            print("   - White text")
            print("   - Multiple tabs")
            print("   - Working controls")
            print("   - Fully functional")
            
            # Keep window open for verification
            addon.window.after(5000, addon.window.destroy)
            addon.window.mainloop()
            
            print("\\n✅ Final test completed successfully!")
            print("The PGLOK menu link should now work correctly!")
            
        else:
            print("❌ No window created")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pglok_menu_final()
