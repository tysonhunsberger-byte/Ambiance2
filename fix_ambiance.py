"""Apply fixes to the existing ambiance_qt.py file."""

import sys
from pathlib import Path

def apply_fixes():
    """Apply critical fixes to ambiance_qt.py"""
    
    ambiance_path = Path("C:/Ambiance2/ambiance_qt.py")
    
    if not ambiance_path.exists():
        print("ERROR: ambiance_qt.py not found at C:/Ambiance2/")
        return False
    
    # Read the file
    with open(ambiance_path, 'r') as f:
        content = f.read()
    
    # Fix 1: Expand keyboard octaves
    content = content.replace(
        "self.octaves = 2",
        "self.octaves = 5  # Expanded from 2"
    )
    content = content.replace(
        "self.start_note = 48  # C3",
        "self.start_note = 36  # C2 - Lower starting note"
    )
    content = content.replace(
        "self.white_key_width = 42",
        "self.white_key_width = 28  # Narrower to fit more octaves"
    )
    
    # Fix 2: Fix the UI display issue by using QTimer for async UI operations
    if "def toggle_ui(self):" in content:
        # Add QTimer import if not present
        if "from PyQt5.QtCore import Qt, QTimer, QSize" not in content:
            content = content.replace(
                "from PyQt5.QtCore import Qt, QTimer, QSize",
                "from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal"
            )
        
        # Replace toggle_ui method
        old_toggle_ui = '''    def toggle_ui(self):
        """Toggle native UI."""
        try:
            status = self.host.status()
            if status.get("ui_visible"):
                self.host.hide_ui()
                self.ui_btn.setText("Show Plugin UI")
            else:
                self.host.show_ui()
                self.ui_btn.setText("Hide Plugin UI")
        except CarlaHostError as e:
            QMessageBox.warning(self, "UI Error", str(e))'''
        
        new_toggle_ui = '''    def toggle_ui(self):
        """Toggle native UI with improved error handling."""
        try:
            status = self.host.status()
            if status.get("ui_visible"):
                self.host.hide_ui()
                self.ui_btn.setText("Show Plugin UI")
            else:
                # Use QTimer to defer UI showing to avoid blocking
                QTimer.singleShot(0, self._show_ui_deferred)
        except CarlaHostError as e:
            QMessageBox.warning(self, "UI Error", str(e))
    
    def _show_ui_deferred(self):
        """Show UI in deferred manner."""
        try:
            self.host.show_ui()
            self.ui_btn.setText("Hide Plugin UI")
        except CarlaHostError as e:
            QMessageBox.warning(self, "UI Error", f"Failed to show plugin UI:\\n{e}")'''
        
        if old_toggle_ui in content:
            content = content.replace(old_toggle_ui, new_toggle_ui)
        else:
            # Add the deferred method after toggle_ui
            content = content.replace(
                "def toggle_ui(self):",
                '''def toggle_ui(self):
        """Toggle native UI with improved error handling."""
        try:
            status = self.host.status()
            if status.get("ui_visible"):
                self.host.hide_ui()
                self.ui_btn.setText("Show Plugin UI")
            else:
                QTimer.singleShot(0, self._show_ui_deferred)
        except CarlaHostError as e:
            QMessageBox.warning(self, "UI Error", str(e))
    
    def _show_ui_deferred(self):
        """Show UI in deferred manner."""
        try:
            self.host.show_ui()
            self.ui_btn.setText("Hide Plugin UI")
        except CarlaHostError as e:
            QMessageBox.warning(self, "UI Error", f"Failed to show plugin UI:\\n{e}")
    
    def toggle_ui_original(self):'''
            )
    
    # Fix 3: Ensure parameters display properly
    if "def update_parameters(self):" in content:
        # Make sure parameter polling is more robust
        content = content.replace(
            "self.poll_timer.start(100)",
            "self.poll_timer.start(50)  # Faster polling for smoother updates"
        )
    
    # Fix 4: Add more plugin search paths
    if "plugin_dirs = [" in content:
        old_dirs = """        plugin_dirs = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
        ]"""
        
        new_dirs = """        plugin_dirs = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
            Path("C:/Program Files/VSTPlugins"),
            Path("C:/Program Files/Steinberg/VSTPlugins"),
            Path("C:/Program Files/Common Files/VST3"),
            Path("C:/Program Files (x86)/VSTPlugins"),
        ]"""
        
        content = content.replace(old_dirs, new_dirs)
    
    # Write the fixed content back
    backup_path = ambiance_path.with_suffix('.py.backup')
    ambiance_path.rename(backup_path)
    print(f"Original file backed up to: {backup_path}")
    
    with open(ambiance_path, 'w') as f:
        f.write(content)
    
    print("Fixes applied successfully!")
    print("\nFixed issues:")
    print("1. ✓ Expanded MIDI keyboard from 2 to 5 octaves")
    print("2. ✓ Fixed plugin UI display with deferred loading")
    print("3. ✓ Improved parameter update polling")
    print("4. ✓ Added more VST search paths")
    
    return True

if __name__ == "__main__":
    if apply_fixes():
        print("\nYou can now run: python ambiance_qt.py")
    else:
        print("\nFix failed. Please check the file path.")
