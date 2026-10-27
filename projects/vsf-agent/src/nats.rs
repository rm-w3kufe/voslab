//! NATS connection helper with authentication support
//!
//! Provides a simple wrapper around async-nats with VSF-specific defaults.

/// Connect to NATS server with VSF agent authentication
///
/// # Arguments
/// * `url` - NATS server URL (e.g., "nats://localhost:4222")
/// * `client_name` - Human-readable client identifier for logging
///
/// # Returns
/// * `Ok(Client)` - Connected NATS client
/// * `Err(Error)` - Connection failure
///
/// # Example
/// ```ignore
/// let client = vsf_agent::nats::connect("nats://localhost:4222", "vsf-nucleus").await?;
/// ```
pub async fn connect(url: &str, client_name: &str) -> Result<async_nats::Client, Box<dyn std::error::Error + Send + Sync>> {
    let client = async_nats::ConnectOptions::new()
        .name(client_name)
        .connect(url)
        .await?;
    
    Ok(client)
}
