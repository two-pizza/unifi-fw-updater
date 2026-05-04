"""Tests for unifi_client.py."""

from __future__ import annotations

import json

import pytest
import responses

from unifi_fw.unifi_client import (
    PROTECTED_DEVICE_TYPES,
    UniFiClient,
    UniFiLoginError,
    client_from_env,
)

HOST = "https://192.168.1.1"
SITE = "default"


@pytest.fixture
def client() -> UniFiClient:
    return UniFiClient(host=HOST, username="admin", password="secret", site=SITE, verify_tls=False)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestLogin:
    @responses.activate
    def test_new_api_login_success(self, client: UniFiClient) -> None:
        responses.add(responses.POST, f"{HOST}/api/auth/login", json={}, status=200)
        client.login()  # must not raise

    @responses.activate
    def test_fallback_to_legacy_login(self, client: UniFiClient) -> None:
        responses.add(responses.POST, f"{HOST}/api/auth/login", status=404)
        responses.add(responses.POST, f"{HOST}/api/login", json={}, status=200)
        client.login()

    @responses.activate
    def test_login_bad_credentials_raises(self, client: UniFiClient) -> None:
        responses.add(
            responses.POST,
            f"{HOST}/api/auth/login",
            json={"errors": ["Invalid credentials"]},
            status=400,
        )
        with pytest.raises(UniFiLoginError):
            client.login()

    @responses.activate
    def test_login_captures_csrf_header(self, client: UniFiClient) -> None:
        responses.add(
            responses.POST,
            f"{HOST}/api/auth/login",
            json={},
            status=200,
            headers={"X-CSRF-Token": "tok-abc"},
        )
        client.login()
        assert client._csrf_token == "tok-abc"

    @responses.activate
    def test_login_sends_remember_true(self, client: UniFiClient) -> None:
        responses.add(responses.POST, f"{HOST}/api/auth/login", json={}, status=200)
        client.login()
        body = json.loads(responses.calls[0].request.body)
        assert body["remember"] is True

    @responses.activate
    def test_login_does_not_log_password(self, client: UniFiClient) -> None:
        responses.add(responses.POST, f"{HOST}/api/auth/login", json={}, status=200)
        client.login()
        # password must NOT appear in the URL or headers
        req = responses.calls[0].request
        assert "secret" not in (req.url or "")
        # it IS in the body (sent to the server), but we verify it's not in headers
        for k, v in req.headers.items():
            assert "secret" not in v, f"Password leaked in header {k}"


# ---------------------------------------------------------------------------
# get_devices
# ---------------------------------------------------------------------------


class TestGetDevices:
    @responses.activate
    def test_parses_device_fields(self, client: UniFiClient) -> None:
        responses.add(
            responses.GET,
            f"{HOST}/proxy/network/api/s/{SITE}/stat/device",
            json={
                "data": [
                    {
                        "mac": "aa:bb:cc:dd:ee:01",
                        "model": "U7PG2",
                        "name": "AP-Living",
                        "ip": "192.168.1.100",
                        "version": "6.6.77",
                        "state": 1,
                        "uptime": 7200,
                        "type": "uap",
                        "adopted": True,
                    }
                ]
            },
            status=200,
        )
        devices = client.get_devices()

        assert len(devices) == 1
        d = devices[0]
        assert d.mac == "aa:bb:cc:dd:ee:01"
        assert d.model == "U7PG2"
        assert d.name == "AP-Living"
        assert d.version == "6.6.77"
        assert d.state == 1
        assert d.uptime == 7200
        assert d.device_type == "uap"
        assert d.adopted is True

    @responses.activate
    def test_empty_data_returns_empty_list(self, client: UniFiClient) -> None:
        responses.add(
            responses.GET,
            f"{HOST}/proxy/network/api/s/{SITE}/stat/device",
            json={"data": []},
            status=200,
        )
        assert client.get_devices() == []

    @responses.activate
    def test_device_type_lowercased(self, client: UniFiClient) -> None:
        responses.add(
            responses.GET,
            f"{HOST}/proxy/network/api/s/{SITE}/stat/device",
            json={"data": [{"mac": "a", "type": "UAP", "state": 1, "uptime": 0, "adopted": True}]},
            status=200,
        )
        devices = client.get_devices()
        assert devices[0].device_type == "uap"

    @responses.activate
    def test_udr_device_returned_in_inventory(self, client: UniFiClient) -> None:
        responses.add(
            responses.GET,
            f"{HOST}/proxy/network/api/s/{SITE}/stat/device",
            json={
                "data": [
                    {
                        "mac": "ff:ee:dd:cc:bb:aa",
                        "model": "UDR",
                        "name": "Dream Router",
                        "ip": "192.168.1.1",
                        "version": "4.4.0",
                        "state": 1,
                        "uptime": 86400,
                        "type": "udr",
                        "adopted": True,
                    }
                ]
            },
            status=200,
        )
        devices = client.get_devices()
        assert devices[0].device_type in PROTECTED_DEVICE_TYPES


