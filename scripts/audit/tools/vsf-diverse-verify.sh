#!/usr/bin/env bash
# vsf-diverse-verify.sh — wrapper for daily diverse chain verification (DIVERSE-VERIFIER)
#
# Runs verify_chain_diverse.py on the last 1000 events from LXC 101.
# If findings exist: emits algedonic via dual-channel (g6 inbox + NATS).
# Always exits 0 — the timer unit never shows as failed; findings travel via algedonic.
#
# Deploy: /usr/local/bin/vsf-diverse-verify.sh
# Schedule: vsf-diverse-verify.timer (daily 04:30 UTC)
#
# @vsm 0.3 — V(diverse-verifier-wrapper, L=1) = { role: "scheduler+emitter for diverse chain verify" }
#
# INDEPENDENCE RULE: this file only SCHEDULES and EMITS — never modifies verification logic.

set -euo pipefail

# ── config ──────────────────────────────────────────────────────────────────────
VERIFIER="/usr/local/bin/verify_chain_diverse.py"
REPORT_FILE="/tmp/diverse_report.json"
NUCLEUS_LXC=101
INBOX_LXC=104
NATS_LXC=106
INBOX_PATH="/alerts/operator_inbox.log"
TAIL_LINES=1000
EVENTS_PATH="/var/lib/vsf/vsf_nucleus/events.jsonl"
WRITERS="vsf_nucleus"
MAX_FINDINGS=10
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ── run verification ────────────────────────────────────────────────────────────
# Tail the last N events from the nucleus LXC, pipe through verifier
pct exec "${NUCLEUS_LXC}" -- tail -"${TAIL_LINES}" "${EVENTS_PATH}" \
  | python3 "${VERIFIER}" --stdin --writers "${WRITERS}" --max-findings "${MAX_FINDINGS}" \
  > "${REPORT_FILE}" 2>/dev/null || true

# Read the report
if [[ ! -f "${REPORT_FILE}" ]]; then
  echo "${TIMESTAMP} [diverse-verify] REPORT_FILE missing — skipping algedonic" >&2
  exit 0
fi

# ── analyze findings ────────────────────────────────────────────────────────────
# Parse the JSON report to extract findings
# We use a small Python inline because shell is painful for JSON
python3 -c "
import json, subprocess, sys

with open('${REPORT_FILE}') as f:
    report = json.load(f)

if report.get('clean', True):
    sys.exit(0)  # clean — no algedonic

findings = report.get('findings', [])
counts = report.get('counts', {})

# Group by kind
kinds = {}
for f_item in findings:
    k = f_item.get('kind', 'unknown')
    kinds.setdefault(k, []).append(f_item)

TIMESTAMP = '${TIMESTAMP}'
INBOX_LXC = '${INBOX_LXC}'
INBOX_PATH = '${INBOX_PATH}'
NATS_LXC = '${NATS_LXC}'

def emit_algedonic(category, severity, instance, detail):
    \"\"\"Dual-channel algedonic emission (mirrors vsf-topology-reconcile.py).\"\"\"
    line = f'{TIMESTAMP}  DIVERSE-VERIFY {category}  {instance} — {detail}'
    safe = line.replace(\"'\", '')
    # 1) reliable: g6 inbox on LXC 104
    subprocess.run(['bash', '-c',
        f\"pct exec {INBOX_LXC} -- bash -c 'mkdir -p /alerts && echo \\\"{safe}\\\" >> {INBOX_PATH}'\"
    ], capture_output=True, timeout=20)
    # 2) best-effort: NATS PUB from LXC 106
    import json as _j
    payload = _j.dumps({
        'severity': severity, 'source_id': 'diverse_verifier',
        'category': category, 'instance': instance, 'detail': detail, 'ts': TIMESTAMP
    })
    py_code = f'import socket,sys; p={payload!r}.encode(); s=socket.socket(); s.settimeout(3); s.connect((\"127.0.0.1\",4222)); s.recv(4096); s.send(b\"PUB vsf.alpha.algedonic.{category} \"+str(len(p)).encode()+b\"\\r\\n\"+p+b\"\\r\\n\"); s.close()'
    subprocess.run(['bash', '-c',
        f\"pct exec {NATS_LXC} -- python3 -c '{py_code}'\"
    ], capture_output=True, timeout=20)

# Emit per finding kind:
#   content_tamper|link_break -> diverse_verifier_disagreement sev 9.0
#   foreign_writer            -> foreign_writer                sev 8.0
#   restart_seam              -> restart_seam                  sev 4.0

severity_map = {
    'content_tamper':  (9.0, 'diverse_verifier_disagreement'),
    'link_break':      (9.0, 'diverse_verifier_disagreement'),
    'foreign_writer':  (8.0, 'foreign_writer'),
    'restart_seam':    (4.0, 'restart_seam'),
    'malformed_line':  (5.0, 'malformed_line'),
}

for kind, items in kinds.items():
    sev, cat = severity_map.get(kind, (5.0, kind))
    detail = items[0].get('detail', '')[:200]
    instance = items[0].get('system_id') or items[0].get('ts', '?')
    emit_algedonic(cat, sev, instance, detail)

# Summary: log total findings
total = len(findings)
print(f'{TIMESTAMP} [diverse-verify] {total} finding(s) — algedonic emitted', flush=True)
" 2>&1 || true

# Always exit 0 — findings travel via algedonic, not systemd failure
exit 0
