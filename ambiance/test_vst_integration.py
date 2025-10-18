"""Test script to verify Carla VST integration is working correctly."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_imports():
    """Test that all required imports work."""
    print("Testing imports...")
    
    try:
        from ambiance.integrations.carla_host import CarlaVSTHost, HAS_PYQT5
        print("✓ CarlaVSTHost import successful")
        
        if HAS_PYQT5:
            print("✓ PyQt5 is available")
        else:
            print("✗ PyQt5 is NOT available - plugin UIs won't work!")
            print("  Install with: pip install PyQt5")
            return False
        
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_carla_backend():
    """Test that Carla backend can be initialized."""
    print("\nTesting Carla backend initialization...")
    
    try:
        from ambiance.integrations.carla_host import CarlaVSTHost
        
        host = CarlaVSTHost()
        status = host.status()
        
        print(f"\nCarla Status:")
        print(f"  Available: {status['available']}")
        print(f"  Qt Available: {status.get('qt_available', False)}")
        print(f"  Toolkit Path: {status.get('toolkit_path', 'Not found')}")
        print(f"  Engine Path: {status.get('engine_path', 'Not found')}")
        
        if status['warnings']:
            print(f"\n  Warnings:")
            for warning in status['warnings']:
                print(f"    - {warning}")
        
        if not status['available']:
            print("\n✗ Carla backend is NOT available")
            print("  Check the warnings above for details")
            return False
        
        print("\n✓ Carla backend is available!")
        return True
        
    except Exception as e:
        print(f"✗ Error testing Carla backend: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_loading():
    """Test loading a plugin if one is available."""
    print("\nTesting plugin loading (optional)...")
    
    try:
        from ambiance.integrations.carla_host import CarlaVSTHost
        
        # Look for test plugins in cache
        cache_dir = Path(__file__).parent / ".cache" / "plugins"
        
        if not cache_dir.exists():
            print("  No .cache/plugins directory found - skipping plugin test")
            return True
        
        # Find any VST plugin
        test_plugins = list(cache_dir.glob("**/*.dll")) + list(cache_dir.glob("**/*.vst3"))
        
        if not test_plugins:
            print("  No test plugins found in .cache/plugins - skipping")
            return True
        
        test_plugin = test_plugins[0]
        print(f"  Found test plugin: {test_plugin.name}")
        
        host = CarlaVSTHost()
        
        try:
            print(f"  Loading plugin...")
            plugin = host.load_plugin(str(test_plugin), show_ui=False)
            print(f"  ✓ Plugin loaded: {plugin['metadata']['name']}")
            
            # Check capabilities
            caps = plugin['capabilities']
            print(f"    - Is instrument: {caps.get('instrument', False)}")
            print(f"    - Has editor: {caps.get('editor', False)}")
            print(f"    - Parameter count: {len(plugin['parameters'])}")
            
            # Clean up
            host.unload()
            host.shutdown()
            
            return True
            
        except Exception as e:
            print(f"  ✗ Failed to load plugin: {e}")
            return False
        
    except Exception as e:
        print(f"  Error in plugin test: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Carla VST Integration Test Suite")
    print("=" * 60)
    
    results = {
        "Imports": test_imports(),
        "Carla Backend": test_carla_backend(),
        "Plugin Loading": test_plugin_loading(),
    }
    
    print("\n" + "=" * 60)
    print("Test Results Summary:")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name:.<40} {status}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: All tests passed! 🎉")
        print("\nYour Carla VST integration is working correctly.")
        print("You can now load VST plugins and show their UIs.")
    else:
        print("ISSUES FOUND: Some tests failed")
        print("\nPlease review the errors above and follow the fix guide:")
        print("  VST_INTEGRATION_FIX_GUIDE.md")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
