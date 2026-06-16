"""
Real LAN discovery — no demo data.

Strategy
--------
1. Detect the local IPv4 + subnet from the OS routing table.
2. Run a parallel ping sweep across the /24 (populates the ARP cache).
3. Read the OS ARP table to get IP↔MAC pairs of every host that replied.
4. For each live host:
   - Reverse-DNS → hostname (if available).
   - OUI prefix → vendor name (small built-in table).
   - Quick TCP probe to common admin ports → guess at OS / role.

Returns a list of `discovered_host` dicts ready to feed the UI / monitor.

Safe by design: only the local /24 is touched, and probes are bounded
(semaphore-limited + short timeouts).
"""
from __future__ import annotations
import asyncio
import ipaddress
import platform
import re
import socket
import subprocess
from datetime import datetime, timezone

from demo.host_monitor import probe_host, _classify_role


# ── Vendor lookup (compact OUI prefix → vendor map) ──────────────────────────
# This is intentionally short; covers the most common consumer/enterprise
# vendors you'd see on a typical LAN. Easy to extend.
OUI_VENDORS: dict[str, str] = {
    "00:0c:29": "VMware",      "00:50:56": "VMware",        "00:05:69": "VMware",
    "00:1c:14": "VMware",      "00:1c:42": "Parallels",
    "08:00:27": "VirtualBox",
    "52:54:00": "QEMU/KVM",
    "00:15:5d": "Microsoft Hyper-V",
    "f4:1e:57": "TP-Link",     "1c:61:b4": "TP-Link",       "b0:4e:26": "TP-Link",
    "00:1f:3a": "Cisco",       "00:1c:0e": "Cisco",         "f4:cf:e2": "Cisco",
                               "70:db:98": "Cisco Meraki",  "00:1b:24": "Cisco",
    "00:0c:42": "MikroTik",    "4c:5e:0c": "MikroTik",      "6c:3b:6b": "MikroTik",
    "fc:ec:da": "Ubiquiti",    "78:8a:20": "Ubiquiti",      "24:5a:4c": "Ubiquiti",
    "00:0d:b9": "PC Engines",  "44:38:39": "Cumulus",
    "00:50:f9": "HP",          "00:1f:29": "HP",            "94:57:a5": "HP",
    "00:21:f6": "Dell",        "f8:bc:12": "Dell",          "f4:8e:38": "Dell",
    "00:09:0f": "Fortinet",    "00:1a:6c": "Comcast",
    "ac:de:48": "Apple (private)", "f0:18:98": "Apple",     "a4:83:e7": "Apple",
                               "3c:22:fb": "Apple",         "f4:5c:89": "Apple",
    "98:01:a7": "Apple",       "a8:60:b6": "Apple",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    "c4:e9:0a": "Google",      "f4:f5:d8": "Google",        "1a:11:bf": "Google",
    "00:17:c8": "Samsung",     "5c:0a:5b": "Samsung",       "00:23:99": "Samsung",
    "94:e9:79": "Huawei",      "00:1e:10": "Huawei",        "fc:01:74": "Huawei",
    "00:30:48": "Supermicro",  "ac:1f:6b": "Supermicro",
    "a4:bb:6d": "Intel",       "00:13:e8": "Intel",         "00:21:6a": "Intel",
                               "ac:2b:6e": "Intel",
    "00:e0:4c": "Realtek",
    "00:11:22": "Cimsys",
    "00:1a:1e": "Aruba",       "20:4c:03": "Aruba",
    "00:24:a8": "Juniper",     "00:90:69": "Juniper",
    "00:04:9f": "Freescale",
    "20:cf:30": "ASRock",
    "00:25:90": "Super Micro",
    "fc:c8:97": "Inteno",
    "00:50:ba": "D-Link",      "1c:af:f7": "D-Link",
    "00:18:e7": "CMD-Tech",
    "e8:6f:38": "Zyxel",       "10:7b:ef": "Zyxel",
    "00:23:54": "ASUSTek",     "30:5a:3a": "ASUSTek",       "ac:9e:17": "ASUSTek",
                               "1c:b7:2c": "ASUSTek",
    "00:1d:0f": "TP-LINK",
}


