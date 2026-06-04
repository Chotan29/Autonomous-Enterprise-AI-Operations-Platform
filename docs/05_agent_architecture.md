# AEAOP — Agent Architecture Design

## Agent Framework Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AEAOP AGENT ARCHITECTURE                              │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                  MASTER ORCHESTRATOR (LangGraph)                    │   │
│  │                                                                     │   │
│  │    Alert/Event ──► Router ──► Agent Selector ──► Agent Spawner     │   │
│  │                              │                                      │   │
│  │              ┌───────────────┴──────────────────────┐              │   │
│  │              │               │              │        │              │   │
│  │         NOC Agent      SOC Agent    Server Agent  PhySec Agent     │   │
│  │              │               │              │        │              │   │
│  │              └───────────────┴──────────────┘────────┘              │   │
│  │                              │                                      │   │
│  │                    Healing Agent ◄──── Approval Gate               │   │
│  │                              │                                      │   │
│  │                      Report Agent ◄──── Scheduled                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Agent Capabilities:                                                        │
│  • Each agent uses LangGraph stateful workflow                              │
│  • Agents communicate via Kafka message bus                                 │
│  • Each agent has dedicated MCP tool set                                    │
│  • All agent decisions are logged + explainable                             │
│  • Human-in-the-loop gates for risky actions                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. NOC Agent — LangGraph Workflow

```python
# agents/noc_agent/graph.py

"""
NOC Agent Workflow:
Alert Received
    → Classify Alert
    → Enrich with Device Context
    → Query RAG for Similar Incidents
    → AI Root Cause Analysis
    → Generate Solution Options
    → Risk Assessment
    → [Auto-Execute if low risk] OR [Request Approval]
    → Execute Fix
    → Verify Fix
    → Update Incident
    → Generate Report Entry
"""

from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional
import json

class NOCAgentState(TypedDict):
    alert_id: str
    tenant_id: str
    alert_data: dict
    device_info: dict
    interface_data: dict
    snmp_data: dict
    enrichment: dict
    similar_incidents: List[dict]
    rag_context: List[dict]
    rca_result: str
    rca_confidence: float
    solution_options: List[dict]
    selected_solution: dict
    risk_level: str
    requires_approval: bool
    approval_status: str
    execution_result: dict
    verification_status: str
    messages: List[str]
    final_summary: str


def build_noc_agent_graph():
    graph = StateGraph(NOCAgentState)

    # Node definitions
    graph.add_node("alert_intake",        alert_intake_node)
    graph.add_node("device_enrichment",   device_enrichment_node)
    graph.add_node("rag_query",           rag_query_node)
    graph.add_node("rca_analysis",        rca_analysis_node)
    graph.add_node("solution_generation", solution_generation_node)
    graph.add_node("risk_assessment",     risk_assessment_node)
    graph.add_node("approval_gate",       approval_gate_node)
    graph.add_node("execute_fix",         execute_fix_node)
    graph.add_node("verify_fix",          verify_fix_node)
    graph.add_node("update_incident",     update_incident_node)

    # Edge definitions
    graph.set_entry_point("alert_intake")
    graph.add_edge("alert_intake",        "device_enrichment")
    graph.add_edge("device_enrichment",   "rag_query")
    graph.add_edge("rag_query",           "rca_analysis")
    graph.add_edge("rca_analysis",        "solution_generation")
    graph.add_edge("solution_generation", "risk_assessment")

    # Conditional: auto-execute vs. require approval
    graph.add_conditional_edges(
        "risk_assessment",
        lambda state: "approval_gate" if state["requires_approval"] else "execute_fix",
        {
            "approval_gate": "approval_gate",
            "execute_fix":   "execute_fix"
        }
    )

    graph.add_conditional_edges(
        "approval_gate",
        lambda state: "execute_fix" if state["approval_status"] == "approved" else END,
        {
            "execute_fix": "execute_fix",
            END:           END
        }
    )

    graph.add_edge("execute_fix",   "verify_fix")
    graph.add_edge("verify_fix",    "update_incident")
    graph.add_edge("update_incident", END)

    return graph.compile()


# ─── Node Implementations ─────────────────────────────────────────────────

async def rca_analysis_node(state: NOCAgentState) -> NOCAgentState:
    """AI Root Cause Analysis using LLM"""

    prompt = f"""
    You are a senior NOC engineer. Analyze this alert and provide root cause analysis.

    ALERT DATA:
    {json.dumps(state['alert_data'], indent=2)}

    DEVICE INFO:
    {json.dumps(state['device_info'], indent=2)}

    SNMP DATA:
    {json.dumps(state['snmp_data'], indent=2)}

    SIMILAR PAST INCIDENTS:
    {json.dumps(state['similar_incidents'][:3], indent=2)}

    KNOWLEDGE BASE CONTEXT:
    {json.dumps(state['rag_context'][:3], indent=2)}

    Provide:
    1. Root cause (specific, not generic)
    2. Contributing factors
    3. Impact assessment
    4. Confidence level (0-1)

    Be specific. Reference actual interface names, IP addresses, metrics from the data.
    """

    response = await llm_client.generate(
        model="qwen3-72b",
        prompt=prompt,
        temperature=0.1
    )

    state["rca_result"] = response.content
    state["rca_confidence"] = response.confidence
    return state


async def risk_assessment_node(state: NOCAgentState) -> NOCAgentState:
    """Determine if action requires human approval"""

    solution = state["selected_solution"]
    action_type = solution.get("action_type", "")

    # Autonomous actions (no approval needed)
    AUTO_APPROVE = [
        "restart_service",
        "clear_temp_files",
        "send_notification",
        "update_monitoring",
    ]

    # Always require approval
    ALWAYS_APPROVE = [
        "reboot_device",
        "rollback_config",
        "firmware_upgrade",
        "shutdown_interface",
        "change_routing",
    ]

    if action_type in ALWAYS_APPROVE:
        state["risk_level"] = "high"
        state["requires_approval"] = True
    elif action_type in AUTO_APPROVE:
        state["risk_level"] = "low"
        state["requires_approval"] = False
    else:
        state["risk_level"] = "medium"
        state["requires_approval"] = True

    return state
```

