//! NATS connection helper with authentication support
//!
//! Provides a simple wrapper around async-nats with VSF-specific defaults.
//!
//! IMPORTANT: async-nats (0.49.x) does NOT extract auth credentials from the
//! URL. `nats://token@host` is parsed only for the server address; the token
//! is dropped unless passed explicitly via `ConnectOptions::token()` /
//! `user_and_password()`. See docs/findings/nats_auth_root_cause_final.md.

use async_nats::ConnectOptions;

/// Parse a NATS URL into `(server_addr, token, user_pass)`.
///
/// Supports:
/// * `nats://token@host:4222`          → token auth
/// * `nats://user:pass@host:4222`      → user/password auth
/// * `nats://host:4222`                → no auth
/// * `host:4222`                       → no auth (scheme optional)
pub fn parse_url_auth(url: &str) -> (String, Option<String>, Option<(String, String)>) {
    let rest = url.strip_prefix("nats://").unwrap_or(url);
    match rest.rfind('@') {
        Some(at) => {
            let creds = &rest[..at];
            let addr = rest[at + 1..].to_string();
            if let Some(colon) = creds.find(':') {
                let user = creds[..colon].to_string();
                let pass = creds[colon + 1..].to_string();
                if user.is_empty() {
                    (addr, None, None)
                } else {
                    (addr, None, Some((user, pass)))
                }
            } else if creds.is_empty() {
                (addr, None, None)
            } else {
                (addr, Some(creds.to_string()), None)
            }
        }
        None => (rest.to_string(), None, None),
    }
}

/// Connect to NATS server with VSF agent authentication
///
/// # Arguments
/// * `url` - NATS server URL (e.g., "nats://token@localhost:4222")
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
    let (addr, token, user_pass) = parse_url_auth(url);
    let mut opts = ConnectOptions::new().name(client_name);
    if let Some(token) = token {
        opts = opts.token(token);
    } else if let Some((user, pass)) = user_pass {
        opts = opts.user_and_password(user, pass);
    }
    let client = opts.connect(addr).await?;

    Ok(client)
}

#[cfg(test)]
mod tests {
    use super::parse_url_auth;

    #[test]
    fn token_url_is_extracted() {
        let (addr, token, up) = parse_url_auth("nats://s3cr3t@10.10.20.20:4222");
        assert_eq!(addr, "10.10.20.20:4222");
        assert_eq!(token.as_deref(), Some("s3cr3t"));
        assert!(up.is_none());
    }

    #[test]
    fn user_pass_url_is_extracted() {
        let (addr, token, up) = parse_url_auth("nats://user:pass@10.10.20.20:4222");
        assert_eq!(addr, "10.10.20.20:4222");
        assert!(token.is_none());
        assert_eq!(up, Some(("user".to_string(), "pass".to_string())));
    }

    #[test]
    fn plain_url_has_no_auth() {
        let (addr, token, up) = parse_url_auth("nats://10.10.20.20:4222");
        assert_eq!(addr, "10.10.20.20:4222");
        assert!(token.is_none());
        assert!(up.is_none());
    }

    #[test]
    fn scheme_optional() {
        let (addr, token, up) = parse_url_auth("10.10.20.20:4222");
        assert_eq!(addr, "10.10.20.20:4222");
        assert!(token.is_none());
        assert!(up.is_none());
    }
}
