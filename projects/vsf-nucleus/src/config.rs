/// config.rs — Nucleus operational configuration
///
/// Load from environment variables or config file
/// Controls: S4 cycle interval, Ollama endpoint, BBS endpoint, etc.

use serde::{Deserialize, Serialize};
use std::env;
use std::error::Error;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NucleusConfig {
    pub mode: String,                          // "operational" or "experimental"
    pub s4_cycle_interval_secs: u32,           // How often S4 analyzes (default 300)
    pub telemetry_interval_secs: u32,          // How often telemetry publishes (default 60)
    pub bbs_url: String,                       // BBS endpoint
    pub ollama_url: String,                    // Ollama endpoint
    pub ollama_model: String,                  // Model name (e.g. qwen2.5-coder:7b)
    pub ollama_timeout_secs: u32,              // Inference timeout (default 120)
    pub nucleus_source_id: String,             // Source identifier in BBS messages
    pub beacon_url: String,                    // VSF beacon URL (POST /api/v1/attested_check). Empty = skip.
    pub beacon_key_path: String,               // Path to Ed25519 signing key for beacon attestation.
    pub beacon_cert_path: String,              // Path to S5-CA-issued node cert JSON. Empty = derive.
    pub log_level: String,                     // "debug", "info", "warn", "error"
}

impl Default for NucleusConfig {
    fn default() -> Self {
        NucleusConfig {
            mode: "operational".to_string(),
            s4_cycle_interval_secs: 300,
            telemetry_interval_secs: 60,
            bbs_url: "http://10.10.20.20:8600".to_string(),
            ollama_url: "http://127.0.0.1:11434".to_string(),
            ollama_model: "qwen2.5-coder:7b".to_string(),
            ollama_timeout_secs: 120,
            nucleus_source_id: "vsf_nucleus".to_string(),
            beacon_url: String::new(),                    // empty = skip beaconing
            beacon_key_path: String::new(),               // empty = default path
            beacon_cert_path: String::new(),              // empty = derive from key path
            log_level: "info".to_string(),
        }
    }
}

impl NucleusConfig {
    /// Load from environment variables (override defaults)
    pub fn load_from_env() -> Self {
        let mut config = Self::default();

        if let Ok(val) = env::var("NUCLEUS_MODE") {
            config.mode = val;
        }
        if let Ok(val) = env::var("S4_CYCLE_INTERVAL") {
            config.s4_cycle_interval_secs = val.parse().unwrap_or(300);
        }
        if let Ok(val) = env::var("TELEMETRY_INTERVAL") {
            config.telemetry_interval_secs = val.parse().unwrap_or(60);
        }
        if let Ok(val) = env::var("BBS_URL") {
            config.bbs_url = val;
        }
        if let Ok(val) = env::var("OLLAMA_URL") {
            config.ollama_url = val;
        }
        if let Ok(val) = env::var("OLLAMA_MODEL") {
            config.ollama_model = val;
        }
        if let Ok(val) = env::var("OLLAMA_TIMEOUT") {
            config.ollama_timeout_secs = val.parse().unwrap_or(120);
        }
        if let Ok(val) = env::var("NUCLEUS_SOURCE_ID") {
            config.nucleus_source_id = val;
        }
        if let Ok(val) = env::var("LOG_LEVEL") {
            config.log_level = val;
        }
        if let Ok(val) = env::var("BEACON_URL") {
            config.beacon_url = val;
        }
        if let Ok(val) = env::var("BEACON_KEY_PATH") {
            config.beacon_key_path = val;
        }
        if let Ok(val) = env::var("BEACON_CERT_PATH") {
            config.beacon_cert_path = val;
        }
        config
    }

    /// Load from JSON file
    pub fn load_from_file(path: &Path) -> Result<Self, Box<dyn Error>> {
        let content = fs::read_to_string(path)?;
        let config: NucleusConfig = serde_json::from_str(&content)?;
        Ok(config)
    }

    /// Save to JSON file
    pub fn save_to_file(&self, path: &Path) -> Result<(), Box<dyn Error>> {
        let content = serde_json::to_string_pretty(self)?;
        fs::write(path, content)?;
        Ok(())
    }

    /// Validate configuration
    pub fn validate(&self) -> Result<(), String> {
        if self.s4_cycle_interval_secs == 0 {
            return Err("s4_cycle_interval_secs must be > 0".to_string());
        }
        if self.bbs_url.is_empty() {
            return Err("bbs_url cannot be empty".to_string());
        }
        if self.ollama_url.is_empty() {
            return Err("ollama_url cannot be empty".to_string());
        }
        if self.ollama_model.is_empty() {
            return Err("ollama_model cannot be empty".to_string());
        }
        Ok(())
    }

    /// Print config (debug)
    pub fn print(&self) {
        println!("=== Nucleus Configuration ===");
        println!("Mode:                {}", self.mode);
        println!("S4 cycle interval:   {}s", self.s4_cycle_interval_secs);
        println!("Telemetry interval:  {}s", self.telemetry_interval_secs);
        println!("BBS endpoint:        {}", self.bbs_url);
        println!("Ollama endpoint:     {}", self.ollama_url);
        println!("Ollama model:        {}", self.ollama_model);
        println!("Ollama timeout:      {}s", self.ollama_timeout_secs);
        println!("Nucleus source:      {}", self.nucleus_source_id);
        println!("Beacon URL:          {}", if self.beacon_url.is_empty() { "(disabled)".into() } else { self.beacon_url.clone() });
        println!("Beacon key path:     {}", if self.beacon_key_path.is_empty() { "(default)".into() } else { self.beacon_key_path.clone() });
        println!("Beacon cert path:    {}", if self.beacon_cert_path.is_empty() { "(derive)".into() } else { self.beacon_cert_path.clone() });
        println!("Log level:           {}", self.log_level);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = NucleusConfig::default();
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_config_from_env() {
        // Rust 2024: env::set_var is unsafe (requires explicit block)
        unsafe {
            env::set_var("NUCLEUS_MODE", "experimental");
        }
        let config = NucleusConfig::load_from_env();
        assert_eq!(config.mode, "experimental");
    }
}
