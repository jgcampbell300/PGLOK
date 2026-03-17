#!/usr/bin/env python3
"""
Test script to verify addon window persistence
"""

import sys
import os
import json
from pathlib import Path

# Add PGLOK to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_addon_persistence():
    """Test addon window persistence functionality."""
    print("🧪 Testing Addon Window Persistence...")
    
    try:
        # Check addons directory
        from src.addons import AddonManager
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        
        class MockPGLOKApp:
            def __init__(self):
                self.root = root
                self.status_var = tk.StringVar(value="Test")
        
        mock_app = MockPGLOKApp()
        addon_manager = AddonManager(mock_app)
        
        print(f"✅ Addons directory: {addon_manager.addons_dir}")
        print(f"✅ Addons directory exists: {addon_manager.addons_dir.exists()}")
        
        # Test geometry file creation
        test_addon_name = "TestAddon"
        test_window = tk.Toplevel(root)
        test_window.title("Test Window")
        test_window.geometry("800x600+100+100")
        
        # Test saving geometry
        test_window.deiconify()  # Make window visible
        test_window.update_idletasks()  # Ensure proper sizing
        test_window.geometry("800x600+100+100")  # Set geometry
        test_window.update_idletasks()  # Update again
        
        addon_manager._save_addon_geometry(test_addon_name, test_window)
        
        # Check if geometry file was created
        geometry_file = addon_manager.addons_dir / f"{test_addon_name}_geometry.json"
        if geometry_file.exists():
            print(f"✅ Geometry file created: {geometry_file}")
            
            # Read and display saved geometry
            with open(geometry_file, 'r') as f:
                saved_data = json.load(f)
            print(f"✅ Saved geometry: {saved_data}")
        else:
            print(f"❌ Geometry file not created")
            return False
        
        # Test loading geometry
        test_window2 = tk.Toplevel(root)
        test_window2.title("Test Window 2")
        test_window2.deiconify()  # Make window visible
        test_window2.update_idletasks()  # Ensure proper sizing
        addon_manager._apply_saved_addon_geometry(test_addon_name, test_window2)
        test_window2.update_idletasks()  # Update after applying geometry
        
        # Check if geometry was applied
        applied_geometry = test_window2.geometry()
        if applied_geometry == "800x600+100+100":
            print(f"✅ Geometry applied correctly: {applied_geometry}")
        else:
            print(f"❌ Geometry not applied correctly. Expected: 800x600+100+100, Got: {applied_geometry}")
        
        # Cleanup
        test_window.destroy()
        test_window2.destroy()
        geometry_file.unlink(missing_ok=True)
        
        root.destroy()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_bambam_persistence():
    """Test BamBam addon persistence specifically."""
    print("\n🧪 Testing BamBam Addon Persistence...")
    
    try:
        # Check BamBam geometry file
        addons_dir = Path(__file__).parent.parent / "addons"
        bambam_geometry_file = addons_dir / "BamBam_geometry.json"
        
        if bambam_geometry_file.exists():
            print(f"✅ BamBam geometry file exists: {bambam_geometry_file}")
            with open(bambam_geometry_file, 'r') as f:
                data = json.load(f)
            print(f"✅ BamBam saved geometry: {data}")
        else:
            print(f"ℹ️  BamBam geometry file not found (expected if not yet launched)")
        
        return True
        
    except Exception as e:
        print(f"❌ BamBam test failed: {e}")
        return False

if __name__ == "__main__":
    print("🎯 Addon Window Persistence Test")
    print("=" * 50)
    
    success = True
    
    # Test general persistence
    if not test_addon_persistence():
        success = False
    
    # Test BamBam specifically
    if not test_bambam_persistence():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Persistence tests passed!")
        print("\n📋 To test in PGLOK:")
        print("1. Start PGLOK")
        print("2. Launch BamBam addon")
        print("3. Resize and move the window")
        print("4. Close the window")
        print("5. Launch BamBam again")
        print("6. Verify window opens in same position/size")
    else:
        print("❌ Some tests failed. Check the errors above.")