---

## 2. SOC Agent — Threat Detection Workflow

```python
# agents/soc_agent/graph.py

class SOCAgentState(TypedDict):
    event_id: str
    tenant_id: str
    raw_events: List[dict]
    correlated_events: List[dict]
    threat_type: str
    threat_confidence: float
    mitre_tactics: List[str]
    mitre_techniques: List[str]
    ioc_matches: List[dict]
    affected_entities: List[dict]
    risk_score: int
    incident_id: Optional[str]
    response_actions: List[dict]
    investigation_notes: str
    messages: List[str]


def build_soc_agent_graph():
    graph = StateGraph(SOCAgentState)

    graph.add_node("event_intake",        soc_event_intake_node)
    graph.add_node("event_correlation",   event_correlation_node)
    graph.add_node("ioc_lookup",          ioc_lookup_node)
    graph.add_node("threat_classification", threat_classification_node)
    graph.add_node("mitre_mapping",       mitre_mapping_node)
    graph.add_node("entity_analysis",     entity_analysis_node)
    graph.add_node("risk_scoring",        risk_scoring_node)
    graph.add_node("incident_creation",   incident_creation_node)
    graph.add_node("response_planning",   response_planning_node)
    graph.add_node("notify_analyst",      notify_analyst_node)

    graph.set_entry_point("event_intake")
    graph.add_edge("event_intake",         "event_correlation")
    graph.add_edge("event_correlation",    "ioc_lookup")
    graph.add_edge("ioc_lookup",           "threat_classification")
    graph.add_edge("threat_classification","mitre_mapping")
    graph.add_edge("mitre_mapping",        "entity_analysis")
    graph.add_edge("entity_analysis",      "risk_scoring")

    graph.add_conditional_edges(
        "risk_scoring",
        lambda s: "incident_creation" if s["risk_score"] >= 60 else "notify_analyst",
        {
            "incident_creation": "incident_creation",
            "notify_analyst":    "notify_analyst"
        }
    )

    graph.add_edge("incident_creation", "response_planning")
    graph.add_edge("response_planning", "notify_analyst")
    graph.add_edge("notify_analyst",    END)

    return graph.compile()
```

