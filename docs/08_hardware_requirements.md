# AEAOP — Hardware Requirements (All Deployment Tiers)

---

## DEPLOYMENT TIER OVERVIEW

```
┌────────────────────────────────────────────────────────────────────────────┐
│  TIER 1: SMALL      │  Up to 50 devices, 5 cameras, 50 servers            │
│  TIER 2: MEDIUM     │  Up to 500 devices, 50 cameras, 500 servers          │
│  TIER 3: ENTERPRISE │  Up to 5,000 devices, 200 cameras, 2,000 servers    │
│  TIER 4: BANK SCALE │  10,000+ devices, 1,000+ cameras, 5,000+ servers    │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## TIER 1: SMALL DEPLOYMENT

**Use Case:** Branch office, small enterprise, proof of concept

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SMALL DEPLOYMENT — BILL OF MATERIALS                                       │
├────────────────────────────────────────────────────────────────────────────┤
│  NODE 1: AI + APPLICATION SERVER                                           │
│  ─────────────────────────────────────────────────────────────────────────│
│  CPU:     AMD EPYC 9354 or Intel Xeon Gold 6434H (32 cores / 64 threads)  │
│  RAM:     256 GB DDR5 ECC (8x 32GB)                                        │
│  GPU:     2x NVIDIA RTX 4090 (24GB VRAM each = 48GB total)                │
│           OR 1x NVIDIA A100 40GB (preferred for AI inference)              │
│  Storage: 2x 2TB NVMe SSD (OS + Apps) — RAID 1                            │
│           4x 4TB SAS HDD (Data) — RAID 10                                 │
│  NIC:     2x 10GbE (management + data)                                    │
│  Power:   2x 800W PSU (redundant)                                          │
│  Form:    2U Rackmount                                                     │
│                                                                            │
│  RUNS:    Ollama (Qwen3-14B for AI), All FastAPI services,                │
│           PostgreSQL, TimescaleDB, Redis, Qdrant, Elasticsearch           │
│                                                                            │
│  ESTIMATED HARDWARE COST: $8,000 – $15,000 USD                            │
│                                                                            │
│  CAPACITY:                                                                 │
│  • AI Model: Qwen3-14B (14B params, fits in RTX 4090)                     │
│  • Handles: 50 devices, 10 cameras, 50 servers                            │
│  • SIEM: 100K events/day                                                   │
│  • Concurrent users: Up to 20                                              │
├────────────────────────────────────────────────────────────────────────────┤
│  NODE 2: COLLECTOR + MONITORING (Optional for small)                       │
│  ─────────────────────────────────────────────────────────────────────────│
│  CPU:     Intel Core i9-13900 or AMD Ryzen 9 7950X (16 cores)             │
│  RAM:     64 GB DDR5                                                       │
│  Storage: 2x 2TB NVMe SSD — RAID 1                                        │
│  NIC:     2x 10GbE                                                        │
│  RUNS:    Prometheus, Grafana, Syslog, NetFlow, SNMP collectors           │
│  COST:    $2,000 – $4,000 USD                                              │
└────────────────────────────────────────────────────────────────────────────┘

TOTAL TIER 1 COST: $10,000 – $20,000 USD (hardware only)
POWER CONSUMPTION: ~800W average
RACK SPACE: 4U
```

---

## TIER 2: MEDIUM DEPLOYMENT

