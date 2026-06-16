"""
SQLite persistence layer for the Network Discovery Tool.

Stores three things:
  * ``devices``      -- the current inventory (one row per MAC, or per IP when
                        no MAC is available), with first_seen / last_seen /
                        current status.
  * ``scan_runs``    -- one row per scan, for history.
  * ``scan_results`` -- per-device snapshot for each scan run (device history).
  * ``users``        -- dashboard login accounts (bcrypt-hashed passwords).

The store is deliberately dependency-light (stdlib ``sqlite3`` only) and
thread-safe via a lock, so it runs anywhere without the platform's Postgres.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.core.security import hash_password, verify_password


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_key    TEXT UNIQUE NOT NULL,      -- MAC (preferred) or 'ip:<addr>'
    ip_address    TEXT NOT NULL,
    mac_address   TEXT,
    hostname      TEXT,
    vendor        TEXT,
    device_type   TEXT,
    open_ports    TEXT,                      -- JSON list[int]
    is_gateway    INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'online',     -- online | offline
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    times_seen    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_devices_ip     ON devices(ip_address);
CREATE INDEX IF NOT EXISTS idx_devices_vendor ON devices(vendor);
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);

CREATE TABLE IF NOT EXISTS scan_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    subnet        TEXT,
    method        TEXT,
    hosts_found   INTEGER DEFAULT 0,
    duration_sec  REAL,
    triggered_by  TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at);

CREATE TABLE IF NOT EXISTS scan_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL,
    ip_address    TEXT NOT NULL,
    mac_address   TEXT,
    hostname      TEXT,
    vendor        TEXT,
    device_type   TEXT,
    open_ports    TEXT,
    seen_at       TEXT NOT NULL,
    FOREIGN KEY (scan_id) REFERENCES scan_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_scan_results_scan ON scan_results(scan_id);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);
"""


class DiscoveryStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    # ── low-level ──────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── users / auth ───────────────────────────────────────────────────────
    def ensure_admin(self, username: str, password: str) -> None:
        """Create the bootstrap admin if no users exist."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            if row["c"] == 0:
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                    (username, hash_password(password), _utcnow_iso()),
                )

    def verify_login(self, username: str, password: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not row:
                return False
            if verify_password(password, row["password_hash"]):
                conn.execute(
                    "UPDATE users SET last_login_at = ? WHERE username = ?",
                    (_utcnow_iso(), username),
                )
                return True
            return False

    def create_user(self, username: str, password: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                (username, hash_password(password), _utcnow_iso()),
            )

    def change_password(self, username: str, new_password: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (hash_password(new_password), username),
            )
            return cur.rowcount > 0

    # ── scan persistence ───────────────────────────────────────────────────
    def start_scan(self, subnet: str, method: str, triggered_by: str | None) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scan_runs (started_at, subnet, method, triggered_by) "
                "VALUES (?,?,?,?)",
                (_utcnow_iso(), subnet, method, triggered_by),
            )
            return int(cur.lastrowid)

    def finish_scan(self, scan_id: int, devices: list[dict[str, Any]], duration: float) -> None:
        """Record results, refresh the inventory, and mark missing as offline."""
        now = _utcnow_iso()
        seen_keys: list[str] = []
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE scan_runs SET finished_at=?, hosts_found=?, duration_sec=? WHERE id=?",
                (now, len(devices), round(duration, 2), scan_id),
            )
            for d in devices:
                key = d.get("mac_address") or f"ip:{d['ip_address']}"
                seen_keys.append(key)
                ports_json = json.dumps(sorted(d.get("open_ports") or []))
                # scan_results snapshot
                conn.execute(
                    "INSERT INTO scan_results "
                    "(scan_id, ip_address, mac_address, hostname, vendor, device_type, open_ports, seen_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (scan_id, d["ip_address"], d.get("mac_address"), d.get("hostname"),
                     d.get("vendor"), d.get("device_type"), ports_json, now),
                )
                # upsert inventory
                existing = conn.execute(
                    "SELECT id, times_seen FROM devices WHERE device_key = ?", (key,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE devices SET ip_address=?, mac_address=?, hostname=?, vendor=?, "
                        "device_type=?, open_ports=?, is_gateway=?, status='online', "
                        "last_seen=?, times_seen=? WHERE id=?",
                        (d["ip_address"], d.get("mac_address"), d.get("hostname"), d.get("vendor"),
                         d.get("device_type"), ports_json, int(bool(d.get("is_gateway"))),
                         now, existing["times_seen"] + 1, existing["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO devices "
                        "(device_key, ip_address, mac_address, hostname, vendor, device_type, "
                        " open_ports, is_gateway, status, first_seen, last_seen, times_seen) "
                        "VALUES (?,?,?,?,?,?,?,?, 'online', ?, ?, 1)",
                        (key, d["ip_address"], d.get("mac_address"), d.get("hostname"),
                         d.get("vendor"), d.get("device_type"), ports_json,
                         int(bool(d.get("is_gateway"))), now, now),
                    )
            # Mark everything not seen in this scan as offline.
            if seen_keys:
                placeholders = ",".join("?" * len(seen_keys))
                conn.execute(
                    f"UPDATE devices SET status='offline' WHERE device_key NOT IN ({placeholders})",
                    seen_keys,
                )

    # ── queries ────────────────────────────────────────────────────────────
    def list_devices(
        self,
        *,
        status: str | None = None,
        vendor: str | None = None,
        device_type: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM devices WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if vendor:
            sql += " AND vendor LIKE ?"
            params.append(f"%{vendor}%")
        if device_type:
            sql += " AND device_type = ?"
            params.append(device_type)
        if search:
            sql += " AND (ip_address LIKE ? OR hostname LIKE ? OR mac_address LIKE ? OR vendor LIKE ?)"
            like = f"%{search}%"
            params += [like, like, like, like]
        sql += " ORDER BY (status='online') DESC, ip_address"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_device(r) for r in rows]

    def online_count(self) -> int:
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM devices WHERE status='online'"
            ).fetchone()["c"]

    def vendors(self) -> list[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT vendor FROM devices WHERE vendor IS NOT NULL AND vendor != '' "
                "ORDER BY vendor"
            ).fetchall()
        return [r["vendor"] for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM devices").fetchone()["c"]
            online = conn.execute(
                "SELECT COUNT(*) AS c FROM devices WHERE status='online'"
            ).fetchone()["c"]
            by_type = {
                r["device_type"] or "Unknown": r["c"]
                for r in conn.execute(
                    "SELECT device_type, COUNT(*) AS c FROM devices WHERE status='online' "
                    "GROUP BY device_type"
                ).fetchall()
            }
            last = conn.execute(
                "SELECT finished_at FROM scan_runs WHERE finished_at IS NOT NULL "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "total_devices": total,
            "online_devices": online,
            "offline_devices": total - online,
            "by_type": by_type,
            "last_scan": last["finished_at"] if last else None,
        }

    def scan_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def device_history(self, device_key: str, limit: int = 100) -> list[dict[str, Any]]:
        """History snapshots for one device (by MAC or 'ip:<addr>')."""
        ip = device_key[3:] if device_key.startswith("ip:") else None
        with self._lock, self._connect() as conn:
            if ip:
                rows = conn.execute(
                    "SELECT * FROM scan_results WHERE mac_address IS NULL AND ip_address=? "
                    "ORDER BY id DESC LIMIT ?",
                    (ip, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scan_results WHERE mac_address=? ORDER BY id DESC LIMIT ?",
                    (device_key, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_device(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        try:
            d["open_ports"] = json.loads(d.get("open_ports") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["open_ports"] = []
        d["is_gateway"] = bool(d.get("is_gateway"))
        return d
