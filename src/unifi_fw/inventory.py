"""Device inventory formatting."""

from __future__ import annotations

import datetime

from rich.console import Console
from rich.table import Table

from .unifi_client import PROTECTED_DEVICE_TYPES, UniFiDevice

STATE_LABELS: dict[int, str] = {
    0: "disconnected",
    1: "connected",
    2: "pending",
    4: "upgrading",
    5: "provisioning",
    6: "heartbeat missed",
    7: "adopting",
    9: "adoption failed",
    11: "isolated",
}


def format_uptime(seconds: int) -> str:
    td = datetime.timedelta(seconds=seconds)
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_state_label(state: int) -> str:
    return STATE_LABELS.get(state, f"unknown({state})")


def print_inventory(devices: list[UniFiDevice], console: Console | None = None) -> None:
    if console is None:
        console = Console()

    table = Table(title="UniFi Device Inventory", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="white", no_wrap=True)
    table.add_column("Model", style="cyan")
    table.add_column("MAC", style="dim")
    table.add_column("IP", style="green")
    table.add_column("Version", style="yellow")
    table.add_column("State")
    table.add_column("Uptime", style="dim")
    table.add_column("Note", style="dim red")

    for d in devices:
        state_label = get_state_label(d.state)
        note = "[PROTECTED — upgrade via UI]" if d.device_type in PROTECTED_DEVICE_TYPES else ""

        if d.state == 1:
            state_cell = f"[green]{state_label}[/green]"
        elif d.state == 0:
            state_cell = f"[red]{state_label}[/red]"
        else:
            state_cell = f"[yellow]{state_label}[/yellow]"

        table.add_row(
            d.name,
            d.model,
            d.mac,
            d.ip,
            d.version,
            state_cell,
            format_uptime(d.uptime),
            note,
        )

    console.print(table)
    console.print(f"[dim]Total: {len(devices)} device(s)[/dim]")
