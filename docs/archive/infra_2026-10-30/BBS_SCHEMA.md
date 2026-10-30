# BBS (Bulletin Board System) Schema — VSF Communication Protocol

**Status**: Active design (2026-05-22)  
**Version**: 1.0  
**Purpose**: Persistent inter-system communication + state hub

---

## Overview

BBS es el **canal S2 central** que coordina información entre S1, S3, S4, S5.

```
┌─────────────────────────────────────────────────────┐
│                    BBS (LXC 106)                     │
│              Persistent Message Queue                │
├─────────────────────────────────────────────────────┤
│  Topics:                                             │
│  • system-state    (Proxmox, LXCs, resources)       │
│  • s1-events       (BBH phases, findings)           │
│  • s3-decisions    (governance, policy changes)     │
│  • s4-analysis     (intelligence, recommendations)  │
│  • s5-audit        (compliance, security alerts)    │
│  • alerts          (anomalies, thresholds)          │
└─────────────────────────────────────────────────────┘
```

---

## Message Format

All messages to BBS follow this envelope:

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "telemetry",
  "topic": "system-state",
  "priority": "info|warning|critical",
  "ttl": 3600,
  "payload": { ... }
}
```

---

## Topic: `system-state`

**Source**: LXC 104 (Telemetry) — injected every 1 hour  
**Consumer**: S4 (orchestrator), S3 (nucleus), S5 (audit)  
**TTL**: 3600s (1 hour)

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "telemetry",
  "topic": "system-state",
  "priority": "info",
  "ttl": 3600,
  "payload": {
    "node": "n02",
    "hardware": {
      "cpu_cores": 8,
      "ram_total_gb": 24,
      "ram_allocated_gb": 22.512,
      "ram_free_gb": 1.488,
      "disk_total_gb": 94,
      "disk_used_gb": 22,
      "disk_free_gb": 72
    },
    "containers": {
      "vm_100_kali": {
        "status": "running",
        "ram_allocated_mb": 6144,
        "ram_used_mb": 4821,
        "cpu_load": 2.3,
        "disk_gb": 80,
        "network": "10.10.30.100",
        "vlan": 30
      },
      "lxc_101_ollama": {
        "status": "running",
        "ram_allocated_mb": 8192,
        "ram_used_mb": 6847,
        "model": "qwen2.5-coder:7b",
        "inference_pending": 0,
        "network": "10.10.20.10",
        "vlan": 20
      },
      "lxc_102_nucleus": {
        "status": "running",
        "ram_allocated_mb": 1024,
        "ram_used_mb": 512,
        "governance_mode": "trust=1.0",
        "network": "10.10.20.11",
        "vlan": 20
      },
      "lxc_104_telemetry": {
        "status": "running",
        "ram_allocated_mb": 256,
        "ram_used_mb": 128,
        "network": "10.10.10.10",
        "vlan": 10
      },
      "lxc_105_bbh_prod": {
        "status": "running",
        "ram_allocated_mb": 2048,
        "ram_used_mb": 1024,
        "disk_gb": 20,
        "network": "10.10.30.110",
        "vlan": 30
      },
      "lxc_106_bbs": {
        "status": "running",
        "ram_allocated_mb": 256,
        "ram_used_mb": 128,
        "queue_depth": 47,
        "network": "10.10.20.20",
        "vlan": 20
      },
      "lxc_107_subagents": {
        "status": "running",
        "ram_allocated_mb": 5120,
        "ram_used_mb": 2400,
        "services": ["asc-paper", "asc-rust", "asc-exp"],
        "network": "10.10.20.30",
        "vlan": 20
      }
    },
    "alerts": [
      {
        "severity": "warning",
        "container": "lxc_101_ollama",
        "metric": "ram_used_percent",
        "value": 83.5,
        "threshold": 85,
        "status": "approaching_limit"
      }
    ]
  }
}
```

---

## Topic: `s1-events`

