# AEAOP — Complete API Design

## API Architecture Overview

```
Base URL: https://api.aeaop.internal/api/v1
Authentication: Bearer JWT (Keycloak OIDC) + API Key support
Format: JSON (application/json)
Versioning: URL path (/api/v1, /api/v2)
Rate Limiting: Per-tenant, per-user, per-endpoint
WebSocket: wss://api.aeaop.internal/ws/v1 (real-time events)
```

### Global Headers
```
Authorization: Bearer <jwt_token>
X-Tenant-ID: <tenant_uuid>
X-Request-ID: <uuid>            # idempotency / tracing
X-API-Version: 1
Content-Type: application/json
```

### Standard Response Envelope
```json
{
  "success": true,
  "data": {},
  "meta": {
    "page": 1,
    "per_page": 50,
    "total": 1234,
    "request_id": "uuid",
    "timestamp": "2026-06-04T10:00:00Z"
  },
  "error": null
}
```

---

## NOC Service API (:8001)

### Device Management
```
GET    /api/v1/noc/devices                    # List all devices
POST   /api/v1/noc/devices                    # Add device manually
GET    /api/v1/noc/devices/{id}               # Get device detail
PUT    /api/v1/noc/devices/{id}               # Update device
DELETE /api/v1/noc/devices/{id}               # Remove device
POST   /api/v1/noc/devices/{id}/poll          # Force SNMP poll
POST   /api/v1/noc/devices/{id}/ping          # Ping check
GET    /api/v1/noc/devices/{id}/interfaces    # List interfaces
GET    /api/v1/noc/devices/{id}/neighbors     # LLDP/CDP neighbors
GET    /api/v1/noc/devices/{id}/metrics       # Current metrics
GET    /api/v1/noc/devices/{id}/bandwidth     # Bandwidth history
GET    /api/v1/noc/devices/{id}/configs       # Config backup list
POST   /api/v1/noc/devices/{id}/configs/backup     # Trigger backup
POST   /api/v1/noc/devices/{id}/configs/restore    # Restore config
GET    /api/v1/noc/devices/{id}/compliance    # Compliance results
POST   /api/v1/noc/devices/{id}/compliance/run     # Run compliance check
POST   /api/v1/noc/devices/{id}/firmware/upgrade   # Upgrade firmware
```

### Discovery
```
POST   /api/v1/noc/discovery/scan             # IP range scan
POST   /api/v1/noc/discovery/snmp             # SNMP discovery
GET    /api/v1/noc/discovery/jobs             # List discovery jobs
GET    /api/v1/noc/discovery/jobs/{id}        # Job status/results
```

### Topology
```
GET    /api/v1/noc/topology                   # Full topology graph
GET    /api/v1/noc/topology/devices/{id}      # Device neighborhood
POST   /api/v1/noc/topology/rebuild           # Rebuild topology
```

### Bandwidth Analytics
```
GET    /api/v1/noc/bandwidth/top              # Top talkers
GET    /api/v1/noc/bandwidth/trends           # Bandwidth trends
GET    /api/v1/noc/bandwidth/forecast         # AI bandwidth forecast
POST   /api/v1/noc/bandwidth/anomaly          # Get anomalies
```

### Sample Payloads

**POST /api/v1/noc/devices**
```json
{
  "hostname": "core-sw-01",
  "ip_address": "10.0.0.1",
  "device_type": "cisco_ios_xe",
  "vendor": "Cisco",
  "snmp_version": "v3",
  "snmp_config": {
    "vault_secret_path": "secret/noc/devices/core-sw-01/snmp"
  },
  "ssh_config": {
    "vault_secret_path": "secret/noc/devices/core-sw-01/ssh"
  },
  "location": "DC1-RACK-A01",
  "tags": ["core", "production", "campus"]
}
```

**GET /api/v1/noc/devices/{id}/metrics — Response**
```json
{
  "success": true,
  "data": {
    "device_id": "uuid",
    "hostname": "core-sw-01",
    "timestamp": "2026-06-04T10:00:00Z",
    "cpu_util": 45.2,
    "mem_util": 62.8,
    "temperature": 38.5,
    "interfaces": [
      {
        "name": "GigabitEthernet0/0",
        "in_bps": 450234567,
        "out_bps": 89234567,
        "utilization_pct": 45.0,
        "errors": 0,
        "status": "up"
      }
    ],
    "uptime_seconds": 3456789,
    "ai_health_score": 94
  }
}
```

---

## SOC Service API (:8002)

### SIEM & Events
```
GET    /api/v1/soc/events                     # Query SIEM events
POST   /api/v1/soc/events/search              # Advanced search (KQL)
GET    /api/v1/soc/events/{id}               # Event detail
POST   /api/v1/soc/events/correlate           # Manual correlation
```

