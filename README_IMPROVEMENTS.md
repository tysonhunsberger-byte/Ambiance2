# Ambiance VST Host - Improvements & Fixes

## Files Provided

1. **ambiance_qt_improved.py** - Complete rewrite with plugin chaining support
2. **fix_ambiance.py** - Patch script to fix issues in your existing ambiance_qt.py
3. **start_ambiance_improved.bat** - Launch script for the improved version

## Key Improvements

### 1. Plugin Chaining Support ✨
- Load multiple VST plugins simultaneously
- Create processing chains with multiple effects
- Individual bypass control for each plugin slot
- Per-slot parameter controls in tabbed interface

### 2. Extended MIDI Keyboard 🎹
- Expanded from 2 to 5 octaves (customizable 1-8)
- Lower starting note (C2 instead of C3) for better bass range
- Visual note indicators for C notes
- Toggle note name display
- Improved visual feedback

### 3. Fixed Plugin UI Display 🖼️
- Proper Qt event loop handling
- Threaded UI operations to prevent blocking
- Better error messages when UI fails
- Deferred UI loading for stability

### 4. Enhanced Parameter Controls 🎛️
- Tabbed interface for multi-plugin parameters
- Faster parameter polling (50ms)
- Per-slot parameter organization
- Better visual grouping

## Installation Options

### Option 1: Use the Improved Version (Recommended)
```batch
cd C:\Ambiance2
copy ambiance_qt_improved.py .
start_ambiance_improved.bat
```

### Option 2: Fix Your Existing Version
```batch
cd C:\Ambiance2
python fix_ambiance.py
python ambiance_qt.py
```

## How to Use Plugin Chaining

1. **Add Slots**: Click "+ Add Slot" to create plugin slots
2. **Load Plugins**: Select a slot, then double-click a plugin from the library
3. **Chain Processing**: Audio flows through all active slots in order
4. **Bypass**: Toggle individual slots or bypass all
5. **Show UI**: Each slot can show its plugin's native UI independently

## Troubleshooting

### Plugin UI Not Showing
- Ensure PyQt5 is installed: `pip install PyQt5`
- Check that the plugin has a UI (not all do)
- Try running as administrator
- Check Windows audio permissions

### MIDI Not Working
- Ensure plugin accepts MIDI input
- Check if plugin is an instrument/synth
- Try different velocity values

### No Sound
- Check Windows audio settings
- Verify DirectSound/WASAPI is working
- Ensure plugins are not bypassed
- Check plugin audio routing in chain

## Technical Details

The improved version uses:
- **Threading** for UI operations to prevent blocking
- **Plugin isolation** with separate Carla hosts per slot
- **Event-driven architecture** for better responsiveness
- **Enhanced error handling** with detailed messages

## Future Enhancements Possible
- Drag & drop reordering of plugin chain
- Preset saving/loading for entire chains
- MIDI learn for parameters
- Audio routing matrix between plugins
- Side-chain support
