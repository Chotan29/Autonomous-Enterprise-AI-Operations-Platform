"""
AEAOP — Autonomous Enterprise AI Operations Platform
Self-contained Demo Server (no Docker, no external DBs required)
Runs with: python demo/app.py
"""
import asyncio
import json
import os
import random
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="AEAOP Demo", docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── In-memory demo store ──────────────────────────────────────────────────────

DEMO_DEVICES = [
    {"id": "d1", "hostname": "core-rtr-01", "ip": "10.0.0.1",  "vendor": "Cisco",    "category": "Router",   "status": "online",  "cpu": 45, "mem": 62, "location": "DC1-A01", "uptime": 2345678},
    {"id": "d2", "hostname": "core-rtr-02", "ip": "10.0.0.2",  "vendor": "Cisco",    "category": "Router",   "status": "online",  "cpu": 38, "mem": 55, "location": "DC1-A02", "uptime": 2300000},
    {"id": "d3", "hostname": "dist-sw-01",  "ip": "10.0.1.1",  "vendor": "Cisco",    "category": "Switch",   "status": "online",  "cpu": 22, "mem": 41, "location": "DC1-B01", "uptime": 5678901},
    {"id": "d4", "hostname": "dist-sw-02",  "ip": "10.0.1.2",  "vendor": "Cisco",    "category": "Switch",   "status": "online",  "cpu": 18, "mem": 38, "location": "DC1-B02", "uptime": 5600000},
    {"id": "d5", "hostname": "acc-sw-01",   "ip": "10.0.2.1",  "vendor": "HP",       "category": "Switch",   "status": "online",  "cpu": 12, "mem": 28, "location": "FL1-C01", "uptime": 8765432},
    {"id": "d6", "hostname": "fw-01",       "ip": "10.0.0.254","vendor": "Fortinet", "category": "Firewall", "status": "online",  "cpu": 31, "mem": 49, "location": "DC1-FW",  "uptime": 3456789},
    {"id": "d7", "hostname": "fw-02",       "ip": "10.0.0.253","vendor": "Fortinet", "category": "Firewall", "status": "online",  "cpu": 29, "mem": 47, "location": "DC1-FW",  "uptime": 3450000},
    {"id": "d8", "hostname": "branch-rtr-01","ip": "192.168.1.1","vendor": "MikroTik","category": "Router",  "status": "degraded","cpu": 87, "mem": 78, "location": "BR1",     "uptime": 456789},
    {"id": "d9", "hostname": "isp-rtr-01",  "ip": "172.16.0.1","vendor": "Juniper",  "category": "Router",   "status": "online",  "cpu": 55, "mem": 60, "location": "DC1-ISP", "uptime": 9876543},
    {"id": "d10","hostname": "acc-ap-01",   "ip": "10.0.3.1",  "vendor": "Ubiquiti", "category": "AP",       "status": "offline", "cpu": 0,  "mem": 0,  "location": "FL1-D01", "uptime": 0},
]

# ── User's real servers (starts EMPTY — user adds their own) ─────────────────
DEMO_SERVERS: list[dict] = []

# Snapshot of initial demo servers (used by "Load Demo Data" only)
_DEMO_SERVERS_SNAPSHOT = [
    {"id":"s1","hostname":"web-prod-01",  "ip":"10.1.0.1",  "os":"Ubuntu 24.04","cpu":34,"mem":58,"disk":45,"status":"online", "role":"web"},
    {"id":"s2","hostname":"web-prod-02",  "ip":"10.1.0.2",  "os":"Ubuntu 24.04","cpu":29,"mem":54,"disk":42,"status":"online", "role":"web"},
    {"id":"s3","hostname":"db-prod-01",   "ip":"10.1.1.1",  "os":"RHEL 9",      "cpu":67,"mem":82,"disk":71,"status":"online", "role":"database"},
    {"id":"s4","hostname":"db-prod-02",   "ip":"10.1.1.2",  "os":"RHEL 9",      "cpu":12,"mem":45,"disk":68,"status":"online", "role":"database"},
    {"id":"s5","hostname":"app-prod-01",  "ip":"10.1.2.1",  "os":"Ubuntu 22.04","cpu":91,"mem":88,"disk":89,"status":"degraded","role":"application"},
    {"id":"s6","hostname":"k8s-node-01",  "ip":"10.1.3.1",  "os":"Ubuntu 24.04","cpu":43,"mem":61,"disk":38,"status":"online", "role":"kubernetes"},
    {"id":"s7","hostname":"k8s-node-02",  "ip":"10.1.3.2",  "os":"Ubuntu 24.04","cpu":39,"mem":57,"disk":35,"status":"online", "role":"kubernetes"},
    {"id":"s8","hostname":"backup-srv-01","ip":"10.1.4.1",  "os":"Windows 2022","cpu":8, "mem":22,"disk":93,"status":"warning","role":"backup"},
]

DEMO_ALERTS = [
    {"id": "a1", "severity": "critical", "category": "noc",    "title": "BGP Session Down: branch-rtr-01 ↔ isp-rtr-01",      "device": "branch-rtr-01", "status": "new",           "ai_rca": "BGP session dropped due to route refresh storm from peer AS65001. Hold timer expired after 180s.", "time": "2 min ago"},
    {"id": "a2", "severity": "critical", "category": "server", "title": "CPU Critical: app-prod-01 at 91%",                   "device": "app-prod-01",   "status": "in_progress",   "ai_rca": "Java heap memory leak in OrderProcessingService causing GC pressure and CPU spike.", "time": "5 min ago"},
    {"id": "a3", "severity": "high",     "category": "soc",    "title": "Brute Force Detected: 847 failed logins in 5 min",   "device": "fw-01",         "status": "acknowledged",  "ai_rca": "Credential stuffing attack from 185.220.101.45 targeting SSH on jump servers.", "time": "12 min ago"},
    {"id": "a4", "severity": "high",     "category": "noc",    "title": "Interface Down: acc-ap-01 GE0/1",                    "device": "acc-ap-01",     "status": "new",           "ai_rca": "Physical link failure detected. No LLDP neighbor since 08:42 UTC. Likely cable fault.", "time": "18 min ago"},
    {"id": "a5", "severity": "high",     "category": "server", "title": "Disk 93% Full: backup-srv-01 /data",                 "device": "backup-srv-01", "status": "new",           "ai_rca": "Backup retention policy not enforcing cleanup. Old backups from 90+ days accumulating.", "time": "23 min ago"},
    {"id": "a6", "severity": "medium",   "category": "soc",    "title": "Unusual Outbound Traffic: 2.3 GB to unknown IP",     "device": "web-prod-01",   "status": "new",           "ai_rca": "Possible data exfiltration or misconfigured backup job to 45.33.32.156 (Linode).", "time": "31 min ago"},
    {"id": "a7", "severity": "medium",   "category": "noc",    "title": "High CPU: branch-rtr-01 at 87%",                     "device": "branch-rtr-01", "status": "acknowledged",  "ai_rca": "BGP route calculation overload due to full table received from upstream peer.", "time": "35 min ago"},
    {"id": "a8", "severity": "low",      "category": "noc",    "title": "Interface Error Rate High: dist-sw-01 GE0/24",       "device": "dist-sw-01",    "status": "new",           "ai_rca": "CRC errors suggest duplex mismatch or cable degradation on uplink port.", "time": "42 min ago"},
    {"id": "a9", "severity": "medium",   "category": "server", "title": "Memory Warning: db-prod-01 at 82%",                  "device": "db-prod-01",    "status": "new",           "ai_rca": "PostgreSQL shared_buffers consuming 24 GB. Query cache hit ratio below 85%.", "time": "55 min ago"},
    {"id": "a10","severity": "low",      "category": "physec", "title": "Loitering Detected: Server Room Entrance Cam 3",     "device": "CAM-SR-03",     "status": "new",           "ai_rca": "Person detected near server room entrance for 8 minutes. After-hours (02:15 UTC).", "time": "1 hr ago"},
]