### Alerts
```
GET    /api/v1/soc/alerts                     # List security alerts
GET    /api/v1/soc/alerts/{id}               # Alert detail + AI analysis
POST   /api/v1/soc/alerts/{id}/acknowledge   # Acknowledge
POST   /api/v1/soc/alerts/{id}/resolve       # Resolve with notes
POST   /api/v1/soc/alerts/{id}/escalate      # Escalate to incident
```

### Incidents
```
GET    /api/v1/soc/incidents                  # List incidents
POST   /api/v1/soc/incidents                  # Create incident
GET    /api/v1/soc/incidents/{id}            # Full incident detail
PUT    /api/v1/soc/incidents/{id}            # Update incident
POST   /api/v1/soc/incidents/{id}/timeline   # Add timeline entry
GET    /api/v1/soc/incidents/{id}/ai-summary # AI-generated summary
POST   /api/v1/soc/incidents/{id}/close      # Close incident
```

### Threat Intelligence
```
GET    /api/v1/soc/threat-intel/iocs          # List IOCs
POST   /api/v1/soc/threat-intel/iocs          # Add IOC
POST   /api/v1/soc/threat-intel/iocs/lookup   # Lookup specific IOC
DELETE /api/v1/soc/threat-intel/iocs/{id}     # Remove IOC
POST   /api/v1/soc/threat-intel/iocs/bulk     # Bulk import
```

### UEBA
```
GET    /api/v1/soc/ueba/entities              # List monitored entities
GET    /api/v1/soc/ueba/entities/{id}        # Entity risk profile
GET    /api/v1/soc/ueba/anomalies             # Current anomalies
GET    /api/v1/soc/ueba/risk-scores           # Risk leaderboard
```

### Malware Analysis
```
POST   /api/v1/soc/malware/analyze            # Submit file/hash
GET    /api/v1/soc/malware/jobs/{id}         # Analysis status
GET    /api/v1/soc/malware/reports/{id}      # Full report
```

---

## Server Service API (:8003)

```
GET    /api/v1/servers                        # List servers
POST   /api/v1/servers                        # Register server
GET    /api/v1/servers/{id}                  # Server detail
GET    /api/v1/servers/{id}/metrics          # Current metrics
GET    /api/v1/servers/{id}/services         # Running services
POST   /api/v1/servers/{id}/services/{name}/restart  # Restart service
GET    /api/v1/servers/{id}/processes        # Process list
GET    /api/v1/servers/{id}/logs             # Recent logs
GET    /api/v1/servers/{id}/patches          # Available patches
POST   /api/v1/servers/{id}/patches/apply    # Apply patches
POST   /api/v1/servers/provision             # PXE/cloud-init provision
GET    /api/v1/servers/provision/jobs/{id}   # Provisioning status
```

### Virtualization
```
GET    /api/v1/servers/vms                    # List all VMs
GET    /api/v1/servers/clusters               # Cluster overview
GET    /api/v1/servers/clusters/{id}/capacity # Capacity stats
POST   /api/v1/servers/vms/{id}/migrate      # Live migrate VM
POST   /api/v1/servers/vms/{id}/snapshot     # Create snapshot
GET    /api/v1/servers/k8s/clusters          # K8s clusters
GET    /api/v1/servers/k8s/clusters/{id}/nodes # Cluster nodes
```

---

## Physical Security API (:8004)

```
GET    /api/v1/physec/cameras                 # List cameras
GET    /api/v1/physec/cameras/{id}           # Camera detail
GET    /api/v1/physec/cameras/{id}/stream    # RTSP stream proxy URL
GET    /api/v1/physec/cameras/{id}/snapshot  # Latest snapshot
GET    /api/v1/physec/events                  # Vision events list
GET    /api/v1/physec/events/{id}            # Event detail + clips
POST   /api/v1/physec/events/{id}/review     # Human review action
GET    /api/v1/physec/zones                   # Security zones
GET    /api/v1/physec/zones/{id}/events      # Zone-specific events
GET    /api/v1/physec/analytics/occupancy    # Real-time occupancy
GET    /api/v1/physec/analytics/heatmap      # Movement heatmap
GET    /api/v1/physec/analytics/trends       # Event trends
```

---

## RAG / AI Service API (:8005, :8006)

### RAG Queries
```
POST   /api/v1/rag/query                      # Ask question using RAG
POST   /api/v1/rag/documents/ingest           # Upload/index document
GET    /api/v1/rag/documents                  # List indexed documents
DELETE /api/v1/rag/documents/{id}            # Remove from index
POST   /api/v1/rag/documents/reindex          # Reindex all
GET    /api/v1/rag/similar-incidents          # Find similar past incidents
```

**POST /api/v1/rag/query — Request**
```json
{
  "question": "How do I recover a failed BGP session on Cisco IOS-XE?",
  "context": {
    "device_id": "uuid-of-device",
    "alert_id": "uuid-of-alert"
  },
  "filters": {
    "source_types": ["runbook", "sop", "vendor_manual"],
    "top_k": 5
  }
}
```

