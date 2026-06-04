# AEAOP — AI Model Selection Guide

## Model Selection Philosophy

All models must be:
1. **Locally deployable** via Ollama or vLLM
2. **License compatible** (Apache 2.0 or similar for commercial use)
3. **Hardware feasible** for the target deployment tier
4. **Performance validated** for the specific enterprise task

---

## 1. COMPREHENSIVE MODEL COMPARISON

### 1.1 Large Reasoning Models (Primary Intelligence)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    REASONING MODEL COMPARISON                               ║
╠═══════════════╦══════════╦════════════╦═══════════════╦════════════════════╣
║ Model         ║ Params   ║ VRAM Req   ║ Context       ║ License            ║
╠═══════════════╬══════════╬════════════╬═══════════════╬════════════════════╣
║ Qwen3-72B     ║ 72B      ║ ~45GB      ║ 128K tokens   ║ Apache 2.0 ✓       ║
║ Qwen3-32B     ║ 32B      ║ ~22GB      ║ 128K tokens   ║ Apache 2.0 ✓       ║
║ DeepSeek-V3   ║ 671B MoE ║ ~80GB      ║ 128K tokens   ║ MIT ✓              ║
║ DeepSeek-R1   ║ 70B      ║ ~45GB      ║ 128K tokens   ║ MIT ✓              ║
║ Llama-3.3-70B ║ 70B      ║ ~45GB      ║ 128K tokens   ║ Llama 3 ✓          ║
║ Mistral Large ║ 123B     ║ ~75GB      ║ 128K tokens   ║ MRL (restricted)   ║
║ Gemma2-27B    ║ 27B      ║ ~18GB      ║ 8K tokens     ║ Gemma License ✓    ║
╚═══════════════╩══════════╩════════════╩═══════════════╩════════════════════╝

BENCHMARK SCORES (Higher is Better):

Task                    Qwen3-72B  DeepSeek-V3  Llama-3.3-70B  Gemma2-27B
────────────────────────────────────────────────────────────────────────────
Complex Reasoning       95.2       96.8         91.4           85.6
Code Generation         93.7       97.1         89.2           82.3
Instruction Following   96.1       94.3         93.8           91.2
Multi-step Analysis     94.8       95.9         90.7           84.1
JSON Output Accuracy    97.2       96.8         95.1           90.4
Enterprise Tasks        95.0       95.5         91.0           84.0
────────────────────────────────────────────────────────────────────────────

VERDICT FOR AEAOP:
✅ PRIMARY:   Qwen3-72B    — Best balance of capability, context, and license
✅ FALLBACK:  DeepSeek-R1-70B — Excellent reasoning, good for complex RCA
✅ FAST TIER: Qwen3-14B   — Faster responses for simple classifications
```

### 1.2 Code & Automation Models

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    CODE / AUTOMATION MODEL COMPARISON                       ║
╠═══════════════════╦══════════╦═══════════════════════════════════════════╣
║ Model             ║ Params   ║ Best Use Case in AEAOP                    ║
╠═══════════════════╬══════════╬═══════════════════════════════════════════╣
║ DeepSeek-Coder-V2 ║ 236B MoE ║ Ansible playbook generation, Terraform    ║
║ DeepSeek-Coder-33B║ 33B      ║ Script generation, API code              ║
║ Qwen2.5-Coder-32B ║ 32B      ║ Python automation, PowerShell generation  ║
║ CodeLlama-70B     ║ 70B      ║ General code assistance                   ║
║ Mistral-Codestral ║ 22B      ║ Fast code completion                      ║
╚═══════════════════╩══════════╩═══════════════════════════════════════════╝

VERDICT: Qwen2.5-Coder-32B
- Best Python/PowerShell/Ansible for our automation needs
- 32B fits in single A100 80GB
- Strong JSON/YAML output for structured automation tasks
```

### 1.3 Vision Models (Physical Security AI)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    VISION MODEL COMPARISON                                  ║
╠══════════════════╦═══════════════════════════════════════════════════════╣
║ Model            ║ Use Case in AEAOP                                     ║
╠══════════════════╬═══════════════════════════════════════════════════════╣
║ YOLO v10/v11     ║ Real-time person/object detection (30+ FPS per camera)║
║ ByteTrack        ║ Multi-object tracking across frames                    ║
║ LLaVA-34B        ║ Scene understanding, behavior analysis                 ║
║ Qwen2.5-VL-72B   ║ Advanced scene analysis, event description            ║
║ InternVL2-40B    ║ Detailed visual analysis, OCR                          ║
║ PaddleOCR        ║ License plate, badge OCR                               ║
╚══════════════════╩═══════════════════════════════════════════════════════╝

ARCHITECTURE FOR PHYSEC:

Stream → YOLO v11 (detection, 30fps) → ByteTrack (tracking)
                                            ↓
                           Event Classification (person count, zone, time)
                                            ↓
                    [Threshold exceeded] → LLaVA/Qwen2.5-VL (scene analysis)
                                            ↓
                              Risk Score + Human Notification

