"""
MikroTik RouterOS driver via API (librouteros) and SSH fallback.
"""
import re
from typing import Optional

import asyncssh

from backend.services.noc_service.drivers.base_driver import BaseNetworkDriver


class MikrotikDriver(BaseNetworkDriver):
    """Driver for MikroTik RouterOS devices."""

    async def execute_command(self, command: str) -> str:
        """Execute command via SSH (RouterOS CLI)."""
        creds = self._get_credentials()
        async with await asyncssh.connect(
            self.host,
            port=creds.get("port", 22),
            username=creds["username"],
            password=creds.get("password"),
            known_hosts=None,
            connect_timeout=15,
        ) as conn:
            result = await conn.run(command, timeout=30)
            return result.stdout

    async def get_running_config(self) -> str:
        """Export full RouterOS configuration."""
        return await self.execute_command("/export verbose")

    async def get_interfaces(self) -> list[dict]:
        output = await self.execute_command("/interface print detail")
        return self._parse_interfaces(output)

    async def get_lldp_neighbors(self) -> list[dict]:
        try:
            output = await self.execute_command("/ip neighbor print detail")
            return self._parse_neighbors(output)
        except Exception:
            return []

    async def get_routing_table(self) -> str:
        return await self.execute_command("/ip route print")

    async def get_arp_table(self) -> str:
        return await self.execute_command("/ip arp print")

    def _parse_interfaces(self, output: str) -> list[dict]:
        interfaces = []
        current: Optional[dict] = None

        for line in output.splitlines():
            line = line.strip()
            if re.match(r'^\d+\s+', line) or line.startswith("Flags:"):
                if current:
                    interfaces.append(current)
                current = {}
            if current is not None:
                if "name=" in line:
                    m = re.search(r'name="?([^"\s]+)"?', line)
                    if m:
                        current["if_name"] = m.group(1)
                if "type=" in line:
                    m = re.search(r'type=(\S+)', line)
                    if m:
                        current["if_type"] = m.group(1)
                if "running" in line.lower():
                    current["oper_status"] = "up"
                elif "disabled" in line.lower():
                    current["admin_status"] = "down"
                if "actual-mtu=" in line:
                    m = re.search(r'actual-mtu=(\d+)', line)
                    if m:
                        current["mtu"] = int(m.group(1))

        if current:
            interfaces.append(current)
        return interfaces

    def _parse_neighbors(self, output: str) -> list[dict]:
        neighbors = []
        current: Optional[dict] = None

        for line in output.splitlines():
            line = line.strip()
            if line.startswith("0 ") or re.match(r'^\d+\s+', line):
                if current:
                    neighbors.append(current)
                current = {"protocol": "mikrotik_neighbor"}
            if current:
                if "interface=" in line:
                    m = re.search(r'interface=(\S+)', line)
                    if m:
                        current["local_port"] = m.group(1)
                if "address=" in line:
                    m = re.search(r'address=(\S+)', line)
                    if m:
                        current["remote_ip"] = m.group(1)
                if "identity=" in line:
                    m = re.search(r'identity="?([^"]+)"?', line)
                    if m:
                        current["remote_hostname"] = m.group(1)

        if current:
            neighbors.append(current)
        return neighbors
