# AEAOP — Complete Database Schema Design

## Database Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    AEAOP DATABASE ARCHITECTURE                           │
│                                                                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │   PostgreSQL 16  │  │   TimescaleDB    │  │    Elasticsearch 8    │  │
│  │                  │  │                  │  │                       │  │
│  │  - Devices       │  │  - Metrics       │  │  - Logs (SIEM)        │  │
│  │  - Users/RBAC    │  │  - Bandwidth     │  │  - Events             │  │
│  │  - Tenants       │  │  - Health data   │  │  - Threat data        │  │
│  │  - Incidents     │  │  - Alert history │  │  - Full-text search   │  │
│  │  - Configs       │  │  - Forecasts     │  │  - NetFlow            │  │
│  │  - Audit Logs    │  │  - Agg. Views    │  │                       │  │
│  └─────────────────┘  └──────────────────┘  └───────────────────────┘  │
│                                                                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │   Redis 7        │  │   Qdrant         │  │    MinIO              │  │
│  │                  │  │   (Vector DB)    │  │  (Object Storage)     │  │
│  │  - Sessions      │  │                  │  │                       │  │
│  │  - Cache         │  │  - Doc embeddings│  │  - Config backups     │  │
│  │  - Rate limits   │  │  - Log vectors   │  │  - Report PDFs        │  │
│  │  - Real-time     │  │  - KB vectors    │  │  - Camera snapshots   │  │
│  │    alerts        │  │  - Incident vecs │  │  - Firmware files     │  │
│  │  - Pub/Sub       │  │                  │  │  - Agent packages     │  │
│  └─────────────────┘  └──────────────────┘  └───────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## PostgreSQL Schema (Core Operational Database)

