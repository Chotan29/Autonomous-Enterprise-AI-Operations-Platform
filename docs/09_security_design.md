# AEAOP — Security Design & Zero Trust Architecture

---

## 1. ZERO TRUST ARCHITECTURE

```
ZERO TRUST PRINCIPLE: "Never Trust, Always Verify"

┌─────────────────────────────────────────────────────────────────────────────┐
│                    AEAOP ZERO TRUST ARCHITECTURE                            │
│                                                                             │
│  Traditional Security:                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │ [Internet] ──Firewall──► [Trusted Internal Network]            │       │
│  │               Once inside = Fully trusted                       │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  AEAOP Zero Trust:                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │ Every Request → Identity Verify → Device Trust → MFA →         │       │
│  │ Least Privilege → Network Segment Check → Encrypted Transport  │       │
│  │ → Audit Log → Continuous Verification                          │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  ZERO TRUST PILLARS:                                                        │
│  1. IDENTITY PILLAR:    Verify every user/service identity                 │
│  2. DEVICE PILLAR:      Only managed, compliant devices                    │
│  3. NETWORK PILLAR:     Microsegment, encrypt all traffic                  │
│  4. APPLICATION PILLAR: Authorize per-application, per-action              │
│  5. DATA PILLAR:        Classify data, enforce DLP                         │
│  6. VISIBILITY PILLAR:  Log everything, analyze continuously               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. IDENTITY AND ACCESS MANAGEMENT (IAM)

### 2.1 Keycloak SSO + OIDC

```
SSO ARCHITECTURE:

┌─────────┐    1. Login Request    ┌──────────────────┐
│  User   │ ──────────────────────► │   AEAOP Portal   │
│ Browser │                        │   (React App)    │
└─────────┘                        └────────┬─────────┘
                                            │ 2. Redirect to IdP
                                            ▼
                                   ┌──────────────────┐
                                   │   Keycloak       │
                                   │   OIDC/SSO       │
                                   │   Server         │
                                   │  ┌────────────┐  │
                                   │  │ LDAP/AD    │  │
                                   │  │ Integration│  │
                                   │  └────────────┘  │
                                   │  ┌────────────┐  │
                                   │  │ TOTP/FIDO2 │  │
                                   │  │ MFA        │  │
                                   │  └────────────┘  │
                                   └────────┬─────────┘
                                            │ 3. JWT Token
                                            ▼
                                   ┌──────────────────┐
                                   │   API Gateway    │
                                   │   (Kong/Nginx)   │
                                   │   Validates JWT  │
                                   └──────────────────┘
```

### 2.2 RBAC Matrix

```
ROLE-BASED ACCESS CONTROL MATRIX

ROLES:
───────────────────────────────────────────────────────────────────────────────
super_admin       — Platform-wide administration (only platform team)
tenant_admin      — Full access within their tenant
noc_manager       — NOC team lead, can approve healing actions
noc_operator      — View + acknowledge + basic actions
soc_manager       — SOC team lead, manage incidents, approve responses
soc_analyst       — Investigate, create incidents, view all SOC data
server_admin      — Full server management, patch approval
server_operator   — View + basic server operations
physec_manager    — Physical security oversight, review events
physec_operator   — View cameras, acknowledge events
compliance_officer— View compliance reports, cannot modify configs
report_viewer     — View reports only, no operational access
api_service       — Machine-to-machine service accounts

