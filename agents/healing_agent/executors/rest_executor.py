"""
REST executor — calls device REST APIs (Fortinet, Palo Alto, Ubiquiti, etc.)
"""
import logging

import httpx

logger = logging.getLogger(__name__)


class RESTExecutor:
    async def execute(self, step: dict, state: dict) -> str:
        url = step.get("url")
        method = step.get("method", "POST").upper()
        headers = step.get("headers", {})
        body = step.get("body", {})
        expected_status = step.get("expected_status", 200)

        if not url:
            raise ValueError("REST executor requires 'url' in step config")

        logger.info(f"REST {method} {url}")

        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            resp = await client.request(method, url, json=body, headers=headers)

        if resp.status_code != expected_status:
            raise RuntimeError(
                f"REST call failed: {resp.status_code} {resp.text[:200]}"
            )

        return resp.text
