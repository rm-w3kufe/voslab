#!/usr/bin/env python3
"""topology_reconcile — viability certification: declared model (state.db) ≡ actual reality (processes).

The orphan-tower failure (FIND-NUC-ORPHANS, 2026-06-03) was a MODEL↔REALITY divergence: 3 nucleus
processes ran while state.db declared 1, undetected for 9 days. Liveness checks ("is the declared
service active?") are UNIDIRECTIONAL and blind to undeclared processes. This certifier closes that gap
with a BIDIRECTIONAL census + flap detection — Beer's S3* (sporadic direct audit) made concrete.

Runs ON the n02 HOST (needs host-wide ps + cgroup→container + pct + state.db + systemctl). Read-only.
Pure stdlib. Exit 0 = reconciled, 1 = anomalies.

Anomaly classes (the two that the 9-day incident proved we were blind to are HARD):
  ORPHAN   — a running VSF binary (exe basename vsf-*) with no declared service of that name in its
             container. HARD. (caught: the LXC-107 legacy nucleus.)
  FLAP     — a vsf systemd unit whose NRestarts DELTA (change within 5-min window) exceeds
             FLAP_THRESHOLD. HARD. (2026-07-13 fix: windowed rate replaces lifetime counter —
             avoids false-positive on stable units with high lifetime counts.)
  MISSING  — a declared active service with no matching process anywhere in its container. WARN.
  SHA_DRIFT— matched by name but exe sha ≠ declared sha. INFO (often just state.db refresh lag).

Identity is matched by NAME (normalized), not sha — sha-equality false-fires on third-party services
(ollama model blob ≠ exe) and on state.db refresh lag. sha is used only for the soft SHA_DRIFT note.
"""
import subprocess, re, sqlite3, sys, os, json, glob

STATE_DB = "/var/lib/vsf-state/state.db"
STATE_DIR = "/var/lib/vsf-state"
FLAP_STATE_FILE = os.path.join(STATE_DIR, "flap_state.json")
FLAP_THRESHOLD = 5     # max allowed NRestarts delta per 5-min reconciliation window
OUR_BIN_RE = re.compile(r"^vsf[-_]")     # OUR components (exe basename). ssh/python/ollama excluded.
# RECON-BIDIRECTIONAL: reverse sweep catches long-lived non-vsf processes not in state.db.
# OS_NOISE: processes exempt from the reverse sweep (kernel, infrastructure).
BRACKET_RE = re.compile(r"^\[.*\]")     # kernel thread marker in ps output
OS_NOISE = {"kernel", "systemd", "systemd-journald", "sshd", "sshd:", "getty", "agetty",
            "login", "cron", "dbus", "dbus-daemon", "polkitd", "haveged", "rpcbind",
            "rpc.statd", "nscd", "atd", "acpid", "irqbalance", "rsyslogd", "udevd",
            "kworker", "kthreadd", "migration", "rcu", "rcuog", "rcuos", "watchdog",
            # netdata REMOVED from OS_NOISE 2026-08-09. It was declared
            # decommissioned on 2026-05-31 (vsf-net-housekeeping.sh:55, "flag if
            # it resurfaces") and ran until 2026-08-09 anyway — ten weeks past
            # its own decommission, holding a firewall permit from the
            # adversarial VLAN into management. Nothing flagged it: the script
            # carrying the detector was never deployed and has no timer, and
            # THIS list told the reverse sweep to read it as OS infrastructure.
            # A process exempted as noise cannot be reported as an orphan.
            "mysqld", "mariadbd", "postgres", "redis-server", "nginx",
            "apache2", "containerd", "dockerd", "pveprox", "pvedaemon", "pvestatd",
            "pveproxy", "pvefw-logger", "pvefw", "qmeventd", "init", "systemd-networkd",
            "systemd-logind", "systemd-udevd", "systemd-resolved", "systemd-timesyncd",
            "systemd-journal", "lxcfs", "lxc-monitord", "chronyd", "smartd", "zed",
            "dmeventd", "blkmapd", "fail2ban-server", "avahi-daemon:", "pmxcfs",
            "lxc-start", "lxc-attach", "lxc-stop", "lxc-destroy",
            "master", "pickup", "qmgr", "cleanup", "sendmail", "postfix",
            "privoxy", "tor", "gpg-agent", "gpg", "ssh-agent",
            "sleep", "tail", "head", "nano", "vim", "top", "htop",
            "less", "more", "cat", "screen", "tmux", "sudo",
            "autossh", "mitmdump", "interactsh-client", "opencode"}