---

## 3. Self-Healing Agent — Autonomous Remediation

```python
# agents/healing_agent/graph.py

class HealingAgentState(TypedDict):
    action_id: str
    tenant_id: str
    trigger_type: str            # 'alert', 'incident', 'scheduled', 'manual'
    trigger_id: str
    diagnosis: dict
    playbook_id: Optional[str]
    playbook_steps: List[dict]
    current_step: int
    step_results: List[dict]
    approval_required: bool
    approval_status: str         # 'pending', 'approved', 'rejected'
    rollback_available: bool
    rollback_steps: List[dict]
    execution_status: str
    verification_checks: List[dict]
    final_status: str


def build_healing_graph():
    graph = StateGraph(HealingAgentState)

    graph.add_node("intake",          healing_intake_node)
    graph.add_node("diagnosis",       diagnosis_node)
    graph.add_node("playbook_select", playbook_selection_node)
    graph.add_node("pre_check",       pre_check_node)
    graph.add_node("approval_gate",   healing_approval_gate)
    graph.add_node("execute_step",    execute_step_node)
    graph.add_node("verify_step",     verify_step_node)
    graph.add_node("post_verify",     post_verify_node)
    graph.add_node("rollback",        rollback_node)
    graph.add_node("report",          report_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake",          "diagnosis")
    graph.add_edge("diagnosis",       "playbook_select")
    graph.add_edge("playbook_select", "pre_check")

    # Conditional: approval required?
    graph.add_conditional_edges(
        "pre_check",
        lambda s: "approval_gate" if s["approval_required"] else "execute_step",
        {"approval_gate": "approval_gate", "execute_step": "execute_step"}
    )

    graph.add_conditional_edges(
        "approval_gate",
        lambda s: "execute_step" if s["approval_status"] == "approved" else "report",
        {"execute_step": "execute_step", "report": "report"}
    )

    # Step loop: execute → verify → next step or rollback
    graph.add_edge("execute_step", "verify_step")

    graph.add_conditional_edges(
        "verify_step",
        lambda s: "execute_step" if s["current_step"] < len(s["playbook_steps"]) - 1
                  else "post_verify" if s["execution_status"] == "success"
                  else "rollback",
        {
            "execute_step": "execute_step",
            "post_verify":  "post_verify",
            "rollback":     "rollback"
        }
    )

    graph.add_edge("post_verify", "report")
    graph.add_edge("rollback",    "report")
    graph.add_edge("report",      END)

    return graph.compile()
```

---

## 4. RAG Agent — Enterprise Knowledge Retrieval

```python
# agents/rag_agent/graph.py

class RAGAgentState(TypedDict):
    query: str
    tenant_id: str
    context: dict                   # device_id, alert_id, etc.
    query_plan: List[str]           # decomposed sub-queries
    retrieved_chunks: List[dict]
    reranked_chunks: List[dict]
    knowledge_graph_facts: List[dict]
    similar_incidents: List[dict]
    final_context: str
    answer: str
    answer_confidence: float
    sources: List[dict]


def build_rag_graph():
    graph = StateGraph(RAGAgentState)

    graph.add_node("query_planner",    rag_query_planner_node)
    graph.add_node("vector_search",    vector_search_node)
    graph.add_node("bm25_search",      bm25_search_node)
    graph.add_node("kg_query",         knowledge_graph_query_node)
    graph.add_node("incident_search",  incident_search_node)
    graph.add_node("rerank",           rerank_node)
    graph.add_node("context_builder",  context_builder_node)
    graph.add_node("answer_generator", answer_generator_node)
    graph.add_node("hallucination_check", hallucination_check_node)

    graph.set_entry_point("query_planner")

    # Parallel retrieval branches
    graph.add_edge("query_planner", "vector_search")
    graph.add_edge("query_planner", "bm25_search")
    graph.add_edge("query_planner", "kg_query")
    graph.add_edge("query_planner", "incident_search")

    # Merge and rerank
    graph.add_edge("vector_search",    "rerank")
    graph.add_edge("bm25_search",      "rerank")
    graph.add_edge("kg_query",         "rerank")
    graph.add_edge("incident_search",  "rerank")

    graph.add_edge("rerank",           "context_builder")
    graph.add_edge("context_builder",  "answer_generator")
    graph.add_edge("answer_generator", "hallucination_check")

    graph.add_conditional_edges(
        "hallucination_check",
        lambda s: "answer_generator" if s["answer_confidence"] < 0.7 else END,
        {"answer_generator": "answer_generator", END: END}
    )

    return graph.compile()
```

