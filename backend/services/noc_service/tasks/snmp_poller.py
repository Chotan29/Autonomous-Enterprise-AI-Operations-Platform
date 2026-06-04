"""
Background SNMP poller — runs forever, polls all managed devices on schedule.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import get_db_context
from backend.core.kafka_client import Topics, publish
from backend.core.redis_client import device_cache
from backend.shared.models.device import Device, DeviceInterface
from backend.services.noc_service.collectors.snmp_collector import SNMPCollector

logger = logging.getLogger(__name__)


class SNMPPoller:
    def __init__(self):
        self.collector = SNMPCollector()
        self.interval = settings.SNMP_POLL_INTERVAL_SECONDS
        self._semaphore = asyncio.Semaphore(50)  # max 50 concurrent polls

    async def run_forever(self) -> None:
        logger.info(f"SNMP poller started (interval={self.interval}s)")
        while True:
            try:
                await self._poll_all_devices()
            except Exception as exc:
                logger.error(f"SNMP poller cycle error: {exc}")
            await asyncio.sleep(self.interval)

    async def _poll_all_devices(self) -> None:
        async with get_db_context() as db:
            result = await db.execute(
                select(Device).where(Device.is_managed == True)
            )
            devices = result.scalars().all()

        if not devices:
            return

        logger.info(f"Polling {len(devices)} devices...")
        tasks = [self._poll_device(d) for d in devices]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_device(self, device: Device) -> None:
        async with self._semaphore:
            try:
                result = await self.collector.full_poll(
                    host=device.ip_address,
                    device={
                        "vendor": device.vendor,
                        "snmp_version": device.snmp_version,
                        "snmp_community": device.snmp_community,
                        "snmp_config": device.snmp_config,
                    },
                )
                await self._save_poll_result(device, result)
            except Exception as exc:
                logger.debug(f"Poll failed {device.hostname}: {exc}")
                await self._mark_device_offline(device)

    async def _save_poll_result(self, device: Device, result: dict) -> None:
        now = datetime.now(timezone.utc)
        async with get_db_context() as db:
            db_device = await db.get(Device, device.id)
            if not db_device:
                return

            if not result["success"]:
                db_device.status = "offline"
                db_device.last_poll = now
                await db.commit()
                await self._emit_alert_if_needed(device, was_online=True, is_online=False)
                return

            sys = result.get("system", {})
            perf = result.get("performance", {})
            prev_status = db_device.status

            db_device.status = "online"
            db_device.last_seen = now
            db_device.last_poll = now
            db_device.uptime_seconds = sys.get("uptime_seconds")
            db_device.os_version = sys.get("sysDescr", db_device.os_version)
            db_device.last_cpu_util = perf.get("cpu_util")

            # Update interfaces
            interfaces_data = result.get("interfaces", [])
            await self._update_interfaces(db_device.id, interfaces_data, db)

            await db.commit()

            # Publish metrics to Kafka for TimescaleDB ingestion
            if perf.get("cpu_util") is not None:
                await publish(Topics.METRICS_RAW, {
                    "type": "device_metric",
                    "tenant_id": str(device.tenant_id),
                    "device_id": str(device.id),
                    "hostname": device.hostname,
                    "timestamp": now.isoformat(),
                    "metrics": {
                        "cpu_util": perf.get("cpu_util"),
                        "mem_util": perf.get("mem_util"),
                        "uptime_seconds": sys.get("uptime_seconds"),
                    },
                    "interfaces": interfaces_data[:20],  # top 20 interfaces
                })

            # Device came back online
            if prev_status == "offline":
                await self._emit_alert_resolved(device)

            # High CPU alert
            cpu = perf.get("cpu_util")
            if cpu and cpu > 90:
                await self._emit_high_cpu_alert(device, cpu)

    async def _update_interfaces(
        self, device_id, interfaces_data: list[dict], db
    ) -> None:
        from sqlalchemy import delete
        existing_result = await db.execute(
            select(DeviceInterface).where(DeviceInterface.device_id == device_id)
        )
        existing = {i.if_index: i for i in existing_result.scalars().all()}
        now = datetime.now(timezone.utc)

        for iface_data in interfaces_data:
            idx = iface_data.get("if_index")
            if idx is None:
                continue
            if idx in existing:
                iface = existing[idx]
                for field in ("if_name", "admin_status", "oper_status", "in_octets", "out_octets", "in_errors", "out_errors", "speed_bps"):
                    if field in iface_data:
                        setattr(iface, field, iface_data[field])
                iface.last_updated = now
            else:
                new_iface = DeviceInterface(
                    device_id=device_id,
                    if_index=idx,
                    if_name=iface_data.get("if_name"),
                    if_type=iface_data.get("if_type"),
                    speed_bps=iface_data.get("speed_bps"),
                    admin_status=iface_data.get("admin_status"),
                    oper_status=iface_data.get("oper_status"),
                    in_octets=iface_data.get("in_octets"),
                    out_octets=iface_data.get("out_octets"),
                    in_errors=iface_data.get("in_errors"),
                    out_errors=iface_data.get("out_errors"),
                    last_updated=now,
                )
                db.add(new_iface)

    async def _mark_device_offline(self, device: Device) -> None:
        async with get_db_context() as db:
            db_device = await db.get(Device, device.id)
            if db_device and db_device.status != "offline":
                db_device.status = "offline"
                db_device.last_poll = datetime.now(timezone.utc)
                await db.commit()
                await self._emit_alert_if_needed(device, was_online=True, is_online=False)

    async def _emit_alert_if_needed(self, device: Device, was_online: bool, is_online: bool) -> None:
        if was_online and not is_online:
            await publish(Topics.ALERTS_RAW, {
                "type": "create_alert",
                "tenant_id": str(device.tenant_id),
                "alert": {
                    "source": "snmp_poller",
                    "source_device_id": str(device.id),
                    "source_host": device.hostname,
                    "alert_type": "device_unreachable",
                    "category": "noc",
                    "severity": "critical",
                    "title": f"Device Unreachable: {device.hostname}",
                    "description": f"SNMP polling failed for {device.hostname} ({device.ip_address}). Device appears offline.",
                },
            })

    async def _emit_alert_resolved(self, device: Device) -> None:
        await publish(Topics.ALERTS_RAW, {
            "type": "resolve_alert",
            "tenant_id": str(device.tenant_id),
            "source_device_id": str(device.id),
            "alert_type": "device_unreachable",
        })

    async def _emit_high_cpu_alert(self, device: Device, cpu: float) -> None:
        await publish(Topics.ALERTS_RAW, {
            "type": "create_alert",
            "tenant_id": str(device.tenant_id),
            "alert": {
                "source": "snmp_poller",
                "source_device_id": str(device.id),
                "source_host": device.hostname,
                "alert_type": "high_cpu",
                "category": "noc",
                "severity": "high" if cpu > 95 else "medium",
                "title": f"High CPU: {device.hostname} ({cpu:.1f}%)",
                "description": f"CPU utilization is {cpu:.1f}% on {device.hostname} ({device.ip_address})",
                "raw_event": {"cpu_util": cpu},
            },
        })
