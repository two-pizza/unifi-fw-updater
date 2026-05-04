"""Tests for firmware_resolver.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import responses

from unifi_fw.firmware_resolver import (
    PLATFORM_MAP,
    _version_to_fw_part,
    download_firmware,
    resolve_firmware_url,
)


class TestVersionToFwPart:
    def test_standard_version(self) -> None:
        assert _version_to_fw_part("6.8.2.15592") == "6.8.2+15592"

    def test_different_build(self) -> None:
        assert _version_to_fw_part("6.7.35.15586") == "6.7.35+15586"

    def test_no_dot_unchanged(self) -> None:
        assert _version_to_fw_part("noversion") == "noversion"

    def test_two_part_version(self) -> None:
        assert _version_to_fw_part("6.8") == "6+8"


class TestResolveFirmwareUrl:
    def test_known_model_returns_url(self) -> None:
        url = resolve_firmware_url("U7PG2", "6.8.2.15592")
        assert url is not None
        assert "dl.ui.com/unifi/firmware/U7PG2/6.8.2+15592" in url
        assert "BZ.qca956x_6.8.2+15592.bin" in url

    def test_ac_lite_same_platform_as_ac_pro(self) -> None:
        url = resolve_firmware_url("U7LT", "6.8.2.15592")
        assert url is not None
        assert "U7LT" in url
        assert "BZ.qca956x" in url

    def test_unknown_model_returns_none(self) -> None:
        assert resolve_firmware_url("UNKNOWN_MODEL", "6.8.2.15592") is None
        assert resolve_firmware_url("U6Lite", "6.8.2.15592") is None
        assert resolve_firmware_url("U7Pro", "6.8.2.15592") is None

    def test_url_format(self) -> None:
        url = resolve_firmware_url("U7HD", "6.8.2.15592")
        assert url == "https://dl.ui.com/unifi/firmware/U7HD/6.8.2+15592/BZ.qca956x_6.8.2+15592.bin"

    def test_all_mapped_models_return_url(self) -> None:
        for model in PLATFORM_MAP:
            url = resolve_firmware_url(model, "6.8.2.15592")
            assert url is not None, f"Expected URL for {model}"


class TestDownloadFirmware:
    @responses.activate
    def test_downloads_and_returns_sha256(self, tmp_path: Path) -> None:
        from rich.console import Console

        firmware_data = b"fake firmware binary data"
        responses.add(
            responses.GET,
            "https://dl.ui.com/unifi/firmware/U7PG2/6.8.2+15592/BZ.qca956x_6.8.2+15592.bin",
            body=firmware_data,
            status=200,
        )
        dest = tmp_path / "firmware.bin"
        sha256 = download_firmware(
            "https://dl.ui.com/unifi/firmware/U7PG2/6.8.2+15592/BZ.qca956x_6.8.2+15592.bin",
            dest,
            Console(quiet=True),
        )
        import hashlib

        expected = hashlib.sha256(firmware_data).hexdigest()
        assert sha256 == expected
        assert dest.read_bytes() == firmware_data

    @responses.activate
    def test_raises_on_http_error(self, tmp_path: Path) -> None:
        import requests as req
        from rich.console import Console

        responses.add(responses.GET, "https://dl.ui.com/fw.bin", status=404)
        with pytest.raises(req.HTTPError):
            download_firmware("https://dl.ui.com/fw.bin", tmp_path / "fw.bin", Console(quiet=True))
