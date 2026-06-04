# AEAOP — NOC, SOC, Server Ops & Physical Security Design

---

## 1. AI-POWERED NOC DESIGN

### 1.1 Network Device Driver Architecture

```python
# backend/services/noc_service/drivers/base_driver.py

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import asyncssh
import asyncio

class BaseNetworkDriver(ABC):
    """Abstract base for all vendor drivers"""

    def __init__(self, device_config: dict, credential_manager):
        self.host = device_config['ip_address']
        self.vendor = device_config['vendor']
        self.model = device_config.get('model')
        self.cred_mgr = credential_manager

    @abstractmethod
    async def get_running_config(self) -> str: ...

    @abstractmethod
    async def get_interfaces(self) -> list: ...

    @abstractmethod
    async def get_routing_table(self) -> list: ...

    @abstractmethod
    async def get_arp_table(self) -> list: ...

    @abstractmethod
    async def execute_command(self, command: str) -> str: ...

    @abstractmethod
    async def apply_config(self, config: str) -> bool: ...

    @abstractmethod
    async def get_snmp_data(self, oids: list) -> dict: ...

    async def backup_config(self) -> dict:
        config = await self.get_running_config()
        return {
            "content": config,
            "hash": hashlib.sha256(config.encode()).hexdigest(),
            "timestamp": datetime.utcnow().isoformat()
        }


class CiscoIOSDriver(BaseNetworkDriver):
    """Driver for Cisco IOS / IOS-XE devices"""

    SNMP_OIDS = {
        "sysDescr":       "1.3.6.1.2.1.1.1.0",
        "sysUpTime":      "1.3.6.1.2.1.1.3.0",
        "ifTable":        "1.3.6.1.2.1.2.2.1",
        "ifInOctets":     "1.3.6.1.2.1.2.2.1.10",
        "ifOutOctets":    "1.3.6.1.2.1.2.2.1.16",
        "cpuUtil5min":    "1.3.6.1.4.1.9.2.1.58.0",    # Cisco-specific
        "memFree":        "1.3.6.1.4.1.9.9.48.1.1.1.6",
        "cdpNeighbors":   "1.3.6.1.4.1.9.9.23.1.2.1",
        "lldpNeighbors":  "1.0.8802.1.1.2.1.4.1.1"
    }

    async def get_running_config(self) -> str:
        creds = await self.cred_mgr.get_ssh_credentials(self.host)
        async with asyncssh.connect(
            self.host,
            username=creds['username'],
            password=creds['password'],
            known_hosts=None
        ) as conn:
            result = await conn.run('show running-config')
            return result.stdout

    async def execute_command(self, command: str) -> str:
        creds = await self.cred_mgr.get_ssh_credentials(self.host)
        async with asyncssh.connect(
            self.host, username=creds['username'],
            password=creds['password'], known_hosts=None
        ) as conn:
            result = await conn.run(command)
            return result.stdout

    COMPLIANCE_CHECKS = {
        "ssh_v2_only":       r"ip ssh version 2",
        "no_telnet":         r"(?!.*transport input telnet)",
        "snmp_v3_required":  r"snmp-server group .* v3 auth",
        "aaa_enabled":       r"aaa new-model",
        "logging_enabled":   r"logging \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
        "ntp_configured":    r"ntp server",
        "no_cdp_edge":       r"no cdp enable",
    }


class MikrotikDriver(BaseNetworkDriver):
    """Driver for MikroTik RouterOS via API"""

    async def get_running_config(self) -> str:
        # Uses MikroTik API library (librouteros)
        import librouteros
        creds = await self.cred_mgr.get_api_credentials(self.host)
        api = librouteros.connect(
            host=self.host,
            username=creds['username'],
            password=creds['password']
        )
        export = api('/export verbose')
        return "\n".join(export)

    async def execute_command(self, command: str) -> str:
        # RouterOS API command execution
        import librouteros
        creds = await self.cred_mgr.get_api_credentials(self.host)
        api = librouteros.connect(
            host=self.host, username=creds['username'], password=creds['password']
        )
        return str(list(api(command)))
```

### 1.2 Topology Builder