DEMO_INCIDENTS = [
    {"id": "i1", "number": "INC-2026-001247", "title": "BGP Flapping — Branch Network Degraded",       "severity": "critical", "status": "investigating", "assigned": "NOC Team",   "mitre": [], "created": "2 min ago",  "category": "noc"},
    {"id": "i2", "number": "INC-2026-001246", "title": "Credential Stuffing Attack on Jump Servers",   "severity": "high",     "status": "open",          "assigned": "SOC Team",   "mitre": ["TA0006","T1110"], "created": "12 min ago", "category": "soc"},
    {"id": "i3", "number": "INC-2026-001245", "title": "Application Server Resource Exhaustion",       "severity": "high",     "status": "mitigated",     "assigned": "Server Ops", "mitre": [], "created": "1 hr ago",   "category": "server"},
    {"id": "i4", "number": "INC-2026-001241", "title": "Ransomware Indicator — File Server Activity",  "severity": "critical", "status": "resolved",      "assigned": "SOC Team",   "mitre": ["TA0040","T1486"], "created": "3 hrs ago",  "category": "soc"},
    {"id": "i5", "number": "INC-2026-001238", "title": "WAN Link Degradation — Primary ISP Circuit",   "severity": "high",     "status": "resolved",      "assigned": "NOC Team",   "mitre": [], "created": "6 hrs ago",  "category": "noc"},
]

DEMO_HEALING = [
    {"id": "h1", "action": "restart_service",  "target": "app-prod-01",    "service": "OrderProcessingService", "risk": "low",    "status": "pending",  "ai_reason": "Service has accumulated 3.2 GB heap. Restart will clear GC overhead."},
    {"id": "h2", "action": "clear_disk_space", "target": "backup-srv-01",  "path": "/data/backups",              "risk": "low",    "status": "pending",  "ai_reason": "Delete backups older than 30 days to free ~40 GB of space."},
    {"id": "h3", "action": "rollback_config",  "target": "branch-rtr-01",  "version": "v14",                     "risk": "medium", "status": "pending",  "ai_reason": "Rollback to pre-BGP-peer-change config from 6 hours ago."},
    {"id": "h4", "action": "block_ip",         "target": "fw-01",          "ip": "185.220.101.45",               "risk": "low",    "status": "approved", "ai_reason": "Automated: IP in threat intel feed (abuse.ch). Block on perimeter."},
]

# ── Problem simulation state ──────────────────────────────────────────────────
ACTIVE_PROBLEMS: dict[str, dict] = {}   # server_id → problem data
HEALING_LOG:     list[dict]      = []   # full audit trail

# Extra servers that join in the "connect all" flow
EXTRA_SERVERS = [
    {"id":"e1","hostname":"mail-srv-01",  "ip":"10.1.5.1","os":"Ubuntu 22.04","cpu":22,"mem":44,"disk":38,"status":"online","role":"mail"},
    {"id":"e2","hostname":"dns-srv-01",   "ip":"10.1.5.2","os":"Ubuntu 24.04","cpu":8, "mem":18,"disk":22,"status":"online","role":"dns"},
    {"id":"e3","hostname":"file-srv-01",  "ip":"10.1.6.1","os":"Windows 2022","cpu":34,"mem":56,"disk":67,"status":"online","role":"fileserver"},
    {"id":"e4","hostname":"monitoring-01","ip":"10.1.6.2","os":"Ubuntu 24.04","cpu":45,"mem":62,"disk":48,"status":"online","role":"monitoring"},
    {"id":"e5","hostname":"proxy-srv-01", "ip":"10.1.7.1","os":"RHEL 9",      "cpu":18,"mem":31,"disk":29,"status":"online","role":"proxy"},
    {"id":"e6","hostname":"log-srv-01",   "ip":"10.1.7.2","os":"Ubuntu 24.04","cpu":12,"mem":25,"disk":91,"status":"warning","role":"logging"},
    {"id":"e7","hostname":"auth-srv-01",  "ip":"10.1.8.1","os":"RHEL 9",      "cpu":29,"mem":48,"disk":35,"status":"online","role":"auth"},
    {"id":"e8","hostname":"cache-srv-01", "ip":"10.1.8.2","os":"Ubuntu 22.04","cpu":55,"mem":78,"disk":42,"status":"online","role":"cache"},
]

DEMO_CAMERAS = [
    {"id": "c1", "name": "Main Entrance",     "location": "Ground Floor",   "status": "online",  "events_today": 12, "risk": "low"},
    {"id": "c2", "name": "Server Room",       "location": "DC Floor 2",     "status": "online",  "events_today": 3,  "risk": "medium"},
    {"id": "c3", "name": "Reception",         "location": "Ground Floor",   "status": "online",  "events_today": 47, "risk": "low"},
    {"id": "c4", "name": "Parking Lot N",     "location": "External",       "status": "online",  "events_today": 8,  "risk": "low"},
    {"id": "c5", "name": "Loading Dock",      "location": "Rear Entrance",  "status": "offline", "events_today": 0,  "risk": "low"},
    {"id": "c6", "name": "Executive Floor",   "location": "Floor 8",        "status": "online",  "events_today": 5,  "risk": "low"},
]

DEMO_RAG_RESPONSES = {
    "bgp": "**BGP Session Recovery (Cisco IOS-XE)**\n\n1. Verify BGP state: `show bgp summary`\n2. Check peer reachability: `ping <peer_ip> source <local_ip>`\n3. Clear soft: `clear ip bgp <peer_ip> soft`\n4. If still down, hard reset: `clear ip bgp <peer_ip>`\n5. Check logs: `show logging | include BGP`\n\n*Source: Cisco BGP Recovery Runbook v2.1*",
    "disk": "**Linux Disk Space Recovery**\n\n1. Find large files: `find / -size +100M -type f 2>/dev/null | sort -k5 -rn`\n2. Clean logs: `find /var/log -name '*.gz' -mtime +7 -delete`\n3. Journal: `journalctl --vacuum-time=7d`\n4. Package cache: `apt-get clean` or `yum clean all`\n\n*Source: Internal SOP — Storage Management v3.0*",
    "cpu": "**High CPU Investigation**\n\n1. Identify top process: `top -bn1 | head -20`\n2. Java GC analysis: `jstat -gcutil <pid> 1000 5`\n3. Thread dump: `jstack <pid> > /tmp/thread_dump.txt`\n4. If heap issue: restart service with increased heap or analyze dump\n\n*Source: Application Performance Runbook v1.8*",
    "ssh": "**SSH Brute Force Response**\n\n1. Block attacking IP at firewall: `iptables -I INPUT -s <ip> -j DROP`\n2. Check for successful logins: `grep 'Accepted' /var/log/auth.log`\n3. Reset compromised accounts if any\n4. Enable fail2ban if not active\n5. Review SSH config: disable password auth, use keys only\n\n*Source: SOC Playbook — Brute Force T1110*",
    "default": "**Enterprise Knowledge Base Response**\n\nBased on the AEAOP knowledge base including SOPs, runbooks, vendor manuals, and incident history, here is the recommended approach:\n\n1. Verify the alert is genuine (not a false positive)\n2. Identify affected systems and scope of impact\n3. Check similar past incidents for proven remediation steps\n4. Follow the appropriate runbook for this alert type\n5. Document actions taken in the incident timeline\n\n*Source: General Operations Runbook v5.2*"
}

# ── Live metrics generator ────────────────────────────────────────────────────
_connected_websockets: list[WebSocket] = []
_alert_counter = {"new": 3}


async def broadcast(data: dict):
    dead = []
    for ws in _connected_websockets:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connected_websockets.remove(ws)


async def metrics_generator():
    """Simulate live metrics — pushes updates every 3 seconds."""
    while True:
        await asyncio.sleep(3)
        # Fluctuate CPU on a few devices
        for dev in DEMO_DEVICES:
            if dev["status"] == "online":
                dev["cpu"] = max(5, min(98, dev["cpu"] + random.randint(-5, 5)))
                dev["mem"] = max(10, min(95, dev["mem"] + random.randint(-2, 2)))

        for srv in DEMO_SERVERS:
            if srv["status"] == "online":
                srv["cpu"] = max(3, min(98, srv["cpu"] + random.randint(-6, 6)))
                srv["mem"] = max(10, min(95, srv["mem"] + random.randint(-2, 2)))

        # Occasionally generate a new alert
        if random.random() < 0.08:
            new_alert = {
                "id": f"live_{int(time.time())}",
                "severity": random.choice(["medium", "low", "high"]),
                "category": random.choice(["noc", "soc", "server"]),
                "title": random.choice([
                    "Interface utilization > 80%: core-rtr-01 GE0/1",
                    "Memory threshold exceeded: dist-sw-01",
                    "Authentication failure spike detected",
                    "Packet loss detected on WAN link",
                    "SSL certificate expiring in 7 days",
                ]),
                "device": random.choice([d["hostname"] for d in DEMO_DEVICES]),
                "status": "new",
                "ai_rca": "AI analysis in progress...",
                "time": "just now",
            }
            DEMO_ALERTS.insert(0, new_alert)
            if len(DEMO_ALERTS) > 30:
                DEMO_ALERTS.pop()
            await broadcast({"type": "new_alert", "alert": new_alert})

        # Push live metrics
        await broadcast({
            "type": "metrics",
            "devices": [{"id": d["id"], "cpu": d["cpu"], "mem": d["mem"], "status": d["status"]} for d in DEMO_DEVICES],
            "servers": [{"id": s["id"], "cpu": s["cpu"], "mem": s["mem"]} for s in DEMO_SERVERS],
            "stats": {
                "online_devices": sum(1 for d in DEMO_DEVICES if d["status"] == "online"),
                "offline_devices": sum(1 for d in DEMO_DEVICES if d["status"] == "offline"),
                "open_alerts": sum(1 for a in DEMO_ALERTS if a["status"] in ("new", "in_progress")),
                "critical_alerts": sum(1 for a in DEMO_ALERTS if a["severity"] == "critical"),
            }
        })


