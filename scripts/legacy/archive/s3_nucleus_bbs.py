#!/usr/bin/env python3
"""
S3 Control (nucleus) — Reads alerts, enforces governance
Monitors BBS for system alerts, makes governance decisions
"""

import requests
import json
from datetime import datetime
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BBS_URL = "http://10.10.20.20:8600"  # LXC 106 BBS

class S3Nucleus:
    """S3 Control Layer — governance and policy enforcement"""

    def __init__(self):
        self.acknowledged_alerts = set()
        logger.info("S3 Nucleus initialized (governance mode)")

    def read_alerts(self):
        """Read alerts from BBS"""
        try:
            r = requests.get(f"{BBS_URL}/api/messages/alerts?limit=20", timeout=5)
            if r.status_code == 200:
                result = r.json()
                alerts = result.get("messages", [])
                return alerts
        except Exception as e:
            logger.warning(f"Failed to read alerts: {e}")
        return []

    def process_alert(self, alert):
        """Process individual alert and decide governance action"""
        msg_id = alert.get("id")
        payload = alert.get("payload", {})
        alert_type = payload.get("alert_type", "unknown")
        severity = payload.get("severity", "info")

        if msg_id in self.acknowledged_alerts:
            return  # Already processed

        logger.info(f"→ Alert: {alert_type} [{severity}] (msg_id={msg_id})")

        # Governance decisions based on severity
        if severity == "critical":
            self._handle_critical(payload)
        elif severity == "warning":
            self._handle_warning(payload)
        else:
            self._handle_info(payload)

        self.acknowledged_alerts.add(msg_id)

    def _handle_critical(self, alert):
        """Handle critical alerts — immediate action required"""
        action = alert.get("action", "investigate")
        reason = alert.get("reason", "")

        logger.warning(f"  [CRITICAL] {reason}")
        logger.warning(f"  Action: {action}")

        # Governance decision
        decision = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "nucleus",
            "topic": "s3-decisions",
            "priority": "critical",
            "ttl": 604800,
            "payload": {
                "decision_id": f"D-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
                "decision_type": "governance_critical",
                "alert_type": alert.get("alert_type"),
                "action": action,
                "rationale": f"Critical severity: {reason}",
                "approved_by": "nucleus",
                "timestamp_decided": datetime.utcnow().isoformat()
            }
        }

        self._publish_decision(decision)

    def _handle_warning(self, alert):
        """Handle warnings — log and monitor"""
        reason = alert.get("reason", "")
        recommendation = alert.get("recommendation", "")

        logger.info(f"  [WARNING] {reason}")
        if recommendation:
            logger.info(f"  Recommendation: {recommendation}")

        decision = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "nucleus",
            "topic": "s3-decisions",
            "priority": "warning",
            "ttl": 604800,
            "payload": {
                "decision_id": f"D-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
                "decision_type": "governance_warning",
                "alert_type": alert.get("alert_type"),
                "action": "monitor",
                "rationale": f"Warning: {reason}",
                "recommendation": recommendation,
                "approved_by": "nucleus"
            }
        }

        self._publish_decision(decision)

    def _handle_info(self, alert):
        """Handle info alerts — log only"""
        logger.info(f"  [INFO] {alert.get('reason', 'Event logged')}")

    def _publish_decision(self, decision):
        """Publish governance decision back to BBS"""
        try:
            r = requests.post(f"{BBS_URL}/api/message", json=decision, timeout=5)
            if r.status_code == 200:
                result = r.json()
                logger.info(f"  ✓ Decision published (msg_id={result.get('id')})")
                return True
        except Exception as e:
            logger.warning(f"  Failed to publish decision: {e}")
        return False

    def run_once(self):
        """Single governance cycle"""
        logger.info("=" * 60)
        logger.info("S3 GOVERNANCE CYCLE")
        logger.info("=" * 60)

        # Read all pending alerts
        alerts = self.read_alerts()

        if not alerts:
            logger.info("No alerts to process")
        else:
            logger.info(f"Processing {len(alerts)} alerts...")
            for alert in alerts:
                self.process_alert(alert)

        logger.info("Governance cycle complete\n")

    def run_continuous(self, interval=60):
        """Run governance monitoring continuously"""
        logger.info(f"Starting continuous governance mode (interval={interval}s)")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in governance cycle: {e}")
            time.sleep(interval)

if __name__ == "__main__":
    s3 = S3Nucleus()
    s3.run_continuous(interval=60)  # Every minute
