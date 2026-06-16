"""
MAC address -> vendor (OUI) lookup.

Works fully offline using an embedded table of common OUI prefixes. For
exhaustive coverage you may drop an IEEE ``oui.txt`` or Wireshark ``manuf``
file next to this module (or point ``DISCOVERY_OUI_FILE`` at one) and it will
be loaded automatically and merged on top of the embedded table.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# ── Embedded OUI prefixes (first 3 MAC octets, upper-case, no separators) ──────
# Curated for the device classes this tool targets: routers, switches,
# firewalls, APs, printers, cameras, servers and common PC/NIC vendors.
_EMBEDDED_OUI: dict[str, str] = {
    # Cisco
    "00000C": "Cisco Systems", "001A2F": "Cisco Systems", "0026CB": "Cisco Systems",
    "00D0BC": "Cisco Systems", "F4CFE2": "Cisco Systems", "00071B": "Cisco Systems",
    "E0D173": "Cisco Systems", "70708B": "Cisco Meraki",
    # MikroTik
    "4C5E0C": "MikroTik", "6C3B6B": "MikroTik", "B869F4": "MikroTik",
    "CC2DE0": "MikroTik", "DC2C6E": "MikroTik", "E48D8C": "MikroTik",
    "2CC81B": "MikroTik", "48A98A": "MikroTik", "744D28": "MikroTik",
    # Ubiquiti
    "002722": "Ubiquiti Networks", "0418D6": "Ubiquiti Networks",
    "24A43C": "Ubiquiti Networks", "44D9E7": "Ubiquiti Networks",
    "788A20": "Ubiquiti Networks", "802AA8": "Ubiquiti Networks",
    "DC9FDB": "Ubiquiti Networks", "F09FC2": "Ubiquiti Networks",
    "FCECDA": "Ubiquiti Networks", "687251": "Ubiquiti Networks",
    # TP-Link
    "001478": "TP-Link", "143FC0": "TP-Link", "1C61B4": "TP-Link",
    "50C7BF": "TP-Link", "84D81B": "TP-Link", "A42BB0": "TP-Link",
    "C46E1F": "TP-Link", "EC086B": "TP-Link", "F4F26D": "TP-Link",
    # Netgear
    "00095B": "Netgear", "0026F2": "Netgear", "20E52A": "Netgear",
    "44944A": "Netgear", "9CD36D": "Netgear", "A040A0": "Netgear",
    # D-Link
    "001346": "D-Link", "002191": "D-Link", "1CBDB9": "D-Link",
    "340804": "D-Link", "C8BE19": "D-Link",
    # Juniper / Fortinet / Palo Alto / SonicWall (firewalls/switches)
    "3C61046": "Juniper Networks", "002688": "Juniper Networks",
    "0090FB": "Juniper Networks", "001BC0": "Juniper Networks",
    "00090F": "Fortinet", "081196": "Fortinet", "904CE5": "Fortinet",
    "70CB0D": "Fortinet", "001B17": "Palo Alto Networks",
    "B4007F": "Palo Alto Networks", "0017C5": "SonicWall",
    "C0EAE4": "SonicWall", "18B169": "WatchGuard",
    # HP / HPE / Aruba (servers, switches, printers, APs)
    "001321": "Hewlett Packard", "001F29": "Hewlett Packard",
    "002655": "Hewlett Packard", "3863BB": "Hewlett Packard",
    "9457A5": "Hewlett Packard", "B499BA": "Hewlett Packard Enterprise",
    "94F128": "Aruba Networks", "000B86": "Aruba Networks",
    "24DEC6": "Aruba Networks", "6CF37F": "Aruba Networks",
    # Dell (servers / PCs)
    "00188B": "Dell", "00219B": "Dell", "001EC9": "Dell",
    "B083FE": "Dell", "D067E5": "Dell", "F8BC12": "Dell", "18DBF2": "Dell",
    # Printers
    "0000AA": "Xerox", "9CB654": "Xerox",
    "002673": "Brother", "008077": "Brother", "30055C": "Brother",
    "0000F0": "Samsung", "001599": "Samsung", "F008F1": "Samsung",
    "08005A": "IBM", "002414": "Canon", "8C5877": "Canon",
    "0080A3": "Lexmark", "E80188": "Lexmark", "002129": "Epson",
    "44D884": "Epson", "001B78": "HP Printer",
    # IP Cameras / surveillance
    "001599C": "Hikvision", "4419B6": "Hikvision", "C0561D": "Hikvision",
    "BCAD28": "Hikvision", "44A642": "Hikvision",
    "000B8C": "Dahua", "3CEF8C": "Dahua", "90020A": "Dahua", "E0508B": "Dahua",
    "000FF6": "Axis Communications", "00408C": "Axis Communications",
    "ACCC8E": "Axis Communications",
    # Servers / virtualization / cloud NICs
    "000C29": "VMware", "005056": "VMware", "001C14": "VMware",
    "080027": "Oracle VirtualBox", "525400": "QEMU/KVM",
    "00155D": "Microsoft Hyper-V", "00163E": "Xen",
    "001A11": "Google", "3C5AB4": "Google",
    "0017FA": "Microsoft", "F01DBC": "Microsoft", "7C1E52": "Microsoft",
    "001B21": "Intel", "001E67": "Intel", "3CFDFE": "Intel",
    "A0369F": "Intel", "8CDCD4": "Hewlett Packard Enterprise",
    # Apple (PC/laptop/phone)
    "001451": "Apple", "0050E4": "Apple", "3C0754": "Apple",
    "685B35": "Apple", "A85C2C": "Apple", "F0DBF8": "Apple", "BCEC5D": "Apple",
    # Raspberry Pi / IoT
    "B827EB": "Raspberry Pi Foundation", "DCA632": "Raspberry Pi (Trading)",
    "E45F01": "Raspberry Pi (Trading)", "2CCF67": "Raspberry Pi (Trading)",
    # Common consumer / mobile
    "F4F5D8": "Google", "001A11G": "Google",
    "0024D7": "Intel", "AC220B": "ASUSTek", "049226": "ASUSTek",
    "1C872C": "ASUSTek", "50465D": "ASUSTek",
    "0019DB": "MSI", "70850A": "MSI",
}


def normalize_mac(mac: str | None) -> str | None:
    """Return MAC as upper-case ``AA:BB:CC:DD:EE:FF`` or None if invalid."""
    if not mac:
        return None
    hexed = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    if len(hexed) != 12:
        return None
    return ":".join(hexed[i : i + 2] for i in range(0, 12, 2))


def _oui_key(mac: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", mac).upper()[:6]


@lru_cache(maxsize=1)
def _load_table() -> dict[str, str]:
    table = dict(_EMBEDDED_OUI)
    # Optional external IEEE/Wireshark database.
    candidates = []
    env_path = os.environ.get("DISCOVERY_OUI_FILE")
    if env_path:
        candidates.append(Path(env_path))
    here = Path(__file__).parent
    candidates += [here / "oui.txt", here / "manuf"]
    for path in candidates:
        if path and path.exists():
            try:
                table.update(_parse_oui_file(path))
            except Exception:  # pragma: no cover - best effort
                pass
    return table


def _parse_oui_file(path: Path) -> dict[str, str]:
    """Parse an IEEE ``oui.txt`` or Wireshark ``manuf`` file."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Wireshark manuf:  "00:00:0C   Cisco   Cisco Systems, Inc"
        m = re.match(r"^([0-9A-Fa-f]{2}[:\-][0-9A-Fa-f]{2}[:\-][0-9A-Fa-f]{2})\s+(.+)$", line)
        if m:
            prefix = re.sub(r"[^0-9A-Fa-f]", "", m.group(1)).upper()
            name = m.group(2).split("\t")[-1].strip()
            out[prefix] = name
            continue
        # IEEE oui.txt:  "00-00-0C   (hex)   CISCO SYSTEMS, INC."
        m = re.match(r"^([0-9A-Fa-f]{2}-[0-9A-Fa-f]{2}-[0-9A-Fa-f]{2})\s+\(hex\)\s+(.+)$", line)
        if m:
            prefix = re.sub(r"[^0-9A-Fa-f]", "", m.group(1)).upper()
            out[prefix] = m.group(2).strip()
    return out


def lookup_vendor(mac: str | None) -> str:
    """Return the vendor name for a MAC, or 'Unknown' if not found."""
    norm = normalize_mac(mac)
    if not norm:
        return "Unknown"
    key = _oui_key(norm)
    table = _load_table()
    # Try 6-hex prefix, then known longer keys (some embedded entries are 7).
    if key in table:
        return table[key]
    seven = re.sub(r"[^0-9A-Fa-f]", "", norm).upper()[:7]
    return table.get(seven, "Unknown")


# Locally-administered / multicast MAC detection (helps skip virtual/random MACs)
def is_locally_administered(mac: str | None) -> bool:
    norm = normalize_mac(mac)
    if not norm:
        return False
    first_octet = int(norm[:2], 16)
    return bool(first_octet & 0b10)
