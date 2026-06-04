from abc import ABC, abstractmethod


class BaseNetworkDriver(ABC):
    """Abstract base for all vendor network device drivers."""

    def __init__(self, device_config: dict):
        self.host = device_config["ip_address"]
        self.hostname = device_config.get("hostname", self.host)
        self.vendor = device_config.get("vendor", "unknown")
        self.model = device_config.get("model")
        self.ssh_config = device_config.get("ssh_config", {})
        self.snmp_config = device_config.get("snmp_config", {})

    @abstractmethod
    async def get_running_config(self) -> str:
        """Retrieve the current running configuration."""
        ...

    @abstractmethod
    async def execute_command(self, command: str) -> str:
        """Execute a CLI command and return output."""
        ...

    async def get_startup_config(self) -> str:
        return await self.execute_command("show startup-config")

    async def get_interfaces(self) -> list[dict]:
        output = await self.execute_command("show interfaces")
        return [{"raw": output}]

    async def get_routing_table(self) -> str:
        return await self.execute_command("show ip route")

    async def get_arp_table(self) -> str:
        return await self.execute_command("show arp")

    async def get_lldp_neighbors(self) -> list[dict]:
        return []

    async def get_cdp_neighbors(self) -> list[dict]:
        return []

    def _get_credentials(self) -> dict:
        """Get credentials from vault reference or direct config."""
        cfg = self.ssh_config or {}
        if "vault_secret_path" in cfg:
            from backend.core.vault_client import vault
            return vault.get_ssh_credentials(self.hostname)
        return {
            "username": cfg.get("username", "admin"),
            "password": cfg.get("password", ""),
            "port": cfg.get("port", 22),
        }