**Use Case:** Regional office, ISP edge, mid-size enterprise, datacenter pod

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MEDIUM DEPLOYMENT — CLUSTER DESIGN                                         │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  AI GPU SERVER (1x) — PRIMARY INTELLIGENCE                                │
│  ─────────────────────────────────────────────────────────────────────────│
│  CPU:     2x AMD EPYC 9354 (64 cores total / 128 threads)                 │
│  RAM:     512 GB DDR5 ECC (16x 32GB)                                      │
│  GPU:     4x NVIDIA A100 80GB SXM (320GB total VRAM)                      │
│           Connected via NVLink                                             │
│  Storage: 4x 3.84TB NVMe SSD (OS + Model storage) — RAID 10              │
│  NIC:     2x 25GbE + 1x InfiniBand HDR (for GPU interconnect)            │
│  Form:    4U (DGX-style or custom GPU server)                             │
│  Cost:    $80,000 – $150,000 USD                                           │
│                                                                            │
│  RUNS:    vLLM serving Qwen3-72B + DeepSeek-R1-70B                       │
│           YOLO vision pipeline (handles 50 cameras)                       │
│                                                                            │
│  APPLICATION SERVERS (3x HA Cluster)                                      │
│  ─────────────────────────────────────────────────────────────────────────│
│  Per Node:                                                                 │
│  CPU:     2x Intel Xeon Gold 6434H (32 cores / 64 threads)               │
│  RAM:     256 GB DDR5 ECC                                                 │
│  Storage: 2x 1.92TB NVMe (OS + App) — RAID 1                             │
│  NIC:     2x 25GbE                                                        │
│  Form:    2U Rackmount                                                    │
│  Cost:    $12,000 – $18,000 per node = $36,000 – $54,000                  │
│  RUNS:    Kubernetes workers, FastAPI services, Kafka                     │
│                                                                            │
│  DATABASE SERVERS (2x HA Cluster)                                         │
│  ─────────────────────────────────────────────────────────────────────────│
│  Per Node:                                                                 │
│  CPU:     2x AMD EPYC 9274F (24 cores / 48 threads)                      │
│  RAM:     512 GB DDR5 ECC                                                 │
│  Storage: 4x 7.68TB NVMe SSD (Data) — RAID 10                            │
│           2x 960GB NVMe SSD (WAL/Redo logs) — RAID 1                     │
│  NIC:     2x 25GbE                                                        │
│  Form:    2U Rackmount                                                    │
│  Cost:    $25,000 – $40,000 per node = $50,000 – $80,000                  │
│  RUNS:    PostgreSQL primary/replica, TimescaleDB, Redis cluster          │
│                                                                            │
│  ELASTICSEARCH NODES (3x cluster)                                         │
│  Per Node:                                                                 │
│  CPU:     2x Intel Xeon Silver 4416+ (20 cores / 40 threads)             │
│  RAM:     256 GB DDR5 ECC                                                 │
│  Storage: 8x 7.68TB SAS SSD (hot data)                                   │
│           12x 16TB SAS HDD (warm/cold data)                               │
│  NIC:     2x 25GbE                                                        │
│  Form:    4U Rackmount                                                    │
│  Cost:    $20,000 – $30,000 per node = $60,000 – $90,000                  │
│  RUNS:    Elasticsearch cluster, Kibana, Logstash                        │
│                                                                            │
│  STORAGE SERVER (1x)                                                      │
│  CPU:     1x AMD EPYC 9124 (16 cores)                                    │
│  RAM:     128 GB DDR5 ECC                                                 │
│  Storage: 24x 16TB SAS HDD (RAID-6) = ~300TB usable                      │
│  NIC:     2x 25GbE                                                        │
│  Form:    4U Rackmount                                                    │
│  Cost:    $15,000 – $25,000 USD                                            │
│  RUNS:    MinIO Object Storage (config backups, video, reports)           │
│                                                                            │
│  NETWORK INFRASTRUCTURE                                                   │
│  ─────────────────────────────────────────────────────────────────────────│
│  Core Switch:   Cisco Nexus 9300 or Arista 7050X3 (25GbE leaf)           │
│  ToR Switches:  2x 48-port 25GbE switches (top-of-rack)                  │
│  Firewall:      Fortinet FG-600F or Palo Alto PA-3430                    │
│  NIC Cost:      $30,000 – $60,000 USD                                     │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

TOTAL TIER 2 HARDWARE COST: $280,000 – $480,000 USD
TOTAL POWER: ~15–20 kW
RACK SPACE: 3–4 full 42U racks
CAPACITY:
  • Devices: 500, Cameras: 50, Servers: 500
  • SIEM: 10M events/day
  • Concurrent users: 200
  • AI throughput: 50 requests/second
