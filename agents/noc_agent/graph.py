"""
NOC Agent — LangGraph workflow for AI-powered alert analysis and root cause analysis.

Workflow:
  alert_intake → device_enrichment → rag_query → rca_analysis
              → solution_generation → risk_assessment → [approval_gate | execute_fix]
              → verify_fix → update_incident → END
"""
import json
import logging
import uuid
from typing import Literal, TypedDict, Annotated, Optional

from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage, HumanMessage, add_messages

from backend.core.database import get_db_context
from backend.core.kafka_client import Topics, publish
from backend.services.ai_service.llm.model_router import llm
from backend.services.ai_service.prompts.noc_prompts import NOC_RCA_SYSTEM, NOC_SOLUTION_SYSTEM
from backend.shared.models.device import Device, DeviceInterface
from backend.shared.models.alert import Alert

logger = logging.getLogger(__name__)


class NOCAgentState(TypedDict):
    # Core
    alert_id: str
    tenant_id: str
    alert_data: dict
    # Enrichment
    device_info: dict
    interface_data: list[dict]
    recent_metrics: dict
    # RAG
    similar_incidents: list[dict]
    rag_context: list[dict]
    # Analysis
    rca_result: dict
    rca_confidence: float
    # Solution
    solution_options: list[dict]
    selected_solution: dict
    risk_level: str
    requires_approval: bool
    # Execution
    approval_status: str
    execution_result: dict
    verification_status: str
    # Output
    final_summary: str
    messages: Annotated[list, add_messages]


# ── Node implementations ──────────────────────────────────────────────────────

async def alert_intake_node(state: NOCAgentState) -> NOCAgentState:
    """Load and validate the alert from database."""
    async with get_db_context() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(Alert).where(
                Alert.id == uuid.UUID(state["alert_id"])
            )
        )
        alert = result.scalar_one_or_none()
        if alert:
            return {
                **state,
                "alert_data": {
                    "id": str(alert.id),
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "title": alert.title,
                    "description": alert.description,
                    "source_host": alert.source_host,
                    "source_device_id": str(alert.source_device_id) if alert.source_device_id else None,
                    "raw_event": alert.raw_event or {},
                    "created_at": alert.created_at.isoformat() if alert.created_at else None,
                },
            }
    return state


async def device_enrichment_node(state: NOCAgentState) -> NOCAgentState:
    """Collect real-time device data for the alert source device."""
    device_id_str = state.get("alert_data", {}).get("source_device_id")
    if not device_id_str:
        return {**state, "device_info": {}, "interface_data": []}

    from sqlalchemy import select as sqlselect
    async with get_db_context() as db:
        result = await db.execute(
            sqlselect(Device).where(Device.id == uuid.UUID(device_id_str))
        )
        device = result.scalar_one_or_none()
        if not device:
            return {**state, "device_info": {}, "interface_data": []}

        # Get interfaces
        iface_result = await db.execute(
            sqlselect(DeviceInterface).where(DeviceInterface.device_id == device.id)
        )
        interfaces = [
            {
                "name": i.if_name, "oper_status": i.oper_status,
                "in_errors": i.in_errors, "out_errors": i.out_errors,
                "speed_bps": i.speed_bps,
            }
            for i in iface_result.scalars().all()
        ]

        device_info = {
            "id": str(device.id),
            "hostname": device.hostname,
            "ip_address": device.ip_address,
            "vendor": device.vendor,
            "model": device.model,
            "status": device.status,
            "cpu_util": device.last_cpu_util,
            "mem_util": device.last_mem_util,
            "uptime_seconds": device.uptime_seconds,
            "os_version": device.os_version,
            "location": device.location,
        }

    return {
        **state,
        "device_info": device_info,
        "interface_data": interfaces,
        "messages": [HumanMessage(content=f"Enriched: {device_info.get('hostname')} ({device_info.get('status')})")],
    }


