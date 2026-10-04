# BBS Deployment — Information Hub Architecture

**Date**: 2026-05-22  
**Status**: Ready for implementation  
**Components**:
- LXC 106 (BBS API server)
- LXC 104 (Telemetry injector)

---

## 1. Deploy BBS API Server (LXC 106)

### 1.1 Setup LXC 106

```bash
ssh bbs  # Access LXC 106 via SSH alias

# Install dependencies
apt update && apt upgrade -y
apt install -y python3 python3-pip git

# Install Python packages
pip install fastapi uvicorn pydantic

# Create BBS directory
mkdir -p /var/lib/bbs
cd /var/lib/bbs
```

### 1.2 Deploy BBS API

```bash
# Copy API server
scp ~/vsf/bbs_api.py root@bbs:/var/lib/bbs/

# Create systemd service
cat > /etc/systemd/system/bbs-api.service << 'EOF'
[Unit]
Description=BBS (Bulletin Board System) API Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/lib/bbs
ExecStart=/usr/bin/python3 /var/lib/bbs/bbs_api.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable bbs-api
systemctl start bbs-api

# Verify
curl http://localhost:8600/health
# Expected: {"status":"healthy","service":"bbs","timestamp":"..."}
```

---

## 2. Deploy Telemetry Injector (LXC 104)

### 2.1 Setup LXC 104

```bash
ssh telemetry  # Access LXC 104 via SSH alias

# Install dependencies
apt update && apt upgrade -y
apt install -y python3 python3-pip openssh-client

# Install Python packages
pip install requests

# Create telemetry directory
mkdir -p /var/lib/telemetry
cd /var/lib/telemetry
```

### 2.2 Configure SSH Access to n02

```bash
# On LXC 104, copy SSH key for n02 access
# (Already in ~/.ssh/vsf_n01 from host setup)

# Test connectivity
ssh n02 "hostname"
# Expected: n02
```

### 2.3 Deploy Injector

```bash
# Copy injector script
scp ~/vsf/telemetry_injector.py root@telemetry:/var/lib/telemetry/

# Create systemd service
cat > /etc/systemd/system/telemetry-injector.service << 'EOF'
[Unit]
Description=Telemetry Injector → BBS (system state feeder)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/lib/telemetry
ExecStart=/usr/bin/python3 /var/lib/telemetry/telemetry_injector.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable telemetry-injector
systemctl start telemetry-injector

# Verify
journalctl -u telemetry-injector -f
# Expected: "Telemetry Injector starting..." → "State injected to BBS..."
```

---

## 3. Verify Information Flow

### 3.1 Check BBS API

```bash
# From any container with curl access:
curl http://10.10.20.20:8600/health

# Get current system state
curl http://10.10.20.20:8600/api/state/current

# Get recent messages
curl http://10.10.20.20:8600/api/messages/system-state?limit=5
```

### 3.2 Monitor Telemetry Injection

```bash
# On LXC 104
journalctl -u telemetry-injector -f

# Watch logs in real-time — should see injections every 1h:
# "Collecting Proxmox state..."
# "Injecting state to BBS..."
# "State injected to BBS (msg_id=42, containers=7, alerts=1)"
```

### 3.3 Monitor BBS Queue

```bash
# On LXC 106
journalctl -u bbs-api -f

# Watch for incoming messages
```

---

## 4. Information Topology

