"""CLI entry point: python -m unifi_fw <command> [options]."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from rich.console import Console

from .auto_upgrade import run_auto_upgrade
from .inventory import get_state_label, print_inventory
from .unifi_client import UniFiLoginError, client_from_env
from .upgrade import (
    CONNECTED_STATE,
    build_upgrade_plan,
    load_firmware_config,
    print_upgrade_plan,
    run_upgrade,
)

_console = Console()

_CommandHandler = Callable[[argparse.Namespace], int]


def _setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"upgrade-{stamp}.log"

    logger = logging.getLogger("unifi_fw")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
    logger.addHandler(fh)
    return logger


def _cmd_inventory(_args: argparse.Namespace) -> int:
    try:
        client = client_from_env()
    except ValueError as exc:
        _console.print(f"[red]Error: {exc}[/red]")
        return 1

    with client:
        try:
            client.login()
        except UniFiLoginError as exc:
            _console.print(f"[red]Login failed: {exc}[/red]")
            return 1
        except Exception as exc:
            _console.print(f"[red]Connection error: {exc}[/red]")
            return 1

        devices = client.get_devices()

    print_inventory(devices, _console)
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if not config_path.exists():
        _console.print(f"[red]Config file not found: {config_path}[/red]")
        return 1

    try:
        entries = load_firmware_config(config_path)
    except Exception as exc:
        _console.print(f"[red]Failed to load config: {exc}[/red]")
        return 1

    try:
        client = client_from_env()
    except ValueError as exc:
        _console.print(f"[red]Error: {exc}[/red]")
        return 1

    with client:
        try:
            client.login()
        except UniFiLoginError as exc:
            _console.print(f"[red]Login failed: {exc}[/red]")
            return 1

        devices = client.get_devices()

    plan = build_upgrade_plan(devices, entries, _console)
    print_upgrade_plan(plan, _console)
    return 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if not config_path.exists():
        _console.print(f"[red]Config file not found: {config_path}[/red]")
        return 1

    try:
        entries = load_firmware_config(config_path)
    except Exception as exc:
        _console.print(f"[red]Failed to load config: {exc}[/red]")
        return 1

    only_macs: set[str] | None = None
    if args.only:
        only_macs = {m.strip().lower() for m in args.only.split(",") if m.strip()}

    logger = _setup_logger(Path("logs"))

    try:
        client = client_from_env()
    except ValueError as exc:
        _console.print(f"[red]Error: {exc}[/red]")
        return 1

    with client:
        try:
            client.login()
        except UniFiLoginError as exc:
            _console.print(f"[red]Login failed: {exc}[/red]")
            return 1

        devices = client.get_devices()
        plan = build_upgrade_plan(devices, entries, _console)
        print_upgrade_plan(plan, _console)

        if not args.yes:
            try:
                answer = input("\nProceed with upgrade? [y/N]: ").strip().lower()
            except EOFError:
                answer = ""
            if answer != "y":
                _console.print("Aborted.")
                return 0

        success = run_upgrade(client, plan, logger, _console, only_macs)

    if not success:
        _console.print("\n[red]✗ Upgrade failed — check logs for details.[/red]")
        return 2

    _console.print("\n[green]✓ All upgrades completed successfully.[/green]")
    return 0


def _cmd_auto(args: argparse.Namespace) -> int:
    try:
        client = client_from_env()
    except ValueError as exc:
        _console.print(f"[red]Error: {exc}[/red]")
        return 1

    logger = _setup_logger(Path("logs"))

    with client:
        try:
            client.login()
        except UniFiLoginError as exc:
            _console.print(f"[red]Login failed: {exc}[/red]")
            return 1
        except Exception as exc:
            _console.print(f"[red]Connection error: {exc}[/red]")
            return 1

        success = run_auto_upgrade(client, logger, _console, yes=args.yes)

    if not success:
        _console.print("\n[red]✗ Upgrade failed — check logs for details.[/red]")
        return 2

    return 0


def _cmd_health(_args: argparse.Namespace) -> int:
    host = os.environ.get("UNIFI_HOST", "?")
    site = os.environ.get("UNIFI_SITE", "default")

    try:
        client = client_from_env()
    except ValueError as exc:
        _console.print(f"[red]Error: {exc}[/red]")
        return 1

    _console.print(f"Connecting to [cyan]{host}[/cyan]  site=[cyan]{site}[/cyan] …")

    with client:
        try:
            client.login()
            _console.print("[green]✓ Login OK[/green]")
        except UniFiLoginError as exc:
            _console.print(f"[red]✗ Login failed: {exc}[/red]")
            return 1
        except Exception as exc:
            _console.print(f"[red]✗ Connection error: {exc}[/red]")
            return 1

        try:
            devices = client.get_devices()
        except Exception as exc:
            _console.print(f"[red]✗ Failed to fetch device list: {exc}[/red]")
            return 1

    _console.print(f"[green]✓ Site OK[/green] — [bold]{len(devices)}[/bold] device(s) found")

    offline = [d for d in devices if d.state != CONNECTED_STATE]
    if offline:
        _console.print(f"[yellow]⚠ {len(offline)} offline device(s):[/yellow]")
        for d in offline:
            _console.print(f"  - {d.name} ({d.mac})  state={get_state_label(d.state)}")
    else:
        _console.print("[green]✓ All devices online[/green]")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m unifi_fw",
        description="UniFi local firmware updater",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inventory", help="List all managed devices")
    sub.add_parser("health", help="Quick connectivity and device health check")

    plan_p = sub.add_parser("plan", help="Show what would be upgraded")
    plan_p.add_argument("--config", default="firmware.yaml", metavar="FILE")

    upg_p = sub.add_parser("upgrade", help="Run firmware upgrades")
    upg_p.add_argument("--config", default="firmware.yaml", metavar="FILE")
    upg_p.add_argument(
        "--only",
        default="",
        metavar="MAC[,MAC…]",
        help="Comma-separated list of MACs to limit upgrade to",
    )
    upg_p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    auto_p = sub.add_parser(
        "auto",
        help="Auto-discover devices, download firmware, and upgrade — no config file needed",
    )
    auto_p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    return parser


def main() -> NoReturn:
    parser = _build_parser()
    args = parser.parse_args()

    handlers: dict[str, _CommandHandler] = {
        "inventory": _cmd_inventory,
        "plan": _cmd_plan,
        "upgrade": _cmd_upgrade,
        "auto": _cmd_auto,
        "health": _cmd_health,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