# DSN-COUPLE-01 Phase 2 — coupling manifests give per-S1 AUTHORITATIVE audit identity (expected sha,
# flap threshold), upgrading SHA_DRIFT from INFO (state.db lag) to HARD (forged/swapped instance).
MANIFEST_DIR = os.environ.get("VSF_COUPLING_DIR", "/etc/vsf/coupling")

# Algedonic emission (reuses populate.sh's proven dual-channel: reliable inbox append on LXC 104 +
# best-effort NATS PUB). The inbox is the g6 sink's monitored path; NATS is secondary.
EMIT = "--emit" in sys.argv
SELFTEST = "--selftest" in sys.argv
INBOX_LXC = "104"
INBOX_PATH = "/alerts/operator_inbox.log"
NATS_LXC = "106"
SEVERITY = {"ORPHAN": 7.0, "FLAP": 6.0, "MISSING": 5.0}  # ≥ g6 sink ALG_SEVERITY_MIN (1.0)

def now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def emit_algedonic(category, severity, instance, detail):
    """Dual-channel (mirrors populate.sh emit_algedonic). source_id/category drive the g6 sink dedup."""
    ts = now_iso()
    line = f"{ts}  S3-RECONCILE {category}  {instance} — {detail}"
    # 1) reliable: append to the operator inbox the g6 sink polls (LXC 104).
    safe = line.replace("'", "")
    subprocess.run(["bash", "-c",
        f"pct exec {INBOX_LXC} -- bash -c \"mkdir -p /alerts && echo '{safe}' >> {INBOX_PATH}\""],
        capture_output=True, timeout=20)
    # 2) best-effort: NATS PUB on vsf.alpha.algedonic.<category> from where NATS is localhost (LXC 106).
    import json as _j
    payload = _j.dumps({"severity": severity, "source_id": "s3_topology_audit",
                        "category": category, "instance": instance, "detail": detail, "ts": ts})
    py = ("import socket,sys\n"
          f"p={payload!r}.encode()\n"
          "s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',4222)); s.recv(4096)\n"
          "s.send(b'CONNECT {}\\r\\n'); "
          f"s.send(b'PUB vsf.alpha.algedonic.{category} '+str(len(p)).encode()+b'\\r\\n'+p+b'\\r\\n')\n"
          "s.close()")
    subprocess.run(["bash", "-c", f"pct exec {NATS_LXC} -- python3 -c {py!r}"],
                   capture_output=True, timeout=20)
    return line

def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""

def norm(s):
    return re.sub(r"[-_]", "", (s or "").lower())

def container_of(cgroup):
    m = re.search(r"/lxc/(\d+)", cgroup or "")
    return m.group(1) if m else "host"

def all_processes():
    """Every process: pid, container, exe-basename, sha (via /proc/PID/exe, cross-namespace), args."""
    out = sh("ps -eo pid,cgroup,args --no-headers")
    procs = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, cgroup, args = parts
        exe = sh(f"readlink /proc/{pid}/exe").strip()
        procs.append(dict(pid=pid, container=container_of(cgroup), exe=exe,
                          binary=os.path.basename(exe) if exe else "", args=args.strip()))
    return procs

def sha_of(pid):
    out = sh(f"sha256sum /proc/{pid}/exe 2>/dev/null").split()
    return out[0] if out else "?"

def declared_services():
    rows = []
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        for lxc, name, sha, active in con.execute("SELECT lxc,name,binary_sha,active FROM services"):
            rows.append(dict(lxc=str(lxc), name=name or "", sha=(sha or ""),
                             active=str(active) in ("1", "True", "active")))
        con.close()
    except Exception as e:
        print(f"WARN: cannot read state.db services: {e}", file=sys.stderr)
    return rows

def systemd_units():
    units = sh("systemctl list-units 'vsf*' --all --no-legend --plain 2>/dev/null").splitlines()
    names = {ln.split()[0] for ln in units if ln.strip()}
    out = []
    for u in sorted(names):
        info = sh(f"systemctl show {u} -p NRestarts,ActiveState,SubState,Result 2>/dev/null")
        kv = dict(l.split("=", 1) for l in info.splitlines() if "=" in l)
        out.append(dict(unit=u, nrestarts=int(kv.get("NRestarts", "0") or 0),
                        active=kv.get("ActiveState"), sub=kv.get("SubState"), result=kv.get("Result")))
    return out

