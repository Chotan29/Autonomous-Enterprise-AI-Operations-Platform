"""
Cross-platform local network information: primary IP, subnet (CIDR), default
gateway and the system ARP cache. No third-party dependencies required
(``psutil`` is used when available for accurate netmasks, otherwise a /24 is
assumed).
"""
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from typing import Optional

try:  # optional, for accurate netmask
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


def get_primary_ip() -> Optional[str]:
    """Return the host's primary outbound IPv4 address (no traffic sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # does not actually send packets for UDP
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None
    finally:
        s.close()


def get_local_subnet() -> Optional[str]:
    """Return the local subnet in CIDR form, e.g. '192.168.1.0/24'."""
    ip = get_primary_ip()
    if not ip:
        return None

    netmask = _netmask_for_ip(ip)
    try:
        if netmask:
            net = ipaddress.ip_network(f"{ip}/{netmask}", strict=False)
        else:
            # Assume /24 for typical LANs when netmask is unknown.
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
        return str(net)
    except ValueError:
        return None


def _netmask_for_ip(ip: str) -> Optional[str]:
    if psutil is None:
        return None
    try:
        for _iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and a.address == ip:
                    return a.netmask
    except Exception:
        pass
    return None


def get_default_gateway() -> Optional[str]:
    """Best-effort default gateway IPv4 address."""
    # Linux: /proc/net/route
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    gw_hex = fields[2]
                    gw = ".".join(
                        str(int(gw_hex[i : i + 2], 16)) for i in (6, 4, 2, 0)
                    )
                    return gw
    except (FileNotFoundError, PermissionError, OSError):
        pass

    # Windows / macOS / fallback via route or ipconfig
    try:
        if _is_windows():
            out = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, timeout=8
            ).stdout
            m = re.search(r"Default Gateway[ .]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", out)
            if m:
                return m.group(1)
        else:
            out = subprocess.run(
                ["netstat", "-rn"], capture_output=True, text=True, timeout=8
            ).stdout
            for line in out.splitlines():
                if line.split()[:1] in (["default"], ["0.0.0.0"]):
                    parts = line.split()
                    for p in parts:
                        if re.match(r"^\d+\.\d+\.\d+\.\d+$", p) and p != "0.0.0.0":
                            return p
    except Exception:
        pass
    return None


def read_arp_cache() -> dict[str, str]:
    """Return {ip: mac} from the OS ARP table (cross-platform)."""
    result: dict[str, str] = {}
    try:
        cmd = ["arp", "-a"] if _is_windows() else ["arp", "-an"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return result

    mac_re = re.compile(r"([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}")
    ip_re = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
    for line in out.splitlines():
        ip_m = ip_re.search(line)
        mac_m = mac_re.search(line)
        if ip_m and mac_m:
            mac = mac_m.group(0).replace("-", ":").upper()
            if mac not in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"):
                result[ip_m.group(0)] = mac
    return result


def _is_windows() -> bool:
    import os

    return os.name == "nt"


def is_private_subnet(cidr: str) -> bool:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        return net.is_private
    except ValueError:
        return False
