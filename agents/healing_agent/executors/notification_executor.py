"""
Notification executor — sends alerts via Teams/Slack/email/SMS.
"""
import logging

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)


class NotificationExecutor:
    async def execute(self, step: dict, state: dict) -> str:
        message = step.get("message", "AEAOP Healing Agent notification")
        channels = step.get("channels", ["log"])

        for channel in channels:
            if channel == "log":
                logger.warning(f"[HEALING NOTIFICATION] {message}")

            elif channel == "teams" and hasattr(settings, "TEAMS_WEBHOOK_URL"):
                await self._send_teams(message)

            elif channel == "slack" and hasattr(settings, "SLACK_WEBHOOK_URL"):
                await self._send_slack(message)

        return f"Notification sent: {message[:100]}"

    async def _send_teams(self, message: str) -> None:
        webhook_url = getattr(settings, "TEAMS_WEBHOOK_URL", "")
        if not webhook_url:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json={
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "summary": "AEAOP Alert",
                "text": message,
            })

    async def _send_slack(self, message: str) -> None:
        webhook_url = getattr(settings, "SLACK_WEBHOOK_URL", "")
        if not webhook_url:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json={"text": message})