PERMISSION MATRIX:
Resource              super  t_admin  noc_mgr  noc_op  soc_mgr  soc_an
──────────────────────────────────────────────────────────────────────────────
View devices          ✓      ✓        ✓        ✓       ✓        ✓
Manage devices        ✓      ✓        ✓        ✗       ✗        ✗
View configs          ✓      ✓        ✓        ✓       ✗        ✗
Backup configs        ✓      ✓        ✓        ✓       ✗        ✗
Restore configs       ✓      ✓        APPROVE  ✗       ✗        ✗
View alerts           ✓      ✓        ✓        ✓       ✓        ✓
Acknowledge alerts    ✓      ✓        ✓        ✓       ✓        ✓
Approve healing       ✓      ✓        ✓        ✗       ✓*       ✗
View incidents        ✓      ✓        ✓        ✓       ✓        ✓
Manage incidents      ✓      ✓        ✗        ✗       ✓        ✓
Manage users          ✓      ✓        ✗        ✗       ✗        ✗
View cameras          ✓      ✓        ✓        ✗       ✓        ✓
View SIEM events      ✓      ✓        ✗        ✗       ✓        ✓
Block IP (firewall)   ✓      ✓        ✗        ✗       APPROVE  ✓
View audit logs       ✓      ✓        ✗        ✗       ✓        ✗
Export data           ✓      ✓        ✓        ✗       ✓        ✗
─────────────────────────────────────────────────────────────────────────────
* SOC manager can approve security-specific healing (isolate host, block IP)
```

---

## 3. MULTI-FACTOR AUTHENTICATION

```python
# auth_service/providers/mfa_provider.py

class MFAProvider:
    """
    Supports multiple MFA methods:
    1. TOTP (Google Authenticator, Authy) — Recommended
    2. FIDO2/WebAuthn (hardware keys, passkeys)
    3. SMS/Email OTP (fallback only — less secure)
    4. Push notification (Duo-style)
    """

    MFA_REQUIREMENTS_BY_ROLE = {
        "super_admin":        "mandatory_hardware_key",    # FIDO2 required
        "tenant_admin":       "mandatory_totp_or_fido2",
        "soc_manager":        "mandatory_totp_or_fido2",
        "noc_manager":        "mandatory_totp",
        "soc_analyst":        "mandatory_totp",
        "noc_operator":       "mandatory_totp",
        "server_admin":       "mandatory_totp_or_fido2",
        "physec_manager":     "mandatory_totp",
        "compliance_officer": "optional_totp",
        "report_viewer":      "optional",
    }

    # Adaptive MFA: extra factors based on risk signals
    ADAPTIVE_MFA_RULES = [
        {
            "condition": "new_location",       # Login from new IP/country
            "action": "require_extra_totp"
        },
        {
            "condition": "after_hours",        # Login 10pm-6am
            "action": "require_manager_approval"
        },
        {
            "condition": "sensitive_operation", # Approve healing, export data
            "action": "require_totp_step_up"
        }
    ]
```

---

## 4. SECRETS MANAGEMENT (HashiCorp Vault)

```yaml
# vault/policies/noc-service-policy.hcl

# NOC Service — can read device credentials, cannot modify
path "secret/noc/devices/+/ssh" {
  capabilities = ["read"]
}

path "secret/noc/devices/+/snmp" {
  capabilities = ["read"]
}

# Cannot access SOC secrets
path "secret/soc/*" {
  capabilities = ["deny"]
}

# Cannot access user credentials
path "secret/users/*" {
  capabilities = ["deny"]
}

# Dynamic secrets for database connections
path "database/creds/noc-readonly" {
  capabilities = ["read"]
}
```

```
VAULT SECRETS STRUCTURE:

secret/
├── noc/
│   └── devices/
│       ├── {device_hostname}/
│       │   ├── ssh           → {username, password/key, port}
│       │   ├── snmp          → {community, auth_key, priv_key}
│       │   └── api           → {api_key, api_secret}
│       └── default/
│           └── ssh           → default credentials
├── soc/
│   └── integrations/
│       ├── threat_intel/     → API keys for threat feeds
│       └── ticketing/        → ServiceNow/Jira credentials
├── physec/
│   └── cameras/
│       └── {camera_id}/      → {rtsp_url, username, password}
├── databases/
│   ├── postgresql/           → Connection strings (dynamic)
│   ├── elasticsearch/        → Service account credentials
│   └── redis/                → Auth password
└── ai/
    └── models/               → Model API endpoints (internal)
```

---

## 5. NETWORK SECURITY ARCHITECTURE

### 5.1 Network Segmentation

```
AEAOP NETWORK ZONES:

