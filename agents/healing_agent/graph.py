"""
Self-Healing Agent — LangGraph workflow for autonomous infrastructure remediation.

Workflow:
  intake → diagnosis → playbook_select → pre_check → approval_gate
       → execute_step → verify_step → [loop or post_verify or rollback]
       → report → END
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Literal

from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage

from agents.healing_agent.state import HealingState
from agents.healing_agent.executors.executor_factory import get_executor
from backend.core.config import settings
from backend.core.database import get_db_context
from backend.core.kafka_client import Topics, publish
from backend.services.ai_service.llm.model_router import llm
from backend.shared.models.healing import HealingAction, Playbook

logger = logging.getLogger(__name__)

# ── Low-risk action types that execute without human approval ─────────────────
AUTO_APPROVE_ACTIONS = {
    "restart_service",
    "clear_temp_files",
    "clear_old_logs",
    "send_notification",
    "update_monitoring_threshold",
    "ping_check",
    "dns_flush",
}

ALWAYS_REQUIRE_APPROVAL = {
    "reboot_device",
    "reboot_server",
    "rollback_config",
    "firmware_upgrade",
    "shutdown_interface",
    "modify_firewall_policy",
    "delete_file",
    "change_routing",
    "isolate_host",
    "reset_credentials",
}


# ── Node implementations ──────────────────────────────────────────────────────

async def intake_node(state: HealingState) -> HealingState:
    """Load full alert/incident context."""
    logger.info(f"Healing intake: action_id={state['action_id']}")
    return state


async def diagnosis_node(state: HealingState) -> HealingState:
    """AI diagnosis: understand the problem from alert data."""
    alert = state.get("alert_data", {})

    prompt = f"""Analyze this infrastructure alert and diagnose the root cause.

ALERT DATA:
{json.dumps(alert, indent=2, default=str)}