def short(s):
    return s[:8] if s and s != "?" else s

def load_manifests():
    """DSN-COUPLE-01 — index deployed coupling manifests by normalized system_id.
    Each gives AUTHORITATIVE audit identity (expected binary_sha) + per-S1 flap threshold."""
    idx = {}
    for path in sorted(glob.glob(os.path.join(MANIFEST_DIR, "*.coupling.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        ident = m.get("identity") or {}
        sid = ident.get("system_id")
        if not sid:
            continue
        am = m.get("audit_map") or {}
        ip = am.get("identity_proof") or {}
        health = am.get("health") or {}
        idx[norm(sid)] = {"system_id": sid, "sha": ip.get("binary_sha", ""),
                          "flap_max": health.get("flap_nrestarts_max"),
                          "vantage": ident.get("vantage", "")}
    return idx


# ── RECON-BIDIRECTIONAL: reverse sweep ─────────────────────────────────────────

RECON_ALLOWLIST_SQL = """CREATE TABLE IF NOT EXISTS recon_allowlist (
    lxc INTEGER, pattern TEXT, reason TEXT, added_by TEXT, added_ts TEXT,
    PRIMARY KEY (lxc, pattern));"""

def ensure_allowlist_table():
    """Idempotent ALTER — create recon_allowlist if missing."""
    try:
        con = sqlite3.connect(STATE_DB, timeout=10)
        con.execute(RECON_ALLOWLIST_SQL)
        con.commit()
        con.close()
    except Exception as e:
        print(f"WARN: cannot create recon_allowlist table: {e}", file=sys.stderr)

def load_allowlist() -> dict:
    """Returns {(lxc, pattern): reason} for quick lookup."""
    out = {}
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        for row in con.execute("SELECT lxc, pattern, reason FROM recon_allowlist"):
            out[(int(row[0]), row[1])] = row[2]
        con.close()
    except Exception:
        pass
    return out

def lxc_list() -> list[dict]:
    """All LXCs from state.db, returning {vmid, role}."""
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        rows = [{"vmid": r[0], "role": r[1]}
                for r in con.execute("SELECT id, role FROM lxcs ORDER BY id")]
        con.close()
        return rows
    except Exception as e:
        print(f"WARN: cannot read lxcs table: {e}", file=sys.stderr)
        return []

def _cmdline_basename(args: str) -> str:
    """Extract the 'command' part from a cmdline, handling python/perl interpreters."""
    parts = args.strip().split()
    if not parts:
        return ""
    # python3 /path/to/script.py → script.py
    if "/python" in parts[0] and len(parts) > 1:
        return os.path.basename(parts[1])
    # perl /path/to/script.pl → script.pl
    if "perl" in parts[0] and len(parts) > 1:
        return os.path.basename(parts[1])
    # /usr/bin/bash /path/to/script.sh → script.sh
    if parts[0].endswith(("bash", "sh", "zsh")) and len(parts) > 1:
        return os.path.basename(parts[1])
    # direct binary
    return os.path.basename(parts[0])

def _proc_age_seconds(pid: str) -> int:
    """Parse /proc/PID/stat start time vs now → age in seconds."""
    out = sh(f"ps -o etimes= -p {pid} 2>/dev/null").strip()
    try:
        return int(out)
    except (ValueError, TypeError):
        return 0

def sweep_undeclared(dry_run: bool = False) -> list[tuple]:
    """Reverse census: for each LXC, find long-lived processes not in state.db or allowlist.
    
    Scans INSIDE each container via pct exec (not host-level ps which mixes namespaces).
    Returns list of (severity, category, instance, detail) findings.
    """
    findings = []
    allowlist = load_allowlist()
    lxcs = lxc_list()
    
    for lxc in lxcs:
        vmid = lxc["vmid"]
        if vmid == 0:
            continue  # host scan deferred — LXCs only in phase 1
        
        # Get declared service + component names for this LXC
        declared = set()
        try:
            con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
            for r in con.execute("SELECT name FROM services WHERE lxc=?", (vmid,)):
                declared.add(r[0].lower())
            for r in con.execute("SELECT name FROM components WHERE deploy_target_lxc=?", (vmid,)):
                declared.add(r[0].lower())
            con.close()
        except Exception:
            pass
        
        # Get running systemd units inside LXC
        unit_output = sh(f"pct exec {vmid} -- systemctl list-units '*.service' --state=running --no-legend --plain 2>/dev/null")
        running_units = set()
        for ln in unit_output.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            nm = ln.split()[0]
            if nm.endswith(".service"):
                nm = nm[:-8]
            running_units.add(nm.lower())
        
        # Get long-lived processes (>1h) inside the container
        proc_output = sh(f"pct exec {vmid} -- ps -eo pid,etime,args --no-headers --sort=-etime 2>/dev/null")
        
        candidates = {}
        for ln in proc_output.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split(None, 2)
            if len(parts) < 3:
                continue
            pid, etime, args = parts
            
            age = _proc_age_seconds(pid)
            if age < 3600:
                continue
            
            cmd = _cmdline_basename(args)
            if not cmd:
                continue
            cmd_lower = cmd.lower()
            
            # Skip kernel threads (bracketed [kworker/...])  # note: inside LXCs via pct exec this is redundant but harmless
            if BRACKET_RE.match(cmd_lower):
                continue
            # Skip jbd2, cpuhp, irq etc (bracketed but _cmdline_basename may drop brackets)
            if cmd_lower.startswith(("kworker", "kthreadd", "migration", "rcu", "watchdog", "jbd2", "cpuhp", "irq", "kdmflush")):
                continue
            
            # Filter OS noise
            if cmd_lower in OS_NOISE:
                continue
            if OUR_BIN_RE.search(cmd_lower):
                continue
            # Skip known VSF python services (systemd-managed)
            if ("vsf_" in cmd_lower or "s4_" in cmd_lower or "s1_" in cmd_lower):
                if vmid != 0:
                    # Check if it's a declared component
                    if cmd_lower.rstrip(".py") in declared:
                        continue
                    # Check if running unit matches
                    if cmd_lower in running_units:
                        continue
                else:
                    continue  # host shouldn't have VSF processes
            
            # Skip interactive/login shells and common tools (including `bash -c` wrapper → basename is "-c")
            if cmd_lower in ("bash", "sh", "zsh", "dash", "ssh", "tmux", "screen", "-c",
                             "nano", "vim", "top", "htop", "less", "more", "cat",
                             "ls", "ps", "grep", "find"):
                continue
            # Skip session leaders
            if cmd_lower in ("-bash", "-sh", "-zsh", "-dash", "login"):
                continue
            
            candidates[cmd] = {"pid": pid, "args": args, "age_s": age, "etime": etime, "vmid": vmid}
        
        # Cross-check candidates against declared + allowlist
        for cmd, info in sorted(candidates.items()):
            cmd_base = cmd.lower()
            cmd_norm = re.sub(r"\.(py|pl|sh|rb)$", "", cmd_base)
            
            # Check if known as running unit or declared component
            if cmd_norm in running_units or cmd_base in running_units:
                continue
            if cmd_norm in declared or cmd_base in declared:
                continue
            
            # Check allowlist (substring match on cmd)
            allowlisted = False
            for (pat_lxc, pat) in allowlist:
                if pat_lxc == vmid and (pat in cmd_base or cmd_base.startswith(pat)):
                    allowlisted = True
                    break
            
            if allowlisted:
                continue
            
            # Determine severity: 8.0 if touches canon surfaces
            sev = 6.0
            canon_hint = "no_canon_surface"
            canon_fd = ""
            canon_cwd = ""
            if vmid != 0:
                canon_fd = sh(f"pct exec {vmid} -- ls -la /proc/{info['pid']}/fd/ 2>/dev/null | grep -E '/var/lib/vsf|/run/vsf'")
                canon_cwd = sh(f"pct exec {vmid} -- readlink /proc/{info['pid']}/cwd 2>/dev/null")
            else:
                canon_fd = sh(f"ls -la /proc/{info['pid']}/fd/ 2>/dev/null | grep -E '/var/lib/vsf|/run/vsf'")
                canon_cwd = sh(f"readlink /proc/{info['pid']}/cwd 2>/dev/null")
            
            if canon_fd.strip():
                canon_hint = "canon_contact"
                sev = 8.0
            elif canon_cwd.strip() and "vsf" in canon_cwd.lower():
                canon_hint = "canon_cwd"
                sev = 8.0
            
            instance = f"lxc={vmid}:{cmd}"
            detail = (f"long-lived undeclared process: {info['args'][:120]} "
                      f"since {info['etime']} age={info['age_s']}s pid={info['pid']} "
                      f"{canon_hint}")
            
            findings.append((sev, "undeclared_service", instance, detail))
    
    return findings

# ── FLAP state (windowed rate, not lifetime counter) ──────────────────────────
# The bug (2026-07-13): FLAP probed u["nrestarts"] > FLAP_THRESHOLD, but
# NRestarts from systemctl show is a LIFETIME COUNTER (cumulative since install).
# A service stable for months (NRestarts=5321) always false-positives.
# Fix: store previous readings, compare delta within the 5min reconciliation window.
# Reference: broker_probe.rs emit_count_divergence (same counter-vs-rate pattern).
# > Never compare absolute lifetime counters. Always store the prior observation
# > and compare the delta.

FLAP_STATE_DEFAULT = {
    "prev_restarts": {},   # unit_name → previous NRestarts value
    "version": 2,          # schema version, bump on incompatible changes
    "updated_ts": "never",
}

def load_flap_state() -> dict:
    """Load previous NRestarts snapshot. Returns default if missing or corrupt."""
    try:
        with open(FLAP_STATE_FILE) as f:
            state = json.load(f)
            if isinstance(state, dict) and "prev_restarts" in state:
                return state
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        pass
    return dict(FLAP_STATE_DEFAULT)

def save_flap_state(state: dict) -> None:
    """Write current NRestarts snapshot for next reconciliation window."""
    state["updated_ts"] = now_iso()
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(FLAP_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print(f"WARN: cannot save flap state: {e}", file=sys.stderr)


def main():
    # ── RECON-BIDIRECTIONAL: ensure allowlist table exists ──
    ensure_allowlist_table()
    SWEEP_DRY = "--sweep-dry" in sys.argv
    SWEEP = "--sweep" in sys.argv

    if SELFTEST:
        line = emit_algedonic("ORPHAN", SEVERITY["ORPHAN"], "selftest",
                              "topology_reconcile --selftest: algedonic channel probe (ignore)")
        print(f"# selftest emitted → {line}")
        return 0

    procs = all_processes()
    decl = [d for d in declared_services() if d["active"]]
    units = systemd_units()

    our = [p for p in procs if OUR_BIN_RE.search(p["binary"])]
    for p in our:
        p["sha"] = sha_of(p["pid"])

    decl_norms_by_lxc = {}
    for d in decl:
        decl_norms_by_lxc.setdefault(d["lxc"], []).append(d)

    manifests = load_manifests()          # DSN-COUPLE-01 Phase 2 — authoritative audit identity per S1
    hard, warn, info = [], [], []
    undeclared = []                       # declared/running S1s without a coupling manifest (onboarding pending)

    # ── ORPHAN (HARD): our-binary process accounted by NEITHER state.db NOR a coupling manifest ──
    for p in our:
        nb = norm(p["binary"])
        cands = decl_norms_by_lxc.get(p["container"], [])
        matched = next((d for d in cands if norm(d["name"]) == nb
                        or nb.startswith(norm(d["name"])) or norm(d["name"]).startswith(nb)), None)
        man = manifests.get(nb)
        if not matched and not man:
            hard.append(("ORPHAN", f"pid={p['pid']} lxc={p['container']} {p['binary']} "
                         f"sha={short(p['sha'])} — no declared service NOR coupling manifest"))
            continue
        # SHA_DRIFT: a MANIFEST sha is AUTHORITATIVE (declared expected identity) → mismatch = forged/
        # swapped instance ⇒ HARD. A state.db-only mismatch is usually refresh lag ⇒ INFO.
        if man and man["sha"] and p["sha"] != "?" and not p["sha"].startswith(man["sha"][:12]):
            hard.append(("SHA_DRIFT", f"{p['binary']} lxc={p['container']} running {short(p['sha'])} "
                         f"≠ manifest {short(man['sha'])} — forged/swapped instance?"))
        elif matched and matched["sha"] and p["sha"] != "?" and not p["sha"].startswith(matched["sha"][:12]):
            info.append(("SHA_DRIFT", f"{p['binary']} lxc={p['container']} running {short(p['sha'])} "
                         f"≠ state.db {short(matched['sha'])} (often refresh lag)"))
        if matched and not man:
            undeclared.append(f"{p['binary']}@lxc{p['container']}")

    # ── MISSING (WARN): declared active service whose systemd unit is not active in its container ──
    # Authoritative liveness via systemd (avoids name↔scriptfile guesswork). host lxc → no pct.
    for d in decl:
        if d["lxc"] in ("host", "0", ""):
            st = sh(f"systemctl is-active {d['name']} 2>/dev/null").strip()
        else:
            st = sh(f"pct exec {d['lxc']} -- systemctl is-active {d['name']} 2>/dev/null").strip()
        if st and st != "active":
            warn.append(("MISSING", f"{d['name']} lxc={d['lxc']} declared active but systemd is-active={st or 'unknown'}"))

    # ── FLAP (HARD): hung / crash-looping units; windowed rate (not lifetime counter) ──
    flap_state = load_flap_state()
    prev = flap_state.get("prev_restarts", {})
    current_nrestarts = {}
    for u in units:
        unit_name = u["unit"]
        cur = u["nrestarts"]
        current_nrestarts[unit_name] = cur
        prev_val = prev.get(unit_name, None)
        if prev_val is None:
            continue  # first observation — no delta yet
        delta = cur - prev_val
        if delta < 0:
            # Counter reset (service reinstall or counter wraparound) — treat as fresh
            continue
        ub = norm(re.sub(r"\.service$", "", unit_name))
        man = next((mm for k, mm in manifests.items() if ub == k or ub.startswith(k) or k.startswith(ub)), None)
        thresh = man["flap_max"] if (man and man.get("flap_max") is not None) else FLAP_THRESHOLD
        if delta > thresh:
            hard.append(("FLAP", f"{unit_name} delta_restarts={delta} (>thr {thresh}) "
                         f"lifetime={cur} ({u['active']}/{u['sub']} result={u['result']}) — hung/crash-loop"))
    flap_state["prev_restarts"] = current_nrestarts
    save_flap_state(flap_state)

    if undeclared:
        warn.append(("UNDECLARED_COUPLING", f"{len(undeclared)} declared S1(s) without a coupling manifest "
                     f"(onboarding pending): {', '.join(undeclared)}"))

    # ── RECON-BIDIRECTIONAL: reverse sweep (undeclared long-lived processes) ──
    # Always runs alongside the forward census. Controlled by --emit (default) or
    # standalone with --sweep/--sweep-dry for testing.
    if SWEEP_DRY or SWEEP:
        # Standalone mode — skip forward census; emit controlled by --sweep flag
        findings = sweep_undeclared(dry_run=not SWEEP)
        print(f"## RECON-BIDIRECTIONAL: {len(findings)} undeclared process(es)")
        for sev, cat, inst, detail in findings:
            print(f"  sev={sev:.1f} [{cat}] {inst}")
            print(f"    {detail}")
            if SWEEP:
                emit_algedonic("UNDECLARED_SERVICE", sev, inst, detail)
        if SWEEP:
            print(f"  → {len(findings)} algedonic(s) emitted for undeclared processes.")
        if findings:
            return 1
        return 0
    else:
        # Integrated mode — sweep runs alongside forward census; emission via sweep's internal emit_algedonic
        # when EMIT=True (no double-emission: sweep_undeclared handles its own emit, forward census handles its own)
        sweep_findings = sweep_undeclared(dry_run=not EMIT)

    # ── report ──
    print("# topology_reconcile — declared(state.db) ≡ actual(processes)")
    print(f"declared active: {len(decl)} | OUR vsf binaries running: {len(our)} | vsf units: {len(units)} | "
          f"manifests: {len(manifests)} | sweep_undeclared: {len(sweep_findings)}")
    for sev, cat, inst, detail in sweep_findings:
        tag = "HARD" if sev >= 7.0 else "WARN"
        print(f"  [{tag}/{cat}] {inst} — {detail}")
    print()
    print("## VSF binary census (exe basename vsf-*)")
    for p in our:
        print(f"  lxc={p['container']:>4} pid={p['pid']:>8} {p['binary']:<26} sha={short(p['sha'])}")
    print()
    for tag, items in (("INFO", info), ("WARN", warn)):
        for cls, msg in items:
            print(f"  [{tag}/{cls}] {msg}")
    if not hard:
        print("\n## RESULT: ✓ RECONCILED — no orphan VSF binaries, no crash-loops, no undeclared processes.")
        return 0
    print(f"\n## RESULT: ✗ {len(hard)} HARD ANOMALIES (model ↔ reality divergence)")
    for cls, msg in hard:
        print(f"  [{cls}] {msg}")
        if EMIT:
            emit_algedonic(cls, SEVERITY.get(cls, 5.0), msg.split(" — ")[0], msg)
    if EMIT:
        print(f"  → {len(hard)} algedonic(s) emitted to the operator inbox (S3* topology audit).")
    return 1

if __name__ == "__main__":
    sys.exit(main())
