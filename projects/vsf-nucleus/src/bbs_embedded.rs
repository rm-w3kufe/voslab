/// bbs_embedded.rs — Embedded SQLite BBS client
///
/// Replaces HTTP calls to external BBS (LXC 106) with direct SQLite access.
/// Same API as bbs.rs but operates on local database.
/// Phase 4: Nucleus consolidation — eliminates LXC 106 dependency.

use rusqlite::{Connection, Result as SqlResult};
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Decision {
    pub decision_type: String,
    pub action: String,
    pub target: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemState {
    pub node: String,
    pub ram_gb: f64,
    pub containers: usize,
    pub cpu_cores: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BbsMessage {
    pub id: Option<u32>,
    pub timestamp: String,
    pub source: String,
    pub topic: String,
    pub priority: String,
    pub ttl: u32,
    pub payload: serde_json::Value,
}

pub struct BbsEmbeddedClient {
    db: Arc<Mutex<Connection>>,
    source: String,
}

impl Clone for BbsEmbeddedClient {
    fn clone(&self) -> Self {
        BbsEmbeddedClient {
            db: Arc::clone(&self.db),
            source: self.source.clone(),
        }
    }
}

impl BbsEmbeddedClient {
    /// Create or open embedded BBS database
    pub fn new(db_path: &str, source: String) -> Result<Self, Box<dyn Error>> {
        let conn = Connection::open(db_path)?;

        // Initialize schema if needed
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                topic TEXT NOT NULL,
                priority TEXT NOT NULL,
                ttl INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_topic_ts ON messages(topic, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_source_topic ON messages(source, topic);
            ",
        )?;

        Ok(BbsEmbeddedClient {
            db: Arc::new(Mutex::new(conn)),
            source,
        })
    }

    /// Read current system state from latest telemetry message
    pub fn read_system_state(&self) -> Result<SystemState, Box<dyn Error>> {
        let db = self.db.lock().unwrap();

        let mut stmt = db.prepare(
            "SELECT payload FROM messages WHERE topic = 'telemetry' ORDER BY timestamp DESC LIMIT 1"
        )?;

        let payload: String = stmt.query_row([], |row| row.get(0))
            .unwrap_or_else(|_| {
                // Default state if no telemetry yet
                serde_json::json!({
                    "node": "unknown",
                    "memory": {"total_mb": 0},
                    "cpu": {"cores": 0},
                    "disk": {"total_gb": 0}
                }).to_string()
            });

        let data: serde_json::Value = serde_json::from_str(&payload)?;

        let state = SystemState {
            node: data.get("node")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string(),
            ram_gb: data.get("memory")
                .and_then(|m| m.get("total_mb"))
                .and_then(|v| v.as_u64())
                .map(|mb| mb as f64 / 1024.0)
                .unwrap_or(0.0),
            containers: 0, // Not available in telemetry
            cpu_cores: data.get("cpu")
                .and_then(|c| c.get("cores"))
                .and_then(|v| v.as_u64())
                .map(|c| c as usize)
                .unwrap_or(0),
        };

        Ok(state)
    }

    /// Publish S4 analysis decisions
    pub fn publish_s4_analysis(
        &self,
        decisions: Vec<Decision>,
    ) -> Result<String, Box<dyn Error>> {
        let db = self.db.lock().unwrap();
        let now = chrono::Utc::now().to_rfc3339();
        let msg_id = format!("{:x}", std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos())[..12].to_string();

        let payload = serde_json::json!({
            "analysis_type": "s4_nucleus_analysis",
            "timestamp": now,
            "decisions": decisions,
            "llm_source": "Rust/Ollama",
        });

        db.execute(
            "INSERT INTO messages (timestamp, source, topic, priority, ttl, payload)
             VALUES (?, ?, ?, ?, ?, ?)",
            rusqlite::params![
                now,
                self.source,
                "s4-analysis",
                "info",
                86400i32,
                payload.to_string(),
            ],
        )?;

        Ok(msg_id)
    }

    /// Read recent alerts from telemetry
    pub fn read_alerts(&self) -> Result<Vec<serde_json::Value>, Box<dyn Error>> {
        let db = self.db.lock().unwrap();

        let mut stmt = db.prepare(
            "SELECT payload FROM messages WHERE topic = 'alerts' ORDER BY timestamp DESC LIMIT 10"
        )?;

        let alerts: Vec<serde_json::Value> = stmt.query_map([], |row| {
            let payload: String = row.get(0)?;
            Ok(serde_json::from_str(&payload).unwrap_or(serde_json::json!({})))
        })?
            .filter_map(|r| r.ok())
            .collect();

        Ok(alerts)
    }

    /// Health check: can we connect to database?
    pub fn health_check(&self) -> bool {
        match self.db.lock() {
            Ok(db) => {
                db.query_row("SELECT COUNT(*) FROM messages", [], |row| row.get::<_, i32>(0))
                    .is_ok()
            }
            Err(_) => false,
        }
    }

    /// Publish telemetry metrics (internal use by TelemetryPublisher)
    pub fn publish_telemetry(
        &self,
        payload: serde_json::Value,
    ) -> Result<String, Box<dyn Error>> {
        let db = self.db.lock().unwrap();
        let now = chrono::Utc::now().to_rfc3339();
        let msg_id = format!("{:x}", std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos())[..12].to_string();

        db.execute(
            "INSERT INTO messages (timestamp, source, topic, priority, ttl, payload)
             VALUES (?, ?, ?, ?, ?, ?)",
            rusqlite::params![
                now,
                self.source,
                "telemetry",
                "info",
                86400i32,
                payload.to_string(),
            ],
        )?;

        Ok(msg_id)
    }
}