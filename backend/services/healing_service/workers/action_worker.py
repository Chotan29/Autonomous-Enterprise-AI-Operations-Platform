"""
Kafka consumer worker that processes healing task messages.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from backend.core.database import get_db_context
from backend.shared.models.healing import HealingAction

logger = logging.getLogger(__name__)


class ActionWorker:
    async def handle_message(self, topic: str, message: dict) -> None:
        msg_type = message.get("type")
        try:
            if msg_type == "create_action":
                await self._create_action(message)
            elif msg_type == "execute_now":
                await self._execute_action(message)
            elif msg_type == "run_noc_agent":
                await self._run_noc_agent(message)
        except Exception as exc:
            logger.error(f"ActionWorker error type={msg_type}: {exc}")

    async def _create_action(self, message: dict) -> None:
        action_data = message.get("action", {})
        tenant_id = message.get("tenant_id")
        if not tenant_id or not action_data:
            return

        async with get_db_context() as db:
            action = HealingAction(
                tenant_id=uuid.UUID(tenant_id),
                alert_id=uuid.UUID(action_data["alert_id"]) if action_data.get("alert_id") else None,
                action_type=action_data.get("action_type", "unknown"),
                executor_type=action_data.get("executor_type", "ssh"),
                target_device_id=uuid.UUID(action_data["target_device_id"]) if action_data.get("target_device_id") else None,
                parameters=action_data.get("parameters", {}),
                ai_reasoning=action_data.get("ai_reasoning"),
                risk_level=action_data.get("risk_level", "medium"),
                requires_approval=action_data.get("requires_approval", True),
                status="pending",
            )
            db.add(action)
            await db.commit()
            logger.info(f"Healing action created: {action.action_type} risk={action.risk_level}")

    async def _execute_action(self, message: dict) -> None:
        """Execute a healing action via the NOC agent."""
        from agents.healing_agent.graph import healing_graph

        action_id = message.get("action_id", str(uuid.uuid4()))
        tenant_id = message.get("tenant_id", "")
        solution = message.get("solution", {})
        alert_id = message.get("alert_id", "")

        initial_state = {
            "action_id": action_id,
            "tenant_id": tenant_id,
            "trigger_type": "alert",
            "trigger_id": alert_id,
            "alert_data": message.get("alert_data", {}),
            "diagnosis": {"recommended_action": solution.get("action_type", ""), "confidence": 0.9},
            "root_cause": "",
            "confidence": 0.9,
            "playbook_id": None,
            "playbook_name": solution.get("name", ""),
            "playbook_steps": [
                {
                    "name": f"Execute: {cmd}",
                    "executor_type": solution.get("executor_type", "ssh"),
                    "command": cmd,
                    "target_host": message.get("device_info", {}).get("ip_address"),
                }
                for cmd in solution.get("commands", [])
            ],
            "current_step_index": 0,
            "step_results": [],
            "execution_status": "pending",
            "requires_approval": False,
            "risk_level": solution.get("risk_level", "low"),
            "approval_status": "auto_approved",
            "rollback_available": False,
            "rollback_triggered": False,
            "final_status": "",
            "summary": "",
            "messages": [],
        }

        await healing_graph.ainvoke(initial_state)

    async def _run_noc_agent(self, message: dict) -> None:
        """Run the NOC LangGraph agent for RCA."""
        from agents.noc_agent.graph import noc_graph

        alert_id = message.get("alert_id")
        tenant_id = message.get("tenant_id")
        if not alert_id or not tenant_id:
            return

        initial_state = {
            "alert_id": alert_id,
            "tenant_id": tenant_id,
            "alert_data": {},
            "device_info": {},
            "interface_data": [],
            "recent_metrics": {},
            "similar_incidents": [],
            "rag_context": [],
            "rca_result": {},
            "rca_confidence": 0.0,
            "solution_options": [],
            "selected_solution": {},
            "risk_level": "medium",
            "requires_approval": True,
            "approval_status": "pending",
            "execution_result": {},
            "verification_status": "",
            "final_summary": "",
            "messages": [],
        }

        result = await noc_graph.ainvoke(initial_state)
        logger.info(f"NOC agent complete: {result.get('final_summary', '')[:100]}")
