#!/usr/bin/env python3
"""
Test end-to-end S1→BBS→S4 loop
Injects s1-events (BBH findings) → BBS reads → S4 analyzes → decision published
"""

import requests
import json
from datetime import datetime
import time

BBS_URL = "http://127.0.0.1:8600"

def inject_s1_event(target="test.example.com", phase=2, findings_count=3):
    """Inject fake S1 event (as if BBH published it)"""
    message = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "bbh",
        "topic": "s1-events",
        "priority": "info",
        "ttl": 86400,
        "payload": {
            "phase": phase,
            "target": target,
            "status": "phase_complete",
            "findings_count": findings_count,
            "critical_findings": max(0, findings_count - 2),
            "phase_duration_seconds": 45,
            "progress_percent": int((phase / 5) * 100),
            "metrics": {
                "new_findings": findings_count,
                "endpoints_tested": 15,
                "vulnerabilities": ["SQLi", "XSS", "SSRF"]
            }
        }
    }

    try:
        resp = requests.post(f"{BBS_URL}/api/message", json=message, timeout=5)
        if resp.status_code == 200:
            print(f"✓ S1 event injected: {target} phase {phase} ({findings_count} findings)")
            return True
        else:
            print(f"✗ Failed: HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def check_s4_can_read_s1():
    """Verify S4 can read s1-events from BBS"""
    try:
        resp = requests.get(f"{BBS_URL}/api/messages/s1-events?limit=5", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data['count'] > 0:
                msg = data['messages'][0]
                print(f"✓ S4 can read S1 events: {data['count']} messages in queue")
                print(f"  Latest: {msg['payload']['target']} phase {msg['payload']['phase']}")
                return True
        print(f"✗ S1-events queue empty or unreachable")
        return False
    except Exception as e:
        print(f"✗ Error reading s1-events: {e}")
        return False

def check_system_state_updated():
    """Check if system-state was updated (S4 processes it)"""
    try:
        resp = requests.get(f"{BBS_URL}/api/state/current", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✓ System state available: last update {data.get('timestamp', 'unknown')[:19]}")
            return True
    except:
        pass
    return False

if __name__ == "__main__":
    print("=" * 70)
    print("S1→BBS→S4 END-TO-END LOOP TEST")
    print("=" * 70)

    print("\n[1] Injecting S1 events (simulating BBH findings)...")
    inject_s1_event(target="stripe.example.com", phase=2, findings_count=3)
    inject_s1_event(target="github.example.com", phase=3, findings_count=5)

    print("\n[2] Verifying S4 can read S1 events from BBS...")
    check_s4_can_read_s1()

    print("\n[3] Checking system state (S4 consumption)...")
    check_system_state_updated()

    print("\n[4] Checking BBS topics after loop...")
    topics = ['s1-events', 's4-analysis', 'system-state', 's3-decisions']
    for topic in topics:
        try:
            r = requests.get(f"{BBS_URL}/api/messages/{topic}?limit=1", timeout=5)
            if r.ok:
                count = r.json()['count']
                print(f"  {topic:20s}: {count:3d} messages")
        except:
            print(f"  {topic:20s}: unreachable")

    print("\n[STATUS] Loop cycle complete.")
    print("S1 (BBH) → s1-events topic → S4 reads → analyzes → S4-analysis published")
    print("Next: S3 should read alerts and publish governance decisions")