def _lookup_vendor(mac: str) -> str:
    """Match the OUI (first 3 octets) against the built-in table."""
    if not mac or len(mac) < 8:
        return "Unknown"
    key = mac.lower().replace("-", ":")[:8]
    return OUI_VENDORS.get(key, "Unknown")


def _guess_os_from_ports(open_ports: list[dict], mac_vendor: str = "") -> str:
    """Heuristic OS detection based on listening ports + MAC vendor."""
    portset = {p["port"] for p in open_ports}
    if portset & {3389, 5985, 5986, 135, 445}:
        return "Windows"
    if portset & {22} and not (portset & {445}):
        return "Linux/Unix"
    if "Apple" in mac_vendor:
        return "macOS / iOS"
    if "Raspberry Pi" in mac_vendor:
        return "Raspberry Pi OS (Linux)"
    if "VMware" in mac_vendor or "VirtualBox" in mac_vendor or "Hyper-V" in mac_vendor:
        return "Virtual Machine"
    if "MikroTik" in mac_vendor:
        return "RouterOS"
    if "Ubiquiti" in mac_vendor:
        return "UniFi OS"
    if "Cisco" in mac_vendor:
        return "Cisco IOS"
    return "Unknown"


# ── Subnet / interface detection ─────────────────────────────────────────────


def detect_local_subnet() -> tuple[str | None, str | None]:
    """Return (local_ip, /24 cidr) for the primary interface."""
    try:
        # Trick: open a UDP socket to a public IP — the kernel picks the
        # outbound interface but no packet is actually sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 53))
            local_ip = s.getsockname()[0]
        net = ipaddress.ip_network(f"{local_ip}/24", strict=False)
        return local_ip, str(net)
    except Exception:
        return None, None


# ── ARP table parsing (cross-platform) ───────────────────────────────────────

_ARP_LINE = re.compile(r"\(?(\d+\.\d+\.\d+\.\d+)\)?\s+(?:at\s+)?([0-9a-fA-F:-]{17})")


async def _read_arp_table() -> dict[str, str]:
    """Return {ip: mac} from the OS ARP cache."""
    cmd = ["arp", "-a"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=4.0)
        except asyncio.TimeoutError:
            proc.kill()
            return {}
        text = out.decode("utf-8", "ignore")
    except Exception:
        return {}

    table: dict[str, str] = {}
    for line in text.splitlines():
        m = _ARP_LINE.search(line)
        if not m:
            continue
        ip, mac = m.group(1), m.group(2).lower().replace("-", ":")
        if mac.startswith("ff:ff:ff") or mac == "00:00:00:00:00:00":
            continue
        if ip.endswith(".255") or ip.startswith("224.") or ip.startswith("239."):
            continue
        table[ip] = mac
    return table


# ── Reverse DNS ──────────────────────────────────────────────────────────────


async def _reverse_dns(ip: str) -> str | None:
    """Reverse-lookup an IP to hostname (best-effort, no DNS server failures)."""
    try:
        loop = asyncio.get_running_loop()
        name = await asyncio.wait_for(
            loop.run_in_executor(None, socket.gethostbyaddr, ip),
            timeout=1.5,
        )
        return name[0]
    except Exception:
        return None


# ── Ping sweep (populates ARP cache) ─────────────────────────────────────────


async def _ping_one(ip: str, timeout_ms: int = 800) -> bool:
    is_win = platform.system().lower().startswith("win")
    cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip] if is_win else \
          ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=(timeout_ms / 1000) + 1.0)
        except asyncio.TimeoutError:
            proc.kill()
            return False
        return proc.returncode == 0
    except Exception:
        return False


async def _ping_sweep(cidr: str, *, concurrency: int = 64) -> set[str]:
    """Ping every host in the /24. Returns the set of IPs that replied."""
    net = ipaddress.ip_network(cidr, strict=False)
    sem = asyncio.Semaphore(concurrency)
    alive: set[str] = set()

    async def _one(ip: str):
        async with sem:
            if await _ping_one(ip):
                alive.add(ip)

    await asyncio.gather(*(_one(str(h)) for h in net.hosts()))
    return alive


# ── Public entry: discover the LAN ───────────────────────────────────────────


