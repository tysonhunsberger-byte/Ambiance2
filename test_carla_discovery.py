"""Test Carla discovery to diagnose path issues."""

import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

print("="*70)
print("Carla Discovery Test")
print("="*70)

# Test 1: Check paths
print("\n[1] Path Check:")
print(f"  Current directory: {Path.cwd()}")
print(f"  Script location: {Path(__file__).resolve()}")

# Test 2: Import and create backend
print("\n[2] Importing CarlaBackend...")
try:
    from ambiance.integrations.carla_host import CarlaBackend
    print("  ✓ Import successful")
except Exception as e:
    print(f"  ✗ Import failed: {e}")
    sys.exit(1)

print("\n[3] Creating CarlaBackend instance...")
try:
    backend = CarlaBackend()
    print("  ✓ Instance created")
except Exception as e:
    print(f"  ✗ Creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Check discovery results
print("\n[4] Discovery Results:")
print(f"  base_dir: {backend.base_dir}")
print(f"  root: {backend.root}")
print(f"  library_path: {backend.library_path}")
print(f"  available: {backend.available}")

# Test 4: Check what paths were searched
print("\n[5] Path Search:")
search_paths = [
    backend.base_dir / "Carla-main",
    backend.base_dir / "Carla-main" / "Carla",
    backend.base_dir / "Carla",
    backend.base_dir.parent / "Carla-main",
    backend.base_dir.parent / "Carla",
]

for path in search_paths:
    exists = path.exists()
    marker = "✓" if exists else "✗"
    print(f"  {marker} {path}")

# Test 5: Check for source/frontend/carla_backend.py
if backend.root:
    backend_py = backend.root / "source" / "frontend" / "carla_backend.py"
    exists = backend_py.exists()
    marker = "✓" if exists else "✗"
    print(f"\n[6] Carla Backend Script:")
    print(f"  {marker} {backend_py}")

# Test 6: Check for library
if backend.root:
    print(f"\n[7] Library Search in {backend.root}:")
    dll_paths = [
        backend.root / "bin" / "libcarla_standalone2.dll",
        backend.root / "Carla" / "libcarla_standalone2.dll",
        backend.root / "libcarla_standalone2.dll",
    ]
    for path in dll_paths:
        exists = path.exists()
        marker = "✓" if exists else "✗"
        print(f"  {marker} {path}")

# Test 7: Show warnings
if backend.warnings:
    print(f"\n[8] Warnings ({len(backend.warnings)}):")
    for warning in backend.warnings:
        print(f"  - {warning}")
else:
    print(f"\n[8] No warnings!")

# Test 8: Test wrapper class
print("\n[9] Testing CarlaVSTHost wrapper...")
try:
    from ambiance.integrations.carla_host import CarlaVSTHost
    host = CarlaVSTHost()
    print(f"  ✓ Wrapper created")
    print(f"  base_dir: {host.base_dir}")
    status = host.status()
    print(f"  available: {status['available']}")
    print(f"  qt_available: {status.get('qt_available', False)}")
    if status.get('warnings'):
        print(f"  warnings: {len(status['warnings'])}")
        for w in status['warnings']:
            print(f"    - {w}")
except Exception as e:
    print(f"  ✗ Wrapper failed: {e}")
    import traceback
    traceback.print_exc()

# Summary
print("\n" + "="*70)
if backend.available:
    print("SUCCESS: Carla backend is available!")
    print(f"Library: {backend.library_path}")
else:
    print("FAILURE: Carla backend not available")
    print("Check the warnings above for details")

print("="*70)