async def rag_query_node(state: NOCAgentState) -> NOCAgentState:
    """Query enterprise knowledge base for similar incidents and documentation."""
    alert = state.get("alert_data", {})
    query = f"{alert.get('alert_type', '')} {alert.get('title', '')} {alert.get('description', '')}"

    similar_incidents = []
    rag_context = []

    try:
        import httpx
        from backend.core.config import settings
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"http://localhost:{settings.RAG_SERVICE_PORT}/api/v1/rag/query",
                json={
                    "question": query,
                    "filters": {"source_types": ["runbook", "sop", "incident_history"]},
                    "top_k": 5,
                },
                headers={"X-Internal": "true"},
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                rag_context = data.get("sources", [])
                similar_incidents = data.get("related_incidents", [])
    except Exception as exc:
        logger.warning(f"RAG query failed: {exc}")

    return {
        **state,
        "rag_context": rag_context,
        "similar_incidents": similar_incidents,
    }


async def rca_analysis_node(state: NOCAgentState) -> NOCAgentState:
    """AI Root Cause Analysis using the primary reasoning model."""
    prompt = f"""Perform root cause analysis for this network alert.

ALERT:
{json.dumps(state.get('alert_data', {}), indent=2, default=str)}

DEVICE INFO:
{json.dumps(state.get('device_info', {}), indent=2, default=str)}

INTERFACE DATA:
{json.dumps(state.get('interface_data', [])[:10], indent=2, default=str)}

SIMILAR INCIDENTS (from history):
{json.dumps(state.get('similar_incidents', [])[:3], indent=2, default=str)}

DOCUMENTATION/RUNBOOKS:
{json.dumps(state.get('rag_context', [])[:3], indent=2, default=str)}

Provide root cause analysis as JSON."""

    response = await llm.generate(
        prompt=prompt,
        system_prompt=NOC_RCA_SYSTEM,
        temperature=0.05,
    )

    try:
        import re
        json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
        rca = json.loads(json_match.group()) if json_match else {}
    except Exception:
        rca = {"root_cause": response.content, "confidence_pct": 50}

    confidence = rca.get("confidence_pct", 50) / 100.0

    # Save RCA to alert
    async with get_db_context() as db:
        alert = await db.get(Alert, uuid.UUID(state["alert_id"]))
        if alert:
            alert.ai_rca = rca.get("root_cause", "")
            alert.ai_confidence = confidence
            await db.commit()

    return {
        **state,
        "rca_result": rca,
        "rca_confidence": confidence,
        "messages": [AIMessage(content=f"RCA: {rca.get('root_cause', '')[:200]}")],
    }


async def solution_generation_node(state: NOCAgentState) -> NOCAgentState:
    """Generate remediation options based on RCA."""
    rca = state.get("rca_result", {})

    prompt = f"""Based on this root cause analysis, generate remediation options.

ROOT CAUSE:
{json.dumps(rca, indent=2, default=str)}

DEVICE: {state.get('device_info', {}).get('hostname')} ({state.get('device_info', {}).get('vendor')})

Generate 2-3 remediation options ordered from safest to most disruptive.
Output JSON:
{{
  "options": [
    {{
      "id": "option_1",
      "name": "Safest option",
      "action_type": "restart_service|clear_disk|rollback_config|etc",
      "description": "...",
      "risk_level": "low|medium|high",
      "estimated_downtime_minutes": 0,
      "commands": ["cmd1", "cmd2"],
      "executor_type": "ssh|ansible|snmp|rest"
    }}
  ],
  "recommended_option_id": "option_1"
}}"""

    response = await llm.generate(
        prompt=prompt,
        system_prompt=NOC_SOLUTION_SYSTEM,
        temperature=0.1,
    )

    try:
        import re
        json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
        solutions_data = json.loads(json_match.group()) if json_match else {}
    except Exception:
        solutions_data = {"options": [], "recommended_option_id": None}

    options = solutions_data.get("options", [])
    recommended_id = solutions_data.get("recommended_option_id")
    selected = next((o for o in options if o.get("id") == recommended_id), options[0] if options else {})

    # Save suggestion to alert
    async with get_db_context() as db:
        alert = await db.get(Alert, uuid.UUID(state["alert_id"]))
        if alert:
            alert.ai_suggestion = selected.get("description", "")
            await db.commit()

    return {
        **state,
        "solution_options": options,
        "selected_solution": selected,
    }


