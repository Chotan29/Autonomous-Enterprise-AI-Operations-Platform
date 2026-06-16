"""
Device configuration intelligence — collect, parse, embed, generate.

Pipeline:
  1. collect_config(host, creds)  — pull running-config from the device
       SSH for Cisco/Juniper/MikroTik/HP/Linux ; REST for Fortinet/Palo Alto ;
       PowerShell/WinRM for Windows. If no creds, falls back to a realistic
       sample-config so the rest of the pipeline can be demonstrated.
  2. parse_config(text, vendor)   — split into semantic blocks
       interfaces, vlans, acls, routing, security, snmp, users, ntp, syslog.
  3. ingest_into_vector_db(host, blocks)
       Embed each block, store in the vector store with rich metadata
       (vendor, host, ip, role, section, change_hash, ts).
  4. search(query, filters)       — RAG retrieval across all indexed configs.
  5. generate_config(intent, topology, vendor)
       Retrieves similar blocks from past configs, feeds as few-shot
       context to the LLM, returns proposed config + diff against current.
  6. validate(proposed, current)   — basic syntax + dangerous-keyword check
                                     (in prod: NAPALM compare_config).
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from demo import ai_client
    from demo.vector_store import VectorStore
except ImportError:
    from . import ai_client
    from .vector_store import VectorStore


# ══════════════════════════════════════════════════════════════════════════
# 1. SAMPLE CONFIGS (used when no creds; real collector below for SSH/REST)
# ══════════════════════════════════════════════════════════════════════════

_SAMPLE_CONFIGS: dict[str, str] = {
    "Cisco": """!
! Cisco IOS-XE 17.09.04a
hostname core-rtr-01
!
username admin privilege 15 secret 5 $1$8AQK$REDACTED
!
ip ssh version 2
ip ssh time-out 60
ip ssh authentication-retries 3
no ip http server
ip http secure-server
!
snmp-server group AEAOP-RW v3 priv
snmp-server user aeaop-mon AEAOP-RW v3 auth sha REDACTED priv aes 128 REDACTED
snmp-server host 10.0.0.50 version 3 priv aeaop-mon
!
ntp server 10.0.0.5 prefer
ntp server 10.0.0.6
!
vlan 10
 name MGMT
vlan 20
 name USERS
vlan 30
 name SERVERS
vlan 99
 name BLACKHOLE
!
interface GigabitEthernet0/0
 description Uplink to ISP
 ip address 203.0.113.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description Trunk to dist-sw-01
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 no shutdown
!
router ospf 1
 router-id 10.0.0.1
 network 10.0.0.0 0.0.0.255 area 0
 network 10.0.1.0 0.0.0.255 area 0
!
ip access-list extended MGMT-ACL
 permit tcp 10.0.0.0 0.0.0.255 any eq 22
 deny ip any any log
!
line vty 0 4
 access-class MGMT-ACL in
 transport input ssh
!
end""",

    "MikroTik": """# RouterOS 7.14.3
/system identity set name=core-rtr-mt-01
/system clock set time-zone-name=Asia/Dhaka

/user add name=aeaop-admin group=full password=REDACTED comment=AEAOP
/ip service disable telnet,ftp,www,api
/ip service set ssh port=22

/snmp set enabled=yes
/snmp community set [find name=public] disabled=yes
/snmp community add name=aeaop-mon security=authPriv \\
    authentication-protocol=SHA1 encryption-protocol=AES \\
    authentication-password=REDACTED encryption-password=REDACTED

/ip pool add name=USERS ranges=10.0.20.10-10.0.20.250
/ip pool add name=SERVERS ranges=10.0.30.10-10.0.30.250

/interface vlan add interface=ether1 name=vlan-mgmt vlan-id=10
/interface vlan add interface=ether1 name=vlan-users vlan-id=20
/interface vlan add interface=ether1 name=vlan-servers vlan-id=30

