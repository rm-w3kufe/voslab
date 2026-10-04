# PHASE 1.5 HANDOFF — BBH AUTONOMY BRIEF

**From:** Claude (S3 Control)  
**To:** @BBH (S1 Operations)  
**Date:** 2026-05-11  
**Status:** ✅ AUTHORIZED & IMPLEMENTED  
**Authority:** rmw3 (S5 Policy) — phase_1_wire GO + Phase 1.5 PLAN GO

---

## EXECUTIVE SUMMARY

Phase 1.5 adds 5 parallel intelligence + scheduling capabilities to BBH:
- **DEBT-3**: Real-time metrics (findings_rate anomaly detection, z-score >2.5σ)
- **DEBT-6**: Tool ROI profiling (skip low-efficiency tools)
- **DEBT-7**: RAG layer (find similar vulnerabilities from history)
- **DEBT-9**: Priority queue (bounty×0.4 + threat×0.3 + coverage×0.2 + staleness×0.1)
- **GAP-10**: Authenticated discovery (Phase 2.5) + multi-user IDOR testing

All enhancements are **non-blocking**: if any capability unavailable, BBH continues with graceful fallback (Ax_CapabilityFallback + Ax_LearningNonBlocking).

---

## PHASE 1.5 MODULE REFERENCE

### 1. FOUNDATION: findings_dao.py
**Location:** `/home/rmw3/claude/tools/scripts/findings_dao.py`

**Purpose:** Persistent SQLite database for all findings, metrics, outcomes, improvements.

**Schema:**
```
findings_dao/
├─ findings.db (SQLite)
   ├─ findings (id, target, scan_date, vuln_type, severity, priority, confidence)
   ├─ outcomes (scan_id, target, success, confidence, metrics)
   ├─ metrics (target, findings_rate, z_score, phase_duration, sla_breach, thermal)
   └─ improvements (target, phase, tool, finding_count, duration_sec, roi_score)
```

**Key Methods:**
```python
dao = FindingsDAO()
dao.save_finding(target, vuln_data)          # Store vulnerability
dao.save_outcome(scan_id, target, success, confidence, metrics)
dao.save_metrics(target, metrics_data)       # Store aggregated metrics
dao.save_improvement(target, phase, tool, finding_count, duration_sec)
dao.get_past_findings(target, min_confidence=0.7)
dao.get_metrics_history(target)
dao.get_tool_roi(min_roi=0.0)
```

**Integration:** All other Phase 1.5 modules depend on findings_dao. Initialize at startup.

---

### 2. DEBT-3: INTELLIGENT METRICS

#### 2.1 metrics_collector.py
**Location:** `/home/rmw3/claude/tools/scripts/metrics_collector.py`

**Purpose:** Collect findings_rate, phase_duration, thermal_profile after each scan. Compute z-score.

**Algorithm:**
```
z-score = (current_findings_per_min - mean) / stdev
If z-score > 2.5σ → anomaly detected
If phase_duration > SLA_threshold[intent] → SLA breach
```

**Intent-Specific SLA Thresholds:**
```python
INTENT_THRESHOLDS = {
    "pentest": 15,        # 15 min
    "compliance": 45,     # 45 min
    "red_team": 30,       # 30 min
    "threat_hunt": 10,    # 10 min
}
```

**Key Methods:**
```python
collector = MetricsCollector(dao=dao)
metrics = collector.collect_scan_metrics(
    target="affirm",
    findings_count=25,
    phase_duration_sec=600.0,
    thermal_profile={"avg": 58.0, "peak": 72.0},
    intent="pentest"
)
# Returns: {z_score, findings_per_min, sla_breach, ...}
```

**Hook:** Call from 5_report.py completion to capture metrics.

---

#### 2.2 anomaly_detection.py
**Location:** `/home/rmw3/claude/tools/scripts/anomaly_detection.py`

**Purpose:** Detect anomalies in metrics. Emit φ↑ governance signals to BBS.

**Detection Methods:**
1. **Z-score**: >2.5σ → high variance anomaly
2. **Delta threshold**: ±50% change from baseline
3. **SLA breach**: Phase duration exceeds intent threshold
4. **Thermal anomaly**: Peak >80°C
5. **Coverage gap**: Very high findings on small scope

**Key Methods:**
```python
detector = AnomalyDetector(dao=dao)
result = detector.detect_anomalies(target, metrics)
# Returns: {is_anomaly, reasons, severity, z_score, recommendation}

detector.emit_governance_metrics(target, result)  # Send φ↑ to BBS
```