async def risk_assessment_node(state: NOCAgentState) -> NOCAgentState:
    """Determine risk level and whether human approval is required."""
    solution = state.get("selected_solution", {})
    action_type = solution.get("action_type", "")
    risk_level = solution.get("risk_level", "medium")

    ALWAYS_APPROVE = {"reboot_device", "rollback_config", "firmware_upgrade", "shutdown_interface"}
    AUTO_APPROVE = {"restart_service", "clear_temp_files", "clear_old_logs", "send_notification"}

    if action_type in ALWAYS_APPROVE:
        requires_approval = True
        risk_level = "high"
    elif action_type in AUTO_APPROVE:
        requires_approval = False
        risk_level = "low"
    else:
        requires_approval = True

    return {
        **state,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
    }


async def approval_gate_node(state: NOCAgentState) -> NOCAgentState:
    """Submit to approval queue and wait (or auto-approve if configured)."""
    if not state.get("requires_approval"):
        return {**state, "approval_status": "auto_approved"}

    # Create healing action in DB for human review
    solution = state.get("selected_solution", {})
    await publish(Topics.HEALING_TASKS, {
        "type": "create_action",
        "tenant_id": state["tenant_id"],
        "action": {
            "action_type": solution.get("action_type"),
            "executor_type": solution.get("executor_type", "ssh"),
            "target_device_id": state.get("alert_data", {}).get("source_device_id"),
            "parameters": {
                "commands": solution.get("commands", []),
                "alert_id": state["alert_id"],
            },
            "ai_reasoning": state.get("rca_result", {}).get("root_cause", ""),
            "risk_level": state.get("risk_level"),
            "requires_approval": True,
        },
    })

    return {**state, "approval_status": "pending_human_approval"}


async def execute_fix_node(state: NOCAgentState) -> NOCAgentState:
    """Execute the approved fix by publishing to healing service."""
    solution = state.get("selected_solution", {})
    await publish(Topics.HEALING_TASKS, {
        "type": "execute_now",
        "tenant_id": state["tenant_id"],
        "solution": solution,
        "alert_id": state["alert_id"],
        "device_info": state.get("device_info", {}),
    })
    return {**state, "execution_result": {"status": "submitted", "solution": solution.get("name")}}


async def update_incident_node(state: NOCAgentState) -> NOCAgentState:
    """Update the alert with analysis results."""
    rca = state.get("rca_result", {})
    return {
        **state,
        "final_summary": (
            f"RCA: {rca.get('root_cause', 'Unknown cause')} | "
            f"Solution: {state.get('selected_solution', {}).get('name', 'N/A')} | "
            f"Risk: {state.get('risk_level', 'unknown')} | "
            f"Status: {state.get('approval_status', 'unknown')}"
        ),
    }


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_noc_graph():
    graph = StateGraph(NOCAgentState)

    graph.add_node("alert_intake",        alert_intake_node)
    graph.add_node("device_enrichment",   device_enrichment_node)
    graph.add_node("rag_query",           rag_query_node)
    graph.add_node("rca_analysis",        rca_analysis_node)
    graph.add_node("solution_generation", solution_generation_node)
    graph.add_node("risk_assessment",     risk_assessment_node)
    graph.add_node("approval_gate",       approval_gate_node)
    graph.add_node("execute_fix",         execute_fix_node)
    graph.add_node("update_incident",     update_incident_node)

    graph.set_entry_point("alert_intake")
    graph.add_edge("alert_intake",        "device_enrichment")
    graph.add_edge("device_enrichment",   "rag_query")
    graph.add_edge("rag_query",           "rca_analysis")
    graph.add_edge("rca_analysis",        "solution_generation")
    graph.add_edge("solution_generation", "risk_assessment")

    graph.add_conditional_edges(
        "risk_assessment",
        lambda s: "approval_gate" if s.get("requires_approval") else "execute_fix",
        {"approval_gate": "approval_gate", "execute_fix": "execute_fix"},
    )
    graph.add_conditional_edges(
        "approval_gate",
        lambda s: "execute_fix" if s.get("approval_status") == "auto_approved" else "update_incident",
        {"execute_fix": "execute_fix", "update_incident": "update_incident"},
    )
    graph.add_edge("execute_fix",      "update_incident")
    graph.add_edge("update_incident",  END)

    return graph.compile()


noc_graph = build_noc_graph()