**Source**: Kali VM (BBH pipeline) + bbh-prod LXC  
**Consumer**: S3 (decisions), S4 (analysis), S5 (audit)  
**TTL**: 86400s (24 hours)

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "bbh_orchestrator",
  "topic": "s1-events",
  "priority": "info",
  "ttl": 86400,
  "payload": {
    "phase": "P2_active",
    "target": "api.example.com",
    "status": "in_progress",
    "findings_count": 23,
    "critical_findings": [
      {
        "id": "F-2026-0512-001",
        "type": "sql_injection",
        "endpoint": "/api/users",
        "cvss_base": 8.9,
        "cvss_with_context": 9.5,
        "confidence": 0.95,
        "reproducible": true
      }
    ],
    "phase_duration_seconds": 1847,
    "progress_percent": 45
  }
}
```

---

## Topic: `s3-decisions`

**Source**: vsf-nucleus (S3 governance)  
**Consumer**: S1 (gates), S2 (coordination), S4 (planning)  
**TTL**: 604800s (7 days)

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "nucleus",
  "topic": "s3-decisions",
  "priority": "critical",
  "ttl": 604800,
  "payload": {
    "decision_id": "D-2026-0512-042",
    "decision_type": "escalate_finding",
    "finding_id": "F-2026-0512-001",
    "action": "approve_for_h1_submission",
    "rationale": "CVSS 9.5 exceeds threshold 5.5 with commercial impact multiplier",
    "approved_by": "nucleus",
    "timestamp_decided": "2026-05-22T14:30:00Z",
    "effective_until": "2026-05-29T14:30:00Z"
  }
}
```

---

## Topic: `s4-analysis`

**Source**: Ollama (qwen orchestrator) + subagents  
**Consumer**: S3 (decisions), S2 (coordination), S1 (gates)  
**TTL**: 86400s (24 hours)

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "s4_orchestrator",
  "topic": "s4-analysis",
  "priority": "info",
  "ttl": 86400,
  "payload": {
    "analysis_id": "A-2026-0512-018",
    "analysis_type": "attack_chain_correlation",
    "findings": ["F-2026-0512-001", "F-2026-0512-003"],
    "hypothesis": "Chained vulnerability: SQLi in /api/users → password reset token leak → account takeover",
    "confidence": 0.87,
    "exploitability": "high",
    "recommendation": "Bundle findings into single H1 report",
    "estimated_impact": "critical"
  }
}
```

---

## Topic: `s5-audit`

**Source**: Nucleus + Proxmox firewall logs  
**Consumer**: Audit trail (immutable), security review  
**TTL**: 2592000s (30 days)

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "nucleus",
  "topic": "s5-audit",
  "priority": "critical",
  "ttl": 2592000,
  "payload": {
    "event_id": "AUD-2026-0512-009",
    "event_type": "decision_made",
    "actor": "nucleus",
    "action": "approve_finding_escalation",
    "target_id": "F-2026-0512-001",
    "result": "approved",
    "reason": "CVSS threshold exceeded",
    "previous_state": "pending_review",
    "new_state": "approved_for_submission",
    "integrity_hash": "sha256:..."
  }
}
```

---

## Topic: `alerts`

**Source**: LXC 104 (Telemetry), nucleus (S3)  
**Consumer**: S3 (governance), S5 (audit), on-call (human)  
**TTL**: 604800s (7 days)

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "telemetry",
  "topic": "alerts",
  "priority": "warning",
  "ttl": 604800,
  "payload": {
    "alert_id": "ALRT-2026-0512-003",
    "alert_type": "resource_threshold",
    "container": "lxc_101_ollama",
    "metric": "memory_percent",
    "value": 83.5,
    "threshold": 85,
    "status": "warning",
    "recommendation": "Monitor closely; may need to reduce concurrent inference or scale up",
    "acknowledged": false,
    "acknowledged_by": null
  }
}
```

---

## BBS API Endpoints

### POST /api/message

Publish message to BBS:

```bash
curl -X POST http://localhost:8600/api/message \
  -H "Content-Type: application/json" \
  -d @message.json
```

### GET /api/messages/{topic}

Retrieve latest messages for topic:

```bash
curl http://localhost:8600/api/messages/system-state
```

### GET /api/state/current

Get latest state snapshot (all topics):

```bash
curl http://localhost:8600/api/state/current
```

### POST /api/alert/{alert_id}/acknowledge

Acknowledge alert:

```bash
curl -X POST http://localhost:8600/api/alert/ALRT-2026-0512-003/acknowledge \
  -H "Content-Type: application/json" \
  -d '{"acknowledged_by": "nucleus", "note": "Monitoring set to 15-min intervals"}'
```

---

## Implementation Checklist

- [ ] BBS HTTP API server (FastAPI, LXC 106)
- [ ] Message validation schema (Pydantic)
- [ ] SQLite persistence (messages.db)
- [ ] Telemetry injector systemd service (LXC 104)
- [ ] S4 reader (Ollama, reads BBS on startup)
- [ ] S3 reader (nucleus, reads alerts + decisions)
- [ ] S5 audit sink (all messages logged + hashed)
- [ ] Monitoring dashboard (integra BBS state)

---

**Owner**: Architecture  
**Status**: Design complete, ready for implementation  
**Next**: Deploy BBS API + telemetry injector
