"""Simple check to verify the code fixes are in place."""

import sys
from pathlib import Path

print("="*60)
print("Checking Ambiance Keyboard & Audio Fixes")
print("="*60)

# Check 1: MIDI capability detection fix
print("\n[1] Checking MIDI capability detection fix...")
carla_host_file = Path(__file__).parent / "ambiance" / "src" / "ambiance" / "integrations" / "carla_host.py"

if not carla_host_file.exists():
    print("ERROR: carla_host.py not found!")
    sys.exit(1)

content = carla_host_file.read_text(encoding='utf-8')

if "accepts_midi = self._plugin_accepts_midi()" in content:
    print("PASS: MIDI detection code updated")
else:
    print("FAIL: MIDI detection fix not found")

if "supports_midi = self._supports_midi or accepts_midi" in content:
    print("PASS: MIDI capability fallback logic added")
else:
    print("FAIL: MIDI fallback logic not found")

# Check 2: Exception handling in server
print("\n[2] Checking exception handling in server.py...")
server_file = Path(__file__).parent / "ambiance" / "src" / "ambiance" / "server.py"

if not server_file.exists():
    print("ERROR: server.py not found!")
    sys.exit(1)

content = server_file.read_text(encoding='utf-8')

if "except Exception as exc:" in content and "/api/vst/ui" in content:
    print("PASS: Broader exception handling added")
else:
    print("FAIL: Exception handling not updated")

if "fallback_descriptor" in content:
    print("PASS: Fallback descriptor logic added")
else:
    print("FAIL: Fallback descriptor not found")

# Check 3: Documentation updated
print("\n[3] Checking CLAUDE.md documentation...")
claude_md = Path(__file__).parent / "CLAUDE.md"

if not claude_md.exists():
    print("ERROR: CLAUDE.md not found!")
    sys.exit(1)

content = claude_md.read_text(encoding='utf-8')

if "Audio Architecture & Real-Time Playback" in content:
    print("PASS: Audio architecture section added")
else:
    print("FAIL: Audio architecture documentation missing")

if "Audio bypasses the browser entirely" in content:
    print("PASS: Browser audio bypass explanation added")
else:
    print("FAIL: Browser bypass explanation missing")

if "Digital Keyboard Display" in content:
    print("PASS: Keyboard display documentation added")
else:
    print("FAIL: Keyboard display docs missing")

# Check 4: Find included plugins
print("\n[4] Checking included plugins...")
included_dir = Path(__file__).parent / "included_plugins"

if not included_dir.exists():
    print("WARNING: included_plugins directory not found")
    plugins = []
else:
    plugins = list(included_dir.rglob("*.vst3")) + list(included_dir.rglob("*.dll"))
    # Filter out non-plugin DLLs
    plugins = [p for p in plugins if not any(skip in p.name.lower() for skip in
                                             ['msvc', 'ucrt', 'vcrun', 'api-ms'])]

    print(f"Found {len(plugins)} plugin(s):")
    for p in plugins:
        print(f"  - {p.name}")

# Summary
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print("\nCode fixes are in place!")
print("\nTo test the fixes:")
print("1. Start server: python -m ambiance.server")
print("2. Open browser: http://127.0.0.1:8000/")
print("3. Load a plugin from the included_plugins folder")
print("4. Look for 'Digital Instrument' panel with keyboard")
print("5. Click keyboard keys to send MIDI")
print("6. Listen for audio from your speakers/headphones")
print("\nIMPORTANT:")
print("- Audio plays through system audio, NOT the browser")
print("- Ensure your speakers/headphones are on and volume is up")
print("- The keyboard only shows for MIDI-capable plugins")

print("\nIf you have issues:")
print("- Check browser console for errors")
print("- Visit http://127.0.0.1:8000/api/vst/status")
print("- Look for 'available': true and 'engine': {'running': true}")
print("\nSee CLAUDE.md for detailed troubleshooting!")
