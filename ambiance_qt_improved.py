
"""Ambiance - Improved Qt application with plugin chaining and UI fixes."""

import sys
import json
import logging
import queue
import os
os.environ.setdefault("QT_API", "pyqt6")
import re
from pathlib import Path
from collections import deque
from typing import Optional, List, Dict, Any, Tuple, Deque, Set, Callable, cast, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from string import Template
from textwrap import dedent
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

# Harden QtWebEngine: disable GPU/WebGL when not already requested by the environment.
QTWEBENGINE_SAFE_FLAGS = "--disable-gpu --disable-software-rasterizer --disable-webgl --disable-webgl2 --disable-accelerated-video"
existing_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
if existing_flags:
    if QTWEBENGINE_SAFE_FLAGS not in existing_flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{existing_flags} {QTWEBENGINE_SAFE_FLAGS}"
else:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = QTWEBENGINE_SAFE_FLAGS
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

try:
    import winsound  # Windows-only fallback tone generator
except ImportError:  # pragma: no cover - non-Windows systems
    winsound = None

from qtpy.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QScrollArea,
    QSlider, QFrame, QMessageBox, QComboBox, QTabWidget, QCheckBox,
    QPlainTextEdit, QToolButton, QSizePolicy, QStackedWidget
)
from qtpy.QtCore import Qt, QTimer, QThread, Signal as pyqtSignal, Slot as pyqtSlot, QObject, QEvent, QUrl, QSize
from qtpy.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPalette,
    QFont,
    QPaintEvent,
    QResizeEvent,
    QMouseEvent,
    QKeyEvent,
    QCloseEvent,
    QWindow,
    QDesktopServices,
)

QWebEngineView = None  # type: ignore
QWebEngineSettings = None  # type: ignore
QWebEnginePage = None  # type: ignore
QWebChannel = None  # type: ignore
WEBENGINE_IMPORT_ERROR: Optional[BaseException] = None
StrudelWebPage = None  # type: ignore


def _define_strudel_web_page() -> None:
    """Create or clear the StrudelWebPage definition depending on WebEngine availability."""
    global StrudelWebPage
    if QWebEnginePage is None:
        StrudelWebPage = None
        return

    class _StrudelWebPage(QWebEnginePage):
        def __init__(self, view: Optional["QWebEngineView"] = None, base_url: Optional[QUrl] = None) -> None:
            super().__init__(view)
            try:
                self.setAudioMuted(False)
            except Exception:
                pass
            self._skip_next_failure = False
            self._base_url = base_url

            try:
                self.renderProcessTerminated.connect(self._on_render_process_terminated)
            except Exception as exc:
                logging.getLogger(__name__).warning(f"Could not connect renderProcessTerminated signal: {exc}")

        def _on_render_process_terminated(self, termination_status, exit_code):
            logger = logging.getLogger(__name__)
            status_names = {
                0: "NormalTerminationStatus",
                1: "AbnormalTerminationStatus",
                2: "CrashedTerminationStatus",
                3: "KilledTerminationStatus",
            }
            status_name = status_names.get(termination_status, f"Unknown({termination_status})")
            logger.critical(f"Qt WebEngine render process terminated: {status_name}, exit code: {exit_code}")
            logger.critical(f"Current URL: {self.url().toString() if self.url() else 'None'}")

            if self.view():
                try:
                    logger.critical(f"View URL: {self.view().url().toString()}")
                except Exception:
                    pass

                try:
                    self.view().setHtml(
                        "<html><body style='background:#111;color:#fafafa;font-family:sans-serif;"
                        "display:flex;align-items:center;justify-content:center;height:100vh;'>"
                        "<div style='max-width:480px;text-align:center;'>"
                        "<h2>Strudel crashed inside the embedded browser</h2>"
                        "<p>We opened https://strudel.cc/ in your default browser so you can keep jamming.</p>"
                        "<p>You can also disable the embedded view via STRUDEL_FORCE_REMOTE/STRUDEL_ENABLED "
                        "in ambiance_qt_improved.py.</p>"
                        "</div></body></html>"
                    )
                except Exception:
                    pass

        def javaScriptConsoleMessage(self, level, message, line_number, source_id):
            logger = logging.getLogger(__name__)
            level_names = {0: "INFO", 1: "WARNING", 2: "ERROR"}
            level_name = level_names.get(level, f"LEVEL{level}")
            source = source_id if source_id else "(inline)"
            logger.info(f"[Strudel JS {level_name}] {source}:{line_number} - {message}")

        def _should_externalize(self, url: QUrl, nav_type: "QWebEnginePage.NavigationType", base_host: str) -> bool:
            if url is None:
                return False
            scheme = url.scheme().lower()
            path = url.path() or ""
            host = (url.host() or "").lower()

            if scheme in ("http", "https"):
                if base_host and host == base_host:
                    return False
                if host in ("localhost", "127.0.0.1"):
                    return path.startswith("/learn")
                if host in ("strudel.cc", "www.strudel.cc", "strudel.tidalcycles.org"):
                    return nav_type == QWebEnginePage.NavigationTypeLinkClicked and path.startswith("/learn")
                return nav_type == QWebEnginePage.NavigationTypeLinkClicked

            if scheme in ("", "file"):
                return path.startswith("/learn")
            return True

        def _open_external(self, url: QUrl) -> None:
            if url is None:
                return
            if url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)
                return
            path = url.path() or "/learn"
            external = QUrl(f"https://strudel.cc{path}")
            QDesktopServices.openUrl(external)

        def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame):
            base_host = ""
            if self._base_url is not None and self._base_url.isValid():
                base_host = (self._base_url.host() or "").lower()
            elif self.view() is not None:
                try:
                    current = self.view().url()
                    if current and current.isValid():
                        base_host = (current.host() or "").lower()
                except Exception:
                    base_host = ""

            if is_main_frame and self._should_externalize(url, nav_type, base_host):
                self._open_external(url)
                self._skip_next_failure = True
                if self._base_url is not None and self.view() is not None:
                    try:
                        base = QUrl(self._base_url)
                        if base.isValid():
                            QTimer.singleShot(0, lambda v=self.view(), u=base: v.setUrl(u))
                    except Exception:
                        pass
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def createWindow(self, window_type):
            page = _StrudelWebPage(base_url=self._base_url)

            def handle_url_changed(new_url: QUrl) -> None:
                page.deleteLater()
                base_host = ""
                if self._base_url is not None and self._base_url.isValid():
                    base_host = (self._base_url.host() or "").lower()
                if self._should_externalize(new_url, QWebEnginePage.NavigationTypeLinkClicked, base_host):
                    self._open_external(new_url)
                    page._skip_next_failure = True
                    if self._base_url is not None and self.view() is not None:
                        try:
                            base = QUrl(self._base_url)
                            if base.isValid():
                                QTimer.singleShot(0, lambda v=self.view(), u=base: v.setUrl(u))
                        except Exception:
                            pass
                else:
                    QDesktopServices.openUrl(new_url)

            page.urlChanged.connect(handle_url_changed)
            return page

    StrudelWebPage = _StrudelWebPage  # type: ignore


def ensure_webengine() -> None:
    """Load Qt WebEngine lazily after QApplication is created."""
    global QWebEngineView, QWebEngineSettings, QWebEnginePage, QWebChannel, WEBENGINE_IMPORT_ERROR
    if QWebEngineView is not None or WEBENGINE_IMPORT_ERROR is not None:
        return
    try:
        from qtpy.QtWebEngineWidgets import (
            QWebEngineView as _QWebEngineView,
            QWebEngineSettings as _QWebEngineSettings,
            QWebEnginePage as _QWebEnginePage,
        )
        from qtpy.QtWebChannel import QWebChannel as _QWebChannel
    except ImportError as exc:  # pragma: no cover - optional dependency
        WEBENGINE_IMPORT_ERROR = exc
        return
    QWebEngineView = _QWebEngineView  # type: ignore
    QWebEngineSettings = _QWebEngineSettings  # type: ignore
    QWebEnginePage = _QWebEnginePage  # type: ignore
    QWebChannel = _QWebChannel  # type: ignore
    _define_strudel_web_page()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.carla_host import CarlaVSTHost, CarlaHostError
try:
    from ambiance.audio_engine import AudioEngine
except (RuntimeError, ImportError) as exc:
    AudioEngine = None  # type: ignore[assignment]
    AUDIO_ENGINE_IMPORT_ERROR: Optional[BaseException] = exc
else:
    AUDIO_ENGINE_IMPORT_ERROR = None

if TYPE_CHECKING:
    from ambiance.audio_engine import AudioEngine as _AudioEngineType
from ambiance.widgets import BlocksPanel

# Color scheme
COLORS = {
    'bg': '#121212',
    'panel': '#1e1e1e',
    'card': '#222',
    'text': '#f0f0f0',
    'muted': '#bbb',
    'accent': '#59a7ff',
    'border': '#444',
    'success': '#4caf50',
    'warning': '#ff9800',
    'error': '#f44336'
}

THEME_PRESETS = {
    "flat": {
        "colors": {
            'bg': '#10141d',
            'panel': '#19202b',
            'card': '#202835',
            'text': '#f4f6fb',
            'muted': '#aeb7c9',
            'accent': '#4da3ff',
            'border': '#2f3b4c',
            'success': '#36c16b',
            'warning': '#ffb547',
            'error': '#ff5f5f'
        },
        "dark": True
    },
    "win98": {
        "colors": {
            'bg': '#008080',
            'panel': '#c3c7cb',
            'card': '#dfdfdf',
            'text': '#1a1a1a',
            'muted': '#4f4f4f',
            'accent': '#000080',
            'border': '#808080',
            'success': '#0f7a0f',
            'warning': '#ba7b00',
            'error': '#b00020'
        },
        "dark": False
    },
    "winxp": {
        "colors": {
            'bg': '#245edb',
            'panel': '#ece9d8',
            'card': '#ffffff',
            'text': '#1b2a4a',
            'muted': '#4a5c7a',
            'accent': '#3d6dd1',
            'border': '#7f9db9',
            'success': '#3c8500',
            'warning': '#f0a000',
            'error': '#d83c3c'
        },
        "dark": False
    }
}

STRUDEL_REMOTE_BASES: Tuple[str, ...] = (
    "https://strudel.cc/",
    "https://strudel.tidalcycles.org/",
)
STRUDEL_REMOTE_URL = STRUDEL_REMOTE_BASES[0]
STRUDEL_REMOTE_FALLBACK_PREFIXES: Tuple[str, ...] = (
    "/_astro/",
    "/fonts/",
    "/icons/",
    "/images/",
    "/audio/",
    "/sounds/",
    "/media/",
)

# Global toggle controlling Strudel integration inside the desktop shell
STRUDEL_ENABLED = True
# Force the embedded view to use the remote Strudel site instead of local assets.
# Set to False once the local bundle is stable again.
STRUDEL_FORCE_REMOTE = False

# Debug toggles for Strudel crash investigation
DEBUG_SERVE_RAW_STRUDEL_INDEX = True
DEBUG_ENABLE_STRUDEL_POLYFILLS = False
DEBUG_ENABLE_STRUDEL_THEME_INJECTION = False
DEBUG_ENABLE_STRUDEL_BRIDGE = False


@dataclass(eq=False)
class PluginChainSlot:
    """Represents a plugin slot in the chain."""
    index: int
    plugin_path: Optional[Path] = None
    host: Optional[CarlaVSTHost] = None
    enabled: bool = True
    ui_visible: bool = False
    parameters: Dict[int, float] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    supports_midi: bool = False



