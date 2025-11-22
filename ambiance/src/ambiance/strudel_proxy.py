"""Standalone Strudel proxy for serving the docs/REPL bundle with browser parity."""

from __future__ import annotations

import argparse
import logging
import mimetypes
import threading
import urllib.request
from functools import partial
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path, PurePosixPath
from socketserver import ThreadingMixIn
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse

LOGGER = logging.getLogger("ambiance.strudel_proxy")

LOCAL_ROOT = Path(__file__).resolve().parents[2] / "resources" / "strudel" / "dist"
REMOTE_BASE = "https://strudel.cc/"

TEXTUAL_MIME_PREFIXES = (
    "text/",
    "application/javascript",
    "application/json",
    "application/xml",
)

BRIDGE_SNIPPET = """
<script id="ambiance-strudel-bridge">
(function () {
  if (window.__ambianceStrudelBridge) {
    return;
  }
  window.__ambianceStrudelBridge = true;
  const pending = [];
  let flushTimer = null;
  const flushPending = (mirror) => {
    while (pending.length) {
      const next = pending.shift();
      if (typeof next === "function") {
        try {
          next(mirror);
        } catch (err) {
          console.error("[Ambiance] Strudel bridge callback failed", err);
        }
      }
    }
  };
  const enqueue = (fn) => {
    if (typeof fn !== "function") return;
    pending.push(fn);
    scheduleFlush();
  };
  const withMirror = (callback) => {
    const mirror = window.strudelMirror;
    if (mirror) {
      callback(mirror);
      return true;
    }
    return false;
  };
  const scheduleFlush = () => {
    if (flushTimer !== null) {
      return;
    }
    const tryFlush = () => {
      if (pending.length === 0) {
        clearInterval(flushTimer);
        flushTimer = null;
        return;
      }
      if (withMirror((mirror) => flushPending(mirror))) {
        clearInterval(flushTimer);
        flushTimer = null;
      }
    };
    flushTimer = window.setInterval(tryFlush, 150);
    tryFlush();
    window.addEventListener(
      "load",
      () => {
        tryFlush();
      },
      { once: true }
    );
  };
  const handleAction = (mirror, action) => {
    const repl = mirror && mirror.repl;
    switch (action) {
      case "play":
      case "toggle":
        if (typeof mirror.toggle === "function") {
          mirror.toggle();
        } else if (repl && typeof repl.toggle === "function") {
          repl.toggle();
        }
        break;
      case "stop":
        if (repl && typeof repl.stop === "function") {
          repl.stop();
        } else if (typeof mirror.stop === "function") {
          mirror.stop();
        } else if (typeof mirror.toggle === "function") {
          mirror.toggle();
        }
        break;
      case "update":
      case "evaluate":
        if (typeof mirror.evaluate === "function") {
          mirror.evaluate();
        } else if (repl && typeof repl.evaluate === "function") {
          repl.evaluate(mirror.getCode ? mirror.getCode() : undefined);
        }
        break;
      default:
        break;
    }
  };
  const messageHandler = (event) => {
    const data = event && event.data;
    if (!data || typeof data !== "object") {
      return;
    }
    if (data.type === "ambiance-strudel-action") {
      const action = String(data.action || "").toLowerCase();
      if (!action) {
        return;
      }
      enqueue((mirror) => handleAction(mirror, action));
    } else if (data.type === "ambiance-strudel-set-code" && typeof data.code === "string") {
      enqueue((mirror) => {
        try {
          mirror.setCode && mirror.setCode(data.code);
          if (data.autoPlay === true) {
            if (typeof mirror.evaluate === "function") {
              mirror.evaluate();
            } else if (mirror.repl && typeof mirror.repl.evaluate === "function") {
              mirror.repl.evaluate(mirror.getCode ? mirror.getCode() : undefined);
            }
          }
        } catch (err) {
          console.error("[Ambiance] Failed to sync code with Strudel", err);
        }
      });
    }
  };
  window.addEventListener("message", messageHandler);
  if (document.readyState === "complete" || document.readyState === "interactive") {
    scheduleFlush();
  } else {
    window.addEventListener(
      "DOMContentLoaded",
      () => scheduleFlush(),
      { once: true }
    );
  }
})();
</script>
"""


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class StrudelProxyRequestHandler(SimpleHTTPRequestHandler):
    """Serve local Strudel assets and fall back to the live site when needed."""

    def __init__(
        self,
        *args: Any,
        root_dir: Path,
        remote_base: str,
        **kwargs: Any,
    ) -> None:
        self.root_dir = root_dir
        self.remote_base = remote_base.rstrip("/") + "/"
        super().__init__(*args, directory=str(root_dir), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        LOGGER.info(format, *args)

    # -- HTTP entry points -------------------------------------------------
    def do_HEAD(self) -> None:  # noqa: N802 - stdlib signature
        if self._serve_local(head_only=True):
            return
        self._proxy_remote(head_only=True)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if self._serve_local():
            return
        self._proxy_remote()

    # -- Local file handling ----------------------------------------------
    def _serve_local(self, head_only: bool = False) -> bool:
        candidate = self._resolve_local_path()
        if not candidate:
            return False
        try:
            ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            data = b""
            if not head_only:
                data = candidate.read_bytes()
                if self._is_textual(ctype):
                    data = self._maybe_inject_bridge(data, ctype)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head_only:
                self.wfile.write(data)
            return True
        except OSError as exc:  # pragma: no cover - rare filesystem error
            LOGGER.error("Failed to read %s: %s", candidate, exc)
            return False

    def _resolve_local_path(self) -> Path | None:
        parsed = urlparse(self.path)
        clean = PurePosixPath(parsed.path)
        rel = clean.relative_to("/") if clean.is_absolute() else clean
        candidate = (self.root_dir / rel).resolve()
        try:
            candidate.relative_to(self.root_dir.resolve())
        except ValueError:
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if candidate.exists():
            return candidate
        # SPA fallback: serve root index for routes without file extensions
        if not rel.suffix:
            fallback = (self.root_dir / "index.html").resolve()
            if fallback.exists():
                return fallback
        return None

    # -- Remote fallback ---------------------------------------------------
    def _proxy_remote(self, head_only: bool = False) -> None:
        url = self._build_remote_url()
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AmbianceStrudelProxy/1.0",
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
            method="HEAD" if head_only else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = b"" if head_only else response.read()
                self._write_remote_response(response.status, response.headers, raw)
        except HTTPError as exc:
            body = exc.read() if not head_only else b""
            self._write_remote_response(exc.code, exc.headers, body)
        except URLError as exc:
            LOGGER.error("Strudel proxy failed for %s: %s", url, exc)
            self.send_error(HTTPStatus.BAD_GATEWAY, f"Strudel proxy failed: {exc.reason if hasattr(exc, 'reason') else exc}")

    def _build_remote_url(self) -> str:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        upstream = urljoin(self.remote_base, path.lstrip("/"))
        if parsed.query:
            upstream = f"{upstream}?{parsed.query}"
        if parsed.fragment:
            upstream = f"{upstream}#{parsed.fragment}"
        return upstream

    def _write_remote_response(self, status: int, headers, body: bytes) -> None:
        self.send_response(status)
        content_type = headers.get("Content-Type", "application/octet-stream") if headers else "application/octet-stream"
        if body and self._is_textual(content_type):
            body = self._maybe_inject_bridge(body, content_type)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        cache_control = headers.get("Cache-Control") if headers else None
        self.send_header("Cache-Control", cache_control or "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if headers:
            for key, value in headers.items():
                lowered = key.lower()
                if lowered in {
                    "content-length",
                    "content-type",
                    "transfer-encoding",
                    "connection",
                    "keep-alive",
                    "proxy-authenticate",
                    "proxy-authorization",
                    "te",
                    "trailer",
                    "upgrade",
                    "vary",
                    "content-security-policy",
                    "x-frame-options",
                    "strict-transport-security",
                }:
                    continue
                self.send_header(key, value)
        self.end_headers()
        if body and not self._is_textual(content_type):
            self.wfile.write(body)
        elif body:
            self.wfile.write(body)

    @staticmethod
    def _is_textual(content_type: str) -> bool:
        return any(content_type.startswith(prefix) for prefix in TEXTUAL_MIME_PREFIXES)

    def _maybe_inject_bridge(self, body: bytes, content_type: str) -> bytes:
        """Inject the Ambiance bridge snippet into Strudel HTML responses."""
        if not body or "html" not in content_type.lower():
            return body
        try:
            html = body.decode("utf-8")
        except UnicodeDecodeError:
            return body
        marker = "ambiance-strudel-bridge"
        if marker in html:
            return body
        lower = html.lower()
        needle = "</body>"
        index = lower.rfind(needle)
        if index == -1:
            html = f"{html}{BRIDGE_SNIPPET}"
        else:
            html = f"{html[:index]}{BRIDGE_SNIPPET}{html[index:]}"
        return html.encode("utf-8")


class StrudelProxy:
    """Manage the lifecycle of the Strudel proxy server."""

    def __init__(
        self,
        root_dir: Path | None = None,
        remote_base: str = REMOTE_BASE,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.root_dir = (root_dir or LOCAL_ROOT).resolve()
        self.remote_base = remote_base
        self.host = host
        self.port = port
        self._httpd: _ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        if self._httpd:
            return self._httpd.server_address[1]
        handler = partial(
            StrudelProxyRequestHandler,
            root_dir=self.root_dir,
            remote_base=self.remote_base,
        )
        self._httpd = _ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        LOGGER.info(
            "Strudel proxy serving %s (remote fallback %s) at http://%s:%s/",
            self.root_dir,
            self.remote_base,
            self.host,
            self._httpd.server_address[1],
        )
        return self._httpd.server_address[1]

    def stop(self) -> None:
        if not self._httpd:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=1.5)
        self._httpd = None
        self._thread = None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the standalone Strudel proxy server.")
    parser.add_argument("--root", type=Path, default=LOCAL_ROOT, help="Path to the Strudel dist/ directory.")
    parser.add_argument("--remote", default=REMOTE_BASE, help="Fallback remote base URL (default: https://strudel.cc/).")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (default: 0 = auto).")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="[%(asctime)s] %(levelname)s: %(message)s")
    proxy = StrudelProxy(root_dir=args.root, remote_base=args.remote, host=args.host, port=args.port)
    port = proxy.start()
    print(f"Strudel proxy running at http://{args.host}:{port}/ (CTRL+C to stop)")
    try:
        while True:
            threading.Event().wait(86400)
    except KeyboardInterrupt:
        print("\nStopping Strudel proxy...")
    finally:
        proxy.stop()


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