```

---

## TIER 3: ENTERPRISE DEPLOYMENT

**Use Case:** Large enterprise HQ, ISP core, full data center

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ENTERPRISE DEPLOYMENT — FULL HA DESIGN                                    │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  AI GPU CLUSTER (2x nodes for HA)                                         │
│  ─────────────────────────────────────────────────────────────────────────│
│  Per Node:                                                                 │
│  CPU:     2x AMD EPYC 9654 (96 cores / 192 threads per node)             │
│  RAM:     1 TB DDR5 ECC (16x 64GB)                                        │
│  GPU:     8x NVIDIA H100 80GB SXM5 (640GB VRAM)                          │
│           Connected via NVSwitch + InfiniBand NDR                         │
│  NVMe:    8x 7.68TB NVMe Gen5 SSD                                         │
│  NIC:     4x 100GbE + InfiniBand NDR 200Gbps                             │
│  Form:    8U (NVIDIA DGX H100 or equivalent)                              │
│  Per Node Cost: $300,000 – $500,000 USD                                   │
│  2x Nodes Total: $600,000 – $1,000,000 USD                                │
│                                                                            │
│  RUNS: Full model suite at maximum performance                            │
│  Capacity: 200 cameras, 5,000 concurrent events, 200 req/sec AI          │
│                                                                            │
│  APPLICATION CLUSTER (6x nodes — Kubernetes)                              │
│  ─────────────────────────────────────────────────────────────────────────│
│  Per Node:                                                                 │
│  CPU:     2x AMD EPYC 9654 (96 cores / 192 threads)                      │
│  RAM:     512 GB DDR5 ECC                                                 │
│  Storage: 4x 3.84TB NVMe SSD                                              │
│  NIC:     2x 100GbE                                                       │
│  Cost:    $40,000 – $60,000 per node = $240,000 – $360,000               │
│                                                                            │
│  DATABASE CLUSTER (6x nodes — 3 primary/replica pairs)                   │
│  ─────────────────────────────────────────────────────────────────────────│
│  Per Node:                                                                 │
│  CPU:     2x AMD EPYC 9754 (128 cores / 256 threads)                     │
│  RAM:     1 TB DDR5 ECC                                                   │
│  NVMe:    8x 7.68TB NVMe Gen5 SSD (RAID 10)                              │
│  NIC:     2x 100GbE                                                       │
│  Cost:    $60,000 – $80,000 per node = $360,000 – $480,000               │
│                                                                            │
│  ELASTICSEARCH CLUSTER (9x nodes — 3 hot + 3 warm + 3 cold)             │
│  ─────────────────────────────────────────────────────────────────────────│
│  Hot Nodes (3x):  256GB RAM, 8x 7.68TB NVMe SSD                          │
│  Warm Nodes (3x): 128GB RAM, 16x 16TB SAS SSD                            │
│  Cold Nodes (3x): 64GB RAM, 24x 20TB SAS HDD                             │
│  Cost: $200,000 – $300,000 total                                          │
│                                                                            │
│  OBJECT STORAGE CLUSTER — MinIO (4x nodes)                               │
│  Per Node:                                                                 │
│  CPU:     2x Intel Xeon Gold 6438N (32 cores)                            │
│  RAM:     256 GB DDR5 ECC                                                 │
│  Storage: 24x 20TB SAS HDD = 480TB per node                              │
│  NIC:     2x 100GbE                                                       │
│  Total:   ~1.5 PB raw storage (~1 PB usable)                             │
│  Cost:    $80,000 – $120,000 total                                        │
│                                                                            │
│  NETWORK INFRASTRUCTURE                                                   │
│  ─────────────────────────────────────────────────────────────────────────│
│  Spine:    2x Cisco Nexus 9508 (400GbE spine)                            │
│  Leaf:     8x Arista 7050X3 (100GbE leaf, 48-port)                       │
│  Firewall: 2x Palo Alto PA-5450 (HA pair, 100Gbps)                       │
│  IDS/IPS:  2x Cisco FMC 1600 cluster                                     │
│  NIC Cost: $500,000 – $800,000 USD                                        │
│                                                                            │
│  OUT-OF-BAND MANAGEMENT                                                   │
│  ─────────────────────────────────────────────────────────────────────────│
│  IPMI/iDRAC management network (separate 1GbE)                            │
│  Dedicated OOB switch: 1x 48-port managed                                │
│  Console server: 1x 48-port console server                               │
│  KVM-over-IP: Per rack                                                    │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

TOTAL TIER 3 HARDWARE COST: $2,500,000 – $4,000,000 USD
TOTAL POWER: ~100–150 kW
RACK SPACE: 12–16 full 42U racks
CAPACITY:
  • Devices: 5,000, Cameras: 200, Servers: 2,000
  • SIEM: 100M events/day
  • Concurrent users: 1,000
  • AI throughput: 500+ requests/second
```