```python
# backend/services/noc_service/analyzers/topology_builder.py

class TopologyBuilder:
    """
    Builds network topology graph from LLDP/CDP discovery data.
    Output: NetworkX graph suitable for D3.js visualization.
    """

    def __init__(self, db_session, device_driver_factory):
        self.db = db_session
        self.driver_factory = device_driver_factory

    async def discover_topology(self, tenant_id: str) -> dict:
        """Full topology discovery across all managed devices"""
        devices = await self.db.get_all_devices(tenant_id)
        graph_nodes = []
        graph_edges = []

        for device in devices:
            driver = self.driver_factory.get_driver(device)

            # Gather LLDP neighbors
            lldp_neighbors = await driver.get_lldp_neighbors()

            # Gather CDP neighbors (Cisco)
            cdp_neighbors = []
            if device.vendor == "Cisco":
                cdp_neighbors = await driver.get_cdp_neighbors()

            node = {
                "id":       str(device.id),
                "hostname": device.hostname,
                "ip":       str(device.ip_address),
                "vendor":   device.vendor,
                "category": device.category,
                "status":   device.status,
                "location": device.location,
                "metrics": {
                    "cpu":  device.last_cpu_util,
                    "mem":  device.last_mem_util,
                    "uptime": device.uptime_seconds
                }
            }
            graph_nodes.append(node)

            for neighbor in lldp_neighbors + cdp_neighbors:
                edge = {
                    "source":      str(device.id),
                    "target_ip":   neighbor.get('remote_ip'),
                    "local_port":  neighbor.get('local_port'),
                    "remote_port": neighbor.get('remote_port'),
                    "protocol":    neighbor.get('protocol', 'lldp'),
                    "bandwidth":   neighbor.get('speed_mbps')
                }
                graph_edges.append(edge)

        # Resolve target IPs to device IDs
        resolved_edges = await self._resolve_edges(graph_edges, devices)

        return {
            "nodes": graph_nodes,
            "edges": resolved_edges,
            "generated_at": datetime.utcnow().isoformat()
        }
```

### 1.3 NOC Dashboard Components

```
NOC DASHBOARD LAYOUT:
┌─────────────────────────────────────────────────────────────────────────────┐
│  AEAOP NOC DASHBOARD                          🔴 3 Critical  🟡 12 Warning  │
├────────────────────┬───────────────────────────┬────────────────────────────┤
│  DEVICE STATUS     │  NETWORK TOPOLOGY          │  ACTIVE ALERTS             │
│  ┌─────────────┐   │  [Interactive D3.js Graph] │  ┌──────────────────────┐ │
│  │ Online: 847 │   │                            │  │🔴 core-rtr-01        │ │
│  │ Offline: 3  │   │  Nodes: ● green=ok         │  │   CPU: 98% (5min)    │ │
│  │ Degraded: 8 │   │         ● red=down          │  │   AI: BGP storm      │ │
│  │ Unknown: 2  │   │         ● yellow=warn        │  │   [View] [Fix]       │ │
│  └─────────────┘   │  Edges: — green=up          │  ├──────────────────────┤ │
│                    │         — red=down           │  │🔴 sw-access-07       │ │
│  TOP ISSUES:       │         — dashed=degraded    │  │   Port GE0/5 DOWN    │ │
│  • BGP flapping    │                            │  │   AI: Cable fault    │ │
│  • High CPU x2     │  [Filter] [Export]         │  │   [View] [Fix]       │ │
│  • Disk 95%        │                            │  └──────────────────────┘ │
├────────────────────┴───────────────────────────┴────────────────────────────┤
│  BANDWIDTH ANALYTICS                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  [Real-time bandwidth chart — 5-minute granularity — 24hr view]     │  │
│  │  Top Talkers: 192.168.1.50 (4.2 Gbps out)  192.168.5.10 (2.1 Gbps) │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. AI-POWERED SOC DESIGN

### 2.1 SIEM Architecture

```
                    SIEM DATA PIPELINE

  Log Sources               Collection              Processing
  ──────────                ──────────              ──────────
  Firewall (Syslog) ──────► Syslog Server  ──────► Logstash/
  Windows Event Log ──────► Winlogbeat     ──────► Fluentd   ──► Elasticsearch
  Linux Auditd      ──────► Filebeat       ──────► Pipeline
  IDS/IPS (Syslog)  ──────► Syslog Server            │
  NetFlow           ──────► Collector                │
  Web Proxy         ──────► API            ──────────┘
  DNS               ──────►               
  Email Gateway     ──────►               
                                          Enrichment:
                                          • GeoIP lookup
                                          • DNS reverse lookup
                                          • Asset lookup (is this a known server?)
                                          • IOC matching (threat intel)
                                          • UEBA risk scoring
                                          • AI threat classification

