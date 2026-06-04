# AEAOP — RAG System, Physical Security & Self-Healing Engine Detail

---

## 1. ENTERPRISE RAG ARCHITECTURE

```
ENTERPRISE RAG SYSTEM DESIGN

     ┌─────────────────────────────────────────────────────────────────┐
     │                  KNOWLEDGE BASE SOURCES                         │
     │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐ │
     │  │ Device   │ │ Vendor   │ │ Internal │ │ Incident Reports  │ │
     │  │ Configs  │ │ Manuals  │ │ SOPs     │ │ + Runbooks        │ │
     │  └──────────┘ └──────────┘ └──────────┘ └───────────────────┘ │
     │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐ │
     │  │ Security │ │ Compliance│ │ KB       │ │ Ticket History    │ │
     │  │ Policies │ │ Frameworks│ │ Articles │ │ + Resolutions     │ │
     │  └──────────┘ └──────────┘ └──────────┘ └───────────────────┘ │
     └──────────────────────────┬──────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   INGESTION PIPELINE  │
                    │                       │
                    │ 1. Load document      │
                    │    (PDF, DOCX, TXT,   │
                    │     Markdown, Config) │
                    │                       │
                    │ 2. Parse + Clean      │
                    │    (Remove boilerplate│
                    │     headers, footers) │
                    │                       │
                    │ 3. Chunk              │
                    │    (512-1024 tokens)  │
                    │    Overlap: 128 tokens│
                    │    Semantic splitting │
                    │                       │
                    │ 4. Embed              │
                    │    nomic-embed-text   │
                    │    768-dim vectors    │
                    │                       │
                    │ 5. Index              │
                    │    Qdrant + BM25      │
                    └───────────┬───────────┘
                                │
     ┌──────────────────────────▼──────────────────────────────────────┐
     │                    RETRIEVAL ENGINE                             │
     │                                                                 │
     │  User/Agent Query: "How to fix OSPF neighbor not forming?"     │
     │                           │                                     │
     │           ┌───────────────┼───────────────┐                   │
     │           │               │               │                   │
     │    Dense Search    Sparse Search    KG Lookup                 │
     │    (Qdrant vec.)   (BM25/ES)        (entity graph)            │
     │           │               │               │                   │
     │           └───────────────┴───────────────┘                   │
     │                           │                                     │
     │                   ┌───────▼───────┐                            │
     │                   │ Cross-Encoder │                            │
     │                   │ Re-Ranker     │                            │
     │                   │ (top-5 chunks)│                            │
     │                   └───────┬───────┘                            │
     │                           │                                     │
     │                   ┌───────▼───────┐                            │
     │                   │ Context       │                            │
     │                   │ Assembly      │                            │
     │                   │ (device info  │                            │
     │                   │ + retrieved   │                            │
     │                   │ + similar inc)│                            │
     │                   └───────┬───────┘                            │
     └───────────────────────────┼────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    LLM GENERATION       │
                    │    Qwen3-72B            │
                    │                         │
                    │    [System: Expert NOC  │
                    │     Engineer]           │
                    │    [Context: chunks +   │
                    │     device state]       │
                    │    [Query: user Q]      │
                    │           │             │
                    │    [Answer with sources]│
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   RESPONSE WITH SOURCES │
                    │   + Confidence score    │
                    │   + Citation links      │
                    └─────────────────────────┘
```

### RAG Implementation