# ── API Routes ────────────────────────────────────────────────────────────────

@app.get("/api/v1/dashboard/stats")
async def dashboard_stats():
    return {
        "devices": {
            "total": len(DEMO_DEVICES),
            "online": sum(1 for d in DEMO_DEVICES if d["status"] == "online"),
            "offline": sum(1 for d in DEMO_DEVICES if d["status"] == "offline"),
            "degraded": sum(1 for d in DEMO_DEVICES if d["status"] == "degraded"),
        },
        "servers": {
            "total": len(DEMO_SERVERS),
            "online": sum(1 for s in DEMO_SERVERS if s["status"] == "online"),
            "degraded": sum(1 for s in DEMO_SERVERS if s["status"] == "degraded"),
            "warning": sum(1 for s in DEMO_SERVERS if s["status"] == "warning"),
        },
        "alerts": {
            "total": len(DEMO_ALERTS),
            "critical": sum(1 for a in DEMO_ALERTS if a["severity"] == "critical"),
            "high": sum(1 for a in DEMO_ALERTS if a["severity"] == "high"),
            "open": sum(1 for a in DEMO_ALERTS if a["status"] in ("new", "in_progress")),
        },
        "incidents": {
            "open": sum(1 for i in DEMO_INCIDENTS if i["status"] not in ("resolved", "closed")),
            "total_today": len(DEMO_INCIDENTS),
        },
        "cameras": {
            "total": len(DEMO_CAMERAS),
            "online": sum(1 for c in DEMO_CAMERAS if c["status"] == "online"),
        },
        "healing": {
            "pending_approval": sum(1 for h in DEMO_HEALING if h["status"] == "pending"),
            "auto_approved": sum(1 for h in DEMO_HEALING if h["status"] == "approved"),
        },
        "ai_autonomous_rate": 68.4,
        "mttd_minutes": 4.2,
        "mttr_minutes": 18.7,
    }


class DeviceAddRequest(BaseModel):
    hostname: str
    ip: str
    vendor: str
    category: str
    snmp_version: str = "v2c"
    snmp_community: str = "public"
    location: str = ""
    ssh_username: str = ""
    ssh_password: str = ""

class DeviceScanRequest(BaseModel):
    ip_range: str
    snmp_community: str = "public"

class PCConnectRequest(BaseModel):
    hostname: str
    ip: str
    os_type: str          # windows | linux | macos
    connect_method: str   # agent | winrm | ssh
    username: str = ""
    password: str = ""
    location: str = ""
    department: str = ""
    role: str = "workstation"

class PCAgentCheckIn(BaseModel):
    hostname: str
    ip: str
    os_name: str
    os_version: str
    cpu_model: str
    cpu_cores: int
    ram_gb: int
    disk_gb: int
    agent_version: str = "1.0.0"


@app.get("/api/v1/noc/devices")
async def get_devices():
    return {"items": DEMO_DEVICES, "total": len(DEMO_DEVICES)}


@app.post("/api/v1/noc/devices")
async def add_device(body: DeviceAddRequest):
    """Add a new device and simulate initial SNMP discovery."""
    # Check duplicate IP
    if any(d["ip"] == body.ip for d in DEMO_DEVICES):
        return JSONResponse(status_code=409, content={"detail": f"Device with IP {body.ip} already exists"})

    new_id = f"d{len(DEMO_DEVICES)+1}_{int(time.time())}"
    new_device = {
        "id":       new_id,
        "hostname": body.hostname,
        "ip":       body.ip,
        "vendor":   body.vendor,
        "category": body.category,
        "status":   "polling",          # initial state
        "cpu":      0,
        "mem":      0,
        "location": body.location,
        "uptime":   0,
        "snmp_version":    body.snmp_version,
        "snmp_community":  body.snmp_community,
        "ssh_username":    body.ssh_username,
        "added_at":        datetime.now(timezone.utc).isoformat(),
        "discovery_steps": [],
    }
    DEMO_DEVICES.append(new_device)

    # Simulate background SNMP polling with AI analysis
    asyncio.create_task(_simulate_device_discovery(new_id, body))

    await broadcast({
        "type": "device_added",
        "device": {k: v for k, v in new_device.items() if k not in ("ssh_username",)},
    })
    return {"message": "Device added — initial discovery started", "device_id": new_id, "device": new_device}


@app.post("/api/v1/noc/discovery/scan")
async def scan_network(body: DeviceScanRequest):
    """Simulate network scan discovery."""
    scan_id = f"scan_{int(time.time())}"
    asyncio.create_task(_simulate_network_scan(scan_id, body.ip_range, body.snmp_community))
    return {
        "scan_id":     scan_id,
        "ip_range":    body.ip_range,
        "status":      "running",
        "message":     "Network scan started — results will appear as devices are discovered",
    }


@app.get("/api/v1/noc/discovery/scan/{scan_id}")
async def get_scan_status(scan_id: str):
    result = SCAN_RESULTS.get(scan_id)
    if not result:
        return {"scan_id": scan_id, "status": "running", "found": 0, "devices": []}
    return result


SCAN_RESULTS: dict = {}


async def _simulate_device_discovery(device_id: str, body: DeviceAddRequest):
    """Simulates: ping → SNMP poll → AI analysis → online."""
    dev = next((d for d in DEMO_DEVICES if d["id"] == device_id), None)
    if not dev:
        return

    steps = [
        (1.5, "ping",        f"Pinging {body.ip}..."),
        (2.0, "snmp_basic",  f"SNMP v{body.snmp_version} — sysDescr, sysName, sysUpTime"),
        (2.5, "snmp_ifaces", f"SNMP — Walking interface table (ifTable OID 1.3.6.1.2.1.2.2)"),
        (2.0, "lldp",        f"LLDP neighbor discovery (OID 1.0.8802.1.1.2.1.4)"),
        (1.5, "ai_analysis", f"AI analyzing device fingerprint and config..."),
        (1.0, "online",      f"Device online — added to monitoring"),
    ]

    VENDOR_SYSDESCRMAP = {
        "Cisco":    "Cisco IOS Software, Version 17.09.04a",
        "MikroTik": "RouterOS 7.14.3",
        "Juniper":  "Juniper Networks, Inc. ex2300-24t",
        "Fortinet": "FortiGate-100F v7.4.3",
        "Palo Alto":"PAN-OS 11.1.2",
        "HP":       "HP Aruba OS 10.12",
        "Dell":     "Dell OS10 Enterprise 10.5.5",
        "Ubiquiti": "UniFi OS 3.2.9",
        "Huawei":   "Huawei Versatile Routing Platform Software VRP V200R021C10",
    }

    for delay, step_type, msg in steps:
        await asyncio.sleep(delay)
        dev["discovery_steps"].append({"step": step_type, "msg": msg, "ts": datetime.now(timezone.utc).isoformat()})

        if step_type == "snmp_basic":
            dev["os_version"] = VENDOR_SYSDESCRMAP.get(body.vendor, f"{body.vendor} OS")
            dev["uptime"] = random.randint(100000, 9000000)
        elif step_type == "snmp_ifaces":
            dev["interface_count"] = random.randint(8, 48)
        elif step_type == "ai_analysis":
            dev["ai_health_score"] = random.randint(78, 99)
            dev["ai_recommendation"] = f"Device appears healthy. Recommend enabling SNMPv3 for improved security. Verify NTP sync with corporate NTP servers."
        elif step_type == "online":
            dev["status"] = "online"
            dev["cpu"] = random.randint(5, 40)
            dev["mem"] = random.randint(20, 60)

        await broadcast({
            "type":      "device_discovery_update",
            "device_id": device_id,
            "step":      step_type,
            "message":   msg,
            "device":    {k: v for k, v in dev.items() if k != "ssh_username"},
        })

    # Add to topology with a random edge
    parent = random.choice([d for d in DEMO_DEVICES if d["status"] == "online" and d["id"] != device_id])
    DEMO_TOPOLOGY_EDGES.append({
        "source": parent["id"], "target": device_id,
        "source_port": f"GE0/{random.randint(1,48)}",
        "target_port": "GE0/0", "status": "up",
    })


