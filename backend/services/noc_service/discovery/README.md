# Network Discovery Tool

A professional, cross-platform (**Windows + Linux**) network inventory and
discovery subsystem for the AEAOP NOC service — comparable in spirit to
SolarWinds Network Discovery, PRTG Discovery and Advanced IP Scanner.

It auto-detects your **local subnet**, discovers **only live hosts**, and
identifies each device's IP, MAC, hostname, vendor and device type. Results are
stored in SQLite with full scan history and surfaced through a modern Bootstrap
web dashboard and a REST API with session login.

---

## Features

| Requirement | Status |
|---|---|
| Auto-detect & scan local subnet only (ignore external IPs) | ✅ private-subnet guard + in-range filter |
| Discover live hosts only (no offline hosts in results) | ✅ |
| IP / MAC / Hostname / Vendor / Device Type | ✅ |
| nmap for host discovery | ✅ (`python-nmap`, with pure-python fallback) |
| ARP scan for MAC addresses | ✅ (scapy, with OS ARP-cache fallback) |
| Runs on Windows and Linux | ✅ |
| Multi-threaded scanning | ✅ (`ThreadPoolExecutor`) |
| Export CSV / Excel / JSON | ✅ |
| Modern Flask-style web dashboard | ✅ (FastAPI + Bootstrap 5) |
| Live count, table, search, vendor filter, refresh, history | ✅ |
| Device types: Router / Switch / Firewall / AP / Printer / Server / PC / Camera | ✅ |
| SQLite scan history (first seen / last seen / status) | ✅ |
| REST API: `/scan`, `/devices`, `/history` | ✅ |
| Login authentication | ✅ (session + bcrypt-hashed passwords) |
| Installer + requirements.txt | ✅ |
| Modular, production-ready, documented | ✅ |

---

## Folder structure

```
backend/services/noc_service/discovery/
├── __init__.py                 # package + version
├── config.py                   # settings (env: DISCOVERY_*), cross-platform data dir
├── netinfo.py                  # subnet / gateway / ARP-cache detection (Win+Linux)
├── oui.py                      # MAC → vendor (offline OUI table + optional IEEE file)
├── classifier.py               # device-type classification engine
├── scanner.py                  # core engine: nmap + scapy ARP + threaded enrichment
├── store.py                    # SQLite store: devices, scan_runs, scan_results, users
├── exporters.py                # CSV / Excel (openpyxl) / JSON export
├── auth.py                     # session auth helpers
├── app.py                      # FastAPI app: REST API + dashboard (mountable + standalone)
├── run.py                      # entrypoint: `serve` (web) and `scan` (CLI)
├── templates/                  # Jinja2 + Bootstrap
│   ├── base.html
│   ├── login.html
│   └── dashboard.html
├── static/
│   ├── css/dashboard.css
│   └── js/dashboard.js
├── requirements-discovery.txt  # standalone dependencies
├── install.sh                  # Linux/macOS installer
├── install.ps1                 # Windows installer
└── README.md
```

---

## Install

### Linux / macOS
```bash
cd backend/services/noc_service/discovery
chmod +x install.sh
./install.sh
```

### Windows (elevated PowerShell)
```powershell
cd backend\services\noc_service\discovery
powershell -ExecutionPolicy Bypass -File install.ps1
```

The installer installs the **nmap** binary (and Npcap on Windows for scapy),
creates a virtualenv and installs `requirements-discovery.txt`. The tool also
works **without** nmap/scapy/root by falling back to a pure-python TCP sweep and
the OS ARP cache — you simply get fewer MAC addresses without L2 privileges.

> Run from the **project root** so `backend...` imports resolve, or
> `pip install -e .` the project.

---

## Usage

### Web dashboard + REST API
```bash
# from project root; use sudo / Administrator for full ARP scans
python -m backend.services.noc_service.discovery.run serve
```
Open **http://localhost:8088/** — default login **admin / admin**
(set `DISCOVERY_ADMIN_PASSWORD` before first run to change it).

