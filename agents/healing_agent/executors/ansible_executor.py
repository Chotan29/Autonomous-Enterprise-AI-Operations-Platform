"""
Ansible executor — runs Ansible playbooks for complex multi-step remediation.
"""
import asyncio
import json
import logging
import os
import tempfile

import ansible_runner

logger = logging.getLogger(__name__)


class AnsibleExecutor:
    async def execute(self, step: dict, state: dict) -> str:
        """Run an Ansible playbook from the playbooks directory."""
        playbook = step.get("playbook")
        inventory = step.get("inventory") or self._build_inventory(step, state)
        extra_vars = step.get("extra_vars", {})

        if not playbook:
            raise ValueError("Ansible executor requires 'playbook' in step config")

        playbook_path = os.path.join("agents", "healing_agent", "playbooks", playbook)
        if not os.path.exists(playbook_path):
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        logger.info(f"Running Ansible playbook: {playbook}")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: ansible_runner.run(
                playbook=playbook_path,
                inventory=inventory,
                extravars=extra_vars,
                quiet=False,
            )
        )

        if result.status != "successful":
            raise RuntimeError(f"Ansible playbook failed: {result.status}")

        # Collect stdout from events
        output_lines = []
        for event in result.events:
            if event.get("stdout"):
                output_lines.append(event["stdout"])

        return "\n".join(output_lines[-50:])  # last 50 lines

    def _build_inventory(self, step: dict, state: dict) -> dict:
        alert = state.get("alert_data", {})
        host = step.get("target_host") or alert.get("source_host", "localhost")
        return {
            "all": {
                "hosts": {
                    host: {
                        "ansible_host": host,
                        "ansible_user": "ansible",
                        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
                    }
                }
            }
        }
