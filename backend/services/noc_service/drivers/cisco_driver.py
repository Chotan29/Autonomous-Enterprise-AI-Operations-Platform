"""
Cisco IOS / IOS-XE driver using asyncssh.
"""
import re
from typing import Optional

import asyncssh

from backend.services.noc_service.drivers.base_driver import BaseNetworkDriver


class CiscoDriver(BaseNetworkDriver):
    """Driver for Cisco IOS and IOS-XE devices."""

    async def _connect(self) -> asyncssh.SSHClientConnection:
        creds = self._get_credentials()
        return await asyncssh.connect(
            self.host,
            port=creds.get("port", 22),
            username=creds["username"],
            password=creds.get("password"),
            known_hosts=None,
            connect_timeout=15,
        )

    async def execute_command(self, command: str) -> str:
        async with await self._connect() as conn:
            result = await conn.run(command, timeout=30)
            return result.stdout

    async def get_running_config(self) -> str:
        return await self.execute_command("show running-config")

    async def get_interfaces(self) -> list[dict]:
        output = await self.execute_command("show interfaces")
        return self._parse_interfaces(output)

    async def get_lldp_neighbors(self) -> list[dict]:
        try:
            output = await self.execute_command("show lldp neighbors detail")
            return self._parse_lldp_neighbors(output)
        except Exception:
            return []

    async def get_cdp_neighbors(self) -> list[dict]:
        try:
            output = await self.execute_command("show cdp neighbors detail")
            return self._parse_cdp_neighbors(output)
        except Exception:
            return []

    async def get_routing_table(self) -> str:
        return await self.execute_command("show ip route")

    def _parse_interfaces(self, output: str) -> list[dict]:
        interfaces = []
        current: Optional[dict] = None

        for line in output.splitlines():
            # New interface block
            if_match = re.match(r'^(\S+)\s+is\s+(up|down|administratively down)', line)
            if if_match:
                if current:
                    interfaces.append(current)
                current = {
                    "if_name": if_match.group(1),
                    "oper_status": "up" if if_match.group(2) == "up" else "down",
                    "admin_status": "down" if "administratively" in line else "up",
                }
            elif current:
                # MTU
                mtu_match = re.search(r'MTU (\d+)', line)
                if mtu_match:
                    current["mtu"] = int(mtu_match.group(1))
                # Speed
                speed_match = re.search(r'BW (\d+) Kbit', line)
                if speed_match:
                    current["speed_bps"] = int(speed_match.group(1)) * 1000
                # IP address
                ip_match = re.search(r'Internet address is (\S+)', line)
                if ip_match:
                    current.setdefault("ip_addresses", []).append(ip_match.group(1))
                # In/Out octets
                pkts_match = re.search(r'(\d+) packets input.*?(\d+) bytes', line)
                if pkts_match:
                    current["in_octets"] = int(pkts_match.group(2))
                out_match = re.search(r'(\d+) packets output.*?(\d+) bytes', line)
                if out_match:
                    current["out_octets"] = int(out_match.group(2))

        if current:
            interfaces.append(current)
        return interfaces

    def _parse_lldp_neighbors(self, output: str) -> list[dict]:
        neighbors = []
        current: Optional[dict] = None

        for line in output.splitlines():
            if line.startswith("Local Intf:"):
                if current:
                    neighbors.append(current)
                current = {"protocol": "lldp", "local_port": line.split(":", 1)[1].strip()}
            elif current:
                if "System Name:" in line:
                    current["remote_hostname"] = line.split(":", 1)[1].strip()
                elif "Port id:" in line:
                    current["remote_port"] = line.split(":", 1)[1].strip()
                elif "Management Addresses:" in line:
                    pass
                elif re.match(r'\s+\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', line):
                    current["remote_ip"] = line.strip()

        if current:
            neighbors.append(current)
        return neighbors

    def _parse_cdp_neighbors(self, output: str) -> list[dict]:
        neighbors = []
        current: Optional[dict] = None

        for line in output.splitlines():
            if line.startswith("Device ID:"):
                if current:
                    neighbors.append(current)
                current = {"protocol": "cdp", "remote_hostname": line.split(":", 1)[1].strip()}
            elif current:
                if "Interface:" in line and "Port ID (outgoing port):" in line:
                    parts = line.split(",")
                    for part in parts:
                        if "Interface:" in part:
                            current["local_port"] = part.split(":", 1)[1].strip()
                        elif "Port ID" in part:
                            current["remote_port"] = part.split(":", 1)[1].strip()
                elif "IP address:" in line:
                    current["remote_ip"] = line.split(":", 1)[1].strip()

        if current:
            neighbors.append(current)
        return neighbors
