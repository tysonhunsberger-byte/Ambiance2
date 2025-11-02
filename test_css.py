#!/usr/bin/env python3
"""Test CSS parsing to find problematic lines."""

import sys
from pathlib import Path

# Suppress Qt warnings temporarily
import os
os.environ.setdefault("QT_API", "pyqt6")
os.environ["QT_LOGGING_RULES"] = "qt.qpa.xcb=false"

from qtpy.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)
widget = QWidget()

# Test minimal CSS
css_tests = [
    ("text-align test", "QPushButton { text-align: left; }"),
    ("padding test", "QPushButton { padding: 8px 16px; }"),
    ("multiple selectors", "QSpinBox, QSlider { background: #2a2a2a; }"),
    ("background-size", "QWidget { background-size: cover; }"),
    ("color shorthand", "QWidget { color: #0f0; }"),
]

print("Testing CSS properties...")
for name, css in css_tests:
    widget.setStyleSheet(css)
    print(f"[OK] {name}")

print("\nTesting full flat.css...")
flat_css = Path("themes/flat.css")
if flat_css.exists():
    with open(flat_css, 'r') as f:
        content = f.read()
    widget.setStyleSheet(content)
    print(f"[OK] Flat theme loaded ({len(content)} bytes)")
else:
    print("[FAIL] flat.css not found")

print("\nDone! If you see Qt warnings above, those properties aren't supported.")
