"""
SNMP collector: polls devices via SNMPv2c/v3, stores metrics, updates device status.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from pysnmp.hlapi.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType,
    SnmpEngine, UdpTransportTarget, getCmd, bulkCmd,
    UsmUserData, usmHMACMD5AuthProtocol, usmDESPrivProtocol,
)

logger = logging.getLogger(__name__)

# ── Common OIDs ───────────────────────────────────────────────────────────────
OID = {
    "sysDescr":        "1.3.6.1.2.1.1.1.0",
    "sysName":         "1.3.6.1.2.1.1.5.0",
    "sysUpTime":       "1.3.6.1.2.1.1.3.0",
    "sysContact":      "1.3.6.1.2.1.1.4.0",
    "sysLocation":     "1.3.6.1.2.1.1.6.0",
    "ifNumber":        "1.3.6.1.2.1.2.1.0",
    "ifDescr":         "1.3.6.1.2.1.2.2.1.2",
    "ifType":          "1.3.6.1.2.1.2.2.1.3",
    "ifSpeed":         "1.3.6.1.2.1.2.2.1.5",
    "ifAdminStatus":   "1.3.6.1.2.1.2.2.1.7",
    "ifOperStatus":    "1.3.6.1.2.1.2.2.1.8",
    "ifInOctets":      "1.3.6.1.2.1.2.2.1.10",
    "ifInErrors":      "1.3.6.1.2.1.2.2.1.14",
    "ifOutOctets":     "1.3.6.1.2.1.2.2.1.16",
    "ifOutErrors":     "1.3.6.1.2.1.2.2.1.20",
    # Cisco-specific
    "ciscoMemFree":    "1.3.6.1.4.1.9.9.48.1.1.1.6",
    "ciscoCPU5min":    "1.3.6.1.4.1.9.2.1.58.0",
    # MikroTik-specific
    "mtCPUFreq":       "1.3.6.1.4.1.14988.1.1.3.14.0",
    # LLDP
    "lldpRemSysName":  "1.0.8802.1.1.2.1.4.1.1.9",
    "lldpRemPortId":   "1.0.8802.1.1.2.1.4.1.1.7",
}

IF_STATUS = {1: "up", 2: "down", 3: "testing"}


class SNMPCollector:
    def __init__(self):
        self.engine = SnmpEngine()

    def _get_auth(self, device: dict):
        version = device.get("snmp_version", "v2c")
        if version == "v3":
            cfg = device.get("snmp_config", {})
            return UsmUserData(
                cfg.get("username", ""),
                authKey=cfg.get("auth_key", ""),
                privKey=cfg.get("priv_key", ""),
                authProtocol=usmHMACMD5AuthProtocol,
                privProtocol=usmDESPrivProtocol,
            )
        community = device.get("snmp_community", "public")
        return CommunityData(community)

    async def get_system_info(self, host: str, device: dict) -> dict:
        """Collect sysDescr, sysName, sysUpTime."""
        auth = self._get_auth(device)
        transport = UdpTransportTarget((host, 161), timeout=5, retries=2)

        result = {}
        oids = [
            ObjectType(ObjectIdentity(OID["sysDescr"])),
            ObjectType(ObjectIdentity(OID["sysName"])),
            ObjectType(ObjectIdentity(OID["sysUpTime"])),
            ObjectType(ObjectIdentity(OID["sysContact"])),
            ObjectType(ObjectIdentity(OID["sysLocation"])),
        ]
        error_indication, error_status, _, var_binds = await getCmd(
            self.engine, auth, transport, ContextData(), *oids
        )
        if error_indication or error_status:
            raise ConnectionError(f"SNMP error for {host}: {error_indication or error_status}")

        keys = ["sysDescr", "sysName", "sysUpTime", "sysContact", "sysLocation"]
        for key, var in zip(keys, var_binds):
            result[key] = str(var[1])

        # Convert uptime timeticks to seconds
        try:
            result["uptime_seconds"] = int(result["sysUpTime"]) // 100
        except (ValueError, TypeError):
            result["uptime_seconds"] = None

        return result

    async def get_interfaces(self, host: str, device: dict) -> list[dict]:
        """Bulk walk interface table."""
        auth = self._get_auth(device)
        transport = UdpTransportTarget((host, 161), timeout=10, retries=2)
        interfaces: dict[int, dict] = {}

        table_oids = {
            "if_name": OID["ifDescr"],
            "if_type": OID["ifType"],
            "speed_bps": OID["ifSpeed"],
            "admin_status": OID["ifAdminStatus"],
            "oper_status": OID["ifOperStatus"],
            "in_octets": OID["ifInOctets"],
            "in_errors": OID["ifInErrors"],
            "out_octets": OID["ifOutOctets"],
            "out_errors": OID["ifOutErrors"],
        }

        for field_name, base_oid in table_oids.items():
            error_indication, error_status, _, var_bind_table = await bulkCmd(
                self.engine, auth, transport, ContextData(),
                0, 50, ObjectType(ObjectIdentity(base_oid)),
                lexicographicMode=False,
            )
            if error_indication:
                logger.warning(f"SNMP bulk walk failed {host} {base_oid}: {error_indication}")
                continue

            for var_bind in var_bind_table:
                for oid, val in var_bind:
                    oid_str = str(oid)
                    index = int(oid_str.split(".")[-1])
                    if index not in interfaces:
                        interfaces[index] = {"if_index": index}
                    raw = str(val)
                    if field_name in ("admin_status", "oper_status"):
                        raw = IF_STATUS.get(int(raw), raw)
                    elif field_name == "speed_bps":
                        try:
                            raw = int(raw)
                        except (ValueError, TypeError):
                            raw = None
                    interfaces[index][field_name] = raw

        return list(interfaces.values())

    async def get_cpu_memory(self, host: str, device: dict) -> dict:
        """Get CPU and memory utilization."""
        vendor = (device.get("vendor") or "").lower()
        auth = self._get_auth(device)
        transport = UdpTransportTarget((host, 161), timeout=5, retries=2)

        result = {"cpu_util": None, "mem_util": None}

        if "cisco" in vendor:
            oids = [
                ObjectType(ObjectIdentity(OID["ciscoCPU5min"])),
                ObjectType(ObjectIdentity(OID["ciscoMemFree"])),
            ]
            error_indication, error_status, _, var_binds = await getCmd(
                self.engine, auth, transport, ContextData(), *oids
            )
            if not error_indication and not error_status:
                try:
                    result["cpu_util"] = float(str(var_binds[0][1]))
                    result["mem_free"] = int(str(var_binds[1][1]))
                except (ValueError, TypeError, IndexError):
                    pass

        return result

    async def full_poll(self, host: str, device: dict) -> dict:
        """Complete device poll: system info + interfaces + CPU/memory."""
        try:
            sys_info = await self.get_system_info(host, device)
            interfaces = await self.get_interfaces(host, device)
            perf = await self.get_cpu_memory(host, device)
            return {
                "success": True,
                "host": host,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system": sys_info,
                "interfaces": interfaces,
                "performance": perf,
            }
        except Exception as exc:
            return {
                "success": False,
                "host": host,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
