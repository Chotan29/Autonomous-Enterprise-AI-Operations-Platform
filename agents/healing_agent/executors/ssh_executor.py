"""
SSH executor for healing actions on Linux/Unix servers and network devices.
"""
import asyncio
import logging

import asyncssh

from backend.core.vault_client import vault

logger = logging.getLogger(__name__)


class SSHExecutor:
    async def execute(self, step: dict, state: dict) -> str:
        """Execute a command on a remote host via SSH."""
        host = step.get("target_host") or state.get("alert_data", {}).get("source_host")
        command = step.get("command")

        if not host or not command:
            raise ValueError(f"SSH executor missing host={host} or command")

        # Get credentials
        creds = vault.get_ssh_credentials(host)

        logger.info(f"SSH exec host={host} cmd={command[:80]}...")

        async with await asyncssh.connect(
            host,
            port=creds.get("port", 22),
            username=creds["username"],
            password=creds.get("password"),
            known_hosts=None,
            connect_timeout=15,
        ) as conn:
            result = await conn.run(command, timeout=60)

        output = result.stdout
        exit_code = result.exit_status

        # Check expected output if defined
        expected = step.get("expected_output")
        if expected and expected not in output:
            raise RuntimeError(
                f"Command output does not match expected. "
                f"Expected: '{expected}' Got: '{output[:200]}'"
            )

        if exit_code != 0 and not step.get("ignore_failure"):
            raise RuntimeError(f"SSH command failed (exit {exit_code}): {result.stderr[:200]}")

        return output
