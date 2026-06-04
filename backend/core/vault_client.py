import logging
from typing import Any

import hvac

from backend.core.config import settings

logger = logging.getLogger(__name__)


class VaultClient:
    """HashiCorp Vault client for secrets management."""

    def __init__(self):
        self._client: hvac.Client | None = None

    @property
    def client(self) -> hvac.Client:
        if self._client is None or not self._client.is_authenticated():
            self._client = hvac.Client(url=settings.VAULT_ADDR)
            if settings.VAULT_TOKEN:
                self._client.token = settings.VAULT_TOKEN
            else:
                # Kubernetes auth for production
                with open("/var/run/secrets/vault/vault-token") as f:
                    jwt_token = f.read().strip()
                self._client.auth.kubernetes.login(
                    role=settings.VAULT_ROLE,
                    jwt=jwt_token,
                )
        return self._client

    def get_secret(self, path: str, key: str | None = None) -> Any:
        """Read a KV v2 secret."""
        try:
            secret = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=settings.VAULT_MOUNT_KV,
            )
            data: dict = secret["data"]["data"]
            return data.get(key) if key else data
        except Exception as exc:
            logger.error(f"Vault read failed path={path}: {exc}")
            raise

    def get_ssh_credentials(self, device_hostname: str) -> dict:
        """Get SSH credentials for a network device."""
        path = f"noc/devices/{device_hostname}/ssh"
        try:
            return self.get_secret(path)
        except Exception:
            # Fall back to default credentials
            return self.get_secret("noc/devices/default/ssh")

    def get_snmp_credentials(self, device_hostname: str) -> dict:
        path = f"noc/devices/{device_hostname}/snmp"
        try:
            return self.get_secret(path)
        except Exception:
            return {"community": settings.SNMP_COMMUNITY, "version": settings.SNMP_VERSION}

    def get_camera_credentials(self, camera_id: str) -> dict:
        return self.get_secret(f"physec/cameras/{camera_id}")

    def write_secret(self, path: str, data: dict) -> None:
        self.client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret=data,
            mount_point=settings.VAULT_MOUNT_KV,
        )

    def delete_secret(self, path: str) -> None:
        self.client.secrets.kv.v2.delete_latest_version_of_secret(
            path=path,
            mount_point=settings.VAULT_MOUNT_KV,
        )


vault = VaultClient()