---

## TIER 4: BANK-SCALE DEPLOYMENT

**Use Case:** National bank HQ + DR site, ISP national backbone, hyperscale datacenter

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BANK-SCALE DEPLOYMENT — DUAL SITE HA + DR                                 │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  PRIMARY SITE (MAIN DATA CENTER)                                           │
│  ═══════════════════════════════════════════════════════════════════════  │
│                                                                            │
│  AI GPU FARM (8x H100 nodes)                                              │
│  ─────────────────────────────────────────────────────────────────────────│
│  Per Node: 8x H100 80GB SXM5 = 640GB VRAM                               │
│  Total:    8 nodes × 640GB = 5,120GB GPU VRAM                            │
│  RAM:      1 TB per node × 8 = 8 TB total                               │
│  NVMe:     8x 15.36TB NVMe per node = 983TB total NVMe                  │
│  Interconnect: NDR InfiniBand 400Gbps fat-tree fabric                   │
│  Cost:     $3,000,000 – $5,000,000 USD                                   │
│                                                                            │
│  RUNS: Multiple concurrent LLMs, 1,000+ cameras, real-time SIEM         │
│        Dedicated model instances per tenant (Bank isolation)             │
│                                                                            │
│  APPLICATION CLUSTER (12x Kubernetes nodes)                               │
│  Per Node: 256 cores, 1 TB RAM, 8x 7.68TB NVMe                          │
│  Cost: $1,000,000 – $1,500,000 USD                                        │
│                                                                            │
│  DATABASE CLUSTER (12x nodes)                                             │
│  PostgreSQL: 4-node active/passive cluster (Patroni)                     │
│  TimescaleDB: 4-node multi-node distributed                               │
│  Redis: 6-node cluster (3 master + 3 replica)                            │
│  Per Node: 256 cores, 2 TB RAM, 12x 15.36TB NVMe SSD                   │
│  Cost: $1,500,000 – $2,500,000 USD                                        │
│                                                                            │
│  ELASTICSEARCH CLUSTER (24x nodes)                                        │
│  Hot:  6 nodes (NVMe SSD)                                                │
│  Warm: 6 nodes (SAS SSD)                                                 │
│  Cold: 6 nodes (SAS HDD)                                                 │
│  Frozen: 6 nodes (searchable snapshot on MinIO)                          │
│  Cost: $600,000 – $1,000,000 USD                                          │
│                                                                            │
│  OBJECT STORAGE — MinIO (12x nodes = 5+ PB usable)                      │
│  Cost: $400,000 – $600,000 USD                                            │
│                                                                            │
│  NETWORK FABRIC                                                           │
│  ─────────────────────────────────────────────────────────────────────────│
│  Core:     4x Cisco Nexus 9516 (400GbE, full mesh)                      │
│  Leaf:     32x Arista 7060CX (100GbE ToR, 64-port)                      │
│  Border:   4x Cisco ASR 9910 (internet/WAN routing)                     │
│  Security: 4x Palo Alto PA-7080 (1Tbps firewall cluster)                │
│  DDoS:     2x Arbor Networks APS4500 (BGP blackhole)                    │
│  Cost:     $3,000,000 – $5,000,000 USD                                   │
│                                                                            │
│  DR SITE (SECONDARY DATA CENTER — 80% capacity)                           │
│  ═══════════════════════════════════════════════════════════════════════  │
│  • 60–80% of primary capacity                                            │
│  • Active-passive for databases (synchronous replication)               │
│  • Active-active for AI inference (load distributed)                     │
│  • RPO: < 15 seconds   RTO: < 5 minutes                                  │
│  DR Site Cost: 70% of Primary = $8,000,000 – $12,000,000 USD            │
│                                                                            │
│  TOTAL BANK-SCALE HARDWARE: $18,000,000 – $28,000,000 USD               │
│                                                                            │
│  CAPACITY AT BANK SCALE:                                                  │
│  • Devices: 50,000+    • Cameras: 1,000+    • Servers: 10,000+          │
│  • SIEM: 1 BILLION events/day               • Users: 5,000 concurrent   │
│  • AI: 5,000+ requests/second               • Storage: 10+ PB           │
│  • Uptime SLA: 99.999% (Five 9s = 5 min downtime/year)                  │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## GPU SELECTION GUIDE

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    GPU SELECTION MATRIX FOR AI WORKLOADS                  │
├─────────────────┬─────────┬──────────┬──────────┬──────────┬────────────┤
│ GPU             │ VRAM    │ TFlops   │ Price    │ Best For │ Tier       │
├─────────────────┼─────────┼──────────┼──────────┼──────────┼────────────┤
│ RTX 4090        │ 24 GB   │ 82.6     │ $1,800   │ Dev/PoC  │ Tier 1     │
│ RTX 6000 Ada    │ 48 GB   │ 91.1     │ $6,800   │ Medium   │ Tier 1-2   │
│ L40S            │ 48 GB   │ 91.6     │ $8,000   │ Vision   │ Tier 2     │
│ A100 40GB PCIe  │ 40 GB   │ 77.6     │ $10,000  │ Inference│ Tier 2     │
│ A100 80GB SXM4  │ 80 GB   │ 77.6     │ $15,000  │ Large LLM│ Tier 2-3  │
│ H100 80GB SXM5  │ 80 GB   │ 989      │ $30,000  │ Prod AI  │ Tier 3-4  │
│ H100 80GB NVL   │ 80 GB   │ 989      │ $25,000  │ Prod AI  │ Tier 3-4  │
│ H200 141GB      │ 141 GB  │ 989      │ $50,000  │ LLM Farm │ Tier 4     │
├─────────────────┼─────────┼──────────┼──────────┼──────────┼────────────┤
│ MODEL FITS IN:  │         │          │          │          │            │
│ Qwen3-14B       │ ~10GB   │ Runs on  │ RTX 4090 │ RTX 4090 │ Any        │
│ Qwen3-32B       │ ~20GB   │ L40S     │          │          │            │
│ Qwen3-72B Q4    │ ~45GB   │ 2x A100  │ 2x 40GB  │          │ Tier 2+    │
│ Qwen3-72B FP16  │ ~144GB  │ 2x H100  │          │          │ Tier 3+    │
│ DeepSeek-V3 Q4  │ ~400GB  │ 5x H100  │          │          │ Tier 4     │
└─────────────────┴─────────┴──────────┴──────────┴──────────┴────────────┘