Log Retention Policy:
  Hot (0-30 days):    Elasticsearch (fast search)
  Warm (31-90 days):  Elasticsearch ILM frozen
  Cold (91-365 days): MinIO object storage (compressed)
  Archive (1-7 years): Tape/cold storage (compliance)
```

### 2.2 Threat Detection Rules

```python
# soc_service/engines/threat_detection.py

DETECTION_RULES = [
    {
        "id": "SOC-001",
        "name": "Brute Force Login Detection",
        "description": "Multiple failed login attempts from single source",
        "query": {
            "event_id": [4625],                    # Windows failed login
            "time_window": "5 minutes",
            "threshold": 10,
            "group_by": ["source_ip", "target_host"]
        },
        "severity": "high",
        "mitre_tactic": "TA0006",                  # Credential Access
        "mitre_technique": "T1110",                # Brute Force
        "auto_response": "block_source_ip_temp"
    },
    {
        "id": "SOC-002",
        "name": "Lateral Movement — Pass the Hash",
        "description": "Same hash used across multiple systems",
        "query": {
            "event_id": [4624],
            "logon_type": 3,                       # Network logon
            "auth_package": "NTLM",
            "time_window": "10 minutes",
            "threshold": 5,
            "group_by": ["ntlm_hash"]
        },
        "severity": "critical",
        "mitre_tactic": "TA0008",                  # Lateral Movement
        "mitre_technique": "T1550.002",            # Pass the Hash
    },
    {
        "id": "SOC-003",
        "name": "Data Exfiltration — Large Outbound Transfer",
        "description": "Unusually large data transfer to external IP",
        "query": {
            "direction": "outbound",
            "bytes_threshold": 500_000_000,        # 500MB in single session
            "dst_ip_type": "external",
            "time_window": "1 hour"
        },
        "severity": "critical",
        "mitre_tactic": "TA0010",                  # Exfiltration
        "mitre_technique": "T1048",
    },
    {
        "id": "SOC-004",
        "name": "DNS Tunneling Detection",
        "description": "High volume of DNS queries with large TXT records",
        "query": {
            "protocol": "DNS",
            "record_type": "TXT",
            "query_length_threshold": 100,
            "queries_per_minute": 50,
            "group_by": ["source_ip"]
        },
        "severity": "high",
        "mitre_tactic": "TA0011",                  # Command and Control
        "mitre_technique": "T1071.004",            # DNS
    },
    {
        "id": "SOC-005",
        "name": "Ransomware Indicator — Mass File Modification",
        "description": "Rapid file encryption pattern on file server",
        "query": {
            "event_id": [4663],                    # File access
            "operations": ["WRITE", "DELETE"],
            "file_extension_changes": True,
            "threshold": 100,
            "time_window": "2 minutes",
            "group_by": ["user", "host"]
        },
        "severity": "critical",
        "mitre_tactic": "TA0040",                  # Impact
        "mitre_technique": "T1486",                # Data Encrypted for Impact
        "auto_response": "isolate_host_network"
    }
]
```

### 2.3 UEBA (User Entity Behavior Analytics)

```python
# soc_service/engines/ueba_engine.py

class UEBAEngine:
    """
    Behavioral baseline establishment and anomaly scoring.
    Uses statistical models for baseline, AI for context.
    """

    BEHAVIOR_CATEGORIES = {
        "login_patterns": [
            "typical_login_hours",      # e.g., 8am-6pm weekdays
            "typical_login_locations",  # office IP ranges
            "typical_login_devices",    # registered workstations
            "login_frequency",          # logins per day
        ],
        "data_access": [
            "typical_data_volume",      # bytes accessed per day
            "sensitive_data_access",    # access to classified data
            "bulk_download_pattern",    # files downloaded at once
        ],
        "network_behavior": [
            "outbound_destinations",    # typical external destinations
            "bandwidth_usage",          # normal bandwidth per day
            "protocol_usage",           # typical protocols used
        ],
        "admin_activity": [
            "privilege_use_frequency",  # sudo/admin actions per day
            "account_creation",         # new accounts created
            "policy_changes",           # security policy modifications
        ]
    }

    def calculate_risk_score(self, entity_id: str, current_behavior: dict,
                              baseline: dict) -> dict:
        score = 0
        anomalies = []

        # Login outside typical hours (+20 points)
        if self._is_outside_typical_hours(
            current_behavior['login_time'],
            baseline['typical_login_hours']
        ):
            score += 20
            anomalies.append({
                "type": "unusual_login_time",
                "detail": f"Login at {current_behavior['login_time']} (baseline: {baseline['typical_login_hours']})",
                "points": 20
            })

        # Login from new location (+30 points)
        if current_behavior['source_ip'] not in baseline['known_ips']:
            score += 30
            anomalies.append({
                "type": "new_login_location",
                "detail": f"New IP: {current_behavior['source_ip']}",
                "points": 30
            })

        # Data volume anomaly (+25 points per standard deviation)
        z_score = self._calculate_z_score(
            current_behavior['data_volume_bytes'],
            baseline['avg_daily_bytes'],
            baseline['std_daily_bytes']
        )
        if z_score > 3.0:
            points = min(50, int(z_score * 10))
            score += points
            anomalies.append({
                "type": "data_volume_anomaly",
                "detail": f"Volume {z_score:.1f}x above baseline",
                "points": points
            })

        return {
            "entity_id": entity_id,
            "risk_score": min(100, score),
            "risk_level": "critical" if score >= 80 else
                          "high" if score >= 60 else
                          "medium" if score >= 40 else "low",
            "anomalies": anomalies,
            "timestamp": datetime.utcnow().isoformat()
        }