Already running the NOC service? The tool is auto-mounted there too, at
**`/discovery/`** (e.g. `http://noc-host:PORT/discovery/`).

### One-off CLI scan
```bash
python -m backend.services.noc_service.discovery.run scan                 # auto subnet
python -m backend.services.noc_service.discovery.run scan --subnet 192.168.1.0/24 --export
```

---

## REST API

All `/api/*` endpoints require an authenticated session (log in via `/login`).

| Method | Path | Description |
|---|---|---|
| POST | `/api/scan` | Run a scan of the local subnet. Body: `{"subnet": null}` (auto) or a CIDR. |
| GET  | `/api/devices` | List devices. Query: `status` (`online`/`offline`/`all`), `vendor`, `device_type`, `search`. |
| GET  | `/api/history` | Scan history (`?limit=`). |
| GET  | `/api/device/{key}/history` | Per-device history (key = MAC or `ip:<addr>`). |
| GET  | `/api/stats` | Live counts + breakdown by type. |
| GET  | `/api/vendors` | Distinct vendors (for the filter). |
| GET  | `/api/export?fmt=csv\|excel\|json&status=online` | Download an export file. |

Example:
```bash
curl -X POST http://localhost:8088/api/scan -H "Content-Type: application/json" \
     -b cookies.txt -d '{}'
```

---

## Configuration (environment variables, prefix `DISCOVERY_`)

| Variable | Default | Description |
|---|---|---|
| `DISCOVERY_SUBNET_OVERRIDE` | _(auto)_ | Force a subnet, e.g. `192.168.1.0/24`. |
| `DISCOVERY_MAX_HOSTS` | `1024` | Safety cap on subnet size. |
| `DISCOVERY_MAX_WORKERS` | `64` | Enrichment thread count. |
| `DISCOVERY_HOST_TIMEOUT` | `1.0` | Per-host TCP timeout (s). |
| `DISCOVERY_USE_NMAP` | `true` | Use nmap when available. |
| `DISCOVERY_USE_SCAPY_ARP` | `true` | Use scapy ARP when privileged. |
| `DISCOVERY_ADMIN_USERNAME` / `DISCOVERY_ADMIN_PASSWORD` | `admin` / `admin` | Bootstrap login. |
| `DISCOVERY_SECRET_KEY` | _(dev key)_ | Session signing key — **set in production**. |
| `DISCOVERY_HOST` / `DISCOVERY_PORT` | `0.0.0.0` / `8088` | Web bind address. |
| `DISCOVERY_DATA_DIR` | per-user | SQLite DB + exports location. |
| `DISCOVERY_OUI_FILE` | _(none)_ | Path to an IEEE `oui.txt` / Wireshark `manuf` for full vendor coverage. |

Data (SQLite DB + exports) is stored under a per-user directory:
`%APPDATA%\NetworkDiscovery` on Windows, `~/.local/share/network-discovery` on Linux.

---

## How discovery works

1. **Subnet resolution** — auto-detect the local subnet (psutil netmask, else
   /24). Non-private subnets are **rejected**; only addresses inside the target
   network are ever probed.
2. **ARP sweep** — scapy `arping` (L2, needs root/admin) for IP→MAC, else the OS
   ARP cache populated by the sweep.
3. **Host discovery** — nmap `-sn` ping scan, else a multi-threaded TCP-connect
   sweep (a refused connection still proves liveness).
4. **Enrichment** (threaded) — reverse-DNS hostname, light TCP port probe,
   vendor via OUI, and device-type classification.
5. **Persist** — upsert inventory, snapshot to history, mark unseen devices
   offline, update first/last-seen.

## Security notes

- Change `DISCOVERY_ADMIN_PASSWORD` and set a strong `DISCOVERY_SECRET_KEY`
  before exposing the dashboard.
- Passwords are bcrypt-hashed (via the platform's `core.security`).
- The scanner only touches the local/private subnet — external IPs are refused
  by design.
- Run behind the platform reverse proxy / TLS in production.
```