```sql
-- ============================================================
-- SCHEMA: public (shared), tenant-specific schemas created dynamically
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "ltree";
CREATE EXTENSION IF NOT EXISTS "hstore";

-- ============================================================
-- MULTI-TENANCY CORE
-- ============================================================

CREATE TABLE tenants (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    code            VARCHAR(50) UNIQUE NOT NULL,        -- 'bank', 'isp', 'dc', 'enterprise'
    name            VARCHAR(255) NOT NULL,
    schema_name     VARCHAR(100) UNIQUE NOT NULL,       -- 'tenant_bank', 'tenant_isp'
    tier            VARCHAR(50) DEFAULT 'enterprise',   -- 'small', 'medium', 'enterprise', 'bank'
    settings        JSONB DEFAULT '{}',
    compliance_mode VARCHAR(100),                       -- 'pci-dss', 'hipaa', 'iso27001'
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tenant_features (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,
    feature     VARCHAR(100) NOT NULL,                  -- 'noc', 'soc', 'server', 'physec', 'rag'
    enabled     BOOLEAN DEFAULT TRUE,
    config      JSONB DEFAULT '{}',
    UNIQUE(tenant_id, feature)
);

-- ============================================================
-- IDENTITY AND ACCESS MANAGEMENT
-- ============================================================

CREATE TABLE users (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    username        VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    password_hash   VARCHAR(255),
    full_name       VARCHAR(255),
    mfa_enabled     BOOLEAN DEFAULT FALSE,
    mfa_secret      TEXT,                               -- TOTP secret (encrypted)
    sso_provider    VARCHAR(100),                       -- 'ldap', 'saml', 'oidc'
    sso_subject     VARCHAR(255),
    is_active       BOOLEAN DEFAULT TRUE,
    is_locked       BOOLEAN DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    last_login_ip   INET,
    failed_attempts INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, username),
    UNIQUE(tenant_id, email)
);

CREATE TABLE roles (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id   UUID REFERENCES tenants(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,                  -- 'noc_operator', 'soc_analyst', 'admin'
    description TEXT,
    is_system   BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

CREATE TABLE permissions (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    resource    VARCHAR(100) NOT NULL,                  -- 'devices', 'incidents', 'configs'
    action      VARCHAR(50) NOT NULL,                   -- 'read', 'write', 'delete', 'execute'
    scope       VARCHAR(50) DEFAULT 'tenant',           -- 'tenant', 'global', 'own'
    UNIQUE(resource, action, scope)
);

CREATE TABLE role_permissions (
    role_id         UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission_id   UUID REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY(role_id, permission_id)
);

CREATE TABLE user_roles (
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id     UUID REFERENCES roles(id) ON DELETE CASCADE,
    granted_by  UUID REFERENCES users(id),
    granted_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ,
    PRIMARY KEY(user_id, role_id)
);

CREATE TABLE api_keys (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash        VARCHAR(255) UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    scopes          TEXT[] DEFAULT '{}',
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    user_id         UUID REFERENCES users(id),
    session_id      VARCHAR(255),
    action          VARCHAR(255) NOT NULL,
    resource_type   VARCHAR(100) NOT NULL,
    resource_id     VARCHAR(255),
    old_value       JSONB,
    new_value       JSONB,
    ip_address      INET,
    user_agent      TEXT,
    status          VARCHAR(50) DEFAULT 'success',      -- 'success', 'failure', 'denied'
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_logs_tenant_created ON audit_logs(tenant_id, created_at DESC);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, created_at DESC);

-- ============================================================
-- NETWORK DEVICE MANAGEMENT (NOC)
-- ============================================================

CREATE TABLE device_types (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    vendor      VARCHAR(100) NOT NULL,                  -- 'Cisco', 'Mikrotik', 'Juniper', etc.
    model       VARCHAR(255),
    category    VARCHAR(100) NOT NULL,                  -- 'router', 'switch', 'firewall', 'ap', 'server'
    os_type     VARCHAR(100),                           -- 'IOS', 'IOS-XE', 'RouterOS', 'Junos'
    snmp_oids   JSONB DEFAULT '{}',                     -- OID mappings for this device type
    driver_name VARCHAR(100),                           -- 'cisco_ios', 'mikrotik_api', etc.
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE devices (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    device_type_id  UUID REFERENCES device_types(id),
    hostname        VARCHAR(255) NOT NULL,
    display_name    VARCHAR(255),
    ip_address      INET NOT NULL,
    management_ip   INET,
    mac_address     MACADDR,
    serial_number   VARCHAR(255),
    asset_tag       VARCHAR(100),
    location        VARCHAR(500),
    site_code       VARCHAR(50),
    rack_unit       VARCHAR(50),
    status          VARCHAR(50) DEFAULT 'unknown',      -- 'online', 'offline', 'degraded', 'maintenance'
    snmp_version    VARCHAR(10) DEFAULT 'v2c',          -- 'v1', 'v2c', 'v3'
    snmp_community  VARCHAR(255),                       -- encrypted reference to Vault
    snmp_auth       JSONB,                              -- v3 auth details (Vault reference)
    ssh_credential  JSONB,                              -- Vault reference
    api_credential  JSONB,                              -- Vault reference
    os_version      VARCHAR(255),
    firmware_version VARCHAR(255),
    uptime_seconds  BIGINT,
    last_seen       TIMESTAMPTZ,
    last_poll       TIMESTAMPTZ,
    discovery_method VARCHAR(50),                       -- 'snmp', 'lldp', 'cdp', 'manual', 'api'
    tags            TEXT[] DEFAULT '{}',
    custom_fields   JSONB DEFAULT '{}',
    is_managed      BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, ip_address)
);
CREATE INDEX idx_devices_tenant ON devices(tenant_id);
CREATE INDEX idx_devices_status ON devices(tenant_id, status);
CREATE INDEX idx_devices_ip ON devices(ip_address);

CREATE TABLE device_interfaces (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    device_id       UUID REFERENCES devices(id) ON DELETE CASCADE,
    if_index        INTEGER NOT NULL,
    if_name         VARCHAR(255),
    if_alias        VARCHAR(255),
    if_type         VARCHAR(100),                       -- 'ethernet', 'loopback', 'tunnel', 'vlan'
    speed_bps       BIGINT,
    mac_address     MACADDR,
    ip_addresses    INET[],
    admin_status    VARCHAR(20),                        -- 'up', 'down', 'testing'
    oper_status     VARCHAR(20),
    mtu             INTEGER,
    in_octets       BIGINT,
    out_octets      BIGINT,
    in_errors       BIGINT,
    out_errors      BIGINT,
    last_updated    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, if_index)
);

CREATE TABLE device_neighbors (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    local_device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
    local_port      VARCHAR(255),
    remote_device_id UUID REFERENCES devices(id),
    remote_port     VARCHAR(255),
    remote_hostname VARCHAR(255),
    remote_ip       INET,
    protocol        VARCHAR(20),                        -- 'lldp', 'cdp', 'manual'
    discovered_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE device_configs (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    device_id       UUID REFERENCES devices(id) ON DELETE CASCADE,
    config_type     VARCHAR(50) DEFAULT 'running',      -- 'running', 'startup', 'candidate'
    content         TEXT NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,               -- SHA-256
    version         INTEGER DEFAULT 1,
    is_baseline     BOOLEAN DEFAULT FALSE,
    backup_at       TIMESTAMPTZ DEFAULT NOW(),
    backed_up_by    UUID REFERENCES users(id),
    storage_path    VARCHAR(500),                       -- MinIO path
    diff_from_prev  TEXT,
    tags            TEXT[] DEFAULT '{}',
    notes           TEXT
);
CREATE INDEX idx_device_configs_device ON device_configs(device_id, backup_at DESC);

CREATE TABLE compliance_rules (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    framework       VARCHAR(100),                       -- 'PCI-DSS', 'CIS', 'NIST', 'internal'
    control_id      VARCHAR(100),
    device_types    TEXT[],                             -- vendor/category filter
    rule_type       VARCHAR(50),                        -- 'regex', 'must_contain', 'must_not_contain', 'script'
    rule_content    TEXT NOT NULL,
    severity        VARCHAR(20) DEFAULT 'medium',       -- 'critical', 'high', 'medium', 'low'
    remediation     TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE compliance_results (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    device_id       UUID REFERENCES devices(id),
    rule_id         UUID REFERENCES compliance_rules(id),
    config_id       UUID REFERENCES device_configs(id),
    status          VARCHAR(20) NOT NULL,               -- 'pass', 'fail', 'error', 'skipped'
    details         TEXT,
    checked_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ALERT AND INCIDENT MANAGEMENT
-- ============================================================

CREATE TABLE alerts (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    source          VARCHAR(100) NOT NULL,              -- 'snmp', 'syslog', 'agent', 'ai', 'siem'
    source_device_id UUID REFERENCES devices(id),
    source_host     VARCHAR(255),
    alert_type      VARCHAR(100) NOT NULL,              -- 'interface_down', 'cpu_high', 'threat_detected'
    category        VARCHAR(50),                        -- 'noc', 'soc', 'server', 'physec'
    severity        VARCHAR(20) NOT NULL,               -- 'critical', 'high', 'medium', 'low', 'info'
    priority        INTEGER DEFAULT 50,                 -- 1-100, higher = more urgent
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    raw_event       JSONB,
    enrichment      JSONB DEFAULT '{}',                 -- AI-added context
    status          VARCHAR(50) DEFAULT 'new',          -- 'new', 'acknowledged', 'in_progress', 'resolved', 'suppressed'
    assigned_to     UUID REFERENCES users(id),
    acknowledged_by UUID REFERENCES users(id),
    acknowledged_at TIMESTAMPTZ,
    resolved_by     UUID REFERENCES users(id),
    resolved_at     TIMESTAMPTZ,
    resolution_notes TEXT,
    ai_rca          TEXT,                               -- AI Root Cause Analysis result
    ai_suggestion   TEXT,                               -- AI recommended action
    ai_confidence   FLOAT,                              -- 0.0 - 1.0
    is_ai_resolved  BOOLEAN DEFAULT FALSE,
    parent_alert_id UUID REFERENCES alerts(id),         -- for correlation
    correlation_id  VARCHAR(255),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_alerts_tenant_created ON alerts(tenant_id, created_at DESC);
CREATE INDEX idx_alerts_status ON alerts(tenant_id, status, severity);
CREATE INDEX idx_alerts_device ON alerts(source_device_id);

CREATE TABLE incidents (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    incident_number VARCHAR(50) UNIQUE NOT NULL,        -- 'INC-2026-001234'
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    category        VARCHAR(50),                        -- 'noc', 'soc', 'server', 'physec'
    severity        VARCHAR(20) NOT NULL,
    priority        VARCHAR(20) DEFAULT 'medium',
    status          VARCHAR(50) DEFAULT 'open',         -- 'open', 'investigating', 'mitigated', 'resolved', 'closed'
    impact          TEXT,
    assigned_to     UUID REFERENCES users(id),
    assigned_team   VARCHAR(100),
    sla_deadline    TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    root_cause      TEXT,
    resolution      TEXT,
    ai_summary      TEXT,
    ai_timeline     JSONB DEFAULT '[]',
    mitre_tactics   TEXT[] DEFAULT '{}',
    mitre_techniques TEXT[] DEFAULT '{}',
    tags            TEXT[] DEFAULT '{}',
    related_alerts  UUID[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE incident_timeline (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    incident_id     UUID REFERENCES incidents(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id),
    action_type     VARCHAR(100),                       -- 'note', 'status_change', 'assignment', 'ai_action'
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SERVER MANAGEMENT
-- ============================================================

CREATE TABLE servers (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    hostname        VARCHAR(255) NOT NULL,
    ip_address      INET NOT NULL,
    os_type         VARCHAR(50),                        -- 'linux', 'windows', 'vmware', 'proxmox'
    os_name         VARCHAR(255),
    os_version      VARCHAR(100),
    kernel_version  VARCHAR(100),
    arch            VARCHAR(50),
    cpu_cores       INTEGER,
    cpu_model       VARCHAR(255),
    ram_gb          INTEGER,
    is_virtual      BOOLEAN DEFAULT FALSE,
    hypervisor      VARCHAR(100),                       -- 'vmware', 'proxmox', 'hyper-v', 'kvm'
    vm_uuid         VARCHAR(255),
    cluster_name    VARCHAR(255),
    datacenter      VARCHAR(255),
    rack_location   VARCHAR(255),
    environment     VARCHAR(50),                        -- 'prod', 'staging', 'dev', 'dr'
    role            VARCHAR(255),                       -- 'web', 'db', 'app', 'cache', 'dns'
    status          VARCHAR(50) DEFAULT 'online',
    last_seen       TIMESTAMPTZ,
    ssh_credential  JSONB,
    winrm_credential JSONB,
    agent_version   VARCHAR(50),
    agent_last_seen TIMESTAMPTZ,
    tags            TEXT[] DEFAULT '{}',
    custom_fields   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, hostname)
);

CREATE TABLE patch_records (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    server_id       UUID REFERENCES servers(id),
    package_name    VARCHAR(255) NOT NULL,
    current_version VARCHAR(255),
    available_version VARCHAR(255),
    cve_ids         TEXT[] DEFAULT '{}',
    severity        VARCHAR(20),
    installed_at    TIMESTAMPTZ,
    status          VARCHAR(50) DEFAULT 'pending',      -- 'pending', 'scheduled', 'installing', 'installed', 'failed'
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SOC / SECURITY
-- ============================================================

CREATE TABLE threat_intel (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    ioc_type        VARCHAR(50) NOT NULL,               -- 'ip', 'domain', 'hash', 'url', 'email'
    ioc_value       TEXT NOT NULL,
    threat_type     VARCHAR(100),                       -- 'malware', 'c2', 'ransomware', 'phishing'
    confidence      INTEGER,                            -- 0-100
    severity        VARCHAR(20),
    source          VARCHAR(100),                       -- 'internal', 'misp', 'otx', 'manual'
    tags            TEXT[] DEFAULT '{}',
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, ioc_type, ioc_value)
);

CREATE TABLE ueba_baselines (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    entity_type     VARCHAR(50) NOT NULL,               -- 'user', 'host', 'service_account'
    entity_id       VARCHAR(255) NOT NULL,
    behavior_type   VARCHAR(100) NOT NULL,              -- 'login_time', 'data_volume', 'geo_location'
    baseline_value  JSONB NOT NULL,
    std_deviation   FLOAT,
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    valid_until     TIMESTAMPTZ,
    UNIQUE(tenant_id, entity_type, entity_id, behavior_type)
);

-- ============================================================
-- PHYSICAL SECURITY
-- ============================================================

CREATE TABLE cameras (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    location        VARCHAR(500),
    zone_id         UUID,
    ip_address      INET,
    rtsp_url        TEXT,                               -- encrypted in Vault
    vendor          VARCHAR(100),
    model           VARCHAR(255),
    resolution      VARCHAR(50),
    fps             INTEGER,
    ptz_capable     BOOLEAN DEFAULT FALSE,
    ai_enabled      BOOLEAN DEFAULT TRUE,
    status          VARCHAR(50) DEFAULT 'online',
    last_seen       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE security_zones (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    zone_type       VARCHAR(50),                        -- 'public', 'restricted', 'critical', 'server_room'
    floor_plan_data JSONB,
    access_policy   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE vision_events (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    camera_id       UUID REFERENCES cameras(id),
    event_type      VARCHAR(100) NOT NULL,              -- 'intrusion', 'loitering', 'crowd', 'motion', 'object_detected'
    confidence      FLOAT NOT NULL,                     -- 0.0 - 1.0
    risk_score      INTEGER,                            -- 1-100
    bounding_boxes  JSONB,                              -- detected objects with positions
    person_count    INTEGER,
    snapshot_path   VARCHAR(500),                       -- MinIO reference
    clip_path       VARCHAR(500),
    status          VARCHAR(50) DEFAULT 'new',          -- 'new', 'reviewing', 'confirmed', 'false_positive', 'resolved'
    reviewed_by     UUID REFERENCES users(id),
    reviewed_at     TIMESTAMPTZ,
    notes           TEXT,
    alert_id        UUID REFERENCES alerts(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_vision_events_camera ON vision_events(camera_id, created_at DESC);

-- ============================================================
-- AUTONOMOUS HEALING / ACTIONS
-- ============================================================

CREATE TABLE healing_actions (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    alert_id        UUID REFERENCES alerts(id),
    incident_id     UUID REFERENCES incidents(id),
    action_type     VARCHAR(100) NOT NULL,              -- 'restart_service', 'clear_disk', 'rollback_config'
    executor_type   VARCHAR(50) NOT NULL,               -- 'ssh', 'winrm', 'ansible', 'snmp', 'rest', 'terraform'
    target_device   UUID REFERENCES devices(id),
    target_server   UUID REFERENCES servers(id),
    parameters      JSONB NOT NULL,
    ai_reasoning    TEXT,
    risk_level      VARCHAR(20) DEFAULT 'medium',       -- 'low', 'medium', 'high', 'critical'
    requires_approval BOOLEAN DEFAULT TRUE,
    status          VARCHAR(50) DEFAULT 'pending',      -- 'pending', 'approved', 'rejected', 'running', 'success', 'failed', 'rolled_back'
    approved_by     UUID REFERENCES users(id),
    approved_at     TIMESTAMPTZ,
    rejection_reason TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    execution_log   TEXT,
    rollback_plan   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE playbooks (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    trigger_conditions JSONB NOT NULL,
    steps           JSONB NOT NULL,
    is_autonomous   BOOLEAN DEFAULT FALSE,              -- if true, no approval needed
    risk_level      VARCHAR(20) DEFAULT 'medium',
    estimated_duration_seconds INTEGER,
    success_criteria JSONB,
    rollback_steps  JSONB,
    version         INTEGER DEFAULT 1,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RAG / KNOWLEDGE BASE
-- ============================================================

CREATE TABLE knowledge_documents (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    title           VARCHAR(500) NOT NULL,
    source_type     VARCHAR(100) NOT NULL,              -- 'sop', 'runbook', 'manual', 'config', 'policy', 'incident'
    source_path     VARCHAR(500),
    file_hash       VARCHAR(64),
    status          VARCHAR(50) DEFAULT 'pending',      -- 'pending', 'processing', 'indexed', 'failed'
    chunk_count     INTEGER DEFAULT 0,
    embedding_model VARCHAR(255),
    indexed_at      TIMESTAMPTZ,
    tags            TEXT[] DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE report_schedules (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    report_type     VARCHAR(100) NOT NULL,              -- 'noc_daily', 'soc_weekly', 'executive_monthly'
    schedule_cron   VARCHAR(100) NOT NULL,
    recipients      TEXT[] DEFAULT '{}',
    config          JSONB DEFAULT '{}',
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## TimescaleDB Schema (Time-Series Metrics)

```sql
-- ============================================================
-- TimescaleDB — Time-Series Metrics Database
-- ============================================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Device Metrics (SNMP polling results)
CREATE TABLE device_metrics (
    time            TIMESTAMPTZ NOT NULL,
    tenant_id       UUID NOT NULL,
    device_id       UUID NOT NULL,
    metric_name     VARCHAR(100) NOT NULL,              -- 'cpu_util', 'mem_util', 'if_in_octets'
    interface_id    VARCHAR(100),
    value           DOUBLE PRECISION NOT NULL,
    unit            VARCHAR(50),
    tags            JSONB DEFAULT '{}'
);
SELECT create_hypertable('device_metrics', 'time', chunk_time_interval => INTERVAL '1 hour');
CREATE INDEX ON device_metrics(device_id, metric_name, time DESC);

