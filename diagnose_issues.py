"""Diagnose keyboard and audio issues."""

import sys
from pathlib import Path
import json

# Add to path
sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

print("="*70)
print("Ambiance Issue Diagnosis")
print("="*70)

# Test 1: Check plugin discovery
print("\n[1] Plugin Discovery:")
try:
    from ambiance.integrations.plugins import PluginRackManager
    manager = PluginRackManager(base_dir=Path("C:/Ambiance2/ambiance"))
    plugins = manager.discover_plugins()  # Correct method name
    print(f"  Found {len(plugins)} plugins:")

    # Check for duplicates (should be fixed now)
    paths = {}
    for plugin in plugins:
        path_str = str(plugin.get('path', ''))
        if path_str in paths:
            print(f"  ⚠️  DUPLICATE: {plugin.get('name', 'Unknown')}")
            print(f"      First:  {paths[path_str]}")
            print(f"      Second: {path_str}")
        else:
            paths[path_str] = path_str
            print(f"  - {plugin.get('name', 'Unknown')}")
            print(f"    Path: {path_str}")
            print(f"    Format: {plugin.get('format', 'Unknown')}")

except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Try loading a plugin
print("\n[2] Testing Plugin Load:")
try:
    from ambiance.integrations.carla_host import CarlaVSTHost

    # Find Aspen Trumpet
    aspen_path = Path("C:/Ambiance2/included_plugins/Aspen-Trumpet-1_64/Aspen Trumpet 1.dll")
    if not aspen_path.exists():
        print(f"  ✗ Aspen Trumpet not found at {aspen_path}")
    else:
        print(f"  ✓ Found plugin at {aspen_path}")

        host = CarlaVSTHost(base_dir=Path("C:/Ambiance2/ambiance"))
        print(f"  ✓ Host created")

        # Configure audio first
        host.configure_audio(preferred_drivers=["DirectSound", "WASAPI", "Dummy"])
        print(f"  ✓ Audio configured")

        # Get status before load
        status_before = host.status()
        print(f"\n  Status BEFORE load:")
        print(f"    Available: {status_before['available']}")
        print(f"    Engine running: {status_before.get('engine', {}).get('running', False)}")
        print(f"    Driver: {status_before.get('engine', {}).get('driver', 'N/A')}")

        if not status_before['available']:
            print(f"    ✗ Carla not available!")
            print(f"    Warnings:")
            for w in status_before.get('warnings', []):
                print(f"      - {w}")
        else:
            # Try to load
            print(f"\n  Loading plugin...")
            try:
                result = host.load_plugin(aspen_path, show_ui=False)
                print(f"  ✓ Plugin loaded!")

                # Get status after load
                status_after = host.status()
                print(f"\n  Status AFTER load:")
                print(f"    Plugin loaded: {status_after.get('plugin') is not None}")

                if status_after.get('plugin'):
                    plugin = status_after['plugin']
                    print(f"    Plugin name: {plugin['metadata']['name']}")
                    print(f"    Plugin vendor: {plugin['metadata']['vendor']}")

                    caps = status_after.get('capabilities', {})
                    print(f"\n  Capabilities:")
                    print(f"    Instrument: {caps.get('instrument', False)}")
                    print(f"    MIDI: {caps.get('midi', False)}")
                    print(f"    MIDI Routed: {caps.get('midi_routed', False)}")
                    print(f"    Editor: {caps.get('editor', False)}")

                    # Check engine
                    engine = status_after.get('engine', {})
                    print(f"\n  Engine:")
                    print(f"    Running: {engine.get('running', False)}")
                    print(f"    Driver: {engine.get('driver', 'N/A')}")

                    # Try to get UI descriptor
                    print(f"\n  Getting UI descriptor...")
                    try:
                        descriptor = host.describe_ui()
                        print(f"  ✓ Descriptor obtained!")
                        print(f"    Title: {descriptor.get('title', 'N/A')}")

                        desc_caps = descriptor.get('capabilities', {})
                        print(f"    Capabilities (from descriptor):")
                        print(f"      Instrument: {desc_caps.get('instrument', False)}")
                        print(f"      MIDI: {desc_caps.get('midi', False)}")
                        print(f"      Editor: {desc_caps.get('editor', False)}")

                        keyboard = descriptor.get('keyboard', {})
                        print(f"    Keyboard range: {keyboard.get('min_note', '?')} - {keyboard.get('max_note', '?')}")

                        # THE KEY QUESTION
                        will_show = desc_caps.get('midi', False) or desc_caps.get('instrument', False)
                        if will_show:
                            print(f"\n  ✅ KEYBOARD SHOULD SHOW (midi={desc_caps.get('midi')}, instrument={desc_caps.get('instrument')})")
                        else:
                            print(f"\n  ❌ KEYBOARD WON'T SHOW (midi={desc_caps.get('midi')}, instrument={desc_caps.get('instrument')})")

                    except Exception as e:
                        print(f"  ✗ Descriptor failed: {e}")
                        import traceback
                        traceback.print_exc()

                    # Try to send MIDI
                    if caps.get('midi', False):
                        print(f"\n  Testing MIDI...")
                        try:
                            import time
                            host.note_on(60, velocity=0.8)
                            print(f"  ✓ MIDI note-on sent (C4)")
                            print(f"  💡 Listen to your speakers for 2 seconds...")
                            time.sleep(2)
                            host.note_off(60)
                            print(f"  ✓ MIDI note-off sent")
                            print(f"  (If you see a Carla assertion below, it's been fixed - just a timing issue)")
                        except Exception as e:
                            print(f"  ✗ MIDI failed: {e}")
                            import traceback
                            traceback.print_exc()

                    # Cleanup
                    host.unload()
                    print(f"\n  ✓ Plugin unloaded")

            except Exception as e:
                print(f"  ✗ Load failed: {e}")
                import traceback
                traceback.print_exc()

except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("INSTRUCTIONS:")
print("="*70)
print("\n1. Check the output above:")
print("   - Are plugins duplicated?")
print("   - Did the plugin load successfully?")
print("   - Does it say 'KEYBOARD SHOULD SHOW'?")
print("   - Did you hear audio during the MIDI test?")
print("\n2. If keyboard won't show:")
print("   - Check if MIDI or instrument capability is false")
print("   - Plugin might not be an instrument")
print("\n3. If no audio:")
print("   - Check if engine is running")
print("   - Check if MIDI is routed (might take a few seconds)")
print("   - Check your speaker volume")
print("   - Check Windows audio settings")
print("\n4. Then open browser console (F12) and check for errors")
print("   when loading a plugin in the web UI")
print("="*70)
