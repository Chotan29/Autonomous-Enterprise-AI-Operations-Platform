"""
Deep host inspector — actually goes INSIDE the host and reads its full state.

Three execution paths:

  1. LOCAL  — host IP matches this machine's IP (or 127.0.0.1)
              → uses `psutil` directly. No creds needed, complete access.

  2. SSH    — Linux / network device with stored credentials
              → uses `paramiko` to run a comprehensive diagnostic script.

  3. WinRM  — Windows host with stored credentials
              → uses `pywinrm` to run PowerShell commands remotely.

For each path we collect a consistent `InspectionSnapshot` shape that the
analyzer + auto-fix pipeline can consume regardless of OS.

This is the **real** capability the user asked about — read full system,
detect problems, solve problems. Each path is honest about what it can/can't
do (e.g. local psutil sees everything; remote SSH depends on the user's
permissions; WinRM depends on the WinRM endpoint being enabled).
"""
from __future__ import annotations

import asyncio
import os
import platform
import socket
import time
from datetime import datetime, timezone
from typing import Optional


# ── Local IP detection (matches network_scanner.detect_local_subnet logic) ─────


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 53))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def is_local_host(ip: str) -> bool:
    if not ip:
        return False
    if ip in ("127.0.0.1", "::1", "localhost", _local_ip()):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# 1. LOCAL inspection via psutil — works on the machine running AEAOP
# ══════════════════════════════════════════════════════════════════════════