-- Continuous Aggregate: 5-minute averages
CREATE MATERIALIZED VIEW device_metrics_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    tenant_id,
    device_id,
    metric_name,
    AVG(value) AS avg_value,
    MAX(value) AS max_value,
    MIN(value) AS min_value
FROM device_metrics
GROUP BY bucket, tenant_id, device_id, metric_name;

-- Bandwidth Analytics
CREATE TABLE interface_bandwidth (
    time            TIMESTAMPTZ NOT NULL,
    tenant_id       UUID NOT NULL,
    device_id       UUID NOT NULL,
    interface_name  VARCHAR(255) NOT NULL,
    in_bps          BIGINT,
    out_bps         BIGINT,
    in_errors       INTEGER DEFAULT 0,
    out_errors      INTEGER DEFAULT 0,
    in_discards     INTEGER DEFAULT 0,
    out_discards    INTEGER DEFAULT 0,
    utilization_pct FLOAT
);
SELECT create_hypertable('interface_bandwidth', 'time', chunk_time_interval => INTERVAL '1 hour');

-- Server Metrics
CREATE TABLE server_metrics (
    time            TIMESTAMPTZ NOT NULL,
    tenant_id       UUID NOT NULL,
    server_id       UUID NOT NULL,
    cpu_util        FLOAT,
    mem_used_gb     FLOAT,
    mem_total_gb    FLOAT,
    disk_read_bps   BIGINT,
    disk_write_bps  BIGINT,
    net_in_bps      BIGINT,
    net_out_bps     BIGINT,
    load_avg_1m     FLOAT,
    load_avg_5m     FLOAT,
    load_avg_15m    FLOAT,
    process_count   INTEGER,
    open_files      INTEGER,
    tcp_connections INTEGER
);
SELECT create_hypertable('server_metrics', 'time', chunk_time_interval => INTERVAL '1 hour');