---

## 5. CrewAI Multi-Agent Crews

```python
# agents/crews/incident_crew.py
# For complex incidents requiring multiple specialist agents

from crewai import Agent, Task, Crew, Process

class IncidentResponseCrew:
    """
    Multi-agent crew for complex security incidents.
    Uses CrewAI hierarchical process.
    """

    def __init__(self, llm_config):
        self.llm = llm_config

        # Define specialist agents
        self.incident_commander = Agent(
            role="Incident Commander",
            goal="Coordinate the incident response and make final decisions",
            backstory="Senior incident commander with 15 years of experience in bank security",
            llm=self.llm,
            verbose=True
        )

        self.threat_analyst = Agent(
            role="Threat Intelligence Analyst",
            goal="Analyze threat indicators and map to MITRE ATT&CK framework",
            backstory="Expert in APT groups, malware analysis, and threat intelligence",
            llm=self.llm,
            tools=[siem_query_tool, threat_intel_tool, malware_analysis_tool]
        )

        self.forensic_analyst = Agent(
            role="Digital Forensics Analyst",
            goal="Collect and analyze forensic evidence from affected systems",
            backstory="Certified forensic examiner specializing in live-system analysis",
            llm=self.llm,
            tools=[log_analysis_tool, memory_analysis_tool, file_analysis_tool]
        )

        self.network_analyst = Agent(
            role="Network Security Analyst",
            goal="Analyze network traffic and identify lateral movement",
            backstory="Expert in network forensics and packet analysis",
            llm=self.llm,
            tools=[netflow_tool, pcap_tool, firewall_query_tool]
        )

        self.remediation_specialist = Agent(
            role="Remediation Specialist",
            goal="Plan and execute containment and remediation actions",
            backstory="Expert in incident containment, eradication, and recovery",
            llm=self.llm,
            tools=[ssh_tool, ansible_tool, firewall_rule_tool]
        )

    def create_incident_response_tasks(self, incident_data: dict) -> list:
        return [
            Task(
                description=f"Analyze the initial alert data and create incident timeline: {incident_data}",
                agent=self.incident_commander,
                expected_output="Structured incident timeline and initial impact assessment"
            ),
            Task(
                description="Identify threat actor TTPs and map to MITRE ATT&CK. Check threat intel databases.",
                agent=self.threat_analyst,
                expected_output="MITRE ATT&CK mapping, threat actor attribution (if possible), IOC list"
            ),
            Task(
                description="Collect forensic evidence from affected hosts. Analyze logs, processes, files.",
                agent=self.forensic_analyst,
                expected_output="Forensic timeline, artifacts collected, malicious indicators found"
            ),
            Task(
                description="Analyze NetFlow and firewall logs for lateral movement and exfiltration attempts.",
                agent=self.network_analyst,
                expected_output="Network activity analysis, C2 communication detected, exfiltration assessment"
            ),
            Task(
                description="Based on all findings, create containment and remediation plan.",
                agent=self.remediation_specialist,
                expected_output="Step-by-step remediation plan with rollback procedures"
            )
        ]

    def run(self, incident_data: dict):
        tasks = self.create_incident_response_tasks(incident_data)
        crew = Crew(
            agents=[
                self.incident_commander,
                self.threat_analyst,
                self.forensic_analyst,
                self.network_analyst,
                self.remediation_specialist
            ],
            tasks=tasks,
            process=Process.hierarchical,
            manager_agent=self.incident_commander,
            verbose=True
        )
        return crew.kickoff()
```

