"""Resolve and download firmware for known UniFi AP models."""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from rich.console import Console

# Maps UniFi model codes → BZ firmware platform string.
# All AC-series share the qca956x platform.
# Models not listed here fall back to the controller's built-in upgrade.
PLATFORM_MAP: dict[str, str] = {
    "U7PG2": "qca956x",   # UAP-AC-Pro
    "U7LT": "qca956x",    # UAP-AC-Lite
    "U7HD": "qca956x",    # UAP-AC-HD
    "U7SHD": "qca956x",   # UAP-AC-SHD
    "U7NHD": "qca956x",   # UAP-nanoHD
    "U7MSH": "qca956x",   # UAP-AC-Mesh
    "U7MP": "qca956x",    # UAP-AC-Mesh-Pro
    "U7IW": "qca956x",    # UAP-AC-IW
    "U7O": "qca956x",     # UAP-AC-Outdoor
    "U7Ev2": "qca956x",   # UAP-AC-Edu v2
    "U5O": "qca956x",     # UAP-Outdoor+
    "ULTE": "qca956x",    # UAP-AC-LR
    "U2HSR": "qca956x",   # UAP-Outdoor+ (legacy)
    "U2OSR": "qca956x",   # UAP-Outdoor+ SR
}

_DL_BASE = "https://dl.ui.com/unifi/firmware"


def _version_to_fw_part(version: str) -> str:
    """Convert '6.8.2.15592' → '6.8.2+15592' for use in download URLs."""
    last_dot = version.rfind(".")
    if last_dot == -1:
        return version
    return version[:last_dot] + "+" + version[last_dot + 1:]


def resolve_firmware_url(model: str, target_version: str) -> str | None:
    """Return the dl.ui.com download URL for a known model, or None."""
    platform = PLATFORM_MAP.get(model)
    if not platform:
        return None
    fw_ver = _version_to_fw_part(target_version)
    filename = f"BZ.{platform}_{fw_ver}.bin"
    return f"{_DL_BASE}/{model}/{fw_ver}/{filename}"


def download_firmware(url: str, dest: Path, console: Console) -> str:
    """
    Download firmware from url to dest.
    Returns the sha256 hex digest.
    Raises requests.HTTPError on bad status, OSError on write failure.
    """
    console.print(f"  Downloading [dim]{url}[/dim] …")
    resp = requests.get(url, stream=True, timeout=(10, 300), verify=True)
    resp.raise_for_status()

    hasher = hashlib.sha256()
    total_bytes = 0
    with dest.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            fh.write(chunk)
            hasher.update(chunk)
            total_bytes += len(chunk)

    mb = total_bytes / 1024 / 1024
    sha256 = hasher.hexdigest()
    console.print(f"  [green]✓ {mb:.1f} MB  sha256:{sha256[:16]}…[/green]")
    return sha256
