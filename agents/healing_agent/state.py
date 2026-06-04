from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class HealingState(TypedDict):
    # Input
    action_id: str
    tenant_id: str
    trigger_type: str               # alert | incident | scheduled | manual
    trigger_id: str
    alert_data: dict

    # Diagnosis
    diagnosis: dict
    root_cause: str
    confidence: float

    # Playbook
    playbook_id: Optional[str]
    playbook_name: str
    playbook_steps: list[dict]
    current_step_index: int

    # Execution state
    step_results: list[dict]
    execution_status: str           # pending | running | success | failed | rolled_back

    # Approval
    requires_approval: bool
    risk_level: str                 # low | medium | high | critical
    approval_status: str            # pending | approved | rejected | auto_approved

    # Rollback
    rollback_available: bool
    rollback_triggered: bool

    # Output
    final_status: str               # success | failed | rejected | rolled_back
    summary: str
    messages: Annotated[list, add_messages]