# ---------------------------------------------------------------------------
# upgrade_external / restart_device
# ---------------------------------------------------------------------------


class TestUpgradeExternal:
    @responses.activate
    def test_sends_correct_payload(self, client: UniFiClient) -> None:
        mac = "aa:bb:cc:dd:ee:01"
        url = "http://192.168.1.50:8080/firmware/fw.bin"
        responses.add(
            responses.POST,
            f"{HOST}/proxy/network/api/s/{SITE}/cmd/devmgr",
            json={"data": []},
            status=200,
        )

        client.upgrade_external(mac, url)

        body = json.loads(responses.calls[0].request.body)
        assert body["cmd"] == "upgrade-external"
        assert body["mac"] == mac
        assert body["url"] == url

    @responses.activate
    def test_restart_device_sends_correct_payload(self, client: UniFiClient) -> None:
        mac = "aa:bb:cc:dd:ee:01"
        responses.add(
            responses.POST,
            f"{HOST}/proxy/network/api/s/{SITE}/cmd/devmgr",
            json={"data": []},
            status=200,
        )

        client.restart_device(mac)

        body = json.loads(responses.calls[0].request.body)
        assert body["cmd"] == "restart"
        assert body["mac"] == mac


# ---------------------------------------------------------------------------
# PROTECTED_DEVICE_TYPES guard
# ---------------------------------------------------------------------------


class TestProtectedDeviceTypes:
    def test_all_expected_types_present(self) -> None:
        assert {"udm", "udr", "ugw", "uxg"} <= PROTECTED_DEVICE_TYPES

    def test_regular_device_types_not_protected(self) -> None:
        assert "uap" not in PROTECTED_DEVICE_TYPES
        assert "usw" not in PROTECTED_DEVICE_TYPES
        assert "uck" not in PROTECTED_DEVICE_TYPES


# ---------------------------------------------------------------------------
# client_from_env
# ---------------------------------------------------------------------------


class TestClientFromEnv:
    def test_raises_if_host_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNIFI_HOST", raising=False)
        with pytest.raises(ValueError, match="UNIFI_HOST"):
            client_from_env()

    def test_raises_if_user_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_HOST", HOST)
        monkeypatch.delenv("UNIFI_USER", raising=False)
        with pytest.raises(ValueError, match="UNIFI_USER"):
            client_from_env()

    def test_raises_if_pass_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_HOST", HOST)
        monkeypatch.setenv("UNIFI_USER", "admin")
        monkeypatch.delenv("UNIFI_PASS", raising=False)
        with pytest.raises(ValueError, match="UNIFI_PASS"):
            client_from_env()

    def test_creates_client_with_env_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_HOST", HOST)
        monkeypatch.setenv("UNIFI_USER", "admin")
        monkeypatch.setenv("UNIFI_PASS", "s3cr3t")
        monkeypatch.setenv("UNIFI_SITE", "home")
        monkeypatch.setenv("UNIFI_VERIFY_TLS", "false")

        c = client_from_env()
        assert c._host == HOST
        assert c._site == "home"
        assert c._verify_tls is False

    def test_verify_tls_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_HOST", HOST)
        monkeypatch.setenv("UNIFI_USER", "admin")
        monkeypatch.setenv("UNIFI_PASS", "pass")
        monkeypatch.setenv("UNIFI_VERIFY_TLS", "true")

        c = client_from_env()
        assert c._verify_tls is True

    def test_default_site_is_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIFI_HOST", HOST)
        monkeypatch.setenv("UNIFI_USER", "admin")
        monkeypatch.setenv("UNIFI_PASS", "pass")
        monkeypatch.delenv("UNIFI_SITE", raising=False)

        c = client_from_env()
        assert c._site == "default"