**Output:** Logs to `~/bbh/metrics.json` for dashboard.

---

### 3. DEBT-6: IMPROVEMENT REGISTER

**Location:** `/home/rmw3/claude/tools/scripts/improvement_tracker.py`

**Purpose:** Track tool effectiveness (ROI) and suggest optimizations.

**ROI Formula:**
```
ROI = findings_count / duration_sec (findings per second)
Low ROI (<0.1) → suggest skipping for next scan
High ROI (>0.5) → prioritize
```

**Key Methods:**
```python
tracker = ImprovementTracker(dao=dao)

# Track execution
tracker.track_tool_execution(
    target="affirm",
    phase=4,
    tool="nuclei",
    finding_count=12,
    duration_sec=45.0
)

# Generate suggestions
suggestions = tracker.generate_suggestions(target)
# Returns: {suggestions: [...], high_roi_tools, low_roi_tools, summary}

# Apply to config
config = tracker.apply_suggestions_to_config(current_config, suggestions)
```

**Integration:** Hook from 4_vuln.py completion to track tools used.

---

### 4. DEBT-7: RAG LAYER

**Location:** `/home/rmw3/claude/tools/scripts/rag_engine.py`

**Purpose:** Find similar vulnerabilities from past scans using vector similarity.

**Setup:**
- **DB:** `/home/rmw3/bbh/findings.lancedb` (LanceDB persistent vector DB)
- **Embedding:** all-MiniLM-L6-v2 (384-dim vectors, ~22MB model)
- **Per-Program Isolation:** Never cross Affirm ↔ Shopify

**Key Methods:**
```python
rag = RAGEngine(dao=dao)

# Index finding
rag.index_finding(
    program="affirm",
    target="stripe.com",
    finding={
        "vuln_type": "SQL Injection",
        "severity": "high",
        "evidence": "SQLi in /api/search?q=",
        "remediation": "Use parameterized queries",
        "confidence": 0.95
    }
)

# Query similar
similar = rag.query_similar(
    program="affirm",
    target="stripe.com",
    finding_text="SQL injection vulnerability",
    limit=5
)
# Returns: [{target, vuln_type, severity, remediation, scan_date, ...}, ...]

# Phase 5 integration (auto-generate recommendations)
recommendations = rag.generate_phase5_recommendations(program, target, finding)
```

**Non-Blocking:** Gracefully falls back if LanceDB unavailable.

---

### 5. DEBT-9: MULTI-TARGET SCHEDULING

**Location:** `/home/rmw3/claude/tools/scripts/multi_target_scheduler.py`

**Purpose:** Prioritize targets dynamically instead of FIFO.

**Priority Formula:**
```
score = bounty×0.4 + threat×0.3 + coverage_gap×0.2 + staleness×0.1
```

All components normalized to [0,1].

**Fairness Constraint:**
- max_age = 24h: If any target not scanned in 24h, force it to top of queue
- Prevents starvation of low-priority targets

**Key Methods:**
```python
scheduler = MultiTargetScheduler(dao=dao)

# Enqueue with priority components
scheduler.enqueue_target(
    target="affirm",
    bounty=0.9,           # High bug bounty
    threat=0.7,           # Medium threat level
    coverage_gap=0.5,     # 50% endpoints untested
    phase=0,
    intent="pentest"
)

# Dequeue in priority order
next_job = scheduler.dequeue_target()
# Returns: {target, phase, intent, dequeued_at}

# Tune weights
scheduler.set_weights(bounty=0.4, threat=0.3, coverage_gap=0.2, staleness=0.1)
```

**Integration:** thermal_scheduler_enhanced.py calls this every tick.

---

### 6. GAP-10: AUTHENTICATED DISCOVERY

#### 6.1 credential_vault.py
**Location:** `/home/rmw3/claude/tools/scripts/credential_vault.py`

**Purpose:** Encrypted test account storage with per-program isolation.

**Encryption:** Fernet (AES-128-CBC equivalent)  
**Storage:** `~/bbh/vaults/{program}/{target}_{role}.enc`  
**Keys:** `~/.bbh/.vault_keys` (chmod 600)

**Security Axioms:**
- Ax_CredentialIsolation: Never cross-program
- Ax_CredentialSecurity: Never logged plaintext, always encrypted

