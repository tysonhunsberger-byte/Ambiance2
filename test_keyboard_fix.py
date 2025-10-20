"""Test script to verify keyboard display and audio fixes."""

import sys
import os
from pathlib import Path

# Force UTF-8 encoding for Windows console
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add ambiance to path
sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.carla_host import CarlaVSTHost


def test_plugin_capabilities(plugin_path: Path):
    """Test if a plugin properly reports MIDI/instrument capabilities."""
    print(f"\n{'='*70}")
    print(f"Testing: {plugin_path.name}")
    print(f"{'='*70}")

    host = CarlaVSTHost()

    # Check if Carla is available
    status = host.status()
    print(f"\n✓ Carla available: {status['available']}")
    print(f"✓ Qt available: {status.get('qt_available', False)}")

    if not status['available']:
        print("\n❌ Carla backend not available!")
        print("Warnings:")
        for warning in status.get('warnings', []):
            print(f"  - {warning}")
        return False

    # Configure audio
    print(f"\n⚙️  Configuring audio drivers...")
    host.configure_audio(preferred_drivers=["DirectSound", "WASAPI", "Dummy"])

    # Try to get UI descriptor
    print(f"\n🔍 Fetching UI descriptor...")
    try:
        descriptor = host.describe_ui(plugin_path)
        print(f"✓ Descriptor fetched successfully!")

        print(f"\n📊 Plugin Information:")
        print(f"  Title: {descriptor.get('title', 'N/A')}")
        print(f"  Subtitle: {descriptor.get('subtitle', 'N/A')}")

        caps = descriptor.get('capabilities', {})
        print(f"\n🎹 Capabilities:")
        print(f"  Instrument: {caps.get('instrument', False)}")
        print(f"  MIDI: {caps.get('midi', False)}")
        print(f"  Editor: {caps.get('editor', False)}")

        keyboard = descriptor.get('keyboard', {})
        print(f"\n⌨️  Keyboard Range:")
        print(f"  Min Note: {keyboard.get('min_note', 'N/A')}")
        print(f"  Max Note: {keyboard.get('max_note', 'N/A')}")

        # Key question: Will the keyboard show?
        will_show = caps.get('midi', False) or caps.get('instrument', False)
        if will_show:
            print(f"\n✅ KEYBOARD SHOULD DISPLAY IN UI!")
        else:
            print(f"\n⚠️  Keyboard may not display (no MIDI/instrument capability)")

    except Exception as e:
        print(f"❌ Failed to get descriptor: {e}")
        return False

    # Now test actual loading and MIDI
    print(f"\n🎵 Loading plugin for audio test...")
    try:
        result = host.load_plugin(plugin_path, show_ui=False)
        print(f"✓ Plugin loaded!")

        # Get status after load
        status = host.status()
        engine = status.get('engine', {})
        print(f"\n🔊 Audio Engine:")
        print(f"  Running: {engine.get('running', False)}")
        print(f"  Driver: {engine.get('driver', 'N/A')}")

        caps = status.get('capabilities', {})
        print(f"\n🎛️  Runtime Capabilities:")
        print(f"  MIDI: {caps.get('midi', False)}")
        print(f"  MIDI Routed: {caps.get('midi_routed', False)}")
        print(f"  Instrument: {caps.get('instrument', False)}")

        params = status.get('parameters', [])
        print(f"\n🎚️  Parameters: {len(params)} available")

        if caps.get('midi', False):
            print(f"\n🎹 Testing MIDI note...")
            try:
                host.note_on(60, velocity=0.8)  # Middle C
                print(f"✓ MIDI note-on sent (note 60)")

                import time
                time.sleep(0.5)

                host.note_off(60)
                print(f"✓ MIDI note-off sent")

                print(f"\n💡 If audio is configured correctly, you should have heard a sound!")
                print(f"   Check your speakers/headphones.")

            except Exception as e:
                print(f"❌ MIDI test failed: {e}")
        else:
            print(f"\n⚠️  Plugin does not support MIDI input")

        # Cleanup
        host.unload()
        print(f"\n✓ Plugin unloaded")

    except Exception as e:
        print(f"❌ Failed to load plugin: {e}")
        return False

    finally:
        host.shutdown()

    return True


def main():
    print("="*70)
    print("Ambiance Keyboard & Audio Fix Verification")
    print("="*70)

    # Find included plugins
    included_dir = Path(__file__).parent / "included_plugins"

    if not included_dir.exists():
        print(f"\n❌ Included plugins directory not found: {included_dir}")
        return

    # Find all plugin files
    plugins = list(included_dir.rglob("*.vst3")) + list(included_dir.rglob("*.dll"))

    # Filter out non-plugin DLLs (like dependencies)
    plugins = [p for p in plugins if not any(skip in p.name.lower() for skip in
                                             ['msvc', 'ucrt', 'vcrun', 'api-ms'])]

    if not plugins:
        print(f"\n❌ No plugins found in {included_dir}")
        print("   Looking for .vst3 or .dll files")
        return

    print(f"\nFound {len(plugins)} plugin(s):")
    for p in plugins:
        print(f"  - {p.relative_to(included_dir.parent)}")

    # Test each plugin
    results = {}
    for plugin_path in plugins:
        success = test_plugin_capabilities(plugin_path)
        results[plugin_path.name] = success

    # Summary
    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")

    for name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")

    total = len(results)
    passed = sum(1 for s in results.values() if s)
    print(f"\nTotal: {passed}/{total} passed")

    print(f"\n{'='*70}")
    print("Next Steps:")
    print(f"{'='*70}")
    print("1. Start the server: python -m ambiance.server")
    print("2. Open browser: http://127.0.0.1:8000/")
    print("3. Click 'Load Selected' on a plugin from the library")
    print("4. Look for the 'Digital Instrument' panel with keyboard")
    print("5. Click keys or use Preview button to test audio")
    print("\nNote: Audio plays through your system audio (speakers/headphones),")
    print("      NOT through the browser!")


if __name__ == "__main__":
    main()