async def _simulate_network_scan(scan_id: str, ip_range: str, community: str):
    """Simulate scanning an IP range and discovering devices."""
    SCAN_RESULTS[scan_id] = {"scan_id": scan_id, "status": "running", "found": 0, "devices": [], "ip_range": ip_range}
    await broadcast({"type": "scan_started", "scan_id": scan_id, "ip_range": ip_range})

    # Parse simple ranges like 192.168.1.1-20 or 10.0.0.0/24
    discovered = []
    prefix = ip_range.rsplit(".", 1)[0] if "." in ip_range else "10.0.99"

    fake_devices = [
        {"ip": f"{prefix}.{i}", "hostname": f"auto-disc-{i:02d}", "vendor": random.choice(["Cisco","MikroTik","HP","Juniper"]), "category": random.choice(["Router","Switch","AP"])}
        for i in random.sample(range(1, 50), k=random.randint(3, 7))
    ]

    for fd in fake_devices:
        await asyncio.sleep(random.uniform(0.8, 1.8))
        # Skip already-existing IPs
        if any(d["ip"] == fd["ip"] for d in DEMO_DEVICES):
            continue
        discovered.append(fd)
        SCAN_RESULTS[scan_id]["found"] = len(discovered)
        SCAN_RESULTS[scan_id]["devices"] = discovered
        await broadcast({"type": "scan_discovered", "scan_id": scan_id, "device": fd, "total_found": len(discovered)})

    SCAN_RESULTS[scan_id]["status"] = "complete"
    await broadcast({"type": "scan_complete", "scan_id": scan_id, "total_found": len(discovered), "devices": discovered})


DEMO_TOPOLOGY_EDGES: list = []


@app.get("/api/v1/noc/topology")
async def get_topology():
    nodes = [
        {"id": d["id"], "hostname": d["hostname"], "ip": d["ip"],
         "vendor": d["vendor"], "category": d["category"],
         "status": d["status"], "cpu": d["cpu"]}
        for d in DEMO_DEVICES
    ]
    edges = [
        {"source": "d1", "target": "d3", "source_port": "GE0/0", "target_port": "GE0/1", "status": "up"},
        {"source": "d1", "target": "d4", "source_port": "GE0/1", "target_port": "GE0/1", "status": "up"},
        {"source": "d2", "target": "d3", "source_port": "GE0/0", "target_port": "GE0/2", "status": "up"},
        {"source": "d2", "target": "d4", "source_port": "GE0/1", "target_port": "GE0/2", "status": "up"},
        {"source": "d3", "target": "d5", "source_port": "GE0/10","target_port": "GE0/1", "status": "up"},
        {"source": "d1", "target": "d6", "source_port": "GE0/2", "target_port": "GE0/0", "status": "up"},
        {"source": "d2", "target": "d7", "source_port": "GE0/2", "target_port": "GE0/0", "status": "up"},
        {"source": "d1", "target": "d9", "source_port": "GE0/3", "target_port": "GE0/0", "status": "up"},
        {"source": "d4", "target": "d8", "source_port": "GE0/20","target_port": "GE0/0", "status": "degraded"},
        {"source": "d5", "target": "d10","source_port": "GE0/5", "target_port": "GE0/0", "status": "down"},
    ]
    return {"nodes": nodes, "edges": edges + DEMO_TOPOLOGY_EDGES}


@app.get("/api/v1/noc/alerts")
async def get_noc_alerts(category: Optional[str] = None, severity: Optional[str] = None):
    alerts = DEMO_ALERTS
    if category:
        alerts = [a for a in alerts if a["category"] == category]
    if severity:
        alerts = [a for a in alerts if a["severity"] == severity]
    return {"items": alerts, "total": len(alerts)}