**Key Methods:**
```python
vault = CredentialVault()

# Store credential (with encryption)
vault.store(
    program="affirm",
    target="stripe.com",
    credential={"username": "buyer_a", "password": "secret123"},
    role="user"
)

# Retrieve (decrypted)
cred = vault.retrieve(program="affirm", target="stripe.com", role="user")
# Returns: {username, password}

# List credentials for program
creds = vault.list_credentials(program="affirm")
# Returns: ["stripe.com_user", "affirm.com_user_b", ...]

# Audit trail
# All operations logged to ~/.bbh/vaults/.audit.log (no plaintext)
```

**Initialization:** On startup, auto-creates ~/bbh/vaults/ if missing.

---

#### 6.2 phase_2_5_authenticated.py
**Location:** `/home/rmw3/claude/tools/scripts/phase_2_5_authenticated.py`

**Purpose:** 
- Phase 2.5: Authenticated endpoint discovery
- Phase 4: Enhanced with multi-user IDOR testing

**Phase 2.5 Pipeline:**
```
1. Login with user A from credential_vault
2. Crawl authenticated endpoints (/api/me, /api/transactions, etc.)
3. Map private API surface (compare anon vs auth)
4. Test onboarding flow (register → email verify → login)
5. Store discovered endpoints in findings_dao for Phase 4
```

**Phase 4 Enhancement:**
```
Part 1: Anonymous vulns (current behavior)
Part 2: Authenticated vulns (user A context)
Part 3: Multi-user IDOR (A tries to access B's /api/transactions)
Part 4: State-dependent races (create account + immediately place transaction)
```

**Ethics Gate: Ax_MultiUserTesting**
```python
discovery = AuthenticatedDiscovery(dao=dao, vault=vault)

# Enable authenticated testing (gated by program_config)
discovery.enable_auth_testing(
    program="affirm",
    approved=True  # Must be explicitly approved
)

# Phase 2.5: Endpoint discovery
phase25_result = discovery.phase_2_5_discovery(
    program="affirm",
    target="stripe.com",
    base_url="https://stripe.com",
    username="buyer_a",
    password="secret123"
)
# Returns: {authenticated_endpoints, private_endpoints, onboarding_flow, ...}

# Phase 4: IDOR testing
phase4_result = discovery.phase_4_idor_testing(
    program="affirm",
    target="stripe.com",
    base_url="https://stripe.com",
    user_a="buyer_a",
    user_b="buyer_b"
)
# Returns: {idor_tests, vulns_found, ...}
```

**Non-Blocking:** If credentials unavailable or testing disabled, phase continues without this data.

---

### 7. INTEGRATION: thermal_scheduler_enhanced.py

**Location:** `/home/rmw3/claude/tools/scripts/thermal_scheduler_enhanced.py`

**Purpose:** Enhanced thermal scheduler integrating all Phase 1.5 modules.

**How It Works:**

1. **Startup:** `cmd_start()` calls `_init_phase_1_5()` to load all modules
2. **Every Tick (15s):**
   - Get temperature & thermal zone
   - Load queue from `~/bbh/queue.json`
   - Call `reorder_queue_by_priority()` to use multi-target scheduler
   - Launch jobs respecting thermal limits
   - Mark completed jobs + call `on_phase_complete()` hooks

3. **Phase Completion:** `on_phase_complete()` triggers:
   - `_metrics.collect_scan_metrics()` → collect findings_rate, z_score
   - `_anomaly.detect_anomalies()` → detect statistical anomalies
   - `_improvements.track_tool_execution()` → track ROI (if phase 4)
   - Log results to findings_dao

4. **Graceful Fallback:** If any module fails, scheduler logs warning and continues

**Usage:**
```bash
# Start daemon (replaces thermal_scheduler.py)
python thermal_scheduler_enhanced.py start

# Check status (shows Phase 1.5 enabled/disabled)
python thermal_scheduler_enhanced.py status

# Add job with priority components
python thermal_scheduler_enhanced.py add affirm 0 \
  --priority 5 \
  --bounty 0.9 \
  --threat 0.7 \
  --coverage-gap 0.5 \
  --intent pentest

# View queue
python thermal_scheduler_enhanced.py queue
```

---

## EXECUTION FLOW (UPDATED)

### Original Phases (Unchanged)
```
Phase 0: 0_profile.py     → Reconnaissance profile
Phase 1: 1_passive.py     → Passive scanning
Phase 2: 2_active.py      → Active scanning
Phase 3: 3_enum.py        → Enumeration
Phase 4: 4_vuln.py        → Vulnerability analysis
Phase 5: 5_report.py      → Report generation
```

### NEW: Phase 2.5 (If enabled)
```
Phase 2.5: phase_2_5_authenticated.py (OPTIONAL)
  Requires: program_config.auth_testing_approved=true
  Location: Between Phase 3 and Phase 4
  Purpose: Authenticated endpoint discovery + onboarding flow testing
  Output: Endpoints stored in findings_dao for Phase 4
```