```python
# rag_service/retrieval/hybrid_search.py

class HybridSearchEngine:
    """
    Combines dense vector search (Qdrant) with sparse keyword search (BM25/ES)
    Uses Reciprocal Rank Fusion (RRF) to merge results.
    """

    def __init__(self, qdrant_client, elasticsearch_client, reranker_model):
        self.qdrant = qdrant_client
        self.es = elasticsearch_client
        self.reranker = reranker_model

    async def search(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 10,
        filters: dict = None
    ) -> list[dict]:

        # Embed query
        query_vector = await self.embed(query)

        # Parallel retrieval
        dense_results, sparse_results = await asyncio.gather(
            self.dense_search(query_vector, tenant_id, top_k * 2, filters),
            self.sparse_search(query, tenant_id, top_k * 2, filters)
        )

        # Reciprocal Rank Fusion
        fused = self.rrf_merge(dense_results, sparse_results, k=60)

        # Take top candidates for reranking
        candidates = fused[:top_k * 2]

        # Cross-encoder reranking
        reranked = await self.reranker.rerank(
            query=query,
            documents=[c['text'] for c in candidates],
            top_n=top_k
        )

        # Return with scores and metadata
        return [
            {
                "text":          candidates[i['index']]['text'],
                "doc_id":        candidates[i['index']]['doc_id'],
                "title":         candidates[i['index']]['title'],
                "source_type":   candidates[i['index']]['source_type'],
                "relevance_score": i['relevance_score'],
                "chunk_index":   candidates[i['index']]['chunk_index']
            }
            for i in reranked
        ]

    def rrf_merge(self, dense: list, sparse: list, k: int = 60) -> list:
        """Reciprocal Rank Fusion — combines two ranked lists"""
        scores = {}

        for rank, doc in enumerate(dense):
            doc_id = doc['id']
            scores[doc_id] = scores.get(doc_id, {'score': 0, 'doc': doc})
            scores[doc_id]['score'] += 1.0 / (k + rank + 1)

        for rank, doc in enumerate(sparse):
            doc_id = doc['id']
            scores[doc_id] = scores.get(doc_id, {'score': 0, 'doc': doc})
            scores[doc_id]['score'] += 1.0 / (k + rank + 1)

        merged = sorted(scores.values(), key=lambda x: x['score'], reverse=True)
        return [m['doc'] for m in merged]


class KnowledgeGraph:
    """
    NetworkX-based knowledge graph for entity relationships.
    Entities: Device types, protocols, symptoms, solutions, vendors.
    Helps RAG understand relationships beyond text similarity.
    """

    def __init__(self, neo4j_client=None):
        # Use NetworkX for lighter deployment, Neo4j for enterprise
        self.graph = networkx.DiGraph()

    def add_entity(self, entity: str, entity_type: str, properties: dict = None):
        self.graph.add_node(entity, type=entity_type, **( properties or {}))

    def add_relationship(self, source: str, target: str, relationship: str):
        self.graph.add_edge(source, target, relation=relationship)

    def get_related_entities(self, entity: str, depth: int = 2) -> list:
        """Get all entities within N hops"""
        neighbors = set()
        for node in networkx.bfs_tree(self.graph, entity, depth_limit=depth).nodes:
            neighbors.add(node)
        return list(neighbors)

    # Example graph facts:
    # BGP → relates_to → OSPF (routing protocols)
    # interface_down → causes → packet_loss
    # packet_loss → causes → high_latency
    # high_latency → affects → VoIP, Video
    # Cisco IOS → supports → BGP, OSPF, MPLS
    # MikroTik → supports → BGP, OSPF
```

---

## 2. SELF-HEALING ENGINE DETAIL

### Healing Playbook Examples