```

---

## 3. PHYSICAL SECURITY AI DESIGN

### 3.1 Vision Pipeline Architecture

```
REALISTIC PHYSICAL SECURITY AI CAPABILITIES
(What AI can and cannot do)

┌─────────────────────────────────────────────────────────────────────────────┐
│  WHAT AEAOP VISION AI CAN DO (Realistic)                                    │
│                                                                             │
│  ✅ Person Detection & Counting                                             │
│     - Detect presence of people in frame                                   │
│     - Count number of people in zone                                       │
│     - Track individuals across frames (ByteTrack)                          │
│     - Estimate direction of movement                                        │
│                                                                             │
│  ✅ Zone Monitoring                                                         │
│     - Alert when person enters restricted area                             │
│     - Count people in queues (bank teller lines, entry points)             │
│     - Detect loitering (person in zone > X minutes)                        │
│     - Detect crowd formation (density exceeds threshold)                   │
│                                                                             │
│  ✅ Motion Analysis                                                         │
│     - Detect motion in no-motion zones (after hours)                       │
│     - Direction and speed estimation                                        │
│     - Detect running vs. walking behavior                                  │
│     - Detect abandoned objects (object without person > X min)             │
│                                                                             │
│  ✅ Object Detection (Visible Objects Only)                                 │
│     - Large bags/backpacks in restricted areas                             │
│     - Vehicles in no-vehicle zones                                         │
│     - Open/closed door monitoring                                          │
│     - Fire/smoke detection (integrated with specialized models)            │
│                                                                             │
│  ✅ Suspicious Behavior Detection                                           │
│     - Tailgating (two people through one-badge entry)                      │
│     - Unusual loitering near ATMs or server rooms                          │
│     - Person looking around nervously (jitter analysis)                    │
│     - After-hours access attempts                                          │
│                                                                             │
│  ✅ Risk Scoring                                                            │
│     - Zone-based risk (server room > lobby)                                │
│     - Time-based risk (3am > 2pm)                                          │
│     - Behavior pattern risk score                                          │
│     - Combined score triggers human review                                 │
│                                                                             │
│  ❌ WHAT AI CANNOT DO (Honest Disclaimer)                                  │
│     ✗ Detect hidden/concealed weapons (X-ray hardware required)            │
│     ✗ 100% accurate face recognition (not deployed — privacy/bias risk)    │
│     ✗ Determine intent with certainty                                      │
│     ✗ Read lips or hear audio (separate system needed)                     │
│     ✗ Replace human security judgment                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Vision Event Processing Pipeline