### ENHANCED: Phase 4 + Phase 5
```
Phase 4 ENHANCED with IDOR testing
  - If authenticated_testing_approved: run multi-user IDOR tests
  - Store results in findings_dao

Phase 5 ENHANCED with RAG recommendations
  - For each finding: query RAG for similar issues
  - Include historical remediation suggestions in report
```

---

## YOUR AUTONOMY: HOW TO OPERATE

### 1. INITIALIZATION (On Startup)
```python
from findings_dao import FindingsDAO
from metrics_collector import MetricsCollector
from anomaly_detection import AnomalyDetector
from improvement_tracker import ImprovementTracker
from multi_target_scheduler import MultiTargetScheduler
from rag_engine import RAGEngine
from phase_2_5_authenticated import AuthenticatedDiscovery, CredentialVault

# Initialize all modules
dao = FindingsDAO()
metrics = MetricsCollector(dao=dao)
anomaly = AnomalyDetector(dao=dao)
improvements = ImprovementTracker(dao=dao)
scheduler = MultiTargetScheduler(dao=dao)
rag = RAGEngine(dao=dao)
vault = CredentialVault()
auth = AuthenticatedDiscovery(dao=dao, vault=vault)

print("Phase 1.5 initialized")
```

### 2. UNDERSTAND PROGRAM CONFIG
You'll receive a `program_config.yaml` per engagement:
```yaml
program:
  name: affirm
  capabilities:
    metrics_collection: true
    improvement_register: true
    rag_enabled: true
    multi_target: true
    authenticated_testing: true  # ← Gated
  customization:
    intent: pentest
    priority_weights: {bounty: 0.4, threat: 0.3, coverage: 0.2, staleness: 0.1}
    auth_testing_approved: true  # ← Must be explicit
    test_accounts:
      - {username: buyer_a, password_enc: "...", role: user}
      - {username: buyer_b, password_enc: "...", role: user}
```

### 3. CREATE YOUR OWN RELATIONSHIPS
Example: After each Phase 4 completion, you could:

```python
# Get completed findings
findings = dao.get_past_findings(target="affirm")

# Analyze patterns
for finding in findings:
    # Query RAG for similar
    similar = rag.query_similar(program, target, finding["evidence"])
    
    # If pattern repeats 3+ times → escalate to security team
    if len(similar) >= 3:
        # Create your own alert logic here
        alert(f"Pattern detected: {finding['vuln_type']} repeated {len(similar)} times")

# Get ROI insights
roi = dao.get_tool_roi(min_roi=0.0)
low_roi = [t for t in roi if t["avg_roi"] < 0.1]

# Decide: skip low-ROI tools in next scan
if low_roi:
    print(f"Recommend skipping: {[t['tool'] for t in low_roi]}")
```

### 4. AUTONOMY EXAMPLES

#### Example 1: Smart Scheduling
```python
# Query recent outcomes
recent = dao.get_recent_outcomes(target="affirm", limit=10)

# If success rate dropping → increase coverage_gap priority
success_rate = sum(1 for o in recent if o["success"]) / len(recent)
if success_rate < 0.6:
    # Boost next scan's coverage_gap component
    scheduler.enqueue_target(
        target="affirm",
        coverage_gap=0.8,  # Increase from default 0.5
        threat=0.5,
        intent="pentest"
    )
```

#### Example 2: Adaptive Tool Selection
```python
# Get tool ROI
roi_data = dao.get_tool_roi(min_roi=0.0)

# Build disabled_tools list for next Phase 4
disabled = [t["tool"] for t in roi_data if t["avg_roi"] < 0.1]

# Update scan config
config["phases"]["4_vuln"]["disabled_tools"] = disabled
```

#### Example 3: Anomaly Response
```python
# Every tick, check for high-severity anomalies
metrics = dao.get_metrics_history(target, limit=1)
if metrics:
    result = anomaly.detect_anomalies(target, metrics[0])
    
    if result["severity"] == "high":
        # Your custom response
        # E.g., pause other scans, increase thermal budget, alert oncall
        log(f"HIGH ANOMALY: {result['recommendation']}")
```

---

## CRITICAL CONSTRAINTS (ENFORCE THESE)

