"""
Vendor-aware config snippet generator.

Given a finding (e.g. "Telnet exposed", "SNMP v1/v2c in use") + the device's
vendor, produce a CLI command sequence that fixes it. The output is a list
of commands ready to copy/paste OR feed to an SSH/Netmiko executor.

Supported vendors: Cisco IOS-XE, MikroTik RouterOS, Juniper Junos, Fortinet
FortiOS, HP / Aruba ProCurve, Ubiquiti EdgeOS / UniFi, Linux/Generic.
"""
from __future__ import annotations
from typing import Optional


# Each entry: (matcher_keywords, vendor_recipes)
#   matcher_keywords: list of substrings that select the recipe family
#   vendor_recipes:   {vendor_name: [commands]}
_RECIPES: list[tuple[list[str], dict[str, list[str]]]] = [
    # ── Disable Telnet ──────────────────────────────────────────────
    (["telnet"], {
        "Cisco":     ["enable", "configure terminal",
                      "line vty 0 4", " transport input ssh", " exit",
                      "no service telnet-server", "end",
                      "write memory"],
        "TP-Link":   ["# TP-Link routers — no shell; use Web UI",
                      "# 1. Login to http://192.168.x.1 (admin/admin or set password)",
                      "# 2. Advanced → System Tools → Administration",
                      "# 3. Set 'Remote Management' = Disable",
                      "# 4. Under 'Service' uncheck Telnet, save"],
        "MikroTik":  ["/ip service disable telnet"],
        "Juniper":   ["edit",
                      "delete system services telnet",
                      "set system services ssh",
                      "commit and-quit"],
        "Fortinet":  ["config system global",
                      " set admin-https-redirect enable",
                      " set admintimeout 5",
                      "end",
                      "config system interface",
                      " edit any",
                      " unset allowaccess",
                      " set allowaccess ping https ssh",
                      "next",
                      "end"],
        "HP":        ["configure",
                      "no telnet-server",
                      "ip ssh", "ip ssh version 2",
                      "write memory"],
        "Ubiquiti":  ["configure",
                      "delete service telnet-server",
                      "set service ssh",
                      "commit", "save", "exit"],
        "Linux":     ["sudo systemctl disable --now telnet.socket telnetd 2>/dev/null || true",
                      "sudo apt purge -y telnetd inetutils-telnetd 2>/dev/null || true"],
    }),

    # ── Upgrade SNMP v1/v2c → SNMPv3 ────────────────────────────────
    (["snmp v1", "snmp v2c", "snmp v1/v2c", "cleartext community"], {
        "Cisco":     ["configure terminal",
                      "no snmp-server community public",
                      "no snmp-server community private",
                      "snmp-server group AEAOP-RW v3 priv",
                      "snmp-server user aeaop-mon AEAOP-RW v3 auth sha {AUTH_PASS} priv aes 128 {PRIV_PASS}",
                      "end", "write memory"],
        "MikroTik":  ["/snmp community remove [find name=public]",
                      "/snmp community add name=aeaop-mon security=authPriv "
                      "authentication-protocol=SHA1 encryption-protocol=AES "
                      "authentication-password={AUTH_PASS} encryption-password={PRIV_PASS}"],
        "Juniper":   ["edit",
                      "delete snmp community public",
                      "set snmp v3 usm local-engine user aeaop-mon authentication-sha "
                      "authentication-password {AUTH_PASS} privacy-aes128 "
                      "privacy-password {PRIV_PASS}",
                      "commit and-quit"],
        "Fortinet":  ["config system snmp community",
                      " delete public",
                      "end",
                      "config system snmp user",
                      " edit aeaop-mon",
                      "  set security-level auth-priv",
                      "  set auth-proto sha",
                      "  set auth-pwd {AUTH_PASS}",
                      "  set priv-proto aes",
                      "  set priv-pwd {PRIV_PASS}",
                      " next", "end"],
        "HP":        ["configure",
                      "no snmp-server community public",
                      "snmpv3 enable",
                      "snmpv3 user aeaop-mon auth sha {AUTH_PASS} priv aes {PRIV_PASS}",
                      "write memory"],
        "Linux":     ["sudo systemctl stop snmpd",
                      "sudo sed -i 's/^rocommunity public.*/# disabled/' /etc/snmp/snmpd.conf",
                      "echo 'createUser aeaop-mon SHA {AUTH_PASS} AES {PRIV_PASS}' | sudo tee -a /var/lib/snmp/snmpd.conf",
                      "echo 'rouser aeaop-mon authpriv' | sudo tee -a /etc/snmp/snmpd.conf",
                      "sudo systemctl start snmpd"],
    }),

    # ── Restrict RDP exposure (tcp/3389) ────────────────────────────
    (["rdp exposed", "tcp/3389"], {
        "Windows":   ["# Restrict RDP to mgmt subnet via Windows Firewall",
                      "powershell -Command \"Set-NetFirewallRule -DisplayGroup 'Remote Desktop' -RemoteAddress '10.0.0.0/8','192.168.0.0/16'\"",
                      "powershell -Command \"Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name 'UserAuthentication' -Value 1\"  # require NLA"],
        "Linux":     ["# Linux not typically RDP — but if xrdp installed:",
                      "sudo ufw deny 3389/tcp"],
    }),

    # ── Restrict / harden exposed Redis ─────────────────────────────
    (["redis exposed", "tcp/6379"], {
        "Linux":     ["sudo sed -i 's/^bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf",
                      "sudo sed -i 's/^# requirepass.*/requirepass {REDIS_PASS}/' /etc/redis/redis.conf",
                      "sudo sed -i 's/^protected-mode .*/protected-mode yes/' /etc/redis/redis.conf",
                      "sudo systemctl restart redis-server"],
    }),

    # ── Restrict / harden exposed Postgres ─────────────────────────
    (["postgresql", "postgres port"], {
        "Linux":     ["# Restrict to app subnet via pg_hba.conf",
                      "sudo sed -i 's/^host\\s\\+all\\s\\+all\\s\\+0\\.0\\.0\\.0\\/0.*/host all all 10.0.0.0\\/8 scram-sha-256/' /etc/postgresql/*/main/pg_hba.conf",
                      "sudo systemctl reload postgresql"],
    }),

    # ── Restrict / harden exposed Elasticsearch ─────────────────────
    (["elasticsearch", "tcp/9200"], {
        "Linux":     ["echo 'xpack.security.enabled: true' | sudo tee -a /etc/elasticsearch/elasticsearch.yml",
                      "echo 'network.host: 127.0.0.1' | sudo tee -a /etc/elasticsearch/elasticsearch.yml",
                      "sudo systemctl restart elasticsearch"],
    }),

    # ── CPU pressure ────────────────────────────────────────────────
    (["cpu saturated", "cpu pressure", "cpu critical", "cpu high"], {
        "Linux":     ["top -bn1 | head -20",
                      "ps -eo pid,pcpu,pmem,cmd --sort=-pcpu | head",
                      "# After identifying the hot process:",
                      "sudo systemctl restart <SERVICE>"],
        "Windows":   ["powershell -Command \"Get-Process | Sort-Object CPU -Descending | Select-Object -First 5\"",
                      "# Then restart the offending service:",
                      "powershell -Command \"Restart-Service <SERVICE>\""],
        "Cisco":     ["show processes cpu sorted",
                      "show running-config | begin route-map",
                      "# Likely a route flap or AAA issue; investigate before clearing."],
    }),

    # ── Memory pressure ─────────────────────────────────────────────
    (["memory high", "memory critical", "mem high"], {
        "Linux":     ["free -h",
                      "ps -eo pid,pmem,cmd --sort=-pmem | head",
                      "sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches"],
        "Windows":   ["powershell -Command \"Get-Counter '\\Memory\\Available MBytes'\"",
                      "powershell -Command \"Get-Process | Sort-Object WS -Descending | Select -First 5\""],
    }),

    # ── Disk almost full ────────────────────────────────────────────
    (["disk almost full", "disk usage high", "disk full"], {
        "Linux":     ["df -h",
                      "sudo find /var/log -type f \\( -name '*.gz' -o -name '*.old' \\) -mtime +7 -delete",
                      "sudo journalctl --vacuum-time=7d",
                      "sudo apt clean || sudo yum clean all"],
        "Windows":   ["powershell -Command \"Get-PSDrive C\"",
                      "powershell -Command \"cleanmgr /sagerun:1\"",
                      "powershell -Command \"Get-ChildItem $env:TEMP -Recurse | Remove-Item -Force -Recurse\""],
    }),
]


