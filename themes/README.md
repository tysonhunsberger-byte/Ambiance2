# Ambiance Themes

This directory contains CSS theme files for the Ambiance application. You can create your own custom themes by following this guide!

## How to Create a Custom Theme

1. **Create a new CSS file** in this directory with a descriptive name (e.g., `my-theme.css`)

2. **Use the existing themes as templates**:
   - `flat.css` - Modern dark theme
   - `win98.css` - Classic Windows 98
   - `winxp.css` - Windows XP with Bliss wallpaper
   - `win7.css` - Windows 7 Aero

3. **Your theme will automatically appear** in the "Theme" dropdown menu

## Theme Structure

Every theme should style these components:

### Basic Widgets
- `QMainWindow, QWidget` - Main window and widget defaults
- `QPushButton` - Buttons (normal, hover, pressed states)
- `QComboBox` - Dropdown menus
- `QListWidget` - List boxes
- `QGroupBox` - Group boxes with titles
- `QTextEdit` - Text areas
- `QLabel` - Labels
- `QSpinBox` - Number inputs
- `QSlider` - Sliders (groove and handle)
- `QScrollArea` - Scroll areas
- `QTabWidget`, `QTabBar` - Tabs

### Desktop Background
- `QMdiArea#desktop` - The main desktop area background
  - Can use solid colors: `background: #008080;`
  - Can use images: `background: url({image.jpg}); background-repeat: no-repeat; background-position: center;`
  - **Note**: Qt stylesheets don't support `background-size: cover` - use separate properties instead

### Window Decorations (MDI Windows)
- `QMdiSubWindow` - Window frame
- `QMdiSubWindow::title` - Title bar
- `QMdiSubWindow::close-button` - Close button
- `QMdiSubWindow::minimize-button` - Minimize button
- `QMdiSubWindow::maximize-button` - Maximize button

### Taskbar
- `QWidget#taskbar` - Taskbar container
- `QWidget#taskbar QPushButton` - Taskbar buttons (normal, hover, checked states)

## Variables

You can use these variables in your theme CSS:

- `{bliss_path}` - Replaced with the full path to `bliss.jpg`
- `{win7_path}` - Replaced with the full path to `win7.jpg`

To use your own background images, place them in the Ambiance root directory and reference them:

```css
QMdiArea#desktop {
    background: url({your_image.jpg});
    background-repeat: no-repeat;
    background-position: center;
}
```

Then the application will replace `{your_image.jpg}` with the full path automatically.

**Important**: Qt stylesheets use slightly different syntax than standard CSS:
- Use `QWidget#id` instead of `#id` for ID selectors
- Separate background properties (no shorthand for all properties)
- Use `::` for pseudo-elements (e.g., `::title`, `::close-button`)

## Example: Creating a "Dark Purple" Theme

Create `themes/dark-purple.css`:

```css
/* Dark Purple Theme */

QMainWindow, QWidget {
    background: #1a0033;
    color: #e0d0ff;
}

QPushButton {
    background: #330066;
    color: #fff;
    border: 1px solid #6600cc;
    border-radius: 4px;
    padding: 8px 16px;
}

QPushButton:hover {
    background: #440088;
}

QPushButton:pressed {
    background: #220044;
}

QMdiArea#desktop {
    background: #0d001a;
}

QMdiSubWindow {
    background: #1a0033;
    border: 1px solid #6600cc;
}

QMdiSubWindow::title {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #6600cc, stop:1 #440088);
    color: #fff;
    padding: 4px;
    padding-left: 8px;
}

QWidget#taskbar {
    background: #220044;
    border-top: 1px solid #6600cc;
}

QWidget#taskbar QPushButton {
    background: #330066;
    border: 1px solid #6600cc;
    color: #fff;
}

/* Add other widget styles... */
```

Save the file, restart Ambiance, and "Dark Purple" will appear in the theme menu!

## Tips

- Use **contrasting colors** for text and backgrounds
- Test **hover and pressed states** for buttons
- Make sure **window titles are readable**
- Use **gradients** for depth (qlineargradient)
- Keep **taskbar buttons** visually distinct when checked
- Test with **different plugins** loaded to ensure all widgets look good

## Color Scheme Resources

- [Coolors.co](https://coolors.co/) - Color palette generator
- [Adobe Color](https://color.adobe.com/) - Color wheel and schemes
- [Material Design Colors](https://materialui.co/colors/) - Predefined palettes

## Qt Stylesheet Reference

- [Qt Stylesheet Syntax](https://doc.qt.io/qt-6/stylesheet-syntax.html)
- [Qt Style Sheets Examples](https://doc.qt.io/qt-6/stylesheet-examples.html)

## Share Your Themes!

Created a cool theme? Share it with the community! Themes are just CSS files, so they're easy to share and remix.
