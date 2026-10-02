#!/usr/bin/env python3
"""
BBS (Bulletin Board System) API Server
LXC 106 (VLAN 20) — Central message hub for VSM coordination
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import sqlite3
import json
import hashlib
from pathlib import Path
import logging

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Database Setup
# ============================================================================

DB_PATH = Path("/var/lib/bbs/messages.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def init_db():
    """Initialize SQLite database for message persistence."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Messages table
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            topic TEXT NOT NULL,
            priority TEXT NOT NULL,
            ttl INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL DEFAULT (julianday('now')),
            expires_at REAL,
            integrity_hash TEXT
        )
    """)

    # Alerts table
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            container TEXT,
            metric TEXT,
            value REAL,
            threshold REAL,
            status TEXT NOT NULL,
            acknowledged INTEGER DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_at TEXT,
            created_at REAL DEFAULT (julianday('now'))
        )
    """)

    # Create indices
    c.execute("CREATE INDEX IF NOT EXISTS idx_topic ON messages(topic)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_expires ON messages(expires_at)")

    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# ============================================================================
# Pydantic Models
# ============================================================================

class MessagePayload(BaseModel):
    """Base message envelope."""
    timestamp: str
    source: str
    topic: str
    priority: str = "info"
    ttl: int = 3600
    payload: dict

class SystemStatePayload(BaseModel):
    """system-state topic payload."""
    node: str
    hardware: dict
    containers: dict
    alerts: list = []

class S1EventPayload(BaseModel):
    """s1-events topic payload."""
    phase: str
    target: str
    status: str
    findings_count: int
    critical_findings: list = []
    phase_duration_seconds: int
    progress_percent: int

class AlertPayload(BaseModel):
    """alerts topic payload."""
    alert_id: str
    alert_type: str
    container: str = None
    metric: str = None
    value: float = None
    threshold: float = None
    status: str
    recommendation: str = ""

# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="BBS API", version="1.0")

@app.post("/api/message")
async def publish_message(msg: MessagePayload):
    """
    Publish message to BBS.

    Topics:
    - system-state: Proxmox + LXC state (1h TTL)
    - s1-events: BBH findings (24h TTL)
    - s3-decisions: Governance (7d TTL)
    - s4-analysis: Intelligence (24h TTL)
    - s5-audit: Compliance (30d TTL)
    - alerts: Anomalies (7d TTL)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Compute integrity hash
        payload_str = json.dumps(msg.payload, sort_keys=True)
        integrity_hash = hashlib.sha256(payload_str.encode()).hexdigest()

        # Calculate expiration
        ttl_days = msg.ttl / 86400.0
        expires_at = f"julianday('now') + {ttl_days}"

        # Calculate expires_at in Python
        from datetime import datetime, timedelta
        created_at = datetime.utcnow().timestamp() / 86400.0 + 2440587.5
        expires_at = created_at + (msg.ttl / 86400.0)

        # Insert message
        c.execute("""
            INSERT INTO messages
            (timestamp, source, topic, priority, ttl, payload_json, integrity_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg.timestamp,
            msg.source,
            msg.topic,
            msg.priority,
            msg.ttl,
            payload_str,
            integrity_hash,
            created_at,
            expires_at
        ))

        conn.commit()
        msg_id = c.lastrowid
        conn.close()

        logger.info(f"Message {msg_id} published to topic={msg.topic} source={msg.source}")

        return {
            "status": "published",
            "message_id": msg_id,
            "topic": msg.topic,
            "integrity_hash": integrity_hash
        }

    except Exception as e:
        logger.error(f"Error publishing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/messages/{topic}")
async def get_messages(topic: str, limit: int = 100):
    """Retrieve latest messages for topic."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Clean expired messages first
        c.execute("DELETE FROM messages WHERE expires_at < julianday('now')")

        # Get messages
        c.execute("""
            SELECT id, timestamp, source, topic, priority, payload_json
            FROM messages
            WHERE topic = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (topic, limit))

        rows = c.fetchall()
        conn.close()

        messages = [
            {
                "id": row[0],
                "timestamp": row[1],
                "source": row[2],
                "topic": row[3],
                "priority": row[4],
                "payload": json.loads(row[5])
            }
            for row in rows
        ]

        return {
            "topic": topic,
            "count": len(messages),
            "messages": messages
        }

    except Exception as e:
        logger.error(f"Error retrieving messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/state/current")
async def get_current_state():
    """Get latest state snapshot (most recent system-state message)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            SELECT timestamp, source, payload_json
            FROM messages
            WHERE topic = 'system-state'
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        row = c.fetchone()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="No system-state message found")

        return {
            "timestamp": row[0],
            "source": row[1],
            "state": json.loads(row[2])
        }

    except Exception as e:
        logger.error(f"Error retrieving current state: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/alert/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, acknowledged_by: str = "system"):
    """Acknowledge alert."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            UPDATE alerts
            SET acknowledged = 1, acknowledged_by = ?, acknowledged_at = ?
            WHERE id = ?
        """, (acknowledged_by, datetime.utcnow().isoformat(), alert_id))

        conn.commit()
        conn.close()

        logger.info(f"Alert {alert_id} acknowledged by {acknowledged_by}")

        return {
            "status": "acknowledged",
            "alert_id": alert_id,
            "acknowledged_by": acknowledged_by
        }

    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "bbs",
        "timestamp": datetime.utcnow().isoformat()
    }

# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8600,
        log_level="info"
    )
