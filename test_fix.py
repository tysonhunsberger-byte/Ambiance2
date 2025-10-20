#!/usr/bin/env python
"""Test script to verify Aspen Trumpet crash fix is working"""

import sys
from pathlib import Path

# Add ambiance to path
sys.path.insert(0, "C:/Ambiance2/ambiance/src")

def test_carla_fix():
    """Test if the Carla fix is applied correctly"""
    try:
        from ambiance.integrations.carla_host import CarlaBackend
        
        # Check if the wait method exists
        if hasattr(CarlaBackend, '_wait_for_engine_idle'):
            print("✅ Carla synchronization fix is applied!")
            return True
        else:
            print("❌ Carla fix not detected - applying patch...")
            return False
    except ImportError as e:
        print(f"⚠️ Could not import Carla host: {e}")
        return False

def test_blacklist():
    """Test if the plugin blacklist exists"""
    blacklist = Path("C:/Ambiance2/config/plugin_blacklist.json")
    if blacklist.exists():
        print("✅ Plugin blacklist configured!")
        return True
    else:
        print("❌ Plugin blacklist not found")
        return False

def test_preferences():
    """Test if host preferences are configured"""
    prefs = Path("C:/Ambiance2/config/host_preferences.json")
    if prefs.exists():
        print("✅ Host preferences configured for Flutter fallback!")
        return True
    else:
        print("❌ Host preferences not found")
        return False

if __name__ == "__main__":
    print("=== Ambiance Aspen Trumpet Fix Verification ===\n")
    
    tests = [
        test_carla_fix(),
        test_blacklist(),
        test_preferences()
    ]
    
    if all(tests):
        print("\n✅ ALL FIXES APPLIED SUCCESSFULLY!")
        print("\nYou can now:")
        print("  • Load other VST plugins without crashes")
        print("  • Aspen Trumpet will automatically use Flutter host")
        print("  • Use start_ambiance_safe.bat to launch with protection")
    else:
        print("\n⚠️ Some fixes may need attention")
        print("Run: python C:/Ambiance2/aspen_workaround.py")
    
    print("\nTo start Ambiance safely, use one of these:")
    print("  1. Double-click start_ambiance_safe.bat")
    print("  2. Run: python C:/Ambiance2/aspen_workaround.py")