@app.post("/api/v1/noc/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    for a in DEMO_ALERTS:
        if a["id"] == alert_id:
            a["status"] = "acknowledged"
            return {"message": "Acknowledged", "id": alert_id}
    return {"message": "Not found"}


@app.post("/api/v1/noc/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    for a in DEMO_ALERTS:
        if a["id"] == alert_id:
            a["status"] = "resolved"
            await broadcast({"type": "alert_resolved", "alert_id": alert_id})
            return {"message": "Resolved", "id": alert_id}
    return {"message": "Not found"}


@app.get("/api/v1/soc/incidents")
async def get_incidents():
    return {"items": DEMO_INCIDENTS, "total": len(DEMO_INCIDENTS)}


@app.get("/api/v1/server/servers")
async def get_servers():
    return {"items": DEMO_SERVERS, "total": len(DEMO_SERVERS)}


@app.delete("/api/v1/server/reset")
async def reset_all_servers():
    """Remove ALL servers — fresh start."""
    count = len(DEMO_SERVERS)
    DEMO_SERVERS.clear()
    ACTIVE_PROBLEMS.clear()
    HEALING_LOG.clear()
    await broadcast({"type": "servers_reset", "message": "All servers removed"})
    return {"message": f"{count} server(s) removed. Fresh start ready.", "removed": count}


@app.delete("/api/v1/server/servers/{server_id}")
async def remove_server(server_id: str):
    """Remove a single server."""
    before = len(DEMO_SERVERS)
    to_remove = next((s for s in DEMO_SERVERS if s["id"] == server_id), None)
    if not to_remove:
        return JSONResponse(status_code=404, content={"detail": "Server not found"})
    DEMO_SERVERS.remove(to_remove)
    await broadcast({"type": "server_removed", "server_id": server_id, "hostname": to_remove["hostname"]})
    return {"message": f"{to_remove['hostname']} removed", "server_id": server_id}


@app.post("/api/v1/server/load-demo-data")
async def load_demo_data():
    """Load the built-in demo servers (for demo/testing purposes)."""
    import copy
    added = 0
    for s in _DEMO_SERVERS_SNAPSHOT:
        if not any(x["id"] == s["id"] for x in DEMO_SERVERS):
            DEMO_SERVERS.append(copy.deepcopy(s))
            added += 1
    await broadcast({"type": "demo_data_loaded", "count": len(DEMO_SERVERS)})
    return {"message": f"{added} demo server(s) loaded", "total": len(DEMO_SERVERS)}


# ── PC / Workstation / Server Connect ────────────────────────────────────────

@app.post("/api/v1/server/pc/connect")
async def connect_pc(body: PCConnectRequest):
    """Connect a PC, workstation or server to AEAOP monitoring."""
    if any(s["ip"] == body.ip for s in DEMO_SERVERS):
        return JSONResponse(status_code=409, content={"detail": f"PC/Server with IP {body.ip} already monitored"})

    pc_id = f"pc_{int(time.time())}"
    os_icons = {"windows": "🪟", "linux": "🐧", "macos": "🍎"}

    new_pc = {
        "id":         pc_id,
        "hostname":   body.hostname,
        "ip":         body.ip,
        "os":         f"{body.os_type.capitalize()} (detecting...)",
        "os_type":    body.os_type,
        "cpu":        0,
        "mem":        0,
        "disk":       0,
        "status":     "connecting",
        "role":       body.role,
        "location":   body.location,
        "department": body.department,
        "connect_method": body.connect_method,
        "agent_installed": False,
        "discovery_steps": [],
    }
    DEMO_SERVERS.append(new_pc)

    # Simulate background connection + discovery
    asyncio.create_task(_simulate_pc_discovery(pc_id, body))

    await broadcast({
        "type":    "pc_connecting",
        "pc_id":   pc_id,
        "hostname": body.hostname,
        "os_type":  body.os_type,
        "method":   body.connect_method,
    })
    return {
        "message":    "PC connection initiated",
        "pc_id":      pc_id,
        "install_cmd": _get_agent_install_cmd(body.os_type, body.ip),
        "status":     "connecting",
    }


@app.post("/api/v1/server/pc/agent-checkin")
async def agent_checkin(body: PCAgentCheckIn):
    """Called by the AEAOP agent on the PC after successful installation."""
    for s in DEMO_SERVERS:
        if s["hostname"] == body.hostname or s["ip"] == body.ip:
            s["os"] = f"{body.os_name} {body.os_version}"
            s["cpu_model"] = body.cpu_model
            s["cpu_cores"] = body.cpu_cores
            s["ram_gb"] = body.ram_gb
            s["status"] = "online"
            s["agent_installed"] = True
            s["agent_version"] = body.agent_version
            await broadcast({"type": "pc_agent_checkin", "hostname": body.hostname, "server": s})
            return {"message": "Agent check-in successful", "hostname": body.hostname}
    return JSONResponse(status_code=404, content={"detail": "PC not found"})


@app.get("/api/v1/server/pc/agent-script/{os_type}")
async def get_agent_script(os_type: str):
    """Return the agent install script for the given OS."""
    scripts = {
        "windows": _windows_agent_script(),
        "linux":   _linux_agent_script(),
        "macos":   _macos_agent_script(),
    }
    return {"os_type": os_type, "script": scripts.get(os_type, "# Unsupported OS")}


def _get_agent_install_cmd(os_type: str, server_ip: str) -> str:
    base = "http://localhost:8888"
    if os_type == "windows":
        return f'powershell -Command "iwr {base}/agent/install.ps1 | iex"'
    elif os_type == "linux":
        return f'curl -s {base}/agent/install.sh | sudo bash'
    elif os_type == "macos":
        return f'curl -s {base}/agent/install.sh | bash'
    return ""


def _windows_agent_script() -> str:
    return r"""# AEAOP Windows Monitoring Agent Install Script
# Run as Administrator in PowerShell

$AEAOP_SERVER = "http://localhost:8888"
$AGENT_DIR    = "C:\AEAOP\Agent"

Write-Host "[AEAOP] Installing Windows Monitoring Agent..." -ForegroundColor Cyan

# 1. Create agent directory
New-Item -ItemType Directory -Force -Path $AGENT_DIR | Out-Null

# 2. Enable WinRM for remote management
Write-Host "[AEAOP] Enabling WinRM..." -ForegroundColor Yellow
Enable-PSRemoting -Force -SkipNetworkProfileCheck | Out-Null
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force

# 3. Collect system info
$hostname    = $env:COMPUTERNAME
$ip          = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike "127.*"} | Select-Object -First 1).IPAddress
$os          = (Get-WmiObject Win32_OperatingSystem).Caption
$osVer       = (Get-WmiObject Win32_OperatingSystem).Version
$cpu         = (Get-WmiObject Win32_Processor | Select-Object -First 1).Name
$cpuCores    = (Get-WmiObject Win32_Processor | Measure-Object NumberOfCores -Sum).Sum
$ramGB       = [math]::Round((Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$diskGB      = [math]::Round((Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'").Size / 1GB)

Write-Host "[AEAOP] Detected: $hostname ($ip) | $os | $cpuCores cores | $ramGB GB RAM" -ForegroundColor Green

# 4. Register agent with AEAOP server
$body = @{
    hostname    = $hostname
    ip          = $ip
    os_name     = $os
    os_version  = $osVer
    cpu_model   = $cpu
    cpu_cores   = $cpuCores
    ram_gb      = $ramGB
    disk_gb     = $diskGB
    agent_version = "1.0.0"
} | ConvertTo-Json

try {
    Invoke-RestMethod -Uri "$AEAOP_SERVER/api/v1/server/pc/agent-checkin" `
        -Method POST -Body $body -ContentType "application/json"
    Write-Host "[AEAOP] ✅ Agent registered successfully!" -ForegroundColor Green
} catch {
    Write-Host "[AEAOP] ⚠ Could not reach AEAOP server: $_" -ForegroundColor Red
}

# 5. Create scheduled task for ongoing metrics (every 5 min)
Write-Host "[AEAOP] Creating monitoring scheduled task..." -ForegroundColor Yellow
$task = @"
\$cpu = [math]::Round((Get-WmiObject Win32_Processor | Measure-Object LoadPercentage -Average).Average)
\$mem = [math]::Round((1 - (Get-WmiObject Win32_OperatingSystem).FreePhysicalMemory / (Get-WmiObject Win32_OperatingSystem).TotalVisibleMemorySize) * 100)
\$body = '{"hostname":"'+(hostname)+'","cpu_util":\$cpu,"mem_util":\$mem}' | ConvertTo-Json
Invoke-RestMethod -Uri "$AEAOP_SERVER/api/v1/server/metrics" -Method POST -Body \$body -ContentType "application/json"
"@

Write-Host "[AEAOP] ✅ Installation complete! PC is now monitored by AEAOP." -ForegroundColor Green
"""


def _linux_agent_script() -> str:
    return """#!/bin/bash
# AEAOP Linux Monitoring Agent Install Script
# Run: curl -s http://localhost:8888/api/v1/server/pc/agent-script/linux | sudo bash

AEAOP_SERVER="http://localhost:8888"
AGENT_DIR="/opt/aeaop-agent"

echo -e "\\033[36m[AEAOP] Installing Linux Monitoring Agent...\\033[0m"

# 1. Install dependencies
if command -v apt-get &>/dev/null; then
    apt-get install -y -qq python3 python3-pip curl jq 2>/dev/null
elif command -v yum &>/dev/null; then
    yum install -y -q python3 python3-pip curl jq 2>/dev/null
fi

# 2. Create agent directory
mkdir -p $AGENT_DIR

# 3. Collect system info
HOSTNAME=$(hostname)
IP=$(hostname -I | awk '{print $1}')
OS_NAME=$(. /etc/os-release && echo "$PRETTY_NAME")
OS_VER=$(uname -r)
CPU_MODEL=$(grep "model name" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
CPU_CORES=$(nproc)
RAM_GB=$(awk '/MemTotal/{printf "%d", $2/1024/1024}' /proc/meminfo)
DISK_GB=$(df -BG / | awk 'NR==2{print $2}' | tr -d 'G')

echo -e "\\033[32m[AEAOP] Detected: $HOSTNAME ($IP) | $OS_NAME | $CPU_CORES cores | ${RAM_GB}GB RAM\\033[0m"

# 4. Register with AEAOP server
PAYLOAD=$(cat <<EOF
{
  "hostname": "$HOSTNAME",
  "ip": "$IP",
  "os_name": "$OS_NAME",
  "os_version": "$OS_VER",
  "cpu_model": "$CPU_MODEL",
  "cpu_cores": $CPU_CORES,
  "ram_gb": $RAM_GB,
  "disk_gb": $DISK_GB,
  "agent_version": "1.0.0"
}
EOF
)

RESPONSE=$(curl -s -X POST "$AEAOP_SERVER/api/v1/server/pc/agent-checkin" \\
    -H "Content-Type: application/json" \\
    -d "$PAYLOAD")

echo "[AEAOP] Server response: $RESPONSE"

# 5. Create systemd service for continuous monitoring
cat > /etc/systemd/system/aeaop-agent.service <<SERVICE
[Unit]
Description=AEAOP Monitoring Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $AGENT_DIR/agent.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
SERVICE

# 6. Create metrics sender (runs every 5 min via cron)
cat > /etc/cron.d/aeaop-agent <<CRON
*/5 * * * * root curl -s -X POST $AEAOP_SERVER/api/v1/server/metrics \\
  -H "Content-Type: application/json" \\
  -d "{\\"hostname\\":\\"$HOSTNAME\\",\\"cpu_util\\":$(top -bn1 | grep Cpu | awk '{print $2}'),\\"mem_util\\":$(free | awk '/Mem/{printf \\"%.0f\\",($2-$7)/$2*100}')}"
CRON

echo -e "\\033[32m[AEAOP] ✅ Agent installed! PC '$HOSTNAME' is now monitored.\\033[0m"
"""


def _macos_agent_script() -> str:
    return """#!/bin/bash
# AEAOP macOS Monitoring Agent
AEAOP_SERVER="http://localhost:8888"
HOSTNAME=$(hostname)
IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
OS_NAME=$(sw_vers -productName)
OS_VER=$(sw_vers -productVersion)
CPU_MODEL=$(sysctl -n machdep.cpu.brand_string)
CPU_CORES=$(sysctl -n hw.logicalcpu)
RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
DISK_GB=$(df -BG / | awk 'NR==2{print $2}' | tr -d 'G')

curl -s -X POST "$AEAOP_SERVER/api/v1/server/pc/agent-checkin" \\
  -H "Content-Type: application/json" \\
  -d "{\"hostname\":\"$HOSTNAME\",\"ip\":\"$IP\",\"os_name\":\"$OS_NAME\",\"os_version\":\"$OS_VER\",\"cpu_model\":\"$CPU_MODEL\",\"cpu_cores\":$CPU_CORES,\"ram_gb\":$RAM_GB,\"disk_gb\":$DISK_GB,\"agent_version\":\"1.0.0\"}"
echo "macOS agent registered!"
"""


async def _simulate_pc_discovery(pc_id: str, body: PCConnectRequest):
    """Simulate PC connection and agent install process."""
    pc = next((s for s in DEMO_SERVERS if s["id"] == pc_id), None)
    if not pc:
        return

    os_details = {
        "windows": {"os": "Windows 11 Pro 23H2", "cpu": "Intel Core i7-13700", "cores": 16, "ram": 32, "disk": 512},
        "linux":   {"os": "Ubuntu 24.04 LTS",    "cpu": "AMD Ryzen 5 5600X",  "cores": 12, "ram": 16, "disk": 256},
        "macos":   {"os": "macOS Sonoma 14.4",   "cpu": "Apple M2 Pro",       "cores": 10, "ram": 16, "disk": 512},
    }
    specs = os_details.get(body.os_type, os_details["linux"])

    method_steps = {
        "agent": [
            (1.5, "connect",   f"Reaching {body.ip} on port 8888 (agent callback)..."),
            (2.0, "ping",      f"Ping check: {body.ip} — 4ms avg latency"),
            (2.5, "agent_dl",  f"Agent installer sent to {body.hostname}"),
            (3.0, "agent_run", f"Agent executing on {body.hostname}..."),
            (2.5, "sysinfo",   f"Collecting system info: OS, CPU, RAM, Disk, Services"),
            (2.0, "services",  f"Enumerating running services and processes"),
            (1.5, "ai",        f"AI analyzing hardware profile and security posture"),
            (1.0, "online",    f"Agent online — metrics streaming to AEAOP"),
        ],
        "winrm": [
            (1.5, "connect",   f"WinRM connection to {body.ip}:5985..."),
            (2.0, "auth",      f"Authenticating as {body.username or 'administrator'}"),
            (2.5, "sysinfo",   f"Running: Get-WmiObject Win32_ComputerSystem"),
            (2.0, "services",  f"Running: Get-Service | Where Status -eq Running"),
            (2.5, "patches",   f"Running: Get-HotFix — checking patch status"),
            (1.5, "ai",        f"AI analyzing Windows event logs and security config"),
            (1.0, "online",    f"WinRM session active — PC connected"),
        ],
        "ssh": [
            (1.5, "connect",   f"SSH connecting to {body.ip}:22..."),
            (2.0, "auth",      f"Authenticating as {body.username or 'root'}"),
            (2.5, "sysinfo",   f"Running: uname -a && lscpu && free -h"),
            (2.0, "services",  f"Running: systemctl list-units --type=service --state=running"),
            (2.5, "packages",  f"Running: dpkg -l or rpm -qa — package inventory"),
            (1.5, "ai",        f"AI analyzing system logs and open ports"),
            (1.0, "online",    f"SSH monitoring active — PC connected"),
        ],
    }

    steps = method_steps.get(body.connect_method, method_steps["agent"])

    for delay, step_type, msg in steps:
        await asyncio.sleep(delay)
        pc["discovery_steps"].append({"step": step_type, "msg": msg})

        if step_type == "sysinfo":
            pc["os"] = specs["os"]
            pc["cpu_model"] = specs["cpu"]
            pc["cpu_cores"] = specs["cores"]
            pc["ram_gb"] = specs["ram"]
            pc["disk_gb"] = specs["disk"]
            pc["disk"] = random.randint(20, 75)

        elif step_type in ("agent_run", "auth"):
            pc["agent_installed"] = body.connect_method == "agent"

        elif step_type == "ai":
            open_ports = [22, 80, 443, 3389, 8080] if body.os_type == "windows" else [22, 80, 443]
            pc["ai_health_score"] = random.randint(72, 96)
            pc["open_ports"] = open_ports
            pc["patches_pending"] = random.randint(0, 12)
            pc["security_score"] = random.randint(70, 95)

        elif step_type == "online":
            pc["status"] = "online"
            pc["cpu"] = random.randint(8, 55)
            pc["mem"] = random.randint(25, 70)

        await broadcast({
            "type":    "pc_discovery_update",
            "pc_id":   pc_id,
            "step":    step_type,
            "message": msg,
            "pc":      {k: v for k, v in pc.items() if k not in ("password",)},
        })


@app.get("/api/v1/physec/cameras")
async def get_cameras():
    return {"items": DEMO_CAMERAS, "total": len(DEMO_CAMERAS)}


@app.get("/api/v1/healing/actions")
async def get_healing_actions():
    return {"items": DEMO_HEALING, "pending": sum(1 for h in DEMO_HEALING if h["status"] == "pending")}


@app.post("/api/v1/healing/actions/{action_id}/approve")
async def approve_action(action_id: str):
    for h in DEMO_HEALING:
        if h["id"] == action_id:
            h["status"] = "running"
            await broadcast({"type": "healing_approved", "action_id": action_id, "action": h["action"]})
            # Simulate completion after 3s
            asyncio.create_task(_simulate_healing_complete(action_id))
            return {"message": "Approved and executing", "action_id": action_id}
    return {"message": "Not found"}


@app.post("/api/v1/healing/actions/{action_id}/reject")
async def reject_action(action_id: str):
    for h in DEMO_HEALING:
        if h["id"] == action_id:
            h["status"] = "rejected"
            return {"message": "Rejected", "action_id": action_id}
    return {"message": "Not found"}


async def _simulate_healing_complete(action_id: str):
    await asyncio.sleep(4)
    for h in DEMO_HEALING:
        if h["id"] == action_id:
            h["status"] = "success"
    await broadcast({"type": "healing_complete", "action_id": action_id, "status": "success"})


class RAGQuery(BaseModel):
    question: str


@app.post("/api/v1/rag/query")
async def rag_query(body: RAGQuery):
    q = body.question.lower()
    answer = DEMO_RAG_RESPONSES["default"]
    sources = [{"title": "Operations Runbook v5.2", "type": "runbook", "score": 0.72}]

    if any(w in q for w in ["bgp", "routing", "ospf", "mpls"]):
        answer = DEMO_RAG_RESPONSES["bgp"]
        sources = [{"title": "Cisco BGP Recovery Runbook v2.1", "type": "runbook", "score": 0.97}, {"title": "BGP Troubleshooting Guide", "type": "manual", "score": 0.89}]
    elif any(w in q for w in ["disk", "storage", "space", "partition"]):
        answer = DEMO_RAG_RESPONSES["disk"]
        sources = [{"title": "Storage Management SOP v3.0", "type": "sop", "score": 0.95}]
    elif any(w in q for w in ["cpu", "memory", "performance", "java", "heap"]):
        answer = DEMO_RAG_RESPONSES["cpu"]
        sources = [{"title": "Application Performance Runbook v1.8", "type": "runbook", "score": 0.93}]
    elif any(w in q for w in ["ssh", "brute", "attack", "login", "password"]):
        answer = DEMO_RAG_RESPONSES["ssh"]
        sources = [{"title": "SOC Playbook — Brute Force", "type": "playbook", "score": 0.96}]

    await asyncio.sleep(0.8)  # Simulate inference time
    return {
        "answer": answer,
        "confidence": 0.94,
        "sources": sources,
        "model": "qwen3:14b (demo mode)",
        "tokens_used": random.randint(800, 1800),
    }


# ── Connect All Servers ───────────────────────────────────────────────────────

@app.post("/api/v1/server/connect-all")
async def connect_all_servers():
    """One-click: connect all remaining demo servers with live progress."""
    new_ids = []
    for s in EXTRA_SERVERS:
        if not any(x["id"] == s["id"] for x in DEMO_SERVERS):
            DEMO_SERVERS.append(dict(s))
            new_ids.append(s["id"])

    asyncio.create_task(_simulate_connect_all(new_ids))
    return {"message": f"{len(new_ids)} server(s) queued for connection", "server_ids": new_ids}


async def _simulate_connect_all(ids: list[str]):
    """Stream connection progress for each server."""
    await asyncio.sleep(0.5)
    for sid in ids:
        srv = next((s for s in DEMO_SERVERS if s["id"] == sid), None)
        if not srv:
            continue
        srv["status"] = "connecting"
        await broadcast({"type": "server_connecting", "server": srv})
        await asyncio.sleep(random.uniform(0.8, 1.4))

        # Simulate agent install + system info
        srv["os_version"] = srv["os"]
        srv["agent_installed"] = True
        srv["status"] = "online"
        srv["cpu"] = max(5, srv["cpu"] + random.randint(-5, 5))
        srv["mem"] = max(10, srv["mem"] + random.randint(-3, 3))

        await broadcast({
            "type":    "server_connected",
            "server":  srv,
            "message": f"Agent deployed — {srv['hostname']} now monitored",
        })
        await asyncio.sleep(0.4)

    total = len([s for s in DEMO_SERVERS if s.get("status") == "online"])
    await broadcast({"type": "all_servers_connected", "total_online": total})


# ── Problem Injection + Self-Healing Demo ─────────────────────────────────────

PROBLEM_SCENARIOS = {
    "high_cpu": {
        "title":      "🔥 CPU Critical — {hostname} at {value}%",
        "severity":   "critical",
        "category":   "server",
        "alert_type": "cpu_critical",
        "description": "CPU utilization spiked to {value}% sustained for 5 minutes. Java process consuming full core.",
        "ai_rca":     "OrderProcessingService JVM heap pressure causing GC loops. GC overhead >95% — application effectively stalled.",
        "fix_action": "restart_service",
        "fix_steps":  ["systemctl status OrderProcessingService", "jstack -l $(pgrep java) > /tmp/thread_dump.txt", "systemctl restart OrderProcessingService", "sleep 5 && systemctl is-active OrderProcessingService"],
        "fix_label":  "Restart OrderProcessingService",
        "risk":       "low",
        "auto":       True,
        "verify_metric": "cpu",
        "resolved_value": lambda: random.randint(12, 32),
    },
    "disk_full": {
        "title":      "💾 Disk Full — {hostname} /data at {value}%",
        "severity":   "critical",
        "category":   "server",
        "alert_type": "disk_critical",
        "description": "/data partition at {value}% — applications will crash when 100% reached.",
        "ai_rca":     "Log rotation not running. /var/log/app/*.log files older than 30 days consuming 47 GB. Safe to delete.",
        "fix_action": "clear_disk_space",
        "fix_steps":  ["df -h /data", "find /var/log -name '*.log' -mtime +7 | head -20", "find /var/log -name '*.log' -mtime +7 -delete", "find /tmp -mtime +3 -delete 2>/dev/null", "journalctl --vacuum-time=7d", "df -h /data"],
        "fix_label":  "Clear old logs & temp files",
        "risk":       "low",
        "auto":       True,
        "verify_metric": "disk",
        "resolved_value": lambda: random.randint(42, 58),
    },
    "service_down": {
        "title":      "🔴 Service Down — nginx on {hostname}",
        "severity":   "high",
        "category":   "server",
        "alert_type": "service_down",
        "description": "nginx process not responding. Health check failed for 3 consecutive polls.",
        "ai_rca":     "nginx OOM-killed by kernel (out of memory). Worker processes consuming >8GB RAM due to upstream connection leak.",
        "fix_action": "restart_service",
        "fix_steps":  ["systemctl status nginx", "journalctl -u nginx --since '10 min ago'", "systemctl start nginx", "curl -s -o /dev/null -w '%{http_code}' http://localhost/health"],
        "fix_label":  "Start nginx service",
        "risk":       "low",
        "auto":       True,
        "verify_metric": "service",
        "resolved_value": lambda: "active",
    },
    "memory_leak": {
        "title":      "⚠️ Memory Leak — {hostname} at {value}%",
        "severity":   "high",
        "category":   "server",
        "alert_type": "memory_critical",
        "description": "Memory at {value}% — growing 2% per minute. OOM kill imminent.",
        "ai_rca":     "Redis maxmemory policy not set. Dataset grown to 28GB — exceeds server RAM. Connection pool leak in app code.",
        "fix_action": "restart_service",
        "fix_steps":  ["free -h", "redis-cli info memory | grep used_memory_human", "redis-cli config set maxmemory 4gb", "redis-cli config set maxmemory-policy allkeys-lru", "redis-cli memory doctor"],
        "fix_label":  "Fix Redis maxmemory + policy",
        "risk":       "medium",
        "auto":       False,
        "verify_metric": "mem",
        "resolved_value": lambda: random.randint(45, 62),
    },
    "log_disk_full": {
        "title":      "💽 Log Disk 91% — {hostname}",
        "severity":   "high",
        "category":   "server",
        "alert_type": "disk_warning",
        "description": "Log partition 91% full. Log rotation failing — disk will be full in ~4 hours.",
        "ai_rca":     "Logrotate cron job not running since last kernel update broke cron. 14 GB of unrotated app logs accumulated.",
        "fix_action": "clear_disk_space",
        "fix_steps":  ["du -sh /var/log/*", "logrotate -f /etc/logrotate.conf", "find /var/log -name '*.gz' -mtime +7 -delete", "systemctl restart cron"],
        "fix_label":  "Force logrotate + fix cron",
        "risk":       "low",
        "auto":       True,
        "verify_metric": "disk",
        "resolved_value": lambda: random.randint(55, 68),
    },
}


@app.post("/api/v1/demo/inject-problem")
async def inject_problem(server_id: str, problem_type: str):
    """Inject a simulated problem into a server and trigger AI healing workflow."""
    srv = next((s for s in DEMO_SERVERS if s["id"] == server_id), None)
    if not srv:
        return JSONResponse(status_code=404, content={"detail": "Server not found"})

    scenario = PROBLEM_SCENARIOS.get(problem_type)
    if not scenario:
        return JSONResponse(status_code=400, content={"detail": f"Unknown problem: {problem_type}"})

    # Set degraded metric
    value = {"high_cpu": 97, "disk_full": 97, "service_down": 0, "memory_leak": 94, "log_disk_full": 91}.get(problem_type, 90)
    if problem_type == "high_cpu":
        srv["cpu"] = value; srv["status"] = "degraded"
    elif problem_type in ("disk_full", "log_disk_full"):
        srv["disk"] = value; srv["status"] = "warning" if value < 95 else "degraded"
    elif problem_type == "memory_leak":
        srv["mem"] = value; srv["status"] = "degraded"
    elif problem_type == "service_down":
        srv["status"] = "degraded"

    problem_id = f"prob_{server_id}_{int(time.time())}"
    title = scenario["title"].format(hostname=srv["hostname"], value=value)
    desc  = scenario["description"].format(value=value)

    alert = {
        "id":          problem_id,
        "severity":    scenario["severity"],
        "category":    scenario["category"],
        "alert_type":  scenario["alert_type"],
        "title":       title,
        "description": desc,
        "device":      srv["hostname"],
        "status":      "new",
        "ai_rca":      scenario["ai_rca"],
        "time":        "just now",
        "server_id":   server_id,
        "problem_type": problem_type,
    }
    DEMO_ALERTS.insert(0, alert)
    ACTIVE_PROBLEMS[problem_id] = {"alert": alert, "server": srv, "scenario": scenario, "problem_id": problem_id}

    await broadcast({"type": "problem_injected", "alert": alert, "server": srv})

    # Start the AI healing pipeline
    asyncio.create_task(_run_healing_pipeline(problem_id, srv, scenario, alert, value))

    return {"message": "Problem injected — AI healing pipeline started", "problem_id": problem_id, "alert": alert}


@app.get("/api/v1/demo/healing-log")
async def get_healing_log():
    return {"log": HEALING_LOG[-50:], "total": len(HEALING_LOG)}


@app.post("/api/v1/demo/inject-all-problems")
async def inject_all_problems():
    """Inject one problem per available server (round-robin across problem types)."""
    injected = []
    problem_types = list(PROBLEM_SCENARIOS.keys())
    available = [s for s in DEMO_SERVERS
                 if s.get("status") in ("online","warning","degraded")
                 and not any(p["server"]["id"]==s["id"] for p in ACTIVE_PROBLEMS.values())]

    for i, srv in enumerate(available[:6]):   # max 6 concurrent
        ptype = problem_types[i % len(problem_types)]
        asyncio.create_task(_run_single_inject(srv["id"], ptype))
        injected.append({"hostname": srv["hostname"], "problem": ptype})
    return {"injected": injected, "count": len(injected)}


async def _run_single_inject(server_id: str, problem_type: str):
    await asyncio.sleep(random.uniform(0.5, 2.5))
    # Reuse the inject logic inline
    srv = next((s for s in DEMO_SERVERS if s["id"] == server_id), None)
    if not srv:
        return
    scenario = PROBLEM_SCENARIOS.get(problem_type)
    if not scenario:
        return
    value = {"high_cpu": 97, "disk_full": 97, "service_down": 0, "memory_leak": 94, "log_disk_full": 91}.get(problem_type, 90)
    if problem_type == "high_cpu":   srv["cpu"] = value; srv["status"] = "degraded"
    elif problem_type in ("disk_full","log_disk_full"): srv["disk"] = value; srv["status"] = "warning"
    elif problem_type == "memory_leak": srv["mem"] = value; srv["status"] = "degraded"
    elif problem_type == "service_down": srv["status"] = "degraded"

    problem_id = f"prob_{server_id}_{int(time.time())}"
    title = scenario["title"].format(hostname=srv["hostname"], value=value)
    alert = {
        "id": problem_id, "severity": scenario["severity"],
        "category": scenario["category"], "alert_type": scenario["alert_type"],
        "title": title, "description": scenario["description"].format(value=value),
        "device": srv["hostname"], "status": "new",
        "ai_rca": scenario["ai_rca"], "time": "just now",
        "server_id": server_id, "problem_type": problem_type,
    }
    DEMO_ALERTS.insert(0, alert)
    ACTIVE_PROBLEMS[problem_id] = {"alert": alert, "server": srv, "scenario": scenario, "problem_id": problem_id}
    await broadcast({"type": "problem_injected", "alert": alert, "server": srv})
    asyncio.create_task(_run_healing_pipeline(problem_id, srv, scenario, alert, value))


async def _run_healing_pipeline(problem_id: str, srv: dict, scenario: dict, alert: dict, value):
    """Full AI-powered healing pipeline with live broadcast."""

    def log(phase: str, msg: str, level: str = "info"):
        entry = {"time": datetime.now(timezone.utc).isoformat(), "phase": phase, "msg": msg, "level": level, "server": srv["hostname"]}
        HEALING_LOG.append(entry)
        return entry

    async def bcast(phase: str, msg: str, level: str = "info", extra: dict = None):
        entry = log(phase, msg, level)
        payload = {"type": "healing_pipeline", "problem_id": problem_id, "phase": phase,
                   "msg": msg, "level": level, "server_id": srv["id"],
                   "hostname": srv["hostname"]}
        if extra:
            payload.update(extra)
        await broadcast(payload)

    # ── PHASE 1: ALERT DETECTED ───────────────────────────────────────────
    await asyncio.sleep(0.5)
    await bcast("alert_detected", f"🚨 Alert detected: {alert['title']}", "critical")
    await asyncio.sleep(1.0)
    await bcast("alert_detected", f"Severity: {alert['severity'].upper()} | Category: {alert['category'].upper()}", "info")

    # ── PHASE 2: AI ANALYSIS ──────────────────────────────────────────────
    await asyncio.sleep(1.5)
    await bcast("ai_analysis", "🤖 AI Engine: Analyzing alert context...", "ai")
    await asyncio.sleep(1.2)
    await bcast("ai_analysis", f"📊 Collecting metrics from {srv['hostname']}...", "ai")
    await asyncio.sleep(1.0)
    await bcast("ai_analysis", f"🔍 Querying RAG: searching 312 runbooks + 1,847 past incidents...", "ai")
    await asyncio.sleep(1.5)
    await bcast("ai_analysis", f"💡 ROOT CAUSE IDENTIFIED (confidence: 94%)", "ai",
                {"rca": scenario["ai_rca"]})
    await asyncio.sleep(0.8)
    await bcast("ai_analysis", f"Root cause: {scenario['ai_rca']}", "rca")

    # ── PHASE 3: SOLUTION GENERATION ─────────────────────────────────────
    await asyncio.sleep(1.0)
    await bcast("solution", f"⚙️  Generating remediation plan...", "ai")
    await asyncio.sleep(1.2)
    await bcast("solution", f"✅ Solution selected: {scenario['fix_label']}", "ok",
                {"fix_steps": scenario["fix_steps"], "risk": scenario["risk"],
                 "auto": scenario["auto"], "action": scenario["fix_action"]})

    # ── PHASE 4: RISK CHECK & APPROVAL ───────────────────────────────────
    await asyncio.sleep(0.8)
    risk = scenario["risk"]
    auto = scenario["auto"]
    await bcast("approval", f"🔒 Risk Level: {risk.upper()} | Auto-execute: {auto}", "info")
    await asyncio.sleep(0.8)

    if auto:
        await bcast("approval", f"✅ AUTO-APPROVED — risk={risk}, action is safe to execute autonomously", "ok")
        alert["status"] = "in_progress"
    else:
        await bcast("approval", f"⏳ PENDING APPROVAL — medium risk, sending to NOC Manager...", "warning")
        await asyncio.sleep(2.5)
        await bcast("approval", f"✅ APPROVED by NOC Manager (auto-simulated in demo)", "ok")
        alert["status"] = "in_progress"

    await broadcast({"type": "alert_status_update", "alert_id": problem_id, "status": "in_progress"})

    # ── PHASE 5: EXECUTION ────────────────────────────────────────────────
    await asyncio.sleep(0.8)
    await bcast("execution", f"🔧 EXECUTING on {srv['hostname']} via SSH...", "run")
    await asyncio.sleep(0.6)

    for i, cmd in enumerate(scenario["fix_steps"], 1):
        await asyncio.sleep(random.uniform(0.8, 1.6))
        await bcast("execution", f"  [{i}/{len(scenario['fix_steps'])}] $ {cmd}", "cmd")
        # Fake output for key commands
        if "systemctl restart" in cmd or "systemctl start" in cmd:
            await asyncio.sleep(0.6)
            svc = cmd.split()[-1]
            await bcast("execution", f"       → {svc}: active (running) since {datetime.now(timezone.utc).strftime('%H:%M:%S')}", "ok")
        elif "df -h" in cmd:
            await asyncio.sleep(0.3)
            new_disk = scenario["resolved_value"]() if callable(scenario["resolved_value"]) else 55
            await bcast("execution", f"       → Filesystem /data  256G  {new_disk}G  {256-new_disk}G  {new_disk}% /data", "ok")
        elif "find" in cmd and "delete" in cmd:
            freed = random.randint(8, 22)
            await bcast("execution", f"       → {freed} files deleted — freed {freed*1.2:.1f} GB", "ok")
        elif "curl" in cmd:
            await bcast("execution", f"       → HTTP 200 ✓ (health check passed)", "ok")

    # ── PHASE 6: VERIFICATION ─────────────────────────────────────────────
    await asyncio.sleep(1.0)
    await bcast("verification", f"🔎 Verifying fix on {srv['hostname']}...", "run")
    await asyncio.sleep(1.5)

    # Update actual metrics
    resolved = scenario["resolved_value"]() if callable(scenario["resolved_value"]) else 30
    metric = scenario.get("verify_metric", "cpu")
    if metric == "cpu":
        srv["cpu"] = resolved
        await bcast("verification", f"  ✅ CPU: {value}% → {resolved}% (back to normal)", "ok")
    elif metric == "disk":
        srv["disk"] = resolved
        await bcast("verification", f"  ✅ Disk: {value}% → {resolved}% (space freed)", "ok")
    elif metric == "mem":
        srv["mem"] = resolved
        await bcast("verification", f"  ✅ Memory: {value}% → {resolved}% (leak fixed)", "ok")
    elif metric == "service":
        await bcast("verification", f"  ✅ Service: down → active (running)", "ok")

    srv["status"] = "online"
    await asyncio.sleep(0.8)
    await bcast("verification", f"  ✅ All health checks passed", "ok")

    # ── PHASE 7: RESOLVED ─────────────────────────────────────────────────
    await asyncio.sleep(0.6)
    alert["status"] = "resolved"
    alert["is_ai_resolved"] = True

    if problem_id in ACTIVE_PROBLEMS:
        del ACTIVE_PROBLEMS[problem_id]

    await bcast("resolved",
        f"🎉 PROBLEM RESOLVED — Total time: {random.randint(45, 90)}s | AI autonomous: yes",
        "success",
        {"server": srv, "alert_id": problem_id}
    )
    await broadcast({"type": "alert_resolved", "alert_id": problem_id, "server": srv,
                     "metric": metric, "old_value": value, "new_value": resolved})


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connected_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _connected_websockets:
            _connected_websockets.remove(websocket)


# ── Static files ──────────────────────────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = os.path.join(static_dir, "index.html")
    with open(index_path, encoding="utf-8") as f:
        return f.read()


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    asyncio.create_task(metrics_generator())
    print("\n" + "═"*60)
    print("  AEAOP — AI Operations Platform  |  Demo Mode")
    print("═"*60)
    print("  Dashboard:  http://localhost:8888")
    print("  API Docs:   http://localhost:8888/api/docs")
    print("═"*60 + "\n")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8888, reload=False)
