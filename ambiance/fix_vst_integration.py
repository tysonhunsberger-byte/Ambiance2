"""
Quick Fix Script for Carla VST Integration
==========================================

This script automatically applies the fixes to enable VST plugin UI support.

What it does:
1. Checks if PyQt5 is installed
2. Backs up your current carla_host.py
3. Replaces it with the fixed version
4. Runs tests to verify everything works

Run this script to fix your VST integration!
"""

import sys
import shutil
from pathlib import Path
import subprocess


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60 + "\n")


def check_pyqt5():
    """Check if PyQt5 is installed."""
    try:
        import PyQt5
        print("✓ PyQt5 is already installed")
        return True
    except ImportError:
        print("✗ PyQt5 is NOT installed")
        return False


def install_pyqt5():
    """Install PyQt5 using pip."""
    print("Installing PyQt5...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "PyQt5"])
        print("✓ PyQt5 installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install PyQt5: {e}")
        return False


def backup_original(original_file):
    """Backup the original carla_host.py file."""
    backup_file = original_file.with_suffix(".py.backup")
    
    if backup_file.exists():
        print(f"✓ Backup already exists: {backup_file.name}")
        return True
    
    try:
        shutil.copy2(original_file, backup_file)
        print(f"✓ Created backup: {backup_file.name}")
        return True
    except Exception as e:
        print(f"✗ Failed to create backup: {e}")
        return False


def apply_fix(fixed_file, original_file):
    """Replace the original file with the fixed version."""
    try:
        shutil.copy2(fixed_file, original_file)
        print(f"✓ Applied fix: {original_file.name}")
        return True
    except Exception as e:
        print(f"✗ Failed to apply fix: {e}")
        return False


def run_tests():
    """Run the test script to verify everything works."""
    test_script = Path(__file__).parent / "test_vst_integration.py"
    
    if not test_script.exists():
        print("⚠ Test script not found - skipping tests")
        return True
    
    print("\nRunning verification tests...")
    try:
        result = subprocess.run(
            [sys.executable, str(test_script)],
            capture_output=False,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"✗ Failed to run tests: {e}")
        return False


def main():
    """Main fix application function."""
    print_header("Carla VST Integration Quick Fix")
    
    # Define paths
    base_dir = Path(__file__).parent
    integrations_dir = base_dir / "src" / "ambiance" / "integrations"
    original_file = integrations_dir / "carla_host.py"
    fixed_file = integrations_dir / "carla_host_fixed.py"
    
    # Verify files exist
    if not fixed_file.exists():
        print(f"✗ Fixed file not found: {fixed_file}")
        print("  Make sure carla_host_fixed.py is in the integrations directory")
        return 1
    
    if not original_file.exists():
        print(f"✗ Original file not found: {original_file}")
        print("  This doesn't look like the Ambiance project directory")
        return 1
    
    # Step 1: Check/Install PyQt5
    print_header("Step 1: Checking PyQt5")
    
    if not check_pyqt5():
        response = input("\nDo you want to install PyQt5 now? (y/n): ").lower()
        if response == 'y':
            if not install_pyqt5():
                print("\n⚠ PyQt5 installation failed. Please install manually:")
                print("  pip install PyQt5")
                return 1
        else:
            print("\n⚠ PyQt5 is required for plugin UIs to work!")
            print("  Install it later with: pip install PyQt5")
    
    # Step 2: Backup original file
    print_header("Step 2: Backing up original file")
    
    if not backup_original(original_file):
        print("\n⚠ Failed to create backup")
        response = input("Continue anyway? (y/n): ").lower()
        if response != 'y':
            print("Aborted")
            return 1
    
    # Step 3: Apply fix
    print_header("Step 3: Applying fix")
    
    if not apply_fix(fixed_file, original_file):
        print("\n✗ Failed to apply fix")
        print("  You may need administrator privileges")
        return 1
    
    # Step 4: Run tests
    print_header("Step 4: Running verification tests")
    
    tests_passed = run_tests()
    
    # Final summary
    print_header("Fix Application Complete")
    
    if tests_passed:
        print("✓ SUCCESS! Your VST integration is now working!")
        print("\nNext steps:")
        print("  1. Start your Ambiance server")
        print("  2. Load a VST plugin via the API")
        print("  3. Call /api/vst/editor/open to show the plugin UI")
        print("\nFor more information, see VST_INTEGRATION_FIX_GUIDE.md")
    else:
        print("⚠ Fix applied but tests failed")
        print("\nPlease review the test output above for details.")
        print("Check VST_INTEGRATION_FIX_GUIDE.md for troubleshooting.")
        print("\nYour original file has been backed up to:")
        print(f"  {original_file.with_suffix('.py.backup')}")
    
    return 0 if tests_passed else 1


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
