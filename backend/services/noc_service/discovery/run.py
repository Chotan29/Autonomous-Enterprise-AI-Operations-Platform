"""
Standalone entrypoint for the Network Discovery Tool.

Run the web dashboard + REST API:
    python -m backend.services.noc_service.discovery.run

Run a one-off CLI scan (no web server) and export results:
    python -m backend.services.noc_service.discovery.run scan
    python -m backend.services.noc_service.discovery.run scan --subnet 192.168.1.0/24 --export

Environment overrides (examples):
    DISCOVERY_PORT=9000 DISCOVERY_ADMIN_PASSWORD=secret python -m ...run
"""
from __future__ import annotations

import argparse
import logging
import sys

from backend.services.noc_service.discovery.config import discovery_settings


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def cmd_serve(_args: argparse.Namespace) -> int:
    import uvicorn

    print(f"  Network Discovery dashboard:  http://{discovery_settings.HOST}:{discovery_settings.PORT}/")
    print(f"  Default login: {discovery_settings.ADMIN_USERNAME} / {discovery_settings.ADMIN_PASSWORD}")
    print("  (change DISCOVERY_ADMIN_PASSWORD in production)\n")
    uvicorn.run(
        "backend.services.noc_service.discovery.app:app",
        host=discovery_settings.HOST,
        port=discovery_settings.PORT,
        log_level="info",
    )
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    from backend.services.noc_service.discovery import exporters
    from backend.services.noc_service.discovery.scanner import NetworkScanner
    from backend.services.noc_service.discovery.store import DiscoveryStore

    scanner = NetworkScanner(discovery_settings)
    try:
        target = scanner.resolve_subnet(args.subnet)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Scanning {target} ...")
    store = DiscoveryStore(discovery_settings.db_path)
    scan_id = store.start_scan(target, "cli", "cli")
    result = scanner.scan(target)
    devices = [h.to_dict() for h in result.hosts]
    store.finish_scan(scan_id, devices, result.duration)

    print(f"\nFound {len(devices)} live host(s) via {result.method} in {result.duration:.1f}s:\n")
    print(f"{'IP':<16}{'MAC':<19}{'Vendor':<22}{'Type':<16}{'Hostname'}")
    print("-" * 90)
    for d in devices:
        print(f"{d['ip_address']:<16}{(d['mac_address'] or '—'):<19}"
              f"{(d['vendor'] or 'Unknown')[:21]:<22}{(d['device_type'] or '—'):<16}"
              f"{d['hostname'] or '—'}")

    if args.export:
        paths = exporters.export_all(store.list_devices(status="online"), discovery_settings.export_dir)
        print("\nExported:")
        for fmt, path in paths.items():
            print(f"  {fmt:<6} {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="network-discovery", description="Network Discovery Tool")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Run the web dashboard + REST API (default).")
    p_serve.set_defaults(func=cmd_serve)

    p_scan = sub.add_parser("scan", help="Run a one-off CLI scan.")
    p_scan.add_argument("--subnet", default=None, help="CIDR to scan (default: auto-detect local subnet).")
    p_scan.add_argument("--export", action="store_true", help="Export CSV/Excel/JSON after scanning.")
    p_scan.set_defaults(func=cmd_scan)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_serve(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
