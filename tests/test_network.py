"""Tests for the functional network layer."""

import subprocess
from unittest.mock import MagicMock, call, patch

from network import get_device_ipv4, get_ethernet_interface, get_wifi_list


class TestGetWifiList:
    """Unit tests for get_wifi_list."""

    def test_parses_wifi_list(self):
        nmcli_output = (
            "HomeNet:85:WPA2:\nGuestNet:70:WPA2:\nOpenNet:60::\nEnterpriseNet:55:WPA-EAP 802.1X:\n"
        )
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=nmcli_output, returncode=0)
            result = get_wifi_list()

        assert len(result) == 4
        assert result[0]["ssid"] == "HomeNet"
        assert result[0]["signal"] == 85
        assert result[0]["security"] == "WPA2"
        assert result[0]["connected"] is False
        assert result[1]["ssid"] == "GuestNet"
        assert result[2]["ssid"] == "OpenNet"
        assert result[3]["ssid"] == "EnterpriseNet"

        mock_run.assert_called_once_with(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_deduplicates_by_ssid(self):
        nmcli_output = "HomeNet:80:WPA2:*\nHomeNet:85:WPA2:\n"
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=nmcli_output, returncode=0)
            result = get_wifi_list()

        assert len(result) == 1
        assert result[0]["ssid"] == "HomeNet"
        assert result[0]["signal"] == 80
        assert result[0]["connected"] is True

    def test_force_rescan_uses_modern_flag(self):
        nmcli_output = "HomeNet:85:WPA2:\n"
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=nmcli_output, returncode=0)
            result = get_wifi_list(force_rescan=True)

        assert len(result) == 1
        mock_run.assert_called_once_with(
            [
                "nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY,IN-USE",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_force_rescan_falls_back_on_old_nmcli(self):
        nmcli_output = "HomeNet:85:WPA2:\n"

        def side_effect(cmd, **kwargs):
            if "--rescan" in cmd:
                raise subprocess.CalledProcessError(2, cmd)
            return MagicMock(stdout=nmcli_output, returncode=0)

        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = side_effect
            result = get_wifi_list(force_rescan=True)

        assert len(result) == 1
        assert mock_run.call_count == 3
        assert mock_run.call_args_list[0] == call(
            [
                "nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY,IN-USE",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert mock_run.call_args_list[1] == call(
            ["nmcli", "device", "wifi", "rescan"],
            capture_output=True,
        )
        assert mock_run.call_args_list[2] == call(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_returns_empty_list_when_nmcli_fails(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "nmcli")
            result = get_wifi_list()

        assert result == []

    def test_returns_empty_list_when_nmcli_missing(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nmcli not found")
            result = get_wifi_list()

        assert result == []


class TestGetDeviceIpv4:
    """Unit tests for get_device_ipv4."""

    def test_returns_first_ipv4_without_cidr(self):
        nmcli_output = "192.168.1.5/24\n"
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=nmcli_output, returncode=0)
            result = get_device_ipv4("wlp0s20f3")

        assert result == "192.168.1.5"
        mock_run.assert_called_once_with(
            ["nmcli", "-t", "-g", "IP4.ADDRESS", "device", "show", "wlp0s20f3"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_returns_dash_when_no_address(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = get_device_ipv4("wlp0s20f3")

        assert result == "-"

    def test_returns_dash_when_iface_is_none(self):
        result = get_device_ipv4(None)
        assert result == "-"

    def test_returns_dash_when_nmcli_fails(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "nmcli")
            result = get_device_ipv4("wlp0s20f3")

        assert result == "-"

    def test_returns_dash_when_nmcli_missing(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nmcli not found")
            result = get_device_ipv4("wlp0s20f3")

        assert result == "-"


class TestGetEthernetInterface:
    """Unit tests for get_ethernet_interface."""

    def test_returns_ethernet_device(self):
        nmcli_output = "wlan0:wifi\ntailscale0:tun\nlo:loopback\ndocker0:bridge\n/net/connman/iwd/0:wifi-p2p\neth0:ethernet\n"
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=nmcli_output, returncode=0)
            result = get_ethernet_interface()

        assert result == "eth0"
        mock_run.assert_called_once_with(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "device"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_returns_none_when_no_ethernet(self):
        nmcli_output = "wlan0:wifi\ntailscale0:tun\nlo:loopback\n"
        with patch("network.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=nmcli_output, returncode=0)
            result = get_ethernet_interface()

        assert result is None

    def test_returns_none_when_nmcli_fails(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "nmcli")
            result = get_ethernet_interface()

        assert result is None

    def test_returns_none_when_nmcli_missing(self):
        with patch("network.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nmcli not found")
            result = get_ethernet_interface()

        assert result is None