┌─────────────────────────────────────────────────────────────────────────────┐
│  INTERNET / WAN (Zone 0 — Untrusted)                                       │
│  ↕ Firewall / IPS / DDoS Protection                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  DMZ (Zone 1 — Semi-trusted)                                               │
│  • API Gateway (Kong) — Load balancer exposed                              │
│  • Web Application Firewall (WAF)                                          │
│  • VPN Concentrator (for remote NOC/SOC staff)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  APPLICATION ZONE (Zone 2 — Internal)                                      │
│  • FastAPI services                                                         │
│  • Frontend (React)                                                         │
│  • Agent orchestration                                                      │
│  Policy: Can read from DATA ZONE, cannot access MANAGEMENT ZONE directly   │
├─────────────────────────────────────────────────────────────────────────────┤
│  DATA ZONE (Zone 3 — Restricted)                                           │
│  • PostgreSQL / TimescaleDB                                                 │
│  • Elasticsearch                                                            │
│  • Redis                                                                    │
│  • Qdrant                                                                   │
│  Policy: Only APPLICATION ZONE + MANAGEMENT ZONE can access                │
├─────────────────────────────────────────────────────────────────────────────┤
│  AI ZONE (Zone 4 — Isolated)                                               │
│  • vLLM / Ollama inference servers                                         │
│  • GPU nodes                                                                │
│  Policy: Only APPLICATION ZONE can call AI APIs. No internet.              │
├─────────────────────────────────────────────────────────────────────────────┤
│  MANAGEMENT ZONE (Zone 5 — Highly Restricted)                              │
│  • HashiCorp Vault                                                          │
│  • Keycloak (IAM)                                                           │
│  • Kubernetes control plane                                                 │
│  • OOB management network                                                  │
│  Policy: Jumpbox access only, MFA mandatory, audit all sessions            │
├─────────────────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE ZONE (Zone 6 — Monitored)                                  │
│  • Network devices (switches, routers, firewalls)                          │
│  • Servers (SNMP, SSH, WinRM)                                              │
│  • Cameras (RTSP streams)                                                  │
│  Policy: SNMP read from NOC zone, SSH only from AI ZONE for healing        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Kubernetes Network Policies

```yaml
# infrastructure/kubernetes/network-policies/deny-all-default.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-default
  namespace: aeaop-prod
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress

---
# Allow NOC service to access database
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-noc-to-db
  namespace: aeaop-prod
spec:
  podSelector:
    matchLabels:
      app: noc-service
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  - to:
    - podSelector:
        matchLabels:
          app: qdrant
    ports:
    - protocol: TCP
      port: 6333

---
# Allow NOC service to reach infrastructure devices (SSH, SNMP)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-noc-to-infra
  namespace: aeaop-prod
spec:
  podSelector:
    matchLabels:
      app: noc-service
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8      # Internal infrastructure networks
        except:
          - 10.255.0.0/16     # Management zone (blocked)
    ports:
    - protocol: TCP
      port: 22       # SSH
    - protocol: UDP
      port: 161      # SNMP
    - protocol: TCP
      port: 443      # HTTPS APIs
```

---

## 6. ENCRYPTION STANDARDS

```
DATA ENCRYPTION STRATEGY:

AT REST:
┌──────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Disk-level encryption (LUKS/BitLocker on all nodes)             │
│ Layer 2: Database-level encryption (TDE for PostgreSQL via pgcrypto)     │
│ Layer 3: Application-level encryption for sensitive fields               │
│          (passwords, API keys, camera URLs → encrypted before storage)   │
│ Algorithm: AES-256-GCM                                                   │
│ Key Management: HashiCorp Vault (auto-unsealed with Shamir Secret Share) │
└──────────────────────────────────────────────────────────────────────────┘

IN TRANSIT:
┌──────────────────────────────────────────────────────────────────────────┐
│ External API:    TLS 1.3 minimum (TLS 1.2 explicitly disabled)          │
│ Internal APIs:   mTLS (mutual TLS) between all microservices            │
│ Service Mesh:    Istio with automatic mTLS (zero-config encryption)     │
│ Database conns:  TLS for all PostgreSQL, Redis, Elasticsearch           │
│ AI inference:    TLS internally (models don't leave cluster)            │
│ Certificate CA:  Internal PKI (Vault PKI secrets engine)                │
│ Certificate TTL: 72 hours (auto-rotated via cert-manager)               │
└──────────────────────────────────────────────────────────────────────────┘

CIPHER SUITES (Approved):
  TLS_AES_256_GCM_SHA384        (TLS 1.3 — preferred)
  TLS_CHACHA20_POLY1305_SHA256  (TLS 1.3)
  TLS_AES_128_GCM_SHA256        (TLS 1.3)

CERTIFICATE MANAGEMENT:
  cert-manager (K8s) → Vault PKI → Auto-renews before expiry
  Hardware Security Module (HSM): Luna HSM for CA root keys (bank tier)
```

