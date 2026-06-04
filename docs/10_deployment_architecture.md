# AEAOP — Deployment Architecture

## 1. KUBERNETES DEPLOYMENT ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AEAOP KUBERNETES CLUSTER LAYOUT                          │
│                                                                             │
│  NAMESPACES:                                                                │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐  │
│  │  aeaop-core     │ │  aeaop-ai       │ │  aeaop-data                 │  │
│  │  (Applications) │ │  (AI/ML)        │ │  (Databases)                │  │
│  │  ─────────────  │ │  ─────────────  │ │  ─────────────────────────  │  │
│  │  noc-service    │ │  vllm-server    │ │  postgresql-primary         │  │
│  │  soc-service    │ │  ollama         │ │  postgresql-replica         │  │
│  │  server-service │ │  vision-api     │ │  timescaledb                │  │
│  │  physec-service │ │  embedding-svc  │ │  elasticsearch-cluster      │  │
│  │  rag-service    │ │  anomaly-svc    │ │  redis-cluster              │  │
│  │  auth-service   │ │                 │ │  qdrant-cluster             │  │
│  │  report-service │ │                 │ │  minio-cluster              │  │
│  │  healing-svc    │ │                 │ │  kafka-cluster              │  │
│  └─────────────────┘ └─────────────────┘ └─────────────────────────────┘  │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐  │
│  │  aeaop-infra    │ │  aeaop-observe  │ │  aeaop-security             │  │
│  │  (Infrastructure│ │  (Monitoring)   │ │  (Security)                 │  │
│  │  ─────────────  │ │  ─────────────  │ │  ─────────────────────────  │  │
│  │  kong-gateway   │ │  prometheus     │ │  vault                      │  │
│  │  nginx-ingress  │ │  grafana        │ │  keycloak                   │  │
│  │  cert-manager   │ │  alertmanager   │ │  cert-manager               │  │
│  │  istio          │ │  loki           │ │  falco (runtime security)   │  │
│  │  velero (backup)│ │  tempo (traces) │ │  trivy (image scanning)     │  │
│  └─────────────────┘ └─────────────────┘ └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. KEY KUBERNETES MANIFESTS

### 2.1 NOC Service Deployment

```yaml
# infrastructure/kubernetes/deployments/noc-service.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: noc-service
  namespace: aeaop-core
  labels:
    app: noc-service
    version: "1.0"
    tier: application
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: noc-service
  template:
    metadata:
      labels:
        app: noc-service
        version: "1.0"
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8001"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: noc-service-sa
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
      - name: noc-service
        image: aeaop/noc-service:1.0.0
        ports:
        - containerPort: 8001
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: noc-service-url
        - name: VAULT_ADDR
          value: "https://vault.aeaop-security.svc.cluster.local:8200"
        - name: VAULT_ROLE
          value: "noc-service"
        - name: AI_SERVICE_URL
          value: "http://ai-service.aeaop-core.svc.cluster.local:8006"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8001
          initialDelaySeconds: 10
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8001
          initialDelaySeconds: 30
          periodSeconds: 10
        volumeMounts:
        - name: vault-token
          mountPath: /var/run/secrets/vault
          readOnly: true
      volumes:
      - name: vault-token
        projected:
          sources:
          - serviceAccountToken:
              path: vault-token
              expirationSeconds: 3600
              audience: vault
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: noc-service
---
apiVersion: v1
kind: Service
metadata:
  name: noc-service
  namespace: aeaop-core
spec:
  selector:
    app: noc-service
  ports:
  - port: 8001
    targetPort: 8001
  type: ClusterIP
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: noc-service-hpa
  namespace: aeaop-core
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: noc-service
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 2.2 vLLM AI Deployment

```yaml
# infrastructure/kubernetes/deployments/vllm-server.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-qwen3-72b
  namespace: aeaop-ai
spec:
  replicas: 1          # Scale via separate replicas on multiple GPU nodes
  selector:
    matchLabels:
      app: vllm-qwen3-72b
  template:
    metadata:
      labels:
        app: vllm-qwen3-72b
    spec:
      nodeSelector:
        accelerator: nvidia-a100    # Only schedule on GPU nodes
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        command:
        - python
        - -m
        - vllm.entrypoints.openai.api_server
        args:
        - --model=/models/qwen3-72b
        - --tensor-parallel-size=2       # Use 2 GPUs
        - --max-model-len=65536
        - --max-num-seqs=64
        - --gpu-memory-utilization=0.90
        - --enable-chunked-prefill
        - --disable-log-requests
        ports:
        - containerPort: 8000
          name: api
        resources:
          limits:
            nvidia.com/gpu: "2"          # Request 2 A100 GPUs
            memory: "128Gi"
            cpu: "16"
          requests:
            nvidia.com/gpu: "2"
            memory: "96Gi"
            cpu: "8"
        volumeMounts:
        - name: model-storage
          mountPath: /models
        - name: shm
          mountPath: /dev/shm
      volumes:
      - name: model-storage
        persistentVolumeClaim:
          claimName: ai-model-pvc
      - name: shm
        emptyDir:
          medium: Memory
          sizeLimit: "16Gi"
```

### 2.3 PostgreSQL HA with Patroni

```yaml
# Helm values for postgresql-ha
# infrastructure/helm-charts/aeaop-data/values.yaml

postgresql:
  replicaCount: 3                    # 1 primary + 2 replicas
  
  patroni:
    enabled: true
    failover:
      autoFailover: true
      maxLagOnFailover: 1048576      # 1MB lag threshold
    
  primary:
    resources:
      requests:
        cpu: "8"
        memory: "64Gi"
      limits:
        cpu: "16"
        memory: "128Gi"
    
    persistence:
      enabled: true
      storageClass: "fast-nvme"
      size: "2Ti"                    # 2TB NVMe per node
    
    postgresql:
      maxConnections: 1000
      sharedBuffers: "32GB"
      effectiveCacheSize: "96GB"
      maintenanceWorkMem: "2GB"
      walBuffers: "256MB"
      maxWalSize: "8GB"
      checkpointCompletionTarget: "0.9"
      randomPageCost: "1.1"          # For SSD storage

timescaledb:
  enabled: true
  image: timescale/timescaledb-ha:pg16-latest
  replicaCount: 2
  
  tune:
    timescaledb:
      maxChunkSize: "2GB"
    memory_budget_mb: 65536          # 64GB for TimescaleDB
```

---

## 3. HIGH AVAILABILITY DESIGN

```
HA STRATEGY PER COMPONENT:

┌──────────────────────────────────────────────────────────────────────────┐
│ Component         │ HA Method              │ Failover Time │ RPO        │
├──────────────────────────────────────────────────────────────────────────┤
│ FastAPI Services  │ K8s replicas (3+)      │ < 10 seconds  │ 0 (stat.)  │
│ API Gateway       │ K8s replicas (2+)      │ < 5 seconds   │ 0          │
│ PostgreSQL        │ Patroni (1+2 replicas) │ < 30 seconds  │ ~0 sync    │
│ TimescaleDB       │ Patroni + streaming    │ < 30 seconds  │ ~0 sync    │
│ Redis             │ Redis Sentinel (3 node)│ < 15 seconds  │ < 1 second │
│ Elasticsearch     │ 3-node cluster         │ < 60 seconds  │ < 5 seconds│
│ Kafka             │ 3-broker cluster       │ < 30 seconds  │ < 1 second │
│ Qdrant            │ 3-node Raft cluster    │ < 30 seconds  │ ~0 (Raft)  │
│ MinIO             │ 4-node erasure code    │ < 5 seconds   │ 0          │
│ Vault             │ Raft cluster (3 node)  │ < 30 seconds  │ ~0 (Raft)  │
│ Keycloak          │ Active-active (2 node) │ < 10 seconds  │ 0          │
│ vLLM AI           │ 2 node load balancing  │ < 60 seconds  │ N/A        │
│ Kong Gateway      │ K8s replicas (2+)      │ < 10 seconds  │ 0          │
│ Ingress           │ 2 replicas             │ < 10 seconds  │ 0          │
└──────────────────────────────────────────────────────────────────────────┘

OVERALL PLATFORM SLA:
  Target: 99.95% availability = 4.38 hours downtime/year
  Bank Tier: 99.999% = 5.26 minutes downtime/year
```

---

## 4. DISASTER RECOVERY

```yaml
# Velero backup configuration
# infrastructure/kubernetes/velero/schedule.yaml

apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: aeaop-daily-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"           # 2 AM daily
  template:
    includedNamespaces:
    - aeaop-core
    - aeaop-ai
    - aeaop-data
    - aeaop-security
    excludedResources:
    - pods
    - events
    storageLocation: minio-backup
    ttl: 720h                     # 30 days retention
    hooks:
      resources:
      - name: postgresql-backup
        includedNamespaces:
        - aeaop-data
        labelSelector:
          matchLabels:
            app: postgresql
        pre:
        - exec:
            container: postgresql
            command:
            - /bin/bash
            - -c
            - "pg_dump -U postgres aeaop > /backup/aeaop-$(date +%Y%m%d).sql"
            onError: Fail
            timeout: 30m
```

```
DR RUNBOOK SUMMARY:

SCENARIO 1: Single Node Failure
├── Detection: Kubernetes detects unhealthy node in < 30 seconds
├── Action: Pods rescheduled automatically to healthy nodes
└── Recovery: Automatic, no human intervention needed
Time: < 2 minutes

SCENARIO 2: Database Primary Failure
├── Detection: Patroni detects primary failure in < 10 seconds
├── Action: Automatic promotion of replica to primary
├── Application: Connection string updates via pgBouncer
└── Recovery: Automatic
Time: < 1 minute

SCENARIO 3: Full Site Failure
├── Detection: Monitoring alerts in < 5 minutes
├── Action: Manual or automated DNS failover to DR site
├── Database: DR site replicas promoted to primary
├── AI Models: Pre-loaded on DR site
└── Recovery: Manual/semi-automated
Time: < 15 minutes (RTO target)
RPO: < 1 minute (async replication)

SCENARIO 4: Ransomware/Cyber Attack
├── Detection: SOC agent detects attack pattern
├── Immediate: Isolate affected segments (network microsegmentation)
├── Preserve: Activate legal hold, preserve evidence
├── Restore: Roll back to last clean backup (Velero)
└── Recovery: Restore from offline air-gapped backup
Time: 4–24 hours depending on scope
```

---

## 5. DOCKER COMPOSE (Development)

```yaml
# docker-compose.dev.yml

version: "3.9"

services:
  # ── Core Services ──────────────────────────────────────────────────────────
  noc-service:
    build: ./backend/services/noc_service
    ports: ["8001:8001"]
    environment:
      - DATABASE_URL=postgresql://aeaop:secret@postgres:5432/aeaop_dev
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_BOOTSTRAP=kafka:9092
      - AI_SERVICE_URL=http://ai-service:8006
      - VAULT_ADDR=http://vault:8200
    depends_on: [postgres, redis, kafka, ai-service]
    volumes:
      - ./backend/services/noc_service:/app
    command: uvicorn main:app --reload --host 0.0.0.0 --port 8001

  soc-service:
    build: ./backend/services/soc_service
    ports: ["8002:8002"]
    environment:
      - DATABASE_URL=postgresql://aeaop:secret@postgres:5432/aeaop_dev
      - ELASTICSEARCH_URL=http://elasticsearch:9200
      - KAFKA_BOOTSTRAP=kafka:9092
    depends_on: [postgres, elasticsearch, kafka]

  ai-service:
    build: ./backend/services/ai_service
    ports: ["8006:8006"]
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - VLLM_BASE_URL=http://vllm:8000
    depends_on: [ollama]

  # ── AI Models ──────────────────────────────────────────────────────────────
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama_models:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]

  # ── Databases ──────────────────────────────────────────────────────────────
  postgres:
    image: timescale/timescaledb-ha:pg16-latest
    environment:
      POSTGRES_DB: aeaop_dev
      POSTGRES_USER: aeaop
      POSTGRES_PASSWORD: secret
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./data/migrations/postgresql:/docker-entrypoint-initdb.d
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    ports: ["6379:6379"]

  elasticsearch:
    image: elasticsearch:8.13.0
    environment:
      discovery.type: single-node
      ES_JAVA_OPTS: -Xms4g -Xmx4g
      xpack.security.enabled: "false"
    volumes:
      - es_data:/usr/share/elasticsearch/data
    ports: ["9200:9200"]

  kibana:
    image: kibana:8.13.0
    environment:
      ELASTICSEARCH_HOSTS: http://elasticsearch:9200
    ports: ["5601:5601"]

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant_data:/qdrant/storage
    ports: ["6333:6333"]

  # ── Message Bus ──────────────────────────────────────────────────────────
  zookeeper:
    image: confluentinc/cp-zookeeper:7.6.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    depends_on: [zookeeper]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
    ports: ["9092:9092"]

  # ── Object Storage ─────────────────────────────────────────────────────
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: miniosecret
    volumes:
      - minio_data:/data
    ports: ["9000:9000", "9001:9001"]

  # ── Security ────────────────────────────────────────────────────────────
  vault:
    image: hashicorp/vault:1.16
    command: server -dev
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: dev-root-token
    ports: ["8200:8200"]

  keycloak:
    image: quay.io/keycloak/keycloak:24.0
    command: start-dev
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: aeaop
      KC_DB_PASSWORD: secret
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
    ports: ["8080:8080"]
    depends_on: [postgres]

  # ── Frontend ────────────────────────────────────────────────────────────
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      VITE_API_BASE_URL: http://localhost:8000/api/v1
    volumes:
      - ./frontend/src:/app/src

  # ── Monitoring ──────────────────────────────────────────────────────────
  prometheus:
    image: prom/prometheus:v2.51.0
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:10.4.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
    ports: ["3001:3000"]

volumes:
  postgres_data:
  redis_data:
  es_data:
  qdrant_data:
  minio_data:
  ollama_models:
  grafana_data:
```
