"""NetworkManager interface"""

import subprocess

VPN_TYPES = {
    "vpn",
    "wireguard",
    "vpnc",
    "pptp",
    "openconnect",
    "openvpn",
}


def get_wifi_interface() -> str | None:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "device"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    for line in result.stdout.splitlines():
        device, dev_type = line.split(":", 1)
        if dev_type == "wifi":
            return device

    return None


def get_wifi_list(force_rescan=False):
    """Get available WiFi networks.

    Args:
        force_rescan: If True, request a fresh scan. Newer NetworkManager
            supports ``--rescan yes`` which blocks until the scan completes;
            older versions fall back to ``nmcli device wifi rescan`` followed
            by a plain list.
    """
    list_cmd = ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"]
    try:
        if force_rescan:
            try:
                result = subprocess.run(
                    list_cmd + ["--rescan", "yes"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError:
                # Older nmcli without --rescan support: trigger a rescan and
                # fall back to a plain list.
                subprocess.run(
                    ["nmcli", "device", "wifi", "rescan"],
                    capture_output=True,
                )
                result = subprocess.run(
                    list_cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
        else:
            result = subprocess.run(
                list_cmd,
                capture_output=True,
                text=True,
                check=True,
            )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    networks, seen = [], set()
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] and parts[0] not in seen:
            seen.add(parts[0])
            networks.append(
                {
                    "ssid": parts[0],
                    "signal": int(parts[1]) if parts[1] else 0,
                    "security": parts[2],
                    "connected": parts[3] == "*",
                }
            )
    return sorted(networks, key=lambda x: x["signal"], reverse=True)


def get_current_connection():
    """Get active connection name"""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().split("\n")[0] or None
    except:
        return None


def get_station_info():
    """Get station status"""
    info = {
        "state": "disconnected",
        "frequency": "-",
        "security": "-",
    }
    current = get_current_connection()
    if current:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,FREQ,SECURITY", "device", "wifi", "list"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("yes:"):
                parts = line.split(":")
                info["state"] = "connected"
                info["frequency"] = parts[1] or "-"
                info["security"] = parts[2] or "-"
                break
    return info


def connect_wifi(ssid, password, hidden=False):
    """Connect to WiFi (supports hidden SSIDs)"""
    try:
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])
        if hidden:
            cmd.append("hidden")
            cmd.append("yes")
        result = subprocess.run(cmd, capture_output=True, text=True)

        # If connection failed, delete the connection profile that was created
        if result.returncode != 0:
            forget_network(ssid)

        return result.returncode == 0, result.stderr or result.stdout
    except Exception as e:
        return False, str(e)


def connect_802_1x(
    ssid, username, password, eap_method="peap", phase2_auth="mschapv2", hidden=False
):
    """Connect to 802.1X enterprise WiFi (supports hidden SSIDs)

    Supports:
    - EAP: peap, ttls, tls
    - Phase2: mschapv2, mschap, pap, chap, gtc, md5
    - Hidden SSID networks
    """
    try:
        iface = get_wifi_interface()
        if not iface:
            return False, "No WiFi interface found"
        forget_network(ssid)

        # Build command based on EAP method
        cmd = [
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "con-name",
            ssid,
            "ifname",
            iface,
            "ssid",
            ssid,
            "wifi-sec.key-mgmt",
            "wpa-eap",
            "802-1x.eap",
            eap_method.lower(),
            "802-1x.identity",
            username,
        ]

        # Add hidden SSID support
        if hidden:
            cmd.extend(["wifi.hidden", "yes"])

        # Add auth-specific parameters
        if eap_method.lower() in ["peap", "ttls"]:
            # PEAP and TTLS use phase2 auth + password
            cmd.extend(["802-1x.phase2-auth", phase2_auth.lower()])
            cmd.extend(["802-1x.password", password])
        elif eap_method.lower() == "tls":
            # TLS uses certificates (for now, treat password as private key password)
            cmd.extend(["802-1x.private-key-password", password])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return False, result.stderr

        result = subprocess.run(["nmcli", "connection", "up", ssid], capture_output=True, text=True)

        # If connection failed, delete the connection profile that was created
        if result.returncode != 0:
            forget_network(ssid)

        return result.returncode == 0, result.stderr or "Connected"
    except Exception as e:
        return False, str(e)


