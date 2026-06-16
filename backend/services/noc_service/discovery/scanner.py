"""
Core network scanning engine.

Discovery strategy (each step degrades gracefully):

1. Determine the target subnet -- auto-detected local subnet, or an explicit
   override. Only **private/local** subnets are ever scanned; external IPs are
   rejected outright.
2. ARP sweep (Layer-2) to learn live hosts + MAC addresses:
     * scapy ``arping`` when scapy is installed and the process is privileged,
     * otherwise the OS ARP cache (populated by the ping sweep below).
3. Host discovery (Layer-3):
     * nmap ``-sn`` ping scan when the nmap binary + python-nmap are available,
     * otherwise a multi-threaded TCP-connect ping sweep (pure python).
4. Per-host enrichment (multi-threaded): reverse-DNS hostname, light TCP port
   probe, MAC/vendor resolution and device-type classification.

Only **live** hosts are returned; offline hosts are never included.
"""
from __future__ import annotations

import concurrent.futures as cf
import ipaddress
import logging
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from backend.services.noc_service.discovery import classifier
from backend.services.noc_service.discovery.config import discovery_settings
from backend.services.noc_service.discovery.netinfo import (
    get_default_gateway,
    get_local_subnet,
    is_private_subnet,
    read_arp_cache,
)
from backend.services.noc_service.discovery.oui import lookup_vendor, normalize_mac

logger = logging.getLogger("discovery.scanner")

# Optional dependencies -- imported lazily / defensively.
try:
    import nmap  # python-nmap
except Exception:  # pragma: no cover
    nmap = None

try:
    from scapy.all import ARP, Ether, conf as scapy_conf, srp  # type: ignore
except Exception:  # pragma: no cover
    ARP = Ether = srp = scapy_conf = None


@dataclass
class DiscoveredHost:
    ip_address: str
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    device_type: Optional[str] = None
    open_ports: list[int] = field(default_factory=list)
    is_gateway: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanResult:
    subnet: str
    method: str
    started_at: float
    duration: float
    hosts: list[DiscoveredHost]

    def to_dict(self) -> dict:
        return {
            "subnet": self.subnet,
            "method": self.method,
            "duration_sec": round(self.duration, 2),
            "host_count": len(self.hosts),
            "hosts": [h.to_dict() for h in self.hosts],
        }


