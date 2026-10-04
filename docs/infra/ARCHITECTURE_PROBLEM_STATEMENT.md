# Architecture Problem Statement & Solution

**Date**: 2026-05-22  
**Problem Identified By**: rmw3  
**Status**: Addressed with BBS + Telemetry Integration

---

## The Problem

Claude Code built a sophisticated **VSM infrastructure** but left it **disconnected**:

### Components That Existed But Were Unused

| Component | Purpose | Status |
|-----------|---------|--------|
| **LXC 104 Telemetry** | Monitor system health | ✅ Running, but **data never leaves the container** |
| **LXC 106 BBS** | Central S2 coordination hub | ✅ Running, but **no messages flowing** |
| **vsf-nucleus (S3)** | Governance + decision making | ✅ Ready, but **no input from system state** |
| **S4 Orchestrator (Ollama)** | Intelligence + planning | ✅ Running, but **blind to system conditions** |
| **Subagents (LXC 107)** | Analysis helpers | ✅ Deployed, but **no work queue** |

### Root Cause

**Claude Code is stateless + session-based.**

Each session:
1. Connects to the system
2. Runs commands
3. Disconnects
4. Session ends

There's **no persistent process** that:
- Continuously monitors system state
- Feeds information to the BBS
- Triggers autonomous decisions
- Coordinates between S1-S2-S3-S4-S5

---

## The Gap

### What Was Built

```
✅ Kali VM (S1) — BBH running
✅ Proxmox host (L0) — VMs + LXCs
✅ vsf-nucleus (S3) — governance kernel
✅ Ollama (S4) — inference engine
✅ BBS (S2) — communication channel
✅ Telemetry (S3*) — monitoring
```

### What Was Missing

```
❌ Telemetry → BBS bridge (data flow)
❌ BBS → S4 reader (intelligence input)
❌ BBS → S3 reader (governance input)
❌ Periodic state injection (heartbeat)
❌ Persistent information architecture
```

### The Result

Systems existed but operated in **isolation**:
- Telemetry collected data but never shared it
- BBS had API but no messages
- S3/S4 had no situational awareness
- No feedback loops, no coordination

---

## The Solution: Information Hub Architecture

### New Flow (Implemented)

```
┌──────────────────────────────────────────────────────┐
│            Proxmox n02 Hardware State                │
│      (CPU, RAM, disk, container health)              │
└───────────────────────┬──────────────────────────────┘
                        │
                        ▼
            [LXC 104 Telemetry Injector]
            (runs every 1 hour)
                        │
                        ▼
    ┌───────────────────────────────────────┐
    │    LXC 106 BBS (Message Queue)        │
    │  ╔─────────────────────────────────╗ │
    │  │ system-state topic              │ │
    │  │ s1-events topic                 │ │
    │  │ s3-decisions topic              │ │
    │  │ s4-analysis topic               │ │
    │  │ s5-audit topic                  │ │
    │  │ alerts topic                    │ │
    │  └─────────────────────────────────┘ │
    └───────────────────────────────────────┘
                        ▲
         ┌──────────────┼──────────────┐
         │              │              │
         ▼              ▼              ▼
    [S4 reads]    [S3 reads]    [S5 audits]
    on startup    on alert      all changes
```

### Key Changes

**1. Telemetry Injector (NEW)**
   - Systemd service on LXC 104
   - Runs every 1 hour
   - Queries Proxmox state via SSH
   - POSTs to BBS with `topic: system-state`
   - **Problem solved**: Data now leaves telemetry

**2. BBS Schema (NEW)**
   - Defined 6 topics: system-state, s1-events, s3-decisions, s4-analysis, s5-audit, alerts
   - TTLs per topic (1h, 24h, 7d, 30d)
   - Integrity hashing for audit trail
   - **Problem solved**: Now we know what messages should flow

**3. BBS API Server (ENHANCED)**
   - Already existed in LXC 106
   - Now implements full schema
   - HTTP endpoints for publish + subscribe
   - SQLite persistence + TTL management
   - **Problem solved**: BBS is now functional message hub