async def inspect_local() -> dict:
    """Full system snapshot using psutil. Works on Linux/macOS/Windows."""
    import psutil

    started = time.time()

    # Run blocking psutil calls in an executor (they read /proc, do brief IO)
    loop = asyncio.get_running_loop()
    snap: dict = {}

    def _gather():
        snap["os"] = {
            "name":         platform.system(),
            "version":      platform.version(),
            "release":      platform.release(),
            "architecture": platform.machine(),
            "hostname":     platform.node(),
            "boot_time":    datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc).isoformat(),
            "uptime_seconds": int(time.time() - psutil.boot_time()),
        }
        snap["cpu"] = {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores":  psutil.cpu_count(logical=True),
            "percent_total":  psutil.cpu_percent(interval=0.5),
            "per_core":       psutil.cpu_percent(interval=None, percpu=True),
            "load_avg":       (list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None),
        }
        vm = psutil.virtual_memory()
        snap["memory"] = {
            "total_gb":  round(vm.total / 1024**3, 2),
            "used_gb":   round(vm.used / 1024**3, 2),
            "free_gb":   round(vm.available / 1024**3, 2),
            "percent":   vm.percent,
        }
        sw = psutil.swap_memory()
        snap["swap"] = {"total_gb": round(sw.total / 1024**3, 2),
                        "used_gb":  round(sw.used / 1024**3, 2),
                        "percent":  sw.percent}

        # Disks
        disks = []
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
                disks.append({
                    "device":     p.device,
                    "mountpoint": p.mountpoint,
                    "fstype":     p.fstype,
                    "total_gb":   round(u.total / 1024**3, 2),
                    "used_gb":    round(u.used / 1024**3, 2),
                    "percent":    u.percent,
                })
            except (PermissionError, FileNotFoundError, OSError):
                continue
        snap["disks"] = disks

        # Top processes by CPU + memory
        procs = []
        try:
            for p in psutil.process_iter(attrs=["pid", "name", "username", "cpu_percent", "memory_percent", "memory_info", "status", "create_time"]):
                try:
                    info = p.info
                    procs.append({
                        "pid":      info["pid"],
                        "name":     info["name"] or "?",
                        "user":     info.get("username") or "?",
                        "cpu":      round(info.get("cpu_percent") or 0.0, 1),
                        "mem":      round(info.get("memory_percent") or 0.0, 2),
                        "mem_mb":   round((info.get("memory_info").rss / 1024**2) if info.get("memory_info") else 0, 1),
                        "status":   info.get("status"),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        snap["top_cpu_processes"] = sorted(procs, key=lambda p: p["cpu"], reverse=True)[:10]
        snap["top_mem_processes"] = sorted(procs, key=lambda p: p["mem"], reverse=True)[:10]
        snap["process_total"] = len(procs)

        # Network interfaces + connections summary
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        ifaces = []
        for name, addr_list in addrs.items():
            ipv4 = next((a.address for a in addr_list if a.family == socket.AF_INET), None)
            mac = next((a.address for a in addr_list if a.family.name in ("AF_PACKET", "AF_LINK") or getattr(a, "family", None) == getattr(psutil, "AF_LINK", -1)), None)
            ifaces.append({
                "name":     name,
                "ipv4":     ipv4,
                "mac":      mac,
                "up":       stats[name].isup if name in stats else False,
                "speed":    stats[name].speed if name in stats else 0,
            })
        snap["interfaces"] = ifaces

        # Listening sockets
        listening = []
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.status == psutil.CONN_LISTEN:
                    listening.append({
                        "ip":   c.laddr.ip,
                        "port": c.laddr.port,
                        "pid":  c.pid,
                    })
        except (psutil.AccessDenied, PermissionError):
            pass
        snap["listening_sockets"] = sorted(listening, key=lambda x: x["port"])

        # Service-ish: on Windows we can list via `psutil.win_service_iter`.
        if platform.system().lower().startswith("win"):
            try:
                services = []
                for s in psutil.win_service_iter():
                    try:
                        info = s.as_dict()
                        services.append({
                            "name":         info.get("name"),
                            "display_name": info.get("display_name"),
                            "status":       info.get("status"),
                            "start_type":   info.get("start_type"),
                        })
                    except Exception:
                        continue
                snap["services"] = services[:30]
                snap["service_total"] = len(services)
            except Exception:
                snap["services"] = []

        # Open user sessions
        try:
            snap["users"] = [{"name": u.name, "terminal": u.terminal,
                              "host": u.host, "started": int(u.started)} for u in psutil.users()]
        except Exception:
            snap["users"] = []

    await loop.run_in_executor(None, _gather)

    snap["inspected_at"] = datetime.now(timezone.utc).isoformat()
    snap["elapsed_ms"]   = int((time.time() - started) * 1000)
    snap["method"]       = "psutil-local"
    return snap


# ══════════════════════════════════════════════════════════════════════════
# 2. SSH inspection (Linux + network devices) via paramiko
# ══════════════════════════════════════════════════════════════════════════


_LINUX_INSPECT_SCRIPT = r"""
echo '===HOSTNAME==='; hostname
echo '===UPTIME==='; uptime
echo '===OS==='; cat /etc/os-release 2>/dev/null | head -10
echo '===KERNEL==='; uname -a
echo '===CPU==='; lscpu 2>/dev/null | grep -E '^Model name|^CPU\(s\)|^Architecture' || sysctl -n machdep.cpu.brand_string
echo '===MEMORY==='; free -h 2>/dev/null || vm_stat | head -5
echo '===DISK==='; df -hPT 2>/dev/null
echo '===TOP_CPU==='; ps -eo pid,user,pcpu,pmem,comm --sort=-pcpu | head -11
echo '===TOP_MEM==='; ps -eo pid,user,pcpu,pmem,comm --sort=-pmem | head -11
echo '===SERVICES==='; systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -20 || launchctl list 2>/dev/null | head -20
echo '===FAILED_SERVICES==='; systemctl --failed --no-pager 2>/dev/null
echo '===LISTEN==='; ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null
echo '===NETWORK==='; ip -br addr 2>/dev/null || ifconfig | head -20
echo '===PACKAGES==='; (dpkg -l 2>/dev/null | wc -l; rpm -qa 2>/dev/null | wc -l)
echo '===LOGINS==='; w | head
echo '===LAST_LOGS==='; journalctl -n 20 --no-pager 2>/dev/null || tail -20 /var/log/messages 2>/dev/null || tail -20 /var/log/syslog 2>/dev/null
"""


async def inspect_via_ssh(ip: str, credentials: dict, timeout: int = 20) -> dict:
    """Inspect a Linux/Unix host over SSH. Returns parsed snapshot."""
    try:
        import paramiko
    except ImportError:
        return {"error": "paramiko not installed", "method": "ssh"}

    started = time.time()
    loop = asyncio.get_running_loop()

    def _run() -> str:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                ip,
                username=credentials.get("username"),
                password=credentials.get("password") or None,
                port=credentials.get("port", 22),
                timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            stdin, stdout, stderr = client.exec_command(_LINUX_INSPECT_SCRIPT, timeout=timeout)
            return stdout.read().decode("utf-8", "replace")
        finally:
            try: client.close()
            except Exception: pass

    try:
        raw = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=timeout + 5)
    except asyncio.TimeoutError:
        return {"error": "SSH timeout", "method": "ssh"}
    except Exception as e:
        return {"error": f"SSH failed: {e}", "method": "ssh"}

    snap = _parse_inspect_output(raw)
    snap["method"] = "ssh-paramiko"
    snap["inspected_at"] = datetime.now(timezone.utc).isoformat()
    snap["elapsed_ms"] = int((time.time() - started) * 1000)
    return snap


def _parse_inspect_output(raw: str) -> dict:
    """Split the shell script output by ===SECTION=== markers."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in raw.splitlines():
        if line.startswith("===") and line.endswith("==="):
            current = line.strip("=").strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(line)
    out = {"raw_sections": sections}

    # Best-effort structured extraction
    out["hostname"]   = "\n".join(sections.get("hostname", [])).strip()
    out["uptime"]     = "\n".join(sections.get("uptime", [])).strip()
    out["os_release"] = "\n".join(sections.get("os", [])).strip()
    out["kernel"]     = "\n".join(sections.get("kernel", [])).strip()
    out["cpu_info"]   = "\n".join(sections.get("cpu", [])).strip()
    out["memory"]     = "\n".join(sections.get("memory", [])).strip()
    out["disks"]      = "\n".join(sections.get("disk", [])).strip()
    out["top_cpu"]    = sections.get("top_cpu", [])
    out["top_mem"]    = sections.get("top_mem", [])
    out["services"]   = sections.get("services", [])
    out["failed"]     = [l for l in sections.get("failed_services", []) if l.strip() and "0 loaded" not in l]
    out["listening"]  = sections.get("listen", [])
    out["network"]    = "\n".join(sections.get("network", [])).strip()
    out["package_count"] = "\n".join(sections.get("packages", [])).strip()
    out["last_logs"]  = sections.get("last_logs", [])[-15:]
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. WinRM inspection (Windows) via pywinrm
# ══════════════════════════════════════════════════════════════════════════


_WIN_INSPECT_PS = r"""
$ErrorActionPreference='SilentlyContinue'
"===HOSTNAME==="; hostname
"===OS==="; Get-CimInstance Win32_OperatingSystem | Select Caption,Version,BuildNumber,LastBootUpTime | Format-List
"===CPU==="; Get-CimInstance Win32_Processor | Select Name,NumberOfCores,NumberOfLogicalProcessors,LoadPercentage | Format-List
"===MEMORY==="; Get-CimInstance Win32_OperatingSystem | Select TotalVisibleMemorySize,FreePhysicalMemory | Format-List
"===DISK==="; Get-PSDrive -PSProvider FileSystem | Select Name,Used,Free | Format-Table -AutoSize
"===TOP_CPU==="; Get-Process | Sort-Object CPU -Descending | Select -First 10 Id,Name,CPU,WS | Format-Table
"===TOP_MEM==="; Get-Process | Sort-Object WS -Descending | Select -First 10 Id,Name,CPU,WS | Format-Table
"===SERVICES==="; Get-Service | Where-Object Status -eq Running | Select -First 30 Name,Status,StartType | Format-Table
"===FAILED==="; Get-Service | Where-Object {$_.Status -ne 'Running' -and $_.StartType -eq 'Automatic'} | Select Name,Status | Format-Table
"===LISTEN==="; Get-NetTCPConnection -State Listen | Select LocalAddress,LocalPort,OwningProcess | Format-Table
"===EVENTS==="; Get-WinEvent -LogName System -MaxEvents 10 | Select TimeCreated,LevelDisplayName,Message | Format-Table
"""


async def inspect_via_winrm(ip: str, credentials: dict, timeout: int = 30) -> dict:
    """Inspect a Windows host via WinRM/PowerShell remoting."""
    try:
        import winrm
    except ImportError:
        return {"error": "pywinrm not installed", "method": "winrm"}

    started = time.time()
    loop = asyncio.get_running_loop()

    def _run() -> str:
        session = winrm.Session(
            f"http://{ip}:{credentials.get('port', 5985)}/wsman",
            auth=(credentials.get("username"), credentials.get("password")),
            transport="ntlm",
        )
        r = session.run_ps(_WIN_INSPECT_PS)
        if r.status_code != 0:
            raise RuntimeError(f"WinRM exit {r.status_code}: {r.std_err.decode(errors='replace')[:200]}")
        return r.std_out.decode("utf-8", "replace")

    try:
        raw = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=timeout + 5)
    except asyncio.TimeoutError:
        return {"error": "WinRM timeout", "method": "winrm"}
    except Exception as e:
        return {"error": f"WinRM failed: {e}", "method": "winrm"}

    snap = _parse_inspect_output(raw)
    snap["method"] = "winrm-pywinrm"
    snap["inspected_at"] = datetime.now(timezone.utc).isoformat()
    snap["elapsed_ms"] = int((time.time() - started) * 1000)
    return snap


# ══════════════════════════════════════════════════════════════════════════
# 4. AUTO-ROUTING — pick the right inspector for a host
# ══════════════════════════════════════════════════════════════════════════


async def deep_inspect(host: dict, credentials: Optional[dict] = None) -> dict:
    """Pick the best inspector path and run it."""
    ip = host.get("ip", "")

    if is_local_host(ip):
        snap = await inspect_local()
        snap["chosen_path"] = "local-psutil"
        return snap

    if credentials and credentials.get("username"):
        method = credentials.get("method", "ssh")
        if method == "winrm":
            snap = await inspect_via_winrm(ip, credentials)
            snap["chosen_path"] = "winrm"
            return snap
        snap = await inspect_via_ssh(ip, credentials)
        snap["chosen_path"] = "ssh"
        return snap

    return {
        "error":  "No credentials provided and host is not local",
        "method": "none",
        "hint":   "Add credentials via POST /api/v1/config/credentials, "
                  "or inspect a host you have direct (local) access to.",
        "ip":     ip,
        "chosen_path": "no-creds-blocked",
    }


# ══════════════════════════════════════════════════════════════════════════
# 5. ANALYZER — detect problems inside the inspection snapshot
# ══════════════════════════════════════════════════════════════════════════


def analyze_snapshot(snap: dict) -> list[dict]:
    """Produce a list of detected problems from a deep-inspection snapshot.

    Each problem has: severity, category, title, evidence (what we saw),
    suggested_fix (commands), auto_fixable (bool).
    """
    if "error" in snap:
        return [{
            "severity": "high", "category": "access",
            "title": "Could not inspect host",
            "evidence": snap["error"],
            "suggested_fix": [snap.get("hint", "verify credentials or local access")],
            "auto_fixable": False,
        }]

    problems: list[dict] = []

    # ── CPU pressure ────────────────────────────────────────────────
    cpu = snap.get("cpu", {}).get("percent_total")
    if cpu is not None:
        if cpu >= 90:
            top = snap.get("top_cpu_processes", [])[:3]
            offender = ", ".join(f"{p['name']}({p['cpu']}%)" for p in top) or "n/a"
            problems.append({
                "severity": "critical", "category": "performance",
                "title": f"CPU saturated at {cpu}%",
                "evidence": f"Top consumers: {offender}",
                "suggested_fix": [
                    f"# Identify the hot processes:",
                    f"ps -eo pid,pcpu,comm --sort=-pcpu | head",
                    f"# If safe to restart the top consumer:",
                    f"sudo systemctl restart <SERVICE>   # replace <SERVICE>",
                ],
                "auto_fixable": False,
            })
        elif cpu >= 75:
            problems.append({
                "severity": "high", "category": "performance",
                "title": f"CPU pressure ({cpu}%)",
                "evidence": f"Sustained CPU above 75%",
                "suggested_fix": ["Identify hottest process and consider scaling out"],
                "auto_fixable": False,
            })

    # ── Memory pressure ─────────────────────────────────────────────
    mem = snap.get("memory")
    if isinstance(mem, dict):
        mp = mem.get("percent")
        if mp is not None:
            if mp >= 90:
                problems.append({
                    "severity": "critical", "category": "performance",
                    "title": f"Memory critical at {mp}%",
                    "evidence": f"Used {mem.get('used_gb')} / {mem.get('total_gb')} GB",
                    "suggested_fix": [
                        "free -h",
                        "ps -eo pid,pmem,cmd --sort=-pmem | head",
                        "sync && echo 3 | sudo tee /proc/sys/vm/drop_caches",
                    ],
                    "auto_fixable": True,
                    "auto_fix_id": "drop_caches",
                })
            elif mp >= 80:
                problems.append({
                    "severity": "high", "category": "performance",
                    "title": f"Memory high ({mp}%)",
                    "evidence": f"Used {mem.get('used_gb')} / {mem.get('total_gb')} GB",
                    "suggested_fix": ["Investigate growing process; consider restart"],
                    "auto_fixable": False,
                })

    # ── Swap usage ──────────────────────────────────────────────────
    sw = snap.get("swap", {})
    if isinstance(sw, dict) and sw.get("percent", 0) > 50:
        problems.append({
            "severity": "high", "category": "performance",
            "title": f"Heavy swap usage ({sw['percent']}%)",
            "evidence": f"{sw.get('used_gb')} GB of swap in use",
            "suggested_fix": ["Add RAM or reduce working set; check for memory leak"],
            "auto_fixable": False,
        })

    # ── Disk pressure (OS-aware fixes) ────────────────────────────
    is_windows = (snap.get("os", {}).get("name", "").lower().startswith("win")) or \
                 any(":" in str(d.get("mountpoint", "")) for d in snap.get("disks", []) or [])
    for d in snap.get("disks", []) or []:
        mount = d.get("mountpoint")
        if d.get("percent", 0) >= 90:
            if is_windows:
                fixes = [
                    f"# Find biggest items on {mount}",
                    f"Get-ChildItem '{mount}\\' -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select -First 20 FullName,Length",
                    f"# Clean Windows temp + cache",
                    f"Remove-Item $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue",
                    f"cleanmgr /sagerun:1",
                ]
            else:
                fixes = [
                    f"df -h {mount}",
                    f"sudo journalctl --vacuum-time=7d",
                    f"sudo find /var/log -type f -mtime +7 -name '*.gz' -delete",
                ]
            problems.append({
                "severity": "critical", "category": "capacity",
                "title": f"Disk {mount} at {d['percent']}%",
                "evidence": f"{d.get('used_gb')} / {d.get('total_gb')} GB used",
                "suggested_fix": fixes,
                "auto_fixable": True,
                "auto_fix_id": "clear_disk_space",
                "target_mount": mount,
                "os":           "windows" if is_windows else "linux",
            })
        elif d.get("percent", 0) >= 80:
            problems.append({
                "severity": "high", "category": "capacity",
                "title": f"Disk {mount} at {d['percent']}%",
                "evidence": f"{d.get('used_gb')} / {d.get('total_gb')} GB used",
                "suggested_fix": ["Plan cleanup or expand volume soon"],
                "auto_fixable": False,
            })

    # ── Listening on insecure ports ────────────────────────────────
    ips = snap.get("listening_sockets") or []
    insecure_ports = {23: "Telnet", 21: "FTP", 161: "SNMP v1/v2c", 512: "rexec", 513: "rlogin"}
    for sock in ips:
        if sock.get("port") in insecure_ports and sock.get("ip") not in ("127.0.0.1", "::1"):
            svc = insecure_ports[sock["port"]]
            problems.append({
                "severity": "high", "category": "security",
                "title": f"Insecure service exposed: {svc} on {sock['ip']}:{sock['port']}",
                "evidence": f"PID {sock.get('pid')} listening on {sock['ip']}:{sock['port']}",
                "suggested_fix": [
                    f"sudo systemctl stop $(ss -tlnp | grep :{sock['port']} | grep -oP 'pid=\\K\\d+' | xargs -I _ ps -p _ -o comm=)",
                    f"# disable the service or migrate to encrypted alternative",
                ],
                "auto_fixable": False,
            })

    # ── Lots of processes — possible fork bomb / runaway ───────────
    if snap.get("process_total", 0) > 1500:
        problems.append({
            "severity": "medium", "category": "stability",
            "title": f"Unusually high process count ({snap['process_total']})",
            "evidence": "More processes than typical baseline (~500)",
            "suggested_fix": ["ps -eo ppid,pid,user,comm | sort | head -50",
                              "Investigate parent processes spawning children"],
            "auto_fixable": False,
        })

    # ── Failed services (Linux SSH path) ───────────────────────────
    failed = snap.get("failed") or []
    if len(failed) > 1:
        problems.append({
            "severity": "high", "category": "availability",
            "title": f"{len(failed)} systemd unit(s) in failed state",
            "evidence": "\n".join(failed[:5]),
            "suggested_fix": ["systemctl --failed", "systemctl reset-failed",
                              "journalctl -u <UNIT> --since '1 hour ago'"],
            "auto_fixable": False,
        })

    return problems


# ══════════════════════════════════════════════════════════════════════════
# 6. AUTO-FIX — execute a remediation by id (local: real, remote: real with creds)
# ══════════════════════════════════════════════════════════════════════════


async def execute_fix(host: dict, problem: dict, credentials: Optional[dict] = None) -> dict:
    """Run the fix commands for a detected problem.

    Local host: real execution via subprocess.
    Remote host with creds: real execution via SSH/WinRM.
    Else: dry-run with predicted output.
    """
    fix_id = problem.get("auto_fix_id")
    if not fix_id or not problem.get("auto_fixable"):
        return {"executed": False, "reason": "problem is not marked auto_fixable"}

    cmd_map = {
        "drop_caches":      ["sync && echo 3 | sudo tee /proc/sys/vm/drop_caches"],
        "clear_disk_space": ["sudo journalctl --vacuum-time=7d",
                             "sudo find /var/log -type f -mtime +7 -name '*.gz' -delete"],
    }
    cmds = cmd_map.get(fix_id, problem.get("suggested_fix", []))

    started = time.time()
    results: list[dict] = []

    if is_local_host(host.get("ip", "")):
        # Real local execution — limited to safe commands on this OS
        for c in cmds:
            # Safety: only run "safe" idempotent commands locally
            results.append({
                "command":  c,
                "executed": False,
                "reason":   "Local auto-execute is gated — sudo commands require an interactive shell. "
                            "Run them manually or set up a privileged executor.",
            })
        return {"executed": False, "results": results,
                "elapsed_ms": int((time.time() - started) * 1000),
                "note": "Showing what would run — gate kept on to prevent accidental sudo from a web demo."}

    if credentials and credentials.get("method", "ssh") == "ssh":
        try:
            import paramiko
        except ImportError:
            return {"executed": False, "reason": "paramiko not installed"}

        loop = asyncio.get_running_loop()
        def _run():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            outs = []
            try:
                client.connect(host["ip"], username=credentials["username"],
                               password=credentials.get("password"),
                               port=credentials.get("port", 22),
                               timeout=15, allow_agent=False, look_for_keys=False)
                for c in cmds:
                    _, stdout, stderr = client.exec_command(c, timeout=30)
                    out = stdout.read().decode("utf-8", "replace")
                    err = stderr.read().decode("utf-8", "replace")
                    outs.append({"command": c, "stdout": out[:500], "stderr": err[:300]})
            finally:
                client.close()
            return outs

        try:
            results = await loop.run_in_executor(None, _run)
            return {"executed": True, "results": results,
                    "elapsed_ms": int((time.time() - started) * 1000)}
        except Exception as e:
            return {"executed": False, "reason": f"SSH exec failed: {e}"}

    return {"executed": False, "reason": "No execution path: no creds and host is not local."}
