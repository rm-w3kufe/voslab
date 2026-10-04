@vsm 0.3

fact("W4-NATS-AUTH-ROOT-CAUSE-FINAL") = {
  body: "async-nats v0.49.1 `connect(\"nats://token@host\")` does NOT extract the auth token from the URL. The URL is parsed only for the server address (host:port). The `ConnectOptions::default()` has `auth.token = None`. The token must be passed explicitly via `ConnectOptions::with_token()` or `.token()`. This is a design difference from nats-py (Python) and nats.go (Go), which DO extract URL auth.",
  evidence: [
    "src/lib.rs:1219: `connect<A: ToServerAddrs>(addrs: A)` → `connect_with_options(addrs, ConnectOptions::default())`",
    "src/lib.rs:148: `ConnectOptions::new()` = `ConnectOptions::default()` → `auth.token = None`",
    "src/connector.rs:633: `auth_token: self.options.auth.token.to_owned()` — always None when ConnectOptions::default()",
    "No call sites for `ServerAddr::username()` or `ServerAddr::password()` exist in the crate — they are public API only, not used internally",
    "nats-py (nats.io Python client) DOES extract `nats://token@host` → sends `auth_token` in CONNECT — see my raw socket test on LXC 104 that succeeded",
  ],
  why: "Explains why ALL Rust components (s5-covenant, s5-approval, s5-caution, and via vsf_agent: nats_publisher, phi_down, bbh, s3_star) fail auth after NATS token auth was enabled, while all Python components (s5-covenant.py, s5-ledger.py, bbs-bridge) succeed.",
  apply: [
    "Fix: `vsf_agent::nats::connect` must parse NATS_URL, extract token, and call `ConnectOptions::with_token(token)`",
    "Fix: s5_covenant.rs, s5_caution.rs, s5_approval_nats.rs must use `vsf_agent::nats::connect` instead of direct `async_nats::connect` with token support",
    "Fix: All direct `async_nats::connect(&url)` calls must be replaced with token-aware variant",
    "Workaround (for Python services): continue using token-in-URL format — nats-py handles it correctly",
    "Recommendation: add `vsf_agent::nats::connect_with_token(url, name, token)` or have `connect()` auto-extract token from URL",
  ],
  contradict: "My earlier finding that `nats://token@host` format sends `auth_token` field in CONNECT (confirmed by tcpdump). The FORMAT is correct; the problem is that async-nats v0.49.1 never transmits the token from the URL at all.",
}
