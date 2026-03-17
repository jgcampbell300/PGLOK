#!/usr/bin/env python3
"""
Simple test for farming addon
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    print("Testing import...")
    from addons.farming_automation.addon import FarmingAutomationAddon
    print("Import successful")
    
    print("Testing instantiation...")
    # Create a simple mock
    class MockApp:
        def __init__(self):
            self.db_manager = None
            self.current_user_id = 1
            self.root = None
            
        def apply_theme_to_window(self, window):
            return {}, {}
    
    app = MockApp()
    print("Mock app created")
    
    # This should fail gracefully since db_manager is None
    try:
        addon = FarmingAutomationAddon(app)
        print("Addon created successfully")
    except Exception as e:
        print(f"Addon creation failed: {e}")
        import traceback
        traceback.print_exc()
    
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
