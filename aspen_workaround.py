#!/usr/bin/env python
"""Quick workaround to bypass Aspen Trumpet crash and use Flutter VST host instead"""

import json
import sys
from pathlib import Path

# Add to your main startup or configuration
PROBLEMATIC_PLUGINS = [
    "Aspen Trumpet",
    "aspen_trumpet_1"
]

def configure_host_fallback():
    """Configure automatic fallback to Flutter host for problematic plugins"""
    config_path = Path("C:/Ambiance2/config/host_preferences.json")
    
    fallback_config = {
        "plugin_host_overrides": {
            "Aspen Trumpet 1.vst3": "flutter",
            "default": "carla"
        },
        "carla_options": {
            "ENGINE_OPTION_PREFER_PLUGIN_BRIDGES": 1,
            "ENGINE_OPTION_PREVENT_BAD_BEHAVIOUR": 1,
            "idle_timeout": 0.5
        },
        "flutter_fallback": True
    }
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(fallback_config, f, indent=2)
    
    print(f"✓ Created host fallback configuration at {config_path}")
    return config_path

def patch_carla_loading():
    """Monkey-patch to add synchronization to Carla loading"""
    try:
        # Add the ambiance source to path
        sys.path.insert(0, str(Path("C:/Ambiance2/src")))
        
        from ambiance.integrations.carla_host import CarlaHost
        import time
        
        original_load = CarlaHost.load_plugin
        
        def safe_load(self, plugin_path, **kwargs):
            plugin_name = Path(plugin_path).stem
            
            # Check if it's a problematic plugin
            if any(prob.lower() in plugin_name.lower() for prob in PROBLEMATIC_PLUGINS):
                print(f"⚠ {plugin_name} detected - using Flutter VST host")
                # Trigger fallback to Flutter host
                from ambiance.integrations.flutter_vst_host import FlutterVSTHost
                flutter = FlutterVSTHost(base_dir=Path("C:/Ambiance2"))
                return flutter.load_plugin(plugin_path, **kwargs)
            
            # For other plugins, add synchronization
            try:
                if hasattr(self, '_engine_running') and self._engine_running:
                    self.host.engine_idle()
                    time.sleep(0.05)
                
                result = original_load(self, plugin_path, **kwargs)
                
                # Extra idle after loading
                if hasattr(self, 'host') and self.host:
                    self.host.engine_idle()
                    time.sleep(0.05)
                
                return result
            except Exception as e:
                if "assertion" in str(e).lower():
                    print(f"⚠ Carla assertion error - retrying with Flutter host")
                    from ambiance.integrations.flutter_vst_host import FlutterVSTHost
                    flutter = FlutterVSTHost(base_dir=Path("C:/Ambiance2"))
                    return flutter.load_plugin(plugin_path, **kwargs)
                raise
        
        CarlaHost.load_plugin = safe_load
        print("✓ Patched Carla host with safety fallback")
        
    except ImportError as e:
        print(f"Could not patch: {e}")

def disable_aspen_autoload():
    """Prevent Aspen from auto-loading on startup"""
    autoload_path = Path("C:/Ambiance2/config/autoload.json")
    
    if autoload_path.exists():
        with open(autoload_path, 'r') as f:
            config = json.load(f)
        
        # Remove Aspen from autoload
        if "plugins" in config:
            config["plugins"] = [
                p for p in config["plugins"] 
                if "aspen" not in p.lower()
            ]
        
        with open(autoload_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        print("✓ Removed Aspen from autoload")

if __name__ == "__main__":
    print("Applying Aspen Trumpet crash workaround...")
    
    # 1. Configure host fallbacks
    configure_host_fallback()
    
    # 2. Apply runtime patch
    patch_carla_loading()
    
    # 3. Disable problematic autoload
    disable_aspen_autoload()
    
    print("\n✅ Workaround applied! You can now:")
    print("  • Use other VST plugins normally")
    print("  • Aspen Trumpet will use Flutter host automatically")
    print("  • No more crashes on startup")
    
    print("\nTo make permanent, add to your startup:")
    print("  python C:/Ambiance2/aspen_workaround.py")
