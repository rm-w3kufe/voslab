#!/usr/bin/env python3
"""BBS API Server — Simplified version (robust)"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import sqlite3
import json
import hashlib
from pathlib import Path
import uvicorn
import logging
import os

logger = logging.getLogger(__name__)

DB_PATH = Path("/var/lib/bbs/messages.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ============ DATABASE ============

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            source TEXT,
            topic TEXT,
            priority TEXT,
            ttl INTEGER,
            payload TEXT,
            hash TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ============ MODELS ============

class Message(BaseModel):
    timestamp: str
    source: str
    topic: str
    priority: str = "info"
    ttl: int = 3600
    payload: dict

# ============ API ============

app = FastAPI(title="BBS", version="1.0")

@app.post("/api/message")
async def publish(msg: Message):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()

        payload_str = json.dumps(msg.payload)
        msg_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:8]

        c.execute(
            "INSERT INTO messages (timestamp, source, topic, priority, ttl, payload, hash) VALUES (?,?,?,?,?,?,?)",
            (msg.timestamp, msg.source, msg.topic, msg.priority, msg.ttl, payload_str, msg_hash)
        )
        conn.commit()
        msg_id = c.lastrowid
        conn.close()

        return {"status": "ok", "id": msg_id, "hash": msg_hash}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/messages/{topic}")
async def get_messages(topic: str, limit: int = 100):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute(
            "SELECT id, timestamp, source, topic, priority, payload FROM messages WHERE topic=? ORDER BY timestamp DESC LIMIT ?",
            (topic, limit)
        )
        rows = c.fetchall()
        conn.close()

        messages = [
            {
                "id": r[0],
                "timestamp": r[1],
                "source": r[2],
                "topic": r[3],
                "priority": r[4],
                "payload": json.loads(r[5])
            }
            for r in rows
        ]
        return {"topic": topic, "count": len(messages), "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/state/current")
async def get_state():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute(
            "SELECT timestamp, source, payload FROM messages WHERE topic='system-state' ORDER BY timestamp DESC LIMIT 1"
        )
        row = c.fetchone()
        conn.close()

        if not row:
            return {"status": "no_state"}

        return {
            "timestamp": row[0],
            "source": row[1],
            "state": json.loads(row[2])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "bbs", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    # Use port 0 to find available port, then print it
    os.environ['PORT'] = '8600'
    uvicorn.run(app, host="0.0.0.0", port=8600, log_level="info")