Provide diagnosis as JSON:
{{
  "root_cause": "specific technical explanation",
  "component_affected": "service/device/process name",
  "severity_assessment": "critical|high|medium|low",
  "confidence": 0.85,
  "recommended_action": "restart_service|clear_disk|reboot_device|rollback_config|etc",
  "action_parameters": {{}},
  "safe_to_automate": true|false,
  "additional_checks_needed": []
}}"""

    response = await llm.generate(prompt=prompt, temperature=0.05)

    try:
        json_match = __import__("re").search(r'\{.*\}', response.content, __import__("re").DOTALL)
        diagnosis = json.loads(json_match.group()) if json_match else {}
    except Exception:
        diagnosis = {
            "root_cause": response.content,
            "confidence": 0.5,
            "recommended_action": "manual_intervention",
            "safe_to_automate": False,
        }

    return {
        **state,
        "diagnosis": diagnosis,
        "root_cause": diagnosis.get("root_cause", "Unknown"),
        "confidence": diagnosis.get("confidence", 0.5),
        "messages": [AIMessage(content=f"Diagnosis: {diagnosis.get('root_cause', 'Unknown')}")],
    }


async def playbook_select_node(state: HealingState) -> HealingState:
    """Select the best playbook for this diagnosis."""
    diagnosis = state.get("diagnosis", {})
    recommended_action = diagnosis.get("recommended_action", "")

    async with get_db_context() as db:
        from sqlalchemy import select as sqlselect
        import uuid
        result = await db.execute(
            sqlselect(Playbook).where(
                Playbook.tenant_id == uuid.UUID(state["tenant_id"]),
                Playbook.is_active == True,
            )
        )
        playbooks = result.scalars().all()

    # Simple matching: find playbook where trigger_conditions match action type
    selected = None
    for pb in playbooks:
        conditions = pb.trigger_conditions or {}
        if recommended_action in (conditions.get("action_types", []) or []):
            selected = pb
            break

    if selected:
        return {
            **state,
            "playbook_id": str(selected.id),
            "playbook_name": selected.name,
            "playbook_steps": selected.steps,
            "risk_level": selected.risk_level,
            "requires_approval": not selected.is_autonomous,
            "current_step_index": 0,
        }

    # No playbook found — use dynamic steps from diagnosis
    action_params = diagnosis.get("action_parameters", {})
    dynamic_steps = _build_dynamic_steps(recommended_action, action_params, state)

    return {
        **state,
        "playbook_id": None,
        "playbook_name": f"Dynamic: {recommended_action}",
        "playbook_steps": dynamic_steps,
        "risk_level": _assess_risk(recommended_action),
        "requires_approval": recommended_action not in AUTO_APPROVE_ACTIONS,
        "current_step_index": 0,
    }


async def pre_check_node(state: HealingState) -> HealingState:
    """Verify conditions are still valid before executing."""
    # Check alert is still active
    alert_id = state.get("trigger_id")
    if state.get("trigger_type") == "alert" and alert_id:
        async with get_db_context() as db:
            from sqlalchemy import select as sqlselect
            import uuid
            from backend.shared.models.alert import Alert
            result = await db.execute(
                sqlselect(Alert.status).where(Alert.id == uuid.UUID(alert_id))
            )
            alert_status = result.scalar_one_or_none()
            if alert_status in ("resolved", "suppressed"):
                return {
                    **state,
                    "execution_status": "cancelled",
                    "final_status": "cancelled",
                    "summary": "Alert was resolved before healing could execute",
                }

    return {**state, "execution_status": "pre_check_passed"}


async def approval_gate_node(state: HealingState) -> HealingState:
    """
    Check if this action has been approved.
    In production: waits for human approval via webhook/API.
    For auto-approvable: proceeds immediately.
    """
    action_type = state.get("diagnosis", {}).get("recommended_action", "")
    risk_level = state.get("risk_level", "medium")

    # Auto-approve if action is low-risk and in approved list
    if action_type in AUTO_APPROVE_ACTIONS and risk_level == "low":
        return {
            **state,
            "approval_status": "auto_approved",
            "messages": [AIMessage(content=f"Auto-approved: {action_type} (low risk)")],
        }

    # Check if already approved in database
    action_id = state.get("action_id")
    if action_id:
        async with get_db_context() as db:
            from sqlalchemy import select as sqlselect
            import uuid
            result = await db.execute(
                sqlselect(HealingAction.status).where(HealingAction.id == uuid.UUID(action_id))
            )
            db_status = result.scalar_one_or_none()
            if db_status == "approved":
                return {**state, "approval_status": "approved"}
            elif db_status == "rejected":
                return {
                    **state,
                    "approval_status": "rejected",
                    "final_status": "rejected",
                }

    # Still pending approval
    return {**state, "approval_status": "pending"}


async def execute_step_node(state: HealingState) -> HealingState:
    """Execute the current playbook step."""
    steps = state.get("playbook_steps", [])
    idx = state.get("current_step_index", 0)

    if idx >= len(steps):
        return {**state, "execution_status": "all_steps_complete"}

    step = steps[idx]
    logger.info(f"Executing step {idx + 1}/{len(steps)}: {step.get('name', step.get('type'))}")

    # Update DB status
    await _update_action_status(state.get("action_id"), "running")

    try:
        executor = get_executor(step.get("executor_type", "ssh"))
        result = await executor.execute(step, state)
        step_result = {
            "step_index": idx,
            "step_name": step.get("name"),
            "status": "success",
            "output": str(result)[:2000],
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"Step {idx} failed: {exc}")
        step_result = {
            "step_index": idx,
            "step_name": step.get("name"),
            "status": "failed",
            "error": str(exc),
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            **state,
            "step_results": state.get("step_results", []) + [step_result],
            "execution_status": "step_failed",
        }

    return {
        **state,
        "step_results": state.get("step_results", []) + [step_result],
        "current_step_index": idx + 1,
        "execution_status": "step_success",
    }


async def verify_step_node(state: HealingState) -> HealingState:
    """Check result of last step; decide continue/done/rollback."""
    if state.get("execution_status") == "step_failed":
        return {**state, "execution_status": "needs_rollback"}

    steps = state.get("playbook_steps", [])
    next_idx = state.get("current_step_index", 0)

    if next_idx >= len(steps):
        return {**state, "execution_status": "all_complete"}

    return {**state, "execution_status": "continue"}


async def post_verify_node(state: HealingState) -> HealingState:
    """Final verification that the remediation worked."""
    alert_id = state.get("trigger_id")
    if state.get("trigger_type") == "alert" and alert_id:
        # Check if the original alert auto-resolved
        await asyncio.sleep(5)  # Wait for monitoring to catch up
        async with get_db_context() as db:
            from sqlalchemy import select as sqlselect
            import uuid
            from backend.shared.models.alert import Alert
            result = await db.execute(
                sqlselect(Alert.status).where(Alert.id == uuid.UUID(alert_id))
            )
            status = result.scalar_one_or_none()
            if status == "resolved":
                return {
                    **state,
                    "final_status": "success",
                    "summary": "Remediation successful — alert auto-resolved",
                }

    return {
        **state,
        "final_status": "success",
        "summary": f"Remediation completed: {state.get('playbook_name')}",
    }


async def rollback_node(state: HealingState) -> HealingState:
    """Execute rollback steps on failure."""
    logger.warning(f"Rolling back action_id={state.get('action_id')}")
    playbook_steps = state.get("playbook_steps", [])
    rollback_steps = [s for s in playbook_steps if s.get("is_rollback")]

    rollback_results = []
    for step in rollback_steps:
        try:
            executor = get_executor(step.get("executor_type", "ssh"))
            result = await executor.execute(step, state)
            rollback_results.append({"step": step.get("name"), "status": "success"})
        except Exception as exc:
            rollback_results.append({"step": step.get("name"), "status": "failed", "error": str(exc)})

    return {
        **state,
        "rollback_triggered": True,
        "final_status": "rolled_back",
        "summary": f"Action failed and rolled back. Results: {rollback_results}",
    }


async def report_node(state: HealingState) -> HealingState:
    """Update database and emit completion event."""
    action_id = state.get("action_id")
    final_status = state.get("final_status", "unknown")

    if action_id:
        await _update_action_status(action_id, final_status)

    await publish(Topics.ACTIONS_EXECUTED, {
        "type": "healing_complete",
        "tenant_id": state["tenant_id"],
        "action_id": action_id,
        "final_status": final_status,
        "summary": state.get("summary", ""),
        "step_results": state.get("step_results", []),
    })

    logger.info(f"Healing complete: action_id={action_id} status={final_status}")
    return state


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_pre_check(state: HealingState) -> Literal["approval_gate", "execute_step", "report"]:
    status = state.get("execution_status")
    if status == "cancelled":
        return "report"
    requires = state.get("requires_approval", True)
    return "approval_gate" if requires else "execute_step"


def route_after_approval(state: HealingState) -> Literal["execute_step", "report"]:
    status = state.get("approval_status")
    if status in ("approved", "auto_approved"):
        return "execute_step"
    return "report"  # rejected or pending


def route_after_verify(state: HealingState) -> Literal["execute_step", "post_verify", "rollback"]:
    status = state.get("execution_status")
    if status == "needs_rollback":
        return "rollback"
    if status == "all_complete":
        return "post_verify"
    return "execute_step"  # continue


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_healing_graph():
    graph = StateGraph(HealingState)

    graph.add_node("intake",          intake_node)
    graph.add_node("diagnosis",       diagnosis_node)
    graph.add_node("playbook_select", playbook_select_node)
    graph.add_node("pre_check",       pre_check_node)
    graph.add_node("approval_gate",   approval_gate_node)
    graph.add_node("execute_step",    execute_step_node)
    graph.add_node("verify_step",     verify_step_node)
    graph.add_node("post_verify",     post_verify_node)
    graph.add_node("rollback",        rollback_node)
    graph.add_node("report",          report_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake",          "diagnosis")
    graph.add_edge("diagnosis",       "playbook_select")
    graph.add_edge("playbook_select", "pre_check")

    graph.add_conditional_edges("pre_check", route_after_pre_check, {
        "approval_gate": "approval_gate",
        "execute_step":  "execute_step",
        "report":        "report",
    })

    graph.add_conditional_edges("approval_gate", route_after_approval, {
        "execute_step": "execute_step",
        "report":       "report",
    })

    graph.add_edge("execute_step",    "verify_step")

    graph.add_conditional_edges("verify_step", route_after_verify, {
        "execute_step": "execute_step",
        "post_verify":  "post_verify",
        "rollback":     "rollback",
    })

    graph.add_edge("post_verify",     "report")
    graph.add_edge("rollback",        "report")
    graph.add_edge("report",          END)

    return graph.compile()


healing_graph = build_healing_graph()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _update_action_status(action_id: str | None, status: str) -> None:
    if not action_id:
        return
    import uuid
    async with get_db_context() as db:
        action = await db.get(HealingAction, uuid.UUID(action_id))
        if action:
            action.status = status
            if status == "running":
                action.started_at = datetime.now(timezone.utc)
            elif status in ("success", "failed", "rolled_back"):
                action.completed_at = datetime.now(timezone.utc)
            await db.commit()


def _assess_risk(action_type: str) -> str:
    if action_type in AUTO_APPROVE_ACTIONS:
        return "low"
    if action_type in ALWAYS_REQUIRE_APPROVAL:
        return "high"
    return "medium"


def _build_dynamic_steps(action_type: str, params: dict, state: HealingState) -> list[dict]:
    """Build execution steps dynamically when no playbook matches."""
    alert = state.get("alert_data", {})
    device_id = alert.get("source_device_id")
    host = alert.get("source_host")

    if action_type == "restart_service":
        service = params.get("service_name", "unknown")
        return [
            {
                "name": f"Check service status: {service}",
                "executor_type": "ssh",
                "command": f"systemctl status {service}",
                "target_host": host,
            },
            {
                "name": f"Restart service: {service}",
                "executor_type": "ssh",
                "command": f"systemctl restart {service}",
                "target_host": host,
            },
            {
                "name": "Verify service running",
                "executor_type": "ssh",
                "command": f"systemctl is-active {service}",
                "target_host": host,
                "expected_output": "active",
            },
        ]

    if action_type == "clear_disk_space":
        return [
            {
                "name": "Check disk usage",
                "executor_type": "ssh",
                "command": "df -h",
                "target_host": host,
            },
            {
                "name": "Clean old logs",
                "executor_type": "ssh",
                "command": "find /var/log -name '*.gz' -mtime +7 -delete && journalctl --vacuum-time=7d",
                "target_host": host,
            },
        ]

    return [{
        "name": f"Manual: {action_type}",
        "executor_type": "notification",
        "message": f"Automated healing for '{action_type}' requires manual intervention. Params: {params}",
    }]