**POST /api/v1/rag/query — Response**
```json
{
  "success": true,
  "data": {
    "answer": "To recover a failed BGP session on Cisco IOS-XE: 1. Check BGP neighbor status with 'show bgp summary'...",
    "confidence": 0.94,
    "sources": [
      {
        "doc_id": "uuid",
        "title": "Cisco BGP Recovery Runbook v2.1",
        "chunk": "BGP session recovery procedure...",
        "relevance_score": 0.97,
        "source_type": "runbook"
      }
    ],
    "related_incidents": [
      {
        "incident_id": "INC-2026-000234",
        "similarity": 0.91,
        "resolution": "Cleared stuck BGP state with clear ip bgp..."
      }
    ],
    "ai_model": "qwen3-72b",
    "tokens_used": 1847
  }
}
```

### AI Chat (Contextual)
```
POST   /api/v1/ai/chat                        # Chat with AI assistant
POST   /api/v1/ai/analyze/alert              # Deep AI alert analysis
POST   /api/v1/ai/analyze/incident           # Incident analysis
POST   /api/v1/ai/rca                         # Root cause analysis
POST   /api/v1/ai/recommend                   # Get recommendations
POST   /api/v1/ai/generate/report            # Generate AI report
POST   /api/v1/ai/generate/playbook          # Generate healing playbook
```

---

## Healing Service API (:8013)

```
GET    /api/v1/healing/actions                # List healing actions
GET    /api/v1/healing/actions/{id}          # Action detail
POST   /api/v1/healing/actions/{id}/approve  # Approve execution
POST   /api/v1/healing/actions/{id}/reject   # Reject with reason
POST   /api/v1/healing/actions/{id}/rollback # Rollback executed action
GET    /api/v1/healing/playbooks             # List available playbooks
POST   /api/v1/healing/playbooks/{id}/run   # Manual playbook execution
GET    /api/v1/healing/stats                  # Healing statistics
```

**POST /api/v1/healing/actions/{id}/approve — Request**
```json
{
  "approver_notes": "Verified the service is failed. Safe to restart.",
  "schedule_type": "immediate"
}
```

---

## WebSocket API (Real-Time)

```
wss://api.aeaop.internal/ws/v1/noc/alerts      # Live NOC alert stream
wss://api.aeaop.internal/ws/v1/soc/events      # Live SIEM event stream
wss://api.aeaop.internal/ws/v1/healing/status  # Healing action status
wss://api.aeaop.internal/ws/v1/physec/events   # Physical security events
wss://api.aeaop.internal/ws/v1/devices/metrics # Live device metrics
```

**WebSocket Message Format**
```json
{
  "type": "alert.created",
  "tenant_id": "uuid",
  "timestamp": "2026-06-04T10:00:00Z",
  "payload": {
    "alert_id": "uuid",
    "severity": "critical",
    "title": "Core router CPU > 95%",
    "device": "core-rtr-01",
    "ai_rca": "High CPU due to BGP route refresh storm from peer AS65000"
  }
}
```

---

## MCP (Model Context Protocol) Servers

```python
# network_mcp_server.py — Tools exposed to AI agents via MCP

MCP_TOOLS = [
    {
        "name": "get_device_status",
        "description": "Get real-time status of a network device",
        "parameters": {"device_id": "str", "include_interfaces": "bool"}
    },
    {
        "name": "run_ssh_command",
        "description": "Execute command on device via SSH (read-only by default)",
        "parameters": {"device_id": "str", "command": "str", "read_only": "bool"}
    },
    {
        "name": "get_interface_errors",
        "description": "Get interface error counters for a device",
        "parameters": {"device_id": "str", "interface": "str"}
    },
    {
        "name": "get_routing_table",
        "description": "Get routing table from device",
        "parameters": {"device_id": "str", "vrf": "str"}
    },
    {
        "name": "search_knowledge_base",
        "description": "Search enterprise knowledge base for documentation",
        "parameters": {"query": "str", "top_k": "int", "source_filter": "list"}
    },
    {
        "name": "get_similar_incidents",
        "description": "Find historically similar incidents",
        "parameters": {"description": "str", "category": "str", "limit": "int"}
    },
    {
        "name": "query_siem",
        "description": "Query SIEM for security events",
        "parameters": {"query": "str", "time_range": "str", "limit": "int"}
    },
    {
        "name": "get_server_metrics",
        "description": "Get current server performance metrics",
        "parameters": {"server_id": "str", "metrics": "list"}
    },
    {
        "name": "create_healing_action",
        "description": "Request an autonomous healing action (requires approval)",
        "parameters": {"action_type": "str", "target": "str", "parameters": "dict", "reasoning": "str"}
    }
]
```
