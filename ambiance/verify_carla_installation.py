"""
Carla Installation Verification Script

This script checks if Carla is properly installed and configured
for use with the Ambiance audio app.
"""

import os
import sys
from pathlib import Path


def print_header(text):
    """Print formatted header."""
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


def check_directory_structure():
    """Verify Carla directory structure."""
    print_header("Checking Carla Directory Structure")
    
    base_dir = Path(__file__).parent
    carla_root = base_dir / "Carla-main"
    
    checks = {
        "Carla root directory": carla_root,
        "Carla binary directory": carla_root / "Carla",
        "Carla source directory": carla_root / "source",
        "Carla frontend directory": carla_root / "source" / "frontend",
    }
    
    all_exist = True
    for name, path in checks.items():
        exists = path.exists()
        status = "✓" if exists else "✗"
        print(f"{status} {name}: {path}")
        all_exist = all_exist and exists
    
    return all_exist


def check_required_files():
    """Check for required Carla files."""
    print_header("Checking Required Files")
    
    base_dir = Path(__file__).parent
    carla_root = base_dir / "Carla-main"
    
    required_files = {
        "libcarla_standalone2.dll": [
            carla_root / "Carla" / "libcarla_standalone2.dll",
            carla_root / "bin" / "libcarla_standalone2.dll",
            carla_root / "build" / "libcarla_standalone2.dll",
        ],
        "carla_backend.py": [
            carla_root / "source" / "frontend" / "carla_backend.py",
        ],
        "libcarla_utils.dll": [
            carla_root / "Carla" / "libcarla_utils.dll",
            carla_root / "bin" / "libcarla_utils.dll",
        ],
    }
    
    found_files = {}
    all_found = True
    
    for file_name, possible_paths in required_files.items():
        found = False
        found_path = None
        
        for path in possible_paths:
            if path.exists():
                found = True
                found_path = path
                break
        
        status = "✓" if found else "✗"
        location = f"at {found_path.relative_to(base_dir)}" if found else "NOT FOUND"
        print(f"{status} {file_name}: {location}")
        
        found_files[file_name] = found_path
        all_found = all_found and found
    
    return all_found, found_files


def check_file_sizes(found_files):
    """Check if files have reasonable sizes."""
    print_header("Checking File Sizes")
    
    for name, path in found_files.items():
        if path and path.exists():
            size = path.stat().st_size
            size_mb = size / (1024 * 1024)
            
            # DLLs should be > 100 KB
            if name.endswith('.dll'):
                status = "✓" if size > 100_000 else "⚠"
                print(f"{status} {name}: {size_mb:.2f} MB")
            else:
                status = "✓" if size > 1000 else "⚠"
                print(f"{status} {name}: {size / 1024:.2f} KB")


def check_environment_variables():
    """Check relevant environment variables."""
    print_header("Checking Environment Variables")
    
    env_vars = [
        "CARLA_ROOT",
        "CARLA_HOME",
        "PATH",
    ]
    
    for var in env_vars:
        value = os.environ.get(var)
        if var == "PATH":
            # Just check if it exists, don't print the whole thing
            status = "✓" if value else "✗"
            print(f"{status} {var}: {'Set' if value else 'Not set'}")
            
            # Check if Carla paths are in PATH
            if value:
                has_carla = any("carla" in p.lower() for p in value.split(os.pathsep))
                if has_carla:
                    print(f"   └─ Contains Carla paths: Yes")
        else:
            status = "✓" if value else "○"
            display_value = value if value else "Not set (optional)"
            print(f"{status} {var}: {display_value}")