class NetworkScanner:
    """Discovers live hosts on the local subnet only."""

    def __init__(self, settings=discovery_settings):
        self.settings = settings

    # ── public API ─────────────────────────────────────────────────────────
    def resolve_subnet(self, override: str | None = None) -> str:
        subnet = override or self.settings.SUBNET_OVERRIDE or get_local_subnet()
        if not subnet:
            raise RuntimeError("Could not determine local subnet; set SUBNET_OVERRIDE.")
        if not is_private_subnet(subnet):
            raise ValueError(
                f"Refusing to scan non-private subnet '{subnet}'. "
                "This tool only scans local/private networks."
            )
        net = ipaddress.ip_network(subnet, strict=False)
        if net.num_addresses > self.settings.MAX_HOSTS:
            raise ValueError(
                f"Subnet {subnet} has {net.num_addresses} addresses "
                f"(> MAX_HOSTS={self.settings.MAX_HOSTS}). Narrow the range."
            )
        return str(net)

    def scan(self, subnet: str | None = None) -> ScanResult:
        started = time.time()
        target = self.resolve_subnet(subnet)
        gateway = get_default_gateway()
        logger.info("Scanning %s (gateway=%s)", target, gateway)

        methods: list[str] = []

        # Step 1: ARP -> {ip: mac}
        arp_map = self._arp_scan(target)
        if arp_map:
            methods.append("arp")

        # Step 2: live host set (nmap ping scan or threaded TCP sweep)
        live, host_method, nmap_data = self._discover_live_hosts(target)
        methods.append(host_method)

        # Merge ARP hits (they are definitively live too)
        live |= set(arp_map.keys())

        # Refresh ARP cache after the sweep (the sweep populates it)
        arp_map = {**read_arp_cache(), **arp_map}

        # Restrict to addresses inside the target network only.
        net = ipaddress.ip_network(target, strict=False)
        live = {ip for ip in live if _ip_in_net(ip, net)}

        # Step 3: threaded enrichment
        hosts = self._enrich_hosts(sorted(live, key=_ip_sort_key), arp_map, gateway, nmap_data)

        duration = time.time() - started
        return ScanResult(
            subnet=target,
            method="+".join(dict.fromkeys(methods)),
            started_at=started,
            duration=duration,
            hosts=hosts,
        )

    # ── ARP ─────────────────────────────────────────────────────────────────
    def _arp_scan(self, subnet: str) -> dict[str, str]:
        if not (self.settings.USE_SCAPY_ARP and srp is not None):
            return {}
        try:
            scapy_conf.verb = 0
            answered, _ = srp(
                Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet),
                timeout=3,
                retry=1,
            )
            out: dict[str, str] = {}
            for _sent, recv in answered:
                mac = normalize_mac(recv.hwsrc)
                if mac:
                    out[recv.psrc] = mac
            logger.info("scapy ARP found %d hosts", len(out))
            return out
        except PermissionError:
            logger.warning("scapy ARP needs root/admin; falling back to ARP cache.")
        except Exception as exc:  # pragma: no cover
            logger.warning("scapy ARP failed (%s); falling back.", exc)
        return {}

    # ── host discovery ────────────────────────────────────────────────────
    def _discover_live_hosts(self, subnet: str) -> tuple[set[str], str, dict]:
        if self.settings.USE_NMAP and nmap is not None:
            try:
                return self._nmap_ping_scan(subnet)
            except Exception as exc:
                logger.warning("nmap scan failed (%s); using TCP sweep.", exc)
        return self._tcp_ping_sweep(subnet), "tcp-sweep", {}

    def _nmap_ping_scan(self, subnet: str) -> tuple[set[str], str, dict]:
        nm = nmap.PortScanner()
        # -sn: ping scan (host discovery, no port scan). Add a tiny top-port
        # SYN scan for classification signals when privileged; -sn keeps it
        # fast and unprivileged-friendly.
        nm.scan(hosts=subnet, arguments="-sn -T4")
        live = {h for h in nm.all_hosts() if nm[h].state() == "up"}
        data: dict = {}
        for h in live:
            entry: dict = {}
            addrs = nm[h].get("addresses", {})
            if "mac" in addrs:
                entry["mac"] = normalize_mac(addrs["mac"])
            vendor = nm[h].get("vendor", {})
            if vendor:
                entry["vendor"] = next(iter(vendor.values()))
            data[h] = entry
        logger.info("nmap ping scan found %d live hosts", len(live))
        return live, "nmap", data

    def _tcp_ping_sweep(self, subnet: str) -> set[str]:
        """Pure-python liveness: a host is 'up' if any probe port accepts/refuses."""
        net = ipaddress.ip_network(subnet, strict=False)
        hosts = [str(ip) for ip in net.hosts()]
        live: set[str] = set()
        ports = self.settings.PROBE_PORTS
        timeout = self.settings.HOST_TIMEOUT

        def probe(ip: str) -> Optional[str]:
            # ICMP needs root; instead try a few common TCP ports. A RST
            # (ConnectionRefused) also proves the host is alive.
            for port in ports[:6]:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(timeout)
                        rc = s.connect_ex((ip, port))
                        if rc == 0 or rc in (111, 10061):  # open or refused
                            return ip
                except OSError:
                    continue
            return None

        with cf.ThreadPoolExecutor(max_workers=self.settings.MAX_WORKERS) as ex:
            for result in ex.map(probe, hosts):
                if result:
                    live.add(result)
        logger.info("TCP sweep found %d live hosts", len(live))
        return live

    # ── enrichment ──────────────────────────────────────────────────────────
    def _enrich_hosts(
        self,
        ips: list[str],
        arp_map: dict[str, str],
        gateway: str | None,
        nmap_data: dict,
    ) -> list[DiscoveredHost]:
        def enrich(ip: str) -> DiscoveredHost:
            ndata = nmap_data.get(ip, {})
            mac = ndata.get("mac") or arp_map.get(ip)
            mac = normalize_mac(mac) if mac else None
            vendor = ndata.get("vendor") or (lookup_vendor(mac) if mac else "Unknown")
            hostname = _reverse_dns(ip)
            open_ports = self._scan_ports(ip)
            is_gw = bool(gateway and ip == gateway)
            dtype = classifier.classify(
                open_ports=set(open_ports),
                vendor=vendor,
                hostname=hostname,
                is_gateway=is_gw,
            )
            return DiscoveredHost(
                ip_address=ip,
                mac_address=mac,
                hostname=hostname,
                vendor=vendor,
                device_type=dtype,
                open_ports=open_ports,
                is_gateway=is_gw,
            )

        with cf.ThreadPoolExecutor(max_workers=self.settings.MAX_WORKERS) as ex:
            return list(ex.map(enrich, ips))

    def _scan_ports(self, ip: str) -> list[int]:
        open_ports: list[int] = []
        timeout = self.settings.HOST_TIMEOUT

        def check(port: int) -> Optional[int]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    if s.connect_ex((ip, port)) == 0:
                        return port
            except OSError:
                return None
            return None

        ports = self.settings.PROBE_PORTS
        with cf.ThreadPoolExecutor(max_workers=min(len(ports), 24)) as ex:
            for r in ex.map(check, ports):
                if r is not None:
                    open_ports.append(r)
        return sorted(open_ports)


# ── helpers ────────────────────────────────────────────────────────────────────
def _reverse_dns(ip: str) -> Optional[str]:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return None


def _ip_in_net(ip: str, net: ipaddress._BaseNetwork) -> bool:
    try:
        return ipaddress.ip_address(ip) in net
    except ValueError:
        return False


def _ip_sort_key(ip: str):
    try:
        return int(ipaddress.ip_address(ip))
    except ValueError:
        return 0
