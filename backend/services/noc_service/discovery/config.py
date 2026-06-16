"""
Configuration for the Network Discovery Tool.

These settings are intentionally self-contained so the discovery tool can run
standalone on any Windows/Linux machine without the full AEAOP platform
(Postgres/Kafka/etc.). Everything can be overridden via environment variables
prefixed with ``DISCOVERY_`` or an ``.env`` file.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """Cross-platform per-user data directory."""
    if os.name == "nt":  # Windows
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "NetworkDiscovery"
    # Linux / macOS
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "network-discovery"


class DiscoverySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DISCOVERY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Storage ────────────────────────────────────────────────────────────
    DATA_DIR: Path = Field(default_factory=_default_data_dir)
    DB_FILENAME: str = "discovery.sqlite3"

    # ── Scan behaviour ─────────────────────────────────────────────────────
    # If empty, the subnet is auto-detected. Set e.g. "192.168.1.0/24" to force.
    SUBNET_OVERRIDE: str = ""
    # Hard safety cap: never scan a subnet larger than this many hosts.
    MAX_HOSTS: int = 1024
    # Worker threads for per-host enrichment.
    MAX_WORKERS: int = 64
    # Per-host TCP connect timeout (seconds) for the fallback ping/port probe.
    HOST_TIMEOUT: float = 1.0
    # Ports probed for liveness (fallback) and device-type classification.
    PROBE_PORTS: tuple[int, ...] = (
        22, 23, 53, 80, 135, 139, 443, 445, 161, 515, 631,
        3389, 8080, 8443, 9100, 554, 1900, 2000, 5000,
    )
    # Use nmap binary when available (falls back to pure-python if not).
    USE_NMAP: bool = True
    # Use scapy ARP scan when available + privileged (falls back to ARP cache).
    USE_SCAPY_ARP: bool = True

    # ── Web / Auth ─────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-this-discovery-secret-in-production"
    SESSION_COOKIE: str = "nd_session"
    SESSION_MAX_AGE: int = 60 * 60 * 8  # 8 hours
    # Bootstrap admin account (created on first run if no users exist).
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"  # CHANGE on first login / via env.
    HOST: str = "0.0.0.0"
    PORT: int = 8088

    @property
    def db_path(self) -> Path:
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return self.DATA_DIR / self.DB_FILENAME

    @property
    def export_dir(self) -> Path:
        d = self.DATA_DIR / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d


@lru_cache
def get_discovery_settings() -> DiscoverySettings:
    return DiscoverySettings()


discovery_settings = get_discovery_settings()