```yaml
# agents/healing_agent/playbooks/network/recover_bgp_session.yaml

name: Recover Failed BGP Session
description: Automatically recover a stuck BGP session that has been down > 5 minutes
version: 1.2
author: NOC Team
risk_level: medium
requires_approval: true
estimated_duration_seconds: 120

trigger:
  alert_types:
    - bgp_session_down
    - bgp_peer_unreachable
  conditions:
    - alert_duration_minutes: ">5"
    - device_vendor: ["cisco", "juniper", "mikrotik"]

pre_checks:
  - name: verify_alert_still_active
    type: api_call
    endpoint: "/api/v1/noc/alerts/{alert_id}"
    expected: status != "resolved"
  - name: ping_peer_ip
    type: icmp
    target: "{alert.peer_ip}"
    expected: reachable
  - name: verify_not_maintenance
    type: db_query
    query: "SELECT is_in_maintenance FROM devices WHERE id = '{device_id}'"
    expected: "false"

steps:
  - name: collect_bgp_status
    type: ssh_command
    device: "{device_id}"
    command_template:
      cisco:   "show bgp neighbors {peer_ip} | include BGP state"
      juniper: "show bgp neighbor {peer_ip} | match State"
      mikrotik: "/routing bgp peer print detail where name={peer_name}"
    capture_output: true

  - name: analyze_bgp_state
    type: ai_analysis
    model: qwen3-72b
    context:
      bgp_output: "{steps.collect_bgp_status.output}"
      alert_data: "{alert}"
    prompt: |
      Analyze this BGP session failure. Output JSON:
      {
        "state": "...",
        "likely_cause": "...",
        "safe_to_clear": true/false,
        "recommended_command": "..."
      }

  - name: clear_bgp_session
    type: ssh_command
    condition: "{steps.analyze_bgp_state.output.safe_to_clear} == true"
    device: "{device_id}"
    command_template:
      cisco:   "clear ip bgp {peer_ip} soft"
      juniper: "clear bgp neighbor {peer_ip}"
      mikrotik: "/routing bgp peer reset {peer_name}"
    capture_output: true

  - name: wait_for_convergence
    type: sleep
    seconds: 30

  - name: verify_bgp_recovered
    type: ssh_command
    device: "{device_id}"
    command_template:
      cisco:   "show bgp neighbors {peer_ip} | include BGP state"
    expected_output_contains: "Established"

success_criteria:
  - step: verify_bgp_recovered
    condition: output_contains "Established"

rollback_steps:
  - name: notify_noc
    type: notification
    message: "BGP recovery failed. Manual intervention required for {device_hostname}"
    channels: ["teams", "email", "sms"]

  - name: create_escalation_ticket
    type: api_call
    endpoint: "/api/v1/soc/incidents"
    method: POST
    body:
      title: "BGP Recovery Failed — Escalation Required"
      severity: high
      assigned_team: senior_noc
```

```yaml
# agents/healing_agent/playbooks/server/clear_disk_space.yaml

name: Automated Disk Space Recovery
description: Clear disk space when filesystem exceeds threshold
version: 2.0
risk_level: low
requires_approval: false          # Low risk — auto-approve
estimated_duration_seconds: 180

trigger:
  alert_types:
    - disk_space_critical
    - disk_space_warning
  conditions:
    - disk_util_pct: ">85"

pre_checks:
  - name: verify_mount_point
    type: ssh_command
    command: "df -h {alert.mountpoint}"

  - name: check_not_db_disk
    type: ai_check
    prompt: "Is mountpoint '{alert.mountpoint}' a database data directory? Answer yes/no"
    expected_ai_answer: "no"    # If yes, DO NOT auto-clean, escalate instead

steps:
  - name: find_large_files
    type: ssh_command
    command: "find {mountpoint} -type f -size +100M -printf '%s %p\n' 2>/dev/null | sort -rn | head -20"
    capture_output: true

  - name: ai_analyze_files
    type: ai_analysis
    prompt: |
      These large files were found on a server disk at {alert.mountpoint}.
      Disk usage: {alert.disk_util_pct}%
      Files: {steps.find_large_files.output}

      Which of these are safe to delete automatically?
      Safe to delete: log files older than 7 days, tmp files, core dumps.
      NOT safe: application data, database files, config files.

      Return JSON: {"safe_to_delete": ["/path/file1", "/path/file2"]}

  - name: clean_old_logs
    type: ssh_command
    command: "find /var/log -name '*.gz' -mtime +7 -delete && find /var/log -name '*.log' -mtime +14 -delete"

  - name: clean_tmp
    type: ssh_command
    command: "find /tmp -mtime +3 -delete 2>/dev/null; find /var/tmp -mtime +7 -delete 2>/dev/null"

  - name: clean_package_cache
    type: conditional_command
    condition: "{server.os_type} == 'linux'"
    commands:
      ubuntu: "apt-get clean -y && journalctl --vacuum-time=7d"
      rhel:   "yum clean all && journalctl --vacuum-time=7d"

  - name: verify_disk_recovered
    type: ssh_command
    command: "df -h {alert.mountpoint} | tail -1 | awk '{print $5}'"
    expected_output_regex: "^[0-7][0-9]%$"    # Should be under 80%

success_criteria:
  - condition: "{disk_util_after} < 80"
```