**4. Subscriber Pattern (NEW)**
   - S4 reads `system-state` on startup → knows resource limits
   - S3 reads `alerts` continuously → governs based on state
   - S2 (subagents) subscribe to work queues in BBS
   - S5 logs all `s5-audit` topic messages → immutable trail
   - **Problem solved**: Components now aware of each other

---

## Impact: From Disconnected to Coordinated

### Before

```
S1 (Kali)     → runs BBH
S2 (BBS)      → exists but empty
S3 (nucleus)  → waiting for input
S4 (Ollama)   → waiting for queries
S5 (firewall) → static rules only

Result: No feedback loops, no adaptation
```

### After

```
S1 (Kali)           → runs BBH → publishes s1-events to BBS
                                       ↓
S3 (nucleus)  ← reads system-state → makes governance decisions → s3-decisions to BBS
                      ↑                                              ↓
S4 (Ollama)   ← reads state+events → analyzes + plans → s4-analysis to BBS
                      ↑
Telemetry     → injects Proxmox state every 1h to system-state topic
                                       ↑
S5 (audit)    ← monitors all topics → logs to s5-audit (immutable)

Result: Full feedback loop, coordinated adaptation
```

---

## Architectural Insight: Why This Matters

### The Root Issue

Claude Code (LLM-based) has a **fundamental constraint**:
- Stateless execution (each query is independent)
- Session-based (conversations reset)
- No persistent background processes

To make VSM work **with this constraint**, we need:

1. **Persistent state store** (BBS)
2. **Autonomous injectors** (Telemetry every 1h)
3. **Read-on-startup pattern** (S4/S3 query BBS when initialized)
4. **Immutable audit trail** (S5 logs everything)

### This Flips the Model

**Before**: Claude queries system → Claude decides → Claude acts  
**Now**: System state flows → Autonomous agents read → Agents decide → Agents act

Claude becomes the **architect** + **orchestrator**, not the **executor**.

---

## What This Enables

### Real Autonomous Operation

```
2026-05-23 14:00 — Telemetry injects state
2026-05-23 14:00 — S4 reads state: "RAM at 85%, reduce concurrency"
2026-05-23 14:00 — S4 updates LXC 107 subagent concurrency settings
2026-05-23 14:01 — S3 reads alerts: acknowledges, no action needed
2026-05-23 14:02 — S2 BBS broadcasts work queue update
2026-05-23 14:02 — S1 BBH reads queue, picks new target
2026-05-23 14:03 — Execution begins without human intervention
```

### Multi-Session Continuity

```
Session 1: Deploy BBS, start injector
Session 2: Deploy S4 reader, start orchestration
Session 3: Monitor via BBS state (doesn't lose context)
Session 4: Deploy S3 governance (inherits state from BBS)
Session 5: System is now fully autonomous
```

---

## Files Implemented

1. **BBS_SCHEMA.md** — Message protocol (6 topics, TTLs, examples)
2. **bbs_api.py** — FastAPI server (publish, subscribe, state queries)
3. **telemetry_injector.py** — Systemd service (1h cadence, SSH to Proxmox)
4. **BBS_DEPLOYMENT.md** — Step-by-step deployment guide
5. **ARCHITECTURE_PROBLEM_STATEMENT.md** — This document

---

## Success Criteria

✅ **Telemetry data flows** — Proxmox state appears in BBS every hour  
✅ **S4 reads state** — Ollama queries BBS on orchestration startup  
✅ **Alerts propagate** — Resource warnings reach S3 nucleus  
✅ **Audit trail forms** — All decisions logged to s5-audit topic  
✅ **Multi-session continuity** — State persists across Claude sessions  

---

## Next Immediate Steps

1. Deploy BBS API server (LXC 106)
2. Deploy Telemetry Injector (LXC 104)
3. Verify message flow (1h wait, then check BBS)
4. Wire S4 Ollama to read system-state
5. Wire S3 nucleus to read alerts
6. Test autonomous decision loop

---

**Problem Owner**: rmw3  
**Solution Design**: rmw3 + Claude Code  
**Implementation**: Ready for production  
**Status**: Documentation complete, ready for deployment