/ip address add address=10.0.0.1/24 interface=vlan-mgmt
/ip address add address=10.0.20.1/24 interface=vlan-users
/ip address add address=10.0.30.1/24 interface=vlan-servers

/ip firewall filter add chain=input action=accept connection-state=established,related
/ip firewall filter add chain=input action=accept src-address=10.0.0.0/24 protocol=tcp dst-port=22
/ip firewall filter add chain=input action=drop log=yes log-prefix=FW-DROP-IN

/system ntp client set enabled=yes servers=10.0.0.5,10.0.0.6""",

    "Juniper": """system {
    host-name dist-sw-jnpr-01;
    time-zone Asia/Dhaka;
    services {
        ssh { protocol-version v2; root-login deny; }
    }
    syslog { host 10.0.0.50 any any; }
    ntp { server 10.0.0.5 prefer; server 10.0.0.6; }
}
snmp {
    location "DC1-B01";
    v3 {
        usm local-engine user aeaop-mon {
            authentication-sha { authentication-password "REDACTED"; }
            privacy-aes128     { privacy-password      "REDACTED"; }
        }
    }
}
vlans {
    MGMT     { vlan-id 10; l3-interface vlan.10; }
    USERS    { vlan-id 20; l3-interface vlan.20; }
    SERVERS  { vlan-id 30; l3-interface vlan.30; }
}
interfaces {
    ge-0/0/0 { description "Uplink-core";  unit 0 { family ethernet-switching { interface-mode trunk; vlan { members [ MGMT USERS SERVERS ]; } } } }
}
protocols {
    ospf { area 0.0.0.0 { interface vlan.10; interface vlan.20; interface vlan.30; } }
}""",

    "Fortinet": """config system global
    set hostname "fw-01"
    set timezone "Asia/Dhaka"
    set admintimeout 5
    set admin-https-redirect enable
end
config system interface
    edit "port1"
        set vdom "root"
        set ip 10.0.0.254 255.255.255.0
        set allowaccess ping https ssh
        set role lan
    next
end
config system admin
    edit "admin"
        set accprofile "super_admin"
        set password ENC REDACTED
        set two-factor email
        set email-to "soc@example.com"
    next
end
config firewall policy
    edit 1
        set name "Allow-MGMT-to-DC"
        set srcintf "port1"
        set dstintf "port2"
        set srcaddr "MGMT-Subnet"
        set dstaddr "DC-Subnet"
        set action accept
        set service "SSH" "HTTPS"
        set logtraffic all
    next
end
config system snmp sysinfo
    set status enable
    set engine-id-type mac
end""",

    "Linux": """# /etc/ssh/sshd_config
Port 22
Protocol 2
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server

# /etc/sysctl.d/99-aeaop.conf
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.tcp_syncookies = 1
net.ipv6.conf.all.disable_ipv6 = 0

# /etc/network/interfaces
auto eth0
iface eth0 inet static
    address 10.0.1.50/24
    gateway 10.0.1.1
    dns-nameservers 10.0.0.5 10.0.0.6

