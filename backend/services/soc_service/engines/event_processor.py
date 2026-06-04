"""
SOC event processor — consumes Kafka events, correlates, creates alerts/incidents.
"""
import logging
from datetime import datetime, timezone

from backend.core.database import get_db_context
from backend.core.kafka_client import Topics, publish
from backend.shared.models.alert import Alert

logger = logging.getLogger(__name__)

# Detection rules (simplified — production would use Elasticsearch DSL + ML)
DETECTION_RULES = [
    {
        "id": "SOC-001",
        "name": "Brute Force Login",
        "alert_type": "brute_force_login",
        "severity": "high",
        "mitre_tactic": "TA0006",
        "mitre_technique": "T1110",
        "match": lambda e: (
            e.get("event_id") in (4625,) and
            e.get("event_type") == "auth_failure"
        ),
    },
    {
        "id": "SOC-002",
        "name": "Lateral Movement — NTLM",
        "alert_type": "lateral_movement_ntlm",
        "severity": "critical",
        "mitre_tactic": "TA0008",
        "mitre_technique": "T1550.002",
        "match": lambda e: (
            e.get("auth_package") == "NTLM" and
            e.get("logon_type") == 3 and
            e.get("event_id") == 4624
        ),
    },
    {
        "id": "SOC-003",
        "name": "Large Outbound Data Transfer",
        "alert_type": "data_exfiltration_attempt",
        "severity": "critical",
        "mitre_tactic": "TA0010",
        "mitre_technique": "T1048",
        "match": lambda e: (
            e.get("direction") == "outbound" and
            e.get("bytes_total", 0) > 500_000_000  # 500MB
        ),
    },
    {
        "id": "SOC-005",
        "name": "Ransomware — Mass File Modification",
        "alert_type": "ransomware_indicator",
        "severity": "critical",
        "mitre_tactic": "TA0040",
        "mitre_technique": "T1486",
        "match": lambda e: (
            e.get("event_type") == "file_access" and
            e.get("bulk_operations", 0) > 100
        ),
        "auto_response": "isolate_host",
    },
]


class EventProcessor:
    async def handle_event(self, topic: str, event: dict) -> None:
        try:
            event_type = event.get("type")

            if topic == Topics.ALERTS_RAW and event_type == "create_alert":
                await self._create_alert(event.get("tenant_id"), event.get("alert", {}))

            elif topic == Topics.ALERTS_RAW and event_type == "resolve_alert":
                await self._resolve_alerts(
                    event.get("tenant_id"),
                    event.get("source_device_id"),
                    event.get("alert_type"),
                )

            elif topic == Topics.SIEM_EVENTS:
                await self._process_siem_event(event)

        except Exception as exc:
            logger.error(f"Event processor error topic={topic}: {exc}")

    async def _create_alert(self, tenant_id: str, alert_data: dict) -> None:
        if not tenant_id or not alert_data:
            return

        import uuid
        async with get_db_context() as db:
            alert = Alert(
                tenant_id=uuid.UUID(tenant_id),
                source=alert_data.get("source", "system"),
                source_device_id=uuid.UUID(alert_data["source_device_id"]) if alert_data.get("source_device_id") else None,
                source_host=alert_data.get("source_host"),
                alert_type=alert_data.get("alert_type", "unknown"),
                category=alert_data.get("category", "noc"),
                severity=alert_data.get("severity", "medium"),
                title=alert_data.get("title", "Untitled Alert"),
                description=alert_data.get("description"),
                raw_event=alert_data.get("raw_event"),
                status="new",
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)

            # Trigger AI enrichment for high/critical alerts
            if alert.severity in ("critical", "high"):
                await publish(Topics.NOC_TASKS, {
                    "type": "enrich_alert",
                    "tenant_id": tenant_id,
                    "alert_id": str(alert.id),
                    "alert_data": alert_data,
                })

            logger.info(f"Alert created: {alert.alert_type} severity={alert.severity}")

    async def _resolve_alerts(self, tenant_id: str, device_id: str, alert_type: str) -> None:
        if not tenant_id:
            return
        import uuid
        from sqlalchemy import select, update
        from backend.shared.models.alert import Alert
        async with get_db_context() as db:
            stmt = (
                update(Alert)
                .where(
                    Alert.tenant_id == uuid.UUID(tenant_id),
                    Alert.source_device_id == uuid.UUID(device_id) if device_id else True,
                    Alert.alert_type == alert_type,
                    Alert.status.in_(["new", "acknowledged"]),
                )
                .values(
                    status="resolved",
                    resolved_at=datetime.now(timezone.utc),
                    is_ai_resolved=True,
                )
            )
            await db.execute(stmt)
            await db.commit()

    async def _process_siem_event(self, event: dict) -> None:
        """Apply detection rules to SIEM events."""
        for rule in DETECTION_RULES:
            try:
                if rule["match"](event):
                    await self._create_alert(
                        event.get("tenant_id"),
                        {
                            "source": "siem",
                            "alert_type": rule["alert_type"],
                            "category": "soc",
                            "severity": rule["severity"],
                            "title": f"[{rule['id']}] {rule['name']}",
                            "description": f"MITRE: {rule['mitre_tactic']} / {rule['mitre_technique']}",
                            "raw_event": event,
                        },
                    )
            except Exception:
                pass