def check_dependencies():
    """Check for common Carla dependencies."""
    print_header("Checking Dependencies")
    
    # Check Python version
    py_version = sys.version_info
    py_ok = py_version >= (3, 8)
    status = "✓" if py_ok else "✗"
    print(f"{status} Python version: {py_version.major}.{py_version.minor}.{py_version.micro}")
    
    if not py_ok:
        print("   ⚠ Python 3.8+ required")
    
    # Check for PyQt5 (optional but recommended)
    try:
        import PyQt5
        print(f"✓ PyQt5: Available (version {PyQt5.QtCore.PYQT_VERSION_STR})")
    except ImportError:
        print(f"○ PyQt5: Not installed (optional - needed for plugin UIs)")
    
    # Check if we can import the backend
    print("\nTrying to import carla_backend...")
    base_dir = Path(__file__).parent
    carla_root = base_dir / "Carla-main"
    frontend = carla_root / "source" / "frontend"
    
    if frontend.exists():
        sys.path.insert(0, str(frontend))
        try:
            import carla_backend
            print("✓ Successfully imported carla_backend")
            
            # Check for key constants
            constants = [
                "PLUGIN_VST2",
                "PLUGIN_VST3",
                "ENGINE_OPTION_PLUGIN_PATH",
                "BINARY_NATIVE",
            ]
            
            for const in constants:
                has_const = hasattr(carla_backend, const)
                status = "✓" if has_const else "✗"
                print(f"  {status} {const}: {'Available' if has_const else 'Missing'}")
                
        except ImportError as e:
            print(f"✗ Failed to import carla_backend: {e}")
        finally:
            sys.path.remove(str(frontend))
    else:
        print(f"✗ Frontend directory not found: {frontend}")


def check_plugin_directories():
    """Check for VST plugin directories."""
    print_header("Checking Plugin Directories")
    
    base_dir = Path(__file__).parent
    
    plugin_dirs = {
        "Project cache": base_dir / ".cache" / "plugins",
        "Project data": base_dir / "data" / "vsts",
    }
    
    # Add system VST directories
    if sys.platform.startswith("win"):
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        
        if program_files:
            plugin_dirs["Program Files VST"] = Path(program_files) / "VstPlugins"
        if program_files_x86:
            plugin_dirs["Program Files (x86) VST"] = Path(program_files_x86) / "VstPlugins"
    
    found_any = False
    for name, path in plugin_dirs.items():
        exists = path.exists()
        status = "✓" if exists else "○"
        print(f"{status} {name}: {path}")
        
        if exists:
            found_any = True
            # Count plugins
            plugins = list(path.glob("**/*.dll")) + list(path.glob("**/*.vst3"))
            if plugins:
                print(f"   └─ Contains {len(plugins)} plugin(s)")
    
    if not found_any:
        print("\n⚠ No plugin directories found")
        print("  Place VST plugins in: .cache/plugins/")


def generate_report(results):
    """Generate final report."""
    print_header("Installation Report")
    
    dir_structure_ok = results.get('dir_structure', False)
    files_ok = results.get('files', False)
    
    print("\nOverall Status:")
    
    if dir_structure_ok and files_ok:
        print("✓ Carla is properly installed and should work!")
        print("\nNext steps:")
        print("  1. Install PyQt5 if you haven't: pip install PyQt5")
        print("  2. Run the fix script: python fix_vst_integration.py")
        print("  3. Test it: python test_vst_integration.py")
        return True
    else:
        print("✗ Carla installation has issues")
        print("\nProblems found:")
        
        if not dir_structure_ok:
            print("  - Directory structure incomplete")
            print("    → Ensure Carla source is in: Carla-main/")
        
        if not files_ok:
            print("  - Required files missing")
            print("    → You need the Carla binary distribution")
            print("    → Download from: https://kx.studio/Applications:Carla")
            print("    → Or build from source")
        
        print("\nInstallation options:")
        print("  1. Binary distribution (Windows):")
        print("     - Download Carla for Windows")
        print("     - Extract to Carla-main/ directory")
        print("  2. Build from source:")
        print("     - See Carla documentation for build instructions")
        
        return False


def main():
    """Main verification function."""
    print("=" * 60)
    print("Carla Installation Verification")
    print("=" * 60)
    print("\nThis script checks if Carla is properly installed.")
    print("Run this before applying the VST integration fix.\n")
    
    results = {}
    
    # Run all checks
    results['dir_structure'] = check_directory_structure()
    files_ok, found_files = check_required_files()
    results['files'] = files_ok
    
    if found_files:
        check_file_sizes(found_files)
    
    check_environment_variables()
    check_dependencies()
    check_plugin_directories()
    
    # Generate report
    success = generate_report(results)
    
    print("\n" + "=" * 60)
    if success:
        print("Verification complete! ✓")
    else:
        print("Verification complete - Issues found")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