class StrudelPatternBridge(QObject):
    """Bridge object exposed to Strudel via QWebChannel."""

    patternReceived = pyqtSignal(dict)

    def __init__(self, window: "AmbianceQtImproved") -> None:
        super().__init__()
        self._window = window
        self.patternReceived.connect(window.on_strudel_pattern)

    @pyqtSlot(str)
    def receivePattern(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logging.getLogger(__name__).warning("Invalid Strudel bridge payload: %s", payload)
            return
        self.patternReceived.emit(data)


class StrudelStaticServer:
    """Minimal HTTP server that serves the bundled Strudel assets with proper MIME types."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port: Optional[int] = None
        self._remote_index_cache: Optional[str] = None
        self._remote_index_source: Optional[str] = None
        self._remote_index_lock = threading.Lock()
        self._asset_index: Dict[str, Path] = {}
        self._asset_index_lock = threading.Lock()
        embed_root = root / "strudel" / "website" / "dist"
        self._embed_root: Optional[Path] = embed_root if embed_root.exists() else None
        search_roots: List[Path] = [self.root.resolve()]
        if self._embed_root is not None:
            search_roots.append(self._embed_root.resolve())
        self._search_roots: Tuple[Path, ...] = tuple(search_roots)

    def _extract_missing_assets(self, html: str) -> Set[str]:
        pattern = re.compile(r"[\"'](/?_astro/[^\"']+)")
        assets = {match.group(1) for match in pattern.finditer(html)}
        missing: Set[str] = set()
        for asset in assets:
            relative = asset.lstrip('/')
            found = False
            for base in self._search_roots:
                candidate = base / relative
                if candidate.exists():
                    found = True
                    break
            if not found:
                missing.add(asset)
        return missing

    @staticmethod
    def _score_hashed_candidate(
        prefix: str,
        target_hash: str,
        suffix: str,
        path: Path,
    ) -> Optional[Tuple[Tuple[int, int, int, int, str], Path]]:
        if not path.is_file():
            return None
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        name = path.name
        stem = name[: -len(suffix)] if suffix and name.endswith(suffix) else path.stem
        hash_separator = stem.rfind(".")
        candidate_prefix = stem[:hash_separator] if hash_separator != -1 else stem
        candidate_hash = stem[hash_separator + 1:] if hash_separator != -1 else ""

        prefix_miss = 0 if candidate_prefix == prefix else 1
        ratio = (
            SequenceMatcher(None, target_hash, candidate_hash).ratio()
            if target_hash and candidate_hash
            else 0.0
        )
        ratio_score = -int(ratio * 1000)
        hash_len_score = abs(len(candidate_hash) - len(target_hash))
        size_score = -int(size)

        key = (prefix_miss, ratio_score, hash_len_score, size_score, name)
        return key, path

    def _fetch_remote_index(self) -> Optional[str]:
        with self._remote_index_lock:
            if self._remote_index_cache is not None:
                return self._remote_index_cache
            logger = logging.getLogger(__name__)
            for base in STRUDEL_REMOTE_BASES:
                index_url = urljoin(base.rstrip('/') + '/', 'index.html')
                try:
                    with urlopen(index_url) as response:
                        encoding = response.headers.get_content_charset('utf-8')
                        html = response.read().decode(encoding, errors='replace')
                except Exception as exc:
                    logger.debug("Failed to fetch remote Strudel index from %s: %s", index_url, exc)
                    continue
                self._remote_index_cache = html
                self._remote_index_source = index_url
                logger.info("Fetched remote Strudel index from %s", index_url)
                return html
            return None

    def _attempt_local_asset_remap(self, html: str, missing: Set[str]) -> Tuple[str, Dict[str, str], Set[str]]:
        """Attempt to rewrite missing hashed asset references to files that exist locally."""

        replacements: Dict[str, str] = {}
        unresolved: Set[str] = set()

        for asset in sorted(missing):
            relative = asset.lstrip('/')
            target = self.root / relative
            parent = target.parent
            name = target.name

            suffix = Path(name).suffix
            if not suffix:
                unresolved.add(asset)
                continue

            alternate = self._find_alternate_asset(asset)
            if alternate and alternate.exists():
                replacement = '/' + alternate.relative_to(self.root).as_posix()
                replacements[asset] = replacement
                continue

            stem = name[: -len(suffix)]
            hash_separator = stem.rfind('.')
            if hash_separator == -1:
                unresolved.add(asset)
                continue

            prefix = stem[:hash_separator]
            pattern = f"{prefix}.*{suffix}"

            if not parent.exists():
                unresolved.add(asset)
                continue

            matches = sorted(path for path in parent.glob(pattern) if path.is_file())
            if not matches:
                unresolved.add(asset)
                continue

            target_hash = stem[hash_separator + 1 :]
            scored_matches: List[Tuple[Tuple[int, int, int, int, str], Path]] = []
            for candidate in matches:
                scored_candidate = self._score_hashed_candidate(prefix, target_hash, suffix, candidate)
                if scored_candidate is not None:
                    scored_matches.append(scored_candidate)
            if not scored_matches:
                unresolved.add(asset)
                continue
            scored_matches.sort()
            replacement_path = scored_matches[0][1]
            replacement = '/' + replacement_path.relative_to(self.root).as_posix()
            replacements[asset] = replacement

        for old, new in replacements.items():
            html = html.replace(old, new)

        return html, replacements, unresolved

    def _populate_asset_index(self) -> None:
        with self._asset_index_lock:
            if self._asset_index:
                return
            ignore_dirs = {".git", ".hg", ".svn", ".pnpm", "node_modules", "__pycache__", ".venv"}
            for base in self._search_roots:
                for current, dirnames, filenames in os.walk(base):
                    current_path = Path(current)
                    if current_path.name == "_astro":
                        relative_dir = current_path.relative_to(base)
                        for filename in filenames:
                            rel_path = (base / relative_dir / filename).resolve()
                            self._asset_index.setdefault(filename, rel_path)
                        dirnames[:] = []
                        continue
                    dirnames[:] = [d for d in dirnames if d not in ignore_dirs]

    def _find_alternate_asset(self, rel_path: str) -> Optional[Path]:
        relative = rel_path.lstrip("/")
        if not relative:
            return None
        for base in self._search_roots:
            candidate = base / relative
            if candidate.exists():
                return candidate

        name = Path(relative).name
        if not name:
            return None

        self._populate_asset_index()
        with self._asset_index_lock:
            mapped = self._asset_index.get(name)
            if mapped and mapped.exists():
                return mapped

        suffix = Path(name).suffix
        if suffix:
            stem = name[: -len(suffix)]
            hash_separator = stem.rfind(".")
            if hash_separator != -1:
                prefix = stem[:hash_separator]
                target_hash = stem[hash_separator + 1 :]
                scored_matches: List[Tuple[Tuple[int, int, int, int, str], Path]] = []
                with self._asset_index_lock:
                    for candidate_name, candidate_path in self._asset_index.items():
                        if candidate_name.startswith(prefix) and candidate_name.endswith(suffix):
                            scored = self._score_hashed_candidate(prefix, target_hash, suffix, candidate_path)
                            if scored is not None:
                                scored_matches.append(scored)
                if scored_matches:
                    scored_matches.sort()
                    return scored_matches[0][1]
        return None

    def _serve_alternate_asset(
        self,
        handler: SimpleHTTPRequestHandler,
        rel_path: str,
        query: str,
    ) -> bool:
        alternate = self._find_alternate_asset(rel_path)
        if alternate is None:
            return False
        logger = logging.getLogger(__name__)
        try:
            with alternate.open("rb") as handle:
                data = handle.read()
        except Exception as exc:
            logger.debug("Failed to read fallback Strudel asset %s: %s", alternate, exc)
            return False
        content_type = handler.guess_type(alternate.name)
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        try:
            handler.wfile.write(data)
        except Exception:
            return True
        try:
            relative_display = "/" + alternate.relative_to(self.root).as_posix()
        except ValueError:
            relative_display = "/" + alternate.as_posix()
        suffix = f"?{query}" if query else ""
        logger.info(
            "Served fallback Strudel asset %s%s from %s",
            rel_path,
            suffix,
            relative_display,
        )
        return True

    def _should_serve_from_embed(self, rel_path: str) -> bool:
        if self._embed_root is None:
            return False
        relative = rel_path.lstrip("/")
        if not relative:
            return False
        if not relative.startswith("embed/"):
            return False
        embed_candidate = self._embed_root / relative
        return embed_candidate.exists()

    def _get_index_content(self) -> Tuple[Optional[str], bool, Set[str]]:
        index_path: Optional[Path] = self.root / "index.html"
        if not index_path.exists():
            return None, False, set()
        try:
            content = index_path.read_text(encoding='utf-8')
        except Exception as exc:
            logging.getLogger(__name__).warning("Unable to read Strudel index: %s", exc)
            return None, False, set()
        missing = self._extract_missing_assets(content)
        if missing:
            logger = logging.getLogger(__name__)
            logger.warning(
                "Local Strudel index is missing %d asset(s): %s", len(missing), ", ".join(sorted(missing))
            )

            content, remapped, unresolved = self._attempt_local_asset_remap(content, missing)
            if remapped:
                summary = ", ".join(f"{old} -> {new}" for old, new in remapped.items())
                logger.info("Rewrote Strudel asset references to available bundle files: %s", summary)

            missing_after = self._extract_missing_assets(content)
            if not missing_after:
                return content, False, set()

            if unresolved:
                logger.info(
                    "Unable to locate local replacements for %d Strudel asset(s): %s",
                    len(unresolved),
                    ", ".join(sorted(unresolved)),
                )

            remote = self._fetch_remote_index()
            if remote:
                return remote, True, missing_after
            logger.warning("Remote Strudel index unavailable; continuing with bundled copy")
            return content, False, missing_after

        return content, False, missing

    def start(self) -> None:
        if self._httpd is not None:
            return

        root = self.root
        server_instance = self  # Capture reference for use in Handler

        class Handler(SimpleHTTPRequestHandler):  # type: ignore[misc, valid-type]
            # Set MIME types for JavaScript modules and other assets
            # This is the correct way to configure MIME types in SimpleHTTPRequestHandler
            extensions_map = {
                **SimpleHTTPRequestHandler.extensions_map,
                '.js': 'application/javascript',
                '.mjs': 'application/javascript',
                '.json': 'application/json',
                '.css': 'text/css',
                '.html': 'text/html',
                '.svg': 'image/svg+xml',
                '.wasm': 'application/wasm',
                '': 'application/octet-stream',
            }

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root), **kwargs)  # type: ignore[arg-type]

            def do_GET(self):
                # Intercept index.html to fix base href and module URLs
                if self.path == '/index.html' or self.path == '/':
                    served_raw = False
                    if DEBUG_SERVE_RAW_STRUDEL_INDEX:
                        try:
                            index_path = root / 'index.html'
                            if index_path.exists():
                                logging.getLogger(__name__).info("Serving UNMODIFIED index.html for crash diagnosis")
                                data = index_path.read_bytes()
                                self.send_response(200)
                                self.send_header('Content-Type', 'text/html; charset=utf-8')
                                self.send_header('Content-Length', str(len(data)))
                                self.end_headers()
                                self.wfile.write(data)
                                served_raw = True
                        except Exception as exc:
                            logging.getLogger(__name__).error(f"Failed to serve unmodified index.html: {exc}")
                    if served_raw:
                        return

                    try:
                        content, used_remote, missing_assets = server_instance._get_index_content()
                        if content is not None:
                            raw_base = server_instance.base_url or "/"
                            base_url = raw_base.rstrip('/')
                            if not base_url:
                                base_url = "/"
                            base_href = f"{base_url}/" if base_url != "/" else "/"
                            astro_prefix = "" if base_url == "/" else base_url

                            # Normalise the <base> tag so relative imports resolve to the server origin.
                            base_pattern = re.compile(r'<base\s+href="[^"]*"\s*>', re.IGNORECASE)
                            replacement_base = f'<base href="{base_href}">'
                            if base_pattern.search(content):
                                content, base_subs = base_pattern.subn(replacement_base, content, count=1)
                            else:
                                base_subs = 0

                            # Ensure all Astro-generated asset URLs point at the HTTP server rather than relative paths.
                            def _rewrite_attr(attr: str, html: str) -> Tuple[str, int]:
                                replacements = 0
                                for quote in ('"', "'"):
                                    absolute = f"{attr}={quote}{astro_prefix}/_astro/"
                                    needle_slash = f"{attr}={quote}/_astro/"
                                    needle_plain = f"{attr}={quote}_astro/"
                                    if needle_slash in html:
                                        occurrences = html.count(needle_slash)
                                        html = html.replace(needle_slash, absolute)
                                        replacements += occurrences
                                    if needle_plain in html:
                                        occurrences = html.count(needle_plain)
                                        html = html.replace(needle_plain, absolute)
                                        replacements += occurrences
                                return html, replacements

                            astro_attrs = ("src", "href", "component-url", "renderer-url")
                            total_rewrites = 0
                            for attr in astro_attrs:
                                content, count = _rewrite_attr(attr, content)
                                total_rewrites += count

                            if DEBUG_ENABLE_STRUDEL_POLYFILLS:
                                polyfill_comment = "<!-- Strudel compatibility polyfill -->"
                                if polyfill_comment not in content:
                                    polyfill_script = (
                                        "<script>"
                                        "(function(){"
                                        "if(!('webkitStorageInfo' in window) && typeof navigator !== 'undefined'){"
                                        "var temp=navigator.webkitTemporaryStorage;"
                                        "var persistent=navigator.webkitPersistentStorage;"
                                        "if(temp || persistent){"
                                        "window.webkitStorageInfo={"
                                        "TEMPORARY:0,PERSISTENT:1,"
                                        "requestQuota:function(type,size,success,error){"
                                        "var target=type===1?persistent:temp;"
                                        "if(target && typeof target.requestQuota==='function'){"
                                        "target.requestQuota(size,function(granted){if(typeof success==='function'){success(granted);}},function(err){if(typeof error==='function'){error(err);}});"
                                        "}else if(typeof success==='function'){success(size);}"
                                        "},"
                                        "queryUsageAndQuota:function(type,success,error){"
                                        "var target=type===1?persistent:temp;"
                                        "if(target && typeof target.queryUsageAndQuota==='function'){"
                                        "target.queryUsageAndQuota(function(used,granted){if(typeof success==='function'){success(used,granted);}},function(err){if(typeof error==='function'){error(err);}});"
                                        "}else if(typeof success==='function'){success(0,0);}"
                                        "}"
                                        "};"
                                        "}"
                                        "}"
                                        "})();"
                                        "</script>"
                                    )
                                    if "</head>" in content:
                                        content = content.replace("</head>", f"{polyfill_comment}{polyfill_script}</head>")

                                replace_comment = "<!-- Strudel replaceAll polyfill -->"
                                if replace_comment not in content:
                                    replace_script = (
                                        "<script>"
                                        "(function(){"
                                        "if(typeof String.prototype.replaceAll!=='function'){"
                                        "String.prototype.replaceAll=function(search,replace){"
                                        "if(search instanceof RegExp){"
                                        "if(!search.global) throw new TypeError('replaceAll with non-global RegExp');"
                                        "return this.replace(search,replace);"
                                        "}"
                                        "var escaped=String(search).replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');"
                                        "return this.replace(new RegExp(escaped,'g'),replace);"
                                        "};"
                                        "}"
                                        "})();"
                                        "</script>"
                                    )
                                    if "</head>" in content:
                                        content = content.replace("</head>", f"{replace_comment}{replace_script}</head>")

                            if DEBUG_ENABLE_STRUDEL_THEME_INJECTION:
                                learn_comment = "<!-- Ambiance learn redirect -->"
                                if learn_comment not in content:
                                    learn_script = (
                                        "<script>"
                                        "(function(){"
                                        "function hideLearn(root){if(!root||!root.querySelectorAll){return;}root.querySelectorAll(\\\"a[href^='/learn']\\\").forEach(function(anchor){anchor.style.display='none';anchor.setAttribute('aria-hidden','true');var parent=anchor.parentElement;if(parent && parent.children.length===1){parent.style.display='none';}});}"
                                        "hideLearn(document);"
                                        "new MutationObserver(function(muts){muts.forEach(function(mut){if(mut.addedNodes){mut.addedNodes.forEach(function(node){hideLearn(node);});}});}).observe(document.documentElement,{subtree:true,childList:true});"
                                        "})();"
                                        "</script>"
                                    )
                                    if "</head>" in content:
                                        content = content.replace("</head>", f"{learn_comment}{learn_script}</head>")

                                theme_comment = "<!-- Ambiance Strudel CSS -->"
                                if theme_comment not in content:
                                    theme_style = (
                                        "<style>"
                                        "body,html{background:var(--background,#181a1f);color:var(--foreground,#f2f4f8);}"
                                        ".bg-background,.bg-white,.bg-gray-50,.bg-gray-100,.bg-surface{background:var(--panel,#20252d)!important;color:var(--foreground,#f2f4f8)!important;}"
                                        "button,.btn,.button,[role='tab'],.tab{background:var(--panel,#20252d)!important;color:var(--foreground,#f2f4f8)!important;border-color:var(--accent,#59a7ff)!important;}"
                                        "[role='tab'][aria-selected='true'],.tab-active{color:var(--accent,#59a7ff)!important;border-bottom:2px solid var(--accent,#59a7ff)!important;}"
                                        "a{color:var(--accent,#59a7ff)!important;}"
                                        "input,textarea,select{background:var(--panel,#20252d)!important;color:var(--foreground,#f2f4f8)!important;border-color:rgba(255,255,255,0.15)!important;}"
                                        ".text-foreground,.text-foreground\\/80,.text-foreground\\/60{color:var(--foreground,#f2f4f8)!important;}"
                                        "</style>"
                                    )
                                    if "</head>" in content:
                                        content = content.replace("</head>", f"{theme_comment}{theme_style}</head>")

                            if base_subs or total_rewrites or used_remote:
                                logging.getLogger(__name__).info(
                                    "Modified index.html with base URL %s (base=%s, astro_rewrites=%s, remote_index=%s)",
                                    base_href,
                                    base_subs,
                                    total_rewrites,
                                    used_remote,
                                )
                                if used_remote and missing_assets:
                                    logging.getLogger(__name__).info(
                                        "Bundled Strudel assets missing locally: %s", ", ".join(sorted(missing_assets))
                                    )

                            # Send the modified content
                            content_bytes = content.encode('utf-8')
                            self.send_response(200)
                            self.send_header('Content-Type', 'text/html; charset=utf-8')
                            self.send_header('Content-Length', str(len(content_bytes)))
                            self.end_headers()
                            self.wfile.write(content_bytes)
                            return
                    except Exception as exc:
                        logging.getLogger(__name__).warning(f"Failed to modify index.html: {exc}")
                path_info = urlsplit(self.path)
                normalised_path = path_info.path
                if normalised_path not in ('', '/'):
                    candidate = (root / normalised_path.lstrip('/'))
                    try:
                        resolved_candidate = candidate.resolve()
                        root_path = root.resolve()
                        resolved_candidate.relative_to(root_path)
                    except Exception:
                        self.send_error(403, "Forbidden")
                        return

                    if resolved_candidate.is_dir():
                        index_candidate = resolved_candidate / "index.html"
                        if not normalised_path.endswith('/'):
                            location = normalised_path + '/'
                            self.send_response(301)
                            self.send_header('Location', location)
                            self.end_headers()
                            return
                        if index_candidate.exists():
                            try:
                                content = index_candidate.read_text(encoding='utf-8')

                                # Only apply asset rewriting for full HTML documents, not redirect stubs
                                # Redirect stubs are tiny files (<500 bytes) with just window.location
                                is_redirect_stub = len(content) < 500 and 'window.location' in content

                                if not is_redirect_stub:
                                    # Apply same base URL and asset rewriting as root index.html
                                    raw_base = server_instance.base_url or "/"
                                    base_url = raw_base.rstrip('/')
                                    if not base_url:
                                        base_url = "/"
                                    base_href = f"{base_url}/" if base_url != "/" else "/"
                                    astro_prefix = "" if base_url == "/" else base_url

                                    # Normalize <base> tag
                                    base_pattern = re.compile(r'<base\s+href="[^"]*"\s*>', re.IGNORECASE)
                                    replacement_base = f'<base href="{base_href}">'
                                    if base_pattern.search(content):
                                        content = base_pattern.sub(replacement_base, content, count=1)

                                    # Rewrite asset URLs to use HTTP server paths
                                    for attr in ('src', 'href'):
                                        for quote in ('"', "'"):
                                            absolute = f"{attr}={quote}{astro_prefix}/_astro/"
                                            needle_slash = f"{attr}={quote}/_astro/"
                                            needle_plain = f"{attr}={quote}_astro/"
                                            if needle_slash in content:
                                                content = content.replace(needle_slash, absolute)
                                            if needle_plain in content:
                                                content = content.replace(needle_plain, absolute)

                                data = content.encode('utf-8')
                            except Exception as exc:
                                logging.getLogger(__name__).warning("Unable to read directory index %s: %s", index_candidate, exc)
                                self.send_error(500, "Failed to load directory index")
                                return
                            self.send_response(200)
                            self.send_header('Content-Type', 'text/html; charset=utf-8')
                            self.send_header('Content-Length', str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)
                            return

                    prefer_embed = server_instance._should_serve_from_embed(normalised_path)
                    if resolved_candidate.is_file() and not prefer_embed:
                        super().do_GET()
                        return

                    if prefer_embed:
                        alternate_handled = server_instance._serve_alternate_asset(
                            self,
                            normalised_path,
                            path_info.query,
                        )
                        if alternate_handled:
                            return
                    else:
                        alternate_handled = server_instance._serve_alternate_asset(
                            self,
                            normalised_path,
                            path_info.query,
                        )
                        if alternate_handled:
                            return

                    proxy_handled = False
                    if any(normalised_path.startswith(prefix) for prefix in STRUDEL_REMOTE_FALLBACK_PREFIXES):
                        proxy_handled = self._proxy_remote_asset(
                            resolved_candidate,
                            normalised_path,
                            path_info.query,
                        )
                    if proxy_handled:
                        return
                # Fall back to default behavior for all other files
                super().do_GET()

            def _proxy_remote_asset(self, cache_target: Path, rel_path: str, query: str) -> bool:
                logger = logging.getLogger(__name__)
                data: Optional[bytes] = None
                content_type = self.guess_type(rel_path)
                last_error: Optional[Tuple[str, Exception]] = None
                for base in STRUDEL_REMOTE_BASES:
                    remote_base = base.rstrip('/') + '/'
                    remote_url = urljoin(remote_base, rel_path.lstrip('/'))
                    candidate_url = f"{remote_url}?{query}" if query else remote_url
                    try:
                        with urlopen(candidate_url) as response:
                            data = response.read()
                            content_type = response.headers.get('Content-Type') or self.guess_type(rel_path)
                    except Exception as exc:
                        last_error = (candidate_url, exc)
                        logger.debug("Failed to fetch Strudel asset from %s: %s", candidate_url, exc)
                        continue
                    logger.info(
                        "Proxied missing Strudel asset %s from %s (%d bytes)",
                        rel_path,
                        candidate_url,
                        len(data),
                    )
                    break

                if data is None:
                    if last_error:
                        logger.warning(
                            "Failed to proxy Strudel asset %s after trying %s: %s",
                            rel_path,
                            ", ".join(STRUDEL_REMOTE_BASES),
                            last_error[1],
                        )
                    self.send_error(502, f"Unable to load Strudel asset: {rel_path}")
                    return True

                try:
                    cache_target.parent.mkdir(parents=True, exist_ok=True)
                    with cache_target.open('wb') as handle:
                        handle.write(data)
                except Exception as exc:
                    logger.debug("Could not cache proxied Strudel asset %s: %s", rel_path, exc)

                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except Exception:
                    return True
                return True

            def end_headers(self):
                # Add CORS headers to allow cross-origin requests
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', '*')
                super().end_headers()

            def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - reduces console noise
                logging.getLogger(__name__).debug("Strudel static server: " + format, *args)

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except Exception:
            self._httpd = None
            raise

        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="StrudelStaticServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
        except Exception:
            pass
        try:
            self._httpd.server_close()
        except Exception:
            pass
        thread = self._thread
        self._httpd = None
        self.port = None
        self._thread = None
        if thread and thread.is_alive():
            try:
                thread.join(timeout=0.5)
            except Exception:
                pass

    @property
    def base_url(self) -> Optional[str]:
        if self.port is None:
            return None
        return f"http://127.0.0.1:{self.port}"


class PianoKeyboard(QWidget):
    """Enhanced virtual piano keyboard with extended range."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMaximumHeight(180)
        
        # Extended keyboard settings
        self.octaves = 5  # Expanded from 2 to 5 octaves
        self.start_note = 36  # C2 instead of C3
        self.white_key_width = 28  # Narrower keys to fit more octaves
        self.white_key_height = 140
        self.black_key_width = 18
        self.black_key_height = 95
        
        # Display settings
        self.show_note_names = True
        self.highlight_c_notes = True
        
        # State
        self.pressed_keys = set()
        self.mouse_down_note = None
        self.white_key_rects: Dict[int, Tuple[int, int, int, int]] = {}
        self.black_key_rects: Dict[int, Tuple[int, int, int, int]] = {}
        
        # Callbacks
        self.note_on_callback = None
        self.note_off_callback = None
        
        self.setMouseTracking(True)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(9, 12, 18, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                padding: 18px 14px;
            }}
        """)

    def set_callbacks(self, note_on, note_off):
        self.note_on_callback = note_on
        self.note_off_callback = note_off

    def release_all_keys(self) -> None:
        """Clear any pressed key state without emitting callbacks."""
        self.pressed_keys.clear()
        self.mouse_down_note = None
        self.update()

    def _compute_key_rects(self) -> Tuple[Dict[int, Tuple[int, int, int, int]], Dict[int, Tuple[int, int, int, int]]]:
        """Compute the rectangles for white and black keys."""
        white_rects: Dict[int, Tuple[int, int, int, int]] = {}
        black_rects: Dict[int, Tuple[int, int, int, int]] = {}
        x = 10
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                white_rects[note] = (x, 10, self.white_key_width, self.white_key_height)
                x += self.white_key_width
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [1, 3, 6, 8, 10]:
                base_rect = white_rects.get(note - 1)
                if not base_rect:
                    continue
                base_x = base_rect[0]
                rect_x = base_x + self.white_key_width - self.black_key_width // 2
                black_rects[note] = (rect_x, 10, self.black_key_width, self.black_key_height)
        return white_rects, black_rects
    
    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        white_rects, black_rects = self._compute_key_rects()
        self.white_key_rects = white_rects
        self.black_key_rects = black_rects

        # Draw white keys
        for note in sorted(white_rects):
            is_pressed = note in self.pressed_keys
            is_c = (note % 12 == 0)
            rect = white_rects[note]
            
            if is_pressed:
                color = QColor('#f97316')
            elif is_c and self.highlight_c_notes:
                color = QColor(225, 227, 235)
            else:
                color = QColor(245, 247, 255)
            
            painter.fillRect(*rect, color)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 2))
            painter.drawRect(*rect)
            
            # Draw note names
            if self.show_note_names and is_c:
                painter.setPen(QPen(QColor(100, 100, 100), 1))
                font = QFont("Arial", 8)
                painter.setFont(font)
                octave = (note - 12) // 12
                painter.drawText(rect[0] + 8, rect[1] + rect[3] - 4, f"C{octave}")
        
        # Draw black keys
        for note in sorted(black_rects):
            rect = black_rects[note]
            is_pressed = note in self.pressed_keys
            color = QColor('#f97316') if is_pressed else QColor(15, 18, 24)
            painter.fillRect(*rect, color)
            painter.setPen(QPen(QColor(17, 17, 17), 2))
            painter.drawRect(*rect)
    
    def get_note_at_position(self, x, y):
        """Get note at mouse position."""
        if not (self.white_key_rects and self.black_key_rects):
            self.white_key_rects, self.black_key_rects = self._compute_key_rects()
        if y < 10 or y > 10 + self.white_key_height:
            return None
        
        # Check black keys first (they're on top)
        for note, (rx, ry, rw, rh) in self.black_key_rects.items():
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return note
        
        # Check white keys
        for note, (rx, ry, rw, rh) in self.white_key_rects.items():
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return note
        
        return None
    
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        note = self.get_note_at_position(event.x(), event.y())
        if note is not None:
            self.mouse_down_note = note
            if note not in self.pressed_keys:
                self.pressed_keys.add(note)
                self.update()
                if self.note_on_callback:
                    self.note_on_callback(note)
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self.mouse_down_note is not None:
            if self.mouse_down_note in self.pressed_keys:
                self.pressed_keys.remove(self.mouse_down_note)
                self.update()
                if self.note_off_callback:
                    self.note_off_callback(self.mouse_down_note)
            self.mouse_down_note = None
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self.mouse_down_note is not None:
            current_note = self.get_note_at_position(event.x(), event.y())
            if current_note != self.mouse_down_note:
                # Release old note
                if self.mouse_down_note in self.pressed_keys:
                    self.pressed_keys.remove(self.mouse_down_note)
                    if self.note_off_callback:
                        self.note_off_callback(self.mouse_down_note)
                
                # Press new note
                if current_note is not None:
                    self.mouse_down_note = current_note
                    if current_note not in self.pressed_keys:
                        self.pressed_keys.add(current_note)
                        if self.note_on_callback:
                            self.note_on_callback(current_note)
                else:
                    self.mouse_down_note = None

                self.update()


class PluginEditorContainer(QFrame):
    """Container that can host a native plugin editor window."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PluginEditorContainer")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self._window_container: Optional[QWidget] = None
        self._window: Optional[QWindow] = None
        self._base_minimum_height = 320
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(self._base_minimum_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        self.placeholder = QLabel("Dock the plugin UI to keep it pinned above the keyboard.")
        self.placeholder.setObjectName("PluginEditorPlaceholder")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, 1)

    def embed_handle(self, hwnd: int | None) -> None:
        """Embed a native window handle inside the container."""

        self.clear_container()
        if not hwnd:
            return

        window = QWindow.fromWinId(int(hwnd))
        window.setFlags(Qt.FramelessWindowHint)
        container = QWidget.createWindowContainer(window, self)
        container.setFocusPolicy(Qt.StrongFocus)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout().addWidget(container)
        self._window_container = container
        self._window = window
        try:
            window.widthChanged.connect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
            window.heightChanged.connect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._apply_window_size(window.size())
        self.placeholder.hide()

    def clear_container(self) -> None:
        """Remove any embedded plugin editor from the container."""

        if self._window_container is not None:
            self._window_container.setParent(None)
            self._window_container.deleteLater()
            self._window_container = None
        if self._window is not None:
            try:
                self._window.widthChanged.disconnect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self._window.heightChanged.disconnect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            self._window.setParent(None)
            self._window = None
        self.placeholder.show()
        self.setMinimumHeight(self._base_minimum_height)
        self.setMinimumWidth(0)
        self.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._window is None:
            return
        size = event.size()
        if size.isValid():
            try:
                self._window.resize(size)
            except Exception:
                pass

    def _apply_window_size(self, size: QSize) -> None:
        if not size.isValid():
            return
        margins = self.layout().contentsMargins()
        width = max(size.width(), 320)
        height = max(size.height(), self._base_minimum_height)
        if self._window_container is not None:
            self._window_container.setMinimumSize(size)
            self._window_container.resize(size)
        self.setMinimumSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )
        self.updateGeometry()

    def _on_window_dimension_changed(self, _value: int) -> None:
        if self._window is None:
            return
        self._apply_window_size(self._window.size())

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(event.rect(), self.palette().color(QPalette.Window))
        super().paintEvent(event)


