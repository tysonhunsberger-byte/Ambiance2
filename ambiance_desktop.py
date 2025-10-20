"""Ambiance Desktop - Standalone app with embedded web UI."""

import sys
import threading
import argparse
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl, QTimer

# Add ambiance to path
sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.server import serve


class AmbianceDesktop(QMainWindow):
    """Desktop application with embedded web UI."""

    def __init__(self, host="127.0.0.1", port=8000):
        super().__init__()
        self.host = host
        self.port = port
        self.server_thread = None

        self.setWindowTitle("Ambiance - VST Host")
        self.setGeometry(100, 100, 1200, 900)

        # Create web view
        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)

        # Start server in background thread
        self.start_server()

        # Load web UI after a short delay
        QTimer.singleShot(500, self.load_ui)

    def start_server(self):
        """Start HTTP server in background thread."""
        def run_server():
            # Don't start Qt event loop in serve() since we're already in a Qt app
            # We need to modify serve() to support this, so for now just import and start
            from ambiance.server import serve
            # This will run the server but not the Qt event loop
            serve(host=self.host, port=self.port)

        # Note: We can't use the regular serve() because it wants to run Qt event loop
        # Instead, we'll start just the HTTP server part
        print(f"Starting Ambiance server on {self.host}:{self.port}")
        self.server_thread = threading.Thread(target=self.run_server_thread, daemon=True)
        self.server_thread.start()

    def run_server_thread(self):
        """Run HTTP server in background thread."""
        from http.server import ThreadingHTTPServer
        from ambiance.server import AmbianceRequestHandler
        from ambiance.integrations.plugins import PluginRackManager
        from ambiance.integrations.carla_host import CarlaVSTHost
        from ambiance.integrations.juce_vst3_host import JuceVST3Host
        from pathlib import Path
        import sys
        from typing import Any

        base_dir = Path(__file__).parent / "ambiance" / "src" / "ambiance"
        directory = str(base_dir)
        ui_path = base_dir / "noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html"

        manager = PluginRackManager(base_dir=base_dir)
        vst_host = CarlaVSTHost(base_dir=base_dir)

        preferred_drivers = ["DirectSound", "WASAPI", "ASIO", "MME", "JACK", "Dummy"]
        if sys.platform.startswith("linux"):
            preferred_drivers = ["JACK", "ALSA", "PulseAudio", "Dummy"]
        elif sys.platform == "darwin":
            preferred_drivers = ["CoreAudio", "JACK", "Dummy"]

        vst_host.configure_audio(preferred_drivers=preferred_drivers)
        juce_host = JuceVST3Host(base_dir=base_dir)

        def handler(*args: Any, **kwargs: Any):
            kwargs.setdefault("directory", directory)
            kwargs.setdefault("manager", manager)
            kwargs.setdefault("ui_path", ui_path)
            kwargs.setdefault("vst_host", vst_host)
            kwargs.setdefault("juce_host", juce_host)
            kwargs.setdefault("server_url", f"http://{self.host}:{self.port}")
            return AmbianceRequestHandler(*args, **kwargs)

        httpd = ThreadingHTTPServer((self.host, self.port), handler)
        print(f"Ambiance server running at http://{self.host}:{self.port}")
        httpd.serve_forever()

    def load_ui(self):
        """Load web UI in the embedded browser."""
        url = f"http://{self.host}:{self.port}/"
        print(f"Loading web UI from {url}")
        self.web_view.load(QUrl(url))

    def closeEvent(self, event):
        """Handle window close."""
        # Server will terminate when app exits (daemon thread)
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Ambiance Desktop - Standalone VST Host")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Ambiance")

    window = AmbianceDesktop(host=args.host, port=args.port)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
