"""Check what paths plugins are discovered with."""

import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.plugins import PluginRackManager

manager = PluginRackManager(base_dir=Path("C:/Ambiance2/ambiance"))
plugins = manager.discover_plugins()

print(f"Found {len(plugins)} plugins:\n")

for plugin in plugins:
    name = plugin.get('name', 'Unknown')
    path = plugin.get('path', '')
    rel_path = plugin.get('relative_path', '')

    print(f"Name: {name}")
    print(f"  Full Path: {path}")
    print(f"  Relative Path: {rel_path}")
    print(f"  File Exists: {Path(path).exists() if path else False}")
    print()

print("="*70)
print("ISSUE CHECK:")
print("="*70)

# Check for the specific Aspen plugin
aspen_plugins = [p for p in plugins if 'Aspen' in p.get('name', '')]
if aspen_plugins:
    aspen = aspen_plugins[0]
    path = aspen.get('path', '')
    print(f"\nAspen Trumpet plugin:")
    print(f"  Path from discovery: {path}")
    print(f"  File exists: {Path(path).exists()}")

    expected_path = "C:/Ambiance2/included_plugins/Aspen-Trumpet-1_64/Aspen Trumpet 1.dll"
    print(f"\n  Expected path: {expected_path}")
    print(f"  Expected exists: {Path(expected_path).exists()}")

    if path != expected_path:
        print(f"\n  ❌ PATH MISMATCH!")
        print(f"  The plugin discovery is returning the WRONG path!")
else:
    print("\n❌ Aspen Trumpet not found in discovered plugins!")
