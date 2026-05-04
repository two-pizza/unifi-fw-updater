"""Tests for upgrade.py."""

from __future__ import annotations

import hashlib
import logging
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses
from rich.console import Console

from unifi_fw.unifi_client import UniFiClient, UniFiDevice
from unifi_fw.upgrade import (
    CONNECTED_STATE,
    FirmwareEntry,
    UpgradePlanItem,
    build_upgrade_plan,
    load_firmware_config,
    run_upgrade,
    verify_firmware_url,
)


def _device(**kwargs: object) -> UniFiDevice:
    defaults: dict[str, object] = {
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "U7PG2",
        "name": "AP-1",
        "ip": "192.168.1.100",
        "version": "6.6.77",
        "state": 1,
        "uptime": 3600,
        "device_type": "uap",
        "adopted": True,
    }
    defaults.update(kwargs)
    return UniFiDevice(**defaults)  # type: ignore[arg-type]


def _console() -> Console:
    return Console(file=StringIO(), width=200, highlight=False)


def _logger() -> logging.Logger:
    return logging.getLogger("test_upgrade")


def _plan_item(**kwargs: object) -> UpgradePlanItem:
    defaults: dict[str, object] = {
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "AP-1",
        "model": "U7PG2",
        "current_version": "6.6.0",
        "firmware_url": "http://host/fw.bin",
        "sha256": None,
        "skip": False,
        "skip_reason": "",
    }
    defaults.update(kwargs)
    return UpgradePlanItem(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# load_firmware_config
# ---------------------------------------------------------------------------


class TestLoadFirmwareConfig:
    def test_parses_valid_yaml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text(
            "devices:\n"
            "  - mac: 'AA:BB:CC:DD:EE:01'\n"
            "    model: 'U7PG2'\n"
            "    firmware_url: 'http://192.168.1.50/fw.bin'\n"
            "    sha256: 'abc123'\n"
        )
        entries = load_firmware_config(cfg)
        assert len(entries) == 1
        assert entries[0].mac == "aa:bb:cc:dd:ee:01"
        assert entries[0].sha256 == "abc123"

    def test_mac_normalized_to_lowercase(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text(
            "devices:\n  - mac: 'AA:BB:CC:DD:EE:FF'\n    firmware_url: 'http://h/fw.bin'\n"
        )
        entries = load_firmware_config(cfg)
        assert entries[0].mac == "aa:bb:cc:dd:ee:ff"

    def test_missing_sha256_defaults_to_none(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices:\n  - mac: 'aa:bb:cc:dd:ee:01'\n    firmware_url: 'http://h/fw.bin'\n")
        entries = load_firmware_config(cfg)
        assert entries[0].sha256 is None

    def test_empty_sha256_string_becomes_none(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text(
            "devices:\n"
            "  - mac: 'aa:bb:cc:dd:ee:01'\n"
            "    firmware_url: 'http://h/fw.bin'\n"
            "    sha256: ''\n"
        )
        entries = load_firmware_config(cfg)
        assert entries[0].sha256 is None


# ---------------------------------------------------------------------------
# build_upgrade_plan
# ---------------------------------------------------------------------------


class TestBuildUpgradePlan:
    def test_matches_device_by_mac(self) -> None:
        devices = [_device(mac="aa:bb:cc:dd:ee:01")]
        entries = [FirmwareEntry(mac="aa:bb:cc:dd:ee:01", model="U7PG2", firmware_url="http://h/fw.bin")]
        plan = build_upgrade_plan(devices, entries, _console())
        assert len(plan) == 1
        assert plan[0].mac == "aa:bb:cc:dd:ee:01"
        assert not plan[0].skip

    def test_skips_udr_device(self) -> None:
        devices = [_device(mac="ff:ee:dd:cc:bb:aa", device_type="udr")]
        entries = [FirmwareEntry(mac="ff:ee:dd:cc:bb:aa", model="UDR", firmware_url="http://h/fw.bin")]
        plan = build_upgrade_plan(devices, entries, _console())
        assert plan[0].skip
        assert "udr" in plan[0].skip_reason.lower()

    def test_skips_udm_device(self) -> None:
        devices = [_device(mac="ff:ee:dd:cc:bb:aa", device_type="udm")]
        entries = [FirmwareEntry(mac="ff:ee:dd:cc:bb:aa", model="UDM", firmware_url="http://h/fw.bin")]
        plan = build_upgrade_plan(devices, entries, _console())
        assert plan[0].skip

    def test_skips_ugw_device(self) -> None:
        devices = [_device(mac="ff:ee:dd:cc:bb:aa", device_type="ugw")]
        entries = [FirmwareEntry(mac="ff:ee:dd:cc:bb:aa", model="UGW", firmware_url="http://h/fw.bin")]
        plan = build_upgrade_plan(devices, entries, _console())
        assert plan[0].skip

    def test_device_not_in_network_excluded_from_plan(self) -> None:
        devices: list[UniFiDevice] = []
        entries = [FirmwareEntry(mac="aa:bb:cc:dd:ee:01", model="U7PG2", firmware_url="http://h/fw.bin")]
        plan = build_upgrade_plan(devices, entries, _console())
        assert plan == []

    def test_device_not_in_config_not_included(self) -> None:
        devices = [_device(mac="aa:bb:cc:dd:ee:99")]
        entries: list[FirmwareEntry] = []
        plan = build_upgrade_plan(devices, entries, _console())
        assert plan == []


# ---------------------------------------------------------------------------
# verify_firmware_url
# ---------------------------------------------------------------------------


class TestVerifyFirmwareUrl:
    @responses.activate
    def test_correct_sha256_does_not_raise(self) -> None:
        content = b"firmware data"
        sha = hashlib.sha256(content).hexdigest()
        responses.add(responses.GET, "http://host/fw.bin", body=content, status=200)
        verify_firmware_url("http://host/fw.bin", sha)  # must not raise

    @responses.activate
    def test_wrong_sha256_raises_value_error(self) -> None:
        content = b"firmware data"
        responses.add(responses.GET, "http://host/fw.bin", body=content, status=200)
        with pytest.raises(ValueError, match="SHA256 mismatch"):
            verify_firmware_url("http://host/fw.bin", "0" * 64)

    def test_none_sha256_skips_download(self) -> None:
        # No HTTP mock registered — would raise ConnectionError if a request were made
        verify_firmware_url("http://host/fw.bin", None)


# ---------------------------------------------------------------------------
# run_upgrade
# ---------------------------------------------------------------------------


class TestRunUpgrade:
    def _mock_client(self) -> MagicMock:
        return MagicMock(spec=UniFiClient)

    def test_calls_upgrade_external(self) -> None:
        client = self._mock_client()
        dev = _device(mac="aa:bb:cc:dd:ee:01", state=CONNECTED_STATE)
        client.get_devices.return_value = [dev]

        success = run_upgrade(client, [_plan_item()], _logger(), _console())

        client.upgrade_external.assert_called_once_with("aa:bb:cc:dd:ee:01", "http://host/fw.bin")
        assert success

    def test_skips_protected_device(self) -> None:
        client = self._mock_client()
        client.get_devices.return_value = []

        plan = [_plan_item(skip=True, skip_reason="Protected: udr")]
        success = run_upgrade(client, plan, _logger(), _console())

        client.upgrade_external.assert_not_called()
        assert success

    def test_preflight_fails_if_device_disconnected(self) -> None:
        client = self._mock_client()
        dev = _device(mac="aa:bb:cc:dd:ee:01", state=0)
        client.get_devices.return_value = [dev]

        success = run_upgrade(client, [_plan_item()], _logger(), _console())
        assert not success
        client.upgrade_external.assert_not_called()

    def test_preflight_fails_if_device_missing(self) -> None:
        client = self._mock_client()
        client.get_devices.return_value = []

        success = run_upgrade(client, [_plan_item()], _logger(), _console())
        assert not success

    def test_only_macs_filter(self) -> None:
        client = self._mock_client()
        dev1 = _device(mac="aa:bb:cc:dd:ee:01", state=CONNECTED_STATE)
        dev2 = _device(mac="aa:bb:cc:dd:ee:02", state=CONNECTED_STATE, name="AP-2")
        client.get_devices.return_value = [dev1, dev2]

        plan = [
            _plan_item(mac="aa:bb:cc:dd:ee:01"),
            _plan_item(mac="aa:bb:cc:dd:ee:02", name="AP-2"),
        ]
        success = run_upgrade(
            client, plan, _logger(), _console(), only_macs={"aa:bb:cc:dd:ee:01"}
        )

        assert success
        # only the first device should be upgraded
        assert client.upgrade_external.call_count == 1
        client.upgrade_external.assert_called_with("aa:bb:cc:dd:ee:01", "http://host/fw.bin")

    def test_timeout_returns_failure(self) -> None:
        client = self._mock_client()
        dev_connected = _device(mac="aa:bb:cc:dd:ee:01", state=CONNECTED_STATE)
        dev_upgrading = _device(mac="aa:bb:cc:dd:ee:01", state=4)  # upgrading

        call_count: list[int] = [0]

        def _side_effect() -> list[UniFiDevice]:
            call_count[0] += 1
            if call_count[0] == 1:
                return [dev_connected]   # pre-flight
            return [dev_upgrading]       # stuck in upgrading forever

        client.get_devices.side_effect = _side_effect

        with (
            patch("unifi_fw.upgrade.UPGRADE_TIMEOUT_SECONDS", 0),
            patch("unifi_fw.upgrade.POLL_INTERVAL_SECONDS", 0),
        ):
            success = run_upgrade(client, [_plan_item()], _logger(), _console())

        assert not success

    @responses.activate
    def test_sha256_mismatch_aborts(self) -> None:
        client = self._mock_client()
        dev = _device(mac="aa:bb:cc:dd:ee:01", state=CONNECTED_STATE)
        client.get_devices.return_value = [dev]

        responses.add(responses.GET, "http://host/fw.bin", body=b"wrong data", status=200)

        plan = [_plan_item(sha256="0" * 64)]
        success = run_upgrade(client, plan, _logger(), _console())

        assert not success
        client.upgrade_external.assert_not_called()
