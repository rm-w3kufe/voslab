#!/usr/bin/env python3
"""
get_telemetry.py — Extract live telemetry from nucleus BBS SQLite
Reads /root/bbs.db and outputs JSON suitable for dashboard HTML

Usage:
  ./get_telemetry.py [--db /root/bbs.db]

Output: JSON with nucleus state, workers status, BBS message counts
"""

import sqlite3
import json
import sys
from datetime import datetime
from pathlib import Path

def get_telemetry(db_path="/root/bbs.db"):
    """Extract telemetry from nucleus BBS SQLite."""

    if not Path(db_path).exists():
        return {
            "status": "error",
            "message": f"Database not found: {db_path}"
        }

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get latest telemetry message
        cursor.execute("""
            SELECT payload FROM messages
            WHERE topic = 'telemetry'
            ORDER BY timestamp DESC LIMIT 1
        """)
        telemetry_row = cursor.fetchone()

        # Get latest S4 decision
        cursor.execute("""
            SELECT payload, timestamp FROM messages
            WHERE topic = 's4-analysis'
            ORDER BY timestamp DESC LIMIT 1
        """)
        s4_row = cursor.fetchone()

        # Count messages by topic
        cursor.execute("""
            SELECT topic, COUNT(*) as count
            FROM messages
            GROUP BY topic
        """)
        topic_counts = {row['topic']: row['count'] for row in cursor.fetchall()}

        # Get total message count
        cursor.execute("SELECT COUNT(*) as total FROM messages")
        total_messages = cursor.fetchone()['total']

        # Parse telemetry payload
        telemetry_data = {}
        if telemetry_row:
            telemetry_data = json.loads(telemetry_row['payload'])

        # Build response
        response = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "operational",
            "nucleus": {
                "mode": "operational",
                "version": "0.0.1",
                "uptime_secs": "N/A",  # Would need to track start time
            },
            "workers": {
                "s4": {
                    "status": "running" if s4_row else "idle",
                    "cycle_interval_secs": 300,
                    "last_cycle": s4_row['timestamp'] if s4_row else None,
                    "decisions_count": topic_counts.get('s4-analysis', 0),
                },
                "telemetry": {
                    "status": "running" if telemetry_row else "idle",
                    "cycle_interval_secs": 60,
                    "last_publish": telemetry_row['timestamp'] if telemetry_row else None,
                }
            },
            "bbs": {
                "type": "embedded_sqlite",
                "db_path": db_path,
                "message_count": total_messages,
                "topics": topic_counts,
            },
            "system": telemetry_data,
        }

        conn.close()
        return response

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "type": type(e).__name__
        }

if __name__ == "__main__":
    db_path = "/root/bbs.db"
    if len(sys.argv) > 1:
        if sys.argv[1] == "--db" and len(sys.argv) > 2:
            db_path = sys.argv[2]

    data = get_telemetry(db_path)
    print(json.dumps(data, indent=2, default=str))
