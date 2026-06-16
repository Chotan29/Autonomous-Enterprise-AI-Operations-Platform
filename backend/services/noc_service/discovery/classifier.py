"""
Best-effort device-type classification.

Combines several weak signals -- open TCP ports, vendor (from OUI), reverse-DNS
hostname patterns, whether the host is the default gateway, and nmap's OS guess
-- into a single device type. Designed to degrade gracefully: with only a MAC
and one open port it will still make a reasonable guess.

Recognised types:
    Router, Managed Switch, Firewall, Access Point, Printer,
    Camera, Server, PC/Laptop, Unknown
"""
from __future__ import annotations

import re

# Device-type constants
ROUTER = "Router"
SWITCH = "Managed Switch"
FIREWALL = "Firewall"
ACCESS_POINT = "Access Point"
PRINTER = "Printer"
CAMERA = "Camera"
SERVER = "Server"
PC = "PC/Laptop"
UNKNOWN = "Unknown"

# Vendor -> typical device class hint (lower-cased substring match).
_VENDOR_HINTS: list[tuple[str, str]] = [
    ("palo alto", FIREWALL),
    ("fortinet", FIREWALL),
    ("sonicwall", FIREWALL),
    ("watchguard", FIREWALL),
    ("mikrotik", ROUTER),
    ("cisco meraki", ACCESS_POINT),
    ("aruba", ACCESS_POINT),
    ("ubiquiti", ACCESS_POINT),
    ("juniper", SWITCH),
    ("hikvision", CAMERA),
    ("dahua", CAMERA),
    ("axis communications", CAMERA),
    ("brother", PRINTER),
    ("lexmark", PRINTER),
    ("xerox", PRINTER),
    ("epson", PRINTER),
    ("canon", PRINTER),
    ("hp printer", PRINTER),
    ("vmware", SERVER),
    ("qemu", SERVER),
    ("hyper-v", SERVER),
    ("virtualbox", SERVER),
    ("xen", SERVER),
    ("raspberry pi", SERVER),
    ("apple", PC),
    ("asustek", PC),
    ("msi", PC),
    ("intel", PC),
]

# Hostname regex -> device class.
_HOSTNAME_HINTS: list[tuple[str, str]] = [
    (r"\b(gw|gateway|router|rtr|fritz|openwrt|edgerouter)\b", ROUTER),
    (r"\b(fw|firewall|asa|palo|fortigate|forti)\b", FIREWALL),
    (r"\b(sw|switch|cat[0-9])\b", SWITCH),
    (r"\b(ap|wap|wifi|wlan|unifi|access[-_]?point)\b", ACCESS_POINT),
    (r"\b(printer|print|mfp|hp[0-9a-f]{6}|brn[0-9a-f]{6}|epson|canon)\b", PRINTER),
    (r"\b(cam|camera|ipcam|ipc|nvr|dvr|hikvision|dahua)\b", CAMERA),
    (r"\b(srv|server|esx|esxi|vmware|nas|host|dc[0-9])\b", SERVER),
    (r"\b(pc|laptop|desktop|workstation|macbook|win|android|iphone|ipad)\b", PC),
]


def classify(
    *,
    open_ports: set[int] | None = None,
    vendor: str | None = None,
    hostname: str | None = None,
    is_gateway: bool = False,
    os_guess: str | None = None,
    ttl: int | None = None,
) -> str:
    """Return the most likely device type given the available signals."""
    ports = open_ports or set()
    vendor_l = (vendor or "").lower()
    host_l = (hostname or "").lower()
    os_l = (os_guess or "").lower()

    # ── Strong, unambiguous port-based signals first ──────────────────────────
    # Printers
    if ports & {9100, 515, 631}:
        return PRINTER
    # IP cameras / surveillance (RTSP / ONVIF), unless clearly a server
    if 554 in ports and not (ports & {3389, 445, 1433, 3306}):
        return CAMERA

    # ── The default gateway is almost always a router/firewall ────────────────
    if is_gateway:
        if _vendor_is(vendor_l, FIREWALL) or (ports & {500, 4500}):
            return FIREWALL
        return ROUTER

    # ── Vendor hints (high precision for appliance vendors) ───────────────────
    vendor_type = _vendor_type(vendor_l)
    if vendor_type in (FIREWALL, CAMERA, PRINTER):
        return vendor_type

    # ── Hostname hints ────────────────────────────────────────────────────────
    for pattern, dtype in _HOSTNAME_HINTS:
        if re.search(pattern, host_l):
            return dtype

    # ── Networking gear by management ports ───────────────────────────────────
    # SNMP + telnet/ssh and no typical host services -> switch/router
    mgmt = ports & {22, 23, 161, 830}
    host_services = ports & {135, 139, 445, 3389, 88, 389}
    if 161 in ports and not host_services:
        if vendor_type in (ROUTER, ACCESS_POINT, SWITCH):
            return vendor_type
        return SWITCH

    # ── Servers vs PCs ────────────────────────────────────────────────────────
    server_ports = ports & {80, 443, 25, 110, 143, 3306, 5432, 1433, 53, 21, 8080, 8443, 5000}
    if "server" in os_l:
        return SERVER
    if server_ports and not (ports & {3389}):
        # A box serving network services but not an obvious workstation.
        if len(server_ports) >= 2 or vendor_type == SERVER:
            return SERVER

    # Windows workstation signature
    if ports & {135, 139, 445} or 3389 in ports:
        if "server" in os_l:
            return SERVER
        return PC

    # OS-based fallback
    if any(k in os_l for k in ("windows", "macos", "mac os", "ubuntu", "linux desktop")):
        return PC

    # Vendor fallback (PC/Server class vendors)
    if vendor_type in (PC, SERVER, ACCESS_POINT, ROUTER, SWITCH):
        return vendor_type

    # TTL heuristic (very weak): ~64 Linux/unix, ~128 Windows, ~255 net gear
    if ttl is not None:
        if ttl >= 200:
            return ROUTER
        if 100 <= ttl <= 130:
            return PC

    if ports:
        return SERVER  # something is listening; assume a service host
    return UNKNOWN


def _vendor_type(vendor_l: str) -> str:
    for needle, dtype in _VENDOR_HINTS:
        if needle in vendor_l:
            return dtype
    return UNKNOWN


def _vendor_is(vendor_l: str, dtype: str) -> bool:
    return _vendor_type(vendor_l) == dtype