RECOMMENDATION:
For new deployments in 2026:
• Budget tier:    4x RTX 6000 Ada (total ~200GB VRAM, ~$28K)
• Mid tier:       4x NVIDIA L40S (same VRAM, datacenter-grade, ~$32K)
• Enterprise:     4x A100 80GB (320GB VRAM, proven at scale, ~$60K)
• Bank scale:     H100 clusters (maximum performance, enterprise support)
```

---

## STORAGE SIZING GUIDE

```
STORAGE REQUIREMENTS CALCULATION:

┌──────────────────────────────────────────────────────────────────────────────┐
│ Data Type          │ Per Device/Day   │ 500 devices │ 1 year retention    │
├──────────────────────────────────────────────────────────────────────────────┤
│ SNMP Metrics       │ ~100 MB/device   │ 50 GB/day   │ 18.25 TB/year      │
│ Syslog (per server)│ ~500 MB/server   │ 250 GB/day  │ 91 TB/year         │
│ NetFlow (1Gbps link│ ~50 MB/Gbps/hr   │ ~500 GB/day │ 182 TB/year        │
│ Config Backups     │ ~1 MB/device     │ 0.5 GB/day  │ 182 GB/year        │
│ Camera (RTSP 1080p)│ ~4 GB/cam/day    │ 200 GB/day  │ 73 TB/year         │
│ Report PDFs        │ Minimal          │ ~5 GB/day   │ 1.8 TB/year        │
│ AI Model Storage   │ Fixed            │ ~2 TB total │ Static             │
├──────────────────────────────────────────────────────────────────────────────┤
│ TOTALS (500 devices + 50 cameras)                                            │
│ Raw daily:  ~1 TB/day                                                       │
│ Year 1:     ~365 TB                                                         │
│ Year 3:     ~1.1 PB (with growth)                                          │
│                                                                              │
│ RECOMMENDATION: Start with 500 TB usable, plan for 2 PB at 3 years        │
└──────────────────────────────────────────────────────────────────────────────┘
```
