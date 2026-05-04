"""Tests for auto_upgrade.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from unifi_fw.auto_upgrade import find_upgradeable, print_auto_plan, run_auto_upgrade
from unifi_fw.unifi_client import UniFiDevice

_CONNECTED = 1


def _make_device(
    mac: str = "aa:bb:cc:dd:ee:01",
    model: str = "U7PG2",
    device_type: str = "uap",
    state: int = _CONNECTED,
    adopted: bool = True,
    version: str = "6.6.77",
    upgrade_to_firmware: str = "6.8.2.15592",
) -> UniFiDevice:
    return UniFiDevice(
        mac=mac,
        model=model,
        name="Test-AP",
        ip="192.168.1.100",
        version=version,
        state=state,
        uptime=3600,
        device_type=device_type,
        adopted=adopted,
        upgrade_to_firmware=upgrade_to_firmware,
    )


class TestFindUpgradeable:
    def test_returns_upgradeable_devices(self) -> None:
        dev = _make_device()
        result = find_upgradeable([dev])
        assert len(result) == 1
        assert result[0] == (dev, "6.8.2.15592")

    def test_skips_protected_types(self) -> None:
        for dtype in ("udm", "udr", "ugw", "uxg"):
            dev = _make_device(device_type=dtype)
            assert find_upgradeable([dev]) == []

    def test_skips_disconnected(self) -> None:
        dev = _make_device(state=0)
        assert find_upgradeable([dev]) == []

    def test_skips_not_adopted(self) -> None:
        dev = _make_device(adopted=False)
        assert find_upgradeable([dev]) == []

    def test_skips_no_upgrade_target(self) -> None:
        dev = _make_device(upgrade_to_firmware="")
        assert find_upgradeable([dev]) == []

    def test_mixed_list(self) -> None:
        upgradeable = _make_device(mac="aa:bb:cc:dd:ee:01")
        protected = _make_device(mac="aa:bb:cc:dd:ee:02", device_type="udr")
        offline = _make_device(mac="aa:bb:cc:dd:ee:03", state=0)
        result = find_upgradeable([upgradeable, protected, offline])
        assert len(result) == 1
        assert result[0][0] == upgradeable


class TestPrintAutoPlan:
    def test_runs_without_error(self) -> None:
        from rich.console import Console

        dev = _make_device()
        print_auto_plan([(dev, "6.8.2.15592")], Console(quiet=True))

    def test_unknown_model_shows_builtin(self) -> None:
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, highlight=False)
        dev = _make_device(model="UNKNOWN_XYZ")
        print_auto_plan([(dev, "6.8.2.15592")], console)
        assert "built-in" in buf.getvalue()

    def test_known_model_shows_local(self) -> None:
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, highlight=False)
        dev = _make_device(model="U7PG2")
        print_auto_plan([(dev, "6.8.2.15592")], console)
        assert "local" in buf.getvalue()


class TestRunAutoUpgrade:
    def test_returns_true_when_no_upgrades(self) -> None:
        from rich.console import Console

        client = MagicMock()
        client.get_devices.return_value = [_make_device(upgrade_to_firmware="")]
        result = run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=True)
        assert result is True
        client.upgrade_external.assert_not_called()

    def test_external_upgrade_path(self, tmp_path: object) -> None:
        from rich.console import Console

        device = _make_device()
        upgraded = _make_device(version="6.8.2.15592", upgrade_to_firmware="")

        client = MagicMock()
        client.host = "https://192.168.1.1"
        client.get_devices.return_value = [device]

        with (
            patch("unifi_fw.auto_upgrade.get_local_ip", return_value="127.0.0.1"),
            patch("unifi_fw.auto_upgrade.download_firmware", return_value="abc123"),
            patch("unifi_fw.auto_upgrade.wait_for_connected", return_value=upgraded),
        ):
            result = run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=True)

        assert result is True
        client.upgrade_external.assert_called_once()

    def test_builtin_fallback_for_unknown_model(self) -> None:
        from rich.console import Console

        device = _make_device(model="UNKNOWN_MODEL")
        upgraded = _make_device(
            model="UNKNOWN_MODEL", version="6.8.2.15592", upgrade_to_firmware=""
        )

        client = MagicMock()
        client.host = "https://192.168.1.1"
        client.get_devices.return_value = [device]

        with (
            patch("unifi_fw.auto_upgrade.get_local_ip", return_value="127.0.0.1"),
            patch("unifi_fw.auto_upgrade.wait_for_connected", return_value=upgraded),
        ):
            result = run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=True)

        assert result is True
        client.upgrade_builtin.assert_called_once_with(device.mac)
        client.upgrade_external.assert_not_called()

    def test_download_failure_falls_back_to_builtin(self) -> None:
        from rich.console import Console

        device = _make_device()
        upgraded = _make_device(version="6.8.2.15592", upgrade_to_firmware="")

        client = MagicMock()
        client.host = "https://192.168.1.1"
        client.get_devices.return_value = [device]

        with (
            patch("unifi_fw.auto_upgrade.get_local_ip", return_value="127.0.0.1"),
            patch("unifi_fw.auto_upgrade.download_firmware", side_effect=Exception("timeout")),
            patch("unifi_fw.auto_upgrade.wait_for_connected", return_value=upgraded),
        ):
            result = run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=True)

        assert result is True
        client.upgrade_builtin.assert_called_once()

    def test_returns_false_on_timeout(self) -> None:
        from rich.console import Console

        device = _make_device()
        client = MagicMock()
        client.host = "https://192.168.1.1"
        client.get_devices.return_value = [device]

        with (
            patch("unifi_fw.auto_upgrade.get_local_ip", return_value="127.0.0.1"),
            patch("unifi_fw.auto_upgrade.download_firmware", return_value="abc123"),
            patch("unifi_fw.auto_upgrade.wait_for_connected", return_value=None),
        ):
            result = run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=True)

        assert result is False

    def test_aborts_on_no_confirmation(self) -> None:
        from rich.console import Console

        device = _make_device()
        client = MagicMock()
        client.get_devices.return_value = [device]

        with patch("builtins.input", return_value="n"):
            result = run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=False)

        assert result is True  # aborted cleanly
        client.upgrade_external.assert_not_called()

    def test_caches_firmware_for_same_model(self) -> None:
        from rich.console import Console

        devices = [
            _make_device(mac="aa:bb:cc:dd:ee:01"),
            _make_device(mac="aa:bb:cc:dd:ee:02"),
        ]
        upgraded = _make_device(version="6.8.2.15592", upgrade_to_firmware="")

        client = MagicMock()
        client.host = "https://192.168.1.1"
        client.get_devices.return_value = devices

        download_mock = MagicMock(return_value="abc123")
        with (
            patch("unifi_fw.auto_upgrade.get_local_ip", return_value="127.0.0.1"),
            patch("unifi_fw.auto_upgrade.download_firmware", download_mock),
            patch("unifi_fw.auto_upgrade.wait_for_connected", return_value=upgraded),
        ):
            run_auto_upgrade(client, MagicMock(), Console(quiet=True), yes=True)

        # Same firmware file downloaded only once for two devices
        assert download_mock.call_count == 1
