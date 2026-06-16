"""
Network Discovery Tool
======================

A professional, cross-platform (Windows + Linux) network inventory and
discovery subsystem for the AEAOP NOC service. Comparable in spirit to
SolarWinds Network Discovery, PRTG Discovery and Advanced IP Scanner.

Capabilities
------------
* Auto-detects the local network subnet and scans **only** that subnet
  (private/local IPs only -- external IPs are always ignored).
* Discovers **live hosts only** using nmap (with a pure-python fallback).
* Collects IP, MAC (via ARP / scapy), hostname (reverse DNS), vendor
  (offline OUI lookup) and a best-effort device type.
* Multi-threaded enrichment for fast scans.
* Persists scan history in SQLite (first seen / last seen / current status).
* Exports results to CSV, Excel and JSON.
* Ships a FastAPI REST API + Bootstrap web dashboard with session login.

Public entry points
--------------------
* :class:`~backend.services.noc_service.discovery.scanner.NetworkScanner`
* :class:`~backend.services.noc_service.discovery.store.DiscoveryStore`
* :func:`~backend.services.noc_service.discovery.app.create_app`
"""

from backend.services.noc_service.discovery.config import discovery_settings

__all__ = ["discovery_settings", "__version__"]

__version__ = "1.0.0"