-- Alert Metrics (for trending)
CREATE TABLE alert_metrics (
    time            TIMESTAMPTZ NOT NULL,
    tenant_id       UUID NOT NULL,
    category        VARCHAR(50) NOT NULL,
    severity        VARCHAR(20) NOT NULL,
    source          VARCHAR(100),
    alert_count     INTEGER DEFAULT 1,
    resolved_count  INTEGER DEFAULT 0,
    mttr_seconds    FLOAT
);
SELECT create_hypertable('alert_metrics', 'time', chunk_time_interval => INTERVAL '1 day');

-- NetFlow Summary (aggregated from raw flows)
CREATE TABLE netflow_summary (
    time            TIMESTAMPTZ NOT NULL,
    tenant_id       UUID NOT NULL,
    src_ip          INET NOT NULL,
    dst_ip          INET NOT NULL,
    src_port        INTEGER,
    dst_port        INTEGER,
    protocol        INTEGER,
    bytes           BIGINT,
    packets         BIGINT,
    flow_count      INTEGER DEFAULT 1
);
SELECT create_hypertable('netflow_summary', 'time', chunk_time_interval => INTERVAL '1 hour');

-- AI Forecasts
CREATE TABLE ai_forecasts (
    time            TIMESTAMPTZ NOT NULL,
    tenant_id       UUID NOT NULL,
    target_id       UUID NOT NULL,
    target_type     VARCHAR(50) NOT NULL,               -- 'device', 'server', 'link'
    metric_name     VARCHAR(100) NOT NULL,
    forecast_value  FLOAT NOT NULL,
    lower_bound     FLOAT,
    upper_bound     FLOAT,
    confidence      FLOAT,
    horizon_minutes INTEGER,
    model_version   VARCHAR(50)
);
SELECT create_hypertable('ai_forecasts', 'time', chunk_time_interval => INTERVAL '1 day');

