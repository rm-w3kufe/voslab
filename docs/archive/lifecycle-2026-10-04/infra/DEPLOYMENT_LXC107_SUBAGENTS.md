# Deployment Guide — LXC 107 Subagents (asc-paper, asc-rust, asc-exp)
> **STATUS: historical_record** — NUNCA DEPLOYADO/SUPERADO: LXC 107 es hoy `vsf-s3-star` (desde 2026-08-04); servicios asc-paper/asc-rust/asc-exp AUSENTES del census vivo (state-canon services, 2026-08-15). Contenido describe plan 2026-05-22 "Ready for deployment" sin evidencia de ejecución. No traducible como operación vigente.

**Status**: Ready for deployment  
**Date**: 2026-05-22  
**Hardware**: n02 Proxmox, LXC 107 (5 GB RAM, VLAN 20)

---

## 1. LXC 107 Setup Checklist

```bash
# Access LXC 107
ssh subagents

# Update system
apt update && apt upgrade -y

# Install dependencies
apt install -y python3 python3-pip python3-venv git curl

# Create Python virtual environment
python3 -m venv /opt/subagents
source /opt/subagents/bin/activate

# Install Claude SDK only (no local LLMs)
pip install anthropic pydantic python-dotenv
```

---

## 2. Subagent Services Architecture

Each subagent is a systemd service (not processes).

### Service 1: asc-paper

**Purpose**: Paper generation + reportwriting  
**Model**: Claude via API  
**RAM**: 1-2 GB pico  
**Runner**: `systemctl start asc-paper`

```bash
# /etc/systemd/system/asc-paper.service

[Unit]
Description=VSF Paper Subagent (asc-paper)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/asc-paper
Environment="PYTHONUNBUFFERED=1"
Environment="ANTHROPIC_API_KEY=sk-ant-..."
ExecStart=/opt/subagents/bin/python3 /root/asc-paper/main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Service 2: asc-rust

**Purpose**: Rust code analysis, AST parsing  
**Model**: Claude via API  
**RAM**: 1.5-2 GB pico  
**Runner**: `systemctl start asc-rust`

```bash
# /etc/systemd/system/asc-rust.service

[Unit]
Description=VSF Rust Subagent (asc-rust)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/asc-rust
Environment="PYTHONUNBUFFERED=1"
Environment="ANTHROPIC_API_KEY=sk-ant-..."
ExecStart=/opt/subagents/bin/python3 /root/asc-rust/main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Service 3: asc-exp

**Purpose**: Experiment design, hypothesis generation  
**Model**: Claude via API  
**RAM**: 800 MB - 1 GB pico  
**Runner**: `systemctl start asc-exp`

```bash
# /etc/systemd/system/asc-exp.service

[Unit]
Description=VSF Experiment Subagent (asc-exp)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/asc-exp
Environment="PYTHONUNBUFFERED=1"
Environment="ANTHROPIC_API_KEY=sk-ant-..."
ExecStart=/opt/subagents/bin/python3 /root/asc-exp/main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## 3. Deploy Subagent Services

```bash
# Copy service files
sudo cp /etc/systemd/system/asc-*.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable asc-paper asc-rust asc-exp

# Start services
sudo systemctl start asc-paper asc-rust asc-exp

# Verify status
sudo systemctl status asc-paper asc-rust asc-exp

# View logs
journalctl -u asc-paper -f
journalctl -u asc-rust -f
journalctl -u asc-exp -f
```

---

## 4. Network Configuration

LXC 107 is on VLAN 20 (services, no internet).

To allow API calls to internet (Claude API endpoint), configure NAT:

```bash
# On Proxmox host (n02):
iptables -t nat -A POSTROUTING -o vmbr0.20 -j MASQUERADE
# Save rules:
echo "iptables -t nat -A POSTROUTING -o vmbr0.20 -j MASQUERADE" >> /etc/network/if-up.d/iptables-rules
```

Or configure via Proxmox firewall for LXC 107 outbound to 443 (HTTPS).

---

## 5. Health Check

```bash
# SSH to LXC 107
ssh subagents

# Check services running
systemctl status asc-paper asc-rust asc-exp

# Test API connectivity (from LXC 107):
curl -I https://api.anthropic.com

# Monitor resource usage
free -h
ps aux | grep python3
```

---

## 6. Logs & Monitoring

```bash
# Tail all subagent logs
journalctl -u asc-paper -u asc-rust -u asc-exp -f

# Check for errors
journalctl -u asc-paper -p err

# Disk usage
df -h /root/asc-*

# Memory usage (from n02 host)
pct config 107
```

---

## 7. Troubleshooting

| Issue | Solution |
|-------|----------|
| Service fails to start | Check `journalctl -u asc-paper -n 50` for errors |
| API key missing | Set `ANTHROPIC_API_KEY` in `.env` or service ExecStart |
| Network timeout | Verify Proxmox NAT rules for VLAN 20 → internet |
| High memory usage | Check if Claude API calls are queuing; restart service |
| Disk full | Monitor `/root/asc-*` logs; rotate old logs |

---

## 8. Integration Points

### From Claude (S3/S4)

```python
import requests

# Call asc-paper service
response = requests.post(
    "http://10.10.20.30:5000/api/paper",
    json={"topic": "VSF Architecture", "outline": [...]},
    timeout=60
)
```

### From S2 BBS (LXC 106)

```python
# Escalate task to asc-paper
message = {
    "from": "bbs",
    "to": "asc-paper",
    "action": "generate_paper",
    "payload": {"title": "...", "sections": [...]}
}
# Post to LXC 107 message queue
```

---

## 9. Capacity Expectations

| Subagent | Concurrent | Peak RAM | Notes |
|-----------|-----------|----------|-------|
| asc-paper | 1 | 1.5 GB | Batch document generation |
| asc-rust | 1 | 2 GB | Large codebase analysis |
| asc-exp | 2-3 | 1 GB | Lightweight hypothesis gen |
| **Total** | **2-3** | **~3.5 GB** | < 5 GB alloc ✓ |

---

## 10. Next Steps

1. **Deploy** — Follow section 3 to start services
2. **Test** — Verify API connectivity and resource usage (section 5)
3. **Monitor** — Set up alerting on `asc-*` service failures (Netdata in LXC 104)
4. **Integrate** — Wire BBS messaging + S4 orchestrator calls to subagents
5. **Iterate** — Adjust service config based on actual peak usage

---

**Deployment Owner**: rmw3  
**Review Date**: 2026-05-22  
**Status**: Ready for implementation