def forget_network(ssid):
    """Delete saved WiFi network by SSID"""
    try:
        result = subprocess.run(
            ["nmcli", "connection", "delete", ssid], capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False


def disconnect():
    """Disconnect from network"""
    try:
        iface = get_wifi_interface()
        if not iface:
            return False
        result = subprocess.run(
            ["nmcli", "device", "disconnect", iface], capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False


def wifi_enabled():
    """Check if WiFi is enabled"""
    try:
        result = subprocess.run(
            ["nmcli", "radio", "wifi"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip() == "enabled"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def toggle_wifi():
    """Toggle WiFi on/off."""
    enabled = wifi_enabled()

    try:
        subprocess.run(
            ["nmcli", "radio", "wifi", "off" if enabled else "on"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return enabled

    return not enabled


def wwan_enabled() -> bool:
    """Check if WWAN is enabled"""
    try:
        result = subprocess.run(["nmcli", "radio", "wwan"], capture_output=True, text=True)
        return result.stdout.strip() == "enabled"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def toggle_wwan() -> bool:
    """Toggle WWAN on/off"""
    enabled = wwan_enabled()
    try:
        subprocess.run(["nmcli", "radio", "wwan", "off" if enabled else "on"])
        return not enabled
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def get_ethernet_interface() -> str | None:
    """Auto-detect Ethernet interface"""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "device"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            for device, type in line.split(":"):
                if type == "ethernet":
                    return device
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return None


def connect_802_1x_wired(con_name, username, password, eap_method="peap", phase2_auth="mschapv2"):
    """Connect to 802.1X enterprise wired network

    Supports:
    - EAP: peap, ttls, tls
    - Phase2: mschapv2, mschap, pap, chap, gtc, md5
    """
    try:
        iface = get_ethernet_interface()
        if not iface:
            return False, "No Ethernet interface found"

        forget_network(con_name)

        # Build command for wired 802.1X
        cmd = [
            "nmcli",
            "connection",
            "add",
            "type",
            "802-3-ethernet",
            "con-name",
            con_name,
            "ifname",
            iface,
            "802-1x.eap",
            eap_method.lower(),
            "802-1x.identity",
            username,
        ]

        # Add auth-specific parameters
        if eap_method.lower() in ["peap", "ttls"]:
            cmd.extend(["802-1x.phase2-auth", phase2_auth.lower()])
            cmd.extend(["802-1x.password", password])
        elif eap_method.lower() == "tls":
            cmd.extend(["802-1x.private-key-password", password])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return False, result.stderr

        result = subprocess.run(
            ["nmcli", "connection", "up", con_name], capture_output=True, text=True
        )

        # If connection failed, delete the connection profile that was created
        if result.returncode != 0:
            forget_network(con_name)

        return result.returncode == 0, result.stderr or "Connected"
    except Exception as e:
        return False, str(e)


def disconnect_ethernet():
    """Disconnect from wired network"""
    try:
        iface = get_ethernet_interface()
        if not iface:
            return False
        result = subprocess.run(
            ["nmcli", "device", "disconnect", iface], capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False


def is_enterprise(security) -> bool:
    """Check if network is 802.1X"""
    return "WPA-EAP" in security or "802.1X" in security


def is_owe(security) -> bool:
    """Check if network uses OWE (Enhanced Open / WPA3-OWE)"""
    return "OWE" in security or "WPA3-OWE" in security


def get_vpn_list() -> list[dict[str, str]]:
    """Return configured VPN connections from NetworkManager."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.SubprocessError:
        return []

    active_vpn = get_active_vpn()
    vpns = []

    for line in result.stdout.splitlines():
        if not line:
            continue

        try:
            name, conn_type = line.rsplit(":", 1)
        except ValueError:
            continue

        if conn_type not in VPN_TYPES:
            continue

        vpns.append(
            {
                "name": name,
                "active": name == active_vpn,
            }
        )

    return sorted(vpns, key=lambda vpn: (not vpn["active"], vpn["name"]))


def get_active_vpn() -> str | None:
    """Get currently active VPN connection name"""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"],
            capture_output=True,
            text=True,
            check=True,
        )

        # VPN types supported by NetworkManager
        vpn_types = [":vpn", ":wireguard", ":vpnc", ":pptp", ":openconnect", ":openvpn"]

        for line in result.stdout.strip().split("\n"):
            if any(vpn_type in line for vpn_type in vpn_types):
                return line.split(":")[0]
        return None
    except:
        return None


def connect_vpn(name) -> tuple[bool, str]:
    """Connect to VPN by name"""
    try:
        result = subprocess.run(["nmcli", "connection", "up", name], capture_output=True, text=True)
        return result.returncode == 0, result.stderr or result.stdout
    except Exception as e:
        return False, str(e)


def disconnect_vpn(name) -> bool:
    """Disconnect VPN by name"""
    try:
        result = subprocess.run(
            ["nmcli", "connection", "down", name], capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False


def get_modem_info() -> dict[str, str] | None:
    """Get modem information via ModemManager"""
    try:
        # Get modem list
        result = subprocess.run(
            ["mmcli", "--list-modems"], capture_output=True, text=True, check=True
        )

        # Extract modem ID from output (e.g., "/org/freedesktop/ModemManager1/Modem/2")
        modem_id = None
        for line in result.stdout.strip().split("\n"):
            if "/Modem/" in line:
                modem_id = line.split("/Modem/")[-1].split()[0]
                break

        if not modem_id:
            return None

        # Get detailed modem info
        result = subprocess.run(
            ["mmcli", "-m", modem_id], capture_output=True, text=True, check=True
        )

        info = {"signal": "0%", "operator": "-", "tech": "-", "state": "unknown"}

        for line in result.stdout.split("\n"):
            line = line.strip()
            if "signal quality:" in line:
                # Extract percentage (e.g., "48% (cached)")
                info["signal"] = line.split(":")[1].strip().split()[0]
            elif "operator name:" in line:
                info["operator"] = line.split(":")[1].strip()
            elif "access tech:" in line:
                info["tech"] = line.split(":")[1].strip().upper()
            elif "state:" in line:
                # Extract state, removing ANSI color codes
                state = line.split(":")[1].strip()
                # Remove ANSI codes like [32mconnected[0m
                state = state.replace("[32m", "").replace("[0m", "")
                info["state"] = state

        return info
    except:
        return None


def get_wwan_list() -> list[dict[str, str]]:
    """Get all WWAN (cellular) connections configured in NetworkManager"""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True,
            text=True,
            check=True,
        )
        active_wwan = get_active_wwan()
        modem_info = get_modem_info()

        wwans = []
        for line in result.stdout.strip().split("\n"):
            if ":gsm" in line:
                name = line.split(":")[0]
                wwan_entry = {"name": name, "active": name == active_wwan}

                # Add modem info if connection is active
                if wwan_entry["active"] and modem_info:
                    wwan_entry["signal"] = modem_info["signal"]
                    wwan_entry["operator"] = modem_info["operator"]
                    wwan_entry["tech"] = modem_info["tech"]
                else:
                    wwan_entry["signal"] = "-"
                    wwan_entry["operator"] = "-"
                    wwan_entry["tech"] = "-"

                wwans.append(wwan_entry)

        return sorted(wwans, key=lambda x: (not x["active"], x["name"]))
    except:
        return []


def get_active_wwan() -> str | None:
    """Get currently active WWAN connection name"""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"],
            capture_output=True,
            text=True,
            check=True,
        )

        for line in result.stdout.strip().split("\n"):
            if ":gsm" in line:
                return line.split(":")[0]
        return None
    except:
        return None


def connect_wwan(name) -> tuple[bool, str]:
    """Connect to WWAN by name"""
    try:
        result = subprocess.run(["nmcli", "connection", "up", name], capture_output=True, text=True)
        return result.returncode == 0, result.stderr or result.stdout
    except Exception as e:
        return False, str(e)


def disconnect_wwan(name) -> bool:
    """Disconnect WWAN by name"""
    try:
        result = subprocess.run(
            ["nmcli", "connection", "down", name], capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False
