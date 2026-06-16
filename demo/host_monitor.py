"""
Real-time host reachability monitor + deep analyzer.

* `start_monitor(host_provider, broadcaster)` launches a continuous background
  loop that probes every host (TCP-connect to common admin ports; falls back
  to OS `ping` if no port responds) and broadcasts status changes via WebSocket.
* `analyze_host(host)` runs a full diagnostic and returns a structured report
  (reachability, open ports/services, perf snapshot, config heuristics,
  security findings, root cause analysis).

Designed to be safe on a laptop: it scans only the IPs in the host list
provided to it, never the whole internet. Probes are async + bounded by a
semaphore so it won't flood the host machine.
"""
from __future__ import annotations
import asyncio
import platform
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable

# Common admin/service ports to probe — host is "alive" if ANY responds.
TCP_PROBE_PORTS: list[tuple[int, str]] = [
    (22,    "SSH"),
    (23,    "Telnet"),
    (80,    "HTTP"),
    (135,   "RPC"),
    (139,   "NetBIOS"),
    (443,   "HTTPS"),
    (445,   "SMB"),
    (3306,  "MySQL"),
    (3389,  "RDP"),
    (5432,  "PostgreSQL"),
    (5985,  "WinRM-HTTP"),
    (5986,  "WinRM-HTTPS"),
    (6379,  "Redis"),
    (8080,  "HTTP-Alt"),
    (8443,  "HTTPS-Alt"),
    (9200,  "Elasticsearch"),
    (27017, "MongoDB"),
]

INSECURE_PORTS = {21: "FTP", 23: "Telnet", 69: "TFTP", 161: "SNMP v1/v2c", 512: "rexec", 513: "rlogin", 514: "rsh"}