class CollapsibleSection(QFrame):
    """Simple collapsible container with a toggle button."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow)
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.toggled.connect(self._on_toggled)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.content_area = QFrame()
        self.content_area.setObjectName("CollapsibleSectionContent")
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(0)

        wrapper_layout = QVBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(6)
        wrapper_layout.addWidget(self.toggle_button)
        wrapper_layout.addWidget(self.content_area)

        self.content_area.setVisible(self.toggle_button.isChecked())

    def _on_toggled(self, checked: bool) -> None:
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.content_area.setVisible(checked)
        self.toggled.emit(checked)

    def setContentWidget(self, widget: QWidget) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.content_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically expand or collapse the section."""

        self.toggle_button.setChecked(bool(expanded))


class PluginChainWidget(QWidget):
    """Widget for managing the plugin chain."""
    
    slot_selected = pyqtSignal(int)
    slot_updated = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(f"{__name__}.PluginChainWidget")
        self.slots: List[PluginChainSlot] = []
        self.selected_slot_index = -1
        self._ui_threads: Dict[PluginChainSlot, threading.Thread] = {}
        self.host_window_id: Optional[int] = None
        self.host_dock_check: Optional[QCheckBox] = None
        self.host_editor_container: Optional["PluginEditorContainer"] = None

        self.init_ui()
        self._install_event_filter()

        # Create one default slot (multi-slot disabled for now)
        self.add_slot()

    def set_host_controls(
        self,
        dock_check: Optional[QCheckBox],
        editor_container: Optional["PluginEditorContainer"],
    ) -> None:
        """Share the host dock toggle and container owned by the main window."""

        self.host_dock_check = dock_check
        self.host_editor_container = editor_container

    def _clear_host_container(self) -> None:
        if self.host_editor_container:
            self.host_editor_container.clear_container()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Chain controls
        controls = QHBoxLayout()
        
        self.add_slot_btn = QPushButton("+ Add Slot")
        self.add_slot_btn.clicked.connect(self.add_slot)
        self.add_slot_btn.setEnabled(False)  # TEMP: Disabled until multi-engine support added
        self.add_slot_btn.setToolTip("Multiple plugins not yet supported - Carla engine limitation")
        controls.addWidget(self.add_slot_btn)
        
        self.remove_slot_btn = QPushButton("- Remove Slot")
        self.remove_slot_btn.clicked.connect(self.remove_selected_slot)
        self.remove_slot_btn.setEnabled(False)
        controls.addWidget(self.remove_slot_btn)
        
        controls.addStretch()
        
        self.bypass_all_btn = QPushButton("Bypass All")
        self.bypass_all_btn.setCheckable(True)
        self.bypass_all_btn.clicked.connect(self.toggle_bypass_all)
        controls.addWidget(self.bypass_all_btn)
        
        layout.addLayout(controls)
        
        # Chain list
        self.chain_list = QListWidget()
        self.chain_list.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.chain_list)
        
        # Slot controls
        slot_controls = QHBoxLayout()
        
        self.load_btn = QPushButton("Load Plugin")
        self.load_btn.clicked.connect(self.load_plugin_for_slot)
        self.load_btn.setEnabled(False)
        slot_controls.addWidget(self.load_btn)
        
        self.unload_btn = QPushButton("Unload")
        self.unload_btn.clicked.connect(self.unload_plugin_from_slot)
        self.unload_btn.setEnabled(False)
        slot_controls.addWidget(self.unload_btn)
        
        self.bypass_btn = QPushButton("Bypass")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.clicked.connect(self.toggle_bypass_slot)
        self.bypass_btn.setEnabled(False)
        slot_controls.addWidget(self.bypass_btn)
        
        self.ui_btn = QPushButton("Show UI")
        self.ui_btn.clicked.connect(self.toggle_slot_ui)
        self.ui_btn.setEnabled(False)
        slot_controls.addWidget(self.ui_btn)
        
        layout.addLayout(slot_controls)
        
        self.apply_styles()
    
    def apply_styles(self):
        for btn in [self.add_slot_btn, self.remove_slot_btn, self.load_btn, 
                   self.unload_btn, self.bypass_btn, self.ui_btn, self.bypass_all_btn]:
            btn.setStyleSheet("")

        self.chain_list.setStyleSheet(f"""
            QListWidget {{
                background-color: rgba(0, 0, 0, 0.25);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 6px;
            }}
            QListWidget::item {{
                padding: 10px;
                border-radius: 8px;
                margin: 4px 0;
            }}
            QListWidget::item:selected {{
                background-color: rgba(89, 167, 255, 0.35);
                border: 1px solid rgba(89, 167, 255, 0.6);
            }}
            QListWidget::item:hover {{
                background-color: rgba(255, 255, 255, 0.08);
            }}
        """)
    
    def _install_event_filter(self) -> None:
        """Register this widget as an event filter with the active QApplication."""
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.installEventFilter(self)
        except Exception:
            pass

    def register_host_window(self, win_id: int) -> None:
        """Remember the main window handle for plugin window discovery."""

        self.host_window_id = int(win_id)
        for slot in self.slots:
            if slot.host:
                slot.host.register_host_window(self.host_window_id)

    def _current_slot(self) -> Optional[PluginChainSlot]:
        if 0 <= self.selected_slot_index < len(self.slots):
            return self.slots[self.selected_slot_index]
        return None

    def _activate_plugin_ui(self, slot: PluginChainSlot, handle: Optional[int]) -> None:
        """Embed or raise the plugin UI based on the dock toggle state."""

        if not slot.host:
            return

        dock_check = self.host_dock_check
        container = self.host_editor_container

        if dock_check and container and dock_check.isChecked():
            parent_id = int(container.winId())
            if handle and slot.host.embed_plugin_window(parent_id):
                container.embed_handle(handle)
                return

            # Docking failed - fall back to floating window and inform the user.
            container.clear_container()
            dock_check.blockSignals(True)
            dock_check.setChecked(False)
            dock_check.blockSignals(False)
            QMessageBox.warning(
                self,
                "Plugin Dock",
                "This plugin's editor could not be docked. It will open as a separate window instead.",
            )

        # Ensure the plugin UI floats and can be focused from the taskbar.
        slot.host.embed_plugin_window(None)
        if container:
            container.clear_container()
        slot.host.ensure_plugin_window_taskbar()
        slot.host.focus_plugin_window()

    def on_host_dock_toggled(self, checked: bool) -> None:
        slot = self._current_slot()
        if not slot or not slot.host or not slot.ui_visible:
            if not checked:
                self._clear_host_container()
            return

        handle = slot.host.get_plugin_window_handle(attempts=20)
        if checked:
            self._activate_plugin_ui(slot, handle)
        else:
            slot.host.embed_plugin_window(None)
            self._clear_host_container()
            slot.host.ensure_plugin_window_taskbar()
            slot.host.focus_plugin_window()

    def _after_ui_shown(self, slot: PluginChainSlot) -> None:
        if slot not in self.slots or not slot.host:
            return
        dock_check = self.host_dock_check
        attempts = 30 if dock_check and dock_check.isChecked() else 15
        handle = slot.host.get_plugin_window_handle(attempts=attempts)
        self._activate_plugin_ui(slot, handle)

    def add_slot(self):
        """Add a new plugin slot to the chain."""
        slot = PluginChainSlot(index=len(self.slots))
        self.slots.append(slot)
        
        item = QListWidgetItem(f"Slot {slot.index + 1}: [Empty]")
        self.chain_list.addItem(item)
        
        # Auto-select the new slot
        self.chain_list.setCurrentRow(slot.index)
        self.slot_updated.emit(slot.index)
    
    def remove_selected_slot(self):
        """Remove the selected slot from the chain."""
        if self.selected_slot_index < 0:
            return

        removed_index = self.selected_slot_index
        slot = self.slots[removed_index]
        if slot.host:
            with slot.lock:
                slot.host.unload()
                slot.host.shutdown()
        slot.supports_midi = False
        self._clear_host_container()

        self.slots.pop(removed_index)
        self.chain_list.takeItem(removed_index)
        self._ui_threads.pop(slot, None)

        # Re-index remaining slots
        for i, remaining in enumerate(self.slots):
            remaining.index = i
            self.update_slot_display(i)

        if self._ui_threads:
            self._ui_threads = {
                s: t for s, t in self._ui_threads.items() if s in self.slots and (not t or t.is_alive())
            }

        # Determine next selection
        next_index = removed_index
        if next_index >= len(self.slots):
            next_index = len(self.slots) - 1

        if next_index >= 0:
            self.chain_list.setCurrentRow(next_index)
        else:
            self.selected_slot_index = -1
            self.update_controls()
            self.slot_selected.emit(-1)

        self.slot_updated.emit(next_index)
    
    def on_selection_changed(self):
        """Handle slot selection change."""
        items = self.chain_list.selectedItems()
        if items:
            self.selected_slot_index = self.chain_list.row(items[0])
        else:
            self.selected_slot_index = -1
        self.update_controls()
        self.slot_selected.emit(self.selected_slot_index)
    
    def update_controls(self):
        """Update control buttons based on selection."""
        has_selection = self.selected_slot_index >= 0
        self.remove_slot_btn.setEnabled(has_selection)
        self.load_btn.setEnabled(has_selection)
        
        if has_selection:
            slot = self.slots[self.selected_slot_index]
            has_plugin = slot.plugin_path is not None
            self.unload_btn.setEnabled(has_plugin)
            self.bypass_btn.setEnabled(has_plugin)
            self.bypass_btn.setChecked(not slot.enabled)
            self.ui_btn.setEnabled(has_plugin)
            self.ui_btn.setText("Hide UI" if slot.ui_visible else "Show UI")
        else:
            self.unload_btn.setEnabled(False)
            self.bypass_btn.setEnabled(False)
            self.ui_btn.setEnabled(False)
    
    def update_slot_display(self, index):
        """Update the display text for a slot."""
        if 0 <= index < len(self.slots):
            slot = self.slots[index]
            item = self.chain_list.item(index)
            if item is None:
                return
            
            if slot.plugin_path:
                name = slot.plugin_path.stem
                status = "Bypassed" if not slot.enabled else "Active"
                text = f"Slot {index + 1}: {name} [{status}]"
            else:
                text = f"Slot {index + 1}: [Empty]"
            
            item.setText(text)
            self.slot_updated.emit(index)
    
    def load_plugin_for_slot(self):
        """Load a plugin into the selected slot."""
        # This will be connected to the main window's plugin selection
        pass
    
    def unload_plugin_from_slot(self):
        """Unload plugin from the selected slot."""
        if self.selected_slot_index < 0:
            return

        slot = self.slots[self.selected_slot_index]
        if slot.host:
            with slot.lock:
                slot.host.unload()
                slot.host.shutdown()
            slot.host = None
        slot.plugin_path = None
        slot.supports_midi = False
        slot.ui_visible = False
        self._clear_host_container()
        self.update_slot_display(self.selected_slot_index)
        self.update_controls()
    
    def toggle_bypass_slot(self):
        """Toggle bypass for the selected slot."""
        if self.selected_slot_index >= 0:
            slot = self.slots[self.selected_slot_index]
            slot.enabled = not slot.enabled
            self.update_slot_display(self.selected_slot_index)
    
    def toggle_bypass_all(self):
        """Toggle bypass for all slots."""
        bypass = self.bypass_all_btn.isChecked()
        for i, slot in enumerate(self.slots):
            slot.enabled = not bypass
            self.update_slot_display(i)
    
    def toggle_slot_ui(self):
        """Toggle UI for the selected slot."""
        if self.selected_slot_index < 0:
            return
        slot = self.slots[self.selected_slot_index]
        if not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into this slot first.")
            return

        try:
            if slot.ui_visible:
                with slot.lock:
                    try:
                        slot.host.embed_plugin_window(None)
                    except Exception:
                        pass
                    slot.host.hide_ui()
                slot.ui_visible = False
                self._clear_host_container()
                self.update_controls()
            else:
                # Call show_ui() without holding lock - it handles threading internally
                self.logger.info("Requesting UI for slot %s (%s)", slot.index, slot.plugin_path)
                if self.host_window_id is not None:
                    slot.host.register_host_window(self.host_window_id)
                slot.host.show_ui()
                # Set visible flag with a small delay to let UI thread start
                QTimer.singleShot(150, lambda: self._set_ui_visible(slot, True))
                QTimer.singleShot(180, lambda s=slot: self._after_ui_shown(s))
        except Exception as e:
            self.logger.error("UI error for slot %s: %s", slot.index, e, exc_info=True)
            QMessageBox.warning(self, "UI Error", f"Failed to open UI: {e}\n\nSome plugins may not support native UI.")
            slot.ui_visible = False
            self.update_controls()
    
    def _set_ui_visible(self, slot: PluginChainSlot, visible: bool):
        """Set UI visible flag and update controls."""
        slot.ui_visible = visible
        self.update_controls()

    def _show_slot_ui_worker(self, slot: PluginChainSlot):
        if slot not in self.slots:
            return
        host = slot.host
        slot_index = slot.index
        try:
            if host:
                with slot.lock:
                    self.logger.info("Launching host UI for slot %s on worker thread", slot_index)
                    host.show_ui()
                QTimer.singleShot(0, lambda idx=slot_index: self.on_ui_shown(idx, True))
        except Exception as exc:
            self.logger.error("Failed to show UI for slot %s: %s", slot_index, exc, exc_info=True)
            QTimer.singleShot(0, lambda idx=slot_index, msg=str(exc): self.on_ui_error(idx, msg))
        finally:
            self._ui_threads.pop(slot, None)
            QTimer.singleShot(0, self.update_controls)

    def on_ui_shown(self, index: int, shown: bool):
        """Handle UI shown signal."""
        if 0 <= index < len(self.slots):
            self.slots[index].ui_visible = shown
            if index == self.selected_slot_index:
                self.update_controls()
    
    def on_ui_error(self, index: int, error: str):
        """Handle UI error signal."""
        if 0 <= index < len(self.slots):
            slot = self.slots[index]
            self._ui_threads.pop(slot, None)
            slot.ui_visible = False
        QMessageBox.warning(self, "UI Error", f"Failed to show UI for slot {index + 1}:\n{error}")
    
    def get_active_slots(self) -> List[PluginChainSlot]:
        """Get list of active (non-bypassed) slots with hosts."""
        return [s for s in self.slots if s.enabled and s.host]

    def shutdown(self):
        """Ensure any running UI threads are stopped."""
        for thread in list(self._ui_threads.values()):
            if thread and thread.is_alive():
                thread.join(timeout=0.5)
        self._ui_threads.clear()