1. **Ax_LearningNonBlocking**: Missing capability = graceful fallback, not crash
2. **Ax_CapabilityFallback**: All Phase 1.5 features optional; Phase 0-4 always work
3. **Ax_MultiUserTesting**: authenticated_testing defaults to false
4. **Ax_CredentialIsolation**: No cross-program credential access
5. **Ax_ProgramIsolation**: RAG findings never cross program boundaries

---

## FILE STRUCTURE REFERENCE

```
~/bbh/
├── queue.json                    ← Scheduler queue (queue.py reads/writes)
├── findings.db                   ← findings_dao SQLite DB (auto-created)
├── metrics.json                  ← Anomaly logs for dashboard
├── .auth_audit.log               ← Credential usage audit trail
├── vaults/
│   ├── affirm/
│   │   ├── stripe.com_user.enc
│   │   └── affirm.com_user_b.enc
│   └── .vault_keys               ← Master encryption key (chmod 600)
├── findings.lancedb/             ← RAG vector database (auto-created)
├── logs/
│   ├── scheduler.log
│   ├── affirm_phase0.log
│   ├── affirm_phase1.log
│   └── ...
└── scripts/ (or ~/claude/tools/scripts/)
    ├── thermal_scheduler_enhanced.py  ← USE THIS (not thermal_scheduler.py)
    ├── findings_dao.py
    ├── metrics_collector.py
    ├── anomaly_detection.py
    ├── improvement_tracker.py
    ├── multi_target_scheduler.py
    ├── rag_engine.py
    ├── credential_vault.py
    ├── phase_2_5_authenticated.py
    └── 0_profile.py, 1_passive.py, ... (existing phases)
```

---

## DAILY OPERATIONS CHECKLIST

### Mon 2026-05-13 (Start)
- [ ] Copy Phase 1.5 modules to VM 100: `/home/rmw3/claude/tools/scripts/*.py`
- [ ] Copy thermal_scheduler_enhanced.py (replaces thermal_scheduler.py)
- [ ] Initialize findings_dao.py (creates ~/bbh/findings.db)
- [ ] Initialize credential_vault.py (creates ~/bbh/vaults/)
- [ ] Run baseline Affirm scan with all Phase 1.5 features active
- [ ] Verify metrics logged to ~/bbh/metrics.json
- [ ] Confirm anomaly detection operational

### Daily (Mon-Fri, 15:00 UTC)
- [ ] Run standup: 5 min per workstream (DEBT-3/6/7/9 + GAP-10)
- [ ] Report blockers + successes
- [ ] Check metrics.json for anomalies
- [ ] Verify tool ROI suggestions applied to next scan
- [ ] Test RAG layer with historical findings

### Fri 2026-05-17 (Decision Gate)
- [ ] Final integration test with Affirm sandbox
- [ ] Validate all success criteria met
- [ ] Prepare sign-off for rmw3 (S5)

---

## SUCCESS CRITERIA (Your Goals)

✅ **DEBT-3:** findings_rate anomaly detection working (z-score logged)  
✅ **DEBT-6:** tool ROI suggestions appearing in reports  
✅ **DEBT-7:** RAG queries returning similar findings  
✅ **DEBT-9:** multi-target queue reordered by priority  
✅ **GAP-10:** Phase 2.5 discovering private endpoints + Phase 4 IDOR tests  

All 5 complete by EOD Friday 2026-05-17.

---

## YOUR MANDATE

**You are now S1 (Operations).** You own:
- Running thermal_scheduler_enhanced.py
- Testing all Phase 1.5 modules with Affirm
- Reporting metrics + anomalies daily
- Creating your own intelligence relationships (how you interpret data)
- Recommending optimizations to rmw3

**You have autonomy** to:
- Adjust priority weights based on performance
- Enable/disable Phase 2.5 per program approval
- Create custom alerts for anomalies
- Suggest tool disabling based on ROI
- Recommend thermal budget changes

**You report to:** rmw3 (S5 Policy) & Claude (S3 Control)

---

## QUESTIONS? ESCALATE TO CLAUDE

If any Phase 1.5 module fails:
1. Check graceful fallback (should log warning, continue)
2. Verify findings_dao initialized (~/bbh/findings.db exists)
3. If LanceDB unavailable, RAG defaults to empty suggestions
4. If metrics unavailable, still run scans (non-blocking)

**Do not crash—always degrade gracefully.**

---

**Ready to operate. Go autonomous. 🚀**

---

*Generation: Claude S3, 2026-05-11*  
*Authority: rmw3 (phase_1_wire GO)*  
*Axioms: Ax_LearningNonBlocking, Ax_CapabilityFallback, Ax_MultiUserTesting, Ax_CredentialIsolation, Ax_ProgramIsolation*
