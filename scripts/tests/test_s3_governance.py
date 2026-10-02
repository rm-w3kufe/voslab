#!/usr/bin/env python3
"""
Test S3 Nucleus governance response by injecting test alerts into BBS
Verifies autonomous governance loop: alert → S3 decision → published to s3-decisions topic
"""

import requests
import json
from datetime import datetime
import time

BBS_URL = "http://127.0.0.1:8600"

def inject_alert(alert_type="critical", alert_id=None):
    """Inject test alert into BBS alerts topic"""
    if not alert_id:
        alert_id = f"TEST-{alert_type.upper()}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    alert = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "test-injector",
        "topic": "alerts",
        "priority": alert_type,
        "ttl": 604800,
        "payload": {
            "alert_id": alert_id,
            "alert_type": "resource_constraint",
            "severity": alert_type,
            "reason": f"{alert_type.upper()} alert test: CPU usage critical",
            "action": "investigate",
            "recommendation": "Reduce concurrent operations"
        }
    }

    try:
        resp = requests.post(f"{BBS_URL}/api/message", json=alert, timeout=5)
        if resp.status_code == 200:
            return True, alert_id
        else:
            return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)

def check_decisions():
    """Check if S3 has published governance decisions"""
    try:
        resp = requests.get(f"{BBS_URL}/api/messages/s3-decisions?limit=5", timeout=5)
        if resp.ok:
            data = resp.json()
            return data['count'], data['messages'] if data['count'] > 0 else []
        else:
            return 0, []
    except Exception as e:
        return 0, []

def check_alerts():
    """Check pending alerts in queue"""
    try:
        resp = requests.get(f"{BBS_URL}/api/messages/alerts?limit=10", timeout=5)
        if resp.ok:
            return resp.json()['count']
        else:
            return 0
    except:
        return 0

if __name__ == "__main__":
    print("=" * 70)
    print("S3 GOVERNANCE TEST — Autonomous Alert Processing")
    print("=" * 70)

    # Test 1: Inject critical alert
    print("\n[TEST 1] Injecting CRITICAL alert...")
    success, result = inject_alert("critical")
    if success:
        print(f"✓ Alert published: {result}")
    else:
        print(f"✗ Failed: {result}")

    # Test 2: Inject warning alert
    print("\n[TEST 2] Injecting WARNING alert...")
    success, result = inject_alert("warning")
    if success:
        print(f"✓ Alert published: {result}")
    else:
        print(f"✗ Failed: {result}")

    # Check queue status
    print("\n[STATUS] Checking BBS queue...")
    pending = check_alerts()
    print(f"Alerts pending: {pending}")

    # Wait for S3 to process
    print("\n[WAITING] S3 runs every 60 seconds — monitoring governance response...")
    print("(Checking every 10 seconds, timeout 120 seconds)")

    timeout = time.time() + 120
    last_count = 0
    while time.time() < timeout:
        count, messages = check_decisions()
        if count > last_count:
            print(f"\n✓ S3 PUBLISHED GOVERNANCE DECISION!")
            for msg in messages[:1]:
                p = msg['payload']
                print(f"  Decision ID: {p.get('decision_id')}")
                print(f"  Type: {p.get('decision_type')}")
                print(f"  Action: {p.get('action')}")
                print(f"  Rationale: {p.get('rationale')}")
                print(f"  Approved by: {p.get('approved_by')}")
            break

        time.sleep(10)
    else:
        print(f"\n✗ Timeout: S3 did not publish decisions after 120 seconds")
        print(f"Current s3-decisions count: {count}")