# Firewall (ufw)
ufw default deny incoming
ufw default allow outgoing
ufw allow from 10.0.0.0/24 to any port 22 proto tcp
ufw enable""",
}


# ══════════════════════════════════════════════════════════════════════════
# 2. COLLECTOR — reads running-config via SSH / REST / mock
# ══════════════════════════════════════════════════════════════════════════


# Per-vendor commands to retrieve running-config when SSH is available.
_VENDOR_SHOW_CMDS = {
    "Cisco":    ["terminal length 0", "show running-config"],
    "Juniper":  ["set cli screen-length 0", "show configuration | display set"],
    "MikroTik": ["/export show-sensitive"],
    "HP":       ["screen-length disable", "display current-configuration"],
    "Ubiquiti": ["show configuration commands"],
    "Linux":    ["sudo cat /etc/ssh/sshd_config /etc/network/interfaces /etc/sysctl.conf 2>/dev/null"],
}


async def collect_config(host: dict, credentials: Optional[dict] = None) -> dict:
    """Pull the running-config from a device.

    With creds present, attempts a real SSH session via asyncssh and runs
    the vendor-appropriate show commands. Without creds (or on failure),
    falls back to a vendor-matched sample config so the rest of the
    intelligence pipeline can still be exercised.
    """
    vendor = host.get("vendor") or host.get("os_guess") or "Linux"
    # Normalise common matches
    if "windows" in vendor.lower():        vendor = "Windows"
    if "router" in vendor.lower() or "ros" in vendor.lower(): vendor = "MikroTik"

    if credentials and credentials.get("username") and credentials.get("password"):
        cfg = await _ssh_collect(host, credentials, vendor)
        if cfg:
            return {
                "host_id":   host.get("id"),
                "ip":        host.get("ip"),
                "vendor":    vendor,
                "method":    "ssh",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "config":    cfg,
                "size_bytes": len(cfg),
                "redacted":  False,
            }

    # Fallback: vendor-matched sample (clearly marked)
    sample = _SAMPLE_CONFIGS.get(vendor) or _SAMPLE_CONFIGS["Linux"]
    return {
        "host_id":   host.get("id"),
        "ip":        host.get("ip"),
        "vendor":    vendor,
        "method":    "sample-fallback",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "config":    sample,
        "size_bytes": len(sample),
        "redacted":  False,
        "note":      "No SSH credentials provided — using vendor-matched sample. "
                     "Add credentials via POST /api/v1/config/credentials to collect real configs.",
    }


async def _ssh_collect(host: dict, creds: dict, vendor: str) -> Optional[str]:
    """Real SSH-based collection. Returns None if asyncssh isn't available
    or the session fails. Demo-friendly: never raises."""
    try:
        import asyncssh   # only imported if available
    except ImportError:
        return None
    cmds = _VENDOR_SHOW_CMDS.get(vendor, _VENDOR_SHOW_CMDS["Linux"])
    try:
        async with asyncssh.connect(
            host["ip"], username=creds["username"], password=creds["password"],
            known_hosts=None, connect_timeout=8,
        ) as conn:
            outputs = []
            for cmd in cmds:
                r = await conn.run(cmd, timeout=20)
                outputs.append(r.stdout or "")
            return "\n".join(outputs).strip()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════
# 3. PARSER — split config into semantic blocks
# ══════════════════════════════════════════════════════════════════════════


_SECTION_HINTS = {
    "interfaces":  ["interface", "ge-", "ether", "eth0", "auto eth", "port1"],
    "vlans":       ["vlan ", "vlans {", "/interface vlan"],
    "routing":     ["router ospf", "router bgp", "ip route", "protocols", "/ip route"],
    "acls":        ["ip access-list", "firewall policy", "firewall filter", "/ip firewall"],
    "snmp":        ["snmp-server", "snmp {", "/snmp"],
    "users_aaa":   ["username ", "user {", "/user add", "config system admin"],
    "ntp":         ["ntp server", "ntp {", "/system ntp"],
    "syslog":      ["logging host", "syslog {", "log-server"],
    "ssh_mgmt":    ["ip ssh", "line vty", "services {", "sshd_config", "PermitRootLogin", "/ip service"],
    "system":      ["hostname", "host-name", "/system identity", "global"],
    "firewall":    ["/ip firewall", "config firewall", "ufw "],
}


def parse_config(text: str, vendor: str) -> list[dict]:
    """Split a config blob into labelled blocks.

    Strategy: line-based section detection. We walk the text, accumulating
    lines into the current block; when we encounter a marker that signals
    a new section, we close the previous block and open a new one.
    This is intentionally lightweight — production would use ttp or
    textfsm with vendor-specific templates.
    """
    blocks: list[dict] = []
    current = {"section": "header", "lines": []}

    def classify(line: str) -> Optional[str]:
        l = line.lower().strip()
        if not l or l.startswith(("#", "!", "//")):
            return None
        for section, hints in _SECTION_HINTS.items():
            for h in hints:
                if h in l:
                    return section
        return None

    for raw in text.splitlines():
        sect = classify(raw)
        if sect and sect != current["section"]:
            if current["lines"]:
                blocks.append(current)
            current = {"section": sect, "lines": []}
        current["lines"].append(raw)

    if current["lines"]:
        blocks.append(current)

    # Materialise each block as text + metadata
    out = []
    for b in blocks:
        body = "\n".join(b["lines"]).strip()
        if len(body) < 5:
            continue
        out.append({
            "section":  b["section"],
            "vendor":   vendor,
            "text":     body,
            "size":     len(body),
            "line_count": len(b["lines"]),
            "hash":     hashlib.sha1(body.encode()).hexdigest()[:12],
        })
    return out


# ══════════════════════════════════════════════════════════════════════════
# 4. INGEST — collect → parse → embed → store
# ══════════════════════════════════════════════════════════════════════════


# Single shared store; in production this would be a Qdrant client.
CONFIG_STORE = VectorStore(persist_path="tmp/config_vector_db.json")


async def ingest_host_config(host: dict, credentials: Optional[dict] = None) -> dict:
    """Run the full collect → parse → embed → store pipeline for one host."""
    snap = await collect_config(host, credentials)
    blocks = parse_config(snap["config"], snap["vendor"])

    indexed_ids: list[str] = []
    for b in blocks:
        meta = {
            "source":        "device_config",
            "host_id":       host.get("id"),
            "hostname":      host.get("hostname"),
            "ip":            host.get("ip"),
            "vendor":        b["vendor"],
            "section":       b["section"],
            "block_hash":    b["hash"],
            "collected_via": snap["method"],
            "collected_at":  snap["collected_at"],
        }
        eid = await CONFIG_STORE.add(
            text=b["text"],
            metadata=meta,
            entry_id=f"{host.get('id')}_{b['section']}_{b['hash']}",
        )
        indexed_ids.append(eid)

    CONFIG_STORE.save()
    return {
        "host_id":       host.get("id"),
        "vendor":        snap["vendor"],
        "method":        snap["method"],
        "config_bytes":  snap["size_bytes"],
        "blocks_parsed": len(blocks),
        "blocks_indexed": len(indexed_ids),
        "block_ids":     indexed_ids,
        "note":          snap.get("note"),
    }


# ══════════════════════════════════════════════════════════════════════════
# 5. SEARCH — semantic retrieval across the corpus
# ══════════════════════════════════════════════════════════════════════════


async def search_configs(query: str, k: int = 5,
                          vendor: Optional[str] = None,
                          section: Optional[str] = None) -> dict:
    def _filter(e):
        if vendor and e.metadata.get("vendor") != vendor:
            return False
        if section and e.metadata.get("section") != section:
            return False
        return True

    results = await CONFIG_STORE.search(query, k=k, filter_fn=_filter)
    return {
        "query":   query,
        "filters": {"vendor": vendor, "section": section},
        "backend": CONFIG_STORE.last_backend,
        "results": [
            {
                "id":       e.id,
                "score":    round(score, 4),
                "vendor":   e.metadata.get("vendor"),
                "host":     e.metadata.get("hostname"),
                "section":  e.metadata.get("section"),
                "ip":       e.metadata.get("ip"),
                "text":     e.text,
                "metadata": e.metadata,
            } for e, score in results
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# 6. GENERATE — RAG-augmented config generation from intent + topology
# ══════════════════════════════════════════════════════════════════════════


GENERATE_SYSTEM = """You are AEAOP's configuration engineer. Given an operator intent,
a physical topology hint, and several relevant configuration examples
retrieved from the organisation's own indexed configs, produce a
vendor-appropriate configuration that fulfils the intent.