---

## 3. COMPLETE SOLUTION SUMMARY

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AEAOP COMPLETE SOLUTION SUMMARY                          │
│                                                                             │
│  WHAT YOU GET:                                                              │
│                                                                             │
│  🌐 AI-POWERED NOC                                                         │
│     • 9 vendor device families (Cisco, Mikrotik, Juniper, Fortinet,        │
│       Palo Alto, HP, Dell, Ubiquiti, Huawei)                               │
│     • SNMP/LLDP/CDP discovery, IP scanning                                 │
│     • Real-time topology mapping (D3.js interactive)                       │
│     • AI Root Cause Analysis on every alert                                │
│     • Automated config backup, compliance, firmware                        │
│                                                                             │
│  🔐 AI-POWERED SOC                                                         │
│     • SIEM ingesting 10+ log source types                                  │
│     • 50+ detection rules (MITRE ATT&CK mapped)                           │
│     • UEBA behavioral analytics                                            │
│     • AI threat analysis and incident correlation                          │
│     • Automated incident response workflows                                │
│                                                                             │
│  🖥️ AI SERVER OPS CENTER                                                  │
│     • Linux + Windows + VMware + Proxmox + K8s                            │
│     • PXE boot OS provisioning                                             │
│     • Automated patch management with AI risk scoring                      │
│     • Service monitoring + auto-recovery                                   │
│                                                                             │
│  📷 PHYSICAL SECURITY AI                                                   │
│     • YOLO v11 person detection (30+ FPS real-time)                       │
│     • ByteTrack multi-person tracking                                      │
│     • Zone monitoring (restricted area, loitering, crowd)                 │
│     • Qwen2.5-VL scene analysis on alerts                                 │
│     • Human verification workflow for all AI detections                   │
│                                                                             │
│  🤖 SELF-HEALING ENGINE                                                    │
│     • SSH, WinRM, SNMP, REST, Ansible, Terraform executors               │
│     • Risk-tiered approval workflow                                        │
│     • 100+ healing playbooks                                               │
│     • Full rollback capability                                             │
│     • Complete audit trail of every action                                │
│                                                                             │
│  🧠 ENTERPRISE RAG                                                         │
│     • Hybrid search (dense + BM25 + knowledge graph)                     │
│     • All SOPs, runbooks, manuals indexed                                 │
│     • Incident history for similarity search                              │
│     • AI answers with citations and confidence                            │
│                                                                             │
│  🔒 ENTERPRISE SECURITY                                                    │
│     • Zero Trust Architecture                                              │
│     • Multi-tenant with strict isolation                                   │
│     • RBAC + MFA + SSO (Keycloak OIDC)                                   │
│     • HashiCorp Vault secrets management                                   │
│     • mTLS between all services                                           │
│     • Immutable audit logs                                                 │
│     • PCI-DSS + ISO 27001 + SOX compliance ready                         │
│                                                                             │
│  🚀 ENTERPRISE DEPLOYMENT                                                  │
│     • Kubernetes HA (99.95% availability target)                          │
│     • Dual-site DR (15-minute RTO)                                        │
│     • Velero backup + MinIO storage                                       │
│     • Fully air-gap capable (no internet required)                        │
│     • Scales from 50 to 50,000+ devices                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```
