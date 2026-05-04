"""Tests for cli.py — covers command functions via unit mocking."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from unifi_fw import cli as cli_module
from unifi_fw.unifi_client import UniFiDevice, UniFiLoginError

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _device(**kwargs: Any) -> UniFiDevice:
    defaults: dict[str, Any] = {
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
    return UniFiDevice(**defaults)


def _mock_client(
    *,
    login_raises: Exception | None = None,
    devices: list[UniFiDevice] | None = None,
    upgrade_external_raises: Exception | None = None,
) -> MagicMock:
    from unifi_fw.unifi_client import UniFiClient

    client = MagicMock(spec=UniFiClient)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    if login_raises:
        client.login.side_effect = login_raises
    if devices is not None:
        client.get_devices.return_value = devices
    if upgrade_external_raises:
        client.upgrade_external.side_effect = upgrade_external_raises

    return client


def _patch_client(client: MagicMock) -> Any:
    return patch("unifi_fw.cli.client_from_env", return_value=client)


def _ns(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# _cmd_inventory
# ---------------------------------------------------------------------------


class TestCmdInventory:
    def test_returns_0_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _mock_client(devices=[_device()])
        with _patch_client(client):
            code = cli_module._cmd_inventory(_ns())
        assert code == 0

    def test_returns_1_if_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with patch("unifi_fw.cli.client_from_env", side_effect=ValueError("UNIFI_HOST")):
            code = cli_module._cmd_inventory(_ns())
        assert code == 1

    def test_returns_1_on_login_failure(self) -> None:
        client = _mock_client(login_raises=UniFiLoginError("bad credentials"))
        with _patch_client(client):
            code = cli_module._cmd_inventory(_ns())
        assert code == 1

    def test_returns_1_on_connection_error(self) -> None:
        client = _mock_client(login_raises=ConnectionError("refused"))
        with _patch_client(client):
            code = cli_module._cmd_inventory(_ns())
        assert code == 1


# ---------------------------------------------------------------------------
# _cmd_health
# ---------------------------------------------------------------------------


class TestCmdHealth:
    def test_returns_0_all_online(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _mock_client(devices=[_device(state=1)])
        with _patch_client(client):
            code = cli_module._cmd_health(_ns())
        assert code == 0

    def test_returns_0_with_offline_device(self) -> None:
        client = _mock_client(devices=[_device(state=0)])
        with _patch_client(client):
            code = cli_module._cmd_health(_ns())
        assert code == 0  # health reports but still returns 0

    def test_returns_1_on_login_error(self) -> None:
        client = _mock_client(login_raises=UniFiLoginError("nope"))
        with _patch_client(client):
            code = cli_module._cmd_health(_ns())
        assert code == 1

    def test_returns_1_on_env_error(self) -> None:
        with patch("unifi_fw.cli.client_from_env", side_effect=ValueError("UNIFI_PASS")):
            code = cli_module._cmd_health(_ns())
        assert code == 1

    def test_returns_1_if_get_devices_fails(self) -> None:
        from unifi_fw.unifi_client import UniFiClient

        client = MagicMock(spec=UniFiClient)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_devices.side_effect = RuntimeError("network error")
        with _patch_client(client):
            code = cli_module._cmd_health(_ns())
        assert code == 1


# ---------------------------------------------------------------------------
# _cmd_plan
# ---------------------------------------------------------------------------


class TestCmdPlan:
    def test_returns_1_if_config_missing(self) -> None:
        code = cli_module._cmd_plan(_ns(config="/nonexistent/firmware.yaml"))
        assert code == 1

    def test_returns_0_on_success(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices:\n  - mac: 'aa:bb:cc:dd:ee:01'\n    firmware_url: 'http://h/fw.bin'\n")
        client = _mock_client(devices=[_device()])
        with _patch_client(client):
            code = cli_module._cmd_plan(_ns(config=str(cfg)))
        assert code == 0

    def test_returns_1_on_login_failure(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices: []\n")
        client = _mock_client(login_raises=UniFiLoginError("no"))
        with _patch_client(client):
            code = cli_module._cmd_plan(_ns(config=str(cfg)))
        assert code == 1

    def test_returns_1_on_invalid_yaml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices:\n  - mac: 'aa'\n    missing_firmware_url: ''\n")
        client = _mock_client(devices=[])
        with _patch_client(client):
            code = cli_module._cmd_plan(_ns(config=str(cfg)))
        assert code == 1


# ---------------------------------------------------------------------------
# _cmd_upgrade
# ---------------------------------------------------------------------------


class TestCmdUpgrade:
    def test_returns_1_if_config_missing(self) -> None:
        code = cli_module._cmd_upgrade(_ns(config="/no/such/file.yaml", only="", yes=True))
        assert code == 1

    def test_aborts_without_yes(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices: []\n")
        client = _mock_client(devices=[])
        with _patch_client(client), patch("builtins.input", return_value="n"):
            code = cli_module._cmd_upgrade(_ns(config=str(cfg), only="", yes=False))
        assert code == 0

    def test_proceeds_with_yes_flag(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices: []\n")
        client = _mock_client(devices=[])
        with _patch_client(client):
            code = cli_module._cmd_upgrade(_ns(config=str(cfg), only="", yes=True))
        assert code == 0

    def test_returns_2_on_upgrade_failure(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text(
            "devices:\n  - mac: 'aa:bb:cc:dd:ee:01'\n    firmware_url: 'http://h/fw.bin'\n"
        )
        # device is disconnected → pre-flight fails → run_upgrade returns False
        client = _mock_client(devices=[_device(state=0)])
        with _patch_client(client):
            code = cli_module._cmd_upgrade(_ns(config=str(cfg), only="", yes=True))
        assert code == 2

    def test_only_macs_parsed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices: []\n")
        client = _mock_client(devices=[])

        captured_only: list[set[str] | None] = []

        def _fake_run_upgrade(
            _c: Any, _p: Any, _l: Any, _console: Any, only_macs: set[str] | None = None
        ) -> bool:
            captured_only.append(only_macs)
            return True

        run_patch = patch("unifi_fw.cli.run_upgrade", side_effect=_fake_run_upgrade)
        with _patch_client(client), run_patch:
            cli_module._cmd_upgrade(
                _ns(config=str(cfg), only="AA:BB:CC:DD:EE:01,AA:BB:CC:DD:EE:02", yes=True)
            )

        assert captured_only[0] == {"aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"}

    def test_returns_1_on_env_error(self, tmp_path: Path) -> None:
        cfg = tmp_path / "firmware.yaml"
        cfg.write_text("devices: []\n")
        with patch("unifi_fw.cli.client_from_env", side_effect=ValueError("UNIFI_HOST")):
            code = cli_module._cmd_upgrade(_ns(config=str(cfg), only="", yes=True))
        assert code == 1


# ---------------------------------------------------------------------------
# build_parser / main
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_inventory_command_parsed(self) -> None:
        parser = cli_module._build_parser()
        args = parser.parse_args(["inventory"])
        assert args.command == "inventory"

    def test_health_command_parsed(self) -> None:
        parser = cli_module._build_parser()
        args = parser.parse_args(["health"])
        assert args.command == "health"

    def test_plan_defaults(self) -> None:
        parser = cli_module._build_parser()
        args = parser.parse_args(["plan"])
        assert args.config == "firmware.yaml"

    def test_upgrade_flags(self) -> None:
        parser = cli_module._build_parser()
        args = parser.parse_args(["upgrade", "--config", "fw.yaml", "--only", "aa:bb", "--yes"])
        assert args.config == "fw.yaml"
        assert args.only == "aa:bb"
        assert args.yes is True

    def test_upgrade_yes_default_false(self) -> None:
        parser = cli_module._build_parser()
        args = parser.parse_args(["upgrade"])
        assert args.yes is False