---

## 6. Agent Decision Logic — Autonomy Levels

```
AUTONOMY LEVEL MATRIX:

┌──────────────────────────────┬──────────────┬───────────────────────────────┐
│ Action                       │ Risk Level   │ Autonomy Level                │
├──────────────────────────────┼──────────────┼───────────────────────────────┤
│ Send notification/alert      │ NONE         │ FULLY AUTONOMOUS              │
│ Create ticket/incident       │ NONE         │ FULLY AUTONOMOUS              │
│ Run read-only diagnostics    │ NONE         │ FULLY AUTONOMOUS              │
│ Collect SNMP/metric data     │ NONE         │ FULLY AUTONOMOUS              │
│ Query threat intel           │ NONE         │ FULLY AUTONOMOUS              │
├──────────────────────────────┼──────────────┼───────────────────────────────┤
│ Restart application service  │ LOW          │ AUTO (if health check fails)  │
│ Clear temp/log files         │ LOW          │ AUTO (if disk > 90%)          │
│ Block single IP in firewall  │ LOW          │ AUTO (if threat score > 90)   │
│ Add monitoring rule          │ LOW          │ AUTO                          │
├──────────────────────────────┼──────────────┼───────────────────────────────┤
│ Reboot server                │ MEDIUM       │ REQUIRES NOC APPROVAL         │
│ Rollback device config       │ MEDIUM       │ REQUIRES NOC APPROVAL         │
│ Patch/update packages        │ MEDIUM       │ REQUIRES CHANGE APPROVAL      │
│ Modify firewall policy       │ MEDIUM       │ REQUIRES SOC APPROVAL         │
│ Isolate network segment      │ MEDIUM       │ REQUIRES SOC APPROVAL         │
├──────────────────────────────┼──────────────┼───────────────────────────────┤
│ Firmware upgrade             │ HIGH         │ REQUIRES CHANGE MANAGEMENT    │
│ Core routing changes         │ HIGH         │ REQUIRES NETWORK TEAM + MGMT  │
│ Shut down production server  │ HIGH         │ REQUIRES MANAGER + IT APPROVAL│
│ Reset admin credentials      │ HIGH         │ REQUIRES SOC MANAGER + CISO   │
│ Shutdown critical systems    │ CRITICAL     │ REQUIRES C-SUITE APPROVAL     │
└──────────────────────────────┴──────────────┴───────────────────────────────┘
```

---

## 7. Agent Communication Architecture

```
                    KAFKA EVENT BUS
    ┌────────────────────────────────────────────────┐
    │                                                │
    │  Topics:                                       │
    │  • aeaop.alerts.raw          (all raw alerts)  │
    │  • aeaop.alerts.enriched     (AI enriched)     │
    │  • aeaop.agents.noc.tasks    (NOC work queue)  │
    │  • aeaop.agents.soc.tasks    (SOC work queue)  │
    │  • aeaop.agents.healing.tasks (healing queue)  │
    │  • aeaop.actions.approved    (approved actions)│
    │  • aeaop.actions.executed    (execution results│
    │  • aeaop.reports.scheduled   (report requests) │
    │  • aeaop.physec.events       (vision events)   │
    │                                                │
    └────────────────────────────────────────────────┘
         ↑                                    ↓
    Collectors                           Agents/Services
    SNMP Poller                          NOC Agent
    Syslog Server                        SOC Agent
    NetFlow Collector                    Healing Agent
    Camera Ingestor                      Report Agent
    Windows Agent                        PhySec Agent
    Linux Agent
```