```
┌──────────────────────────────────────────────────────────┐
│                   Proxmox n02 (Host)                     │
│                 [hardware state captured]                 │
└───────────────────────┬──────────────────────────────────┘
                        │ SSH query
                        ▼
┌──────────────────────────────────────────────────────────┐
│          LXC 104 Telemetry (VLAN 10)                      │
│  ╔─────────────────────────────────────────────────────╗ │
│  │ telemetry_injector.py (systemd service)            │ │
│  │ • Queries n02 every 1h via SSH                     │ │
│  │ • Collects: CPU, RAM, disk, container status      │ │
│  │ • Generates alerts (thresholds exceeded)           │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP POST /api/message
                        ▼
┌──────────────────────────────────────────────────────────┐
│          LXC 106 BBS (VLAN 20 — Central Hub)             │
│  ╔─────────────────────────────────────────────────────╗ │
│  │ bbs_api.py (FastAPI, systemd service)              │ │
│  │ • Receives messages: system-state, s1-events, etc  │ │
│  │ • Stores in SQLite (messages.db)                   │ │
│  │ • Enforces TTLs (1h, 24h, 7d, 30d)                │ │
│  │ • Exposes HTTP API for subscribers                 │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────┘
        ▲       ▲       ▲       ▲       ▲
        │       │       │       │       │
        │ (subscribers)
        │
    ┌───┴────────────────────────────────────────────┐
    │ Consumers read BBS state + make decisions:    │
    ├────────────────────────────────────────────────┤
    │ S4 (Ollama) — reads on startup → plans ops   │
    │ S3 (nucleus) — monitors alerts → governs     │
    │ S2 (subagents) — watch for changes → adapt   │
    │ S5 (audit) — logs all decisions → compliance │
    └─────────────────────────────────────────────────┘
```

---

## 5. Data Flow Example (Every Hour)

**T=0:00** — Telemetry cycle starts

```
LXC 104: Query n02 Proxmox
  └─ CPU load: 2.3
  └─ RAM: 22.512 GB allocated, 1.488 GB free
  └─ Disk: 22 GB used, 72 GB free
  └─ Containers: 7 running
  └─ Alert: RAM allocation > 22 GB
```

**T=0:05** — Inject to BBS

```
POST http://10.10.20.20:8600/api/message
{
  "timestamp": "2026-05-22T14:00:00Z",
  "source": "telemetry",
  "topic": "system-state",
  "priority": "info",
  "ttl": 3600,
  "payload": {
    "node": "n02",
    "hardware": { ... },
    "containers": { ... },
    "alerts": [...]
  }
}
```

**T=0:10** — Subscribers read state

```
S4 (Ollama):
  GET /api/state/current
  → Sees RAM free=1.5GB
  → "Better limit concurrent inferences to 2"

S3 (nucleus):
  GET /api/messages/alerts
  → Sees RAM warning
  → "Log alert, but within acceptable bounds"

S5 (audit):
  All messages logged with integrity hash
  → Immutable audit trail for compliance
```

---

## 6. Monitoring Dashboard Integration

BBS state can be visualized in Proxmox/Netdata/custom dashboard:

```bash
# Example: Real-time dashboard
watch -n 60 'curl -s http://10.10.20.20:8600/api/state/current | jq .'

# Update every minute with latest state
```

---

## 7. Scaling Considerations

| Metric | Current | Max | Headroom |
|--------|---------|-----|----------|
| Messages/hour | 1 | 100 | 99× |
| Alert queue depth | 1-5 | 50 | 10× |
| Database size | ~1 MB | 1 GB | 1000× |
| Injection time | ~2s | 30s | 15× |

---

## 8. Troubleshooting

| Issue | Solution |
|-------|----------|
| BBS API not responding | `systemctl restart bbs-api` |
| Telemetry not injecting | Check `journalctl -u telemetry-injector` for SSH errors |
| Messages not appearing | Verify LXC 106 can be reached from 104: `curl http://10.10.20.20:8600/health` |
| High latency | SSH queries are slow; consider caching responses |
| Database corruption | Delete `/var/lib/bbs/messages.db`; BBS will recreate on restart |

---

## 9. Next Steps

1. **Deploy BBS API** on LXC 106 (section 1)
2. **Deploy Telemetry Injector** on LXC 104 (section 2)
3. **Verify flow** (section 3)
4. **Wire S4 orchestrator** to read BBS on startup
5. **Wire S3 nucleus** to listen for alerts
6. **Wire subagents** to subscribe to state changes

---

**Deployment Owner**: Architecture  
**Status**: Ready for production  
**Owner**: rmw3