def generate_config(finding_title: str, vendor: str, *, params: Optional[dict] = None) -> dict:
    """Return a vendor-specific config snippet to fix the given finding.

    Args:
        finding_title: e.g. "Insecure protocol Telnet (tcp/23) exposed"
        vendor:        e.g. "Cisco", "MikroTik", "Linux", "Windows"
        params:        substitutions (AUTH_PASS, PRIV_PASS, REDIS_PASS, SERVICE)
    Returns:
        {recipe: <matched keyword>, vendor: <chosen vendor>, commands: [...], applied_params: {...}}
    """
    title = (finding_title or "").lower()
    vend  = (vendor or "").strip()

    # Try exact vendor first; fall back to Linux/Generic for *nix hosts.
    candidates = [vend]
    if vend not in ("Windows", "Linux"):
        candidates.append("Linux")   # most appliances + many OSes have a Linux fallback

    for kws, recipes in _RECIPES:
        if not any(k in title for k in kws):
            continue
        for c in candidates:
            if c in recipes:
                cmds = list(recipes[c])
                # Substitute placeholders
                p = {**{"AUTH_PASS": "ChangeMe-Auth!23",
                        "PRIV_PASS": "ChangeMe-Priv!23",
                        "REDIS_PASS": "ChangeMe-Redis!23",
                        "SERVICE":   "<service-name>"}, **(params or {})}
                cmds = [c.format(**p) for c in cmds]
                return {
                    "matched_keyword": next(k for k in kws if k in title),
                    "vendor":          c,
                    "commands":        cmds,
                    "applied_params":  p,
                    "supported":       True,
                }

    return {
        "matched_keyword": None,
        "vendor":          vend,
        "commands":        [],
        "supported":       False,
        "message":         f"No automated config recipe for finding '{finding_title}' on vendor '{vend}'. "
                            "Manual review needed.",
    }
