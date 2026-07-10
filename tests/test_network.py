"""Tests for the functional network layer."""

import subprocess
from unittest.mock import MagicMock, call, patch

from network import get_wifi_list


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
