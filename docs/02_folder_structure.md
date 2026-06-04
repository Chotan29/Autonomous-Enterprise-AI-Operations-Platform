# AEAOP — Complete Folder Structure

## Root Project Layout

```
aeaop/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── security-scan.yml
│   │   └── deploy.yml
│   └── CODEOWNERS
│
├── infrastructure/
│   ├── kubernetes/
│   │   ├── namespaces/
│   │   ├── deployments/
│   │   ├── services/
│   │   ├── configmaps/
│   │   ├── secrets/
│   │   ├── ingress/
│   │   ├── rbac/
│   │   ├── network-policies/
│   │   ├── persistent-volumes/
│   │   └── helm-charts/
│   │       ├── aeaop-core/
│   │       ├── aeaop-ai/
│   │       ├── aeaop-data/
│   │       └── aeaop-monitoring/
│   ├── terraform/
│   │   ├── modules/
│   │   │   ├── k8s-cluster/
│   │   │   ├── storage/
│   │   │   ├── networking/
│   │   │   └── iam/
│   │   ├── environments/
│   │   │   ├── dev/
│   │   │   ├── staging/
│   │   │   └── prod/
│   │   └── providers.tf
│   └── ansible/
│       ├── inventories/
│       │   ├── production/
│       │   ├── staging/
│       │   └── dev/
│       ├── roles/
│       │   ├── common/
│       │   ├── docker/
│       │   ├── k8s-node/
│       │   ├── gpu-driver/
│       │   ├── network-device/
│       │   └── monitoring-agent/
│       ├── playbooks/
│       │   ├── site.yml
│       │   ├── deploy-noc.yml
│       │   ├── deploy-soc.yml
│       │   ├── remediation/
│       │   │   ├── restart-service.yml
│       │   │   ├── clear-disk.yml
│       │   │   ├── recover-link.yml
│       │   │   ├── rollback-config.yml
│       │   │   └── patch-system.yml
│       │   └── provisioning/
│       │       ├── linux-server.yml
│       │       ├── windows-server.yml
│       │       └── network-device.yml
│       └── group_vars/
│
├── backend/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── database.py
│   │   ├── redis_client.py
│   │   ├── kafka_client.py
│   │   └── exceptions.py
│   │
│   ├── services/
│   │   ├── noc_service/
│   │   │   ├── main.py                    # FastAPI app :8001
│   │   │   ├── api/
│   │   │   │   ├── v1/
│   │   │   │   │   ├── routers/
│   │   │   │   │   │   ├── devices.py
│   │   │   │   │   │   ├── topology.py
│   │   │   │   │   │   ├── alerts.py
│   │   │   │   │   │   ├── bandwidth.py
│   │   │   │   │   │   ├── config_backup.py
│   │   │   │   │   │   ├── firmware.py
│   │   │   │   │   │   └── compliance.py
│   │   │   │   │   └── schemas/
│   │   │   │   │       ├── device.py
│   │   │   │   │       ├── alert.py
│   │   │   │   │       └── topology.py
│   │   │   ├── collectors/
│   │   │   │   ├── snmp_collector.py
│   │   │   │   ├── lldp_collector.py
│   │   │   │   ├── cdp_collector.py
│   │   │   │   ├── netflow_collector.py
│   │   │   │   └── icmp_monitor.py
│   │   │   ├── drivers/
│   │   │   │   ├── base_driver.py
│   │   │   │   ├── cisco_driver.py
│   │   │   │   ├── mikrotik_driver.py
│   │   │   │   ├── juniper_driver.py
│   │   │   │   ├── fortinet_driver.py
│   │   │   │   ├── paloalto_driver.py
│   │   │   │   ├── hp_driver.py
│   │   │   │   ├── dell_driver.py
│   │   │   │   ├── ubiquiti_driver.py
│   │   │   │   └── huawei_driver.py
│   │   │   ├── analyzers/
│   │   │   │   ├── rca_engine.py
│   │   │   │   ├── bandwidth_analyzer.py
│   │   │   │   ├── anomaly_detector.py
│   │   │   │   └── topology_builder.py
│   │   │   └── tasks/
│   │   │       ├── discovery_task.py
│   │   │       ├── backup_task.py
│   │   │       └── compliance_task.py
│   │   │
│   │   ├── soc_service/
│   │   │   ├── main.py                    # FastAPI app :8002
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── routers/
│   │   │   │       │   ├── siem.py
│   │   │   │       │   ├── incidents.py
│   │   │   │       │   ├── threats.py
│   │   │   │       │   ├── ueba.py
│   │   │   │       │   ├── threat_intel.py
│   │   │   │       │   └── malware.py
│   │   │   │       └── schemas/
│   │   │   ├── collectors/
│   │   │   │   ├── syslog_collector.py
│   │   │   │   ├── winlog_collector.py
│   │   │   │   ├── firewall_collector.py
│   │   │   │   └── ids_collector.py
│   │   │   ├── engines/
│   │   │   │   ├── correlation_engine.py
│   │   │   │   ├── threat_detection.py
│   │   │   │   ├── ueba_engine.py
│   │   │   │   ├── anomaly_engine.py
│   │   │   │   └── malware_analyzer.py
│   │   │   └── intel/
│   │   │       ├── mitre_mapper.py
│   │   │       ├── ioc_manager.py
│   │   │       └── threat_feed.py
│   │   │
│   │   ├── server_service/
│   │   │   ├── main.py                    # FastAPI app :8003
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── servers.py
│   │   │   │           ├── provisioning.py
│   │   │   │           ├── patching.py
│   │   │   │           ├── services.py
│   │   │   │           └── virtualization.py
│   │   │   ├── collectors/
│   │   │   │   ├── linux_collector.py
│   │   │   │   ├── windows_collector.py
│   │   │   │   ├── vmware_collector.py
│   │   │   │   ├── proxmox_collector.py
│   │   │   │   └── kubernetes_collector.py
│   │   │   └── provisioners/
│   │   │       ├── pxe_boot.py
│   │   │       ├── cloud_init.py
│   │   │       └── kickstart.py
│   │   │
│   │   ├── physec_service/
│   │   │   ├── main.py                    # FastAPI app :8004
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── cameras.py
│   │   │   │           ├── events.py
│   │   │   │           ├── zones.py
│   │   │   │           └── analytics.py
│   │   │   ├── vision/
│   │   │   │   ├── person_detector.py
│   │   │   │   ├── crowd_analyzer.py
│   │   │   │   ├── motion_analyzer.py
│   │   │   │   ├── object_detector.py
│   │   │   │   ├── behavior_analyzer.py
│   │   │   │   ├── loitering_detector.py
│   │   │   │   └── intrusion_detector.py
│   │   │   └── streams/
│   │   │       ├── rtsp_ingestor.py
│   │   │       └── frame_processor.py
│   │   │
│   │   ├── rag_service/
│   │   │   ├── main.py                    # FastAPI app :8005
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── query.py
│   │   │   │           ├── documents.py
│   │   │   │           └── knowledge_graph.py
│   │   │   ├── ingestion/
│   │   │   │   ├── document_loader.py
│   │   │   │   ├── chunker.py
│   │   │   │   ├── embedder.py
│   │   │   │   └── indexer.py
│   │   │   ├── retrieval/
│   │   │   │   ├── hybrid_search.py
│   │   │   │   ├── semantic_search.py
│   │   │   │   ├── bm25_search.py
│   │   │   │   └── reranker.py
│   │   │   └── graph/
│   │   │       ├── knowledge_graph.py
│   │   │       └── entity_extractor.py
│   │   │
│   │   ├── ai_service/
│   │   │   ├── main.py                    # FastAPI app :8006
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── chat.py
│   │   │   │           ├── analysis.py
│   │   │   │           └── generation.py
│   │   │   ├── llm/
│   │   │   │   ├── ollama_client.py
│   │   │   │   ├── vllm_client.py
│   │   │   │   └── model_router.py
│   │   │   └── prompts/
│   │   │       ├── noc_prompts.py
│   │   │       ├── soc_prompts.py
│   │   │       ├── rca_prompts.py
│   │   │       └── report_prompts.py
│   │   │
│   │   ├── config_service/
│   │   │   ├── main.py                    # FastAPI app :8007
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── configs.py
│   │   │   │           ├── compliance.py
│   │   │   │           └── templates.py
│   │   │   └── engines/
│   │   │       ├── backup_engine.py
│   │   │       ├── restore_engine.py
│   │   │       ├── diff_engine.py
│   │   │       └── compliance_checker.py
│   │   │
│   │   ├── report_service/
│   │   │   ├── main.py                    # FastAPI app :8008
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── reports.py
│   │   │   │           └── schedules.py
│   │   │   ├── generators/
│   │   │   │   ├── noc_report.py
│   │   │   │   ├── soc_report.py
│   │   │   │   ├── executive_report.py
│   │   │   │   └── compliance_report.py
│   │   │   └── templates/
│   │   │       ├── pdf_templates/
│   │   │       └── html_templates/
│   │   │
│   │   ├── auth_service/
│   │   │   ├── main.py                    # FastAPI app :8009
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       └── routers/
│   │   │   │           ├── auth.py
│   │   │   │           ├── users.py
│   │   │   │           ├── roles.py
│   │   │   │           └── tenants.py
│   │   │   └── providers/
│   │   │       ├── keycloak_provider.py
│   │   │       ├── ldap_provider.py
│   │   │       └── mfa_provider.py
│   │   │
│   │   └── healing_service/
│   │       ├── main.py                    # FastAPI app :8013
│   │       ├── api/
│   │       │   └── v1/
│   │       │       └── routers/
│   │       │           ├── actions.py
│   │       │           ├── approvals.py
│   │       │           └── playbooks.py
│   │       └── executors/
│   │           ├── ssh_executor.py
│   │           ├── winrm_executor.py
│   │           ├── snmp_executor.py
│   │           ├── ansible_executor.py
│   │           ├── terraform_executor.py
│   │           └── rest_executor.py
│   │
│   └── shared/
│       ├── models/
│       │   ├── device.py
│       │   ├── alert.py
│       │   ├── incident.py
│       │   ├── user.py
│       │   └── tenant.py
│       ├── middleware/
│       │   ├── auth_middleware.py
│       │   ├── tenant_middleware.py
│       │   ├── audit_middleware.py
│       │   └── rate_limit_middleware.py
│       └── utils/
│           ├── encryption.py
│           ├── validators.py
│           └── helpers.py
│
├── agents/
│   ├── orchestrator/
│   │   ├── main_graph.py               # LangGraph master graph
│   │   ├── state.py
│   │   └── router.py
│   ├── noc_agent/
│   │   ├── graph.py                    # LangGraph NOC workflow
│   │   ├── nodes/
│   │   │   ├── alert_analyzer.py
│   │   │   ├── rca_node.py
│   │   │   ├── solution_generator.py
│   │   │   ├── approval_gate.py
│   │   │   └── executor_node.py
│   │   ├── tools/
│   │   │   ├── snmp_tool.py
│   │   │   ├── ssh_tool.py
│   │   │   ├── ping_tool.py
│   │   │   └── traceroute_tool.py
│   │   └── state.py
│   ├── soc_agent/
│   │   ├── graph.py
│   │   ├── nodes/
│   │   │   ├── event_correlator.py
│   │   │   ├── threat_classifier.py
│   │   │   ├── ioc_extractor.py
│   │   │   ├── mitre_mapper.py
│   │   │   └── response_planner.py
│   │   └── tools/
│   │       ├── siem_query_tool.py
│   │       ├── threat_intel_tool.py
│   │       └── sandbox_tool.py
│   ├── server_agent/
│   │   ├── graph.py
│   │   ├── nodes/
│   │   │   ├── health_checker.py
│   │   │   ├── patch_planner.py
│   │   │   ├── recovery_executor.py
│   │   │   └── capacity_planner.py
│   │   └── tools/
│   ├── physec_agent/
│   │   ├── graph.py
│   │   ├── nodes/
│   │   │   ├── event_classifier.py
│   │   │   ├── risk_scorer.py
│   │   │   └── alert_dispatcher.py
│   │   └── tools/
│   ├── rag_agent/
│   │   ├── graph.py
│   │   ├── nodes/
│   │   │   ├── query_planner.py
│   │   │   ├── retriever_node.py
│   │   │   ├── reranker_node.py
│   │   │   └── answer_generator.py
│   │   └── tools/
│   ├── compliance_agent/
│   │   ├── graph.py
│   │   └── nodes/
│   ├── report_agent/
│   │   ├── graph.py
│   │   └── nodes/
│   └── healing_agent/
│       ├── graph.py
│       ├── nodes/
│       │   ├── alert_intake.py
│       │   ├── diagnosis_node.py
│       │   ├── playbook_selector.py
│       │   ├── approval_gate.py
│       │   ├── execution_node.py
│       │   └── verification_node.py
│       └── playbooks/
│           ├── network/
│           │   ├── recover_link.yaml
│           │   ├── rollback_config.yaml
│           │   └── restart_interface.yaml
│           ├── server/
│           │   ├── restart_service.yaml
│           │   ├── clear_disk.yaml
│           │   ├── reboot_server.yaml
│           │   └── patch_system.yaml
│           └── security/
│               ├── block_ip.yaml
│               ├── isolate_host.yaml
│               └── reset_credentials.yaml
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── providers.tsx
│   │   │   └── routes.tsx
│   │   ├── features/
│   │   │   ├── noc/
│   │   │   │   ├── components/
│   │   │   │   │   ├── NetworkTopology.tsx
│   │   │   │   │   ├── DeviceTable.tsx
│   │   │   │   │   ├── AlertPanel.tsx
│   │   │   │   │   ├── BandwidthChart.tsx
│   │   │   │   │   └── DeviceDetail.tsx
│   │   │   │   ├── hooks/
│   │   │   │   └── store/
│   │   │   ├── soc/
│   │   │   │   ├── components/
│   │   │   │   │   ├── ThreatTimeline.tsx
│   │   │   │   │   ├── IncidentManager.tsx
│   │   │   │   │   ├── UEBADashboard.tsx
│   │   │   │   │   ├── MitreHeatmap.tsx
│   │   │   │   │   └── ThreatIntelPanel.tsx
│   │   │   │   ├── hooks/
│   │   │   │   └── store/
│   │   │   ├── server/
│   │   │   │   ├── components/
│   │   │   │   │   ├── ServerGrid.tsx
│   │   │   │   │   ├── VMInventory.tsx
│   │   │   │   │   ├── PatchStatus.tsx
│   │   │   │   │   └── ServiceHealth.tsx
│   │   │   │   ├── hooks/
│   │   │   │   └── store/
│   │   │   ├── physec/
│   │   │   │   ├── components/
│   │   │   │   │   ├── CameraGrid.tsx
│   │   │   │   │   ├── FloorPlan.tsx
│   │   │   │   │   ├── EventFeed.tsx
│   │   │   │   │   └── SecurityRiskMap.tsx
│   │   │   │   ├── hooks/
│   │   │   │   └── store/
│   │   │   ├── ai-chat/
│   │   │   │   └── components/
│   │   │   │       ├── ChatInterface.tsx
│   │   │   │       └── ContextPanel.tsx
│   │   │   ├── reports/
│   │   │   ├── compliance/
│   │   │   └── admin/
│   │   ├── shared/
│   │   │   ├── components/
│   │   │   │   ├── ui/
│   │   │   │   ├── charts/
│   │   │   │   └── layout/
│   │   │   ├── hooks/
│   │   │   ├── store/
│   │   │   ├── api/
│   │   │   └── types/
│   │   └── main.tsx
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── ai-models/
│   ├── configs/
│   │   ├── ollama_models.yaml
│   │   └── vllm_config.yaml
│   ├── modelfiles/
│   │   ├── Modelfile.noc-assistant
│   │   ├── Modelfile.soc-analyst
│   │   └── Modelfile.rag-assistant
│   └── fine-tuning/
│       ├── datasets/
│       └── scripts/
│
├── data/
│   ├── migrations/
│   │   ├── postgresql/
│   │   └── timescaledb/
│   ├── seeds/
│   │   ├── device_types.sql
│   │   ├── compliance_rules.sql
│   │   └── mitre_attack.sql
│   └── schemas/
│       ├── postgresql_schema.sql
│       ├── elasticsearch_mappings.json
│       └── qdrant_collections.json
│
├── collectors/
│   ├── snmp/
│   │   ├── snmp_poller.py
│   │   └── mib_loader.py
│   ├── syslog/
│   │   └── syslog_server.py
│   ├── netflow/
│   │   └── netflow_collector.py
│   └── agents/
│       ├── linux_agent/
│       │   ├── main.py
│       │   └── install.sh
│       └── windows_agent/
│           ├── main.py
│           └── install.ps1
│
├── mcp/
│   ├── servers/
│   │   ├── network_mcp_server.py
│   │   ├── security_mcp_server.py
│   │   └── server_ops_mcp_server.py
│   └── tools/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── operations/
│   └── runbooks/
│
├── scripts/
│   ├── setup/
│   ├── maintenance/
│   └── migration/
│
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── grafana/
│   │   └── dashboards/
│   ├── alertmanager/
│   │   └── alertmanager.yml
│   └── loki/
│       └── loki-config.yml
│
├── docker-compose.yml
├── docker-compose.prod.yml
├── docker-compose.dev.yml
├── Makefile
├── .env.example
└── README.md
```
