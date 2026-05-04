"""Minimal HTTP server for serving firmware files to UniFi devices."""

from __future__ import annotations

import http.server
import socket
import threading
from pathlib import Path


def get_local_ip(unifi_host: str) -> str:
    """Return the local IP on the interface that can reach unifi_host."""
    host = unifi_host.removeprefix("https://").removeprefix("http://").split(":")[0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, 80))
        ip: str = sock.getsockname()[0]
        return ip


class FirmwareServer:
    """Thread-backed HTTP server that serves files from a directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._httpd: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0
        self.local_ip: str = ""

    def start(self, local_ip: str) -> None:
        self.local_ip = local_ip
        directory = str(self._directory)

        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self_, *args: object, **kwargs: object) -> None:
                super().__init__(*args, directory=directory, **kwargs)  # type: ignore[arg-type]

            def log_message(self_, _fmt: str, *_args: object) -> None:
                pass  # silence access log

        self._httpd = http.server.HTTPServer(("0.0.0.0", 0), _Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def url_for(self, filename: str) -> str:
        return f"http://{self.local_ip}:{self.port}/{filename}"

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
