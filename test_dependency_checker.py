#!/usr/bin/env python3
"""
Test script for PGLOK dependency checker
"""

import sys
import os
from pathlib import Path

# Add PGLOK to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_dependency_checker_import():
    """Test if the dependency checker can be imported."""
    print("🧪 Testing dependency checker import...")
    
    try:
        from dependency_checker import DependencyChecker
        print("✅ DependencyChecker module imported successfully")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import dependency checker: {e}")
        return False

def test_dependency_checker_functionality():
    """Test the dependency checker functionality."""
    print("\n🧪 Testing dependency checker functionality...")
    
    try:
        from dependency_checker import DependencyChecker
        
        # Create a mock PGLOK app
        class MockPGLOKApp:
            def __init__(self):
                self.root = None
        
        mock_app = MockPGLOKApp()
        checker = DependencyChecker(mock_app)
        
        # Test dependency checking
        installed, missing = checker.check_dependencies()
        print(f"✅ Found {len(installed)} installed dependencies")
        print(f"✅ Found {len(missing)} missing dependencies")
        
        # Test detailed status
        status = checker.get_dependency_status()
        print(f"✅ Got status for {len(status)} dependencies")
        
        for package, info in status.items():
            status_text = "✓" if info["installed"] else "✗"
            optional_text = "(optional)" if info["optional"] else "(required)"
            print(f"  {status_text} {package} {optional_text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to test dependency checker functionality: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pglok_integration():
    """Test if PGLOK can import the dependency checker."""
    print("\n🧪 Testing PGLOK integration...")
    
    try:
        # Test importing the check_dependencies method
        import importlib.util
        
        # Check if the method exists in pglok.py
        pglok_path = Path(__file__).parent.parent / "src" / "pglok.py"
        if pglok_path.exists():
            with open(pglok_path, 'r') as f:
                content = f.read()
            
            if "_check_dependencies" in content:
                print("✅ _check_dependencies method found in PGLOK")
            else:
                print("❌ _check_dependencies method not found in PGLOK")
                return False
            
            if "from src.dependency_checker import DependencyChecker" in content:
                print("✅ DependencyChecker import found in PGLOK")
            else:
                print("❌ DependencyChecker import not found in PGLOK")
                return False
        else:
            print("❌ PGLOK source file not found")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to test PGLOK integration: {e}")
        return False

def test_settings_button():
    """Test if the settings button was added."""
    print("\n🧪 Testing settings button integration...")
    
    try:
        pglok_path = Path(__file__).parent.parent / "src" / "pglok.py"
        if pglok_path.exists():
            with open(pglok_path, 'r') as f:
                content = f.read()
            
            if "dependencies_button" in content:
                print("✅ dependencies_button found in PGLOK")
            else:
                print("❌ dependencies_button not found in PGLOK")
                return False
            
            if "Check Dependencies" in content:
                print("✅ 'Check Dependencies' button text found")
            else:
                print("❌ 'Check Dependencies' button text not found")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to test settings button: {e}")
        return False

if __name__ == "__main__":
    print("🎯 PGLOK Dependency Checker Test")
    print("=" * 50)
    
    success = True
    
    # Test dependency checker import
    if not test_dependency_checker_import():
        success = False
    
    # Test dependency checker functionality
    if not test_dependency_checker_functionality():
        success = False
    
    # Test PGLOK integration
    if not test_pglok_integration():
        success = False
    
    # Test settings button
    if not test_settings_button():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Dependency checker tests passed!")
        print("\n📋 To use the dependency checker:")
        print("1. Start PGLOK")
        print("2. Click: Tools → Settings")
        print("3. Click: 'Check Dependencies' button")
        print("4. Review dependency status")
        print("5. Click 'Install Missing' if needed")
        print("6. Confirm installation")
        print("7. Wait for installation to complete")
    else:
        print("❌ Some tests failed. Check the errors above.")