```python
# physec_service/vision/pipeline.py

class VisionPipeline:
    """
    Real-time camera stream processing pipeline.
    Processing chain: Ingest → Detect → Track → Classify → Score → Alert
    """

    def __init__(self, camera_config: dict, models: dict):
        self.camera_id = camera_config['id']
        self.rtsp_url = camera_config['rtsp_url']
        self.zone_config = camera_config['zones']
        self.fps = camera_config.get('process_fps', 5)  # Process every Nth frame

        # Models
        self.detector = models['yolo']          # YOLO v11
        self.tracker = models['bytetrack']      # ByteTrack
        self.behavior = models['behavior']      # Behavior classifier
        self.vl_model = models['vision_llm']   # Qwen2.5-VL for analysis

    async def process_stream(self):
        cap = cv2.VideoCapture(self.rtsp_url)
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                await self._handle_stream_loss()
                continue

            frame_count += 1
            if frame_count % self.fps != 0:
                continue  # Skip frames to maintain desired FPS

            # Step 1: Detect objects
            detections = await self.detector.detect(frame)
            persons = [d for d in detections if d['class'] == 'person']
            objects = [d for d in detections if d['class'] != 'person']

            # Step 2: Track persons
            tracked = self.tracker.update(persons, frame)

            # Step 3: Zone analysis
            zone_events = self._analyze_zones(tracked, objects)

            # Step 4: Behavior analysis
            behavior_events = await self._analyze_behavior(tracked, zone_events)

            # Step 5: Risk scoring
            risk_events = self._score_events(behavior_events)

            # Step 6: Trigger alerts for high-risk events
            for event in risk_events:
                if event['risk_score'] >= 60:
                    await self._trigger_alert(event, frame)

    def _analyze_zones(self, tracked_persons: list, objects: list) -> list:
        events = []

        for person in tracked_persons:
            person_bbox = person['bbox']
            person_id = person['track_id']

            for zone in self.zone_config:
                if self._bbox_in_zone(person_bbox, zone['polygon']):
                    if zone['type'] == 'restricted':
                        events.append({
                            "type": "restricted_area_entry",
                            "zone_name": zone['name'],
                            "person_track_id": person_id,
                            "timestamp": datetime.utcnow(),
                            "base_risk": 70
                        })

                    # Loitering check
                    dwell_time = self._get_dwell_time(person_id, zone['id'])
                    if dwell_time > zone.get('loiter_threshold_seconds', 120):
                        events.append({
                            "type": "loitering_detected",
                            "zone_name": zone['name'],
                            "person_track_id": person_id,
                            "dwell_seconds": dwell_time,
                            "base_risk": 50
                        })

        return events

    async def _trigger_alert(self, event: dict, frame):
        # Save snapshot to MinIO
        snapshot_path = await self._save_snapshot(frame)

        # For high-severity events, get VL model analysis
        if event['risk_score'] >= 80:
            analysis = await self._get_vl_analysis(frame, event)
            event['ai_description'] = analysis

        # Create alert in database and notify operators
        alert_data = {
            "camera_id": self.camera_id,
            "event_type": event['type'],
            "risk_score": event['risk_score'],
            "snapshot_path": snapshot_path,
            "zone_name": event.get('zone_name'),
            "ai_description": event.get('ai_description'),
            "status": "new"
        }

        await self.alert_service.create_vision_alert(alert_data)
        await self.websocket_service.broadcast(
            f"physec.alert",
            alert_data
        )

    async def _get_vl_analysis(self, frame, event: dict) -> str:
        """Use Qwen2.5-VL for detailed scene description"""
        image_b64 = frame_to_base64(frame)

        prompt = f"""
        Analyze this security camera frame. An alert was triggered for: {event['type']}
        Zone: {event.get('zone_name', 'unknown')}

        Describe:
        1. What you observe in the scene
        2. Number of people and their positions
        3. Any suspicious objects or behaviors
        4. Risk assessment (low/medium/high)

        Be objective and factual. This will be reviewed by a human security officer.
        """

        response = await self.vl_client.analyze(
            image=image_b64,
            prompt=prompt,
            model="qwen2.5-vl-72b"
        )

        return response.content
```

### 3.3 Human Security Officer Verification Workflow

```
SECURITY EVENT VERIFICATION WORKFLOW:

AI Detects Event (risk_score ≥ 60)
          │
          ▼
Auto-save snapshot + 10-second video clip
          │
          ▼
Notification sent to Security Officer dashboard + mobile app
          │
          ▼
Officer reviews:
  ┌──────────────────────────────────────────┐
  │  EVENT: Restricted Area Entry           │
  │  Camera: Server Room Cam 3              │
  │  Time: 2026-06-04 03:47:12             │
  │  Risk Score: 85/100                    │
  │  AI Analysis: "One person in blue shirt │
  │  entered server room at 3:47am.        │
  │  No badge scan detected."              │
  │  [View Snapshot] [Play Clip]           │
  │                                        │
  │  [✅ Confirm — Security Breach]        │
  │  [⚠️  Confirm — Authorized Person]    │
  │  [❌ False Positive]                   │
  └──────────────────────────────────────────┘
          │
          ▼
   IF CONFIRMED BREACH:
   → Create Security Incident
   → Notify Security Manager
   → Trigger lockdown protocol (if configured)
   → Preserve evidence chain (legal hold)
   → Integrate with physical access control system

   IF AUTHORIZED:
   → Log as verified access
   → AI model learns from feedback (reduces false positives)

   IF FALSE POSITIVE:
   → Log for model improvement
   → Adjust zone sensitivity if recurring
```

