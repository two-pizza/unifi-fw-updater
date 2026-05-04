"""Tests for local_server.py."""

from __future__ import annotations

import urllib.request
from pathlib import Path

from unifi_fw.local_server import FirmwareServer


class TestFirmwareServer:
    def test_starts_and_serves_file(self, tmp_path: Path) -> None:
        (tmp_path / "test.bin").write_bytes(b"firmware")
        server = FirmwareServer(tmp_path)
        server.start("127.0.0.1")
        try:
            assert server.port > 0
            assert server.local_ip == "127.0.0.1"
            url = server.url_for("test.bin")
            assert url == f"http://127.0.0.1:{server.port}/test.bin"
            with urllib.request.urlopen(url) as resp:
                assert resp.read() == b"firmware"
        finally:
            server.stop()

    def test_stop_cleans_up(self, tmp_path: Path) -> None:
        server = FirmwareServer(tmp_path)
        server.start("127.0.0.1")
        server.stop()
        assert server._httpd is None

    def test_url_for_format(self, tmp_path: Path) -> None:
        server = FirmwareServer(tmp_path)
        server.start("192.168.1.100")
        try:
            url = server.url_for("BZ.qca956x_6.8.2+15592.bin")
            assert url.startswith("http://192.168.1.100:")
            assert url.endswith("/BZ.qca956x_6.8.2+15592.bin")
        finally:
            server.stop()

    def test_multiple_files_served(self, tmp_path: Path) -> None:
        (tmp_path / "fw1.bin").write_bytes(b"fw1")
        (tmp_path / "fw2.bin").write_bytes(b"fw2")
        server = FirmwareServer(tmp_path)
        server.start("127.0.0.1")
        try:
            for name, expected in [("fw1.bin", b"fw1"), ("fw2.bin", b"fw2")]:
                with urllib.request.urlopen(server.url_for(name)) as resp:
                    assert resp.read() == expected
        finally:
            server.stop()