class AmbianceQtImproved(QMainWindow):
    """Improved Qt desktop app with plugin chaining."""

    # Map QWERTY keyboard keys to semitone offsets from the piano's start note.
    # Layout follows common DAW conventions (Z row = base octave, Q row = +1 octave).
    KEYBOARD_NOTE_MAP: Dict[int, int] = {
        # Lower row (Z-M)
        Qt.Key_Z: 0,
        Qt.Key_S: 1,
        Qt.Key_X: 2,
        Qt.Key_D: 3,
        Qt.Key_C: 4,
        Qt.Key_V: 5,
        Qt.Key_G: 6,
        Qt.Key_B: 7,
        Qt.Key_H: 8,
        Qt.Key_N: 9,
        Qt.Key_J: 10,
        Qt.Key_M: 11,
        Qt.Key_Comma: 12,
        Qt.Key_L: 13,
        Qt.Key_Period: 14,
        Qt.Key_Semicolon: 15,
        Qt.Key_Slash: 16,
        Qt.Key_Apostrophe: 17,
        # Upper row (Q-P) mirrors next octave
        Qt.Key_Q: 12,
        Qt.Key_2: 13,
        Qt.Key_W: 14,
        Qt.Key_3: 15,
        Qt.Key_E: 16,
        Qt.Key_R: 17,
        Qt.Key_5: 18,
        Qt.Key_T: 19,
        Qt.Key_6: 20,
        Qt.Key_Y: 21,
        Qt.Key_7: 22,
        Qt.Key_U: 23,
        Qt.Key_I: 24,
        Qt.Key_9: 25,
        Qt.Key_O: 26,
        Qt.Key_0: 27,
        Qt.Key_P: 28,
        Qt.Key_BracketLeft: 29,
        Qt.Key_Equal: 30,
        Qt.Key_BracketRight: 31,
    }
    
    def _install_event_filter(self):
        if self._qt_app is None:
            self._qt_app = QApplication.instance()
        if self._qt_app is not None:
            try:
                self._qt_app.installEventFilter(self)
            except Exception:
                pass

    def _midi_worker_loop(self) -> None:
        """Background thread that serialises MIDI operations."""
        while not getattr(self, "_midi_worker_stop", threading.Event()).is_set():
            try:
                job = self._midi_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                self._midi_queue.task_done()
                break
            callback, args, kwargs = job
            try:
                callback(*args, **kwargs)
            except CarlaHostError as exc:
                self.logger.warning("MIDI dispatch error: %s", exc)
            except Exception as exc:
                self.logger.error("MIDI dispatch crashed: %s", exc, exc_info=True)
            finally:
                self._midi_queue.task_done()
    def poll_parameters(self):
        pass

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.keyboard_active_notes: Dict[int, int] = {}
        self._qt_app = QApplication.instance()
        self._keyboard_suspended = False

        
        # Logging
        self.logger = logging.getLogger(__name__)
        
        # State
        self.plugin_chain = []
        self.param_sliders = {}
        self.updating_from_plugin = False
        self.instrument_velocity = 0.85
        self.instrument_octave = 4
        self.param_refresh_attempts: Dict[int, int] = {}
        self.theme_key = "flat"
        self.dark_mode = THEME_PRESETS[self.theme_key]["dark"]
        self.colors = dict(COLORS)
        self._apply_theme_colors(self.theme_key)
        self.fallback_audio_threads: List[threading.Thread] = []
        self.warned_no_winsound = False

        # MIDI dispatch worker keeps Carla calls off the UI thread to prevent plugin crashes.
        self._midi_queue: "queue.Queue[Optional[tuple[Callable[..., None], tuple, dict]]]" = queue.Queue()
        self._midi_worker_stop = threading.Event()
        self._midi_worker = threading.Thread(
            target=self._midi_worker_loop,
            name="AmbianceMIDIWorker",
            daemon=True,
        )
        self._midi_worker.start()

        ensure_webengine()
        self.strudel_available = STRUDEL_ENABLED and QWebEngineView is not None
        if not self.strudel_available and WEBENGINE_IMPORT_ERROR:
            self.logger.warning(f"PyQtWebEngine import failed: {WEBENGINE_IMPORT_ERROR}")
        elif not self.strudel_available:
            if STRUDEL_ENABLED:
                self.logger.warning("PyQtWebEngine is not available (QWebEngineView is None)")
            else:
                self.logger.info("Strudel integration disabled by configuration")
        else:
            self.logger.info("PyQtWebEngine is available")
        self.strudel_loaded = False
        self._strudel_signals_connected = False
        self.body_stack: Optional[QStackedWidget] = None
        self.strudel_container: Optional[QWidget] = None
        self.strudel_view: Optional["QWebEngineView"] = None
        self.strudel_mode_btn: Optional[QPushButton] = None
        self._strudel_channel: Optional["QWebChannel"] = None
        self._strudel_module_hint: Optional[str] = None
        self._strudel_local_index: Optional[Path] = None
        self._strudel_using_local = False
        self._strudel_base_url: Optional[QUrl] = None
        self._strudel_page = None
        self._strudel_static_server: Optional[StrudelStaticServer] = None
        self._strudel_event_queue: Deque[Dict[str, Any]] = deque(maxlen=512)
        self.strudel_bridge = StrudelPatternBridge(self)
        self.default_status_message = "Ready - pick a plugin from the library."

        self.audio_engine: Optional["AudioEngine"] = None
        if AudioEngine is not None:
            try:
                self.audio_engine = AudioEngine()
                self.logger.info("Audio engine booted (pyo).")
            except Exception as exc:
                self.logger.error("Failed to initialise audio engine: %s", exc, exc_info=True)
                self.audio_engine = None
        else:
            if AUDIO_ENGINE_IMPORT_ERROR is not None:
                self.logger.warning(
                    "Audio engine disabled (pyo unavailable): %s",
                    AUDIO_ENGINE_IMPORT_ERROR,
                )
        
        # Timer for parameter updates
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_parameters)
        
        self.init_ui()

        if self._qt_app is not None:
            self._qt_app.installEventFilter(self)
        
        # Start Qt event processing
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(QApplication.processEvents)
        self.process_timer.start(10)  # Process events every 10ms
    
    def init_ui(self):
        self.setWindowTitle("Ambiance Studio Rack")
        self.setGeometry(120, 80, 1560, 960)
        self.update_theme_palette()

        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(14)

        self.toolbar = self.build_toolbar()
        root_layout.addWidget(self.toolbar)

        self.body_stack = QStackedWidget()
        self.body_stack.setObjectName("BodyStack")
        root_layout.addWidget(self.body_stack, 1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("BodyScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.body_stack.addWidget(self.scroll_area)

        self.body_widget = QWidget()
        self.body_widget.setObjectName("BodyWidget")
        self.scroll_area.setWidget(self.body_widget)

        self.body_layout = QVBoxLayout(self.body_widget)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(20)
        
        self.plugin_block = self.build_plugin_block()
        self.plugin_section = CollapsibleSection("Plugin Rack")
        self.plugin_section.setContentWidget(self.plugin_block)
        self.plugin_section.set_expanded(False)
        self.body_layout.addWidget(self.plugin_section)

        if self.audio_engine is not None:
            self.blocks_panel = BlocksPanel(self.audio_engine)
            self.blocks_panel.apply_theme(self.colors, dark=self.dark_mode)
            created_block = self.blocks_panel.create_block()
            if created_block is not None:
                self.append_log("Blocks engine ready - Block 1 created.")
            self.blocks_section = CollapsibleSection("Blocks & Streams")
            self.blocks_section.setContentWidget(self.blocks_panel)
            self.body_layout.addWidget(self.blocks_section)
        else:
            self.blocks_panel = None
            self.blocks_section = None
            self.append_log("Audio engine unavailable - Blocks panel disabled.")

        self.strudel_container = QWidget()
        self.strudel_container.setObjectName("StrudelContainer")
        self._strudel_layout = QVBoxLayout(self.strudel_container)
        self._strudel_layout.setContentsMargins(0, 0, 0, 0)
        self._strudel_layout.setSpacing(0)

        if self.strudel_available:
            self.strudel_view = None
        else:
            if not STRUDEL_ENABLED:
                error_msg = (
                    "Strudel Mode has been disabled in this build due to stability issues.\n"
                    "Open https://strudel.cc/ in your web browser to keep jamming."
                )
            elif WEBENGINE_IMPORT_ERROR:
                error_msg = (
                    f"PyQtWebEngine import failed: {WEBENGINE_IMPORT_ERROR}\n\n"
                    "Strudel Mode requires PyQtWebEngine.\n"
                    "Try: pip install --force-reinstall PyQt6-WebEngine PyQt6"
                )
            else:
                error_msg = (
                    "Strudel Mode requires PyQtWebEngine. Install the 'PyQtWebEngine' package "
                    "to enable the embedded browser."
                )
            fallback_label = QLabel(error_msg)
            fallback_label.setObjectName("StrudelFallback")
            fallback_label.setWordWrap(True)
            fallback_label.setAlignment(Qt.AlignCenter)
            self._strudel_layout.addStretch(1)
            self._strudel_layout.addWidget(fallback_label)
            self._strudel_layout.addStretch(1)

        self.body_stack.addWidget(self.strudel_container)
        self.body_stack.setCurrentWidget(self.scroll_area)

        self.body_layout.addStretch()

        self.update_host_controls()

        self.statusBar().showMessage(self.default_status_message)
        self.apply_theme(self.theme_key, update_combo=False)

        QTimer.singleShot(150, self.scan_plugins)

    def build_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(10)

        title = QLabel("Noisetown Ultimate")
        title.setObjectName("ToolbarTitle")
        layout.addWidget(title)

        self.start_audio_btn = QPushButton("Start Audio")
        self.start_audio_btn.clicked.connect(self.on_start_audio_clicked)
        self.start_audio_btn.setEnabled(self.audio_engine is not None)
        layout.addWidget(self.start_audio_btn)

        self.add_block_btn = QPushButton("Add Block")
        self.add_block_btn.clicked.connect(self.on_add_block_clicked)
        self.add_block_btn.setEnabled(self.audio_engine is not None)
        layout.addWidget(self.add_block_btn)

        self.edit_mode_btn = QPushButton("Edit: OFF")
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.toggled.connect(self.on_edit_mode_toggled)
        layout.addWidget(self.edit_mode_btn)

        self.style_mode_btn = QPushButton("Style Mode: OFF")
        self.style_mode_btn.setCheckable(True)
        self.style_mode_btn.toggled.connect(self.on_style_mode_toggled)
        layout.addWidget(self.style_mode_btn)


        self.strudel_mode_btn = QPushButton("Strudel Mode: OFF")
        self.strudel_mode_btn.setCheckable(True)
        if not STRUDEL_ENABLED:
            self.strudel_mode_btn.setEnabled(False)
            self.strudel_mode_btn.setText("Strudel Mode (Disabled)")
            self.strudel_mode_btn.setToolTip(
                "Strudel integration is temporarily disabled due to crashes. Please open https://strudel.cc/ in your browser."
            )
        elif not self.strudel_available:
            self.strudel_mode_btn.setToolTip(
                "Install the 'PyQtWebEngine' package to enable the embedded Strudel playground."
            )
        self.strudel_mode_btn.toggled.connect(self.on_strudel_mode_toggled)
        layout.addWidget(self.strudel_mode_btn)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("ThemePicker")
        self.theme_combo.blockSignals(True)
        self.theme_combo.addItem("Flat (Default)", "flat")
        self.theme_combo.addItem("Windows 98", "win98")
        self.theme_combo.addItem("Windows XP", "winxp")
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        default_index = self.theme_combo.findData(self.theme_key)
        if default_index >= 0:
            self.theme_combo.setCurrentIndex(default_index)
        self.theme_combo.blockSignals(False)
        layout.addWidget(self.theme_combo)

        layout.addStretch()

        self.save_session_btn = QPushButton("Save")
        self.save_session_btn.clicked.connect(
            lambda: self.append_log("Session saving is not wired yet in offline mode.")
        )
        layout.addWidget(self.save_session_btn)

        self.save_preset_btn = QPushButton("Save Preset+Audio")
        self.save_preset_btn.clicked.connect(
            lambda: self.append_log("Preset capture is not yet implemented for the desktop app.")
        )
        layout.addWidget(self.save_preset_btn)

        self.load_session_btn = QPushButton("Load")
        self.load_session_btn.clicked.connect(
            lambda: self.append_log("Session loading is coming soon for the desktop app.")
        )
        layout.addWidget(self.load_session_btn)

        self.load_preset_btn = QPushButton("Load Preset")
        self.load_preset_btn.clicked.connect(
            lambda: self.append_log("Preset loading is not yet implemented offline.")
        )
        layout.addWidget(self.load_preset_btn)

        return toolbar

    def _ensure_strudel_view(self) -> bool:
        if self.strudel_view is not None:
            return True
        ensure_webengine()
        if QWebEngineView is None:
            self.logger.error("Qt WebEngine is unavailable; cannot create Strudel view.")
            return False
        try:
            view = QWebEngineView()
            view.setParent(self.strudel_container)
            if StrudelWebPage is not None:
                self._strudel_page = StrudelWebPage(view, self._strudel_base_url)
                view.setPage(self._strudel_page)
            else:
                self._strudel_page = None
            view.setObjectName("StrudelView")
            view.setContextMenuPolicy(Qt.NoContextMenu)
            if QWebEngineSettings is not None:
                try:
                    settings = view.settings()
                    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
                    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                    settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                    settings.setAttribute(QWebEngineSettings.WebGLEnabled, False)
                    if hasattr(QWebEngineSettings, "Accelerated2dCanvasEnabled"):
                        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, False)
                    settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
                    settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
                    settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
                except Exception as exc:
                    self.logger.warning(f"Failed to configure WebEngine settings: {exc}")
            self._strudel_layout.addWidget(view)
            self.strudel_view = view
            return True
        except Exception as exc:
            self.logger.error(f"Failed to create Strudel WebEngineView: {exc}")
            self.append_log(f"Strudel view creation failed: {exc}")
            self.strudel_available = False
            return False

    def ensure_strudel_loaded(self) -> None:
        if not self.strudel_available:
            return
        if self.strudel_loaded:
            return
        if not self._ensure_strudel_view():
            return
        if not self._strudel_signals_connected:
            try:
                self.strudel_view.loadStarted.connect(self.on_strudel_load_started)  # type: ignore[attr-defined]
                self.strudel_view.loadProgress.connect(self.on_strudel_load_progress)  # type: ignore[attr-defined]
                self.strudel_view.loadFinished.connect(self.on_strudel_load_finished)  # type: ignore[attr-defined]
            except Exception:
                pass
            else:
                self._strudel_signals_connected = True
        target_url, module_hint, using_local = self._determine_strudel_target()
        self._strudel_module_hint = module_hint
        self._strudel_using_local = using_local
        if using_local and self._strudel_static_server and self._strudel_static_server.base_url:
            self._strudel_base_url = QUrl(self._strudel_static_server.base_url + "/")
        else:
            self._strudel_base_url = QUrl(target_url) if target_url is not None else None
        if self._strudel_page is not None:
            self._strudel_page._base_url = self._strudel_base_url
        message = (
            "Strudel Mode active  loading local playground"
            if using_local
            else "Strudel Mode active  loading web playground"
        )
        try:
            self.logger.info(f"Loading Strudel from URL: {target_url.toString()}")
            self.statusBar().showMessage(message)
            # Delay the actual URL load slightly to ensure Qt is fully initialized
            QTimer.singleShot(100, lambda: self._delayed_strudel_load(target_url))
        except Exception as exc:
            self.logger.error(f"Failed to initiate Strudel load: {exc}", exc_info=True)
            self.append_log(f"Failed to load Strudel playground: {exc}")
            return

    def _delayed_strudel_load(self, url: QUrl) -> None:
        """Load Strudel with a slight delay to ensure Qt is ready."""
        try:
            if self.strudel_view:
                self.logger.info("Setting Strudel URL...")
                self.strudel_view.setUrl(url)
                if DEBUG_ENABLE_STRUDEL_BRIDGE:
                    self._ensure_strudel_channel()
                else:
                    self.logger.debug("Strudel bridge connection skipped (disabled for testing)")
                self.strudel_loaded = True
                self.logger.info("Strudel load initiated successfully")
        except Exception as exc:
            self.logger.error(f"Failed in delayed Strudel load: {exc}", exc_info=True)
            self.append_log(f"Failed to load Strudel: {exc}")

    def _ensure_strudel_server(self, dist_dir: Path) -> Optional[str]:
        if self._strudel_static_server and self._strudel_static_server.base_url:
            if self._strudel_static_server.root == dist_dir:
                return self._strudel_static_server.base_url
            self._strudel_static_server.stop()
            self._strudel_static_server = None

        server = StrudelStaticServer(dist_dir)
        try:
            server.start()
        except Exception as exc:
            self.logger.warning("Failed to start Strudel asset server: %s", exc)
            return None
        self._strudel_static_server = server
        return server.base_url

    def _teardown_strudel_server(self) -> None:
        if self._strudel_static_server is None:
            return
        try:
            self._strudel_static_server.stop()
        except Exception:
            pass
        finally:
            self._strudel_static_server = None

    def _determine_strudel_target(self) -> Tuple[QUrl, Optional[str], bool]:
        if STRUDEL_FORCE_REMOTE:
            self._teardown_strudel_server()
            self._strudel_local_index = None
            return QUrl(STRUDEL_REMOTE_URL), None, False
        base_dir = Path(__file__).resolve().parent / "resources" / "strudel" / "dist"
        index_path = base_dir / "index.html"
        if index_path.exists():
            self._strudel_local_index = index_path
            server_url = self._ensure_strudel_server(base_dir)
            if server_url:
                # Build full HTTP URL for module hint
                module_hint_path = self._discover_strudel_module(base_dir)
                module_hint = f"{server_url}/{module_hint_path}" if module_hint_path else None
                self.logger.info(f"Strudel server started at {server_url}, module hint: {module_hint}")
                return QUrl(f"{server_url}/index.html"), module_hint, True
            self.logger.warning("Local Strudel bundle present but static server failed; falling back to remote site.")
        else:
            self._teardown_strudel_server()
        self._strudel_local_index = None
        return QUrl(STRUDEL_REMOTE_URL), None, False

    def _discover_strudel_module(self, dist_dir: Path) -> Optional[str]:
        astro_dir = dist_dir / "_astro"
        if not astro_dir.exists():
            return None
        for candidate in sorted(astro_dir.glob("index*.js")):
            # Use forward slashes for URLs (not OS-specific path separators)
            return f"_astro/{candidate.name}"
        return None

    def _ensure_strudel_channel(self) -> None:
        if not self.strudel_view or QWebChannel is None:
            return
        page = self.strudel_view.page()
        if not page:
            return
        if self._strudel_channel is None:
            self._strudel_channel = QWebChannel(page)
            try:
                self._strudel_channel.registerObject("qt_pattern_bridge", self.strudel_bridge)
            except Exception as exc:
                self.logger.debug("Failed to register Strudel bridge: %s", exc)
        try:
            page.setWebChannel(self._strudel_channel)
        except Exception as exc:
            self.logger.debug("Unable to attach web channel: %s", exc)

    def on_strudel_load_started(self) -> None:
        try:
            if self._strudel_using_local:
                self.statusBar().showMessage("Strudel Mode  preparing local playground")
            else:
                self.statusBar().showMessage("Strudel Mode  contacting playground")
        except Exception:
            pass

    def on_strudel_load_progress(self, progress: int) -> None:
        try:
            self.statusBar().showMessage(f"Strudel Mode loading {progress}%")
        except Exception:
            pass

    def on_strudel_load_finished(self, ok: bool) -> None:
        if ok:
            try:
                self.statusBar().showMessage("Strudel Mode active  ready to jam.")
                self.logger.info("Strudel page loaded successfully")
            except Exception:
                pass
            if DEBUG_ENABLE_STRUDEL_BRIDGE:
                try:
                    self._ensure_strudel_channel()
                    self._inject_strudel_bridge()
                    self.logger.info("Strudel load completed (bridge active)")
                except Exception as exc:
                    self.logger.error(f"Failed to inject Strudel bridge: {exc}", exc_info=True)
            else:
                self.logger.info("Strudel load completed (bridge disabled for testing)")
            return

        page = getattr(self, "_strudel_page", None)
        if page is not None and getattr(page, "_skip_next_failure", False):
            page._skip_next_failure = False
            return

        current_url = self.strudel_view.url() if self.strudel_view else None
        if current_url is not None:
            try:
                if current_url.path().startswith('/learn'):
                    if self._strudel_base_url is not None and self.strudel_view is not None:
                        self.strudel_view.setUrl(self._strudel_base_url)
                    return
            except Exception:
                pass

        self.strudel_loaded = False
        self.append_log("Strudel playground failed to load. Check your internet connection or firewall settings.")
        try:
            self.statusBar().showMessage("Strudel Mode unavailable  check your internet connection.")
        except Exception:
            pass
        if self.strudel_view:
            bg = self.colors.get('bg', '#111')
            text = self.colors.get('text', '#f0f0f0')
            accent = self.colors.get('accent', '#59a7ff')
            html = f"""
            <html><body style='background:{bg};color:{text};font-family:"Segoe UI",sans-serif;display:flex;align-items:center;justify-content:center;height:100%;text-align:center;padding:32px;'>
                <div>
                    <h2 style='margin-bottom:12px;'>Unable to reach the Strudel playground</h2>
                    <p>Check your internet connection or firewall, then toggle Strudel Mode again.</p>
                    <p style='margin-top:16px;color:{accent};'>https://strudel.tidalcycles.org/</p>
                </div>
            </body></html>
            """
            try:
                self.strudel_view.setHtml(html)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _build_strudel_bridge_script(self) -> str:
        module_hint_js = json.dumps(self._strudel_module_hint)
        script = rf"""
            (function() {{
                if (window.__ambianceStrudelBridgeInstalled) {{
                    return;
                }}
                window.__ambianceStrudelBridgeInstalled = true;
                const moduleHint = {module_hint_js};
                function log(message) {{
                    console.info('[AmbianceBridge]', message);
                }}
                function locateModulePath() {{
                    const candidates = [];
                    document.querySelectorAll('script[type="module"]').forEach((el) => {{
                        if (el.src && el.src.includes('_astro/') && el.src.includes('index')) {{
                            candidates.push(el.src);
                        }}
                    }});
                    document.querySelectorAll('link[rel="modulepreload"]').forEach((el) => {{
                        if (el.href && el.href.includes('_astro/') && el.href.includes('index')) {{
                            candidates.push(el.href);
                        }}
                    }});
                    if (moduleHint) {{
                        if (moduleHint.startsWith('http')) {{
                            return moduleHint;
                        }}
                        try {{
                            return new URL(moduleHint, window.location.href).toString();
                        }} catch (err) {{
                            console.warn('[AmbianceBridge] Failed to resolve module hint', moduleHint, err);
                        }}
                    }}
                    if (candidates.length > 0) {{
                        try {{
                            return new URL(candidates[0], window.location.href).toString();
                        }} catch (err) {{
                            console.warn('[AmbianceBridge] Unable to normalise candidate module path', candidates[0], err);
                            return candidates[0];
                        }}
                    }}
                    return null;
                }}
                function ensureChannel(callback) {{
                    const start = () => {{
                        if (window.qt && window.qt.webChannelTransport) {{
                            const onReady = () => {{
                                new QWebChannel(window.qt.webChannelTransport, function(channel) {{
                                    window.ambianceQtBridge = channel.objects.qt_pattern_bridge;
                                    callback();
                                }});
                            }};
                            if (typeof QWebChannel === 'undefined') {{
                                const script = document.createElement('script');
                                script.src = 'qrc:///qtwebchannel/qwebchannel.js';
                                script.onload = () => onReady();
                                script.onerror = () => console.error('[AmbianceBridge] Unable to load qwebchannel.js');
                                document.head.appendChild(script);
                            }} else {{
                                onReady();
                            }}
                            return;
                        }}
                        setTimeout(start, 100);
                    }};
                    start();
                }}
                function sendToQt(payload) {{
                    try {{
                        if (window.ambianceQtBridge && window.ambianceQtBridge.receivePattern) {{
                            window.ambianceQtBridge.receivePattern(JSON.stringify(payload));
                        }}
                    }} catch (err) {{
                        console.error('[AmbianceBridge] Forward error', err, payload);
                    }}
                }}
                function serialiseHap(hap) {{
                    if (!hap) {{
                        return null;
                    }}
                    const safe = {{
                        value: hap.value ?? null,
                        context: hap.context ?? null,
                        whole: hap.whole ?? null
                    }};
                    try {{
                        if (hap.duration && typeof hap.duration.valueOf === 'function') {{
                            safe.duration = hap.duration.valueOf();
                        }} else if (typeof hap.duration !== 'undefined') {{
                            safe.duration = hap.duration;
                        }}
                    }} catch (err) {{
                        safe.duration = null;
                    }}
                    return safe;
                }}
                function installHooksOnRepl(repl) {{
                    if (!repl || repl.__ambianceHooked) {{
                        return;
                    }}
                    const originalSetPattern = repl.setPattern;
                    if (typeof originalSetPattern === 'function') {{
                        repl.setPattern = async function(pat, autostart) {{
                            let patched = pat;
                            if (patched && typeof patched.onTrigger === 'function' && !patched.__ambianceForwarded) {{
                                try {{
                                    patched = patched.onTrigger((hap, currentTime, cps, targetTime) => {{
                                        sendToQt({{
                                            kind: 'pattern-trigger',
                                            hap: serialiseHap(hap),
                                            currentTime,
                                            cps,
                                            targetTime,
                                            receivedAt: Date.now()
                                        }});
                                    }}, false);
                                    patched.__ambianceForwarded = true;
                                }} catch (err) {{
                                    console.error('[AmbianceBridge] Failed to wrap pattern', err);
                                }}
                            }}
                            return originalSetPattern.call(this, patched, autostart);
                        }};
                    }}
                    if (typeof repl.evaluate === 'function' && !repl.evaluate.__ambianceWrapped) {{
                        const originalEval = repl.evaluate;
                        repl.evaluate = async function(code, autoplay = true) {{
                            return originalEval.call(this, code, autoplay);
                        }};
                        repl.evaluate.__ambianceWrapped = true;
                    }}
                    repl.__ambianceHooked = true;
                    log('Bridge attached to Strudel repl');
                }}
                function scanForRepl() {{
                    const visited = new Set();
                    const attempt = () => {{
                        let found = false;
                        for (const key of Object.getOwnPropertyNames(window)) {{
                            if (visited.has(key)) {{
                                continue;
                            }}
                            visited.add(key);
                            try {{
                                const candidate = window[key];
                                if (candidate && typeof candidate === 'object' && typeof candidate.setPattern === 'function' && typeof candidate.evaluate === 'function') {{
                                    installHooksOnRepl(candidate);
                                    found = true;
                                }}
                            }} catch (err) {{}}
                        }}
                        if (!found) {{
                            setTimeout(attempt, 1000);
                        }}
                    }};
                    attempt();
                }}
                function bootstrapModule() {{
                    const modulePath = locateModulePath();
                    if (!modulePath) {{
                        console.warn('[AmbianceBridge] Module path unresolved, relying on runtime detection');
                        scanForRepl();
                        return;
                    }}
                    import(modulePath).then((mod) => {{
                        if (mod && mod.W && typeof mod.W === 'function' && !mod.W.__ambianceWrapped) {{
                            const originalFactory = mod.W;
                            mod.W = function(options) {{
                                const repl = originalFactory.apply(this, arguments);
                                installHooksOnRepl(repl);
                                return repl;
                            }};
                            mod.W.__ambianceWrapped = true;
                            log('Repl factory patched');
                        }}
                        scanForRepl();
                    }}).catch((err) => {{
                        console.error('[AmbianceBridge] Failed to import Strudel module', err);
                        scanForRepl();
                    }});
                }}
                ensureChannel(() => {{
                    bootstrapModule();
                }});
            }})();
        """
        return dedent(script)

    def _inject_strudel_bridge(self) -> None:
        if not self.strudel_view or QWebChannel is None:
            return
        page = self.strudel_view.page()
        if not page:
            return
        script = self._build_strudel_bridge_script()
        try:
            page.runJavaScript(script)
        except Exception as exc:
            self.logger.warning("Failed to inject Strudel bridge: %s", exc)

    def on_strudel_pattern(self, payload: Dict[str, Any]) -> None:
        self._strudel_event_queue.append(payload)
        if self.audio_engine is not None:
            try:
                self.audio_engine.ensure_running()
            except Exception as exc:
                self.logger.debug("Audio engine ensure_running failed: %s", exc)
        kind = payload.get("kind", "event")
        hap = payload.get("hap")
        try:
            hap_text = json.dumps(hap) if isinstance(hap, dict) else str(hap)
        except Exception:
            hap_text = str(hap)
        self.append_log(f"Strudel {kind}: {hap_text}")


    def on_strudel_mode_toggled(self, checked: bool) -> None:
        self.logger.info(f"Strudel mode toggled: {'ON' if checked else 'OFF'}")

        if not self.strudel_mode_btn:
            self.logger.warning("Strudel mode button not available")
            return
        if STRUDEL_ENABLED:
            self.strudel_mode_btn.setText("Strudel Mode: ON" if checked else "Strudel Mode: OFF")

        self.apply_theme(self.theme_key, update_combo=False)

        if not self.strudel_available:
            if not STRUDEL_ENABLED:
                self.logger.info("Strudel integration disabled; forwarding user to browser")
                if checked:
                    QMessageBox.information(
                        self,
                        "Strudel Mode Disabled",
                        "The embedded Strudel playground has been turned off in this build because it was unstable.\n\n"
                        "Please open https://strudel.cc/ in your browser to keep jamming.",
                    )
                if self.strudel_mode_btn.isCheckable():
                    self.strudel_mode_btn.blockSignals(True)
                    self.strudel_mode_btn.setChecked(False)
                    self.strudel_mode_btn.blockSignals(False)
                self._set_keyboard_suspended(False)
                return

            self.logger.warning("Strudel mode not available (PyQtWebEngine not installed)")
            if checked:
                QMessageBox.warning(
                    self,
                    "Strudel Mode",
                    "PyQtWebEngine is not installed. Install 'PyQtWebEngine' to enable the Strudel playground."
                )
                self.strudel_mode_btn.blockSignals(True)
                self.strudel_mode_btn.setChecked(False)
                self.strudel_mode_btn.blockSignals(False)
            self._set_keyboard_suspended(False)
            return

        if not self.body_stack or not self.strudel_container:
            self.logger.warning("Strudel UI containers not available")
            return

        if checked:
            self.logger.info("Activating Strudel mode - loading playground...")
            try:
                self.ensure_strudel_loaded()
                self.logger.info("Switching to Strudel container")
                self.body_stack.setCurrentWidget(self.strudel_container)
                if self.strudel_loaded:
                    self.statusBar().showMessage("Strudel Mode active  jam inside the embedded playground.")
                    self.logger.info("Strudel mode activated successfully")
            except Exception as exc:
                self.logger.error(f"Failed to activate Strudel mode: {exc}", exc_info=True)
                self.append_log(f"Error activating Strudel mode: {exc}")
        else:
            self.logger.info("Deactivating Strudel mode")
            self.body_stack.setCurrentWidget(self.scroll_area)
            self.statusBar().showMessage(self.default_status_message)

        self._set_keyboard_suspended(self.strudel_mode_btn.isChecked())

    def on_start_audio_clicked(self) -> None:
        if not self.audio_engine:
            QMessageBox.warning(self, "Audio Engine", "Audio engine is unavailable. Install required dependencies (pyo).")
            return
        try:
            self.audio_engine.ensure_running()
            self.append_log("Audio engine running.")
        except Exception as exc:
            QMessageBox.critical(self, "Audio Engine", f"Failed to start audio engine:\n{exc}")

    def on_add_block_clicked(self) -> None:
        if not self.audio_engine or not self.blocks_panel:
            QMessageBox.warning(self, "Blocks", "Audio engine is unavailable, cannot add blocks.")
            return
        self.blocks_panel.create_block()

    def on_theme_changed(self, index: int) -> None:
        """Handle theme combo box change."""
        if not hasattr(self, "theme_combo"):
            return
        key = self.theme_combo.itemData(index)
        if not key:
            key_text = self.theme_combo.itemText(index).strip().lower()
            key = key_text.replace(" ", "")
        key = str(key)
        if key not in THEME_PRESETS:
            key = "flat"
        self.apply_theme(key, update_combo=False, log_change=True)
        self.statusBar().showMessage(f"Theme set to {self.theme_combo.currentText()}")

    def on_plugin_focus_changed(self) -> None:
        """Update status label when plugin selection changes."""
        if not getattr(self, "plugin_list", None):
            return
        items = self.plugin_list.selectedItems()
        if not items:
            if hasattr(self, "selected_plugin_label"):
                self.selected_plugin_label.setText("Select a plugin to assign it to a lane.")
            return
        item = items[0]
        name = item.text()
        path = item.data(Qt.UserRole)
        suffix = ""
        if path:
            try:
                suffix = Path(path).suffix.upper()
            except Exception:
                suffix = ""
        label = f"Selected: {name}"
        if suffix:
            label += f"  {suffix}"
        if hasattr(self, "selected_plugin_label"):
            self.selected_plugin_label.setText(label)

    def on_chain_slot_selected(self, slot_index: int) -> None:
        """React to plugin chain slot selections."""
        slot = None
        if getattr(self, "chain_widget", None) and 0 <= slot_index < len(self.chain_widget.slots):
            slot = self.chain_widget.slots[slot_index]
        self.refresh_selected_plugin_label()
        self.refresh_host_status(slot)
        self.update_host_controls()

    def on_chain_slot_updated(self, slot_index: int) -> None:
        """Refresh host panel when a slot changes."""
        slot = None
        if getattr(self, "chain_widget", None) and 0 <= slot_index < len(self.chain_widget.slots):
            slot = self.chain_widget.slots[slot_index]
        self.refresh_host_status(slot)
        self.update_host_controls()

    def refresh_selected_plugin_label(self) -> None:
        """Show the currently selected slot info."""
        if not hasattr(self, "selected_plugin_label") or not getattr(self, "chain_widget", None):
            return
        index = getattr(self.chain_widget, "selected_slot_index", -1)
        if index is None or index < 0 or index >= len(self.chain_widget.slots):
            self.selected_plugin_label.setText("Select a plugin to assign it to a lane.")
            return
        slot = self.chain_widget.slots[index]
        if slot.plugin_path:
            name = slot.plugin_path.stem
            suffix = slot.plugin_path.suffix.upper()
            status = " [Bypassed]" if not slot.enabled else ""
            self.selected_plugin_label.setText(f"Slot {slot.index + 1}: {name} {suffix}{status}")
        else:
            self.selected_plugin_label.setText(f"Slot {slot.index + 1}: [Empty]")

    def update_host_controls(self) -> None:
        """Enable/disable host controls based on current slot state."""
        slot = None
        if getattr(self, "chain_widget", None) and self.chain_widget.selected_slot_index >= 0:
            try:
                slot = self.chain_widget.slots[self.chain_widget.selected_slot_index]
            except (IndexError, AttributeError):
                slot = None
        has_host = bool(slot and slot.host)
        supports_midi = bool(slot and slot.supports_midi)

        for btn_name in ("host_ui_btn", "instrument_open_ui_btn", "instrument_preview_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(has_host)
        if hasattr(self, "instrument_panel") and self.instrument_panel is not None:
            self.instrument_panel.setEnabled(has_host and supports_midi)
        if hasattr(self, "rack_status_label") and slot:
            name = slot.plugin_path.stem if slot.plugin_path else "Empty"
            self.rack_status_label.setText(f"Slot {slot.index + 1}: {name}")
        elif hasattr(self, "rack_status_label"):
            self.rack_status_label.setText("No slot selected")

    def append_log(self, message: str) -> None:
        """Prepend a log entry to the rack output panel."""
        if not hasattr(self, "rack_output") or self.rack_output is None:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        existing = self.rack_output.toPlainText()
        if existing:
            self.rack_output.setPlainText(entry + "\n" + existing)
        else:
            self.rack_output.setPlainText(entry)
        bar = self.rack_output.verticalScrollBar()
        if bar:
            bar.setValue(bar.minimum())

    def copy_workspace_path(self) -> None:
        """Copy the plugin workspace path to the clipboard."""
        path = getattr(self, "last_workspace_path", "")
        clipboard = QApplication.clipboard()
        if clipboard is not None and path:
            clipboard.setText(path)
            self.append_log(f"Copied workspace path: {path}")
        else:
            self.append_log("Workspace path unavailable.")

    def scan_plugins(self) -> None:
        """Scan plugin directories and populate the library list."""
        if not hasattr(self, "plugin_list") or self.plugin_list is None:
            return

        self.plugin_list.clear()
        base_dir = Path(__file__).parent
        workspace_candidates = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
        ]
        workspace_dir = next((p for p in workspace_candidates if p.exists()), None)
        self.last_workspace_path = str(workspace_dir or "")
        if hasattr(self, "workspace_path_label"):
            self.workspace_path_label.setText(self.last_workspace_path or "Workspace not found")

        plugin_dirs = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
            Path("C:/Program Files/VSTPlugins"),
            Path("C:/Program Files/Steinberg/VSTPlugins"),
            Path("C:/Program Files/Common Files/VST3"),
            Path("C:/Program Files (x86)/VSTPlugins"),
            Path("C:/Program Files (x86)/Steinberg/VSTPlugins"),
        ]
        available_dirs: List[Path] = [p for p in plugin_dirs if p.exists()]
        missing_dirs: List[Path] = [p for p in plugin_dirs if not p.exists() and "Program Files" not in str(p)]

        plugins: List[Path] = []
        for plugin_dir in available_dirs:
            for pattern in ("**/*.dll", "**/*.vst3", "**/*.vst"):
                plugins.extend(plugin_dir.glob(pattern))

        seen: Dict[str, Path] = {}
        for plugin_path in sorted(set(plugins)):
            key = plugin_path.name.lower()
            if key in seen:
                continue
            seen[key] = plugin_path
            item = QListWidgetItem(plugin_path.stem)
            item.setData(Qt.UserRole, str(plugin_path))
            item.setToolTip(str(plugin_path))
            self.plugin_list.addItem(item)

        notes: List[str] = []
        if not available_dirs:
            notes.append("No plugin directories were found. Drop VST files into the Ambiance 'included_plugins' folder.")
        elif missing_dirs:
            notes.append("Some optional plugin folders were not found and will be skipped.")
        if hasattr(self, "workspace_notes"):
            self.workspace_notes.setText("\n".join(notes))

        plugin_count = len(seen)
        dir_count = len(available_dirs)
        self.statusBar().showMessage(f"Found {plugin_count} plugins across {dir_count} folders")
        if hasattr(self, "rack_status_label"):
            self.rack_status_label.setText(f"Library: {plugin_count} plugins")

        if plugin_count == 0:
            self.append_log("No plugins discovered. Add VST/VST3 files to your workspace directory.")
        else:
            self.append_log(f"Library refreshed - {plugin_count} plugins ready.")

        self.refresh_selected_plugin_label()
        self.update_host_controls()

    def get_selected_slot(self) -> Optional[PluginChainSlot]:
        if getattr(self, "chain_widget", None) is None:
            return None
        index = getattr(self.chain_widget, "selected_slot_index", -1)
        if index is None or index < 0 or index >= len(self.chain_widget.slots):
            return None
        return self.chain_widget.slots[index]

    def load_plugin_to_chain(self) -> None:
        slot = self.get_selected_slot()
        if slot is None:
            QMessageBox.information(self, "No Slot", "Select a lane in the rack before loading a plugin.")
            return
        items = self.plugin_list.selectedItems() if hasattr(self, "plugin_list") else []
        if not items:
            QMessageBox.information(self, "No Plugin", "Select a plugin from the library first.")
            return

        plugin_path = Path(items[0].data(Qt.UserRole))
        slot.supports_midi = False

        try:
            if slot.host:
                with slot.lock:
                    slot.host.unload()
                    slot.host.shutdown()

            slot.host = CarlaVSTHost(client_name=f"AmbianceSlot{slot.index}")
            if self.chain_widget.host_window_id is not None:
                slot.host.register_host_window(self.chain_widget.host_window_id)

            slot.host.configure_audio(preferred_drivers=["DirectSound", "ASIO", "WASAPI", "Dummy", "JACK"])
            slot.host.load_plugin(plugin_path, show_ui=False)
            slot.plugin_path = plugin_path
            slot.ui_visible = False

            status: Dict[str, Any] = {}
            try:
                status = slot.host.status()
            except Exception:
                status = {}

            driver_name = status.get("driver", "unknown")
            self.logger.info(f"Slot {slot.index} using audio driver: {driver_name}")

            slot.supports_midi, _ = self._extract_plugin_capabilities(status)
            self.chain_widget.update_slot_display(slot.index)
            self.chain_widget.update_controls()

            self.update_parameters_for_slot(slot)
            self.refresh_host_status(slot)
            self.update_host_controls()
            self.refresh_selected_plugin_label()

            if len(self.chain_widget.get_active_slots()) == 1:
                self.poll_timer.start(100)

            self.statusBar().showMessage(f"Loaded {plugin_path.stem} into slot {slot.index + 1}")
            self.append_log(f"Loaded '{plugin_path.stem}' into slot {slot.index + 1}.")

        except Exception as exc:
            slot.supports_midi = False
            QMessageBox.critical(self, "Load Error", f"Failed to load plugin:\n{exc}")
            self.logger.error(f"Plugin load error: {exc}", exc_info=True)
            self.append_log(f"Failed to load plugin: {exc}")

    def unload_selected_slot(self) -> None:
        slot = self.get_selected_slot()
        if slot is None:
            QMessageBox.information(self, "No Slot", "Select a lane from the rack first.")
            return
        self.chain_widget.unload_plugin_from_slot()
        self.param_refresh_attempts.pop(slot.index, None)
        self.append_log(f"Unloaded slot {slot.index + 1}.")
        self.refresh_host_status(self.get_selected_slot())
        self.update_host_controls()

    def toggle_slot_ui_from_host(self) -> None:
        slot = self.get_selected_slot()
        if not slot or not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into the selected slot first.")
            return
        self.chain_widget.toggle_slot_ui()

    def preview_plugin(self) -> None:
        slot = self.get_selected_slot()
        if not slot or not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into the selected slot first.")
            return
        self.append_log("Preview playback is not implemented for the Carla backend yet.")

    def adjust_instrument_octave(self, delta: int) -> None:
        self.instrument_octave = max(0, min(8, self.instrument_octave + delta))
        self.update_instrument_octave_label()
        if hasattr(self, "piano") and self.piano is not None:
            self.piano.start_note = 12 * (self.instrument_octave + 1)
            self.piano.update()

    def update_instrument_octave_label(self) -> None:
        if hasattr(self, "instrument_octave_label"):
            self.instrument_octave_label.setText(f"Octave {self.instrument_octave}")

    def on_instrument_velocity_changed(self, value: int) -> None:
        self.instrument_velocity = max(0.2, min(1.2, value / 100.0))

    def on_plugin_selected(self, item: QListWidgetItem) -> None:
        """Double-click handler from the plugin library."""
        if item is None:
            return
        self.load_plugin_to_chain()

    def on_note_on(self, note: int) -> None:
        """Send note-on to all active MIDI-capable slots."""
        active_slots = []
        if getattr(self, "chain_widget", None):
            active_slots = [s for s in self.chain_widget.get_active_slots() if s.supports_midi]
        if not active_slots:
            self.play_fallback_tone(note, self.instrument_velocity)
            return
        velocity = self.instrument_velocity
        for slot in active_slots:
            host = slot.host
            if host is None:
                continue
            self._submit_midi_job(self._perform_note_on, host, note, velocity, slot.index)

    def on_note_off(self, note: int) -> None:
        """Send note-off to all active MIDI-capable slots."""
        if not getattr(self, "chain_widget", None):
            return
        for slot in [s for s in self.chain_widget.get_active_slots() if s.supports_midi]:
            host = slot.host
            if host is None:
                continue
            self._submit_midi_job(self._perform_note_off, host, note, slot.index)

    def build_plugin_block(self) -> QFrame:
        block = QFrame()
        block.setObjectName("PluginBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)

        rack_title = QLabel("Plugin Rack")
        rack_title.setObjectName("RackTitle")
        header.addWidget(rack_title)

        self.plugin_block_tagline = QLabel("Route native plugins directly alongside your Noisetown sessions.")
        self.plugin_block_tagline.setObjectName("RackTagline")
        header.addWidget(self.plugin_block_tagline, 1)

        self.rack_status_label = QLabel("Library pending")
        self.rack_status_label.setObjectName("RackStatus")
        header.addWidget(self.rack_status_label, 0, Qt.AlignRight)

        layout.addLayout(header)

        plugin_row = QHBoxLayout()
        plugin_row.setSpacing(18)

        self.workspace_panel = self.build_workspace_panel()
        plugin_row.addWidget(self.workspace_panel, 1)

        self.rack_panel = self.build_rack_panel()
        plugin_row.addWidget(self.rack_panel, 1)

        layout.addLayout(plugin_row)

        self.host_panel = self.build_host_panel()
        layout.addWidget(self.host_panel)

        self.instrument_panel = self.build_instrument_panel()
        layout.addWidget(self.instrument_panel)
        self.instrument_panel.setEnabled(False)




        self.log_panel = self.build_rack_log_panel()
        layout.addWidget(self.log_panel)

        return block

    def build_workspace_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("WorkspacePanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("Plugin Library")
        title.setObjectName("WorkspaceTitle")
        header.addWidget(title)

        self.scan_btn = QPushButton("Refresh")
        self.scan_btn.clicked.connect(self.scan_plugins)
        header.addWidget(self.scan_btn)
        layout.addLayout(header)

        self.workspace_hint = QLabel("Drop VST, VST3, Audio Unit, or mc.svt plugins into this folder.")
        self.workspace_hint.setWordWrap(True)
        self.workspace_hint.setObjectName("WorkspaceHint")
        layout.addWidget(self.workspace_hint)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        self.workspace_path_label = QLabel("Not available")
        self.workspace_path_label.setObjectName("WorkspacePath")
        path_row.addWidget(self.workspace_path_label, 1)

        self.copy_path_btn = QPushButton("Copy Path")
        self.copy_path_btn.clicked.connect(self.copy_workspace_path)
        path_row.addWidget(self.copy_path_btn)
        layout.addLayout(path_row)

        self.plugin_list = QListWidget()
        self.plugin_list.setObjectName("PluginList")
        self.plugin_list.itemSelectionChanged.connect(self.on_plugin_focus_changed)
        self.plugin_list.itemDoubleClicked.connect(self.on_plugin_selected)
        layout.addWidget(self.plugin_list, 1)

        self.workspace_notes = QLabel()
        self.workspace_notes.setObjectName("WorkspaceNotes")
        self.workspace_notes.setWordWrap(True)
        layout.addWidget(self.workspace_notes)

        return frame

    def build_rack_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("RackPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(6)

        title = QLabel("Streams & Lanes")
        title.setObjectName("RackStreamsTitle")
        header.addWidget(title)

        self.selected_plugin_label = QLabel("Select a plugin to assign it to a lane.")
        self.selected_plugin_label.setObjectName("SelectedPlugin")
        self.selected_plugin_label.setWordWrap(True)
        header.addWidget(self.selected_plugin_label)

        layout.addLayout(header)

        self.chain_widget = PluginChainWidget()
        self.chain_widget.load_btn.clicked.connect(self.load_plugin_to_chain)
        self.chain_widget.slot_selected.connect(self.on_chain_slot_selected)
        self.chain_widget.slot_updated.connect(self.on_chain_slot_updated)
        layout.addWidget(self.chain_widget)
        QTimer.singleShot(0, self._register_chain_window)

        self.rack_notes_label = QLabel()
        self.rack_notes_label.setObjectName("RackNotes")
        self.rack_notes_label.setWordWrap(True)
        self.rack_notes_label.setText("Tip: Add slots to build A/B processing lanes and stack effects.")
        layout.addWidget(self.rack_notes_label)

        return frame

    def build_host_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("HostPanel")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        host_title = QLabel("Live VST Host")
        host_title.setObjectName("HostTitle")
        titles.addWidget(host_title)
        host_subtitle = QLabel("Powered by the embedded Carla engine")
        host_subtitle.setObjectName("HostSubtitle")
        titles.addWidget(host_subtitle)
        header.addLayout(titles)

        header.addStretch()

        self.host_load_btn = QPushButton("Load Selected")
        self.host_load_btn.clicked.connect(self.load_plugin_to_chain)
        header.addWidget(self.host_load_btn)

        self.host_unload_btn = QPushButton("Unload")
        self.host_unload_btn.clicked.connect(self.unload_selected_slot)
        header.addWidget(self.host_unload_btn)

        self.host_ui_btn = QPushButton("Show Plugin UI")
        self.host_ui_btn.clicked.connect(self.toggle_slot_ui_from_host)
        header.addWidget(self.host_ui_btn)

        self.host_preview_btn = QPushButton("Preview")
        self.host_preview_btn.setEnabled(False)
        self.host_preview_btn.clicked.connect(self.preview_plugin)
        header.addWidget(self.host_preview_btn)
        self.host_preview_btn.hide()

        layout.addLayout(header)

        self.host_status_label = QLabel("Toolkit status pending...")
        self.host_status_label.setObjectName("HostStatus")
        self.host_status_label.setWordWrap(True)
        layout.addWidget(self.host_status_label)

        self.host_warnings_label = QLabel()
        self.host_warnings_label.setObjectName("HostWarnings")
        self.host_warnings_label.setWordWrap(True)
        layout.addWidget(self.host_warnings_label)

        dock_row = QHBoxLayout()
        dock_row.setSpacing(8)
        self.host_dock_check = QCheckBox("Dock plugin UI inside host panel")
        self.host_dock_check.setObjectName("HostDockToggle")
        self.host_dock_check.setChecked(False)
        dock_row.addWidget(self.host_dock_check)
        dock_row.addStretch()
        layout.addLayout(dock_row)

        self.host_editor_container = PluginEditorContainer()
        layout.addWidget(self.host_editor_container, 1)

        if hasattr(self, "chain_widget"):
            self.chain_widget.set_host_controls(self.host_dock_check, self.host_editor_container)
            self.host_dock_check.toggled.connect(self.chain_widget.on_host_dock_toggled)
        else:
            self.host_dock_check.toggled.connect(lambda _checked: None)

        return frame

    def build_instrument_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("InstrumentPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.instrument_title_label = QLabel("Digital Instrument")
        self.instrument_title_label.setObjectName("InstrumentTitle")
        titles.addWidget(self.instrument_title_label)
        self.instrument_subtitle_label = QLabel("Load an instrument plugin to unlock performance controls.")
        self.instrument_subtitle_label.setObjectName("InstrumentSubtitle")
        titles.addWidget(self.instrument_subtitle_label)
        header.addLayout(titles)

        header.addStretch()
        octave_box = QHBoxLayout()
        octave_box.setSpacing(6)
        self.instrument_octave_down = QPushButton("Oct -")
        self.instrument_octave_down.clicked.connect(lambda: self.adjust_instrument_octave(-1))
        octave_box.addWidget(self.instrument_octave_down)
        self.instrument_octave_label = QLabel(f"Octave {self.instrument_octave}")
        self.instrument_octave_label.setObjectName("InstrumentOctave")
        octave_box.addWidget(self.instrument_octave_label)
        self.instrument_octave_up = QPushButton("Oct +")
        self.instrument_octave_up.clicked.connect(lambda: self.adjust_instrument_octave(1))
        octave_box.addWidget(self.instrument_octave_up)
        header.addLayout(octave_box)

        layout.addLayout(header)

        self.instrument_status_label = QLabel("Load an instrument plugin to begin.")
        self.instrument_status_label.setObjectName("InstrumentStatus")
        self.instrument_status_label.setWordWrap(True)
        layout.addWidget(self.instrument_status_label)

        control_row = QHBoxLayout()
        control_row.setSpacing(12)
        self.note_names_check = QCheckBox("Show note names")
        self.note_names_check.setChecked(True)
        self.note_names_check.toggled.connect(self.toggle_note_names)
        control_row.addWidget(self.note_names_check)
        control_row.addStretch()
        layout.addLayout(control_row)

        self.piano = PianoKeyboard()
        self.piano.setObjectName("InstrumentKeyboard")
        self.piano.set_callbacks(self.on_note_on, self.on_note_off)
        # MIDI: C4 (middle C) = note 60 = 12 * (4 + 1)
        self.piano.start_note = 12 * (self.instrument_octave + 1)
        layout.addWidget(self.piano)
        self._apply_keyboard_enabled_state()

        footer = QHBoxLayout()
        footer.setSpacing(12)
        velocity_label = QLabel("Velocity")
        velocity_label.setObjectName("VelocityLabel")
        footer.addWidget(velocity_label)
        self.instrument_velocity_slider = QSlider(Qt.Horizontal)
        self.instrument_velocity_slider.setRange(20, 120)
        self.instrument_velocity_slider.setValue(int(self.instrument_velocity * 100))
        self.instrument_velocity_slider.valueChanged.connect(self.on_instrument_velocity_changed)
        footer.addWidget(self.instrument_velocity_slider, 1)
        self.instrument_open_ui_btn = QPushButton("Show UI")
        self.instrument_open_ui_btn.clicked.connect(self.toggle_slot_ui_from_host)
        footer.addWidget(self.instrument_open_ui_btn)
        self.instrument_preview_btn = QPushButton("Preview")
        self.instrument_preview_btn.clicked.connect(self.preview_plugin)
        footer.addWidget(self.instrument_preview_btn)
        self.instrument_preview_btn.hide()
        layout.addLayout(footer)

        self.param_tabs = QTabWidget()
        self.param_tabs.setObjectName("ParameterTabs")
        layout.addWidget(self.param_tabs)

        return frame

    def _register_chain_window(self) -> None:
        """Share the main window handle with the plugin chain widget."""

        if not getattr(self, "chain_widget", None):
            return
        window = self.windowHandle()
        if window is None:
            return
        try:
            self.chain_widget.register_host_window(int(window.winId()))
        except Exception:
            pass

    def build_rack_log_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("RackLogPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        title = QLabel("Rack Activity")
        title.setObjectName("RackLogTitle")
        layout.addWidget(title)

        self.rack_output = QPlainTextEdit()
        self.rack_output.setObjectName("RackOutput")
        self.rack_output.setReadOnly(True)
        layout.addWidget(self.rack_output)

        return frame

    def rgba(self, hex_color: str, alpha: float) -> str:
        value = hex_color.lstrip('#')
        if len(value) == 3:
            value = ''.join(ch * 2 for ch in value)
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"

    def _apply_theme_colors(self, key: str) -> None:
        preset = THEME_PRESETS.get(key, THEME_PRESETS['flat'])
        self.colors.update(preset["colors"])
        self.dark_mode = preset["dark"]
        self.setStyleSheet("")

    def apply_global_styles(self) -> None:
        """Apply theme-specific application-wide styling."""
        key = getattr(self, "theme_key", "flat")
        c = self.colors

        if key == "win98":
            palette = {
                "teal": "#008080",
                "surface": "#c3c7cb",
                "face": "#dfdfdf",
                "shadow": "#808080",
                "highlight": "#ffffff",
                "frame": "#0a0a0a",
                "blue": "#000080",
                "text": "#000000",
            }
            style_template = Template(
                dedent(
                    """
                    QMainWindow {
                        background-color: $teal;
                        color: $text;
                        font-family: 'MS Sans Serif','Microsoft Sans Serif','Pixelated MS Sans Serif',sans-serif;
                        font-size: 11px;
                    }
                    QWidget#CentralWidget,
                    QWidget#BodyWidget,
                    QWidget#StrudelContainer {
                        background-color: $surface;
                        color: $text;
                    }
                    QFrame#Toolbar,
                    QFrame#PluginBlock,
                    QFrame#WorkspacePanel,
                    QFrame#RackPanel,
                    QFrame#HostPanel,
                    QFrame#InstrumentPanel,
                    QFrame#RackLogPanel {
                        background-color: $surface;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-radius: 0px;
                        padding: 6px;
                    }
                    QLabel#RackTitle,
                    QLabel#WorkspaceTitle,
                    QLabel#HostTitle,
                    QLabel#InstrumentTitle {
                        color: $text;
                        font-weight: bold;
                    }
                    QLabel#RackStatus,
                    QLabel#WorkspaceHint,
                    QLabel#WorkspaceNotes,
                    QLabel#RackTagline,
                    QLabel#HostSubtitle,
                    QLabel#HostStatus,
                    QLabel#HostWarnings,
                    QLabel#InstrumentSubtitle,
                    QLabel#InstrumentStatus,
                    QLabel#VelocityLabel {
                        color: $text;
                    }
                    QPushButton,
                    QToolButton,
                    QComboBox,
                    QLineEdit,
                    QPlainTextEdit,
                    QTextEdit,
                    QSpinBox,
                    QDoubleSpinBox {
                        background-color: $face;
                        color: $text;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-radius: 0px;
                        padding: 2px 8px;
                    }
                    QPushButton,
                    QToolButton {
                        min-height: 22px;
                    }
                    QPushButton:pressed,
                    QToolButton:pressed {
                        border-top-color: $shadow;
                        border-left-color: $shadow;
                        border-bottom-color: $highlight;
                        border-right-color: $highlight;
                        padding-left: 9px;
                        padding-top: 3px;
                    }
                    QPushButton:focus,
                    QToolButton:focus,
                    QComboBox:focus,
                    QLineEdit:focus {
                        outline: 1px dotted $frame;
                        outline-offset: -3px;
                    }
                    QPushButton:disabled,
                    QToolButton:disabled {
                        color: #6e6e6e;
                        background-color: #dfdfdf;
                    }
                    QListWidget,
                    QTreeWidget,
                    QTableWidget {
                        background-color: $face;
                        color: $text;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-radius: 0px;
                    }
                    QListWidget::item:selected,
                    QTreeWidget::item:selected,
                    QTableWidget::item:selected {
                        background-color: $blue;
                        color: #ffffff;
                    }
                    QTabWidget::pane {
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-radius: 0px;
                        background-color: $surface;
                    }
                    QTabBar::tab {
                        background-color: $surface;
                        color: $text;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-bottom: none;
                        border-radius: 0px;
                        padding: 4px 10px;
                        margin-right: 2px;
                    }
                    QTabBar::tab:selected {
                        background-color: $face;
                    }
                    QPlainTextEdit#RackOutput {
                        background-color: #ffffff;
                        color: #000000;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                    }
                    QScrollBar:vertical,
                    QScrollBar:horizontal {
                        background: $surface;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-radius: 0px;
                        margin: 0px;
                    }
                    QScrollBar::handle:vertical,
                    QScrollBar::handle:horizontal {
                        background: $face;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        border-radius: 0px;
                        min-height: 20px;
                        min-width: 20px;
                    }
                    QScrollBar::add-line:vertical,
                    QScrollBar::sub-line:vertical,
                    QScrollBar::add-line:horizontal,
                    QScrollBar::sub-line:horizontal {
                        background: $face;
                        border: 2px solid $shadow;
                        border-top-color: $highlight;
                        border-left-color: $highlight;
                        width: 18px;
                        height: 18px;
                    }
                    """
                )
            )
            self.setStyleSheet(style_template.substitute(**palette))
            return

        if key == "winxp":
            palette = {
                "bg_top": "#4f7cd7",
                "bg_bottom": "#1b4aa5",
                "surface": "#ece9d8",
                "panel": "#f6f9ff",
                "card": "#ffffff",
                "border": "#7f9db9",
                "border_light": "#bcd0f1",
                "text": "#1a2848",
                "muted": "#3b4f78",
                "button_top": "#fefefe",
                "button_bottom": "#d7e4fb",
                "button_hover_top": "#ffffff",
                "button_hover_bottom": "#dfeaff",
                "button_pressed_top": "#cbdafe",
                "button_pressed_bottom": "#b7caf5",
                "selected": "#316ac5",
            }
            style_template = Template(
                dedent(
                    """
                    QMainWindow {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $bg_top, stop:1 $bg_bottom);
                        color: $text;
                        font-family: 'Tahoma','Segoe UI',sans-serif;
                        font-size: 12px;
                    }
                    QWidget#CentralWidget,
                    QWidget#BodyWidget,
                    QWidget#StrudelContainer {
                        background-color: $surface;
                        color: $text;
                    }
                    QFrame#Toolbar,
                    QFrame#PluginBlock,
                    QFrame#WorkspacePanel,
                    QFrame#RackPanel,
                    QFrame#HostPanel,
                    QFrame#InstrumentPanel,
                    QFrame#RackLogPanel {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fefefe, stop:1 #e1ecff);
                        border: 1px solid $border;
                        border-radius: 12px;
                        padding: 12px;
                        box-shadow: 0 1px 4px rgba(18,44,120,0.18);
                    }
                    QLabel#RackTitle,
                    QLabel#WorkspaceTitle,
                    QLabel#HostTitle,
                    QLabel#InstrumentTitle {
                        color: $text;
                        font-weight: bold;
                    }
                    QLabel#RackTagline,
                    QLabel#WorkspaceHint,
                    QLabel#WorkspaceNotes,
                    QLabel#HostSubtitle,
                    QLabel#HostStatus,
                    QLabel#HostWarnings,
                    QLabel#InstrumentSubtitle,
                    QLabel#InstrumentStatus,
                    QLabel#VelocityLabel {
                        color: $muted;
                    }
                    QPushButton,
                    QToolButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $button_top, stop:1 $button_bottom);
                        border: 1px solid $border;
                        border-radius: 6px;
                        padding: 6px 16px;
                        color: $text;
                        min-height: 24px;
                    }
                    QPushButton:hover,
                    QToolButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $button_hover_top, stop:1 $button_hover_bottom);
                    }
                    QPushButton:pressed,
                    QToolButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $button_pressed_top, stop:1 $button_pressed_bottom);
                        border-color: $border_light;
                    }
                    QPushButton:disabled,
                    QToolButton:disabled {
                        color: rgba(0,0,0,0.35);
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f0f2f7, stop:1 #dbe2f4);
                    }
                    QLineEdit,
                    QPlainTextEdit,
                    QTextEdit,
                    QSpinBox,
                    QDoubleSpinBox,
                    QComboBox {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #edf3ff);
                        border: 1px solid $border;
                        border-radius: 6px;
                        padding: 6px 8px;
                        color: $text;
                    }
                    QListWidget,
                    QTreeWidget,
                    QTableWidget {
                        background-color: #ffffff;
                        color: $text;
                        border: 1px solid $border;
                        border-radius: 8px;
                    }
                    QListWidget::item:selected,
                    QTreeWidget::item:selected,
                    QTableWidget::item:selected {
                        background: $selected;
                        color: #ffffff;
                    }
                    QTabWidget::pane {
                        border: 1px solid $border;
                        border-radius: 10px;
                        background: #ffffff;
                    }
                    QTabBar::tab {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f9fcff, stop:1 #dfe9ff);
                        border: 1px solid $border;
                        border-bottom: none;
                        border-top-left-radius: 8px;
                        border-top-right-radius: 8px;
                        padding: 6px 14px;
                        margin-right: 4px;
                        color: $text;
                    }
                    QTabBar::tab:selected {
                        background: #ffffff;
                    }
                    QPlainTextEdit#RackOutput {
                        background: #0f0f0f;
                        color: #00ffd0;
                        border: 1px solid $border;
                        border-radius: 8px;
                        font-family: 'Consolas','Courier New',monospace;
                        font-size: 11px;
                    }
                    QScrollBar:vertical,
                    QScrollBar:horizontal {
                        background: #dce6ff;
                        border: 1px solid $border;
                        border-radius: 6px;
                        margin: 0px;
                    }
                    QScrollBar::handle:vertical,
                    QScrollBar::handle:horizontal {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e3ecff);
                        border: 1px solid $border;
                        border-radius: 6px;
                        min-height: 18px;
                        min-width: 18px;
                    }
                    QScrollBar::add-line:vertical,
                    QScrollBar::sub-line:vertical,
                    QScrollBar::add-line:horizontal,
                    QScrollBar::sub-line:horizontal {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fefefe, stop:1 #dfe9ff);
                        border: 1px solid $border;
                        border-radius: 6px;
                        width: 18px;
                        height: 18px;
                    }
                    """
                )
            )
            self.setStyleSheet(style_template.substitute(**palette))
            return

        # Default modern fallback styling.
        panel = c['panel']
        card = c['card']
        text = c['text']
        accent = c['accent']
        border = c['border']
        bg = c['bg']

        style_template = Template(
            dedent(
                """
                QMainWindow {
                    background-color: $bg;
                    color: $text;
                    font-family: 'Segoe UI', 'Tahoma', sans-serif;
                    font-size: 14px;
                }
                QWidget#CentralWidget,
                QWidget#BodyWidget,
                QWidget#StrudelContainer {
                    background-color: $panel;
                    color: $text;
                }
                QFrame#Toolbar,
                QFrame#PluginBlock,
                QFrame#WorkspacePanel,
                QFrame#RackPanel,
                QFrame#HostPanel,
                QFrame#InstrumentPanel,
                QFrame#RackLogPanel {
                    background-color: $card;
                    border: 1px solid $border;
                    border-radius: 10px;
                }
                QPushButton,
                QToolButton {
                    background-color: $accent;
                    color: $text;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:disabled,
                QToolButton:disabled {
                    background-color: rgba(128,128,128,0.35);
                }
                QLineEdit,
                QPlainTextEdit,
                QTextEdit,
                QSpinBox,
                QDoubleSpinBox,
                QComboBox {
                    background-color: $card;
                    color: $text;
                    border: 1px solid $border;
                    border-radius: 6px;
                    padding: 4px;
                }
                QListWidget,
                QTreeWidget,
                QTableWidget {
                    background-color: $card;
                    color: $text;
                    border: 1px solid $border;
                    border-radius: 6px;
                }
                QListWidget::item:selected,
                QTreeWidget::item:selected,
                QTableWidget::item:selected {
                    background-color: $accent;
                    color: $text;
                }
                QTabWidget::pane {
                    border: 1px solid $border;
                    border-radius: 8px;
                    background-color: $card;
                }
                QTabBar::tab {
                    background-color: $panel;
                    color: $text;
                    padding: 6px 12px;
                    border: 1px solid $border;
                    border-bottom: none;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                }
                QTabBar::tab:selected {
                    background-color: $card;
                }
                """
            )
        )

        self.setStyleSheet(
            style_template.substitute(
                bg=bg,
                text=text,
                panel=panel,
                card=card,
                accent=accent,
                border=border,
            )
        )
    def apply_theme(self, key: str, *, update_combo: bool = True, log_change: bool = False) -> None:
        theme_key = key if key in THEME_PRESETS else "flat"
        self.theme_key = theme_key
        self._apply_theme_colors(theme_key)

        if update_combo and hasattr(self, "theme_combo"):
            index = self.theme_combo.findData(theme_key)
            if index >= 0:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(index)
                self.theme_combo.blockSignals(False)

        self.update_theme_palette()
        self.apply_global_styles()

        if getattr(self, "blocks_panel", None):
            self.blocks_panel.apply_theme(self.colors, dark=self.dark_mode)

        if log_change and hasattr(self, "rack_output"):
            label = self.theme_combo.currentText() if hasattr(self, "theme_combo") else theme_key
            self.append_log(f"Theme switched to '{label}'.")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.KeyPress:
            if self._handle_key_press(cast(QKeyEvent, event)):
                return True
        elif event.type() == QEvent.KeyRelease:
            if self._handle_key_release(cast(QKeyEvent, event)):
                return True
        return super().eventFilter(watched, event)

    def _set_keyboard_suspended(self, suspended: bool) -> None:
        if self._keyboard_suspended == suspended:
            return
        self._keyboard_suspended = suspended
        if suspended:
            self._release_all_keyboard_notes()
        self._apply_keyboard_enabled_state()

    def _apply_keyboard_enabled_state(self) -> None:
        piano = getattr(self, "piano", None)
        if not piano:
            return
        enabled = not self._keyboard_suspended
        piano.setEnabled(enabled)
        if enabled:
            piano.setToolTip("")
        else:
            piano.setToolTip("Disable Strudel Mode to play the built-in keyboard.")

    def _release_all_keyboard_notes(self) -> None:
        piano = getattr(self, "piano", None)
        if piano is None:
            return
        pending = set(piano.pressed_keys)
        pending.update(self.keyboard_active_notes.values())
        for note in sorted(pending):
            try:
                self.on_note_off(note)
            except Exception:
                pass
        self.keyboard_active_notes.clear()
        piano.release_all_keys()

    def _handle_key_press(self, event: QKeyEvent) -> bool:
        try:
            if event.isAutoRepeat() or not self.isActiveWindow():
                return False
            if not getattr(self, "piano", None):
                return False
            if self._keyboard_suspended:
                return False
            if not getattr(self, "chain_widget", None):
                return False
            modifiers = event.modifiers()
            disallowed = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
            def _has_disallowed(mods, mask) -> bool:
                combined = mods & mask
                if hasattr(combined, "value"):
                    return combined.value != 0
                try:
                    return int(combined) != 0
                except TypeError:
                    no_modifier = getattr(getattr(Qt, "KeyboardModifier", Qt), "NoModifier", 0)
                    return combined != no_modifier

            if _has_disallowed(modifiers, disallowed):
                return False
            offset = self.KEYBOARD_NOTE_MAP.get(event.key())
            if offset is None:
                return False
            note = self.piano.start_note + offset
            max_note = self.piano.start_note + self.piano.octaves * 12 - 1
            if not (self.piano.start_note <= note <= max_note):
                return False
            if event.key() in self.keyboard_active_notes:
                return True
            self.keyboard_active_notes[event.key()] = note
            if note not in self.piano.pressed_keys:
                self.piano.pressed_keys.add(note)
                self.piano.update()
            self.on_note_on(note)
            return True
        except Exception as exc:
            if hasattr(self, "logger"):
                self.logger.error("Keyboard press handling failed: %s", exc, exc_info=True)
            return False

    def _handle_key_release(self, event: QKeyEvent) -> bool:
        try:
            if event.isAutoRepeat():
                return False
            if not getattr(self, "piano", None):
                return False
            note = self.keyboard_active_notes.pop(event.key(), None)
            if note is None:
                return False
            if note in self.piano.pressed_keys:
                self.piano.pressed_keys.remove(note)
                self.piano.update()
            self.on_note_off(note)
            return True
        except Exception as exc:
            if hasattr(self, "logger"):
                self.logger.error("Keyboard release handling failed: %s", exc, exc_info=True)
            return False


    def update_theme_palette(self) -> None:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(self.colors['bg']))
        palette.setColor(QPalette.WindowText, QColor(self.colors['text']))
        base_color = self.colors['panel'] if self.dark_mode else self.colors['card']
        palette.setColor(QPalette.Base, QColor(base_color))
        palette.setColor(QPalette.AlternateBase, QColor(self.colors['card']))
        palette.setColor(QPalette.Text, QColor(self.colors['text']))
        palette.setColor(QPalette.Button, QColor(self.colors['panel']))
        palette.setColor(QPalette.ButtonText, QColor(self.colors['text']))
        palette.setColor(QPalette.Highlight, QColor(self.colors['accent']))
        highlight_text = QColor("#000000") if not self.dark_mode else QColor(self.colors['text'])
        palette.setColor(QPalette.HighlightedText, highlight_text)
        self.setPalette(palette)

    def cleanup_fallback_threads(self):
        self.fallback_audio_threads = [t for t in self.fallback_audio_threads if t.is_alive()]

    def play_fallback_tone(self, note: int, velocity: float = 0.5):
        ws = winsound
        if ws is None:
            if not self.warned_no_winsound and hasattr(self, "rack_output"):
                self.append_log("Fallback audio not available (winsound module missing).")
                self.warned_no_winsound = True
            return

        frequency = int(440 * (2 ** ((note - 69) / 12)))
        frequency = max(37, min(32767, frequency))
        millis = max(40, int(max(0.2, min(1.0, velocity)) * 220))

        def beep() -> None:
            try:
                ws.Beep(frequency, millis)
            except RuntimeError:
                pass

        thread = threading.Thread(target=beep, daemon=True)
        thread.start()
        self.fallback_audio_threads.append(thread)
        self.cleanup_fallback_threads()

    def apply_global_styles(self):
        if self.theme_key == "win98":
            win98 = {
                "teal": "#008080",
                "surface": "#c3c7cb",
                "face": "#dfdfdf",
                "shadow": "#808080",
                "highlight": "#ffffff",
                "blue": "#000080",
            }
            style_template = Template(
                dedent(
                    """
                    QMainWindow {
                        background-color: ;
                        color: ;
                        font-family: 'MS Sans Serif', 'Microsoft Sans Serif', 'Pixelated MS Sans Serif', sans-serif;
                        font-size: 11px;
                    }
                    QWidget#CentralWidget,
                    QWidget#BodyWidget,
                    QFrame#Toolbar,
                    QFrame#PluginBlock,
                    QWidget#StrudelContainer {
                        background-color: ;
                        color: ;
                    }
                    QFrame#Toolbar,
                    QFrame#PluginBlock,
                    QWidget#StrudelContainer {
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        border-radius: 0px;
                        padding: 6px;
                    }
                    QLabel#ToolbarTitle {
                        font-weight: bold;
                        color: ;
                    }
                    QPushButton,
                    QToolButton,
                    QComboBox,
                    QLineEdit,
                    QSpinBox,
                    QDoubleSpinBox,
                    QTextEdit,
                    QPlainTextEdit,
                    QListWidget,
                    QTreeWidget,
                    QTableWidget {
                        background-color: ;
                        color: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        border-radius: 0px;
                        padding: 2px 6px;
                    }
                    QComboBox QAbstractItemView {
                        background-color: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                    }
                    QGroupBox {
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        background-color: ;
                        margin-top: 10px;
                        padding: 12px;
                    }
                    QGroupBox::title {
                        subcontrol-origin: margin;
                        left: 8px;
                        padding: 0 4px;
                        color: ;
                        background-color: ;
                    }
                    QListWidget::item:selected,
                    QTreeWidget::item:selected,
                    QTableWidget::item:selected {
                        background: ;
                        color: #ffffff;
                    }
                    QHeaderView::section {
                        background-color: ;
                        color: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        padding: 2px 6px;
                    }
                    QScrollBar:vertical,
                    QScrollBar:horizontal {
                        background: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        margin: 0px;
                    }
                    QScrollBar::handle:vertical,
                    QScrollBar::handle:horizontal {
                        background: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        min-width: 18px;
                        min-height: 18px;
                    }
                    QScrollBar::add-line,
                    QScrollBar::sub-line {
                        background: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        width: 18px;
                        height: 18px;
                    }
                    QTabWidget::pane {
                        background: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                    }
                    QTabBar::tab {
                        background: ;
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        padding: 4px 10px;
                        margin-right: 2px;
                        color: ;
                    }
                    QTabBar::tab:selected {
                        background: ;
                    }
                    QProgressBar {
                        border: 2px solid ;
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                        background: ;
                        color: ;
                        text-align: center;
                    }
                    QProgressBar::chunk {
                        background: ;
                    }
                    QPushButton:pressed,
                    QToolButton:pressed {
                        border-top-color: ;
                        border-left-color: ;
                        border-bottom-color: ;
                        border-right-color: ;
                    }
                    QPushButton:disabled,
                    QToolButton:disabled {
                        color: #6e6e6e;
                    }
                    """
                )
            )
            style = style_template.substitute(
                teal=win98["teal"],
                text=self.colors['text'],
                surface=win98["surface"],
                face=win98["face"],
                shadow=win98["shadow"],
                highlight=win98["highlight"],
                blue=win98["blue"],
            )
            self.setStyleSheet(style)
            return

        if self.theme_key == "winxp":
            xp = {
                "bg_top": "#4f7cd7",
                "bg_bottom": "#1b4aa5",
                "surface": "#ece9d8",
                "button_top": "#fefefe",
                "button_bottom": "#d7e4fb",
                "button_hover_top": "#ffffff",
                "button_hover_bottom": "#dfeaff",
                "button_pressed_top": "#cbdafe",
                "button_pressed_bottom": "#b7caf5",
                "selected": "#316ac5",
            }
            style_template = Template(
                dedent(
                    """
                    QMainWindow {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 , stop:1 );
                        color: ;
                        font-family: 'Tahoma', 'Segoe UI', Arial, sans-serif;
                        font-size: 12px;
                    }
                    QWidget#CentralWidget,
                    QWidget#BodyWidget,
                    QWidget#StrudelContainer {
                        background-color: ;
                        color: ;
                        border-radius: 12px;
                    }
                    QFrame#Toolbar {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f9ff, stop:1 #d6e5ff);
                        border: 1px solid ;
                        border-radius: 10px;
                        padding: 8px 12px;
                    }
                    QLabel#ToolbarTitle {
                        font-size: 18px;
                        font-weight: bold;
                        color: #0a246a;
                        text-shadow: 0 1px 0 rgba(255,255,255,0.6);
                    }
                    QFrame#PluginBlock {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f9fcff, stop:1 #e1edff);
                        border: 1px solid ;
                        border-radius: 14px;
                        box-shadow: 0px 8px 18px rgba(16,43,105,0.22);
                    }
                    QPushButton,
                    QToolButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 , stop:1 );
                        border: 1px solid ;
                        border-radius: 6px;
                        padding: 4px 14px;
                        color: ;
                        min-height: 24px;
                        font-weight: 500;
                    }
                    QPushButton:hover,
                    QToolButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 , stop:1 );
                    }
                    QPushButton:pressed,
                    QToolButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 , stop:1 );
                        border-color: ;
                    }
                    QPushButton:disabled,
                    QToolButton:disabled {
                        color: rgba(0,0,0,0.35);
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f0f2f7, stop:1 #dbe2f4);
                    }
                    QComboBox,
                    QLineEdit,
                    QSpinBox,
                    QDoubleSpinBox,
                    QTextEdit,
                    QPlainTextEdit {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #edf3ff);
                        border: 1px solid ;
                        border-radius: 6px;
                        padding: 6px 10px;
                        color: ;
                    }
                    QComboBox QAbstractItemView {
                        background: #ffffff;
                        border: 1px solid ;
                        selection-background-color: ;
                        selection-color: #ffffff;
                    }
                    QListWidget,
                    QTreeWidget,
                    QTableWidget {
                        background: #ffffff;
                        border: 1px solid ;
                        border-radius: 8px;
                    }
                    QListWidget::item:selected,
                    QTreeWidget::item:selected,
                    QTableWidget::item:selected {
                        background: ;
                        color: #ffffff;
                    }
                    QHeaderView::section {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f9ff, stop:1 #d9e8ff);
                        color: #123169;
                        border: 1px solid ;
                        padding: 4px 8px;
                    }
                    QScrollBar:vertical,
                    QScrollBar:horizontal {
                        background: #f0f5ff;
                        border: 1px solid ;
                        border-radius: 6px;
                    }
                    QScrollBar::handle:vertical,
                    QScrollBar::handle:horizontal {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e3ecff);
                        border: 1px solid ;
                        border-radius: 6px;
                        min-height: 20px;
                        min-width: 20px;
                    }
                    QTabWidget::pane {
                        border: 1px solid ;
                        border-radius: 10px;
                        background: #ffffff;
                    }
                    QTabBar::tab {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f9fcff, stop:1 #dfe9ff);
                        border: 1px solid ;
                        border-bottom: none;
                        border-top-left-radius: 8px;
                        border-top-right-radius: 8px;
                        padding: 6px 14px;
                        margin-right: 4px;
                        color: ;
                    }
                    QTabBar::tab:selected {
                        background: #ffffff;
                    }
                    QProgressBar {
                        border: 1px solid ;
                        border-radius: 8px;
                        background: #f0f4ff;
                        color: ;
                        text-align: center;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5d9bff, stop:1 #2f69d3);
                        border-radius: 6px;
                    }
                    """
                )
            )
            style = style_template.substitute(
                bg_top=xp["bg_top"],
                bg_bottom=xp["bg_bottom"],
                text=self.colors['text'],
                surface=xp["surface"],
                border=self.colors['border'],
                border_light=self.rgba(self.colors['border'], 0.75),
                button_top=xp["button_top"],
                button_bottom=xp["button_bottom"],
                button_hover_top=xp["button_hover_top"],
                button_hover_bottom=xp["button_hover_bottom"],
                button_pressed_top=xp["button_pressed_top"],
                button_pressed_bottom=xp["button_pressed_bottom"],
                selected=xp["selected"],
            )
            self.setStyleSheet(style)
            return

        c = self.colors
        panel_border = self.rgba(c['border'], 0.85)
        accent_soft = self.rgba(c['accent'], 0.22)
        accent_hover = self.rgba(c['accent'], 0.32)
        accent_selected = self.rgba(c['accent'], 0.45)

        style_template = Template(
            dedent(
                """
                QMainWindow {
                    background-color: ;
                    color: ;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    font-size: 14px;
                }
                QWidget#CentralWidget,
                QWidget#BodyWidget,
                QWidget#StrudelContainer {
                    background-color: ;
                    color: ;
                }
                QFrame#Toolbar {
                    background-color: ;
                    border: 1px solid ;
                    border-radius: 12px;
                    padding: 12px;
                }
                QLabel#ToolbarTitle {
                    font-size: 18px;
                    font-weight: 600;
                    color: ;
                }
                QFrame#PluginBlock {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 , stop:1 );
                    border-radius: 14px;
                    border: 1px solid ;
                    padding: 12px;
                }
                QPushButton,
                QToolButton {
                    background-color: ;
                    border: 1px solid ;
                    border-radius: 10px;
                    padding: 6px 16px;
                    color: ;
                    font-weight: 600;
                }
                QPushButton:hover,
                QToolButton:hover {
                    background-color: ;
                }
                QPushButton:pressed,
                QToolButton:pressed {
                    background-color: ;
                }
                QComboBox,
                QLineEdit,
                QSpinBox,
                QDoubleSpinBox,
                QTextEdit,
                QPlainTextEdit {
                    background-color: ;
                    border: 1px solid ;
                    border-radius: 10px;
                    padding: 6px 10px;
                    color: ;
                }
                QListWidget,
                QTreeWidget,
                QTableWidget {
                    background-color: ;
                    border: 1px solid ;
                    border-radius: 12px;
                }
                QListWidget::item:selected,
                QTreeWidget::item:selected,
                QTableWidget::item:selected {
                    background-color: ;
                    color: ;
                }
                QProgressBar {
                    border: 1px solid ;
                    border-radius: 10px;
                    background-color: ;
                    color: ;
                    text-align: center;
                }
                QProgressBar::chunk {
                    background-color: ;
                    border-radius: 9px;
                }
                """
            )
        )

        style = style_template.substitute(
            bg=c['bg'],
            text=c['text'],
            panel=c['panel'],
            card=c['card'],
            panel_border=panel_border,
            accent_soft=accent_soft,
            accent_hover=accent_hover,
            accent_selected=accent_selected,
        )

        self.setStyleSheet(style)
    def _extract_plugin_capabilities(self, status: Dict[str, Any]) -> Tuple[bool, bool]:
        """Determine plugin MIDI support and instrument flag from a status payload."""
        supports_midi = False
        is_instrument = False

        if not isinstance(status, dict):
            return supports_midi, is_instrument

        def consider(container: Any) -> None:
            nonlocal supports_midi, is_instrument
            if not isinstance(container, dict):
                return
            if container.get("instrument"):
                is_instrument = True
                supports_midi = True
            if container.get("midi"):
                supports_midi = True

        consider(status.get("capabilities"))

        plugin = status.get("plugin")
        if isinstance(plugin, dict):
            consider(plugin.get("capabilities"))
            metadata = plugin.get("metadata")
            if isinstance(metadata, dict):
                categories = metadata.get("categories") or metadata.get("category")
                values: List[str] = []
                if isinstance(categories, str):
                    values = [categories]
                elif isinstance(categories, (list, tuple, set)):
                    values = [str(value) for value in categories]
                for entry in values:
                    lower = entry.lower()
                    if any(keyword in lower for keyword in ("instrument", "synth", "generator")):
                        is_instrument = True
                        supports_midi = True
                        break
            keyboard_info = plugin.get("keyboard")
            if isinstance(keyboard_info, dict):
                supports_midi = True

        return supports_midi, is_instrument

    def refresh_host_status(self, slot: Optional[PluginChainSlot]):
        if slot and slot.host:
            try:
                status = slot.host.status()
            except Exception as exc:
                self.host_status_label.setText(f"Status unavailable: {exc}")
                self.host_warnings_label.setText("")
                return

            plugin = status.get("plugin") or {}
            metadata = plugin.get("metadata") or {}
            plugin_name = metadata.get("name") or (slot.plugin_path.stem if slot.plugin_path else "Unknown plugin")
            engine = status.get("engine") or {}
            driver = engine.get("driver") or "Auto"
            sample_rate = engine.get("sample_rate") or "?"
            buffer_size = engine.get("buffer_size") or "?"

            slot.supports_midi, is_instrument = self._extract_plugin_capabilities(status)

            self.host_status_label.setText(
                f"Loaded {plugin_name} | Driver: {driver} | SR: {sample_rate} | Buffer: {buffer_size}"
            )

            warnings = status.get("warnings") or []
            warnings_text = "\n".join(warnings)
            self.host_warnings_label.setText(warnings_text)

            if slot.supports_midi and is_instrument:
                self.instrument_title_label.setText(plugin_name)
                self.instrument_status_label.setText("Instrument ready. Use the keyboard below to audition.")
                self.instrument_panel.setEnabled(True)
            else:
                self.instrument_title_label.setText("Digital Instrument")
                self.instrument_status_label.setText("Load an instrument plugin to unlock performance controls.")
                self.instrument_panel.setEnabled(False)

            self.rack_status_label.setText(f"Host: {plugin_name}")
        else:
            self.host_status_label.setText("No plugin is currently loaded into the host.")
            self.host_warnings_label.setText("")
            self.instrument_title_label.setText("Digital Instrument")
            self.instrument_status_label.setText("Load an instrument plugin to unlock performance controls.")
            self.instrument_panel.setEnabled(False)
            if slot:
                slot.supports_midi = False
            self.rack_status_label.setText(f"Library: {self.plugin_list.count()} plugins")

    def unload_selected_slot(self):
        slot = self.get_selected_slot()
        if not slot:
            QMessageBox.information(self, "No Slot", "Select a slot from the rack first.")
            return
        self.chain_widget.unload_plugin_from_slot()
        self.param_refresh_attempts.pop(slot.index, None)
        self.append_log(f"Unloaded slot {slot.index + 1}.")
        self.refresh_host_status(self.get_selected_slot())
        self.update_host_controls()

    def toggle_slot_ui_from_host(self):
        slot = self.get_selected_slot()
        if not slot or not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into the selected slot first.")
            return
        self.chain_widget.toggle_slot_ui()

    def preview_plugin(self):
        slot = self.get_selected_slot()
        if not slot or not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into the selected slot first.")
            return
        self.append_log("Preview playback is not implemented for the Carla backend yet.")

    def adjust_instrument_octave(self, delta: int):
        self.instrument_octave = max(0, min(8, self.instrument_octave + delta))
        self.update_instrument_octave_label()
        # MIDI: C at octave N = note 12 * (N + 1)
        self.piano.start_note = 12 * (self.instrument_octave + 1)
        self.piano.update()

    def update_instrument_octave_label(self):
        self.instrument_octave_label.setText(f"Octave {self.instrument_octave}")

    def on_instrument_velocity_changed(self, value: int):
        self.instrument_velocity = max(0.2, min(1.2, value / 100.0))

    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        existing = self.rack_output.toPlainText()
        if existing:
            self.rack_output.setPlainText(entry + "\n" + existing)
        else:
            self.rack_output.setPlainText(entry)
        self.rack_output.verticalScrollBar().setValue(0)

    def scan_plugins(self):
        """Scan for VST plugins."""
        self.plugin_list.clear()
        base_dir = Path(__file__).parent
        workspace_candidates = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
        ]
        workspace_dir = next((p for p in workspace_candidates if p.exists()), None)
        self.last_workspace_path = str(workspace_dir) if workspace_dir else ""
        self.workspace_path_label.setText(self.last_workspace_path or "Workspace not found")

        # Multiple search paths
        plugin_dirs = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
            Path("C:/Program Files/VSTPlugins"),
            Path("C:/Program Files/Steinberg/VSTPlugins"),
            Path("C:/Program Files/Common Files/VST3"),
            Path("C:/Program Files (x86)/VSTPlugins"),
            Path("C:/Program Files (x86)/Steinberg/VSTPlugins"),
        ]

        available_dirs = [p for p in plugin_dirs if p.exists()]
        missing_dirs = [p for p in plugin_dirs if not p.exists() and "Program Files" not in str(p)]

        plugins = []
        for plugin_dir in available_dirs:
            for pattern in ("**/*.dll", "**/*.vst3", "**/*.vst"):
                plugins.extend(plugin_dir.glob(pattern))
        
        # Remove duplicates and sort
        seen = {}
        for plugin_path in sorted(set(plugins)):
            key = plugin_path.name.lower()
            if key in seen:
                continue
            seen[key] = plugin_path
            item = QListWidgetItem(plugin_path.stem)
            item.setData(Qt.UserRole, str(plugin_path))
            item.setToolTip(str(plugin_path))
            self.plugin_list.addItem(item)

        notes: List[str] = []
        if not available_dirs:
            notes.append("No plugin directories were found. Drop VST files into the Ambiance 'included_plugins' folder.")
        elif missing_dirs:
            notes.append("Some optional plugin folders were not found and will be skipped.")

        self.workspace_notes.setText("\n".join(notes))

        plugin_count = len(seen)
        dir_count = len(available_dirs)
        self.statusBar().showMessage(f"Found {plugin_count} plugins across {dir_count} folders")
        self.rack_status_label.setText(f"Library: {plugin_count} plugins")
        if plugin_count == 0:
            self.append_log("No plugins discovered. Add VST/VST3 files to your workspace directory.")
        else:
            self.append_log(f"Library refreshed - {plugin_count} plugins ready.")

        self.refresh_selected_plugin_label()
        self.update_host_controls()
    
    def on_plugin_selected(self, item):
        """Handle plugin double-click."""
        # Check if there's a selected slot in chain
        if self.chain_widget.selected_slot_index >= 0:
            self.load_plugin_to_chain()
    
    def load_plugin_to_chain(self):
        """Load selected plugin into selected chain slot."""
        if self.chain_widget.selected_slot_index < 0:
            QMessageBox.information(self, "No Slot", "Please select or add a plugin slot first")
            return
        
        items = self.plugin_list.selectedItems()
        if not items:
            QMessageBox.information(self, "No Plugin", "Please select a plugin to load")
            return
        
        plugin_path = Path(items[0].data(Qt.UserRole))
        slot = self.chain_widget.slots[self.chain_widget.selected_slot_index]
        slot.supports_midi = False
        
        try:
            if slot.host:
                with slot.lock:
                    slot.host.unload()
                    slot.host.shutdown()

            # Create fresh host with unique JACK client name (prevents conflicts)
            slot.host = CarlaVSTHost(client_name=f"AmbianceSlot{slot.index}")
            if self.chain_widget.host_window_id is not None:
                slot.host.register_host_window(self.chain_widget.host_window_id)

            # Configure audio WITHOUT lock (plugin_host.py doesn't use locks)
            # Try DirectSound first for testing - JACK needs server running + routing setup
            slot.host.configure_audio(preferred_drivers=["DirectSound", "ASIO", "WASAPI", "Dummy", "JACK"])

            # Load plugin WITHOUT lock (plugin_host.py doesn't use locks)
            slot.host.load_plugin(plugin_path, show_ui=False)
            slot.plugin_path = plugin_path
            slot.ui_visible = False

            # Get status WITHOUT lock (plugin_host.py doesn't use locks)
            status: Dict[str, Any] = {}
            try:
                status = slot.host.status()
            except Exception:
                status = {}

            # Log which audio driver is being used
            driver_name = status.get("driver", "unknown")
            self.logger.info(f"Slot {slot.index} using audio driver: {driver_name}")
            if driver_name not in ["JACK", "ASIO"]:
                self.logger.warning(f"Using {driver_name} driver - Install JACK or ASIO for better compatibility")
                self.logger.warning(f"See JACK_SETUP.md for installation instructions")

            slot.supports_midi, _ = self._extract_plugin_capabilities(status)

            self.chain_widget.update_slot_display(slot.index)
            self.chain_widget.update_controls()

            self.update_parameters_for_slot(slot)
            self.refresh_host_status(slot)
            self.update_host_controls()
            self.refresh_selected_plugin_label()

            if len(self.chain_widget.get_active_slots()) == 1:
                self.poll_timer.start(100)

            self.statusBar().showMessage(f"Loaded {plugin_path.stem} into slot {slot.index + 1}")
            self.append_log(f"Loaded '{plugin_path.stem}' into slot {slot.index + 1}.")

        except Exception as e:
            slot.supports_midi = False
            QMessageBox.critical(self, "Load Error", f"Failed to load plugin:\n{str(e)}")
            self.logger.error(f"Plugin load error: {e}", exc_info=True)
            self.append_log(f"Failed to load plugin: {e}")
    
    def update_parameters_for_slot(self, slot: PluginChainSlot):
        """Update parameter controls for a slot."""
        if not slot.host:
            return
        
        # Get or create tab for this slot
        tab_name = f"Slot {slot.index + 1}"
        tab_index = -1
        for i in range(self.param_tabs.count()):
            if self.param_tabs.tabText(i) == tab_name:
                tab_index = i
                break
        
        layout: QVBoxLayout
        if tab_index == -1:
            # Create new tab
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            widget = QWidget()
            layout = QVBoxLayout(widget)
            scroll.setWidget(widget)
            tab_index = self.param_tabs.addTab(scroll, tab_name)
        else:
            # Clear existing tab
            scroll_widget = self.param_tabs.widget(tab_index)
            if not isinstance(scroll_widget, QScrollArea):
                return
            widget = scroll_widget.widget()
            if widget is None:
                return
            existing_layout = widget.layout()
            if existing_layout is None or not isinstance(existing_layout, QVBoxLayout):
                existing_layout = QVBoxLayout(widget)
            layout = cast(QVBoxLayout, existing_layout)
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        
        # Add parameters
        status: Dict[str, Any] = {}
        try:
            with slot.lock:
                status = slot.host.status()
        except Exception as exc:
            status = {}
            self.logger.debug("Failed to read slot %s status: %s", slot.index, exc, exc_info=True)

        if not isinstance(status, dict):
            status = {}

        params = status.get("parameters", [])
        self.logger.debug("Slot %s initial parameter count: %s", slot.index, len(params) if isinstance(params, list) else 'n/a')

        if not params:
            descriptor: Dict[str, Any] = {}
            try:
                with slot.lock:
                    descriptor = slot.host.describe_ui(include_parameters=True)
            except Exception as exc:
                self.logger.debug("describe_ui failed for slot %s: %s", slot.index, exc, exc_info=True)
            else:
                if isinstance(descriptor, dict):
                    params = descriptor.get("parameters") or []
                    if not params:
                        plugin_info = descriptor.get("plugin")
                        if isinstance(plugin_info, dict):
                            params = plugin_info.get("parameters") or []
                    if params:
                        status["parameters"] = params
                        self.logger.debug("Slot %s recovered %d parameters via describe_ui()", slot.index, len(params))
                    else:
                        self.logger.debug("Slot %s still reports no parameters after describe_ui()", slot.index)

        attempts = self.param_refresh_attempts.get(slot.index, 0)

        if not params:
            max_attempts = 10  # Increased from 5 to 10 for slow plugins like Aspen
            if attempts == 0:
                message = "Discovering parameters..."
            elif attempts < max_attempts:
                message = f"No parameters yet. Retrying... (attempt {attempts + 1}/{max_attempts})"
            else:
                message = "No parameters reported by this plugin."
            label = QLabel(message)
            layout.addWidget(label)
            layout.addStretch()
            if attempts < max_attempts:
                self.param_refresh_attempts[slot.index] = attempts + 1
                # Progressive delays: start fast, get slower for stubborn plugins
                if attempts < 2:
                    delay = 500  # First 2: 500ms (quick check)
                elif attempts < 5:
                    delay = 1500  # Next 3: 1.5s (give it time)
                else:
                    delay = 3000  # Final 5: 3s (really patient)
                QTimer.singleShot(
                    delay,
                    lambda idx=slot.index: self.retry_parameter_fetch(idx)
                )
            return
        
        self.param_refresh_attempts[slot.index] = 0
        for param in params:
            self.create_parameter_control(layout, slot, param)
        
        layout.addStretch()

    def retry_parameter_fetch(self, slot_index: int):
        if 0 <= slot_index < len(self.chain_widget.slots):
            slot = self.chain_widget.slots[slot_index]
            if slot.host:
                self.update_parameters_for_slot(slot)
                self.refresh_host_status(slot)
    
    def create_parameter_control(self, layout: QVBoxLayout, slot: PluginChainSlot, param: Dict[str, Any]) -> None:
        """Create a parameter control widget."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        param_layout = QVBoxLayout(frame)
        
        # Label
        name = param.get("display_name") or param.get("name", "Parameter")
        value_label = QLabel(f"{name}: {param['value']:.3f} {param.get('units', '')}")
        param_layout.addWidget(value_label)
        
        # Slider
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(1000)
        
        min_val = param.get("min", 0)
        max_val = param.get("max", 1)
        current_val = param.get("value", 0)
        
        normalized = (current_val - min_val) / (max_val - min_val) if max_val != min_val else 0
        slider.setValue(int(normalized * 1000))
        
        def on_value_changed(val: int) -> None:
            host = slot.host
            if host is None:
                return
            norm = val / 1000.0
            actual = min_val + norm * (max_val - min_val)
            try:
                with slot.lock:
                    host.set_parameter(param["id"], actual)
                value_label.setText(f"{name}: {actual:.3f} {param.get('units', '')}")
            except:
                pass
        
        slider.valueChanged.connect(on_value_changed)
        param_layout.addWidget(slider)
        
        layout.addWidget(frame)
    
    def _submit_midi_job(self, callback: Callable[..., None], *args, **kwargs) -> None:
        """Queue a MIDI operation, falling back to direct execution if the worker is stopping."""
        if self._midi_worker_stop.is_set():
            try:
                callback(*args, **kwargs)
            except Exception as exc:
                self.logger.error("MIDI dispatch (sync) failed: %s", exc, exc_info=True)
            return
        self._midi_queue.put((callback, args, kwargs))

    def on_edit_mode_toggled(self, checked: bool) -> None:
        """Toggle edit affordances in the UI."""
        label = "Edit: ON" if checked else "Edit: OFF"
        self.edit_mode_btn.setText(label)
        self.edit_mode_btn.setProperty("toggled", checked)
        self.edit_mode_btn.style().unpolish(self.edit_mode_btn)
        self.edit_mode_btn.style().polish(self.edit_mode_btn)
        self.edit_mode_btn.update()
        if checked:
            self.append_log("Edit mode enabled.")
        else:
            self.append_log("Edit mode disabled.")

    def on_style_mode_toggled(self, checked: bool) -> None:
        """Toggle style controls visibility."""
        label = "Style Mode: ON" if checked else "Style Mode: OFF"
        self.style_mode_btn.setText(label)
        self.style_mode_btn.setProperty("toggled", checked)
        self.style_mode_btn.style().unpolish(self.style_mode_btn)
        self.style_mode_btn.style().polish(self.style_mode_btn)
        self.style_mode_btn.update()
        if checked:
            self.append_log("Style mode enabled.")
        else:
            self.append_log("Style mode disabled.")

    def _perform_note_on(self, host: CarlaVSTHost, note: int, velocity: float, slot_index: Optional[int] = None) -> None:
        try:
            host.note_on(note, velocity=velocity)
        except CarlaHostError as exc:
            if slot_index is not None:
                self.logger.warning("Note on error for slot %s: %s", slot_index, exc)
            else:
                self.logger.warning("Note on error: %s", exc)
        except Exception as exc:
            if slot_index is not None:
                self.logger.error("Note on crash for slot %s: %s", slot_index, exc, exc_info=True)
            else:
                self.logger.error("Note on crash: %s", exc, exc_info=True)

    def _perform_note_off(self, host: CarlaVSTHost, note: int, slot_index: Optional[int] = None) -> None:
        try:
            host.note_off(note)
        except CarlaHostError as exc:
            if slot_index is not None:
                self.logger.warning("Note off error for slot %s: %s", slot_index, exc)
            else:
                self.logger.warning("Note off error: %s", exc)
        except Exception as exc:
            if slot_index is not None:
                self.logger.error("Note off crash for slot %s: %s", slot_index, exc, exc_info=True)
            else:
                self.logger.error("Note off crash: %s", exc, exc_info=True)

    def toggle_note_names(self, checked):
        """Toggle note name display."""
        self.piano.show_note_names = checked
        self.piano.update()

    def on_note_on(self, note: int):
        """Handle note on event - send to all active plugins in chain."""
        active_slots = [s for s in self.chain_widget.get_active_slots() if s.supports_midi]
        if not active_slots:
            self.play_fallback_tone(note, self.instrument_velocity)
            return

        velocity = self.instrument_velocity
        for slot in active_slots:
            host = slot.host
            if host is None:
                continue
            self._submit_midi_job(self._perform_note_on, host, note, velocity, slot.index)

    def on_note_off(self, note: int):
        """Handle note off event - send to all active plugins in chain."""
        for slot in [s for s in self.chain_widget.get_active_slots() if s.supports_midi]:
            host = slot.host
            if host is None:
                continue
            self._submit_midi_job(self._perform_note_off, host, note, slot.index)
    
    def poll_parameters(self):
        """Poll parameter values for all active slots."""
        # TODO: Implement parameter polling for all slots
        pass


    def on_tempo_changed(self, tempo: float):
        """Handle tempo change from Time & Pitch mod."""
        self.logger.info(f"Tempo changed: {tempo:.2f}x")
        # TODO: Apply tempo change to audio stream
        self.append_log(f"Tempo: {tempo:.2f}x")

    def on_pitch_changed(self, pitch: int):
        """Handle pitch change from Time & Pitch mod."""
        self.logger.info(f"Pitch changed: {pitch:+d} semitones")
        # TODO: Apply pitch shift to audio stream
        self.append_log(f"Pitch: {pitch:+d} st")

    def on_reverse_changed(self, reverse: bool):
        """Handle reverse toggle from Time & Pitch mod."""
        self.logger.info(f"Reverse: {reverse}")
        # TODO: Apply reverse to audio stream
        self.append_log(f"Reverse: {'ON' if reverse else 'OFF'}")

    def on_loop_changed(self, loop: bool):
        """Handle loop toggle from Time & Pitch mod."""
        self.logger.info(f"Loop: {loop}")
        # TODO: Apply loop to audio stream
        self.append_log(f"Loop: {'ON' if loop else 'OFF'}")

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Clean shutdown."""
        self.poll_timer.stop()
        self.process_timer.stop()

        self._teardown_strudel_server()

        # Shutdown all plugin hosts
        for slot in self.chain_widget.slots:
            if slot.host:
                try:
                    with slot.lock:
                        slot.host.unload()
                        slot.host.shutdown()
                except Exception:
                    pass

        for note in list(self.keyboard_active_notes.values()):
            try:
                self.on_note_off(note)
            except Exception:
                pass
        self.keyboard_active_notes.clear()

        if self.audio_engine is not None:
            try:
                self.audio_engine.shutdown()
            except Exception as exc:
                self.logger.error("Audio engine shutdown failed: %s", exc, exc_info=True)

        self.chain_widget.shutdown()
        for thread in list(self.fallback_audio_threads):
            if thread.is_alive():
                thread.join(timeout=0.2)
        self.fallback_audio_threads.clear()

        if getattr(self, "_midi_worker_stop", None):
            self._midi_worker_stop.set()
            try:
                self._midi_queue.put(None)
            except Exception:
                pass
            worker = getattr(self, "_midi_worker", None)
            if worker and worker.is_alive():
                worker.join(timeout=1.0)

        if self._qt_app is not None:
            try:
                self._qt_app.removeEventFilter(self)
            except Exception:
                pass

        event.accept()


def _ambiance_on_edit_mode_toggled(self: AmbianceQtImproved, checked: bool) -> None:
    label = "Edit: ON" if checked else "Edit: OFF"
    if getattr(self, "edit_mode_btn", None):
        self.edit_mode_btn.setText(label)
        self.edit_mode_btn.setProperty("toggled", checked)
        self.edit_mode_btn.style().unpolish(self.edit_mode_btn)
        self.edit_mode_btn.style().polish(self.edit_mode_btn)
        self.edit_mode_btn.update()
    if hasattr(self, "append_log"):
        self.append_log("Edit mode enabled." if checked else "Edit mode disabled.")


def _ambiance_on_style_mode_toggled(self: AmbianceQtImproved, checked: bool) -> None:
    label = "Style Mode: ON" if checked else "Style Mode: OFF"
    if getattr(self, "style_mode_btn", None):
        self.style_mode_btn.setText(label)
        self.style_mode_btn.setProperty("toggled", checked)
        self.style_mode_btn.style().unpolish(self.style_mode_btn)
        self.style_mode_btn.style().polish(self.style_mode_btn)
        self.style_mode_btn.update()
    if hasattr(self, "append_log"):
        self.append_log("Style mode enabled." if checked else "Style mode disabled.")


AmbianceQtImproved.on_edit_mode_toggled = _ambiance_on_edit_mode_toggled
AmbianceQtImproved.on_style_mode_toggled = _ambiance_on_style_mode_toggled


def _ambiance_toggle_note_names(self: AmbianceQtImproved, checked: bool) -> None:
    if getattr(self, "piano", None):
        self.piano.show_note_names = checked
        self.piano.update()


AmbianceQtImproved.toggle_note_names = _ambiance_toggle_note_names


def qt_message_handler(mode, context, message):
    """Capture Qt warning/error messages."""
    import logging
    logger = logging.getLogger('Qt')
    if mode == 0:  # QtDebugMsg
        logger.debug(f"Qt: {message}")
    elif mode == 1:  # QtWarningMsg
        logger.warning(f"Qt: {message}")
    elif mode == 2:  # QtCriticalMsg
        logger.error(f"Qt: {message}")
    elif mode == 3:  # QtFatalMsg
        logger.critical(f"Qt FATAL: {message}")

def main():
    try:
        # Install Qt message handler to capture errors
        try:
            from qtpy.QtCore import qInstallMessageHandler
            qInstallMessageHandler(qt_message_handler)
        except Exception:
            pass

        try:
            share_attr = getattr(Qt, "AA_ShareOpenGLContexts", None)
            if share_attr is None and hasattr(Qt, "ApplicationAttribute"):
                share_attr = Qt.ApplicationAttribute.AA_ShareOpenGLContexts
            if share_attr is not None:
                QApplication.setAttribute(share_attr, True)
        except Exception:
            pass

        try:
            attr = getattr(Qt, "AA_UseSoftwareOpenGL", None)
            if attr is None and hasattr(Qt, "ApplicationAttribute"):
                attr = Qt.ApplicationAttribute.AA_UseSoftwareOpenGL
            if attr is not None:
                QApplication.setAttribute(attr, True)
        except Exception:
            pass

        app = QApplication(sys.argv)
        app.setApplicationName("Ambiance Improved")
        app.setStyle("Fusion")

        ensure_webengine()
        if QWebEngineView is not None:
            try:
                from qtpy.QtWebEngineCore import QtWebEngine
                QtWebEngine.initialize()
            except Exception:
                pass
        elif WEBENGINE_IMPORT_ERROR is not None:
            logging.getLogger(__name__).warning("Qt WebEngine failed to import: %s", WEBENGINE_IMPORT_ERROR)

        window = AmbianceQtImproved()
        window.show()

        logging.getLogger(__name__).info("Application window shown, entering event loop")
        exit_code = app.exec()
        logging.getLogger(__name__).info(f"Event loop exited with code: {exit_code}")
        sys.exit(exit_code)
    except Exception as exc:
        import traceback
        logging.getLogger(__name__).critical("FATAL ERROR during Ambiance startup", exc_info=True)
        print(f"\n{'='*60}")
        print("FATAL ERROR during Ambiance startup:")
        print(f"{'='*60}")
        traceback.print_exc()
        print(f"{'='*60}\n")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Application interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()


