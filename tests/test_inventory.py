"""Tests for inventory.py."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from unifi_fw.inventory import format_uptime, get_state_label, print_inventory
from unifi_fw.unifi_client import UniFiDevice


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


class TestFormatUptime:
    def test_minutes_only(self) -> None:
        assert format_uptime(300) == "5m"

    def test_one_hour(self) -> None:
        assert format_uptime(3600) == "1h 0m"

    def test_hours_and_minutes(self) -> None:
        assert format_uptime(3900) == "1h 5m"

    def test_days_hours_minutes(self) -> None:
        assert format_uptime(90000) == "1d 1h 0m"

    def test_zero(self) -> None:
        assert format_uptime(0) == "0m"


class TestGetStateLabel:
    def test_connected(self) -> None:
        assert get_state_label(1) == "connected"

    def test_disconnected(self) -> None:
        assert get_state_label(0) == "disconnected"

    def test_upgrading(self) -> None:
        assert get_state_label(4) == "upgrading"

    def test_provisioning(self) -> None:
        assert get_state_label(5) == "provisioning"

    def test_unknown_state(self) -> None:
        label = get_state_label(99)
        assert "unknown" in label
        assert "99" in label


class TestPrintInventory:
    def test_lists_device_names(self) -> None:
        devices = [_device(name="AP-Living"), _device(mac="aa:bb:cc:dd:ee:02", name="AP-Office")]
        c = _console()
        print_inventory(devices, c)
        out = c.file.getvalue()  # type: ignore[union-attr]
        assert "AP-Living" in out
        assert "AP-Office" in out

    def test_protected_device_shows_note(self) -> None:
        devices = [_device(device_type="udr", name="Dream Router")]
        c = _console()
        print_inventory(devices, c)
        out = c.file.getvalue()  # type: ignore[union-attr]
        assert "PROTECTED" in out

    def test_regular_device_has_no_note(self) -> None:
        devices = [_device(device_type="uap", name="AP-1")]
        c = _console()
        print_inventory(devices, c)
        out = c.file.getvalue()  # type: ignore[union-attr]
        assert "PROTECTED" not in out

    def test_shows_total_count(self) -> None:
        devices = [_device(), _device(mac="aa:bb:cc:dd:ee:02")]
        c = _console()
        print_inventory(devices, c)
        out = c.file.getvalue()  # type: ignore[union-attr]
        assert "2" in out

    def test_empty_list(self) -> None:
        c = _console()
        print_inventory([], c)
        out = c.file.getvalue()  # type: ignore[union-attr]
        assert "0" in out
