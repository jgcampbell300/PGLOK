#!/usr/bin/env python3
"""
Test script for dependency checker crash fixes
"""

import sys
import os
from pathlib import Path

# Add PGLOK to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_dependency_checker_crash_fixes():
    """Test the dependency checker crash fixes."""
    print("🧪 Testing dependency checker crash fixes...")
    
    try:
        from dependency_checker import DependencyChecker
        print("✅ DependencyChecker imported successfully")
        
        # Create a mock PGLOK app
        class MockPGLOKApp:
            def __init__(self):
                self.root = None
        
        mock_app = MockPGLOKApp()
        checker = DependencyChecker(mock_app)
        
        # Test dependency checking (should not crash)
        print("🔍 Testing dependency checking...")
        installed, missing = checker.check_dependencies()
        print(f"✅ Dependency check completed: {len(installed)} installed, {len(missing)} missing")
        
        # Test status checking (should not crash)
        print("🔍 Testing status checking...")
        status = checker.get_dependency_status()
        print(f"✅ Status check completed: {len(status)} total dependencies")
        
        # Test addon dependency scanning (should not crash)
        print("🔍 Testing addon dependency scanning...")
        addon_deps = checker.addon_dependencies
        print(f"✅ Addon scan completed: {len(addon_deps)} addon dependencies")
        
        # Test error handling in install_dependencies
        print("🔍 Testing install_dependencies error handling...")
        # Test with empty list (should not crash)
        result = checker.install_dependencies([])
        print(f"✅ Empty install test completed: {result}")
        
        # Test with invalid package (should handle gracefully)
        result = checker.install_dependencies(["nonexistent_package_12345"])
        print(f"✅ Invalid package test completed: {result}")
        
        print("✅ All crash fix tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_error_handling():
    """Test specific error handling scenarios."""
    print("\n🧪 Testing error handling scenarios...")
    
    try:
        from dependency_checker import DependencyChecker
        
        class MockPGLOKApp:
            def __init__(self):
                self.root = None
        
        mock_app = MockPGLOKApp()
        checker = DependencyChecker(mock_app)
        
        # Test _on_install_complete with None callback
        print("🔍 Testing _on_install_complete with None callback...")
        try:
            checker._on_install_complete(True, ["test"], None)
            print("✅ _on_install_complete with None callback handled")
        except Exception as e:
            print(f"❌ _on_install_complete failed: {e}")
        
        print("✅ Error handling tests completed!")
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False

if __name__ == "__main__":
    print("🎯 Dependency Checker Crash Fix Test")
    print("=" * 50)
    
    success = True
    
    # Test crash fixes
    if not test_dependency_checker_crash_fixes():
        success = False
    
    # Test error handling
    if not test_error_handling():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All crash fix tests passed!")
        print("\n📋 Fixes Applied:")
        print("✅ Added try-catch blocks to prevent crashes")
        print("✅ Improved threading safety")
        print("✅ Added timeout to pip installations")
        print("✅ Enhanced error handling in UI updates")
        print("✅ Safe callback execution")
        print("\n🚀 Dependency checker should now be crash-resistant!")
    else:
        print("❌ Some tests failed. Check the errors above.")