---

## 4. SERVER OPERATIONS CENTER

### 4.1 PXE Boot Deployment

```python
# server_service/provisioners/pxe_boot.py

class PXEBootProvisioner:
    """
    Automated OS deployment via PXE boot + cloud-init
    Supports: Ubuntu, RHEL/CentOS, Windows Server, VMware ESXi
    """

    SUPPORTED_OS = {
        "ubuntu-22.04": {
            "kernel": "vmlinuz-22.04",
            "initrd": "initrd-22.04",
            "preseed": "ubuntu-22.04-preseed.cfg",
            "cloud_init": True
        },
        "ubuntu-24.04": {
            "kernel": "vmlinuz-24.04",
            "initrd": "initrd-24.04",
            "autoinstall": True
        },
        "rhel-9": {
            "kernel": "vmlinuz-rhel9",
            "initrd": "initrd-rhel9",
            "kickstart": "rhel9-ks.cfg"
        },
        "windows-2022": {
            "wds": True,
            "answer_file": "autounattend.xml"
        }
    }

    async def provision_server(self, provision_request: dict) -> str:
        """
        Full automated server provisioning:
        1. Configure DHCP (assign IP to MAC)
        2. Configure TFTP (set PXE boot file)
        3. Configure preseed/kickstart/autoinstall
        4. Boot server → OS installs automatically
        5. Post-install: Ansible hardening + agent install
        """
        server_mac = provision_request['mac_address']
        os_type = provision_request['os_type']
        hostname = provision_request['hostname']
        ip_address = provision_request['ip_address']

        # Step 1: Generate OS-specific config
        os_config = await self._generate_os_config(provision_request)

        # Step 2: Configure DHCP reservation
        await self._configure_dhcp(server_mac, ip_address, hostname)

        # Step 3: Configure PXE boot
        await self._configure_pxe(server_mac, os_type, os_config)

        # Step 4: Wait for installation
        job_id = str(uuid.uuid4())
        await self._start_monitoring_job(job_id, ip_address, hostname)

        return job_id

    async def _generate_ubuntu_autoinstall(self, request: dict) -> str:
        """Generate Ubuntu 24.04 autoinstall YAML"""
        return yaml.dump({
            "version": 1,
            "identity": {
                "hostname": request['hostname'],
                "username": "sysadmin",
                "password": await self._hash_password(request['initial_password'])
            },
            "network": {
                "ethernets": {
                    request.get('primary_nic', 'ens3'): {
                        "addresses": [f"{request['ip_address']}/24"],
                        "gateway4": request['gateway'],
                        "nameservers": {"addresses": request['dns_servers']}
                    }
                },
                "version": 2
            },
            "storage": {
                "layout": {"name": "lvm"}
            },
            "packages": [
                "openssh-server", "python3", "curl", "git"
            ],
            "late-commands": [
                f"curtin in-target -- bash -c 'curl -s http://aeaop.internal/agent/install.sh | bash'"
            ]
        })
```

### 4.2 Patch Management

```python
# server_service/tasks/patch_management.py

class PatchManagementEngine:
    """
    Automated patch discovery, planning, and execution.
    Uses AI for:
    1. CVE impact analysis (is this CVE relevant to our systems?)
    2. Patch scheduling (optimal maintenance window)
    3. Rollback planning
    """

    async def assess_patch_risk(self, server: dict, patches: list) -> dict:
        """AI-assisted patch risk assessment"""
        prompt = f"""
        You are a senior Linux/Windows system administrator.

        Server: {server['hostname']} ({server['os_name']} {server['os_version']})
        Role: {server['role']} (environment: {server['environment']})

        Pending patches:
        {json.dumps(patches, indent=2)}

        For each patch, assess:
        1. Risk level (low/medium/high/critical)
        2. Impact on server role
        3. Recommended action (apply immediately / schedule / defer)
        4. Estimated downtime required (if any)

        Return structured JSON.
        """

        return await self.llm.generate(prompt, model="qwen3-72b")

    async def create_patch_schedule(self, tenant_id: str) -> dict:
        """Create optimized patch schedule across all servers"""
        # Group servers by criticality and environment
        # Critical prod servers: only in maintenance windows
        # Dev/test: immediate patching allowed
        # Use AI to identify patch dependencies and optimal order
        pass
```
