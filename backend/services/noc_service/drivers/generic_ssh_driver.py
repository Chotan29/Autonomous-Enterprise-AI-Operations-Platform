"""
Generic SSH driver for unknown/unsupported vendors using Netmiko.
"""
import asyncio
from functools import partial

from netmiko import ConnectHandler

from backend.services.noc_service.drivers.base_driver import BaseNetworkDriver

VENDOR_DEVICE_TYPE: dict[str, str] = {
    "juniper":   "juniper_junos",
    "fortinet":  "fortinet",
    "paloalto":  "paloalto_panos",
    "hp":        "hp_procurve",
    "dell":      "dell_os10",
    "ubiquiti":  "linux",
    "huawei":    "huawei",
    "arista":    "arista_eos",
}


class GenericSSHDriver(BaseNetworkDriver):
    """Netmiko-based generic driver supporting many vendors."""

    def _get_device_type(self) -> str:
        vendor = (self.vendor or "").lower()
        for key, dtype in VENDOR_DEVICE_TYPE.items():
            if key in vendor:
                return dtype
        return "linux"

    async def execute_command(self, command: str) -> str:
        creds = self._get_credentials()
        device_params = {
            "device_type":       self._get_device_type(),
            "host":              self.host,
            "username":          creds["username"],
            "password":          creds.get("password", ""),
            "port":              creds.get("port", 22),
            "timeout":           30,
            "conn_timeout":      15,
            "auth_timeout":      15,
            "global_delay_factor": 1,
        }
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(self._sync_execute, device_params, command)
        )
        return result

    @staticmethod
    def _sync_execute(device_params: dict, command: str) -> str:
        with ConnectHandler(**device_params) as conn:
            output = conn.send_command(command, read_timeout=30)
            return output

    async def get_running_config(self) -> str:
        vendor = (self.vendor or "").lower()
        cmd_map = {
            "juniper":   "show configuration | display set",
            "fortinet":  "show full-configuration",
            "paloalto":  "show config running",
            "hp":        "show running-config",
            "dell":      "show running-configuration",
            "ubiquiti":  "mca-ctrl -t dump-cfg",
            "huawei":    "display current-configuration",
        }
        for key, cmd in cmd_map.items():
            if key in vendor:
                return await self.execute_command(cmd)
        return await self.execute_command("show running-config")

    async def get_lldp_neighbors(self) -> list[dict]:
        vendor = (self.vendor or "").lower()
        cmd_map = {
            "juniper":  "show lldp neighbors",
            "hp":       "show lldp remote-device",
            "huawei":   "display lldp neighbor",
        }
        for key, cmd in cmd_map.items():
            if key in vendor:
                try:
                    output = await self.execute_command(cmd)
                    return [{"raw": output, "protocol": "lldp"}]
                except Exception:
                    return []
        return []