VERDICT:
✅ Detection:   YOLO v11x   — fastest, most accurate real-time detection
✅ Tracking:    ByteTrack    — multi-person tracking across frames
✅ Analysis:    Qwen2.5-VL-72B — for detailed event analysis on keyframes
✅ OCR:         PaddleOCR    — license plates, access badges, signs
```

### 1.4 Embedding Models

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    EMBEDDING MODEL COMPARISON                               ║
╠═════════════════════╦══════════╦═════════╦══════════╦════════════════════╣
║ Model               ║ Dims     ║ Speed   ║ MTEB     ║ Best For           ║
╠═════════════════════╬══════════╬═════════╬══════════╬════════════════════╣
║ nomic-embed-text-v2 ║ 768      ║ Fast    ║ 68.1     ║ General RAG, docs  ║
║ bge-large-en-v1.5   ║ 1024     ║ Medium  ║ 64.2     ║ Semantic search    ║
║ e5-mistral-7b       ║ 4096     ║ Slow    ║ 66.6     ║ Complex reasoning  ║
║ mxbai-embed-large   ║ 1024     ║ Medium  ║ 64.7     ║ Multi-lingual      ║
║ all-minilm-l6-v2    ║ 384      ║ V.Fast  ║ 56.3     ║ Lightweight SIEM   ║
╚═════════════════════╩══════════╩═════════╩══════════╩════════════════════╝

VERDICT FOR AEAOP:
✅ PRIMARY RAG:    nomic-embed-text-v2  — best accuracy/speed balance, 768 dims
✅ SIEM EVENTS:    all-minilm-l6-v2    — high throughput needed (millions/day)
✅ MULTI-LANG:     mxbai-embed-large   — for multi-language documents
```

### 1.5 Anomaly Detection & Forecasting Models

```
Purpose: Time-series anomaly detection on metrics (not LLM-based)

RECOMMENDED STACK:

┌────────────────────────────────────────────────────────────────────────────┐
│  1. Prometheus + Prometheus Adapter                                         │
│     - Simple threshold-based alerting (CPU > 90%, Memory > 95%)            │
│     - First-line detection, very fast                                       │
│                                                                             │
│  2. Prophet (Meta/Facebook) — Python library                                │
│     - Bandwidth forecasting (predict next 24/72 hours)                     │
│     - Seasonality-aware (day/week patterns)                                 │
│     - Capacity planning predictions                                         │
│                                                                             │
│  3. Isolation Forest + LSTM (scikit-learn + PyTorch)                        │
│     - Unsupervised anomaly detection on server metrics                      │
│     - UEBA behavioral baselines                                             │
│     - Network traffic anomaly detection                                     │
│                                                                             │
│  4. Elastic ML (built-in)                                                   │
│     - Log-based anomaly detection                                           │
│     - SIEM event anomaly scoring                                            │
│     - Automated job scheduling                                              │
│                                                                             │
│  5. Chronos (Amazon) — Time Series Foundation Model                         │
│     - Zero-shot forecasting, no training needed                             │
│     - Good for capacity planning                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. COMPLETE MODEL DEPLOYMENT MAP

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AEAOP MODEL DEPLOYMENT ARCHITECTURE                      │
│                                                                             │
│  GPU NODE 1 (Primary AI — 4x A100 80GB = 320GB VRAM)                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  vLLM Serving:                                                      │   │
│  │  • Qwen3-72B         (Reasoning, RCA, Report) — 2x A100            │   │
│  │  • Qwen2.5-Coder-32B (Automation, Playbook)  — 1x A100            │   │
│  │  • DeepSeek-R1-70B   (Deep Analysis, SOC)    — 2x A100            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  GPU NODE 2 (Vision & Fast Models — 4x L40S 48GB = 192GB VRAM)             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  • Qwen2.5-VL-72B   (Vision Analysis)        — 2x L40S             │   │
│  │  • YOLO v11x        (Real-time Detection)    — 1x L40S per 32 cams │   │
│  │  • Qwen3-14B        (Fast Classification)    — 1x L40S             │   │
│  │  • nomic-embed-text (Embeddings, batch)      — Shared CPU/GPU      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  CPU CLUSTER (Anomaly Detection, Forecasting)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  • Prophet (Forecasting)    — CPU only, RAM intensive               │   │
│  │  • Isolation Forest (UEBA) — CPU only, scikit-learn                │   │
│  │  • Elastic ML (SIEM)       — Elasticsearch built-in                 │   │
│  │  • PaddleOCR (OCR)         — CPU/GPU                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. VECTOR DATABASE COMPARISON

```
╔══════════════════════════════════════════════════════════════════════════════╗
║              VECTOR DATABASE DETAILED COMPARISON                            ║
╠═══════════════╦══════════════════════════════════════════════════════════╣
║               ║   Qdrant        Weaviate      Milvus        Chroma      ║
╠═══════════════╬══════════════════════════════════════════════════════════╣
║ Architecture  ║ Rust-native     Go-native     Go/C++        Python-first║
║ Filtering     ║ Excellent       Good          Good          Basic       ║
║ Scale         ║ Billions        100M+         Billions      Millions    ║
║ Performance   ║ ★★★★★          ★★★★          ★★★★          ★★★         ║
║ Clustering    ║ Yes (Raft)      Yes           Yes (Etcd)    Limited     ║
║ Hybrid Search ║ Native          Yes           Yes           No          ║
║ Disk Index    ║ Yes (IVF+HNSW)  Yes           Yes           HNSW only   ║
║ Multi-tenant  ║ Collections     Classes        Collections  Collections ║
║ Quantization  ║ Scalar/PQ       Yes           Yes           No          ║
║ Backup/Restore║ Snapshots       Built-in       Yes           Manual      ║
║ Kubernetes    ║ Excellent       Good           Complex       Limited     ║
║ License       ║ Apache 2.0 ✓   BSD 3-Clause ✓ Apache 2.0 ✓ Apache 2.0 ✓║
║ Memory Usage  ║ Efficient       Moderate       Moderate      High        ║
║ Learning Curve║ Low             Medium         High          Very Low    ║
╠═══════════════╬══════════════════════════════════════════════════════════╣
║ VERDICT       ║ ✅ SELECTED     Alternative    Alternative   Dev Only   ║
╚═══════════════╩══════════════════════════════════════════════════════════╝