-- Data Retention Policies
SELECT add_retention_policy('device_metrics', INTERVAL '90 days');
SELECT add_retention_policy('interface_bandwidth', INTERVAL '180 days');
SELECT add_retention_policy('server_metrics', INTERVAL '90 days');
SELECT add_retention_policy('netflow_summary', INTERVAL '30 days');
SELECT add_retention_policy('alert_metrics', INTERVAL '2 years');
```

---

## Elasticsearch Index Mappings (SIEM & Logs)

```json
{
  "index_patterns": ["aeaop-siem-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "index.lifecycle.name": "aeaop-log-ilm",
      "index.lifecycle.rollover_alias": "aeaop-siem"
    },
    "mappings": {
      "properties": {
        "@timestamp":       { "type": "date" },
        "tenant_id":        { "type": "keyword" },
        "source_ip":        { "type": "ip" },
        "destination_ip":   { "type": "ip" },
        "source_host":      { "type": "keyword" },
        "destination_host": { "type": "keyword" },
        "source_port":      { "type": "integer" },
        "destination_port": { "type": "integer" },
        "protocol":         { "type": "keyword" },
        "event_type":       { "type": "keyword" },
        "event_category":   { "type": "keyword" },
        "severity":         { "type": "keyword" },
        "log_source":       { "type": "keyword" },
        "message":          { "type": "text", "analyzer": "standard" },
        "raw_log":          { "type": "text", "index": false },
        "user":             { "type": "keyword" },
        "process_name":     { "type": "keyword" },
        "process_pid":      { "type": "integer" },
        "file_path":        { "type": "keyword" },
        "command_line":     { "type": "text" },
        "mitre_tactic":     { "type": "keyword" },
        "mitre_technique":  { "type": "keyword" },
        "ioc_matches":      { "type": "keyword" },
        "threat_score":     { "type": "float" },
        "geo_location":     { "type": "geo_point" },
        "country_code":     { "type": "keyword" },
        "tags":             { "type": "keyword" },
        "enrichment":       { "type": "object" }
      }
    }
  }
}
```

---

## Qdrant Collections Schema

```json
{
  "collections": [
    {
      "name": "knowledge_base",
      "description": "Enterprise RAG knowledge base — SOPs, runbooks, manuals",
      "vectors": {
        "size": 768,
        "distance": "Cosine"
      },
      "payload_schema": {
        "tenant_id":     "keyword",
        "doc_id":        "keyword",
        "source_type":   "keyword",
        "title":         "text",
        "chunk_index":   "integer",
        "tags":          "keyword[]",
        "created_at":    "datetime"
      }
    },
    {
      "name": "incident_history",
      "description": "Past incidents for similarity search and RCA support",
      "vectors": {
        "size": 768,
        "distance": "Cosine"
      },
      "payload_schema": {
        "tenant_id":     "keyword",
        "incident_id":   "keyword",
        "category":      "keyword",
        "severity":      "keyword",
        "root_cause":    "text",
        "resolution":    "text",
        "created_at":    "datetime"
      }
    },
    {
      "name": "device_configs",
      "description": "Vectorized device configurations for semantic search",
      "vectors": {
        "size": 768,
        "distance": "Cosine"
      },
      "payload_schema": {
        "tenant_id":     "keyword",
        "device_id":     "keyword",
        "config_id":     "keyword",
        "device_type":   "keyword",
        "vendor":        "keyword",
        "backup_at":     "datetime"
      }
    },
    {
      "name": "siem_events",
      "description": "SIEM event vectors for behavioral similarity detection",
      "vectors": {
        "size": 384,
        "distance": "Cosine"
      },
      "payload_schema": {
        "tenant_id":     "keyword",
        "event_type":    "keyword",
        "source_ip":     "keyword",
        "severity":      "keyword",
        "timestamp":     "datetime"
      }
    }
  ]
}
```