async def discover_lan(
    *,
    cidr: str | None = None,
    do_ping_sweep: bool = True,
    deep_probe: bool = True,
    progress_cb=None,
) -> dict:
    """Discover live hosts on the LAN.

    Args:
        cidr:           subnet to scan (default: auto-detect local /24)
        do_ping_sweep:  if True, ARP cache is warmed via parallel ping first
        deep_probe:     if True, TCP-probes each live host for ports/services
        progress_cb:    optional async callable invoked with progress dicts

    Returns a dict with `subnet`, `scanned_at`, `host_count`, and `hosts[]`.
    """
    local_ip, auto_cidr = detect_local_subnet()
    target = cidr or auto_cidr
    if not target:
        return {"error": "could not detect local subnet"}

    started = datetime.now(timezone.utc)
    if progress_cb:
        await progress_cb({"phase": "start", "subnet": target, "local_ip": local_ip})

    # Stage 1 — ping sweep to populate ARP
    pinged: set[str] = set()
    if do_ping_sweep:
        if progress_cb:
            await progress_cb({"phase": "ping_sweep", "msg": f"Pinging {target} ..."})
        pinged = await _ping_sweep(target)
        if progress_cb:
            await progress_cb({"phase": "ping_done", "alive_count": len(pinged)})

    # Stage 2 — read ARP table
    arp = await _read_arp_table()
    if progress_cb:
        await progress_cb({"phase": "arp_read", "arp_entries": len(arp)})

    # Build candidate set: union of pinged + ARP
    candidates: dict[str, str] = {}        # ip → mac (or "" if unknown)
    for ip in pinged:
        candidates.setdefault(ip, arp.get(ip, ""))
    for ip, mac in arp.items():
        candidates.setdefault(ip, mac)

    # Drop IPs outside the subnet (e.g. router LAN-side from another segment)
    try:
        net = ipaddress.ip_network(target, strict=False)
        candidates = {ip: mac for ip, mac in candidates.items()
                      if ipaddress.ip_address(ip) in net}
    except Exception:
        pass

    if progress_cb:
        await progress_cb({"phase": "enrich", "candidate_count": len(candidates)})

    # Stage 3 — enrich each candidate
    sem = asyncio.Semaphore(16)

    async def _enrich(ip: str, mac: str) -> dict:
        async with sem:
            hostname_task = _reverse_dns(ip)
            probe_task = probe_host(ip, port_timeout=0.6) if deep_probe else None

            hostname = await hostname_task
            probe    = await probe_task if probe_task else {"ping_ok": True, "tcp_open": [], "rtt_ms": None, "method": "skipped"}

            vendor = _lookup_vendor(mac)
            os_guess = _guess_os_from_ports(probe.get("tcp_open", []), vendor)
            roles    = _classify_role(probe.get("tcp_open", []))

            return {
                "ip":              ip,
                "mac":             mac or None,
                "hostname":        hostname or "—",
                "vendor":          vendor,
                "os_guess":        os_guess,
                "roles":           roles,
                "live_status":     "online" if probe.get("ping_ok") else "offline",
                "rtt_ms":          probe.get("rtt_ms"),
                "open_ports":      probe.get("tcp_open", []),
                "is_local_host":   ip == local_ip,
                "is_gateway":      ip.endswith(".1") and not ip.endswith("0.1") if "." in ip else False,
                "discovered_at":   datetime.now(timezone.utc).isoformat(),
            }

    enriched: list[dict] = []
    for coro in asyncio.as_completed([_enrich(ip, mac) for ip, mac in candidates.items()]):
        host = await coro
        enriched.append(host)
        if progress_cb:
            await progress_cb({"phase": "host_found", "host": host, "progress": len(enriched), "total": len(candidates)})

    # Sort by IP numerically
    enriched.sort(key=lambda h: tuple(int(x) for x in h["ip"].split(".")))

    finished = datetime.now(timezone.utc)
    elapsed = (finished - started).total_seconds()
    return {
        "subnet":        target,
        "local_ip":      local_ip,
        "scanned_at":    started.isoformat(),
        "elapsed_s":     round(elapsed, 1),
        "host_count":    len(enriched),
        "hosts":         enriched,
    }