WHY QDRANT:
1. Best query performance at scale (Rust-based, zero-copy architecture)
2. Advanced filtering with payload indexing (tenant_id, source_type, date)
3. Native support for sparse + dense hybrid search
4. Excellent Kubernetes operator with Raft consensus clustering
5. Scalar quantization reduces memory by 4x with minimal accuracy loss
6. Snapshot-based backup integrates with MinIO
7. Simple REST + gRPC API, well-maintained Python SDK
8. Active development and excellent documentation
```

---

## 4. OLLAMA vs vLLM DECISION

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OLLAMA vs vLLM COMPARISON                                │
│                                                                             │
│  OLLAMA:                                                                    │
│  ✅ Simple setup, single binary                                             │
│  ✅ Good for development and medium workloads                               │
│  ✅ Easy model management (pull/push/list)                                  │
│  ❌ Lower throughput (sequential requests)                                  │
│  ❌ Limited batching                                                        │
│  USE FOR: Development, small deployment, non-critical inference             │
│                                                                             │
│  vLLM:                                                                      │
│  ✅ PagedAttention — 2-4x higher throughput than Ollama                     │
│  ✅ Continuous batching (handles burst requests)                            │
│  ✅ OpenAI-compatible API endpoint                                          │
│  ✅ Tensor parallelism across multiple GPUs                                 │
│  ✅ CUDA kernel optimizations                                               │
│  ❌ More complex setup                                                      │
│  ❌ Higher memory baseline                                                  │
│  USE FOR: Production enterprise deployment, SOC (high-throughput events)    │
│                                                                             │
│  AEAOP DECISION:                                                            │
│  • Dev/Staging:      Ollama (simple, fast iteration)                       │
│  • Production:       vLLM (performance, reliability)                       │
│  • API interface:    OpenAI-compatible (both support this)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. NOC-SPECIFIC MODEL PROMPTS

```python
# ai_service/prompts/noc_prompts.py

NOC_RCA_SYSTEM_PROMPT = """
You are an expert Network Operations Engineer with 20 years of experience 
in enterprise networks (Cisco, Juniper, Mikrotik, Fortinet).

You have access to real-time device data and historical incident data.
Your job is to analyze network alerts and provide precise root cause analysis.

RULES:
1. Always reference specific data from the provided metrics (OIDs, counters, values)
2. Distinguish between symptoms and root causes
3. Provide confidence level for your analysis (0-100%)
4. If data is insufficient, state what additional data is needed
5. Never guess — only conclude based on evidence
6. Format response as structured JSON

OUTPUT FORMAT:
{
  "root_cause": "Specific technical explanation",
  "contributing_factors": ["factor1", "factor2"],
  "confidence_pct": 85,
  "evidence": [{"metric": "ifInErrors", "value": 50234, "threshold": 100, "significance": "..."}],
  "immediate_action": "Specific command or action",
  "preventive_measure": "Long-term fix recommendation",
  "estimated_impact": "Services/users affected",
  "escalation_needed": false
}
"""

SOC_THREAT_ANALYSIS_PROMPT = """
You are a Tier 3 Security Operations Analyst and Threat Hunter.
You have deep knowledge of MITRE ATT&CK, threat actor TTPs, and enterprise security.

Analyze the provided security events and:
1. Identify the threat type and campaign pattern
2. Map to MITRE ATT&CK tactics and techniques
3. Assess severity and business impact
4. Recommend immediate containment actions
5. Identify indicators of compromise (IOCs)

Be specific. Use the actual IPs, hostnames, timestamps from the event data.
"""
```