---

## 7. AUDIT LOGGING ARCHITECTURE

```python
# shared/middleware/audit_middleware.py

class AuditMiddleware:
    """
    Logs ALL actions with:
    - Who (user_id, IP, session)
    - What (action, resource, parameters)
    - When (timestamp, duration)
    - Result (success/failure/denied)
    - Why (business justification if required)
    """

    SENSITIVE_ACTIONS = [
        "config.restore",
        "healing.approve",
        "healing.execute",
        "user.create",
        "user.delete",
        "role.assign",
        "incident.close",
        "firewall.rule.modify",
        "vault.secret.read",   # When a service reads credentials
    ]

    async def log_action(self, context: dict) -> None:
        audit_entry = {
            "id":            str(uuid.uuid4()),
            "tenant_id":     context["tenant_id"],
            "user_id":       context["user_id"],
            "session_id":    context["session_id"],
            "action":        context["action"],
            "resource_type": context["resource_type"],
            "resource_id":   context.get("resource_id"),
            "parameters":    self._sanitize_params(context.get("parameters", {})),
            "ip_address":    context["client_ip"],
            "user_agent":    context.get("user_agent"),
            "status":        context["status"],
            "duration_ms":   context.get("duration_ms"),
            "metadata":      context.get("metadata", {}),
            "created_at":    datetime.utcnow().isoformat()
        }

        # Write to database (immutable — no update/delete allowed)
        await self.db.write_audit_log(audit_entry)

        # Also write to Elasticsearch for SIEM analysis
        await self.elasticsearch.index(
            index=f"aeaop-audit-{datetime.utcnow().strftime('%Y.%m')}",
            body=audit_entry
        )

        # For sensitive actions: also write to append-only S3/MinIO
        if context["action"] in self.SENSITIVE_ACTIONS:
            await self.minio.put_object(
                bucket=f"audit-immutable-{context['tenant_id']}",
                key=f"{datetime.utcnow().isoformat()}/{audit_entry['id']}.json",
                data=json.dumps(audit_entry)
            )
```

---

## 8. COMPLIANCE FRAMEWORK MAPPING

```
PCI-DSS v4.0 CONTROL MAPPING:

Control       Requirement                    AEAOP Implementation
─────────────────────────────────────────────────────────────────────────────
Req 1.1       Network security controls      Firewall rules audited, topology mapped
Req 2.1       Default passwords changed      Compliance engine checks default creds
Req 2.2       System configurations          Config backup + compliance rules engine
Req 6.3       Security patches              Automated patch management + AI prioritization
Req 7.1       Access control               RBAC + least privilege enforcement
Req 8.2       Multi-factor authentication  MFA mandatory for all admin users
Req 8.6       System accounts managed      Service account monitoring in UEBA
Req 10.2      Audit logs                   Full audit log — who/what/when/result
Req 10.5      Log protection              Immutable audit logs in MinIO
Req 10.6      Log review                  AI-powered automated log review (SOC)
Req 11.3      External vulnerability scan  Automated vulnerability assessment
Req 11.4      Intrusion detection          AI-powered IDS in SOC
Req 12.10     Incident response            Automated incident response playbooks

ISO 27001:2022 ANNEX A CONTROLS:
A.5  Organization controls      → Policies enforced via compliance engine
A.6  People controls            → RBAC, background check tracking
A.7  Physical controls          → Physical Security AI system
A.8  Technological controls     → Full technical control suite
A.9  Access control             → IAM + Zero Trust
A.10 Cryptography               → Vault-managed encryption
A.12 Operations security        → Automated patching, config mgmt
A.13 Communications security    → mTLS, network segmentation
A.16 Information security incidents → AI-powered incident management
A.17 Business continuity        → HA/DR architecture
```