Rules:
  * Output ONLY the configuration commands — no markdown, no commentary.
  * Use the same syntax style and naming convention as the retrieved examples.
  * Be conservative: prefer additive changes, avoid touching unrelated config.
  * If the intent is ambiguous or risky, output a single comment line starting
    with "! WARNING:" explaining what clarification is needed.
"""


async def generate_config(intent: str,
                          vendor: str,
                          topology_hint: str = "",
                          context_k: int = 4) -> dict:
    """Generate a new configuration block from operator intent.

    Pipeline:
      1. Embed intent → retrieve top-k similar config blocks (filtered by vendor).
      2. Build a few-shot prompt with the retrieved snippets as context.
      3. Ask the LLM chain (Ollama → Anthropic → OpenAI → keyword) to draft.
      4. Return draft + the snippets used as grounding citations.
    """
    retrieved = await CONFIG_STORE.search(intent, k=context_k,
        filter_fn=lambda e: (e.metadata.get("vendor") == vendor)
                            if vendor else True)

    citations: list[dict] = []
    examples_text: list[str] = []
    for e, score in retrieved:
        citations.append({
            "id":      e.id,
            "score":   round(score, 4),
            "host":    e.metadata.get("hostname"),
            "section": e.metadata.get("section"),
            "vendor":  e.metadata.get("vendor"),
        })
        examples_text.append(
            f"## Example from {e.metadata.get('hostname') or '?'} "
            f"({e.metadata.get('vendor')} / {e.metadata.get('section')})\n"
            f"{e.text}"
        )

    context = "\n\n".join(examples_text) if examples_text else "(no prior examples indexed)"
    if topology_hint:
        context = f"# Topology / physical layout\n{topology_hint}\n\n" + context

    prompt = (
        f"Vendor: {vendor}\n"
        f"Intent: {intent}\n\n"
        f"Produce the configuration commands now."
    )

    llm = await ai_client.chat(
        question=prompt,
        system=GENERATE_SYSTEM,
        context=context,
    )

    return {
        "intent":     intent,
        "vendor":     vendor,
        "topology_hint": topology_hint or None,
        "draft":      llm["answer"],
        "model":      llm["model"],
        "provider":   llm["provider"],
        "citations":  citations,
        "context_used_chars": len(context),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════
# 7. VALIDATE — sanity checks before push
# ══════════════════════════════════════════════════════════════════════════


_DANGEROUS_KEYWORDS = [
    ("write erase",         "would wipe the startup-config — refuse"),
    ("reload in 0",         "would immediately reboot — refuse"),
    ("shutdown",            "interface shutdown — high blast radius — require approval"),
    ("no router ospf",      "tears down routing — require approval"),
    ("no router bgp",       "tears down BGP — require approval"),
    ("erase startup",       "wipes startup-config — refuse"),
    ("delete /",            "deletes filesystem — refuse"),
    ("factory-reset",       "wipes device — refuse"),
    ("/system reset",       "factory reset — refuse"),
]


def validate(draft: str) -> dict:
    """Cheap static check for dangerous keywords + obvious shape issues.

    In production: hand off to NAPALM `compare_config` against a sandbox
    image of the device, or push to a candidate config + `commit check`
    on Junos / IOS-XE.
    """
    issues: list[dict] = []
    txt = (draft or "").lower()
    for kw, why in _DANGEROUS_KEYWORDS:
        if kw in txt:
            issues.append({"severity": "high", "keyword": kw, "reason": why})

    if not draft or len(draft.strip()) < 10:
        issues.append({"severity": "high", "keyword": "<empty>", "reason": "draft is empty"})

    line_count = len([l for l in draft.splitlines() if l.strip()])
    return {
        "lines":   line_count,
        "issues":  issues,
        "safe_to_preview": all(i["severity"] != "high" or "refuse" not in i["reason"] for i in issues),
        "verdict": "ok" if not issues else ("warn" if all(i["severity"] != "high" or "refuse" not in i["reason"] for i in issues) else "block"),
    }
