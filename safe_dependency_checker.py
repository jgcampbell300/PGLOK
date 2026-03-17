#!/usr/bin/env python3
"""
Safe wrapper for dependency checker to prevent crashes
"""

import sys
import traceback
from pathlib import Path

# Add PGLOK to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def safe_check_dependencies(pglok_app):
    """Safely check dependencies without crashing."""
    try:
        print("🔍 Starting safe dependency check...")
        
        # Check if we can import the dependency checker
        try:
            from dependency_checker import DependencyChecker
            print("✅ DependencyChecker imported successfully")
        except ImportError as e:
            print(f"❌ Failed to import DependencyChecker: {e}")
            return False
        
        # Create checker instance
        try:
            checker = DependencyChecker(pglok_app)
            print("✅ DependencyChecker created successfully")
        except Exception as e:
            print(f"❌ Failed to create DependencyChecker: {e}")
            return False
        
        # Check dependencies
        try:
            installed, missing = checker.check_dependencies()
            print(f"✅ Dependency check completed: {len(installed)} installed, {len(missing)} missing")
            
            # Show status
            status = checker.get_dependency_status()
            print("\n📋 Dependency Status:")
            for pkg, info in status.items():
                status_text = "✓" if info["installed"] else "✗"
                optional_text = "(optional)" if info["optional"] else "(required)"
                used_by = info.get("addon_specific", "PGLOK Core")
                print(f"  {status_text} {pkg} {optional_text} - {used_by}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to check dependencies: {e}")
            traceback.print_exc()
            return False
            
    except Exception as e:
        print(f"❌ Unexpected error in safe dependency check: {e}")
        traceback.print_exc()
        return False

def safe_show_dependency_checker(pglok_app):
    """Safely show dependency checker window without crashing."""
    try:
        print("🔍 Starting safe dependency checker window...")
        
        # Check if tkinter is available
        try:
            import tkinter as tk
            from tkinter import messagebox
        except ImportError as e:
            print(f"❌ Tkinter not available: {e}")
            return False
        
        # Check if PGLOK root window exists
        if not pglok_app or not hasattr(pglok_app, 'root') or not pglok_app.root:
            print("❌ PGLOK root window not available")
            return False
        
        # Try to update root window to check if it's still valid
        try:
            pglok_app.root.update()
        except tk.TclError:
            print("❌ PGLOK root window no longer exists")
            return False
        
        # Import and create dependency checker
        from dependency_checker import DependencyChecker
        checker = DependencyChecker(pglok_app)
        
        # Try to show the window
        try:
            window = checker.show_dependency_checker()
            if window:
                print("✅ Dependency checker window opened successfully")
                return True
            else:
                print("❌ Dependency checker window failed to open")
                return False
        except Exception as e:
            print(f"❌ Failed to show dependency checker window: {e}")
            traceback.print_exc()
            
            # Show error message to user
            try:
                messagebox.showerror("Error", f"Failed to open dependency checker: {e}")
            except:
                print("Could not show error message")
            
            return False
            
    except Exception as e:
        print(f"❌ Unexpected error in safe dependency checker: {e}")
        traceback.print_exc()
        
        # Show error message to user if possible
        try:
            import tkinter as tk
            from tkinter import messagebox
            messagebox.showerror("Error", f"An error occurred: {e}")
        except:
            print("Could not show error message")
        
        return False

if __name__ == "__main__":
    print("🎯 Safe Dependency Checker Test")
    print("=" * 50)
    
    # Test safe dependency check
    print("\n🧪 Testing safe dependency check...")
    success = safe_check_dependencies(None)
    
    if success:
        print("✅ Safe dependency check test passed!")
    else:
        print("❌ Safe dependency check test failed!")
    
    print("\n🚀 Use safe_show_dependency_checker() instead of direct dependency checker calls!")
