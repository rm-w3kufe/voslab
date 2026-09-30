#!/usr/bin/env python3
"""PROD-A1a acceptance test — drives run_agent over a real state.db COPY through the injection
scenario. Proves: bootstrap is silent, a real out-of-band edit ALARMS, a volatile-column bump is
SILENT (canonical excludes it). Run on the n02 sandbox (108), never WSL — this is the reproducible
acceptance test for PROD-A1a (push to 108 + a /root/snap.db backup of state.db, then run). 9/9 = ship."""
import os
import sys
import shutil
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_attest as A

DB = "/root/snap.db"
WORK = "/root/_inj"
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
db = os.path.join(WORK, "snap.db")
shutil.copy(DB, db)
AT, AK, SEEN = WORK + "/at", WORK + "/ak", WORK + "/seen.json"

PASS, FAIL = [], []


def mut(sql):
    c = sqlite3.connect(db)
    c.execute(sql)
    c.commit()
    c.close()


def run():
    _, summary = A.run_agent(db, AT, AK, SEEN, emit=False)
    return {t: cats for t, n, cats in summary}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name)


print("### 1. bootstrap — both surfaces silent (nothing to verify yet)")
r = run()
check("bootstrap: deploys silent", r["deploys"] == [])
check("bootstrap: coupling_registry silent", r["coupling_registry"] == [])

print("### 2. clean re-run — live == last attestation, silent")
r = run()
check("clean: deploys silent", r["deploys"] == [])
check("clean: coupling_registry silent", r["coupling_registry"] == [])

print("### 3. TAMPER deploys (edit newest row.result) — deploys ALARMS, coupling silent")
mut("UPDATE deploys SET result='TAMPERED' WHERE id=(SELECT MAX(id) FROM deploys)")
r = run()
check("tamper: deploys reports ATTEST_TAMPER", "ATTEST_TAMPER" in r["deploys"])
check("tamper: coupling_registry stays silent", r["coupling_registry"] == [])

print("### 4. VOLATILE bump coupling_registry.refreshed_at (excluded) — coupling SILENT")
mut("UPDATE coupling_registry SET refreshed_at='2099-01-01T00:00:00Z'")
r = run()
check("volatile: coupling_registry silent (canonical excludes refreshed_at)", r["coupling_registry"] == [])

print("### 5. REAL change coupling_registry.status (non-volatile) — coupling ALARMS")
mut("UPDATE coupling_registry SET status='REVOKED'")  # all rows; no rowid assumption (may be WITHOUT ROWID)
r = run()
check("real-change: coupling_registry reports ATTEST_TAMPER", "ATTEST_TAMPER" in r["coupling_registry"])

print("### 6. ROLLBACK deploys chain (truncate to genesis) — deploys ALARMS rollback")
sfile = A._surface_file(AT, "statedb.deploys")
open(sfile, "w").close()  # empty the chain file → shorter than seen head
r = run()
check("rollback: deploys reports ATTEST_MISSING or ATTEST_ROLLBACK",
      ("ATTEST_ROLLBACK" in r["deploys"] or "ATTEST_MISSING" in r["deploys"]))

print(f"\n## RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("## ✗ AGENT NOT ACCEPTED: " + ", ".join(FAIL))
    sys.exit(1)
print("## ✓ AGENT ACCEPTED — alarms on real tamper/rollback, silent on volatile/legit. Ready to deploy.")
shutil.rmtree(WORK, ignore_errors=True)
