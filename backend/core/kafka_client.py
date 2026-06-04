import json
import logging
from typing import Any, Callable, Awaitable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from backend.core.config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


# ── Kafka Topics ──────────────────────────────────────────────────────────────

class Topics:
    ALERTS_RAW = "aeaop.alerts.raw"
    ALERTS_ENRICHED = "aeaop.alerts.enriched"
    NOC_TASKS = "aeaop.agents.noc.tasks"
    SOC_TASKS = "aeaop.agents.soc.tasks"
    HEALING_TASKS = "aeaop.agents.healing.tasks"
    ACTIONS_APPROVED = "aeaop.actions.approved"
    ACTIONS_EXECUTED = "aeaop.actions.executed"
    REPORTS_SCHEDULED = "aeaop.reports.scheduled"
    PHYSEC_EVENTS = "aeaop.physec.events"
    METRICS_RAW = "aeaop.metrics.raw"
    DEVICE_EVENTS = "aeaop.devices.events"
    SIEM_EVENTS = "aeaop.siem.events"


# ── Producer ─────────────────────────────────────────────────────────────────

async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_servers_list,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            compression_type="gzip",
            acks="all",
            enable_idempotence=True,
        )
        await _producer.start()
    return _producer


async def publish(topic: str, value: dict[str, Any], key: str | None = None) -> None:
    try:
        producer = await get_producer()
        await producer.send_and_wait(topic, value=value, key=key)
    except Exception as exc:
        logger.error(f"Kafka publish failed topic={topic}: {exc}")
        raise


async def close_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None


# ── Consumer Factory ──────────────────────────────────────────────────────────

def make_consumer(topics: list[str], group_id: str | None = None) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_servers_list,
        group_id=group_id or settings.KAFKA_CONSUMER_GROUP,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="latest",
        enable_auto_commit=True,
        auto_commit_interval_ms=1000,
    )


async def consume_forever(
    topics: list[str],
    handler: Callable[[str, dict], Awaitable[None]],
    group_id: str | None = None,
) -> None:
    """Run a consumer loop. Call this in a background task."""
    consumer = make_consumer(topics, group_id)
    await consumer.start()
    try:
        async for msg in consumer:
            try:
                await handler(msg.topic, msg.value)
            except Exception as exc:
                logger.error(f"Consumer handler error topic={msg.topic}: {exc}")
    finally:
        await consumer.stop()
