"""Firmware upgrade orchestration."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
import yaml
from rich.console import Console
from rich.table import Table

from .unifi_client import PROTECTED_DEVICE_TYPES, UniFiClient, UniFiDevice

UPGRADE_TIMEOUT_SECONDS = 900   # 15 minutes per device
POLL_INTERVAL_SECONDS = 10
CONNECTED_STATE = 1


@dataclass
class FirmwareEntry:
    mac: str
    model: str
    firmware_url: str
    sha256: str | None = field(default=None)


@dataclass
class UpgradePlanItem:
    mac: str
    name: str
    model: str
    current_version: str
    firmware_url: str
    sha256: str | None
    skip: bool = False
    skip_reason: str = ""


def load_firmware_config(config_path: Path) -> list[FirmwareEntry]:
    with config_path.open() as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    entries: list[FirmwareEntry] = []
    for item in data.get("devices", []):
        raw: dict[str, Any] = item
        sha256_raw = raw.get("sha256") or None
        entries.append(
            FirmwareEntry(
                mac=str(raw["mac"]).lower(),
                model=str(raw.get("model", "")),
                firmware_url=str(raw["firmware_url"]),
                sha256=str(sha256_raw) if sha256_raw else None,
            )
        )
    return entries


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_firmware_url(url: str, expected_sha256: str | None) -> None:
    """Download firmware from *url* and verify its SHA-256 if *expected_sha256* is given."""
    if not expected_sha256:
        return
    resp = requests.get(url, timeout=(5, 120), verify=False)  # noqa: S501
    resp.raise_for_status()
    actual = compute_sha256(resp.content)
    if actual != expected_sha256.lower():
        raise ValueError(
            f"SHA256 mismatch for {url}: expected {expected_sha256}, got {actual}"
        )


def build_upgrade_plan(
    devices: list[UniFiDevice],
    firmware_entries: list[FirmwareEntry],
    console: Console,
) -> list[UpgradePlanItem]:
    device_by_mac: dict[str, UniFiDevice] = {d.mac.lower(): d for d in devices}
    planned_macs: set[str] = set()
    plan: list[UpgradePlanItem] = []

    for entry in firmware_entries:
        mac = entry.mac.lower()
        planned_macs.add(mac)

        if mac not in device_by_mac:
            console.print(
                f"[yellow]⚠ Device {mac} not found in network inventory — skipping[/yellow]"
            )
            continue

        device = device_by_mac[mac]
        item = UpgradePlanItem(
            mac=mac,
            name=device.name,
            model=device.model,
            current_version=device.version,
            firmware_url=entry.firmware_url,
            sha256=entry.sha256,
        )

        if device.device_type in PROTECTED_DEVICE_TYPES:
            item.skip = True
            item.skip_reason = (
                f"Protected device type: {device.device_type} — upgrade manually via UniFi OS UI"
            )

        plan.append(item)

    for mac, device in device_by_mac.items():
        if mac not in planned_macs:
            console.print(
                f"[dim]ℹ {device.name} ({mac}) not in firmware config — skipping[/dim]"
            )

    return plan


def print_upgrade_plan(plan: list[UpgradePlanItem], console: Console) -> None:
    table = Table(title="Upgrade Plan", header_style="bold cyan")
    table.add_column("Name")
    table.add_column("MAC")
    table.add_column("Model")
    table.add_column("Current Version")
    table.add_column("Firmware URL")
    table.add_column("Action")

    for item in plan:
        if item.skip:
            action = f"[red]SKIP: {item.skip_reason}[/red]"
        else:
            action = "[green]UPGRADE[/green]"

        table.add_row(
            item.name,
            item.mac,
            item.model,
            item.current_version,
            item.firmware_url,
            action,
        )

    console.print(table)


def wait_for_connected(
    client: UniFiClient,
    mac: str,
    timeout: int,
    logger: logging.Logger,
    console: Console,
) -> UniFiDevice | None:
    start = time.monotonic()
    last_state: int | None = None

    while time.monotonic() - start < timeout:
        try:
            devices = client.get_devices()
            device = next((d for d in devices if d.mac.lower() == mac.lower()), None)
            if device is None:
                logger.warning("Device %s not found during polling", mac)
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            if device.state != last_state:
                from .inventory import get_state_label

                label = get_state_label(device.state)
                logger.info("Device %s state → %s (%d)", mac, label, device.state)
                console.print(f"  [dim]  state: {label}[/dim]")
                last_state = device.state

            if device.state == CONNECTED_STATE:
                return device

        except Exception as exc:
            logger.warning("Poll error for %s: %s", mac, exc)

        time.sleep(POLL_INTERVAL_SECONDS)

    return None


def run_upgrade(
    client: UniFiClient,
    plan: list[UpgradePlanItem],
    logger: logging.Logger,
    console: Console,
    only_macs: set[str] | None = None,
) -> bool:
    """Execute upgrades sequentially. Returns True if all succeeded."""
    active_items = [
        item
        for item in plan
        if not item.skip and (only_macs is None or item.mac.lower() in only_macs)
    ]

    # Pre-flight: every target device must be connected
    if active_items:
        devices = client.get_devices()
        device_by_mac: dict[str, UniFiDevice] = {d.mac.lower(): d for d in devices}

        for item in active_items:
            dev = device_by_mac.get(item.mac.lower())
            if dev is None:
                console.print(f"[red]✗ Device {item.mac} not found before upgrade[/red]")
                logger.error("Pre-flight: %s not found", item.mac)
                return False
            if dev.state != CONNECTED_STATE:
                from .inventory import get_state_label

                console.print(
                    f"[red]✗ {item.name} ({item.mac}) is not connected "
                    f"(state={get_state_label(dev.state)})[/red]"
                )
                logger.error("Pre-flight: %s state=%d", item.mac, dev.state)
                return False

    for item in plan:
        if item.skip:
            logger.warning("Skipping %s: %s", item.mac, item.skip_reason)
            console.print(
                f"[yellow]⚠ Skipping {item.name} ({item.mac}): {item.skip_reason}[/yellow]"
            )
            continue

        if only_macs is not None and item.mac.lower() not in only_macs:
            continue

        console.print(f"\n[bold cyan]▶ Upgrading {item.name} ({item.mac})[/bold cyan]")
        logger.info("Starting upgrade: %s (%s) → %s", item.mac, item.name, item.firmware_url)

        if item.sha256:
            console.print(f"  Verifying SHA256 for [dim]{item.firmware_url}[/dim] …")
            try:
                verify_firmware_url(item.firmware_url, item.sha256)
                console.print("  [green]✓ SHA256 OK[/green]")
                logger.info("SHA256 verified for %s", item.mac)
            except ValueError as exc:
                console.print(f"  [red]✗ {exc}[/red]")
                logger.error("SHA256 mismatch for %s: %s", item.mac, exc)
                return False
            except requests.RequestException as exc:
                console.print(f"  [red]✗ Failed to download firmware for verification: {exc}[/red]")
                logger.error("Firmware download failed for %s: %s", item.mac, exc)
                return False

        try:
            client.upgrade_external(item.mac, item.firmware_url)
        except Exception as exc:
            console.print(f"  [red]✗ upgrade-external command failed: {exc}[/red]")
            logger.error("upgrade-external failed for %s: %s", item.mac, exc)
            return False

        console.print(
            f"  Command sent. Polling for reconnect (timeout {UPGRADE_TIMEOUT_SECONDS}s) …"
        )

        result = wait_for_connected(
            client, item.mac, UPGRADE_TIMEOUT_SECONDS, logger, console
        )

        if result is None:
            console.print(
                f"  [red]✗ Timeout: {item.name} did not return to connected state[/red]"
            )
            logger.error("Timeout waiting for %s to reconnect", item.mac)
            return False

        console.print(
            f"  [green]✓ {item.name} online. Version: {result.version}[/green]"
        )
        logger.info("Upgrade complete: %s new version=%s", item.mac, result.version)

    return True
