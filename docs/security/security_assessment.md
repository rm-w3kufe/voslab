# VSF Security Assessment — n01 / n02

> Consolidated defensive-security review of the VSF infrastructure. First full pass: 2026-07-03
> (Claude/Fable + rmw3, S5). Scope: n01 (public bastion), n02 (Proxmox host), the LXC fleet, the
> public surface (u2738.org). Authorized defensive review of own infrastructure.

## 1. Executive summary

The perimeter is **sound by design**. n02 (the compute host, where all viable-system state lives)
has **no public IP** — it sits behind the n01 bastion on private LAN + internal VLANs, with the
Proxmox firewall restricting management ports to trusted sources. The only internet-facing host is
**n01**, whose public surface is a hardened Caddy reverse-proxy fronting a localhost-bound app.
This pass **applied** the outstanding LAN hardening and **designed** the one real functional gap
(a dormant, unauthenticated beacon) into an authenticated, monitored service.

## 2. Architecture & posture

| Plane | Detail | Verdict |
|---|---|---|
| **n02** (Proxmox host) | IPs `192.168.0.168` (LAN) + `10.10.{10,20,30}.1` (VLANs). **No public IP.** Reached only via n01's reverse SSH tunnel (`n02-hop`). PVE firewall restricts 8006/22/19999/3128 to LAN/VLAN/management sets. | 🟢 not internet-exposed |
| **n01** (public bastion, DigitalOcean `167.172.210.112`) | 443/80 (Caddy), 22 (SSH), 8080 (beacon). The perimeter. | 🟢 hardened (below) |
| **Public web** (`vsf.u2738.org`) | Caddy → `reverse_proxy localhost:8333` (vsf-bastion, localhost-bound) with HSTS(preload) / CSP / X-Frame `DENY` / nosniff / Referrer-Policy / Permissions-Policy. | 🟢 well-configured |
| **SSH** | n01: `PermitRootLogin no`. n02: `PermitRootLogin prohibit-password` (key-only, applied 2026-07-03). fail2ban active. | 🟢 |
| **Patching** | unattended-upgrades active on n01. | 🟢 |

## 3. Findings & resolutions

| # | Surface | Finding | Sev | Status |
|---|---|---|---|---|
| S-1 | n02 | `PermitRootLogin yes` (LAN-only) | 🟡 | ✅ **fixed** → `prohibit-password` (key-only) |
| S-2 | n02 | rpcbind (111) on 0.0.0.0 (LAN) — unneeded | 🟡 | ✅ **fixed** → disabled, port closed |
| S-3 | n01 | **beacon (`vsf-api` :8080)** — dormant since Apr (0 registrations ever), `POST /registry` **unauthenticated**, plain HTTP (bypasses Caddy), no systemd | 🔴 | 📐 **designed** → `beacon_activation.spec.vsm` (authenticated onboarding + Caddy TLS + systemd + continuous health probe + algedonic) |
| S-4 | n01 | CORS #469 (bbh-lab) | 🟡 | resolved by S-3 (was a `:8080` route; disappears when the beacon is bound behind Caddy) |
| S-5 | all | **monitoring blind spot**: peripherals / manual n01 processes are NOT in the S3\* liveness census → can die silently (the beacon did) | 🔴 | 📐 **designed** → `task(PERIPHERAL-HEALTH-CENSUS)` (declare + probe + algedonic per peripheral) |
| — | n01 | honeypot (`vsf.u2738.org/monitor`) | — | intentional own service — left as-is |

## 4. Standards we adhere to

- **Defense in depth** — bastion + private-IP host + host firewall + reverse-proxy + fail2ban; no single control is load-bearing.
- **Least exposure** — services bind `127.0.0.1` and are fronted by Caddy; only the reverse-proxy is public. (Gap S-3 = the one violation; being fixed.)
- **Key-only SSH** — `prohibit-password` / `no` for root; public-key auth only.
- **TLS everywhere + browser hardening** — HSTS (with `preload`), CSP `default-src 'self'`, `X-Frame-Options DENY`, `X-Content-Type-Options nosniff`, Referrer-Policy, Permissions-Policy. (OWASP Secure Headers.)
- **PKI** — an offline Ed25519 root (S5 CA) issues node certs; consumers pin the root.
- **Automatic patching** — unattended-upgrades.
- **External frames referenced** — OWASP (headers/testing), CIS-style host hardening, PTES/MITRE ATT&CK (via the BBH engagement lineage).

## 5. Our own protocols (the VSF security model)

VSF adds a *cybernetic* security layer on top of the standard controls — security as a property of a **viable** system, not just a hardened host:

- **The Covenant (A0 / A0.1)** — ethical primacy + anti-capture as **invariant constraints**. A0.1 ("no node can be forced to violate A0 through hunger or pressure") is, formally, a security property: it bounds what coercion/resource-deprivation can make the system do. Violation → `trust_score = 0`, channel revoked.
- **The S5 CA** — offline Ed25519 root (WSL + USB), pinned; issues the node certs that anchor all attestation. Fails **closed** on covenant-boot verification.
- **Witness-verify / AX-STATE** — signed state attestation; a consumer verifies rather than trusts.
- **The EVC (embedded viability certifier) + calibrate-before-trust** — a node is not trusted to participate until it presents a covenant-signed attestation that its viability instruments are **calibrated** (Axis-1) and it is covenant-compliant. **The beacon is the network-level EVC gate** (`beacon_activation.spec.vsm`).
- **The algedonic channel as a security signal** — a dead peripheral, a merkle break, a divergence → **pain** routed to S5. Security failures must *hurt*, not pass silently (finding S-5).
- **Model≡reality census (S3\*)** — declared vs running; every component (core **and** peripheral) must be declared, health-probed, and algedonic-on-failure.
- **Hard rules (R-series)** — R8 (n01 bastion / ProxyJump, root disabled), R3 (`/root` on the host off-limits), R1 (WSL is agent-only; builds on target LXCs). Enforced as canon in `state.db`.

## 6. Pending (designed, queued for DS — gated on rmw3 ratification)

1. **Beacon activation** — authenticated registration (S5-CA cert + covenant_sha + Axis-1 calibration hash → verified vs pinned root), Caddy TLS, `127.0.0.1` bind, systemd. Wire the nucleus to beacon on birth.
2. **Beacon continuous control** — declare in `state.db`; continuous end-to-end health probe; `beacon_down` algedonic; redundant channels (NATS fallback / mirror — future).
3. **PERIPHERAL-HEALTH-CENSUS** — declare + probe + algedonic for every peripheral (beacon, honeypot, caddy, vsf-bastion, any manual/n01 process).

**Verdict:** the "solid base" exists and was reinforced this pass. Remaining work is *building* the
designed items (authenticated beacon + peripheral monitoring), not fixing a broken perimeter.
