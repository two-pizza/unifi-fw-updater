"""Fully automatic firmware upgrade — discovers devices and handles everything."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .firmware_resolver import download_firmware, resolve_firmware_url
from .local_server import FirmwareServer, get_local_ip
from .unifi_client import PROTECTED_DEVICE_TYPES, UniFiClient, UniFiDevice
from .upgrade import CONNECTED_STATE, UPGRADE_TIMEOUT_SECONDS, wait_for_connected


def find_upgradeable(devices: list[UniFiDevice]) -> list[tuple[UniFiDevice, str]]:
    """Return (device, target_version) for all upgradeable connected devices."""
    result: list[tuple[UniFiDevice, str]] = []
    for d in devices:
        if d.device_type in PROTECTED_DEVICE_TYPES:
            continue
        if not d.adopted or d.state != CONNECTED_STATE:
            continue
        if d.upgrade_to_firmware:
            result.append((d, d.upgrade_to_firmware))
    return result


def print_auto_plan(items: list[tuple[UniFiDevice, str]], console: Console) -> None:
    table = Table(title="Auto Upgrade Plan", header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Model")
    table.add_column("Current")
    table.add_column("Target")
    table.add_column("Method")

    for device, target in items:
        url = resolve_firmware_url(device.model, target)
        method = "local (dl.ui.com)" if url else "built-in (controller)"
        table.add_row(device.name, device.model, device.version, target, method)

    console.print(table)


def run_auto_upgrade(
    client: UniFiClient,
    logger: logging.Logger,
    console: Console,
    yes: bool = False,
) -> bool:
    devices = client.get_devices()
    items = find_upgradeable(devices)

    if not items:
        console.print("[green]✓ All devices are up to date.[/green]")
        return True

    print_auto_plan(items, console)

    if not yes:
        try:
            answer = input("\nProceed with upgrade? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            console.print("Aborted.")
            return True

    local_ip = get_local_ip(client.host)
    console.print(f"[dim]Serving firmware from {local_ip}[/dim]")

    with tempfile.TemporaryDirectory(prefix="unifi_fw_") as tmpdir:
        fw_dir = Path(tmpdir)
        server = FirmwareServer(fw_dir)
        server.start(local_ip)
        console.print(f"[dim]HTTP server: http://{local_ip}:{server.port}/[/dim]")
        try:
            return _upgrade_all(client, items, server, fw_dir, logger, console)
        finally:
            server.stop()


def _upgrade_all(
    client: UniFiClient,
    items: list[tuple[UniFiDevice, str]],
    server: FirmwareServer,
    fw_dir: Path,
    logger: logging.Logger,
    console: Console,
) -> bool:
    downloaded: dict[str, Path] = {}  # dl_url → local path

    for device, target in items:
        console.print(f"\n[bold cyan]▶ Upgrading {device.name} ({device.mac})[/bold cyan]")
        console.print(f"  [dim]{device.version} → {target}[/dim]")
        logger.info("Auto upgrade: %s %s → %s", device.mac, device.version, target)

        dl_url = resolve_firmware_url(device.model, target)
        used_external = False

        if dl_url:
            filename = dl_url.split("/")[-1]
            local_path = fw_dir / filename

            if dl_url not in downloaded:
                try:
                    download_firmware(dl_url, local_path, console)
                    downloaded[dl_url] = local_path
                except Exception as exc:
                    console.print(
                        f"  [yellow]⚠ Download failed ({exc}), falling back to built-in[/yellow]"
                    )
                    logger.warning("Download failed %s: %s — falling back", device.mac, exc)
                    dl_url = None

            if dl_url:
                serve_url = server.url_for(filename)
                try:
                    client.upgrade_external(device.mac, serve_url)
                    used_external = True
                except Exception as exc:
                    console.print(f"  [red]✗ upgrade-external failed: {exc}[/red]")
                    logger.error("upgrade-external failed %s: %s", device.mac, exc)
                    return False

        if not used_external:
            console.print(
                f"  [dim]Model {device.model} — using built-in upgrade (controller downloads)[/dim]"
            )
            try:
                client.upgrade_builtin(device.mac)
            except Exception as exc:
                console.print(f"  [red]✗ upgrade command failed: {exc}[/red]")
                logger.error("upgrade_builtin failed %s: %s", device.mac, exc)
                return False

        console.print(f"  Polling for reconnect (timeout {UPGRADE_TIMEOUT_SECONDS}s) …")
        result = wait_for_connected(client, device.mac, UPGRADE_TIMEOUT_SECONDS, logger, console)

        if result is None:
            console.print(f"  [red]✗ Timeout: {device.name} did not reconnect[/red]")
            logger.error("Timeout waiting for %s", device.mac)
            return False

        console.print(f"  [green]✓ {device.name} online — version: {result.version}[/green]")
        logger.info("Auto upgrade done: %s new version=%s", device.mac, result.version)

    return True
