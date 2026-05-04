"""UniFi controller HTTP client."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from typing import Any

import requests
import urllib3
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

PROTECTED_DEVICE_TYPES: frozenset[str] = frozenset({"udm", "udr", "ugw", "uxg"})

_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 30


class UniFiLoginError(Exception):
    """Raised when login to the controller fails."""


class UniFiAPIError(Exception):
    """Raised on unexpected API errors."""


@dataclass
class UniFiDevice:
    mac: str
    model: str
    name: str
    ip: str
    version: str
    state: int
    uptime: int
    device_type: str
    adopted: bool
    upgrade_to_firmware: str = ""


class UniFiClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        site: str = "default",
        verify_tls: bool = False,
        network_prefix: str = "/proxy/network",
    ) -> None:
        self._host = host.rstrip("/")
        self._username = username
        self._password = password
        self._site = site
        self._verify_tls = verify_tls
        self._network_prefix = network_prefix.rstrip("/")
        self._session = requests.Session()
        self._csrf_token: str | None = None

        if not verify_tls:
            warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    def _base_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token
        return headers

    def _net_path(self, suffix: str) -> str:
        """Build full path for Network Application API calls."""
        return f"{self._network_prefix}{suffix}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def login(self) -> None:
        """Login to the controller. Tries /api/auth/login (UniFi OS) then /api/login (legacy)."""
        for endpoint in ("/api/auth/login", "/api/login"):
            url = f"{self._host}{endpoint}"
            try:
                resp = self._session.post(
                    url,
                    json={"username": self._username, "password": self._password, "remember": True},
                    headers={"Content-Type": "application/json"},
                    verify=self._verify_tls,
                    timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                )
            except requests.ConnectionError:
                if endpoint == "/api/login":
                    raise
                continue

            if resp.status_code == 200:
                csrf = resp.headers.get("X-CSRF-Token") or resp.cookies.get("csrf_token")
                if csrf:
                    self._csrf_token = csrf
                return

            if resp.status_code == 404:
                continue

            raise UniFiLoginError(f"Login failed [{resp.status_code}]: {resp.text[:200]}")

        raise UniFiLoginError("Login failed: neither /api/auth/login nor /api/login responded")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def _get(self, path: str) -> Any:
        resp = self._session.get(
            f"{self._host}{path}",
            headers=self._base_headers(),
            verify=self._verify_tls,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        resp.raise_for_status()
        result: Any = resp.json()
        return result

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        resp = self._session.post(
            f"{self._host}{path}",
            json=payload,
            headers=self._base_headers(),
            verify=self._verify_tls,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        resp.raise_for_status()
        result: Any = resp.json()
        return result

    def get_devices(self) -> list[UniFiDevice]:
        data: dict[str, Any] = self._get(
            self._net_path(f"/api/s/{self._site}/stat/device")
        )
        devices: list[UniFiDevice] = []
        for raw in data.get("data", []):
            d: dict[str, Any] = raw
            devices.append(
                UniFiDevice(
                    mac=str(d.get("mac", "")),
                    model=str(d.get("model", "")),
                    name=str(d.get("name") or d.get("hostname") or d.get("mac", "")),
                    ip=str(d.get("ip", "")),
                    version=str(d.get("version", "")),
                    state=int(d.get("state", 0)),
                    uptime=int(d.get("uptime", 0)),
                    device_type=str(d.get("type", "")).lower(),
                    adopted=bool(d.get("adopted", False)),
                    upgrade_to_firmware=str(d.get("upgrade_to_firmware") or ""),
                )
            )
        return devices

    @property
    def host(self) -> str:
        return self._host

    def upgrade_external(self, mac: str, firmware_url: str) -> dict[str, Any]:
        result: dict[str, Any] = self._post(
            self._net_path(f"/api/s/{self._site}/cmd/devmgr"),
            {"cmd": "upgrade-external", "mac": mac, "url": firmware_url},
        )
        return result

    def upgrade_builtin(self, mac: str) -> dict[str, Any]:
        result: dict[str, Any] = self._post(
            self._net_path(f"/api/s/{self._site}/cmd/devmgr"),
            {"cmd": "upgrade", "mac": mac},
        )
        return result

    def restart_device(self, mac: str) -> dict[str, Any]:
        result: dict[str, Any] = self._post(
            self._net_path(f"/api/s/{self._site}/cmd/devmgr"),
            {"cmd": "restart", "mac": mac},
        )
        return result

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> UniFiClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def client_from_env() -> UniFiClient:
    """Build a UniFiClient from environment variables."""
    host = os.environ.get("UNIFI_HOST")
    user = os.environ.get("UNIFI_USER")
    password = os.environ.get("UNIFI_PASS")

    if not host:
        raise ValueError("UNIFI_HOST environment variable is not set")
    if not user:
        raise ValueError("UNIFI_USER environment variable is not set")
    if not password:
        raise ValueError("UNIFI_PASS environment variable is not set")

    site = os.environ.get("UNIFI_SITE", "default")
    verify_tls = os.environ.get("UNIFI_VERIFY_TLS", "false").lower() == "true"
    network_prefix = os.environ.get("UNIFI_NETWORK_PREFIX", "/proxy/network")

    return UniFiClient(
        host=host,
        username=user,
        password=password,
        site=site,
        verify_tls=verify_tls,
        network_prefix=network_prefix,
    )