async def _tcp_probe(ip: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to (ip, port) succeeds within timeout."""
    try:
        fut  = asyncio.open_connection(ip, port)
        r, w = await asyncio.wait_for(fut, timeout=timeout)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _icmp_ping(ip: str, timeout_ms: int = 1500) -> tuple[bool, float | None]:
    """Best-effort OS `ping` (one packet). Returns (alive, rtt_ms).

    Windows quirk: `ping` returns exit 0 even when the destination is
    unreachable (e.g. "TTL expired in transit" or "Destination net
    unreachable" replies from an intermediate router). We must parse the
    output to confirm we actually got an echo-reply from the target.
    """
    is_win = platform.system().lower().startswith("win")
    cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip] if is_win else \
          ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=(timeout_ms / 1000) + 1.0)
        except asyncio.TimeoutError:
            proc.kill()
            return False, None

        text = out.decode("utf-8", "ignore").lower()

        # Hard-fail markers — even if exit was 0, these mean "not reachable"
        fail_markers = (
            "ttl expired",
            "destination host unreachable",
            "destination net unreachable",
            "destination port unreachable",
            "request timed out",
            "100% loss",
            "100% packet loss",
            "could not find host",
            "general failure",
        )
        if any(m in text for m in fail_markers):
            return False, None

        if proc.returncode != 0:
            return False, None

        # Parse RTT from "time=Xms" or "time<Xms"
        rtt: float | None = None
        for token in ("time=", "time<"):
            i = text.find(token)
            if i != -1:
                tail = text[i + len(token):i + len(token) + 12]
                num = ""
                for ch in tail:
                    if ch.isdigit() or ch == ".":
                        num += ch
                    else:
                        break
                if num:
                    try:
                        rtt = float(num)
                    except ValueError:
                        rtt = None
                break
        return True, rtt
    except Exception:
        return False, None


async def probe_host(ip: str, *, port_timeout: float = 0.7) -> dict:
    """Single-IP reachability probe used by both monitor + analyzer."""
    if not ip or ip == "0.0.0.0":
        return {"ping_ok": False, "tcp_open": [], "method": "skipped", "rtt_ms": None}

    # 1. Quick scan of admin ports — cheap, doesn't need admin rights
    open_ports: list[dict] = []
    sem = asyncio.Semaphore(8)

    async def _check(port_svc: tuple[int, str]):
        port, svc = port_svc
        async with sem:
            if await _tcp_probe(ip, port, timeout=port_timeout):
                open_ports.append({"port": port, "service": svc})

    await asyncio.gather(*(_check(p) for p in TCP_PROBE_PORTS))

    tcp_alive = bool(open_ports)

    # 2. Fall back to ICMP if no TCP port answered
    icmp_alive, rtt = (True, None) if tcp_alive else await _icmp_ping(ip)

    method = "tcp" if tcp_alive else ("icmp" if icmp_alive else "none")
    return {
        "ping_ok":  tcp_alive or icmp_alive,
        "tcp_open": sorted(open_ports, key=lambda x: x["port"]),
        "rtt_ms":   rtt,
        "method":   method,
    }


# ── Continuous monitor ───────────────────────────────────────────────────────

HostProvider = Callable[[], Iterable[dict]]
Broadcaster  = Callable[[dict], Awaitable[None]]


class HostMonitor:
    """Polls every host in the provider at a fixed interval and broadcasts
    online/offline transitions. State is mutated in-place on the host dict
    (sets `live_status`, `last_seen`, `rtt_ms`, `monitored`)."""

    def __init__(self, provider: HostProvider, broadcaster: Broadcaster, interval: float = 8.0):
        self.provider    = provider
        self.broadcast   = broadcaster
        self.interval    = interval
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self._stop.set()

    async def _loop(self):
        while not self._stop.is_set():
            try:
                hosts = list(self.provider())
                await asyncio.gather(*(self._poll_one(h) for h in hosts), return_exceptions=True)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                continue

    async def _poll_one(self, host: dict):
        ip = host.get("ip")
        if not ip:
            return
        result = await probe_host(ip, port_timeout=0.5)
        new_status = "online" if result["ping_ok"] else "offline"
        old_status = host.get("live_status")

        host["live_status"] = new_status
        host["monitored"]   = True
        host["rtt_ms"]      = result["rtt_ms"]
        host["last_probed"] = datetime.now(timezone.utc).isoformat()
        if new_status == "online":
            host["last_seen"] = host["last_probed"]

        if old_status != new_status:
            await self.broadcast({
                "type":          "host_status_change",
                "host_id":       host.get("id"),
                "hostname":      host.get("hostname"),
                "ip":            ip,
                "previous":      old_status or "unknown",
                "current":       new_status,
                "rtt_ms":        result["rtt_ms"],
                "tcp_open":      result["tcp_open"],
                "ts":            host["last_probed"],
            })


# ── Deep analysis ────────────────────────────────────────────────────────────


def _classify_role(open_ports: list[dict]) -> list[str]:
    """Guess what kind of host this is based on what's listening."""
    portset = {p["port"] for p in open_ports}
    roles = []
    if portset & {80, 443, 8080, 8443}:           roles.append("Web Server")
    if portset & {22}:                            roles.append("Linux/Unix")
    if portset & {3389, 5985, 5986, 135, 445}:    roles.append("Windows")
    if portset & {3306, 5432, 27017, 6379}:       roles.append("Database")
    if portset & {9200}:                          roles.append("Elasticsearch")
    if portset & {161}:                           roles.append("SNMP-managed network device")
    return roles


def _security_findings(open_ports: list[dict]) -> list[dict]:
    findings = []
    portset = {p["port"]: p for p in open_ports}

    for port, name in INSECURE_PORTS.items():
        if port in portset:
            findings.append({
                "severity":      "high",
                "title":         f"Insecure protocol {name} (tcp/{port}) exposed",
                "recommendation": f"Disable {name}, migrate to encrypted alternative",
            })

    if 23 in portset:
        findings.append({"severity": "critical", "title": "Telnet enabled — cleartext credentials",
                         "recommendation": "Disable telnetd, use SSH only"})
    if 3389 in portset:
        findings.append({"severity": "medium", "title": "RDP exposed (tcp/3389)",
                         "recommendation": "Restrict RDP to jumphost/VPN, enable NLA + MFA"})
    if 5432 in portset:
        findings.append({"severity": "medium", "title": "PostgreSQL port reachable",
                         "recommendation": "Restrict pg_hba.conf to app subnet, require TLS"})
    if 6379 in portset:
        findings.append({"severity": "high", "title": "Redis exposed (tcp/6379)",
                         "recommendation": "Bind to localhost or require AUTH + TLS"})
    if 9200 in portset:
        findings.append({"severity": "high", "title": "Elasticsearch exposed",
                         "recommendation": "Enable X-Pack security, restrict to ingest subnet"})
    return findings


def _performance_findings(metrics: dict) -> list[dict]:
    out = []
    cpu  = metrics.get("cpu",  0) or 0
    mem  = metrics.get("mem",  0) or 0
    disk = metrics.get("disk", 0) or 0
    if cpu >= 90:  out.append({"severity": "critical", "title": f"CPU saturated at {cpu}%",       "metric": "cpu",  "value": cpu})
    elif cpu >= 80: out.append({"severity": "high",    "title": f"CPU pressure ({cpu}%)",         "metric": "cpu",  "value": cpu})
    if mem >= 90:  out.append({"severity": "critical", "title": f"Memory critical ({mem}%)",     "metric": "mem",  "value": mem})
    elif mem >= 80: out.append({"severity": "high",    "title": f"Memory high ({mem}%)",          "metric": "mem",  "value": mem})
    if disk >= 90: out.append({"severity": "critical", "title": f"Disk almost full ({disk}%)",    "metric": "disk", "value": disk})
    elif disk >= 80: out.append({"severity": "high",   "title": f"Disk usage high ({disk}%)",     "metric": "disk", "value": disk})
    return out


def _config_findings(host: dict, open_ports: list[dict]) -> list[dict]:
    findings = []
    if not host.get("agent_installed") and not open_ports:
        findings.append({"severity": "medium", "title": "No monitoring agent or admin port detected",
                         "recommendation": "Install AEAOP agent or enable SSH/WinRM"})
    if host.get("os_version") in (None, "", "unknown"):
        findings.append({"severity": "low", "title": "OS version unknown",
                         "recommendation": "Run SNMP sysDescr / agent check-in to populate"})
    if host.get("snmp_version") in ("v1", "v2c"):
        findings.append({"severity": "high", "title": "SNMP v1/v2c in use (cleartext community)",
                         "recommendation": "Migrate to SNMPv3 with authPriv"})
    return findings


async def analyze_host(host: dict, *, related_alerts: list[dict] | None = None) -> dict:
    """Full diagnostic. Returns a snapshot ready for AI consumption."""
    t0 = time.time()
    ip = host.get("ip", "")
    probe = await probe_host(ip, port_timeout=0.8) if ip else {"ping_ok": False, "tcp_open": [], "rtt_ms": None, "method": "skipped"}

    metrics = {k: host.get(k) for k in ("cpu", "mem", "disk", "uptime") if host.get(k) is not None}

    perf_findings = _performance_findings(metrics)
    sec_findings  = _security_findings(probe["tcp_open"])
    cfg_findings  = _config_findings(host, probe["tcp_open"])
    detected_role = _classify_role(probe["tcp_open"])

    # Build a one-line RCA summary
    if not probe["ping_ok"]:
        rca = f"Host {host.get('hostname', ip)} is currently unreachable on all probed channels (TCP/ICMP). Possible causes: powered off, network isolation, firewall block, or NIC failure."
    elif perf_findings:
        worst = sorted(perf_findings, key=lambda f: {"critical": 0, "high": 1, "medium": 2, "low": 3}[f["severity"]])[0]
        rca = f"Performance pressure: {worst['title']}. Likely cause: workload spike, memory/disk leak, or runaway process."
    elif sec_findings:
        rca = f"Reachable & performing, but {len(sec_findings)} security exposure(s) detected — review listening services."
    else:
        rca = "No issues detected at this time."

    return {
        "host_id":      host.get("id"),
        "hostname":     host.get("hostname"),
        "ip":           ip,
        "analyzed_at":  datetime.now(timezone.utc).isoformat(),
        "elapsed_ms":   int((time.time() - t0) * 1000),
        "reachability": {
            "ping_ok":  probe["ping_ok"],
            "method":   probe["method"],
            "rtt_ms":   probe["rtt_ms"],
        },
        "ports": {
            "scanned":  len(TCP_PROBE_PORTS),
            "open":     probe["tcp_open"],
            "insecure": [p for p in probe["tcp_open"] if p["port"] in INSECURE_PORTS],
        },
        "detected_role": detected_role,
        "metrics":       metrics,
        "findings": {
            "performance": perf_findings,
            "security":    sec_findings,
            "configuration": cfg_findings,
            "total":       len(perf_findings) + len(sec_findings) + len(cfg_findings),
        },
        "related_alerts": [a for a in (related_alerts or [])
                           if a.get("device") == host.get("hostname")][:5],
        "rca_summary": rca,
    }
