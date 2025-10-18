"""
Example usage scenarios for the fixed Carla VST integration.
Run these examples to test different features.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def example_1_basic_loading():
    """Example 1: Basic plugin loading and info."""
    print("=" * 60)
    print("Example 1: Basic Plugin Loading")
    print("=" * 60)
    
    from ambiance.integrations.carla_host import CarlaVSTHost
    
    # Create host
    host = CarlaVSTHost()
    
    # Check status
    status = host.status()
    print(f"\nHost Status:")
    print(f"  Available: {status['available']}")
    print(f"  Qt Available: {status.get('qt_available', False)}")
    
    if not status['available']:
        print("\n⚠ Carla not available. Check the warnings:")
        for warning in status['warnings']:
            print(f"    - {warning}")
        return
    
    # Find a test plugin
    cache_dir = Path(__file__).parent / ".cache" / "plugins"
    plugins = list(cache_dir.glob("**/*.dll")) + list(cache_dir.glob("**/*.vst3"))
    
    if not plugins:
        print("\n⚠ No test plugins found in .cache/plugins")
        print("  Place some VST plugins there to test")
        return
    
    plugin_path = plugins[0]
    print(f"\nLoading plugin: {plugin_path.name}")
    
    try:
        plugin = host.load_plugin(str(plugin_path))
        
        print(f"\n✓ Plugin loaded successfully!")
        print(f"\nPlugin Info:")
        print(f"  Name: {plugin['metadata']['name']}")
        print(f"  Vendor: {plugin['metadata']['vendor']}")
        print(f"  Format: {plugin['metadata']['format']}")
        print(f"  Category: {plugin['metadata']['category']}")
        
        print(f"\nCapabilities:")
        print(f"  Is Instrument: {plugin['capabilities']['instrument']}")
        print(f"  Has Editor: {plugin['capabilities']['editor']}")
        
        print(f"\nParameters: {len(plugin['parameters'])} total")
        for i, param in enumerate(plugin['parameters'][:5]):  # First 5
            print(f"  {i}: {param['name']} = {param['value']:.3f}")
        
        if len(plugin['parameters']) > 5:
            print(f"  ... and {len(plugin['parameters']) - 5} more")
        
        # Cleanup
        host.unload()
        host.shutdown()
        
    except Exception as e:
        print(f"\n✗ Error loading plugin: {e}")


def example_2_parameter_control():
    """Example 2: Loading plugin and controlling parameters."""
    print("\n" + "=" * 60)
    print("Example 2: Parameter Control")
    print("=" * 60)
    
    from ambiance.integrations.carla_host import CarlaVSTHost
    
    host = CarlaVSTHost()
    
    # Find a plugin
    cache_dir = Path(__file__).parent / ".cache" / "plugins"
    plugins = list(cache_dir.glob("**/*.dll")) + list(cache_dir.glob("**/*.vst3"))
    
    if not plugins:
        print("\n⚠ No test plugins found")
        return
    
    plugin_path = plugins[0]
    print(f"\nLoading plugin: {plugin_path.name}")
    
    try:
        plugin = host.load_plugin(str(plugin_path))
        print("✓ Plugin loaded")
        
        # Get first parameter
        if not plugin['parameters']:
            print("  Plugin has no parameters")
            return
        
        param = plugin['parameters'][0]
        print(f"\nTesting parameter: {param['name']}")
        print(f"  Current value: {param['value']:.3f}")
        print(f"  Range: {param['min']:.3f} to {param['max']:.3f}")
        
        # Set to middle
        mid_value = (param['min'] + param['max']) / 2
        print(f"\nSetting to middle value: {mid_value:.3f}")
        
        result = host.set_parameter(param['id'], mid_value)
        new_value = result['parameters'][0]['value']
        print(f"✓ New value: {new_value:.3f}")
        
        # Set to max
        print(f"\nSetting to max value: {param['max']:.3f}")
        result = host.set_parameter(param['id'], param['max'])
        new_value = result['parameters'][0]['value']
        print(f"✓ New value: {new_value:.3f}")
        
        # Cleanup
        host.unload()
        host.shutdown()
        
    except Exception as e:
        print(f"\n✗ Error: {e}")


def example_3_ui_control():
    """Example 3: Opening plugin UI (requires PyQt5)."""
    print("\n" + "=" * 60)
    print("Example 3: Plugin UI Control")
    print("=" * 60)
    
    from ambiance.integrations.carla_host import CarlaVSTHost, HAS_PYQT5
    
    if not HAS_PYQT5:
        print("\n⚠ PyQt5 not available - cannot show UIs")
        print("  Install with: pip install PyQt5")
        return
    
    host = CarlaVSTHost()
    status = host.status()
    
    if not status.get('qt_available'):
        print("\n⚠ Qt not initialized - cannot show UIs")
        return
    
    # Find a plugin
    cache_dir = Path(__file__).parent / ".cache" / "plugins"
    plugins = list(cache_dir.glob("**/*.dll")) + list(cache_dir.glob("**/*.vst3"))
    
    if not plugins:
        print("\n⚠ No test plugins found")
        return
    
    # Try to find one with a UI
    for plugin_path in plugins:
        try:
            print(f"\nTrying plugin: {plugin_path.name}")
            plugin = host.load_plugin(str(plugin_path))
            
            if plugin['capabilities']['editor']:
                print(f"✓ Plugin has editor!")
                print(f"  Name: {plugin['metadata']['name']}")
                
                print("\nOpening UI...")
                try:
                    host.show_ui()
                    print("✓ UI opened successfully!")
                    print("\nThe plugin UI should now be visible in a separate window.")
                    print("Press Enter to close it...")
                    input()
                    
                    print("\nClosing UI...")
                    host.hide_ui()
                    print("✓ UI closed")
                    
                except Exception as e:
                    print(f"✗ Failed to show UI: {e}")
                
                host.unload()
                break
            else:
                print("  No editor available, trying next plugin...")
                host.unload()
                
        except Exception as e:
            print(f"  Error: {e}")
            continue
    else:
        print("\n⚠ No plugins with UIs found")
    
    host.shutdown()


def example_4_describe_ui():
    """Example 4: Describing plugin UI structure."""
    print("\n" + "=" * 60)
    print("Example 4: UI Description")
    print("=" * 60)
    
    from ambiance.integrations.carla_host import CarlaVSTHost
    
    host = CarlaVSTHost()
    
    # Find a plugin
    cache_dir = Path(__file__).parent / ".cache" / "plugins"
    plugins = list(cache_dir.glob("**/*.dll")) + list(cache_dir.glob("**/*.vst3"))
    
    if not plugins:
        print("\n⚠ No test plugins found")
        return
    
    plugin_path = plugins[0]
    print(f"\nDescribing plugin: {plugin_path.name}")
    
    try:
        descriptor = host.describe_ui(str(plugin_path))
        
        print(f"\n✓ UI Description:")
        print(f"  Title: {descriptor['title']}")
        print(f"  Subtitle: {descriptor['subtitle']}")
        
        print(f"\nPanels:")
        for panel in descriptor['panels']:
            print(f"  - {panel['name']}: {len(panel['controls'])} controls")
        
        print(f"\nCapabilities:")
        for key, value in descriptor['capabilities'].items():
            print(f"  - {key}: {value}")
        
        print(f"\nParameters: {len(descriptor['parameters'])}")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
    
    finally:
        host.shutdown()


def example_5_multiple_plugins():
    """Example 5: Loading multiple plugins sequentially."""
    print("\n" + "=" * 60)
    print("Example 5: Multiple Plugins")
    print("=" * 60)
    
    from ambiance.integrations.carla_host import CarlaVSTHost
    
    host = CarlaVSTHost()
    
    # Find plugins
    cache_dir = Path(__file__).parent / ".cache" / "plugins"
    plugins = list(cache_dir.glob("**/*.dll")) + list(cache_dir.glob("**/*.vst3"))
    
    if len(plugins) < 2:
        print("\n⚠ Need at least 2 plugins to test. Found:", len(plugins))
        return
    
    print(f"\nFound {len(plugins)} plugins")
    print("Loading them one at a time...\n")
    
    for i, plugin_path in enumerate(plugins[:3]):  # Test first 3
        print(f"{i+1}. Loading: {plugin_path.name}")
        
        try:
            plugin = host.load_plugin(str(plugin_path))
            print(f"   ✓ {plugin['metadata']['name']}")
            print(f"     Parameters: {len(plugin['parameters'])}")
            print(f"     Has UI: {plugin['capabilities']['editor']}")
            
            # Unload before loading next
            host.unload()
            
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    host.shutdown()
    print("\n✓ Test complete")


def main():
    """Run all examples."""
    print("Carla VST Integration - Example Usage\n")
    
    examples = [
        ("Basic Loading", example_1_basic_loading),
        ("Parameter Control", example_2_parameter_control),
        ("UI Control", example_3_ui_control),
        ("UI Description", example_4_describe_ui),
        ("Multiple Plugins", example_5_multiple_plugins),
    ]
    
    print("Available examples:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    print(f"  0. Run all examples")
    
    try:
        choice = input("\nSelect example (0-5): ").strip()
        
        if choice == "0":
            for name, func in examples:
                print(f"\n{'=' * 60}")
                print(f"Running: {name}")
                print(f"{'=' * 60}")
                try:
                    func()
                except KeyboardInterrupt:
                    print("\n\nSkipped by user")
                    break
                except Exception as e:
                    print(f"\nUnexpected error: {e}")
                    import traceback
                    traceback.print_exc()
        elif choice in ["1", "2", "3", "4", "5"]:
            idx = int(choice) - 1
            name, func = examples[idx]
            print(f"\nRunning: {name}\n")
            func()
        else:
            print("Invalid choice")
            return 1
        
        print("\n" + "=" * 60)
        print("Examples complete!")
        print("=" * 60)
        return 0
        
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        return 1
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
