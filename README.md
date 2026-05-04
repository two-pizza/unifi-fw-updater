# unifi-fw-updater

CLI tool for upgrading firmware on UniFi access points — fully automatic or via a config file.

**[Документация на русском →](README.ru.md)**

---

## Features

- **Auto mode** — discovers all upgradeable APs, downloads firmware from Ubiquiti, serves it locally, upgrades one by one. Only three environment variables needed.
- **Manual mode** — point to your own `firmware.yaml` with device MACs and firmware URLs.
- SHA-256 verification before upgrade
- Sequential upgrade with polling (waits for each device to come back online)
- Hard guard against upgrading gateway/router devices (`udm`, `udr`, `ugw`, `uxg`) — those must be done via UI
- Supports UniFi OS 4.x API (`/proxy/network/` prefix) and legacy controllers
- 110 tests · 86% coverage · mypy --strict · ruff

## Supported models (auto mode)

Auto mode downloads firmware automatically for AC-series devices:

| Model code | Device |
|---|---|
| `U7PG2` | UAP-AC-Pro |
| `U7LT` | UAP-AC-Lite |
| `U7HD` | UAP-AC-HD |
| `U7SHD` | UAP-AC-SHD |
| `U7NHD` | UAP-nanoHD |
| `U7MSH` | UAP-AC-Mesh |
| `U7MP` | UAP-AC-Mesh-Pro |
| `U7IW` | UAP-AC-IW |

Other models (U6, U7 WiFi 6/7 series) fall back to the controller's built-in upgrade.

## Requirements

- Python 3.11+
- UniFi controller with a **local admin account** (cloud/SSO accounts with 2FA return HTTP 499)
- Network access from your machine to the controller

## Installation

```bash
git clone https://github.com/two-pizza/unifi-fw-updater.git
cd unifi-fw-updater
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start — auto mode

Set three environment variables and run:

```bash
export UNIFI_HOST=https://192.168.1.1
export UNIFI_USER=admin
export UNIFI_PASS=your_password

python -m unifi_fw auto
```

The tool will:
1. Connect to the controller and list all APs with available firmware updates
2. Ask for confirmation
3. Download each firmware from `dl.ui.com`
4. Start a temporary local HTTP server
5. Upgrade devices one by one, polling until each comes back online
6. Clean up the temp server and downloaded files

Add `--yes` to skip the confirmation prompt.

## Manual mode

Copy the example config and fill in your device MACs:

```bash
cp firmware.example.yaml firmware.yaml
# edit firmware.yaml
```

Then:

```bash
# See what would be upgraded
python -m unifi_fw plan

# Run upgrade
python -m unifi_fw upgrade --yes
```

For the `firmware_url` field you need to serve the firmware file yourself:

```bash
# Download firmware from ui.com, then:
cd ~/Downloads
python3 -m http.server 8080
```

Use `http://YOUR_LAN_IP:8080/filename.bin` as the URL in `firmware.yaml`.

## All commands

```
python -m unifi_fw auto        # fully automatic, no config file needed
python -m unifi_fw inventory   # list all devices
python -m unifi_fw health      # check controller connectivity
python -m unifi_fw plan        # show upgrade plan (requires firmware.yaml)
python -m unifi_fw upgrade     # run upgrade (requires firmware.yaml)
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `UNIFI_HOST` | ✅ | — | Controller URL, e.g. `https://192.168.1.1` |
| `UNIFI_USER` | ✅ | — | Local admin username |
| `UNIFI_PASS` | ✅ | — | Password |
| `UNIFI_SITE` | — | `default` | Site name |
| `UNIFI_VERIFY_TLS` | — | `false` | Set `true` to verify TLS certificate |
| `UNIFI_NETWORK_PREFIX` | — | `/proxy/network` | API prefix for UniFi OS 4.x. Use empty string for legacy controllers |

Store them in a `.env` file (already in `.gitignore`):

```bash
cp .env.example .env
# fill in your values
```

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/ tests/

# Type check
mypy src/unifi_fw/ --strict
```

## Safety

- Gateway/router devices (`udm`, `udr`, `ugw`, `uxg`) are **always skipped** with a warning. Upgrading them via API is unsafe — use the UniFi OS web UI instead.
- Firmware SHA-256 is verified before the upgrade command is sent.
- Each device is upgraded sequentially. The next device starts only after the previous one is back online.
- Upgrade times out after 15 minutes per device.

## License

MIT
